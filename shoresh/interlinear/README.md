# interlinear/ — per-occurrence Hebrew/Greek + contextual glosses

Ports `example/aleph/data-api`'s full `API_CONTRACT.md` into shoresh (Python/FastAPI, reading the
same portable SQLite files — no `better-sqlite3`/Node dependency). Source: **globalbibletools/data**
(CC0-1.0 — org-wide default license, no per-repo override) for the per-occurrence words/glosses;
**globalbibletools/study-app** (same pinned-commit discipline) for the pre-baked `eng_bsb.db`
(Berean Standard Bible, public domain) and `sdbh.db`/`sdbg.db` (SDBH/SDBG lexicon meanings,
CC-BY-SA-4.0 — an accepted license here).

## What this is, concretely

Per-**occurrence** (not dictionary-lemma) data: every Hebrew/Greek word in Scripture, Strong's-tagged,
with a human-edited, contextual gloss per language where translators have filled it in. Distinct from
shoresh's existing `/gloss`/`gloss_of` (one canonical dictionary gloss per Strong's) — this is "what
does *this specific occurrence* render as," e.g. Exodus 1:1's `הַבָּאִים` glosses as *"who came"* in
context, not the dictionary form "come."

## Build pipeline

```bash
python -m interlinear.fetch                          # gbt data + strongs-data + eng_bsb/sdbh/sdbg.db
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

- `GET /interlinear/chapter/{book}/{chapter}` — every word's text + Strong's code
  (`hebrewGreekWords`) plus English (Berean Standard Bible) translation lines (`translationLines`)
  for a chapter
- `GET /interlinear/word/{word_id}?lang=eng` — one word: text, Strong's + root, grammar code (raw +
  human-readable `grammarExpanded`), SDBH/SDBG `lexiconMeanings`, contextual gloss in `lang`
- `GET /interlinear/languages` — `{code, name}` for every gloss `.db` built
- `GET /interlinear/similar/{strong}` — deduplicated verse list (with `bookName`) + total count for
  a Strong's code

Word ids are packed `BBCCCVVVWW` (book/chapter/verse/word) — same USFM book numbering as
`references.BOOK_NUMBERS` (verified: GEN=1, EXO=2, MAT=40, matching gbt's own book ids exactly, no
translation table needed).

## Deliberate deviation from `example/aleph/data-api`'s `API_CONTRACT.md`

That contract (written for a SvelteKit `web-app` client, not shoresh) specifies `:book` on
`/chapter/:book/:chapter` as a numeric id (1–66). This port keeps the 3-letter USFM code instead
(`GEN`, not `1`) — every other shoresh route (`/verse`, `/coref`, `/frame`, …) takes book this way,
case-insensitively, and breaking that consistency for one endpoint to match an external client's
convention wasn't worth it. Response field *names* (`hebrewGreekWords`, `translationLines`,
`bookName`, `{code, name}` for languages) do follow the contract exactly, since those don't collide
with any existing shoresh convention. If a caller needs the numeric-book-id contract verbatim, that's
a one-line adapter on their side (`BOOK_NUMBERS`-equivalent lookup), not a shoresh change.

One content (not format) difference, not adapted: shoresh's own book-name resource returns "Song of
Songs" for SNG where `data-api`'s `BOOK_NAMES_BY_ID` says "Song of Solomon" — `bookName`/`bookId`
here reuse shoresh's single existing book-name source rather than a second hardcoded list, so this
one title differs from the original data-api's output.

## Deferred — not in this port

- **The 3-tier gloss resolver** (occurrence-precise → lexeme-aligner statistical fallback → shoresh's
  own dictionary gold) — paused. The per-occurrence data here revealed a richer design question than
  a flat gloss merge (see the many-to-many alignment finding below) that changes what the fallback
  layer should even consume; picking this back up depends on that being resolved first.
- **`mode=root|exact&text=` params, a `root` field, and per-verse `words[].highlighted` flags on
  `/similar`** — reportedly expected by a newer version of the `web-app` client, but not present in
  the `API_CONTRACT.md` this port was built against. Not implemented pending an updated contract.

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
