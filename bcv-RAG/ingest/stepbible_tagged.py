"""STEPBible tagged-text ingest: TAGNT (Greek NT) + TAHOT (Hebrew OT).

  python -m ingest.stepbible_tagged                  # all 6 files (full Bible)
  python -m ingest.stepbible_tagged --testament nt   # NT only (TAGNT)
  python -m ingest.stepbible_tagged --testament ot   # OT only (TAHOT)
  python -m ingest.stepbible_tagged --no-fetch       # use already-staged TSV files

Output (chunks-shaped, picked up by `indexer.build` via MarkdownAdapter):

  ingest/_staging/stepbible/<USFM>/<chap>_<verse>.md   one verse per file

Each verse markdown carries a word-by-word parse (lemma + Strong's +
morph code + English gloss) as a markdown list. Tags include
`kind:morphology`, `book:<USFM>`, `lang:grc`/`hbo`, plus per-word
`strongs:G####`, `lemma:<translit>`, and `morph:<code>` so word-study
retrievers in stage 3 can hit them via tag lookup.

Source & license
----------------
STEPBible Translators' Amalgamated OT+NT, CC BY 4.0:
  https://github.com/STEPBible/STEPBible-Data/tree/master/Translators%20Amalgamated%20OT%2BNT
NT split into 2 files (Mat-Jhn / Act-Rev), OT into 4 (Gen-Deu / Jos-Est /
Job-Sng / Isa-Mal). Each file is TSV; one row per word; verse boundaries
inferred from the reference column (Mat.1.1#01=NKO → strip `#NN=...`).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Iterator

import httpx
import yaml

from indexer.env import load_env
from indexer.references import BOOK_NUMBERS, encode

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STAGING = REPO_ROOT / "ingest" / "_staging" / "stepbible"

BASE = "https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/Translators%20Amalgamated%20OT%2BNT"

FILES: dict[str, list[tuple[str, str, str]]] = {
    # testament -> [(filename, url-encoded path, language ('grc'|'hbo'))]
    "nt": [
        ("TAGNT_Mat-Jhn.txt",
         "TAGNT%20Mat-Jhn%20-%20Translators%20Amalgamated%20Greek%20NT%20-%20STEPBible.org%20CC-BY.txt", "grc"),
        ("TAGNT_Act-Rev.txt",
         "TAGNT%20Act-Rev%20-%20Translators%20Amalgamated%20Greek%20NT%20-%20STEPBible.org%20CC-BY.txt", "grc"),
    ],
    "ot": [
        ("TAHOT_Gen-Deu.txt",
         "TAHOT%20Gen-Deu%20-%20Translators%20Amalgamated%20Hebrew%20OT%20-%20STEPBible.org%20CC%20BY.txt", "hbo"),
        ("TAHOT_Jos-Est.txt",
         "TAHOT%20Jos-Est%20-%20Translators%20Amalgamated%20Hebrew%20OT%20-%20STEPBible.org%20CC%20BY.txt", "hbo"),
        ("TAHOT_Job-Sng.txt",
         "TAHOT%20Job-Sng%20-%20Translators%20Amalgamated%20Hebrew%20OT%20-%20STEPBible.org%20CC%20BY.txt", "hbo"),
        ("TAHOT_Isa-Mal.txt",
         "TAHOT%20Isa-Mal%20-%20Translators%20Amalgamated%20Hebrew%20OT%20-%20STEPBible.org%20CC%20BY.txt", "hbo"),
    ],
}

# STEPBible 3-letter book codes use Title-case; our schema uses uppercase
# USFM 3-letter codes. Matching is just `.upper()` for every code we've
# seen — confirm at parse time and skip unknown codes.
_REF_RE = re.compile(r"^([1-3]?[A-Za-z]{2,3})\.(\d+)\.(\d+)(?:#.*)?$")
_STRONGS_TOKEN_RE = re.compile(r"[GH]\d+")


# ---------- helpers ----------

def _normalize_strongs(s: str) -> str:
    """G26 → G0026, H1 → H0001. Same convention as ingest/lexicons.py."""
    m = re.match(r"^([GH])(\d+)([a-zA-Z]?)$", s.strip())
    if not m:
        return s
    return f"{m.group(1)}{int(m.group(2)):04d}{m.group(3)}"


def _extract_strongs(field: str) -> list[str]:
    """STEPBible Strong's column has forms like 'H9003/{H7225G}', '{H7225/9016}',
    'G0976=N-NSF'. We extract every G####/H#### token and normalize."""
    tokens = _STRONGS_TOKEN_RE.findall(field or "")
    return sorted({_normalize_strongs(t) for t in tokens})


