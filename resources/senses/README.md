# senses/

Word-sense inventories — for a single lexeme, its distinct senses with a
representative gloss + frequency (i.e. **polysemy**: *ruach* → spirit / wind /
breath; *logos* → word / account / speech). **Senses disambiguate; domains
group** — use `../semantic_domains/` to broaden a lexeme to its semantic field.

Two layers live here:

| file | key | what |
|---|---|---|
| `hbo.tsv`, `grc.tsv` | **Strong's** | older per-Strong's sense inventory, from MACULA |
| `hbo_lex.tsv` | **BHSA lex + stem** | newer Hebrew sense layer, derived from Hebrew **context** — binyan-aware, splits the homographs Strong's conflates |

> ⚠️ **Licensing — NOT CC BY 4.0.** The Strong's-keyed `hbo.tsv`/`grc.tsv` are
> derived from **UBS MARBLE** (SDBG/SDBH) sense data, which MACULA's LICENSE
> carries **"used with permission,"** *outside* its CC BY 4.0 grant. Reference
> data under UBS terms — not safe to redistribute/use commercially as CC-BY
> without your own UBS permission. See `../semantic_domains/README.md`.
> (`hbo_lex.tsv` clusters Hebrew context and labels from the curated per-stem
> glosses + scrubbed MACULA glosses — same caution applies to the MACULA-derived
> labels.)

---

## `hbo_lex.tsv` — the lex-anchored Hebrew sense layer

The served truth for Hebrew word-senses. **Guiding principle:** Hebrew word data
is anchored on the BHSA `lex` (and per-occurrence node), **not** Strong's — `lex`
distinguishes homographs that Strong's conflates, and the sense set is split per
verbal **stem**. Strong's/English/coarser senses are *derived* from this.

How it's built (full pipeline: [`docs/sense-layer-pipeline.md`](../../docs/sense-layer-pipeline.md)):
per-occurrence senses are clustered on **bge-m3 embeddings of the Hebrew clause**;
the dominant sense is labeled with the curated per-stem gloss, sub-senses with
scrubbed MACULA glosses.

Schema — `lex  stem  sense  gloss  count  share`:
- `lex` = BHSA lexeme id (e.g. `<BD[`); `stem` = verbal binyan (`qal`, `nif`,
  `piel`, `hif`, …), empty for non-verbs.
- `sense` = sense number within (lex, stem); `gloss` = representative label.
- `count` = occurrences of that sense; `share` = count / the (lex, stem) total.

Build: `bcv-RAG/scripts/build_lex_senses.py` + `cluster_senses_hebrew.py`. The
per-occurrence sidecar (`../occurrences/hbo.db`) and `context_emb.npz` are
**gitignored build artifacts**, regenerable from BHSA/MACULA.

---

## `hbo.tsv` / `grc.tsv` — the older Strong's-keyed inventory

Schema — `strong  sense  gloss  count  share`:
- `sense` = MACULA sense number; `gloss` = the **dominant English rendering** of
  that sense (a label — *not* the formal SDBH/SDBG sense title, which lives in the
  LFS-gated senses XML).
- `count` = occurrences; `share` = count / the lexeme's total.
- primary sense always kept; secondaries when count ≥ 2; sorted by strong, count desc.

Sources:
- **hbo** (5,607 lexemes): macula-hebrew WLC TSV — `sensenumber` + `english` per word (direct).
- **grc** (4,565 lexemes): `sources/Clear/wordsense/greek-wordsenses.tsv`
  (word_id → sense_number) joined to the Nestle1904 TSV (word_id = `xml:id` → strong, gloss).

Caveat: sense *labels* are translation glosses, so two distinct senses can share a
gloss (*dabar* senses 2 & 3 both surface as "thing"); the sense *number* still
distinguishes them.

---

## Forward
- Polish sub-sense labels in `hbo_lex.tsv` (the scrubbed-MACULA secondaries are the
  rough edge).
- Sense-aware synthesis: tag retrieval/answers with the resolved sense, not just the lexeme.
- Upgrade path for the Strong's tables: join the formal SDBH/SDBG sense titles from
  `sdbh-senses.xml` when the LFS fetch is wired.

## Rebuild
```bash
python -m scripts.build_senses --lang hbo     # Strong's-keyed hbo.tsv
python -m scripts.build_senses --lang grc     # Strong's-keyed grc.tsv
python -m scripts.build_lex_senses            # lex-keyed hbo_lex.tsv (+ cluster_senses_hebrew)
```
