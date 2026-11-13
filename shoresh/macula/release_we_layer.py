"""Package bcv-commons/inclusive-we: inclusive / exclusive value of every first-person plural of the Hebrew Bible and the Greek NT
(macula/build_we_votes.py + build_we_layer.py; wave 1d, released after research's track D measurement).

    cd shoresh && .venv/bin/python3 -m macula.release_we_layer --out DIR [--allow-dirty]

Rebuilds the votes and the layer, then writes DIR/data/words.parquet, DIR/data/verses.parquet (per verse: vote counts per
edition as codes), checks.md (the votes' checks), README.md, build.json and SHA256SUMS. No translation text is stored or shipped.
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
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from macula import build_we_layer as L
from macula import build_we_votes as V
from macula import release_guard  # refuses TBTA and private inputs

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 1
VERSION = "v0.1"
REPO = "bcv-commons/inclusive-we"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def table(path: Path, drop=()):
    rows = list(csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"))
    cols = [c for c in rows[0] if c not in drop]
    return pa.table({c: pa.array([r[c] for r in rows], type=pa.string()) for c in cols}), rows


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
        V.main()
        L.main()
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "data").mkdir()
    words, wrows = table(L.OUT / "words.tsv")
    pq.write_table(words, a.out / "data/words.parquet")
    verses, vrows = table(V.OUT / "verses.tsv")
    pq.write_table(verses, a.out / "data/verses.parquet")
    checks = (V.OUT / "checks.md").read_text(encoding="utf-8")
    (a.out / "checks.md").write_text(checks + "\n" + (L.OUT / "checks.md").read_text(encoding="utf-8"), encoding="utf-8")
    nt = lambda r: r["book"] in V.NT  # noqa: E731
    cnt = {side: {v: sum(1 for r in wrows if (nt(r) == (side == "nt")) and r["value"] == v) for v in ("i", "e", "split", "unknown")}
           for side in ("nt", "tanakh")}
    (a.out / "README.md").write_text(card(len(wrows), len(vrows), cnt), encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    meta = {"schema": SCHEMA, "version": VERSION, "built": datetime.date.today().isoformat(), "code": code, "licence": "CC BY-SA 4.0",
            "editions": {e: {"licence": v[0], "family": v[1], "voting": e not in V.NON_VOTING} for e, v in V.EDITIONS.items()},
            "stores_translation_text": False, "not_read": ["BHSA", "TBTA", "English text"], "counts": cnt,
            "files": {str(p.relative_to(a.out)): sha256(p) for p in files}}
    (a.out / "build.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(a.out)}\n" for p in files), encoding="utf-8")
    print(f"{a.out}: {len(wrows):,} words, {len(vrows):,} verses; code {code}")
    return 0


def card(n_words: int, n_verses: int, c: dict) -> str:
    eds = "\n".join(f"| `{e}` | {v[1]} | {v[0]} | {'no (counted only)' if e in V.NON_VOTING else 'yes'} |" for e, v in V.EDITIONS.items())
    return f"""---
license: cc-by-sa-4.0
language: [hbo, arc, grc]
pretty_name: Inclusive and exclusive "we" in the Hebrew Bible and the Greek New Testament
tags: [bible, hebrew, greek, clusivity, pronouns, translation]
configs:
- config_name: words
  data_files: data/words.parquet
- config_name: verses
  data_files: data/verses.parquet
---

# Inclusive and exclusive "we" ({VERSION})

