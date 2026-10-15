#!/usr/bin/env python3
"""Build resources/speaker_quotations/speaker_quotations.tsv — who speaks where.

Roadmap S1 (speaker / red-letter index). Ingests Clear-Bible/speaker-quotations
(MACULA Quotation and Speaker Data) — the consensus, translation-independent
projection of every biblical quotation onto its speaker (FCBH character data).

We anchor on the WORD SPAN (CLEAR START / CLEAR END, MACULA word ids) and give its verse range in English
numbering (bibles' org-to-eng map via shoresh/vrsmap.py), so a range is the verses of the quoted words, not the
wider FCBH quote block. start_partial / end_partial say whether the span covers only part of its first / last
verse (against shoresh/macula/macula-spine.db, which must be built). Rows without word ids keep START VS / END VS.

Enables: speaker-scoped retrieval ("what did Jesus say about X"), "God's
promises", and red-letter (divine speakers) via the `divine` flag.

Sources (fetched from raw GitHub, or pass --data-dir for a local clone):
  tsv/Clear-Aligned-Projections.tsv      — KEY, START VS, END VS, SPEAKER (FCBH),
      ALT SPEAKER (FCBH), SPEAKER REFERENT (CLEAR), ..., QUOTE TYPE, QUOTE DELIVERY, ...
  tsv/character_detail.semantic_data.tsv — CharacterID, ..., Divinty, ... (red-letter flag)

Output: resources/speaker_quotations/speaker_quotations.tsv
  columns: speaker, alt_speaker, start_bbcccvvv, end_bbcccvvv, word_start, word_end, start_partial, end_partial,
           quote_type, delivery, divine
  sorted by start_bbcccvvv, then word_start, then speaker.

    python3 scripts/build_speaker_quotations.py
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from indexer.references import encode  # noqa: E402
from resource_paths import resource_path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "shoresh"))
import vrsmap  # noqa: E402
from spine.common import NT_BOOKS, OT_BOOKS  # noqa: E402

RAW = "https://raw.githubusercontent.com/Clear-Bible/speaker-quotations/main/tsv"
PROJECTIONS = "Clear-Aligned-Projections.tsv"
CHARACTERS = "character_detail.semantic_data.tsv"
OUT = resource_path("speaker_quotations") / "speaker_quotations.tsv"
CORRECTIONS = resource_path("speaker_quotations") / "corrections.tsv"
MACULA_DB = ROOT / "shoresh" / "macula" / "macula-spine.db"
_ID = re.compile(r"^[on]\d{11,12}$")
_BOOK_BY_NUM = {i: b for i, b in enumerate(OT_BOOKS + NT_BOOKS, 1)}  # MACULA numbers books 1-66
ATTRIBUTION = ("MACULA Quotation and Speaker Data, (c) 2023 by Clear Bible, Inc, "
               "CC-BY-4.0, https://github.com/Clear-Bible/speaker-quotations/")
GLYSSEN_RAW = "https://raw.githubusercontent.com/sillsdev/Glyssen/master/GlyssenCharacters/Resources"
CHARACTER_VERSE = "CharacterVerse.txt"
GLYSSEN_ATTRIBUTION = ("Glyssen CharacterVerse.txt, Copyright (c) 2014-2020 SIL LSDev and Faith Comes By Hearing, MIT, "
                       "https://github.com/sillsdev/Glyssen")
# Lemmas that name God: a quotation whose speaker is introduced by one of them is God's.
GOD_LEMMAS = frozenset({"יהוה", "יָהּ", "אֲדֹנָי", "אֱלֹהִים", "אֱלָהּ", "θεός"})
# Glyssen characters that are not a person's own voice (never taken as a replacement speaker).
_NOT_A_VOICE = ("narrator-", "scripture", "interruption-")
# Glyssen quote types of a character who does speak in the verse; "Potential", "Alternate", "Hypothetical", "Indirect" and
# "Rare" only allow for a reading, and Clear's referent there is often the person addressed (Jer 15:20, Jer 20:10).
_SPEAKS = frozenset({"Normal", "Dialogue", "Quotation", "Implicit"})


def _load(name: str, data_dir: Path | None, base: str = RAW) -> list[str]:
    if data_dir:
        return (data_dir / name).read_text(encoding="utf-8").splitlines()
    import httpx  # noqa: PLC0415
    r = httpx.get(f"{base}/{name}", timeout=60.0, follow_redirects=True)
    r.raise_for_status()
    return r.text.splitlines()


def _usfm_to_bbcccvvv(ref: str) -> int | None:
    """'GEN 1:3' → 1001003. None if unparseable / unknown book."""
    try:
        book, cv = ref.strip().split(" ", 1)
        chap, verse = cv.split(":")
        return encode(book, int(chap), int(verse))
    except (ValueError, KeyError):
        return None


def _divinity_map(lines: list[str]) -> dict[str, bool]:
    """{CharacterID: is_divine} from character_detail. The divine marker is the
    'Status' column (= 'Y' for God/Jesus/Holy Spirit; the literally-named
    'Divinty' column is blank in the data). We accept 'Y' in either, by header
    name, so the data deciding which column to trust — not a fixed position."""
    if not lines:
        return {}
    header = [h.strip() for h in lines[0].split("\t")]
    try:
        cid_i = header.index("CharacterID")
    except ValueError:
        return {}
    flag_cols = [i for i, h in enumerate(header)
                 if h.lower() in ("status", "divinty", "divinity")]
    out: dict[str, bool] = {}
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) <= cid_i:
            continue
        cid = parts[cid_i].strip()
        if not cid:
            continue
        out[cid] = any(len(parts) > i and parts[i].strip().upper() == "Y"
                       for i in flag_cols)
    return out


def _word_pos(xml_id: str) -> tuple[str, int, int, int] | None:
    """MACULA word id → (book, chapter, verse, word, testament prefix) in the original (MACULA) numbering.
    'o010010030031' = OT book 01, 1:3, word 003 (last digit: the part); 'n40001001001' = NT book 40, 1:1, word 001."""
    if not _ID.match(xml_id or ""):
        return None
    digits = xml_id[1:]
    book = _BOOK_BY_NUM.get(int(digits[0:2]))
    if book is None:
        return None
    return book, int(digits[2:5]), int(digits[5:8]), int(digits[8:11])


def _verse_extents() -> dict[tuple[str, int, int], tuple[int, int]]:
    """{(book, chapter, verse): (first word, last word)} in MACULA numbering, from shoresh's macula-spine.db."""
    con = sqlite3.connect(f"file:{MACULA_DB}?mode=ro", uri=True)
    try:
        return {(b, c, v): (lo, hi) for b, c, v, lo, hi in con.execute(
            "SELECT book, chapter, verse, MIN(word), MAX(word) FROM macula_words GROUP BY book, chapter, verse")}
    finally:
        con.close()


