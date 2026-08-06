#!/usr/bin/env python3
"""LLM pairwise verification for single-signal-family candidate pairs — Lever #2 of the publication-
confidence plan (domain-replacement-roadmap.md). Cross-signal agreement (build_confidence_tiers.py)
already promotes pairs with >=2 independent signal families to 73.4% SDBH agreement; this targets the
~33,500-pair middle tier (exactly 1 family — some real signal, not yet cross-checked) and asks an LLM
to judge each one directly, so real pairs the corroboration net missed aren't left stranded at low
trust just because they only ever got one kind of evidence.

Deliberately NOT run over the >=2-family tier (already trusted, would waste spend) or the zero-family
noise floor (not worth judging). Batches N pairs per call for cost efficiency — same pattern as
label_domain_clusters.py / build_llm_neighbors.py (both in bcv-RAG/scripts/, since that's historically
where ANTHROPIC_API_KEY lived; this script moved to shoresh/macula/ in 2026-08 once shoresh got its own
.env — it's shoresh's own pipeline, not bcv-RAG's, and had only been living there for credential
convenience).

Requires ANTHROPIC_API_KEY (shoresh/.env). Resumable (skips pairs already in the output file).
  python -m macula.verify_pairs_llm --limit 50 --dry-run     # see cost/prompt shape, no spend
  python -m macula.verify_pairs_llm --limit 300              # small real batch, check cost
  python -m macula.verify_pairs_llm                          # full run
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent           # shoresh/macula/
ROOT = HERE.parents[1]                            # repo root
TIERS = ROOT / "resources" / "semantic_neighbors" / "confidence_tiers.tsv"
GLOSS_TSV = ROOT / "resources" / "strongs_gloss.tsv"
OUT = ROOT / "resources" / "semantic_neighbors" / "llm_pair_verification.tsv"

# --candidates/--out (below) let this run against any strong_a/strong_b-shaped TSV, not just the
# confidence-tier single-signal-family candidates — e.g. resources/sefer_hashorashim/candidate_pairs.tsv.
# Default behavior (no flags) is unchanged: confidence_tiers.tsv -> llm_pair_verification.tsv.

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
PAIRS_PER_CALL = 25


def _load_dotenv() -> None:
    env = HERE.parent / ".env"                   # shoresh/.env
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            if not os.environ.get(k):
                os.environ[k] = v.strip().strip('"').strip("'")


def load_candidates(path: Path = TIERS, require_single_family: bool = True) -> list[tuple[str, str]]:
    """[(strong_a, strong_b)]. Against the default confidence_tiers.tsv, filters to exactly
    n_families == 1 (the target tier for that source — see module docstring). Against any other
    --candidates file (e.g. sefer_hashorashim/candidate_pairs.tsv), takes every row as-is — those
    files are already scoped to "needs verification" by their own builder."""
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("strong_a\t"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < 2:
                continue
            if require_single_family and path == TIERS:
                if len(p) >= 3 and p[2] == "1":
                    out.append((p[0], p[1]))
            else:
                out.append((p[0], p[1]))
    return out


def load_glosses() -> dict[str, str]:
    gl: dict[str, str] = {}
    if not GLOSS_TSV.exists():
        return gl
    with GLOSS_TSV.open(encoding="utf-8") as fh:
        header = next(fh).rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) > idx.get("lang", -1) and p[idx["lang"]] == "eng":
                gl.setdefault(p[idx["strong"]], p[idx["gloss"]])
    return gl


PROMPT = (
    "You are a Biblical Hebrew lexicographer. For each PAIR below (two Strong's numbers + their English "
    "glosses), judge whether the two words are genuinely synonyms or belong to the same tight semantic "
    "concept in Biblical Hebrew usage — not just loosely related or co-occurring. Be strict: many "
    "candidate pairs will be wrong (that's why they're being checked).\n"
    "Return ONE verdict PER LINE, exactly:  <pair_id><TAB><yes|no|unsure>\n"
    "No JSON, no commentary, no extra text.\nPairs:\n"
)


def call_llm(batch: list[dict], tries: int = 5):
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        sys.exit("ERROR: set ANTHROPIC_API_KEY (shoresh/.env)")
    body = json.dumps({"model": MODEL, "max_tokens": 1500,
                       "messages": [{"role": "user",
                                     "content": PROMPT + json.dumps(batch, ensure_ascii=False)}]}).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            u = data.get("usage", {})
            itok, otok = u.get("input_tokens", 0), u.get("output_tokens", 0)
            text = next((b["text"] for b in data.get("content", []) if b.get("type") == "text"), None)
            if text:
                return parse(text, {p["pair_id"] for p in batch}), itok, otok
            print(f"[verify-pairs] warn: no text block (try {attempt+1})", file=sys.stderr)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")[:400]
            except Exception:
                detail = str(e)
            print(f"[verify-pairs] HTTP {e.code} (try {attempt+1}): {detail}", file=sys.stderr)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            # network-level failure (connection reset, DNS hiccup, timeout, ...) — NOT an HTTPError,
            # a plain retry-on-HTTPError-only loop lets these crash the whole run (seen 2026-08: a
            # single "Connection reset by peer" ~20 minutes into a full pass killed the process and
            # lost everything, since output used to be written once at the end — see main()'s
            # incremental-flush fix for the other half of this bug).
            wait = min(2 ** attempt, 30)
            print(f"[verify-pairs] network error (try {attempt+1}): {e} — retrying in {wait}s",
                  file=sys.stderr)
            import time
            time.sleep(wait)
    return {}, 0, 0


def parse(text: str, wanted: set[str]) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        parts = re.split(r"\t", line.strip(), maxsplit=1)
        if len(parts) != 2:
            continue
        pid, verdict = parts[0].strip(), parts[1].strip().lower()
        if pid in wanted and verdict in ("yes", "no", "unsure"):
            out[pid] = verdict
    return out


_PRICES = {"haiku": (1.0, 5.0), "sonnet": (3.0, 15.0), "opus": (15.0, 75.0)}


def _cost(itok: int, otok: int) -> float:
    rin, rout = next((v for k, v in _PRICES.items() if k in MODEL), (3.0, 15.0))
    return itok / 1e6 * rin + otok / 1e6 * rout


def _already_done(out_path: Path = OUT) -> set[str]:
    done = set()
    if out_path.exists():
        with out_path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("#") or line.startswith("strong_a\t"):
                    continue
                p = line.rstrip("\n").split("\t")
                if len(p) >= 3:
                    done.add(f"{p[0]}|{p[1]}")
    return done


def main() -> int:
    _load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0, help="cap #pairs (0 = all)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--candidates", type=Path, default=TIERS,
                    help="strong_a/strong_b-shaped TSV to verify (default: confidence_tiers.tsv, "
                         "filtered to n_families==1)")
    ap.add_argument("--out", type=Path, default=OUT, help="output path (default: llm_pair_verification.tsv)")
    args = ap.parse_args()

    candidates = load_candidates(args.candidates)
    done = _already_done(args.out)
    candidates = [(a, b) for a, b in candidates if f"{a}|{b}" not in done]
    if args.limit:
        candidates = candidates[:args.limit]
    glosses = load_glosses()

    entries = []
    for i, (a, b) in enumerate(candidates):
        pid = f"{a}-{b}"
        entries.append({"pair_id": pid, "a": f"{a} {glosses.get(a, '')}", "b": f"{b} {glosses.get(b, '')}"})

    if args.dry_run:
        print(f"[verify-pairs] {len(entries)} pairs pending (of which this dry-run shows "
              f"{min(PAIRS_PER_CALL, len(entries))})", file=sys.stderr)
        print(PROMPT + json.dumps(entries[:PAIRS_PER_CALL], ensure_ascii=False, indent=1))
        return 0

    print(f"[verify-pairs] {len(entries)} pairs to verify, model={MODEL}", file=sys.stderr)
    results: dict[str, str] = {}
    tot_in = tot_out = 0
    id2pair = {f"{a}-{b}": (a, b) for a, b in candidates}

    # Write incrementally (flush after every batch), not once at the end — FIXED 2026-08: a full run
    # crashed ~20 minutes in on a network error and lost everything, since output used to be
    # accumulated in memory and written only after the whole loop finished. Now each batch's verdicts
    # land on disk immediately, so a crash only costs the in-flight batch, not the whole run — and
    # --limit/resume (_already_done) means simply re-running picks up where it left off.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    is_new_file = not args.out.exists()
    fh = args.out.open("a", encoding="utf-8")
    if is_new_file:
        fh.write(f"# LLM pairwise verification ({MODEL}) of {args.candidates.name}. verdict: "
                 f"yes/no/unsure. See verify_pairs_llm.py.\n")
        fh.write("strong_a\tstrong_b\tverdict\n")
        fh.flush()

    try:
        for i in range(0, len(entries), PAIRS_PER_CALL):
            batch = entries[i:i + PAIRS_PER_CALL]
            got, itok, otok = call_llm(batch)
            results.update(got)
            tot_in += itok; tot_out += otok
            for pid, verdict in got.items():
                a, b = id2pair[pid]
                fh.write(f"{a}\t{b}\t{verdict}\n")
            fh.flush()
            print(f"[verify-pairs] {i + len(batch)}/{len(entries)} · +{len(got)} verdicts · "
                  f"running ${_cost(tot_in, tot_out):.3f}", file=sys.stderr)
    finally:
        fh.close()

    tally = collections.Counter(results.values())
    print(f"[verify-pairs] DONE · {len(results)}/{len(entries)} verified "
          f"(yes={tally['yes']} no={tally['no']} unsure={tally['unsure']}) · "
          f"est cost ${_cost(tot_in, tot_out):.3f} ({MODEL}) -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
