"""Part-to-part links between a Hebrew New Testament (as source) and the Greek New Testament (as the text to be learnt).

The word-level bridge (hebrew-nt-bridge) links Hebrew word parts to whole Greek words. For work on word forms both sides
have to be in parts: the Hebrew word as prefixes, word and suffixed pronoun (hebrew-nt-analysis), the Greek word as preverb,
augment, reduplication, stem and ending (word-parts). lexeme-aligner splits only the edition side and has no Hebrew-as-source
direction, so this step calls eflomal itself on the two part sequences, verse by verse.

  python part_links.py --analysis DIR --parts FILE --bridge DIR --edition heb_scg --out OUT [--runs 5]

Run it with a Python that has eflomal and pyarrow (lexeme-aligner's environment has both); it imports nothing else of ours.

  --analysis  hebrew-nt-analysis release folder (<edition>/words.parquet)
  --parts     word-parts src_part_grc.parquet (key, n, text, kind)
  --bridge    hebrew-nt-bridge data folder (<edition>/links.parquet): pairs the verses and marks which part links lie
              inside a word link

What eflomal sees. Hebrew: the Strong's number of each part, or its consonants where the part has none. A word the tagger
split with less than 0.9 confidence is one unit. Greek: the written part without accents, an ending as `-x`, a preverb,
augment or reduplication as `x-`. Nothing of MACULA Greek's analysis beyond the cut points goes in.

eflomal has no seed, so the runs differ. The raw links of every run are kept beside the table (OUT/<edition>/raw/), and the
table gives per link in how many runs it was made (`runs`) and in how many of them both directions agreed (`both`).
Writes OUT/<edition>/part_links.parquet and OUT/<edition>/build.json.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import unicodedata
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

BEFORE = {"preverb", "augment", "reduplication"}
NEIGH = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]


def consonants(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if "א" <= c <= "ת")


def plain_greek(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c)).lower()
    return "".join(c for c in s if c.isalpha()).replace("ς", "σ")


def hebrew_units(analysis: Path, ed: str, min_split: float) -> dict:
    """(book, chapter, verse) -> [(i, part or -1 for a whole word, token, class)] in text order"""
    words: dict = collections.defaultdict(list)
    for r in pq.read_table(analysis / ed / "words.parquet").to_pylist():
        if r["source"] is not None:
            words[(r["book"], r["chapter"], r["verse"], r["i"])].append(r)
    verses: dict = collections.defaultdict(list)
    for (b, ch, v, i), parts in sorted(words.items()):
        parts.sort(key=lambda r: r["part"])
        if len(parts) > 1 and parts[0]["source"] == "model" and (parts[0]["p_split"] or 0) < min_split:
            tok = consonants(parts[0]["word"])
            if tok:
                verses[(b, ch, v)].append((i, -1, "x:" + tok, "-"))
            continue
        for r in parts:
            tok = r["strong"] or ("x:" + consonants(r["text"]) if consonants(r["text"]) else "")
            if tok:
                verses[(b, ch, v)].append((i, r["part"], tok, r["class"] or "-"))
    return verses


def greek_units(parts: Path) -> dict:
    """Greek verse (first 8 digits of the word key) -> [(key, n, token, kind)]"""
    verses: dict = collections.defaultdict(list)
    for r in sorted(pq.read_table(parts).to_pylist(), key=lambda r: (r["key"], r["n"])):
        t = plain_greek(r["text"])
        if not t or r["kind"] == "mark":
            continue
        tok = "-" + t if r["kind"] == "ending" else t + "-" if r["kind"] in BEFORE else t
        verses[r["key"][:8]].append((r["key"], r["n"], tok, r["kind"]))
    return verses


def symmetrise(fwd: set, rev: set, n_src: int, n_trg: int) -> set:
    """grow-diag-final-and, ties broken by position (as lexeme-aligner does)"""
    union, aligned = fwd | rev, set(fwd & rev)
    src_al, trg_al = {s for s, _ in aligned}, {t for _, t in aligned}
    added = True
    while added:
        added = False
        for s, t in sorted(aligned):
            for ds, dt in NEIGH:
                ns, nt = s + ds, t + dt
                if 0 <= ns < n_src and 0 <= nt < n_trg and (ns, nt) in union and (ns not in src_al or nt not in trg_al):
                    aligned.add((ns, nt)); src_al.add(ns); trg_al.add(nt)
                    added = True
    for s, t in sorted(union):
        if s not in src_al and t not in trg_al:
            aligned.add((s, t)); src_al.add(s); trg_al.add(t)
    return aligned


def parse(line: str) -> set:
    return {tuple(int(x) for x in p.split("-")) for p in line.split()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--analysis", type=Path, required=True)
    ap.add_argument("--parts", type=Path, required=True)
    ap.add_argument("--bridge", type=Path, required=True)
    ap.add_argument("--edition", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--min-split", type=float, default=0.9)
    a = ap.parse_args()
    ed, out = a.edition, a.out / a.edition
    (out / "raw").mkdir(parents=True, exist_ok=True)

    heb, grc = hebrew_units(a.analysis, ed, a.min_split), greek_units(a.parts)
    votes: dict = collections.defaultdict(collections.Counter)
    word_links = set()
    for l in pq.read_table(a.bridge / ed / "links.parquet", columns=["greek_id", "book", "chapter", "verse", "i"]).to_pylist():
        votes[(l["book"], l["chapter"], l["verse"])][l["greek_id"][1:9]] += 1
        word_links.add((l["book"], l["chapter"], l["verse"], l["i"], l["greek_id"][1:]))
    group: dict = collections.defaultdict(list)                       # Greek verse -> the Hebrew verses that render it
    for hv in sorted(heb):
        if votes.get(hv):
            group[votes[hv].most_common(1)[0][0]].append(hv)
    lines = []
    for g8 in sorted(group):
        if g8 not in grc:
            continue
        src = [(hv,) + u for hv in group[g8] for u in heb[hv]]
        if src:
            lines.append((src, grc[g8]))
    (out / "raw" / "src.txt").write_text("\n".join(" ".join(u[3] for u in s) for s, _ in lines) + "\n")
    (out / "raw" / "trg.txt").write_text("\n".join(" ".join(u[2] for u in t) for _, t in lines) + "\n")

    import eflomal
    made: dict = collections.Counter()
    both: dict = collections.Counter()
    for k in range(1, a.runs + 1):
        ff, rf = out / "raw" / f"fwd-{k}.txt", out / "raw" / f"rev-{k}.txt"
        if not (ff.exists() and rf.exists()):                         # a kept run is read back, not made again
            with (out / "raw" / "src.txt").open() as sf, (out / "raw" / "trg.txt").open() as tf:
                eflomal.Aligner().align(sf, tf, links_filename_fwd=str(ff), links_filename_rev=str(rf), quiet=True)
        for n, (fl, rl) in enumerate(zip(ff.read_text().split("\n"), rf.read_text().split("\n"))):
            if n >= len(lines):
                break
            fwd, rev = parse(fl), parse(rl)
            for p in symmetrise(fwd, rev, len(lines[n][0]), len(lines[n][1])):
                made[(n,) + p] += 1
                both[(n,) + p] += p in fwd and p in rev
    rows = []
    for (n, s, t), c in sorted(made.items()):
        (b, ch, v), i, part, _, cls = lines[n][0][s]
        key, gn, _, kind = lines[n][1][t]
        rows.append({"book": b, "chapter": ch, "verse": v, "i": i, "part": part, "hebrew_class": cls, "greek_id": "n" + key,
                     "greek_n": gn, "greek_kind": kind, "runs": c, "both": both[(n, s, t)],
                     "in_word_link": (b, ch, v, i, key) in word_links})
    schema = pa.schema([("book", pa.string()), ("chapter", pa.int16()), ("verse", pa.int16()), ("i", pa.int16()), ("part", pa.int8()),
                        ("hebrew_class", pa.string()), ("greek_id", pa.string()), ("greek_n", pa.int8()), ("greek_kind", pa.string()),
                        ("runs", pa.int8()), ("both", pa.int8()), ("in_word_link", pa.bool_())])
    f = out / "part_links.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), f, compression="zstd")

    K = a.runs
    firm = [r for r in rows if r["runs"] == K]
    heb_n = collections.Counter(u[4] for s, _ in lines for u in s)
    grc_n = collections.Counter(u[3] for _, t in lines for u in t)
    heb_firm = collections.Counter(c for (_, c) in {((r["book"], r["chapter"], r["verse"], r["i"], r["part"]), r["hebrew_class"]) for r in firm})
    grc_firm = collections.Counter(k for (_, k) in {((r["greek_id"], r["greek_n"]), r["greek_kind"]) for r in firm})
    stems = [r for r in firm if r["greek_kind"] == "stem" and r["hebrew_class"] in ("noun", "verb", "adj", "adv", "num")]
    build = {"edition": ed, "runs": K, "min_split": a.min_split, "lines": len(lines),
             "hebrew_verses_unpaired": sum(1 for hv in heb if not votes.get(hv)),
             "hebrew_units": sum(heb_n.values()), "greek_units": sum(grc_n.values()), "links": len(rows),
             "links_by_runs": dict(sorted(collections.Counter(r["runs"] for r in rows).items())),
             "links_all_runs": len(firm), "links_all_runs_both_directions": sum(r["both"] == K for r in rows),
             "content_to_stem_all_runs": len(stems),
             "content_to_stem_inside_word_link": round(sum(r["in_word_link"] for r in stems) / max(1, len(stems)), 3),
             "hebrew_share_linked_all_runs": {c: [round(heb_firm[c] / n, 3), n] for c, n in heb_n.most_common()},
             "greek_share_linked_all_runs": {k: [round(grc_firm[k] / n, 3), n] for k, n in grc_n.most_common()},
             "pairs_all_runs": {f"{c}>{k}": n for (c, k), n in
                                collections.Counter((r["hebrew_class"], r["greek_kind"]) for r in firm).most_common(24)},
             "inputs": {"analysis": a.analysis.name, "parts": hashlib.sha256(a.parts.read_bytes()).hexdigest(),
                        "bridge_links": hashlib.sha256((a.bridge / ed / "links.parquet").read_bytes()).hexdigest()},
             "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}
    (out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(build, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
