"""Package bcv-commons/addressees: who each quotation of the Hebrew Bible and the Greek NT is said to, how that was found, and the
speaker-to-hearer relation (macula/build_addressees.py; wave 3).

    cd shoresh && .venv/bin/python3 -m macula.release_addressees --out DIR [--allow-dirty]

Rebuilds the table and replaces ACAI's entity ids (English names) with the same neutral codes bcv-commons/reference-status uses
(`e` + 10 hex digits of the id's SHA-1), so the two datasets join. Writes DIR/data/{quotations,persons}.parquet, checks.md, README.md,
build.json, SHA256SUMS. Nothing is uploaded.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import datetime
import io
import json
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from macula import build_addressees as B
from macula import release_guard  # refuses TBTA and private inputs
from macula.release_reference_status import code, sha256

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 1
VERSION = "v0.1"
REPO = "bcv-commons/addressees"
ENTITY_COLS = {"speaker", "addressee", "second_person"}
INTS = {"spoke", "addressed", "father", "mother", "partners", "children"}


def c(v: str) -> str:
    return code(v) if v else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "shoresh/macula"], cwd=ROOT, text=True).strip()
    if dirty and not a.allow_dirty:
        raise SystemExit(f"uncommitted changes in shoresh/macula:\n{dirty}")
    commit = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=ROOT, text=True).strip() + ("+uncommitted" if dirty else "")
    with contextlib.redirect_stdout(io.StringIO()):
        B.main()
    q = list(csv.DictReader(open(B.OUT / "quotations.tsv", encoding="utf-8"), delimiter="\t"))
    p = list(csv.DictReader(open(B.OUT / "persons.tsv", encoding="utf-8"), delimiter="\t"))
    bad = [r["quote"] for r in q if r["addressee"] == "lemma:"]
    if bad:
        raise SystemExit(f"{len(bad)} addressees with an empty lemma: {bad[:5]}")
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "data").mkdir()
    qcols = list(q[0])
    pq.write_table(pa.table({k: pa.array([c(r[k]) if k in ENTITY_COLS else r[k] for r in q], type=pa.string()) for k in qcols}),
                   a.out / "data/quotations.parquet")
    pcols = list(p[0])
    pq.write_table(pa.table({k: (pa.array([int(r[k] or 0) for r in p], type=pa.int32()) if k in INTS else
                                 pa.array([c(r[k]) if k == "entity" else r[k] for r in p], type=pa.string())) for k in pcols}),
                   a.out / "data/persons.parquet")
    counts = {}
    for corpus in ("hbo", "grc"):
        sub = [r for r in q if r["corpus"] == corpus]
        counts[corpus] = {"quotations": len(sub), **{b: sum(r["basis"] == b for r in sub) for b in ("inquit", "second_person", "turn")},
                          "none": sum(not r["basis"] for r in sub),
                          "agree": f"{sum(r['agree'] == '1' for r in sub) / max(1, sum(r['agree'] != '' for r in sub)):.2f}",
                          "relation": sum(bool(r["relation"]) for r in sub)}
    (a.out / "checks.md").write_text((B.OUT / "checks.md").read_text(encoding="utf-8"), encoding="utf-8")
    (a.out / "README.md").write_text(card(counts, len(p)), encoding="utf-8")
    files = sorted(x for x in a.out.rglob("*") if x.is_file())
    meta = {"schema": SCHEMA, "version": VERSION, "repo": REPO, "built": datetime.date.today().isoformat(), "code": commit,
            "licence": "CC BY-SA 4.0", "entity_codes": "e + sha1(ACAI id)[:10], as in bcv-commons/reference-status",
            "not_read": ["BHSA", "TBTA", "English text"], "counts": counts, "persons": len(p),
            "files": {str(x.relative_to(a.out)): sha256(x) for x in files}}
    (a.out / "build.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    files = sorted(x for x in a.out.rglob("*") if x.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(x)}  {x.relative_to(a.out)}\n" for x in files), encoding="utf-8")
    print(f"{a.out}: " + "; ".join(f"{k} {v}" for k, v in counts.items()) + f"; persons {len(p)}; code {commit}")
    return 0


def card(n: dict, n_persons: int) -> str:
    h, g = n["hbo"], n["grc"]
    return f"""---
