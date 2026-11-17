"""Package the Hebrew <-> Greek lexeme bridge and the verb-form bridge as one pinned dataset (plan step M7), in the shape
make-tanakh-grammar reads, with a provenance statement. Nothing is uploaded: files are written to a folder for review.

    python -m macula.release_hebrew_greek_bridge --tag v0.1 --out DIR [--compare PRODUCTION_BRIDGES_DIR] [--allow-dirty]

Inputs (in git): resources/lxx_bridge_tiers/{macula,glaux,greek_numbers}.tsv (macula.build_lxx_bridge_tiers) and
resources/grammar_bridge/grammar_bridge.tsv (macula.build_grammar_bridge). Only Hebrew and Greek: no gloss-found tier (the user,
2026-11-17; production's NO_TIERS = {"jev"}), no model-made pairs (those are bcv-commons/hebrew-greek-lexeme-bridge-model, read beside
this one).

DIR gets:
  data/lexemes.parquet      hebrew_strong, greek_strong, tier (macula | glaux), count, score, score_reverse
  data/verb_forms.parquet   hebrew_form, greek_form, count, p_greek_given_hebrew, p_hebrew_given_greek
  data/greek_numbers.parquet MACULA `greekstrong` numbers the Greek NT never uses -> the NT number of their forms
  strong_bridge.json        {"h2g": {hebrew: [[greek, tier, count, share], ...]}, "g2h": {greek: [[hebrew, tier, count, share]]},
                             "sources": {...}}: numbers without padding or letters, best first per tier, as production's file
  grammar_bridge.json       {"pairs": [[hebrew_form, greek_form, count]], "h2g": {"conj|stem": [["tense|voice|mood", share]]},
                             "g2h": {...}}
  README.md, SHA256SUMS; with --compare also compare.md (figures only, kept out of the release folder's checksums)

Shares: h2g's share is P(greek | hebrew) for macula (the tier's score) and Dice for glaux (symmetric); g2h's macula share is
P(hebrew | greek) over the tier's rows (count >= 3, so a little above the share over all occurrences).
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TIERS = ROOT / "resources" / "lxx_bridge_tiers"
GRAMMAR = ROOT / "resources" / "grammar_bridge" / "grammar_bridge.tsv"
CARD = HERE / "hebrew_greek_bridge_card.md"
CODE = [HERE / "release_hebrew_greek_bridge.py", HERE / "build_lxx_bridge_tiers.py", HERE / "build_grammar_bridge.py", CARD,
        TIERS, GRAMMAR.parent]


def tsv(p):
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def num(s: str) -> int:
    return int(s.lstrip("HG").lstrip("0") or 0)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def lexeme_rows():
    rows = [r for t in ("macula", "glaux") for r in tsv(TIERS / f"{t}.tsv")]
    tot = collections.Counter()
    for r in rows:
        if r["tier"] == "macula":
            tot[r["greek_strong"]] += int(r["count"])
    out = []
    for r in rows:
        rev = int(r["count"]) / tot[r["greek_strong"]] if r["tier"] == "macula" else float(r["score"])
        out.append({"hebrew_strong": r["hebrew_strong"], "greek_strong": r["greek_strong"], "tier": r["tier"], "count": int(r["count"]),
                    "score": round(float(r["score"]), 5), "score_reverse": round(rev, 5)})
    return out


def strong_json(rows):
    h2g, g2h = collections.defaultdict(list), collections.defaultdict(list)
    for r in rows:
        h2g[str(num(r["hebrew_strong"]))].append([num(r["greek_strong"]), r["tier"], r["count"], r["score"]])
        g2h[str(num(r["greek_strong"]))].append([num(r["hebrew_strong"]), r["tier"], r["count"], r["score_reverse"]])
    order = {"macula": 0, "glaux": 1}
    for d in (h2g, g2h):
        for v in d.values():
            v.sort(key=lambda x: (-x[3], order[x[1]]))
    return {"h2g": dict(sorted(h2g.items(), key=lambda x: int(x[0]))), "g2h": dict(sorted(g2h.items(), key=lambda x: int(x[0]))),
            "sources": {"macula": "MACULA Hebrew WLC `greekstrong` per occurrence, CC BY 4.0 (Clear Bible / Biblica)",
                        "glaux": "verse co-occurrence, Hebrew text against the Septuagint of GLAUx (CC BY-SA 4.0), verses mapped with "
                                 "STEPBible TVTMS (CC BY 4.0); production's tier `lxx`"}}


def grammar_json(rows):
    h2g, g2h = collections.defaultdict(list), collections.defaultdict(list)
    for r in rows:
        h2g[r["hebrew_form"]].append([r["greek_form"], round(float(r["p_greek_given_hebrew"]), 3)])
        g2h[r["greek_form"]].append([r["hebrew_form"], round(float(r["p_hebrew_given_greek"]), 3)])
    for d in (h2g, g2h):
        for v in d.values():
            v.sort(key=lambda x: -x[1])
    return {"pairs": [[r["hebrew_form"], r["greek_form"], int(r["count"])] for r in sorted(rows, key=lambda r: -int(r["count"]))],
            "h2g": dict(h2g), "g2h": dict(g2h)}


def compare(sj, gj, prod: Path) -> str:
    """Figures only: what production's lexemes() and cells() would read from ours against its own files (jev left out)."""
    TOP, MIN_SHARE, CELL_MIN = 3, 0.05, 0.2

    def lexemes(j):
        out = {}
        for h, lst in j.items():
            best = collections.defaultdict(float)
            for g, src, n, p in lst:
                if src != "jev":
                    best[str(g)] = max(best[str(g)], p)
            out[h] = [g for g, p in sorted(best.items(), key=lambda x: -x[1]) if p >= MIN_SHARE]
        return out

    def cells(j):
        return {h: {f"{g.split('|')[0]}|{g.split('|')[-1]}" for g, p in lst if p >= CELL_MIN} for h, lst in j.items()}

    ps = json.load(open(prod / "strong_bridge.json", encoding="utf-8"))
    pg = json.load(open(prod / "grammar_bridge.json", encoding="utf-8"))
    a, b = lexemes(sj["h2g"]), lexemes(ps["h2g"])
    both = set(a) & set(b)
    same_top1 = sum(1 for h in both if a[h][:1] == b[h][:1])
    same_top3 = sum(1 for h in both if set(a[h][:TOP]) == set(b[h][:TOP]))
    ca, cb = cells(gj["h2g"]), cells(pg["h2g"])
    cboth = set(ca) & set(cb)
    lines = ["# Compared with production's private bridge files (figures only)", "",
             "As production reads them (source/bridges.py: TOP 3, MIN_SHARE 0.05, CELL_MIN 0.2, tier `jev` not read).", "",
             "| | ours | production | both |", "|---|---|---|---|",
             f"| Hebrew lexemes with a Greek partner | {sum(1 for v in a.values() if v):,} | {sum(1 for v in b.values() if v):,} | "
             f"{sum(1 for h in both if a[h] and b[h]):,} |",
             f"| same best Greek lexeme | | | {same_top1:,} of {len(both):,} |",
             f"| same top-3 set | | | {same_top3:,} of {len(both):,} |",
             f"| Hebrew verb forms (cells) | {len(ca)} | {len(cb)} | {len(cboth)} |",
             f"| same Greek tense-mood set at share >= 0.2 | | | {sum(1 for h in cboth if ca[h] == cb[h])} of {len(cboth)} |", ""]
    only_ours = sorted((h for h in a if a[h] and not b.get(h)), key=int)
    only_prod = sorted((h for h in b if b[h] and not a.get(h)), key=int)
    lines += [f"Hebrew lexemes with a partner only here: {len(only_ours)} (first: {', '.join(only_ours[:15])}).",
              f"Only in production's file: {len(only_prod)} (first: {', '.join(only_prod[:15])}).", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--compare", type=Path)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    import pyarrow as pa
    import pyarrow.parquet as pq
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *map(str, CODE)], cwd=ROOT, capture_output=True, text=True).stdout
    if dirty.strip() and not a.allow_dirty:
        raise SystemExit("uncommitted changes in the builder or its inputs; commit first (or --allow-dirty):\n" + dirty)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; use a new folder")
    (a.out / "data").mkdir(parents=True)
    lex = lexeme_rows()
    gram = tsv(GRAMMAR)
    nums = tsv(TIERS / "greek_numbers.tsv")
    pq.write_table(pa.Table.from_pylist(lex), a.out / "data" / "lexemes.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist([{**r, "count": int(r["count"]), "p_greek_given_hebrew": float(r["p_greek_given_hebrew"]),
                                          "p_hebrew_given_greek": float(r["p_hebrew_given_greek"])} for r in gram]),
                   a.out / "data" / "verb_forms.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(nums), a.out / "data" / "greek_numbers.parquet", compression="zstd")
    sj, gj = strong_json(lex), grammar_json(gram)
    (a.out / "strong_bridge.json").write_text(json.dumps(sj, ensure_ascii=False), encoding="utf-8")
    (a.out / "grammar_bridge.json").write_text(json.dumps(gj, ensure_ascii=False), encoding="utf-8")
    tiers = collections.Counter(r["tier"] for r in lex)
    fill = {"@TAG@": a.tag, "@CODE@": commit + (" (dirty)" if dirty.strip() else ""),
            "@MACULA_ROWS@": f"{tiers['macula']:,}", "@GLAUX_ROWS@": f"{tiers['glaux']:,}",
            "@HEBREW@": f"{len(sj['h2g']):,}", "@GREEK@": f"{len(sj['g2h']):,}",
            "@FORM_ROWS@": f"{len(gram):,}", "@HFORMS@": f"{len(gj['h2g'])}", "@GFORMS@": f"{len(gj['g2h'])}",
            "@NUMS@": f"{sum(1 for r in nums if r.get('nt_strong')):,}"}
    card = CARD.read_text(encoding="utf-8")
    for k, v in fill.items():
        card = card.replace(k, v)
    if "@" in "".join(w for w in card.split() if w.startswith("@") and w.endswith("@")):
        raise SystemExit("unfilled card field")
    (a.out / "README.md").write_text(card, encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (a.out / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(a.out)}\n" for p in files))
    print(f"{a.out}: lexeme rows {len(lex):,} ({dict(tiers)}), Hebrew {len(sj['h2g']):,}, Greek {len(sj['g2h']):,}; "
          f"verb-form rows {len(gram):,}; code {fill['@CODE@']}")
    if a.compare:
        cmp = a.out.parent / f"{a.out.name}-compare.md"
        cmp.write_text(compare(sj, gj, a.compare), encoding="utf-8")
        print(cmp.read_text())


if __name__ == "__main__":
    main()
