"""Package two small source layers that held in research's track D measurement, each as its own HF dataset:

    cd shoresh && .venv/bin/python3 -m macula.release_small connectives --out DIR [--allow-dirty]
    cd shoresh && .venv/bin/python3 -m macula.release_small noun-relations --out DIR [--allow-dirty]
    cd shoresh && .venv/bin/python3 -m macula.release_small time-aspect --out DIR [--allow-dirty]
    cd shoresh && .venv/bin/python3 -m macula.release_small clause-extras --out DIR [--allow-dirty]

connectives     bcv-commons/clause-connectives v0.1 (macula/build_connectives.py): the opening connective and the kind of link of
                every layout clause
noun-relations  bcv-commons/noun-relations v0.1 (macula/build_noun_relations.py): the relation in every Hebrew construct /
                suffix and Greek genitive pair
Rebuilds the layer, checks clause keys against the pinned layouts where the table has them, writes DIR/data/{hebrew,greek-nt}.parquet,
checks.md, README.md, build.json, SHA256SUMS. Nothing is uploaded.
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

from macula import build_connectives as C
from macula import build_noun_relations as R
from macula import build_time_aspect as T
from macula import build_clause_extras as X
from macula import release_guard  # refuses TBTA and private inputs
from macula.release_clause_columns import LAYOUTS, layout_keys

ROOT = Path(__file__).resolve().parents[2]
VERSION = "v0.1"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


CONN_CARD = """---
license: cc-by-sa-4.0
language: [hbo, arc, grc]
pretty_name: Clause connectives of the Hebrew Bible and the Greek New Testament
tags: [bible, hebrew, greek, connectives, discourse, translation]
configs:
- config_name: hebrew
  data_files: data/hebrew.parquet
- config_name: greek-nt
  data_files: data/greek-nt.parquet
---

# Clause connectives ({v})

Every clause of the bcv-commons clause layouts ({nh:,} Hebrew, {ng:,} Greek) with the connective that opens it and the kind of link it
makes, for translations that must choose "then", "but", "because", "now" or nothing where Hebrew writes וְ for almost all of them.

| column | description |
|---|---|
| `clause_key` | the clause (as in bcv-commons/clause-columns) |
| `conn` | the opening connective lemma(s) (Hebrew among the first three words, Greek the first four, plus the connective the Greek layout moves to the clause) |
| `link` | sequence (Hebrew wayyiqtol, וְ + weqatal), disjunctive (וְ + a fronted constituent), circumstantial (וְ + a verbless clause), episode (וַיְהִי / וְהָיָה + setting), and_now (וְעַתָּה), look (הִנֵּה, ἰδού), coordination, development (δέ, οὖν, τότε), contrast, reason, content, purpose, condition, time, result, relative, comparison, asyndetic |
| `relation` | the layout's own relation, as is |
| `line` | the clause-columns `line` (main / background / setting / speech / non-narrative) |

{counts}

## Measured use

A rule-based drafting engine learned one target word per `link` from Tanakh training text and placed it at the clause's opening
word; tested on the Tanakh in six rotating test groups:

| | connectives right (governed verses) | word F1 of the draft | chrF3 |
|---|---|---|---|
| Tagalog | 0.074 → 0.385 | +2.50 | +0.73 |

In Indonesian and Swahili the drafts already write a connective for nearly every וְ, and adding one by `link` did not help; one
learned word per link is too coarse there (only Indonesian *sekarang* for `and_now` was right more than half the time).

## Licence

CC BY-SA 4.0. Built from MACULA Hebrew and Greek (CC BY 4.0) and the bcv-commons clause layouts (Hebrew CC BY-SA 4.0, Greek CC BY
4.0). Credit: MACULA (Clear Bible / Biblica), make-tanakh-research (the measurements), and this dataset.
"""

NR_CARD = """---
license: cc-by-sa-4.0
language: [hbo, arc, grc]
pretty_name: Noun-to-noun relations in the Hebrew Bible and the Greek New Testament
tags: [bible, hebrew, greek, genitive, construct, possession, translation]
configs:
- config_name: hebrew
  data_files: data/hebrew.parquet
- config_name: greek-nt
  data_files: data/greek-nt.parquet
---

# Noun-to-noun relations ({v})

"The son of Jesse", "the hand of Moses", "the king of Babylon", "an altar of gold", "all the kingdoms", "the mountain of holiness":
Hebrew and Greek join two nouns the same way for all of these, and many languages do not. This dataset gives each pair its relation:
{nh:,} Hebrew pairs (construct + noun, pronominal suffix on a noun) and {ng:,} Greek (a genitive under a noun).

| column | description |
|---|---|
| `head`, `dependent` | MACULA word ids (Hebrew 12 digits, Greek 11) |
| `form` | construct, suffix, genitive |
| `relation` | quantity, kin, part, member, ruler, name, material, measure, origin, time, agent, event_other, attribute, possessor, other |
| `animacy` | the dependent's: person, deity, animal, place, thing, or empty |

