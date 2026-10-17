"""Score a clause layout against bsb-add-books' moving-out test set (shoresh/tests/data/moving_out_test_set.tsv).

Each test line names a verse, the opening of one segment in it (their wording) and the direction the layout should take from the
segment before: to the margin, to the speech's main line, out one level, out two or more levels, out of the speech, level or in.
Scored as they score it: "to the margin" is right only at depth 0; the other ways out are right for any step out that stays above
the margin (the layout has no explicit speech-main-line level). Law chapters are scored in the law view (text_depth_law).

    python -m macula.moving_out_score [CLAUSES_DIR]       # default: macula/data/clause-layout/clauses
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEST_SET = HERE.parent / "tests" / "data" / "moving_out_test_set.tsv"
BOOKS = {"Gen": "GEN", "Exod": "EXO", "Lev": "LEV", "Num": "NUM", "Deut": "DEU", "Josh": "JOS", "1 Sam": "1SA", "2 Sam": "2SA",
         "1 Kgs": "1KI", "2 Kgs": "2KI", "Isa": "ISA", "Jer": "JER", "Amos": "AMO", "Hab": "HAB", "Hag": "HAG", "Job": "JOB",
         "Ps": "PSA"}
# the law view for the law corpus: Leviticus, Exod 21-23, Deut 12-26, the law chapters of Numbers (bsb-add-books' genre split)
LAW = {"LEV": range(1, 28), "EXO": range(21, 24), "DEU": range(12, 27), "NUM": (5, 6, 9, 15, 18, 19, 27, 28, 29, 30, 35, 36)}
OUT = {"to the speech's main line", "out one level", "out two or more levels", "out of the speech"}


def plain(text: str) -> str:
    """consonants only, no maqaf or punctuation"""
    return "".join(c for c in text if "א" <= c <= "ת" or c == " ")


def tests() -> list[dict]:
    rows = []
    for line in TEST_SET.read_text(encoding="utf-8").splitlines()[1:]:
        verse, opening, expected, src = line.split("\t")
        m = re.match(r"(.+) (\d+):(\d+)$", verse)
        rows.append({"book": BOOKS[m.group(1)], "ch": int(m.group(2)), "v": int(m.group(3)), "verse": verse, "opening": opening,
                     "expected": expected, "from": src})
    return rows


def find(t: dict, segs: list[dict]) -> int | None:
    """the index of the segment the test line means"""
    idx = [i for i, s in enumerate(segs) if s["verse"] == t["v"]]
    if not idx:
        return None
    if t["opening"].startswith("the line after"):
        return idx[0]
    words = plain(re.sub(r"\(.*?\)", "", t["opening"]).split("/")[0]).split()
    hits = [i for i in idx if plain(segs[i]["text"]).replace(" ", "").startswith("".join(words[:2]).replace(" ", ""))]
    if not hits and words:
        hits = [i for i in idx if plain(segs[i]["text"]).replace(" ", "").startswith(words[0])]
    if not hits and words:                        # "וְ" written in the wording but not in the segment, or the other way round
        w = words[0][1:] if words[0].startswith("ו") else "ו" + words[0]
        hits = [i for i in idx if plain(segs[i]["text"]).replace(" ", "").startswith(w)]
    nth = 1 if "second" in t["opening"] else 0
    if "after the speech" in t["opening"] or "after background" in t["opening"]:
        nth = 0
    return hits[nth] if len(hits) > nth else None


def score(clauses_dir: Path) -> list[dict]:
    out = []
    for t in tests():
        f = clauses_dir / t["book"] / f"{t['book']}_{t['ch']:03d}.jsonl"
        segs = [json.loads(line) for line in open(f, encoding="utf-8")]
        i = find(t, segs)
        key = "text_depth_law" if t["ch"] in LAW.get(t["book"], ()) else "text_depth"
        if i is None or i == 0:
            out.append({**t, "found": False, "right": False, "got": None})
            continue
        d, p = segs[i][key], segs[i - 1][key]
        got = "to the margin" if d < p and d == 0 else "out" if d < p else "level" if d == p else "in"
        e = t["expected"]
        right = got == e if e in ("to the margin", "level", "in") else got == "out"
        out.append({**t, "found": True, "right": right, "got": got, "text": segs[i]["text"]})
    return out


def main() -> None:
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "data" / "clause-layout" / "clauses"
    res = score(d)
    for r in res:
        if not r["right"]:
            print(f"miss  {r['verse']:12} {r['opening'][:40]:40} expected {r['expected']:28} got {r['got']}")
    print(f"{sum(r['right'] for r in res)} of {len(res)} right; {sum(not r['found'] for r in res)} not found")


if __name__ == "__main__":
    main()
