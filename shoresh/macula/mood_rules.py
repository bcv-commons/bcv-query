"""Moods per passage by rule, from evidence already in our data (no model). Internal for now: candidates, scores, hard cases.

    cd shoresh && .venv/bin/python -m macula.mood_rules --facts <passage-facts build folder> [--books PSA MRK] [--out <dir>]

Units: the Masoretic paragraphs (sc.pe / sc.sa) of a Hebrew book, Nestle 1904's (sc.np) of a Greek one; a paragraph of more
than 8 verses in windows of at most five. Evidence per unit, each with its word keys:
  - feeling words: the words that mark a mood family (macula/mood_families.py: SDBH and Louw-Nida domains, lemmas by Strong's
    number); weight 1 per word; cues (woe, a named lament, blessing, hallelujah): weight 2;
  - speech moods (passage-facts `mood` from Glyssen deliveries, themselves marked by the text): weight 2.
Each unit gets a status:
  - none     nothing marks a feeling (narration, law, lists): no mood, no model;
  - decided  one mood carries at least weight 2 and the unit's evidence is at least 75% on one side (pleasant / painful);
  - thin     weight 1 in all: one emotion word, kept as a low-confidence candidate;
  - mixed    both sides strong: a hard case (the short list a model may see later, only after the user's go).
Scriptura's psalm moods (b.source) are never evidence here; they are the yardstick (score()).
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
from pathlib import Path

from macula import build_passage_facts as pf, mood_families as mf, scriptura

# the mood families and the words that mark them: macula/mood_families.py (resources/passage_facts/mood_families.tsv), from v0.3.1


def side(fid: str) -> str:
    return mf.FAMILIES[fid]["side"] if fid in mf.FAMILIES else "neutral"


def _facts(folder: Path, book: str) -> list[dict]:
    p = folder / f"{book}.jsonl"
    if not p.exists():
        p = folder / "data" / f"{book}.jsonl"
    return [json.loads(l) for l in p.open(encoding="utf-8")]


def _windows(bk, a: int, z: int, size: int = 5) -> list[tuple[int, int]]:
    """Split a span into runs of at most `size` verses, never across a chapter."""
    out, cur, prev = [], [], None
    for i in range(a, z + 1):
        v = bk.cv(bk.keys[i])
        if v != prev:
            if cur and (v[0] != prev[0] or len({bk.cv(bk.keys[j]) for j in cur}) == size):
                out.append((cur[0], cur[-1]))
                cur = []
            prev = v
        cur.append(i)
    if cur:
        out.append((cur[0], cur[-1]))
    return out


def units(bk, facts: list[dict], keys: list[str], pos: dict[str, int], longest: int = 8) -> list[tuple[int, int]]:
    """Word index spans. Hebrew: from each paragraph mark to the next (sc.pe / sc.sa carry the last word before the break); a
    paragraph of more than `longest` verses, or one that crosses a chapter, in windows of at most five verses. Greek: Nestle
    1904's paragraphs (sc.np), the same way; a book without them in windows of five verses inside a chapter."""
    ends = sorted({pos[f["last"]] for f in facts if f["kind"] == "section" and f["value"] in ("sc.pe", "sc.sa", "sc.np") and f["last"] in pos})
    spans, a = [], 0
    for e in (ends + [len(keys) - 1]) if ends else []:
        if e >= a:
            spans.append((a, e))
            a = e + 1
    if not spans:
        return _windows(bk, 0, len(keys) - 1)
    out = []
    for a, z in spans:
        vs = {bk.cv(keys[i]) for i in range(a, z + 1)}
        out += [(a, z)] if len(vs) <= longest and len({c for c, _ in vs}) == 1 else _windows(bk, a, z)
    return out


