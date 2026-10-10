# `lxx_orphan_lexemes/` — LXX-only Greek lexemes (no Strong's number)

`lexemes.tsv` — the ~7% of the Septuagint (via `shoresh/lxx/data/lxx-glaux.db`) that carries no
Strong's number, because it never occurs in the NT (Strong's numbering is NT-catalogued only) —
e.g. Genesis 1:2's ἀκατασκεύαστος. Grouped by lemma into a citation form + all attested inflected
variants, so these words can be given lexicon entries of their own.

**Grouping key:** the LXX source format carries a `wordid` per token that VALIDATED (2026-08, see
`shoresh/lxx/parse.py`'s module docstring) reliably groups inflected forms of the same lemma — 0/4,050
distinct `wordid`s that co-occur with a real Strong's number ever map to more than one — even though
it was previously treated as a throwaway per-occurrence id and discarded during parsing.

## Columns
| col | meaning |
|---|---|
| `wordid` | stable id of the GLAUx lemma (grouping key of the inflected forms) |
| `citation_form` / `citation_morph` | the chosen dictionary-headword surface form + its morph tag |
| `pos` | `N` noun, `A` adjective, `V` verb |
| `citation_confidence` | `standard` — the citation form is on a fixed priority list of lexicon-headword-shaped forms (nominative singular for nouns/adjectives; present/aorist indicative or infinitive, preferring active + 1st singular, for verbs); `fallback` — nothing on that list was attested in this corpus, so the most frequent attested form was used regardless of shape. Fallback groups are worth a lexicographer's eye before publishing as-is (mostly single-occurrence proper nouns attested only in an oblique case — see Coverage). |
| `variant_surface` / `variant_plain` / `variant_morph` | one attested inflected form + its morph tag (`plain` = de-accented, matches `lxx_words.plain`) |
| `count` | how many times this specific variant occurs |
| `sample_ref` | one example verse reference for this variant |

## Coverage (2026-10-10)
10,897 lemma groups, 21,548 variant rows, built from `lxx-glaux.db` (GLAUx). The citation form is the GLAUx lemma (`citation_confidence=lemma`, `citation_morph` empty), so nothing
is guessed from the attested forms any more. `wordid` is a stable id of the lemma (31 bits of the SHA-1 of the NFC lemma), so URLs survive rebuilds.

## License
Derived from GLAUx (Alek Keersmaekers, KU Leuven, https://github.com/alekkeersmaekers/glaux) — **CC BY-SA 4.0**, share-alike; texts from el.wikisource (CC BY-SA 3.0).

## Rebuild
```bash
cd shoresh && PYTHONPATH=. python -m lxx.build_orphan_lexemes   # -> resources/lxx_orphan_lexemes/lexemes.tsv
```
Requires `lxx-glaux.db` (`python -m lxx.build_glaux`).
