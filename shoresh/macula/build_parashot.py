"""Paragraph divisions of the Leningrad Codex (petuchot / setumot) as a verse-level table.

The Masoretic text marks its own paragraphs: an open paragraph (petucha, פ) or a closed one (setuma, ס)
after a verse. These are Hebrew-native passage units, older than chapter numbers, and the setting axis
(build_setting_axis.py) uses them as its documents.

Source: Open Scriptures Hebrew Bible, `wlc/*.xml` (`<seg type="x-pe">` / `"x-samekh"`), CC BY 4.0.
Versification is the WLC's, the same as MACULA's.

  python -m macula.build_parashot      # -> resources/parashot/parashot.tsv
"""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = HERE / "data" / "oshb_wlc"
OUT = ROOT / "resources" / "parashot" / "parashot.tsv"
URL = "https://raw.githubusercontent.com/openscriptures/morphhb/master/wlc/{}.xml"

# OSHB file name -> USFM book code (the spine's)
BOOKS = {
    "Gen": "GEN", "Exod": "EXO", "Lev": "LEV", "Num": "NUM", "Deut": "DEU", "Josh": "JOS", "Judg": "JDG",
    "Ruth": "RUT", "1Sam": "1SA", "2Sam": "2SA", "1Kgs": "1KI", "2Kgs": "2KI", "1Chr": "1CH", "2Chr": "2CH",
    "Ezra": "EZR", "Neh": "NEH", "Esth": "EST", "Job": "JOB", "Ps": "PSA", "Prov": "PRO", "Eccl": "ECC",
    "Song": "SNG", "Isa": "ISA", "Jer": "JER", "Lam": "LAM", "Ezek": "EZK", "Dan": "DAN", "Hos": "HOS",
    "Joel": "JOL", "Amos": "AMO", "Obad": "OBA", "Jonah": "JON", "Mic": "MIC", "Nah": "NAM", "Hab": "HAB",
    "Zeph": "ZEP", "Hag": "HAG", "Zech": "ZEC", "Mal": "MAL",
}
_VERSE = re.compile(r'<verse osisID="[^.]+\.(\d+)\.(\d+)"')
_MARK = re.compile(r'<seg type="x-(pe|samekh)">')


def fetch(name: str) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{name}.xml"
    if not p.exists():
        with urllib.request.urlopen(URL.format(name), timeout=120) as r:
            p.write_bytes(r.read())
    return p.read_text(encoding="utf-8")


def marks(xml: str) -> list[tuple[int, int, str]]:
    """[(chapter, verse, 'pe'|'samekh')]: a mark closes the paragraph after that verse."""
    out = []
    last = None
    for m in re.finditer(r'<verse osisID="[^.]+\.(\d+)\.(\d+)"|<seg type="x-(pe|samekh)">', xml):
        if m.group(1):
            last = (int(m.group(1)), int(m.group(2)))
        elif last:
            out.append((*last, "petucha" if m.group(3) == "pe" else "setuma"))
    return out


def main() -> int:
    rows = []
    for name, code in BOOKS.items():
        for c, v, kind in marks(fetch(name)):
            rows.append((code, c, v, kind))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write("# Leningrad Codex paragraph marks (petucha = open, setuma = closed), each closing the paragraph\n"
                 "# after book chapter:verse. Source: Open Scriptures Hebrew Bible wlc/ (CC BY 4.0).\n"
                 "# Built by shoresh/macula/build_parashot.py.\n")
        fh.write("book\tchapter\tverse\tmark\n")
        for r in rows:
            fh.write("\t".join(map(str, r)) + "\n")
    n_p = sum(r[3] == "petucha" for r in rows)
    print(f"{len(rows)} marks ({n_p} petucha, {len(rows) - n_p} setuma) across {len(BOOKS)} books -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
