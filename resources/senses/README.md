# senses/

Lexeme-level **Strong's → word-sense inventory** (S2 / Phase 1). For each
Strong's, its distinct word-senses with a representative gloss + frequency —
i.e. **polysemy** (H7307 *ruach* → spirit / wind / breath / side; G3056 *logos*
→ word / account / speech / report).

**Senses disambiguate; domains group.** Use this to show or filter a lexeme's
range of meanings; use `../semantic_domains/` to broaden a lexeme to its
semantic field. Built by `bcv-RAG/scripts/build_senses.py` from **MACULA**
(CC BY 4.0, Biblica + UBS MARBLE).

## Schema
`<lang>.tsv` columns: `strong  sense  gloss  count  share`
- `sense` = MACULA sense number (1, 2, …); `gloss` = the **dominant English
  rendering** of that sense (a label — *not* the formal SDBH/SDBG sense title,
  which lives in the LFS-gated senses XML).
- `count` = occurrences of that sense; `share` = count / the lexeme's total.
- primary sense always kept; secondaries when count ≥ 2; sorted by strong, count desc.

## Sources
- **hbo** (5,607 lexemes): macula-hebrew WLC TSV — `sensenumber` + `english` per word (direct).
- **grc** (4,565 lexemes): `sources/Clear/wordsense/greek-wordsenses.tsv`
  (word_id → sense_number) joined to the Nestle1904 TSV (word_id = `xml:id` → strong, gloss).

## Caveat
Sense *labels* are translation glosses, so two distinct senses can share a gloss
(e.g. *dabar* senses 2 & 3 both surface as "thing"). The sense *number* still
distinguishes them; the gloss is a human-readable hint. Upgrade path: join the
formal sense titles from `sdbh-senses.xml` / SDBG senses when the LFS fetch is wired.

## Rebuild
```bash
python -m scripts.build_senses --lang hbo
python -m scripts.build_senses --lang grc
```
