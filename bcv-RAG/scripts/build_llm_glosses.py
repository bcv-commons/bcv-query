#!/usr/bin/env python3
"""Tier-1: LLM-translate Strong's glosses into a target language, **anchored on
the original-language word** (NOT pivoted through English), filling the gaps
where the authoritative (UBS) gloss is missing or a multi-word paraphrase.

Anchoring principle: each entry is translated from the **Hebrew/Greek lemma**
(+ transliteration + Strong's code); the English gloss is only a *hint*. This
avoids translation-of-a-translation. Output is a per-language file (scales to
hundreds of languages by adding files, not columns — see plan-spanish-ingestion
A1 and build-and-artifacts.md).

Gap = codes that have a gloss but NO single-word gloss in the target language
(catches absent + paraphrase-only, e.g. G5485 es "mostrar bondad" → "gracia").

Provenance: everything here is `source=llm`. The runtime UNIONs these with the
UBS glosses (more query words → a concept); never overwrites the authoritative.
Resumable: re-running fills only codes not already in the output.

Requires ANTHROPIC_API_KEY. Model via ANTHROPIC_MODEL (default Haiku 4.5).
Usage: python3 scripts/build_llm_glosses.py es
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
GLOSS = HERE.parent / "resources" / "strongs_gloss.tsv"
LEMMA = HERE / "strong_lemma.tsv"
FORMS = HERE / "forms.tsv"
OUT_DIR = HERE.parent / "resources" / "llm_strongs_glosses"
SPINE_DB = HERE.parent / "shoresh" / "spine" / "spine.db"

N_EXAMPLES = int(os.environ.get("LLM_GLOSS_EXAMPLES", "2"))  # sample verses per code

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
BATCH = int(os.environ.get("LLM_GLOSS_BATCH", "40"))

# keyed by canonical tag (ISO 639-3 / BCP 47)
LANG_NAMES = {"spa": "Spanish", "fra": "French", "por": "Portuguese",
              "cmn-Hans": "Simplified Chinese", "cmn-Hant": "Traditional Chinese",
              "deu": "German", "ita": "Italian", "ind": "Indonesian",
              "rus": "Russian", "arb": "Arabic", "hin": "Hindi",
              "ben": "Bengali", "asm": "Assamese", "hau": "Hausa"}
# accept legacy 2-letter on the CLI
_LEGACY = {"es": "spa", "fr": "fra", "pt": "por", "zh": "cmn-Hans",
           "zh-Hant": "cmn-Hant", "de": "deu", "it": "ita", "ru": "rus",
           "ar": "arb", "hi": "hin", "bn": "ben", "as": "asm", "ha": "hau"}


def _load_dotenv() -> None:
    """Load bcv-RAG/.env into os.environ (keys not already set). No dependency."""
    env = HERE / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _single(g: str) -> bool:
    return bool(g) and len(re.findall(r"\S+", g)) == 1


def _load():
    """Per code: en gloss, translit, target gloss, and original lemma."""
    en, translit, tgt = {}, {}, {}
    with GLOSS.open(encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 4:
                if p[3] == "eng":
                    en[p[0]] = p[1]
                    translit[p[0]] = p[2] if len(p) > 2 else ""
                elif p[3] == LANG:
                    tgt[p[0]] = p[1]
    lemma = {}
    if LEMMA.exists():
        with LEMMA.open(encoding="utf-8") as fh:
            next(fh)
            for line in fh:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 3 and p[2]:
                    lemma[p[0]] = p[2]
    return en, translit, tgt, lemma


def _load_forms() -> dict[str, list[str]]:
    """{code: [sample refs]} ordered by surface-form frequency (typical usage first)."""
    out: dict[str, list[tuple[int, str]]] = {}
    if not FORMS.exists():
        return {}
    with FORMS.open(encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            p = line.rstrip("\n").split("\t")  # strong, lemma, surface, count, ref
            if len(p) >= 5:
                try:
                    out.setdefault(p[0], []).append((int(p[3]), p[4]))
                except ValueError:
                    continue
    return {c: [r for _, r in sorted(v, key=lambda x: -x[0])] for c, v in out.items()}


def _verse_text(con, ref: str) -> str:
    """Original-language text of a 'BOOK ch:vs' reference (surfaces joined)."""
    m = re.match(r"^(\S+)\s+(\d+):(\d+)$", ref)
    if not m:
        return ""
    rows = con.execute(
        "SELECT surface FROM spine_words WHERE book=? AND chapter=? AND verse=? "
        "ORDER BY idx", (m.group(1), int(m.group(2)), int(m.group(3)))).fetchall()
    return " ".join(r[0] for r in rows if r[0])


def _translate_batch(entries: list[dict], lang_name: str) -> dict[str, str]:
    """entries: [{strong, lemma, translit, hint}] → {strong: target_word}.
    Anchored on the original lemma; English is only a hint."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("ERROR: set ANTHROPIC_API_KEY", file=sys.stderr)
        sys.exit(1)
    prompt = (
        f"You are a biblical-languages lexicographer. For each entry, give the "
        f"single most natural {lang_name} word for the biblical meaning of the "
        f"ORIGINAL-language word (Hebrew or Greek). **Anchor on the original "
        f"word** (lemma + transliteration + Strong's); the English gloss is only "
        f"a hint. Each entry may include example occurrences (original text, most "
        f"frequent usage first) — use them to infer the word's PRIMARY biblical "
        f"sense; do NOT translate a specific verse. One {lang_name} word (closest "
        f"common single word if none).\n"
        f"Return ONE LINE PER ENTRY, exactly: the Strong's code, then a TAB, then "
        f"the single {lang_name} word. Nothing else — no JSON, no numbering, no commentary.\n"
        f"Entries:\n{json.dumps(entries, ensure_ascii=False)}"
    )
    body = json.dumps({
        "model": MODEL, "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    text = data["content"][0]["text"]
    # Line-based parse (no JSON to break): each line = "<code><sep><word>".
    # Tolerate tabs/colons/bullets/quotes; only accept codes we asked for.
    codes = {e["strong"] for e in entries}
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^[\s\"'\-*•]*([GH]\d{1,5}[a-zA-Z]?)\b[\s:.\t)\"'–-]*(.+)$", line)
        if not m:
            continue
        code, word = m.group(1), m.group(2).strip().strip("\"'")
        if code in codes and word:
            out[code] = word
    return out


def main() -> None:
    global LANG
    _load_dotenv()
    LANG = sys.argv[1] if len(sys.argv) > 1 else "spa"
    LANG = _LEGACY.get(LANG, LANG)              # accept legacy 2-letter
    lang_name = LANG_NAMES.get(LANG, LANG)
    OUT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / f"{LANG}.tsv"

    en, translit, tgt, lemma = _load()
    forms = _load_forms()
    con = sqlite3.connect(SPINE_DB) if SPINE_DB.exists() else None
    tgt_single = {c for c, g in tgt.items() if _single(g)}
    done = set()
    if out_path.exists():
        with out_path.open(encoding="utf-8") as fh:
            for ln in fh:
                if ln and not ln.startswith(("#", "strong\t")):
                    done.add(ln.split("\t", 1)[0])

    gap = [c for c in en if c not in tgt_single and c not in done]
    print(f"{LANG} ({lang_name}): {len(gap)} codes to fill "
          f"(original-language anchored; {len(done)} already done)", file=sys.stderr)
    if not gap:
        return

    new = not out_path.exists()
    with out_path.open("a", encoding="utf-8") as fh:
        if new:
            fh.write("# source=llm; anchored on the original lemma (Hebrew/Greek), "
                     "English gloss used only as a hint\n")
            fh.write("strong\tlemma_ref\ten_ref\tgloss\n")
        written = 0
        for i in range(0, len(gap), BATCH):
            chunk = gap[i:i + BATCH]
            entries = []
            for c in chunk:
                e = {"strong": c, "lemma": lemma.get(c, ""),
                     "translit": translit.get(c, ""), "hint": en.get(c, "")}
                if con is not None:  # frequency-ranked usage context
                    ex = []
                    for ref in forms.get(c, [])[:N_EXAMPLES]:
                        txt = _verse_text(con, ref)
                        if txt:
                            ex.append({"ref": ref, "text": txt})
                    if ex:
                        e["examples"] = ex
                entries.append(e)
            out: dict[str, str] = {}
            for attempt in range(3):
                try:
                    out = _translate_batch(entries, lang_name)
                    break
                except Exception as e:
                    print(f"  batch {i//BATCH} attempt {attempt+1}: {e}", file=sys.stderr)
                    time.sleep(2 * (attempt + 1))
            for c in chunk:
                g = (out.get(c) or "").strip()
                if g:
                    fh.write(f"{c}\t{lemma.get(c,'')}\t{en.get(c,'')}\t{g}\n")
                    written += 1
            fh.flush()
            print(f"  {min(i+BATCH, len(gap))}/{len(gap)} codes", file=sys.stderr)
    print(f"Wrote {written} {LANG} glosses to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