def run(folder: Path, book: str) -> list[dict]:
    bk = pf.Book(book)
    keys, pos = bk.keys, bk.pos
    facts = _facts(folder, book)
    ev: dict[int, list[tuple[str, int, str]]] = collections.defaultdict(list)   # word index -> (family, weight, why)
    cues = {pos[f["first"]]: f["value"] for f in facts if f["kind"] == "cue" and f["first"] in pos}
    for i, ms in mf.word_marks(book, bk, cues).items():
        for fam, why in ms:
            ev[i].append((fam, 2 if why.startswith("rg.") else 1, why))
    for f in facts:
        if f["kind"] == "mood" and "glyssen" in f["src"] and f["first"] in pos:
            ev[pos[f["first"]]].append((f["value"], 2, "glyssen:" + f["id"]))
    out = []
    for a, z in units(bk, facts, keys, pos):
        weight, why = collections.Counter(), collections.defaultdict(list)
        for i in range(a, z + 1):
            for m, wt, r in ev.get(i, []):
                weight[m] += wt
                why[m].append((keys[i], r))
        total = sum(weight.values())
        sides = collections.Counter()
        for m, wt in weight.items():
            sides[side(m)] += wt
        lean = max(sides["painful"], sides["pleasant"]) / max(1, sides["painful"] + sides["pleasant"])
        top = weight.most_common(3)
        status = ("none" if not total else "thin" if total == 1 else
                  "decided" if top[0][1] >= 2 and lean >= 0.75 else "mixed")
        out.append({"book": book, "first": keys[a], "last": keys[z], "ref": bk.ref(keys[a], keys[z]), "status": status,
                    "moods": [m for m, _ in top], "weights": dict(weight), "sides": dict(sides),
                    "evidence": {m: why[m] for m, _ in top}})
    return out


def score(rows: list[dict], psalms=None) -> dict:
    """Against Scriptura (Psalms, the yardstick, never evidence): per verse with a Scriptura mood (its word mapped to a family by
    mood_families.tsv), is that family among the unit's families? Units with status none count as misses."""
    bk = pf.Book("PSA")
    unit_at = {}
    for r in rows:
        if r["book"] == "PSA":
            for i in range(bk.pos[r["first"]], bk.pos[r["last"]] + 1):
                unit_at[bk.cv(bk.keys[i])] = r
    last = collections.Counter()
    for c, v in bk.verses:
        last[c] = max(last[c], v)
    n = near = covered = 0
    for p in range(1, 151):
        if psalms is not None and p not in psalms:
            continue
        r = scriptura.read(p)
        for a, nxt, labels in (r or {}).get("moods", []):
            fams = {mf.source_family(x) for x in scriptura.mood_labels(labels)} - {None}
            end = (nxt[0] - 1 if not nxt[1] or nxt[1] == "a" else nxt[0]) if nxt else last[p]
            for v in range(a[0], max(a[0], end) + 1):
                u = unit_at.get((p, v))
                for fam in fams:
                    n += 1
                    if u and u["status"] != "none":
                        covered += 1
                        near += fam in u["moods"]
    return {"verses": n, "covered": covered, "near": round(near / max(1, n), 3), "near_when_covered": round(near / max(1, covered), 3)}


def glyssen_score(rows: list[dict]) -> dict:
    """Leave-one-out against the Glyssen speech moods: is the speech's family among the unit's families counted without that
    speech's own evidence?"""
    n = near = 0
    for r in rows:
        own = [(m, k) for m, ev in r["evidence"].items() for k, why in ev if why.startswith("glyssen:")]
        for m, _ in own:
            rest = collections.Counter({x: w for x, w in r["weights"].items()})
            rest[m] -= 2
            moods = [x for x, w in rest.most_common(3) if w > 0]
            n += 1
            near += m in moods
    return {"speeches": n, "near": round(near / max(1, n), 3)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--facts", type=Path, required=True)
    ap.add_argument("--books", nargs="*")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    books = a.books or sorted(p.stem for p in (a.facts.glob("*.jsonl") or (a.facts / "data").glob("*.jsonl")))
    rows = [r for b in books for r in run(a.facts, b)]
    st = collections.Counter(r["status"] for r in rows)
    print("units", len(rows), dict(st))
    for b in books:
        c = collections.Counter(r["status"] for r in rows if r["book"] == b)
        print(f"  {b}: {dict(c)}")
    if "PSA" in books:
        print("Scriptura (Psalms):", score(rows), "odd:", score(rows, set(range(1, 151, 2))), "even:", score(rows, set(range(2, 151, 2))))
    print("Glyssen (leave-one-out):", glyssen_score(rows))
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        with (a.out / "mood_units.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
