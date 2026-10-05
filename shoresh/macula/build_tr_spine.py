#!/usr/bin/env python3
"""Build a THIRD, independently-sourced Greek spine_words db -- Scrivener's 1894 Textus Receptus
(same schema/contract as build_spine_words.py's lexeme-spine.db and build_rp_spine.py's
rp2018-spine.db). This is the source build_rp_spine.py's docstring flagged as still missing: RP2018
(Robinson-Pierpont, our second spine) is the Byzantine-majority text, which does NOT carry the Comma
Johanneum (1 John 5:7-8) -- verified directly there. This source DOES, confirmed directly before
writing this script (see below) -- so it closes that specific gap.

WHY A THIRD SPINE, NOT A PATCH ONTO RP2018: checked directly -- RP2018 is not a subset of this text.
The two editions differ in scattered word choices and word order throughout the NT, not just at the
Comma; they're two independently edited critical texts over the same broad Byzantine manuscript
tradition, not one nested inside the other. So this is built the same way RP2018 was -- a complete,
independent, drop-in-alternate spine_words db -- not a delta/append onto rp2018-spine.db.

SOURCE: github.com/byztxt/greektext-textus-receptus (27 per-book `.UTR` files, one word-token stream
each). Editor: Dr. Maurice A. Robinson (Wake Forest, NC) -- the same scholar who co-edited RP2018,
maintained by Dr. Ulrik Sandborg-Petersen. Public domain: repo README states "Public Domain. Copy
freely" (verified directly by fetching it, not taken on trust). EDITION CAVEAT: the repo's own README
doesn't name a specific base edition (Stephanus/Beza/Elzevir/Scrivener); it's presumed to be Scrivener's
1894 edition because it shares book-code conventions and the same maintainer with the sibling
`byztxt/greektext-scrivener` ("Scrivener's 1894 edition... text only") repo -- a reasonable inference,
not a confirmed fact, so don't assert "Scrivener 1894" more strongly than that anywhere downstream.

COMMA JOHANNEUM, verified directly (not taken on the requester's word) before building anything: 1 John
5:7 in the parsed source reads "...treiv eisin oi marturountev en tw ouranw o pathr o logov kai to
agion pneuma kai outoi oi treiv en eisin..." -- "there are three that bear record in heaven, the
Father, the Word, and the Holy Ghost: and these three are one" -- the full traditional reading, Strong's
-tagged like every other word. RP2018 (see build_rp_spine.py) has the short reading at this exact verse.

SOURCE FORMAT AND WHAT THIS PARSER HANDLES (all verified directly against the raw files, not assumed):
  - Per-book files: "book_code<TAB..whitespace>token token token...". Verse markers are inline
    "chapter:verse" tokens; a word entry is "surface strong [robinson_code] {PARSING-TAG}".
  - Alternate readings use a literal "|" pipe: spelling variants ("word1 | word2 strong tag", shared
    tag), tag-only variants ("strong | {tag1} | {tag2}", shared strong), and combinations of both --
    this parser keeps the FIRST alternative in each case and discards the rest (a textual-variant
    apparatus collapsed to one reading, same posture as any single critical edition's own choices).
  - Some words carry a SECOND, redundant (strong, tag) analysis immediately after the first, with no
    separating pipe (e.g. an inflected form that parses identically under two genders) -- the first
    analysis is kept, the second discarded.
  - Compound-number words (`eanper`, "thirty-eight" written as one word, etc.) reference 2-3 Strong's
    numbers, sometimes via a literal "0" sentinel token, sometimes as a bare digit run -- the FIRST
    Strong's number is kept as the word's `strong`.
  - `(chapter:verse)` parenthetical notes mark alternate historical versification (e.g. Matt 23:13/14,
    2 Cor 13:12/13, Acts 4:6 -- places where Byzantine-tradition and modern verse numbering disagree)
    -- these are notes, not words or real verse boundaries; skipped.
  - `[bracketed spans]` are traditional manuscript SUBSCRIPTIONS (postscripts like "written to the
    Corinthians from Philippi by Titus and Timothy" after several epistles) -- not canonical verse
    text (no chapter:verse of their own), excluded from the word list (140 words across 14 epistles).
  - 4 words (verified: 1 John... no -- John 9:21 `autou`, Rev 7:4 `rmd`) sit in apparatus notation this
    parser doesn't fully resolve after all the above; each has strong or tag missing and is DROPPED
    rather than emitting a row with a fabricated value -- both spot-checked directly: in both cases a
    complete alternate/adjacent analysis survives nearby, so nothing is silently lost from the running
    text, only a redundant broken duplicate is skipped. Printed at build time if the count ever changes.
  - Parsed and reconciled against a from-scratch tokenizer twice (different fix iterations) before
    being trusted; final run: 140,856/140,858 candidate words kept (99.999%), all Strong's+tag complete.

SCHEMA PARITY, and where it can't be full parity (same posture as build_rp_spine.py):
  - `lexeme`/`strong` are bare (`grc:<strong>`, no augment) -- same reasoning as RP2018: this source
    doesn't split homographs the way MACULA does.
  - `lemma` blank, `role`/`stem` blank, `is_superscription` always 0 -- same as RP2018 (see
    build_rp_spine.py; none of these apply to a Greek-only, BHSA-bridge-free spine).
  - `gloss` is ALWAYS BLANK here -- unlike RP2018's Berean-sourced per-word English gloss, this source
    carries no gloss column at all. A real, disclosed gap versus the other two Greek spines, not a bug.
  - `morph` carries the raw parsing-code tag verbatim (e.g. "V-2AAI-3S"); structured
    person/number/.../state columns blank in v1, same reasoning as RP2018 (needs a verified code table
    this pass didn't build).
  - `surface` IS RENDERED AS UNICODE GREEK, but from an ASCII transliteration source that carries NO
    accents or breathing marks and no capitalization (verified directly -- every sample file is fully
    lowercase, unaccented). The letter-to-letter mapping (a=alpha, b=beta, ... v=final sigma, s=medial
    sigma, ...) was reverse-engineered and cross-checked against known words (cristov=christos,
    exousian=exousian/xi, xenov=xenos/xi, yucikov=psychikos/psi) -- confident in the letter mapping
    itself, but the RESULT is honest, accent-less Greek, a real fidelity gap versus lexeme-spine.db and
    rp2018-spine.db's accented surface text. Flagged in spine_meta, not silently presented as equal
    fidelity.

  python -m macula.build_tr_spine                       # fetch + build tr-textus-receptus-spine.db
  TR_UTR_DIR=/path/to/local/utr/files python -m macula.build_tr_spine   # use local .UTR files
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from references import BOOK_NUMBERS  # USFM code -> book number; sanity-checks the map below

HERE = Path(__file__).resolve().parent
OUT_DEFAULT = HERE / "tr-textus-receptus-spine.db"
RAW_BASE = "https://raw.githubusercontent.com/byztxt/greektext-textus-receptus/master/parsed"
ENV_DIR = "TR_UTR_DIR"

# .UTR filename (byztxt's own book codes) -> this project's USFM codes (shoresh/references.py)
_BOOK_CODE = {
    "MT": "MAT", "MR": "MRK", "LU": "LUK", "JOH": "JHN", "AC": "ACT", "RO": "ROM",
    "1CO": "1CO", "2CO": "2CO", "GA": "GAL", "EPH": "EPH", "PHP": "PHP", "COL": "COL",
    "1TH": "1TH", "2TH": "2TH", "1TI": "1TI", "2TI": "2TI", "TIT": "TIT", "PHM": "PHM",
    "HEB": "HEB", "JAS": "JAS", "1PE": "1PE", "2PE": "2PE", "1JO": "1JN", "2JO": "2JN",
    "3JO": "3JN", "JUDE": "JUD", "RE": "REV",
}
assert set(_BOOK_CODE.values()) <= set(BOOK_NUMBERS), "book map drifted from references.py"

_CONTENT_POS = {"N", "V", "A"}   # parity with build_rp_spine._CONTENT_POS

# ASCII transliteration -> Greek letter, reverse-engineered from the source and cross-checked against
# known words (see docstring). 'v' is final sigma, only ever word-final; 's' is medial sigma.
_translit = {
    "a": "α", "b": "β", "g": "γ", "d": "δ", "e": "ε", "z": "ζ", "h": "η", "q": "θ",
    "i": "ι", "k": "κ", "l": "λ", "m": "μ", "n": "ν", "x": "ξ", "o": "ο", "p": "π",
    "r": "ρ", "s": "σ", "t": "τ", "u": "υ", "f": "φ", "c": "χ", "y": "ψ", "w": "ω",
}


def to_unicode_greek(word: str) -> str:
    out = []
    for i, ch in enumerate(word.lower()):
        if ch == "v":
            out.append("ς" if i == len(word) - 1 else "σ")  # defensive; source only uses 'v' word-final
        else:
            out.append(_translit.get(ch, ch))
    return "".join(out)


_VERSE = re.compile(r"^\d+:\d+$")
_ALTVERSE = re.compile(r"^\(\d+:\d+\)$")


def _looks_like_alt_word(tok: str) -> bool:
    return not (tok.isdigit() or tok.startswith("{") or tok.startswith("[") or _VERSE.match(tok) or tok == "|")


def _skip_alt_chain(toks: list[str], i: int) -> int:
    while i < len(toks) and toks[i] == "|":
        j = i + 1
        if j < len(toks) and _looks_like_alt_word(toks[j]):
            j += 1
            if j < len(toks) and toks[j].isdigit():
                j += 1  # alternate's own strong number, discarded
            i = j
        else:
            break
    return i


def _parse_word_entry(toks: list[str], i: int) -> tuple[dict, int]:
    surface = toks[i]; i += 1
    subscript_start = surface.startswith("[")
    if subscript_start:
        surface = surface[1:]

    i = _skip_alt_chain(toks, i)
    if i < len(toks) and toks[i] == "|":
        i += 1

    strong = None
    if i < len(toks) and toks[i].isdigit():
        first = toks[i]; i += 1
        if first == "0":  # compound-word sentinel: real Strong's numbers follow
            strongs = []
            while i < len(toks) and toks[i].isdigit():
                strongs.append(toks[i]); i += 1
            strong = strongs[0] if strongs else None
        else:
            strong = first
            if i < len(toks) and toks[i].isdigit():
                i += 1  # Robinson numeric code (redundant with the {tag}), discarded

    tags = []
    if i < len(toks) and toks[i].startswith("{") and toks[i].endswith("}"):
        tags.append(toks[i][1:-1]); i += 1
    while i < len(toks) and toks[i] == "|":
        j = i + 1
        if j < len(toks) and toks[j].startswith("{") and toks[j].endswith("}"):
            tags.append(toks[j][1:-1]); i = j + 1
        else:
            break
    tag = tags[0] if tags else None

    # secondary, unmarked (strong, tag) re-analysis of the SAME surface -- discard
    while i < len(toks) and toks[i].isdigit() and not _VERSE.match(toks[i]):
        i += 1
        if i < len(toks) and toks[i].isdigit():
            i += 1
        if i < len(toks) and toks[i].startswith("{") and toks[i].endswith("}"):
            i += 1

    subscript_end = surface.endswith("]")
    if subscript_end:
        surface = surface[:-1]
    return {
        "surface": surface, "strong": strong, "tag": tag,
        "subscript_start": subscript_start, "subscript_end": subscript_end,
    }, i


def parse_book(book_code: str, text: str) -> tuple[list[dict], int, list[tuple]]:
    """Returns (words, n_excluded_subscript, dropped_incomplete)."""
    toks = text.split()
    words, dropped = [], []
    n_excluded = 0
    i, ch, v, in_sub = 0, None, None, False
    while i < len(toks):
        t = toks[i]
        if _VERSE.match(t):
            ch, v = map(int, t.split(":")); i += 1; continue
        if _ALTVERSE.match(t):
            i += 1; continue
        if t == "|":
            i += 1; continue
        rec, i = _parse_word_entry(toks, i)
        if rec["subscript_start"]:
            in_sub = True
        keep_zone = not in_sub
        if keep_zone:
            if rec["strong"] is None or rec["tag"] is None:
                dropped.append((book_code, ch, v, rec["surface"], rec["strong"], rec["tag"]))
            else:
                words.append({"book": book_code, "chapter": ch, "verse": v,
                               "surface": rec["surface"], "strong": int(rec["strong"]), "tag": rec["tag"]})
        else:
            n_excluded += 1
        if rec["subscript_end"]:
            in_sub = False
    return words, n_excluded, dropped


def _fetch_book(code: str) -> str:
    local_dir = os.environ.get(ENV_DIR)
    if local_dir:
        return (Path(local_dir) / f"{code}.UTR").read_text(encoding="utf-8")
    with urllib.request.urlopen(f"{RAW_BASE}/{code}.UTR", timeout=60) as resp:  # noqa: S310 -- fixed, pinned URL
        return resp.read().decode("utf-8")


def build(out_path: Path) -> tuple[int, int, list, str]:
    out_path.unlink(missing_ok=True)
    db = sqlite3.connect(out_path)
    db.executescript("""
        CREATE TABLE spine_words (
            book TEXT NOT NULL, chapter INTEGER NOT NULL, verse INTEGER NOT NULL,
            idx INTEGER NOT NULL,
            key TEXT NOT NULL,           -- synthesized: "grc-tr:<book>:<running index>" -- no native
                                          -- per-occurrence id exists in this source
            surface TEXT NOT NULL,       -- unaccented Unicode Greek (see docstring caveat)
            lexeme TEXT NOT NULL,        -- ANCHOR: grc:<bare-strong> -- no augment (see docstring)
            strong INTEGER,
            lemma TEXT, is_content INTEGER NOT NULL, morph TEXT,
            gloss TEXT, role TEXT,
            stem TEXT,
            person TEXT, number TEXT, gender TEXT, case_ TEXT, tense TEXT, voice TEXT,
            mood TEXT, degree TEXT, state TEXT,   -- left blank in v1 -- see docstring
            is_superscription INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (book, chapter, verse, idx)
        );
        CREATE UNIQUE INDEX ix_ls_key ON spine_words(key);
        CREATE INDEX ix_ls_lexeme ON spine_words(lexeme);
        CREATE INDEX ix_ls_strong ON spine_words(strong);
        CREATE TABLE spine_meta (key TEXT PRIMARY KEY, value TEXT);
    """)

    all_text = []
    rows, idx, prev, n_excluded_total, all_dropped, key_n = [], 0, None, 0, [], 0
    for utr_code, usfm in _BOOK_CODE.items():
        text = _fetch_book(utr_code)
        all_text.append(text)
        words, n_excluded, dropped = parse_book(usfm, text)
        n_excluded_total += n_excluded
        all_dropped.extend(dropped)
        for w in words:
            cvk = (w["book"], w["chapter"], w["verse"])
            idx = idx + 1 if cvk == prev else 0
            prev = cvk
            key_n += 1
            surface_uni = to_unicode_greek(w["surface"])
            lexeme = f"grc:{w['strong']}"
            pos = w["tag"].split("-", 1)[0]
            rows.append((
                w["book"], w["chapter"], w["verse"], idx,
                f"grc-tr:{w['book']}:{key_n}", surface_uni, lexeme, w["strong"],
                None, 1 if pos in _CONTENT_POS else 0, w["tag"], None, "", "",
                "", "", "", "", "", "", "", "", "", 0,
            ))

    db.executemany(
        "INSERT INTO spine_words VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows,
    )
    db.commit()
    db.close()
    src_sha = hashlib.sha256("".join(all_text).encode("utf-8")).hexdigest()
    return len(rows), n_excluded_total, all_dropped, src_sha


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the Textus Receptus-anchored Greek spine_words (third, independent Greek spine).")
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args()

    n, n_excluded, dropped, src_sha = build(args.out)
    if not n:
        sys.exit("parsed 0 words -- source format changed, check the column layout in the docstring")

    with sqlite3.connect(args.out) as db:
        content = db.execute("SELECT COUNT(*) FROM spine_words WHERE is_content=1").fetchone()[0]
        n_books = db.execute("SELECT COUNT(DISTINCT book) FROM spine_words").fetchone()[0]
        db.executemany("INSERT INTO spine_meta VALUES (?,?)", [
            ("anchor", "lexeme = grc:bare-strong (no augment -- source has no homograph split)"),
            ("strong_rollup", "identical to lexeme -- nothing to strip"),
            ("content_classes", "adj,noun,verb (= STEPBible spine N/V/A); POS = source parsing-code "
                                 "first segment"),
            ("source_greek", "github.com/byztxt/greektext-textus-receptus -- Dr. Maurice A. Robinson's "
                              "Textus Receptus text with Strong's numbers + morphological parsing; "
                              "presumed Scrivener 1894 by convention/maintainer match with the sibling "
                              "greektext-scrivener repo, not confirmed in this repo's own README"),
            ("edition", "grc-tr (third, independent Greek spine -- NOT a subset/superset of grc-rp2018, "
                         "see build_tr_spine.py docstring)"),
            ("comma_johanneum", "PRESENT, verified directly at 1 John 5:7-8 -- see build_tr_spine.py "
                                 "docstring for the exact reading checked"),
            ("license", "Public domain -- github.com/byztxt/greektext-textus-receptus README: "
                         "'Public Domain. Copy freely.' (verified directly)"),
            ("surface_note", "unaccented, uncapitalized Unicode Greek, transliterated from the source's "
                              "ASCII form -- letter mapping cross-checked but the source itself has no "
                              "accents/breathings/capitals; a real fidelity gap vs. lexeme-spine.db and "
                              "rp2018-spine.db. See build_tr_spine.py docstring."),
            ("gloss_note", "always blank -- this source carries no per-word English gloss (unlike "
                            "rp2018-spine.db's Berean-sourced gloss)"),
            ("morph_note", "raw source parsing-code verbatim in `morph`; structured "
                            "person/number/gender/case_/tense/voice/mood/degree/state columns blank in "
                            "v1, same reasoning as rp2018-spine.db."),
            ("excluded_subscription_words", str(n_excluded)),
            ("dropped_incomplete_words", str(len(dropped)) + (
                (": " + "; ".join(f"{b} {c}:{v} {s}" for b, c, v, s, *_ in dropped)) if dropped else "")),
            ("source_sha256", src_sha),
            ("words", str(n)),
        ])
        from macula.spine_versification import declaration    # the spine's own verse numbering
        db.executemany("INSERT OR REPLACE INTO spine_meta(key, value) VALUES (?, ?)",
                       list(declaration(db, "tr").items()))
        db.commit()

    out_sha = hashlib.sha256(args.out.read_bytes()).hexdigest()
    print(f"{n} words, {n_books} books -> {args.out}")
    print(f"  content (N/V/A): {content}  ({100 * content / n:.1f}%)")
    print(f"  excluded (manuscript subscriptions): {n_excluded}")
    if dropped:
        print(f"  ! {len(dropped)} word(s) dropped (incomplete after parsing -- see spine_meta."
              f"dropped_incomplete_words for exactly which)", file=sys.stderr)
    print(f"  source sha256: {src_sha}")
    print(f"  build sha256:  {out_sha}")
    print("  -> pin both sha256s in the consumer's provenance note (same discipline as contract §1)")


if __name__ == "__main__":
    main()
