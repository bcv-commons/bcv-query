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
2026-11-17 (two runs) and handed over to bcv-query. No person has checked them. Use it as a tier beside the Septuagint bridge, never in its place.

| | |
|---|---|
| Release | **@TAG@**, built @BUILT@ from bcv-query `@COMMIT@` |
| Lexemes looked at | @LEXEMES@ (Greek NT and Tanakh lexemes with no Septuagint pair); @ASKED@ had a candidate and were asked |
| Answers | @PAIRS@ pairs at p ≥ @MINP@ (@NT@ from the Greek side, @OT@ from the Hebrew side); @NONE@ "none"; @LOW@ below @MINP@ |

## How it was made

1. **Candidates, first run** (`macula/build_bridge_candidates.py`), up to 6 per lexeme:
   - the Hebrew New Testaments ([hebrew-nt-bridge](https://huggingface.co/datasets/bcv-commons/hebrew-nt-bridge) v0.2: which Hebrew
     word Salkinson–Ginsburg and Delitzsch wrote for a Greek word; pairs seen 3 times or more);
   - the Septuagint: Hebrew and Greek lexemes in the same verses, Dice ≥ 0.08 (below the bridge's own 0.3, so these are candidates
     only; many are collocates).
   No English is used: no glosses, no English translation.
2. **Candidates from vectors** (`macula/build_vector_candidates.py`): the first run's candidates, then the 8 lexemes nearest on
   the other side in contextual word vectors. Run `vector` (v0.2): 92 Tanakh lexemes left without a partner when the gloss-found
   tier was dropped; Greek mapped onto Hebrew by Procrustes on MACULA's Septuagint lexeme pairs. Run `v3a` (v0.3): every noun, verb
   and adjective with at least 5 occurrences, not a proper name, and still without a partner in the Septuagint tiers or v0.2, on
   both sides (975 Tanakh lexemes, 889 Greek NT lexemes); the map trained on 144,795 Tanakh–Septuagint word pairs (held-out top 10
   0.840; Hebrew NT pairs with no Septuagint seed 0.595 / 0.555). The vectors (Hebrew: BEREL 3.0 on the unpointed Tanakh
   and both Hebrew New Testaments; Greek: GreBerta on the Greek NT and the Septuagint; Greek mapped onto the Hebrew space by
   orthogonal Procrustes on MACULA's Septuagint word links). On held-out pairs these vectors put the right Greek lexeme in their
   top 10 for 0.53–0.84 of lexemes. A vector neighbour is a similarity of use, not a translation, and Jev was told so.
3. **The choice.** Jev saw the lexeme, its number of occurrences, up to three verses in its own language, and each candidate's
   lemma, occurrences and evidence counts. It chose one candidate or "none", judged by biblical usage. In the vector runs it saw every candidate (up to 14) and each vector
   candidate's rank and cosine (runs `vector` and `v3a`). The counts per run are in *Runs*; where a lexeme was asked again in a later run (a "none" or a
   choice below the cut-off before, now with more candidates), the later answer is used. "p" is the probability of the chosen candidate (research's own count uses Jev's confidence, which keeps 24 of
   these in run `vector`); 16 of run `vector`'s pairs are the same as in the gloss-found version.

An earlier version of this tier (research's, 2026-10-30) found its candidates by matching English glosses; it was not published.
Of the pairs here, 96 are the same as in that version.

## Runs

Where a lexeme was asked in more than one run, the last answer is used.

@RUNS@

## Files

| File | |
|---|---|
| `pairs.tsv` | `side` (`nt`: a Greek NT lexeme given a Hebrew partner; `ot`: a Tanakh lexeme given a Greek partner), `hebrew_strong`, `greek_strong` (zero-padded, as in the Septuagint tiers), `hebrew_lemma`, `greek_lemma`, `p` (Jev's probability for the choice), `hnt_links` (links in the two Hebrew NTs), `lxx_dice` (the Septuagint co-occurrence), `vector_rank` (the candidate's rank among the vector neighbours, if it was one), `run` (`33b` or `vector`) |
| `answers.json` | every answer: the choice (`c<i>` or `none`), the probabilities of all candidates, the candidates' numbers, the model, the `run` |
| `candidates.json` | the candidate lists with their evidence |
| `SHA256SUMS` | SHA-256 of every file |

## Sources and licence

| Part | Source | Licence |
|---|---|---|
| Lexemes, lemmas, verses | MACULA Hebrew and Greek (Clear Bible / Biblica) | CC BY 4.0 |
| Septuagint co-occurrence | GLAUx Septuagint | CC BY-SA 4.0 |
| Hebrew NT pairs | bcv-commons/hebrew-nt-bridge v0.2 | CC BY 4.0 |
| Vector models | BEREL 3.0 (DICTA), GreBerta (Riemenschneider and Frank) | Apache 2.0 |
| Choices | Jev (TypeSafe), run by make-tanakh-research | model output |
| This dataset | bcv-commons | **CC BY-SA 4.0** |

## Versions

- v0.1: the first release.
- v0.2: a second run for Tanakh lexemes left without a partner when the gloss-found tier was dropped, with candidates from
  contextual word vectors.
- v0.3: run `v3a`, every content lexeme still without a partner, both sides, on the word-pair map.
