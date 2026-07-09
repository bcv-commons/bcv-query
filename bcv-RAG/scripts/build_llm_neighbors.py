#!/usr/bin/env python3
"""method=llm semantic-neighbor layer — the *scholarly-prior* signal for semantic_neighbors/.

The embedding pack (macula.build_semantic_neighbors) gives distributional *relatedness*; an LLM
encodes the lexical scholarship, so it supplies near-synonymy / same-concept judgment that
distributional signal structurally can't. This asks a biblical-Hebrew lexicographer model for each
lexeme's related Strong's (syn = near-synonym/same-concept, ant = antonym), anchored on the Hebrew
lemma. Output is a clean `method=llm` edge list; `macula.build_semantic_neighbors --llm-edges` then
tiers it against the empirical pack (agreement → high-confidence; antonyms → demote emb false-positives).

PROVENANCE + CAUTION: `source=llm`. The model's knowledge derives from the same scholarship (incl. the
NC MARBLE data), so this is a clean-*output* reconstruction, not a from-scratch derivation. It is a
PRIOR (assertion), not attestation — always grounded against the empirical layer before it's trusted.
Keep it INDEPENDENT of any LLM gold used to evaluate (don't grade the LLM with the LLM).

Requires ANTHROPIC_API_KEY (bcv-RAG/.env). Model via ANTHROPIC_MODEL. Resumable. --dry-run prints the
first prompt and exits (no spend).
  python3 scripts/build_llm_neighbors.py            # all Hebrew content lexemes
  python3 scripts/build_llm_neighbors.py --limit 40 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent          # bcv-RAG/
ROOT = HERE.parent                                     # repo root
SPINE = ROOT / "shoresh" / "macula" / "lexeme-spine.db"
OUT = ROOT / "resources" / "semantic_neighbors" / "llm_edges.tsv"

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
BATCH = int(os.environ.get("LLM_NEIGH_BATCH", "25"))
MAX_NB = 8

_STRONG = re.compile(r"[GH]?(\d{1,5})[a-zA-Z]?")


def _load_dotenv() -> None:
    env = HERE / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_lexemes() -> list[dict]:
    """One entry per Hebrew content Strong's (the LLM's natural granularity): {strong, lemma, hint}.
    Rolls the homograph-precise lexemes up to Strong's; a representative lemma/gloss per code."""
    db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    seen: dict[str, dict] = {}
    for strong, lemma, gloss in db.execute(
            "SELECT strong, lemma, gloss FROM spine_words "
            "WHERE is_content=1 AND strong IS NOT NULL AND lexeme LIKE 'hbo:%' "
            "ORDER BY book, chapter, verse, idx"):
        code = f"H{int(strong):04d}"
        if code not in seen:
            seen[code] = {"strong": code, "lemma": lemma or "", "hint": (gloss or "").replace(".", " ")}
    return list(seen.values())


PROMPT = (
    "You are a lexicographer of Biblical Hebrew. For each TARGET below (Strong's code + Hebrew lemma "
    "+ an English hint), list other Hebrew Strong's numbers that are SEMANTICALLY related IN BIBLICAL "
    "HEBREW USAGE:\n"
    "  syn = near-synonym or same-concept word (e.g. words for 'fear', for covenant-loyalty, for "
    "'ruler')\n"
    "  ant = clear antonym / opposite\n"
    "Anchor on the Hebrew lemma and its primary biblical meaning; the English hint is only a hint. "
    f"At most {MAX_NB} related codes per target, most-related first, Hebrew (H####) only. If you know "
    "nothing reliable for a target, OMIT it — do NOT guess or pad.\n"
    "Return ONE relation PER LINE, exactly:  <target H####><TAB><syn|ant><TAB><neighbor H####>\n"
    "No JSON, no numbering, no commentary.\nEntries:\n"
)


def call_llm(entries: list[dict]) -> list[tuple[str, str, str]]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        sys.exit("ERROR: set ANTHROPIC_API_KEY (bcv-RAG/.env)")
    body = json.dumps({"model": MODEL, "max_tokens": 4000,
                       "messages": [{"role": "user",
                                     "content": PROMPT + json.dumps(entries, ensure_ascii=False)}]}).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        text = json.loads(resp.read())["content"][0]["text"]
    return parse(text, {e["strong"] for e in entries})


def parse(text: str, targets: set[str]) -> list[tuple[str, str, str]]:
    """Robust line parse → (target, relation, neighbor). Only accept asked-for targets + valid codes."""
    out = []
    for line in text.splitlines():
        parts = re.split(r"[\t|;,]", line.strip())
        if len(parts) < 3:
            continue
        tm, rel, nm = _STRONG.search(parts[0]), parts[1].strip().lower(), _STRONG.search(parts[2])
        if not tm or not nm or rel not in ("syn", "ant"):
            continue
        t, n = f"H{int(tm.group(1)):04d}", f"H{int(nm.group(1)):04d}"
        if t in targets and t != n:
            out.append((t, rel, n))
    return out


def main() -> None:
    _load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="cap #lexemes (0 = all)")
    ap.add_argument("--dry-run", action="store_true", help="print the first prompt and exit (no spend)")
    a = ap.parse_args()

    entries = load_lexemes()
    if a.limit:
        entries = entries[:a.limit]
    done = set()
    if OUT.exists():                                   # resumable: skip targets already emitted
        done = {ln.split("\t")[0] for ln in OUT.read_text(encoding="utf-8").splitlines()
                if ln and not ln.startswith("#")}
    todo = [e for e in entries if e["strong"] not in done]
    print(f"[llm-neighbors] {len(todo)}/{len(entries)} lexemes to do ({len(done)} cached)", file=sys.stderr)

    if a.dry_run:
        print(PROMPT + json.dumps(todo[:BATCH], ensure_ascii=False, indent=1))
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    if not OUT.exists():
        OUT.write_text("# source=llm; semantic neighbors (syn|ant) anchored on the Hebrew lemma\n"
                       "target\trelation\tneighbor\n", encoding="utf-8")
    with OUT.open("a", encoding="utf-8") as fh:
        for i in range(0, len(todo), BATCH):
            edges = call_llm(todo[i:i + BATCH])
            for t, rel, n in edges:
                fh.write(f"{t}\t{rel}\t{n}\n")
            fh.flush()
            print(f"[llm-neighbors] {i+BATCH}/{len(todo)} · +{len(edges)} edges", file=sys.stderr)


if __name__ == "__main__":
    main()
