"""Package bcv-commons/argument-roles: every constituent of every clause of the two clause layouts with its grammatical relation,
voice, frame macrorole and semantic role (macula/build_arg_roles.py; wave 1c, released after research's track D measurement).

    cd shoresh && .venv/bin/python3 -m macula.release_argument_roles --out DIR [--allow-dirty]

Rebuilds macula/data/arg-roles first (it reads clause-columns and word-senses-ubs as built locally), checks the clause keys
against bcv-commons/clause-columns v1.0's layouts, and writes DIR/data/{hebrew,greek-nt}.parquet, checks.md, README.md,
build.json and SHA256SUMS. Nothing is uploaded.
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

from macula import build_arg_roles as B
from macula import release_guard  # refuses TBTA and private inputs
from macula.release_clause_columns import LAYOUTS, layout_keys

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 1
VERSION = "v0.1"
REPO = "bcv-commons/argument-roles"


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
    rows = list(csv.DictReader(open(B.OUT / "roles.tsv", encoding="utf-8"), delimiter="\t"))
    assert rows and list(rows[0]) == B.COLS, list(rows[0])
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "data").mkdir()
    counts = {}
    cols = [c for c in B.COLS if c != "corpus"]
    for name, corpus in (("hebrew", "hbo"), ("greek-nt", "grc")):
        sel = [r for r in rows if r["corpus"] == corpus]
        keys = {r["clause_key"] for r in sel}
        extra = keys - layout_keys(LAYOUTS[name])
        assert not extra, f"{name}: {len(extra)} clause keys not in {LAYOUTS[name]['version']}"
        drop = {"case", "prep_ln"} if corpus == "hbo" else {"prep_lxx", "lxx_case"}
        c_ = [c for c in cols if c not in drop]
        pq.write_table(pa.table({c: pa.array([r[c] for r in sel], type=pa.string()) for c in c_}), a.out / "data" / f"{name}.parquet")
        counts[name] = {"rows": len(sel), "clauses": len(keys), "with_role": sum(1 for r in sel if r["role"]),
                        "prep": sum(1 for r in sel if r["prep"]), "prep_with_role": sum(1 for r in sel if r["prep"] and r["role"])}
    shutil.copyfile(B.OUT / "checks.md", a.out / "checks.md")
    (a.out / "README.md").write_text(card(counts), encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    meta = {"schema": SCHEMA, "version": VERSION, "built": datetime.date.today().isoformat(), "code": code, "licence": "CC BY-SA 4.0",
            "layouts": {n: {k: v for k, v in l.items() if k not in ("local", "glob")} for n, l in LAYOUTS.items()},
            "inputs": {"clause-columns": "bcv-commons/clause-columns v1.0 (verb, voice)", "word-senses": "bcv-commons/word-senses v0.1",
                       "lxx": "GLAUx Septuagint parses (CC BY-SA 4.0), spine-releases lxx-glaux-2026-10-10",
                       "macula": "MACULA Hebrew and Greek trees, frames, Septuagint alignment column (CC BY 4.0)"},
            "not_read": ["BHSA", "TBTA", "English text as evidence"], "counts": counts,
            "files": {str(p.relative_to(a.out)): sha256(p) for p in files}}
    (a.out / "build.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(a.out)}\n" for p in files), encoding="utf-8")
    print(f"{a.out}: " + ", ".join(f"{n} {c['rows']:,} rows" for n, c in counts.items()) + f"; code {code}")
    return 0


def card(c: dict) -> str:
    h, g = LAYOUTS["hebrew"], LAYOUTS["greek-nt"]
    hp, gp = c["hebrew"], c["greek-nt"]
    return f"""---
license: cc-by-sa-4.0
language: [hbo, arc, grc]
pretty_name: Argument roles for the Hebrew and Greek clause layouts
tags: [bible, hebrew, greek, semantic-roles, rrg, prepositions, louw-nida, septuagint]
configs:
- config_name: hebrew
  data_files: data/hebrew.parquet
- config_name: greek-nt
  data_files: data/greek-nt.parquet
---

# Argument roles ({VERSION})

Every constituent of every clause of the two bcv-commons clause layouts, with its grammatical relation, the clause's voice, the verb
frame's macrorole and a semantic role: actor, undergoer, recipient, addressee, goal, source, location, time, accompaniment,
instrument, means, beneficiary, agent and others. These are what a translation into another language needs to choose case markers,
prepositions and voice.

