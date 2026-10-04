#!/usr/bin/env python3
"""Build the served Hebrew semantic groups, resources/semantic_groups/ (CC0), which replace SDBH's
`core`/`ctx` axes in shoresh /verse, /wordstudy and /domain.

Groups are the CC0 domain clusters (Louvain over the semantic-neighbors graph). Each word is served the
group holding most of its occurrences, if that group holds at least 60% of them (the same gate
`_dominant_domain` applied to SDBH). Each membership carries a confidence: `high` if the word has at least
one embedding-confirmed (anchor=high) unit in that group, else `extended`. Clients that want the most
precise labels filter to `high`.

Labels are Hebrew: a group is named by its most frequent served member (pointed lemma). An English
reading aid is kept separately; shoresh localizes it per request and appends it only when asked.

Chosen and measured with the usability scorecard (internal-docs/usability-scorecard.md): served with the
confidence flag, these groups kept 0.91-0.93 of the SDBH labels' label-fit usefulness on the locked test
split, with 93% of content tokens labelled (SDBH: 41%).

Sources:
  --source bhsa-free-served  shoresh/macula/data/bhsa_free/served/domain_clusters.tsv (default since
                       2026-10-04): bhsa-free-routed plus --no-corroborated (the corroborated family rests on
                       Wiktionary roots, CC BY-SA, so it stays out of the CC0 lineage) and a fixed hash seed
                       (reproducible builds). Label fit 86.7% vs 87.6% with those edges (dev, seed-matched,
                       within hash-seed noise)
  --source bhsa-free-routed  shoresh/macula/data/bhsa_free/routed/domain_clusters.tsv (2026-10-03):
                       the BHSA-free build with --route-homographs, so Strong's-level evidence
                       (BDB roots, LLM pairs) attaches only to the matching MACULA homograph (fixes Ps 23:1
                       רֹעִי "my shepherd" being labelled רֵעַ "neighbor"); scorecard-neutral on dev
  --source bhsa-free   shoresh/macula/data/bhsa_free/domain_clusters.tsv (no
                       BHSA input, so no non-commercial data in the CC0 lineage; on the locked test split
                       it kept 0.95-0.96 of the SDBH labels' label-fit usefulness, vs 0.91-0.93 for production)
  --source production  resources/semantic_neighbors/domain_clusters.tsv (BHSA-derived signals)

Full BHSA-free rebuild (outputs under shoresh/macula/data/bhsa_free/, gitignored):
  cd shoresh
  .venv/bin/python3 -m macula.build_bhsa_free_contexts
  .venv/bin/python3 -m macula.build_semantic_neighbors --emb macula/data/bhsa_free/context_emb_berel.npz \
      --macula-contexts macula/data/bhsa_free/occurrence.db --no-structural --parallelism-tomim-only \
      --no-xling --no-corroborated --route-homographs --emb-label "BEREL word-window centroids (MACULA, BHSA-free)" \
      --out-dir macula/data/bhsa_free/served
  .venv/bin/python3 -m macula.build_domain_clusters --neighbors macula/data/bhsa_free/served/by_lexeme.tsv \
      --out macula/data/bhsa_free/served/domain_clusters.tsv
  (both builders fix PYTHONHASHSEED=0 themselves; two runs are byte-identical)
  .venv/bin/python3 -m macula.build_semantic_groups
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from macula import domain_providers as dp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "resources" / "semantic_groups"


def live_gloss(strong: str) -> str:
    """The served gloss table (spine/spine_glosses.tsv) — not the scorecard's frozen copy."""
    import sys as _sys
    _sys.path.insert(0, str(HERE.parent))
    import data
    return ((data.gloss_of(strong) or {}).get("gloss")) or ""


