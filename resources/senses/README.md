# senses/

Word-sense inventories — for a single lexeme, its distinct senses with a
representative gloss + frequency (i.e. **polysemy**: *ruach* → spirit / wind /
breath; *logos* → word / account / speech). **Senses disambiguate; domains
group** — use `../semantic_domains/` to broaden a lexeme to its semantic field.

Two layers live here:

| file | key | what |
|---|---|---|
| `hbo.tsv`, `grc.tsv` | **Strong's** | per-Strong's sense inventory from the **UBS open release** (rebuilt 2026-10) |
| `hbo_lex.tsv` | **BHSA lex + stem** (LOCAL ONLY since 2026-10-09, git-ignored; replaced by the MACULA `hebrew-word-senses`) | newer Hebrew sense layer, derived from Hebrew **context** — binyan-aware, splits the homographs Strong's conflates |

> **Licensing.** `hbo.tsv` / `grc.tsv` are built by `shoresh/macula/build_ubs_open.py` from the UBS
> Dictionary of Biblical Hebrew and the UBS Dictionary of the Greek New Testament (© United Bible
> Societies 2023, **CC BY-SA 4.0**, github.com/ubsicap/ubs-open-license @ `33dcc8c`): one row per
> dictionary sense, `sense` = its order in the entry, `gloss` = its first English gloss, `count` = the
> Scripture references UBS lists for it. Attribute UBS and keep anything built from them CC BY-SA.
> (Until 2026-10 they came from the MARBLE sense layer bundled with MACULA, "used with permission" and
> not redistributable.) `hbo_lex.tsv` is our own: Hebrew-context clusters labelled from curated per-stem
> glosses and MACULA's CC BY glosses; it is keyed on, and built from, BHSA (see the BHSA licence note in
> the repo README).

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
