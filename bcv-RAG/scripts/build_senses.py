"""Build the lexeme-level Strong's → word-sense inventory (S2 / Phase 1, senses).

Completes the "sense + domain" macula layer at the lexeme level: for each
Strong's, its distinct word-senses with a representative gloss + frequency
(polysemy — e.g. H7307 ruach → spirit / wind / breath). Senses disambiguate;
domains group. From MACULA (CC BY 4.0, Biblica + UBS MARBLE).

Sources:
  hbo  macula-hebrew WLC TSV — `sensenumber` + `english` per word (direct).
  grc  macula-greek sources/Clear/wordsense/greek-wordsenses.tsv (word_id →
       sense_number), joined to the Nestle1904 TSV (word_id=xml:id → strong, gloss).

Output: resources/senses/<lang>.tsv
  columns: strong, sense, gloss, count, share
  (one row per (lexeme, sense); the lexeme's primary sense is always kept,
  secondaries when count >= 2; sorted by strong then count desc.)
NOTE: `gloss` is the dominant English rendering of that sense (a label, not the
formal SDBH/SDBG sense title — those live in the senses XML, which is LFS-gated).
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import re
import sys
from pathlib import Path

import httpx

RAW_G = "https://raw.githubusercontent.com/Clear-Bible/macula-greek/main"
MED_H = "https://media.githubusercontent.com/media/Clear-Bible/macula-hebrew/main"
URLS = {
    "grc_tsv": f"{RAW_G}/Nestle1904/tsv/macula-greek-Nestle1904.tsv",
    "grc_ws": f"{RAW_G}/sources/Clear/wordsense/greek-wordsenses.tsv",
    "hbo_tsv": f"{MED_H}/WLC/tsv/macula-hebrew.tsv",
}
_ART = re.compile(r"^\[?(a|an|the|of|to)\]?\s+", re.I)


def _text(url: str, cached: str) -> str:
    if cached:
        return Path(cached).read_text(encoding="utf-8")
    print(f"downloading {url} …", file=sys.stderr)
    r = httpx.get(url, timeout=300.0, follow_redirects=True)
    r.raise_for_status()
    return r.text


def _norm(prefix: str, s: str) -> str | None:
    m = re.match(r"(\d+)", s.strip())
    return f"{prefix}{int(m.group(1)):04d}" if m else None


def _clean(g: str) -> str:
    g = g.strip().replace(".", " ").strip("[] ")
    g = _ART.sub("", g).strip("[] ")           # drop a/an/the/of/to + brackets
    return g


def _write(out: Path, agg: dict) -> None:
    """agg[strong][sense_number][gloss] = count."""
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for s, senses in agg.items():
        total = sum(sum(g.values()) for g in senses.values())
        ranked = sorted(((sn, gc.most_common(1)[0][0], sum(gc.values()))
                         for sn, gc in senses.items()), key=lambda x: -x[2])
        for i, (sn, label, n) in enumerate(ranked):
            if i == 0 or n >= 2:
                rows.append((s, sn, label, n, round(n / total, 3)))
    rows.sort(key=lambda r: (r[0], -r[3]))
    with out.open("w", encoding="utf-8") as f:
        f.write("strong\tsense\tgloss\tcount\tshare\n")
        for s, sn, label, n, share in rows:
            f.write(f"{s}\t{sn}\t{label}\t{n}\t{share}\n")
    print(f"  wrote {out}: {len(agg)} lexemes, {len(rows)} senses")


def build_hbo(args) -> None:
    agg: dict = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for r in csv.DictReader(io.StringIO(_text(URLS["hbo_tsv"], args.tsv)), delimiter="\t"):
        s = _norm("H", r.get("strongnumberx") or "")
        sn = (r.get("sensenumber") or "").strip()
        gl = _clean(r.get("english") or "")
        if s and sn and gl:
            agg[s][sn][gl] += 1
    _write(Path(args.out or "resources/senses/hbo.tsv"), agg)


def build_grc(args) -> None:
    sense: dict[str, str] = {}
    for r in csv.DictReader(io.StringIO(_text(URLS["grc_ws"], args.wordsenses)), delimiter="\t"):
        sn = (r.get("sense_number") or "").strip()
        if sn:
            sense[r["macula_greek_word_id"]] = sn
    agg: dict = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for r in csv.DictReader(io.StringIO(_text(URLS["grc_tsv"], args.tsv)), delimiter="\t"):
        s = _norm("G", r.get("strong") or "")
        sn = sense.get((r.get("xml:id") or "").strip())
        gl = _clean(r.get("gloss") or "")
        if s and sn and gl:
            agg[s][sn][gl] += 1
    _write(Path(args.out or "resources/senses/grc.tsv"), agg)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=["grc", "hbo"])
    ap.add_argument("--out", default="")
    ap.add_argument("--tsv", default="")
    ap.add_argument("--wordsenses", default="")     # grc only
    args = ap.parse_args()
    (build_grc if args.lang == "grc" else build_hbo)(args)


if __name__ == "__main__":
    main()
