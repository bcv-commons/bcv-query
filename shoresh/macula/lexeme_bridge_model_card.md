---
license: cc-by-sa-4.0
language:
  - hbo
  - grc
pretty_name: Hebrew–Greek Lexeme Bridge (model-made)
tags:
  - bible
  - hebrew
  - greek
  - lexicon
  - model-made
configs:
  - config_name: pairs
    default: true
    data_files:
      - split: all
        path: pairs.tsv
    sep: "\t"
---

# Hebrew–Greek Lexeme Bridge (model-made)

A Hebrew partner for Greek New Testament lexemes, and a Greek partner for Tanakh lexemes, where the Septuagint bridge
([lxx_bridge_tiers](https://github.com/bcv-commons/bcv-query/tree/main/resources/lxx_bridge_tiers): MACULA's word links and the
Septuagint co-occurrence at Dice ≥ 0.3) has none. A model chose each partner from candidates that Hebrew and Greek evidence alone
proposed.

**Model-made, no human check.** The choices are by the Jev model (TypeSafe, `jev-1.14.0`), run by make-tanakh-research on
2026-11-17 and handed over to bcv-query. No person has checked them. Use it as a tier beside the Septuagint bridge, never in its place.

| | |
|---|---|
| Release | **@TAG@**, built @BUILT@ from bcv-query `@COMMIT@` |
| Lexemes looked at | @LEXEMES@ (Greek NT and Tanakh lexemes with no Septuagint pair); @ASKED@ had a candidate and were asked |
| Answers | @PAIRS@ pairs at p ≥ @MINP@ (@NT@ from the Greek side, @OT@ from the Hebrew side); @NONE@ "none"; @LOW@ below @MINP@ |

## How it was made

1. **Candidates** (`macula/build_bridge_candidates.py`), up to 6 per lexeme:
   - the Hebrew New Testaments ([hebrew-nt-bridge](https://huggingface.co/datasets/bcv-commons/hebrew-nt-bridge) v0.2: which Hebrew
     word Salkinson–Ginsburg and Delitzsch wrote for a Greek word; pairs seen 3 times or more);
   - the Septuagint: Hebrew and Greek lexemes in the same verses, Dice ≥ 0.08 (below the bridge's own 0.3, so these are candidates
     only; many are collocates).
   No English is used: no glosses, no English translation.
2. **The choice.** Jev saw the lexeme, its number of occurrences, up to three verses in its own language, and each candidate's
   lemma, occurrences and evidence counts. It chose one candidate or "none", judged by biblical usage.

An earlier version of this tier (research's, 2026-10-30) found its candidates by matching English glosses; it was not published.
Of the pairs here, 96 are the same as in that version.

## Files

| File | |
|---|---|
| `pairs.tsv` | `side` (`nt`: a Greek NT lexeme given a Hebrew partner; `ot`: a Tanakh lexeme given a Greek partner), `hebrew_strong`, `greek_strong` (zero-padded, as in the Septuagint tiers), `hebrew_lemma`, `greek_lemma`, `p` (Jev's probability for the choice), `hnt_links` (links in the two Hebrew NTs), `lxx_dice` (the Septuagint co-occurrence) |
| `answers.json` | every answer: the choice (`c<i>` or `none`), the probabilities of all candidates, the candidates' numbers, the model |
| `candidates.json` | the candidate lists with their evidence |
| `SHA256SUMS` | SHA-256 of every file |

## Sources and licence

| Part | Source | Licence |
|---|---|---|
| Lexemes, lemmas, verses | MACULA Hebrew and Greek (Clear Bible / Biblica) | CC BY 4.0 |
| Septuagint co-occurrence | GLAUx Septuagint | CC BY-SA 4.0 |
| Hebrew NT pairs | bcv-commons/hebrew-nt-bridge v0.2 | CC BY 4.0 |
| Choices | Jev (TypeSafe), run by make-tanakh-research | model output |
| This dataset | bcv-commons | **CC BY-SA 4.0** |

## Versions

- v0.1: the first release.
