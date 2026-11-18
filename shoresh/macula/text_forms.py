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
"""
from __future__ import annotations

import collections
import unicodedata

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


KNOWN_ACROSTICS = {("PSA", 9), ("PSA", 10), ("PSA", 25), ("PSA", 34), ("PSA", 37), ("PSA", 111), ("PSA", 112), ("PSA", 119),
                   ("PSA", 145), ("PRO", 31), ("LAM", 1), ("LAM", 2), ("LAM", 3), ("LAM", 4), ("NAM", 1)}
