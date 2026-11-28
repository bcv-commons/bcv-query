"""Package bcv-commons/hebrew-nt-probe-sets: grammar probes on the Hebrew New Testaments, in a compact form
(macula/probe_sets.py, macula/probe_labels.py, macula/probe_changes.toml, macula/probe_dimensions.toml).

    cd shoresh && .venv/bin/python3 -m macula.release_probe_sets --out DIR [--no-rebuild] [--allow-dirty]

Rebuilds the labels, the pairs and the made probes (with the layer model's read-back), then writes DIR/<edition>/
{pairs,probes,changes,clauses}.parquet and CHECKS.json, DIR/<edition>/labels/{kinds,frames,we,we_without,plural_size,relatives}.parquet,
DIR/PIN.json, the two catalogue files, resolve.py, README.md, build.json and SHA256SUMS. Before it writes the hashes
it runs resolve.py --check on what it packed. No Hebrew text and no translation is in the package. Nothing is uploaded.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq

from macula import hebrew_nt_clauses as N
from macula import probe_labels as PL
from macula import probe_relatives as PR
from macula import probe_sets as PS
from macula import release_guard  # refuses TBTA and private inputs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCHEMA = 1
VERSION = "v0.2"
REPO = "bcv-commons/hebrew-nt-probe-sets"
LABELS = ("kinds", "frames", "we", "we_without", "plural_size", "relatives")      # the Greek side (`*_source`) stays here


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--no-rebuild", action="store_true")
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "shoresh/macula"], cwd=ROOT, text=True).strip()
    if dirty and not a.allow_dirty:
        raise SystemExit(f"uncommitted changes in shoresh/macula:\n{dirty}")
    code = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=ROOT, text=True).strip() + ("+uncommitted" if dirty else "")
    eds = list(PS.EDITIONS)
    if not a.no_rebuild:
        PL.build(eds)
        PR.build(eds)
        PS.build_pairs(eds)
        PS.build_changes(eds, True)
    a.out.mkdir(parents=True, exist_ok=False)
    counts = {}
    for ed in eds:
        (a.out / ed / "labels").mkdir(parents=True)
        for f in ("pairs.parquet", "probes.parquet", "changes.parquet", "clauses.parquet", "CHECKS.json"):
            shutil.copyfile(PS.OUT / ed / f, a.out / ed / f)
        for f in LABELS:
            shutil.copyfile(PL.OUT / ed / f"{f}.parquet", a.out / ed / "labels" / f"{f}.parquet")
        probes = pq.read_table(a.out / ed / "probes.parquet", columns=["default", "read_ok", "clause_above"]).to_pylist()
        counts[ed] = {"pairs": pq.read_metadata(a.out / ed / "pairs.parquet").num_rows, "probes": len(probes),
                      "changes": pq.read_metadata(a.out / ed / "changes.parquet").num_rows,
                      "clauses": pq.read_metadata(a.out / ed / "clauses.parquet").num_rows,
                      "default": sum(1 for r in probes if r["default"]),
                      "unit_probes": sum(1 for r in probes if r["clause_above"]),
                      "unit_default": sum(1 for r in probes if r["clause_above"] and r["default"]),
                      "read": sum(1 for r in probes if r["default"] and r["read_ok"] is not None),
                      "read_as_meant": sum(1 for r in probes if r["default"] and r["read_ok"])}
    shutil.copyfile(PS.OUT / "PIN.json", a.out / "PIN.json")
    shutil.copyfile(HERE / "probe_changes.toml", a.out / "probe_changes.toml")
    shutil.copyfile(HERE / "probe_dimensions.toml", a.out / "probe_dimensions.toml")
    shutil.copyfile(HERE / "probe_resolve.py", a.out / "resolve.py")
    for ed in eds:                                                   # the package against the text, by its own resolver
        r = subprocess.run([sys.executable, "-I", str(a.out / "resolve.py"), str(N.ANALYSIS / ed / "words.parquet"), str(a.out / ed), "--check"],
                           capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"{ed}: the package does not resolve against the word table: {r.stdout}{r.stderr}")
        counts[ed]["resolve_check"] = r.stdout.strip()
    (a.out / "README.md").write_text(card(counts), encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    meta = {"schema": SCHEMA, "version": VERSION, "built": datetime.date.today().isoformat(), "code": code,
            "licence": "CC BY-SA 4.0", "pin": json.loads((a.out / "PIN.json").read_text(encoding="utf-8")),
            "stores_hebrew_text": False, "stores_translation_text": False, "not_read": ["BHSA", "TBTA", "any translation"],
            "counts": counts, "files": {str(p.relative_to(a.out)): sha256(p) for p in files}}
    (a.out / "build.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(a.out)}\n" for p in files), encoding="utf-8")
    print(f"{a.out}: {json.dumps(counts, ensure_ascii=False)}; code {code}")
    return 0


def card(c: dict) -> str:
    s, m = c["heb_scg"], c["heb_mod"]
    configs = "".join(f"- config_name: {t}_{ed}\n  data_files: {ed}/{t}.parquet\n" for ed in ("heb_scg", "heb_mod")
                      for t in ("pairs", "probes", "changes", "clauses"))
    return f"""---
