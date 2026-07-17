# interlinear/ — per-occurrence Hebrew/Greek + contextual glosses

Ports `example/aleph/data-api`'s full `API_CONTRACT.md` into shoresh (Python/FastAPI, reading the
same portable SQLite files — no `better-sqlite3`/Node dependency). Three pinned sources:
**globalbibletools/data** (CC0-1.0) for per-occurrence words/glosses; a small pinned text-file fetch
from **globalbibletools/study-app** for Strong's-code→root-word lookup; **BSB-publishing/bsb-data-output**
(CC0/CC-BY-4.0) for English translation text + headings. Lexicon meanings do NOT come from an
externally-fetched `.db` — see the deviation note below.

## What this is, concretely

Per-**occurrence** (not dictionary-lemma) data: every Hebrew/Greek word in Scripture, Strong's-tagged,
with a human-edited, contextual gloss per language where translators have filled it in. Distinct from
shoresh's existing `/gloss`/`gloss_of` (one canonical dictionary gloss per Strong's) — this is "what
does *this specific occurrence* render as," e.g. Exodus 1:1's `הַבָּאִים` glosses as *"who came"* in
context, not the dictionary form "come."

## Build pipeline

```bash
python -m interlinear.fetch                          # gbt data + strongs-code->root-word text files + bsb-data-output
python -m interlinear.build_hebrew_greek              # -> data/hebrew_greek.db (448,269 words)
python -m interlinear.build_gloss eng spa fra por are  # -> data/gloss/<lang>.db
python -m interlinear.build_gloss                      # every real gloss language found (~38)
```

Pinned to commit `f5af0eb89e4b845b2b30beb9f4360b50ddb08f6a` (2026-07-12) in `fetch.py` for
globalbibletools/data, `a0bcfbbcfe217c66f31b1c886dd95c4424061e0e` (2026-07-17) for bsb-data-output —
same discipline as `macula/parse.py`'s MACULA fetch and `lxx/parse.py`'s `LXX_COMMIT`: re-pin
deliberately (bump the relevant `*_COMMIT`, re-fetch, re-build, re-verify), never float on live HEAD.
All `.db` files + fetched source trees (`data/gbt/`, `data/bsb/`) are gitignored, rebuilt from source.

**Coverage at the current pin** (verified against the raw JSON, not just the built db):
| lang | coverage | note |
|---|---|---|
| eng | **100%** (real words) | the 99% the build script prints includes 1,324 inert `-01`/`-02` placeholder slots — zero nulls on real word ids, verified directly |
| spa / fra | 71% / 72% | |
| por / are | 68% / 68% | |
| ~33 more | JSON present, not yet built — completeness varies widely, some near-empty | run `build_gloss` with no args to discover + build all |

## Endpoints (in `shoresh/app.py`)

- `GET /interlinear/chapter/{book}/{chapter}` — every word's text + Strong's code
  (`hebrewGreekWords`) plus English translation lines (`translationLines`, from BSB-publishing's
  bsb-data-output — headings interleaved by verse) for a chapter
- `GET /interlinear/word/{word_id}?lang=eng` — one word: text, Strong's + root, grammar code (raw +
  human-readable `grammarExpanded`), sense-level `lexiconMeanings` (from shoresh's own in-house
  `resources/senses/` tables — see the deviation note below), contextual gloss in `lang`
- `GET /interlinear/languages` — `{code, name}` for every gloss `.db` built
- `GET /interlinear/similar/{strong}?mode=root|exact&text=<word>&limit=` — `root` mode (default):
  every verse sharing `strong`'s Strong's code; `exact` mode: every verse containing `text` exactly
  (punctuation/case-insensitive), independent of Strong's code. Deduplicated verse list (with
  `bookName` + each verse's full `words[]`, matching word `highlighted`) + true total + the
  Strong's code's `root` word

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

**`lexiconMeanings` is NOT sourced from SDBH/SDBG** (`sdbh.db`/`sdbg.db`), unlike the original
data-api. It's built from `resources/senses/{grc,hbo_lex}.tsv` — the same UBS-derived sense/gloss
data, already in-house, already correctly licensed and caveated, already used by `/senses` and
`/lexeme` (see `data.lexicon_meanings_for_strongs`). Shape-compatible with the contract
(`lexId`/`lemma`/`grammar`/`definitionShort`/`comments`/`glosses`), but `lexId` is a locally-
synthesized int (not SDBH's own numbering — we don't carry that identifier space), and
`grammar`/`comments` are always null (not available at this granularity in our resources; Hebrew
uses `grammar` for the binyan/stem instead, since we do have that).

## Deferred — not in this port

- **The 3-tier gloss resolver** (occurrence-precise → lexeme-aligner statistical fallback → shoresh's
  own dictionary gold) — paused. The per-occurrence data here revealed a richer design question than
  a flat gloss merge (see the many-to-many alignment finding below) that changes what the fallback
  layer should even consume; picking this back up depends on that being resolved first.
- **`translationLines[].format` fidelity for verse lines.** bsb-data-output's `display/` files carry
  headings with their real level (`s1`/`s2`/`r`, from `headings.jsonl`), but no per-verse paragraph/
  poetry style marker (`m`/`q1`/`b`/…) the way the old study-app `eng_bsb.db` table did — that
  distinction isn't in this source. Every verse line is emitted as `format: "m"`. Contract-compliant
  (the field is just `string`), just less granular than the original eng_bsb.db-backed version was.

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
