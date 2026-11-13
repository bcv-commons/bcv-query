"""Package bcv-commons/word-senses: the UBS dictionaries' sense and meaning domain on every MACULA Hebrew and Greek word that has one
(macula/build_word_senses_ubs.py; wave 1a, released after research's track D measurement, the user's go 2026-11-13).

    cd shoresh && .venv/bin/python3 -m macula.release_word_senses --out DIR [--allow-dirty]

Rebuilds macula/data/word-senses-ubs first, then writes DIR/data/words.parquet, DIR/domains.tsv (the code table: the
dictionaries' English domain names, as passage-facts' codes.tsv), checks.md, README.md (the card), build.json and SHA256SUMS.
Nothing is uploaded.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import datetime
import hashlib
import io
import json
import shutil
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from macula import build_word_senses_ubs as B
from macula import release_guard  # refuses TBTA and private inputs

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 1
VERSION = "v0.1"
REPO = "bcv-commons/word-senses"
COLS = ["key", "lang", "entry", "sense", "ln", "domains", "subdomains", "basis", "part"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "shoresh/macula"], cwd=ROOT, text=True).strip()
    if dirty and not a.allow_dirty:
        raise SystemExit(f"uncommitted changes in shoresh/macula:\n{dirty}")
    code = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=ROOT, text=True).strip() + ("+uncommitted" if dirty else "")
    with contextlib.redirect_stdout(io.StringIO()):
        B.main()
    src = B.OUT
    build = json.loads((src / "build.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader(open(src / "words.tsv", encoding="utf-8"), delimiter="\t"))
    assert rows and list(rows[0]) == COLS, list(rows[0]) if rows else "empty"
    keys = {r["key"] for r in rows}
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "data").mkdir()
    S = pa.string()
    pq.write_table(pa.table({c: pa.array([r[c] for r in rows], type=S) for c in COLS}), a.out / "data/words.parquet")
    with open(src / "domains.tsv", encoding="utf-8") as f, open(a.out / "domains.tsv", "w", encoding="utf-8") as g:
        g.write("# UBS dictionary domain codes and their names. The data holds codes only; this table is the English.\n")
        g.write(f.read())
    shutil.copyfile(src / "checks.md", a.out / "checks.md")
    n = {"rows": len(rows), "words": len(keys), "hbo": len({r["key"] for r in rows if r["lang"] == "hbo"}),
         "grc": len({r["key"] for r in rows if r["lang"] == "grc"})}
    (a.out / "README.md").write_text(card(n), encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    meta = {"schema": SCHEMA, "version": VERSION, "built": datetime.date.today().isoformat(), "code": code,
            "source": build["source"], "licence": "CC BY-SA 4.0", "counts": {**build["counts"], **n},
            "not_read": ["MACULA's inline copies of the UBS fields", "BHSA", "TBTA", "English text as evidence"],
            "files": {str(p.relative_to(a.out)): sha256(p) for p in files}}
    (a.out / "build.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(a.out)}\n" for p in files), encoding="utf-8")
    print(f"{a.out}: {n['rows']:,} rows on {n['words']:,} words (Hebrew {n['hbo']:,}, Greek {n['grc']:,}); code {code}")
    return 0


def card(n: dict) -> str:
    return f"""---
license: cc-by-sa-4.0
language: [hbo, arc, grc]
pretty_name: Word senses (UBS) on MACULA Hebrew and Greek words
tags: [bible, hebrew, greek, lexicography, word-sense, semantic-domains, louw-nida, sdbh]
configs:
- config_name: words
  data_files: data/words.parquet
---

# Word senses ({VERSION})

The sense and meaning domains of the UBS dictionaries on every word of the Hebrew Bible and the Greek New Testament that UBS links
to one: {n['words']:,} words (Hebrew and Aramaic {n['hbo']:,}, Greek {n['grc']:,}), keyed by MACULA's word ids, as codes.

