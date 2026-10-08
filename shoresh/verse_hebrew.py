"""Hebrew words of `GET /verse` built from MACULA tokens (NC exit, step 1; design: internal-docs/nc-exit-step1-verse-design.md).

MACULA stores a Hebrew word as several pieces (a prefix such as be-/ha-/ve-, the stem, sometimes a pronominal suffix); the key of a piece is
BBCCCVVVWWWP (book, chapter, verse, word, piece). `/verse` shows the words a reader sees, each with its pieces under `parts`:

  word:  idx (0-based), word (MACULA's 1-based word number, the argument of /coref and /frame), key (11 digits), surface, lemma, strong,
         head (key of the head piece), morph {class, stem, person, number, gender, state, ...}, lang ("arc" for Aramaic only), parts
  part:  key (12 digits), surface, lexeme (hbo:7225), strong, lemma, gloss (MACULA's contextual English gloss), class, role, morph

The head piece gives the word its lemma, Strong's number and morphology: it is the last piece that is not an ending (is_suffix). Pure functions, no database access:
the caller supplies the token rows and a function that turns a raw MACULA Strong's number into the code used elsewhere (e.g. "H7225").
"""
from __future__ import annotations

import collections
import re
from typing import Callable, Iterable

MORPH_FIELDS = ("stem", "person", "number", "gender", "state", "tense", "voice", "mood", "degree", "case_")
_EMPTY = {"", "NA", "na", None}


def group_words(tokens: Iterable[dict]) -> list[list[dict]]:
    """Group token rows (each with a `key`) into words by the first 11 digits of the key, in text order."""
    words: "collections.OrderedDict[str, list[dict]]" = collections.OrderedDict()
    for t in sorted(tokens, key=lambda t: t["key"]):
        words.setdefault(t["key"][:11], []).append(t)
    return list(words.values())


def _consonants(text: str | None) -> str:
    return re.sub(r"[^\u05D0-\u05EA]", "", text or "")


def is_suffix(parts: list[dict], i: int) -> bool:
    """Is piece i an ending that is not the word's head? Two kinds, both marked by MACULA:
    - a pronominal suffix (the -o of lo, -ay of alay, -hen of chelbehen): generic lemma hu, often a pseudo Strong's number such as 2050c.
      An independent pronoun has its own lemma (mah, atta, hem) or follows a bare conjunction or article (ve+hu "and he", ha+hu "that"),
      which makes it a word of its own.
    - an article-class piece AFTER a stem at the end of the word: the Hebrew directional ending (-ah in yammah "westward", Strong's 1886) and
      the Aramaic emphatic ending (-a in malka "the king", pseudo Strong's 0001b). A true article is a prefix and never follows a stem.
    - a trailing piece of class x (MACULA's miscellaneous class): the directional -ah (1886c, Gerar+ah) and the paragogic -ah on verbs (1886j)."""
    p = parts[i]
    if i > 0 and p.get("class") == "pron":
        return _consonants(p.get("lemma")) == "הוא" and parts[i - 1].get("class") not in ("cj", "art")
    if i > 0 and i == len(parts) - 1 and p.get("class") == "art":
        return parts[i - 1].get("class") not in ("prep", "cj", "art")
    if i > 0 and i == len(parts) - 1 and p.get("class") == "x":
        return True                       # the he of Gerar+ah, hava+h (pseudo Strong's 1886c / 1886j): class x, always an ending
    return False


def head_index(parts: list[dict]) -> int:
    """Index of the head piece of a word: the last piece that is not a pronominal suffix. So ve+el+ay ("and to me") has el as its head,
    be+reshit has reshit, ha+aretz has aretz, ve+hu has hu, and a word that is only a pronoun is its own head."""
    for i in range(len(parts) - 1, -1, -1):
        if not is_suffix(parts, i):
            return i
    return 0


def morph_of(t: dict) -> dict:
    """Structured morphology of one piece: its word class plus every grammatical field that applies."""
    out: dict = {}
    if t.get("class") not in _EMPTY:
        out["class"] = t["class"]
    for f in MORPH_FIELDS:
        v = t.get(f)
        if v not in _EMPTY:
            out["case" if f == "case_" else f] = v
    return out


def part_dict(t: dict, strong_code: Callable[[str | None], str | None]) -> dict:
    raw = (t.get("strong") or "").strip()
    out = {"key": t["key"], "surface": (t.get("text") or "").strip(),
           "lexeme": f"hbo:{raw}" if raw else None, "strong": strong_code(raw) if raw else None,
           "lemma": t.get("lemma") or None, "gloss": (t.get("gloss") or "").strip() or None,
           "class": t.get("class") or None, "morph": morph_of(t)}
    if t.get("role"):
        out["role"] = t["role"]
    return {k: v for k, v in out.items() if v is not None}


def word_dict(parts: list[dict], idx: int, strong_code: Callable[[str | None], str | None]) -> dict:
    """One word of /verse from its pieces (token rows in text order)."""
    h = parts[head_index(parts)]
    key = parts[0]["key"][:11]
    raw = (h.get("strong") or "").strip()
    w = {"idx": idx, "word": int(key[8:11]), "key": key,
         "surface": "".join((p.get("text") or "").strip() for p in parts),
         "lemma": h.get("lemma") or "", "strong": strong_code(raw) if raw else None,
         "head": h["key"], "morph": morph_of(h)}
    if any((p.get("wlang") or "") == "A" for p in parts):
        w["lang"] = "arc"
    w["parts"] = [part_dict(p, strong_code) for p in parts]
    return w


def build_words(tokens: Iterable[dict], strong_code: Callable[[str | None], str | None]) -> list[dict]:
    """All words of a verse from its token rows."""
    return [word_dict(parts, i, strong_code) for i, parts in enumerate(group_words(tokens))]
