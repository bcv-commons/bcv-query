#!/usr/bin/env python3
"""Mahberet Menahem: words Menahem ben Saruq explains with another Hebrew word. Hebrew explaining Hebrew.

Mahberet Menahem (10th c., the first Hebrew-language dictionary of the Bible) splits each root into
numbered divisions by meaning ("מתחלק לשני מחלקות: האחד, ... השני, ..."). A division cites verses, the
cited word in bold, and often names its sense with ענין: `השני, תחת שערה <b>באשה</b> (איוב לא, מ) ...
ענין קוצים הם` ("the second: ... in the sense of thorns"). Hebrew text Public Domain (London 1854 edition),
via Sefaria.

Extraction, the same narrow pattern as build_metzudat_zion.py:
  - each cited bold word is resolved through its own verse in lexeme-spine.db (surface or lemma,
    consonants only, trying up to two prefix letters removed); "שם" in a citation repeats the last book;
  - the sense word is the word after ענין in that division; it is resolved by consonants against Biblical
    Hebrew lemmas and kept only if it names exactly one content Strong's number;
  - a pair = (a cited word's Strong's, the sense word's Strong's), different, names and function words
    dropped. Divisions that only cite the same root's derivatives give no pair here: BDB and Radak
    already cover root families.

  cd shoresh && .venv/bin/python3 -m macula.build_mahberet_menahem            # fetch (resumable) + extract
  cd shoresh && .venv/bin/python3 -m macula.build_mahberet_menahem --no-fetch
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine.common import to_modern_form  # noqa: E402

from macula.build_metzudat_zion import PREFIXES, _bare_index, _get, _resolve_gloss, excluded  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine.db"
CACHE = HERE / "data" / "mahberet_menahem_letters.jsonl"
OUT = ROOT / "resources" / "mahberet_menahem" / "candidate_pairs.tsv"
LETTERS = ["Alef", "Bet", "Gimel", "Daled", "Heh", "Vav", "Zayin", "Chet", "Tet", "Yod", "Kaf", "Lamed",
           "Mem", "Nun", "Samekh", "Ayin", "Peh", "Tzadi", "Kof", "Resh", "Shin", "Tav"]
# Hebrew book names and abbreviations as Menahem's citations write them -> spine book codes
HEB_BOOKS = {
    "בראשית": "GEN", "שמות": "EXO", "ויקרא": "LEV", "במדבר": "NUM", "דברים": "DEU", "יהושע": "JOS",
    "שופטים": "JDG", "רות": "RUT", "ש\"א": "1SA", "שמואל א": "1SA", "ש\"ב": "2SA", "שמואל ב": "2SA",
    "מ\"א": "1KI", "מלכים א": "1KI", "מ\"ב": "2KI", "מלכים ב": "2KI", "ישעיהו": "ISA", "ישעיה": "ISA",
    "ירמיהו": "JER", "ירמיה": "JER", "יחזקאל": "EZK", "הושע": "HOS", "יואל": "JOL", "עמוס": "AMO",
    "עובדיה": "OBA", "יונה": "JON", "מיכה": "MIC", "נחום": "NAM", "חבקוק": "HAB", "צפניה": "ZEP",
    "חגי": "HAG", "זכריה": "ZEC", "מלאכי": "MAL", "תהלים": "PSA", "תהלות": "PSA", "משלי": "PRO",
    "איוב": "JOB", "שיר השירים": "SNG", "שה\"ש": "SNG", "איכה": "LAM", "קהלת": "ECC", "אסתר": "EST",
    "דניאל": "DAN", "עזרא": "EZR", "נחמיה": "NEH", "דה\"א": "1CH", "דברי הימים א": "1CH",
    "דה\"ב": "2CH", "דברי הימים ב": "2CH",
    # abbreviations and misprints as they occur in the 1854 edition's citations
    "שיר": "SNG", "עמום": "AMO", "ההלים": "PSA", "יחקאל": "EZK", "חבקוקו": "HAB",
}
_GEM = {c: v for c, v in zip("אבגדהוזחטיכלמנסעפצקרשת", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 30, 40, 50, 60,
                                                       70, 80, 90, 100, 200, 300, 400])}
_ORDINALS = r"(?:האחד|האחת|השני|השנית|השלישי|השלישית|הרביעי|הרביעית|החמישי|החמישית|הששי|הששית|השביעי|השמיני|התשיעי|העשירי)"
_CITE = re.compile(r"<b>([^<]+)</b>([^<]*?)<small>\(([^)]+)\)</small>")


def gematria(s: str) -> int | None:
    s = re.sub(r"[\"'״׳\s]", "", s)
    if not s or any(c not in _GEM for c in s):
        return None
    return sum(_GEM[c] for c in s)


def fetch() -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if CACHE.exists():
        done = {json.loads(l)["ref"] for l in CACHE.read_text(encoding="utf-8").splitlines() if l}
    with CACHE.open("a", encoding="utf-8") as fh:
        for letter in LETTERS:
            ref = f"Machberet Menachem, Letter {letter}"
            if ref in done:
                continue
            d = _get(ref)
            v = (d or {}).get("versions") or []
            if not v or not v[0].get("text"):
                print(f"[menahem] nothing for {ref}", file=sys.stderr)
                continue
            fh.write(json.dumps({"ref": ref, "license": v[0].get("license"), "version": v[0].get("versionTitle"),
                                 "entries": v[0]["text"]}, ensure_ascii=False) + "\n")
            fh.flush()
            time.sleep(0.3)
            print(f"[menahem] {letter}: {len(v[0]['text'])} entries", file=sys.stderr)


def parse_ref(text: str, last_book: str | None, last_chapter: int | None = None
              ) -> tuple[str | None, int | None, int | None]:
    """'שמות כה, יד' -> (EXO, 25, 14). 'שם' repeats the last book; 'שם, ו' = same book and chapter, verse 6.
    Typographic gershayim and invisible direction marks are normalised first."""
    text = re.sub(r"[\u200e\u200f]", "", text).replace("״", '"').replace("׳", "'").strip().rstrip(",")
    m = re.match(r"^(.*?)\s*([א-ת\"']+)\s*,\s*([א-ת\"']+)\s*$", text)
    if not m:
        m2 = re.match(r"^שם\s*,\s*([א-ת\"']+)$", text)
        if m2 and last_book and last_chapter:
            return last_book, last_chapter, gematria(m2.group(1))
        return last_book, None, None
    book_txt = m.group(1).strip()
    book = last_book if book_txt in ("שם", "") else HEB_BOOKS.get(book_txt)
    return book, gematria(m.group(2)), gematria(m.group(3))


def verse_words(conn, book, ch, vs):
    return [(to_modern_form(s, "hbo"), to_modern_form(l, "hbo") if l else None, f"H{int(st):04d}")
            for s, l, st in conn.execute(
                "SELECT surface, lemma, strong FROM spine_words WHERE book=? AND chapter=? AND verse=? "
                "AND strong IS NOT NULL AND lexeme LIKE 'hbo:%'", (book, ch, vs))]


def resolve_cited(word: str, vwords, drop: set[str]) -> set[str]:
    b = to_modern_form(word, "hbo")
    for k in range(3):                       # as written, then up to two prefix letters removed
        if k and (len(b) <= 2 or b[0] not in PREFIXES):
            break
        if k:
            b = b[1:]
        hits = {s for sb, lb, s in vwords if b and (b == sb or b == lb) and s not in drop}
        if hits:
            return hits
    return set()


def extract() -> collections.Counter:
    drop = excluded()
    idx = _bare_index(drop)
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    pairs: collections.Counter = collections.Counter()
    stats = collections.Counter()
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        for entry in row["entries"]:
            if not isinstance(entry, list) or len(entry) < 2:
                continue
            body = " ".join(x for x in entry[1:] if isinstance(x, str))
            stats["entries"] += 1
            divisions = re.split(_ORDINALS + r"\s*,", body)
            for div in divisions:
                m = re.search(r"ענין\s+([א-ת][א-ת֑-ׇ]*)", re.sub(r"<[^>]+>", " ", div))
                if not m:
                    continue
                stats["divisions_with_inyan"] += 1
                sense = _resolve_gloss(m.group(1), idx)
                if len(sense) != 1:
                    continue
                stats["sense_resolved"] += 1
                last_book = None
                cited = set()
                for word, _between, ref in _CITE.findall(div):
                    book, ch, vs = parse_ref(ref, last_book)
                    if not book or not ch or not vs:
                        continue
                    last_book = book
                    cited |= resolve_cited(word, verse_words(sp, book, ch, vs), drop)
                for c in cited - sense:
                    pairs[frozenset({c} | sense)] += 1
                    stats["pairs"] += 1
    print(f"[menahem] {dict(stats)} -> {len(pairs)} distinct pairs", file=sys.stderr)
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--senses", action="store_true",
                    help="write resources/mahberet_menahem/senses.tsv (sense inventory) and stop")
    args = ap.parse_args()
    if not args.no_fetch:
        fetch()
    if args.senses:
        write_senses(senses())
        return 0
    pairs = extract()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write("# CANDIDATE Hebrew Strong's pairs from Mahberet Menahem (Menahem ben Saruq, 10th c.; Hebrew text "
                 "Public Domain,\n# London 1854, via Sefaria): a cited word and the Hebrew word naming its sense "
                 "(ענין). Derived data CC0.\n# `count` = number of divisions giving the pair. See "
                 "shoresh/macula/build_mahberet_menahem.py.\n")
        fh.write("strong_a\tstrong_b\tcount\n")
        for pair, cnt in sorted(pairs.items(), key=lambda kv: (-kv[1], sorted(kv[0]))):
            if len(pair) == 2:
                a, b = sorted(pair)
                fh.write(f"{a}\t{b}\t{cnt}\n")
    print(f"[menahem] -> {OUT}", file=sys.stderr)
    return 0



# ---------- sense inventory (Hebrew) for word studies and /verse ----------

SENSES = ROOT / "resources" / "mahberet_menahem" / "senses.tsv"


def _sense_phrase(text: str) -> str:
    """The division's own sense words: 'ענין X Y' up to punctuation, or כמשמעו ('as it sounds'); else ''."""
    m = re.search(r"(ענין\s+[^.,:;()]+)", text)
    if m:
        return re.sub(r"\s+(הם|הוא|היא|הן)\s*$", "", m.group(1).strip())
    return "כמשמעו" if "כמשמעו" in text else ""


