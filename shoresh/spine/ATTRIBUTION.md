# Attribution & licensing — original-language spine

The spine is built from third-party data. Several sources are
**non-commercial (NC)**, which makes `spine.db` and the service data derived from
it **non-commercial**. This project operates under that constraint **while it
migrates off those sources** (status below). Published open datasets are BHSA-free:
see `resources/LICENSES.md`.

**Status 2026-10-09 (NC exit, service side complete):**
- The running service reads **no BHSA / ETCBC / OpenHebrewBible files**: structure, trees, syntax search, `/words`,
  senses, `/verse` Hebrew words and clause search are all MACULA (CC BY 4.0). The BHSA text-fabric corpus mount and
  `hbo.db` are retired; `clause_dependencies` was dropped from `index.db` (MACULA has no clause-to-clause relations).
  The audit of served resources derived from BHSA is done (2026-10-09, `resources/LICENSES.md` is the register): nothing served or published is BHSA-derived.
  **Septuagint, 2026-10-10:** the word store is now GLAUx-based (see the table below), not the CATSS/CCAT one, which was licensed for non-commercial use only. The CATSS
  file stays in the image until `Dockerfile.base` stops building it; the service no longer reads it once `lxx-glaux.db` is on the data volume. Small BHSA / OpenHebrewBible
  traces remain in `spine/` build inputs (`reconciliation/`, `psalm_superscription_clauses.tsv`, `strongs_equivalence.tsv`) and decide when the non-commercial declaration can change.
- `spine.db` stays, built from UHB / UGNT (unfoldingWord, CC BY-SA 4.0) only: it serves the Greek NT `/verse` words,
  `/morph` and the `/gloss` counts. It is not NC.
- Still NC and only used **offline** (build scripts, local, git-ignored outputs): the BHSA text-fabric corpus
  (`corpus_engine/`, `macula/build_*` scripts, `spine/reconcile.py`), `resources/senses/hbo_lex.tsv`,
  the BHSA-keyed `word_glosses/hbo`, `word_freq/hbo*` and `lexicons/` (untracked from the public repo and excluded from the images since 2026-10-09; the MACULA-keyed `word_glosses/hbo_lexeme` replaces them). The Greek half of the
  engine, `ETCBC/nestle1904`, is **not NC**: its repository is MIT (checked 2026-10-09) and is a conversion of Clear-Bible
  MACULA Greek (CC BY 4.0); keep the attribution to ETCBC and Clear Bible. Open datasets published from this repo are BHSA-free.
- Already open: the published `lexeme-spine-macula.db` (CC BY, MACULA only, Psalm titles from Hebrew-only spans),
  `semantic-neighbors`, `prior-pack`, `hebrew-word-senses`, `hebrew-lexical-references`, `strongs`.

## Sources

| Source | Used for | License | Attribution |
|---|---|---|---|
| **unfoldingWord Hebrew Bible (UHB)** — `unfoldingWord/hbo_uhb` | OT spine (Strong's, lemma, morph per word) | CC BY-SA 4.0 | unfoldingWord® |
| **unfoldingWord Greek NT (UGNT)** — `unfoldingWord/el-x-koine_ugnt` | NT spine | CC BY-SA 4.0 | unfoldingWord® |
| **BHSA** — `ETCBC/bhsa` (via bcv-corpus) | syntactic roles (Layer 4) | CC BY-NC-SA 4.0 | ETCBC, VU Amsterdam |
| **OpenHebrewBible** — `eliranwong/OpenHebrewBible` | BHSA↔Strong's crosswalk (`002`), versification map (`019`) | **CC BY-NC 4.0** | Eliran Wong, *Open Hebrew Bible Project* |
| **MACULA Hebrew** — `Clear-Bible/macula-hebrew` (`WLC/lowfat`) | verse structure, trees, syntax search, `/words` feed (`trees-macula.db`); lexeme spine | CC BY 4.0 | Biblica, Inc. / Clear Bible; Westminster Hebrew Syntax © Groves Center (CC BY 4.0); OpenScriptures Hebrew Bible morphology (CC BY 4.0); Westminster Leningrad Codex text (public domain) |
| **MACULA Greek** — `Clear-Bible/macula-greek` (`Nestle1904/lowfat`) | Greek structure, trees, syntax search (`trees-macula.db`); Greek spine | CC BY 4.0 | Clear Bible (Nestle 1904 text: public domain) |
| **GLAUx** (KU Leuven, A. Keersmaekers) — Septuagint texts from el.wikisource (CC BY-SA 3.0), Genesis annotation Pedalion Trees (CC BY-SA 4.0) | `lxx-glaux.db`: `/verse` `lxx` words, `/word/G####`, `/lxx-lexeme`, LXX concordance | **CC BY-SA 4.0, share-alike** | Alek Keersmaekers, KU Leuven; Pedalion Trees; el.wikisource |
| ~~CATSS / CCAT Septuagint~~ (replaced 2026-10-10) | former `lxx.db` | non-commercial | CCAT / CATSS Project, University of Pennsylvania |
| **STEPBible TBESH/TBESG** — `STEPBible/STEPBible-Data` | Strong's→gloss dictionary (Lexical line) | CC BY 4.0 | Tyndale House, *STEPBible.org* |

## What the NC clause means here

CC BY-NC (OpenHebrewBible) and CC BY-NC-SA (BHSA) require that the work
and its derivatives are **not used for commercial purposes**. Because the
service still reads BHSA-derived syntax, lexeme and sense data and
crosswalk-derived Strong's mappings (list above), keep the deployment
non-commercial, and carry attribution in any distributed output.

Required attribution line (e.g. in the API/about page):

> Original-language data: unfoldingWord® UHB/UGNT (CC BY-SA 4.0); MACULA
> Hebrew and Greek, Biblica, Inc. / Clear Bible, with Westminster Hebrew Syntax
> (Groves Center) and OpenScriptures morphology (CC BY 4.0); Septuagint:
> GLAUx corpus, Alek Keersmaekers, KU Leuven (CC BY-SA 4.0), with texts from
> el.wikisource (CC BY-SA 3.0) and Pedalion Trees (CC BY-SA 4.0); ETCBC
> BHSA (CC BY-NC-SA 4.0); Open Hebrew Bible Project by Eliran Wong
> (CC BY-NC 4.0).
