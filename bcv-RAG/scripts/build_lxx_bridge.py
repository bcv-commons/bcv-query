"""Precompute the Hebrew→Greek LXX bridge into a local table.

Strategy 2 (query/lxx_expand.py) used to hit shoresh `/bridge/{H}` once per
Hebrew tag at query time — fine for rare lemmas, but a few-hundred-ms to
multi-second tax for frequent ones (the endpoint aggregates LXX alignments on
the fly). The bridge is STATIC reference data, so we materialize it once here
into resources/lxx_bridge.tsv and let expand_lxx read it locally (zero network
on the hot path).

We only build the codes expand_lxx actually queries: Hebrew codes with spine
frequency in [MIN_FREQ, MAX_FREQ). Generic high-frequency lemmas (God, LORD, …)
are skipped at query time anyway (they bridge only to generic Greek), so there
is no point paying their — most expensive — bridge here either.

Usage (run where SHORESH_URL is reachable, e.g. on the host against private
shoresh):
    SHORESH_URL=http://host.docker.internal:8080 \
        python -m scripts.build_lxx_bridge --out resources/lxx_bridge.tsv

Output TSV columns: hebrew_strong<TAB>greek_strong<TAB>count
(zero-padded codes, e.g. H0430 / G1656; top GREEK_PER_HEBREW greek per hebrew,
each with count >= MIN_GREEK_COUNT; sorted by hebrew then count desc).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

DEFAULT_MIN_FREQ = 3   # below this, bridges are too thin to clear MIN_GREEK_COUNT anyway
GREEK_PER_HEBREW = 4
MIN_GREEK_COUNT = 3


def _norm(code: str) -> str:
    m = re.match(r"^([HG])(\d+)$", code)
    return f"{m.group(1)}{int(m.group(2)):04d}" if m else code


def _hebrew_codes(freq_path: Path, min_freq: int, max_freq: int) -> list[str]:
    """Hebrew codes with spine frequency in [min_freq, max_freq); max_freq<=0
    means no upper bound (the full table — now cheap since shoresh is O(n))."""
    out: list[str] = []
    with freq_path.open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 2 and p[0].startswith("H"):
                try:
                    c = int(p[1])
                except ValueError:
                    continue
                if c >= min_freq and (max_freq <= 0 or c < max_freq):
                    out.append(_norm(p[0]))
    return out


def _fetch(client: httpx.Client, padded: str) -> tuple[str, list[tuple[str, int]]]:
    url_code = re.sub(r"^H0*", "H", padded)
    try:
        r = client.get(f"/bridge/{url_code}", timeout=30.0)
        if r.status_code != 200:
            return padded, []
        rows = []
        for t in r.json().get("greek_translations", []):
            g = t.get("greek_strong", "")
            n = int(t.get("count", 0))
            if g and n >= MIN_GREEK_COUNT:
                rows.append((_norm(g), n))
            if len(rows) >= GREEK_PER_HEBREW:
                break
        return padded, rows
    except Exception as e:
        print(f"  warn: {padded} failed: {e}", file=sys.stderr)
        return padded, []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freq", default="resources/strongs_freq.tsv")
    ap.add_argument("--out", default="resources/lxx_bridge.tsv")
    ap.add_argument("--shoresh", default=os.environ.get("SHORESH_URL", "").rstrip("/"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--min-freq", type=int, default=DEFAULT_MIN_FREQ)
    ap.add_argument("--max-freq", type=int, default=0,
                    help="exclusive upper frequency bound; <=0 = no cap (full table)")
    args = ap.parse_args()
    if not args.shoresh:
        sys.exit("set SHORESH_URL or pass --shoresh")

    codes = _hebrew_codes(Path(args.freq), args.min_freq, args.max_freq)
    cap = "no cap" if args.max_freq <= 0 else f"<{args.max_freq}"
    print(f"building LXX bridge for {len(codes)} Hebrew codes "
          f"(freq >={args.min_freq}, {cap}) via {args.shoresh}")

    results: dict[str, list[tuple[str, int]]] = {}
    done = 0
    with httpx.Client(base_url=args.shoresh) as client:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(_fetch, client, c): c for c in codes}
            for fut in as_completed(futs):
                code, rows = fut.result()
                if rows:
                    results[code] = rows
                done += 1
                if done % 500 == 0:
                    print(f"  {done}/{len(codes)} ({len(results)} with bridges)")

    out = Path(args.out)
    with out.open("w", encoding="utf-8") as fh:
        fh.write("hebrew_strong\tgreek_strong\tcount\n")
        for h in sorted(results):
            for g, n in results[h]:
                fh.write(f"{h}\t{g}\t{n}\n")
    pairs = sum(len(v) for v in results.values())
    print(f"wrote {out}: {len(results)} hebrew codes, {pairs} bridge pairs")


if __name__ == "__main__":
    main()
