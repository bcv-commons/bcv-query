# Text faults

`text_faults.tsv`: faults found in the texts we build on, one row each, with the fix our builders apply. The texts come
through bcv-commons/bibles' catalog from their sources; bibles does not edit them, so faults are recorded and fixed here.

| column | meaning |
|---|---|
| `fault_id` | F0001, ... never reused |
| `layer` | `source_text` (the edition's text as fetched) or `ours:<dataset>@<version>` (a fault in one of our own datasets) |
| `edition`, `word_id`, `book`, `chapter`, `verse`, `position` | where: our frozen word id, and the tokenizer position |
| `found` | the token (or part) as found |
| `fault` | `stray_label` (a label such as a book's end line, not text), `stray_letter`, `lost_letters`, ... |
| `fix` | `drop` (not a word of the text: no parts, not to be aligned) or `replace` (read as `fixed`) |
| `fixed` | the reading for `replace` |
| `note`, `found_on`, `status` | `open`; `fixed_upstream` once the source or our dataset carries the fix |

Ids stay frozen: a dropped token keeps its word id, marked by its fault. Readers: `macula.text_faults.load()`. Builders
that check a text (e.g. `build_aligner_tables`) stop on a fault that is not in the table; add it here, then rebuild.
