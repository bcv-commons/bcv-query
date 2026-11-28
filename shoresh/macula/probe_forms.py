"""Forms an edition never writes, for the made probes: how a wanted form can be had (grammar probes, the gap of the
first probe sets: for most wanted forms no word of the edition has them).

  python -I macula/probe_forms.py rules [--edition heb_scg] [--folds 5]    # built forms: the rules on words held out

Three ways, each less sure than the one before:
  tanakh   a word of the Tanakh with the same prefixes, lexeme and suffixes and the wanted form
  joined   the place's prefixes with a real stem (and its suffixes) of the wanted form
  built    a form made by a rewrite rule from another form of the same word (this file, so far: the rules and their
           measure; without points only)

Built forms. A paradigm is a lexeme (a verb: in one stem) with its cells: the form's features and those of a suffix
on it. Its forms are the letters of the stem part and what follows it in the word, without points, as real words of
the Tanakh and of the edition (forms the Tanakh has) write them. A rule says how one cell's letters become another's:
what goes off the beginning and the end and what is put on, with the letters next to it and the length as the
condition (`עשה` to `עשיתי` is another rule than `אמר` to `אמרתי`). The rule with the longest condition that was seen
at least twice is taken; its sureness is how often it gave the written form among the words it could be used on.

Measure: the paradigms in folds by lexeme; for a held-out paradigm every cell is made from its other cells by rules
learned on the other folds, and compared with what is written (any written spelling counts). No hand check.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sys
import unicodedata
import zlib
from pathlib import Path

import pyarrow.parquet as pq

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from macula import clause_scheme as CS
from macula import probe_diff as PD

MIN_SUPPORT = 2
LEVELS = 4


def letters(text):
    """the text without points, final letters as plain ones (a form's end is not a word's end once a suffix follows)"""
    s = "".join(c for c in unicodedata.normalize("NFD", text or "") if "א" <= c <= "ת")
    return s.translate(str.maketrans("ךםןףץ", "כמנפצ"))


def cell_of(stem, suffix):
    c = (stem["type"], stem.get("person") or "", stem.get("number") or "", stem.get("gender") or "", stem.get("state") or "")
    return c + ((suffix.get("person") or "", suffix.get("number") or "", suffix.get("gender") or "") if suffix else ("", "", ""))


def paradigms(edition):
    """{(class, lexeme, stem): {cell: Counter(letters)}} from the Tanakh and the edition's words the Tanakh has"""
    out = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))

    def add(parts):
        k = next((i for i, p in enumerate(parts) if p["kind"] == "stem"), None)
        if k is None or parts[k]["cls"] not in ("verb", "noun", "adj") or not parts[k]["lexeme"] or not parts[k]["type"]:
            return
        tail = parts[k:]
        if len(tail) > 2 or (len(tail) == 2 and not (tail[1]["cls"] == "pron" and tail[1]["kind"] == "suffix")):
            return
        if parts[k]["type"] == "proper":
            return
        form = "".join(letters(p["text"]) for p in tail)
        if form:
            key = (parts[k]["cls"], CS.strong(parts[k]["lexeme"]).lstrip("0"), parts[k].get("stem") or "")
            out[key][cell_of(parts[k], tail[1] if len(tail) == 2 else None)][form] += 1

    words = collections.defaultdict(list)
    for p in pq.read_table(CS.K1 / "hbo" / "pieces.parquet", columns=["t", "n", "text", "kind", "class", "lexeme", "marks"]).to_pylist():
        m = json.loads(p["marks"] or "{}")
        words[p["t"]].append({"n": p["n"], "text": p["text"], "kind": p["kind"], "cls": p["class"] or "", "lexeme": p["lexeme"] or "",
                              **{f: m.get(f, "") for f in ("type", "stem", "person", "number", "gender", "state")}})
    for ps in words.values():
        add(sorted(ps, key=lambda p: p["n"]))
    n_tanakh = sum(len(c) for c in out.values())
    if edition:
        S = PD.NT(edition)
        for ps in S.parts.values():
            ps = [p for p in ps if p["cls"] != "art"]
            if ps and all(p["known"] for p in ps):
                add(ps)
    return out, n_tanakh