def _extract_morph(field: str) -> str:
    """Morphology codes are typically the part after '=' in TAGNT (e.g.
    'G0976=N-NSF' → 'N-NSF'), or the whole field in TAHOT (e.g. 'HR/Ncfsa').
    We split on '=' and take the tail if present, else return the field."""
    if not field:
        return ""
    if "=" in field:
        return field.split("=", 1)[1].strip()
    return field.strip()


def _safe_translit(t: str) -> str:
    """Lowercase + ASCII-only fragment for `lemma:<translit>` tags.
    STEPBible transliterations contain dots and hyphens to mark morpheme
    boundaries; we collapse to a queryable form."""
    return re.sub(r"[^a-z0-9]+", "", t.lower())


def _parse_ref(ref: str) -> tuple[str, int, int] | None:
    """`Mat.1.1#01=NKO` → ('MAT', 1, 1). None on malformed/unknown book."""
    m = _REF_RE.match(ref)
    if not m:
        return None
    book = m.group(1).upper()
    if book not in BOOK_NUMBERS:
        return None
    try:
        return book, int(m.group(2)), int(m.group(3))
    except ValueError:
        return None


# ---------- fetcher ----------

def fetch(testament: str, raw_dir: Path, *, timeout: float = 120.0) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for fname, url_path, _lang in FILES[testament]:
            url = f"{BASE}/{url_path}"
            print(f"  fetch {fname}", flush=True)
            r = client.get(url)
            r.raise_for_status()
            (raw_dir / fname).write_bytes(r.content)


# ---------- parser ----------

def _iter_words(path: Path) -> Iterator[tuple[str, list[str]]]:
    """Yield (raw_ref, columns) tuples from a TAGNT/TAHOT TSV, skipping
    headers and comments. STEPBible uses `#`-prefixed comment lines and a
    section of preamble before the data block; we filter strictly on rows
    whose first column starts with a recognized book code."""
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 4:
                continue
            ref_field = cols[0].strip()
            if not _REF_RE.match(ref_field):
                continue
            yield ref_field, cols


def parse_file(path: Path, language: str) -> Iterator[dict]:
    """Group word-rows by verse and yield one verse-dict per verse."""
    current_ref: tuple[str, int, int] | None = None
    words: list[dict] = []

    def flush() -> dict | None:
        if current_ref is None or not words:
            return None
        book, chap, verse = current_ref
        return {
            "book": book,
            "chapter": chap,
            "verse": verse,
            "language": language,
            "words": list(words),
        }

    for raw_ref, cols in _iter_words(path):
        parsed = _parse_ref(raw_ref)
        if parsed is None:
            continue
        if current_ref is None or parsed != current_ref:
            v = flush()
            if v is not None:
                yield v
            current_ref = parsed
            words = []

        # Per-word fields. Both TAGNT and TAHOT happen to share a 6-column
        # shape with our four most-needed fields at the same indices.
        original = cols[1].strip() if len(cols) > 1 else ""
        translit = ""
        m = re.search(r"\(([^)]+)\)", original)
        if m:
            translit = m.group(1).strip()
            original = original.split("(", 1)[0].strip()
        elif len(cols) > 2:
            # TAHOT separates transliteration into col 2 directly.
            translit = cols[2].strip()
        gloss = cols[2].strip() if len(cols) > 2 and language == "grc" else (
            cols[3].strip() if len(cols) > 3 else ""
        )
        strongs_field = cols[3].strip() if language == "grc" else (
            cols[4].strip() if len(cols) > 4 else ""
        )
        morph_field = strongs_field if language == "hbo" else strongs_field
        # NT: col 3 is "G####=N-NSF" combined; OT: col 4 is Strong's, col 5 is morph.
        if language == "hbo" and len(cols) > 5:
            morph_field = cols[5].strip()

        words.append({
            "original": original,
            "translit": translit,
            "gloss": gloss,
            "strongs": _extract_strongs(strongs_field),
            "morph": _extract_morph(morph_field),
        })

    v = flush()
    if v is not None:
        yield v