license: cc-by-sa-4.0
language: [he]
pretty_name: Grammar probes on the Hebrew New Testaments
tags: [bible, hebrew, new-testament, grammar, probes, translation]
configs:
{configs}---

# Grammar probes on the Hebrew New Testaments ({VERSION})

Short Hebrew clauses with one thing changed, to ask a translation model how a target language marks that thing. A
model that translates from Hebrew is given a clause and the same clause with one change (the subject in the plural,
`לֹא` added, a person where a thing stood); where its two answers differ is a hypothesis about the target language's
grammar. The clauses are those of two Hebrew New Testaments: Salkinson-Ginsburg (`heb_scg`, pointed) and Delitzsch
(`heb_mod`, read without points).

**The set holds no Hebrew text.** A probe is a place in the text and one named change. A clause is its id with its
first and last word; a changed word is a pointer to a real word of the same edition that has the wanted form (a
donor). The text is made from the word table of
[bcv-commons/hebrew-nt-analysis](https://huggingface.co/datasets/bcv-commons/hebrew-nt-analysis) (v0.8,
`<edition>/words.parquet`; `PIN.json` has its SHA-256) with `resolve.py`, which stands alone:

```
python resolve.py heb_scg/words.parquet heb_scg --check                 # every clause against its hash
python resolve.py heb_scg/words.parquet heb_scg pr:heb_scg:000042 --plain
```

| | `heb_scg` | `heb_mod` |
|---|---|---|
| real pairs | {s['pairs']:,} | {m['pairs']:,} |
| made probes | {s['probes']:,} | {m['probes']:,} |
| changes of the catalogue that have probes | {s['changes']:,} | {m['changes']:,} |
| probes marked `default` | {s['default']:,} | {m['default']:,} |
| of these, read back by the layer model | {s['read']:,} | {m['read']:,} |
| read back as meant | {s['read_as_meant']:,} | {m['read_as_meant']:,} |
| probes on a noun with its relative clause | {s['unit_probes']:,} | {m['unit_probes']:,} |
| of these, in the default spread | {s['unit_default']:,} | {m['unit_default']:,} |
| clauses named | {s['clauses']:,} | {m['clauses']:,} |

Nothing here was made from a translation: the set is the same for every target language. What is not the same for
every language is which changes matter; see "Limits".

## Ids

