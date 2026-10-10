# Attribution & licensing — original-language data

The service is built from third-party data. **Since 2026-10-10 it reads no non-commercial (NC) data** (the "NC exit"): the earlier NC sources — BHSA / ETCBC
(CC BY-NC-SA), Open Hebrew Bible (CC BY-NC) and the CATSS / CCAT Septuagint (non-commercial) — are no longer read by the running service, shipped in an image, or
tracked in the repository. They remain only in the git history of this public repository, where they stay under their original terms. Published open datasets are
BHSA-free: see `resources/LICENSES.md` for the register of every tracked data folder.

**What is left to keep in mind**
- **Share-alike.** UHB / UGNT, GLAUx, el.wikisource and Pedalion are CC BY-SA: data derived from them (`spine.db`, `lxx-glaux.db`, the tables built from them) stays CC BY-SA
  with attribution, including what the API returns from them.
- **GLAUx annotation.** Its automatic lemmas, morphology and syntax were trained by the author on treebanks that include non-commercial ones (PROIEL, Gorman); the author
  releases the corpus as CC BY-SA. This project relies on that release and cites GLAUx (decision 2026-10-10).
- **Offline tools.** `corpus_engine/` and some `macula/build_*` scripts can read the BHSA text-fabric corpus on a developer machine (a CC BY-NC-SA download that is not in the
  repo or any image). Their outputs are not tracked or served; the guard test (`tests/test_nc_register.py`) keeps BHSA-keyed inputs out of git.
- `spine.db` is built from UHB / UGNT (unfoldingWord, CC BY-SA 4.0) only and serves the Greek NT `/verse` words, `/morph` and the `/gloss` counts. Already open:
  `lexeme-spine-macula.db` (CC BY, MACULA only), `semantic-neighbors`, `prior-pack`, `hebrew-word-senses`, `hebrew-lexical-references`, `strongs`.
- `ETCBC/nestle1904` (the Greek half of the offline engine) is MIT (checked 2026-10-09) and a conversion of Clear-Bible MACULA Greek (CC BY 4.0): keep the attribution to ETCBC and Clear Bible.

**History of the exit:** 2026-10-07 plan and register; 2026-10-09 service reads MACULA only (structure, trees, syntax search, `/words`, senses, `/verse` Hebrew, clause search), BHSA files and `hbo.db`
retired, BHSA-keyed inputs untracked; 2026-10-10 Septuagint on GLAUx, CATSS store, parser and user declaration removed, BHSA / Open Hebrew Bible comparison files removed from `spine/`.

## Sources

| Source | Used for | License | Attribution |
|---|---|---|---|
| **unfoldingWord Hebrew Bible (UHB)** — `unfoldingWord/hbo_uhb` | OT spine (Strong's, lemma, morph per word) | CC BY-SA 4.0 | unfoldingWord® |
| **unfoldingWord Greek NT (UGNT)** — `unfoldingWord/el-x-koine_ugnt` | NT spine | CC BY-SA 4.0 | unfoldingWord® |
| ~~BHSA~~ — `ETCBC/bhsa` (no longer read by the service) | former syntactic roles | CC BY-NC-SA 4.0 | ETCBC, VU Amsterdam |
| ~~OpenHebrewBible~~ — `eliranwong/OpenHebrewBible` (no longer used) | former crosswalk / versification map | CC BY-NC 4.0 | Eliran Wong, *Open Hebrew Bible Project* |
| **MACULA Hebrew** — `Clear-Bible/macula-hebrew` (`WLC/lowfat`) | verse structure, trees, syntax search, `/words` feed (`trees-macula.db`); lexeme spine | CC BY 4.0 | Biblica, Inc. / Clear Bible; Westminster Hebrew Syntax © Groves Center (CC BY 4.0); OpenScriptures Hebrew Bible morphology (CC BY 4.0); Westminster Leningrad Codex text (public domain) |
| **MACULA Greek** — `Clear-Bible/macula-greek` (`Nestle1904/lowfat`) | Greek structure, trees, syntax search (`trees-macula.db`); Greek spine | CC BY 4.0 | Clear Bible (Nestle 1904 text: public domain) |
| **GLAUx** (KU Leuven, A. Keersmaekers) — Septuagint texts from el.wikisource (CC BY-SA 3.0), Genesis annotation Pedalion Trees (CC BY-SA 4.0) | `lxx-glaux.db`: `/verse` `lxx` words, `/word/G####`, `/lxx-lexeme`, LXX concordance | **CC BY-SA 4.0, share-alike** | Alek Keersmaekers, KU Leuven; Pedalion Trees; el.wikisource |
| ~~CATSS / CCAT Septuagint~~ (replaced 2026-10-10) | former `lxx.db` | non-commercial | CCAT / CATSS Project, University of Pennsylvania |
| **STEPBible TBESH/TBESG** — `STEPBible/STEPBible-Data` | Strong's→gloss dictionary (Lexical line) | CC BY 4.0 | Tyndale House, *STEPBible.org* |

## Attribution

CC BY and CC BY-SA require attribution in any distributed output (an API or about page counts).

Required attribution line (e.g. in the API/about page):

> Original-language data: unfoldingWord® UHB/UGNT (CC BY-SA 4.0); MACULA
> Hebrew and Greek, Biblica, Inc. / Clear Bible, with Westminster Hebrew Syntax
> (Groves Center) and OpenScriptures morphology (CC BY 4.0); Septuagint:
> GLAUx corpus, Alek Keersmaekers, KU Leuven (CC BY-SA 4.0), with texts from
> el.wikisource (CC BY-SA 3.0) and Pedalion Trees (CC BY-SA 4.0).
