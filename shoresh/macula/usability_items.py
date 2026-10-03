#!/usr/bin/env python3
"""Frozen test items for the judged part of the usability scorecard.

Two tasks, generated identically for every provider (macula.domain_providers):

  intrusion  Is a group a coherent set? Up to 4 served members of one group plus 1 intruder (a content
             word of the same part of speech and frequency band, with no row in that group). Shown as
             Hebrew lemmas only. The judge picks the odd one out. Chance = 1 / number of words.
  labelfit   Is the label useful where the client sees it? A Hebrew verse from a held-out book with one
             word marked, and four labels: the one the provider serves for that word and three labels of
             other groups of the same provider. Chance = 1/4. Tokens whose own word is the label's
             exemplar are skipped (that would be a giveaway). Distractor groups are drawn in proportion to
             their token mass, the same distribution the served label follows; drawing them uniformly made
             label breadth a cue (the random control scored 36% instead of 25%, 2026-10-02 pilot).

Item ids end in a hash of the item's content, so a changed item never reuses an old judgment.

Splits: intrusion items are dev or test by a hash of the group's exemplar Strong's (stable across cluster
rebuilds); labelfit items by a hash of the verse reference. Candidates are tuned on dev only; test is
scored once. Item files are hashed into a manifest so a locked test set can be verified.

The gold file holds hand-made items with unambiguous answers; each judge must score >= 90% on it before
its scores count (usability_judge --gold).

  cd shoresh && .venv/bin/python3 -m macula.usability_items
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

from macula.domain_providers import OUT as PROVIDERS_DIR, SPINE_DB, lemma_of, load_provider, token_counts

HERE = Path(__file__).resolve().parent
ITEMS = HERE / "data" / "usability" / "items"
SEEDS = (13, 17, 23, 29, 31)
PROVIDERS = ("P0", "P1", "P2", "PR-P0", "PR-P2", "P1nb", "P2nb", "PR-P2nb", "A1", "A2", "P2nbmz")
N_GROUPS = 200
N_TOKENS = 300
MAX_MEMBERS = 4
MIN_MEMBERS = 3
SPLIT_SEED = 13                        # intrinsic_yardstick.book_split seed that defines held-out books

_ACCENTS = re.compile(r"[֑-ֽ֯⁠]")    # cantillation, meteg, word joiner


def with_content_id(item: dict) -> dict:
    """Append a short hash of everything the judge sees plus the answer key to the item id."""
    shown = {k: item.get(k) for k in ("words", "verse", "options", "answer")}
    h = hashlib.sha1(json.dumps(shown, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:8]
    return {**item, "id": f"{item['id']}-{h}"}


def split_of(key: str) -> str:
    return "dev" if int(hashlib.sha1(key.encode()).hexdigest(), 16) % 2 == 0 else "test"


def excluded_strongs() -> set[str]:
    from macula.build_semantic_neighbors import non_content_strongs, proper_strongs
    return proper_strongs() | non_content_strongs()


def pos_of() -> dict[str, str]:
    """H#### -> majority part-of-speech letter of the head morph segment (V, N, A, ...)."""
    db = sqlite3.connect(f"file:{SPINE_DB}?mode=ro", uri=True)
    ct: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for strong, morph in db.execute(
            "SELECT strong, morph FROM spine_words WHERE strong IS NOT NULL "
            "AND (morph LIKE 'He,%' OR morph LIKE 'Ar,%')"):
        head = morph.split(",", 1)[1].split(":")[-1] if "," in morph else ""
        if head:
            ct[f"H{int(strong):04d}"][head[0]] += 1
    return {s: c.most_common(1)[0][0] for s, c in ct.items()}


