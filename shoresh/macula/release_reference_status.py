"""Package bcv-commons/reference-status: who each noun phrase of the Hebrew Bible and the Greek NT refers to, whether the referent is new,
given or brought back, how the source marks it, and its animacy (macula/build_reference_status.py; wave 1b, held for Indonesian in
research's track D measurement).

    cd shoresh && .venv/bin/python3 -m macula.release_reference_status --out DIR [--allow-dirty]

Rebuilds the table, replaces ACAI's entity ids (English names) with neutral codes (`e` + 10 hex digits of the id's SHA-1, stable
across builds), and writes DIR/data/{hebrew,greek-nt}.parquet, checks.md, README.md, build.json, SHA256SUMS. Nothing is uploaded.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import datetime
import hashlib
import io
import json
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from macula import build_reference_status as B
from macula import release_guard  # refuses TBTA and private inputs
from macula.release_clause_columns import LAYOUTS, layout_keys

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 1
VERSION = "v0.1"
REPO = "bcv-commons/reference-status"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def code(referent: str) -> str:
    """ACAI ids are English names: publish a neutral code; Strong's / Greek lemma chains and unresolved ids stay as they are"""
    if referent.startswith(("lemma:", "unresolved:")):
        return referent
    return "e" + hashlib.sha1(referent.encode("utf-8")).hexdigest()[:10]


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
    rows = list(csv.DictReader(open(B.OUT / "np.tsv", encoding="utf-8"), delimiter="\t"))
    keys = {"hbo": layout_keys(LAYOUTS["hebrew"]), "grc": layout_keys(LAYOUTS["greek-nt"])}
    missing = {c: sum(1 for r in rows if r["corpus"] == c and r["clause_key"] not in keys[c]) for c in ("hbo", "grc")}
    if any(missing.values()):
        raise SystemExit(f"clause keys not in the pinned layouts: {missing}")
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "data").mkdir()
    cols = [c for c in B.COLS if c != "corpus"]
    counts = {}
    for corpus, name in (("hbo", "hebrew"), ("grc", "greek-nt")):
        sub = [r for r in rows if r["corpus"] == corpus]
        data = {c: [code(r[c]) if c == "referent" else r[c] for r in sub] for c in cols}
        data["distance"] = [int(x) if x else None for x in data["distance"]]
        t = pa.table({c: (pa.array(v, type=pa.int32()) if c == "distance" else pa.array(v, type=pa.string())) for c, v in data.items()})
        pq.write_table(t, a.out / f"data/{name}.parquet")
        counts[name] = {"rows": len(sub), **{f"status:{s}": sum(1 for r in sub if r["status"] == s) for s in
                                              ("new", "given", "restaged", "known", "unresolved")}}
    (a.out / "checks.md").write_text((B.OUT / "checks.md").read_text(encoding="utf-8"), encoding="utf-8")
    (a.out / "README.md").write_text(card(counts), encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    meta = {"schema": SCHEMA, "version": VERSION, "built": datetime.date.today().isoformat(), "code": commit, "licence": "CC BY-SA 4.0",
            "layouts": {c: {"repo": v["repo"], "version": v["version"], "revision": v["revision"]} for c, v in LAYOUTS.items()},
            "window": B.WINDOW, "episode": "chapter", "referent_codes": "e + sha1(ACAI id)[:10]; lemma:<Strong's or lemma>; unresolved:<word>",
            "not_read": ["BHSA", "TBTA", "English text"], "counts": counts,
            "files": {str(p.relative_to(a.out)): sha256(p) for p in files}}
    (a.out / "build.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(a.out)}\n" for p in files), encoding="utf-8")
    print(f"{a.out}: " + ", ".join(f"{k} {v['rows']:,} rows" for k, v in counts.items()) + f"; code {commit}")
    return 0


