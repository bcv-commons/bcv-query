"""Cross-check the Greek NT clause layout against an independent Hebrew reading of the same text: the clause segments the clause
tagger (trained on the Old Testament only) gives Salkinson–Ginsburg's Hebrew New Testament, joined to the Greek through
lexeme-aligner's alignment by Greek word id (bcv-commons/alignments-by-id, CC0).

    python -m macula.nt_layout_crosscheck --alignments DIR [--classes kept] [--layout macula/data/nt-clause-layout]
                                          [--analysis macula/data/clause-tagger/export/heb_scg] [--out macula/data/nt-clause-layout]

The unit is a pair of neighbouring Hebrew tokens of a verse whose Greek words are known (links of the chosen classes; a token
whose links fall on more than one Greek line is left out). The pair is "together" in Hebrew when both tokens are in one clause
segment, and in Greek when their Greek words are on one line of the layout. Where the two disagree, either reading can be the one
that is off, or the translation changed the structure: the figures say how far two readings made independently agree, not which
is right. The alignment is never used to build either reading.

Writes crosscheck.json (agreement overall and per book) and crosscheck-disagreements.tsv (each disagreeing pair with both lines).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
EDITION = "heb_scg"


def greek_lines(layout: Path) -> tuple[dict[str, int], list[dict]]:
    """Greek word id ('n' + key) -> line number; the lines in text order."""
    line_of, lines = {}, []
    order = sorted((layout / "clauses").iterdir(), key=lambda d: json.loads(next(d.glob("*.jsonl")).open().readline())["first"][:2])
    for d in order:
        for f in sorted(d.glob("*.jsonl")):
            ch = int(f.stem.split("_")[-1])
            for row in f.read_text(encoding="utf-8").splitlines():
                r = json.loads(row)
                n = len(lines)
                lines.append({"book": d.name, "chapter": ch, "verse": r["verse"], "text": r["text"], "text_depth": r["text_depth"]})
                for k in r["words"]:
                    line_of["n" + k] = n
    return line_of, lines


def hebrew_segments(analysis: Path) -> tuple[dict[tuple, int], dict[tuple, str], dict[tuple, str]]:
    """(book, chapter, verse, token) -> segment; (book, chapter, verse, seg) -> its text; (book, chapter, verse, token) -> word."""
    import pyarrow.parquet as pq
    words = pq.read_table(analysis / "words.parquet", columns=["book", "chapter", "verse", "i", "part", "word", "seg", "class"]).to_pylist()
    seg_of, text, word = {}, collections.defaultdict(list), {}
    for w in words:
        if w["class"] == "verse-number" or w["part"] != 0:
            continue
        k = (w["book"], w["chapter"], w["verse"], w["i"])
        seg_of[k] = w["seg"]
        word[k] = w["word"]
        text[(w["book"], w["chapter"], w["verse"], w["seg"])].append(w["word"])
    return seg_of, {k: " ".join(v) for k, v in text.items()}, word


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--alignments", required=True, help="a download of bcv-commons/alignments-by-id")
    ap.add_argument("--classes", default="kept", help="link classes to use (comma-separated)")
    ap.add_argument("--layout", default=str(HERE / "data" / "nt-clause-layout"))
    ap.add_argument("--analysis", default=str(HERE / "data" / "clause-tagger" / "export" / EDITION))
    ap.add_argument("--out", default=str(HERE / "data" / "nt-clause-layout"))
    a = ap.parse_args()
    root = Path(a.alignments) / "n1904"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    pin = manifest["languages"]["heb"]["editions"][EDITION]["parts"]
    analysis = Path(a.analysis)
    if hashlib.sha256((analysis / "words.parquet").read_bytes()).hexdigest() != pin["sha256"]:
        raise SystemExit(f"the alignment's part numbers are pinned to {pin['dataset']} {pin['revision']} (sha256 {pin['sha256'][:12]}…); "
                         "this words.parquet differs")
    classes = set(a.classes.split(","))
    line_of, lines = greek_lines(Path(a.layout))
    seg_of, seg_text, word = hebrew_segments(analysis)

    table = collections.Counter()                      # (hebrew together, greek together)
    per_book: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    rows = []
    stats = collections.Counter()
    for f in sorted((root / "h" / "heb" / EDITION).glob("*.json")):
        book = f.name.split("_")[0]
        for cv, v in json.loads(f.read_text(encoding="utf-8")).items():
            ch, vs = map(int, cv.split(":"))
            greek_of: dict[int, set] = collections.defaultdict(set)
            for positions, ids, cls in v["links"]:
                if cls not in classes:
                    continue
                for p in positions:
                    t = int(str(p).split(".")[0])
                    greek_of[t].update(line_of[i] for i in ids if i in line_of)
            known = {t: next(iter(g)) for t, g in greek_of.items() if len(g) == 1}
            stats["tokens_with_one_line"] += len(known)
            stats["tokens_on_two_lines"] += sum(len(g) > 1 for g in greek_of.values())
            for t in sorted(known):
                if t + 1 not in known:
                    continue
                k1, k2 = (book, ch, vs, t), (book, ch, vs, t + 1)
                if k1 not in seg_of or k2 not in seg_of:
                    continue
                h = seg_of[k1] == seg_of[k2]
                g = known[t] == known[t + 1]
                table[(h, g)] += 1
                per_book[book][(h, g)] += 1
                if h != g:
                    rows.append((book, ch, vs, t, word[k1], word[k2], "together" if h else "apart", "together" if g else "apart",
                                 seg_text[(book, ch, vs, seg_of[k1])], seg_text[(book, ch, vs, seg_of[k2])] if not h else "",
                                 lines[known[t]]["text"], lines[known[t + 1]]["text"] if not g else ""))

    def figures(c: collections.Counter) -> dict:
        n = sum(c.values())
        both_apart, h_apart, g_apart = c[(False, False)], c[(False, False)] + c[(False, True)], c[(False, False)] + c[(True, False)]
        p = both_apart / h_apart if h_apart else 0.0
        r = both_apart / g_apart if g_apart else 0.0
        return {"pairs": n, "agree": round((c[(True, True)] + both_apart) / n, 4) if n else None,
                "boundaries_hebrew": h_apart, "boundaries_greek": g_apart, "boundaries_both": both_apart,
                "hebrew_boundary_also_greek": round(p, 4), "greek_boundary_also_hebrew": round(r, 4),
                "boundary_f1": round(2 * p * r / (p + r), 4) if p + r else 0.0}

    report = {"edition": EDITION, "classes": sorted(classes), "alignment_built": manifest["languages"]["heb"]["editions"][EDITION]["built"],
              "analysis": f"{pin['dataset']} {pin['revision']}", **stats, **figures(table),
              "books": {b: figures(c) for b, c in sorted(per_book.items())}}
    out = Path(a.out)
    (out / "crosscheck.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    with open(out / "crosscheck-disagreements.tsv", "w", encoding="utf-8") as fh:
        fh.write("book\tchapter\tverse\ttoken\tword\tnext_word\thebrew\tgreek\thebrew_segment\thebrew_next_segment\tgreek_line\tgreek_next_line\n")
        for r in rows:
            fh.write("\t".join(map(str, r)) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "books"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
