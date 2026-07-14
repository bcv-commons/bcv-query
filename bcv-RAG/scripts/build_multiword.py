#!/usr/bin/env python3
"""Multi-word expressions (roadmap M1) — target phrase → the original lexeme(s) it renders.

Mined from `bcv-commons/lexeme-alignments` (the aligner's contiguous multi-word surfaces). Two kinds,
both useful for the analyzer's phrase detection:
  • fertility  — one original lexeme rendered by a multi-word target phrase (`only begotten` ← G3439)
  • phrasal    — a target phrase spanning several original lexemes  (`holy spirit` → {G4151, G0040})

The dataset is TYPE-level (surface→lexeme, no verse/occurrence), so a surface's lexeme *set* is the
union over the corpus; we can't see co-occurrence. We therefore precision-filter and emit a confidence
so consumers threshold: content lexemes only (POS from the prior pack — drops article/preposition glue),
same-testament sets (drops OT/NT homograph pooling), evidence floor, and share/hi_conf ranking.

  python3 scripts/build_multiword.py            # -> resources/multiword_expressions/<iso>.tsv
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
OUT = HERE.parent / "resources" / "multiword_expressions"
PRIOR = HERE.parent / "resources" / "prior_pack" / "prior_pack.parquet"

MIN_COUNT = 2         # a (surface→lexeme) pair needs this many alignments
MIN_SHARE = 0.10      # …and this P(lexeme|surface) to be a real component
MIN_TOKENS = 2        # multi-word


def _content_strongs() -> set:
    """H####/G#### Strong's whose dominant POS is a content word (prior-pack word_class=content)."""
    import pyarrow.parquet as pq
    if not PRIOR.exists():
        return set()
    t = pq.read_table(PRIOR, columns=["strong", "word_class"]).to_pylist()
    return {r["strong"] for r in t if r["word_class"] == "content" and r["strong"]}


def build(iso_list=None):
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download, HfApi
    content = _content_strongs()
    print(f"[mwe] {len(content)} content Strong's from prior pack", file=sys.stderr)

    repo = "bcv-commons/lexeme-alignments"
    isos = iso_list or sorted(f.split("/")[0][4:] for f in HfApi().list_repo_files(repo, repo_type="dataset")
                              if f.startswith("iso=") and f.endswith("data.parquet"))
    OUT.mkdir(parents=True, exist_ok=True)
    summary = []
    for iso in isos:
        p = hf_hub_download(repo, f"iso={iso}/data.parquet", repo_type="dataset")
        rows = pq.read_table(p).to_pylist()
        # surface -> {lexeme: [strong, count, share, hi_conf, {methods}]}
        agg: dict = collections.defaultdict(dict)
        for r in rows:
            s = (r["surface"] or "").strip()
            if len(s.split()) < MIN_TOKENS:
                continue
            if r["count"] < MIN_COUNT or r["share"] < MIN_SHARE:
                continue
            if content and r["strong"] not in content:     # content lexemes only
                continue
            lx = r["lexeme"]
            e = agg[s].get(lx)
            if e is None:
                agg[s][lx] = [r["strong"], r["count"], r["share"], r["hi_conf"], {r["method"]}]
            else:
                e[1] += r["count"]; e[2] = max(e[2], r["share"]); e[3] = max(e[3], r["hi_conf"]); e[4].add(r["method"])

        out_rows = []
        for surface, lexs in agg.items():
            # same-testament only (a real phrase renders one original language)
            testaments = {("NT" if lx.startswith("grc") else "OT") for lx in lexs}
            if len(testaments) > 1:
                # keep the dominant-testament subset (drop the pooled-homograph tail)
                dom = max(("NT", "OT"), key=lambda t: sum(1 for lx in lexs if (lx.startswith("grc")) == (t == "NT")))
                lexs = {lx: v for lx, v in lexs.items() if (lx.startswith("grc")) == (dom == "NT")}
            if not lexs:
                continue
            lex_sorted = sorted(lexs.items(), key=lambda kv: -kv[1][2])   # by share desc
            strongs = ",".join(v[0] for _lx, v in lex_sorted)
            lexemes = ",".join(lx for lx, _v in lex_sorted)
            conf = round(max(v[2] * v[3] for _lx, v in lexs.items()), 3)  # best share×hi_conf
            tot = sum(v[1] for _lx, v in lexs.items())
            methods = ";".join(sorted(set().union(*(v[4] for v in lexs.values()))))
            arity = "phrasal" if len(lexs) > 1 else "fertility"
            # fertility for ONE content lexeme is a real MWE only if it's a content phrase, not
            # article+noun glue — drop when a short leading token (article/prep) reduces it to 1 word.
            toks = surface.split()
            if arity == "fertility" and len(toks) == 2 and len(toks[0]) <= 3:
                continue
            out_rows.append((surface, strongs, lexemes, arity, conf, tot, methods))
        out_rows.sort(key=lambda r: -r[4])

        with (OUT / f"{iso}.tsv").open("w", encoding="utf-8") as fh:
            fh.write(f"# multi-word expressions (M1): target phrase -> original lexeme(s); lang={iso}; "
                     f"from bcv-commons/lexeme-alignments; content+same-testament, count>={MIN_COUNT}. CC0\n")
            fh.write("surface\tstrongs\tlexemes\tkind\tconfidence\tcount\tmethods\n")
            for r in out_rows:
                fh.write("\t".join(map(str, r)) + "\n")
        ph = sum(1 for r in out_rows if r[3] == "phrasal")
        summary.append((iso, len(out_rows), ph))
        print(f"[mwe] {iso}: {len(out_rows)} MWEs ({ph} phrasal, {len(out_rows)-ph} fertility)", file=sys.stderr)
    return summary


if __name__ == "__main__":
    build(sys.argv[1:] or None)
