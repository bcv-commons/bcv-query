#!/usr/bin/env python3
"""Build lxx-glaux.db: the Septuagint word store from GLAUx (KU Leuven, A. Keersmaekers; CC BY-SA 4.0) instead of CATSS/CCAT (non-commercial).

Same table as lxx.db (`lxx_words`) so it can replace it, plus `lemma` and `glaux_id`. Candidate for the NC exit; not wired into the service.

Source: github.com/alekkeersmaekers/glaux, xml/0527-*.xml (TLG 0527 = Septuagint; text from el.wikisource, CC BY-SA 3.0; lemmas, AGDT-style morphology and
dependency syntax: Genesis hand-checked (Pedalion Trees, CC BY-SA 4.0), the rest automatic). Share-alike: this file and everything built from it is CC BY-SA 4.0.
Attribution: Keersmaekers, GLAUx corpus (KU Leuven); Pedalion Trees; el.wikisource.

What is built here, and from what:
  * words, lemma, morphology, POS, verse numbers: GLAUx.
  * strong: lemma -> Strong's number from OPEN sources only (UGNT in spine.db, unfoldingWord CC BY-SA; MACULA Greek in trees-macula.db, CC BY 4.0). Nothing is
    learned from the CATSS-based lxx.db; a lemma that never occurs in the New Testament has no Strong's number, as before.
  * wordid = lexid = a stable id of the lemma (first 31 bits of the SHA-1 of the NFC lemma, probed upward on a collision), so /lxx-lexeme/{wordid} URLs survive
    rebuilds; glaux_id = GLAUx's own word id.
  * morph: CCAT-like display string converted from the AGDT code (N.DSF, V.AAI3S, V.AAPNSM, RA.NSM); indeclinables carry the POS code only. A missing feature
    inside the nominal string is written `-` (N.-SM = number and gender known, case not); trailing gaps are dropped; a name with no features is plain `N`.
  * morph_inferred: GLAUx does not tag case, number or gender of indeclinable names (Ἰσραήλ, Δαυίδ ...). They are filled from the context and listed here:
    `article` (case, number, gender from the article directly before), `preposition` (case from the preposition directly before), `syntax` (case from the
    syntactic relation: attribute -> genitive, subject -> nominative; about 91% right against CATSS, the others about 96-99%). Empty when nothing was inferred.
  * strong_form: the classic (1890) Strong's number of the FORM where it differs from the lemma-level `strong` (μου G3450 against ἐγώ G1473, εἶπεν G2036 against
    λέγω G3004, Ἰερουσαλήμ G2419, Ἰούδα G2448, Σαούλ G4549 ...). A short table of public-domain Strong's numbers (CLASSIC_FORMS), not learned from CATSS.
is_content is 1 for nouns, verbs, adjectives and numerals (the CATSS store counted numerals as adjectives).
Book mapping: TLG 0527-0nn -> our book codes; Esdras II is split into EZR (chapters 1-10) and NEH (11-23, renumbered). Where GLAUx has two versions of a book
(Tobit, Daniel, Susanna, Bel and the Dragon) the one whose words match the existing store best is used when the store is available (--compare), else the first.

  cd shoresh && ../bcv-RAG/.venv/bin/python3 -m lxx.build_glaux [--xml DIR] [--out lxx/data/lxx-glaux.db] [--compare lxx/lxx.db]
"""
from __future__ import annotations

import argparse
import collections
import difflib
import hashlib
import re
import sqlite3
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHORESH = HERE.parent
RAW = "https://raw.githubusercontent.com/alekkeersmaekers/glaux/master/xml/{}.xml"

# TLG 0527 number -> our book code(s); a list means alternative versions of one book (first wins unless --compare picks another)
BOOKS = {1: "GEN", 2: "EXO", 3: "LEV", 4: "NUM", 5: "DEU", 6: "JOS", 9: "JDG", 10: "RUT", 11: "1SA", 12: "2SA", 13: "1KI", 14: "2KI", 15: "1CH", 16: "2CH",
         17: "1ES", 18: "EZR+NEH", 19: "EST", 20: "JDT", 21: "TOB", 22: "TOB", 23: "1MA", 24: "2MA", 25: "3MA", 26: "4MA", 27: "PSA", 28: "ODA", 29: "PRO",
         30: "ECC", 31: "SNG", 32: "JOB", 33: "WIS", 34: "SIR", 35: "PSS", 36: "HOS", 37: "AMO", 38: "MIC", 39: "JOL", 40: "OBA", 41: "JON", 42: "NAM",
         43: "HAB", 44: "ZEP", 45: "HAG", 46: "ZEC", 47: "MAL", 48: "ISA", 49: "JER", 50: "BAR", 51: "LAM", 52: "LJE", 53: "EZK", 54: "SUS", 55: "SUS",
         56: "DAN", 57: "DAN", 58: "BEL", 59: "BEL"}
