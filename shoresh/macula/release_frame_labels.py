"""Package the dataset bcv-commons/hebrew-verb-frame-labels: which of MACULA's frame labels the subject and the object of a
Hebrew verb carry in the Tanakh, per verb and per stem, with the lookup that reads it. Nothing is uploaded.

    cd shoresh && .venv/bin/python3 -m macula.release_frame_labels --out DIR [--scheme-release DIR] [--allow-dirty]

Rebuilds the table (macula/build_frame_labels.py, from the Tanakh in the clause scheme and MACULA's Hebrew words) and writes
DIR/data/frames.parquet, lookup.py, ACCOUNT.json, PIN.json, README.md, build.json, SHA256SUMS. With --scheme-release (a
folder of bcv-commons/tanakh-clause-scheme as published) the table is built a second time from the published tables and
must come out the same. The table holds no model value and no English (labels, stems and roles are codes; the lemma is
Hebrew); the packaged lookup is run on the packaged table.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pyarrow.parquet as pq

from macula import build_frame_labels as B
from macula import release_guard  # refuses TBTA and private inputs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
VERSION = "v0.1"
REPO = "bcv-commons/hebrew-verb-frame-labels"
SCHEME_PIN = {"repo": "bcv-commons/tanakh-clause-scheme", "version": "v0.1", "revision": "6f5fb2c750b48c6baf6f2d1e3784ff6b3bb116e3"}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--scheme-release", type=Path, help="a folder of the published tanakh-clause-scheme, to build from a second time")
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "shoresh/macula"], cwd=ROOT, text=True).strip()
    if dirty and not a.allow_dirty:
        raise SystemExit(f"uncommitted changes in shoresh/macula:\n{dirty}")
    commit = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=ROOT, text=True).strip() + ("+uncommitted" if dirty else "")
    rows, lemma, unlabelled = B.places()
    tab = B.table(rows, lemma)
    same = None
    if a.scheme_release:
        again = B.table(B.places(a.scheme_release / "data")[0], lemma)
        same = again == tab
        if not same:
            raise SystemExit("the table built from the published tanakh-clause-scheme is another one than the local build's")
    a.out.mkdir(parents=True, exist_ok=False)
    B.main_into(a.out / "data", rows, lemma, unlabelled, tab)
    shutil.move(a.out / "data" / "ACCOUNT.json", a.out / "ACCOUNT.json")
    (a.out / "data" / "report.md").rename(a.out / "report.md")
    shutil.copy(HERE / "frame_labels_lookup.py", a.out / "lookup.py")
    packed = pq.read_table(a.out / "data" / "frames.parquet").to_pylist()
    if any(not r["stem"] and r["step"] != "lexeme" for r in packed) or {r["label"] for r in packed} - set(B.LABELS):
        raise SystemExit("a row without a stem outside the lexeme step, or a label that is none of MACULA's")
    probe = next(r for r in packed if r["step"] == "verb" and r["settled"] and r["stem"] == "niphal")
    run = subprocess.run([sys.executable, "-I", str(a.out / "lookup.py"), str(a.out / "data" / "frames.parquet"), probe["lexeme"], "niphal", probe["role"]],
                         capture_output=True, text=True)
    if run.returncode or run.stdout.split()[:2] != [probe["label"], "verb"]:
        raise SystemExit(f"the packaged lookup does not read the packaged table: {run.stdout}{run.stderr[-800:]}")
    account = json.loads((a.out / "ACCOUNT.json").read_text(encoding="utf-8"))
    layout = tomllib.loads((HERE / "clause_layout.toml").read_text(encoding="utf-8"))
    pin = {"tanakh_clause_scheme": {**SCHEME_PIN, "built_from_the_published_tables_too": same},
           "macula_hebrew": layout["sources"]["macula_hebrew"]["commit"],
           "new_testament_counted_on": "bcv-commons/hebrew-nt-analysis v0.9 (scheme tables, stems of its features table)"}
    (a.out / "PIN.json").write_text(json.dumps(pin, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (a.out / "README.md").write_text(card(account, packed, pin), encoding="utf-8")
    files = sorted(x for x in a.out.rglob("*") if x.is_file())
    meta = {"version": VERSION, "repo": REPO, "built": datetime.date.today().isoformat(), "code": commit, "licence": "CC BY-SA 4.0",
            "rows": len(packed), "settled": sum(1 for r in packed if r["settled"]),
            "files": {str(x.relative_to(a.out)): sha256(x) for x in files}}
    (a.out / "build.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    files = sorted(x for x in a.out.rglob("*") if x.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(x)}  {x.relative_to(a.out)}\n" for x in files), encoding="utf-8")
    print(f"{a.out}: rows {len(packed):,}, settled {meta['settled']:,}; code {commit}")
    return 0


def card(acc: dict, rows: list[dict], pin: dict) -> str:
    cc = acc["cross_check"]["figures"]

    def f(key, what="right"):
        x = cc.get(key) or {"places": 0, "right": 0}
        return f"{x['right'] / x['places']:.1%}" if what == "right" and x["places"] else f"{x['places']:,}"

    def share(role, step, stem="all"):
        tot = cc[f"{role}|the stem's commonest label|{stem}"]["places"]
        return f"{(cc.get(f'{role}|{step}|{stem}') or {'places': 0})['places'] / tot:.1%}"

    stems = "\n".join(
        f"| {st} | {f(f's|the stem' + chr(39) + f's commonest label|{st}', 'n')} | {f(f's|the stem' + chr(39) + f's commonest label|{st}')} | {share('s', 'any step', st)} | {f(f's|any step|{st}')} |"
        for st in ("qal", "hiphil", "piel", "niphal", "hithpael", "hophal", "pual"))
    stem_rows = "\n".join(f"| {r['stem']} | {r['role']} | {r['object'] or '-'} | {r['label']} | {r['share']:.1%} | {r['n']:,} | {'yes' if r['settled'] else 'no'} |"
                          for r in acc["stem_rows"] if r["n"] >= 100)
    nt = []
    for ed, x in acc["new_testament"].items():
        s = {k.split("|", 1)[1]: v for k, v in x["by_step"].items() if k.startswith("s|")}
        got = sum(v for k, v in s.items() if not k.startswith("open"))
        nt.append(f"| `{ed}` | {x['subjects']:,} | {got / x['subjects']:.1%} | {s.get('open: no stem', 0) / x['subjects']:.1%} | "
                  f"{s.get('open: two labels in the Tanakh', 0) / x['subjects']:.1%} | "
                  f"{(s.get('open: no settled row', 0) + s.get('open: a verb the Tanakh does not have', 0)) / x['subjects']:.1%} |")
    by = acc["rows"]
    th = acc["thresholds"]
    hi = {r["object"]: r for r in acc["stem_rows"] if r["stem"] == "hiphil" and r["role"] == "s"}
    ni = [r for r in rows if r["step"] == "verb" and r["stem"] == "niphal" and r["role"] == "s" and r["n"] >= 5]
    ni_n = {k: sum(1 for r in ni if (r["label"] if r["settled"] else "both") == k) for k in ("A1", "A0", "both")}
    return f"""---