A translation choice often depends on the sense, not on the word: the same Hebrew or Greek lemma is translated differently when it
means different things. This dataset gives each word occurrence its sense, so a lexicon or a rule can be keyed by lemma and sense.

## Files

- `data/words.parquet`: one row per word and sense (a word UBS links to two senses has two rows; {n['rows']:,} rows).
- `domains.tsv`: the domain codes and their names in the UBS dictionaries (the only English in the dataset).
- `checks.md`: coverage per word class and the largest gaps.

## Columns

| column | description |
|---|---|
| `key` | MACULA word id: Hebrew 12 digits (WLC, MACULA Hebrew), Greek 11 digits (Nestle 1904, MACULA Greek) |
| `lang` | hbo (Hebrew and Aramaic) or grc |
| `entry` | the UBS dictionary entry (MainId) |
| `sense` | the UBS meaning id (LEXID): entry, base form, meaning |
| `ln` | Greek: the Louw-Nida number of the meaning (LEXEntryCode); Hebrew: empty |
| `domains` | the meaning's domain codes, `;`-joined (see `domains.tsv`) |
| `subdomains` | its subdomain codes, `;`-joined |
| `basis` | `index`: UBS's word index on the WLC (Hebrew); `references`: the dictionary's own references per meaning (Greek) |
| `part` | `i/n` when UBS links one sense to a phrase of n MACULA words (this word is the i-th), else empty |

## How it was made

- **Hebrew and Aramaic:** from UBS's own word index on the WLC. Each word's link names a lemma, a base form and a meaning in the
  Semantic Dictionary of Biblical Hebrew (SDBH, v0.9.3), resolved to the meaning's id and checked against the domain the index
  names.
- **Greek:** from the UBS Greek New Testament dictionary (v1.1). Each meaning lists the verses and word positions it covers.
- Source: [ubsicap/ubs-open-license](https://github.com/ubsicap/ubs-open-license), CC BY-SA 4.0. MACULA's own copies of these UBS
  fields are not read. Nothing comes from BHSA or TBTA.

Code: `shoresh/macula/build_word_senses_ubs.py` and `release_word_senses.py` in bcv-query.

## Coverage and gaps

| | noun | verb | adjective | preposition |
|---|---|---|---|---|
| Hebrew | 0.93 | 0.83 | 0.79 | 0.05 |
| Greek | 0.99 | 0.96 | 0.98 | 0.87 |

The open SDBH release has no entry, or no linked meaning, for 264 Hebrew content lemmas, among them some of the most frequent verbs
(הָיָה, בּוֹא, נָתַן, שָׁמַע, לָקַח) and כֹּל. Hebrew particles, prepositions and conjunctions are mostly not covered. `checks.md`
lists the largest gaps.

## How far to trust it

The senses are UBS's own assignments, carried over by code, not judged here. No row was checked by hand. A human review of samples
is planned and will be reported here.

Use in drafting has been measured. A rule-based drafting engine whose lexicon is keyed by Hebrew lemma and UBS sense, instead of
lemma alone, was tested on the Tanakh in six rotating test groups. Each group was drafted by an engine that had not seen it. The
measure is the share of words drafted correctly among those whose senses take different translations in training:

| language | lemma only | lemma and sense | gain | chrF3 gain |
|---|---|---|---|---|
| Indonesian | 0.337 | 0.387 | +5.1 | +1.4 |
| Tagalog | 0.244 | 0.272 | +2.8 | +1.1 |
| Swahili | 0.249 | 0.281 | +3.2 | +1.4 |

The Greek side has not been measured in drafting yet.

## Licence

CC BY-SA 4.0, as the UBS dictionaries' open release. Credit: United Bible Societies (Semantic Dictionary of Biblical Hebrew, UBS
Greek New Testament dictionary based on Louw and Nida), MACULA (Clear Bible / Biblica) for the word ids, and this dataset.
"""


if __name__ == "__main__":
    raise SystemExit(main())
