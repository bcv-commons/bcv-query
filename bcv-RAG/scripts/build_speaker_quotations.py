#!/usr/bin/env python3
"""Build resources/speaker_quotations/speaker_quotations.tsv — who speaks where.

Roadmap S1 (speaker / red-letter index). Ingests Clear-Bible/speaker-quotations
(MACULA Quotation and Speaker Data) — the consensus, translation-independent
projection of every biblical quotation onto its speaker (FCBH character data).

We anchor on the VERSE RANGE (the projection's START VS / END VS, USFM) → our
BBCCCVVV scheme, matching passage_refs — robust and join-ready, no brittle
word-index alignment. (Word-level anchoring via the CLEAR/MACULA token ids is a
possible future refinement.)

Enables: speaker-scoped retrieval ("what did Jesus say about X"), "God's
promises", and red-letter (divine speakers) via the `divine` flag.

Sources (fetched from raw GitHub, or pass --data-dir for a local clone):
  tsv/Clear-Aligned-Projections.tsv      — KEY, START VS, END VS, SPEAKER (FCBH),
      ALT SPEAKER (FCBH), SPEAKER REFERENT (CLEAR), ..., QUOTE TYPE, QUOTE DELIVERY, ...
  tsv/character_detail.semantic_data.tsv — CharacterID, ..., Divinty, ... (red-letter flag)

Output: resources/speaker_quotations/speaker_quotations.tsv
  columns: speaker, alt_speaker, start_bbcccvvv, end_bbcccvvv, quote_type, delivery, divine
  sorted by start_bbcccvvv, then speaker.

    python3 scripts/build_speaker_quotations.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from indexer.references import encode  # noqa: E402
from resource_paths import resource_path  # noqa: E402

RAW = "https://raw.githubusercontent.com/Clear-Bible/speaker-quotations/main/tsv"
PROJECTIONS = "Clear-Aligned-Projections.tsv"
CHARACTERS = "character_detail.semantic_data.tsv"
OUT = resource_path("speaker_quotations") / "speaker_quotations.tsv"
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=None,
                    help="local clone's tsv/ dir (default: fetch from GitHub)")
    args = ap.parse_args()

    proj = _load(PROJECTIONS, args.data_dir)
    divinity = _divinity_map(_load(CHARACTERS, args.data_dir))

    header = proj[0].split("\t")
    col = {h: i for i, h in enumerate(header)}
    need = ["START VS", "END VS", "SPEAKER (FCBH)", "ALT SPEAKER (FCBH)",
            "QUOTE TYPE", "QUOTE DELIVERY"]
    missing = [c for c in need if c not in col]
    if missing:
        print(f"projection file missing columns: {missing}", file=sys.stderr)
        return 2

    rows: list[tuple] = []
    skipped = 0
    for line in proj[1:]:
        p = line.split("\t")
        if len(p) <= col["QUOTE DELIVERY"]:
            continue
        start = _usfm_to_bbcccvvv(p[col["START VS"]])
        end = _usfm_to_bbcccvvv(p[col["END VS"]])
        speaker = p[col["SPEAKER (FCBH)"]].strip()
        if start is None or end is None or not speaker:
            skipped += 1
            continue
        if end < start:
            start, end = end, start
        divine = "Y" if divinity.get(speaker) else ""
        rows.append((start, end, speaker, p[col["ALT SPEAKER (FCBH)"]].strip(),
                     p[col["QUOTE TYPE"]].strip(), p[col["QUOTE DELIVERY"]].strip(), divine))

    # Dedupe: the source has multiple word-level spans per verse range, which
    # collapse to one row at verse granularity.
    rows = sorted(set(rows), key=lambda r: (r[0], r[2]))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write(f"# source={ATTRIBUTION}\n")
        fh.write("# anchor=verse range (START/END VS → BBCCCVVV); consensus (Clear-Aligned-Projections)\n")
        fh.write("speaker\talt_speaker\tstart_bbcccvvv\tend_bbcccvvv\tquote_type\tdelivery\tdivine\n")
        for start, end, speaker, alt, qtype, delivery, divine in rows:
            fh.write(f"{speaker}\t{alt}\t{start}\t{end}\t{qtype}\t{delivery}\t{divine}\n")

    speakers = {r[2] for r in rows}
    divine_n = sum(1 for r in rows if r[6] == "Y")
    print(f"  wrote {len(rows)} quotation ranges, {len(speakers)} distinct speakers "
          f"({divine_n} divine-speaker ranges), {skipped} skipped → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
