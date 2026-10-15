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
MACULA_DB = ROOT / "shoresh" / "macula" / "macula-spine.db"
_ID = re.compile(r"^[on]\d{11,12}$")
_BOOK_BY_NUM = {i: b for i, b in enumerate(OT_BOOKS + NT_BOOKS, 1)}  # MACULA numbers books 1-66
ATTRIBUTION = ("MACULA Quotation and Speaker Data, (c) 2023 by Clear Bible, Inc, "
               "CC-BY-4.0, https://github.com/Clear-Bible/speaker-quotations/")


def _load(name: str, data_dir: Path | None) -> list[str]:
    if data_dir:
        return (data_dir / name).read_text(encoding="utf-8").splitlines()
    import httpx  # noqa: PLC0415
    r = httpx.get(f"{RAW}/{name}", timeout=60.0, follow_redirects=True)
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
    extents = _verse_extents()

    header = proj[0].split("\t")
    col = {h: i for i, h in enumerate(header)}
    need = ["START VS", "END VS", "SPEAKER (FCBH)", "ALT SPEAKER (FCBH)",
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
        divine = "Y" if divinity.get(speaker) else ""
        rows.append((start, end, w0, w1, sp, ep, speaker, p[col["ALT SPEAKER (FCBH)"]].strip(),
                     p[col["QUOTE TYPE"]].strip(), p[col["QUOTE DELIVERY"]].strip(), divine))

    rows = sorted(set(rows), key=lambda r: (r[0], r[2], r[6]))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write(f"# source={ATTRIBUTION}\n")
        fh.write("# anchor=word span (CLEAR START/END, MACULA word ids); verse range in English numbering "
                 "(bibles org-to-eng); consensus (Clear-Aligned-Projections)\n")
        fh.write("speaker\talt_speaker\tstart_bbcccvvv\tend_bbcccvvv\tword_start\tword_end\t"
                 "start_partial\tend_partial\tquote_type\tdelivery\tdivine\n")
        for start, end, w0, w1, sp, ep, speaker, alt, qtype, delivery, divine in rows:
            fh.write(f"{speaker}\t{alt}\t{start}\t{end}\t{w0}\t{w1}\t{sp}\t{ep}\t{qtype}\t{delivery}\t{divine}\n")

    speakers = {r[6] for r in rows}
    divine_n = sum(1 for r in rows if r[10] == "Y")
    part_n = sum(1 for r in rows if "Y" in (r[4], r[5]))
    print(f"  wrote {len(rows)} quotation spans, {len(speakers)} distinct speakers "
          f"({divine_n} divine-speaker spans, {part_n} covering part of a verse, "
          f"{by_block} without word ids), {skipped} skipped → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
