"""Usability scorecard for the setting axis (the SDBH `ctx` stand-in), same method as usability_*.

Measures, judged by an LLM (default OpenAI, see usability_judge.MODELS):
- setting fit: a held-out verse with one word marked, four setting labels; the judge picks the setting the
  word is used in. Every provider is scored on the SAME tokens (those all providers label).
- intrusion: five words of one setting plus one from another; the judge finds the outsider (Hebrew lemmas).
Providers:
- C0      SDBH `ctx` as it was served (dominant top-level contextual domain per Strong's), the baseline.
- S{k}    our settings, per occurrence (build_setting_axis.py).
- S{k}t   our settings, per word (the word's most frequent setting), to see whether per-occurrence helps.
- PR-*    the provider's labels shuffled across tokens: must score at chance.
Coverage (share of Hebrew content tokens with a label) is reported without a judge.

  python -m macula.setting_scorecard --items --k 40 60 80
  python -m macula.setting_scorecard --run --judge openai
  python -m macula.setting_scorecard --report
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine.db"
SETTINGS = HERE / "data" / "settings"
EVAL = SETTINGS / "eval"
CTX_COMMIT = "e184b8b"           # last commit with SDBH core/ctx in resources/semantic_domains/hbo.tsv
SEEDS = (13, 17, 23)
N_TOKENS = 200
PROMPTS = {
    "settingfit": (
        "You are an expert in Biblical Hebrew. Each item below is a verse of the Hebrew Bible with one word "
        "marked like ⟦this⟧, followed by four candidate labels. Each label names a setting or subject area "
        "in which words are used (for example a ritual, legal, military, domestic, royal or wisdom "
        "setting). A label is either a short category name or a few Hebrew words with English glosses that "
        "characterise the setting. For every item, choose the label that best describes the setting in "
        "which the marked word is used in this verse.\n"
        "Reply with JSON only, no prose: a list of objects {\"id\": <item id>, \"choice\": <number>}.\n\n"
        "Items:\n"),
    "intrusion": (
        "You are an expert in Biblical Hebrew vocabulary. Each item below lists Biblical Hebrew words "
        "(dictionary forms). All but one of them are typically used in the same setting or subject area; "
        "exactly one is the odd one out. For every item, give the number of the odd one out.\n"
        "Reply with JSON only, no prose: a list of objects {\"id\": <item id>, \"choice\": <number>}.\n\n"
        "Items:\n"),
}


# ---------- providers ----------

def ctx_p0() -> dict[str, str]:
    """H#### -> dominant top-level SDBH contextual domain label (frozen locally, never published)."""
    snap = EVAL / "ctx_p0.tsv"
    if not snap.exists():
        raw = subprocess.run(["git", "-C", str(ROOT), "show", f"{CTX_COMMIT}:resources/semantic_domains/hbo.tsv"],
                             capture_output=True, text=True, check=True).stdout
        share = collections.defaultdict(collections.Counter)
        label = {}
        for line in raw.splitlines()[1:]:
            strong, typ, code, lab, count, _sh = line.split("\t")
            if typ != "ctx":
                continue
            top = code[:3]
            if len(code) == 3:
                label[top] = lab
            share[strong][top] += int(count)
        snap.parent.mkdir(parents=True, exist_ok=True)
        with snap.open("w", encoding="utf-8") as fh:
            for s, c in sorted(share.items()):
                top = c.most_common(1)[0][0]
                if top in label:
                    fh.write(f"{s}\t{label[top]}\n")
    return dict(line.rstrip("\n").split("\t") for line in snap.read_text(encoding="utf-8").splitlines())


def setting_labels(k) -> dict[str, str]:
    sys.path.insert(0, str(HERE.parent))
    import data
    out = {}
    for t in json.loads((SETTINGS / f"k{k}" / "topics.json").read_text(encoding="utf-8")):
        parts = []
        for w in t["words"][:2]:
            g = (data.gloss_of(w["strong"]) or {}).get("gloss") or ""
            parts.append(f"{w['lemma']} · {g}" if g else w["lemma"])
        out[t["topic"]] = ", ".join(parts)
    return out


VIA: dict[tuple, str] = {}


