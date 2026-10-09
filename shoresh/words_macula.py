"""The /words vocabulary feed on MACULA tokens (NC exit, step 3b; design: internal-docs/nc-exit-step3-structure-design.md).

Replaces cf_engine.list_words_filtered (BHSA lexemes, resources/word_freq/*.tsv keyed by BHSA lex) when STRUCTURE_BASE=macula. Same response, same query vocabulary:
the BHSA-style codes of the API (pos: subs verb prep conj art prde prin advb nmpr intj nega inrg ...; stem: qal nif piel pual hif hof hit ...; tense: perf impf wayq impv
infc infa ptca ptcp for Hebrew, aor pres fut perf imperf plup for Greek) are translated at the edge to MACULA's class / verb form / stem, and MACULA names are accepted too.
What changes: `lex` is a MACULA lexeme id (hbo:6942) for Hebrew (the lemma for Greek, as before), `node` is the token's sequence number in trees-macula.db, `rank` counts
MACULA lexeme occurrences (prefix and suffix tokens are tokens of their own, as BHSA's prefix words were), `sfx` is true when a pronominal suffix token follows in the same
word (BHSA's `prs` flagged articles and particles too), `ref` of Hebrew words is in Hebrew numbering.
The pos table was checked against BHSA's `sp` through the BHSA<->MACULA bridge (macula/compare_words_bases.py reports the agreement).
"""
from __future__ import annotations

import functools
import random as _random

import trees_macula as T

# BHSA-style part-of-speech code <- (MACULA class, verb/pronoun/adverb type or None for any)
HBO_POS = [
    ("nmpr", "noun", "proper"), ("adjv", "noun", "gentilic"), ("verb", "noun", "participle active"), ("subs", "noun", None),
    ("verb", "verb", None), ("prep", "prep", None), ("prep", "om", None), ("conj", "cj", None), ("conj", "rel", None),
    ("nega", "adv", "negative"), ("inrg", "adv", "interrogative"), ("subs", "adv", "common"), ("verb", "adv", "infinitive absolute"), ("advb", "adv", None),
    ("prde", "adj", "demonstrative"), ("subs", "adj", "common"), ("adjv", "adj", None), ("subs", "num", None),
    ("prps", "pron", "personal"), ("prin", "pron", "interrogative"), ("prps", "pron", None),
    ("art", "art", None), ("intj", "ij", None), ("inrg", "ptcl", None), ("prep", "x", None),
]
GRC_POS = {"verb": "verb", "noun": "noun", "adj": "adj", "adv": "adv", "prep": "prep", "conj": "conj", "det": "det", "pron": "pron", "ptcl": "ptcl", "intj": "intj", "num": "num"}
HBO_TENSE = {"qatal": "perf", "weqatal": "perf", "yiqtol": "impf", "jussive": "impf", "cohortative": "impf", "wayyiqtol": "wayq", "imperative": "impv",
             "infinitive construct": "infc", "infinitive absolute": "infa", "participle active": "ptca", "participle passive": "ptcp"}
GRC_TENSE = {"aorist": "aor", "present": "pres", "future": "fut", "perfect": "perf", "imperfect": "imperf", "pluperfect": "plup"}
STEM_CODE = {"niphal": "nif", "hiphil": "hif", "hophal": "hof", "hithpael": "hit", "hitpael": "hit"}        # the rest (qal piel pual ...) are the same word
STEM_NAME = {v: k for k, v in STEM_CODE.items()}


def bhsa_pos(cls: str | None, typ: str | None) -> str:
    for code, c, t in HBO_POS:
        if c == cls and (t is None or t == typ):
            return code
    return cls or ""


