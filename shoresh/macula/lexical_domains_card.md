---
license: cc-by-sa-4.0
language:
- hbo
- grc
pretty_name: Lexical domains
tags:
- bible
- hebrew
- greek
- semantic-domains
- louw-nida
- sdbh
---

# lexical-domains @TAG@

The meaning domains of the UBS dictionaries as a tree of codes, joined to the words of the Tanakh and the Greek NT (MACULA
word keys): SDBH lexical domains for Hebrew and Aramaic, Louw-Nida domains and subdomains for Greek. Each domain row says
where it sits in its tree, how many words fall in it, and which Hebrew or Greek lemmas fill it.

**Codes only.** The domains' names are not stored: they are English (or other modern-language) labels in UBS's own files,
looked up by code (`UBSHebrewDicLexicalDomains-v0.9.3-en.JSON`, `UBSGreekNTDicLexicalDomains-v1.1-en.JSON` and their
localisations, github.com/ubsicap/ubs-open-license at @UBS@). What a domain holds is shown by its lemmas, in Hebrew and Greek.

## Tables

`data/domains.parquet`: one row per domain code (SDBH @SDBH@ codes, @SDBH_USED@ with words; Louw-Nida @LN@ codes, @LN_USED@ with words).

| column | |
|---|---|
| `system` | `sdbh` (Hebrew/Aramaic) or `ln` (Greek, Louw-Nida) |
| `code` | the UBS domain code: SDBH 3-digit segments (`001001002` is inside `001001` inside `001`); Louw-Nida `033` a domain, `033005` its subdomain |
| `parent` | the code one level up, null at the top |
| `level` | as UBS gives it; `has_subdomains` from the tree (UBS's own flag is wrong for 3 SDBH codes; build.json lists them) |
| `senses` | UBS senses that place a word directly in this domain (in the words below) |
| `words` | MACULA words placed directly in this domain; `words_with_narrower` adds those of its narrower domains |
| `lemmas` | up to 12 lemmas found in the domain or its narrower domains, with Strong's number and word count, most frequent first |

`data/word_domains.parquet` (@ROWS@ rows): `key` (MACULA word or morpheme key), `lang`, `system`, `code`, `sense` (UBS sense id).
A word whose sense lists two SDBH domains (`a;b`) has a row for each; a Greek word has its Louw-Nida subdomain where the
dictionary gives one, else its domain. Hebrew @HBO_WORDS@ words, Greek @GRC_WORDS@ words with a sense.

Not here: SDBH's contextual domains. The v0.9.3 dictionary ships their tree but does not link senses to them.

## Sources and licence

UBS Dictionary of Biblical Hebrew (from SDBH) v0.9.3 and UBS Dictionary of the Greek New Testament v1.1 (Louw-Nida),
© United Bible Societies 2023, CC BY-SA 4.0; the word to sense links from bcv-commons/word-senses v0.1 (@WS@); word keys and
lemmas MACULA Hebrew and Greek (CC BY 4.0). This dataset: CC BY-SA 4.0.

## Provenance

Code @CODE@: `shoresh/macula/build_lexical_domains.py` (with `build_ubs_open.py` for the pinned UBS files).