def _anchor_citation(sp, word: str, book: str, ch: int, vs: int):
    """(word unit, how): the cited verse; then each word of a multi-word citation; then verses +-1/+-2 (the 1854
    edition's numbering is sometimes off); then a word occurring exactly once in the chapter (wrong verse
    number). Every step still requires the word itself to match."""
    from macula.build_metzudat_zion import _anchor, _verse_word_units

    def exact(w, us):
        """Wider searches use only exact whole-word or lemma matches of 3+ letters (a sampled 20% error rate
        with the looser rules: הוות -> ממות, מעל -> על)."""
        h = to_modern_form(w, "hbo")
        if len(h) < 3:
            return None
        hit = [u for u in us if u["surface"] == h or any(h == p[0] for p in u["parts"])]
        return hit[0] if len(hit) == 1 else None

    words = word.split()
    units = _verse_word_units(sp, book, ch, vs)
    u = _anchor(words[0], units)
    if u:
        return u, "verse"
    for w in words[1:]:
        u = exact(w, units)
        if u:
            return u, "verse_other_word"
    for d in (-1, 1, -2, 2):
        u = _anchor(words[0], _verse_word_units(sp, book, ch, vs + d)) if vs + d > 0 else None
        if u:
            return u, "neighbour_verse"
    hits = []
    n_vs = sp.execute("SELECT MAX(verse) FROM spine_words WHERE book=? AND chapter=?", (book, ch)).fetchone()[0] or 0
    for v in range(1, n_vs + 1):
        u = exact(words[0], _verse_word_units(sp, book, ch, v))
        if u:
            hits.append(u)
            if len(hits) > 1:
                break
    if len(hits) == 1:
        return hits[0], "unique_in_chapter"
    from macula.anchor_llm import fallback
    u = fallback("menahem", book, ch, vs, word, units)
    return (u, "llm") if u else (None, "")


