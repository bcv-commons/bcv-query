"""Verse structure on MACULA's lowfat trees, Hebrew and Greek (NC exit, step 3; design: internal-docs/nc-exit-step3-structure-design.md).

Replaces the Context-Fabric reads of BHSA / Nestle1904 behind /structure, /structure/.../syntax, /verse/.../tree, /structure/.../word/{idx} and /syntax/search
when STRUCTURE_BASE=macula (corpus.py switches). The response shapes are the engine's (corpus_engine/cf_engine.py); the values are MACULA's:
  - a word is a MACULA token (prefix particles and pronominal suffixes are tokens of their own, as in /verse `parts`), `lexeme` is a MACULA lexeme id
    (`hbo:6942`) for Hebrew and the lemma for Greek;
  - a clause is a word group of class "cl"; its phrases are the role-bearing groups (or single words) directly below it; a clause's `phrases` list only its OWN words
    (a nested clause is a clause of its own, as in the BHSA view) while its `text` reads through the nested clauses;
  - a phrase `function` is the MACULA role (s o o2 io p v vc adv aux pp) as a readable label, the same labels the Greek view always had.
Data: trees-macula.db (macula/build_trees.py) joined by token key to lexeme-spine-macula.db for lexeme, gloss and morphology. Both CC BY, no BHSA input.
Every function opens its own read-only connection.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent

# role -> readable label (the Greek labels, plus MACULA Hebrew's `pp`)
ROLE_LABELS = {"s": "Subject", "o": "Object", "o2": "Object2", "io": "IndirectObject", "p": "Predicate", "v": "Verb", "vc": "VerbCopula",
               "adv": "Adverbial", "aux": "Auxiliary", "apposition": "Apposition", "pp": "PrepositionalPhrase"}

# canonical function tokens, so /syntax/search matches across spellings: MACULA role codes, readable labels and the old BHSA function codes
_CANON: dict[str, str] = {}
for _canon, _variants in {
    "subject": ("subj", "subject", "s"), "predicate": ("pred", "prec", "predicate", "p"), "object": ("objc", "object", "obj", "o"),
    "object2": ("o2", "object2"), "indirectobject": ("io", "indirectobject"), "verb": ("v", "verb"), "verbcopula": ("vc", "verbcopula"),
    "complement": ("cmpl", "complement"), "adverbial": ("adju", "adverbial", "adv"), "time": ("time",), "location": ("loca", "location"),
    "apposition": ("appo", "apposition"), "prepositionalphrase": ("pp", "prepositionalphrase"), "auxiliary": ("aux", "auxiliary"),
}.items():
    for _v in _variants:
        _CANON[_v] = _canon
# BHSA's `Pred` is the verbal predicate, which MACULA calls Verb: a Hebrew query for the predicate also finds the verb
_HEBREW_ALSO = {"predicate": {"predicate", "verb"}}

_HEBREW_NAME_TO_USFM = {
    "Genesis": "GEN", "Exodus": "EXO", "Leviticus": "LEV", "Numbers": "NUM", "Deuteronomy": "DEU", "Joshua": "JOS", "Judges": "JDG", "Ruth": "RUT",
    "1_Samuel": "1SA", "2_Samuel": "2SA", "1_Kings": "1KI", "2_Kings": "2KI", "1_Chronicles": "1CH", "2_Chronicles": "2CH", "Ezra": "EZR",
    "Nehemiah": "NEH", "Esther": "EST", "Job": "JOB", "Psalms": "PSA", "Proverbs": "PRO", "Ecclesiastes": "ECC", "Song_of_songs": "SNG",
    "Isaiah": "ISA", "Jeremiah": "JER", "Lamentations": "LAM", "Ezekiel": "EZK", "Daniel": "DAN", "Hosea": "HOS", "Joel": "JOL", "Amos": "AMO",
    "Obadiah": "OBA", "Jonah": "JON", "Micah": "MIC", "Nahum": "NAM", "Habakkuk": "HAB", "Zephaniah": "ZEP", "Haggai": "HAG", "Zechariah": "ZEC",
    "Malachi": "MAL",
}
_USFM_TO_HEBREW_NAME = {v: k for k, v in _HEBREW_NAME_TO_USFM.items()}
_CORPUS = {"hbo": "hebrew", "grc": "greek"}


def _first(env: str, name: str) -> Path | None:
    for c in (os.environ.get(env), f"/data/{name}", f"/data/public/{name}", str(HERE / "macula" / name)):
        if c and Path(c).exists():
            return Path(c)
    return None


def trees_path() -> Path | None:
    return _first("TREES_DB", "trees-macula.db")


def available() -> bool:
    import lexeme_macula
    return trees_path() is not None and lexeme_macula.spine_path() is not None


def _con() -> sqlite3.Connection:
    import lexeme_macula
    tp, sp = trees_path(), lexeme_macula.spine_path()
    if tp is None or sp is None:
        raise RuntimeError("trees-macula.db / lexeme-spine-macula.db not found")
    con = sqlite3.connect(f"file:{tp}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("ATTACH DATABASE ? AS sp", (f"file:{sp}?mode=ro",))
    return con


def corpus_of(book: str) -> str | None:
    """'hbo' | 'grc' for a USFM book code, from the trees themselves."""
    con = _con()
    try:
        r = con.execute("SELECT corpus FROM words WHERE book=? LIMIT 1", (book.upper(),)).fetchone()
    finally:
        con.close()
    return r[0] if r else None


def book_name(corpus: str, usfm: str) -> str:
    return _USFM_TO_HEBREW_NAME.get(usfm, usfm) if corpus == "hbo" else usfm


def _label(role: str | None) -> str | None:
    return ROLE_LABELS.get(role, role) if role else None


def _text(words, corpus: str = "hbo") -> str:
    """Words joined by their trailers. Greek lowfat trailers carry punctuation without the following space ("κόσμον,"), so a space is added there."""
    out = []
    for w in words:
        after = w["after"] or ""
        if corpus == "grc" and after and not after.endswith(" "):
            after += " "
        out.append(w["surface"] + after)
    return "".join(out).strip()


TEXT_ORDER = "w.chapter, w.verse, w.word, w.part, w.seq"     # seq is tree order; text order is the position in the verse
_WORDS_SQL = ("SELECT w.*, s.gloss AS gloss, s.person AS person, s.number AS number, s.gender AS gender, s.state AS state, s.mood AS mood, s.case_ AS case_ "
              "FROM words w LEFT JOIN sp.spine_words s ON s.key=w.key ")


def _verse_words(con, corpus: str, book: str, chapter: int, verse: int, with_inserted: bool = False) -> list:
    rows = con.execute(_WORDS_SQL + "WHERE w.corpus=? AND w.book=? AND w.chapter=? AND w.verse=? ORDER BY " + TEXT_ORDER, (corpus, book, chapter, verse)).fetchall()
    return rows if with_inserted else [r for r in rows if not r["inserted"]]


def _word_dict(con, w, following) -> dict:
    """The engine's word shape. `following` is the next word of the verse, to tell whether a pronominal suffix follows."""
    hebrew = w["corpus"] == "hbo"
    suffix = bool(hebrew and following is not None and following["word"] == w["word"] and following["class"] == "pron" and following["wtype"] == "pronominal"
                  and following["part"] > w["part"])
    return {"monad": w["seq"], "key": w["key"], "text": w["surface"], "trailer": w["after"] or "",
            "lexeme": w["lexeme"] or "", "lexeme_utf8": w["lemma"] or "", "gloss": w["gloss"] or "",
            "part_of_speech": w["class"] or "", "gender": w["gender"] or "", "number": w["number"] or "", "person": w["person"] or "",
            "state": w["state"] or "", "verbal_stem": (w["stem"] if hebrew else w["voice"]) or "", "verbal_tense": w["tense"] or "",
            "language": "", "suffix": suffix}


