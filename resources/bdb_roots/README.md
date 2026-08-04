# `bdb_roots/` — BDB etymological root-groups (public domain)

`root_groups.tsv` — Hebrew Strong's numbers grouped by **etymological root**, from Brown-Driver-Briggs
(1906, public domain) via the [OpenScriptures/HebrewLexicon](https://github.com/openscriptures/HebrewLexicon)
digitization (CC-BY-4.0 for the XML structure, pinned commit `21c9add1`). Words sharing a `root_id` are
derivatives of the same Hebrew root — a real etymological fact, not an assertion, and one that
correlates strongly with shared meaning.

**Not Louw-Nida/SDBH derived** — an independent free source, unlike `resources/semantic_domains/`.

## Columns
| col | meaning |
|---|---|
| `root_id` | anchoring LexicalIndex entry id for the group (arbitrary but stable) |
| `strong` | `H####` |
| `xlit` | transliterated Hebrew form |
| `gloss` | short English gloss (BDB's own) |
| `pos` | part of speech (`V` verb, `N` noun, `Np` proper noun, ...) |

## Validation (2026-08)
Checked against SDBH (the same yardstick used throughout `domain-replacement-roadmap.md`): same-root
pairs share an SDBH domain **50.6%** of the time (2,731/5,397 checkable pairs) — better than this
project's own from-scratch Louvain clustering (45.1%), at meaningfully larger scale (1,432 root-groups,
4,616 distinct Strong's here vs. our 131 clusters / 2,397 Strong's).

## Coverage
1,432 root-groups (median size 2, max 18), 4,962 rows, 4,616 distinct Strong's.

## Rebuild
```bash
cd shoresh && python -m macula.build_bdb_roots   # -> resources/bdb_roots/root_groups.tsv
```
Fetch is pinned (`build_bdb_roots.py`'s `COMMIT`) — re-pin deliberately if OpenScriptures updates.