Relations are by rule from the UBS domains (SDBH, Louw-Nida), ACAI entity types and short word lists. `agent` (an event noun with
a personal dependent: "the word of the LORD") does not separate subjective from objective genitives ("the fear of the LORD"). The
edges are noisy: sampled pairs look right for kin, ruler, name, part, material and quantity, and mixed for agent, other and Greek
measure. Nothing was checked by hand.

{counts}

## Measured use

A rule-based drafting engine choosing the target's associative marker by (`relation`, `animacy`), tested on the Tanakh in six
rotating test groups:

| | linkers right | precision of the added | word F1 of the draft |
|---|---|---|---|
| Swahili (-a of association with class agreement) | +8.9 points (+13.7 in governed verses) | 0.62 | +0.76 |

In Tagalog the engine's lexicon already carries *ng* / *ni* right 0.73 of the time and the learned marker lost more than it wrote
(word F1 −0.64); in Indonesian it made no difference.

## Licence

CC BY-SA 4.0 (UBS domains, ACAI). Built from MACULA Hebrew and Greek (CC BY 4.0), the UBS dictionaries' domains (CC BY-SA 4.0), ACAI
Biblical Entity Data (CC BY-SA 4.0) and bcv-commons/reference-status. Credit: MACULA (Clear Bible / Biblica), United Bible Societies,
ACAI (BibleAquifer), make-tanakh-research (the measurements), and this dataset.
"""

TA_CARD = """---
license: cc-by-sa-4.0
language: [hbo, arc, grc]
pretty_name: Time, aspect and salience band per clause, Hebrew Bible and Greek New Testament
tags: [bible, hebrew, greek, tense, aspect, discourse, translation]
configs:
- config_name: hebrew
  data_files: data/hebrew.parquet
- config_name: greek-nt
  data_files: data/greek-nt.parquet
---

# Time, aspect and band ({v})

Every clause of the bcv-commons clause layouts ({nh:,} Hebrew, {ng:,} Greek) with its time, aspect and salience band, under one
policy: absolute time for main clauses (discourse time in narration), relative time
(anterior / simultaneous / posterior) in relative, complement, purpose and temporal clauses and for participles and infinitives,
irrealis for commands and wishes, timeless for law, wisdom and poetry outside speech.

| column | description |
|---|---|
| `clause_key` | the clause (as in bcv-commons/clause-columns) |
| `band` | main, background, setting, speech, non-narrative (clause-columns `line`) |
| `time` | past, present, future, timeless, anterior, simultaneous, posterior, irrealis |
| `aspect` | perfective, imperfective, progressive, resultative, stative |
| `basis` | the rule: `<corpus>:<verb form>:<context>`; `...:lxx` where the Septuagint's verb form decided (modal, present or past yiqtol in speech) |
| `lxx`, `agree` | Hebrew only: the time the Septuagint's verb form gives, and whether it agrees (a check, empty on rows it decided) |

Rules from the Hebrew verb form and its context (wayyiqtol, qatal with the Septuagint's future as the prophetic perfect, yiqtol,
weqatal by its chain, participle, הִנֵּה + participle as imminent, verbless clauses), and from the Greek tense-form and mood (the
present indicative in narration as a historical present). Where the rule alone decides, it agrees with the Septuagint's verb form in
0.92 of the comparable Hebrew clauses.

{counts}

## Measured use

In a rule-based drafting engine tested on the Tanakh in six rotating test groups: with a Tagalog focus x aspect analyser, verb form
exact +4.8 points at the verbs the key changed; as features of a Swahili verb-slot builder (with the argument roles, clause extras and
connectives), verb exact +2.2 points. Choosing Indonesian *sudah / sedang / akan* or the Swahili tense prefix from `time` / `aspect`
alone did not help.

## Licence

CC BY-SA 4.0. Built from MACULA Hebrew and Greek (CC BY 4.0), GLAUx Septuagint (CC BY-SA 4.0), bcv-commons/clause-columns and the
clause layouts. Credit: MACULA (Clear Bible / Biblica), GLAUx (KU Leuven), make-tanakh-research (the measurements), and this dataset.
"""

EX_CARD = """---
license: cc-by-sa-4.0
language: [hbo, arc, grc]
pretty_name: Polarity, mood, reflexivity and degree, Hebrew Bible and Greek New Testament
tags: [bible, hebrew, greek, negation, mood, reflexive, comparison, translation]
configs:
- config_name: hebrew
  data_files: data/hebrew.parquet
- config_name: greek-nt
  data_files: data/greek-nt.parquet
---

# Clause extras ({v})

Small clause values, by rule: every clause of the bcv-commons clause layouts ({nh:,} Hebrew, {ng:,} Greek).

