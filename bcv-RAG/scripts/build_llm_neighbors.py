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
import time
import urllib.error
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
            k = k.strip()
            # plain setdefault() treats an EMPTY existing value as "already set" and refuses to
            # override it — some harnesses pre-declare ANTHROPIC_API_KEY="" in the shell env for
            # safety, which would otherwise silently defeat .env entirely.
            if not os.environ.get(k):
                os.environ[k] = v.strip().strip('"').strip("'")


STEP_SPINE = ROOT / "shoresh" / "spine" / "spine.db"   # STEPBible morph → proper-noun flag
PACK = ROOT / "resources" / "semantic_neighbors" / "neighbors.parquet"


def _pack_strongs():
    """H#### strongs that are actually in the embedding pack (>=3 clauses). LLM edges for lexemes
    outside the pack can't map to a neighbor, so querying them is wasted spend — restrict to these."""
    if not PACK.exists():
        return None
    import re as _re
    import pyarrow.parquet as pq
    lex = set(pq.read_table(PACK, columns=["lexeme"]).column("lexeme").to_pylist())
    return {f"H{int(_re.search(r'(\d+)', l).group(1)):04d}" for l in lex if _re.search(r'\d', l)}


def _proper_strongs() -> set:
    """H#### proper nouns (STEPBible morph `Np` dominant) — don't waste LLM calls on names; the model
    chains genealogy/nation lists as bogus synonyms. Must match build_semantic_neighbors' exclusion."""
    if not STEP_SPINE.exists():
        return set()
    import collections
    db = sqlite3.connect(f"file:{STEP_SPINE}?mode=ro", uri=True)
    tot, prop = collections.Counter(), collections.Counter()
    for strong, morph in db.execute("SELECT strong, morph FROM spine_words WHERE strong IS NOT NULL"):
        s = f"H{int(strong):04d}"; tot[s] += 1
        if morph and "Np" in morph:
            prop[s] += 1
    return {s for s in tot if prop[s] > 0.5 * tot[s]}


def load_lexemes() -> list[dict]:
    """One entry per Hebrew content Strong's (the LLM's natural granularity): {strong, lemma, hint}.
    Rolls the homograph-precise lexemes up to Strong's; proper nouns excluded (names aren't neighbors)."""
    proper = _proper_strongs()
    pack = _pack_strongs()          # restrict to lexemes in the embedding pack (else the edge is useless)
    db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    seen: dict[str, dict] = {}
    for strong, lemma, gloss in db.execute(
            "SELECT strong, lemma, gloss FROM spine_words "
            "WHERE is_content=1 AND strong IS NOT NULL AND lexeme LIKE 'hbo:%' "
            "ORDER BY book, chapter, verse, idx"):
        code = f"H{int(strong):04d}"
        if code in seen or code in proper or (pack is not None and code not in pack):
            continue
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


