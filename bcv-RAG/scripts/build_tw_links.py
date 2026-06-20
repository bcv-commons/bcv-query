#!/usr/bin/env python3
"""Phase 1c: anchor Translation Words (TW) to the actual original token(s).

Fetches unfoldingWord TWL (en_twl) per book and aligns each link's
`OrigWords` + `Occurrence` to `spine_words` via the shared UHB/UGNT base,
emitting an occurrence-level `tw_links.tsv`. `concepts.tw_ref`/`tw_kt` are
DERIVED from this file (a later step), preserving the occurrence-level spans
for Plan C (phrase lexicon) and display.

Anchoring standard: the TW link points at the actual original *token*
(occurrence + lemma); the Strong's code is the derived alias.

Multi-token OrigWords (space- or maqqef-separated): ALL matched tokens are
recorded (lossless, feeds Plan C); one is marked `is_head` (content token,
highest keyness) for the kt-flag / primary concept link.

Usage:
  python3 scripts/build_tw_links.py RUT TIT     # validation subset (default)
  python3 scripts/build_tw_links.py --all       # all 66 books
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
import sys
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SPINE_DB = ROOT / "shoresh" / "spine" / "spine.db"
KEYNESS = Path(__file__).resolve().parent.parent / "strongs_keyness.tsv"
OUTPUT = Path(__file__).resolve().parent.parent / "tw_links.tsv"
TWL_URL = "https://git.door43.org/unfoldingWord/en_twl/raw/branch/master/twl_{book}.tsv"

sys.path.insert(0, str(ROOT / "shoresh"))
from spine.common import NT_BOOKS, FILENUM  # noqa: E402

JOINER = "⁠"          # morpheme word-joiner used in UHB/spine surface
MAQQEF = "־"
# Hebrew cantillation accents (te'amim) + meteg/rafe/marks — strip for matching,
# KEEP vowel points (niqqud).
_CANT = "".join(chr(c) for c in range(0x0591, 0x05B0)) + "ֽֿ׀׃ׅׄ׆"


def _norm(s: str, *, consonantal: bool = False) -> str:
    s = unicodedata.normalize("NFC", s).replace(JOINER, "")
    if consonantal:  # strip ALL combining marks → consonant skeleton (fallback)
        return "".join(c for c in unicodedata.normalize("NFD", s)
                       if not unicodedata.combining(c))
    return s.translate({ord(c): None for c in _CANT})


def _pad(prefix: str, strong) -> str:
    return f"{prefix}{int(strong):04d}" if strong is not None else ""


def _load_keyness() -> dict[str, float]:
    out: dict[str, float] = {}
    if KEYNESS.exists():
        with KEYNESS.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 2:
                    try:
                        out[p[0]] = float(p[1])
                    except ValueError:
                        pass
    return out


def _parse_tw(link: str) -> tuple[str, str] | None:
    """rc://*/tw/dict/bible/kt/love → ('bible/kt/love', 'kt')."""
    m = re.search(r"/tw/dict/(bible/([a-z]+)/[a-z0-9-]+)\s*$", link.strip(), re.I)
    return (m.group(1), m.group(2)) if m else None


def _verse_tokens(con, book, ch, vs):
    return con.execute(
        "SELECT idx, surface, strong, lemma, is_content FROM spine_words "
        "WHERE book=? AND chapter=? AND verse=? ORDER BY idx",
        (book, ch, vs)).fetchall()


def _match_span(parts, tokens, occurrence):
    """Find the `occurrence`-th run of consecutive tokens matching `parts`.

    Returns list of matched token rows, or [] if no match. Tries exact
    (cantillation-stripped) then consonantal-skeleton.
    """
    for consonantal in (False, True):
        norm_parts = [_norm(p, consonantal=consonantal) for p in parts]
        hits = 0
        toks = [(t, _norm(t["surface"], consonantal=consonantal)) for t in tokens]
        for i in range(len(toks) - len(norm_parts) + 1):
            window = [toks[i + j][1] for j in range(len(norm_parts))]
            if window == norm_parts:
                hits += 1
                if hits == occurrence:
                    return [toks[i + j][0] for j in range(len(norm_parts))]
    return []


def _split_origwords(ow: str) -> list[str]:
    """OrigWords → sub-word parts (split on whitespace and maqqef)."""
    parts: list[str] = []
    for w in ow.split():
        parts.extend(p for p in w.split(MAQQEF) if p)
    return parts


def main() -> None:
    books = [b.upper() for b in sys.argv[1:] if not b.startswith("-")]
    if "--all" in sys.argv:
        books = [c for c, _ in sorted(FILENUM.items(), key=lambda kv: kv[1])]
    if not books:
        books = ["RUT", "TIT"]

    keyness = _load_keyness()
    con = sqlite3.connect(SPINE_DB)
    con.row_factory = sqlite3.Row

    rows_out = []
    stats = {}
    for book in books:
        prefix = "G" if book in NT_BOOKS else "H"
        try:
            text = urllib.request.urlopen(
                urllib.request.Request(TWL_URL.format(book=book),
                                       headers={"User-Agent": "bcv-query/1.0"}),
                timeout=30).read().decode("utf-8")
        except Exception as e:
            print(f"  {book}: fetch failed ({e})", file=sys.stderr)
            continue

        total = matched = 0
        for r in csv.DictReader(io.StringIO(text), delimiter="\t"):
            ref = (r.get("Reference") or "").strip()
            m = re.match(r"^(\d+):(\d+)$", ref)
            tw = _parse_tw(r.get("TWLink") or "")
            if not m or not tw:
                continue
            total += 1
            ch, vs = int(m.group(1)), int(m.group(2))
            occ = int(r.get("Occurrence") or "1")
            parts = _split_origwords(r.get("OrigWords") or "")
            toks = _verse_tokens(con, book, ch, vs)
            hit = _match_span(parts, toks, occ) if parts and toks else []
            if not hit:
                continue
            matched += 1
            is_kt = (tw[1] == "kt") or ((r.get("Tags") or "").strip() == "keyterm")
            # head = highest-keyness content token (fallback: first content, else first)
            def score(t):
                code = _pad(prefix, t["strong"])
                return (t["is_content"] or 0, keyness.get(code, -9.9))
            head = max(hit, key=score)
            for t in hit:
                code = _pad(prefix, t["strong"])
                rows_out.append((tw[0], tw[1], int(is_kt), book, ch, vs, t["idx"],
                                 code, t["lemma"] or "", int(t["idx"] == head["idx"])))
        stats[book] = (matched, total)
        print(f"  {book}: matched {matched}/{total} links "
              f"({100*matched/total:.0f}%)" if total else f"  {book}: 0 links",
              file=sys.stderr)
    con.close()

    with OUTPUT.open("w", encoding="utf-8") as fh:
        fh.write("tw_article\tcategory\tis_kt\tbook\tchapter\tverse\tidx\t"
                 "strong\tlemma\tis_head\n")
        for row in rows_out:
            fh.write("\t".join(str(x) for x in row) + "\n")

    tot_m = sum(m for m, _ in stats.values())
    tot_t = sum(t for _, t in stats.values())
    print(f"\nWrote {len(rows_out)} token-rows ({tot_m}/{tot_t} links matched, "
          f"{100*tot_m/tot_t:.0f}%) to {OUTPUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
