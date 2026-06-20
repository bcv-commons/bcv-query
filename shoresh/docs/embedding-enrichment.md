# Embedding enrichment — original-language spine

Investigation of whether prepending an original-language "spine" (BCV +
Strong's + glosses) to embedding inputs improves retrieval.

Status: **investigated and concluded — do NOT re-embed.** The spine
*data* was built and validated; the *embedding-prefix* idea was measured
and does not earn a format-locking re-embed. The spine's value is
realized in the **deterministic retrieval layer** instead. Verdict and
evidence below; the detailed plan is kept as the investigation record.

## Outcome (the verdict)

**Decision: keep embeddings as a good multilingual model over the
natural-language bodies (Voyage today). Do not prepend the spine. Realize
the spine's value through the deterministic layer (`strongs:` / `lemma:`
tag retrieval, the live `cfabric` syntax retriever).**

Two independent lines of evidence converged:

**1. Measurement — the prefix doesn't help (4 representations × 3 test families).**
Single-book ablations on the production model (Voyage) — see
[`spine/ablation.py`](../spine/ablation.py),
[`spine/ablation_wordstudy.py`](../spine/ablation_wordstudy.py):

| Test | Result |
|---|---|
| Easy thematic + cross-lingual | **saturated** — Voyage already retrieves distinct verses at rank 1, incl. fr/es→en. The prefix adds nothing. |
| Word-study clustering (separation) | every prefix variant *lowers* same-word separation vs body-only; the original-language `hebrew_lemma` arm was the **worst** (0.0560 vs body 0.0614). |
| Word-study queries (P@5) | English `code+gloss` helps modestly (0.60→0.76) but is **beaten by exact `strongs:` tag_search** (≈1.0); `hebrew_lemma` helps least (0.64). |

The original-language anchor — the most promising idea — came in last,
consistent with Voyage's thin Hebrew/Greek geometry (the lemma arrives as
noise, not signal).

**2. Structure — the corpus is European-language, so the anchor is the wrong layer.**
The chunks we embed are overwhelmingly **English** (BSB, TN/TQ/TW/TA,
Aquifer, lexicon definitions) and will grow with **French/Spanish/Russian**
— all modern languages the model bridges natively. Verse-level
cross-lingual clustering is already handled by the **BCV** line; the
Hebrew/Greek lemma's only unique contribution (word-level cross-lingual)
is marginal when the bodies are European. An original-language anchor
would matter most when embedding *original-language* content — which this
corpus isn't.

**BGE-M3 — parked, not pursued.** A balanced-multilingual model has real
Hebrew/Greek geometry where Voyage has little, so it's the one untested
escape. But (a) the experiment would be reframed to "does BGE-M3 improve
*European* cross-lingual?" — which the saturation result suggests it
won't, and (b) standing it up in production is real infra for a use case
the deterministic layer already serves exactly and for free. The local
ablation hook is ready ([`spine/common.to_modern_form`](../spine/common.py)
carries the arm-B normalization note) if a future need justifies it.

**What this is not:** wasted. The spine became a **validated
original-language data layer** (UHB/UGNT parsed, 99.59% BHSA-reconciled,
100%-glossed) — a durable asset for the deterministic retrievers and for
the future direction in
[`../../docs/original-language-anchoring.md`](../../docs/original-language-anchoring.md),
which is where original-language *structure* (not English embeddings) is
the right tool.

---

*The rest of this document is the investigation record — the plan, the
reconciliation, the parser, and the ablation design that produced the
verdict above. Kept for rationale.*

## Goal (as originally framed)

Today the embedding input is the raw `chunks.body` — English (or
whatever language the chunk is in). Two chunks about the same verse in
different resources, or the same verse in different languages, land far
apart in vector space because their surface text differs.

The aim was to **demote natural language from "the thing being embedded"
to "one aligned view hanging off a language-neutral spine."** The spine
— book/chapter/verse + Strong's numbers + morphology + (where available)
syntactic roles — is prepended to every passage-bearing chunk's
embedding input. Content about the same verse, word, or grammatical
structure then clusters together regardless of surface language.

Natural-language text would **not** have been removed — the embedding
model has no idea what `H1254` means without the gloss `create`. The
spine *adds* a language-neutral skeleton; the body text stays as the
semantic surface.

## The enabling artifact: UHB + UGNT (original-language texts)

