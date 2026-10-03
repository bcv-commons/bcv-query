#!/usr/bin/env python3
"""Human check for the usability scorecard: export a blinded item set for the shared rating page, and
score the answers people enter there against the answer key and the LLM judges.

The page shows CC0 group items only (P2 = the served candidate, PR-P2 = its random control, plus the
hand-made gold items as attention checks). SDBH labels never appear on it: they may not be shared outside
the licence. The question the human check answers is whether people agree with the LLM judges; if they
do, the judges' comparison against today's SDBH labels can be trusted.

Item ids on the page are opaque (h + 8 hex); the mapping and the answer key stay in
data/usability/human/key.json, never on the page.

  cd shoresh && .venv/bin/python3 -m macula.usability_human --export
  cd shoresh && .venv/bin/python3 -m macula.usability_human --score responses.json   # ArtifactData list dump
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import sys
from pathlib import Path

from macula.usability_items import ITEMS
from macula.usability_judge import load_choices

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "usability" / "human"
PLAN = (("labelfit", "P2", 40), ("intrusion", "P2", 20), ("labelfit", "PR-P2", 8))
SEED = 13
SPLIT = "test"


def blind_id(item_id: str) -> str:
    return "h" + hashlib.sha1(item_id.encode()).hexdigest()[:8]


def shown(it: dict) -> dict:
    """Exactly what a rater sees: no provider, seed, group or answer."""
    rec = {"id": blind_id(it["id"]), "task": it["task"]}
    if it["task"] == "intrusion":
        rec["words"] = [w["lemma"] for w in it["words"]]
    else:
        rec["verse"] = it["verse"]
        rec["options"] = it["options"]
    return rec


def export() -> None:
    rng = random.Random(SEED)
    chosen = []
    for task, provider, n in PLAN:
        rel = f"{task}/{provider}_s{SEED}.jsonl"
        items = [json.loads(l) for l in (ITEMS / rel).read_text(encoding="utf-8").splitlines() if l]
        items = [it for it in items if it["split"] == SPLIT]
        chosen += [(rel, it) for it in rng.sample(items, n)]
    gold = [json.loads(l) for l in (ITEMS / "gold.jsonl").read_text(encoding="utf-8").splitlines() if l]
    gold = [it for it in gold if it["task"] == "intrusion"][:8] + [it for it in gold if it["task"] == "labelfit"][:4]
    chosen += [("gold.jsonl", it) for it in gold]
    rng.shuffle(chosen)

    page = {"version": 1, "items": [shown(it) for _rel, it in chosen]}
    key = {blind_id(it["id"]): {"item_id": it["id"], "file": rel, "task": it["task"],
                                "provider": it["provider"], "answer": it["answer"], "chance": it["chance"]}
           for rel, it in chosen}
    assert len(key) == len(chosen), "blind id collision"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "items_blind.json").write_text(json.dumps(page, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (OUT / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n = collections.Counter((v["task"], v["provider"]) for v in key.values())
    print(f"[human] {len(key)} items: {dict(n)} -> {OUT}", file=sys.stderr)


def score(responses_path: Path) -> None:
    """responses_path: JSON list of {"id": <viewer doc id>, "data": {"answers": {hid: {"c": int}}}} (or the
    raw ArtifactData list result with `documents`)."""
    raw = json.loads(responses_path.read_text(encoding="utf-8"))
    docs = raw.get("documents", raw) if isinstance(raw, dict) else raw
    key = json.loads((OUT / "key.json").read_text(encoding="utf-8"))
    by_group: dict = collections.defaultdict(lambda: [0, 0])
    agree: dict = collections.defaultdict(lambda: collections.Counter())
    raters = 0
    for d in docs:
        answers = (d.get("data") or d).get("answers") or {}
        if not answers:
            continue
        raters += 1
        for hid, a in answers.items():
            k = key.get(hid)
            if not k or a.get("c", -1) < 0:
                continue
            grp = (k["task"], k["provider"])
            by_group[grp][0] += a["c"] == k["answer"]
            by_group[grp][1] += 1
            if k["provider"] != "gold":
                for judge in ("claude-cli", "openai"):
                    ch = load_choices(judge, "served", k["file"]).get(k["item_id"])
                    if ch is not None:
                        agree[judge]["n"] += 1
                        agree[judge]["same"] += ch == a["c"]
    print(f"raters with answers: {raters}")
    for (task, provider), (hit, n) in sorted(by_group.items()):
        print(f"{task:10} {provider:6} n={n:4}  correct={hit / n:.3f}")
    for judge, c in agree.items():
        print(f"agreement with {judge}: {c['same'] / c['n']:.3f} (n={c['n']})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--score", type=Path)
    args = ap.parse_args()
    if args.export:
        export()
    if args.score:
        score(args.score)
    return 0


if __name__ == "__main__":
    sys.exit(main())
