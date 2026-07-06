#!/usr/bin/env python3
"""Phase B of languages.db — data-derived relatedness edges for the registry.

For each language, the top-K nearest relatives, ranked by GENETIC distance from the Glottolog
classification tree (shared-ancestor depth), with GEOGRAPHIC distance (Glottolog lat/long) as
the tiebreak among genetically-equidistant siblings. Replaces the curated `basis=curated`
bootstrap in related_langs/ with `basis=genetic-glottolog`.

Why Glottolog rather than URIEL/lang2vec (which the design note names): Glottolog covers ALL
~7,800 classified languages (URIEL ~4,000) with no heavy dependency, and its genetic distance
IS tree-derived — the same signal. URIEL's *typological/lexical* distance is a future layer
(add edges with a distinct `basis`, blend at query time); the `basis` column keeps them separable.

Reads resources/languages/languages.tsv (Phase A) + the cached Glottolog source. Emits
resources/languages/related.tsv:  iso639_3 · rank · related_iso639_3 · distance · basis

  python -m scripts.build_language_relatedness            # from the _raw/ cache (built by Phase A)
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "resources" / "languages"
RAW = OUT / "_raw"

TOP_K = 25


def _rows(path: Path, delim: str) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=delim))


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    (lat1, lon1), (lat2, lon2) = a, b
    r1, r2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(r1) * math.cos(r2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))       # km


def build() -> None:
    reg = _rows(OUT / "languages.tsv", "\t")
    glot = {g["ID"]: g for g in _rows(RAW / "glottolog.csv", ",")}
    gvalues = _rows(RAW / "glottolog_values.csv", ",")
    class_by_glotto = {v["Language_ID"]: v["Value"].split("/")
                       for v in gvalues if v["Parameter_ID"] == "classification" and v["Value"]}

    # Per language (that has a classification): its ancestor path + geo point + stock.
    langs: dict[str, dict] = {}
    for r in reg:
        gc = r["glottocode"]
        path = class_by_glotto.get(gc)
        if not path:                                   # no genealogy → no genetic relatives
            continue
        grow = glot.get(gc, {})
        try:
            geo = (float(grow["Latitude"]), float(grow["Longitude"]))
        except (KeyError, ValueError):
            geo = None
        langs[r["iso639_3"]] = {"path": path, "geo": geo, "stock": path[0]}

    # Candidates share a stock (top-level family). Compare only within a stock — genetic
    # relatedness across families is 0, and it keeps the pairwise work near-linear per family.
    by_stock: dict[str, list[str]] = {}
    for code, info in langs.items():
        by_stock.setdefault(info["stock"], []).append(code)

    edges: list[tuple[str, int, str, float, str]] = []
    for stock, codes in by_stock.items():
        if len(codes) < 2:
            continue
        for a in codes:
            pa, ga = langs[a]["path"], langs[a]["geo"]
            scored = []
            for b in codes:
                if b == a:
                    continue
                pb = langs[b]["path"]
                shared = 0
                for x, y in zip(pa, pb):
                    if x != y:
                        break
                    shared += 1
                tree_dist = (len(pa) - shared) + (len(pb) - shared)   # steps A→LCA→B
                gb = langs[b]["geo"]
                geo_dist = _haversine(ga, gb) if (ga and gb) else float("inf")
                scored.append((tree_dist, geo_dist, b))
            scored.sort(key=lambda t: (t[0], t[1]))
            for rank, (tree_dist, _geo, b) in enumerate(scored[:TOP_K], start=1):
                edges.append((a, rank, b, float(tree_dist), "genetic-glottolog"))

    edges.sort(key=lambda e: (e[0], e[1]))
    with (OUT / "related.tsv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["iso639_3", "rank", "related_iso639_3", "distance", "basis"])
        for a, rank, b, dist, basis in edges:
            w.writerow([a, rank, b, dist, basis])

    n_langs = len({e[0] for e in edges})
    print(f"related.tsv: {len(edges)} edges for {n_langs} languages "
          f"(top-{TOP_K} each; {len(langs)} classified, "
          f"{len(langs) - n_langs} with no same-stock relative)", file=sys.stderr)


if __name__ == "__main__":
    build()
    raise SystemExit(0)