The spine is built from the **unfoldingWord Hebrew Bible (UHB)** and
**unfoldingWord Greek New Testament (UGNT)** — the original-language
texts themselves, distributed as USFM with per-word markup:

```
\w בְּ⁠רֵאשִׁ֖ית|lemma="רֵאשִׁית" strong="b:H7225" x-morph="He,R:Ncfsa"\w*
\w βίβλος|lemma="βίβλος" strong="G09760" x-morph="Gr,N,,,,,NFS,"\w*
```

Each `\w` element carries:

- **`strong`** — Strong's number, with morpheme prefixes (`b:` prep,
  `d:` article, `c:` conjunction) marking segmentation.
- **`lemma`** — the Hebrew/Greek dictionary headword.
- **`x-morph`** — morpheme-segmented parse (`R:Ncfsa` = preposition :
  noun-common-feminine-singular-absolute).
- the surface form, with `⁠` (U+2060) joining segmented morphemes.

**Why the original-language texts, not a translation's alignment.** An
earlier approach parsed the word-aligned BSB/ULT (English→Hebrew `\zaln`
markup). It works, but the English alignment introduces avoidable
problems: it can bracket one Hebrew word into two fragments (over-count),
omit words the translation doesn't render (under-count), and it uses
English versification (mis-pairs verses against BHSA). UHB/UGNT *are* the
Hebrew/Greek text — every word present, no alignment artifacts, native
(Hebrew/Greek) versification. They also reconcile with BHSA far better.

### Reconciliation with BHSA — verified

UHB and BHSA both encode the **same physical text** (the Leningrad
Codex), so an exact word correspondence exists in principle. Three
measures on Genesis (against local BHSA), increasingly truthful:

| Join method | UHB↔BHSA coherence | Notes |
|---|---|---|
| per-verse word **count** | 94% exact | a *proxy* — partly coincidental (similar verse lengths) |
| consonantal **surface** string | 86% word-level | too strict — fails on plene/defective spelling, ketiv/qere, empty article-nodes |
| **Strong's number** (via crosswalk) | **~99%** word-level | the robust join — Strong's anchors past spelling and versification |

