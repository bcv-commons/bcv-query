"""Compare two group builds where they differ: head-to-head judging, plus a free Hebrew-native agreement score.

Two builds serve the same label for ~96% of word occurrences, so averaged label-fit scores mostly re-measure
identical items (a 3-point gap is a handful of items). This judges only the held-out tokens whose served
labels differ:
- head-to-head: the verse with the word marked, the two labels; the judge picks the one that better fits
  the word here. Every item is asked in both orders (cancels position bias); a pair counts only when both
  orders agree, otherwise it is a tie. Sanity check: two builds that differ only by noise sit near 50%.
- agreement: share of verified commentary pairs (Malbim, Metzudat Zion, Mahberet Menahem) whose two words
  share a served group; random pairs ~0.2%. No judge. Only meaningful for sources the builds do not use.

  python -m macula.group_compare --a B0 --b B1 --items --run --judge claude-cli
  python -m macula.group_compare --a B0 --b MZMM0 --agreement
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROV = HERE / "data" / "usability" / "providers"
OUT = HERE / "data" / "usability" / "h2h"
N_ITEMS = 300
SOURCES = ("metzudat_zion", "malbim", "mahberet_menahem")
PROMPT = (
    "You are an expert in Biblical Hebrew. Each item below is a verse of the Hebrew Bible with one word marked "
    "like ⟦this⟧, followed by two labels A and B. Each label is a Hebrew word (with an English gloss) that names "
    "a group of related words. For every item, choose the label that better fits the meaning of the marked word "
    "in this verse.\nReply with JSON only, no prose: a list of objects {\"id\": <item id>, \"choice\": \"A\" or "
    "\"B\"}.\n\nItems:\n")


def served(name: str) -> dict[str, str]:
    lab = {l.split("\t")[0]: l.split("\t")[1] for l in (PROV / f"{name}.groups.tsv").read_text(encoding="utf-8").splitlines()[1:]}
    out = {}
    for line in (PROV / f"{name}.members.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        s, _a, g, _sh, sv = line.split("\t")
        if sv == "1" and g in lab:
            out[s] = lab[g]
    return out


def served_groups(name: str) -> dict[str, str]:
    out = {}
    for line in (PROV / f"{name}.members.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        s, _a, g, _sh, sv = line.split("\t")
        if sv == "1":
            out[s] = g
    return out


def agreement(names: list[str]) -> None:
    pairs = {}
    for src in SOURCES:
        p = ROOT / "resources" / src / "llm_verification.tsv"
        pairs[src] = [tuple(l.split("\t")[:2]) for l in p.read_text(encoding="utf-8").splitlines()
                      if l.startswith("H") and l.rstrip().endswith("\tyes")]
    for name in names:
        g = served_groups(name)
        row = []
        for src, ps in pairs.items():
            ok = [g[a] == g[b] for a, b in ps if a in g and b in g]
            row.append(f"{src} {sum(ok) / len(ok):.1%} (n={len(ok)})")
        print(f"[agreement] {name:7s} " + " | ".join(row))


def _lemmas() -> dict[str, str]:
    import pyarrow.parquet as pq
    out = {}
    for r in pq.read_table(ROOT / "resources" / "prior_pack" / "prior_pack.parquet",
                           columns=["strong", "lemma", "testament"]).to_pylist():
        if r["testament"] == "OT" and r["strong"]:
            out.setdefault(r["strong"], r["lemma"])
    return out


def make_items(a: str, b: str) -> list[dict]:
    from macula.setting_scorecard import render_verse, tokens_and_verses
    la, lb = served(a), served(b)
    tokens, verses, strong_of = tokens_and_verses()
    lemma = _lemmas()
    # a label that is the marked word itself wins regardless of quality (and tells a reader nothing), so
    # those tokens are left out, as in the label-fit scorecard
    own = lambda t, lab: lab.split(" · ")[0] == lemma.get(strong_of[t], "")
    diff = [t for t in tokens if strong_of[t] in la and strong_of[t] in lb and la[strong_of[t]] != lb[strong_of[t]]
            and not own(t, la[strong_of[t]]) and not own(t, lb[strong_of[t]])]
    both = [t for t in tokens if strong_of[t] in la and strong_of[t] in lb]
    print(f"[h2h] {a} vs {b}: {len(both)} held-out dev tokens labelled by both; {len(diff)} differ with neither "
          f"label the word itself ({len(diff) / max(len(both), 1):.1%})")
    rng = random.Random(f"h2h-{a}-{b}")
    # one token per word: repeated tokens of a frequent word get the same two labels and the same verdict,
    # so they are not independent evidence (a first version counted one word 14 times)
    by_word: dict[str, list] = collections.defaultdict(list)
    for t in diff:
        by_word[strong_of[t]].append(t)
    one_each = [rng.choice(ts) for _w, ts in sorted(by_word.items())]
    print(f"[h2h] {len(by_word)} distinct words among them; sampling one token per word")
    sample = sorted(rng.sample(one_each, min(N_ITEMS, len(one_each))))
    items = []
    for t in sample:
        bk, c, v, idx = t
        s = strong_of[t]
        for order in ("ab", "ba"):
            first, second = (la[s], lb[s]) if order == "ab" else (lb[s], la[s])
            items.append({"id": f"h2h-{a}-{b}-{bk}{c}:{v}.{idx}-{order}", "token": f"{bk}{c}:{v}.{idx}",
                          "order": order, "verse": render_verse(verses[(bk, c, v)], idx),
                          "labels": {"A": first, "B": second}})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{a}-vs-{b}.jsonl").write_text("".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items),
                                           encoding="utf-8")
    return items


def run(a: str, b: str, judge: str) -> None:
    import concurrent.futures
    import re
    from macula import usability_judge as uj
    uj._load_env()
    path = OUT / f"{a}-vs-{b}.jsonl"
    items = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l]
    out = OUT / f"{a}-vs-{b}.{judge}.jsonl"
    done = {json.loads(l)["id"] for l in out.read_text(encoding="utf-8").splitlines()} if out.exists() else set()
    # the two orders of a token go to different batches: all "ab" items first, then all "ba"
    todo = sorted((it for it in items if it["id"] not in done), key=lambda it: (it["order"], it["token"]))

    def call(batch):
        prompt = PROMPT + json.dumps([{"id": it["id"], "verse": it["verse"], "labels": it["labels"]} for it in batch],
                                     ensure_ascii=False, indent=1)
        text, _i, _o = uj.call_judge(judge, prompt)
        m = re.search(r"\[.*\]", text, re.S)
        try:
            got = json.loads(m.group(0)) if m else []
        except json.JSONDecodeError:
            return {}
        ids = {it["id"] for it in batch}
        return {r["id"]: r["choice"] for r in got if isinstance(r, dict) and r.get("id") in ids and r.get("choice") in ("A", "B")}

    with concurrent.futures.ThreadPoolExecutor(uj.WORKERS_FOR.get(judge, uj.WORKERS)) as pool, out.open("a", encoding="utf-8") as fh:
        for got in pool.map(call, [todo[i:i + 20] for i in range(0, len(todo), 20)]):
            for iid, ch in got.items():
                fh.write(json.dumps({"id": iid, "choice": ch}) + "\n")


def report(a: str, b: str, judge: str) -> None:
    items = [json.loads(l) for l in (OUT / f"{a}-vs-{b}.jsonl").read_text(encoding="utf-8").splitlines() if l]
    p = OUT / f"{a}-vs-{b}.{judge}.jsonl"
    ch = {r["id"]: r["choice"] for r in map(json.loads, p.read_text(encoding="utf-8").splitlines())} if p.exists() else {}
    votes = collections.defaultdict(dict)
    first_pick = collections.Counter()
    for it in items:
        if it["id"] in ch:
            c = ch[it["id"]]
            first_pick[c] += 1
            winner = (a if c == "A" else b) if it["order"] == "ab" else (b if c == "A" else a)
            votes[it["token"]][it["order"]] = winner
    full = [v for v in votes.values() if len(v) == 2]
    wa = sum(1 for v in full if v["ab"] == v["ba"] == a)
    wb = sum(1 for v in full if v["ab"] == v["ba"] == b)
    ties = len(full) - wa - wb
    decided = wa + wb
    share = wa / decided if decided else float("nan")
    se = math.sqrt(share * (1 - share) / decided) if decided else float("nan")
    pos = first_pick["A"] / max(sum(first_pick.values()), 1)
    print(f"[h2h] {a} vs {b} ({judge}): words judged in both orders {len(full)}; {a} wins {wa}, {b} wins {wb}, "
          f"order-dependent (tie) {ties}; {a} share of decided {share:.1%} ± {1.96 * se:.1%} (95%); "
          f"label A picked {pos:.0%} of the time")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--items", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--agreement", action="store_true")
    ap.add_argument("--judge", default="claude-cli")
    x = ap.parse_args()
    if x.agreement:
        agreement([x.a, x.b])
    if x.items:
        make_items(x.a, x.b)
    if x.run:
        for _ in range(3):
            run(x.a, x.b, x.judge)
    if (OUT / f"{x.a}-vs-{x.b}.jsonl").exists():
        report(x.a, x.b, x.judge)
    return 0


if __name__ == "__main__":
    sys.exit(main())