license: cc-by-sa-4.0
language: [hbo, arc, grc]
pretty_name: Addressees of the quotations of the Hebrew Bible and the Greek New Testament
tags: [bible, hebrew, greek, discourse, speech, addressee, honorifics, translation]
configs:
- config_name: quotations
  data_files: data/quotations.parquet
- config_name: persons
  data_files: data/persons.parquet
---

# Addressees ({VERSION})

Many languages choose pronouns, verb forms or polite registers by who speaks to whom: a child to a parent, a person to God, one
person to a crowd. This dataset gives each quotation of the Hebrew Bible ({h['quotations']:,}) and the Greek New Testament
({g['quotations']:,}) its addressee where the text shows one, how it was found, and the speaker-to-hearer relation.

| | quotations | from the inquit | from "you" in the quotation | a reply | not found |
|---|---|---|---|---|---|
| Hebrew Bible | {h['quotations']:,} | {h['inquit']:,} | {h['second_person']:,} | {h['turn']:,} | {h['none']:,} |
| Greek New Testament | {g['quotations']:,} | {g['inquit']:,} | {g['second_person']:,} | {g['turn']:,} | {g['none']:,} |

## `quotations`

| column | description |
|---|---|
| `corpus`, `quote`, `first` | hbo / grc, the quotation id of the bcv-commons speaker layers, its first clause key |
| `speaker_id`, `speaker` | the speaker-layer character id, and the speaker's entity code |
| `addressee` | the hearer: an entity code (`e…`, as in bcv-commons/reference-status), or `lemma:<Strong's or lemma>` where the inquit names a hearer no entity covers ("the people", "the vessels") |
| `addressee_id` | the hearer's speaker-layer character ids, where the hearer also speaks |
| `basis` | `inquit`: the speech clause names the hearer (Hebrew אֶל / לְ / עַל or the object of צִוָּה; Greek a dative, πρός, or the object of asking verbs); `second_person`: the commonest entity the quotation's second-person words refer to; `turn`: a reply to the quotation before, which was said to this speaker; empty: not found |
| `addressee_words` | the inquit word naming the hearer (MACULA id) |
| `second_person` | the second-person check on its own, where it gives an entity |
| `agree` | 1 / 0: whether the inquit and the second-person check agree, where both give an entity |
| `plural` | 1 when the hearer is a group or the inquit word is plural |
| `relation` | `parent_to_child`, `child_to_parent`, `spouse`, `sibling` (from ACAI's kinship), `divine_to_human`, `human_to_divine`, `to_group`, or empty |

## `persons` ({n_persons:,} entities who speak or are spoken to)

`entity` (code), `type`, `gender`, `characters` (speaker-layer ids), `spoke`, `addressed` (quotation counts), and how many fathers,
mothers, partners and children ACAI records for them.

## How good it is

Nothing was checked by hand. Where the inquit and the second-person words both give an entity, they agree {h['agree']} of the time
in Hebrew and {g['agree']} in Greek. A reply is only taken where the quotation before was said to this speaker (then right 0.85 in
Hebrew and 0.75 in Greek, by the same agreement check); the plain "next speaker answers" rule held only 0.5 to 0.65 and is not used.
Not measured in drafting yet.

## Licence

CC BY-SA 4.0 (ACAI's ShareAlike). Built from MACULA Hebrew and Greek (CC BY 4.0), ACAI Biblical Entity Data (CC BY-SA 4.0), and
the bcv-commons speaker layers, clause layouts, argument roles and reference status. Credit: MACULA (Clear Bible / Biblica), ACAI
(BibleAquifer), and this dataset.
"""


if __name__ == "__main__":
    raise SystemExit(main())
