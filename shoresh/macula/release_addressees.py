"""Package bcv-commons/addressees: who each quotation of the Hebrew Bible and the Greek NT is said to, how that was found, and the
speaker-to-hearer relation (macula/build_addressees.py; wave 3).

    cd shoresh && .venv/bin/python3 -m macula.release_addressees --out DIR [--src BUILD] [--allow-dirty]

Rebuilds the table in place (or, with --src, packages a build made elsewhere with build_addressees --out) and replaces ACAI's entity ids (English names) with the same neutral codes bcv-commons/reference-status uses
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
VERSION = "v0.4"
REPO = "bcv-commons/addressees"
ENTITY_COLS = {"speaker", "addressee", "second_person", "member_of_plural"}
INTS = {"spoke", "addressed", "father", "mother", "partners", "children"}


def c(v: str) -> str:
    return code(v) if v else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--src", type=Path, help="package this build (build_addressees --out DIR); without it the layer is built in place first")
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "shoresh/macula"], cwd=ROOT, text=True).strip()
    if dirty and not a.allow_dirty:
        raise SystemExit(f"uncommitted changes in shoresh/macula:\n{dirty}")
    commit = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=ROOT, text=True).strip() + ("+uncommitted" if dirty else "")
    src = a.src or B.OUT
    if not a.src:
        with contextlib.redirect_stdout(io.StringIO()):
            B.main([])
    q = list(csv.DictReader(open(src / "quotations.tsv", encoding="utf-8"), delimiter="\t"))
    p = list(csv.DictReader(open(src / "persons.tsv", encoding="utf-8"), delimiter="\t"))
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
        counts[corpus] = {"quotations": len(sub), **{b: sum(r["basis"] == b for r in sub) for b in ("inquit", "second_person", "turn", "review")},
                          "none": sum(not r["basis"] for r in sub),
                          "agree": f"{sum(r['agree'] == '1' for r in sub) / max(1, sum(r['agree'] != '' for r in sub)):.2f}",
                          "relation": sum(bool(r["relation"]) for r in sub),
                          "number": sum(bool(r["number"]) for r in sub), "member_dropped": sum(bool(r["member_of_plural"]) for r in sub),
                          "inner": sum(bool(r["around"]) for r in sub), "inner_hearer": sum(bool(r["around"] and r["basis"]) for r in sub),
                          "inner_speaker": sum(bool(r["around"] and r["speaker"]) for r in sub),
                          "inner_number": sum(bool(r["around"] and r["number"]) for r in sub)}
    (a.out / "checks.md").write_text((src / "checks.md").read_text(encoding="utf-8"), encoding="utf-8")
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
| `basis` | `inquit`: the speech clause names the hearer (Hebrew אֶל / לְ / עַל or the object of צִוָּה; Greek a dative, πρός, or the object of asking verbs); `second_person`: the commonest entity the quotation's second-person words refer to; `turn`: a reply to the quotation before, which was said to this speaker; `review` (v0.3): a review row names the words of the text that name the hearer, where the rules went wrong; empty: not found |
| `addressee_words` | the inquit word naming the hearer (MACULA id) |
| `second_person` | the second-person check on its own, where it gives an entity |
| `agree` | 1 / 0: whether the inquit and the second-person check agree, where both give an entity |
| `plural` | 1 when the hearer is a group, the inquit word is plural, or `number` is plural |
| `number`, `number_basis` | the hearer's number (v0.2), strongest first: `second_person` (most of the quotation's second-person words, at least two of them and 2/3), `inquit_word` (the word that names the hearer), `entity` (a group plural, a person or deity singular); `review` (v0.3) with a review row; empty where none says |
| `member_of_plural` | v0.2: where the inquit's hearer is plural ("to them") but its entity lookup gave one person, that person; the hearer is then a group the second-person words point to, or the inquit word's lemma |
| `level`, `around` | v0.4: 1 for a quotation in the narrative, 2 and deeper for one inside another, and the `quote` of the quotation it stands in (empty at level 1). A quotation's second-person words are its own: those of a quotation inside it are not counted with it |
| `relation` | `parent_to_child`, `child_to_parent`, `spouse`, `sibling` (from ACAI's kinship), `divine_to_human`, `human_to_divine`, `to_group`, or empty |

## Changes in v0.4 (2026-11-28)

**Speech inside speech in the Greek New Testament.** The Greek speaker layer had one level only: a parable's people, a cited
psalm, an angel whose words Paul reports were all words of the outer speaker, said to the outer hearers. The Greek clause
layout (v0.8) now finds the quotations inside a quotation, from the Greek text with the translations' quotation depth as the
second witness (its card says how). Here each is a row of its own ({g['inner']:,} rows, `level` 2 or 3, `around` the quotation
it stands in), with its own speaker's entity where the layout names a character for it ({g['inner_speaker']:,}; the layout
gives the speaker's Greek words for more), and its own hearer where its inquit or its second-person words show one
({g['inner_hearer']:,}; a number for {g['inner_number']:,}). A cited scripture mostly has neither. The outer quotation's row no
longer counts the inner one's words: Peter's speech in Acts 2:14-36 is plural by its own words now, and the review row of v0.3
is kept only because it names the hearers. In the Hebrew Bible, where the speaker layer always had levels, no row changes;
`level` and `around` are filled there too.

**The Greek "you" counts pronouns.** The second-person rule counted verbs alone in Greek, since the word table gives a pronoun
no person: σου, ὑμῖν, ὑμᾶς were not seen. They are counted now (the pronoun σύ / ὑμεῖς, with its number). More Greek
quotations get a number and a hearer from their own words, and where the inquit and the second-person words both name an
entity they agree in {g['agree']} of the cases.

**Measured** against the second-person forms of two Hebrew New Testaments (bcv-commons/hebrew-nt-analysis; a form is the
edition's own, so it is a witness, not a key): the segments whose form goes against this layer's number fell from 308 of 3,181
to 180 of 3,477 (9.7% to 5.2%) in one edition and from 308 of 3,070 to 178 of 3,355 (10.0% to 5.3%) in the other. Of the 180
left, 106 follow a Greek "you" of that number in the same verse of the same quotation: the text's own change of number (a
generic singular in a speech to many, an apostrophe, a turn to one hearer). The rest were read in part only.

**Smaller mends.** A hearer named inside the quotation's own words is no longer taken from the inquit's clause; where a
quotation's first clause introduces the next one, each now takes its own inquit (Greek); five review rows (Mark 9:39, Luke
7:40, 18:41, 18:42, Acts 25:24) name the hearer where the rule gave one person for many or a group for one. Review rows are
made by a language model reading the Greek text and are not checked by a person; each names its words, so it can be checked.

## Changes in v0.3 (2026-11-28)

One quotation mended, by a review row (`basis` and `number_basis` = `review`; quotations with it: {g['review']:,}): Peter's speech in Acts 2:14-36 was
marked as said to God, since the singular "you" of the psalm he cites (2:27-28) is linked to the Lord and the plural "you" of
his hearers to nothing. The Greek text names the hearers at its opening (Ἄνδρες Ἰουδαῖοι καὶ οἱ κατοικοῦντες Ἱερουσαλὴμ
πάντες); the row names those words, and the hearer is the group, in the plural. It was the only quotation of the 33 said to God
that the Hebrew New Testaments' own second-person forms contradict throughout (21 plural forms). Review rows are made by a
language model reading the Greek text and are not checked by a person; each names its words, so it can be checked.
Every other row is as in v0.2.

## Changes in v0.2 (2026-11-26)

A check against the Swahili New Testament (make-tanakh-research) found the addressee's number wrong where the speech is to many.
Two rules made it: a plural hearer ("he said to them") was resolved to one of them (Andrew, James, Peter), and the second-person
rule counted words of every number, so a few singular "you"s linked to the Lord outvoted many plural ones linked to nothing
(Matthew 5, Acts 2, Acts 7). Now a plural hearer is never a single person or deity (`member_of_plural` keeps the lookup's
answer), the second-person rule counts only words of the quotation's own number, takes a group only for a plural, and names an
entity only where it has at least a third of the quotation's second-person words, and every quotation with a known hearer has a
`number`. Changed hearers: {g['member_dropped']:,} Greek and {h['member_dropped']:,} Hebrew plural hearers; the second-person rule
now names {g['second_person']:,} (Greek) and {h['second_person']:,} (Hebrew) hearers (v0.1: 144 and 825). Where the inquit also
names the hearer, the second-person rule agrees {g['agree']} (Greek) and {h['agree']} (Hebrew), against 0.96 and 0.92 in v0.1.
On the Hebrew New Testaments (bcv-commons/hebrew-nt-analysis v0.6) the hearer's number now agrees with the Hebrew's own
second-person forms in 0.90 of the segments where both are known, against 0.75.

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
