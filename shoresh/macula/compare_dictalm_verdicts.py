#!/usr/bin/env python3
"""Head-to-head test: DictaLM (local MLX inference, Hebrew-specialized) vs. Claude Haiku (already run,
see llm_pair_verification.tsv) on the SAME sample of pairs, both scored against SDBH `core` agreement.
Motivation (2026-08): before committing local-inference infrastructure to the full pipeline, check
whether a Hebrew-specialized generative model actually judges these pairs better than a general
frontier model — measure, don't assume. See domain-replacement-roadmap.md.

Uses the identical prompt/batch/parse shape as verify_pairs_llm.py for a fair comparison — the only
difference is the inference backend (local MLX generate() vs. the Anthropic API).

  python -m macula.compare_dictalm_verdicts --limit 300 --mlx-path /tmp/dictalm-1.7b-mlx
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TIERS = ROOT / "resources" / "semantic_neighbors" / "confidence_tiers.tsv"
GLOSS_TSV = ROOT / "resources" / "strongs_gloss.tsv"
HAIKU_VERDICTS = ROOT / "resources" / "semantic_neighbors" / "llm_pair_verification.tsv"
DOMAINS = ROOT / "resources" / "semantic_domains" / "hbo.tsv"
OUT = ROOT / "resources" / "semantic_neighbors" / "dictalm_pair_verification_sample.tsv"

PAIRS_PER_CALL = 10   # smaller than the Haiku run's 25 — local generation is slower per token


def load_glosses() -> dict[str, str]:
    gl: dict[str, str] = {}
    with GLOSS_TSV.open(encoding="utf-8") as fh:
        header = next(fh).rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) > idx.get("lang", -1) and p[idx["lang"]] == "eng":
                gl.setdefault(p[idx["strong"]], p[idx["gloss"]])
    return gl


def load_sample(n: int) -> list[tuple[str, str]]:
    """Same pairs Haiku already verified (n_families==1 tier), so the comparison is apples-to-apples."""
    out = []
    with TIERS.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("strong_a\t"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) >= 3 and p[2] == "1":
                out.append((p[0], p[1]))
                if len(out) >= n:
                    break
    return out


PROMPT = (
    "You are a Biblical Hebrew lexicographer. For each PAIR below (two Strong's numbers + their English "
    "glosses), judge whether the two words are genuinely synonyms or belong to the same tight semantic "
    "concept in Biblical Hebrew usage — not just loosely related or co-occurring. Be strict: many "
    "candidate pairs will be wrong (that's why they're being checked).\n"
    "Return ONE verdict PER LINE, exactly:  <pair_id><TAB><yes|no|unsure>\n"
    "No JSON, no commentary, no extra text.\nPairs:\n"
)


def parse(text: str, wanted: set[str]) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        parts = re.split(r"\t", line.strip(), maxsplit=1)
        if len(parts) != 2:
            continue
        pid, verdict = parts[0].strip(), parts[1].strip().lower()
        if pid in wanted and verdict in ("yes", "no", "unsure"):
            out[pid] = verdict
    return out


def load_domains() -> dict[str, set[str]]:
    dom = collections.defaultdict(set)
    for line in DOMAINS.read_text(encoding="utf-8").splitlines()[1:]:
        p = line.split("\t")
        if len(p) >= 3 and p[1] == "core":
            dom[p[0]].add(p[2])
    return dom


def score(verdicts: dict[tuple[str, str], str], dom: dict, label: str) -> None:
    by_v = collections.defaultdict(lambda: [0, 0])
    for (a, b), v in verdicts.items():
        ds, db_ = dom.get(a, set()), dom.get(b, set())
        if ds and db_:
            by_v[v][1] += 1
            by_v[v][0] += bool(ds & db_)
    print(f"--- {label} ---")
    for v, (same, tot) in sorted(by_v.items()):
        print(f"  {v}: {same}/{tot} = {100*same/max(tot,1):.1f}%")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--mlx-path", type=Path, required=True)
    args = ap.parse_args()

    from mlx_lm import generate, load

    print(f"[compare] loading {args.mlx_path} ...", file=sys.stderr)
    model, tokenizer = load(str(args.mlx_path))

    candidates = load_sample(args.limit)
    glosses = load_glosses()
    entries = [{"pair_id": f"{a}-{b}", "a": f"{a} {glosses.get(a, '')}", "b": f"{b} {glosses.get(b, '')}"}
               for a, b in candidates]
    id2pair = {f"{a}-{b}": (a, b) for a, b in candidates}

    dictalm_verdicts: dict[tuple[str, str], str] = {}
    for i in range(0, len(entries), PAIRS_PER_CALL):
        batch = entries[i:i + PAIRS_PER_CALL]
        content = PROMPT + json.dumps(batch, ensure_ascii=False)
        chat = [{"role": "user", "content": content}]
        prompt = tokenizer.apply_chat_template(chat, add_generation_prompt=True, tokenize=False)
        text = generate(model, tokenizer, prompt=prompt, max_tokens=800, verbose=False)
        got = parse(text, {e["pair_id"] for e in batch})
        for pid, v in got.items():
            dictalm_verdicts[id2pair[pid]] = v
        print(f"[compare] {i + len(batch)}/{len(entries)} · +{len(got)} verdicts", file=sys.stderr)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write("strong_a\tstrong_b\tverdict\n")
        for (a, b), v in dictalm_verdicts.items():
            fh.write(f"{a}\t{b}\t{v}\n")
    print(f"[compare] {len(dictalm_verdicts)}/{len(entries)} verified -> {OUT}", file=sys.stderr)

    # load Haiku's verdicts for the SAME pairs, for a direct comparison
    haiku_verdicts: dict[tuple[str, str], str] = {}
    wanted = set(id2pair.values())
    with HAIKU_VERDICTS.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("strong_a"):
                continue
            a, b, v = line.rstrip("\n").split("\t")
            if (a, b) in wanted:
                haiku_verdicts[(a, b)] = v

    dom = load_domains()
    score(dictalm_verdicts, dom, "DictaLM-3.0-1.7B-Instruct")
    score(haiku_verdicts, dom, "Claude Haiku (already run)")

    agree = sum(1 for k in dictalm_verdicts if k in haiku_verdicts and dictalm_verdicts[k] == haiku_verdicts[k])
    both = sum(1 for k in dictalm_verdicts if k in haiku_verdicts)
    print(f"\nverdict agreement (same pair, same call): {agree}/{both} = {100*agree/max(both,1):.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
