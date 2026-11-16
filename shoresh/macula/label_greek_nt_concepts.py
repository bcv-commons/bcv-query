"""The items of a model labelling of every Greek New Testament content word with a Hebrew concept (the pilot: pilot_greek_nt_concepts).

    python -m macula.label_greek_nt_concepts --items
    python -m macula.label_greek_nt_concepts --build FILE      FILE = Jev's answers, one line per call: {"id", "choice": "c<n>", "confidence"}

--items writes, under macula/data/greek-nt-concepts/labelling (local, nothing here is released):
  items.jsonl        one row per word of build_greek_nt_concepts' words.parquet: its set, its Hebrew lexemes, its inventory in the order shown
  jev_items.jsonl    the words with more than one concept as calls for Jev (TypeSafe System One: state, a choice), in the pilot's form

--build writes words.parquet (one row per word: greek_id, greek_strong, greek_lemma, set, concept, hebrew_strong of the concept, n_concepts,
confidence, none, labeller: `jev`, or `one concept` for a word whose inventory has one, which no model read) and report.json (counts by
set and confidence; on the quoted words, the share with the concept of the Tanakh word).

Two sets, told apart in every later figure:
  hebrew-nt     a Hebrew New Testament renders the word by a lexeme that has concepts: the inventory is the concepts of the lexeme(s) of
                both editions (the pilot's items; a word of the pilot has the same call here)
  septuagint    no such lexeme: the inventory is the concepts the Septuagint renders by this Greek lexeme, the ten with most occurrences
                (build_greek_nt_concepts' candidates). Not piloted; the right concept may be outside the ten and many of these words
                are names, so these calls have one more choice, "none of the concepts".
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
from macula import build_greek_nt_concepts as g
from macula import pilot_greek_nt_concepts as p

OUT = g.OUT / "labelling"
JEV_LXX = ("The occurrence is a word of the Greek New Testament (between ⟦ and ⟧ in its verse). The concepts are concepts of Hebrew lexemes "
           "that the Septuagint renders by this Greek word. Which of the concepts does this occurrence express? Choose exactly one; choose the "
           "last one if none of the concepts fits.")


def build_items(folder: Path) -> list[dict]:
    import pyarrow.parquet as pq
    con = g.Concepts(folder)
    of, hebrew = p.lexemes(con)
    word, _ = p.verses()
    cands = collections.defaultdict(list)
    for r in pq.read_table(g.OUT / "candidates.parquet").to_pylist():
        cands[r["greek_id"]].append(r["concept"])
    items = []
    for r in pq.read_table(g.OUT / "words.parquet").to_pylist():
        it = {"id": r["greek_id"], "ref": word[r["greek_id"]][0], "greek_strong": r["greek_strong"], "lemma": r["greek_lemma"],
              "morph": word[r["greek_id"]][1], "basis": r["basis"], "tanakh": r["tanakh"]}
        hs = sorted(hebrew[r["greek_id"]]) if r["greek_id"] in hebrew else []
        if hs:
            it.update({"set": "hebrew-nt", "hebrew": hs, "inventory": p.inventory((c for h in hs for c in of[h]), " ".join(hs))})
        else:
            inv = p.inventory(cands[r["greek_id"]], r["greek_strong"])
            it.update({"set": "septuagint", "hebrew": sorted({con.lexeme[c] for c in inv}), "inventory": inv, "instructions": JEV_LXX, "none": True})
        items.append(it)
    return items


def build(folder: Path, answers: Path) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq
    con = g.Concepts(folder)
    items = [json.loads(x) for x in (OUT / "items.jsonl").read_text(encoding="utf-8").splitlines()]
    jev = p.load_jev(answers, items)
    rows, rep = [], {"concepts": f"bcv-commons/hebrew-word-concepts-model@{g.REVISION}", "labeller": "jev-latest (TypeSafe System One), one run",
                     "answers": str(answers), "words": len(items), "sets": {}}
    for it in items:
        a = jev.get(it["id"])
        if len(it["inventory"]) == 1 and not a:
            a = {"concept": it["inventory"][0], "confidence": None, "one": True}
        if not a:
            continue
        c = a["concept"]
        rows.append({"greek_id": it["id"], "greek_strong": it["greek_strong"], "greek_lemma": it["lemma"], "set": it["set"], "concept": c,
                     "hebrew_strong": con.lexeme[c] if c else "", "n_concepts": len(it["inventory"]),
                     "confidence": None if a.get("one") else float(a["confidence"] or 0), "none": not c, "labeller": "one concept" if a.get("one") else "jev"})
    by = {r["greek_id"]: r for r in rows}
    for name in ("hebrew-nt", "septuagint"):
        own = [it for it in items if it["set"] == name]
        got = [by[it["id"]] for it in own if it["id"] in by]
        read = [r for r in got if r["labeller"] == "jev"]
        rep["sets"][name] = {"words": len(own), "one concept (no call)": sum(r["labeller"] == "one concept" for r in got), "answered by jev": len(read),
                             "no answer": len(own) - len(got), "none of the concepts": sum(r["none"] for r in read),
                             "confidence >= 0.9": sum(r["confidence"] >= 0.9 for r in read), "confidence >= 0.8": sum(r["confidence"] >= 0.8 for r in read),
                             "confidence >= 0.8 with a concept": sum(r["confidence"] >= 0.8 and not r["none"] for r in read)}
    quoted = [(by[it["id"]], con.label[it["tanakh"]]) for it in items if it["tanakh"] and it["id"] in by and by[it["id"]]["labeller"] == "jev"]
    rep["quoted words"] = {"words": len(quoted), "same concept": p.share(sum(r["concept"] == gold for r, gold in quoted), len(quoted))}
    for lo, hi in ((0.9, 2), (0.8, 0.9), (0.6, 0.8), (0, 0.6)):
        sub = [(r, gold) for r, gold in quoted if lo <= r["confidence"] < hi]
        rep["quoted words"][f"confidence {lo} to {hi}" if hi < 2 else f"confidence >= {lo}"] = {"words": len(sub), "same concept": p.share(sum(r["concept"] == gold for r, gold in sub), len(sub))}
    pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema(
        [("greek_id", pa.string()), ("greek_strong", pa.string()), ("greek_lemma", pa.string()), ("set", pa.string()), ("concept", pa.string()),
         ("hebrew_strong", pa.string()), ("n_concepts", pa.int16()), ("confidence", pa.float32()), ("none", pa.bool_()), ("labeller", pa.string())])),
        OUT / "words.parquet", compression="zstd")
    (OUT / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return rep


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--concepts", type=Path, default=g.CONCEPTS)
    ap.add_argument("--items", action="store_true")
    ap.add_argument("--build", type=Path, metavar="FILE", help="Jev's answers")
    a = ap.parse_args()
    if a.items:
        OUT.mkdir(parents=True, exist_ok=True)
        items = build_items(a.concepts)
        (OUT / "items.jsonl").write_text("".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items), encoding="utf-8")
        rows = p.jev_items(items, a.concepts)
        (OUT / "jev_items.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        n = collections.Counter((it["set"], len(it["inventory"]) > 1) for it in items)
        print(f"[label] {len(items):,} words, {len(rows):,} calls for Jev -> {OUT}: " + ", ".join(f"{s} {'more than one' if m else 'one'} concept {v:,}"
                                                                                                    for (s, m), v in sorted(n.items())))
    if a.build:
        print(json.dumps(build(a.concepts, a.build), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