def passage(book: str, chapter: int, verse: int) -> dict:
    book = book.upper()
    con = _con()
    try:
        corpus = corpus_of(book)
        if not corpus:
            return {"error": f"no corpus mapping for book '{book}'"}
        words = _verse_words(con, corpus, book, chapter, verse)
        name = book_name(corpus, book)
        verses = []
        if words:
            verses.append({"book": name, "chapter": chapter, "verse": verse,
                           "words": [_word_dict(con, w, words[i + 1] if i + 1 < len(words) else None) for i, w in enumerate(words)]})
        return {"corpus": _CORPUS[corpus], "corpus_book": name, "data": {"corpus": _CORPUS[corpus], "verses": verses}}
    finally:
        con.close()


# ------------------------------------------------------------------------------------------------ clauses, phrases, trees
def _clause_ids(con, corpus, book, chapter, verse) -> list[int]:
    return [r[0] for r in con.execute(
        "SELECT w.cl FROM words w WHERE w.corpus=? AND w.book=? AND w.chapter=? AND w.verse=? AND w.cl IS NOT NULL AND w.inserted=0 "
        "GROUP BY w.cl ORDER BY MIN(w.word * 100 + w.part)", (corpus, book, chapter, verse))]


def _node(con, nid):
    return con.execute("SELECT * FROM nodes WHERE id=?", (nid,)).fetchone()


