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
sys.path.insert(0, str(HERE.parents[0]))
from references import encode  # noqa: E402

HBO = ROOT / "resources" / "occurrences" / "hbo.db"
OUT_DIR = ROOT / "resources" / "bhsa_hierarchy"
BHSA_PATH = Path.home() / "text-fabric-data" / "github" / "ETCBC" / "bhsa" / "tf" / "2021"

# BHSA's own book-name convention (full English name, underscored multi-word) -> this project's USFM
# codes, needed to compute BBCCCVVV for clause_mother.tsv's new addressable columns. Verified all 39
# OT books round-trip cleanly (chiasm-pilot-plan.md's segmentation-fit work hit the same mapping need
# in the other direction).
_BHSA_TO_USFM = {
    "Genesis": "GEN", "Exodus": "EXO", "Leviticus": "LEV", "Numbers": "NUM", "Deuteronomy": "DEU",
    "Joshua": "JOS", "Judges": "JDG", "1_Samuel": "1SA", "2_Samuel": "2SA", "1_Kings": "1KI",
    "2_Kings": "2KI", "Isaiah": "ISA", "Jeremiah": "JER", "Ezekiel": "EZK", "Hosea": "HOS",
    "Joel": "JOL", "Amos": "AMO", "Obadiah": "OBA", "Jonah": "JON", "Micah": "MIC", "Nahum": "NAM",
    "Habakkuk": "HAB", "Zephaniah": "ZEP", "Haggai": "HAG", "Zechariah": "ZEC", "Malachi": "MAL",
    "Psalms": "PSA", "Job": "JOB", "Proverbs": "PRO", "Ruth": "RUT", "Song_of_songs": "SNG",
    "Ecclesiastes": "ECC", "Lamentations": "LAM", "Esther": "EST", "Daniel": "DAN", "Ezra": "EZR",
    "Nehemiah": "NEH", "1_Chronicles": "1CH", "2_Chronicles": "2CH",
}

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


def _node_text(node, F, L) -> str:
    """Hebrew word text for a word/phrase/clause node -- L.d(word, otype='word') is empty for a
    bare word node (same gotcha noted in extract_apposition/extract_construct above), so handle a
    word node directly rather than via L.d."""
    words = [node] if F.otype.v(node) == "word" else L.d(node, otype="word")
    text = "".join((F.g_word_utf8.v(w) or "") + (F.trailer_utf8.v(w) or "") for w in words)
    return " ".join(text.split())  # collapses any stray tab/newline in trailer text -- a TSV row
                                    # (see chiasm_pilot's earlier embedded-newline bug) must not
                                    # carry one, and this also normalizes visual whitespace/maqaf runs


def _node_bbcccvvv(node, T) -> tuple[int, int]:
    """(start, end) BBCCCVVV -- a single verse for every node type seen here (clause/phrase/word
    are all verse-nested in BHSA, confirmed by T.sectionFromNode never returning a multi-verse
    span), so start == end. USFM_TO_BHSA's inverse; unmapped book (shouldn't happen, OT-only
    corpus) falls back to (0, 0), never raises."""
    book, ch, vs = T.sectionFromNode(node)
    usfm = _BHSA_TO_USFM.get(book)
    if usfm is None:
        return 0, 0
    bb = encode(usfm, ch, vs)
    return bb, bb


