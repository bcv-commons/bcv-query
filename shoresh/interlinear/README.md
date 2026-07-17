# interlinear/ — per-occurrence Hebrew/Greek + contextual glosses

Ports `example/aleph/data-api`'s core contract into shoresh (Python/FastAPI, reading the same
portable SQLite files — no `better-sqlite3`/Node dependency). Source: **globalbibletools/data**
(CC0-1.0 — org-wide default license, no per-repo override; the one exception, SDBH/SDBG lexicon
data, is CC-BY-SA-4.0 and is *not* included here — see "Deferred" below).

## What this is, concretely

Per-**occurrence** (not dictionary-lemma) data: every Hebrew/Greek word in Scripture, Strong's-tagged,
with a human-edited, contextual gloss per language where translators have filled it in. Distinct from
shoresh's existing `/gloss`/`gloss_of` (one canonical dictionary gloss per Strong's) — this is "what
does *this specific occurrence* render as," e.g. Exodus 1:1's `הַבָּאִים` glosses as *"who came"* in
context, not the dictionary form "come."

## Build pipeline

```bash
python -m interlinear.fetch                          # pinned commit -> interlinear/data/gbt/
python -m interlinear.build_hebrew_greek              # -> data/hebrew_greek.db (448,269 words)
python -m interlinear.build_gloss eng spa fra por are  # -> data/gloss/<lang>.db
python -m interlinear.build_gloss                      # every real gloss language found (~38)
```

Pinned to commit `f5af0eb89e4b845b2b30beb9f4360b50ddb08f6a` (2026-07-12) in `fetch.py` — same
discipline as `macula/parse.py`'s MACULA fetch and `lxx/parse.py`'s `LXX_COMMIT`: re-pin
deliberately (bump `GBT_DATA_COMMIT`, re-fetch, re-build, re-verify coverage), never float on live
HEAD. All `.db` files + the fetched `data/gbt/` are gitignored, rebuilt from source.

**Coverage at the current pin** (verified against the raw JSON, not just the built db):
| lang | coverage | note |
|---|---|---|
| eng | **100%** (real words) | the 99% the build script prints includes 1,324 inert `-01`/`-02` placeholder slots — zero nulls on real word ids, verified directly |
| spa / fra | 71% / 72% | |
| por / are | 68% / 68% | |
| ~33 more | JSON present, not yet built — completeness varies widely, some near-empty | run `build_gloss` with no args to discover + build all |

## Endpoints (in `shoresh/app.py`)

- `GET /interlinear/chapter/{book}/{chapter}` — every word's text + Strong's code for a chapter
- `GET /interlinear/word/{word_id}?lang=eng` — one word: text, Strong's + root, grammar code, contextual gloss in `lang`
- `GET /interlinear/languages` — which gloss `.db`s are built
- `GET /interlinear/similar/{strong}` — deduplicated verse list + total count for a Strong's code

Word ids are packed `BBCCCVVVWW` (book/chapter/verse/word) — same USFM book numbering as
`references.BOOK_NUMBERS` (verified: GEN=1, EXO=2, MAT=40, matching gbt's own book ids exactly, no
translation table needed).

## Deferred — not in this port

- **`eng_bsb.db` (full Berean Standard Bible text)** and **`sdbh.db`/`sdbg.db` (SDBH/SDBG lexicon
  meanings)** — these are pre-baked *assets* bundled with the original Flutter app, not derived from
  the `globalbibletools/data` JSON this module builds from, so they're not reproducible via the pinned
  fetch here. `sdbh`/`sdbg` are also CC-BY-SA-4.0 (a specified license override, not the org's CC0
  default) and likely overlap shoresh's existing `/domain?axis=sdbg` (UBS domain-mining) data —
  worth reconciling rather than importing a second parallel copy. Not started.
- **`morphology.js`'s grammar-code expansion** ("N-mpc" → human-readable) — `grammar` is returned as
  the raw code only; the display expansion wasn't ported.
- **The 3-tier gloss resolver** (occurrence-precise → lexeme-aligner statistical fallback → shoresh's
  own dictionary gold) — paused. The per-occurrence data here revealed a richer design question than
  a flat gloss merge (see the many-to-many alignment finding below) that changes what the fallback
  layer should even consume; picking this back up depends on that being resolved first.

## An important finding, not yet acted on here

The `-01`/`-02` suffix mechanism in the gloss JSON (documented in `build_gloss.py`'s docstring) isn't
just "duplicate a name for a genealogy list" — verified against Matthew 1:13, it's genuine **many-to-
many positional realignment**: consecutive source words can have *no entry at all* in the target
file, with their content represented via synthetic continuation slots anchored to an *earlier* source
word. This is occurrence-level source↔target alignment data, structurally the same *kind* of thing
`bcv-commons/lexeme-alignments`' underlying Clear gold represents (just currently locked inside a
gloss-JSON format, human-edited, and richer). Judged to be lexeme-aligner's work to extract and own,
not shoresh's — see `internal-docs/gbt-alignment-handover.md` for the handover package (findings +
a small proof-of-concept extraction script + a proposed schema).
