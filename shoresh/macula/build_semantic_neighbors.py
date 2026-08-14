#!/usr/bin/env python3
"""Build the CC0 semantic-neighbors pack — internal-docs/semantic-neighbors-pack.md.

Re-derives lexeme semantic proximity from CLEAN sources — a CC0 stand-in for the NC Louw-Nida/SDBH
domains, never touching the MARBLE taxonomy as an input. Hebrew/OT (the context embeddings are
Hebrew clauses). Anchor = MACULA `lexeme` (CC-BY, homograph-precise).

Signals (merged into a consensus):
  emb   — mean bge-m3 embedding of a lexeme's occurrence CLAUSES (distributional neighbors)   [primary]
  lxx   — two Hebrew lexemes the LXX renders into the SAME Greek Strong's (lxx_bridge.tsv)     [corroborate]
  gloss — lexemes whose English glosses share content words                                    [corroborate]

Output: resources/semantic_neighbors/neighbors.parquet (lexeme, neighbor_lexeme, score, sources) + a
manifest.json. CC0 (public texts + open model + CC-BY tables). --validate scores against the
text-anchored intrinsic yardstick (held-out BHSA slot-filler prediction, see intrinsic_yardstick.py) —
SDBH retired as the validation yardstick 2026-08-14, see internal-docs/text-anchored-semantics-plan.md.
Per-signal percentages quoted below in --no-* flag help are the historical SDBH-era record and are
pending re-derivation under the new yardstick.

  python -m macula.build_semantic_neighbors --validate
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import itertools
import json
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine.db"
BRIDGE = HERE / "bhsa-macula-bridge.db"
HBO = ROOT / "resources" / "occurrences" / "hbo.db"
EMB = ROOT / "resources" / "occurrences" / "context_emb.npz"
LXX = ROOT / "resources" / "lxx_bridge.tsv"
OUT_DIR = ROOT / "resources" / "semantic_neighbors"
LLM_EDGES = OUT_DIR / "llm_edges.tsv"        # method=llm layer (bcv-RAG/scripts/build_llm_neighbors.py)
ALIGNED_HF_DIR = ROOT / "resources" / "aligned_lex_hf"   # bcv-commons/lexeme-alignments, ~924 languages
BDB_ROOTS = ROOT / "resources" / "bdb_roots" / "root_groups.tsv"   # public-domain BDB etymological roots
PARALLELISM = ROOT / "resources" / "parallelism" / "parallelism_pairs.tsv"   # T'OMIM + our own detection
BHSA_STRUCTURAL = ROOT / "resources" / "bhsa_structural" / "structural_pairs.tsv"   # coordination+apposition
WIKTIONARY_ROOTS = ROOT / "resources" / "wiktionary_roots" / "root_pairs.tsv"   # weak alone; corroboration input
SEFER_HASHORASHIM = ROOT / "resources" / "sefer_hashorashim" / "llm_pair_verification.tsv"

MIN_OCC = 3        # a lexeme needs this many clause vectors for a stable centroid
TOPK = 10          # neighbors kept per lexeme
MIN_COS = 0.30     # cosine floor (post mean-centering scale)
XLING_MIN_LANGS = 3        # a Hebrew Strong's pair needs >= this many INDEPENDENT languages
                           # co-rendering it via the same surface to count as corroborated
XLING_MIN_COUNT = 2        # per-language quality floor, matches build_aligned_lex_hf.py's own bar
XLING_MIN_SHARE = 0.10
_STOP = set("the a an of to and in be is was were for from with his her its their this that "
            "he she it they them who which what will would shall not no".split())


STEP_SPINE = ROOT / "shoresh" / "spine" / "spine.db"   # STEPBible morph → proper-noun flag (CC-BY)


def proper_strongs() -> set:
    """H#### strongs that are proper nouns (STEPBible morph `Np` dominant) — excluded from the pack:
    they aren't semantic-field words, and LLMs chain genealogy/nation lists as bogus 'synonyms'.

    BUG FIXED 2026-08: spine.db's `strong` column is a bare integer shared across BOTH testaments
    (Hebrew H1746 and Greek G1746 are unrelated words that collide on the same digits) — the
    un-filtered query below used to mix Greek rows into the Np-majority vote for every Hebrew Strong's
    number that happens to collide with a Greek one, diluting real proper-name majorities below the
    50% threshold (verified: H1746 "Dumah" was 4/32 Np-tagged once 28 unrelated Greek verb rows were
    included, so it silently failed to get excluded). Filter to Hebrew-only rows via `morph LIKE
    'He,%'` — spine.db's own morph strings are language-prefixed ("He,..." / "Gr,...")."""
    if not STEP_SPINE.exists():
        return set()
    db = sqlite3.connect(f"file:{STEP_SPINE}?mode=ro", uri=True)
    tot, prop = collections.Counter(), collections.Counter()
    for strong, morph in db.execute(
            "SELECT strong, morph FROM spine_words WHERE strong IS NOT NULL AND morph LIKE 'He,%'"):
        s = f"H{int(strong):04d}"
        tot[s] += 1
        if morph and "Np" in morph:
            prop[s] += 1
    return {s for s in tot if prop[s] > 0.5 * tot[s]}


def non_content_strongs() -> set:
    """H#### strongs that spine.db's OWN (Hebrew-only) is_content majority-vote says are NOT content
    words, but lexeme-spine.db's MACULA-derived is_content=1 lets through anyway. Found 2026-08: MACULA
    tags Hebrew demonstrative pronouns (זֹאת "this", אֵלֶּה "these") as class='adj' (adjectival usage),
    and _CONTENT_CLASSES = {noun, verb, adj} doesn't distinguish that from genuine descriptive
    adjectives — 34 Strong's leak through this way (verified count). Cross-referencing spine.db's own
    is_content flag (computed independently, from STEPBible tagging, not MACULA's class field) catches
    these without needing to fix MACULA's class scheme itself."""
    if not STEP_SPINE.exists():
        return set()
    db = sqlite3.connect(f"file:{STEP_SPINE}?mode=ro", uri=True)
    tot, content = collections.Counter(), collections.Counter()
    for strong, is_content, morph in db.execute(
            "SELECT strong, is_content, morph FROM spine_words WHERE strong IS NOT NULL AND morph LIKE 'He,%'"):
        s = f"H{int(strong):04d}"
        tot[s] += 1
        content[s] += is_content
    return {s for s in tot if content[s] <= 0.5 * tot[s]}