def _eng(book: str, ch: int, v: int) -> int | None:
    """MACULA (original) verse → BBCCCVVV in English numbering (bibles' org-to-eng map via vrsmap). A Psalm title
    (English verse 0) counts as verse 1, where English Bibles print it."""
    refs = vrsmap.to_eng((book, ch, v), "org")
    b, c, vv = refs[0] if refs else (book, ch, v)
    try:
        return encode(b, c, max(vv, 1))
    except (ValueError, KeyError):
        return None


def _character_verses(lines: list[str]) -> dict[tuple[str, int, int], list[tuple[str, str, bool]]]:
    """{(book, chapter, verse) in English numbering: [(character, default character, speaks), ...]} from Glyssen's
    CharacterVerse.txt (columns: book, chapter, verse or range, character id, delivery, alias, quote type, default character,
    ...); `speaks`: the quote type says the character does speak there (_SPEAKS)."""
    out: dict[tuple[str, int, int], list[tuple[str, str, bool]]] = {}
    for line in lines:
        if line.startswith(("#", "Control")):
            continue
        p = line.split("\t")
        if len(p) < 8:
            continue
        a, _, b = p[2].partition("-")
        try:
            vs = range(int(a), int(b or a) + 1)
            ch = int(p[1])
        except ValueError:
            continue
        for v in vs:
            out.setdefault((p[0], ch, v), []).append((p[3], p[7], p[6] in _SPEAKS))
    return out


