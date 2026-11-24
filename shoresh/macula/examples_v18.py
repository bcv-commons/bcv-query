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
STRONG_REL = "shoresh/macula/text_faults/strong_fixes.tsv"

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
    import hebrew_nt_strong_fixes as SF
    v19 = getattr(X, "V19", False)
    strong = str(SF.FIXES)      # SPEC 1.9 stage 55: k0 points it at the 1.8 table in its cache (git show HEAD~1:…)
    for path, want in ((LEVEL1, LEVEL1_SHA), (strong, STRONG19_SHA if v19 else STRONG_SHA)):
        got = sha(path)
        if not got.startswith(want):
            raise SystemExit(f"{os.path.basename(path)}: sha256 {got[:8]}…, pinned {want}… (SPEC section 5, "
                             f"{'1.9' if v19 else '1.8'})")
        rel = os.path.relpath(path, os.path.dirname(os.path.dirname(HERE)))
        out[STRONG_REL if path == strong else rel] = got
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


# ---- SPEC 1.9 (k builds, stage 55) -----------------------------------------------------------------------------------
STRONG19_SHA = "3650d1d2"    # SPEC section 5 (1.9, N5): strong_fixes.tsv as it now stands, 1,184 rows
COORD_REL = __import__("re").compile(r"^(NpaNp|[0-9]+Np):[0-9]+$")
NOUNISH = ("noun", "name", "propn", "n")


def coordinated_places(base, lg):
    """SPEC 1.9 D18 step W (N3): coord(verb t, place entity, kept set) is true where a noun piece of the verb's verse
    whose `who` holds the place has a coordination rel (NpaNp:<k>, <n>Np:<k>) and shares its head with, or has as its
    head, a noun piece of the same verse whose `who` holds a kept member. Reads the pieces and words of `base`."""
    import collections
    W = pq.read_table(os.path.join(base, lg, "words.parquet"), columns=["t", "book", "chapter", "verse"]).to_pylist()
    vk = {r["t"]: (r["book"], r["chapter"], r["verse"]) for r in W}
    byv = collections.defaultdict(list)
    for p in pq.read_table(os.path.join(base, lg, "pieces.parquet"),
                           columns=["t", "n", "who", "rel", "head_t", "head_n", "class"]).to_pylist():
        if p["who"] and p["class"] in NOUNISH:
            byv[vk[p["t"]]].append((p["t"], p["n"], set(p["who"].split()), str(p["rel"]), (p["head_t"], p["head_n"])))

    def coord(verb, e, kept):
        ps = byv.get(vk.get(verb), [])
        pe = [p for p in ps if e in p[2] and COORD_REL.match(p[3])]
        pk = [q for q in ps if kept & q[2]]
        return any((p[4] == q[4] and p[4][0] is not None) or p[4] == (q[0], q[1]) for p in pe for q in pk)
    return coord
