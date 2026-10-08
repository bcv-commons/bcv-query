"""Lexeme and sense read path on MACULA keys (NC exit, step 2a; design: internal-docs/nc-exit-step2-lexeme-design.md).

Replaces the BHSA-keyed hbo.db / senses/hbo_lex.tsv readers behind /senses, /lexeme, /wordstudy, /word and the SDBH-shaped lexicon meanings.
Key forms: a lexeme is a MACULA id `hbo:NNNN[a]` (NNNN = Strong's number, a = homograph letter, e.g. hbo:0871a); an occurrence is a MACULA token key.
Data (both CC BY, no BHSA input):
  lexeme-spine-macula.db  spine_words(key, book, chapter, verse, lexeme, strong, lemma, stem, surface, morph ...)  Hebrew numbering
  verse-senses.db         occ(key, lexeme, sense) per occurrence, senses(lexeme, sense, label, n, share)          hebrew-word-senses
Senses are global per lexeme (not per stem as hbo.db's were); the stem of an occurrence comes from its token, so the old per-stem views are
recomputed from the occurrences: a stem's senses are the senses its own tokens carry, with their share within that stem.
Every function opens its own read-only connection (never a shared one: sqlite3 connections must not cross request threads).
"""
from __future__ import annotations

import collections
import os
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
_LEXEME = re.compile(r"^hbo:\d{4}[a-z]?$")


class NotAvailable(RuntimeError):
    """The MACULA lexeme databases are not on this host."""


def _first(env: str, name: str) -> Path | None:
    for c in (os.environ.get(env), f"/data/{name}", f"/data/public/{name}", str(HERE / "macula" / name)):    # /data/public: where the published spines (GET /files) live on the server
        if c and Path(c).exists():
            return Path(c)
    return None


def spine_path() -> Path | None:
    return _first("LEXEME_SPINE_DB", "lexeme-spine-macula.db")


def senses_path() -> Path | None:
    return _first("VERSE_SENSES_DB", "verse-senses.db")


def available() -> bool:
    return spine_path() is not None and senses_path() is not None


def _con() -> sqlite3.Connection:
    sp, se = spine_path(), senses_path()
    if sp is None or se is None:
        raise NotAvailable("lexeme-spine-macula.db / verse-senses.db not found")
    con = sqlite3.connect(f"file:{sp}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("ATTACH DATABASE ? AS vs", (f"file:{se}?mode=ro",))
    return con


def is_lexeme_id(s: str) -> bool:
    return bool(_LEXEME.match((s or "").strip().lower()))


def strong_number(code: str) -> int | None:
    m = re.match(r"^[Hh]0*(\d+)$", (code or "").strip())
    return int(m.group(1)) if m else None


def lexemes_of(num: int) -> list[str]:
    """The lexemes (homographs) a Strong's number covers, most frequent first."""
    con = _con()
    try:
        return [r[0] for r in con.execute(
            "SELECT lexeme FROM spine_words WHERE strong=? AND lexeme LIKE 'hbo:%' GROUP BY lexeme ORDER BY count(*) DESC", (num,))]
    finally:
        con.close()


def _ref(r) -> str:
    return f"{r['book']} {r['chapter']}:{r['verse']}"


# ---------------------------------------------------------------- sense groups (same shape as the BHSA version)
def sense_groups(rows) -> list[dict]:
    """rows: lexeme, stem, sense (int or None), label, book, chapter, verse -> [{lex, stem, sense, label, count, refs}], most frequent first.
    `lex` is the MACULA lexeme id; `sense` the sense number as a string; occurrences with no assigned sense form a group with sense "" and no label (as in hbo.db)."""
    groups: dict = collections.OrderedDict()
    for r in rows:
        key = (r["lexeme"], r["stem"] or "", "" if r["sense"] is None else int(r["sense"]))      # like hbo.db: unsensed occurrences form a group with sense ""
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"lex": r["lexeme"], "stem": key[1], "sense": str(key[2]), "label": r["label"], "count": 0, "refs": []}
        g["count"] += 1
        if len(g["refs"]) < 6:
            g["refs"].append(_ref(r))
    return sorted(groups.values(), key=lambda x: -x["count"])


_SELECT = ("SELECT w.key, w.book, w.chapter, w.verse, w.lexeme, w.stem, o.sense, s.label FROM spine_words w "
           "LEFT JOIN vs.occ o ON o.key=w.key LEFT JOIN vs.senses s ON s.lexeme=o.lexeme AND s.sense=o.sense ")


def sense_rows(where: str, args: tuple, limit: int | None = None) -> list:
    con = _con()
    try:
        return con.execute(_SELECT + f"WHERE {where} ORDER BY w.key" + (f" LIMIT {int(limit)}" if limit else ""), args).fetchall()
    finally:
        con.close()


def sense_concordance(strong_code: str, limit: int = 5000) -> dict:
    """Occurrences of a Hebrew Strong's grouped by lexeme x stem x sense."""
    num = strong_number(strong_code)
    if num is None:
        return {"error": "sense-concordance is Hebrew-only (H####)"}
    return {"senses": sense_groups(sense_rows("w.strong=? AND w.lexeme LIKE 'hbo:%'", (num,), limit))}


def lexeme_profile_one(lex: str) -> dict:
    rows = sense_rows("w.lexeme=?", (lex,))
    if not rows:
        return {"error": f"no occurrences for lexeme {lex!r}"}
    return {"lex": lex, "strong": [f"H{int(lex[4:8]):04d}"], "total": len(rows), "senses": sense_groups(rows)}


