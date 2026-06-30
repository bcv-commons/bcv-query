#!/usr/bin/env python3
"""Generate per-STEM Hebrew verb glosses for a target language (Hebrew-anchored, LLM).

Brings a Strong's-bridged language (single gloss per lexeme) up to the per-stem
granularity of the BibleOL languages — anchored on the Hebrew binyan, NOT on English.
For each Hebrew verb that occurs in ≥2 stems with distinct senses, each (lemma, stem) is
glossed into the target with the LLM given: the Hebrew lemma + transliteration, the
stem's grammatical function, the English gloss, AND the already-curated witnesses
(German/Danish/Swahili) — English/others are references, the Hebrew is the anchor.

  python scripts/build_perstem_glosses_llm.py <Language>          # DRY RUN (no API): scope, cost, sample prompts
  python scripts/build_perstem_glosses_llm.py <Language> --run    # call the LLM ($), write the per-stem CSV

DRY RUN is the default and makes NO API calls. --run requires ANTHROPIC_API_KEY and
incurs token cost. Output (run): merges per-stem cells into resources/word_glosses/hbo/
<Language>.csv (existing `default` preserved). Seed: example/BibleOL/lexicons/heb_en.csv.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SEED = ROOT / "example/BibleOL/lexicons/heb_en.csv"          # per-stem ENGLISH template
WG = ROOT / "resources/word_glosses/hbo"
REF_LANGS = ["German", "Danish", "Swahili"]                  # curated per-stem witnesses
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
BATCH = 40
_PLACEHOLDER = re.compile(r"^[A-ZÆØÅ]{2,}$")

# heb_en column index → (BHSA stem code, grammatical function for the prompt)
STEMS = {5: ("qal", "basic active"), 6: ("nif", "passive/reflexive"),
         7: ("piel", "intensive/factitive"), 8: ("pual", "passive of piel"),
         9: ("hit", "reflexive/iterative"), 10: ("hif", "causative"),
         11: ("hof", "passive of causative"), 12: ("hsht", "Shaphel/causative"),
         13: ("pasq", "passive qal"), 14: ("etpa", "Etpaal"), 15: ("nit", "Nitpael"),
         16: ("hotp", "Hotpaal"), 17: ("tif", "Tifal"), 18: ("htpa", "Hitpoel"),
         19: ("poal", "Poal"), 20: ("poel", "Poel")}


def _real(v):
    v = (v or "").strip()
    return "" if (not v or v == "-" or _PLACEHOLDER.match(v)) else v


def _ref_table(language):
    """{lex: {stem: gloss}} for a curated per-stem language (its CSV)."""
    p = WG / f"{language}.csv"
    out = {}
    if not p.exists():
        return out
    with p.open(encoding="utf-8-sig", newline="") as fh:
        r = csv.reader(fh)
        cols = [c.strip() for c in next(r)]
        li = cols.index("lex")
        for row in r:
            if li < len(row) and row[li].strip():
                out[row[li].strip()] = {cols[i]: row[i].strip()
                                        for i in range(len(cols)) if i < len(row) and cols[i]}
    return out


def _worklist():
    """Entries for the multi-stem verbs only (single-stem/non-verbs already have default)."""
    refs = {L: _ref_table(L) for L in REF_LANGS}
    entries = []
    with SEED.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) < 6 or row[1] == "lex" or not row[1].strip():
                continue
            lex, translit = row[1].strip(), (row[3].strip() if len(row) > 3 else "")
            cells = {STEMS[i][0]: _real(row[i]) for i in STEMS if i < len(row) and _real(row[i])}
            if len({v for v in cells.values()}) < 2:        # not genuinely multi-stem → skip
                continue
            for stem, en in cells.items():
                fn = next(f for c, f in STEMS.values() if c == stem)
                rg = {L: refs[L].get(lex, {}).get(stem) for L in REF_LANGS}
                entries.append({"key": f"{lex}|{stem}", "lemma": lex, "translit": translit,
                                "stem": stem, "function": fn, "en": en,
                                "refs": {k: v for k, v in rg.items() if v}})
    return entries


def _prompt(batch, lang_name):
    return (
        f"You are a biblical-Hebrew lexicographer. For each entry, give the single most "
        f"natural {lang_name} gloss for the Hebrew verb IN THE GIVEN STEM (binyan). "
        f"**Anchor on the Hebrew** (lemma + transliteration) and the stem's function; the "
        f"English gloss and any other-language glosses are references, not the source — "
        f"capture the sense the STEM produces (e.g. qal 'be holy' vs hif 'declare holy'). "
        f"Return ONE LINE PER ENTRY, exactly: the key, a TAB, then the {lang_name} gloss "
        f"(a short phrase if needed). No JSON, no numbering, no commentary.\n"
        f"Entries:\n{json.dumps(batch, ensure_ascii=False)}"
    )


def main():
    run = "--run" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("usage: build_perstem_glosses_llm.py <Language> [--run]")
    language = args[0]
    entries = _worklist()
    verbs = len({e["lemma"] for e in entries})
    batches = [entries[i:i + BATCH] for i in range(0, len(entries), BATCH)]
    # rough token estimate (chars/4): prompt boilerplate + entries in, ~8 tok/entry out
    in_tok = sum(len(_prompt(b, language)) for b in batches) // 4
    out_tok = len(entries) * 8

    if not run:
        outdir = ROOT / "out" / "perstem"
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / f"{language}_prompts.txt").write_text(
            "\n\n===\n\n".join(_prompt(b, language) for b in batches), encoding="utf-8")
        print(f"DRY RUN — {language}", file=sys.stderr)
        print(f"  multi-stem verbs: {verbs}", file=sys.stderr)
        print(f"  (lemma,stem) cells to gloss: {len(entries)}", file=sys.stderr)
        print(f"  API calls (batch {BATCH}): {len(batches)}", file=sys.stderr)
        print(f"  est. tokens: ~{in_tok:,} in + ~{out_tok:,} out", file=sys.stderr)
        print(f"  est. cost @ Haiku (~$0.80/M in, $4/M out): "
              f"~${in_tok/1e6*0.8 + out_tok/1e6*4:.2f}", file=sys.stderr)
        print(f"  prompts written: {(outdir / f'{language}_prompts.txt').relative_to(ROOT)}", file=sys.stderr)
        print(f"  sample entry: {entries[0] if entries else '(none)'}", file=sys.stderr)
        print("\n  → re-run with --run to call the LLM and write the per-stem CSV.", file=sys.stderr)
        return

    # --- live run (paid) ---
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        sys.exit("ERROR: set ANTHROPIC_API_KEY (--run incurs token cost)")
    import urllib.request
    glosses = {}
    for i, b in enumerate(batches):
        body = json.dumps({"model": MODEL, "max_tokens": 4000,
                           "messages": [{"role": "user", "content": _prompt(b, language)}]}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                              "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            text = json.loads(resp.read())["content"][0]["text"]
        keys = {e["key"] for e in b}
        for line in text.splitlines():
            if "\t" in line:
                k, g = line.split("\t", 1)
                if k.strip() in keys and g.strip():
                    glosses[k.strip()] = g.strip()
        print(f"  batch {i+1}/{len(batches)}: {len(glosses)} cumulative", file=sys.stderr)

    # merge into the existing <Language>.csv (preserve default), add stem columns
    out_path = WG / f"{language}.csv"
    rows, cols = {}, ["lex", "default"]
    if out_path.exists():
        with out_path.open(encoding="utf-8-sig", newline="") as fh:
            r = csv.reader(fh); cols = [c for c in next(r) if c]; li = cols.index("lex")
            for row in r:
                if li < len(row) and row[li].strip():
                    rows[row[li].strip()] = {cols[i]: row[i] for i in range(len(cols)) if i < len(row)}
    stem_order = [c for _, (c, _f) in sorted(STEMS.items())]
    for c in stem_order:
        if c not in cols:
            cols.append(c)
    for k, g in glosses.items():
        lex, stem = k.split("|", 1)
        rows.setdefault(lex, {"lex": lex})["lex"] = lex
        rows[lex][stem] = g
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh); w.writerow(cols)
        for lex in sorted(rows):
            w.writerow([rows[lex].get(c, "") for c in cols])
    print(f"wrote {len(glosses)} per-stem cells → {out_path.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