| config | layout (pinned) | constituents | with a role | preposition phrases with a role |
|---|---|---|---|---|
| `hebrew` | [{h['repo']}](https://huggingface.co/datasets/{h['repo']}) {h['version']} (`{h['revision'][:8]}`) | {hp['rows']:,} | {hp['with_role']:,} | {hp['prep_with_role']:,} of {hp['prep']:,} |
| `greek-nt` | [{g['repo']}](https://huggingface.co/datasets/{g['repo']}) {g['version']} (`{g['revision'][:8]}`) | {gp['rows']:,} | {gp['with_role']:,} | {gp['prep_with_role']:,} of {gp['prep']:,} |

Join a row to its clause by `clause_key`: the Hebrew layout's `clause_key`, the Greek layout's `first`, as in
[bcv-commons/clause-columns](https://huggingface.co/datasets/bcv-commons/clause-columns).

## Columns

| column | in | description |
|---|---|---|
| `clause_key` | both | the layout clause |
| `words` | both | the constituent's word ids inside the clause, in text order, space-joined |
| `head` | both | its first noun, pronoun, adjective or number word; empty when none |
| `relation` | both | the constituent's role in MACULA's tree: s, o, o2, io, p, adv, pp |
| `verb`, `voice` | both | the clause's main verb and voice (clause-columns) |
| `macrorole` | both | the verb frame's label for the constituent (MACULA frames: A0, A1, A2, AA); empty when the frame does not list it |
| `case` | greek-nt | the head's case |
| `prep`, `prep_lemma` | both | the preposition heading the constituent |
| `prep_ln` | greek-nt | the Louw-Nida subdomain of that preposition's sense here (bcv-commons/word-senses) |
| `prep_lxx` | hebrew | the Septuagint word MACULA aligns to the Hebrew preposition |
| `lxx_case` | hebrew | the case of the Septuagint word aligned to the phrase's first noun (GLAUx) |
| `role` | both | the semantic role; empty where the evidence does not decide |
| `role_basis` | both | which rule gave it (below) |

## How the roles are assigned

- **frame / frame_passive:** the verb frame's A0 is the actor, A1 the undergoer (frame_passive: the passive subject), A2 kept as A2.
- **ln (Greek):** the Louw-Nida subdomain of the preposition's sense names the role. For example, 90.A agent, 90.B instrument,
  84.A source, 84.B goal, 83 location, 67 time, 89.H purpose, 34 accompaniment. With a verb of speaking (Louw-Nida 33), an
  experiencer or goal is the addressee (`ln_speech`, `+speech`).
- **Hebrew preposition phrases,** in this order:
  - `lxx_nt_domain`: the Septuagint's preposition, the case of its noun, and the Louw-Nida domain that noun's lemma has in the
    New Testament. These are read through the New Testament's own (preposition, case, domain) → role table, with at least 8
    examples and 60% agreement.
  - `lxx_nt`: the same without the domain (at least 20 examples, 60%).
  - `lxx_dative`: לְ that the Septuagint gives as a bare dative is the recipient.
  - `hebrew_prep`: כְּ is a comparison (`standard`).
  - `hebrew_domain`: the Hebrew preposition with its noun's SDBH domain, learned from the rows above.
  - `+speech`: a goal with אֶל, לְ or עַל after a verb of speaking (אָמַר, דָּבַר, קָרָא, צָוָה, עָנָה ...) is the addressee.

Nothing comes from BHSA or TBTA, and no English text is used as evidence. No row was checked by hand; a human review of samples is
planned and will be reported here.

## Measured use

A rule-based drafting engine was tested on the Tanakh in six rotating test groups, each drafted by an engine that had not seen it.
The figure is the share of right choices where the role changed the engine's choice:

| use | Indonesian | Swahili | Tagalog |
|---|---|---|---|
| prepositions chosen by Hebrew preposition and role | +7.4 | +16.2 | +5.4 |
| Tagalog case markers (ang / ng) by actor and undergoer | | | +3.6 |

Word-level F1 of the whole draft against the published translation rises by +0.46 (Indonesian) and +0.85 (Swahili) from the
prepositions alone. The Tagalog figure (+0.20) also includes kay / sa chosen by role and by whether the noun refers to a person.

The Greek side has not been measured in drafting yet.

## Licence

CC BY-SA 4.0: the Hebrew layout's clause keys, the UBS senses and the GLAUx parses are CC BY-SA 4.0. Credit: MACULA (Clear Bible /
Biblica), United Bible Societies (word senses), GLAUx (KU Leuven, Alek Keersmaekers), make-tanakh-research (the measurements), and
this dataset.
"""


if __name__ == "__main__":
    raise SystemExit(main())