Hebrew and Greek say "we" without saying whether the person spoken to is included. Many languages must choose: an inclusive "we"
(speaker and addressee: "let us go", said to companions) or an exclusive one (the speaker's group without the addressee: "we have
sinned", said to God). This dataset gives every first-person plural word of the Hebrew Bible and the Greek New Testament
({n_words:,} words in {n_verses:,} verses) a value, with its reason and the other reading where one is attested.

| | inclusive | exclusive | translators differ | unknown |
|---|---|---|---|---|
| New Testament | {c['nt']['i']:,} | {c['nt']['e']:,} | {c['nt']['split']:,} | {c['nt']['unknown']:,} |
| Tanakh | {c['tanakh']['i']:,} | {c['tanakh']['e']:,} | {c['tanakh']['split']:,} | {c['tanakh']['unknown']:,} |

(word counts)

## How the values were made

**Votes.** Translators into languages that mark the distinction have each decided every case. For every verse with a source
first-person plural, the inclusive and exclusive forms of a closed list per language were counted in openly licensed editions. A
verse with only inclusive forms is an inclusive vote, only exclusive an exclusive vote; a verse with neither is an abstention, not
a vote. A value is set when at least 75% of at least 3 decisive votes agree; otherwise the verse is `split` (translators differ,
both readings kept) or `unknown` (too few votes). Edition verses are mapped to the source's numbering. No alignment is used, and
no translation text is stored: only codes and counts.

| edition | family | licence | votes |
|---|---|---|---|
{eds}

Each form list was checked by its precision (the share of a form's occurrences in verses with a source "we"); forms mostly used
otherwise were dropped. Marathi is counted but does not vote: it agrees with the others 0.74-0.82, against 0.89-0.95 for every
other pair.

**Agreement.** Among decisive votes, editions agree 0.96 in the New Testament and 0.93 in the Tanakh; Fleiss' kappa 0.87 and 0.75.
Counted with abstentions as votes, kappa falls to about 0.5, which is why studies that count every token find lower figures.
Disagreement concentrates in Paul's letters (Paul and co-workers, or Paul and readers) and in communal laments and confessions
(Psalms, Isaiah, Jeremiah).

**Rules.** Two rules from the source, checked against the votes, also give values:
- `to_god`: a verse with a second-person form whose MACULA referent is God is exclusive; God is not in the "we" (agrees 0.99).
- `let_us`: a cohortative or hortatory "we" with no "you" in the verse is inclusive (agrees 0.94).
A rule settles a split verse and fills an unknown one; where a rule and the votes disagree, the votes win and the rule's value is
the `alternative`.

## Columns (`words`)

| column | description |
|---|---|
| `key` | MACULA word id (Hebrew 12 digits, Greek 11) |
| `lang`, `book`, `chapter`, `verse` | where (source numbering) |
| `clause_key` | the clause in the bcv-commons clause layouts (as in bcv-commons/clause-columns) |
| `form` | verb, pronoun, suffix (Hebrew pronominal suffix), possessive (Greek ἡμέτερος) |
| `value` | i (inclusive), e (exclusive), split (translators differ), unknown |
| `alternative` | the other attested reading |
| `basis` | votes, rule:to_god, rule:let_us, votes+rule:… (both agree), rule:…,votes_split |
| `n_i`, `n_e`, `agree` | the verse's decisive inclusive and exclusive votes, and the majority's share |

The value is per verse: several "we" words in one verse share it (about 5% of edition votes show both forms in one verse).
`verses` has the per-edition votes (i, e, m for both, - for none) behind each value.

## Measured use

A rule-based drafting engine choosing the target form from `value`, tested on the Tanakh in six rotating test groups (each drafted
by an engine that had not seen it), on the 1,117 verses where the value changed its choice:

| | before | after |
|---|---|---|
| Indonesian kita / kami right | 0.614 | 0.912 |
| Tagalog inclusive / exclusive right | 0.529 | 0.788 |

No value was checked by hand; a human review of samples is planned and will be reported here.

## Licence

CC BY-SA 4.0. The values are computed from counts in the editions above (CC BY-SA 4.0 and public domain, eBible), MACULA (CC BY 4.0)
and the Hebrew clause layout's keys (CC BY-SA 4.0); no translation text is included. Credit: the translation teams of the editions
above, MACULA (Clear Bible / Biblica), make-tanakh-research (the measurements), and this dataset.
"""


if __name__ == "__main__":
    raise SystemExit(main())
