"""Turn rows of a probe set into Hebrew text, and check the set against the text it was made on.

Stands alone (pyarrow only) and is shipped with the dataset as `resolve.py`. A probe set holds no Hebrew: a clause is
its first and last word, a changed word is a pointer to another word of the same edition. The text comes from the
word table of bcv-commons/hebrew-nt-analysis (`<edition>/words.parquet`, the version PIN.json names).

  python resolve.py WORDS_PARQUET SET_DIR --check                # every clause and made clause against its hash
  python resolve.py WORDS_PARQUET SET_DIR ID [ID ...] [--plain]   # a pair (pp:…), a probe (pr:…) or a clause (cl:…)

SET_DIR is the edition's folder of the set (pairs.parquet, probes.parquet, clauses.parquet). A probe that names a
`clause_above` has as its place that clause followed by its own (a noun with its relative clause).

A word id is `<text>:<book number, 2><chapter, 3><verse, 3><word, 3>`; the word is the row of the word table with that
book, chapter and verse and `i` = word - 1. The edits of a probe, in order: `put` (the donor stands where the word
stood), `add_before`, `add_after`, `drop`, `move_before` (the word goes before the word named as donor).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from pathlib import Path

import pyarrow.parquet as pq


def check(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def plain(text):
    """the text without points: one plain way to strip them (letters and spaces stay)"""
    return "".join(c for c in unicodedata.normalize("NFD", text) if c == " " or "א" <= c <= "ת")


class Text:
    def __init__(self, words_parquet, set_dir):
        self.dir = Path(set_dir)
        pin = json.loads((self.dir.parent / "PIN.json").read_text(encoding="utf-8"))
        self.book = {int(n): b for b, n in pin["books"].items()}
        self.word = {}
        for r in pq.read_table(words_parquet, columns=["book", "chapter", "verse", "i", "part", "word", "class"]).to_pylist():
            if r["class"] != "verse-number":
                self.word.setdefault((r["book"], r["chapter"], r["verse"], r["i"]), r["word"])
        self.clauses = {r["clause"]: r for r in pq.read_table(self.dir / "clauses.parquet").to_pylist()}

    def key(self, wid):
        d = wid.split(":")[1]
        return self.book[int(d[:2])], int(d[2:5]), int(d[5:8]), int(d[8:]) - 1

    def ids(self, cid):
        c = self.clauses[cid]
        head = c["first"][:-3]
        return [f"{head}{w:03d}" for w in range(int(c["first"][-3:]), int(c["last"][-3:]) + 1) if self.key(f"{head}{w:03d}") in self.word]

    def clause(self, cid):
        return " ".join(self.word[self.key(w)] for w in self.ids(cid))

    def place_ids(self, probe):
        """a probe's place: its clause, after the clause above where the probe names one (a relative unit)"""
        return (self.ids(probe["clause_above"]) if probe.get("clause_above") else []) + self.ids(probe["clause"])

    def place(self, probe):
        return " ".join(self.word[self.key(w)] for w in self.place_ids(probe))

    def made(self, probe):
        seq = [(w, w) for w in self.place_ids(probe)]                 # (the place, the word standing there)
        for op, at, frm in zip(probe["edit_op"], probe["edit_at"], probe["edit_from"]):
            i = next(i for i, (a, _) in enumerate(seq) if a == at)
            if op == "put":
                seq[i] = (at, frm)
            elif op == "drop":
                del seq[i]
            elif op in ("add_before", "add_after"):
                seq.insert(i + (op == "add_after"), (None, frm))
            elif op == "move_before":
                x = seq.pop(i)
                seq.insert(next(j for j, (a, _) in enumerate(seq) if a == frm), x)
        return " ".join(self.word[self.key(w)] for _, w in seq)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("words")
    ap.add_argument("set_dir")
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--plain", action="store_true")
    a = ap.parse_args()
    T = Text(a.words, a.set_dir)
    show = plain if a.plain else (lambda x: x)
    if a.check:
        bad = sum(1 for cid, c in T.clauses.items() if check(T.clause(cid)) != c["check"])
        probes = pq.read_table(T.dir / "probes.parquet").to_pylist()
        bad_made = sum(1 for r in probes if check(T.made(r)) != r["made_check"] or check(T.place(r)) != r["check"])
        print(f"clauses {len(T.clauses):,}, not matching their hash {bad:,}; made clauses {len(probes):,}, not matching {bad_made:,}")
        raise SystemExit(1 if bad or bad_made else 0)
    pairs = probes = None
    for x in a.ids:
        if x.startswith("cl:"):
            print(x, "|", show(T.clause(x)))
        elif x.startswith("pp:"):
            pairs = pairs or {r["pair"]: r for r in pq.read_table(T.dir / "pairs.parquet").to_pylist()}
            r = pairs[x]
            print(f"{x} | {show(T.clause(r['a']))} | {show(T.clause(r['b']))} | {r['dimension']}: {r['from'] or '-'} > {r['to'] or '-'}")
        elif x.startswith("pr:"):
            probes = probes or {r["probe"]: r for r in pq.read_table(T.dir / "probes.parquet").to_pylist()}
            r = probes[x]
            print(f"{x} | {show(T.place(r))} | {show(T.made(r))} | {r['change']}")
        else:
            raise SystemExit(f"{x}: not a clause, pair or probe id")


if __name__ == "__main__":
    main()