def _phrase_word(w) -> dict:
    hebrew = w["corpus"] == "hbo"
    return {"text": w["surface"], "lex": w["lexeme"] or None, "gloss": (w["gloss"].replace(".", " ") or None) if (w["gloss"] and w["gloss"] != "-") else None,      # MACULA joins a multi-word gloss with dots
            "sp": w["class"], "stem": (w["stem"] or None) if hebrew else None}


def _span_text(con, n) -> str:
    """The text of every word below a node, nested clauses included (reading text; the phrases list only the clause's own words)."""
    if n["lo"] is None:
        return ""
    ws = con.execute("SELECT surface, after, inserted FROM words w WHERE seq BETWEEN ? AND ? ORDER BY " + TEXT_ORDER, (n["lo"], n["hi"])).fetchall()
    return _text([{"surface": w["surface"], "after": w["after"]} for w in ws if not w["inserted"]], n["corpus"])


def _clause_kind(own) -> str:
    """BHSA's clause kind: VC (verbal clause) when the clause has a verb of its own, else NC (nominal clause)."""
    return "VC" if any(w["role"] == "v" or w["class"] == "verb" for w in own) else "NC"


_CLAUSE_RELA = {"adv": "Adju", "o": "Objc", "o2": "Objc", "s": "Subj", "p": "PreC", "apposition": "Appo"}


def _clause_rela(cl) -> str | None:
    """How the clause relates to its mother: its junction (Greek) or, from the role it fills, BHSA's relation codes (Adju Objc Subj ...)."""
    return cl["junction"] or _CLAUSE_RELA.get(cl["role"])


def _clause_dict(con, cl_id: int, verse: int | None = None) -> dict:
    cl = _node(con, cl_id)
    own_all = [w for w in con.execute(_WORDS_SQL + "WHERE w.cl=? ORDER BY " + TEXT_ORDER, (cl_id,)).fetchall() if not w["inserted"]]
    own = [w for w in own_all if verse is None or w["verse"] == verse]          # a clause that runs into the next verse lists the words of the requested verse
    phrases: list[tuple[int, dict]] = []
    by_ph: dict = {}
    for w in own:
        if w["ph"] is not None:
            key = ("n", w["ph"])
        elif w["role"]:
            key = ("w", w["seq"])
        else:
            key = ("x", w["seq"])
        by_ph.setdefault(key, []).append(w)
    for key, ws in by_ph.items():
        if key[0] == "n":
            ph = _node(con, key[1])
            function, typ = _label(ph["role"]), ph["cls"]
        elif key[0] == "w":
            function, typ = _label(ws[0]["role"]), ws[0]["class"]
        else:
            function, typ = None, ws[0]["class"]
        phrases.append((ws[0]["word"] * 100 + ws[0]["part"], {"function": function, "type": typ, "text": _text(ws, ws[0]["corpus"]), "words": [_phrase_word(w) for w in ws]}))
    phrases.sort(key=lambda p: p[0])
    return {"type": cl["clausetype"], "rela": _clause_rela(cl), "kind": _clause_kind(own_all), "rule": cl["rule"], "text": _span_text(con, cl),
            "phrases": [p for _, p in phrases]}


