# The aligner — plan for a Strong's word-alignment factory

> **Status: planning.** The `aligner/` folder exists but is empty; nothing is
> implemented yet. This document is the design — and an open invitation to help
> build it. It's the single biggest force-multiplier on the project's roadmap.

## The one-sentence idea

Take *any* Bible translation, automatically **word-align it to the original**
Hebrew/Greek (which carries Strong's numbers), and out comes:

1. a **word-level, Strong's-tagged interlinear** for that translation, and
2. an entry in **[`resources/aligned_lex/<lang>.tsv`](../resources/aligned_lex)**
   — a table of `surface word → Strong's number, count, share` for the whole
   language.

The aligner is a **producer of `resources/`, not a service** — it runs offline,
writes shared data, and both [bcv-RAG](bcv-RAG.md) and [shoresh](shoresh.md)
consume the result.

## Why this matters

`aligned_lex` is already the backbone of the project's multilingual support:
concept expansion, function-word filtering, and the name-bridge (localized name →
Strong's → entity) all read from it. Today it covers ~10 languages because those
alignments were produced **by hand** (the Clear-Bible manual set). The aligner
**generates the same artifact statistically/automatically** — so any language with
a translation can join.

And because everything is keyed on Strong's, alignment unlocks a chain reaction:

> align a translation → get Strong's per word → and the multilingual glosses
> (`llm_strongs_glosses`) and semantic domains (UBS SDBH/SDGNT) **attach for free**.

That's the flywheel: *"any translation in → Strong's + glosses + domains +
interlinear, in that language."*

## How alignment works — three methods that team up

No single method covers every language. The aligner runs them as an **ensemble**:
where they agree, confidence is high; where they disagree, flag for review.

| Method | How it works | Needs | Best for |
|---|---|---|---|
| **Statistical** (co-occurrence / EM, e.g. `eflomal`, `fast_align`) | Counts which target words recur with which Strong's across all verses; normalizes against chance (Dice / PMI / IBM-1) so function words don't dominate. | parallel text + Strong's only | **any language** with a full Bible — the universal spine |
| **LLM gloss** | An LLM *generates* the expected target word for each Strong's; the alignment then matches translation words to those glosses (exact + fuzzy). | an LLM competent in the language | high-resource languages; precise biblical senses; cheap type-level lexicon |
| **Neural aligner** (SimAlign / awesome-align) | A multilingual encoder aligns tokens by embedding similarity, in context, cross-script, no training. | an encoder that covers the language (LaBSE ~109, Glot500 ~500+) | low-resource languages an LLM can't generate for; catches polysemy |

**The rule of thumb:** statistical is the spine (it comes straight from the text);
the LLM gloss and neural aligner are *priors and cross-checks* that help where the
data is sparse. Confidence comes from agreement across methods — exactly the
`share` column already in `aligned_lex` (`P(Strong | surface)`).

> A note on glosses vs. surfaces: glosses *decide* an alignment, but
> `aligned_lex` records the **real attested translation word** with its counts and
> share — not the gloss.

## The English prototype (the seed to generalize)

There's a working **English/NT prototype** (developed separately, kept as a local
seed — not part of this public repo) that converts a verse-level English
translation into a word-level, Greek-aligned, Strong's-tagged interlinear using a
**deterministic, gloss-anchored, $0** strategy chain (no models): translator-
addition detection → exact gloss match → learned Strong's→English patterns →
lexicon gloss → fuzzy gloss → multi-word grouping.

About **70% of that prototype is language-agnostic** (the source parser, the
interlinear schema, the strategy framework, the string algorithms). The
English-specific part is concentrated in **one swappable place** — the gloss
table. Point it at `resources/llm_strongs_glosses/<lang>.tsv` instead of the
English lexicon and the gloss-anchored strategy becomes multilingual immediately.
The plan is to **absorb that prototype as the English/NT core**, then generalize.

## What the aligner produces

- **Per-word interlinear TSV** — Greek/Hebrew word, Strong's, morphology,
  transliteration, the target word(s), sort orders. Display-grade, for
  shoresh/bcv-RAG.
- **`resources/aligned_lex/<lang>.tsv`** — `surface, strong, count, share`. The
  reusable lexical artifact, consumed across the project.

## How to build it (suggested sequence)

The aligner is **gated on a versification map** (roadmap item **V1**) — you have
to line verses up before you can align words across editions. Then:

1. **Absorb the English/NT prototype** as the deterministic core.
2. **Extend to the OT** — Hebrew via STEPBible **TAHOT** + **TBESH** (same method,
   clone the source parser).
3. **Go multilingual** — swap the gloss table to `llm_strongs_glosses/<lang>.tsv`,
   add the **neural fallback** strategy, and add the **statistical** spine for
   languages with little gloss coverage.
4. **Benchmark** against the existing hand-made `aligned_lex` (the 10
   Clear-manual languages) as a gold set; tune the `share` threshold and add a
   manual/transfer **confidence flag** before trusting new languages.

## Inputs & sources (all CC-BY or free)

- **STEPBible** TAGNT (Greek NT) / TAHOT (Hebrew OT) — extended Strong's +
  morphology + per-word glosses (CC BY 4.0); TBESG/TBESH lexicons (CC BY).
- **Parallel Bible text** — eBible.org / seven1m's open-bibles (hundreds of
  languages) as the target side.
- **`resources/llm_strongs_glosses/`** — per-language glosses we already produce,
  for the gloss-anchored strategy.
- A **versification map** to align verses first (roadmap **V1**).

## Where it fits

```
aligner/  (offline producer)
   reads:  original+Strong's, parallel translations, llm_strongs_glosses
   writes: resources/aligned_lex/<lang>.tsv  +  per-word interlinear
                 │
                 ▼ consumed by
   shoresh (gloss/concept go multilingual, interlinear) · bcv-RAG (concept expansion, name-bridge)
```

The project is **shoresh-first**: shoresh supplies the original-language +
Strong's input and is the primary consumer of the interlinear and `aligned_lex`.

## How to help

This is a great place to contribute, especially if you know NLP/word-alignment:

- Stand up the **statistical aligner** (eflomal/fast_align + Dice/IBM-1 scoring)
  on one full-Bible language and compare its `aligned_lex` output to the manual
  gold set.
- Wire a **neural aligner** (SimAlign) as one strategy in the chain and measure
  where it beats the gloss-anchored method.
- Help build the **versification map** (V1) that everything here depends on.

If you want to take one of these on, open an issue describing the language and
method you'd start with.

---

## Out of scope (for now): audio forced-alignment

A *separate*, future concern — aligning a Bible **audio** recording to its text to
get per-word **timing** (read-along UX; also the backbone behind a speaker /
red-letter index). The method (Meta **MMS-FA** + **Whisper**, fused) and a mature
local prototype exist, but this is its **own** future subfolder, not part of the
text aligner. It will be designed when the audio resources are brought in.
