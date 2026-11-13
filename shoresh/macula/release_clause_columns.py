"""Package bcv-commons/clause-columns from our own build (macula/build_clause_columns.py), replacing make-tanakh-research's table
(revision 8a132e44) under the same repository and the same column names (agreed with research, packet 25).

    cd shoresh && .venv/bin/python3 -m macula.release_clause_columns --out DIR [--allow-dirty]

Reads macula/data/clause-columns/ (run the builder with --check first: the contract check must join at 1.0 both ways) and the
local copies of the two layouts' releases the table is keyed by. Nothing is uploaded. DIR gets data/hebrew.parquet,
data/greek-nt.parquet, checks.md (the contract check), README.md (the card), build.json and SHA256SUMS.
"""
from __future__ import annotations

import argparse
import datetime
import glob
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pyarrow.parquet as pq

from macula import release_guard  # refuses TBTA and private inputs

ROOT = Path(__file__).resolve().parents[2]
SRC = Path(__file__).resolve().parent / "data" / "clause-columns"
SCHEMA = 1
VERSION = "v1.0"
REPO = "bcv-commons/clause-columns"
RESEARCH_REV = "8a132e44224c83cdaa92fadd93cf440c58552354"
LAYOUTS = {
    "hebrew": {"repo": "bcv-commons/hebrew-clause-layout", "version": "v0.37.1", "revision": "32f89b719c0fc648320428c8492709c474c17ff2",
               "licence": "CC BY-SA 4.0", "key": "clause_key",
               "local": ROOT / "internal-docs/hebrew-clause-layout-release/v0.37.1/data", "glob": "clauses-*.parquet"},
    "greek-nt": {"repo": "bcv-commons/greek-nt-clause-layout", "version": "v0.7", "revision": "9168fac3bd26d7d0e4e63e3a5905199c2182905a",
                 "licence": "CC BY 4.0", "key": "first",
                 "local": ROOT / "internal-docs/greek-nt-clause-layout-release/v0.7/data", "glob": "clauses.parquet"},
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def layout_keys(lay: dict) -> set[str]:
    keys = set()
    for f in sorted(glob.glob(str(lay["local"] / lay["glob"]))):
        keys |= {k for k in pq.read_table(f, columns=[lay["key"]]).column(0).to_pylist() if k}
    return keys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--src", type=Path, default=SRC)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "shoresh/macula"], cwd=ROOT, text=True).strip()
    if dirty and not a.allow_dirty:
        raise SystemExit(f"uncommitted changes in shoresh/macula:\n{dirty}")
    code = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=ROOT, text=True).strip() + ("+uncommitted" if dirty else "")
    build = json.loads((a.src / "build.json").read_text(encoding="utf-8"))
    checks = (a.src / "checks.md").read_text(encoding="utf-8")
    contract = json.loads(checks.split("```json", 1)[1].split("```", 1)[0]) if "```json" in checks else {}
    # the table's keys must be the released layouts' keys, one row each
    counts = {}
    for name, lay in LAYOUTS.items():
        t = pq.read_table(a.src / f"{name}.parquet")
        keys = t.column("clause_key").to_pylist()
        assert len(keys) == len(set(keys)), f"{name}: duplicate clause keys"
        want = layout_keys(lay)
        assert want, f"{name}: no local copy of {lay['repo']} {lay['version']} at {lay['local']}"
        assert set(keys) == want, f"{name}: keys differ from {lay['version']}: {len(set(keys) - want)} extra, {len(want - set(keys))} missing"
        counts[name] = {"rows": t.num_rows, "columns": t.column_names}
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "data").mkdir()
    for name in LAYOUTS:
        shutil.copyfile(a.src / f"{name}.parquet", a.out / "data" / f"{name}.parquet")
    shutil.copyfile(a.src / "checks.md", a.out / "checks.md")
    (a.out / "README.md").write_text(card(build, counts), encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    meta = {"schema": SCHEMA, "version": VERSION, "built": datetime.date.today().isoformat(), "code": code,
            "builder": build.get("code"), "layouts": {n: {k: v for k, v in l.items() if k not in ("local", "glob")}
                                                      for n, l in LAYOUTS.items()},
            "sources": build.get("sources"), "licence": "CC BY-SA 4.0", "replaces": {"repo": REPO, "revision": RESEARCH_REV,
                                                                                      "built_by": "make-tanakh-research"},
            "contract_check": contract or "see checks.md", "not_read": build.get("not_read"), "counts": build.get("counts"),
            "files": {str(p.relative_to(a.out)): sha256(p) for p in files}}
    (a.out / "build.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(a.out)}\n" for p in files), encoding="utf-8")
    print(f"{a.out}: {', '.join(f'{n} {c['rows']:,}' for n, c in counts.items())} rows; code {code}")
    return 0