def rule_of(x, y):
    """how x becomes y around their longest common run of letters: (off the front, onto the front, off the end, onto
    the end) and the run"""
    best = (0, 0, 0)
    for i in range(len(x)):
        for j in range(len(y)):
            k = 0
            while i + k < len(x) and j + k < len(y) and x[i + k] == y[j + k]:
                k += 1
            if k > best[0]:
                best = (k, i, j)
    k, i, j = best
    return (x[:i], y[:j], x[i + k:], y[j + k:]), x[i:i + k]


def conds(mid, n):
    """a rule's conditions from the longest to none: the letters at both ends of what stays, and the form's length"""
    return [(mid[:2], mid[-2:], n), (mid[:1], mid[-1:], n), ("", "", n), ("", "", 0)]


def use(change, x):
    off_a, on_a, off_b, on_b = change
    if not x.startswith(off_a) or not x.endswith(off_b) or len(x) < len(off_a) + len(off_b):
        return None, None
    mid = x[len(off_a):len(x) - len(off_b)]
    return on_a + mid + on_b, mid


class Rules:
    def __init__(self, pars):
        self.support = collections.Counter()                         # (pair, level, condition, change) -> paradigms
        self.by_pair = collections.defaultdict(list)                 # (class, stem, cell, cell) -> [(x, the written forms of y)]
        self.changes = collections.defaultdict(set)                  # pair -> changes seen
        for key, cells in pars.items():
            top = {c: f.most_common(1)[0][0] for c, f in cells.items()}
            for a in top:
                for b in top:
                    if a == b:
                        continue
                    pair = (key[0], key[2], a, b)
                    change, mid = rule_of(top[a], top[b])
                    self.by_pair[pair].append((top[a], set(cells[b])))
                    self.changes[pair].add(change)
                    for lvl, c in enumerate(conds(mid, len(top[a]))):
                        self.support[(pair, lvl, c, change)] += 1
        self._right = {}

    def right(self, pair, lvl, c, change):
        """among the pair's words the rule can be used on (its condition holds), the share it gives as written"""
        k = (pair, lvl, c, change)
        if k not in self._right:
            fit = good = 0
            for x, ys in self.by_pair[pair]:
                y, mid = use(change, x)
                if y is not None and conds(mid, len(x))[lvl] == c:
                    fit += 1
                    good += y in ys
            self._right[k] = good / fit if fit else 0.0
        return self._right[k]

    def make(self, cls, stem, a, x, b):
        """cell b's letters from cell a's letters x: (letters, sureness, level, support) or None"""
        pair = (cls, stem, a, b)
        best = None
        for lvl in range(LEVELS):
            cands = []
            for change in self.changes.get(pair, ()):
                y, mid = use(change, x)
                if y is None:
                    continue
                c = conds(mid, len(x))[lvl]
                n = self.support[(pair, lvl, c, change)]
                if n >= MIN_SUPPORT:
                    cands.append((self.right(pair, lvl, c, change), n, y))
            if cands:
                r, n, y = max(cands)
                if best is None or r > best[1]:
                    best = (y, r, lvl, n)
                if r >= 0.95:
                    break
        return best


def cautious(r, n, z=1.64):
    """the lower end of a share r seen on n words (Wilson): a rule right on 2 of 2 is not as sure as one on 40 of 40"""
    return (r + z * z / (2 * n) - z * math.sqrt((r * (1 - r) + z * z / (4 * n)) / n)) / (1 + z * z / n) if n else 0.0


def vote(R, key, cells, top, b):
    """cell b from every other cell of the paradigm: (letters, source cells that give them, the best cautious
    sureness among those, does another source cell give other letters) or None"""
    votes = collections.defaultdict(list)
    for a in cells:
        if a != b:
            g = R.make(key[0], key[2], a, top[a], b)
            if g:
                votes[g[0]].append(cautious(g[1], g[3]))
    if not votes:
        return None
    y = max(votes, key=lambda y: (len(votes[y]), max(votes[y])))
    return y, len(votes[y]), max(votes[y]), len(votes) > 1


