# resources/

Shared, **Strong's/BCVW-keyed** data resources consumed by **bcv-RAG** and
**shoresh** (and reusable by other projects). This is the repo-root home created
in Phase 0.

## How it's resolved
- **Runtime:** `bcv-RAG/resource_paths.py` → `$BCV_RESOURCES_DIR` if set, else it
  walks up to the nearest `resources/` (depth-independent — no fixed paths).
- **Docker image:** the build context is the **repo root**
  (`docker build -f bcv-RAG/Dockerfile .`); this dir is COPYed to `/app/resources`
  and pinned by `ENV BCV_RESOURCES_DIR=/app/resources`.

## Conventions
- **Anchor:** Clear/BCVW token id for word/instance-level data, else **Strong's**
  (`H####`/`G####`); enrichment columns (Louw-Nida, lemma, refs) when available.
- **Format:** TSV (flat) default, JSONL (nested), sqlite only as a runtime cache.
- **Language codes:** canonical **ISO 639-3 within BCP 47** — `<lang>` means
  `eng`, `spa`, `arb`, `cmn-Hant`, … (file names + in-data `lang` values). Matches
  the Bible-data ecosystem and scales past 2-letter codes; new languages use their
  639-3 code. The runtime accepts legacy 2-letter input (`en`→`eng`) and emits the
  short form (`eng`→`en`) for the web/Hugging Face. Helper: `bcv-RAG/lang.py`.
- **Licenses:** CC-BY-SA and CC-NC both acceptable here — just attribute.

## Contents
| Path | What | Key |
|---|---|---|
| `llm_strongs_glosses/<lang>.tsv` | LLM gap-fill glosses, 7 gloss-thin langs (see its README) | `strong → gloss` |
| `aligned_lex/<lang>.tsv` | surface→Strong's from word alignment, 10 langs | `surface, strong, count, share` |
| `concept_surfaces/<lang>.tsv` | Strong's → surface family (inverse of aligned_lex), 10 langs — query-time recall expansion (R1) | `strong, surface, count, share` |
| `stopwords/<lang>.tsv` | data-derived function-word stopwords, 10 langs (R2) — unioned into the analyzer | `surface, codes, max_share` |
| `analyzer_lang/<lang>.json` | per-language analyzer intent configs, 10 langs | — |
| `book_names.json` | localized Bible book names + aliases, 10 langs | USFM code → names |
| `bible_editions.json` | edition registry (handles OT≠NT composites) | edition id → metadata |
| `strongs_gloss.tsv` | authoritative UBS/English glosses | `strong → gloss` |
| `strongs_freq.tsv` | Strong's frequency + `is_function` flag | `strong` |
| `strongs_keyness.tsv` | per-Strong's biblical-salience weight (`bible − general` zipf; He real, Gr English-proxy) | `strong, keyness, anchor` |
| `word_freq/{hbo,grc}.tsv` | corpus-internal lemma frequency **rank** for the `/words` trainer (lex-keyed, NOT Strong's; OT BHSA / NT Nestle1904) — built by `shoresh/corpus_engine/build_freq.py` | `lex, count, rank` |
| `word_freq/{hbo,grc}_strong.tsv` | TF lexeme → Strong's bridge so `/words` can attach keyness (Gr from Nestle1904 `strong`; He via spine.db 3-tier resolver, ~96% freq-weighted) — built by `shoresh/corpus_engine/build_lex_strong.py` | `lex, strong` |
| `strongs_tw.tsv` | Strong's → unfoldingWord Translation-Words article(s), ranked by occurrence | `strong, tw_article, category, is_kt, lemma, n` |
| `topic_strongs.tsv` | Nave's-style topic → Strong's | `topic_id, strong, verse_count` |
| `speaker_quotations/` | who speaks where — quotations → speaker, verse-range, red-letter flag (S1) | `speaker, …, start_bbcccvvv, end_bbcccvvv, divine` |
| `lxx_bridge.tsv` | Hebrew→Greek LXX bridge (from MACULA `greekstrong`); concept expansion across the Testaments | `hebrew_strong, greek_strong, count` |
| `semantic_domains/<lang>.tsv` | Strong's → semantic domain (SDBG Greek / SDBH Hebrew, from MACULA); broaden a lexeme to its domain (S2) — see its README | `strong, domain_type, domain, label, count, share` |
| `senses/<lang>.tsv` | Strong's → word-sense inventory (polysemy; e.g. ruach → spirit/wind/breath), from MACULA — see its README | `strong, sense, gloss, count, share` |

Build-only intermediates (`strong_lemma.tsv`, `concepts/forms/tw_links.tsv`,
`glosses_overview.tsv`) intentionally stay in `bcv-RAG/` — they are **git-tracked
but not baked into the image** (the Dockerfile does not COPY them, and they're
not part of the published `strongs/` dataset). They're kept under version control
so a clone has the build-chain inputs without regenerating the whole pipeline;
they are read only by build scripts at build time, never at runtime.

**`strongs/`** is different from the above: it's the **standalone published
dataset** (Strong's→words, provenance-marked), **not** consumed by the services.
Its data files are git-ignored and re-derivable (`bcv-RAG/scripts/build_strongs_words*.py`);
only the card (`strongs/README.md`) + `LICENSE` are tracked. Published at
**bcv-commons/strongs** (Hugging Face + GitHub) — see its README.
