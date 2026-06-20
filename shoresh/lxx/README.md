# lxx/

The **Septuagint** (Greek Old Testament) as a per-word original-language
store — the Tier 1 gap-fill (the Greek OT the current English corpus lacks,
and the text the NT quotes). See
[`../../docs/resource-inventory.md`](../../docs/resource-inventory.md) Gap 1
for the source survey.

## Source

`eliranwong/LXX-Rahlfs-1935`, the assembled MyBible export
`11_end-users_files/MyBible/Bibles/LXX_final_main.csv` (Rahlfs 1935 base,
**B-text** recension; the A-text is `LXX_final_alternate.csv`). Pinned to
commit `a1b5ff1` (see `LXX_COMMIT` in `parse.py`).

**Licence:** CATSS-derived — **non-commercial**, with attribution. Sign and
keep [`../legal/CATSS-user-declaration.md`](../legal/CATSS-user-declaration.md);
attribution in [`../spine/ATTRIBUTION.md`](../spine/ATTRIBUTION.md). The
public-domain **Swete 1930** is the zero-CATSS fallback if needed.

## Output: `lxx.db` (gitignored, re-derivable)

Table `lxx_words`, schema parallel to the spine's `spine_words` so canonical
OT verses join **LXX ↔ spine ↔ BHSA** on `(book, chapter, verse, strong)`:

| column | meaning |
|---|---|
| `book` | USFM code (canonical) or USFM-deutero code; `canonical` flags which |
| `chapter`, `verse`, `idx` | reference + word position in the verse |
| `surface` | accented Greek (`ἀρχῇ`) |
| `plain` | monotonic, de-accented form (`αρχη`) — matches Greek-model orthography, via `spine.common.to_modern_form` |
| `strong` | Strong's number (int; first `<S>` after the `<m>` tag) — NULL for rare untagged words |
| `morph`, `pos` | CCAT/Packard code (`N.DSF`) and head POS (`N`) |
| `is_content` | POS ∈ {N, V, A} — same content rule as the spine |
| `canonical` | 1 = the 39 OT books (join the spine); 0 = deuterocanon |

## Coverage (full parse)

**586,992 words · 54 books** (39 canonical + 15 deuterocanonical) · 93% carry
Strong's · 48% content words. All MyBible book numbers map (no unmapped books).

## Run (from `shoresh/` with `PYTHONPATH=.`)

```bash
PYTHONPATH=. python3 -m lxx.parse              # smoke test: Genesis only
PYTHONPATH=. python3 -m lxx.parse --canonical  # the 39 canonical OT books
PYTHONPATH=. python3 -m lxx.parse --all        # full LXX incl. deuterocanon
PYTHONPATH=. python3 -m lxx.parse --book PSA ISA
```

First run downloads the pinned CSV to `data/` (cached); `--src PATH` uses a
local copy.

## Next (follow-ups)

- **Lemmas** — the inline data carries a lexeme id; resolve it against the
  repo's `02_lexemes` / `09a_LXX_lexicon` tables to add a `lemma` column.
- **Versification** — LXX numbering differs from MT/Protestant (esp. Psalms,
  Jeremiah, Esdras B = Ezra+Nehemiah); a mapping is needed before tight
  verse-level LXX↔BHSA joins.
- **Embedding** — feed `plain` (or clause windows) to a Greek model
  (SPhilBERTa) behind the service's embedding interface.