def setting_occurrences(k) -> dict[tuple, str]:
    occ = {}
    with (SETTINGS / f"k{k}" / "occurrences.tsv").open(encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            b, c, v, idx, _lx, t, _conf, *via = line.rstrip("\n").split("\t")
            occ[(b, int(c), int(v), int(idx))] = t
            VIA[(k, b, int(c), int(v), int(idx))] = via[0] if via else "word"
    return occ


# ---------- items ----------

def tokens_and_verses() -> tuple[list[tuple], dict[tuple, list[tuple]], dict[tuple, str]]:
    from macula.intrinsic_yardstick import book_split
    from macula.usability_items import split_of
    import pyarrow.parquet as pq
    _train, test_books = book_split(13)
    content = {r["lexeme"] for r in pq.read_table(ROOT / "resources" / "prior_pack" / "prior_pack.parquet",
                                                    columns=["lexeme", "pos"]).to_pylist()
               if r["pos"] in ("noun", "verb", "adj")}
    db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    verses = collections.defaultdict(list)
    tokens, strong_of = [], {}
    for b, c, v, idx, key, surface, lexeme, strong in db.execute(
            "SELECT book, chapter, verse, idx, key, surface, lexeme, strong FROM spine_words "
            "WHERE lexeme LIKE 'hbo:%' ORDER BY book, chapter, verse, idx"):
        verses[(b, c, v)].append((idx, key, surface))
        if b in test_books and lexeme in content and strong is not None \
                and split_of(f"{b} {c}:{v}") == "dev":
            t = (b, c, v, idx)
            tokens.append(t)
            strong_of[t] = f"H{int(strong):04d}"
    return tokens, verses, strong_of


def render_verse(words: list[tuple], target: int) -> str:
    from macula.usability_items import _ACCENTS
    out, cur_word, buf = [], None, ""
    for idx, key, surface in words:
        w = _ACCENTS.sub("", surface or "")
        w = f"⟦{w}⟧" if idx == target else w
        if key[:-1] != cur_word and buf:
            out.append(buf)
            buf = ""
        cur_word = key[:-1]
        buf += w
    if buf:
        out.append(buf)
    return " ".join(out)


def make_items(ks: list[int]) -> None:
    tokens, verses, strong_of = tokens_and_verses()
    c0 = ctx_p0()
    prov: dict[str, dict[tuple, str]] = {"C0": {t: c0[strong_of[t]] for t in tokens if strong_of[t] in c0}}
    for k in ks:
        labels, occ = setting_labels(k), setting_occurrences(k)
        prov[f"S{k}"] = {t: labels[occ[t]] for t in tokens if t in occ}
        # per word: the lexeme's most frequent setting over all its occurrences
        db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
        lex_of = {(b, c, v, i): lx for b, c, v, i, lx in db.execute(
            "SELECT book, chapter, verse, idx, lexeme FROM spine_words WHERE lexeme LIKE 'hbo:%'")}
        dom = collections.defaultdict(collections.Counter)
        for t, top in occ.items():
            dom[lex_of[t]][top] += 1
        prov[f"S{k}t"] = {t: labels[dom[lex_of[t]].most_common(1)[0][0]] for t in tokens if lex_of[t] in dom}
    shared = sorted(set.intersection(*(set(p) for p in prov.values())))
    cov = {name: round(len(p) / len(tokens), 3) for name, p in prov.items()}
    print(f"held-out dev content tokens {len(tokens)}; shared by all providers {len(shared)}; coverage {cov}")
    EVAL.mkdir(parents=True, exist_ok=True)
    (EVAL / "coverage.json").write_text(json.dumps({"tokens": len(tokens), "shared": len(shared),
                                                    "coverage": cov}, indent=1), encoding="utf-8")
    for name in list(prov):
        prov[f"PR-{name}"] = None
    for name, p in prov.items():
        base = name[3:] if name.startswith("PR-") else name
        labmap = dict(prov[base])
        mass = collections.Counter(labmap.values())
        pool, weights = list(mass), [mass[x] for x in mass]
        items = []
        for seed in SEEDS:
            rng = random.Random(f"setting-{base}-{seed}")
            sample = sorted(rng.sample(shared, min(N_TOKENS, len(shared))))
            if name.startswith("PR-"):         # shuffled control: correct label taken from another token
                prng = random.Random(f"pr-{base}-{seed}")
                donors = [labmap[t] for t in sample]
                prng.shuffle(donors)
                served = dict(zip(sample, donors))
            else:
                served = {t: labmap[t] for t in sample}
            for t in sample:
                correct = served[t]
                distract = []
                for _ in range(500):
                    lab = rng.choices(pool, weights=weights)[0]
                    if lab != correct and lab not in distract:
                        distract.append(lab)
                        if len(distract) == 3:
                            break
                opts = [correct] + distract
                rng.shuffle(opts)
                b, c, v, idx = t
                items.append({"id": f"settingfit-{name}-s{seed}-{b}{c}:{v}.{idx}", "task": "settingfit",
                              "provider": name, "seed": seed, "verse": render_verse(verses[(b, c, v)], idx),
                              "options": opts, "answer": opts.index(correct), "chance": 0.25})
        (EVAL / f"settingfit-{name}.jsonl").write_text(
            "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items), encoding="utf-8")
    make_intrusion(ks, c0)


def make_intrusion(ks: list[int], c0: dict[str, str]) -> None:
    groups: dict[str, dict[str, list[str]]] = {}
    freq = _strong_freq()
    by_dom = collections.defaultdict(list)
    for s, lab in c0.items():
        if _lemma_of(s):
            by_dom[lab].append(s)
    groups["C0"] = {d: sorted(m, key=lambda s: -freq.get(s, 0))[:12] for d, m in by_dom.items() if len(m) >= 8}
    for k in ks:
        T = json.loads((SETTINGS / f"k{k}" / "topics.json").read_text(encoding="utf-8"))
        groups[f"S{k}"] = {t["topic"]: [w["strong"] for w in t["words"]] for t in T}
    for name, gs in groups.items():
        items = []
        member_of = collections.defaultdict(set)
        for g, m in gs.items():
            for s in m:
                member_of[s].add(g)
        for seed in SEEDS:
            rng = random.Random(f"intr-{name}-{seed}")
            for g, m in sorted(gs.items()):
                five = []
                for s in m:
                    if _lemma_of(s) and _lemma_of(s) not in [_lemma_of(x) for x in five]:
                        five.append(s)
                    if len(five) == 5:
                        break
                if len(five) < 5:
                    continue
                others = [s for og, om in gs.items() if og != g for s in om[:5]
                          if g not in member_of[s] and _lemma_of(s) and _lemma_of(s) not in [_lemma_of(x) for x in five]]
                if not others:
                    continue
                intruder = rng.choice(others)
                words = five + [intruder]
                rng.shuffle(words)
                items.append({"id": f"intr-{name}-s{seed}-{g}", "task": "intrusion", "provider": name,
                              "seed": seed, "words": [{"lemma": _lemma_of(s)} for s in words],
                              "answer": words.index(intruder), "chance": round(1 / 6, 4)})
        (EVAL / f"intrusion-{name}.jsonl").write_text(
            "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items), encoding="utf-8")
        print(f"intrusion {name}: {len(items)} items")


_LEMMA: dict[str, str] = {}


def _lemma_of(s: str) -> str:
    if not _LEMMA:
        import pyarrow.parquet as pq
        for r in pq.read_table(ROOT / "resources" / "prior_pack" / "prior_pack.parquet",
                               columns=["strong", "lemma", "testament"]).to_pylist():
            if r["testament"] == "OT" and r["strong"] and r["strong"] not in _LEMMA:
                _LEMMA[r["strong"]] = r["lemma"]
    return _LEMMA.get(s, "")


def _strong_freq() -> collections.Counter:
    db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    return collections.Counter({f"H{int(s):04d}": n for s, n in db.execute(
        "SELECT strong, COUNT(*) FROM spine_words WHERE lexeme LIKE 'hbo:%' AND strong IS NOT NULL GROUP BY strong")})


# ---------- judging ----------

def run(judge: str) -> None:
    import concurrent.futures
    from macula import usability_judge as uj
    uj._load_env()
    out_dir = EVAL / "judgments" / f"{judge}--{uj.MODELS[judge].replace('/', '_')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(EVAL.glob("*.jsonl")):
        items = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l]
        out = out_dir / path.name
        done = {json.loads(l)["id"] for l in out.read_text(encoding="utf-8").splitlines()} if out.exists() else set()
        todo = [it for it in items if it["id"] not in done]
        if not todo:
            continue
        task = todo[0]["task"]

        def render(it):
            if it["task"] == "intrusion":
                return {"id": it["id"], "words": {str(i + 1): w["lemma"] for i, w in enumerate(it["words"])}}
            return {"id": it["id"], "verse": it["verse"],
                    "labels": {str(i + 1): o for i, o in enumerate(it["options"])}}

        def call(batch):
            prompt = PROMPTS[task] + json.dumps([render(it) for it in batch], ensure_ascii=False, indent=1)
            text, _i, _o = uj.call_judge(judge, prompt)
            return uj.parse(text, [dict(it, task="labelfit" if it["task"] == "settingfit" else it["task"])
                                   for it in batch])

        batches = [todo[i:i + 20] for i in range(0, len(todo), 20)]
        n = 0
        with concurrent.futures.ThreadPoolExecutor(uj.WORKERS_FOR.get(judge, uj.WORKERS)) as pool, \
                out.open("a", encoding="utf-8") as fh:
            for got in pool.map(call, batches):
                for iid, ch in got.items():
                    fh.write(json.dumps({"id": iid, "choice": ch}) + "\n")
                    n += 1
                fh.flush()
        print(f"{path.name}: +{n}", file=sys.stderr)


def report(judge: str) -> dict:
    from macula import usability_judge as uj
    out_dir = EVAL / "judgments" / f"{judge}--{uj.MODELS[judge].replace('/', '_')}"
    res = {}
    for path in sorted(EVAL.glob("*.jsonl")):
        items = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l]
        jp = out_dir / path.name
        if not jp.exists():
            continue
        ch = {r["id"]: r["choice"] for r in map(json.loads, jp.read_text(encoding="utf-8").splitlines())}
        per_seed = {}
        for seed in SEEDS:
            j = [it for it in items if it["seed"] == seed and it["id"] in ch]
            if j:
                per_seed[seed] = sum(ch[it["id"]] == it["answer"] for it in j) / len(j)
        judged = [it for it in items if it["id"] in ch]
        res[path.stem] = {"n": len(judged), "acc": round(sum(per_seed.values()) / len(per_seed), 3),
                          "per_seed": {s: round(a, 3) for s, a in per_seed.items()},
                          "chance": items[0]["chance"]}
    for name, r in res.items():
        print(f"{name:28s} n={r['n']:4d} acc={r['acc']:.3f} chance={r['chance']:.3f} seeds={r['per_seed']}")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--items", action="store_true")
    ap.add_argument("--k", nargs="*", default=["60"], help="build names under data/settings/: 40, 40a05, ...")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--judge", default="openai")
    a = ap.parse_args()
    if a.items:
        make_items(a.k)
    if a.run:
        run(a.judge)
    if a.report:
        report(a.judge)
    return 0


if __name__ == "__main__":
    sys.exit(main())


def make_fallback_items(k: int) -> None:
    """Items on tokens that got their setting from the passage (outside the topic vocabulary), scored for
    our label (S{k}p), SDBH ctx on the same tokens (C0p), and a shuffled control."""
    tokens, verses, strong_of = tokens_and_verses()
    c0 = ctx_p0()
    labels, occ = setting_labels(k), setting_occurrences(k)
    fb = [t for t in tokens if t in occ and VIA.get((k, *t)) == "passage" and strong_of[t] in c0]
    covered = sum(1 for t in tokens if t in occ)
    print(f"k={k}: coverage {covered / len(tokens):.3f} (C0 {sum(strong_of[t] in c0 for t in tokens) / len(tokens):.3f}); "
          f"passage-assigned tokens with a C0 label: {len(fb)}")
    for name, labmap in ((f"S{k}p", {t: labels[occ[t]] for t in fb}), ("C0p", {t: c0[strong_of[t]] for t in fb})):
        for pr in (False, True):
            mass = collections.Counter(labmap.values())
            pool, weights = list(mass), [mass[x] for x in mass]
            items = []
            pname = f"PR-{name}" if pr else name
            for seed in SEEDS:
                rng = random.Random(f"setting-{name}-{seed}")
                sample = sorted(rng.sample(fb, min(N_TOKENS, len(fb))))
                served = {t: labmap[t] for t in sample}
                if pr:
                    donors = list(served.values())
                    random.Random(f"pr-{name}-{seed}").shuffle(donors)
                    served = dict(zip(sample, donors))
                for t in sample:
                    correct, distract = served[t], []
                    for _ in range(500):
                        lab = rng.choices(pool, weights=weights)[0]
                        if lab != correct and lab not in distract:
                            distract.append(lab)
                            if len(distract) == 3:
                                break
                    opts = [correct] + distract
                    rng.shuffle(opts)
                    b, c, v, idx = t
                    items.append({"id": f"settingfit-{pname}-s{seed}-{b}{c}:{v}.{idx}", "task": "settingfit",
                                  "provider": pname, "seed": seed, "verse": render_verse(verses[(b, c, v)], idx),
                                  "options": opts, "answer": opts.index(correct), "chance": 0.25})
            (EVAL / f"settingfit-{pname}.jsonl").write_text(
                "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items), encoding="utf-8")