def _pos_conditions(codes: list[str]) -> tuple[str, list]:
    """SQL for Hebrew `pos` codes (BHSA style, or MACULA class names)."""
    parts, args = [], []
    for code in codes:
        matched = False
        for c, cls, typ in HBO_POS:
            if c == code:
                matched = True
                if typ is None:
                    # rules listed before this one for the same class take precedence: exclude their types
                    earlier = [t for (cc, k, t) in HBO_POS[:HBO_POS.index((c, cls, typ))] if k == cls and t is not None and cc != code]
                    sql = "(w.class=?" + (" AND COALESCE(w.wtype,'') NOT IN (" + ",".join("?" * len(earlier)) + ")" if earlier else "") + ")"
                    parts.append(sql); args += [cls] + earlier
                else:
                    parts.append("(w.class=? AND w.wtype=?)"); args += [cls, typ]
        if not matched:
            parts.append("w.class=?"); args.append(code)
    return "(" + " OR ".join(parts) + ")" if parts else "0", args


NOT_SUFFIX = "NOT (w.class='pron' AND w.wtype='pronominal')"


@functools.lru_cache(maxsize=4)
def _ranks(db_stamp: str, corpus: str) -> dict[str, int]:
    """{lexeme (Hebrew) or lemma (Greek): rank}, rank 0 = most frequent."""
    con = T._con()
    try:
        if corpus == "hbo":
            rows = con.execute("SELECT w.lexeme, COUNT(*) n FROM words w WHERE w.corpus='hbo' AND w.inserted=0 AND w.lexeme LIKE 'hbo:%' AND NOT (w.class='pron' AND w.wtype='pronominal') GROUP BY w.lexeme ORDER BY n DESC, w.lexeme").fetchall()
        else:
            rows = con.execute("SELECT lexeme, COUNT(*) n FROM words WHERE corpus='grc' AND inserted=0 GROUP BY lexeme ORDER BY n DESC, lexeme").fetchall()
    finally:
        con.close()
    return {r[0]: i for i, r in enumerate(rows)}


def ranks(corpus: str) -> dict[str, int]:
    return _ranks(str(T.trees_path().stat().st_mtime_ns), corpus)


def _strong_code(corpus: str, strong_n, strong_raw) -> str | None:
    if corpus == "hbo":
        return f"H{int(strong_n):04d}" if strong_n else None
    try:
        return f"G{int(strong_raw):04d}"
    except (TypeError, ValueError):
        return None


def list_words_filtered(corpus: str = "hebrew", language: str | None = None, pos: list[str] | None = None, stem: list[str] | None = None,
                        tense: list[str] | None = None, suffix: bool | None = None, min_rank: int | None = None, max_rank: int | None = None,
                        limit: int = 50, random_sample: bool = False, order: str = "pool", lex_filter: set | None = None) -> dict:
    c = "hbo" if corpus == "hebrew" else "grc"
    hebrew = c == "hbo"
    rk = ranks(c)
    where, args = ["w.corpus=?", "w.inserted=0"], [c]
    join = ""
    key_col = "w.lexeme"
    if hebrew:
        where.append("w.lexeme LIKE 'hbo:%'")
        where.append(NOT_SUFFIX)                       # a pronominal suffix is not a word of its own in the feed (BHSA kept it as a feature of the word before it)
        if language == "Hebrew":
            where.append("COALESCE(w.wlang,'H')='H'")
        elif language == "Aramaic":
            where.append("w.wlang='A'")
    if pos:
        if hebrew:
            sql, a = _pos_conditions(pos); where.append(sql); args += a
        else:
            wanted = [k for k, v in GRC_POS.items() if v in pos or k in pos]
            where.append("w.class IN (" + ",".join("?" * len(wanted)) + ")" if wanted else "0"); args += wanted
    if stem:
        if hebrew:
            names = {STEM_NAME.get(x, x) for x in stem}
            where.append("w.stem IN (" + ",".join("?" * len(names)) + ")"); args += sorted(names)
        # Greek: the old view had no stem (voice is reported as `stem` but was never a filter)
    if tense:
        if hebrew:
            forms = [k for k, v in HBO_TENSE.items() if v in tense or k in tense]
            where.append("w.class='verb' AND w.wtype IN (" + ",".join("?" * len(forms)) + ")" if forms else "0"); args += forms
        else:
            names = [k for k, v in GRC_TENSE.items() if v in tense or k in tense]
            where.append("w.class='verb' AND w.tense IN (" + ",".join("?" * len(names)) + ")" if names else "0"); args += names
    if suffix is not None and hebrew:
        where.append("COALESCE(w.sfx,0)=?"); args.append(1 if suffix else 0)
    con = T._con()
    try:
        rows = con.execute(f"SELECT w.seq, {key_col} FROM words w {join} WHERE " + " AND ".join(where) + " ORDER BY w.seq", args).fetchall()
        matching = []
        for seq, lex in rows:
            r = rk.get(lex, 999999)
            if (min_rank is not None and r < min_rank) or (max_rank is not None and r > max_rank):
                continue
            if lex_filter is not None and lex not in lex_filter:
                continue
            matching.append((seq, lex))
        total = len(matching)
        if order in ("frequency", "rare"):
            by: dict = {}
            for seq, lex in matching:
                by.setdefault(lex, []).append(seq)
            reps = [(_random.choice(v), k) for k, v in by.items()]
            reps.sort(key=lambda x: rk.get(x[1], 10**9), reverse=(order == "rare"))
            selected = reps[:limit]
        elif order == "random" or random_sample:
            selected = _random.sample(matching, min(limit, total))
        else:
            selected = matching[:limit]
        words = [_word(con, c, seq, lex, rk, language) for seq, lex in selected]
    finally:
        con.close()
    return {"total_pool": total, "count": len(words), "words": words}


