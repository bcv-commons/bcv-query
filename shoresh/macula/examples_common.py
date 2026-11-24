"""Shared helpers of the source-examples builders: codes (SPEC 4.10, rule C0), normalised forms (section 7),
deterministic Parquet and TSV writing."""
import json
import os
import re
import unicodedata

import pyarrow as pa
import pyarrow.parquet as pq

# SPEC 1.2 (stage 23, d builds): build_examples.py sets this before it runs the stage builders; each module reads it
# where 1.2 changes a rule (CHANGES-1.2.md)
V12 = False
# SPEC 1.3 (stage 27, e builds): set by build_examples.py through examples_v13.setup
V13 = False
# SPEC 1.4 (stage 32, f builds): set by build_examples.py; the 1.3 builders then write facts.equivalent_of per
# evidence basis (D24a), everything else as in 1.3
V14 = False
# SPEC 1.5 (g builds, stage 35): the rules 1.5 changes, in the builders of 1.4 (examples_values11, examples_v13,
# examples_v13m, examples_v15, examples_v14)
V15 = False
# SPEC 1.6 (h builds, stage 38): D18 steps 2 and W of 1.6, SE5, D25 step 2b, D27 kept_out, D28 (examples_v15,
# examples_people11, examples_v15b, examples_v14, examples_v14doc)
V16 = False
# SPEC 1.8 (j builds, stage 52): the mends M1 to M5 (CHANGES-1.8.md): M1, M2 in examples_v15 (D18) and examples_v17
# (D39, D40); M3 through examples_v18.analysis_words (examples_links11, examples_v14, examples_v17); M4 in
# examples_links.lowfat_greek and examples_links12 (form_near). Off by default, so that i1 still rebuilds as it is.
V18 = False
# SPEC 1.8, stage 52 (report 52): j1 is i1 with the mends; two inputs of i1 are gone from the disk, so the sub-stages the
# mends reach are replayed on a sha-checked copy of i1 (build_examples.replay18), and a guard of a lost input counts
REPLAY18 = False
REPLAY18_DRIFT = []

# SPEC 4.10: closed categories, source value -> code
CLOSED = {
    "gender": {"masculine": "m", "feminine": "f", "neuter": "n", "common": "c", "both": "b", "unknown: x": "x"},
    "number": {"singular": "sg", "plural": "pl", "dual": "du", "unknown: x": "x"},
    "person": {"first": "1", "second": "2", "third": "3", "unknown: x": "x"},
    "state": {"absolute": "abs", "construct": "cstr", "determined": "det"},
    "case": {"nominative": "nom", "genitive": "gen", "dative": "dat", "accusative": "acc", "vocative": "voc"},
    "tense": {"present": "pres", "imperfect": "impf", "future": "fut", "aorist": "aor", "perfect": "prf",
              "pluperfect": "plprf"},
    "voice": {"active": "act", "middle": "mid", "passive": "pass", "middlepassive": "midpass"},
    "mood": {"indicative": "ind", "subjunctive": "sbjv", "optative": "opt", "imperative": "imp",
             "infinitive": "inf", "participle": "ptcp"},
    "degree": {"comparative": "cmpr", "superlative": "sprl"},
}

# SPEC 4.10: the categories `marks` takes
MARK_CATS = {
    "hbo": ("type", "stem", "person", "gender", "number", "state"),
    "arc": ("type", "stem", "person", "gender", "number", "state"),
    "grc": ("type", "tense", "voice", "mood", "person", "case", "gender", "number", "degree"),
}

LANG_OF = {"H": "hbo", "A": "arc"}


def c0(value):
    """Rule C0: lower-case, every run outside a-z 0-9 -> '_', strip '_' at either end."""
    code = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not code:
        raise ValueError(f"C0 gives an empty code for {value!r}")
    return code


class Coder:
    """Codes values per category and records (category, code) -> source value and how the code was made.
    Two source values that give one code raise (SPEC 4.10: an error of the build)."""

    def __init__(self):
        self.seen = {}      # (cat, code) -> value
        self.rule = {}      # (cat, code) -> 'list' | 'C0'
        self.c0_closed = {}  # (cat, value) -> code, closed-category values that fell to C0

    def code(self, cat, value):
        table = CLOSED.get(cat)
        if table is not None and value in table:
            code, rule = table[value], "list"
        else:
            code, rule = c0(value), "C0"
            if table is not None:
                self.c0_closed[(cat, value)] = code
        prev = self.seen.get((cat, code))
        if prev is None:
            self.seen[(cat, code)] = value
            self.rule[(cat, code)] = rule
        elif prev != value:
            raise ValueError(f"two source values give one code: {cat} {prev!r} and {value!r} -> {code!r}")
        return code


def jdump(obj):
    """A JSON column value: keys sorted, no spaces (SPEC 4)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


_HEB_DROP = set(range(0x0591, 0x05B0)) | {0x05BD, 0x05C4, 0x05C5}


def norm_heb(text):
    """Normalised Hebrew/Aramaic form (SPEC 7): drop accents U+0591-U+05AF, meteg U+05BD, U+05C4, U+05C5; NFC."""
    return unicodedata.normalize("NFC", "".join(ch for ch in text if ord(ch) not in _HEB_DROP))


def norm_grc(normalized):
    """Normalised Greek form (SPEC 7): MACULA's `normalized`, lower-cased, NFC."""
    return unicodedata.normalize("NFC", normalized.lower())


def write_parquet(path, columns, schema):
    """Write columns (dict name -> list) with an explicit schema; no pandas metadata, fixed options."""
    arrays = [pa.array(columns[f.name], type=f.type) for f in schema]
    table = pa.Table.from_arrays(arrays, schema=schema)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    pq.write_table(table, tmp, compression="zstd", compression_level=9, row_group_size=1 << 20)
    os.replace(tmp, path)


def write_tsv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(header) + "\n")
        for r in rows:
            vals = ["" if v is None else str(v) for v in r]
            for v in vals:
                if "\t" in v or "\n" in v:
                    raise ValueError(f"tab or newline in a TSV value: {v!r}")
            fh.write("\t".join(vals) + "\n")
    os.replace(tmp, path)


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def toml_str(s):
    """A TOML basic string (JSON string escapes are valid TOML)."""
    return json.dumps(s, ensure_ascii=False)
