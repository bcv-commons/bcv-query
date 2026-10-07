# resources/ — licence register (NC exit)

Status 2026-10-07: the project is moving off every non-commercial (NC) source (BHSA/ETCBC CC BY-NC-SA, OpenHebrewBible CC BY-NC) and onto
MACULA (CC BY 4.0). Each `resources/<folder>/` still records its own `source` / `license` in its README or manifest. **This file lists every
tracked file that is tied to BHSA, plus the ones that mention it only to say it is not used.** A test (`shoresh/tests/test_nc_register.py`)
fails if a tracked resources file mentions BHSA/ETCBC/OpenHebrewBible in its provenance header and is not listed below, so NC data cannot
come back unnoticed. Plan and status: `internal-docs/` (NC exit) and the project notes.

## Tied to BHSA, still tracked because the running service reads them (replacement planned)
Treat these as **CC BY-NC-SA 4.0** (ETCBC BHSA) unless the entry says otherwise. They are service data, served under the project's declared
non-commercial terms, not an open release. Do not copy them into CC0/CC BY outputs.
- `senses/hbo_lex.tsv` — Hebrew sense layer keyed on BHSA lexeme + stem, built from BHSA clauses. CC BY-NC-SA. Replacement: `hebrew-word-senses` (MACULA lexemes, CC BY).
- `senses/README.md` — describes the file above.
- `word_glosses/` — per-language glosses keyed on ETCBC/BHSA lexeme ids (`lex`). The gloss text comes from BibleOL (MIT) and our conversions; the keys are BHSA lexeme identifiers. Labelled conservatively as BHSA-tied until the files are re-keyed on MACULA lexemes.
- `lexicons/` — BibleOL per-binyan glosses (MIT) for BHSA lexemes, keyed on BHSA `lex`. Same treatment as `word_glosses/`.

## Mention BHSA only to describe or to exclude it (no BHSA content)
- `occurrences/README.md` — describes `hbo.db`, a local, untracked, BHSA-built database.
- `versification/README.md` — one scheme in the registry is named after the BHSA spine (verse counts only).
- `semantic_groups/` — CC0, built from MACULA text; the header says "no BHSA input".
- `semantic_neighbors/` — CC0 published release, BHSA-free (`manifest.json` corrected 2026-10-07).
- `prior_pack/` — rebuilt BHSA-free 2026-10-03; CC BY-SA 4.0.
- `parallelism/parallelism_pairs.tsv` — T'OMIM-confirmed tier only (CC BY 4.0).

## Removed from tracking 2026-10-07 (kept locally, git-ignored, never published)
`bhsa_hierarchy/` (BHSA clause and apposition hierarchy; `clause_mother.tsv` is read by bcv-RAG's `ingest/clause_dependencies.py` from a local copy),
`bhsa_structural/` (coordination and apposition pairs), `syntax_profiles/` (verb argument-slot fillers), and
`parallelism/parallelism_pairs.local.tsv` (the BHSA-derived "detected" tier). They remain in the git history of this public repository.

## Rules for new files
1. Anything published as CC0 / CC BY / CC BY-SA must not take BHSA, OpenHebrewBible, ETCBC Nestle1904, or UBS MARBLE fields as input. Use MACULA (and the open sources named in `internal-docs`).
2. Facts about the Hebrew or Greek text are derived from original-language and versification sources, never from English translations.
