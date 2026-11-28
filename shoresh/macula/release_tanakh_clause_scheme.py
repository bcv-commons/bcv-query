"""Package the dataset bcv-commons/tanakh-clause-scheme: the clause level of the Tanakh in the clause scheme, the form the
Hebrew New Testaments have in bcv-commons/hebrew-nt-analysis (its `scheme/` folders). Nothing is uploaded.

    cd shoresh && .venv/bin/python3 -m macula.release_tanakh_clause_scheme --out DIR [--no-rebuild] [--allow-dirty]

Rebuilds the tables (`clause_scheme.tanakh_export`, from the Tanakh build k1/hbo and the clause layout) unless --no-rebuild,
and writes DIR/data/{clauses,segments,constituents,added,orders,source_groups}.parquet, clause-scheme.toml,
validate_scheme.py, ACCOUNT.json, PIN.json, README.md, build.json, SHA256SUMS.

Ids. The build writes a word as `o` + MACULA's eleven digits (book, chapter, verse, word); the release writes the id
standard's `wlc:` + the same digits, in every column the scheme file calls a word or a part (a part: the word id, a dot,
the part's number). Clause ids (`cl:hbo:…`) and MACULA's own clause ids (`source_clause`) stay as built. The packaged tables
must pass validate_scheme.py, every word and part must be one of the Tanakh build's words, and no value may come from a
model (the build keeps values that rest on the Septuagint's automatic parse apart, and the scheme does not take them).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from macula import clause_scheme as CS
from macula import release_guard  # refuses TBTA and private inputs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
VERSION = "v0.2"
REPO = "bcv-commons/tanakh-clause-scheme"
SRC = CS.SCHEME_OUT / "tanakh"
SCHEME_FILE = CS.SCHEME_OUT / "clause-scheme.toml"
TABLES = ("clauses", "segments", "constituents", "added", "orders", "source_groups")
K1_READ = ("clauses.parquet", "constituents.parquet", "added.parquet", "orders.parquet", "pieces.parquet", "words.parquet",
           "categories.toml", "sources.json")
WORD = re.compile(r"^o(\d{11})(\.\d+)?$")


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def renamed(v):
    m = WORD.match(v)
    if not m:
        raise SystemExit(f"a word or part id of another shape: {v}")
    return f"wlc:{m.group(1)}{m.group(2) or ''}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--no-rebuild", action="store_true")
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "shoresh/macula"], cwd=ROOT, text=True).strip()
    if dirty and not a.allow_dirty:
        raise SystemExit(f"uncommitted changes in shoresh/macula:\n{dirty}")
    commit = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=ROOT, text=True).strip() + ("+uncommitted" if dirty else "")
    k1 = CS.K1 / "hbo"
    src = json.loads((k1 / "sources.json").read_text(encoding="utf-8"))
    moved = [f for f, v in src["builder"]["files"].items() if not (ROOT / f).exists() or sha256(ROOT / f) != v["sha256"]]
    if moved and not a.allow_dirty:
        raise SystemExit(f"the Tanakh build was made by other code than the repository has now: {moved[:5]}")
    if not a.no_rebuild:
        with contextlib.redirect_stdout(io.StringIO()):
            CS.tanakh_export()
    scheme = tomllib.loads(SCHEME_FILE.read_text(encoding="utf-8"))
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "data").mkdir()
    shutil.copy(SCHEME_FILE, a.out / "clause-scheme.toml")
    shutil.copy(HERE / "validate_scheme.py", a.out / "validate_scheme.py")
    shutil.copy(SRC / "ACCOUNT.json", a.out / "ACCOUNT.json")
    words = {f"wlc:{w[1:]}" for w in pq.read_table(k1 / "words.parquet", columns=["id"]).column(0).to_pylist()}
    aramaic = {f"wlc:{w[1:]}" for w in pq.read_table(CS.K1 / "arc" / "words.parquet", columns=["id"]).column(0).to_pylist()}
    beyond = 0
    counts, rows = {}, {}
    for t in TABLES:
        tab = pq.read_table(SRC / f"{t}.parquet")
        for col, spec in scheme["tables"][t]["columns"].items():
            if spec.get("kind") not in ("word", "part"):
                continue
            vals = tab.column(col).to_pylist()
            new = [None if v is None else [renamed(x) for x in v] if isinstance(v, list) else renamed(v) for v in vals]
            flat = {x.split(".")[0] for v in new if v for x in (v if isinstance(v, list) else [v])}
            if not flat <= (words | aramaic if spec["kind"] == "part" else words):      # an antecedent may be an Aramaic word
                raise SystemExit(f"{t}.{col}: {len(flat - words):,} ids that are no word of the Tanakh build")
            beyond += sum(1 for v in new if v for x in (v if isinstance(v, list) else [v]) if x.split(".")[0] in aramaic)
            tab = tab.set_column(tab.schema.get_field_index(col), col, pa.array(new, type=tab.schema.field(col).type))
        for col in tab.schema.names:
            if col.endswith("_basis") and "model" in set(tab.column(col).to_pylist()):
                raise SystemExit(f"{t}.{col}: a value of a model; this dataset is to hold none")
        pq.write_table(tab, a.out / "data" / f"{t}.parquet")
        counts[t] = tab.num_rows
        rows[t] = tab
    check = subprocess.run([sys.executable, "-I", str(a.out / "validate_scheme.py"), str(a.out / "clause-scheme.toml"), str(a.out / "data")],
                           capture_output=True, text=True)
    if check.returncode:
        raise SystemExit(f"the packaged tables do not pass validate_scheme.py:\n{check.stdout[-2000:]}{check.stderr[-2000:]}")
    cl = rows["clauses"].to_pylist()
    marks = {m: sum(1 for r in cl if r[m] not in (None, [])) for m in CS.SCHEME_MARKS}
    groups = {}
    for r in rows["source_groups"].column("kind").to_pylist():
        groups[r] = groups.get(r, 0) + 1
    account = json.loads((SRC / "ACCOUNT.json").read_text(encoding="utf-8"))
    layout = tomllib.loads((HERE / "clause_layout.toml").read_text(encoding="utf-8"))
    pin = {"tanakh_build": {"format": src["specification"]["version"], "built_by": src["builder"]["commit"][:7],
                            "files": {f: sha256(k1 / f) for f in K1_READ}},
           "macula_hebrew": layout["sources"]["macula_hebrew"]["commit"], "clause_layout_rules": layout["version"],
           "scheme": scheme["version"], "not_read": src["not_read"]}
    (a.out / "PIN.json").write_text(json.dumps(pin, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n = {**counts, "joined": counts["segments"] - counts["clauses"], "marks": marks, "groups": groups, "account": account,
         "no_source": sum(1 for r in cl if not r["source_clause"]),
         "who": sum(1 for v in rows["added"].column("who").to_pylist() if v), "aramaic_antecedents": beyond,
         "added_role": sum(1 for v in rows["added"].column("role").to_pylist() if v)}
    (a.out / "README.md").write_text(card(n, scheme["version"], pin), encoding="utf-8")
    files = sorted(x for x in a.out.rglob("*") if x.is_file())
    meta = {"version": VERSION, "repo": REPO, "built": datetime.date.today().isoformat(), "code": commit, "licence": "CC BY-SA 4.0",
            "scheme": scheme["version"], "counts": {k: v for k, v in n.items() if k != "account"}, "account": account,
            "validation": "PASS", "files": {str(x.relative_to(a.out)): sha256(x) for x in files}}
    (a.out / "build.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    files = sorted(x for x in a.out.rglob("*") if x.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(x)}  {x.relative_to(a.out)}\n" for x in files), encoding="utf-8")
    print(f"{a.out}: " + ", ".join(f"{t} {counts[t]:,}" for t in TABLES) + f"; code {commit}")
    return 0


def card(n: dict, scheme_version: str, pin: dict) -> str:
    m, g = n["marks"], n["groups"]
    filled = ", ".join(f"`{k}` {v:,}" for k, v in m.items())
    return f"""---