def syntax(book: str, chapter: int, verse: int) -> dict:
    book = book.upper()
    con = _con()
    try:
        corpus = corpus_of(book)
        if not corpus:
            return {"error": f"no corpus mapping for book '{book}'"}
        ids = _clause_ids(con, corpus, book, chapter, verse)
        name = book_name(corpus, book)
        if not ids and not _verse_words(con, corpus, book, chapter, verse):
            return {"error": f"verse not found: {name} {chapter}:{verse}"}
        return {"corpus": _CORPUS[corpus], "corpus_book": name,
                "data": {"corpus": _CORPUS[corpus], "book": name, "chapter": chapter, "verse": verse, "clauses": [_clause_dict(con, i, verse) for i in ids]}}
    finally:
        con.close()


def tree(book: str, chapter: int, verse: int) -> dict:
    book = book.upper()
    con = _con()
    try:
        corpus = corpus_of(book)
        if not corpus:
            return {"error": f"no corpus mapping for book '{book}'"}
        name = book_name(corpus, book)
        ids = _clause_ids(con, corpus, book, chapter, verse)
        if not ids and not _verse_words(con, corpus, book, chapter, verse):
            return {"error": f"verse not found: {name} {chapter}:{verse}"}
        groups: dict = {}
        for i in ids:
            sent = con.execute("SELECT sent FROM words WHERE cl=? LIMIT 1", (i,)).fetchone()["sent"]
            if sent not in groups:
                sw = con.execute(_WORDS_SQL + "WHERE w.sent=? ORDER BY " + TEXT_ORDER, (sent,)).fetchall()
                groups[sent] = {"text": _text([w for w in sw if not w["inserted"]], corpus), "clauses": []}
            groups[sent]["clauses"].append(_clause_dict(con, i, verse))
        return {"corpus": _CORPUS[corpus], "corpus_book": name,
                "data": {"corpus": _CORPUS[corpus], "book": name, "chapter": chapter, "verse": verse, "sentences": list(groups.values())}}
    finally:
        con.close()


def _features(n, otype: str, hebrew: bool, kind: str | None = None) -> dict:
    f = {"otype": otype}
    for k in ("cls", "role", "rule", "type", "junction", "clausetype", "articular", "head"):
        if n[k]:
            f[k] = str(n[k])
    f["typ"] = n["clausetype"] or n["cls"] or ""
    if n["role"]:
        f["function"] = _label(n["role"])
    if otype == "clause":
        f["kind"] = kind or ""
        f["rela"] = _clause_rela(n) or "NA"
    elif n["junction"]:
        f["rela"] = n["junction"]
    return {k: v for k, v in f.items() if v}


def context(book: str, chapter: int, verse: int, word_index: int = 0) -> dict:
    book = book.upper()
    con = _con()
    try:
        corpus = corpus_of(book)
        if not corpus:
            return {"error": f"no corpus mapping for book '{book}'"}
        words = _verse_words(con, corpus, book, chapter, verse)
        name = book_name(corpus, book)
        if not words:
            return {"error": f"Verse not found: {name} {chapter}:{verse}"}
        if word_index >= len(words) or word_index < 0:
            return {"error": f"Word index {word_index} out of range (max {len(words) - 1})"}
        w = words[word_index]
        ctx = {"word": _word_dict(con, w, words[word_index + 1] if word_index + 1 < len(words) else None)}

        def put(key, n, otype):
            if n is None:
                return
            kind = _clause_kind(con.execute(_WORDS_SQL + "WHERE w.cl=?", (n["id"],)).fetchall()) if otype == "clause" else None
            ws = con.execute(_WORDS_SQL + "WHERE w.seq BETWEEN ? AND ? AND w.corpus=? ORDER BY " + TEXT_ORDER, (n["lo"], n["hi"], w["corpus"])).fetchall() if n["lo"] else []
            ctx[key] = {"node": n["id"], "features": _features(n, otype, w["corpus"] == "hbo", kind),
                        "text": _text([x for x in ws if not x["inserted"]], w["corpus"]) if len(ws) < 400 else ""}
        if w["parent"]:
            put("wg", _node(con, w["parent"]), "wg")
        if w["ph"]:
            put("phrase", _node(con, w["ph"]), "phrase")
        else:                                       # a word that is a phrase by itself (role-bearing) or belongs to none (a conjunction): the word stands as its phrase
            feat = {"otype": "phrase", "typ": w["class"] or ""}
            if w["role"]:
                feat.update({"role": w["role"], "function": _label(w["role"])})
            ctx["phrase"] = {"node": -w["seq"], "features": feat, "text": w["surface"]}
        if w["cl"]:
            put("clause", _node(con, w["cl"]), "clause")
        if w["sent"]:
            put("sentence", _node(con, w["sent"]), "sentence")
        return {"corpus": _CORPUS[corpus], "corpus_book": name, "data": ctx}
    finally:
        con.close()