COLUMNS = [
    ("clause_key", "both", "the layout's clause key (Hebrew `clause_key`, one row per key: a clause the layout splits into several segments "
                           "is read whole; Greek: the segment's first word id, the layout's `first`)"),
    ("ref", "both", "BOOK c:v.seg of the clause's first segment"),
    ("verb", "both", "the main verb's word id (first finite verb; else participle / infinitive); null in a verbless clause"),
    ("conj", "both", "Hebrew: qatal | wayyiqtol | yiqtol | weqatal | imperative | jussive | cohortative | ptc | ptc_pass | inf_c | inf_a; "
                     "Greek: `<tense>_<mood>`"),
    ("voice", "both", "active | passive | middle (Hebrew, from the stem) ; Greek: the verb's voice"),
    ("neg", "both", "the negator's class: lo | al | en | bal | la | bilti (Hebrew), ou | me (Greek, with their compounds); null when none"),
    ("kind", "both", "the layout's clause kind (VC verbal, NC nominal)"),
    ("force", "both", "prohibitive | imperative | jussive | cohortative | hortatory | interrogative | declarative: the strongest of the "
                      "layout's own force codes over the clause (fc.proh, fc.imp, fc.jus, fc.coh, fc.hort, fc.q); declarative when none"),
    ("interrog", "both", "true when the clause carries the layout's question code (fc.q)"),
    ("person, number, gender", "both", "the main verb's (1 2 3; s p d; m f c n); null where the form has none"),
    ("stem", "both", "Hebrew / Aramaic stem of the verb (qal, niphal ... peal, aphel ...); Greek: null"),
    ("causative", "both", "true for hiphil, hophal and the causative stems of both languages; Greek: false"),
    ("strong", "both", "the verb's Strong's number"),
    ("speech", "both", "Hebrew: the quotation level from bcv-commons/hebrew-speaker-layer (0 narration); Greek: 1 inside a quotation"),
    ("speaker", "both", "Hebrew: the layer's speaker (the Hebrew lemma[s] of the words naming the speaker); Greek: the layout's speaker_id"),
    ("speaker_id", "hebrew", "the layer's character id of the speaker (the ids the Greek layout also uses)"),
    ("frame", "hebrew", "the speaker of a text that is speech from its first line (a psalm's psalmist), from the layer"),
    ("genre", "both", "the book's genre (one code per book)"),
    ("line", "both", "main | background | setting | speech | non-narrative: speech inside a quotation; setting when verbless; non-narrative "
                     "outside the narrative books; else Hebrew main = wayyiqtol, Greek main = aorist or present indicative at depth 0"),
    ("actor", "both", "overt | implicit | none: the verb's frame A0 inside the clause (overt), named elsewhere or carried by the verb "
                      "(implicit); Greek also the tree role s"),
    ("undergoer", "both", "overt | clause | complement | implicit | none, see below"),
    ("undergoer_basis", "both", "what made the undergoer present: np_a1 | single_word_o | a1_other | passive_subject | clause | "
                                "role_o_et (Hebrew) | role_o_without_a1; empty for implicit and none"),
    ("args", "both", "the verb frame's argument labels in order (A0+A1+A2 ...)"),
    ("subj", "both", "the subject's referent word id(s): MACULA's subjref of the verb, else the A0's referent, else the A0 word"),
    ("subj_switch", "both", "same | switch | first | none, by referent, against the previous clause with a subject in the chapter"),
    ("lxx_form", "hebrew", "the Septuagint form MACULA Hebrew gives for the clause's verb"),
    ("lxx_tense, lxx_mood", "hebrew", "that form's tense and mood: its GLAUx parse in the same verse when found there, else the commonest "
                                      "GLAUx parse of the form"),
    ("lxx_basis", "hebrew", "verse | form: which of the two gave lxx_tense / lxx_mood"),
    ("neg_scope", "both", "verb (the negator right before a verb) | constituent | none"),
    ("subj_form", "both", "noun | pronoun | zero | none"),
    ("part", "both", "the subject's participant: what its reference chain resolves to (Hebrew: Strong's number; Greek: lemma)"),
    ("part_switch", "both", "same | switch | first | none, by participant, against the previous clause with one in the chapter"),
    ("front", "both", "the role of the first constituent before the verb; '' when the verb comes first; verbless"),
    ("focus", "both", "sentence (presentational) | narrow (a fronted non-subject) | topic (a fronted subject) | predicate"),
    ("m_trans", "both", "number of macroroles in the verb's frame: 2 (A0 and A1), 1, 0"),
    ("subj_role", "both", "actor | undergoer | other | none: the subject's macrorole"),
    ("recip", "both", "1 when the frame has an A2"),
]


