# Hebrew NT review: provenance (make-tanakh-research handovers, 2026-11-17)

Research made these and handed them over. Its code needs research's environment (private folders, its Python setup, the Jev
key), so only the script that runs here is kept in git. The rest stays in research's repository and in the packet copies
under `macula/data/handover/` (git-ignored; each checked against its `MANIFEST.sha256`).

| Packet | What it holds | MANIFEST.sha256 (sha256, first 16) | Used by |
|---|---|---|---|
| 32 hebrew-nt-alignments | Delitzsch links by Greek word id; the review records of both editions (Jev + Claude, 2026-10-31); its code: `scg_check`, `scg_review`, `scg_export`, `witness_agree`, `key_bridge`, `scg_bridge_probe`, `hebmod_byid`, `hebmod_parts`, `handover_hebnt`, design notes | `5efdd25013633c2d` | `build_hebrew_nt_bridge.py --by-id-local`, `release_hebrew_nt_review_model.py` |
| 33b lexeme-bridge-orig-judge | Jev's choice among the candidates of `build_bridge_candidates.py` (no glosses); the function-word calibration; code `bridge_jev.py judge-orig`, `hnt_function_jev.py` | `9725ac68f07dadd2` | `release_lexeme_bridge_model.py` |

Kept here: `hnt_function_sample.py`, the blind function-word check (`sample`, `score`). It runs with
`GREEK_TOKENS` set to a table `tokens(key, book, ch, v, text, lemma, class, ord)` of MACULA Greek (from `macula-spine.db`).
Its results are in hebrew-nt-review-model under `checks/function-words/`.
