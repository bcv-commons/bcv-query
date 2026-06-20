"""Shared spine constants + helpers (used by parse.py, reconcile.py, prefix.py)."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --- pinned source versions (see docs/spine-parser.md) ---
UHB_TAG = "v2.1.32"
UGNT_TAG = "v0.34"
UHB_URL = "https://git.door43.org/unfoldingWord/hbo_uhb/raw/tag/%s/{nn:02d}-{code}.usfm" % UHB_TAG
UGNT_URL = "https://git.door43.org/unfoldingWord/el-x-koine_ugnt/raw/tag/%s/{nn:02d}-{code}.usfm" % UGNT_TAG

# USFM file number per book code (Protestant numbering in the Door43 repos)
FILENUM = {
    "GEN":1,"EXO":2,"LEV":3,"NUM":4,"DEU":5,"JOS":6,"JDG":7,"RUT":8,"1SA":9,"2SA":10,
    "1KI":11,"2KI":12,"1CH":13,"2CH":14,"EZR":15,"NEH":16,"EST":17,"JOB":18,"PSA":19,
    "PRO":20,"ECC":21,"SNG":22,"ISA":23,"JER":24,"LAM":25,"EZK":26,"DAN":27,"HOS":28,
    "JOL":29,"AMO":30,"OBA":31,"JON":32,"MIC":33,"NAM":34,"HAB":35,"ZEP":36,"HAG":37,
    "ZEC":38,"MAL":39,
    "MAT":41,"MRK":42,"LUK":43,"JHN":44,"ACT":45,"ROM":46,"1CO":47,"2CO":48,"GAL":49,
    "EPH":50,"PHP":51,"COL":52,"1TH":53,"2TH":54,"1TI":55,"2TI":56,"TIT":57,"PHM":58,
    "HEB":59,"JAS":60,"1PE":61,"2PE":62,"1JN":63,"2JN":64,"3JN":65,"JUD":66,"REV":67,
}
OT_BOOKS = [c for c, n in sorted(FILENUM.items(), key=lambda kv: kv[1]) if n <= 39]
NT_BOOKS = [c for c, n in sorted(FILENUM.items(), key=lambda kv: kv[1]) if n >= 40]

JOINER = "⁠"  # word-joiner separating morphemes inside a surface form

# Head part-of-speech letters counted as content words (kept in the Lexical line)
_CONTENT_POS = {"N", "V", "A"}


def norm_strong(raw: str | None, lang: str) -> int | None:
    """Normalize a Strong's string to an int (drops H/G, leading zeros, variant tail).

    Hebrew (UHB): `H7225`, `H1254a` -> 7225, 1254.
    Greek (UGNT): `G09760` (4-digit number + 1 extension digit) -> 976.
    """
    if not raw:
        return None
    m = re.search(r"[HG](\d+)", raw)
    if not m:
        return None
    digits = m.group(1)
    if lang == "grc" and len(digits) == 5:   # UGNT: NNNN + extension digit
        digits = digits[:4]
    return int(digits)


def content_strong_field(strong_attr: str) -> str:
    """The content Strong's is the last ':'-segment (after prefix particles)."""
    return strong_attr.split(":")[-1]


def morph_body(morph: str) -> str:
    """Strip the `He,` / `Gr,` language tag from an x-morph value."""
    return morph.split(",", 1)[1] if "," in morph else morph


def head_pos(morph: str, lang: str) -> str:
    """First letter of the head part-of-speech."""
    body = morph_body(morph)
    if lang == "hbo":
        segs = [s for s in body.split(":") if not s.startswith("S")]
        head = segs[-1] if segs else body
        return head[:1]
    # Greek: comma-separated fields, first is POS
    return body.split(",", 1)[0][:1]


def is_content(morph: str, lang: str) -> bool:
    return head_pos(morph, lang) in _CONTENT_POS


def lang_of(code: str) -> str:
    """'hbo' for OT books, 'grc' for NT."""
    return "hbo" if FILENUM.get(code, 99) <= 39 else "grc"


def to_modern_form(lemma: str, lang: str) -> str:
    """Naive 'arm A' normalization of a lemma toward the modern form the model knows.

    Hebrew: keep only base consonants (drop niqqud + cantillation) → unpointed form.
    Greek: strip combining diacritics (polytonic accents/breathings) → bare letters.

    NOTE: this is the cheap first pass. Arm B will upgrade to ktiv-male (Hebrew)
    and proper monotonic (Greek) normalization if arm A shows signal.
    """
    if lang == "hbo":
        return "".join(c for c in lemma if "א" <= c <= "ת")
    d = unicodedata.normalize("NFD", lemma)
    return unicodedata.normalize("NFC", "".join(c for c in d if not unicodedata.combining(c)))


def load_equivalences() -> dict[int, int]:
    """variant -> canonical Strong's, from strongs_equivalence.tsv."""
    eq: dict[int, int] = {}
    p = HERE / "strongs_equivalence.tsv"
    if not p.exists():
        return eq
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("variant"):
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            a, b = norm_strong(parts[0], "hbo"), norm_strong(parts[1], "hbo")
            if a and b:
                eq[a] = b
    return eq