def lexeme_vectors(emb_path: Path = EMB, sense_split: bool = False):
    """MACULA lexeme (or lexeme#sense, if sense_split) -> (unit centroid, strong, top gloss). Content
    lexemes with >= MIN_OCC clauses, proper nouns excluded. emb_path override lets this run against an
    alternative embedding model (e.g. BEREL) without touching the default bge-m3 file — dimension is
    read from the file itself, not assumed, since BEREL (768) and bge-m3 (1024) differ.

    sense_split: aggregate centroids per (lexeme, sense) instead of per whole lexeme, using hbo.db's
    own per-occurrence `sense` column (resources/senses/hbo_lex.tsv's cluster boundaries — Hebrew-
    context-embedding-derived, not MACULA/UBS — see bcv-commons-export-candidates.md). Rationale:
    Louw-Nida domains are assigned PER SENSE, not per word — a polysemous lexeme's one blended centroid
    (averaged across all its senses) structurally can't land near any single domain. Occurrences with
    no sense value (~47% of hbo.db) fall back to one shared '_nosense' bucket for that lexeme. LXX/gloss
    corroboration still applies per-STRONG (shared across all senses of a lexeme) — a known simplification,
    not sense-aware itself, but harmless since it only adds score, never gates which pairs are candidates."""
    proper = proper_strongs()
    non_content = non_content_strongs()
    z = np.load(emb_path, allow_pickle=True)
    V, C = z["vectors"], z["contexts"]                     # load each array ONCE (npz re-decompresses per access)
    dim = V.shape[1]
    clause_vec = {c: V[i] for i, c in enumerate(C)}        # clause text -> vector

    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    key2lex = {k: (lx, s) for k, lx, s, ic in sp.execute(
        "SELECT key, lexeme, strong, is_content FROM spine_words WHERE is_content=1 AND lexeme IS NOT NULL")}
    br = sqlite3.connect(f"file:{BRIDGE}?mode=ro", uri=True)
    node2lex = {}
    for node, key in br.execute("SELECT node, key FROM bridge"):
        if key in key2lex:
            node2lex[node] = key2lex[key]

    hbo = sqlite3.connect(f"file:{HBO}?mode=ro", uri=True)
    acc: dict = collections.defaultdict(lambda: [np.zeros(dim, np.float32), 0])
    strong_of, gloss_ct = {}, collections.defaultdict(collections.Counter)
    query = "SELECT node, context, gloss, sense FROM occurrence" if sense_split \
        else "SELECT node, context, gloss FROM occurrence"
    for row in hbo.execute(query):
        node, context, gloss = row[0], row[1], row[2]
        lx = node2lex.get(node)
        v = clause_vec.get(context)
        if lx is None or v is None:
            continue
        lexeme, strong = lx
        key = f"{lexeme}#{row[3]}" if sense_split and row[3] else (f"{lexeme}#_nosense" if sense_split else lexeme)
        acc[key][0] += v
        acc[key][1] += 1
        strong_of[key] = strong
        if gloss:
            gloss_ct[key][gloss] += 1

    lexemes, mat, meta = [], [], {}
    for key, (vsum, n) in acc.items():
        if n < MIN_OCC:
            continue
        c = vsum / n
        norm = np.linalg.norm(c)
        if norm == 0:
            continue
        s = strong_of[key]
        hstrong = f"H{s:04d}" if s is not None else ""
        if hstrong in proper:                       # drop proper nouns (names aren't semantic-field)
            continue
        if hstrong in non_content:                  # drop function words MACULA misclassified as content
            continue
        lexemes.append(key)
        mat.append(c / norm)
        top_gloss = gloss_ct[key].most_common(1)[0][0] if gloss_ct[key] else ""
        meta[key] = (hstrong, top_gloss)            # H#### to join lxx/domains
    return lexemes, np.vstack(mat).astype(np.float32), meta


def _gloss_tokens(g: str) -> set:
    return {w for w in re.findall(r"[a-z]+", (g or "").lower()) if w not in _STOP and len(w) > 2}


