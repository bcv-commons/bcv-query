"""Text forms read from the Hebrew and Greek letters by fixed rules: acrostics and refrains (passage facts `fm.tx.*`, from v0.2).

Both rules read only the text's letters (MACULA surface forms without points or accents). Nothing comes from a list of known
passages: the list in check() is the yardstick, not an input.

acrostics(bk, lines)   Hebrew. Units are verses, and MAM's poetic lines where the book has them. A run is units whose first letters
                       follow the alphabet: a unit may start with the expected next letter, repeat the current one (a stanza of
                       several units, Ps 119, Lam 3), or be a filler that starts with another letter (Ps 37's second verse of a
                       pair) when the expected letter follows within 3 units. One letter may be missing (Ps 25, 34, 145) and
                       פ may stand before ע (Lam 2-4). A run counts at 10 or more letters in order. In verse 1 the letter is read
                       after a psalm's title words (לדוד, תהלה לדוד, למנצח ...).
refrains(bk, segs)     Hebrew and Greek. A whole line that comes back: a word sequence of 3 or more words that starts at a clause
                       segment and ends at a segment's end (a sequence of 6 or more words may end anywhere: Ps 42's refrain differs
                       in its last words), recurring in one chapter at least 3 times (or twice when it is 6 words
                       or longer): Gen 1 "evening and morning", Ps 136, Ps 42's refrain, Amos 4. A sequence that opens with a verb of
                       saying (אמר, דבר; λέγω, λαλέω) is a speech formula and is left out. The longest sequence is kept; one with half
                       or more of its occurrences inside a longer kept one is dropped (shifted copies, Num 7).
heading(bk)            Hebrew, Psalms and Habakkuk 3. The psalm headings' own terms, each on its words (`fm.ps.*`): the kind of song
                       (מזמור, שיר, משכיל, מכתם, תפלה, תהלה, שגיון), for the leader (למנצח), the instruments and tunes
                       (בנגינות, אל הנחילות, על השמינית, על הגתית, על שושנים ...), the occasion (להזכיר, לתודה, ליום השבת) and
                       the name it is ascribed to (לדוד, לאסף, לבני קרח ...); read in a psalm's first verse up to its first finite or
                       imperative verb (Hab 3:1, 3:19). And
                       anywhere in those books: סלה, הגיון before סלה, and הללו יה.
halves(bk, poems)      Hebrew, Psalms, Proverbs and Job. Each verse of MAM's poetic lines splits at its main divider accent into
                       half A and half B: oleh-weyored where the verse has it, else atnach (the poetic accents of these three books).
                       In 4,252 of 4,303 verses checked the divider ends a MAM line, so a half is whole lines. With each split:
                       the lines in each half and the echoes: a content word of half B with the same lexeme or the same BDB root
                       as one of half A.
"""
from __future__ import annotations

import collections
import re
import unicodedata
from pathlib import Path

ALEF_BET = "אבגדהוזחטיכלמנסעפצקרשת"
FINAL = str.maketrans("ךםןףץ", "כמנפצ")
POS = {c: i for i, c in enumerate(ALEF_BET)}
MIN_LETTERS = 10
MAX_FILLER = 3
MIN_WORDS = 3
LONG = 6
TITLE = {"לדוד", "למנצח", "מזמור", "תהלה", "תפלה", "משכיל", "מכתם", "שיר", "לשלמה", "לאסף", "לבני", "קרח", "הללויה"}
SPEAK = {_p for _p in ("אמר", "דבר", "λεγω", "λαλεω")}


def _plain(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if not unicodedata.combining(c))


def inquit(bk, i: int) -> bool:
    """Does the sequence open with a verb of saying (a speech formula, not a refrain)? Reads the MACULA lemmas of the word's parts."""
    wid, j, lemmas = bk.keys[i][:11], i, []
    while j < len(bk.keys) and bk.keys[j][:11] == wid:
        lemmas.append(_plain((bk.w.get(bk.keys[j]) or ("", ""))[1]))
        j += 1
    return any(x in SPEAK for x in lemmas)


def first_letter(word: str) -> str | None:
    w = word.translate(FINAL)
    return next((c for c in w if c in POS), None)


def _fits(prev: int, cur: int, skipped: int, swapped: bool) -> tuple[bool, int, bool]:
    """Can letter `cur` follow letter `prev` in a run? Returns (ok, skipped, swapped)."""
    pe, ayin = POS["פ"], POS["ע"]
    if prev == POS["ס"] and cur == pe and not swapped:          # פ before ע (checked before a skip)
        return True, skipped, True
    if cur == prev + 1:
        return True, skipped, swapped
    if cur == prev + 2 and skipped == 0:
        return True, 1, swapped
    if swapped and prev == pe and cur == ayin:
        return True, skipped, swapped
    if swapped and prev == ayin and cur == POS["צ"]:
        return True, skipped, swapped
    return False, skipped, swapped