def _names(character: str) -> set[str]:
    """Capitalised name words of a character id, without a possessive owner ("Yahweh's angel" → set())."""
    owner = re.match(r"([A-Z][\w\-]*)'s\b", character)
    return set(re.findall(r"[A-Z][\w\-]*", character)) - ({owner.group(1)} if owner else set())


def _referent_name(ref_ids: str, word_start: str, words: dict[str, tuple[str, str]]) -> str | None:
    """The name of the speaker Clear points to (SPEAKER REFERENT: one MACULA word before the quotation): "GOD" for a name of
    God, else the word's capitalised gloss (a proper name); None for a common noun, a group, or a word inside/after the quote."""
    ids = [i for i in re.split(r"[ ,]+", ref_ids) if i]
    if len(ids) != 1 or ids[0] not in words or ids[0] >= word_start:
        return None
    lemma, gloss = words[ids[0]]
    gloss = (gloss or "").strip(".").split(".")[-1]
    if not gloss[:1].isupper():
        return None
    return "GOD" if lemma in GOD_LEMMAS else gloss


def _who(block: str, ref_name: str | None, cands: list[tuple[str, str, bool]]) -> tuple[str, str]:
    """(speaker, basis) of one quotation. FCBH gives one speaker per quote block; in a dialogue the block holds both sides.
    - "referent": Clear names a speaker before this quotation and exactly one of the characters Glyssen lists as speaking in
      the verse has that name, and it is not the block's speaker → that character.
    - "character": the block speaker is only the casting voice (Glyssen's default character, e.g. "Jesus" for "Yahweh's angel")
      of exactly one character in the verse → that character.
    - "block": otherwise the block's speaker."""
    def named(c: str) -> bool:
        return (c == "God" or c.startswith("God ")) if ref_name == "GOD" else ref_name in _names(c)
    mine = {c for c, d, _ in cands if block in (c, d)}
    if ref_name:
        hit = {c for c, _, speaks in cands if speaks and named(c)}
        if len(hit) == 1 and not hit & mine:
            return hit.pop(), "referent"
    if block not in {c for c, _, _ in cands}:
        voiced = {c for c, d, _ in cands if d == block and "/" not in c and not c.startswith(_NOT_A_VOICE)}
        if len(voiced) == 1:
            return voiced.pop(), "character"
    return block, "block"


def _macula_words() -> dict[str, tuple[str, str]]:
    """{MACULA xml id: (lemma, gloss)}."""
    con = sqlite3.connect(f"file:{MACULA_DB}?mode=ro", uri=True)
    try:
        return {i: (lem, gl) for i, lem, gl in con.execute("SELECT xml_id, lemma, gloss FROM macula_words")}
    finally:
        con.close()