def _word(con, c: str, seq: int, lex: str, rk: dict, language: str | None) -> dict:
    hebrew = c == "hbo"
    w = con.execute(T._WORDS_SQL + "WHERE w.seq=?", (seq,)).fetchone()
    if hebrew:
        pos = bhsa_pos(w["class"], w["wtype"])
        stem = STEM_CODE.get(w["stem"], w["stem"]) if w["stem"] else "NA"
        tense = HBO_TENSE.get(w["wtype"], "NA") if w["class"] == "verb" else "NA"
        lang = "Aramaic" if w["wlang"] == "A" else "Hebrew"
        name = T.book_name("hbo", w["book"])
    else:
        pos, stem, tense, lang, name = GRC_POS.get(w["class"], w["class"] or ""), w["voice"] or "NA", w["tense"] or "NA", "", w["book"]
    lo, hi = (None, None)
    nid = (w["cl"] or w["sent"]) if hebrew else w["sent"]          # a word outside any clause (a lone conjunction) shows its sentence
    node = con.execute("SELECT lo, hi FROM nodes WHERE id=?", (nid,)).fetchone() if nid else None
    clause_words, target = [], 0
    if node and node["lo"] is not None:
        cw = con.execute("SELECT seq, surface, after, inserted, cl FROM words w WHERE seq BETWEEN ? AND ? ORDER BY " + T.TEXT_ORDER, (node["lo"], node["hi"])).fetchall()
        for x in cw:
            if x["inserted"] or (hebrew and w["cl"] and x["cl"] != w["cl"]):
                continue
            if x["seq"] == seq:
                target = len(clause_words)
            after = x["after"] or ""
            clause_words.append((x["surface"] or "") + (after + " " if (c == "grc" and after and not after.endswith(" ")) else after))
    return {"node": seq, "lex": lex, "lexUtf8": w["lemma"] or "", "language": lang if hebrew else "", "pos": pos, "stem": stem, "tense": tense,
            "rank": rk.get(lex, 999999), "sfx": bool(w["sfx"]) if hebrew else False, "gloss": w["gloss"] or "",
            "strong": _strong_code(c, w["strong_n"], w["strong"]), "ref": f"{name} {w['chapter']}:{w['verse']}", "clauseWords": clause_words, "targetIndex": target}
