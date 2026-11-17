#!/usr/bin/env python3
"""Delitzsch (heb_mod) in the alignments-by-id format, by lexeme-aligner's own builder (lexeme_aligner.alignments_by_id.build, the
code that made heb_scg's files), on our align-text run (lab/bridge: chain by parts + Jev v4 by clause). The builder is run as it is,
with four of its lookups pointed at our run: the edition's USJ, the parts analysis (our unpointed tagger's file instead of a pin in
config/target_parts.json), the Jev cell name (align-text's clause cells jevC.<edition>.<BOOK>.v4.A.jev-0 instead of the verse cells
jevA.<edition>.<BOOK>.v4.jev-0 heb_scg was built from on 2026-10-23, before lexeme-aligner's clause rule; same cell format), and the
output folder. Nothing in the checkout is written. Output: $MAKE_TANAKH_PRIVATE/rules/data/hebmod/by-id/<BOOK>_<hash>.json (+ the
manifest under by-id-root/).
    . ./env.sh; cd $BCV_COMMONS/lexeme-aligner/pipeline && ../.venv/bin/python $MAKE_TANAKH_GRAMMAR/lab/bridge/hebmod_byid.py"""
import json, os, shutil, sys
from pathlib import Path

P = Path(os.environ["MAKE_TANAKH_PRIVATE"]); A = P / "align" / "heb_mod"
WORDS = P / "rules" / "bridge" / "hebmod" / "tagger" / "export" / "heb_mod" / "words.parquet"
ROOT = P / "rules" / "data" / "hebmod" / "by-id-root"; DL = P / "rules" / "data" / "hebmod" / "by-id"
CELLS = Path(os.environ.get("HEBMOD_CELLS", A / "out"))

from lexeme_aligner import alignments_by_id as abi                         # noqa: E402

abi.usj_dir_of = lambda edition: A / "usj"
abi.tp.for_edition = lambda tag, *a, **k: (WORDS, {"dataset": "make-tanakh-grammar (local): bcv-query clause tagger retrained unpointed",
                                                    "revision": "2026-10-31", "file": "heb_mod/words.parquet", "min_p_split": 0.9})
abi.JEV_CELL = "jevC.{tag}.{book}.v4.A.jev-0"
entry = abi.build("heb_mod", "heb", out=ROOT, align_out=CELLS)
src = ROOT / "n1904" / "h" / "heb" / "heb_mod"
if DL.exists():
    shutil.rmtree(DL)
shutil.copytree(src, DL)
print(json.dumps({k: entry[k] for k in ("classes", "ids_linked", "ids_none", "part_positions", "tokens_added")}), "->", DL)