def build(source: str) -> tuple[list[tuple], dict[str, tuple], str]:
    counts, lemmas = dp.token_counts(), dp.lemma_of()
    if source in ("bhsa-free", "bhsa-free-routed", "bhsa-free-served"):
        occ, glosses = dp.lexeme_occurrences_nb()
        path = {"bhsa-free-served": dp.BHSA_FREE / "served" / "domain_clusters.tsv",
                "bhsa-free-routed": dp.BHSA_FREE / "routed" / "domain_clusters.tsv"}.get(source, dp.CLUSTERS_NB)
        provenance = ("BEREL word-window centroids over MACULA text, no BHSA input (build_bhsa_free_contexts + "
                      "build_semantic_neighbors --macula-contexts"
                      + {"bhsa-free-served": " --route-homographs --no-corroborated: no Wiktionary input)",
                         "bhsa-free-routed": " --route-homographs)"}.get(source, ")"))
    else:
        occ, glosses = dp.unit_occurrences()
        path, provenance = dp.CLUSTERS, "resources/semantic_neighbors/domain_clusters.tsv (production pack)"
    rows_all, sense_gloss = dp.build_clusters(False, occ, glosses, path)
    rows_high, _ = dp.build_clusters(True, occ, glosses, path)
    high = {(s, g) for s, _a, g, _sh, _sv in rows_high}

    members = [(s, g, sh, sv, "high" if (s, g) in high else "extended") for s, _a, g, sh, sv in rows_all]
    ex = dp.exemplar_labels(rows_all, counts, lemmas)
    # MACULA and the spine's Strong's tagging disagree for a few words (MACULA files אֱנוֹשׁ as H0582,
    # the spine as H0376/H0583), leaving the spine with no lemma; take MACULA's own lemma then.
    sp = dp._ro(dp.LEXEME_SPINE)
    for g, (ls, ll) in list(ex.items()):
        if not ll and ls[1:].isdigit():
            row = sp.execute("SELECT lemma FROM spine_words WHERE lexeme LIKE ? AND lemma IS NOT NULL "
                             "GROUP BY lemma ORDER BY COUNT(*) DESC LIMIT 1",
                             (f"hbo:{int(ls[1:]):04d}%",)).fetchone()
            if row:
                ex[g] = (ls, row[0])
    groups = {g: (ls, ll, dp.clean_gloss(sense_gloss.get((ls, g)) or live_gloss(ls)))
              for g, (ls, ll) in ex.items()}
    return members, groups, provenance


def write(members: list[tuple], groups: dict[str, tuple], provenance: str, out: Path = OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    n_served = collections.Counter(g for _s, g, _sh, sv, _c in members if sv)
    n_high = collections.Counter(g for _s, g, _sh, sv, c in members if sv and c == "high")
    header = (f"# Hebrew semantic groups (CC0). Source: {provenance}. "
              "Built by shoresh/macula/build_semantic_groups.py.\n")
    with (out / "hbo_members.tsv").open("w", encoding="utf-8") as fh:
        fh.write(header + "strong\tgroup_id\tshare\tserved\tconfidence\n")
        for s, g, sh, sv, c in sorted(members):
            fh.write(f"{s}\t{g}\t{sh}\t{sv}\t{c}\n")
    with (out / "hbo_groups.tsv").open("w", encoding="utf-8") as fh:
        fh.write(header + "group_id\tlabel_strong\tlabel_lemma\tgloss_en\tn_served\tn_high\n")
        for g in sorted(groups, key=lambda x: int(x[1:]) if x[1:].isdigit() else x):
            ls, ll, gl = groups[g]
            fh.write(f"{g}\t{ls}\t{ll}\t{gl}\t{n_served[g]}\t{n_high[g]}\n")
    print(f"[semantic-groups] {sum(n_served.values())} served words in {len(groups)} groups "
          f"({sum(n_high.values())} high-confidence) -> {out}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["production", "bhsa-free", "bhsa-free-routed", "bhsa-free-served"],
                    default="bhsa-free-served")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    members, groups, provenance = build(args.source)
    write(members, groups, provenance, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
