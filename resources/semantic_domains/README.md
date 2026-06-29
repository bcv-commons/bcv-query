# semantic_domains/

Lexeme-level **Strong's → semantic domain** tables (S2 / Phase 1), so concept
retrieval can broaden a single Strong's to a whole semantic domain (e.g. "love"
→ the *Love/Affection* domain → every lexeme in it).

Built by `bcv-RAG/scripts/build_semantic_domains.py` from **MACULA**
(`Clear-Bible/macula-greek`, `Clear-Bible/macula-hebrew`).

> ⚠️ **Licensing — NOT CC BY 4.0.** This table is derived from the **UBS MARBLE**
> semantic data (SDBG = Louw-Nida; SDBH = de Blois, © 2000–2021 United Bible
> Societies). MACULA's own LICENSE carries this data **"used with permission,"**
> *separately from* its CC BY 4.0 grant — i.e. the CC-BY licence does **not** cover
> the semantic-domain layer, and that permission was granted to Biblica, not
> transitively to downstream users. Treat `semantic_domains/` and `senses/` as
> reference data under UBS terms: usable here, **not** safe to redistribute or use
> commercially as CC-BY without your own UBS permission. (The morphology, syntax,
> Strong's, glosses, frames and referents from MACULA *are* genuinely CC BY 4.0 —
> only the domain/sense layer is encumbered.)

## Files & schema
`<lang>.tsv` columns: `strong  domain_type  domain  label  count  share`
- `count` = occurrences of that (lexeme, domain); `share` = count / the lexeme's
  domain-tagged total **within that `domain_type`**.
- sorted by `strong`, then `domain_type`, then `count` desc (primary domain first).
- a lexeme's **primary** domain per axis is always emitted; secondary domains are
  kept when count ≥ 2.

| lang | `domain_type` | taxonomy | notes |
|---|---|---|---|
| `grc.tsv` | `sdbg` | SDBG / Louw-Nida (6-digit) | one axis; 5,339 lexemes |
| `hbo.tsv` | `core` | SDBH **core concept** | **the concept axis — use this** (Affection, Compassion, Justice…) |
| | `lex` | SDBH **lexical/referential** | finer "what kind"; ~⅓ are proper-name domains — noisier |
| | `ctx` | SDBH **contextual/situational** | register/setting (Divine, Human, Marriage, Law, Sanctuary…) |
| | `sdbg` | **SDBG via the LXX bridge** (Greek's domain) | cross-language unification + fills native-SDBH gaps (e.g. shalom→Peace, chesed→Mercy); uses `../lxx_bridge.tsv` → `grc.tsv` |

`hbo` carries the three native SDBH axes plus the bridged `sdbg` axis (7,198
lexemes; 1,843 with the `sdbg` cross-language axis). Filter by `domain_type`:
`core` for the native Hebrew concept, `sdbg` to match Hebrew↔Greek on a shared
Louw-Nida domain. Native SDBH and bridged SDBG are *different taxonomies* — a
lexeme can legitimately differ across them (chesed: SDBH `core`=Faithfulness,
bridged `sdbg`=Mercy — both true; the LXX rendered חֶסֶד with ἔλεος).

## Taxonomy caveat
SDBG (Greek) and SDBH (Hebrew) are **different** domain systems — codes are **not
cross-comparable**. For cross-language concept linking use the lexical bridge
(`../lxx_bridge.tsv`), not domain-code equality.

## Provenance gotcha (why Hebrew is built from the source, not the TSV)
macula-hebrew's convenience `WLC/tsv/macula-hebrew.tsv` ships **stale/offset**
domain codes (the "MARBLE identifiers changed and aren't reflected" warning in
its `mappings/README`) — they mislabel abstract concepts (chesed→"Evil",
love→"Lazy"). So `hbo.tsv` is built from the **source**
`sources/MARBLE/SDBH/macula-marble-domains.xml` (current codes; chesed→
"Faithfulness", love→"Affection"), joined to the WLC TSV only for the Strong's
number (on `maculaId`). Greek's TSV codes are current (validated), so `grc.tsv`
uses it directly.

## Rebuild
```bash
python -m scripts.build_semantic_domains --lang grc                 # build grc.tsv first
python -m scripts.build_semantic_domains --lang hbo --with-bridge   # native SDBH + bridged sdbg
```
(`--with-bridge` reads the just-built `grc.tsv` + `../lxx_bridge.tsv`; sources download if not cached.)