def _runs(units: list[tuple[int, int, str | None]]) -> list[dict]:
    """units: (first index, last index, first letter). The acrostic runs, each with its units and letters."""
    out, i = [], 0
    while i < len(units):
        if units[i][2] is None:
            i += 1
            continue
        letters = [units[i][2]]
        taken = [(units[i], units[i][2])]
        prev, skipped, swapped, j, filler = POS[units[i][2]], 0, False, i + 1, 0
        while j < len(units):
            ch = units[j][2]
            if ch is not None and POS[ch] == prev and filler == 0:
                taken.append((units[j], ch))              # the same letter again: a stanza
                j += 1
                continue
            ok = False
            if ch is not None:
                ok, sk, sw = _fits(prev, POS[ch], skipped, swapped)
            if ok:
                prev, skipped, swapped, filler = POS[ch], sk, sw, 0
                letters.append(ch)
                taken.append((units[j], ch))
                j += 1
                continue
            look = units[j + 1: j + 1 + MAX_FILLER - filler]
            if any(u[2] is not None and _fits(prev, POS[u[2]], skipped, swapped)[0] for u in look):
                filler += 1
                taken.append((units[j], None))
                j += 1
                continue
            break
        while taken and taken[-1][1] is None:
            taken.pop()
        if len(letters) >= MIN_LETTERS:
            out.append({"units": taken, "letters": letters, "skipped": skipped, "swapped": swapped})
        i += 1                                          # every start is tried; the caller keeps the best run
    return out


def acrostics(bk, lines: dict[int, list[tuple[int, int]]] | None = None) -> list[dict]:
    """Acrostic runs of a Hebrew book, per chapter. lines: chapter -> MAM poetic lines (first, last word index), where there are any.
    Each run: chapter, unit ('verse' / 'line'), units [(first, last, letter or None for a filler)], letters, missing, swapped."""
    if not bk.hebrew:
        return []
    by_ch = collections.defaultdict(list)
    for (c, v), (a, b) in bk.verses.items():
        ws = bk.verse_words.get((c, v)) or []
        k = 0
        while v == 1 and k < len(ws) - 1 and k < 4 and ws[k][1].translate(FINAL) in TITLE:
            k += 1                                      # a psalm's title words before the first letter (לדוד, תהלה לדוד)
        by_ch[c].append((ws[k][0] if ws else a, b, first_letter(ws[k][1]) if ws else None))
    word_at = {i: w for vw in bk.verse_words.values() for i, w in vw}
    out = []
    for c, verses in sorted(by_ch.items()):
        found = [("verse", r) for r in _runs(verses)]
        if lines and lines.get(c):
            units = [(a, b, first_letter(word_at.get(a, ""))) for a, b in lines[c]]
            found += [("line", r) for r in _runs(units)]
        if not found:
            continue
        unit, best = max(found, key=lambda x: (len(x[1]["letters"]), -sum(1 for _, ch in x[1]["units"] if ch is None),
                                                x[0] == "verse"))
        have = set(best["letters"])
        lo, hi = POS[best["letters"][0]], POS[best["letters"][-1]]
        out.append({"chapter": c, "unit": unit, "units": [(u[0], u[1], ch) for u, ch in best["units"]], "letters": best["letters"],
                    "missing": [x for x in ALEF_BET[lo:hi + 1] if x not in have],
                    "swapped": best["swapped"] and "ע" in best["letters"][best["letters"].index("פ"):] if "פ" in best["letters"] else False})
    return out


