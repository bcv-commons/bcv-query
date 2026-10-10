# resources/ — licence register (NC exit)

Status 2026-10-10: the project has left every non-commercial (NC) source (BHSA/ETCBC CC BY-NC-SA, OpenHebrewBible CC BY-NC, the CATSS/CCAT Septuagint); the service
and the tracked data are on MACULA (CC BY 4.0), UHB/UGNT and GLAUx (CC BY-SA 4.0). Each `resources/<folder>/` still records its own `source` / `license` in its README or manifest. **This file lists every
tracked file that is tied to BHSA, plus the ones that mention it only to say it is not used.** A test (`shoresh/tests/test_nc_register.py`)
fails if a tracked resources file mentions BHSA/ETCBC/OpenHebrewBible in its provenance header and is not listed below, so NC data cannot
come back unnoticed. Plan and status: `internal-docs/` (NC exit) and the project notes.

## Tied to BHSA: nothing is tracked any more (NC exit option 3, 2026-10-09)
The BHSA-keyed build inputs were untracked and are git-ignored, kept only on the maintainer's machine; they remain in the git history of this public repository:
`senses/hbo_lex.tsv`, `senses/senses_i18n/_gaps.tsv`, `word_glosses/hbo/`, `word_freq/hbo.tsv`, `word_freq/hbo_strong.tsv`, `lexicons/heb_en.csv`. Treat anything fetched from the history as CC BY-NC-SA.
Their replacements are tracked: `word_glosses/hbo_lexeme/` (BibleOL glosses, MIT, on MACULA lexeme ids; the lex -> lexeme mapping stays local) and the published `hebrew-word-senses` (MACULA).
`strongs_gloss.tsv` is built from `hbo_lexeme` (the Strong's number comes from the lexeme id), not from the BHSA lex -> Strong's bridge.

## Derived from GLAUx (CC BY-SA 4.0, share-alike; decision 2026-10-10)
The Septuagint word store served by shoresh (`lxx-glaux.db`: `/verse` `lxx` words, `/word/G####`, `/lxx-lexeme`, bcv-rag passage-card `lxx` words) is built from
**GLAUx** (Alek Keersmaekers, KU Leuven, https://github.com/alekkeersmaekers/glaux; CC BY-SA 4.0), whose Septuagint texts come from el.wikisource (CC BY-SA 3.0) and whose
Genesis annotation is Pedalion Trees (CC BY-SA 4.0). It replaces the CATSS/CCAT-based store, which was licensed for non-commercial use only. Data built from it is
**CC BY-SA 4.0**; keep the attribution and the share-alike:
- `lxx_orphan_lexemes/` — LXX-only Greek lexemes, grouped by GLAUx lemma.
- `ot_nt_quotations/` — OT-in-NT quotations from LXX Strong's overlap (Odes excluded).
Strong's numbers on this data come from the open lemma lists of UGNT (unfoldingWord, CC BY-SA 4.0) and MACULA Greek (CC BY 4.0) and from a short table of public-domain
classic Strong's numbers; the case of names that GLAUx leaves untagged is inferred from the context and flagged (`morph_inferred`). The CATSS-based tables of 2026-10-09 and
earlier remain in the git history of this public repository and stay non-commercial. Not affected: `lxx_bridge.tsv` (MACULA Hebrew `greekstrong`), the `lxx` versification map (TVTMS).

## Mention BHSA only to describe or to exclude it (no BHSA content)
- `lexicons/README.md` — describes the untracked, BHSA-keyed local files above (no BHSA data in this README).
- `senses/README.md` — describes the untracked, BHSA-keyed local files above (no BHSA data in this README).
- `word_glosses/README.md` — describes the untracked, BHSA-keyed local files above (no BHSA data in this README).
- `occurrences/README.md` — describes `hbo.db`, a local, untracked, BHSA-built database.
- `versification/README.md` — one scheme in the registry is named after the BHSA spine (verse counts only).
- `semantic_groups/` — CC0, built from MACULA text; the header says "no BHSA input".
- `semantic_neighbors/` — CC0 published release, BHSA-free (`manifest.json` corrected 2026-10-07).
- `prior_pack/` — rebuilt BHSA-free 2026-10-03; CC BY-SA 4.0.
- `parallelism/parallelism_pairs.tsv` — T'OMIM-confirmed tier only (CC BY 4.0).

## Removed from tracking 2026-10-07 (kept locally, git-ignored, never published)
`bhsa_hierarchy/` (BHSA clause and apposition hierarchy; `clause_mother.tsv` fed the retired `clause_dependency_lookup` tool (step 4)),
`bhsa_structural/` (coordination and apposition pairs), `syntax_profiles/` (verb argument-slot fillers), and
`parallelism/parallelism_pairs.local.tsv` (the BHSA-derived "detected" tier). They remain in the git history of this public repository.

## Rules for new files
1. Anything published as CC0 / CC BY / CC BY-SA must not take BHSA, OpenHebrewBible, or UBS MARBLE fields (ETCBC Nestle1904 is MIT / MACULA-derived, not NC, but prefer MACULA Greek directly) as input. Use MACULA (and the open sources named in `internal-docs`).
2. Facts about the Hebrew or Greek text are derived from original-language and versification sources, never from English translations.
