# `lxx_orphan_lexemes/` — LXX-only Greek lexemes (no Strong's number)

`lexemes.tsv` — the ~7% of the Septuagint (Rahlfs 1935, via `shoresh/lxx/lxx.db`) that carries no
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
| `wordid` | the validated per-lemma grouping key (see above); arbitrary but stable |
| `citation_form` / `citation_morph` | the chosen dictionary-headword surface form + its morph tag |
| `pos` | `N` noun, `A` adjective, `V` verb |
| `citation_confidence` | `standard` — the citation form is on a fixed priority list of lexicon-headword-shaped forms (nominative singular for nouns/adjectives; present/aorist indicative or infinitive, preferring active + 1st singular, for verbs); `fallback` — nothing on that list was attested in this corpus, so the most frequent attested form was used regardless of shape. Fallback groups are worth a lexicographer's eye before publishing as-is (mostly single-occurrence proper nouns attested only in an oblique case — see Coverage). |
| `variant_surface` / `variant_plain` / `variant_morph` | one attested inflected form + its morph tag (`plain` = de-accented, matches `lxx_words.plain`) |
| `count` | how many times this specific variant occurs |
| `sample_ref` | one example verse reference for this variant |

## Coverage (2026-08)
9,486 lemma groups, 18,994 variant rows, from 37,682 untagged content-word occurrences / 16,171
distinct inflected surfaces (a ~41% collapse). 4,147 groups (44%) reach `standard` citation confidence;
5,339 (56%) are `fallback` — but 75% of the fallback groups are single-occurrence words (mostly proper
nouns attested only in one oblique case), an inherent limit of deriving a citation form from actual
corpus attestation rather than a full paradigm, not a defect in the grouping itself. Confidence rises
sharply with attestation: groups with 4+ variants reach `standard` 78% of the time.

## License
CATSS-derived (non-commercial) — same as the rest of `shoresh/lxx/`, see
`shoresh/legal/CATSS-user-declaration.md`.

## Rebuild
```bash
cd shoresh && PYTHONPATH=. python -m lxx.build_orphan_lexemes   # -> resources/lxx_orphan_lexemes/lexemes.tsv
```
Requires `lxx.db` built with the `wordid` column (`python -m lxx.parse --all`, 2026-08-13 or later).