def senses() -> list[tuple]:
    """One row per cited occurrence: the root entry (headword), its division, the division's sense phrase and
    text, and the anchored word (whole words, as build_metzudat_zion --explanations)."""
    from macula.build_metzudat_zion import _content_strong
    drop = excluded()
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    rows, st = [], collections.Counter()
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        letter = row["ref"].rsplit(" ", 1)[-1]
        for ei, entry in enumerate(row["entries"]):
            if not isinstance(entry, list) or len(entry) < 2:
                continue
            root = re.sub(r"<[^>]+>|[‎‏]", "", entry[0]).strip()
            body = " ".join(x for x in entry[1:] if isinstance(x, str))
            parts = re.split(_ORDINALS + r"\s*,", body)
            divisions = parts[1:] if len(parts) > 1 else parts
            st["entries"] += 1
            for di, div in enumerate(divisions, start=1):
                plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>|[‎‏]", "", div)).strip().rstrip(".:").strip()
                sense = _sense_phrase(plain)
                last, last_ch = None, None
                for word, _between, ref in _CITE.findall(div):
                    book, ch, vs = parse_ref(ref, last, last_ch)
                    if not book or not ch or not vs:
                        st["unparsed_citation"] += 1
                        continue
                    last, last_ch = book, ch
                    u, how = _anchor_citation(sp, word, book, ch, vs)
                    if not u:
                        st["not_anchored"] += 1
                        continue
                    st[f"anchored_{how}"] += 1
                    rows.append((book, ch, vs, u["key"], u["surface"], _content_strong(u, drop), root,
                                 f"{letter}:{ei}", di, len(divisions), sense, plain))
                    st["cited_occurrences"] += 1
    print(f"[menahem] senses: {dict(st)}", file=sys.stderr)
    return rows


def write_senses(rows: list[tuple]) -> None:
    SENSES.parent.mkdir(parents=True, exist_ok=True)
    with SENSES.open("w", encoding="utf-8") as fh:
        fh.write("# Mahberet Menahem (Menahem ben Saruq, 10th c.): its sense divisions per root, one row per cited "
                 "occurrence,\n# anchored to the word. Hebrew text Public Domain (London 1854, via Sefaria); "
                 "anchoring CC0.\n# entry = letter:index of the root entry; division of n_divisions; sense = the "
                 "division's ענין phrase (or כמשמעו).\n# Built by shoresh/macula/build_mahberet_menahem.py --senses.\n")
        fh.write("book\tchapter\tverse\tword_key\tword\tstrong\troot\tentry\tdivision\tn_divisions\tsense\ttext\n")
        for r in rows:
            fh.write("\t".join(str(x).replace("\t", " ") for x in r) + "\n")
    print(f"[menahem] -> {SENSES} ({len(rows)} rows)", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