def call_llm(entries: list[dict], tries: int = 3):
    """-> (edges, input_tokens, output_tokens). Output tokens include thinking (billed at out rate)."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        sys.exit("ERROR: set ANTHROPIC_API_KEY (bcv-RAG/.env)")
    body = json.dumps({"model": MODEL, "max_tokens": 8000,   # room for thinking + the edge list
                       "messages": [{"role": "user",
                                     "content": PROMPT + json.dumps(entries, ensure_ascii=False)}]}).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read())
            u = data.get("usage", {})
            itok, otok = u.get("input_tokens", 0), u.get("output_tokens", 0)
            # content may lead with a non-text block (e.g. thinking) — take the first TEXT block.
            text = next((b["text"] for b in data.get("content", []) if b.get("type") == "text"), None)
            if text:
                return parse(text, {e["strong"] for e in entries}), itok, otok
            print(f"[llm-neighbors] warn: no text block (try {attempt+1})", file=sys.stderr)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")[:400]
            except Exception:
                detail = "(no body)"
            if e.code in (429, 500, 502, 503, 529) and attempt < tries - 1:
                time.sleep(4 * (attempt + 1)); continue
            print(f"[llm-neighbors] HTTP {e.code}: {detail} — skipping batch", file=sys.stderr)
            break
        except Exception as e:  # noqa: BLE001 — one bad batch must not kill a 100+ call run
            print(f"[llm-neighbors] {type(e).__name__}: {e} — skipping batch", file=sys.stderr)
        time.sleep(2)
    return [], 0, 0   # skip: these targets stay 'not done' → the resumable re-run retries them


# rough per-1M-token prices (input, output) — for a running cost estimate in the log only
_PRICES = {"haiku": (1.0, 5.0), "sonnet": (3.0, 15.0), "opus": (15.0, 75.0)}


def _cost(itok: int, otok: int) -> float:
    rin, rout = next((v for k, v in _PRICES.items() if k in MODEL), (3.0, 15.0))
    return itok / 1e6 * rin + otok / 1e6 * rout


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
    ap.add_argument("--only", type=Path, help="restrict to target Strong's listed in this file (one H#### per line)")
    ap.add_argument("--redo", action="store_true", help="with --only: drop those targets' existing edges and re-query (upgrade with a better model)")
    ap.add_argument("--dry-run", action="store_true", help="print the first prompt and exit (no spend)")
    ap.add_argument("--out", type=Path, help="write edges here instead of the default (for A/B scratch runs)")
    a = ap.parse_args()
    global OUT
    if a.out:
        OUT = a.out

    entries = load_lexemes()
    if a.only:                                         # cascade: restrict to a chosen subset
        keep = {ln.strip() for ln in a.only.read_text(encoding="utf-8").splitlines() if ln.strip()}
        entries = [e for e in entries if e["strong"] in keep]
        if a.redo and OUT.exists():                    # re-query these on the current (e.g. Opus) model:
            kept = [ln for ln in OUT.read_text(encoding="utf-8").splitlines()   # drop their old edges first
                    if ln.startswith("#") or ln.split("\t")[0] not in keep]
            OUT.write_text("\n".join(kept) + "\n", encoding="utf-8")
    if a.limit:
        entries = entries[:a.limit]
    done = set()
    if OUT.exists():                                   # resumable: skip targets already emitted
        done = {ln.split("\t")[0] for ln in OUT.read_text(encoding="utf-8").splitlines()
                if ln and not ln.startswith("#")}
    todo = [e for e in entries if e["strong"] not in done]
    print(f"[llm-neighbors] model={MODEL}  {len(todo)}/{len(entries)} lexemes to do "
          f"({len(done)} cached)", file=sys.stderr)

    if a.dry_run:
        print(PROMPT + json.dumps(todo[:BATCH], ensure_ascii=False, indent=1))
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    if not OUT.exists():
        OUT.write_text("# source=llm; semantic neighbors (syn|ant) anchored on the Hebrew lemma\n"
                       "target\trelation\tneighbor\tmodel\n", encoding="utf-8")
    tot_in = tot_out = 0
    with OUT.open("a", encoding="utf-8") as fh:
        for i in range(0, len(todo), BATCH):
            edges, itok, otok = call_llm(todo[i:i + BATCH])
            for t, rel, n in edges:
                fh.write(f"{t}\t{rel}\t{n}\t{MODEL}\n")     # per-edge model provenance
            fh.flush()
            tot_in += itok; tot_out += otok
            print(f"[llm-neighbors] {i+BATCH}/{len(todo)} · +{len(edges)} edges · "
                  f"tok in={itok} out={otok} · running ${_cost(tot_in, tot_out):.2f} "
                  f"(Σ in={tot_in} out={tot_out})", file=sys.stderr)
    print(f"[llm-neighbors] DONE · total tokens in={tot_in} out={tot_out} · "
          f"est cost ${_cost(tot_in, tot_out):.2f} ({MODEL})", file=sys.stderr)


if __name__ == "__main__":
    main()