def context_batch(refs: list[tuple[str, int, int]], word_index: int = 0) -> dict:
    out = {}
    for book, chapter, verse in refs:
        try:
            out[f"{book}/{chapter}/{verse}"] = context(book, chapter, verse, word_index)
        except Exception as e:
            out[f"{book}/{chapter}/{verse}"] = {"error": str(e)}
    return out


# ------------------------------------------------------------------------------------------------ who-did-what search
def _canon(raw) -> str | None:
    if raw is None:
        return None
    k = str(raw).strip().lower()
    return _CANON.get(k, k)


def syntax_search(function: str | None = None, strong: str | None = None, lex: str | None = None, book: str | None = None,
                  corpus: str | None = None, limit: int = 50) -> dict:
    """Clauses where a lexeme fills a phrase function. `strong` is H#### or G####; `lex` is a MACULA lexeme id (hbo:6942) for Hebrew or a lemma for Greek."""
    book = book.upper() if book else None
    con = _con()
    try:
        if book:
            c = corpus_of(book)
            if not c:
                return {"error": f"no corpus mapping for book '{book}'"}
        else:
            c = "grc" if (corpus == "greek" or (strong and strong.strip().upper().startswith("G"))) else "hbo"
        want = _canon(function) if function else None
        wanted = _HEBREW_ALSO.get(want, {want}) if (want and c == "hbo") else ({want} if want else None)
        where, args = ["w.corpus=?", "w.inserted=0", "w.cl IS NOT NULL"], [c]
        target: list[str] = []
        if strong:
            m = re.match(r"^([HG])0*(\d+)", strong.strip(), re.I)
            if not m:
                return {"error": "provide lex= or a known strong="}
            if m.group(1).upper() == "H" and c == "hbo":
                where.append("w.strong_n=?"); args.append(int(m.group(2)))
                target = [r[0] for r in con.execute("SELECT DISTINCT lexeme FROM words WHERE corpus='hbo' AND strong_n=? ORDER BY lexeme", (int(m.group(2)),))]
            elif m.group(1).upper() == "G" and c == "grc":
                where.append("w.strong_n=?"); args.append(int(m.group(2)))
                target = [r[0] for r in con.execute("SELECT DISTINCT lemma FROM words WHERE corpus='grc' AND strong_n=? ORDER BY lemma", (int(m.group(2)),))]
            else:
                return {"error": f"strong {strong!r} does not match the corpus of {book or 'the request'}"}
        elif lex:
            where.append("w.lexeme=?")
            args.append(lex); target = [lex]
        if not target:
            return {"error": "provide lex= or a known strong="}
        if book:
            where.append("w.book=?"); args.append(book)
        rows = con.execute("SELECT w.*, p.role AS ph_role FROM words w LEFT JOIN nodes p ON p.id=w.ph WHERE " + " AND ".join(where) + " ORDER BY " + TEXT_ORDER, args).fetchall()
        seen: set = set()
        out = []
        for w in rows:
            fn_raw = w["ph_role"] if w["ph"] is not None else w["role"]
            if wanted is not None and _canon(fn_raw) not in wanted:
                continue
            if w["cl"] in seen:
                continue
            seen.add(w["cl"])
            if w["ph"] is not None:
                pw = con.execute("SELECT surface, after FROM words w WHERE cl=? AND ph=? AND inserted=0 ORDER BY " + TEXT_ORDER, (w["cl"], w["ph"])).fetchall()
            else:
                pw = [w]
            out.append({"book": book_name(c, w["book"]), "chapter": w["chapter"], "verse": w["verse"], "function": _label(fn_raw),
                        "phrase": _text(pw, c), "clause_text": _span_text(con, _node(con, w["cl"]))})
            if len(out) >= limit:
                break
        return {"corpus": _CORPUS[c], "corpus_book": book_name(c, book) if book else None,
                "data": {"corpus": _CORPUS[c], "lex": sorted(target), "strong": strong, "function": function, "count": len(out), "clauses": out}}
    finally:
        con.close()
