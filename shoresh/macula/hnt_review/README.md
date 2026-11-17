# Hebrew NT alignment review (received from make-tanakh-research, packet 32, 2026-11-17)

Taken over by bcv-query on the user's direction (2026-11-17: original-language work of lasting value is bcv-query's; results and
code handed over so that bcv-query can maintain them). The scripts are as research ran them (sha256 in the packet's
`MANIFEST.sha256`, packet copy under `macula/data/handover/p32/`); they still read research's environment settings, listed in
`paths.json` (`MAKE_TANAKH_PRIVATE`, `MAKE_TANAKH_WORK`, `BCV_COMMONS`, `WORD_PARTS`, `TYPESAFE_API_KEY`). To run them here, point
those settings at our pinned inputs; the one input with no published form is research's lexeme bridge file (`strong_bridge_bq.json`).

| Script | What it does |
|---|---|
| `scg_check.py` | blind reference sample of content-word links, by group against the lexeme bridge |
| `scg_review.py` | Jev check per Greek content word, calibration, the correction layer, Claude batches, marks, spot checks (calls the Jev API) |
| `scg_export.py` | the review as records against the aligner's alignments-by-id files (`before` = staleness key) |
| `witness_agree.py` | Salkinson against Delitzsch, per Greek word |
| `key_bridge.py` | a Hebrew -> Greek lexeme table from the reviewed links (lexical marks only) |
| `scg_bridge_probe.py` | per link class, agreement with the lexeme bridge |
| `hebmod_byid.py` | Delitzsch in the alignments-by-id format by the aligner's own builder on research's align-text run |
| `hebmod_parts.py` | research's unpointed tagger run (superseded by hebrew-nt-analysis v0.2) |
| `hnt_function_sample.py` | the blind function-word check (sample / score) |
| `handover_hebnt.py` | builds the packet |
| `scg-review-design.md` | the review's design and rules v2 |
