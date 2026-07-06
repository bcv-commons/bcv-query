# `languages/` — code-keyed language registry (scaled to all ISO 639-3)

The built, **all-languages** registry — the superset successor to the hand-curated
[`related_langs/`](../related_langs/README.md) bootstrap. Keyed by `iso639_3`, covering every
ISO 639-3 language (~7,900), so cross-language ranking and reference-language fallback work for
*any* language, not just onboarded ones. Design + roadmap: `internal-docs/languages-db-design.md`.

> **Status: Phase A (registry) done.** Phase B (data-derived relatedness) and Phase C
> (`languages.db` + cutover of the live consumers) are not built yet — see the design note.

## Files

| file | what |
|---|---|
| `languages.tsv` | one row per ISO 639-3 language — `iso639_3 · iso639_1 · name · glottocode · stock · group · branch · scripts · macrolanguage` |
| `code_alias.tsv` | retired ISO 639-3 code → current code (`old_code · current_code`), so old citations still resolve |
| `_raw/` | downloaded source cache (git-ignored; re-fetched on build) |

## Columns & provenance

- `iso639_3`, `iso639_1`, `name`, `macrolanguage` — **ISO 639-3** tables (SIL, free): the code
  spine + individual↔macrolanguage links. Scopes `I` (individual) + `M` (macrolanguage); `S`
  (special, e.g. `mul`/`und`) excluded.
- `glottocode`, `stock` — **Glottolog CLDF** (CC-BY-SA), joined on the ISO code. `stock` = the
  top-level family (e.g. Indo-European, Afro-Asiatic). Language-level nodes preferred; dialect
  nodes fill ISO codes Glottolog only carries as dialects (e.g. `srp`/`hrv`). Macrolanguage rows
  (no Glottolog ISO of their own) inherit `stock` from a member individual.
- `group`, `branch`, `scripts` — **empty in Phase A** (documented follow-ups): group/branch need
  the Glottolog classification *path* (intermediate tree levels); `scripts` needs CLDR
  `languageData`. The curated `related_langs/languages.tsv` still has these for the ~50 bootstrap
  languages; the Phase-C cutover merges them in (curated values win as overrides).

Coverage at build: **7,925 languages, ~98% with `stock`, ~98% with `glottocode`.**

## Design rule (inherited from `related_langs/`)

This registry is **pure linguistics** — availability-agnostic. It carries **no**
`is_source` / `available` / `gloss_names` columns; which languages we actually serve is derived
data reconciled at cutover, never baked into the registry.

## Licences

Glottolog CC-BY-SA · ISO 639-3 free (SIL) — both within the project's licensing acceptance
(see `internal-docs/roadmap.md`). CLDR (Unicode) enters with the `scripts` follow-up.

## Regenerating

```bash
python -m scripts.build_languages_registry            # download (cached) + build
python -m scripts.build_languages_registry --no-net   # rebuild from the _raw/ cache only
```
(from `bcv-RAG/`). The `.tsv` outputs are the git-tracked source of truth; `_raw/` is a cache.
This README is hand-authored, not regenerated.