# ---------- markdown writer ----------

def _safe_book(usfm: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", usfm)


def _emit_verse(verse: dict, out_root: Path) -> Path | None:
    """Write one verse-markdown file. Returns the path, or None if degenerate."""
    book = verse["book"]
    chap = verse["chapter"]
    vnum = verse["verse"]
    lang = verse["language"]
    words = verse["words"]
    if not words:
        return None

    bbcccvvv = encode(book, chap, vnum)

    strongs_set: set[str] = set()
    lemmas_set: set[str] = set()
    morph_set: set[str] = set()
    for w in words:
        for s in w["strongs"]:
            strongs_set.add(s)
        if w["translit"]:
            ll = _safe_translit(w["translit"])
            if ll:
                lemmas_set.add(ll)
        if w["morph"]:
            morph_set.add(w["morph"])

    tags = ["kind:morphology", f"book:{book}", f"lang:{lang}"]
    tags += [f"strongs:{s}" for s in sorted(strongs_set)]
    tags += [f"lemma:{l}" for l in sorted(lemmas_set)]
    tags += [f"morph:{m}" for m in sorted(morph_set)]

    title_tag = "TAGNT" if lang == "grc" else "TAHOT"
    front = {
        "title": f"{title_tag} — {book} {chap}:{vnum}",
        "tags": sorted(tags),
        "passages": [[bbcccvvv, bbcccvvv]],
        "language": lang,
    }

    body_lines: list[str] = []
    for i, w in enumerate(words, start=1):
        bits = [f"{i}.", f"**{w['original']}**" if w["original"] else "—"]
        if w["translit"]:
            bits.append(f"*{w['translit']}*")
        meta_bits: list[str] = []
        if w["strongs"]:
            meta_bits.append(", ".join(w["strongs"]))
        if w["morph"]:
            meta_bits.append(w["morph"])
        if meta_bits:
            bits.append(f"[{' / '.join(meta_bits)}]")
        if w["gloss"]:
            bits.append(f"= \"{w['gloss']}\"")
        body_lines.append(" ".join(bits))

    out_dir = out_root / _safe_book(book) / str(chap)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{chap:03d}_{vnum:03d}.md"
    out_path.write_text(
        "---\n"
        + yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
        + "\n---\n\n"
        + "\n".join(body_lines)
        + "\n",
        encoding="utf-8",
    )
    return out_path


# ---------- CLI ----------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--testament", choices=("nt", "ot", "all"), default="all")
    ap.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    ap.add_argument("--no-fetch", action="store_true", help="use already-staged TSV files")
    args = ap.parse_args()
    load_env()

    testaments = ("nt", "ot") if args.testament == "all" else (args.testament,)
    raw_dir = args.staging / "_raw"
    out_dir = args.staging / "verses"

    if out_dir.is_dir():
        # Wipe previous emit so removed verses don't leave stale staged files.
        # (Walk + unlink — pathlib has no rmtree, and shutil's is fine but
        # we want fine-grained behavior.)
        for old in out_dir.rglob("*.md"):
            old.unlink()

    started = time.time()
    summary: dict[str, int] = defaultdict(int)

    for testament in testaments:
        for fname, _url_path, language in FILES[testament]:
            path = raw_dir / fname

            if not args.no_fetch:
                # Fetch only this file if missing (or always re-fetch — keep simple)
                pass  # fetched in bulk below

        if not args.no_fetch:
            print(f"fetching {testament.upper()}", flush=True)
            fetch(testament, raw_dir)

        for fname, _url_path, language in FILES[testament]:
            path = raw_dir / fname
            if not path.is_file():
                print(f"  missing: {path}", file=sys.stderr)
                continue
            print(f"parsing {fname}", flush=True)
            count = 0
            for verse in parse_file(path, language):
                if _emit_verse(verse, out_dir) is not None:
                    count += 1
            summary[fname] = count
            print(f"  {fname}: {count} verses", flush=True)

    summary["elapsed_seconds"] = round(time.time() - started, 2)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
