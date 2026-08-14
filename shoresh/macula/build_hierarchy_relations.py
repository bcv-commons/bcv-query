#!/usr/bin/env python3
"""DIRECTIONAL BHSA relations for the hierarchy DAG (Phase B step 6, internal-docs/
text-anchored-semantics-plan.md) — the parts of BHSA's own tree structure that
build_bhsa_structural_pairs.py deliberately discards by collapsing every pair to an unordered
frozenset. Three relations, all from live Context-Fabric access (needs the BHSA corpus mounted):

  apposition (phrase_atom rela=Appo): "the man, the prophet" -- the phrase_atom marked Appo is the
    APPOSITIVE (the narrower/restating term), its `mother` is the HEAD. Same underlying construction
    build_bhsa_structural_pairs.py already extracts, but kept DIRECTIONAL here (head, appositive)
    instead of collapsed to a symmetric pair -- candidate IS-A evidence: appositive often narrows or
    restates the head, e.g. "David (head), the king (appositive)".

  construct chains (subphrase rela=rec): Hebrew smikhut, e.g. "house of David" (beyt David). The
    subphrase marked `rec` is the RECTUM (the governed/genitive dependent, "David"), its `mother` is
    the REGENS (the construct-state governing word, "house"). Kind/part evidence, not IS-A -- "house
    of David" doesn't mean David is a house. Directional for the same underlying reason apposition is.

  clause `mother` (clause-level dependency, candidate #6 in the export-candidates list, described in
    2026-08 sessions as "parked... never extracted anywhere in this codebase" until now): which
    clause grammatically depends on which, and how (Attr/Adju/Coor/Objc/...). 20,791 of 88,131 OT
    clauses (24%) carry a mother. This is DISCOURSE structure, not a word-pair signal -- built and
    persisted here as a standalone resource for future use, NOT combined into the word-hierarchy DAG
    (build_hierarchy_dag.py) the way apposition direction is -- see that script's docstring for why.

  python -m macula.build_hierarchy_relations
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HBO = ROOT / "resources" / "occurrences" / "hbo.db"
OUT_DIR = ROOT / "resources" / "bhsa_hierarchy"
BHSA_PATH = Path.home() / "text-fabric-data" / "github" / "ETCBC" / "bhsa" / "tf" / "2021"

CONTENT_SP = {"subs", "verb", "adjv"}
NUMERAL_LS = {"card", "ordn", "mult"}   # BHSA `ls` (lexical subset) values for cardinal/ordinal/
                                        # multiplicative numbers -- e.g. "a thousand" as an apposition
                                        # side is grammatically real but not meaningful hierarchy
                                        # content. Checked 2026-08-15: 3.3% of content words carry one
                                        # of these tags, a small and targeted exclusion.


def _load_api():
    import cfabric

    CF = cfabric.Fabric(locations=str(BHSA_PATH), silent="deep")
    return CF.loadAll(silent="deep")


def _content_word(node, F, node2strong) -> str | None:
    sp = F.sp.v(node)
    s = node2strong.get(node)
    if s and sp in CONTENT_SP and F.ls.v(node) not in NUMERAL_LS:
        return s if s.startswith("H") else f"H{int(s):04d}"
    return None


def _content_words(node, F, L, node2strong) -> list[str]:
    return [hs for w in L.d(node, otype="word") if (hs := _content_word(w, F, node2strong))]


def extract_apposition(api, node2strong) -> collections.Counter:
    """Counter[(head_strong, appositive_strong)] -> count. All-cross-product (see
    build_bhsa_structural_pairs.py's 2026-08-15 finding: no real quality cost vs. single-word-only)."""
    F, E, L = api.F, api.E, api.L
    out: collections.Counter = collections.Counter()
    for n in F.otype.s("phrase_atom"):
        if F.rela.v(n) != "Appo":
            continue
        m = E.mother.f(n)
        if not m:
            continue
        mo = m[0]
        head_words = [_content_word(mo, F, node2strong)] if F.otype.v(mo) == "word" \
            else _content_words(mo, F, L, node2strong)
        head_words = [w for w in head_words if w]
        appo_words = _content_words(n, F, L, node2strong)
        for h in head_words:
            for a in appo_words:
                if h != a:
                    out[(h, a)] += 1
    return out


def extract_construct(api, node2strong) -> collections.Counter:
    """Counter[(regens_strong, rectum_strong)] -> count -- construct-chain (smikhut) pairs. The
    regens (mother) is very often a bare `word` node, not a multi-word span -- L.d(word, "word")
    returns nothing for a word node (same gotcha as apposition's head, see extract_apposition)."""
    F, E, L = api.F, api.E, api.L
    out: collections.Counter = collections.Counter()
    for n in F.otype.s("subphrase"):
        if F.rela.v(n) != "rec":
            continue
        m = E.mother.f(n)
        if not m:
            continue
        mo = m[0]
        regens_words = [_content_word(mo, F, node2strong)] if F.otype.v(mo) == "word" \
            else _content_words(mo, F, L, node2strong)
        regens_words = [w for w in regens_words if w]
        rectum_words = _content_words(n, F, L, node2strong)
        for r in regens_words:
            for c in rectum_words:
                if r != c:
                    out[(r, c)] += 1
    return out


def extract_clause_mother(api) -> list[tuple[str, str, str]]:
    """[(dependent_ref, mother_ref, rela)] -- clause-level dependency, verse-addressable."""
    F, E, T = api.F, api.E, api.T
    out = []
    for cl in F.otype.s("clause"):
        m = E.mother.f(cl)
        if not m:
            continue
        rela = F.rela.v(cl) or ""
        dep_ref = "%s %s:%s" % T.sectionFromNode(cl)
        mom_ref = "%s %s:%s" % T.sectionFromNode(m[0])
        out.append((dep_ref, mom_ref, rela))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    api = _load_api()
    hbo = sqlite3.connect(f"file:{HBO}?mode=ro", uri=True)
    node2strong = dict(hbo.execute("SELECT node, strong FROM occurrence WHERE strong IS NOT NULL"))

    args.out_dir.mkdir(parents=True, exist_ok=True)

    appo = extract_apposition(api, node2strong)
    print(f"[hierarchy] apposition (directional): {len(appo)} distinct (head, appositive) pairs, "
          f"{sum(appo.values())} occurrences", file=sys.stderr)
    with (args.out_dir / "apposition_directed.tsv").open("w", encoding="utf-8") as fh:
        fh.write("# Directional BHSA apposition: head -> appositive (candidate IS-A / narrowing "
                  "evidence). See build_hierarchy_relations.py.\n")
        fh.write("head_strong\tappositive_strong\tcount\n")
        for (h, a), cnt in sorted(appo.items(), key=lambda kv: -kv[1]):
            fh.write(f"{h}\t{a}\t{cnt}\n")

    construct = extract_construct(api, node2strong)
    print(f"[hierarchy] construct chains (directional): {len(construct)} distinct (regens, rectum) "
          f"pairs, {sum(construct.values())} occurrences", file=sys.stderr)
    with (args.out_dir / "construct_pairs.tsv").open("w", encoding="utf-8") as fh:
        fh.write("# Directional BHSA construct chains (smikhut): regens (governing) -> rectum "
                  "(dependent/genitive). Kind/part evidence, NOT IS-A. See build_hierarchy_relations.py.\n")
        fh.write("regens_strong\trectum_strong\tcount\n")
        for (r, c), cnt in sorted(construct.items(), key=lambda kv: -kv[1]):
            fh.write(f"{r}\t{c}\t{cnt}\n")

    clause_mother = extract_clause_mother(api)
    print(f"[hierarchy] clause mother: {len(clause_mother)} dependent clauses", file=sys.stderr)
    with (args.out_dir / "clause_mother.tsv").open("w", encoding="utf-8") as fh:
        fh.write("# BHSA clause-level dependency (candidate #6, never built before 2026-08-15): "
                  "dependent_ref depends on mother_ref via `rela`. Discourse structure, not a "
                  "word-pair signal -- see build_hierarchy_relations.py.\n")
        fh.write("dependent_ref\tmother_ref\trela\n")
        for dep, mom, rela in clause_mother:
            fh.write(f"{dep}\t{mom}\t{rela}\n")

    print(f"[hierarchy] -> {args.out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