CANONICAL = set("1CH 1KI 1SA 2CH 2KI 2SA AMO DAN DEU ECC EST EXO EZK EZR GEN HAB HAG HOS ISA JDG JER JOB JOL JON JOS LAM LEV MAL MIC NAM NEH NUM OBA PRO PSA RUT SNG ZEC ZEP".split())
SECTION = re.compile(r"^(?:(\d+)\.)?(\d+)(?!\d)")
GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
CASE = dict(n="N", g="G", d="D", a="A", v="V")
NUM = dict(s="S", p="P", d="D")
GEN = dict(m="M", f="F", n="N")
TENSE = dict(p="P", i="I", r="X", l="Y", t="XF", f="F", a="A")
VOICE = dict(a="A", m="M", p="P", e="P")
MOOD = dict(i="I", s="S", o="O", n="N", m="D", p="P")      # CCAT writes the imperative as D
RP = set("ἐγώ σύ ἡμεῖς ὑμεῖς ἑαυτοῦ ἐμαυτοῦ σεαυτοῦ".split())
RD = set("αὐτός οὗτος ἐκεῖνος ὅδε τοιοῦτος τοσοῦτος τοιόσδε".split())
ADJ_PRON = set("πᾶς ἅπας ἕκαστος ἄλλος ἕτερος ὅλος ἀμφότερος ἑκάτερος οὐδείς μηδείς πολύς ὀλίγος".split())
RR = set("ὅς ὅστις ὅσος οἷος ὁποῖος ὅπως".split())
RI = set("τίς τις".split())


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def plain(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    return unicodedata.normalize("NFC", "".join(c for c in s if not unicodedata.combining(c)).lower())


def compose(pos: str, c: str | None, n: str | None, g: str | None) -> str:
    """POS.CNG with `-` for a gap inside the string, trailing gaps dropped; no feature at all gives the plain POS code."""
    parts = [c or "-", n or "-", g or "-"]
    while parts and parts[-1] == "-":
        parts.pop()
    return f"{pos}.{''.join(parts)}" if parts else pos


def nominal_parts(postag: str) -> tuple[str | None, str | None, str | None]:
    f = (postag + "---------")[:9]
    return CASE.get(f[7]), NUM.get(f[2]), GEN.get(f[6])


def ours_pos_morph(postag: str, lemma: str) -> tuple[str, str]:
    """(POS code, morph string) in the lxx.db style from an AGDT postag."""
    p = postag[0] if postag else "-"
    f = (postag + "---------")[:9]
    c, n, g = nominal_parts(postag)
    if p == "n":
        return "N", compose("N", c, n, g)
    if p == "a":
        return "A", compose("A", c, n, g)
    if p == "l":
        return "RA", compose("RA", c, n, g)
    if p == "p" and lemma in ADJ_PRON:
        return "A", compose("A", c, n, g)
    if p == "p":
        code = "RP" if lemma in RP else "RD" if lemma in RD else "RR" if lemma in RR else "RI" if lemma in RI else "RX"
        return code, compose(code, c, n, g)
    if p == "v":
        t, v, m = TENSE.get(f[3], ""), VOICE.get(f[5], ""), MOOD.get(f[4], "")
        if m == "P":
            return "V", f"V.{t}{v}P{c or ''}{n or ''}{g or ''}"
        if m == "N":
            return "V", f"V.{t}{v}N"
        return "V", f"V.{t}{v}{m}{f[1] if f[1] in '123' else ''}{n or ''}"
    code = {"r": "P", "d": "D", "c": "C", "b": "C", "g": "X", "m": "M", "i": "I"}.get(p, "X")
    return code, code


# ---------------------------------------------------------------- morphology of indeclinable names (inferred from the context, flagged)
PREP_CASE = {"ἐκ": "G", "ἀπό": "G", "πρό": "G", "ἀντί": "G", "ἐν": "D", "σύν": "D", "εἰς": "A", "ἀνά": "A"}
REL_CASE = {"ATR": "G", "SBJ": "N", "SBJ_CO": "N"}


def infer_nominal(words: list[dict], use_syntax: bool = True) -> None:
    """Fill the missing case / number / gender of nouns from the context, in place. words: one verse, in order, each with pos, lemma, parts (c, n, g),
    rel. Rules in order of reliability; sets w['inferred'] to the rules used and rebuilds w['morph']."""
    for i, w in enumerate(words):
        if w["pos"] != "N" or all(w["parts"]):
            continue
        c, n, g = w["parts"]
        used = []
        prev = words[i - 1] if i else None
        if prev and prev["pos"] == "RA" and prev["parts"][0] and prev["parts"][1]:
            pc, pn, pg = prev["parts"]
            if not c: c = pc
            if not n: n = pn
            if not g and pg: g = pg
            used.append("article")
        elif prev and prev["lemma"] in PREP_CASE and not c:
            c = PREP_CASE[prev["lemma"]]
            used.append("preposition")
        elif use_syntax and not c and w.get("rel") in REL_CASE:
            c = REL_CASE[w["rel"]]
            used.append("syntax")
        if used:
            w["parts"] = (c, n, g)
            w["morph"] = compose("N", c, n, g)
            w["inferred"] = ",".join(used)


# ---------------------------------------------------------------- classic (1890) Strong's number of a FORM, where it differs from the lemma-level number
_ego = {"εγω": 1473, "μου": 3450, "μοι": 3427, "με": 3165, "εμου": 1700, "εμοι": 1698, "εμε": 1691, "ημεις": 2249, "ημων": 2257, "ημιν": 2254, "ημας": 2248}
_su = {"συ": 4771, "σου": 4675, "σοι": 4671, "σε": 4571, "υμεις": 5210, "υμων": 5216, "υμιν": 5213, "υμας": 5209}
CLASSIC_FORMS = {("ἐγώ", f): n for f, n in _ego.items()} | {("σύ", f): n for f, n in _su.items()} | {
    ("Ἱεροσόλυμα", "ιερουσαλημ"): 2419,                          # Ἰερουσαλήμ (the Hebrew spelling); UGNT numbers both spellings G2414
    ("Σαῦλος", "σαουλ"): 4549,                                    # Σαούλ, Saul of the Old Testament (Saul / Paul is G4569)
    ("ἄν", "εαν"): 1437,                                          # ἐάν "if", written under the lemma ἄν
    ("οὐ", "ουχι"): 3780,                                         # οὐχί
}
NOT_JUDAH = {"1MA", "2MA", "3MA", "4MA", "TOB", "JDT"}            # there Ἰούδας is the person Judas (G2455)


def classic_number(lemma: str, pl: str, postag: str, book: str) -> int | None:
    """Classic Strong's number of this form when it differs from what the lemma gives; None otherwise."""
    pl_ = pl.rstrip("ν") if lemma not in ("ἐγώ", "σύ") else pl
    if (lemma, pl) in CLASSIC_FORMS:
        return CLASSIC_FORMS[(lemma, pl)]
    f = (postag + "---------")[:9]
    tense = f[3]
    if lemma == "λέγω":
        if tense == "a" and pl.startswith(("ειπ", "επ")):
            return 2036                                           # εἶπον
        if tense in ("f", "r") and pl.startswith(("ερ", "ειρ")):
            return 2046                                           # ἐρῶ / εἴρηκα
    if lemma == "ἐσθίω" and tense == "a" and pl.startswith(("φαγ", "εφαγ")):
        return 5315                                               # φαγεῖν
    if lemma == "Ἰούδας" and pl == "ιουδα" and book not in NOT_JUDAH:
        return 2448                                               # Judah, the tribe and the land
    return None


def strong_table() -> dict[str, int]:
    """lemma (NFC) -> Strong's number from the open Greek sources: UGNT (spine.db) and MACULA Greek (trees-macula.db). Dominant number per lemma."""
    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    sp = SHORESH / "spine" / "spine.db"
    if sp.exists():
        con = sqlite3.connect(f"file:{sp}?mode=ro", uri=True)
        for lem, st in con.execute("SELECT lemma, strong FROM spine_words WHERE lemma IS NOT NULL AND strong IS NOT NULL AND book IN "
                                   "('MAT','MRK','LUK','JHN','ACT','ROM','1CO','2CO','GAL','EPH','PHP','COL','1TH','2TH','1TI','2TI','TIT','PHM','HEB','JAS','1PE','2PE','1JN','2JN','3JN','JUD','REV')"):
            votes[nfc(lem)][int(st)] += 1
    tr = SHORESH / "macula" / "trees-macula.db"
    if tr.exists():
        con = sqlite3.connect(f"file:{tr}?mode=ro", uri=True)
        for lem, st in con.execute("SELECT lemma, strong FROM words WHERE corpus='grc' AND lemma IS NOT NULL AND strong IS NOT NULL"):
            if str(st).isdigit():                               # compound values such as 1417+3461 are skipped
                votes[nfc(lem)][int(st)] += 1
    # Plausibility filter: the open sources contain stray tags (UGNT gives one token of ἐκβαίνω the number of ἑκατοντάρχης G1543, and four tokens of
    # ἐνενήκοντα G1752 = ἕνεκα where MACULA has G1768). A lemma only keeps a number if it carries a real share of that number's tokens.
    per_number: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    for lem, c in votes.items():
        for st, n in c.items():
            per_number[st][lem] += n
    for lem, c in votes.items():
        for st in list(c):
            if c[st] < 0.25 * sum(per_number[st].values()) and c[st] < 10:
                del c[st]
    votes = {lem: c for lem, c in votes.items() if c}
    table = {lem: c.most_common(1)[0][0] for lem, c in votes.items()}
    # accent / breathing / capital variants of a lemma spelling (GLAUx writes names such as Ανανιας or Ἀνανίας where UGNT has Ἁνανίας): match on the
    # accent-stripped lemma when that gives one Strong's number
    by_plain: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for lem, c in votes.items():
        by_plain[plain(lem)].update(c)
    table["__plain__"] = {k: c.most_common(1)[0][0] for k, c in by_plain.items() if len(c) == 1}
    return table


# Orthographic doublets of the Septuagint lemma spelling that the New Testament lemma lists spell differently (Greek orthography and standard Strong's
# headwords, not a CATSS fact). Applied only when the exact and accent-stripped lookups fail.
LEMMA_VARIANTS = {"μείς": "μήν", "ἀείρω": "αἴρω", "πρέσβυς": "πρεσβύτερος", "κύκλος": "κύκλῳ", "ὄμνυμι": "ὀμνύω", "ἀνοίγνυμι": "ἀνοίγω", "ἐθέλω": "θέλω",
                  "βορέας": "βορρᾶς", "φάος": "φῶς", "ρύω": "ῥύομαι", "ἐρύω": "ῥύομαι", "ἀείδω": "ᾄδω", "ἀοιδή": "ᾠδή", "ἐκπορεύω": "ἐκπορεύομαι",
                  "εἰσπορεύω": "εἰσπορεύομαι", "ἐμπίμπλημι": "ἐμπίπλημι", "ἵλαος": "ἵλεως", "νόος": "νοῦς", "ἐξουδενόω": "ἐξουθενέω", "ἐξουδενέω": "ἐξουθενέω", "τεσσαράκοντα": "τεσσεράκοντα", "πλησίος": "πλησίον", "ἑκατόνταρχος": "ἑκατοντάρχης"}
# Standard Strong's numbers (public-domain lexicon) of Septuagint lemmas that the UGNT / MACULA lemma lists do not carry under any spelling.
STRONG_OVERRIDE = {"ἰδού": 2400}


def lemma_candidates(lemma: str):
    yield lemma
    if lemma in LEMMA_VARIANTS:
        yield LEMMA_VARIANTS[lemma]
    yield lemma.replace("γιγν", "γιν")                         # γίγνομαι, παραγίγνομαι, ἐπιγιγνώσκω, ἀναγιγνώσκω
    yield lemma.replace("ρρ", "ρ")
    if lemma.endswith("εος"):                                    # material adjectives: χρύσεος -> χρυσοῦς
        yield lemma[:-3] + "οῦς"
    if lemma.endswith("ω"):                                      # active / deponent doublets: ἐπιλαμβάνω ~ ἐπιλαμβάνομαι
        yield lemma[:-1] + "ομαι"
    if lemma.endswith("ομαι"):
        yield lemma[:-4] + "ω"
    if lemma.endswith("όω"):
        yield lemma[:-2] + "έω"


def lookup_strong(table: dict, lemma: str) -> int | None:
    """Strong's number of a GLAUx lemma: exact (NFC) match, then spelling variants, each also accent-stripped (when that gives one number)."""
    plain_table = table["__plain__"]
    if lemma in STRONG_OVERRIDE:
        return STRONG_OVERRIDE[lemma]
    for cand in lemma_candidates(lemma):
        if cand in table:
            return table[cand]
        v = plain_table.get(plain(cand))
        if v is not None:
            return v
    pl = plain(lemma)                                             # rules that must ignore accents: γίγνομαι, παραγίγνομαι, ἐπιγιγνώσκω -> γινομαι ...
    for a, b in (("γιγν", "γιν"), ("ρρ", "ρ")):
        if a in pl:
            v = plain_table.get(pl.replace(a, b))
            if v is not None:
                return v
    return None


def parse(path: Path) -> list[tuple]:
    """[(chapter, verse, form, lemma, postag, glaux_id, relation)] of the words (punctuation dropped) of one GLAUx document."""
    out = []
    for _, el in ET.iterparse(path):
        if el.tag == "word":
            form, sec = el.get("form") or "", el.get("div_section") or ""
            tag = el.get("postag") or "-"
            m = SECTION.match(sec)                              # "1.5", or "5" in a one-chapter book; a range such as "11-DIV=14" counts as its first verse
            if tag[0] != "u" and GREEK.search(form) and m:
                out.append((int(m.group(1) or 1), int(m.group(2)), nfc(form), nfc(el.get("lemma") or ""), tag, int(el.get("id") or 0), el.get("relation") or ""))
            el.clear()
    return out


def fetch(xmldir: Path, num: int) -> Path:
    name = f"0527-{num:03d}"
    p = xmldir / f"{name}.xml"
    if not p.exists():
        xmldir.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(RAW.format(name), p)
    return p


def match_score(rows, book: str, ref_db: sqlite3.Connection) -> float:
    ours = collections.defaultdict(list)
    for ch, v, pl in ref_db.execute("SELECT chapter, verse, plain FROM lxx_words WHERE book=? ORDER BY chapter, verse, idx", (book,)):
        ours[(ch, v)].append(pl.lower().rstrip("ν"))
    theirs = collections.defaultdict(list)
    for ch, v, form, *_ in rows:
        theirs[(ch, v)].append(plain(form).rstrip("ν"))
    tot = hit = 0
    for k, a in ours.items():
        b = theirs.get(k, [])
        tot += len(a)
        hit += sum(blk.size for blk in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    return hit / tot if tot else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xml", type=Path, default=HERE / "data" / "glaux", help="directory with (or to download) the GLAUx 0527-*.xml files")
    ap.add_argument("--out", type=Path, default=HERE / "data" / "lxx-glaux.db")
    ap.add_argument("--no-syntax", action="store_true", help="do not infer the case of names from the syntactic relation (article and preposition rules only)")
    ap.add_argument("--compare", type=Path, default=HERE / "lxx.db", help="existing store, only used to pick between two GLAUx versions of a book")
    a = ap.parse_args()
    ref = sqlite3.connect(f"file:{a.compare}?mode=ro", uri=True) if a.compare and a.compare.exists() else None

    docs: dict[str, list] = collections.defaultdict(list)           # book -> [(num, rows)]
    for num, book in BOOKS.items():
        docs[book].append((num, parse(fetch(a.xml, num))))
    chosen: dict[str, tuple[int, list]] = {}
    for book, versions in docs.items():
        if len(versions) == 1 or ref is None or "+" in book:
            chosen[book] = versions[0]
        else:
            scores = [(match_score(rows, book, ref), num) for num, rows in versions]
            best = max(scores)[1]
            chosen[book] = next(v for v in versions if v[0] == best)
            print(f"{book}: versions {[(n, round(s, 3)) for s, n in scores]} -> 0527-{best:03d}", file=sys.stderr)

    strong = strong_table()
    lemma_ids: dict[str, int] = {}
    words = []
    for book, (num, rows) in sorted(chosen.items()):
        for ch, v, form, lemma, tag, gid, rel in rows:
            bk, c = book, ch
            if book == "EZR+NEH":
                bk, c = ("EZR", ch) if ch <= 10 else ("NEH", ch - 10)
            words.append((bk, c, v, form, lemma, tag, gid, rel))
    taken: set[int] = set()
    for lemma in sorted({w[4] for w in words}):
        lid = int.from_bytes(hashlib.sha1(lemma.encode("utf-8")).digest()[:4], "big") & 0x7FFFFFFF
        while lid in taken or lid == 0:
            lid = (lid + 1) & 0x7FFFFFFF
        taken.add(lid)
        lemma_ids[lemma] = lid
    words.sort(key=lambda w: (w[0], w[1], w[2]))

    a.out.parent.mkdir(parents=True, exist_ok=True)
    if a.out.exists():
        a.out.unlink()
    con = sqlite3.connect(a.out)
    con.executescript("""
    CREATE TABLE lxx_words (
      book TEXT NOT NULL, chapter INTEGER NOT NULL, verse INTEGER NOT NULL, idx INTEGER NOT NULL,
      surface TEXT NOT NULL, plain TEXT NOT NULL, strong INTEGER, lexid INTEGER, wordid INTEGER,
      morph TEXT, pos TEXT, is_content INTEGER NOT NULL, canonical INTEGER NOT NULL,
      lemma TEXT NOT NULL, glaux_id INTEGER, strong_form INTEGER, morph_inferred TEXT,
      PRIMARY KEY (book, chapter, verse, idx));
    CREATE INDEX idx_lxx_strong ON lxx_words(strong);
    CREATE INDEX idx_lxx_lexid ON lxx_words(lexid);
    CREATE INDEX idx_lxx_strong_form ON lxx_words(strong_form);
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);""")
    n = 0
    verses = collections.OrderedDict()
    for w in words:
        verses.setdefault(w[:3], []).append(w)
    stats = collections.Counter()
    for (bk, c, v), ws in verses.items():
        items = []
        for form, lemma, tag, gid, rel in (w[3:] for w in ws):
            pos, morph = ours_pos_morph(tag, lemma)
            items.append({"form": form, "lemma": lemma, "tag": tag, "gid": gid, "rel": rel, "pos": pos, "morph": morph,
                          "parts": nominal_parts(tag) if pos in ("N", "A", "RA") else (None, None, None), "inferred": ""})
        infer_nominal(items, use_syntax=not a.no_syntax)
        for i, w in enumerate(items, 1):
            lid = lemma_ids[w["lemma"]]
            st = lookup_strong(strong, w["lemma"])
            pl = plain(w["form"])
            sf = classic_number(w["lemma"], pl, w["tag"], bk)
            if sf == st:
                sf = None
            stats["inferred " + w["inferred"]] += 1 if w["inferred"] else 0
            con.execute("INSERT INTO lxx_words VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (bk, c, v, i, w["form"], pl, st, lid, lid, w["morph"], w["pos"], int(w["pos"] in ("N", "V", "A", "M")), int(bk in CANONICAL),
                         w["lemma"], w["gid"], sf, w["inferred"] or None))
            n += 1
    print(f"inferred morphology: { {k: c for k, c in stats.items() if c} }", file=sys.stderr)
    meta = {"source": "GLAUx (KU Leuven), github.com/alekkeersmaekers/glaux, xml/0527-*.xml", "license": "CC BY-SA 4.0 (texts: el.wikisource CC BY-SA 3.0)",
            "strong_sources": "UGNT (unfoldingWord, CC BY-SA 4.0) and MACULA Greek (CC BY 4.0); no CATSS input",
            "morph_inferred": "article, preposition, syntax (see the module docstring)", "strong_form": "CLASSIC_FORMS table, public-domain Strong's numbers",
            "documents": ",".join(f"{b}=0527-{v[0]:03d}" for b, v in sorted(chosen.items()))}
    con.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
    con.commit()
    with_strong = con.execute("SELECT count(*) FROM lxx_words WHERE strong IS NOT NULL").fetchone()[0]
    print(f"{a.out}: {n} words, {len(lemma_ids)} lemmas, {len(chosen)} books, Strong's on {with_strong} words = {100 * with_strong / n:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