def bucket_of(weights: dict[str, int], n_buckets: int = 20) -> dict[str, int]:
    ranked = sorted(weights, key=lambda s: (-weights[s], s))
    return {s: min(i * n_buckets // max(len(ranked), 1), n_buckets - 1) for i, s in enumerate(ranked)}


# ---------- intrusion ----------

def intrusion_items(provider: str, seed: int, ctx: dict) -> list[dict]:
    rows, groups = load_provider(provider, PROVIDERS_DIR)
    excluded, counts, lemmas, pos, pool_bucket = (ctx["excluded"], ctx["counts"], ctx["lemmas"],
                                                  ctx["pos"], ctx["pool_bucket"])
    members: dict[str, list[str]] = collections.defaultdict(list)
    in_group: dict[str, set[str]] = collections.defaultdict(set)
    for s, _a, g, _sh, sv in rows:
        in_group[g].add(s)
        if sv and s not in excluded and s in lemmas and s in pos:
            members[g].append(s)
    eligible = sorted(g for g, m in members.items() if len(m) >= MIN_MEMBERS)

    by_split: dict[str, list[str]] = collections.defaultdict(list)
    for g in eligible:
        key = groups.get(g, {}).get("label_strong") or g
        by_split[split_of(f"{provider}:{key}" if not groups.get(g, {}).get("label_strong") else key)].append(g)

    pool_by: dict[tuple, list[str]] = collections.defaultdict(list)
    for s, b in pool_bucket.items():
        pool_by[(pos[s], b)].append(s)

    rng = random.Random(f"intrusion-{provider}-{seed}")
    out = []
    for split, gids in sorted(by_split.items()):
        chosen = gids if len(gids) <= N_GROUPS else rng.sample(gids, N_GROUPS)
        for g in sorted(chosen):
            mem = rng.sample(sorted(members[g]), min(MAX_MEMBERS, len(members[g])))
            anchor = rng.choice(mem)
            intruder = None
            for spread in (0, 1, 2):
                b = pool_bucket.get(anchor, 0)
                cands = [s for d in range(-spread, spread + 1)
                         for s in pool_by.get((pos[anchor], b + d), []) if s not in in_group[g]]
                if cands:
                    intruder = rng.choice(sorted(cands))
                    break
            if intruder is None:
                continue
            words = mem + [intruder]
            rng.shuffle(words)
            out.append(with_content_id({
                "id": f"intrusion-{provider}-s{seed}-{g}", "task": "intrusion", "provider": provider,
                "seed": seed, "split": split, "group_id": g,
                "words": [{"strong": s, "lemma": lemmas[s]} for s in words],
                "answer": words.index(intruder), "chance": round(1 / len(words), 4),
                "weight": sum(counts.get(s, 0) for s in members[g]),
            }))
    return out


# ---------- labelfit ----------

def held_out_tokens(excluded: set[str]) -> tuple[list[tuple], dict[tuple, list[tuple]]]:
    """Content tokens in held-out books, and every verse's words for rendering."""
    from macula.intrinsic_yardstick import book_split
    _train, test_books = book_split(SPLIT_SEED)
    db = sqlite3.connect(f"file:{SPINE_DB}?mode=ro", uri=True)
    marks = ",".join("?" * len(test_books))
    verses: dict[tuple, list[tuple]] = collections.defaultdict(list)
    tokens = []
    for b, c, v, idx, surface, strong, morph in db.execute(
            f"SELECT book, chapter, verse, idx, surface, strong, morph FROM spine_words "
            f"WHERE book IN ({marks}) ORDER BY book, chapter, verse, idx", sorted(test_books)):
        verses[(b, c, v)].append((idx, surface))
        if strong is not None and morph and morph[:3] in ("He,", "Ar,"):
            s = f"H{int(strong):04d}"
            if s not in excluded:
                tokens.append((b, c, v, idx, s))
    return tokens, verses


def render_verse(words: list[tuple], target_idx: int) -> str:
    out = []
    for idx, surface in words:
        w = _ACCENTS.sub("", surface)
        out.append(f"⟦{w}⟧" if idx == target_idx else w)
    return " ".join(out)


def labelfit_items(provider: str, seed: int, ctx: dict) -> list[dict]:
    rows, groups = load_provider(provider, PROVIDERS_DIR)
    served = {s: g for s, _a, g, _sh, sv in rows if sv}
    labels = {g: rec["label"] for g, rec in groups.items() if rec.get("label")}
    served_groups = sorted({g for g in served.values() if g in labels})
    mass: collections.Counter = collections.Counter()
    for s, g in served.items():
        mass[g] += ctx["counts"].get(s, 0)
    group_weights = [max(mass[g], 1) for g in served_groups]
    tokens = [t for t in ctx["tokens"]
              if t[4] in served and served[t[4]] in labels and groups[served[t[4]]].get("label_strong") != t[4]]

    rng = random.Random(f"labelfit-{provider}-{seed}")
    by_split: dict[str, list[tuple]] = collections.defaultdict(list)
    for t in tokens:
        by_split[split_of(f"{t[0]} {t[1]}:{t[2]}")].append(t)
    out = []
    for split, toks in sorted(by_split.items()):
        for b, c, v, idx, s in sorted(rng.sample(toks, min(N_TOKENS, len(toks)))):
            correct = labels[served[s]]
            distract: list[str] = []
            for _ in range(200):
                g = rng.choices(served_groups, weights=group_weights)[0]
                lab = labels[g]
                if g == served[s] or lab == correct or lab in distract or groups[g].get("label_strong") == s:
                    continue
                distract.append(lab)
                if len(distract) == 3:
                    break
            options = [correct] + distract
            rng.shuffle(options)
            out.append(with_content_id({
                "id": f"labelfit-{provider}-s{seed}-{b}{c}:{v}.{idx}", "task": "labelfit",
                "provider": provider, "seed": seed, "split": split, "ref": f"{b} {c}:{v}",
                "strong": s, "verse": render_verse(ctx["verses"][(b, c, v)], idx),
                "options": options, "answer": options.index(correct), "chance": round(1 / len(options), 4),
                "shared": s in ctx["shared"],
            }))
    return out


# ---------- gold ----------

GOLD_INTRUSION = [            # four of a kind + one clear outsider (last); lemmas come from spine.db
    (1, 517, 1121, 1323, 5483), (3027, 7272, 5869, 241, 1004), (5483, 2543, 1581, 7716, 3701),
    (2091, 3701, 5178, 1270, 3899), (559, 1696, 7121, 6030, 398), (1980, 935, 3318, 5927, 3045),
    (3899, 3196, 8081, 1320, 2719), (2719, 7198, 2671, 4043, 1612), (4196, 2077, 3548, 5930, 7704),
    (2022, 1389, 5158, 6010, 3627), (259, 8147, 7969, 702, 776), (8121, 3394, 3556, 8064, 6086),
    (8057, 1523, 7442, 5937, 1129), (2026, 5221, 7523, 4191, 2232), (8384, 1612, 2132, 7416, 5892),
    (899, 3801, 8071, 4598, 4325), (1004, 1964, 2346, 8179, 3820), (3220, 5104, 875, 4325, 68),
    (3117, 3915, 8141, 2320, 5315), (1, 517, 251, 269, 3701),
]

GOLD_LABELFIT = [             # (book, chapter, verse, target strong, correct label, three distractors)
    ("GEN", 1, 1, 776, "אֲדָמָה · ground", ["בֶּגֶד · garment", "זֶבַח · sacrifice", "קֶשֶׁת · bow"]),
    ("GEN", 22, 2, 1121, "Family relations", ["Clothing", "Metals", "Weather"]),
    ("EXO", 20, 15, 1589, "Theft", ["Music", "Sea creatures", "Building"]),
    ("1SA", 17, 50, 2719, "קֶשֶׁת · bow", ["לֶחֶם · bread", "שָׁנָה · year", "כְּתֹנֶת · tunic"]),
    ("PSA", 23, 1, 7462, "Herding animals", ["Metalwork", "Writing", "Disease"]),
    ("GEN", 8, 22, 7105, "זָרַע · sow", ["חֶרֶב · sword", "כְּתֹנֶת · tunic", "יָרֵחַ · moon"]),
    ("LEV", 1, 9, 4196, "זֶבַח · sacrifice", ["סוּס · horse", "בַּרְזֶל · iron", "רֶגֶל · foot"]),
    ("RUT", 1, 1, 7458, "Hunger and food shortage", ["Royalty", "Clothing", "Musical instruments"]),
    ("JON", 1, 4, 3220, "נָהָר · river", ["בֶּגֶד · garment", "יָד · hand", "שָׁנָה · year"]),
    ("GEN", 37, 9, 3394, "Celestial bodies", ["Tools", "Kinship", "Emotions"]),
]


def gold_items(lemmas: dict[str, str]) -> list[dict]:
    db = sqlite3.connect(f"file:{SPINE_DB}?mode=ro", uri=True)
    rng = random.Random("gold")
    out = []
    for i, strongs in enumerate(GOLD_INTRUSION):
        codes = [f"H{n:04d}" for n in strongs]
        missing = [c for c in codes if c not in lemmas]
        if missing:
            sys.exit(f"gold intrusion item {i}: no lemma for {missing}")
        intruder = codes[-1]
        rng.shuffle(codes)
        out.append({"id": f"gold-intrusion-{i}", "task": "intrusion", "provider": "gold", "seed": 0,
                    "split": "gold", "words": [{"strong": c, "lemma": lemmas[c]} for c in codes],
                    "answer": codes.index(intruder), "chance": 0.2})
    for i, (b, c, v, strong, correct, distract) in enumerate(GOLD_LABELFIT):
        words = db.execute("SELECT idx, surface, strong FROM spine_words WHERE book=? AND chapter=? AND verse=? "
                           "ORDER BY idx", (b, c, v)).fetchall()
        target = next(idx for idx, _s, st in words if st == strong)
        options = [correct] + distract
        rng.shuffle(options)
        out.append({"id": f"gold-labelfit-{i}", "task": "labelfit", "provider": "gold", "seed": 0,
                    "split": "gold", "ref": f"{b} {c}:{v}", "strong": f"H{strong:04d}",
                    "verse": render_verse([(idx, s) for idx, s, _st in words], target),
                    "options": options, "answer": options.index(correct), "chance": 0.25, "shared": False})
    return out


# ---------- main ----------

def write_jsonl(path: Path, items: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(json.dumps(it, ensure_ascii=False, sort_keys=True) + "\n" for it in items)
    path.write_text(data, encoding="utf-8")
    return hashlib.sha256(data.encode()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--providers", nargs="*", default=list(PROVIDERS))
    args = ap.parse_args()

    excluded, counts, lemmas, pos = excluded_strongs(), token_counts(), lemma_of(), pos_of()
    pool = {s: n for s, n in counts.items() if s not in excluded and s in lemmas and s in pos}
    tokens, verses = held_out_tokens(excluded)
    served_by = {}
    for p in ("P0", "P1", "P2"):
        rows, _ = load_provider(p, PROVIDERS_DIR)
        served_by[p] = {s for s, _a, _g, _sh, sv in rows if sv}
    ctx = {"excluded": excluded, "counts": counts, "lemmas": lemmas, "pos": pos,
           "pool_bucket": bucket_of(pool), "tokens": tokens, "verses": verses,
           "shared": served_by["P0"] & served_by["P1"] & served_by["P2"]}

    manifest: dict = {"providers_manifest": hashlib.sha256((PROVIDERS_DIR / "manifest.json").read_bytes()).hexdigest(),
                      "files": {}}
    manifest["files"]["gold.jsonl"] = write_jsonl(ITEMS / "gold.jsonl", gold_items(lemmas))
    for p in args.providers:
        for seed in SEEDS:
            for task, fn in (("intrusion", intrusion_items), ("labelfit", labelfit_items)):
                items = fn(p, seed, ctx)
                rel = f"{task}/{p}_s{seed}.jsonl"
                manifest["files"][rel] = write_jsonl(ITEMS / rel, items)
                n = collections.Counter(it["split"] for it in items)
                print(f"[items] {rel:28} dev={n['dev']:4} test={n['test']:4}")
    (ITEMS / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[items] -> {ITEMS}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
