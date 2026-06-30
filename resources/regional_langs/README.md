# `regional_langs/` — variants **within** one language

The sibling of [`related_langs/`](../related_langs/README.md). That folder answers "which
*other* languages are related to X?"; this one answers **"what regional / script / locale
variants exist *under* one ISO 639-3 code?"** — a different relation, different sources, kept
separate on purpose.

Two sub-relations, both keyed by `iso639_3`:

| file | relation | example |
|---|---|---|
| `variants.tsv` | **locale / script variants** of one language (BCP-47) | `cmn` → `zh-Hans`, `zh-Hant` |
| `macrolanguages.tsv` | ISO 639-3 **macrolanguage → member languages** | `zho` → `cmn`, `yue`, `wuu`… ; `ara` → `arb`, `arz`… |

## Why two relations
- A **macrolanguage** (`zho`, `ara`, `nor`, `swa`, `yid`) is an ISO 639-3 umbrella over several
  *distinct individual languages*. "Regional languages coming from the same 3-letter code" =
  this mapping.
- A **locale/script variant** (`pt-BR` vs `pt-PT`, `zh-Hans` vs `zh-Hant`) is *one* language
  written/used differently by region or script — expressed as **BCP-47** tags
  (`language[-script][-region]`, RFC 5646 = ISO 639 + ISO 15924 script + ISO 3166 region).

The clearest case in the current data: **Chinese-Simplified / Chinese-Traditional are not two
languages** — they're one language (`cmn`) in two scripts. So they live here (`variants.tsv`),
not in the relatedness graph, where they'd otherwise masquerade as "related languages."

## Current state (seed)
`variants.tsv` is real (the `cmn` Hans/Hant split, with `gloss_name` linking each variant to
its generated gloss file). `macrolanguages.tsv` is an illustrative seed for the macrolanguages
present in `related_langs/` — enough to show the shape; the full set comes from the ISO 639-3
ingest below.

### Columns
- `variants.tsv`: `iso639_3 · bcp47 · script(15924) · region(3166) · name · gloss_name · kind`
  (`kind` ∈ `script` | `region` | `locale`). `gloss_name` is the `word_glosses/` file stem if
  a gloss set exists for that variant, else blank.
- `macrolanguages.tsv`: `macro_iso639_3 · macro_name · member_iso639_3 · member_name`.

---

## Planned implementation

Keyed by the same `iso639_3` as `related_langs/`, so the two join cleanly.

- **`macrolanguages.tsv`** ← ISO 639-3 macrolanguage mapping (SIL `iso-639-3-macrolanguages.tab`,
  free) — authoritative and complete (~60 macrolanguages, ~500 members).
- **`variants.tsv`** ← **CLDR** (Unicode Common Locale Data Repository) + the **IANA language
  subtag registry**: the canonical source for which locales/regions/scripts exist per language
  (`pt` → `pt-BR`, `pt-PT`, `pt-AO`…). Emit normalized BCP-47 tags.
- Folds into the planned **`languages.db`** (see `related_langs/` README) as two more indexed
  tables, so "by code → regional variants" is a single join:

```sql
CREATE TABLE variant(iso639_3, bcp47, script, region, name, gloss_name, kind);
CREATE TABLE macrolanguage(macro_iso639_3, member_iso639_3, member_name);
CREATE INDEX var_by_code   ON variant(iso639_3);
CREATE INDEX macro_by_code ON macrolanguage(macro_iso639_3);
```

### Query patterns
1. **code → its variants**: `SELECT bcp47, gloss_name FROM variant WHERE iso639_3=?`.
2. **macrolanguage code → member languages**: `SELECT member_iso639_3 FROM macrolanguage
   WHERE macro_iso639_3=?` — then each member can be looked up in `related_langs/`.
3. **variant tag → base language**: reverse lookup for normalizing an incoming `pt-BR` to `por`.

### Licences
ISO 639-3 macrolanguage table free · CLDR Unicode licence · IANA registry public — within the
project's CC-BY-SA / CC-NC acceptance.

## Regenerating
Seed files are currently hand-maintained. Once the ISO 639-3 + CLDR ingest lands it will be a
`build_regional_langs.py` alongside `build_related_langs.py`. The README is hand-authored.
