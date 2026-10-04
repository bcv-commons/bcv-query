"""Per-occurrence check for sense units: does serving each occurrence its own sense's group help readers?

A sense-unit build (build_semantic_neighbors --rendering-senses) puts a word's senses into groups of their
own; the usual providers still serve one group per word (the group holding most occurrences). This scores
the two ways of serving the SAME build on the tokens where they differ:
- word:  the word's served group (as /verse serves today);
- token: the group of the occurrence's own sense unit;
- PR-token: token labels shuffled across items (must sit at chance).
Held-out books, dev split, judged by usability_judge's label-fit prompt (chance 25%).

  python -m macula.sense_unit_scorecard --provider RSN0 --clusters macula/data/bhsa_free/seeded/rsn_h0/domain_clusters.tsv \
      --senses macula/data/rendering_senses/occurrences_nouns.tsv --items --run --judge claude-cli
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROV = HERE / "data" / "usability" / "providers"
OUT = HERE / "data" / "usability" / "sense_units"
SEEDS = (13, 17, 23)
N_TOKENS = 200


def load(provider: str, clusters: Path, senses: Path):
    labels, mass = {}, {}
    for line in (PROV / f"{provider}.groups.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        gid, label, _ls, _ll, n = line.split("\t")
        labels[gid], mass[gid] = label, int(n)
    served = {}
    for line in (PROV / f"{provider}.members.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        strong, _ax, gid, _sh, sv = line.split("\t")
        if sv == "1":
            served[strong] = gid
    unit_group = {}
    for line in clusters.read_text(encoding="utf-8").splitlines():
        if line.startswith(("#", "lexeme\t")):
            continue
        p = line.split("\t")
        unit_group[p[0]] = f"c{p[2]}"
    sense_of = {}
    with senses.open(encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            k, lx, s = line.rstrip("\n").split("\t")
            sense_of[k] = (lx, s)
    return labels, mass, served, unit_group, sense_of


def make_items(provider: str, clusters: Path, senses: Path) -> None:
    from macula.setting_scorecard import render_verse, tokens_and_verses
    import sqlite3
    labels, mass, served, unit_group, sense_of = load(provider, clusters, senses)
    tokens, verses, strong_of = tokens_and_verses()
    db = sqlite3.connect(f"file:{HERE / 'lexeme-spine.db'}?mode=ro", uri=True)
    key_of = {(b, c, v, i): k for b, c, v, i, k in db.execute(
        "SELECT book, chapter, verse, idx, key FROM spine_words WHERE lexeme LIKE 'hbo:%'")}
    cand = []
    for t in tokens:
        lx_s = sense_of.get(key_of.get(t, ""))
        w = served.get(strong_of[t])
        g = unit_group.get(f"{lx_s[0]}#{lx_s[1]}") if lx_s else None
        if w and g and g != w and w in labels and g in labels and labels[g] != labels[w]:
            cand.append((t, labels[w], labels[g]))
    print(f"[sense-units] {provider}: {len(tokens)} held-out dev content tokens; "
          f"{len(cand)} where the token's sense group differs from the word's group")
    pool = [gid for gid in labels if mass.get(gid)]
    weights = [mass[g] for g in pool]
    OUT.mkdir(parents=True, exist_ok=True)
    for kind in ("word", "token", "PR-token"):
        items = []
        for seed in SEEDS:
            rng = random.Random(f"su-{provider}-{seed}")
            sample = sorted(rng.sample(cand, min(N_TOKENS, len(cand))))
            correct_of = {c[0]: (c[1] if kind == "word" else c[2]) for c in sample}
            if kind == "PR-token":
                donors = [c[2] for c in sample]
                random.Random(f"su-pr-{provider}-{seed}").shuffle(donors)
                correct_of = {c[0]: d for c, d in zip(sample, donors)}
            for t, lw, lg in sample:
                correct = correct_of[t]
                avoid = {lw, lg, correct}          # neither serving's label may appear as a distractor
                distract = []
                for _ in range(500):
                    lab = labels[rng.choices(pool, weights=weights)[0]]
                    if lab not in avoid and lab not in distract:
                        distract.append(lab)
                        if len(distract) == 3:
                            break
                opts = [correct] + distract
                rng.shuffle(opts)
                b, c, v, idx = t
                items.append({"id": f"su-{provider}-{kind}-s{seed}-{b}{c}:{v}.{idx}", "task": "labelfit",
                              "seed": seed, "verse": render_verse(verses[(b, c, v)], idx),
                              "options": opts, "answer": opts.index(correct), "chance": 0.25})
        (OUT / f"{provider}-{kind}.jsonl").write_text(
            "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items), encoding="utf-8")


def run(provider: str, judge: str) -> None:
    import concurrent.futures
    from macula import usability_judge as uj
    uj._load_env()
    jd = OUT / "judgments" / judge
    jd.mkdir(parents=True, exist_ok=True)
    for kind in ("word", "token", "PR-token"):
        path = OUT / f"{provider}-{kind}.jsonl"
        items = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l]
        out = jd / path.name
        done = {json.loads(l)["id"] for l in out.read_text(encoding="utf-8").splitlines()} if out.exists() else set()
        todo = [it for it in items if it["id"] not in done]

        def call(batch):
            prompt = uj.PROMPTS["labelfit"] + json.dumps([uj.render(it, "served") for it in batch],
                                                         ensure_ascii=False, indent=1)
            text, _i, _o = uj.call_judge(judge, prompt)
            return uj.parse(text, batch)

        with concurrent.futures.ThreadPoolExecutor(uj.WORKERS_FOR.get(judge, uj.WORKERS)) as pool, \
                out.open("a", encoding="utf-8") as fh:
            for got in pool.map(call, [todo[i:i + 20] for i in range(0, len(todo), 20)]):
                for iid, ch in got.items():
                    fh.write(json.dumps({"id": iid, "choice": ch}) + "\n")


def report(provider: str, judge: str) -> None:
    jd = OUT / "judgments" / judge
    for kind in ("word", "token", "PR-token"):
        items = [json.loads(l) for l in (OUT / f"{provider}-{kind}.jsonl").read_text(encoding="utf-8").splitlines()]
        p = jd / f"{provider}-{kind}.jsonl"
        ch = {r["id"]: r["choice"] for r in map(json.loads, p.read_text(encoding="utf-8").splitlines())} if p.exists() else {}
        per = {}
        for s in SEEDS:
            j = [it for it in items if it["seed"] == s and it["id"] in ch]
            if j:
                per[s] = round(sum(ch[it["id"]] == it["answer"] for it in j) / len(j), 3)
        n = sum(it["id"] in ch for it in items)
        acc = round(sum(per.values()) / len(per), 3) if per else None
        print(f"{provider:6s} {kind:9s} n={n:4d} acc={acc} seeds={per}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", required=True)
    ap.add_argument("--clusters", type=Path, required=True)
    ap.add_argument("--senses", type=Path, required=True)
    ap.add_argument("--items", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--judge", default="claude-cli")
    a = ap.parse_args()
    if a.items:
        make_items(a.provider, a.clusters, a.senses)
    if a.run:
        run(a.provider, a.judge)
    report(a.provider, a.judge)
    return 0


if __name__ == "__main__":
    sys.exit(main())
