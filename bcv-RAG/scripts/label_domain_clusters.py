#!/usr/bin/env python3
"""LLM-label the canonical domain clusters — the last piece needed before
shoresh/macula/domain_clusters.tsv could ever function as a /domain-style feature.

`build_domain_clusters.py` produces numbered Louvain communities (cluster_id 0, 1, 2, ...) — a real
grouping (45.1% same-domain agreement vs SDBH), but not a NAMED one. This asks an LLM to look at each
cluster's member glosses and propose a short Louw-Nida-style category label (e.g. "Kinship",
"Buying and Selling") — same spirit as the labels domain-replacement-roadmap.md's Phase 4 called for.
The label is a convenience name for a cluster that was already formed by clean signals (embeddings +
LXX + gloss + LLM synonym corroboration) — the LLM is not deciding cluster MEMBERSHIP here, only
describing a group that already exists.

  python3 scripts/label_domain_clusters.py
  python3 scripts/label_domain_clusters.py --limit 10 --dry-run
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent          # bcv-RAG/
ROOT = HERE.parent                                      # repo root
CLUSTERS = ROOT / "resources" / "semantic_neighbors" / "domain_clusters.tsv"
GLOSS_TSV = ROOT / "resources" / "strongs_gloss.tsv"
OUT = ROOT / "resources" / "semantic_neighbors" / "domain_cluster_labels.tsv"

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
CLUSTERS_PER_CALL = 8    # keep prompts small; clusters run up to 78 members
MAX_MEMBERS_SHOWN = 20   # cap how many glosses go in the prompt for a big cluster


def _load_dotenv() -> None:
    env = HERE / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            # plain setdefault() treats an EMPTY existing value as "already set" and refuses to
            # override it — some harnesses (this one included) pre-declare ANTHROPIC_API_KEY="" in
            # the shell env for safety, which would otherwise silently defeat .env entirely.
            if not os.environ.get(k):
                os.environ[k] = v.strip().strip('"').strip("'")


def load_clusters() -> dict[str, list[str]]:
    """{cluster_id: [strong, ...]} deduped (sense-split lexemes collapse to one entry per Strong's)."""
    by_cluster: dict[str, set[str]] = collections.defaultdict(set)
    with CLUSTERS.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("lexeme\t"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) >= 3:
                by_cluster[p[2]].add(p[1])
    return {cid: sorted(strongs) for cid, strongs in by_cluster.items()}


def load_glosses() -> dict[str, str]:
    """{H####: english gloss} from strongs_gloss.tsv, eng rows only."""
    gl: dict[str, str] = {}
    if not GLOSS_TSV.exists():
        return gl
    with GLOSS_TSV.open(encoding="utf-8") as fh:
        header = next(fh).rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) > idx.get("lang", -1) and p[idx["lang"]] == "eng":
                gl.setdefault(p[idx["strong"]], p[idx["gloss"]])
    return gl


PROMPT = (
    "You are a lexicographer labeling semantic-domain clusters of Biblical Hebrew words, in the style "
    "of Louw-Nida (e.g. \"Kinship\", \"Buying and Selling\", \"Guilt\", \"Container\"). For each CLUSTER "
    "below (id + a sample of its member words' English glosses), propose ONE short (1-4 word) label "
    "that best names the shared semantic domain. The clustering is already done — you are naming an "
    "existing group, not deciding membership; if the words look mixed/incoherent, give your best single "
    "label anyway (don't refuse).\n"
    "Return ONE label PER LINE, exactly:  <cluster_id><TAB><label>\n"
    "No JSON, no numbering, no commentary.\nClusters:\n"
)


def call_llm(batch: list[dict], tries: int = 3):
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        sys.exit("ERROR: set ANTHROPIC_API_KEY (bcv-RAG/.env)")
    body = json.dumps({"model": MODEL, "max_tokens": 2000,
                       "messages": [{"role": "user",
                                     "content": PROMPT + json.dumps(batch, ensure_ascii=False)}]}).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            u = data.get("usage", {})
            itok, otok = u.get("input_tokens", 0), u.get("output_tokens", 0)
            text = next((b["text"] for b in data.get("content", []) if b.get("type") == "text"), None)
            if text:
                return parse(text, {c["cluster_id"] for c in batch}), itok, otok
            print(f"[label-clusters] warn: no text block (try {attempt+1})", file=sys.stderr)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")[:400]
            except Exception:
                detail = str(e)
            print(f"[label-clusters] HTTP {e.code} (try {attempt+1}): {detail}", file=sys.stderr)
    return {}, 0, 0


def parse(text: str, wanted: set[str]) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        parts = re.split(r"\t", line.strip(), maxsplit=1)
        if len(parts) != 2:
            continue
        cid, label = parts[0].strip(), parts[1].strip()
        if cid in wanted and label:
            out[cid] = label
    return out


_PRICES = {"haiku": (1.0, 5.0), "sonnet": (3.0, 15.0), "opus": (15.0, 75.0)}


def _cost(itok: int, otok: int) -> float:
    rin, rout = next((v for k, v in _PRICES.items() if k in MODEL), (3.0, 15.0))
    return itok / 1e6 * rin + otok / 1e6 * rout


def main() -> int:
    _load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0, help="cap #clusters (0 = all)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    clusters = load_clusters()
    glosses = load_glosses()
    cluster_ids = sorted(clusters, key=lambda c: -len(clusters[c]))   # biggest first (most informative first)
    if args.limit:
        cluster_ids = cluster_ids[:args.limit]

    entries = []
    for cid in cluster_ids:
        members = clusters[cid][:MAX_MEMBERS_SHOWN]
        glossed = [glosses.get(s, s) for s in members]
        entries.append({"cluster_id": cid, "size": len(clusters[cid]), "glosses": glossed})

    if args.dry_run:
        print(PROMPT + json.dumps(entries[:CLUSTERS_PER_CALL], ensure_ascii=False, indent=1))
        return 0

    print(f"[label-clusters] {len(entries)} clusters to label, model={MODEL}", file=sys.stderr)
    labels: dict[str, str] = {}
    tot_in = tot_out = 0
    for i in range(0, len(entries), CLUSTERS_PER_CALL):
        batch = entries[i:i + CLUSTERS_PER_CALL]
        got, itok, otok = call_llm(batch)
        labels.update(got)
        tot_in += itok; tot_out += otok
        print(f"[label-clusters] {i + len(batch)}/{len(entries)} · +{len(got)} labels · "
              f"running ${_cost(tot_in, tot_out):.3f}", file=sys.stderr)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write(f"# LLM-proposed labels for domain_clusters.tsv's numbered clusters ({MODEL}). Labels are\n"
                 f"# a convenience NAME for a cluster formed by clean signals — the LLM did not decide\n"
                 f"# membership. See label_domain_clusters.py.\n")
        fh.write("cluster_id\tlabel\tsize\tsample_glosses\n")
        for cid in cluster_ids:
            label = labels.get(cid, "")
            sample = ", ".join(glosses.get(s, s) for s in clusters[cid][:8])
            fh.write(f"{cid}\t{label}\t{len(clusters[cid])}\t{sample}\n")
    print(f"[label-clusters] DONE · {len(labels)}/{len(entries)} labeled · "
          f"est cost ${_cost(tot_in, tot_out):.3f} ({MODEL}) -> {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
