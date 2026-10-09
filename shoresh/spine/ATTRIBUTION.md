# Attribution & licensing — original-language spine

The spine is built from third-party data. Several sources are
**non-commercial (NC)**, which makes `spine.db` and the service data derived from
it **non-commercial**. This project operates under that constraint **while it
migrates off those sources** (status below). Published open datasets are BHSA-free:
see `resources/LICENSES.md`.

**Status 2026-10-07 (NC exit in progress):**
- Still NC and used by the running service: the BHSA / ETCBC Nestle1904 text-fabric
  corpus (`/structure*`, `/syntax/search`, trees), `hbo.db` (BHSA lexeme ids, stems,
  senses), the Hebrew and Greek clause-search databases, `spine.db` (UHB plus the
  OpenHebrewBible crosswalk), `resources/senses/hbo_lex.tsv`, and the BHSA-keyed
  `word_glosses/` and `lexicons/`.
- The embedded `index.db` (bcv-RAG) is built from open resources (translations, notes,
  commentary) and carries exactly one BHSA-derived table, `clause_dependencies`
  (20,791 rows). Its embeddings do not contain a BHSA-derived spine prefix.
- Already open: the published `lexeme-spine-macula.db` (CC BY, MACULA only, Psalm titles
  from Hebrew-only spans), `semantic-neighbors`, `prior-pack`, `hebrew-word-senses`,
  `hebrew-lexical-references`, `strongs`.
- Step 3 built (2026-10-08, `STRUCTURE_BASE=macula`, not yet the default): structure,
  trees, syntax search and the `/words` feed from MACULA lowfat trees (CC BY 4.0;
  UBS MARBLE fields are never read). Once flipped, the BHSA / Nestle1904 text-fabric
  corpus is only read by clause search (step 5) and the build scripts.
- Replacement path: MACULA Hebrew and Greek (CC BY 4.0), step by step; the NC-only
  parts above are removed as each is replaced.

## Sources

| Source | Used for | License | Attribution |
|---|---|---|---|
| **unfoldingWord Hebrew Bible (UHB)** — `unfoldingWord/hbo_uhb` | OT spine (Strong's, lemma, morph per word) | CC BY-SA 4.0 | unfoldingWord® |
| **unfoldingWord Greek NT (UGNT)** — `unfoldingWord/el-x-koine_ugnt` | NT spine | CC BY-SA 4.0 | unfoldingWord® |
| **BHSA** — `ETCBC/bhsa` (via bcv-corpus) | syntactic roles (Layer 4) | CC BY-NC-SA 4.0 | ETCBC, VU Amsterdam |
| **OpenHebrewBible** — `eliranwong/OpenHebrewBible` | BHSA↔Strong's crosswalk (`002`), versification map (`019`) | **CC BY-NC 4.0** | Eliran Wong, *Open Hebrew Bible Project* |
| **MACULA Hebrew** — `Clear-Bible/macula-hebrew` (`WLC/lowfat`) | verse structure, trees, syntax search, `/words` feed (`trees-macula.db`); lexeme spine | CC BY 4.0 | Biblica, Inc. / Clear Bible; Westminster Hebrew Syntax © Groves Center (CC BY 4.0); OpenScriptures Hebrew Bible morphology (CC BY 4.0); Westminster Leningrad Codex text (public domain) |
| **MACULA Greek** — `Clear-Bible/macula-greek` (`Nestle1904/lowfat`) | Greek structure, trees, syntax search (`trees-macula.db`); Greek spine | CC BY 4.0 | Clear Bible (Nestle 1904 text: public domain) |
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
> (Groves Center) and OpenScriptures morphology (CC BY 4.0); ETCBC
> BHSA (CC BY-NC-SA 4.0); Open Hebrew Bible Project by Eliran Wong
> (CC BY-NC 4.0).
