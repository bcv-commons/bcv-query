"""SPEC 1.8 (j builds, stage 52): the shared pieces of the mends (CHANGES-1.8.md).

- M1: the passive stems and voices of 4.11 (1.8).
- M2: the type of an entity key (section 3: `<type>:<id>`) and the types step W always keeps.
- M3: every reader of hebrew-nt-analysis v0.2's words reads them through `analysis_words`, which applies
  hebrew_nt_level1_fixes.apply and then hebrew_nt_strong_fixes.apply (D14 in 1.8) when examples_common.V18 is set;
  the two fix tables are pinned by sha256 (section 5).
"""
import hashlib
import os

import pyarrow.parquet as pq

import examples_common as X

HERE = os.path.dirname(os.path.abspath(__file__))
LEVEL1 = os.path.join(HERE, "text_faults", "level1_fixes.tsv")
STRONG = os.path.join(HERE, "text_faults", "strong_fixes.tsv")
LEVEL1_SHA = "2f42b3e9"      # SPEC section 5 (1.8): the prefix the specification gives; the full sum is in sources.json
STRONG_SHA = "585a53c3"

PASSIVE = {"hbo": {"niphal", "pual", "hophal", "qal_passive", "pulal", "polal", "poal", "polpal"},
           "arc": {"peil", "hophal", "hithpeel", "hithpaal", "ithpeel", "ithpaal", "ithpoel"},
           "grc": {"pass", "midpass"}}
KEEP_TYPES = {"person", "group"}

# the columns the two apply() functions read or write
FIX_COLS = ("book", "chapter", "verse", "i", "part", "token", "text", "class", "lemma", "lexeme", "strong", "source",
            "form", "person", "role", "p_split")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fix_pins():
    """{path relative to the repository: sha256} of the two fix tables, checked against section 5's prefixes."""
    out = {}
    for path, want in ((LEVEL1, LEVEL1_SHA), (STRONG, STRONG_SHA)):
        got = sha(path)
        if not got.startswith(want):
            raise SystemExit(f"{os.path.basename(path)}: sha256 {got[:8]}…, pinned {want}… (SPEC section 5, 1.8)")
        out[os.path.relpath(path, os.path.dirname(os.path.dirname(HERE)))] = got
    return out


def is_passive(lang, marks):
    """M1: the stem or voice of a verb's stem piece is passive (4.11 in 1.8)."""
    k = marks.get("voice") if lang == "grc" else marks.get("stem")
    return (k or "") in PASSIVE[lang]


def etype(e):
    return e.split(":")[0]


def larger_set(small, large):
    """M2 (D18 step W in 1.8): the larger set's members beyond the smaller are kept only where their type is a type of
    the smaller set, or person or group. Returns (kept set, left-out members)."""
    st = {etype(e) for e in small}
    out = {e for e in large - small if etype(e) not in st and etype(e) not in KEEP_TYPES}
    return large - out, out


def analysis_words(path, ed, columns=None):
    """The rows of hebrew-nt-analysis v0.2's `<ed>/words.parquet` (in file order), through the two fix tables when
    V18 is set (D14 in 1.8). `columns` as for pyarrow; the rows carry those columns only."""
    if not getattr(X, "V18", False):
        return pq.read_table(path, columns=columns).to_pylist()
    import hebrew_nt_level1_fixes as L1
    import hebrew_nt_strong_fixes as SF
    fix_pins()
    have = pq.read_table(path).schema.names
    cols = list(dict.fromkeys([c for c in FIX_COLS if c in have] + list(columns or have)))
    rows = pq.read_table(path, columns=cols).to_pylist()
    rows = SF.apply(ed, L1.apply(ed, rows))
    keep = list(columns or have)
    return [{c: r.get(c) for c in keep} for r in rows]