def lexeme_profile(lex: str) -> dict:
    """`lex` is a MACULA lexeme id (hbo:6942, hbo:0871a) or a Hebrew Strong's code (H6942), which fans out to every homograph lexeme.
    BHSA lexeme ids (QDC[) are no longer understood."""
    lex = (lex or "").strip()
    if re.match(r"^[GgHh]\d", lex):
        if lex[0] in "Gg":
            return {"error": f"Greek Strong's {lex!r}: lexeme profiles are Hebrew-only"}
        num = strong_number(lex)
        lexes = lexemes_of(num) if num is not None else []
        if not lexes:
            return {"error": f"no occurrences for Strong's {lex!r}"}
        if len(lexes) == 1:
            return lexeme_profile_one(lexes[0])
        return {"strong": f"H{num:04d}", "lexemes": [lexeme_profile_one(l) for l in lexes]}
    if is_lexeme_id(lex):
        return lexeme_profile_one(lex.lower())
    return {"error": f"{lex!r} is not a lexeme id (hbo:NNNN[a]) or a Strong's code (H####); BHSA lexeme ids are no longer supported"}


def sense_by_ref(strong_code: str) -> dict[str, str]:
    """{'BOOK C:V': sense label} for a Hebrew Strong's: the first labelled occurrence per verse (Hebrew numbering)."""
    num = strong_number(strong_code)
    out: dict[str, str] = {}
    if num is None:
        return out
    for r in sense_rows("w.strong=? AND w.lexeme LIKE 'hbo:%' AND o.sense IS NOT NULL", (num,)):
        out.setdefault(_ref(r), r["label"])
    return out


def sense_by_key(strong_code: str) -> dict[str, str]:
    """{token key: sense label} for every labelled occurrence of a Hebrew Strong's."""
    num = strong_number(strong_code)
    if num is None:
        return {}
    return {r["key"]: r["label"] for r in sense_rows("w.strong=? AND w.lexeme LIKE 'hbo:%' AND o.sense IS NOT NULL", (num,))}


# ---------------------------------------------------------------- per-stem views, recomputed from the occurrences
def lex_senses(strong_code: str) -> list[dict]:
    """[{lex, stems: {stem: [{sense, gloss, share}]}}]: for each homograph lexeme, the senses the tokens of each stem carry, with their share
    within that stem, most frequent first. '' = tokens without a verbal stem. Labels are English (hebrew-word-senses)."""
    num = strong_number(strong_code)
    if num is None:
        return []
    per: dict = collections.OrderedDict()
    for lex in lexemes_of(num):
        counts: dict = collections.defaultdict(collections.Counter)
        labels: dict = {}
        for r in sense_rows("w.lexeme=? AND o.sense IS NOT NULL", (lex,)):
            counts[r["stem"] or ""][int(r["sense"])] += 1
            labels[int(r["sense"])] = r["label"]
        if not counts:
            continue
        stems = {}
        for stem, c in sorted(counts.items(), key=lambda kv: -sum(kv[1].values())):
            tot = sum(c.values())
            stems[stem] = [{"sense": str(s), "gloss": labels[s], "share": round(n / tot, 3)} for s, n in c.most_common()]
        per[lex] = stems
    return [{"lex": lex, "stems": stems} for lex, stems in per.items()]


def stem_senses(strong_code: str) -> list[dict]:
    """[{lex, senses: {stem: label}}] for verb lexemes: the dominant sense of each stem (what word_glosses gave per binyan)."""
    out = []
    for e in lex_senses(strong_code):
        verbs = {st: ss[0]["gloss"] for st, ss in e["stems"].items() if st and ss}
        if verbs:
            out.append({"lex": e["lex"], "senses": verbs})
    return out


def lexicon_meanings(strong_code: str, base: int, lemma: str | None) -> list[dict]:
    """The SDBH-shaped `meanings` rows (lexId/lemma/grammar/definitionShort/comments/glosses), one per (stem, sense) of the Strong's."""
    out, n = [], 0
    for e in lex_senses(strong_code):
        for stem, senses in e["stems"].items():
            for row in senses:
                n += 1
                out.append({"lexId": base * 1000 + n, "lemma": lemma, "grammar": stem or None,
                            "definitionShort": row["gloss"], "comments": None, "glosses": row["gloss"]})
    return out


def occurrences(strong_code: str, limit: int) -> list[dict]:
    """Concordance rows of a Hebrew Strong's in Hebrew numbering, text order: ref, key, surface, morph, plus the occurrence's sense."""
    num = strong_number(strong_code)
    if num is None:
        return []
    con = _con()
    try:
        rows = con.execute(
            "SELECT w.key, w.book, w.chapter, w.verse, w.surface, w.morph, s.label FROM spine_words w "
            "LEFT JOIN vs.occ o ON o.key=w.key LEFT JOIN vs.senses s ON s.lexeme=o.lexeme AND s.sense=o.sense "
            "WHERE w.strong=? AND w.lexeme LIKE 'hbo:%' ORDER BY w.key LIMIT ?", (num, int(limit))).fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        o = {"corpus": "spine", "ref": f"{r['book']} {r['chapter']}:{r['verse']}", "key": r["key"], "surface": r["surface"], "morph": r["morph"]}
        if r["label"]:
            o["sense"] = r["label"]
        out.append(o)
    return out