KINDS = (("verb: another person", lambda a, b: a[0] == b[0] and a[1] != b[1] and a[5:] == b[5:] == ("", "", "")),
         ("verb: another number", lambda a, b: a[0] == b[0] and a[1] == b[1] and a[2] != b[2] and a[3] == b[3] and a[5:] == b[5:] == ("", "", "")),
         ("verb: another gender", lambda a, b: a[0] == b[0] and a[1:3] == b[1:3] and a[3] != b[3] and a[5:] == b[5:] == ("", "", "")),
         ("verb: another tense", lambda a, b: a[0] != b[0] and a[5:] == b[5:] == ("", "", "")),
         ("a suffix changed", lambda a, b: a[:5] == b[:5] and a[5:] != b[5:] and a[5] and b[5]),
         ("a suffix put on or taken off", lambda a, b: a[:4] == b[:4] and bool(a[5]) != bool(b[5])),
         ("noun: another number", lambda a, b: a[2] != b[2] and a[4] == b[4] and a[5:] == b[5:] == ("", "", "")))


def measure(edition, folds):
    pars, n_tanakh = paradigms(edition)
    cells = sum(len(c) for c in pars.values())
    print(f"paradigms {len(pars):,}, cells {cells:,} (from the Tanakh alone {n_tanakh:,})")
    fold = lambda key: zlib.crc32(repr(key[:2]).encode()) % folds  # noqa: E731
    T = (0.0, 0.8, 0.9, 0.95, 0.99)
    made, right = collections.Counter(), collections.Counter()
    asked = collections.Counter()
    agreed = collections.Counter()
    for f in range(folds):
        R = Rules({k: v for k, v in pars.items() if fold(k) != f})
        for key, cs in pars.items():
            if fold(key) != f or len(cs) < 2:
                continue
            top = {c: fm.most_common(1)[0][0] for c, fm in cs.items()}
            for b in cs:
                v = vote(R, key, cs, top, b)
                if v:
                    for t in (0.0, 0.8, 0.9):
                        if v[2] >= t:
                            for rival in ("any", "none")[:2 - v[3]]:
                                agreed[(min(v[1], 4), rival, t, "made")] += 1
                                agreed[(min(v[1], 4), rival, t, "right")] += v[0] in cs[b]
                got = {a: R.make(key[0], key[2], a, top[a], b) for a in cs if a != b}
                for name, test in KINDS + (("any", lambda a, b: True),):
                    if name.startswith("verb") != (key[0] == "verb") and not name.startswith(("a suffix", "any")):
                        continue
                    src = [a for a in got if test(a, b)]
                    if not src:
                        continue
                    asked[name] += 1
                    best = max((got[a] for a in src if got[a]), key=lambda g: (g[1], g[3]), default=None)
                    if best:
                        for t in T:
                            if best[1] >= t:
                                made[(name, t)] += 1
                                right[(name, t)] += best[0] in cs[b]
    print("a cell made from the paradigm's other cells, by the kind of change (the best rule among the source cells):")
    print("| change | cells asked | " + " | ".join(f"sureness {t:g}+: made, right" for t in T) + " |")
    for name in [k[0] for k in KINDS] + ["any"]:
        print(f"| {name} | {asked[name]:,} | " + " | ".join(
            f"{made[(name, t)]:,}, {right[(name, t)] / max(1, made[(name, t)]):.1%}" for t in T) + " |")

    print("the same cells by how many source cells give the same letters (cautious sureness: the lower end of the rule's share):")
    print("| source cells agreeing | another source says otherwise | " + " | ".join(f"cautious {t:g}+: made, right" for t in (0.0, 0.8, 0.9)) + " |")
    for rival in ("any", "none"):
        for k in (1, 2, 3, 4):
            print(f"| {k}{'+' if k == 4 else ''} | {'may' if rival == 'any' else 'no'} | " + " | ".join(
                f"{agreed[(k, rival, t, 'made')]:,}, {agreed[(k, rival, t, 'right')] / max(1, agreed[(k, rival, t, 'made')]):.1%}"
                for t in (0.0, 0.8, 0.9)) + " |")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=("rules",))
    ap.add_argument("--edition", default="heb_scg")
    ap.add_argument("--folds", type=int, default=5)
    a = ap.parse_args()
    measure(a.edition, a.folds)


if __name__ == "__main__":
    main()