| column | description |
|---|---|
| `clause_key` | the clause (as in bcv-commons/clause-columns) |
| `polarity`, `neg_word` | negative / affirmative, and the negator's code (clause-columns `neg`) |
| `mood` | declarative, interrogative, directive, conditional, irrealis |
| `reflexive`, `reflexive_basis` | reflexive (Greek reflexive pronoun; Hebrew hithpael / hithpolel without an object, a candidate) or reciprocal (ἀλλήλων) |

{counts}

Degree words (intensifier, comparative, superlative) are built too but not part of this release.

## Measured use

As features of a Swahili verb-slot builder (with the argument roles, time / aspect and connectives) in a rule-based drafting engine:
verb exact +2.2 points together. As a drafting feature of its own (inserting reflexive, intensifier, comparative or conditional
words) it made no difference: these are rare, and the engine already writes most of them.

## Licence

CC BY-SA 4.0. Built from MACULA Hebrew and Greek (CC BY 4.0), bcv-commons/clause-columns and the clause layouts. Credit: MACULA
(Clear Bible / Biblica), make-tanakh-research (the measurements), and this dataset.
"""

LAYERS = {
    "time-aspect": {"repo": "bcv-commons/time-aspect", "build": T, "file": "clauses.tsv", "card": TA_CARD, "keyed": True,
                    "count_col": "time"},
    "clause-extras": {"repo": "bcv-commons/clause-extras", "build": X, "file": "clauses.tsv", "card": EX_CARD, "keyed": True,
                      "count_col": "mood"},
    "connectives": {"repo": "bcv-commons/clause-connectives", "build": C, "file": "clauses.tsv", "card": CONN_CARD, "keyed": True,
                    "count_col": "link"},
    "noun-relations": {"repo": "bcv-commons/noun-relations", "build": R, "file": "pairs.tsv", "card": NR_CARD, "keyed": False,
                       "count_col": "relation"},
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("layer", choices=sorted(LAYERS))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    L = LAYERS[a.layer]
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "shoresh/macula"], cwd=ROOT, text=True).strip()
    if dirty and not a.allow_dirty:
        raise SystemExit(f"uncommitted changes in shoresh/macula:\n{dirty}")
    commit = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=ROOT, text=True).strip() + ("+uncommitted" if dirty else "")
    with contextlib.redirect_stdout(io.StringIO()):
        L["build"].main()
    rows = list(csv.DictReader(open(L["build"].OUT / L["file"], encoding="utf-8"), delimiter="\t"))
    if L["keyed"]:
        keys = {"hbo": layout_keys(LAYOUTS["hebrew"]), "grc": layout_keys(LAYOUTS["greek-nt"])}
        missing = {c: sum(1 for r in rows if r["corpus"] == c and r["clause_key"] not in keys[c]) for c in ("hbo", "grc")}
        if any(missing.values()):
            raise SystemExit(f"clause keys not in the pinned layouts: {missing}")
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "data").mkdir()
    cols = [c for c in rows[0] if c != "corpus"]
    n, tally = {}, {}
    for corpus, name in (("hbo", "hebrew"), ("grc", "greek-nt")):
        sub = [r for r in rows if r["corpus"] == corpus]
        pq.write_table(pa.table({c: pa.array([r[c] for r in sub], type=pa.string()) for c in cols}), a.out / f"data/{name}.parquet")
        n[name] = len(sub)
        t = {}
        for r in sub:
            t[r[L["count_col"]]] = t.get(r[L["count_col"]], 0) + 1
        tally[name] = t
    vals = sorted(set(tally["hebrew"]) | set(tally["greek-nt"]), key=lambda v: -(tally["hebrew"].get(v, 0) + tally["greek-nt"].get(v, 0)))
    counts = f"| `{L['count_col']}` | Hebrew | Greek |\n|---|---|---|\n" + "\n".join(
        f"| {v} | {tally['hebrew'].get(v, 0):,} | {tally['greek-nt'].get(v, 0):,} |" for v in vals)
    (a.out / "checks.md").write_text((L["build"].OUT / "checks.md").read_text(encoding="utf-8"), encoding="utf-8")
    (a.out / "README.md").write_text(L["card"].format(v=VERSION, nh=n["hebrew"], ng=n["greek-nt"], counts=counts), encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    meta = {"schema": 1, "version": VERSION, "repo": L["repo"], "built": datetime.date.today().isoformat(), "code": commit,
            "licence": "CC BY-SA 4.0", "rows": n,
            "layouts": {c: {"repo": v["repo"], "version": v["version"], "revision": v["revision"]} for c, v in LAYOUTS.items()},
            "not_read": ["BHSA", "TBTA", "English text"], "files": {str(p.relative_to(a.out)): sha256(p) for p in files}}
    (a.out / "build.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(a.out)}\n" for p in files), encoding="utf-8")
    print(f"{L['repo']} -> {a.out}: hebrew {n['hebrew']:,}, greek-nt {n['greek-nt']:,}; code {commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