license: cc-by-sa-4.0
language: [hbo]
pretty_name: The Tanakh in the clause scheme
tags: [bible, hebrew, tanakh, syntax, clauses, constituents, translation]
configs:
- config_name: clauses
  default: true
  data_files: data/clauses.parquet
- config_name: segments
  data_files: data/segments.parquet
- config_name: constituents
  data_files: data/constituents.parquet
- config_name: added
  data_files: data/added.parquet
- config_name: orders
  data_files: data/orders.parquet
- config_name: source_groups
  data_files: data/source_groups.parquet
---
# The Tanakh in the clause scheme ({VERSION})

Every Hebrew clause of the Tanakh with its constituents, its marks and its unsaid arguments, in one form: the **clause scheme**
(version {scheme_version}). The two Hebrew New Testaments of
[bcv-commons/hebrew-nt-analysis](https://huggingface.co/datasets/bcv-commons/hebrew-nt-analysis) have the same tables in their
`scheme/` folders, so one reader, one check and one comparison serve both. There the values come from taggers; **here they
come from MACULA Hebrew's own analysis and from layers derived from it by rule. No value in this dataset is a model's.**

No Hebrew text is carried: words are ids of MACULA Hebrew. No English: meaning categories are Hebrew terms, the rest are codes.

| Table | Rows | One row per |
|---|---|---|
| `clauses` | {n['clauses']:,} | clause: parent, rule, pattern, predicate, 17 marks, the MACULA clause it stands for |
| `segments` | {n['segments']:,} | piece of a clause in one verse ({n['joined']:,} are a later piece of a clause an inserted clause breaks) |
| `constituents` | {n['constituents']:,} | constituent of a clause: role, head, first and last word, class, preposition, frame label, semantic role, reference status |
| `added` | {n['added']:,} | unsaid argument of a verb: who does it, said in another clause or nowhere |
| `orders` | {n['orders']:,} | order statement: a relation between two word classes, how often the dependent stands before and after |
| `source_groups` | {n['source_groups']:,} | MACULA clause that is no clause here (see *The anchor*) |

`clause-scheme.toml` is the whole definition: every table, column, kind of column, value set and join.
`python validate_scheme.py clause-scheme.toml data` checks the tables against it (needs pyarrow only).

## Ids

- **A word** is `wlc:` and MACULA Hebrew's eleven digits: book (two), chapter (three), verse (three), word (three), in the
  Hebrew versification. MACULA's own id of a part of that word is `o`, these digits and one part digit. **A part** here is the
  word id, a dot, and the part's number from 1.
- **A clause** is `cl:hbo:<BOOK>.<chapter>.<verse>.<seg>`: `seg` is the number, within the verse, of the clause's first segment
  in the clause layout ([bcv-commons/hebrew-clause-layout](https://huggingface.co/datasets/bcv-commons/hebrew-clause-layout),
  rules {pin['clause_layout_rules']}).
- **A MACULA clause** (`source_clause`, and the keys of `source_groups`) is `cl:<MACULA's id of the clause's first part>:<the
  number of its parts>`, with `:<n>` added where two clauses share both.
- **An entity** (`added.who`) is a kind and a code (`person:e…`): the code is `e` and ten hex digits of the SHA-1 of the entity's
  id in ACAI, as in bcv-commons/reference-status and bcv-commons/addressees.
- **A lexeme** (`prep`, `negator`, `connective`) is `lex:hbo:<lemma>:<Strong's number as MACULA has it>`.

## The clause and the anchor

A clause of the scheme begins with the word that opens it (a conjunction, a relative word, a preposition before a clause). That
cut is the clause layout's, derived from MACULA by rule, and it is the cut the New Testament's tagger learned. MACULA's tree
cuts a little differently: it gives the opening word to the clause around, and it has clauses that only group others.

**MACULA stays the anchor.** `clauses.source_clause` names the MACULA clause a clause here stands for ({n['clauses'] - n['no_source']:,}
clauses; {n['no_source']:,} have none: one-word segments, words MACULA puts in no clause). `source_groups` has one row for
each MACULA clause that is no clause here: `group` ({g.get('group', 0):,}; it owns no word and holds other clauses, coordination
and the like), `opener` ({g.get('opener', 0):,}; it owns only the opening word; `holds` is what that word governs), `inside`
({g.get('inside', 0):,}; a clause of MACULA that the layout does not cut out; `in_clauses` is the clause around it). The account
closes and is in `ACCOUNT.json`: every MACULA clause is a clause's source or a row of `source_groups`, never both, and every
word is in exactly one clause.

## The columns

Every value that is not a key has its basis beside it in `<column>_basis`: `given` (MACULA's own) or `derived` (by a rule of
ours from MACULA and our layers). `<column>_p` is empty throughout (it holds a tagger's probability on the New Testament).

**Changes in v0.2.** The scheme file is version 0.4: the frame label has a basis, so `constituents` and `added` gain
`frame_role_basis` (`given` here: MACULA's own label) and `frame_role_p` (empty). Nothing else changed, value for value.
The Hebrew New Testaments of bcv-commons/hebrew-nt-analysis carry a frame label from its v0.11, looked up in these labels
([bcv-commons/hebrew-verb-frame-labels](https://huggingface.co/datasets/bcv-commons/hebrew-verb-frame-labels)); there the basis says how.

- **`clauses`**: `parent`, `depth` (MACULA's tree); `rule` (MACULA's clause rule) and `pattern` (the roles in order, where the
  rule is a list of roles); `pred`, the predicate's word, and `pred_kind` (`v`, `p` a nominal predicate, `none`);
  `source_clause`; and the marks. How many clauses have each: {filled}.
- **`constituents`**: the clause's direct parts in order (`ord`): `role` (`v`, `s`, `o`, `o2`, `p`, `pp`, `adv`: MACULA's role
  attribute), `head`, `first`, `last`, `class`, `prep`, `frame_role` (MACULA's frame label of the argument: `A0`, `A1`, `AA`,
  `A2`; `frame_role_basis` is `given` wherever there is one), `sem_role` (a Hebrew term, from bcv-commons/argument-roles), `ref_status` and `ref_form` (first mention or mentioned
  before, and by a noun, a pronoun or a suffix, from bcv-commons/reference-status).
- **`added`**: a verb's argument that its clause does not say: `verb`, `role` (`s` where the grammatical role is known:
  {n['added_role']:,} rows), `frame_role`, `kind` (inside the verb's form, or said in another clause), `where`, `form`,
  `person`, `number`, `gender`, `antecedent` (the part that names it), `who` ({n['who']:,} rows) with `who_reason`.
- **`orders`**: for each relation of MACULA's tree between two word classes, how often the dependent stands before and after its
  head, how many places go against the commoner order, and up to three places.

## Where each column comes from, and its licence

| Columns | Source | Licence |
|---|---|---|
| ids; `parent`, `depth`, `rule`, `pattern`, `pred`, `pred_kind`, `source_clause`; `constituents` (role, head, span, class, `prep`, `frame_role`); `orders`; `source_groups` | [MACULA Hebrew](https://github.com/Clear-Bible/macula-hebrew) (Clear Bible / Biblica), `WLC/lowfat` and `WLC/nodes`, commit `{pin['macula_hebrew'][:7]}` | CC BY 4.0 |
| the cut: `segments`, the clause ids, `continues` | bcv-commons/hebrew-clause-layout (rules derived from MACULA) | CC BY 4.0 for these fields |
| `kind`, `force`, `voice`, `transitivity`, `subject_form`, `subject_switch`, `fronted`, `neg_scope` | bcv-commons/clause-columns | CC BY-SA 4.0 |
| `polarity`, `negator`, `mood` | bcv-commons/clause-extras | CC BY-SA 4.0 |
| `connective`, `relation` | bcv-commons/clause-connectives | CC BY-SA 4.0 |
| `time`, `time_abs`, `aspect`, `line_kind` | bcv-commons/time-aspect | CC BY-SA 4.0 |
| `sem_role` | bcv-commons/argument-roles (MACULA's frames read with the UBS dictionaries' senses) | CC BY-SA 4.0 |
| `ref_status`, `ref_form` | bcv-commons/reference-status | CC BY-SA 4.0 |
| `added` | MACULA's subject references and frames, read with the layers above | CC BY-SA 4.0 |
| `added.who` | [ACAI](https://github.com/Clear-Bible/ACAI) entities (Clear Bible), as codes | CC BY-SA 4.0 |
| **This dataset as a whole** | bcv-commons | **CC BY-SA 4.0** |
| `clause-scheme.toml`, `validate_scheme.py` | bcv-commons | MIT |

Not read, here or in any layer beneath: the ETCBC's BHSA and anything derived from it; TBTA; English glosses or translations as
values. `PIN.json` names the Tanakh build this was packaged from (format {pin['tanakh_build']['format']}, built by bcv-query
`{pin['tanakh_build']['built_by']}`) with the SHA-256 of each file read.

## What is not here, and known faults

- **The Aramaic parts are not in this version** (Daniel 2:4b-7:28, Ezra 4:8-6:18 and 7:12-26, Jeremiah 10:11, two words of
  Genesis 31:47; 4,828 words). {n['aramaic_antecedents']:,} antecedents in `added` name an Aramaic word, which no table here has.
- **Values that would rest on a model are left empty.** In 3,659 clauses the time-aspect layer reads the Septuagint verb's
  automatic parse for `time`, `time_abs`, `aspect` or `mood`; the scheme does not take those values.
- `pattern` is filled only where MACULA's rule is a list of roles.
- 235 small clauses of MACULA (`source_groups.kind` = `inside`, mostly one verb after `כַּאֲשֶׁר` or `עַד`) are not clauses here;
  their 345 constituents are not in `constituents`. So are the 630 constituents of `group` and `opener` rows.
- 732 segments are not one run of words (`first_w`, `last_w` give the outer words).
- About 10,000 rows of `added` are an argument said in another clause that has a frame label and no grammatical `role` yet.
- Unsaid objects and possessors as such are not made.
- A preposition before an infinitive or before `אֲשֶׁר` counts as a fronted `pp` (`fronted`), as in clause-columns.
- The rules behind the derived layers were measured on their own cards; nothing here was checked by a person clause by clause.

## Attribution

> The Tanakh in the clause scheme ({VERSION}), bcv-commons, CC BY-SA 4.0. Built on MACULA Hebrew, Clear Bible / Biblica
> (CC BY 4.0), ACAI, Clear Bible (CC BY-SA 4.0), and the UBS dictionaries' senses through bcv-commons/argument-roles.

Issues and requests: [bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query/issues).
"""


if __name__ == "__main__":
    raise SystemExit(main())