def build(validate: bool, llm_edges=None, emb_path: Path = EMB, out_dir: Path = OUT_DIR,
          emb_label: str = "bge-m3 clause centroids", sense_split: bool = False, use_xling: bool = True,
          use_bdb: bool = True, use_parallelism: bool = True, use_hwn: bool = False,
          use_structural: bool = True, use_corroborated: bool = True, use_sefer_hashorashim: bool = True):
    lexemes, M, meta = lexeme_vectors(emb_path, sense_split=sense_split)
    print(f"[neighbors] {len(lexemes)} content lexemes with >= {MIN_OCC} clauses", file=sys.stderr)
    # Mean-center to kill embedding anisotropy: clause centroids all lean toward one "generic biblical
    # clause" direction, which makes everything ~0.94 cosine. Subtracting the global mean removes that
    # shared component so the distinctive (word-meaning) directions dominate the kNN. Then re-normalize.
    M = M - M.mean(axis=0, keepdims=True)
    M /= (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)

    # LXX corroboration: Hebrew lexemes sharing a Greek Strong's (same-rendering) are near.
    greek_share: dict = collections.defaultdict(set)   # greek strong -> {hebrew lexeme}
    if LXX.exists():
        strong2lex = collections.defaultdict(list)
        for lx, (s, _) in meta.items():
            strong2lex[s].append(lx)
        for line in LXX.read_text(encoding="utf-8").splitlines()[1:]:
            p = line.split("\t")
            if len(p) >= 2:
                for lx in strong2lex.get(p[0].strip(), []):     # hebrew_strong is already "H####"
                    greek_share[p[1]].add(lx)
    lxx_pairs = set()
    for _, lxs in greek_share.items():
        lxs = list(lxs)
        for i in range(len(lxs)):
            for j in range(i + 1, len(lxs)):
                lxx_pairs.add(frozenset((lxs[i], lxs[j])))

    gloss_tok = {lx: _gloss_tokens(g) for lx, (_, g) in meta.items()}

    # method=llm layer (scholarly prior): strong-level syn/ant edges. Tier by AGREEMENT with the
    # empirical embedding signal — the LLM supplies synonymy the distributional signal can't, the
    # embedding grounds the LLM and catches hallucination. Keep them independent; agreement = trust.
    syn, ant = _load_llm_edges(llm_edges)
    strong2lex = collections.defaultdict(list)
    for lx, (s, _) in meta.items():
        strong2lex[s].append(lx)

    # poetic-parallelism structural pairs (T'OMIM + our own detection, resources/parallelism/) — real
    # signal, previously built (candidate #7) but never wired in as an active corroborator, only used
    # as a separate validation benchmark. Merge its antonyms into the existing `ant` set (parallelism's
    # own relation-labeling already cross-referenced the same LLM signal, so this is consistent, not
    # circular) so antithetic-parallelism pairs get caught the same way LLM-flagged antonyms are.
    parallelism_syn, parallelism_ant = _load_parallelism_pairs() if use_parallelism else (set(), set())
    ant = ant | parallelism_ant
    print(f"[neighbors] parallelism: {len(parallelism_syn)} likely-synonym, {len(parallelism_ant)} "
          f"likely-antonym structural pairs" + ("" if use_parallelism else " (disabled)"), file=sys.stderr)

    # xling corroboration (free, no LLM spend): two Hebrew Strong's rendered by the SAME surface across
    # many independent languages (aligned_lex_hf). Same principle as `lxx` above, scaled from one
    # translation tradition (Greek/LXX) to ~924. Was in the original 4-signal design, never built until
    # now — see bcv-commons-export-candidates.md.
    xling_strong_pairs = _load_xling_pairs() if use_xling else {}
    print(f"[neighbors] xling: {len(xling_strong_pairs)} Strong's pairs corroborated by "
          f">= {XLING_MIN_LANGS} independent languages" + ("" if use_xling else " (disabled)"),
          file=sys.stderr)

    # BDB etymological root-groups (public domain, resources/bdb_roots/) — validated 2026-08 at 50.6%
    # SDBH-domain agreement, better than this project's own clustering, at ~10x the scale. No corroboration
    # threshold needed (root grouping is already expert etymological judgment, unlike xling's raw
    # cross-lingual co-occurrence) — see build_bdb_roots.py.
    bdb_root_pairs = _load_bdb_root_pairs() if use_bdb else set()
    print(f"[neighbors] bdb_roots: {len(bdb_root_pairs)} Strong's pairs sharing an etymological root"
          + ("" if use_bdb else " (disabled)"), file=sys.stderr)

    # Hebrew WordNet synset co-membership — genuinely independent of UBS MARBLE; modern-register, which
    # was flagged as a risk (the one prior check that favored bge-m3 over BEREL).
    # STALE CLAIM, CORRECTED 2026-08-14: this comment used to say "its own prior-tier edges score 89.7%
    # SDBH agreement... the register mismatch did not materialize as a quality problem" -- re-checked on
    # the exact same subset (555 hwn-only prior edges) and got 44.9%, not 89.7%. Cause not established
    # (data drift in build_hwn_benchmark.py's synset extraction, or the original figure was wrong) but
    # the number does not hold up today. Independently, the text-anchored intrinsic/etymology yardsticks
    # (SDBH retired as the ongoing validator, see internal-docs/text-anchored-semantics-plan.md) also
    # rank hwn among the weakest of the six prior-tier signals -- two independent checks now agree hwn is
    # weak, where only one (now-refuted) number used to justify keeping it on. use_hwn's default is left
    # unchanged pending an explicit decision -- this correction is about the STATED reason, not a
    # unilateral change to the behavior it justified.
    hwn_pairs = _load_hwn_pairs() if use_hwn else set()
    print(f"[neighbors] hwn: {len(hwn_pairs)} Strong's pairs sharing a Hebrew WordNet synset"
          + ("" if use_hwn else " (disabled)"), file=sys.stderr)

    # BHSA coordination + apposition (Context-Fabric syntactic structure, resources/bhsa_structural/) —
    # validated 2026-08 at 61.7% combined SDBH agreement, a genuinely different lineage (syntax, not
    # lexical/etymological) from every other signal here. See build_bhsa_structural_pairs.py.
    structural_pairs = _load_structural_pairs() if use_structural else set()
    print(f"[neighbors] structural: {len(structural_pairs)} Strong's pairs (BHSA coordination+apposition)"
          + ("" if use_structural else " (disabled)"), file=sys.stderr)

    # "Corroborated" tier — pairs where xling agrees with structural or Wiktionary roots. Neither xling
    # nor wiktionary_root_pairs is trustworthy alone (52.8% / 35.0% SDBH agreement — xling is explicitly
    # excluded elsewhere in this function for exactly this reason). Their AGREEMENT is a different story:
    # measured 2026-08 at xling∩wiktionary=87.7%, xling∩structural=73.6% — comparable to or better than
    # every other signal here. Computed regardless of use_xling (raw xling stays excluded as its own
    # standalone signal; only the validated intersection is trusted) — see _load_corroborated_pairs().
    corroborated_pairs: set[frozenset] = set()
    if use_corroborated:
        xling_for_corrob = _load_xling_pairs()
        wiktionary_pairs = _load_wiktionary_root_pairs()
        corroborated_pairs = _load_corroborated_pairs(xling_for_corrob, wiktionary_pairs)
    print(f"[neighbors] corroborated: {len(corroborated_pairs)} Strong's pairs (xling ∩ wiktionary_roots)"
          + ("" if use_corroborated else " (disabled)"), file=sys.stderr)

    # Sefer HaShorashim (Radak, c.1185-1235 CE, Public Domain, via Sefaria) — a medieval rabbinic Hebrew
    # root dictionary, a third independent lineage alongside BDB (academic) and Wiktionary (modern
    # crowd-sourced). "yes"-verdict pairs (LLM-verified from same-entry candidates) validated 2026-08 at
    # 74.1% SDBH agreement on a 761-pair checkable sample — see build_sefer_hashorashim.py.
    sefer_hashorashim_pairs = _load_sefer_hashorashim_pairs() if use_sefer_hashorashim else set()
    print(f"[neighbors] sefer_hashorashim: {len(sefer_hashorashim_pairs)} LLM-verified Strong's pairs"
          + ("" if use_sefer_hashorashim else " (disabled)"), file=sys.stderr)

    # Coverage extension: xling/bdb_roots need no embedding, so they can name lexemes OUTSIDE the pack
    # (too few occurrences to get a stable centroid) — the same coverage gap un-restricting the paid LLM
    # run would close, at zero cost. Pull a representative (lexeme, gloss) for every Hebrew content
    # Strong's from lexeme-spine.db directly (not the embedding pack) and extend meta/strong2lex with any
    # out-of-pack Strong's that actually appear in one of these pairs — no point adding ones that don't.
    xling_strongs = {s for pair in xling_strong_pairs for s in pair}
    bdb_strongs = {s for pair in bdb_root_pairs for s in pair}
    parallelism_strongs = {s for pair in parallelism_syn for s in pair}
    hwn_strongs = {s for pair in hwn_pairs for s in pair}
    structural_strongs = {s for pair in structural_pairs for s in pair}
    corroborated_strongs = {s for pair in corroborated_pairs for s in pair}
    sefer_hashorashim_strongs = {s for pair in sefer_hashorashim_pairs for s in pair}
    out_of_pack = ((xling_strongs | bdb_strongs | parallelism_strongs | hwn_strongs
                    | structural_strongs | corroborated_strongs | sefer_hashorashim_strongs)
                   - set(strong2lex) - proper_strongs() - non_content_strongs())
    if out_of_pack and SPINE.exists():
        sp2 = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
        rep: dict[str, tuple[str, str]] = {}
        for lexeme, strong, gloss in sp2.execute(
                "SELECT lexeme, strong, gloss FROM spine_words "
                "WHERE is_content=1 AND strong IS NOT NULL AND lexeme LIKE 'hbo:%'"):
            hs = f"H{int(strong):04d}"
            if hs in out_of_pack and hs not in rep:
                rep[hs] = (lexeme, gloss or "")
        for hs, (lexeme, gloss) in rep.items():
            meta[lexeme] = (hs, gloss)
            gloss_tok[lexeme] = _gloss_tokens(gloss)
            strong2lex[hs].append(lexeme)
        print(f"[neighbors] coverage extension (xling + bdb_roots + parallelism + hwn + structural + "
              f"corroborated + sefer_hashorashim): +{len(rep)}/{len(out_of_pack)} out-of-pack lexemes "
              f"now reachable (no embedding)", file=sys.stderr)

    # embedding kNN (cosine = dot of unit vectors) — tiered against the LLM prior
    rows, emb_pairs = [], set()
    for i, lx in enumerate(lexemes):
        sims = M @ M[i]
        sims[i] = -1
        top = np.argpartition(-sims, TOPK)[:TOPK]
        for j in top[np.argsort(-sims[top])]:
            cos = float(sims[j])
            if cos < MIN_COS:
                continue
            nb = lexemes[j]
            sources, score = ["emb"], cos
            if frozenset((lx, nb)) in lxx_pairs:
                sources.append("lxx"); score = min(1.0, score + 0.1)
            if gloss_tok[lx] and gloss_tok[lx] & gloss_tok.get(nb, set()):
                sources.append("gloss"); score = min(1.0, score + 0.1)
            pair = frozenset((meta[lx][0], meta[nb][0]))         # strong-level
            if pair in xling_strong_pairs:
                sources.append("xling"); score = min(1.0, score + 0.1)
            if pair in bdb_root_pairs:
                sources.append("bdb_root"); score = min(1.0, score + 0.1)
            if pair in parallelism_syn:
                sources.append("parallelism"); score = min(1.0, score + 0.1)
            if pair in hwn_pairs:
                sources.append("hwn"); score = min(1.0, score + 0.1)
            if pair in structural_pairs:
                sources.append("structural"); score = min(1.0, score + 0.1)
            if pair in corroborated_pairs:
                sources.append("corroborated"); score = min(1.0, score + 0.1)
            if pair in sefer_hashorashim_pairs:
                sources.append("sefer_hashorashim"); score = min(1.0, score + 0.1)
            relation, conf = "similar", "recall"
            if pair in ant:                                      # LLM says OPPOSITE — emb false positive
                relation = "antonym"
            elif pair in syn:                                    # LLM + embedding AGREE
                sources.append("llm"); conf = "high"; score = min(1.0, score + 0.15)
            rows.append((lx, nb, round(score, 4), "|".join(sources), conf, relation))
            emb_pairs.add(frozenset((lx, nb)))

    # LLM-only PRIOR edges — synonymy the LLM asserts but the embedding didn't surface (added coverage,
    # lower trust). Map strong->lexeme(s); skip pairs the embedding already produced.
    for pair in syn:
        a, b = tuple(pair) if len(pair) == 2 else (None, None)
        if not a:
            continue
        for lx in strong2lex.get(a, []):
            for nb in strong2lex.get(b, []):
                if lx != nb and frozenset((lx, nb)) not in emb_pairs:
                    rows.append((lx, nb, 0.5, "llm", "prior", "similar"))

    # xling-only PRIOR edges — synonymy corroborated across independent languages but the embedding
    # didn't surface it (or one side has no embedding at all — the coverage-extension lexemes added
    # above). Score scales gently with corroboration strength (more independent languages = more
    # trust), capped below the LLM-agreement floor since it's a single (if broad) signal, not a
    # cross-checked one. Free — no API spend, unlike the equivalent LLM coverage run.
    xling_rows = 0
    for pair, n_langs in xling_strong_pairs.items():
        a, b = tuple(pair)
        for lx in strong2lex.get(a, []):
            for nb in strong2lex.get(b, []):
                if lx != nb and frozenset((lx, nb)) not in emb_pairs:
                    score = min(0.45, 0.25 + 0.02 * n_langs)
                    rows.append((lx, nb, round(score, 3), "xling", "prior", "similar"))
                    xling_rows += 1
    print(f"[neighbors] xling-only prior edges: {xling_rows}", file=sys.stderr)

    # bdb_root-only PRIOR edges — same-root pairs the embedding didn't surface (or couldn't, for
    # coverage-extension lexemes). Flat score (not corroboration-scaled like xling) since root grouping
    # is a single expert-curated fact, not a statistical count — validated at 50.6% SDBH agreement,
    # roughly on par with the LLM-only prior tier, so scored similarly.
    bdb_rows = 0
    for pair in bdb_root_pairs:
        a, b = tuple(pair)
        for lx in strong2lex.get(a, []):
            for nb in strong2lex.get(b, []):
                if lx != nb and frozenset((lx, nb)) not in emb_pairs:
                    rows.append((lx, nb, 0.5, "bdb_root", "prior", "similar"))
                    bdb_rows += 1
    print(f"[neighbors] bdb_root-only prior edges: {bdb_rows}", file=sys.stderr)

    # parallelism-only PRIOR edges — structural pairs (T'OMIM expert-verified or our own detection) the
    # embedding didn't surface. Flat score, same tier as bdb_root — both are single expert/structural
    # facts, not statistical counts.
    parallelism_rows = 0
    for pair in parallelism_syn:
        a, b = tuple(pair)
        for lx in strong2lex.get(a, []):
            for nb in strong2lex.get(b, []):
                if lx != nb and frozenset((lx, nb)) not in emb_pairs:
                    rows.append((lx, nb, 0.5, "parallelism", "prior", "similar"))
                    parallelism_rows += 1
    print(f"[neighbors] parallelism-only prior edges: {parallelism_rows}", file=sys.stderr)

    # hwn-only PRIOR edges — same tier as bdb_root/parallelism, but EXPERIMENTAL (see caution above).
    hwn_rows = 0
    for pair in hwn_pairs:
        a, b = tuple(pair)
        for lx in strong2lex.get(a, []):
            for nb in strong2lex.get(b, []):
                if lx != nb and frozenset((lx, nb)) not in emb_pairs:
                    rows.append((lx, nb, 0.5, "hwn", "prior", "similar"))
                    hwn_rows += 1
    print(f"[neighbors] hwn-only prior edges: {hwn_rows}", file=sys.stderr)

    # structural-only PRIOR edges — BHSA coordination/apposition pairs the embedding didn't surface.
    # Flat score, same tier as bdb_root/parallelism/hwn (see "not yet done" continuous-weighting note
    # in domain-replacement-roadmap.md — all prior-tier sources share one flat score today regardless
    # of their own validated quality, a known simplification, not an oversight here specifically).
    structural_rows = 0
    for pair in structural_pairs:
        a, b = tuple(pair)
        for lx in strong2lex.get(a, []):
            for nb in strong2lex.get(b, []):
                if lx != nb and frozenset((lx, nb)) not in emb_pairs:
                    rows.append((lx, nb, 0.5, "structural", "prior", "similar"))
                    structural_rows += 1
    print(f"[neighbors] structural-only prior edges: {structural_rows}", file=sys.stderr)

    # corroborated-only PRIOR edges — xling∩{structural,wiktionary} pairs the embedding didn't surface.
    # Already deduped against structural_pairs in _load_corroborated_pairs (no double-counting).
    corroborated_rows = 0
    for pair in corroborated_pairs:
        a, b = tuple(pair)
        for lx in strong2lex.get(a, []):
            for nb in strong2lex.get(b, []):
                if lx != nb and frozenset((lx, nb)) not in emb_pairs:
                    rows.append((lx, nb, 0.5, "corroborated", "prior", "similar"))
                    corroborated_rows += 1
    print(f"[neighbors] corroborated-only prior edges: {corroborated_rows}", file=sys.stderr)

    # sefer_hashorashim-only PRIOR edges — LLM-verified pairs the embedding didn't surface.
    # Re-derived 2026-08-14 under the text-anchored intrinsic yardstick (SDBH retired, see
    # internal-docs/text-anchored-semantics-plan.md): measured across 5 independent book-level
    # train/test splits (etymology_yardstick.py, same-verse held-out prediction), sefer_hashorashim's
    # lift over its frequency-matched baseline (2.24x-3.21x, mean 2.77x) beat structural/bdb_root/
    # wiktionary_roots' lift IN EVERY SINGLE SEED -- the one signal in this pipeline with that level of
    # consistent separation from the pack. Bumped from the flat 0.5 all prior-tier signals otherwise
    # share to 0.6 -- a modest, deliberately conservative move, not a re-scale to match its full
    # measured lift. Every OTHER prior-tier signal (including corroborated, which had the highest MEAN
    # lift at 3.56x but ranged 1.76x-5.10x and even dropped below sefer_hashorashim/structural at one
    # seed) stays at 0.5 -- a single-seed check had suggested moving corroborated up and hwn down, but
    # that ranking did not survive the 5-seed check, so neither was changed. See the plan doc's
    # "Stability check" section for the full per-seed numbers and what would justify revisiting this.
    SEFER_HASHORASHIM_SCORE = 0.6
    sefer_hashorashim_rows = 0
    for pair in sefer_hashorashim_pairs:
        a, b = tuple(pair)
        for lx in strong2lex.get(a, []):
            for nb in strong2lex.get(b, []):
                if lx != nb and frozenset((lx, nb)) not in emb_pairs:
                    rows.append((lx, nb, SEFER_HASHORASHIM_SCORE, "sefer_hashorashim", "prior", "similar"))
                    sefer_hashorashim_rows += 1
    print(f"[neighbors] sefer_hashorashim-only prior edges: {sefer_hashorashim_rows}", file=sys.stderr)

    out_dir.mkdir(parents=True, exist_ok=True)
    import pyarrow as pa, pyarrow.parquet as pq
    c = list(zip(*rows)) if rows else ([], [], [], [], [], [])
    dest = out_dir / "neighbors.parquet"
    pq.write_table(pa.table({"lexeme": pa.array(c[0], pa.string()),
                             "neighbor_lexeme": pa.array(c[1], pa.string()),
                             "score": pa.array(c[2], pa.float32()),
                             "sources": pa.array(c[3], pa.string()),
                             "confidence": pa.array(c[4], pa.string()),   # high | recall | prior
                             "relation": pa.array(c[5], pa.string())}),   # similar | antonym
                   dest, compression="zstd")
    tier = collections.Counter(r[4] for r in rows)
    manifest = {
        "dataset": "semantic_neighbors", "anchor": "MACULA lexeme (CC-BY)", "testament": "OT/Hebrew",
        "license": "CC0-1.0",
        # each entry below is conditioned on the flag that actually controls it -- FIXED 2026-08-14:
        # xling/bdb_root/parallelism used to be unconditional here regardless of --no-xling/--no-bdb/
        # --no-parallelism, silently misreporting which signals actually went into a given pack (found
        # while verifying the hwn-removal rebuild, see internal-docs/text-anchored-semantics-plan.md).
        "signals": [f"emb:{emb_label}", "lxx:shared-greek", "gloss:overlap", "llm:scholarly-prior"]
                   + ([f"xling:shared-surface (>= {XLING_MIN_LANGS} langs, aligned_lex_hf)"]
                      if use_xling else [])
                   + (["bdb_root:shared-etymological-root (public domain, OpenScriptures/HebrewLexicon)"]
                      if use_bdb else [])
                   + (["parallelism:poetic-structural-pair (T'OMIM CC BY 4.0 + our own BHSA half_verse "
                       "detection)"] if use_parallelism else [])
                   + (["hwn:shared-synset (Hebrew WordNet, Ordan & Wintner 2007)"] if use_hwn else [])
                   + (["structural:coordination+apposition (Context-Fabric/BHSA syntactic structure)"]
                      if use_structural else [])
                   + (["corroborated:xling-agrees-with-wiktionary-roots"] if use_corroborated else [])
                   + (["sefer_hashorashim:llm-verified (Radak, Public Domain, via Sefaria)"]
                      if use_sefer_hashorashim else []),
        "confidence_tiers": {"high": tier["high"], "recall": tier["recall"], "prior": tier["prior"]},
        "lexemes": len(lexemes), "edges": len(rows), "topk": TOPK, "min_cos": MIN_COS, "min_occ": MIN_OCC,
        "content_sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
        "note": "high = LLM prior + empirical embedding agree. NC domains used only as internal yardstick.",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _write_by_strong(rows, out_dir)                     # committed service form for shoresh /field, /concept
    _write_by_lexeme(rows, meta, out_dir)                # homograph-precise service form (same, split by lexeme)
    print(f"[neighbors] {len(rows)} edges (high={tier['high']} recall={tier['recall']} "
          f"prior={tier['prior']}) -> {dest}", file=sys.stderr)

    if validate:
        _validate(rows, meta)
    return manifest


def _write_by_strong(rows, out_dir: Path = OUT_DIR):
    """Committed service form: resources/semantic_neighbors/by_strong.tsv — high+prior tiers rolled
    lexeme→Strong's, with the neighbor's English gloss, for the shoresh /field + /concept endpoints
    (which key on Strong's). Small + tracked (the parquet is the bulk/gitignored form)."""
    import re
    gl = {}
    gp = ROOT / "resources" / "strongs_gloss.tsv"
    if gp.exists():
        for ln in gp.read_text(encoding="utf-8").splitlines()[1:]:
            p = ln.split("\t")
            if len(p) >= 2:
                gl.setdefault(p[0], p[1])

    def hs(lx):
        m = re.search(r"(\d+)", lx or "")
        return f"{'G' if lx.startswith('grc') else 'H'}{int(m.group(1)):04d}" if m else ""

    best = {}
    for lx, nb, score, _src, conf, rel in rows:
        if conf == "recall" and rel != "antonym":   # keep high+prior; but antonyms live in recall
            continue
        a, b = hs(lx), hs(nb)
        if not a or not b or a == b:
            continue
        if (a, b) not in best or score > best[(a, b)][2]:
            best[(a, b)] = (rel, conf, score)
    lines = sorted(((a, b, gl.get(b, ""), rel, conf, round(sc, 3))
                    for (a, b), (rel, conf, sc) in best.items()), key=lambda r: (r[0], -r[5]))
    (out_dir / "by_strong.tsv").write_text(
        "# semantic field per Strong's (high+prior tiers, rolled from lexeme neighbors); CC0\n"
        "strong\tneighbor\tneighbor_gloss\trelation\tconfidence\tscore\n"
        + "\n".join("\t".join(map(str, r)) for r in lines) + "\n", encoding="utf-8")


def _write_by_lexeme(rows, meta, out_dir: Path = OUT_DIR):
    """Homograph-precise service form: resources/semantic_neighbors/by_lexeme.tsv — the same high+prior
    field as by_strong.tsv, but NOT rolled: each row keeps the source + neighbor **lexeme** (MACULA
    anchor) and its own gloss. 64% of Strong's numbers cover >1 lexeme, so `by_strong` merges distinct
    words' neighbors into one blurred list; this form lets shoresh split /field + /concept by lexeme
    (and fall back to by_strong for Greek / lexeme-less codes). meta[lexeme] = (H####/G####, top_gloss)."""
    import re

    def hs(lx):
        m = re.search(r"(\d+)", lx or "")
        return f"{'G' if lx.startswith('grc') else 'H'}{int(m.group(1)):04d}" if m else ""

    best = {}
    for lx, nb, score, _src, conf, rel in rows:
        if conf == "recall" and rel != "antonym":   # keep high+prior; antonyms live in recall
            continue
        if lx == nb:
            continue
        if (lx, nb) not in best or score > best[(lx, nb)][2]:
            best[(lx, nb)] = (rel, conf, score)
    lines = sorted(
        ((hs(lx), lx, meta.get(lx, ("", ""))[1], hs(nb), nb, meta.get(nb, ("", ""))[1], rel, conf, round(sc, 3))
         for (lx, nb), (rel, conf, sc) in best.items()),
        key=lambda r: (r[0], r[1], -r[8]))
    (out_dir / "by_lexeme.tsv").write_text(
        "# semantic field per MACULA lexeme (high+prior tiers, homograph-precise); CC0\n"
        "strong\tlexeme\tlexeme_gloss\tneighbor_strong\tneighbor_lexeme\tneighbor_gloss\trelation\tconfidence\tscore\n"
        + "\n".join("\t".join(map(str, r)) for r in lines) + "\n", encoding="utf-8")


def _load_bdb_root_pairs() -> set[frozenset]:
    """{frozenset({H_a, H_b}), ...} — Hebrew Strong's pairs sharing a Brown-Driver-Briggs etymological
    root (resources/bdb_roots/root_groups.tsv, public domain via OpenScriptures/HebrewLexicon CC-BY-4.0,
    see build_bdb_roots.py). Validated 2026-08: same-root pairs share an SDBH domain 50.6% of the time
    (2,731/5,397 checkable pairs) — better than this project's own from-scratch clustering (45.1%), at
    much larger scale. No corroboration-count threshold needed (unlike xling) — root grouping IS already
    expert etymological judgment, not something to additionally statistically corroborate."""
    if not BDB_ROOTS.exists():
        return set()
    by_root: dict[str, set[str]] = collections.defaultdict(set)
    with BDB_ROOTS.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("root_id\t"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) >= 2 and p[1].startswith("H"):
                by_root[p[0]].add(p[1])
    pairs: set[frozenset] = set()
    for strongs in by_root.values():
        for a, b in itertools.combinations(sorted(strongs), 2):
            pairs.add(frozenset((a, b)))
    return pairs


def _load_parallelism_pairs() -> tuple[set[frozenset], set[frozenset]]:
    """(syn_pairs, ant_pairs) from resources/parallelism/parallelism_pairs.tsv — poetic-parallelism
    structural pairs (T'OMIM expert-verified, CC BY 4.0, + our own BHSA half_verse detection; see
    build_parallelism_pairs.py). Only likely_synonym/likely_antonym are used, both already
    cross-referenced against the independent LLM signal in that file's own build. `unclassified` pairs
    (parallelism found the pair, but nothing independently judged relation) are deliberately SKIPPED
    here — Hebrew poetry uses antithetic parallelism as often as synonymous, and mixing unclassified
    pairs back in as a blanket 'similar' signal would reintroduce the exact antithetic-contamination
    problem that file's relation-labeling was built to solve."""
    syn, ant = set(), set()
    if not PARALLELISM.exists():
        return syn, ant
    with PARALLELISM.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("strong_a\t"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < 5:
                continue
            a, b, relation = p[0], p[1], p[4]
            if relation == "likely_synonym":
                syn.add(frozenset((a, b)))
            elif relation == "likely_antonym":
                ant.add(frozenset((a, b)))
    return syn, ant


def _load_sefer_hashorashim_pairs() -> set[frozenset]:
    """{frozenset({H_a, H_b}), ...} — "yes"-verdict pairs from Sefer HaShorashim (Radak, c.1185-1235 CE,
    Public Domain, via Sefaria), a medieval Hebrew root dictionary from WITHIN the Jewish exegetical
    tradition — a different lineage from BDB (19th-c. German-Protestant) and Wiktionary (modern
    crowd-sourced). Candidates were same-entry co-membership (build_sefer_hashorashim.py, 21.6% SDBH
    core-agreement pre-verification — too weak alone, same shape as xling/wiktionary_roots), then
    individually LLM-verified (verify_pairs_llm.py) — "yes" verdicts score 74.1% on a 761-pair checkable
    sample (2026-08), comparable to structural (61.7%) and better than bdb_root (50.6%)."""
    pairs: set[frozenset] = set()
    if not SEFER_HASHORASHIM.exists():
        return pairs
    with SEFER_HASHORASHIM.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("strong_a\t"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) >= 3 and p[2] == "yes" and p[0].startswith("H") and p[1].startswith("H"):
                pairs.add(frozenset((p[0], p[1])))
    return pairs


def _load_structural_pairs() -> set[frozenset]:
    """{frozenset({H_a, H_b}), ...} — BHSA coordination + apposition pairs (Context-Fabric syntactic
    structure, resources/bhsa_structural/structural_pairs.tsv, see build_bhsa_structural_pairs.py).
    Validated 2026-08 at 61.7% combined SDBH-domain agreement (coordination alone 63.7%, apposition
    48.3%) — a genuinely different lineage (syntax, not lexical/etymological derivation) from every
    other signal in this pipeline. No corroboration-count threshold: single-content-word-side
    restriction already did the precision work (see that script's docstring)."""
    pairs: set[frozenset] = set()
    if not BHSA_STRUCTURAL.exists():
        return pairs
    with BHSA_STRUCTURAL.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("strong_a\t"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) >= 2 and p[0].startswith("H") and p[1].startswith("H"):
                pairs.add(frozenset((p[0], p[1])))
    return pairs


def _load_wiktionary_root_pairs() -> set[frozenset]:
    """{frozenset({H_a, H_b}), ...} — Wiktionary Hebrew root-category pairs (resources/wiktionary_roots/
    root_pairs.tsv, see build_wiktionary_roots.py). NOT used standalone (35.0% SDBH agreement alone —
    the weakest signal measured) — only as a corroboration input, see _load_corroborated_pairs()."""
    pairs: set[frozenset] = set()
    if not WIKTIONARY_ROOTS.exists():
        return pairs
    with WIKTIONARY_ROOTS.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("strong_a\t"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) >= 2 and p[0].startswith("H") and p[1].startswith("H"):
                pairs.add(frozenset((p[0], p[1])))
    return pairs


def _load_corroborated_pairs(xling_pairs, wiktionary_pairs) -> set[frozenset]:
    """{frozenset({H_a, H_b}), ...} — pairs where xling AND Wiktionary roots independently agree.
    Neither is trustworthy ALONE (52.8% / 35.0% SDBH agreement — xling is explicitly excluded from
    clustering for exactly this reason, see --no-xling). Their AGREEMENT is: measured 2026-08 at 87.7%
    SDBH agreement, re-confirmed 2026-08-14 at 91.0% -- one of the strongest signals in this pipeline
    (the once-quoted "except HWN (89.7%)" comparison does not hold up on a fresh check -- see
    _load_hwn_pairs()'s use site above and internal-docs/text-anchored-semantics-plan.md).
    (xling ∩ structural was also measured at 73.6%, but that intersection is a strict subset of
    structural_pairs — which already has its own standalone tier — so it contributes nothing NEW here
    and is deliberately left out to avoid a redundant, do-nothing union term.)"""
    xling_keys = set(xling_pairs) if not isinstance(xling_pairs, dict) else set(xling_pairs.keys())
    return xling_keys & wiktionary_pairs


def _load_hwn_pairs() -> set[frozenset]:
    """{frozenset({H_a, H_b}), ...} — Hebrew WordNet synset co-membership (Ordan & Wintner, U. Haifa
    2007), bare-consonant-matched to biblical Strong's (see build_hwn_benchmark.py, same matching
    logic reused here). CAUTION (2026-08 finding): HWN is MODERN Hebrew vocabulary — the one
    independent check that favored generic bge-m3 over BEREL, plausibly because its register doesn't
    match what BEREL specializes in. Using it as an active signal here is a deliberate experiment, not
    an assumed win like bdb_root/parallelism — measure before trusting; if it doesn't help (or hurts),
    drop it rather than keep it out of momentum. Using it as a signal also means it's no longer a clean
    independent validator for any pair it directly produces — T'OMIM and the internal SDBH check remain
    unaffected."""
    try:
        from macula.build_hwn_benchmark import load_bare_to_strongs, load_hwn_synsets, to_modern_form
    except ImportError:
        return set()
    synsets = load_hwn_synsets()
    bare2strongs = load_bare_to_strongs()
    pairs: set[frozenset] = set()
    for _sid, _pos, lemmas in synsets:
        strongs: set[str] = set()
        for lem in lemmas:
            strongs |= bare2strongs.get(to_modern_form(lem, "hbo"), set())
        for a, b in itertools.combinations(sorted(strongs), 2):
            pairs.add(frozenset((a, b)))
    return pairs


def _load_xling_pairs(min_langs: int = XLING_MIN_LANGS) -> dict[frozenset, int]:
    """{frozenset({H_a, H_b}): n_langs} — Hebrew Strong's pairs empirically co-rendered by the SAME
    target-language surface, corroborated across >= min_langs INDEPENDENT languages
    (resources/aligned_lex_hf/<lang>.tsv, bcv-commons/lexeme-alignments — CC0, ~924 languages).

    Same corroboration principle as the existing `lxx` signal (two Hebrew lexemes mapping to the same
    Greek Strong's via the LXX are near) — but scaled from ONE independent translation tradition
    (Greek) to ~924. Was in the original 4-signal design (semantic-neighbors-pack.md) but never built;
    this fills that gap. Free (no LLM spend) — a real alternative/complement to paying for LLM
    coverage over unembedded lexemes, though it only surfaces SYNONYMY (antonyms never share a
    rendering), unlike the LLM layer which also flags antonyms to demote embedding false-positives."""
    pair_langs: dict[frozenset, set[str]] = collections.defaultdict(set)
    if not ALIGNED_HF_DIR.exists():
        return {}
    for path in sorted(ALIGNED_HF_DIR.glob("*.tsv")):
        lang = path.stem
        surface_strongs: dict[str, set[str]] = collections.defaultdict(set)
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("#") or line.startswith("surface"):
                    continue
                p = line.rstrip("\n").split("\t")
                if len(p) < 4:
                    continue
                surface, strong = p[0].strip(), p[1].strip()
                if not surface or not strong.startswith("H"):
                    continue
                try:
                    count, share = int(p[2]), float(p[3])
                except ValueError:
                    continue
                if count >= XLING_MIN_COUNT and share >= XLING_MIN_SHARE:
                    surface_strongs[surface].add(strong)
        for strongs in surface_strongs.values():
            if len(strongs) < 2:
                continue
            for a, b in itertools.combinations(sorted(strongs), 2):
                pair_langs[frozenset((a, b))].add(lang)
    return {pair: len(langs) for pair, langs in pair_langs.items() if len(langs) >= min_langs}


def _load_llm_edges(path):
    """(syn, ant): sets of frozenset({H_a, H_b}) — undirected strong-level relations from the LLM layer."""
    syn, ant = set(), set()
    if path and Path(path).exists():
        for ln in Path(path).read_text(encoding="utf-8").splitlines():
            if ln.startswith("#") or ln.startswith("target"):
                continue
            p = ln.split("\t")
            if len(p) >= 3 and p[0].strip() != p[2].strip():
                (syn if p[1].strip() == "syn" else ant).add(frozenset((p[0].strip(), p[2].strip())))
    return syn, ant


def _validate(rows, meta):
    """Internal yardstick ONLY: does the text-anchored intrinsic yardstick (held-out slot-filler
    prediction) back up derived neighbors? SDBH retired as the yardstick 2026-08-14 — see
    internal-docs/text-anchored-semantics-plan.md and macula/intrinsic_yardstick.py."""
    from macula.intrinsic_yardstick import Yardstick, validate_pairs

    ys = Yardstick()
    for name, pred in (("all-similar", lambda r: True),
                       ("high-conf", lambda r: r[4] == "high"),
                       ("prior-only", lambda r: r[4] == "prior")):
        pairs = [(meta[r[0]][0], meta.get(r[1], ("", ""))[0]) for r in rows
                 if r[5] != "antonym" and pred(r) and r[0] in meta and r[1] in meta]
        pairs = [(a, b) for a, b in pairs if a and b]
        validate_pairs(ys, name, pairs)


def main():
    ap = argparse.ArgumentParser(description="Build the CC0 semantic-neighbors pack.")
    ap.add_argument("--validate", action="store_true",
                     help="score vs the text-anchored intrinsic yardstick (internal, see intrinsic_yardstick.py)")
    ap.add_argument("--llm-edges", type=Path, default=LLM_EDGES if LLM_EDGES.exists() else None,
                    help="method=llm syn/ant edges to tier against (default: semantic_neighbors/llm_edges.tsv)")
    ap.add_argument("--emb", type=Path, default=EMB,
                    help="clause-embedding .npz to use (default: context_emb.npz / bge-m3). Pass an "
                         "alternative (e.g. context_emb__dicta_il_BEREL_3_0.npz) to experiment with a "
                         "different embedding model — dimension is read from the file, no code change needed.")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR,
                    help="output dir (default: resources/semantic_neighbors/). Use a separate dir for "
                         "--emb experiments so they never overwrite the production pack.")
    ap.add_argument("--emb-label", default=None,
                    help="manifest label for the emb signal (default: derived from --emb's filename)")
    ap.add_argument("--sense-split", action="store_true",
                    help="cluster per (lexeme, sense) using resources/senses/hbo_lex.tsv's cluster "
                         "boundaries (hbo.db's sense column), not one blended centroid per whole lexeme")
    ap.add_argument("--no-xling", action="store_true",
                    help="skip the xling signal (aligned_lex_hf cross-lingual corroboration). Useful "
                         "for a clustering-input build — validated (2026-08) that mixing xling's large "
                         "volume of prior-tier edges into Louvain clustering hurts quality; its coverage-"
                         "extension value is for direct lookups, not proven as clustering fuel.")
    ap.add_argument("--no-bdb", action="store_true",
                    help="skip the bdb_root signal (BDB etymological root-groups, public domain). "
                         "Validated (2026-08) at 50.6%% SDBH-domain agreement — better than this "
                         "project's own clustering — with no known downside as clustering fuel (unlike "
                         "xling); default is ON.")
    ap.add_argument("--no-parallelism", action="store_true",
                    help="skip the parallelism signal (T'OMIM + our own poetic-structural pairs, "
                         "candidate #7). Only likely_synonym/likely_antonym are used; default is ON.")
    ap.add_argument("--hwn", action="store_true",
                    help="opt IN to the hwn signal (Hebrew WordNet, Ordan & Wintner 2007, modern "
                         "Hebrew). Independent of UBS MARBLE (still useful as an independent check, "
                         "see etymology_yardstick.py), but removed from the active-signal role "
                         "2026-08-14: the 89.7%% SDBH-agreement figure that justified keeping it on did "
                         "not survive a re-check (44.9%% on the same subset, and it ranks among the "
                         "weakest signals on the text-anchored yardsticks too) -- see hwn_pairs' comment "
                         "and internal-docs/text-anchored-semantics-plan.md. Default is now OFF.")
    ap.add_argument("--no-structural", action="store_true",
                    help="skip the structural signal (BHSA coordination+apposition via Context-Fabric, "
                         "candidate #6 re-purposed). Validated 2026-08 at 61.7%% SDBH agreement — a "
                         "different lineage (syntax) from every other signal here; default is ON.")
    ap.add_argument("--no-corroborated", action="store_true",
                    help="skip the corroborated signal (xling ∩ wiktionary_roots). Neither is trusted "
                         "alone (52.8%% / 35.0%% SDBH); their agreement is (87.7%%, validated 2026-08); "
                         "default is ON.")
    ap.add_argument("--no-sefer-hashorashim", action="store_true",
                    help="skip the sefer_hashorashim signal (Radak, Public Domain, LLM-verified via "
                         "verify_pairs_llm.py). Validated 2026-08 at 74.1%% SDBH agreement; default is ON.")
    a = ap.parse_args()
    label = a.emb_label or ("bge-m3 clause centroids" if a.emb == EMB else f"{a.emb.stem} clause centroids")
    build(a.validate, a.llm_edges, emb_path=a.emb, out_dir=a.out_dir, emb_label=label,
          sense_split=a.sense_split, use_xling=not a.no_xling, use_bdb=not a.no_bdb,
          use_parallelism=not a.no_parallelism, use_hwn=a.hwn,
          use_structural=not a.no_structural, use_corroborated=not a.no_corroborated,
          use_sefer_hashorashim=not a.no_sefer_hashorashim)


if __name__ == "__main__":
    main()
