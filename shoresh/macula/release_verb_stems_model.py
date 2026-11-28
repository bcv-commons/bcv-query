"""Package the dataset bcv-commons/hebrew-nt-verb-stems-model: the stem of verbs in the Hebrew New Testaments, read by a
model for the words whose stem bcv-commons/hebrew-nt-analysis leaves empty. Nothing is uploaded, and no model is called.

    cd shoresh && .venv/bin/python3 -m macula.release_verb_stems_model --out DIR [--src DIR] [--allow-dirty]

Packages a finished run of macula/verb_stems_model.py (its stems.parquet per edition and ACCOUNT.json) as
DIR/<edition>/stems.parquet, ACCOUNT.json, README.md, build.json, SHA256SUMS. Every word id must be a verb of the
edition's word table, and every stem one of MACULA's stem names (or empty: read as no verb form).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pyarrow.parquet as pq

from macula import release_guard  # refuses TBTA and private inputs
from macula.build_text_ids import TEXTS, wid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
VERSION = "v0.1"
REPO = "bcv-commons/hebrew-nt-verb-stems-model"
SRC = HERE / "data" / "hebrew-nt-verb-stems-model" / "2026-11-28"
WORDS = HERE / "data" / "clause-tagger" / "export"
EDITIONS = ("heb_scg", "heb_mod")
ANALYSIS_PIN = "bcv-commons/hebrew-nt-analysis v0.10 (words.parquet and features.parquet, unchanged since v0.8)"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--src", type=Path, default=SRC)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "shoresh/macula"], cwd=ROOT, text=True).strip()
    if dirty and not a.allow_dirty:
        raise SystemExit(f"uncommitted changes in shoresh/macula:\n{dirty}")
    commit = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=ROOT, text=True).strip() + ("+uncommitted" if dirty else "")
    con = sqlite3.connect(f"file:{HERE / 'macula-spine.db'}?mode=ro", uri=True)
    stems = {s for (s,) in con.execute("select distinct stem from macula_words where lang='hbo' and class='verb'") if s and not s.startswith("unknown")}
    con.close()
    account = json.loads((a.src / "ACCOUNT.json").read_text(encoding="utf-8"))
    a.out.mkdir(parents=True, exist_ok=False)
    rows = {}
    for ed in EDITIONS:
        t = pq.read_table(a.src / ed / "stems.parquet")
        r = t.to_pylist()
        verbs = {wid(TEXTS[ed], w["book"], w["chapter"], w["verse"], w["i"])
                 for w in pq.read_table(WORDS / ed / "words.parquet", columns=["book", "chapter", "verse", "i", "class"]).to_pylist() if w["class"] == "verb"}
        if not {x["word"] for x in r} <= verbs or len({x["word"] for x in r}) != len(r):
            raise SystemExit(f"{ed}: a word id that is no verb of the word table, or a word twice")
        if {x["stem"] for x in r} - stems - {""} or {x["sureness"] for x in r} - {"sure", "unsure", "two"} or {x["model"] for x in r} != {account["model"]}:
            raise SystemExit(f"{ed}: a stem that is none of MACULA's, another sureness, or another model than the account names")
        (a.out / ed).mkdir()
        pq.write_table(t, a.out / ed / "stems.parquet", compression="zstd")
        rows[ed] = r
    shutil.copy(a.src / "ACCOUNT.json", a.out / "ACCOUNT.json")
    (a.out / "README.md").write_text(card(account, rows), encoding="utf-8")
    files = sorted(x for x in a.out.rglob("*") if x.is_file())
    meta = {"version": VERSION, "repo": REPO, "built": datetime.date.today().isoformat(), "code": commit, "licence": "CC BY 4.0",
            "model": account["model"], "calls": account["calls"], "rows": {ed: len(r) for ed, r in rows.items()},
            "files": {str(x.relative_to(a.out)): sha256(x) for x in files}}
    (a.out / "build.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    files = sorted(x for x in a.out.rglob("*") if x.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(x)}  {x.relative_to(a.out)}\n" for x in files), encoding="utf-8")
    print(f"{a.out}: " + ", ".join(f"{ed} {len(r):,}" for ed, r in rows.items()) + f"; code {commit}")
    return 0


def card(acc: dict, rows: dict) -> str:
    f = acc["anchors"]["figures"]

    def fig(key):
        x = f[key]
        return f"{x['right'] / x['n']:.1%} | {x['sure'] / x['n']:.1%} | {x['sure_right'] / max(x['sure'], 1):.1%}"

    def per_stem(prefix):
        out = []
        for st in ("qal", "niphal", "piel", "hiphil", "hithpael", "pual", "hophal"):
            x = f.get(f"{prefix}|{st}")
            if x:
                out.append(f"{st} {x['right'] / x['n']:.0%} of {x['n']}")
        return ", ".join(out)

    ed_rows = "\n".join(
        f"| `{ed}` | {len(r):,} | {sum(1 for x in r if x['sureness'] == 'sure' and x['stem']):,} | {sum(1 for x in r if x['sureness'] == 'unsure'):,} | "
        f"{sum(1 for x in r if x['sureness'] == 'two'):,} | {sum(1 for x in r if not x['stem']):,} |" for ed, r in rows.items())
    return f"""---
