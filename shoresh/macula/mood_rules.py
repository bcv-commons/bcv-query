"""Moods per passage by rule, from evidence already in our data (no model). Internal for now: candidates, scores, hard cases.

    cd shoresh && .venv/bin/python -m macula.mood_rules --facts <passage-facts build folder> [--books PSA MRK] [--out <dir>]

Units: the Masoretic paragraphs (sc.pe / sc.sa) of a Hebrew book, Nestle 1904's (sc.np) of a Greek one; a paragraph of more
than 8 verses in windows of at most five. Evidence per unit, each with its word keys:
  - emotion words: the meaning domain UBS gives the word in its place (SDBH for Hebrew, Louw-Nida 25 and 88 for Greek), by the
    fixed table DOMAIN_MOOD; weight 1 per word;
  - cues (passage-facts `cue`): woe and a named lament count toward grief, a blessing or hallelujah toward joy; weight 2;
  - speech moods (passage-facts `mood`, b.rule, from Glyssen deliveries): weight 2.
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

from macula import build_passage_facts as pf, ubs

# SDBH lexical domain (Hebrew) -> mood
SDBH_MOOD = {"Afraid": "fear", "Angry": "anger", "Rejoice": "joy", "Grieve": "grief", "Shame": "shame", "Confident": "confidence",
             "Despise": "contempt", "Relief": "relief", "Merciful": "compassion", "Respect": "reverence",
             # added on the odd psalms (lift 3-8 against Scriptura), tested on the even ones
             "Guilty": "guilt", "Sin": "guilt", "Chastise": "guilt", "Praise": "joy", "Sing": "joy"}
# Louw-Nida subdomain (Greek) -> mood
LN_MOOD = {"025004": "hope", "025009": "gratitude", "025011": "joy", "025012": "grief", "025013": "reassurance",
           "025014": "courage", "025017": "abhorrence", "025018": "shame", "025020": "amazement", "025021": "distress",
           "025022": "fear", "025023": "sadness", "025024": "discouragement", "088024": "anger", "088025": "contempt",
           "088027": "pride"}
# a negator up to three words before an emotion word drops it ("he refused to be comforted", "he did not believe them")
NEGATORS = {"3808", "0408", "0369", "1077", "3756", "3361", "3762", "3367"}   # לֹא אַל אַיִן בַּל, οὐ μή οὐδείς μηδείς
CUE_MOOD = {"rg.woe": "grief", "rg.lament_named": "grief", "rg.lament_open": "grief", "rg.blessing": "joy", "rg.hallelujah": "joy"}

# families for the "near" score (feedback_yardstick_near_miss) and the two sides for the status
FAMILY = {
    "fear": "fear", "terror": "fear", "anxiety": "fear", "alarm": "fear", "dismay": "fear",
    "grief": "grief", "sadness": "grief", "misery": "grief", "abandonment": "grief", "discouragement": "grief",
    "joy": "joy", "triumph": "joy", "enthusiasm": "joy", "admiration": "joy", "passion": "joy", "gratitude": "joy", "well_being": "joy",
    "confidence": "trust", "security": "trust", "hope": "trust", "peace": "trust", "calm": "trust", "reassurance": "trust",
    "relief": "trust", "expectation": "trust", "dependence": "trust", "courage": "trust", "determination": "trust",
    "awe": "awe", "reverence": "awe", "amazement": "awe", "solemnity": "awe", "pensiveness": "awe", "contemplation": "awe",
    "humility": "awe",
    "anger": "anger", "contempt": "anger", "abhorrence": "anger", "frustration": "anger", "impatience": "anger", "pride": "anger",
    "guilt": "guilt", "shame": "guilt", "remorse": "guilt", "humiliation": "guilt",
    "distress": "distress", "desperation": "distress", "vulnerability": "distress", "confusion": "distress",
    "compassion": "trust", "disgust": "anger", "zeal": "joy",
}
PAINFUL = {"fear", "grief", "anger", "guilt", "distress"}
PLEASANT = {"joy", "trust"}


def side(mood: str) -> str:
    f = FAMILY.get(mood, mood)
    return "painful" if f in PAINFUL else "pleasant" if f in PLEASANT else "neutral"


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
    ev: dict[int, list[tuple[str, int, str]]] = collections.defaultdict(list)   # word index -> (mood, weight, why)
    strong = dict(sqlite3.connect(pf.SPINE).execute("SELECT key, strong FROM macula_words WHERE book=?", (book,)))
    negated = {i for i, k in enumerate(keys) if any(strong.get(keys[j]) in NEGATORS for j in range(max(0, i - 3), i))}
    if bk.hebrew:
        for k, d in ubs.hebrew(book).items():
            if k not in pos:
                continue
            w = k
            if pos[w] in negated:
                continue
            for dom in d.split("|"):
                if dom.strip() in SDBH_MOOD:
                    ev[pos[w]].append((SDBH_MOOD[dom.strip()], 1, "sdbh:" + dom.strip()))
                    break
    else:
        for k, (_, code) in ubs.greek().items():
            if k in pos and code in LN_MOOD and pos[k] not in negated:
                ev[pos[k]].append((LN_MOOD[code], 1, "ln:" + code))
    for f in facts:
        if f["first"] not in pos:
            continue
        if f["kind"] == "cue" and f["value"] in CUE_MOOD:
            ev[pos[f["first"]]].append((CUE_MOOD[f["value"]], 2, f["value"]))
        elif f["kind"] == "mood" and f["basis"] == "b.rule":
            ev[pos[f["first"]]].append((f["value"][3:], 2, "glyssen:" + f["id"]))
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


def score(rows: list[dict], folder: Path, psalms=None) -> dict:
    """Against Scriptura (Psalms, held out): per verse with a Scriptura mood, is it among the unit's moods (exact), or its family
    (near)? Units with status none count as misses, so the figure shows the coverage too."""
    facts = _facts(folder, "PSA")
    bk = pf.Book("PSA")
    unit_at = {}
    for r in rows:
        if r["book"] == "PSA":
            for i in range(bk.pos[r["first"]], bk.pos[r["last"]] + 1):
                unit_at[bk.cv(bk.keys[i])] = r
    n = exact = near = covered = 0
    for f in facts:
        if f["kind"] != "mood" or f["basis"] != "b.source":
            continue
        m = f["value"][3:]
        if psalms is not None and bk.cv(f["first"])[0] not in psalms:
            continue
        for i in range(bk.pos[f["first"]], bk.pos[f["last"]] + 1, 1):
            v = bk.cv(bk.keys[i])
            if i > bk.pos[f["first"]] and v == bk.cv(bk.keys[i - 1]):
                continue
            r = unit_at.get(v)
            n += 1
            if not r or r["status"] == "none":
                continue
            covered += 1
            exact += m in r["moods"]
            near += FAMILY.get(m, m) in {FAMILY.get(x, x) for x in r["moods"]}
    return {"verses": n, "covered": covered, "exact": round(exact / max(1, n), 3), "near": round(near / max(1, n), 3),
            "near_when_covered": round(near / max(1, covered), 3)}


def glyssen_score(rows: list[dict], folder: Path) -> dict:
    """Leave-one-out against the Glyssen speech moods: is the speech's mood family among the unit's moods counted without
    that speech's own evidence?"""
    n = near = 0
    for r in rows:
        own = [(m, k) for m, ev in r["evidence"].items() for k, why in ev if why.startswith("glyssen:")]
        for m, _ in own:
            rest = collections.Counter({x: w for x, w in r["weights"].items()})
            rest[m] -= 2
            moods = [x for x, w in rest.most_common(3) if w > 0]
            n += 1
            near += FAMILY.get(m, m) in {FAMILY.get(x, x) for x in moods}
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
        print("Scriptura (Psalms):", score(rows, a.facts))
    print("Glyssen (leave-one-out):", glyssen_score(rows, a.facts))
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        with (a.out / "mood_units.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