- clause `cl:<edition>:<BOOK>.<chapter>.<verse>.<segment>` (the clause scheme's id);
- word `scg:` (Salkinson-Ginsburg) or `del:` (Delitzsch) + book number (2 digits, `PIN.json` `books`), chapter (3),
  verse (3), word (3); the word is the row of the word table with `i` = word - 1;
- word part `<word id>.<part>`, the part counted from 1 (the word table's `part` + 1);
- pair `pp:<edition>:<n>`, probe `pr:<edition>:<n>`. The numbers hold within one version only.

## Tables (per edition)

**`pairs`**: two real clauses that differ in one thing.

| column | |
|---|---|
| `pair`, `a`, `b` | the pair's id and the two clauses |
| `carrier` | `clause`: the two clauses alone show the change; `verse`: the words are the same, the setting differs, and the model must be given the verses |
| `dimension`, `from`, `to` | the change, in the names of `probe_dimensions.toml` (`subject_number`, `polarity`, `swap_noun`, ...; of the setting: `hearer_kind`, `we`, `plural_size`); the value in `a` and in `b` |
| `a_at`, `b_at` | the word parts that differ |
| `with` | what goes with the change (a form that has no gender, the marks a negator brings) |
| `marks_differ` | clause marks the tagger reads differently beside the change (its reading of the time, the order's name): listed, not counted as a second change |
| `bearer`, `from_kind`, `to_kind` | for a swapped word: what it bears in the clause, and a noun's or verb's kind in each clause (Hebrew head words, see `labels/kinds`) |
| `found_by` | `same_words` (another form), `swap`, `small_word`, `constituent` (one more), `same_words_other_setting` |
| `moves` | which of the seventeen target features of the first experiment the change can move (a hint, not a limit) |
| `sure` | the lowest sureness among the constituents of both clauses and the marks the change is named by |
| `known_words` | every word of both clauses is a form the Tanakh has (its lexeme and form are that form's, not a model's guess) |
| `plain_differs` | the two texts differ without points |
| `a_check`, `b_check` | the first 8 hex digits of the SHA-256 of each clause's text |

**`probes`**: a place with one change made by code.

| column | |
|---|---|
| `probe`, `clause` | the probe's id and the place |
| `clause_above` | for a probe on a noun with its relative clause: the clause the noun stands in. The place is then that clause followed by `clause` (the relative clause); `at` is the noun |
| `family`, `change` | the family of `probe_changes.toml` and the change (`subject_person:3>1`, `swap_object_noun:>אָדָם`, `add_negator`) |
| `dimension`, `from`, `to`, `moves` | as in `pairs` |
| `at` | the word part the change is about |
| `edit_op`, `edit_at`, `edit_from` | the edits, in order: `put` (the donor `edit_from` stands where the word `edit_at` stood), `add_before`, `add_after`, `drop`, `move_before` |
| `sure`, `known_words`, `plain_differs` | as in `pairs`, of the place and the made clause |
| `made_one` | the difference function reads the made clause against the place and names this one change (only for `put`) |
| `read_moved`, `read_role`, `read_ok` | the read-back (default probes only): the clause marks the layer model reads differently in the changed verse, whether a replaced word keeps its relations in the tree, and whether both are as the change allows |
| `with` | what comes with the change: `conjunction:added` or `conjunction:dropped` (a change of tense to or from `וַיֹּאמֶר`, `וְאָמַר`, forms written with the conjunction), `agrees:verb` or `agrees:pronoun` (the word of the relative clause that takes the noun's new number) |
| `default` | in the default spread: at most 30 per change, sureness 0.9 and more, all words known, one change, different without points, one per word first |
| `check`, `made_check` | hash of the place's text and of the made clause's |

**`changes`**: the catalogue as built: `change`, `family`, `dimension`, `how`, `moves`, and the counts `probes`,
`sure_probes`, `default_probes`, `read_as_meant`, `words` (different words changed).

**`clauses`**: every clause named: `clause`, `book`, `chapter`, `verse`, `first`, `last` (word ids), `words`, `check`,
`check_plain`, `sure`, `same_text` (short clauses with this very text), and the setting: `frame` (quotation | letter
| none), `hearer_kind`, `hearer_number`, `we` (i | e, where the clause's first person plural has one value).

**`labels/`**, keyed like hebrew-nt-analysis (`book`, `chapter`, `verse`, `i`, `part`) or by clause: `kinds` (a noun's
or verb's kind as a Hebrew head word: `אָדָם`, `מִשְׁפָּחָה`, `עַם`, `אֱלֹוהַּ`, `גּוּף`, `חַיָּה`, `צֶמַח`, `מַאֲכָל`, `כְּלִי`, `בִּנְיָן`,
`מָקוֹם`, `חֹמֶר`, `עִנְיָן`; verbs `אֲמִירָה`, `תְּנוּעָה`, `הֲוָיָה`; `kind_basis` `linked`: read off the Greek word at the
place through word links, `entity`, `entity_lexeme`), `frames` (per clause: quotation, letter or none, speakers and
hearers as coded ids, the hearers' kind and number), `we` (the value of
[bcv-commons/inclusive-we](https://huggingface.co/datasets/bcv-commons/inclusive-we) on the Hebrew word), `we_without`
(the value without one voting edition, where it differs: a language must not be tested on its own vote),
`plural_size` (how many a plural covers where the text says it: few rows), `relatives` (a relative clause with the
noun it hangs on: `rel_clause`, `above_clause`, `head` and its class, number, gender, definiteness and role above;
`rel_role`, what the noun is inside the relative clause: `s` subject, `o` object, `pp` after a preposition, `poss`
owner, `place` taken up by `שָׁם`, `adv` a day or place with nothing taking it up, `other`; `rel_role_basis`
nominal | antecedent | agreement | resumed | gap | none; `rel_also`, a second reading the text allows; `rel_resumed`,
the pronoun that takes the noun up; `sure`, the tree's sureness of the link; `short`, both clauses of 6 words or fewer).

## Changes from v0.1

- New: probes on a noun with its relative clause (families `rel_head_swap`, `rel_head_number`, `rel_drop`; column
  `clause_above`), and the label table `relatives`.
- A change of tense to or from a form written with the conjunction takes or leaves the conjunction (column `with`):
  17 changes of tense that were short of probes are now 8.
- Pair and probe numbers are new: they hold within one version only.

## How it was made

Real pairs: short clauses (2 to 6 words, one segment) are compared where they share their words, all words but
one, or all but a small word or one constituent; a difference function names what differs, and a pair is kept when
the words differ in one thing. Made probes: for each family of `probe_changes.toml`, every place that can take the
change, and for the changed word a donor of the same word shape (the same prefixes and suffixes, the same lexeme
for a change of form, another noun of a wanted kind for a swap). The changed word and the donor must be forms the
Tanakh has. A form the edition never writes gives no probe: a translation model trained on this text has not seen
such a form, and its answer would not tell a misread word from the target language's grammar.

A noun with its relative clause: units where both clauses are short, the relative clause follows the clause above in
its verse, the tree's link has sureness 0.8 and more, the noun's role inside the clause has one reading, and the noun
is one common noun alone in its constituent. The noun is swapped for a noun of another kind and the same gender; its
number is changed together with the one word of the relative clause that agrees with it (the verb where the noun is
the subject, the pronoun that takes it up otherwise; not where something in the clause above agrees with the noun);
or the relative clause is dropped. The link to the noun is right in 97% from sureness 0.9 on the Tanakh's test
chapters; the role inside the clause has no yardstick (a reading of samples by the building agent: about 9 in 10
among units with one reading).

The clauses, their constituents and marks, and the sureness are those of the clause scheme on
bcv-commons/hebrew-nt-analysis: read by a tagger and a layer model trained on the Tanakh (encoder
`dicta-il/dictabert`), not by hand. The read-back uses the same layer model. **No value here has been checked by
hand.** No BHSA, no TBTA and no translation was read.

## Limits

- The catalogue starts from seventeen target features of a first experiment (agreement, noun class, object marking,
  tense, negation, order, definiteness, possession, purpose, number). A language that marks other things needs
  other changes. Not covered: a change of stem (only among the real pairs), how many a plural covers and inclusive
  "we" beyond the labels, repeated action. A noun with its relative clause is covered thinly: few places allow a
  change of number.
- A swapped noun keeps the grammar and not the sense (a thing may speak). A changed gender or person leaves a
  pronoun elsewhere in the clause as it was.
- A noun's kind is read off the Greek word at one place and is wrong at times; a donor noun must have its kind in
  most of its places.
- A donor comes from another context: in the pointed text a point that depends on the neighbour can be off. The
  text without points is not touched by this.
- The layer model does not read about one default probe in seven as meant (`read_ok` false): most often a swapped
  subject it no longer reads as the subject, and changes of tense. The rows stay, marked.
- On the Tanakh's test chapters, keeping clauses of sureness 0.9 and more leaves 70% of the short clauses, with
  every constituent right in 93% of them; in the New Testaments the true figure is lower and cannot be measured.

## Sources and licence

CC BY-SA 4.0. Built on bcv-commons/hebrew-nt-analysis (the Hebrew New Testaments are in the public domain; MACULA
Hebrew, CC BY 4.0), the kinds through MACULA Greek and the UBS lexicon's domains (CC BY-SA 4.0) and
lexeme-aligner's word links, the "we" label from bcv-commons/inclusive-we (CC BY-SA 4.0).
"""


if __name__ == "__main__":
    raise SystemExit(main())
