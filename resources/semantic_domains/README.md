# semantic_domains/

Lexeme-level **Strong's → semantic domain** tables, so concept retrieval can broaden a single
Strong's to a whole semantic domain (e.g. "love" → the *Love/Affection* domain → every lexeme in it).

Built by `shoresh/macula/build_ubs_open.py` from **UBS's open release**: the UBS Dictionary of
Biblical Hebrew (from SDBH) and the UBS Dictionary of the Greek New Testament (Louw-Nida), pinned to
`github.com/ubsicap/ubs-open-license` @ `33dcc8c` (2026-09-22).

> **Licence: CC BY-SA 4.0.** © United Bible Societies 2023. Attribute UBS when serving or
> redistributing, and release anything that incorporates these tables under CC BY-SA too. Keep them
> out of the CC0 lineage (`semantic_neighbors/`, `semantic_groups/`, `prior_pack/`).
>
> History: until 2026-10 these tables came from the UBS MARBLE layer bundled with MACULA, "used with
> permission" and not redistributable. They were rebuilt from the open release, and SDBH's `core` and
> `ctx` axes, which the open release does not include, were retired. Hebrew concept grouping is now
> served from `../semantic_groups/` (CC0).

## Files & schema
`<lang>.tsv` columns: `strong  domain_type  domain  label  count  share`
- `count` = the number of Scripture references UBS lists for the senses of that word in that domain;
  `share` = count / the word's total **within that `domain_type`**.
- sorted by `strong`, then `domain_type`, then `count` desc (primary domain first).
- a word's **primary** domain per axis is always emitted; others are kept when count ≥ 2.

| file | `domain_type` | taxonomy | notes |
|---|---|---|---|
| `grc.tsv` | `sdbg` | Louw-Nida (3-digit domain, 6-digit subdomain where UBS gives one) | 5,311 words |
| `hbo.tsv` | `lex` | SDBH lexical domain (hierarchical, 3-15 digits) | 8,485 words; about a quarter of senses are proper-name domains |
| | `sdbg` | Louw-Nida via the LXX bridge | 1,840 words; cross-language unification (e.g. chesed → Mercy); uses `../lxx_bridge.tsv` → `grc.tsv` |

SDBH and Louw-Nida are different taxonomies; codes are not comparable across them. For
cross-language links use the lexical bridge (`../lxx_bridge.tsv`), not code equality.

## Domain-name localization: `domain_labels/<iso639-3>.tsv`
Localized Louw-Nida domain names, used by shoresh `/verse` (`_localize_domain`, keyed by `gloss_lang`).
One file per language (`code · label`); a new language is a new file plus a `_DOMAIN_LANG_COL` entry in
shoresh `data.py`.
- `eng`, `spa`, `fra`, `cmn-Hans`: from the UBS open release's localized domain files (CC BY-SA 4.0).
- `ind`, `deu`: our own translations of the English names (`bcv-RAG/scripts/build_domain_labels_{id,de}.py`);
  as adaptations of the UBS names they are CC BY-SA 4.0 as well.

## Rebuild
```bash
cd shoresh && .venv/bin/python3 -m macula.build_ubs_open
```
Downloads (cached, resumable) into `shoresh/macula/data/ubs_open/`. To move to a newer UBS release,
change `COMMIT` (and file versions) in the script.
