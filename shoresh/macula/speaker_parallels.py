"""Check the speaker layer against itself: where two passages tell the same thing (Samuel-Kings and Chronicles, Isa 36-39 and
2 Kgs 18-20, Ps 18 and 2 Sam 22, Ps 96 and 1 Chr 16, Jer 52 and 2 Kgs 24-25), the same words should stand at the same level and
be spoken by the same speaker, unless the Hebrew differs.

Passage pairs come from build_parallel_substitutions.passage_pairs (BSB section references, public domain). Each verse of one
passage is aligned with the most similar verse of the other (shared Strong's numbers), and the words of an aligned verse pair are
matched in order (difflib on Strong's numbers). A word's level counts a frame as one level, so that a psalm (a frame) and the same
psalm quoted in a narrative (a quotation) compare.

Writes macula/data/speaker-layer/parallels.tsv (one row per stretch of matched words whose levels or speakers differ) and prints
the agreement.

    python -m macula.speaker_parallels
"""
from __future__ import annotations

import collections
import csv
import difflib
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import trees_macula  # noqa: E402
from macula.build_parallel_substitutions import passage_pairs  # noqa: E402

LAYOUT = HERE / "data" / "clause-layout" / "clauses"
LAYER = HERE / "data" / "speaker-layer"
MIN_SIM = 0.35


def main() -> int:
    con = sqlite3.connect(f"file:{trees_macula.trees_path()}?mode=ro", uri=True)
    strong = {k: "".join(c for c in (s or "") if c.isdigit()).lstrip("0") for k, s in
              con.execute("SELECT key, strong FROM words WHERE corpus='hbo' AND inserted=0")}
    word: dict = {}                                   # word key -> (level with the frame counted, speaker, quotation, segment text)
    verse_words: dict = collections.defaultdict(list)
    for f in sorted(LAYER.glob("segments/*.tsv")):
        book = f.stem
        rows = {(int(r["chapter"]), int(r["seg"])): r for r in csv.DictReader(open(f, encoding="utf-8"), delimiter="\t")}
        for jf in sorted((LAYOUT / book).glob("*.jsonl")):
            for line in open(jf, encoding="utf-8"):
                c = json.loads(line)
                r = rows[(c["chapter"], c["seg"])]
                eff = int(r["level"]) + (1 if r["frame"] else 0)
                for w in c["words"]:
                    word[w] = (eff, r["speaker"] or (r["frame"] if int(r["level"]) == 0 else ""), r["quotation"], c["text"])
                    verse_words[(book, c["chapter"], c["verse"])].append(w)

    def sim(a: list, b: list) -> float:
        sa, sb = collections.Counter(strong[w] for w in a if strong.get(w)), collections.Counter(strong[w] for w in b if strong.get(w))
        inter, union = sum((sa & sb).values()), sum((sa | sb).values())
        return inter / union if union else 0.0

    out, seen = [], set()
    st = collections.Counter()
    for ba, sa, ea, bb, sb, eb in passage_pairs():
        A = [k for k in verse_words if k[0] == ba and sa <= (k[1], k[2]) <= ea]
        B = [k for k in verse_words if k[0] == bb and sb <= (k[1], k[2]) <= eb]
        for va in A:
            if not B:
                break
            vb, score = max(((x, sim(verse_words[va], verse_words[x])) for x in B), key=lambda t: t[1])
            if score < MIN_SIM or tuple(sorted((va, vb))) in seen:
                continue
            seen.add(tuple(sorted((va, vb))))
            wa, wb = verse_words[va], verse_words[vb]
            sm = difflib.SequenceMatcher(a=[strong.get(w, "") for w in wa], b=[strong.get(w, "") for w in wb], autojunk=False)
            for blk in sm.get_matching_blocks():
                run = None
                for k in range(blk.size):
                    x, y = word[wa[blk.a + k]], word[wb[blk.b + k]]
                    st["matched words"] += 1
                    same_level, same_speaker = x[0] == y[0], (x[1] == y[1] or not x[1] or not y[1] or x[1].startswith("(") or y[1].startswith("("))
                    st["same level"] += same_level
                    st["same speaker"] += same_speaker
                    if same_level and same_speaker:
                        run = None
                        continue
                    key = (x[0], y[0], x[1], y[1])
                    if run is None or run["key"] != key:
                        run = {"key": key, "a": f"{va[0]} {va[1]}:{va[2]}", "b": f"{vb[0]} {vb[1]}:{vb[2]}", "words": 0,
                               "text_a": x[3], "text_b": y[3]}
                        out.append(run)
                    run["words"] += 1
    with open(LAYER / "parallels.tsv", "w", encoding="utf-8") as fh:
        fh.write("passage_a\tpassage_b\twords\tlevel_a\tlevel_b\tspeaker_a\tspeaker_b\ttext_a\ttext_b\n")
        for r in sorted(out, key=lambda r: -r["words"]):
            la, lb, pa, pb = r["key"]
            fh.write(f"{r['a']}\t{r['b']}\t{r['words']}\t{la}\t{lb}\t{pa}\t{pb}\t{r['text_a']}\t{r['text_b']}\n")
    n = st["matched words"]
    print(f"parallel passages: {len(seen)} verse pairs, {n} matched words; same level {100 * st['same level'] / max(1, n):.1f}%,"
          f" same speaker {100 * st['same speaker'] / max(1, n):.1f}%; {len(out)} differing stretches -> {LAYER / 'parallels.tsv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