license: cc-by-sa-4.0
language: [hbo]
pretty_name: Frame labels of Hebrew verbs, from the Tanakh
tags: [bible, hebrew, tanakh, verbs, valency, semantic-roles, syntax]
configs:
- config_name: frames
  data_files: data/frames.parquet
---

# Frame labels of Hebrew verbs, counted in the Tanakh ({VERSION})

MACULA Hebrew labels a verb's arguments with frame labels (`A0`, `A1`, `AA`, `A2`). This table counts, over the Hebrew of
the Tanakh, which label the **subject** and the **object** of a verb carry: per verb (its lexeme with its stem) and per
stem. It is made so that a label can be given to a Hebrew text that has none, such as the Hebrew New Testaments of
[bcv-commons/hebrew-nt-analysis](https://huggingface.co/datasets/bcv-commons/hebrew-nt-analysis), from MACULA's own
practice and without a guess: where the Tanakh does not settle a label, the lookup returns none.

No model made any value here, and the table holds no English: labels, stems and roles are codes, the lemma is Hebrew.

## Why a table and not the stem

The stem alone does not give the label. A niphal's subject is `A1` for one verb (נִמְצָא) and `A0` for another (נִשְׁבַּע),
and a hiphil's is `AA` or `A0`. The stem's commonest label is right for {f("s|the stem's commonest label|niphal")} of the niphal's subjects and
{f("s|the stem's commonest label|hiphil")} of the hiphil's. Read per verb, the same places are right {f('s|any step|niphal')} and {f('s|any step|hiphil')} of the time where the
table settles them.

What the counts show of MACULA's practice:

- **qal, piel, hithpael**: the subject is `A0` and the object `A1`, nearly always.
- **hiphil**: the label follows the clause. With an object in the clause the subject is `AA` and the object `A0`
  ({hi['with']['share']:.1%} of {hi['with']['n']:,} subjects); without one the subject is `A0` in {hi['without']['share']:.1%} of {hi['without']['n']:,}. So one
  hiphil verb often has both labels, and the object decides.
- **niphal**: the label is the verb's. Of the {len(ni):,} niphal verbs with five places or more, {ni_n['A1']:,} are `A1`,
  {ni_n['A0']:,} are `A0` and {ni_n['both']:,} have both.
- **hophal, pual**: the subject is `A1`.

## Files

| File | What |
|---|---|
| `data/frames.parquet` | the table, {len(rows):,} rows, {sum(1 for r in rows if r['settled']):,} settled |
| `lookup.py` | the lookup (stands alone, pyarrow only) |
| `ACCOUNT.json` | counts, thresholds, the cross-check per step and stem, the count on the Hebrew New Testaments |
| `report.md` | the same as text |
| `PIN.json` | what the table was built from |

## The table

One row per step, key and role.

| Column | What |
|---|---|
| `step` | `verb`, `verb+object`, `stem+object` or `lexeme` (below) |
| `lexeme` | `hbo:` + MACULA's Strong's key, as in hebrew-nt-analysis; empty on a `stem+object` row |
| `lemma` | MACULA's lemma of the lexeme (its commonest spelling) |
| `stem` | MACULA's stem name; empty on a `lexeme` row |
| `role` | `s` the subject (said, or unsaid and carried by the verb), `o` an object |
| `object` | `with` / `without`: whether the clause has an object (subject rows of the two `+object` steps); else empty |
| `n`, `n_A0`, `n_A1`, `n_AA`, `n_A2` | the Tanakh's places with a label, and per label |
| `label`, `share` | the commonest label and its share of `n` |
| `settled` | `n` and `share` reach the step's thresholds |

Steps, in the order the lookup reads them. The first settled row gives the label.

| Step | Key | Settled from | Rows (subject / object) | Settled |
|---|---|---|---|---|
| `verb` | lexeme, stem | {th['min_places']['verb']} places, {th['min_share']['verb']:.0%} one label | {by['verb|s']['rows']:,} / {by['verb|o']['rows']:,} | {by['verb|s']['settled']:,} / {by['verb|o']['settled']:,} |
| `verb+object` | lexeme, stem, object in the clause | {th['min_places']['verb+object']} places, {th['min_share']['verb+object']:.0%} | {by['verb+object|s']['rows']:,} / - | {by['verb+object|s']['settled']:,} / - |
| `stem+object` | stem, object in the clause | {th['min_places']['stem+object']} places, {th['min_share']['stem+object']:.0%} | {by['stem+object|s']['rows']:,} / {by['stem+object|o']['rows']:,} | {by['stem+object|s']['settled']:,} / {by['stem+object|o']['settled']:,} |
| `lexeme` | lexeme over all its stems; read only for a word whose stem is not known | {th['min_places']['lexeme']} places, {th['min_share']['lexeme']:.0%} | {by['lexeme|s']['rows']:,} / {by['lexeme|o']['rows']:,} | {by['lexeme|s']['settled']:,} / {by['lexeme|o']['settled']:,} |

The `stem+object` step also covers a verb the Tanakh does not have, where its stem is one whose label does not hang on
the verb. The stem rows with a hundred places or more:

| Stem | Role | Object | Label | Share | Places | Settled |
|---|---|---|---|---|---|---|
{stem_rows}

```python
from lookup import Frames
F = Frames("data/frames.parquet")
F.label("hbo:4672", "niphal", "s", has_object=False)   # ('A1', 'verb', share)
F.label("hbo:7650", "niphal", "s", has_object=False)   # ('A0', 'verb', share)
F.label("", "hiphil", "s", has_object=True)            # ('AA', 'stem+object', share)
F.label("", "niphal", "s", has_object=False)           # (None, 'open: no settled row', None)
```

## How right it is

Cross-check inside the Tanakh: the chapters are split in ten parts, and each part is looked up in a table built from
the other nine. Places: {acc['places']['subjects']:,} subjects and {acc['places']['objects']:,} objects of Hebrew verbs that carry a label
in MACULA ({acc['places']['without_a_label_left_out'].get('s', 0):,} subjects and {acc['places']['without_a_label_left_out'].get('o', 0):,} objects without a label are left out).

| | Subjects | Objects |
|---|---|---|
| settled by a step | {share('s', 'any step')} | {share('o', 'any step')} |
| right where settled | {f('s|any step|all')} | {f('o|any step|all')} |
| step `verb`: share, right | {share('s', 'verb')}, {f('s|verb|all')} | {share('o', 'verb')}, {f('o|verb|all')} |
| step `verb+object`: share, right | {share('s', 'verb+object')}, {f('s|verb+object|all')} | - |
| step `stem+object`: share, right | {share('s', 'stem+object')}, {f('s|stem+object|all')} | {share('o', 'stem+object')}, {f('o|stem+object|all')} |
| open: the Tanakh has two labels | {share('s', 'open: two labels in the Tanakh')} | {share('o', 'open: two labels in the Tanakh')} |
| open: no settled row | {share('s', 'open: no settled row')} | {share('o', 'open: no settled row')} |
| with the stem hidden, step `lexeme`: share, right | {share('s', 'stem hidden: lexeme')}, {f('s|stem hidden: lexeme|all')} | {share('o', 'stem hidden: lexeme')}, {f('o|stem hidden: lexeme|all')} |

Subjects per stem:

| Stem | Places | The stem's commonest label right | Settled by a step | Right where settled |
|---|---|---|---|---|
{stems}

"Right" means the same label as MACULA's at that place. The cross-check reads MACULA's own roles for what is a
subject and an object. On a text whose roles come from a tagger, a wrong role gives a wrong key; that loss is not in
these figures.

## On the Hebrew New Testaments

Counted on the clause scheme of hebrew-nt-analysis v0.9 (subjects said and unsaid, with the stems of its features
table). The labels are not in that release; this is what the table would settle.

| Edition | Subjects | Settled | Open: no stem read | Open: two labels in the Tanakh | Open: other |
|---|---|---|---|---|---|
{chr(10).join(nt)}

The largest open part is not the table's: the stem of the verb is not read there (hebrew-nt-analysis leaves a stem
empty where its keys do not decide it).

## Limits

- The labels are MACULA's, and the table repeats its practice, the uneven parts too (the hiphil above).
- Hebrew only; the Aramaic of the Tanakh is not counted.
- A subject is the clause's subject constituent or the subject the verb form carries; an object is a constituent of
  role `o` or `o2`. Arguments with a preposition are not in the table.
- A place whose verb the Tanakh labels both ways stays open; the table gives the counts, not a choice.

## Sources and licence

- Frame labels, lexemes, lemmas, stems: [MACULA Hebrew](https://github.com/Clear-Bible/macula-hebrew) (Clear Bible,
  CC BY 4.0), commit `{pin['macula_hebrew'][:7]}`.
- Subjects, objects and unsaid subjects: [bcv-commons/tanakh-clause-scheme](https://huggingface.co/datasets/bcv-commons/tanakh-clause-scheme)
  {pin['tanakh_clause_scheme']['version']} (`{pin['tanakh_clause_scheme']['revision'][:8]}`, CC BY-SA 4.0).

This dataset: CC BY-SA 4.0. Built by `macula/build_frame_labels.py` and `macula/release_frame_labels.py` of
[bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query).
"""


if __name__ == "__main__":
    raise SystemExit(main())
