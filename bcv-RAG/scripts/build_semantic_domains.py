"""Build the lexeme-level Strong's → semantic-domain tables (S2 / Phase 1).

Aggregates MACULA's per-occurrence domain data into a clean lexeme table so
concept retrieval can broaden a Strong's to its semantic domain(s).

Schema (both langs): strong, domain_type, domain, label, count, share
  share = count / the lexeme's domain-tagged total WITHIN that (strong,type);
  sorted by strong, domain_type, count desc (primary domain first).
Consumers pick a `domain_type`:
  grc → "sdbg"  (Louw-Nida / SDBG, one axis)
  hbo → "core" | "lex" | "ctx"  (SDBH's three axes — core is the concept axis)

Sources (CC BY 4.0, Biblica + UBS MARBLE attribution):
  grc  macula-greek  Nestle1904/tsv/macula-greek-Nestle1904.tsv  (col `strong` + `domain`)
       labels: sources/MARBLE/SDBG/marble-domain-label-mapping.json
  hbo  macula-hebrew sources/MARBLE/SDBH/macula-marble-domains.xml  ← the SOURCE
       (Lex/Core/Contextual domains; the WLC convenience TSV ships STALE codes —
        the source XML has the current ones). Strong's comes from the WLC TSV,
        joined on maculaId (= TSV xml:id minus the 'o'/'n' prefix).
       labels: domain-label-mapping-1.json (LexDomain, deep codes)
               domain-label-mapping-2.json (Core + Contextual, short codes)
NOTE: SDBG (Greek) and SDBH (Hebrew) are different taxonomies — codes are not
cross-comparable. Cross-language linking stays lexical (lxx_bridge.tsv).

Usage (with cached files):
  python -m scripts.build_semantic_domains --lang grc \
      --tsv /tmp/macula-greek.tsv --labels /tmp/sdbg.json
  python -m scripts.build_semantic_domains --lang hbo \
      --domains /tmp/domains.xml --tsv /tmp/macula-hebrew.tsv \
      --labels1 /tmp/sdbh1.json --labels2 /tmp/sdbh2.json
(omit a path to download it.)
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import re
import sys
from pathlib import Path

import httpx

RAW_G = "https://raw.githubusercontent.com/Clear-Bible/macula-greek/main"
RAW_H = "https://raw.githubusercontent.com/Clear-Bible/macula-hebrew/main"
MED_H = "https://media.githubusercontent.com/media/Clear-Bible/macula-hebrew/main"
URLS = {
    "grc_tsv": f"{RAW_G}/Nestle1904/tsv/macula-greek-Nestle1904.tsv",
    "grc_labels": f"{RAW_G}/sources/MARBLE/SDBG/marble-domain-label-mapping.json",
    "hbo_domains": f"{RAW_H}/sources/MARBLE/SDBH/macula-marble-domains.xml",
    "hbo_tsv": f"{MED_H}/WLC/tsv/macula-hebrew.tsv",
    "hbo_labels1": f"{RAW_H}/sources/MARBLE/SDBH/domain-label-mapping-1.json",
    "hbo_labels2": f"{RAW_H}/sources/MARBLE/SDBH/domain-label-mapping-2.json",
}
MIN_COUNT = 2


def _text(url: str, cached: str) -> str:
    if cached:
        return Path(cached).read_text(encoding="utf-8")
    print(f"downloading {url} …", file=sys.stderr)
    r = httpx.get(url, timeout=300.0, follow_redirects=True)
    r.raise_for_status()
    return r.text


def _norm(prefix: str, s: str) -> str | None:
    m = re.match(r"(\d+)", s.strip())          # drop homonym suffix (0871a -> 0871)
    return f"{prefix}{int(m.group(1)):04d}" if m else None


def _label(labels: dict, code: str) -> str:
    if code in labels:
        return labels[code]
    c = code                                    # walk up the hierarchy on a miss
    while len(c) > 3 and len(c) % 3 == 0:
        c = c[:-3]
        if c in labels:
            return labels[c]
    return ""


def _agg_rows(agg: dict, labelers: dict) -> list:
    """agg[(strong, dtype)][code] = count → list of (strong, dtype, code, label, count, share)."""
    rows = []
    for (s, dtype), counter in agg.items():
        total = sum(counter.values())
        for i, (code, n) in enumerate(counter.most_common()):
            if i == 0 or n >= MIN_COUNT:     # always keep the primary domain per axis
                rows.append((s, dtype, code, _label(labelers[dtype], code), n, round(n / total, 3)))
    return rows


def _bridge_rows(grc_path: str, bridge_path: str) -> list:
    """SDBG-via-LXX-bridge rows for Hebrew: H → greekstrong → Greek SDBG domain,
    pooled across renderings. Fills native-SDBH gaps + unifies on SDBG."""
    greek_dom: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    greek_label: dict[str, str] = {}
    with open(grc_path, encoding="utf-8") as f:
        next(f)
        for line in f:
            s, dtype, code, label, count, share = line.rstrip("\n").split("\t")
            if dtype == "sdbg":
                greek_dom[s][code] += int(count)
                greek_label[code] = label
    bridge: dict[str, list] = collections.defaultdict(list)
    with open(bridge_path, encoding="utf-8") as f:
        next(f)
        for line in f:
            h, g, c = line.rstrip("\n").split("\t")
            bridge[h].append((g, int(c)))
    rows = []
    for h, greeks in bridge.items():
        wf: dict[str, float] = collections.defaultdict(float)
        for g, bc in greeks:
            gd = greek_dom.get(g)
            if not gd:
                continue
            gtot = sum(gd.values())
            for code, gc in gd.items():
                wf[code] += bc * (gc / gtot)       # bridge weight × that domain's share in the Greek lexeme
        if not wf:
            continue
        total = sum(wf.values())
        for i, (code, w) in enumerate(sorted(wf.items(), key=lambda x: -x[1])):
            if i == 0 or w / total >= 0.15:        # primary + meaningful secondaries
                rows.append((h, "sdbg", code, greek_label.get(code, ""), max(1, round(w)), round(w / total, 3)))
    return rows


def _write_rows(out: Path, rows: list) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (r[0], r[1], -r[4]))   # strong, domain_type, count desc
    unlabeled = sum(1 for r in rows if not r[3])
    lexemes = len({r[0] for r in rows})
    with out.open("w", encoding="utf-8") as f:
        f.write("strong\tdomain_type\tdomain\tlabel\tcount\tshare\n")
        for s, dtype, code, lab, n, share in rows:
            f.write(f"{s}\t{dtype}\t{code}\t{lab}\t{n}\t{share}\n")
    print(f"  wrote {out}: {lexemes} lexemes, {len(rows)} rows, {unlabeled} unlabeled")


def build_grc(args) -> None:
    labels = json.loads(_text(URLS["grc_labels"], args.labels))
    agg: dict = collections.defaultdict(collections.Counter)
    n = 0
    for r in csv.DictReader(io.StringIO(_text(URLS["grc_tsv"], args.tsv)), delimiter="\t"):
        n += 1
        s = _norm("G", r.get("strong") or "")
        d = (r.get("domain") or "").strip()
        if s and d:
            for code in d.split():
                agg[(s, "sdbg")][code] += 1
    print(f"[grc] scanned {n} rows")
    _write_rows(Path(args.out or "resources/semantic_domains/grc.tsv"),
                _agg_rows(agg, {"sdbg": labels}))


def build_hbo(args) -> None:
    m1 = json.loads(_text(URLS["hbo_labels1"], args.labels1))   # LexDomain
    m2 = json.loads(_text(URLS["hbo_labels2"], args.labels2))   # Core + Contextual
    # maculaId -> strong, from the WLC TSV (xml:id = <o|n> + maculaId)
    mid2strong: dict[str, str] = {}
    for r in csv.DictReader(io.StringIO(_text(URLS["hbo_tsv"], args.tsv)), delimiter="\t"):
        xid = (r.get("xml:id") or "").strip()
        s = _norm("H", r.get("strongnumberx") or "")
        if xid and s:
            mid2strong[xid[1:]] = s            # drop the leading o/n
    # stream the SOURCE domains XML (current codes) and aggregate per (strong, axis)
    agg: dict = collections.defaultdict(collections.Counter)
    axes = (("LexDomain", "lex"), ("CoreDomain", "core"), ("ContextualDomain", "ctx"))
    n = matched = 0
    for line in io.StringIO(_text(URLS["hbo_domains"], args.domains)):
        mid = re.search(r'maculaId="(\d+)"', line)
        if not mid:
            continue
        n += 1
        s = mid2strong.get(mid.group(1))
        if not s:
            continue
        matched += 1
        for attr, dtype in axes:
            m = re.search(attr + r'="([^"]*)"', line)
            if m and m.group(1).strip():
                for code in m.group(1).split():
                    # `A>B` (HTML-escaped) is a domain EXTENSION (metaphor etc.);
                    # collapse to the base domain A for clean concept grouping.
                    base = code.replace("&gt;", ">").split(">")[0]
                    agg[(s, dtype)][base] += 1
    print(f"[hbo] scanned {n} source morphs, {matched} joined to a Strong's")
    rows = _agg_rows(agg, {"lex": m1, "core": m2, "ctx": m2})
    if args.with_bridge:
        br = _bridge_rows(args.grc or "resources/semantic_domains/grc.tsv",
                          args.bridge or "resources/lxx_bridge.tsv")
        print(f"[hbo] + bridge→SDBG backfill: {len(br)} rows on "
              f"{len({r[0] for r in br})} Hebrew lexemes")
        rows += br
    _write_rows(Path(args.out or "resources/semantic_domains/hbo.tsv"), rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=["grc", "hbo"])
    ap.add_argument("--out", default="")
    ap.add_argument("--tsv", default="")
    ap.add_argument("--labels", default="")          # grc
    ap.add_argument("--domains", default="")          # hbo source XML
    ap.add_argument("--labels1", default="")          # hbo LexDomain
    ap.add_argument("--labels2", default="")          # hbo Core+Contextual
    ap.add_argument("--with-bridge", action="store_true",
                    help="hbo: also add SDBG domains via the LXX bridge (fills SDBH gaps + unifies)")
    ap.add_argument("--grc", default="")              # grc.tsv path for --with-bridge
    ap.add_argument("--bridge", default="")           # lxx_bridge.tsv path for --with-bridge
    args = ap.parse_args()
    (build_grc if args.lang == "grc" else build_hbo)(args)


if __name__ == "__main__":
    main()