def extract_clause_mother(api) -> list[tuple]:
    """[(dependent_node, dependent_ref, dependent_start_bbcccvvv, dependent_end_bbcccvvv,
    dependent_text, mother_node, mother_otype, mother_ref, mother_start_bbcccvvv,
    mother_end_bbcccvvv, mother_text, rela)] -- clause-level dependency.

    FIXED 2026-09-24 (internal-docs/clause-dependency-graph-plan.md): the original version keyed
    rows on T.sectionFromNode()'s verse-level ref alone, which collapses 95.7% of rows to (self,
    self) noise whenever a clause's mother sits in the same verse -- the common case. Now keyed on
    the raw BHSA node ids (same anchor convention as hbo.db's word `node` and hbo_syntax.db's phrase
    `node`), with the verse-level ref kept as a human-readable label only.

    `mother_otype`: a clause's `mother` edge is NOT always another clause -- checked directly against
    the live corpus: 13,917 clause->clause, 5,305 clause->phrase, 1,569 clause->word (0 with >1
    mother; 0 cycles in the clause->clause subset, i.e. that subset is a genuine forest). A dependent
    clause can depend on a specific phrase or word inside another clause (e.g. a relative clause
    modifying one noun phrase), not only on "the other clause" as a whole -- recorded, not collapsed.

    EXTENDED 2026-09-2X (for the clause_dependency_lookup MCP tool): `*_text` and `*_bbcccvvv`
    columns, precomputed here (where cfabric access already lives) rather than at ingest/serve time
    in bcv-RAG, which has neither BHSA access nor a use for it elsewhere -- same "compute once at
    build time, serve cheaply from SQL" split as every other bcv-RAG-consumed resource.
    """
    F, E, L, T = api.F, api.E, api.L, api.T
    out = []
    for cl in F.otype.s("clause"):
        m = E.mother.f(cl)
        if not m:
            continue
        mother = m[0]
        rela = F.rela.v(cl) or ""
        dep_ref = "%s %s:%s" % T.sectionFromNode(cl)
        mom_ref = "%s %s:%s" % T.sectionFromNode(mother)
        dep_bb = _node_bbcccvvv(cl, T)
        mom_bb = _node_bbcccvvv(mother, T)
        out.append((cl, dep_ref, dep_bb[0], dep_bb[1], _node_text(cl, F, L),
                     mother, F.otype.v(mother), mom_ref, mom_bb[0], mom_bb[1],
                     _node_text(mother, F, L), rela))
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
    n_same_ref = sum(1 for row in clause_mother if row[1] == row[7])
    print(f"[hierarchy] clause mother: {len(clause_mother)} dependent clauses "
          f"({n_same_ref} same-verse-ref as their mother -- distinguishable now via node id, "
          f"see header)", file=sys.stderr)
    with (args.out_dir / "clause_mother.tsv").open("w", encoding="utf-8") as fh:
        fh.write("# BHSA clause-level dependency (candidate #6). dependent_node depends on\n"
                  "# mother_node via `rela`. Discourse structure, not a word-pair signal -- see\n"
                  "# build_hierarchy_relations.py. mother_otype: a mother is not always a clause\n"
                  "# (13,917 clause / 5,305 phrase / 1,569 word, checked directly) -- a dependent\n"
                  "# clause can depend on one specific phrase/word inside another clause, not just\n"
                  "# \"the other clause\" as a whole. FIXED 2026-09-24: rows now keyed on the raw BHSA\n"
                  "# node id (same anchor convention as hbo.db/hbo_syntax.db's `node`), not the\n"
                  "# verse-level ref alone -- the earlier version collapsed 95.7% of rows to\n"
                  "# same-ref noise whenever a clause's mother sat in the same verse (the common\n"
                  "# case), making same-verse relations unresolvable. *_ref columns are for human\n"
                  "# reading only; join/distinguish on the *_node columns. *_bbcccvvv/*_text added\n"
                  "# for the clause_dependency_lookup MCP tool (bcv-RAG). CAVEAT, read before use:\n"
                  "# a long flat coordinated list (Coor chains, e.g. a genealogy/name roster) chains\n"
                  "# just as deep as genuine narrative subordination -- depth alone does not mean\n"
                  "# discourse nesting, checked directly (1 Chronicles 11:27's roster of names is\n"
                  "# this file's single deepest chain, depth 19, all-Coor).\n")
        fh.write("dependent_node\tdependent_ref\tdependent_start_bbcccvvv\tdependent_end_bbcccvvv\t"
                  "dependent_text\tmother_node\tmother_otype\tmother_ref\tmother_start_bbcccvvv\t"
                  "mother_end_bbcccvvv\tmother_text\trela\n")
        for row in clause_mother:
            fh.write("\t".join(str(v) for v in row) + "\n")

    print(f"[hierarchy] -> {args.out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