def card(c: dict) -> str:
    h, g = c["hebrew"], c["greek-nt"]
    return f"""---
license: cc-by-sa-4.0
language: [hbo, arc, grc]
pretty_name: Reference status of the noun phrases of the Hebrew Bible and the Greek New Testament
tags: [bible, hebrew, greek, reference, definiteness, participant-tracking, translation]
configs:
- config_name: hebrew
  data_files: data/hebrew.parquet
- config_name: greek-nt
  data_files: data/greek-nt.parquet
---

# Reference status ({VERSION})

Whether a translation writes "a", "the", "this", "that" or a pronoun depends on who a phrase refers to and whether the reader
already knows them. This dataset gives every noun-phrase head of the Hebrew Bible ({h['rows']:,}) and the Greek New Testament
({g['rows']:,}) its referent, its status in the episode, how the source marks it, and its animacy.

| | new | given | restaged | known | unresolved |
|---|---|---|---|---|---|
| Hebrew Bible | {h['status:new']:,} | {h['status:given']:,} | {h['status:restaged']:,} | {h['status:known']:,} | {h['status:unresolved']:,} |
| Greek New Testament | {g['status:new']:,} | {g['status:given']:,} | {g['status:restaged']:,} | {g['status:known']:,} | {g['status:unresolved']:,} |

## Columns

| column | description |
|---|---|
| `clause_key` | the clause in the bcv-commons clause layouts (as in bcv-commons/clause-columns) |
| `head` | the phrase's head word (MACULA id: Hebrew 12 digits, Greek 11) |
| `referent` | who or what it refers to: `e…` an entity code (ACAI's entity, coded), `lemma:<Strong's or lemma>` a chain on the word itself, `unresolved:<word>` a pronoun with no referent |
| `basis` | acai (ACAI links the word to the entity), ref (MACULA's reference chain reaches it), lemma, unresolved |
| `status` | new (first mention in the episode), given (mentioned within the last {B.WINDOW} clauses), restaged (mentioned earlier, more than {B.WINDOW} clauses back), known (God on first mention), unresolved |
| `distance` | clauses since the last mention (null for new / known / unresolved) |
| `definite` | how the source marks the phrase: article (Hebrew also inside בַּ / לַ, Aramaic determined state), proper, suffix, construct, demonstrative, pronoun, or empty |
| `proximity` | near (זֶה / זֹאת / אֵלֶּה, Aramaic דְּנָה …, οὗτος) or remote (article + הוּא …, ἐκεῖνος) where a demonstrative stands in the phrase |
| `animacy` | person, deity, animal, place, thing, or empty: ACAI's type, else the head's UBS domain (SDBH, Louw-Nida) |

The episode is the chapter. Mentions are counted from every head and from every word ACAI links to an entity (verbs carry their
implied subjects). Entity codes are stable across builds of this dataset; they are not ACAI's ids.

## How good it is

Nothing was checked by hand. The source's own marking agrees in direction: new referents are unmarked far more often than given
ones (Hebrew 0.30 against 0.11, Greek 0.42 against 0.13), and pronoun heads are mostly given. Greek "new" phrases with the article
(0.41) are partly unique, generic or inferable referents ("the crowd", "the house"), which this version does not separate.

## Measured use

A rule-based drafting engine, tested on the Tanakh in six rotating test groups, each drafted by an engine that had not seen it:

| use | before | after | word F1 of the draft |
|---|---|---|---|
| Indonesian *itu* after a given or restaged phrase the source marks as definite | 0.060 | 0.671 right | +0.34 |
| Swahili demonstrative of the noun's class where the source has one (near / remote) | 0.033 | 0.321 right | +0.03 |

Swahili marks a given phrase far less often than Indonesian: adding a demonstrative at every restaged phrase was right 0.07 of the
time and was dropped.

## Licence

CC BY-SA 4.0 (ACAI's ShareAlike, UBS domains). Built from MACULA Hebrew and Greek (CC BY 4.0), ACAI Biblical Entity Data
(CC BY-SA 4.0), the UBS dictionaries' domains (CC BY-SA 4.0) and the bcv-commons clause layouts (Hebrew CC BY-SA 4.0, Greek CC BY 4.0). Credit: MACULA
(Clear Bible / Biblica), ACAI (BibleAquifer), United Bible Societies, make-tanakh-research (the measurements), and this dataset.
"""


if __name__ == "__main__":
    raise SystemExit(main())
