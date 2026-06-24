# Roadmap

This is where the project is going — and how to help get it there. It's written
for newcomers: if you've read the [main README](../README.md) and the service
deep-dives ([bcv-RAG](bcv-RAG.md), [shoresh](shoresh.md)), you're ready.

Most of what's planned here is **data work, not plumbing** — and a lot of it makes
for friendly, self-contained first contributions. Read on for the pattern, the
ordered plan, the open datasets to build from, and where help is most wanted.

---

## The core idea

Almost every feature on this roadmap is the **same move**, already proven several
times:

> Project an existing dataset through the **Strong's key** (or the token-alignment
> id) into a flat build-time table. Commit it. Ship it in the image. Read it
> read-only at query time.

That's how `concept_expand` (word → Strong's), `filter_biblical_words` (drop
function words), and `name_bridge` (localized name → Strong's → entity) were
built — all from `resources/aligned_lex/<lang>.tsv`. Every item below is another
table built the same way. Because they're all keyed on Strong's (or the
Clear/BCVW token id), they compose: a passage tagged with
**{concept, speaker, genre, speech-act, semantic-domain}** lets retrieval *and*
the answer-writer reason like a translator.

This makes contributions approachable: most items are **"build a table, commit it,
done"** — no need to touch the live serving path.

## Status at a glance

| Phase | Theme | Status |
|---|---|---|
| **0** | Shared `resources/` + repo-root Docker build | ✅ **Done** — `resources/` is live, both services read it |
| **1** | Free recall wins (no new data) | ⬜ Open — great first issues |
| **2** | Headline ingests (speaker index, semantic domains) | ⬜ Open — biggest leap |
| **3** | Better answers (concept briefs, speech-acts, genre) | ⬜ Open |
| **4** | Breadth (OT-in-NT, proper nouns, synoptics, geography) | ⬜ Open |
| **5** | Depth (association graph, MWEs, discourse, versification) | ⬜ Open |

**Already live:** the full retrieval pipeline (13 retrievers + RRF + expansion
strategies); the multilingual core (10 languages — aligned_lex, Bibles, book
names, per-language analyzer configs); the Strong's name-bridge; in-language
synthesis; the MCP server; clause-level semantic search in shoresh; LLM gap-fill
glosses for the gloss-thin languages; **canonical ISO 639-3 / BCP 47 language
codes** (legacy 2-letter still accepted); and the **published `strongs` dataset**
(see Publishing).

## Publishing & open data

Reusable datasets are published under the **[`bcv-commons`](https://github.com/bcv-commons)**
org (same handle on GitHub and Hugging Face), independent of the services so
data-only users never touch the code.

**Strategy — full on Hugging Face, minimal on GitHub:**
- **Hugging Face** holds the *complete* dataset (LFS-backed, all tiers, a
  browsable viewer, `load_dataset(...)`). It's the primary home.
- **GitHub** carries a *shop window* — README (→ HF), LICENSE, and small samples —
  for discovery; it points to HF for the full data. No large files on plain git.

**Live:** **[`bcv-commons/strongs`](https://huggingface.co/datasets/bcv-commons/strongs)** —
Strong's→words, provenance-marked, 10 aligned + 12 gloss languages, four tiers
(`glosses`, `surfaces`, `surfaces_by_method`, `attestations`) + Parquet mirrors.
Card + build: [`resources/strongs/`](../resources/strongs); the dataset itself is
git-ignored here (re-derivable, published externally).

**Next:** **`bcv-commons/bibles`** — the many Bible translations that don't yet have
a home, same pattern (build/normalize → card → HF + GitHub shop window).

Conventions for any published dataset: anchored on Hebrew/Greek (Strong's + lemma,
never English), one language per file, canonical ISO 639-3 / BCP 47 codes, and
**every row provenance-marked** (`method` / `source` / `review`). The build +
publish tooling lives in `bcv-RAG/scripts/build_strongs_words*.py` (public) and
operator-only publish scripts (kept out of the public repo).

## Conventions (read before building a table)

**Anchor — in priority order:**
1. **Clear/BCVW token id** (the MACULA alignment id, e.g. `n40010030011` ≈
   book·chapter·verse·word·part) — for **word/instance-level** data (speaker,
   quotations, domain-in-context). Same scheme as our ingested alignments.
2. **Strong's** (`H####`/`G####`, normalized) — for **concept/lexeme-level** data
   (glosses, surface families, semantic domains). Also the universal key that
   makes a resource reusable by other projects.
3. **Enrichment columns** when available: Louw-Nida domain #, SDGNT/SDBH lexeme
   id, lemma, verse ref (BBCCCVVV).

*Rule of thumb:* instance/passage data → token id (+ verse ref); concept/lexeme
data → Strong's. Carry the other key as an extra column when you can.

**Format:** TSV by default (flat, git-diffable, grep-able, UTF-8, zero parser);
JSONL for nested records; SQLite **only** as a runtime cache (load the canonical
TSV/JSONL into `index.db` for joins — the flat files stay the source of truth).
Every file gets a `# source= / license= / date=` header; every folder gets a
README (source, license, schema, key).

**Location:** `resources/<snake_case_dataset>/`, catalogued in
[`resources/README.md`](../resources). Licenses: both CC-BY-SA and CC-NC are
acceptable — just attribute, and keep SA-derived data under a compatible license.

---

## The plan, phase by phase

### Phase 1 — free recall wins *(no new data, hours of work)*

- **R1 · Concept → surface family** *(highest leverage, near-zero cost)*. Invert
  `aligned_lex`: `Strong's → {all surface renderings} per language`. At query
  time, expand a query word to every in-language rendering of its concept before
  full-text search — fixing recall on prose (study notes, other-language Bibles)
  where exact match misses inflections/synonyms. Build = `GROUP BY strong` over a
  file we already ship. **Do this first.**
  → **Done.** Table: [`resources/concept_surfaces/<lang>.tsv`](../resources/concept_surfaces)
  (`scripts/build_concept_surfaces.py`), 10 langs. Wired at query time:
  `concept_expand.expand_surfaces` → `analyzer` adds each concept word's
  in-language renderings to the FTS query (es "amor" → also "caridad"; "enseña" →
  its conjugations). English is **synonym-only**: the FTS index is porter-stemmed
  so inflections already match — we drop same-stem surfaces (via SQLite's own
  porter tokenizer) and keep only cross-lemma synonyms (covenant→treaty,
  salvation→deliverances, faith→belief). Eval (`eval/set/v2-expansion`): recall
  unchanged (1.0), no regression, + a guard case `surface_expand_covenant_treaty_en`.
- **R2 · Data-derived stopwords per language**. Surfaces aligning to *function*
  Strong's (articles/particles), or high-frequency-low-keyness words, → an
  auto stopword list per language. Replaces the hand-authored lists in
  `analyzer_lang/<lang>.json` and retires the "needs native review" caveat.
  → **Done.** [`resources/stopwords/<lang>.tsv`](../resources/stopwords)
  (`scripts/build_stopwords.py`): a surface whose primary renderings (share ≥
  0.10) are all function Strong's AND that occurs ≥10× → stopword. 10 langs,
  ~1,671 words. The analyzer **unions** them with the hand lists, adding the
  archaic/biblical particles they miss (thence, unto, verily). Composes with R1:
  "verily I say unto you about grace" → `grace OR favour OR gratitude`.

### Phase 2 — headline ingests *(the biggest single leap)*

- **S1 · Speaker / red-letter index**. *Who says what to whom.* This is an
  **ingest, not a derivation** — open token-aligned datasets already label the
  speaker of each word (see the catalog). Enables "what did **Jesus** say about
  X" (red-letter = `speaker:Jesus`), "**God's** promises", speaker-scoped search.
  → **Done.** Table: [`resources/speaker_quotations/`](../resources/speaker_quotations)
  (`scripts/build_speaker_quotations.py`, Clear-Bible/speaker-quotations CC-BY-4.0):
  5,938 verse-range spans, 959 speakers, 2,173 divine, BBCCCVVV-anchored. **shoresh**:
  `/speaker/{name}`, `/speakers`, `/speakers/at/{b}/{c}/{v}` (data.py speaker
  accessors). **bcv-RAG**: `query/speakers.py` (speech-frame detection — "what did
  Jesus say" fires, "the faith of Abraham" doesn't), a `speaker` intent + the
  `speaker_search` retriever that intersects a speaker's ranges with the topic FTS
  ("what did Jesus say about faith" → Mark 11:22 "Have faith in God", Luke 18:42).
  Existing intents unaffected (speaker weight 0.0 / returns []). Eval-gate before deploy.
- **S2 · Semantic domains** (Louw-Nida Greek / SDBH Hebrew). Concept retrieval
  *broader than a single Strong's* — the right granularity for thematic queries.
  Open, token-aligned source exists (MACULA + UBS SDBH/SDGNT). Biggest concept
  upgrade.

### Phase 3 — turn that into better answers

- **P1 · Concept brief per Strong's** — assemble cross-lingual glosses + top
  renderings per language + a definitional **anchor verse** into a compact
  "concept card" handed to the LLM at synthesis. The most direct answer-quality
  win.
- **G2 · Speech-act classification** — command / promise / warning / blessing /
  question / teaching, from verb mood + discourse cues → "the **commands** in
  Deuteronomy".
- **G1 · Genre / discourse profile** per pericope (narrative / law / poetry /
  prophecy / epistle / wisdom / apocalyptic) → genre-aware retrieval & synthesis.

### Phase 4 — breadth (intertextual / names / relational)

- **X1 · OT-in-NT quotations** — derivable with shoresh's existing **LXX bridge**:
  match NT Greek against the LXX (Greek OT) → quotation links far beyond TSK.
  (A ready-made OT-NT reference map also exists — see catalog.)
- **N1 · Proper-noun lexicon** per language — surfaces aligning to person/place
  Strong's → localized name lists; extends the name-bridge and lets the analyzer
  recognize names in queries.
- **X2 · Synoptic Gospel parallels** — passage-parallel index across Matt/Mark/Luke.
- **T1 · Timeline + geography** (viz.bible / OpenBible geocoding) → "passages set
  in Galilee", "what happened around the time of X".

### Phase 5 — depth

- **A1 · Concept-association graph** — `Strong's → frequently co-occurring
  Strong's`, from the corpus clauses or alignment co-occurrence. Powers "related
  concepts" and sense disambiguation. An interpretable, Strong's-anchored
  word2vec.
- **M1 · Multi-word expressions → Strong's** — mine consecutive surfaces aligning
  to the same Strong's set ("Espíritu Santo" → G4151+G0040, חֶסֶד) so the analyzer
  detects multi-word concepts.
- **D1 · Discourse connectives / coreference** — γάρ/οὖν/δέ, כִּי for argument
  flow; participant coreference to resolve "he/they" across a narrative.
- **V1 · Versification map** — canonical ↔ edition verse-offset table (Hebrew vs
  English Psalms, superscription offsets). Quiet but foundational infra — and a
  **prerequisite for the [aligner](aligner-plan.md)**.

---

## shoresh-first

Original-language data and logic get **first priority in shoresh**, and bcv-RAG
becomes a **consumer** of it via the API (it already calls `/verse`, `/bridge`).
Original-language bits migrate out of bcv-RAG into shoresh where it makes sense.
So the original-language roadmap items — **S1** (speaker), **S2** (domains),
**X1** (OT-in-NT via `/bridge`), **D1** (referents/coref) — are built **in
shoresh**, exposed via its API.

Because shoresh is Strong's-keyed, the shared `resources/` is directly consumable
by it. Concrete wins from the shared data:

| Resource | What it unlocks in shoresh |
|---|---|
| `llm_strongs_glosses` | `/verse`, `/word`, `/search?translate=gloss` go **multilingual** (today English-only). Biggest win. |
| `aligned_lex` | `/gloss` + `/concept` accept **non-English** input (Spanish word → Strong's). |
| semantic_domains (S2) | Louw-Nida/SDBH domain per original word in `/verse`, `/word`. |
| speaker_quotations (S1) | speaker per word/verse in `/verse`, `/structure` — shoresh is the natural token-level home. |
| OT-in-NT (X1) | shoresh already has `/bridge` + `lxx.db` → the natural quotation-detection engine. |

*Consolidation note:* shoresh builds its own glosses while bcv-RAG ships
`strongs_gloss.tsv` + LLM glosses. Under the shared `resources/` these should
converge to **one gloss source both read** — avoid two divergent copies.

---

## The aligner

A whole sibling effort — word-align *any* translation to the Strong's-bearing
original, generalizing how `aligned_lex` is built to any language. It's the
largest force-multiplier here and has its own design doc:
**→ [aligner-plan.md](aligner-plan.md)**. (Depends on **V1**, the versification
map.)

---

## Open datasets to build from

The best starting index is **[awesome-bible-data](https://github.com/jcuenod/awesome-bible-data)**
(J. Cuenod) — curated, generously-licensed Bible data. Everything below is
Strong's- or token-keyed, so it maps onto our existing tokens with little
alignment work.

### For the speaker, quotation & semantic-domain items (S1, S2, D1, X1)

| Dataset | Provides | License | Notes |
|---|---|---|---|
| **[Clear-Bible/speaker-quotations](https://github.com/Clear-Bible/speaker-quotations)** | **Whole-Bible (OT+NT)** quotations → original-language words + speaker (`CharacterId`, from Faith Comes By Hearing); TSV per translation; Clear-aligned | see repo | **The headline for S1** — red-letter + all named speakers, our token scheme |
| **[OpenText context-annotation](https://github.com/OpenText-org/context-annotation)** | Speaker turns for the whole Greek NT (per token), projected/embedded speech | CC-BY-SA-4.0 | base texts n1904 (matches ours) + sblgnt; NT-only complement to the above |
| **[Clear-Bible/macula-greek](https://github.com/Clear-Bible/macula-greek)** | syntax, morphology, semantic roles, participant referents (coref), **Louw-Nida domains**, glosses, quotations | per-source | TSV word-level; same provider as our alignment data |
| **[Clear-Bible/macula-hebrew](https://github.com/Clear-Bible/macula-hebrew)** | OT counterpart: morphology, referents, domains | per-source | use with BHSA for OT speakers |
| **[UBS Dictionary SDBH + SDGNT](https://github.com/ubsicap/ubs-open-license)** | lexical **semantic domains** + definitions + glosses (Heb ~90%, Greek NT); XML/JSON | CC-BY-SA-4.0 | the open, licensed source for **S2** |
| **[STEPBible-Data](https://github.com/STEPBible/STEPBible-Data)** (Tyndale) | tagged OT/NT/LXX morphology, lexica, **proper names (TIPNR)** | CC BY 4.0 | foundational; proper names feed **N1** |

### Original-language "gold" (shoresh-side)

| Resource | What | License |
|---|---|---|
| **STEPBible** TAHOT/TAGNT, TBESH/TBESG, TFLSJ, TEHMC/TEGMC, TIPNR | tagged Hebrew OT + Greek NT (extended Strong's + morphology), brief lexica, morph-code explanations, proper names | CC BY 4.0 |
| **CATSS MT-LXX** ([codykingham/catss_lxx](https://github.com/codykingham/catss_lxx)) | Hebrew↔Greek **parallel alignment** of the OT + morphology | academic (confirm) — powers `/bridge` + X1 |
| **[OpenScriptures](https://github.com/openscriptures)** (morphhb/OSHB, HebrewLexicon, strongs) | Hebrew morphology + BDB/Strong's lexica | CC-BY-SA / MIT |
| **MACULA Greek / lowfat trees** | Greek syntax trees | CC-BY / per-source — `/structure` + clause units |
| **[OpenGNT](https://github.com/eliranwong/OpenGNT)** | NA28-equiv text + Levinsohn discourse + clause division + textual variants | open — text/variants + D1 |
| **Dodson** (CC-BY) / **Abbott-Smith** (PD) | Greek lexica keyed by Strong's | CC-BY / PD |

### Content corpora & drop-in upgrades (bcv-RAG-side)

| Resource | What | License | Use |
|---|---|---|---|
| **[OpenBible cross-references](https://www.openbible.info/labs/cross-references/)** | ~340k cross-refs, *ranked* by crowd-voted relevance | CC-BY | upgrade the current TSK xref set |
| **[Bible-Geocoding-Data](https://github.com/openbibleinfo/Bible-Geocoding-Data)** | every Bible place → coordinates + confidence | CC-BY | geography (T1) |
| PD commentaries — [TheologAI](https://github.com/TJ-Frederick/TheologAI), [HistoricalChristianFaith/Commentaries-Database](https://github.com/HistoricalChristianFaith/Commentaries-Database), SWORD modules | verse-keyed classic commentary (Henry, JFB, Clarke, Gill, Keil-Delitzsch, Barnes, …) | public domain | a large **retrievable study corpus** — the cheapest big jump in answer depth |
| PD dictionaries — ISBE, Easton's, Smith's | reference entries | public domain | entity/term content |
| **[eBible.org](https://ebible.org/find/)** + [seven1m/open-bibles](https://github.com/seven1m/open-bibles) | hundreds of translations (USFX/OSIS) | PD / CC-BY / CC-BY-NC | more Bible languages; the aligner's target side |

### Study UX — reading plans & lectionaries

Open, verse-ref-keyed, fit the conventions — collect under their own
`resources/` subfolders:
- **[bible-reading-plan-schema](https://github.com/BibleReadingPlans/bible-reading-plan-schema)** (a JSON schema standard + M'Cheyne) and **[khornberg/readingplans](https://github.com/khornberg/readingplans)** → `resources/reading_plans/`.
- **Revised Common Lectionary** ([Vanderbilt](https://lectionary.library.vanderbilt.edu/)), [marmanold/Date-Lectionary](https://github.com/marmanold/Date-Lectionary), [CatholicOS/cledr](https://github.com/CatholicOS/cledr) → `resources/lectionaries/`. (Pericope boundaries overlap the `section_heading` data we already ship — don't duplicate.)

### Target-language study content (the multilingual content axis)

Open study content concentrates in two ecosystems we already touch:
**Aquifer** ([aquifer.bible](https://www.aquifer.bible/)) and **unfoldingWord /
Door43 gateway languages** (translationNotes/Words/Questions per language). Honest
gradient: **spa/fra/por/rus/arb/hin are well-served** (Aquifer is already ingested);
**ben/asm/hau are thin** and need per-language hunting. For the thin three, the
realistic path is translating the open Study Bible (`en_ubn`, CC-BY-SA) plus
reusing [Bob Utley / freebiblecommentary.org](https://www.freebiblecommentary.org/)
where present, rather than finding scarce native verse-level content.

---

## How to contribute

A few on-ramps, easiest first:

1. **Phase 1 tables (R1, R2)** — invert/aggregate a file we already ship into a
   new `resources/` table. Self-contained, no serving-path changes, follow the
   conventions above. The best first issue.
2. **Ingest an open dataset (S1, S2)** — map one of the token-aligned datasets in
   the catalog onto our token scheme and emit a table. Higher impact, still
   mostly data work.
3. **Onboard a language** — add Bible text, study content, analyzer config, and
   (eventually) an `aligned_lex` for a new language. `ben`/`asm`/`hau` need the most
   love.
4. **The aligner or the versification map (V1)** — for contributors who want a
   meatier, NLP-flavored project. See [aligner-plan.md](aligner-plan.md).

When you pick something up, open an issue describing the item, the dataset, and
the table you'll produce — so we can sanity-check the keys and license before you
invest. Pull requests welcome.

## Further ideas (parking lot)

Lower-priority but on the radar: consensus back-translation glosses (triangulate a
verse's meaning across many languages), a derived per-language lemmatizer (from
aligned inflections), a topic ontology from co-occurrence, multi-granular
embeddings (pericope/book level), Hebrew root families, poetic-parallelism pairs,
Leitwörter/inclusio detection, and versional witnesses (Peshitta/Targum/Vulgate
vs MT, niche but native to shoresh). And — once audio resources arrive — audio
forced-alignment for word timing and read-along (see the stub in
[aligner-plan.md](aligner-plan.md)).
