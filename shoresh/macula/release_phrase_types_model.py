"""Package bcv-commons/hebrew-phrase-types-model: a model layer (not a fact layer) of semantic types for the 50,829 clause-level
prepositional phrases of the Hebrew Bible, from make-tanakh-research's packet 07 v2.1 (the user cleared it for publishing; the merged
`label` is the published one, 2026-11-13).

    cd shoresh && .venv/bin/python3 -m macula.release_phrase_types_model --table TSV --out DIR [--allow-dirty]

TSV is research's hebrew_phrase_types_model.tsv, checked against TABLE_SHA256. Its `node` column (an id of our unpublished trees
database) is dropped: rows join by `phrase_key` (anchor spec) and `first_word`. Nothing is uploaded. DIR gets
data/hebrew_phrase_types.parquet, README.md (hebrew_phrase_types_model_card.md filled in), build.json and SHA256SUMS.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import hashlib
import json
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
CARD = Path(__file__).with_name("hebrew_phrase_types_model_card.md")
SCHEMA, VERSION = 1, "v0.1"
TABLE_SHA256 = "53aa12e53c98b335d856c1fe4777e00639cf494b57c37fd4cf60f3b2cffaeda5"
PHRASE_MAP_SHA256 = "ee049b02a3ab4d71546421d13371019efe3f3bf17491a32fae4825f2630a7a16"
COLUMNS = ["phrase_key", "first_word", "preposition", "head", "label", "basis", "group", "jev_label", "jev_confidence",
           "jev_second", "jev_second_p", "jev_group_p", "opus_label"]
FLOATS = {"jev_confidence", "jev_second_p", "jev_group_p"}
LABELS = {"Recipient", "Beneficiary", "Goal", "Place", "Source", "Time", "Instrument", "Accompaniment", "Manner", "Comparison",
          "Relation", "Purpose", "Possessor", "Object", "Other"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    assert sha256(a.table) == TABLE_SHA256, f"{a.table} is not packet 07 v2.1"
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "shoresh/macula"], cwd=ROOT, text=True).strip()
    if dirty and not a.allow_dirty:
        raise SystemExit(f"uncommitted changes in shoresh/macula:\n{dirty}")
    code = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=ROOT, text=True).strip() + ("+uncommitted" if dirty else "")
    rows = list(csv.DictReader(open(a.table, encoding="utf-8"), delimiter="\t"))
    assert len(rows) == 50829 and len({r["phrase_key"] for r in rows}) == 50829
    for r in rows:
        assert r["label"] in LABELS and r["jev_label"] in LABELS and (not r["opus_label"] or r["opus_label"] in LABELS), r
        assert r["basis"] in ("jev", "jev+opus", "opus")
        assert r["label"] == (r["opus_label"] or r["jev_label"])
    rows.sort(key=lambda r: r["phrase_key"])
    cols = {c: pa.array([float(r[c]) if r[c] != "" else None for r in rows], type=pa.float32()) if c in FLOATS else
            pa.array([r[c] or None for r in rows], type=pa.string()) for c in COLUMNS}
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "data").mkdir()
    pq.write_table(pa.table(cols), a.out / "data/hebrew_phrase_types.parquet")
    basis = collections.Counter(r["basis"] for r in rows)
    head = collections.Counter(r["head"] for r in rows)
    build = {"schema": SCHEMA, "version": VERSION, "built": datetime.date.today().isoformat(), "code": code, "licence": "CC BY 4.0",
             "layer": "model (not fact)", "source_table": {"name": "make-tanakh-research packet 07 v2.1, hebrew_phrase_types_model.tsv",
                                                          "sha256": TABLE_SHA256},
             "phrase_key_map": {"name": "node_phrase_key-trees-macula-2026-10-08.tsv", "sha256": PHRASE_MAP_SHA256},
             "models": {"jev": "Jev (TypeSafe), every phrase", "opus": "Claude Opus 5.5, second judge on 24,057 unsure phrases"},
             "inputs": "the Hebrew clause's words with MACULA Hebrew's lemmas and glosses (CC BY 4.0)",
             "counts": {"phrases": len(rows), "basis": dict(basis), "head": dict(head)}}
    (a.out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    card = CARD.read_text(encoding="utf-8")
    for k, v in {"@VERSION@": VERSION, "@CODE@": code, "@BUILT@": build["built"], "@TABLE_SHA@": TABLE_SHA256}.items():
        card = card.replace(k, v)
    assert "@VERSION@" not in card and "@CODE@" not in card
    (a.out / "README.md").write_text(card, encoding="utf-8")
    sums = sorted(p for p in a.out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(a.out)}\n" for p in sums), encoding="utf-8")
    print(f"bcv-commons/hebrew-phrase-types-model {VERSION} -> {a.out}: {len(rows):,} phrases, {dict(basis)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