def refrains(bk, segs: list[dict]) -> list[dict]:
    """Repeated word sequences that start at clause segments, per chapter. Each: chapter, words (normalised), occurrences [(first,
    last) word index]."""
    norm = {}
    for vw in bk.verse_words.values():
        for i, w in vw:
            norm[i] = w.translate(FINAL) if bk.hebrew else w
    order = sorted(norm)
    nxt = {a: b for a, b in zip(order, order[1:])}
    starts, ends = collections.defaultdict(set), set()
    for s in segs:
        if s["words"]:
            i = bk.pos[s["words"][0]]
            while i not in norm and i > 0:
                i -= 1
            starts[s["chapter"]].add(i)
            e = bk.pos[s["words"][-1]]
            while e not in norm and e > 0:
                e -= 1
            ends.add(e)
    out = []
    for c, st in sorted(starts.items()):
        seqs = collections.defaultdict(list)           # tuple of words -> [start index]
        for p in sorted(st):
            ws, i = [], p
            while i is not None and bk.cv(bk.keys[i])[0] == c and len(ws) < 24:
                ws.append(i)
                if len(ws) >= MIN_WORDS and (ws[-1] in ends or len(ws) >= LONG):
                    seqs[tuple(norm[x] for x in ws)].append((p, ws[-1]))
                i = nxt.get(i)
        cand = []
        for t, occ in seqs.items():
            occ = sorted(set(occ))
            keep, last = [], -1
            for a, b in occ:                            # occurrences must not overlap
                if a > last:
                    keep.append((a, b))
                    last = b
            enough = len(keep) >= 3 or (len(keep) >= 2 and len(t) >= LONG)
            if enough and len(set(t)) >= 2 and not inquit(bk, keep[0][0]):
                cand.append((t, keep))
        cand.sort(key=lambda x: (-len(x[0]), x[1][0][0]))
        chosen = []
        for t, occ in cand:
            over = sum(1 for a, b in occ if any(a <= b2 and a2 <= b for _, o2 in chosen for a2, b2 in o2))
            if over * 2 < len(occ):                     # half or more inside a longer kept sequence: a shifted copy, dropped
                chosen.append((t, occ))
        for t, occ in sorted(chosen, key=lambda x: x[1][0][0]):
            out.append({"chapter": c, "words": list(t), "occurrences": occ})
    return out


# heading terms: code -> word forms (unpointed, final letters as plain); a pair (a, b) needs b to follow a
HEADING = {
    "lamnatseach": {"למנצח"}, "mizmor": {"מזמור", "למזמור"}, "shir": {"שיר"}, "maalot": {"המעלות", "למעלות"},
    "maskil": {"משכיל"}, "miktam": {"מכתמ"}, "tefillah": {"תפלה"}, "tehillah": {"תהלה"}, "shiggayon": {"שגיונ", "שגינות"},
    "neginot": {"בנגינות", "בנגינת", "נגינת", "בנגינותי"}, "nechilot": {"הנחילות"}, "sheminit": {"השמינית"},
    "gittit": {"הגתית"}, "alamot": {"עלמות"}, "shoshannim": {"ששנימ", "שושנימ", "שושנ", "ששנ"}, "ayelet": {"אילת"},
    "yonat": {"יונת"}, "al_tashchet": {"תשחת"}, "machalat": {"מחלת"}, "lehazkir": {"להזכיר"}, "letodah": {"לתודה"},
    "lelamed": {"ללמד"}, "shabbat": {"השבת"}, "yedidot": {"ידידת"}, "chanukkat": {"חנכת"}, "mut_labben": {("מות", "לבנ")},
    "david": {"לדוד"}, "asaph": {"לאספ"}, "korah": {("לבני", "קרח")}, "solomon": {"לשלמה"}, "moses": {"למשה"},
    "heman": {"להימנ"}, "ethan": {"לאיתנ"}, "jeduthun": {"ידותונ", "ידיתונ", "לידותונ", "לידיתונ"},
}
ANYWHERE = {"selah": {"סלה"}, "higgayon": {("הגיונ", "סלה")}, "halleluyah": {("הללו", "יה"), "הללויה"}}
HEADING_VERSES = {"PSA": None, "HAB": {(3, 1), (3, 19)}}


def _match(ws: list[tuple[int, str]], table: dict) -> list[tuple[str, int, int]]:
    out = []
    for code, forms in table.items():
        for f in forms:
            for n, (i, w) in enumerate(ws):
                if isinstance(f, tuple):
                    if w == f[0] and n + 1 < len(ws) and ws[n + 1][1] == f[1]:
                        out.append((code, i, ws[n + 1][0] if code != "higgayon" else i))
                elif w == f:
                    out.append((code, i, i))
    return out


_FORMS = {f for fs in HEADING.values() for f in fs if isinstance(f, str)}
FINITE = {"imperative", "qatal", "yiqtol", "wayyiqtol", "weqatal", "jussive", "cohortative"}