def _corrections() -> dict[str, str]:
    """{word_start: speaker} from corrections.tsv (hand corrections where the text settles who speaks)."""
    if not CORRECTIONS.exists():
        return {}
    lines = [l for l in CORRECTIONS.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    return {p[0]: p[1] for p in (l.split("\t") for l in lines[1:]) if len(p) >= 2}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=None,
                    help="local clone's tsv/ dir (default: fetch from GitHub)")
    args = ap.parse_args()
    if not MACULA_DB.exists():
        print(f"ERROR: {MACULA_DB} not found (shoresh's MACULA word table gives each verse's word extent)", file=sys.stderr)
        return 1

    proj = _load(PROJECTIONS, args.data_dir)
    divinity = _divinity_map(_load(CHARACTERS, args.data_dir))
    characters = _character_verses(_load(CHARACTER_VERSE, args.data_dir, GLYSSEN_RAW))
    extents = _verse_extents()
    words = _macula_words()
    corrections = _corrections()

    header = proj[0].split("\t")
    col = {h: i for i, h in enumerate(header)}
    need = ["START VS", "END VS", "SPEAKER (FCBH)", "ALT SPEAKER (FCBH)", "SPEAKER REFERENT (CLEAR)",
            "QUOTE TYPE", "QUOTE DELIVERY", "CLEAR START", "CLEAR END"]
    missing = [c for c in need if c not in col]
    if missing:
        print(f"projection file missing columns: {missing}", file=sys.stderr)
        return 2

    def partial(pos, at_start: bool) -> str:
        ext = extents.get(pos[:3])
        if ext is None:
            return ""
        return "N" if pos[3] == (ext[0] if at_start else ext[1]) else "Y"

    rows: list[tuple] = []
    skipped = by_block = 0
    for line in proj[1:]:
        p = line.split("\t")
        if len(p) < len(header):
            continue
        speaker = p[col["SPEAKER (FCBH)"]].strip()
        w0, w1 = p[col["CLEAR START"]].strip(), p[col["CLEAR END"]].strip()
        a, b = _word_pos(w0), _word_pos(w1)
        if a and b:
            # The words of the quotation: its verses, mapped to English numbering, and whether it covers its first
            # and last verse whole.
            start, end = _eng(*a[:3]), _eng(*b[:3])
            sp, ep = partial(a, True), partial(b, False)
        else:
            # No word id (25 NT rows): the FCBH quote block's verse range, already in English numbering.
            start, end = _usfm_to_bbcccvvv(p[col["START VS"]]), _usfm_to_bbcccvvv(p[col["END VS"]])
            w0 = w1 = sp = ep = ""
            by_block += 1
        if start is None or end is None or not speaker:
            skipped += 1
            continue
        if end < start:
            start, end = end, start
        block = speaker
        if a:
            eng = vrsmap.to_eng(a[:3], "org")
            b0, c0, v0 = eng[0] if eng else a[:3]
            ref_name = _referent_name(p[col["SPEAKER REFERENT (CLEAR)"]], w0, words)
            speaker, basis = _who(block, ref_name, characters.get((b0, c0, max(v0, 1)), []))
            if w0 in corrections:
                speaker, basis = corrections[w0], "correction"
        else:
            basis = "block"
        divine = "Y" if divinity.get(speaker) else ""
        rows.append((start, end, w0, w1, sp, ep, speaker, block, basis, p[col["ALT SPEAKER (FCBH)"]].strip(),
                     p[col["QUOTE TYPE"]].strip(), p[col["QUOTE DELIVERY"]].strip(), divine))

    rows = sorted(set(rows), key=lambda r: (r[0], r[2], r[6]))
    basis_n = {b: sum(1 for r in rows if r[8] == b) for b in ("referent", "character", "correction")}
    unused = set(corrections) - {r[2] for r in rows if r[8] == "correction"}
    if unused:
        print(f"corrections.tsv: no span starts at {sorted(unused)}", file=sys.stderr)
        return 3

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write(f"# source={ATTRIBUTION}\n")
        fh.write(f"# source={GLYSSEN_ATTRIBUTION} (characters per verse; speaker_basis referent/character)\n")
        fh.write("# anchor=word span (CLEAR START/END, MACULA word ids); verse range in English numbering "
                 "(bibles org-to-eng); consensus (Clear-Aligned-Projections)\n")
        fh.write("speaker\talt_speaker\tstart_bbcccvvv\tend_bbcccvvv\tword_start\tword_end\t"
                 "start_partial\tend_partial\tquote_type\tdelivery\tdivine\tblock_speaker\tspeaker_basis\n")
        for start, end, w0, w1, sp, ep, speaker, block, basis, alt, qtype, delivery, divine in rows:
            fh.write(f"{speaker}\t{alt}\t{start}\t{end}\t{w0}\t{w1}\t{sp}\t{ep}\t{qtype}\t{delivery}\t{divine}\t"
                     f"{block}\t{basis}\n")

    speakers = {r[6] for r in rows}
    divine_n = sum(1 for r in rows if r[12] == "Y")
    part_n = sum(1 for r in rows if "Y" in (r[4], r[5]))
    print(f"  wrote {len(rows)} quotation spans, {len(speakers)} distinct speakers "
          f"({divine_n} divine-speaker spans, {part_n} covering part of a verse, "
          f"{by_block} without word ids; speaker from Clear's referent {basis_n['referent']}, "
          f"character for a casting voice {basis_n['character']}, corrections {basis_n['correction']}), "
          f"{skipped} skipped → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