license: cc-by-4.0
language: [he, hbo]
pretty_name: Verb stems of the Hebrew New Testaments, read by a model
tags: [bible, hebrew, new-testament, morphology, verbs, model-generated]
configs:
- config_name: heb_scg
  data_files: heb_scg/stems.parquet
- config_name: heb_mod
  data_files: heb_mod/stems.parquet
---

# Verb stems of the Hebrew New Testaments, read by a model ({VERSION})

**Every value here was read by a language model ({acc['model']}). No person checked it.**

[bcv-commons/hebrew-nt-analysis](https://huggingface.co/datasets/bcv-commons/hebrew-nt-analysis) gives a verb its stem
(binyan) only where its keys decide one, and leaves the others empty. This table holds a model's reading of the stem for
a part of those words: the verbs that are the predicate of a clause with a subject or an object whose frame label
([bcv-commons/hebrew-verb-frame-labels](https://huggingface.co/datasets/bcv-commons/hebrew-verb-frame-labels)) could not
be looked up for want of a stem. It is kept apart from the analysis so that a value resting on it can say so.

| Edition | Words read | Sure, with a stem | Unsure | Two readings | Read as no verb form |
|---|---|---|---|---|---|
{ed_rows}

`heb_scg` is the Salkinson-Ginsburg Hebrew New Testament (pointed), `heb_mod` Delitzsch's (as that edition's source
writes it, without points). Both texts are public domain.

## The table (`<edition>/stems.parquet`)

| Column | What |
|---|---|
| `word` | the word's id: `scg:` or `del:` and eleven digits (book 40 to 66, chapter, verse, the word's position `i` in hebrew-nt-analysis `words.parquet` plus one) |
| `written` | the word as the edition writes it |
| `lexeme` | the word table's lexeme (`hbo:` + Strong's key), empty where it has none |
| `stem` | the stem read, one of MACULA Hebrew's stem names; empty where the model read the word as no verb form |
| `sureness` | `sure`, `unsure`, or `two` (the written form allows two stems; the other is in `other_stem`) |
| `other_stem` | the second stem of a `two` reading |
| `read` | `form` (read once for the written form with its lexeme, in its first place) or `token` (read in this place) |
| `model` | the model's id |

## How it was read

The model saw the verb as written, the lemma where the word table has a lexeme, and the words around it in its verse, in
Hebrew only: no gloss and no translation. It answered with a stem name and how sure it was. A form was read in the first
place it stands; a form read as `two`, and every repeated form of the edition without points, was read again in each
further place, since the same letters are often two stems there. {acc['calls']} calls, effort `{acc['effort']}`.

## How right it is

Two measures were taken before any reading was used.

| Measure | Right | Called sure | Right where sure |
|---|---|---|---|
| Tanakh verbs with MACULA's stem hidden, pointed (600) | {fig('a1|pointed|all')} |
| the same words with the points stripped (600) | {fig('a1|plain|all')} |
| `heb_scg` verbs whose stem hebrew-nt-analysis gives, hidden (400) | {fig('a2|heb_scg|all')} |
| `heb_mod` verbs whose stem hebrew-nt-analysis gives, hidden (400) | {fig('a2|heb_mod|all')} |

- The Tanakh samples hold more of the rarer stems than running text does. The model may know the Tanakh's text, so those
  two figures are an upper bound.
- The second pair compares with another automatic reading, not with a checked one. In `heb_mod`, per stem:
  {per_stem('a2|heb_mod')}. Some of the disagreements there are faults of the other reading.
- The words read here are the ones the keys of hebrew-nt-analysis could not decide, so they are likely harder than the
  words of the second measure.
- Use `sure` readings where a wrong stem costs something; in the edition without points expect roughly one in fifteen of
  them to differ from the analysis's own kind of reading.

## Known faults

- The `lexeme` is the word table's, and where its tagger chose it the lexeme is sometimes another verb's.
- Words read as no verb form ({sum(1 for r in rows.values() for x in r if not x['stem']):,}) are words the word table calls a verb; that fault is the word table's.

## Sources and licence

- The words, lexemes and the stems compared with: {ANALYSIS_PIN} (CC BY 4.0), on public-domain texts.
- Stem names and the Tanakh sample: MACULA Hebrew (Clear Bible, CC BY 4.0).
- The readings: {acc['model']} (Anthropic), run by bcv-commons.

This dataset: CC BY 4.0. Built by `macula/verb_stems_model.py` and `macula/release_verb_stems_model.py` of
[bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query).
"""


if __name__ == "__main__":
    raise SystemExit(main())