def card(build: dict, counts: dict) -> str:
    h, g = LAYOUTS["hebrew"], LAYOUTS["greek-nt"]
    uh = build["counts"]["hebrew"]["values"]["undergoer"]
    ug = build["counts"]["greek-nt"]["values"]["undergoer"]
    rows = "\n".join(f"| `{c.replace(', ', '`, `')}` | {w} | {d} |" for c, w, d in COLUMNS)
    return f"""---
license: cc-by-sa-4.0
language: [hbo, arc, grc]
pretty_name: Clause columns for the Hebrew and Greek clause layouts
tags: [bible, hebrew, greek, clauses, rrg, discourse]
configs:
- config_name: hebrew
  data_files: data/hebrew.parquet
- config_name: greek-nt
  data_files: data/greek-nt.parquet
---

# Clause columns ({VERSION})

Grammar and discourse facts for every clause of the two bcv-commons clause layouts, keyed by their clause keys: the main verb and its
form, voice, stem and person; negation and its scope; force; quotation and speaker; the narrative line; actor and undergoer with the
verb's argument frame; subject and participant tracking; fronting and focus; and, for the Hebrew, the Septuagint's form of the verb.

| config | layout (pinned) | clauses |
|---|---|---|
| `hebrew` | [{h['repo']}](https://huggingface.co/datasets/{h['repo']}) {h['version']} (`{h['revision'][:8]}`, {h['licence']}) | {counts['hebrew']['rows']:,} |
| `greek-nt` | [{g['repo']}](https://huggingface.co/datasets/{g['repo']}) {g['version']} (`{g['revision'][:8]}`, {g['licence']}) | {counts['greek-nt']['rows']:,} |

Join a row to its layout by `clause_key` (Hebrew `clause_key`; Greek `first`). Every clause of the layout has exactly one row. The
layouts' own columns (rule, relation, parent, depth and so on) are not copied here: read them from the layout.

## What changed from the previous version

The previous table (revision `{RESEARCH_REV[:8]}`) was built by make-tanakh-research. This version is rebuilt by bcv-query from the
same free sources, under the same column names and value names, and research has agreed to retire its builder. Differences, all
measured in `checks.md` (the contract check against the previous table, which joins on every clause both ways):

- **Split clauses.** A Hebrew clause the layout splits into several segments (2,263 keys) is now read whole. The previous table read
  its verb from one segment and its word order from another. Every other Hebrew difference comes from this.
- **Undergoer.** Both testaments now use the verb's frame (A1 inside the clause is overt, A1 elsewhere is implicit), with three new
  values: `clause` (the verb's patient is a clause), `complement` (a word with an object role but no A1 in the frame: complements,
  double and cognate objects, indefinite objects; in Hebrew also objects the frame misses) and, in `undergoer_basis`, what made each
  undergoer present. Hebrew: an object with no frame A1 but with the object marker אֵת counts as overt (`role_o_et`).
- **Greek actor** reads the frame too, as the Hebrew does.
- **Force** is the layouts' own force codes. In the Greek a question covers the whole question within its quotation, so about 5% of
  Greek clauses differ from the previous table.
- **Septuagint parse:** the parse of the form in its own GLAUx verse comes first (`lxx_basis`).
- **New columns:** `speaker_id`, `lxx_basis`, `undergoer_basis`; Greek `args`, `subj`, `subj_switch`.
- **Not carried any more:** `akt`, `akt_p`, `juss_p` (model answers, not source facts), `juncture` and `nexus` (to come with the clause
  relation work), `heb_form` (built from a private alignment), `legal_future`, and the copies of layout columns (`last`, `rule`,
  `relation`, `discourse`, `via`, `role`, `junction`, `parent`, `depth`).

## Columns

| column | in | description |
|---|---|---|
{rows}

### Undergoer

| value | meaning | Hebrew | Greek NT |
|---|---|---|---|
| `overt` | a patient inside the clause (the frame's A1, or an object with אֵת) | {uh.get('overt', 0):,} | {ug.get('overt', 0):,} |
| `clause` | every A1 of the verb lies under an object clause | {uh.get('clause', 0):,} | {ug.get('clause', 0):,} |
| `complement` | an object-role word with no A1 in the frame | {uh.get('complement', 0):,} | {ug.get('complement', 0):,} |
| `implicit` | the frame's A1 is named outside the clause | {uh.get('implicit', 0):,} | {ug.get('implicit', 0):,} |
| `none` | no patient | {uh.get('none', 0):,} | {ug.get('none', 0):,} |

MACULA calls its Hebrew frames tentative and they list fewer patients than the Greek ones, so Hebrew `complement` includes real
objects the frame misses. A second human analysis (used for figures only) finds a patient for 0.75 of Greek `overt` clauses, 0.61 of
`clause`, 0.34 of `complement` and 0.29 of `none`.

## How it was made, and how far to trust it

Built by code (`shoresh/macula/build_clause_columns.py` in bcv-query, contract check `clause_columns_contract.py`) from:
MACULA Hebrew (WLC) and MACULA Greek (Nestle 1904) with their trees, frames and references (CC BY 4.0); the two layouts;
bcv-commons/hebrew-speaker-layer (CC BY 4.0); and GLAUx's Septuagint parses (CC BY-SA 4.0; only `lxx_tense` and `lxx_mood`). Nothing
comes from BHSA or TBTA, and no English text is used as evidence. Every value is a rule's output; no column was checked by hand
row by row. A human review of samples is planned for later and will be reported here.

## Licence

CC BY-SA 4.0: the Hebrew layout's clause keys are CC BY-SA 4.0, and so are GLAUx's parses. Credit: MACULA (Clear Bible / Biblica),
GLAUx (KU Leuven, Alek Keersmaekers), bcv-commons (the layouts, the speaker layer), make-tanakh-research (the column design and
the previous version), and this dataset.
"""


if __name__ == "__main__":
    raise SystemExit(main())
