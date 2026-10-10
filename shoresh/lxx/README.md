# lxx/

The **Septuagint** (Greek Old Testament) as a per-word original-language store: the Greek OT the English corpus lacks, and the text the NT quotes.

## Source and licence

**GLAUx** (Alek Keersmaekers, KU Leuven, https://github.com/alekkeersmaekers/glaux; **CC BY-SA 4.0**, share-alike). The Septuagint texts (TLG 0527) come from el.wikisource
(CC BY-SA 3.0); lemmas, morphology and syntax are GLAUx's (the Genesis annotation is hand-checked, Pedalion Trees, CC BY-SA 4.0; the rest is automatic: about 98.8% lemmas,
97.2% morphology over the whole corpus). Everything built from it is share-alike, with the attribution in `../spine/ATTRIBUTION.md`.

History: until 2026-10-10 the store came from the CATSS / CCAT-based `eliranwong/LXX-Rahlfs-1935`, licensed for non-commercial use only. Its parser, user declaration and
build step were removed; the file stays in the git history only. `compare_glaux.py` needs a copy of the old `lxx.db` if you want to rerun the before/after report
(`internal-docs/lxx-glaux-before-after.md`).

## Output: `lxx-glaux.db`

`python -m lxx.build_glaux` (from `shoresh/`, needs `spine/spine.db` and `macula/trees-macula.db` for the Strong's lemma lists; downloads the GLAUx XML into `lxx/data/glaux/`)
writes `lxx/data/lxx-glaux.db` (gitignored, re-derivable). It is shipped to the data volume (`deploy/deploy-data.sh shoresh/lxx/data/lxx-glaux.db lxx-glaux.db /opt/shoresh/data`)
and `data.py` reads `/data/lxx-glaux.db` (or `$LXX_DB_PATH`, or the local build).

Table `lxx_words`, schema parallel to the spine's `spine_words`:

| column | meaning |
|---|---|
| `book`, `chapter`, `verse`, `idx` | USFM code, reference and word position in the verse (Septuagint numbering); `canonical` is 1 for the 39 Hebrew-canon books |
| `surface`, `plain` | accented Greek and its lower-case, de-accented form (`αρχη`) |
| `lemma` | the GLAUx lemma |
| `strong` | lemma-level Strong's number from the open UGNT / MACULA Greek lemma lists (every form of ἐγώ is G1473); NULL for lemmas that never occur in the NT |
| `strong_form` (`/verse` `strong_form`) | classic 1890 number of the form where it differs (μου G3450, εἶπεν G2036, Ἰερουσαλήμ G2419, Ἰούδα G2448, Σαούλ G4549 …); the `gloss` of the word comes from it; `/word/G3450` finds these forms |
| `lexid`, `wordid` | stable id of the lemma (31 bits of the SHA-1 of the NFC lemma): the `/lxx-lexeme/{wordid}` key of words without a Strong's number |
| `morph`, `pos` | CCAT-like string (`N.DSF`, `V.AAI3S`); a gap inside it is `-` (`N.-SM`), trailing gaps are dropped, a name with no feature is `N` |
| `morph_inferred` (`/verse` `morph_inferred`) | for names GLAUx leaves untagged: `article`, `preposition` or `syntax`, the rule that filled case / number / gender from the context |
| `is_content` | noun, verb, adjective or numeral |
| `glaux_id` | GLAUx's own word id |

591,686 words · 54 books · 92.8% carry a Strong's number. See `build_glaux.py` for the details of each column and `internal-docs/lxx-glaux-before-after.md` for the comparison with the old store.

Derived tables: `python -m lxx.build_orphan_lexemes` (`resources/lxx_orphan_lexemes`, words without a Strong's number grouped by lemma) and `python -m lxx.build_quotations`
(`resources/ot_nt_quotations`, Odes excluded).