The Strong's join (UHB's native `strong` ↔ BHSA's Strong's from the
[OpenHebrewBible crosswalk](#external-resources)) reconciles at **98.83%**
across the full OT — and **99.59%** after a 9-entry Strong's
[equivalence table](../spine/strongs_equivalence.tsv) closes the
high-frequency variant pairs (yalak/halak, YHWH variants, 'et homographs,
…). Run + per-book results: [`spine/reconciliation/`](../spine/reconciliation/).
Joining the whole-book *sequence* also sidesteps versification (word order
within a book is preserved regardless of verse numbering). The remaining
~0.4% is the sparse genuine tail. See the
[divergence catalogue](#divergence-catalogue-supporting-detail) and
[what remains](#what-remains-toward-100).

> Correction to earlier notes: UHB does **not** share BHSA's
> versification — UHB follows standard/English numbering, BHSA follows BHS
> Hebrew (e.g. Genesis 32 is offset by one). The offset is handled by the
> versification map (below); it doesn't affect the whole-book Strong's
> join.

### What the spine provides vs. what still needs bcv-corpus

| Anchor | Source | Self-contained? |
|---|---|---|
| BCV location | UHB/UGNT verse structure | yes |
| Strong's number per word | UHB/UGNT `strong` | yes |
| Lemma per word | UHB/UGNT `lemma` | yes |
| Morphology per word | UHB/UGNT `x-morph` | yes |
| English gloss per Strong's | lexicon cache / Strong's gloss list | yes |
| **Syntactic roles (clause/phrase/subject/object)** | **BHSA via bcv-corpus** | **no** |

**bcv-corpus's only irreplaceable contribution is syntax.** Everything
else comes from UHB/UGNT, self-contained, no service call.

## Parsing the spine

Parse UHB/UGNT directly — plain `\w …|strong=… x-morph=…\w*` per word.
No alignment milestones, **no dedup** (there's no translation alignment to
duplicate a word), and native versification. Far simpler than the
translation-aligned route.

### Per-word extraction

For each `\w surface|lemma="…" strong="…" x-morph="…"\w*`:

- `strong` → Strong's (split `:` for the prefix particles),
- `lemma` → headword,
- `x-morph` → segmented parse (after the `He,`/`Gr,` language tag),
- surface split on `⁠` (U+2060) → the morpheme pieces.

These three encodings (strong `:`-prefixes, morph `:`-segments, surface
joiner-pieces) **agree per word** — a built-in fidelity check; a mismatch
flags malformed data to skip/repair.

Within `x-morph`, segments before the head POS are prefixes (article
`Td`, preposition `R`, conjunction `C`); segments starting with `S` (`Sp`
suffix, `Sd`, `Sn`) are suffixes. BHSA splits prefixes into their own
word-nodes but keeps the suffix on its word — so for a BHSA-aligned unit
count, count non-`S` segments and expand a portmanteau prefix (`Rd` =
preposition + elided article) to 2.

### Output

Per-word records `(book, ch, v, index, surface, strong, lemma, morph)` in
text order, Hebrew/Greek versification. The Lexical prefix line keeps
content words (noun/verb/adjective heads); function morphemes (article,
preposition, conjunction, DOM) are dropped as noise.

### Versification

Three numbering systems are in play: UHB (standard/English-ish), BHSA
(BHS Hebrew), and bcv-RAG's translation chunks (English). They differ in
~4% of verses (e.g. Genesis 32 is offset by one). Two consequences:

- **Spine ↔ BHSA join:** done as a whole-book Strong's *sequence*, which
  is versification-**immune** (word order is preserved regardless of verse
  boundaries). For a per-verse view, apply the map below.
- **Spine ↔ translation-chunk attachment:** map the chunk's English
  reference onto the spine verse via the versification table.

The map is a solved resource — see [external resources](#external-resources).

### Divergence catalogue (supporting detail)

Why translation-alignment was rejected, and what the UHB↔BHSA residual is.
Six mechanisms, all identified — none a parser fault:

| # | Mechanism | Direction | Status under UHB + Strong's join |
|---|---|---|---|
| 1 | **Alignment duplication** — English brackets one word into 2 fragments | over-count | **gone** (no translation alignment) |
| 2 | **Portmanteau prefix** — `Rd` (prep+elided article) = 2 BHSA nodes | under-count | handled (`Rd`→2 for counts; irrelevant to Strong's join) |
| 3 | **Suffixes** — OSHB segments `Sp`/`Sd`/`Sn`; BHSA keeps on host | over-count | handled (drop `S*`) |
| 4 | **Versification offset** — standard vs BHS-Hebrew numbering | mis-paired | resolved by the versification map; immune in the sequence join |
| 5 | **Alignment gaps** — translation omits a Hebrew word | under-count | **gone** (UHB has every word) |
| 6 | **Strong's-assignment / ketiv-qere** — a few common words tagged differently by OSHB vs the crosswalk | ±1 | the ~1% residual; small equivalence table |

Concrete examples (from the BSB-via-English study that surfaced 1–5):

- **Duplication** — Gen 1:3 `וַיֹּאמֶר` ("And…**said**") emitted twice.
- **Portmanteau** — Gen 1:5 `לָאוֹר` (`Rd:Ncbsa`) = BHSA `לָ` + elided
  `ה` + `אוֹר` = 3.
- **Versification** — Gen 32: BHS Hebrew is +1 vs standard (confirmed
  against the OpenHebrewBible map).
- **Strong's residual** — Genesis: H1980 (×88), H582 (×40) tagged
  differently between OSHB and the crosswalk.

Sourcing from UHB/UGNT structurally removes 1, 5; the map resolves 4; the
parser rules handle 2, 3; only the ~1% Strong's-assignment tail (6)
remains.

### External resources

`eliranwong/OpenHebrewBible` (bridges ETCBC/BHSA ↔ OpenScriptures/Strong's
↔ Berean) supplies both keys we need, verified working:

- **`002-BHS-with-Strong-no/`** — per-word BHSA ↔ Strong's crosswalk (CSV,
  BHS canonical order; also `extendedStrongNumbers_*.tf` as a Text-Fabric
  node feature). This is the OSHB/UHB↔ETCBC bridge; it drove the ~99%
  Strong's join. (`.tf` is keyed to BHSA 2017/4c — version-match or join
  by reference for production.)
- **`019-BHSA_to_KJV_versification/`** — complete BHSA↔KJV verse map
  (`all_mappings`, `all_differences`, split/combined cases). Confirmed to
  match the Genesis-32 offset exactly.

Check licensing before depending on these (the repo aggregates sources
with mixed terms). `openscriptures/morphhb` (`remapVerses`) is a UHB-native
fallback for versification.

## The prefix layers

Historical "Layer N" labels kept for continuity with earlier notes.

| Block | Layer | Content | Source | Status |
|---|---|---|---|---|
| Location | 1 | `Genesis 1:1 \| GEN 1:1` | UHB/UGNT verse structure | ready |
| Lexical | 3 | `H7225:reshit:beginning H1254:bara:create …` | UHB/UGNT + gloss cache | ready |
| Structural | 4 | `clause:narrative subject:H0430 object:H8064+H0776` | BHSA via bcv-corpus + `002` Strong's crosswalk | reconciliation passed (~99% Strong's join) |
| Body | — | the chunk's actual text | `chunks.body` | unchanged |

### Target prefix format

```
Genesis 1:1 | GEN 1:1
H7225:reshit:beginning H1254:bara:create H0430:elohim:God H8064:shamayim:heavens H0776:erets:earth
clause:narrative subject:H0430 predicate:H1254 object:H8064+H0776
In the beginning God created the heavens and the earth.
```

The first two lines (Location + Lexical) build from UHB/UGNT alone. The
third (Structural) joins BHSA roles by Strong's via the crosswalk (~99%).

### Design rules

- **Content-word filter.** The lexical line should carry content-word
  Strong's (nouns, verbs, adjectives), not function morphemes
  (`b:` preposition, `d:` article, `c:` conjunction, `H0853` DOM). The
  `x-morph` POS makes this filterable. Function morphemes add noise and
  worsen the prefix-to-body dilution problem (below).
- **Glosses are stable lemma glosses, not contextual English.** Use a
  Strong's→gloss dictionary (built from `kind:lexicon` `short_definition`
  fields, or a curated Strong's gloss list), not the aligned English —
  "beginning" not "In the beginning", so the same word clusters across
  contexts.
- **Per-kind prefixing.** Scripture (BSB) and morphology chunks get the
  full spine. Passage-bearing commentary (TN, TQ, TW with a verse ref)
  gets Location + Lexical for its anchor verse(s). Passage-less chunks
  (lexicon entries, TA modules) get **no** Location line; a lexicon entry
  may use its own Strong's as the Lexical anchor.
- **Dilution risk.** For a 6-word verse, a multi-line prefix can dominate
  the pooled embedding and wash out body semantics. The content-word
  filter and gloss choice mitigate this; the ablation (below) measures it.

## Representation: keep Hebrew out of the embedded text

The spine carries the **Strong's code** and the **English gloss**, not the
Hebrew/Greek word form. Each representation does a different job:

| Form | Role | Goes in the embedded text? |
|---|---|---|
| `H1254` (Strong's) | Mechanical clustering anchor + join key | Yes (light) |
| `create` (gloss) | Semantic bridge the model actually engages | Yes (heavy) |
| `בָּרָא` (script) | BHSA join key + human display | **No** |
| `bara` (transliteration) | Weak phonetic hint | **No** (test only) |

Reasoning:

- **An embedding model clusters through semantics it understands
  (glosses, body text), not opaque codes.** The gloss does the real
  clustering work; the Strong's code is a precise-but-light anchor whose
  *exact*-match value is already captured for free by the deterministic
  retrievers (`tag_search` on `strongs:…`, `passage_search` on BCV). So
  codes earn their place as the **join/retrieval key in code**, less so as
  embedding tokens.
- **Pointed Masoretic Hebrew is the worst possible input.** `בְּרֵאשִׁ֖ית`
  carries niqqud *and* cantillation accents — combining-diacritic
  codepoints that are rare in any model's training data (the web's Hebrew
  is overwhelmingly unpointed modern Hebrew). They fragment into many
  subword tokens in undertrained regions and normalize inconsistently
  (NFC/NFD), injecting noise that can push related chunks *apart*.
- **Transliteration is a hedge, not a default.** Academic schemes
  (`bārāʾ`) reintroduce diacritics; only a simple ASCII unpointed scheme
  (`bara`) tokenizes cleanly, and even then its retrieval value is
  marginal next to Strong's + gloss. Carry the lemma as a **data field**
  (for the BHSA join and display); test ASCII transliteration only as an
  ablation arm.

## Embedding model selection (multilingual)

Multi-language (French, Spanish first) is a concrete near-term goal, so
the model is a near-term decision — and the spine re-embed is the
**free moment to make it** (you re-embed once regardless; `embed.py`'s
model-tracking already guards the swap).

The spine is overwhelmingly **English + alphanumeric codes**, so Hebrew
script handling is *not* a selection factor (we don't embed it). The
differentiators are **cross-lingual retrieval quality** (a French query
must retrieve English-anchored content), **ops model** (managed API vs.
self-hosted), and **sovereignty/cost** (per-query dependency vs. $0
marginal).

Coupling worth exploiting: a strongly cross-lingual model maps
`create` / `créer` / `crear` near each other **natively**, doing the
cross-language clustering *through the glosses* — which reduces how much
the shared Strong's token has to carry. Model strength and spine
complexity trade off.

| Option | Pros | Cons |
|---|---|---|
| **Voyage voyage-3-large** (status quo) | Already deployed (zero migration); top-tier quality; 1024d; asymmetric query/doc | Closed — per-query cost never reaches $0; not the most explicitly cross-lingual-tuned; vendor lock-in |
| **Cohere embed-multilingual v3 / v4** | Purpose-built for cross-lingual query↔doc retrieval (100+ langs); least ops; Matryoshka dims + int8/binary | API cost + key dependency; closed/no self-host; data leaves infra |
| **BGE-M3** (open, self-hosted) | **$0 marginal** (re-embed + per-query → compute only); no lock-in, no key, full sovereignty; strong multilingual; dense **+ sparse** (sparse handles exact codes/rare terms natively); 1024d; 8k context | You run inference; the host is CPU-only → slow bulk re-embed (run one-off on a rented GPU) and ~100–300ms/query on CPU; slightly below top commercial on English |
| **multilingual-e5-large** (open, self-hosted) | Self-hostable ($0 marginal); simpler than M3; proven | Dense-only; **512-token context truncates long article chunks**; a notch below M3/commercial |
| **OpenAI text-embedding-3-large** | Easy (key already present); 3072d (truncatable) | Weaker *cross-lingual* than Cohere/BGE; heavier storage; API cost |
| **Gemini gemini-embedding-001** | Recent MTEB-multilingual leader; Matryoshka dims | API cost + lock-in; newer in this stack; rate limits |

**Honest cost note:** the per-query *dollars* for any closed API are
negligible (~$0.000006/query). The real self-hosting wins are
**sovereignty** (no key, no external dependency — vector search runs in
the fully-offline Mode A) and the **one-time re-embed being free** — not
the per-query pennies.

**Lean, given this project's priorities** (concrete cross-lingual goal +
Mode A "$0/query" ethos + already self-hosting the whole stack):

- **BGE-M3 self-hosted** is the principled fit — it puts vector search
  in the key-free, $0 offline tier (Mode A), the sparse vectors
  complement the Strong's-code anchoring, and it owns the stack like
  everything else here. Cost: you accept inference ops (one-off GPU box
  for the bulk re-embed; CPU per query).
- **Cohere embed-multilingual** is the least-ops fallback if you'd rather
  not run inference — best-in-class cross-lingual, accept a small
  per-query API call.
- **Voyage** is the do-nothing status quo: fine quality, but it doesn't
  advance the cross-lingual or sovereignty goals.

**Decide fast, not endlessly:** pick the top two (likely BGE-M3 vs.
Cohere), and run the **representation × model ablation** below on one OT
book in English + one target language (French or Spanish). Measure
cross-lingual recall (French query → correct English-anchored chunk).
That picks both the model and the representation before the full
re-embed.

## The three access modes

The self-hosting decision (BGE-M3 in Mode A) reshapes the cost ladder.
Each mode **adds one stage** — none swaps the retrieval foundation, so a
mode upgrade re-orders or extends the previous mode's output rather than
returning something different.

| Mode | What runs | External dependency | Cost |
|---|---|---|---|
| **A** — fully offline | deterministic retrievers + self-hosted BGE-M3 (dense + sparse) + bcv-corpus (own service), fused via RRF, then self-hosted `bge-reranker-v2-m3`; local language detection. Returns structured citations. | none | $0 |
| **B** — pennies/query | A's top-N candidates re-scored by a hosted reranker. Precision lift; no re-embed; text-based so model-agnostic. | reranker key | ~$0.002/query |
| **C** — AI tokens | B's results synthesized into prose by an LLM, **output in the query's detected language**. | LLM key | LLM tokens |

Why it's shaped this way:

- **Vector search lives in A** because the embedder is self-hosted →
  multilingual *search* is free and offline; only multilingual *answers*
  (C) cost tokens. This is the cleanest split for the cross-lingual goal.
- **Monotonic ladder.** A ⊂ B ⊂ C in stages. B re-orders A's results
  (consistent UX); it does not return a different set.
- **B is a reranker, not a second embedding.** Query↔doc vectors must
  share a space, so B can't swap in a better query-embedder against
  A's local doc vectors (see *Dual embedding* below).
- **Language detection is local** (fastText LID), so routing "answer in
  the query's language" is free and offline; only generation (C) costs.

Per-mode picks:

| Mode | Top pick | Options |
|---|---|---|
| **A** embedder | **BGE-M3** | `multilingual-e5-large` (512-tok cap), `nomic-embed-text-v1.5` |
| **A** reranker | **`bge-reranker-v2-m3`** | `jina-reranker-v2-multilingual`, or none (RRF only) |
| **B** reranker | **Cohere Rerank 3.5** | `Voyage rerank-2.5`; cheap-LLM query expansion (recall instead of precision) |
| **C** LLM | **Groq Llama 3.3 70B → GPT-4o-mini** (already wired) | Claude Haiku; a frontier model for premium FR/ES |

C needs one small change: detect the query language (local) and pass
"answer in {lang}" to the synthesis prompt. The current Groq→OpenAI
stack already handles French/Spanish output.

### Per-query economics

Marginal *external* cost per query, under the self-hosted BGE-M3 plan
(so the query embedding is $0; local CPU is sunk self-hosted infra):

| Mode | Added component | Cost/query |
|---|---|---|
| **A** | local only | **$0** |
| **B** | hosted reranker — Cohere Rerank 3.5 (1 search unit, ≤100 docs) | **~$0.002** |
| **C** | LLM synthesis (~5k input + ~500 output tokens) + B | **~$0.003–0.005** |

C breakdown (synthesis + the $0.002 rerank):

- **GPT-4o-mini** ($0.15 / $0.60 per 1M): ~$0.001 synth → **~$0.003 total**.
- **Groq Llama 3.3 70B** ($0.59 / $0.79 per 1M): ~$0.003 synth → **~$0.005 total**.

What moves the numbers:

- **Groq's free tier (rate-limited) makes C effectively $0 at low volume**;
  gpt-4o-mini is the cheaper *paid* fallback (~$0.003).
- **C is dominated by input tokens** (the retrieved context) — tightening
  `top_k` or the per-kind body caps lowers it directly (halving context
  → ~$0.0007 synth on gpt-4o-mini).
- **B is flat** at one search unit per query (≤100 docs), so widening the
  rerank pool for recall is free within that bound. Voyage rerank-2.5
  (token-based) can drop B to ~$0.0006 for lean candidate sets.

Net: B is a rounding error; C is well under a cent (and ~free under
Groq's free tier). The binding constraint on C is context size, not price.

## Dual embedding: when a second vector set is worth it

**Default: one embedding. Modes add stages (rerank, synth); they never
swap the embedding.** Note Mode C needs no embedding of its own —
C = B's retrieval + an LLM summary.

Against a second set by *cost tier* (cheap-local for A, premium-hosted
for B):

- A's recall ceiling is the **union of all retrievers** (BGE-M3 dense +
  sparse, FTS, passage, tag, lexicon, morphology, entity, cfabric) — a
  second embedder adds only what BGE-M3-the-model missed *and* the others
  missed too: a thin sliver.
- A **reranker lifts precision** within that pool; the only thing it
  can't fix is a chunk that never surfaced — which the hybrid union makes
  rare. Recall headroom is smaller than precision headroom.
- Two sets cost **2× embed + storage (~1 GB each) + sync forever** (every
  content update writes both or they drift).
- A second embedding makes B return a **different result set**
  (inconsistent UX), not a better-ordered one.

Three exceptions where a second vector set *does* earn its keep:

1. **Proven multilingual recall gap.** If the ablation shows BGE-M3's
   cross-lingual recall lags a specialist (Cohere) *and* a wide candidate
   pool + rerank doesn't close it, a hosted doc-embedding for B is
   justified — rerank can't recover a chunk that never surfaced.
   **Test, don't assume**; BGE-M3 is strongly multilingual.
2. **Same model, two precisions (cheap, do it regardless).** Store a
   binary/int8 BGE-M3 vector (~30 MB / ~240 MB for the corpus) for a fast
   first pass + full float32 for scoring (coarse-to-fine), or use
   Matryoshka truncation. This is an optimization *within* a mode, not an
   A-vs-B split, and storage is nearly free.
3. **Same model, different inputs by intent (the interesting one).** A
   **spine-prefixed** embedding for `word_study` / `morphology` /
   `passage` intents and a **body-only** embedding for `thematic` intents
   escapes the prefix-dilution tradeoff. Both are self-hosted → **both
   live in Mode A**, routed by the analyzer's intent. Worth testing.

Recommendation: ship **one** embedding; do the precision tiering (#2);
hold #1 and #3 as **ablation arms** — pay for a second set only with
data.

## Layer 4: joining BHSA syntax to the spine

The structural line requires BHSA, which keys on ETCBC lex codes, not
Strong's. The [OpenHebrewBible `002` crosswalk](#external-resources)
gives every BHSA word a Strong's number, so the join is **Strong's↔Strong's**
(~99%, far more robust than surface/lemma):

1. For a verse, fetch BHSA's clause/phrase structure from bcv-corpus
   (needs a per-chapter structural-summary endpoint — see ROADMAP).
2. Take BHSA's role-bearing phrase **heads** (subject, predicate, object).
3. Resolve each head's Strong's (via the `002` crosswalk) and match it to
   the spine word carrying the same Strong's in that verse.
4. Emit `clause:<type> subject:<Hxxxx> predicate:<Hxxxx> object:<Hxxxx>`.

### The reconciliation gate — result

**Passed — full OT.** Reconciliation against local BHSA, three measures —
the Strong's join via the crosswalk is the operative one:

| Method | UHB↔BHSA coherence | |
|---|---|---|
| per-verse word count | 94% exact (Genesis) | proxy (partly coincidental) |
| consonantal surface | 86% word-level (Genesis) | too strict (spelling, ketiv/qere, empty nodes) |
| **Strong's via `002` crosswalk** | **98.83%** OT-wide | the real join |
| **+ 9-entry equivalence table** | **99.59%** OT-wide | high-frequency variants closed |

Run across all 39 OT books ([`spine/reconcile.py`](../spine/reconcile.py),
results in [`spine/reconciliation/`](../spine/reconciliation/)); every book
lands 98.5–99.6%. Sourcing from UHB removed the duplication / omission /
versification artifacts; the Strong's crosswalk then carries the match past
spelling and ketiv/qere; the equivalence table closes the high-frequency
variant pairs.

**Verdict:**

- **Loose Strong's-join (embedding prefix): solved** (99.59%).
- **Rigorous Strong's-join (cross-corpus token queries): now viable** —
  the crosswalk + equivalence table is the map; what was a research bet is
  done.

### What remains (toward 100%)

1. **~0.4% sparse tail** — 645 words across 335 distinct Strong's, mostly
   1–2 occurrences each (alignment noise + rare genuine differences).
   Diminishing returns; not needed for the join.
2. **Version matching** — the crosswalk is keyed to BHSA etcbc4c; books
   are sliced by BHSA-2021 counts (a few words of drift land in the tail).
   For an exact per-**node** production map, align the crosswalk to the
   target BHSA version by reference + surface.
3. **Versification map (`019`)** for per-verse attachment (the whole-book
   sequence join doesn't need it; chunk attachment does).
4. **License review** of OpenHebrewBible before depending on it.

## Validation: the ablation

One harness, run on a single OT book, settles three decisions at once:
**the model, the representation, and whether Layer 4 earns its re-embed.**

Arms to cross (pick the top two models — likely BGE-M3 vs. Cohere):

- **Representation:** `Strong's+gloss` (default) vs. `+ASCII translit`
  vs. `+pointed Hebrew` (expected to regress — confirms the rule above).
- **Input/intent** (dual-embedding #3): single spine-prefixed embedding
  vs. intent-routed spine-prefixed + body-only.
- Embed one OT book in English **plus one target language** (French or
  Spanish) so cross-lingual recall is measurable, not assumed.

Win conditions (named, to avoid clashing with the Mode A/B/C labels):

- **Cross-lingual recall** — a French/Spanish query retrieves the correct
  English-anchored chunk. The near-term goal; gates the model +
  representation choice.
- **Layer-4 lift** — on role-sensitive thematic queries (agent vs.
  patient matters), recall@10 / MRR for the correct scripture or
  morphology chunk improves by ≥10–15% for `1+3+4` over `1+3`.
- **No thematic regression** — on ordinary thematic queries, `1+3+4`
  must not drop recall vs. `1+3` (catches prefix dilution).
- **Non-redundancy** — where Layer 4 helps, confirm the already-shipped
  live `cfabric_search` retriever doesn't already cover it as well or
  better at query time.

Decision rules: **Cross-lingual recall** picks the model + representation
(needed for the multilingual goal regardless of Layer 4). **Layer-4 lift
+ no regression + non-redundancy** all clearing is what greenlights
Layer 4's second re-embed.

## Re-embed sequencing

The re-embed (`indexer.embed --reset-vec`, 238k chunks — ~$15 with a
hosted model, or a few dollars of one-off GPU time with self-hosted
BGE-M3) is the **format-locking event** — changing the prefix format
later means re-embedding again. There is no shortcut: prefix enrichment
changes *clustering*, which is a function of the embedded text, so it
cannot be done as a side table.

Recommended sequence:

1. **Eval baseline.** Expand the eval set; lock a baseline against the
   current (no-prefix) index.
2. **Build the spine + gloss cache.** Parse UHB/UGNT into per-word
   records (prerequisite 1); one pass over `kind:lexicon` chunks →
   `{strongs → gloss}` map.
3. **Single-book ablation.** Enrich one book with Layers 1+3 into a
   scratch vector column; run the model × representation × input arms
   above; iterate the format here where it's cheap. This also picks the
   embedding model (the cross-lingual-recall condition).
4. **Re-embed #1 — Layers 1+3** with the validated model + format
   (reserve a slot for the Structural line). Update query-side embedding
   to match.
5. **Build the loose Layer-4 join** (lemma-match; gate already passed for
   the loose form — see result above).
6. **Re-embed #2 — Layer 4**, only if the ablation shows it earns its keep.

Two deliberate re-embeds is the price of de-risking; the compute (a few
dollars self-hosted, ~$15/pass hosted) is trivial next to the cost of
locking in a bad format.

## NT caveat

UGNT carries the same per-word `strong`/`lemma`/`x-morph` markup, so the
NT spine (Location + Lexical) is just as good as the OT's. But Nestle1904
/ the Greek NT's *syntactic* annotation is far thinner than BHSA's — so
the **Structural** line (Layer 4) will be shallow for the NT regardless.
The OT is where structural enrichment pays off.

## Prerequisites / open items

1. **Spine parser** — fetch UHB + UGNT from Door43 and parse the `\w
   …|strong=… x-morph=…\w*` markup into per-word records. Full spec:
   [spine-parser.md](spine-parser.md). No dedup, no zaln.
2. **Strong's→gloss dictionary** — from the lexicon cache or a curated
   list; needed for the Lexical line.
3. **bcv-corpus per-chapter structural endpoint** — to fetch BHSA
   clause/phrase/role data in bulk for the Layer-4 Strong's-join (see
   ROADMAP).

Resolved (see [`../spine/`](../spine/)): the `002` Strong's crosswalk and
`019` versification map are located, license-cleared (CC BY-NC — see
[`../spine/ATTRIBUTION.md`](../spine/ATTRIBUTION.md)), and the
[equivalence table](../spine/strongs_equivalence.tsv) is built.

Done: spine source settled (UHB/UGNT); parse verified; BHSA reconciliation
solved (99.59% OT-wide via the `002` Strong's crosswalk — see *The reconciliation
gate — result*); versification map and Strong's crosswalk located and
tested. The earlier USFM→USJ / translation-alignment experiments are
dropped (USJ lossy; original-language texts are the source).

See [ROADMAP.md](../../bcv-RAG/docs/ROADMAP.md) for how this fits the
broader plan and [data-pipeline.md](../../bcv-RAG/docs/data-pipeline.md)
for current ingest.
