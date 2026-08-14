#!/usr/bin/env python3
"""LLM direction adjudication for hierarchy_dag.tsv's dropped-edge pool (Phase C step 3 follow-up,
internal-docs/phase-c-instrument-calibration-plan.md) -- the "deferred Haiku adjudication pass" noted
throughout that doc, picked back up because the pool turned out small (581 pairs, ~24 batched calls,
negligible cost) rather than something that needed its own planning cycle.

DictaLM was calibrated for this exact task and failed it (chance-level accuracy in all 4 conditions
tested, see the plan doc's Phase C step 2) -- Haiku is the fallback that was always the plan's
intended answer for direction adjudication, not a new idea. Reuses verify_pairs_llm.py's proven
infra directly (dotenv loading, incremental-flush + resumable writes, retry/backoff on network
errors, cost tracking) rather than re-deriving it -- only the prompt/parse/candidate-loading differ
from that script's synonymy task.

Candidates: build_hierarchy_dag.py's dropped_edges.tsv (edges enforce_acyclic() couldn't place in a
consistent generality order -- reversed, tied, or missing a profile-size score on one side). The
column order there (broader_strong, narrower_strong) is the direction apposition/distributional
ORIGINALLY proposed, not a verified fact -- exactly what's being adjudicated. Side (a vs b) is
randomized per pair before prompting so Haiku can't pick up a positional shortcut (same discipline
used in calibrate_dictalm.py's direction task, where an earlier, unrandomized draft of the analogous
few-shot exemplars would have taught exactly that shortcut).

Output columns record Haiku's independent verdict against the original proposal, not just a raw a/b
answer:
  agree     -- Haiku picked the same side as broader_strong: the original direction is corroborated.
  disagree  -- Haiku picked narrower_strong instead: reverse the edge if re-admitting it.
  (blank)   -- unparseable / no answer for that pair.

Requires ANTHROPIC_API_KEY (shoresh/.env, same credential verify_pairs_llm.py uses).
  python -m macula.adjudicate_direction_llm --limit 50 --dry-run
  python -m macula.adjudicate_direction_llm
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

from macula.verify_pairs_llm import _cost, _load_dotenv, call_llm as _base_call_llm, load_glosses

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DROPPED = ROOT / "resources" / "bhsa_hierarchy" / "dropped_edges.tsv"
OUT = ROOT / "resources" / "bhsa_hierarchy" / "direction_llm_verdicts.tsv"

PAIRS_PER_CALL = 25   # same batch size as verify_pairs_llm.py -- Haiku, not the local 1.7B model,
                       # so no throughput reason to go smaller
SIDE_SEED = 2026       # fixed, so side-randomization is reproducible across dry-run/live/resumed runs

PROMPT = (
    "You are a Biblical Hebrew lexicographer. For each PAIR below (two Strong's numbers + their "
    "English glosses), one word is semantically BROADER (a more general category or the head term) "
    "and the other is NARROWER (a more specific instance, kind, or restatement). Judge which side, "
    "'a' or 'b', is the BROADER term. Be strict: many pairs will be genuinely ambiguous or unrelated "
    "-- give your best judgment anyway.\n"
    "Return ONE verdict PER LINE, exactly:  <pair_id><TAB><a|b>\n"
    "No JSON, no commentary, no extra text.\nPairs:\n"
)


def call_llm(batch: list[dict], tries: int = 5):
    # verify_pairs_llm.call_llm hardcodes its own PROMPT and a yes/no/unsure parse -- reimplemented
    # here with this task's PROMPT/parse instead of importing that function directly, but every other
    # line (retry/backoff, usage accounting, HTTPError handling) is identical, deliberately, so a fix
    # to one script's transport layer is a fix worth porting to the other's, not divergent code paths.
    import os
    import urllib.error
    import urllib.request

    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        sys.exit("ERROR: set ANTHROPIC_API_KEY (shoresh/.env)")
    from macula.verify_pairs_llm import API_URL, MODEL

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
            print(f"[adjudicate-direction] warn: no text block (try {attempt+1})", file=sys.stderr)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")[:400]
            except Exception:
                detail = str(e)
            print(f"[adjudicate-direction] HTTP {e.code} (try {attempt+1}): {detail}", file=sys.stderr)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            wait = min(2 ** attempt, 30)
            print(f"[adjudicate-direction] network error (try {attempt+1}): {e} -- retrying in {wait}s",
                  file=sys.stderr)
            import time
            time.sleep(wait)
    return {}, 0, 0


def parse(text: str, wanted: set[str]) -> dict[str, str]:
    import re
    out = {}
    for line in text.splitlines():
        parts = re.split(r"\t", line.strip(), maxsplit=1)
        if len(parts) != 2:
            continue
        pid, verdict = parts[0].strip(), parts[1].strip().lower()
        if pid in wanted and verdict in ("a", "b"):
            out[pid] = verdict
    return out


def load_dropped() -> list[tuple[str, str, str]]:
    """[(broader_strong, narrower_strong, sources)] as originally proposed."""
    if not DROPPED.exists():
        sys.exit(f"{DROPPED} not found -- run build_hierarchy_dag.py first")
    rows = []
    for line in DROPPED.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("broader_strong"):
            continue
        b, n, sources = line.split("\t")
        rows.append((b, n, sources))
    return rows


def _already_done(out_path: Path) -> set[str]:
    done = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or line.startswith("broader_strong"):
                continue
            p = line.split("\t")
            if len(p) >= 2:
                done.add(f"{p[0]}|{p[1]}")
    return done


def main() -> int:
    _load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0, help="cap #pairs (0 = all)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    rows = load_dropped()
    done = _already_done(args.out)
    rows = [(b, n, s) for b, n, s in rows if f"{b}|{n}" not in done]
    if args.limit:
        rows = rows[:args.limit]
    glosses = load_glosses()

    rng = random.Random(SIDE_SEED)
    entries, side_of = [], {}   # pair_id -> 'a' if broader_strong was placed in slot a, else 'b'
    for b, n, _ in rows:
        pid = f"{b}-{n}"
        if rng.random() < 0.5:
            a_strong, b_strong, side_of[pid] = b, n, "a"
        else:
            a_strong, b_strong, side_of[pid] = n, b, "b"
        entries.append({"pair_id": pid, "a": f"{a_strong} {glosses.get(a_strong, '')}",
                         "b": f"{b_strong} {glosses.get(b_strong, '')}"})

    if args.dry_run:
        print(f"[adjudicate-direction] {len(entries)} pairs pending (showing "
              f"{min(PAIRS_PER_CALL, len(entries))})", file=sys.stderr)
        print(PROMPT + json.dumps(entries[:PAIRS_PER_CALL], ensure_ascii=False, indent=1))
        return 0

    from macula.verify_pairs_llm import MODEL
    print(f"[adjudicate-direction] {len(entries)} pairs to adjudicate, model={MODEL}", file=sys.stderr)
    tot_in = tot_out = 0
    row_of = {f"{b}-{n}": (b, n, s) for b, n, s in rows}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    is_new_file = not args.out.exists()
    fh = args.out.open("a", encoding="utf-8")
    if is_new_file:
        fh.write(f"# LLM direction adjudication ({MODEL}) of build_hierarchy_dag.py's dropped-edge\n"
                  f"# pool (dropped_edges.tsv). verdict: agree = Haiku confirmed broader_strong as\n"
                  f"# the broader term; disagree = Haiku picked narrower_strong instead. Side (a/b)\n"
                  f"# was randomized per pair before prompting. See adjudicate_direction_llm.py.\n")
        fh.write("broader_strong\tnarrower_strong\tsources\tverdict\n")
        fh.flush()

    tally = collections.Counter()
    try:
        for i in range(0, len(entries), PAIRS_PER_CALL):
            batch = entries[i:i + PAIRS_PER_CALL]
            got, itok, otok = call_llm(batch)
            tot_in += itok; tot_out += otok
            for pid, side in got.items():
                b, n, sources = row_of[pid]
                verdict = "agree" if side == side_of[pid] else "disagree"
                tally[verdict] += 1
                fh.write(f"{b}\t{n}\t{sources}\t{verdict}\n")
            fh.flush()
            print(f"[adjudicate-direction] {i + len(batch)}/{len(entries)} · +{len(got)} verdicts · "
                  f"running ${_cost(tot_in, tot_out):.3f}", file=sys.stderr)
    finally:
        fh.close()

    print(f"[adjudicate-direction] DONE · agree={tally['agree']} disagree={tally['disagree']} · "
          f"est cost ${_cost(tot_in, tot_out):.3f} ({MODEL}) -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