def _heading_part(bk, ws: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """The words of a first verse up to its first finite or imperative verb (שירו ליהוה שיר חדש, זכור יהוה לדוד are the psalm's
    own words); a verb right after אשר stays in the heading (אשר דבר, Ps 18:1)."""
    for n, (i, w) in enumerate(ws):
        z = bk.wend.get(i, i)
        if w in _FORMS:
            continue                                    # a heading term that is a verb form itself (אל תשחת)
        if any(bk.wtype.get(bk.keys[j]) in FINITE for j in range(i, z + 1)) and not (n and ws[n - 1][1] == "אשר"):
            return ws[:n]
    return ws


def heading(bk) -> list[tuple[str, int, int]]:
    """(code, first word index, last word index) for each heading term and performance mark (Psalms, Habakkuk 3)."""
    if bk.book not in HEADING_VERSES:
        return []
    out = []
    for (c, v), vw in sorted(bk.verse_words.items()):
        ws = [(i, w.translate(FINAL)) for i, w in vw]
        allowed = HEADING_VERSES[bk.book]
        if (v == 1 and allowed is None) or (allowed and (c, v) in allowed):
            out += _match(_heading_part(bk, ws), HEADING)
        if bk.book == "PSA" or c == 3:
            out += _match(ws, ANYWHERE)
    return sorted(set(out), key=lambda x: x[1])


ATNACH, OLEH, MERKHA = "\u0591", "\u05ab", "\u05a5"
CONTENT = {"noun", "verb", "adj"}
ROOTS = Path(__file__).resolve().parents[2] / "resources" / "bdb_roots" / "root_groups.tsv"


def _h(s: str) -> str | None:
    m = re.match(r"H?0*(\d+)", s or "")
    return "H%04d" % int(m.group(1)) if m else None


def _roots() -> dict[str, str]:
    out = {}
    for line in ROOTS.read_text(encoding="utf-8").splitlines():
        f = line.split("\t")
        if line.startswith("#") or f[0] == "root_id" or len(f) < 2:
            continue
        out[f[1]] = f[0]
    return out


def halves(bk, poems: list[dict], mam_verses: dict, align, words: dict) -> list[dict]:
    """The two halves of each verse of MAM's poetic lines (Psalms, Proverbs, Job), split at the main divider accent.
    poems: mam.poem_lines; mam_verses: mam.verses; align: mam._align; words: key -> (class, strong).
    Each: verse (c, v), accent, halves [(first, last), (first, last)] word indexes, lines [n, n], echoes [(i, j, 'lexeme'|'root')]."""
    if bk.book not in ("PSA", "PRO", "JOB"):
        return []
    roots, out = _roots(), []
    for poem in poems:
        lend = {z for _, z in poem["lines"]}
        for cv in poem["verses"]:
            seq = [x for x in mam_verses.get(cv) or [] if x[0] == "w"]
            ws = [(i, w) for (_, w), i in zip(seq, align(seq, bk.verse_words.get(cv, []))) if i is not None]
            div, accent = None, None
            for n, (i, w) in enumerate(ws):
                if OLEH in w and MERKHA in w:
                    div, accent = i, "oleh_weyored"
                elif OLEH in w and n + 1 < len(ws) and MERKHA in ws[n + 1][1]:
                    div, accent = ws[n + 1][0], "oleh_weyored"
                if div is not None:
                    break
            if div is None:
                div, accent = next((i for i, w in ws if ATNACH in w), None), "atnach"
            if div is None or div not in lend or div == ws[-1][0]:
                continue                                 # no divider, or it does not end a line: no claim
            lines = [(a, z) for a, z in poem["lines"] if bk.cv(bk.keys[a]) == cv]
            a1, b2 = lines[0][0], lines[-1][1]
            b1 = div
            a2 = next(a for a, _ in lines if a > div)
            def content(a, z):
                return [(i, words.get(bk.keys[i])) for i in range(a, bk.wend.get(z, z) + 1)
                        if (words.get(bk.keys[i]) or ("", None))[0] in CONTENT and words[bk.keys[i]][1]]
            echoes = []
            for j, (_, s2) in content(a2, b2):
                for i, (_, s1) in content(a1, b1):
                    if s1 == s2:
                        echoes.append((i, j, "lexeme")); break
                    if roots.get(s1) and roots.get(s1) == roots.get(s2):
                        echoes.append((i, j, "root")); break
            out.append({"verse": cv, "accent": accent, "halves": [(a1, b1), (a2, b2)],
                        "lines": [sum(1 for a, _ in lines if a <= div), sum(1 for a, _ in lines if a > div)], "echoes": echoes})
    return out


KNOWN_ACROSTICS = {("PSA", 9), ("PSA", 10), ("PSA", 25), ("PSA", 34), ("PSA", 37), ("PSA", 111), ("PSA", 112), ("PSA", 119),
                   ("PSA", 145), ("PRO", 31), ("LAM", 1), ("LAM", 2), ("LAM", 3), ("LAM", 4), ("NAM", 1)}
