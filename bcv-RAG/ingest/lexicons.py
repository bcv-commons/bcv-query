"""Classical lexicon ingest: LSJ, BDB, Abbott-Smith.

  python -m ingest.lexicons                        # all three
  python -m ingest.lexicons --source lsj           # one at a time
  python -m ingest.lexicons --no-fetch             # use already-staged raw files

Output (standard staging/build pattern, unlike ingest/theographic.py):

  ingest/_staging/lexicons/<source>/<strongs>.md   per-entry markdown files
                                                   with YAML frontmatter

These get picked up by `indexer.build` via the standard MarkdownAdapter and
land in the existing `chunks` / `tags` / `documents` tables, tagged with
`kind:lexicon` so the new analyzer / retrievers in stages 3-4 can recognize
them. Strong's number, lemma transliteration, lexicon source, and language
are all expressed as tags — no new schema needed.

Sources & licenses
------------------
* **TFLSJ** (Full LSJ Greek lexicon, ~5,625 entries + extras) — STEPBible
  CC BY 4.0. https://github.com/STEPBible/STEPBible-Data
* **BDB** (Brown-Driver-Briggs Hebrew, ~8,090 entries) — public domain
  (1906). https://github.com/eliranwong/unabridged-BDB-Hebrew-lexicon
* **Abbott-Smith** Greek NT lexicon (~5,896 entries) — public domain
  (1922). https://github.com/translatable-exegetical-tools/Abbott-Smith
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Iterator

import httpx
import yaml

from indexer.env import load_env

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STAGING = REPO_ROOT / "ingest" / "_staging" / "lexicons"

STEPBIBLE_BASE = "https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master"
SOURCES: dict[str, dict] = {
    "lsj": {
        "files": [
            (
                f"{STEPBIBLE_BASE}/Lexicons/TFLSJ%20%200-5624%20-%20Translators%20Formatted%20full%20LSJ%20Bible%20lexicon%20-%20STEPBible.org%20CC%20BY.txt",
                "TFLSJ_0-5624.txt",
            ),
            (
                f"{STEPBIBLE_BASE}/Lexicons/TFLSJ%20extra%20-%20Translators%20Formatted%20full%20LSJ%20Bible%20lexicon%20-%20STEPBible.org%20CC%20BY.txt",
                "TFLSJ_extra.txt",
            ),
        ],
    },
    "bdb": {
        "files": [
            (
                "https://raw.githubusercontent.com/eliranwong/unabridged-BDB-Hebrew-lexicon/master/DictBDB.json",
                "DictBDB.json",
            ),
        ],
    },
    "abbott-smith": {
        "files": [
            (
                "https://raw.githubusercontent.com/translatable-exegetical-tools/Abbott-Smith/master/abbott-smith.tei.xml",
                "abbott-smith.tei.xml",
            ),
        ],
    },
}


# ---------- HTML / TEI helpers ----------

_HTML_TO_MD_PAIRS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE), "\n"),
    (re.compile(r"</\s*p\s*>", re.IGNORECASE), "\n\n"),
    (re.compile(r"<\s*p[^>]*>", re.IGNORECASE), ""),
    (re.compile(r"<\s*b\s*>(.*?)</\s*b\s*>", re.IGNORECASE | re.DOTALL), r"**\1**"),
    (re.compile(r"<\s*strong\s*>(.*?)</\s*strong\s*>", re.IGNORECASE | re.DOTALL), r"**\1**"),
    (re.compile(r"<\s*i\s*>(.*?)</\s*i\s*>", re.IGNORECASE | re.DOTALL), r"*\1*"),
    (re.compile(r"<\s*em\s*>(.*?)</\s*em\s*>", re.IGNORECASE | re.DOTALL), r"*\1*"),
]
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")


def html_to_markdown(s: str) -> str:
    """Best-effort HTML → minimal markdown for lexicon entries.

    Lexicon HTML is fairly simple (b / i / br / p / font). We preserve bold
    and italic, drop everything else (font, span, etc), unescape entities,
    and collapse runs of whitespace. The Greek/Hebrew script inside <font>
    tags survives because we strip the tag, not its contents.
    """
    if not s:
        return ""
    for pat, repl in _HTML_TO_MD_PAIRS:
        s = pat.sub(repl, s)
    s = _TAG_STRIP_RE.sub("", s)
    s = html.unescape(s)
    s = _WS_RE.sub(" ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _safe_filename(strongs: str) -> str:
    """Strong's numbers like 'G0026' are filename-safe already; defend anyway."""
    return re.sub(r"[^A-Za-z0-9_\-]", "_", strongs)


_STRONGS_RE = re.compile(r"^([GH])(\d+)([a-zA-Z]?)$")


def normalize_strongs(s: str) -> str:
    """Normalize Strong's-like ids to canonical 4-digit-padded form so the same
    word lookups across sources hit the same `strongs:` tag.

    G26 → G0026, G0901a → G0901a, H1 → H0001. Inputs that don't match the
    expected pattern (synthesized AS_ fallbacks etc.) are returned unchanged.
    """
    m = _STRONGS_RE.match(s.strip())
    if not m:
        return s
    letter, num, suffix = m.group(1), m.group(2), m.group(3)
    return f"{letter}{int(num):04d}{suffix}"


# ---------- staged-file writer ----------

def _write_entry(
    *,
    out_dir: Path,
    source: str,
    strongs: str,
    headword: str,
    transliteration: str,
    short_def: str,
    body_md: str,
    extra_meta: dict | None = None,
) -> None:
    """Emit one entry's markdown file with our YAML-frontmatter conventions."""
    title_bits = [s for s in (headword, f"({transliteration})" if transliteration else "") if s]
    title = f"{source.upper()} — {' '.join(title_bits)}".strip()
    if strongs:
        title = f"{title}  [{strongs}]"

    tags = [
        "kind:lexicon",
        f"source:{source}",
        "lang:en",
    ]
    if strongs:
        tags.append(f"strongs:{strongs}")
    if transliteration:
        # NFKD normalize first, then strip non-ASCII. This decomposes "phileō"
        # into "phileo" + combining macron, dropping only the combining mark
        # rather than the whole vowel. Net result: lemma:phileo (matches what
        # users actually type) instead of lemma:phile (LSJ's residue when
        # macrons get stripped without decomposition).
        decomposed = unicodedata.normalize("NFKD", transliteration.lower())
        lemma = re.sub(r"[^a-z0-9]+", "", decomposed)
        if lemma:
            tags.append(f"lemma:{lemma}")
    tags.sort()

    meta: dict = {
        "title": title,
        "tags": tags,
    }
    extras: dict = {
        "headword": headword,
        "transliteration": transliteration,
        "short_definition": short_def,
    }
    if extra_meta:
        extras.update(extra_meta)
    extras = {k: v for k, v in extras.items() if v not in (None, "", [], {})}
    meta.update(extras)

    body_parts: list[str] = []
    if headword or transliteration:
        bits = [s for s in (f"**{headword}**" if headword else "",
                            f"({transliteration})" if transliteration else "") if s]
        body_parts.append(" ".join(bits))
    if short_def:
        body_parts.append(f"_{short_def}_")
    if body_md:
        body_parts.append(body_md)

    out_dir.mkdir(parents=True, exist_ok=True)
    fname = _safe_filename(strongs or transliteration or headword) + ".md"
    out_path = out_dir / fname
    out_path.write_text(
        "---\n"
        + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
        + "\n---\n\n"
        + "\n\n".join(body_parts).strip()
        + "\n",
        encoding="utf-8",
    )


# ---------- LSJ (TFLSJ tab-separated) ----------

def parse_lsj(staging: Path) -> Iterator[dict]:
    """Stream entries out of TFLSJ tab-separated files.

    Columns (8): extended-strongs | xref | back-ref | greek | translit |
    POS | short-gloss | full-definition (HTML).
    """
    for raw_name in ("TFLSJ_0-5624.txt", "TFLSJ_extra.txt"):
        path = staging / raw_name
        if not path.is_file():
            continue
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                if len(cols) < 8:
                    continue
                strongs = cols[0].strip()
                if not strongs or not strongs.startswith("G"):
                    continue
                yield {
                    "strongs": normalize_strongs(strongs),
                    "headword": cols[3].strip(),
                    "transliteration": cols[4].strip(),
                    "pos": cols[5].strip(),
                    "short_def": cols[6].strip(),
                    "full_def_html": cols[7].strip(),
                }


def emit_lsj(staging_raw: Path, out_dir: Path) -> int:
    n = 0
    for entry in parse_lsj(staging_raw):
        body = html_to_markdown(entry["full_def_html"])
        _write_entry(
            out_dir=out_dir,
            source="lsj",
            strongs=entry["strongs"],
            headword=entry["headword"],
            transliteration=entry["transliteration"],
            short_def=entry["short_def"],
            body_md=body,
            extra_meta={"pos": entry["pos"]} if entry["pos"] else None,
        )
        n += 1
    return n


# ---------- BDB (JSON array) ----------

# Inside the BDB HTML, the Hebrew script is wrapped in <font class='c3'>אָב</font>.
# A different class often marks the transliteration; we extract them by structure.
_BDB_HEB_FONT = re.compile(r"<font class=['\"]c3['\"]>([^<]+)</font>")
_BDB_HEADER = re.compile(r"<b>H\d+\.\s*([A-Za-zÀ-ɏ'\-·\s]+?)</b>", re.IGNORECASE)


def _bdb_extract_word_and_translit(def_html: str) -> tuple[str, str]:
    """Return (hebrew_word, transliteration) from the BDB definition HTML."""
    word_match = _BDB_HEB_FONT.search(def_html)
    word = word_match.group(1).strip() if word_match else ""
    header_match = _BDB_HEADER.search(def_html)
    translit = header_match.group(1).strip() if header_match else ""
    return word, translit


def _bdb_extract_short_def(def_html: str) -> str:
    """First bold text after the part-of-speech marker is conventionally the gloss."""
    after_word = _BDB_HEB_FONT.split(def_html, maxsplit=1)
    tail = after_word[-1] if len(after_word) > 1 else def_html
    bolds = re.findall(r"<b>([^<]+)</b>", tail)
    pos_seen = False
    for b in bolds:
        text = b.strip()
        if not pos_seen and re.search(r"noun|verb|adjective|adverb|preposition|particle", text, re.I):
            pos_seen = True
            continue
        if pos_seen and text:
            return text
    return ""


def emit_bdb(staging_raw: Path, out_dir: Path) -> int:
    raw = (staging_raw / "DictBDB.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("expected JSON array in DictBDB.json")
    n = 0
    for item in data:
        strongs = (item.get("top") or "").strip()
        def_html = item.get("def") or ""
        if not strongs or not def_html:
            continue
        # Skip JSON metadata rows like DictInfo that don't carry an entry.
        if not strongs.startswith(("H", "G")) or not strongs[1:].lstrip("0").rstrip("abcdefghij").isdigit():
            continue
        strongs = normalize_strongs(strongs)
        word, translit = _bdb_extract_word_and_translit(def_html)
        short_def = _bdb_extract_short_def(def_html)
        body = html_to_markdown(def_html)
        _write_entry(
            out_dir=out_dir,
            source="bdb",
            strongs=strongs,
            headword=word,
            transliteration=translit,
            short_def=short_def,
            body_md=body,
        )
        n += 1
    return n


# ---------- Abbott-Smith (TEI XML) ----------

# Abbott-Smith uses CrossWire's OSIS-flavored TEI namespace, NOT standard TEI.
_TEI_NS_URI = "http://www.crosswire.org/2013/TEIOSIS/namespace"
_TEI_NS = {"tei": _TEI_NS_URI}


def _tei_text(node: ET.Element | None, sep: str = " ") -> str:
    if node is None:
        return ""
    return sep.join(t.strip() for t in node.itertext() if t and t.strip())


def emit_abbott_smith(staging_raw: Path, out_dir: Path) -> int:
    tree = ET.parse(staging_raw / "abbott-smith.tei.xml")
    root = tree.getroot()
    entries = root.iter(f"{{{_TEI_NS_URI}}}entry")
    n = 0
    for idx, entry in enumerate(entries):
        n_attr = (entry.get("n") or "").strip()
        # n attribute is conventionally "<word>|<strongs>" (e.g., "agape|G0026")
        strongs = ""
        if "|" in n_attr:
            _, _, raw_strongs = n_attr.partition("|")
            strongs = normalize_strongs(raw_strongs.strip())
        if not strongs:
            # No Strong's number — synthesize a stable id from the entry index
            # so the file stays unique. Tag stays `lexicon` regardless.
            strongs = f"AS_entry_{idx:05d}"

        # Headword (Greek): <form><orth>...</orth></form>
        orth = entry.find("tei:form/tei:orth", _TEI_NS)
        headword = _tei_text(orth)

        # Glosses concatenated for short_def
        glosses = [_tei_text(g) for g in entry.findall(".//tei:gloss", _TEI_NS)]
        short_def = ", ".join(g for g in glosses if g)[:300]

        # Body: full text of the entry (sense hierarchy + notes), minus the
        # already-extracted headword. Cheap and good-enough — TEI sense
        # hierarchy details can be reconstructed downstream from the body
        # if needed.
        body = _tei_text(entry, sep="\n").strip()

        # NT occurrence count if present
        nt_count_node = entry.find(
            ".//tei:note[@type='occurrencesNT']", _TEI_NS
        )
        extra: dict = {}
        if nt_count_node is not None and nt_count_node.text:
            try:
                extra["nt_occurrences"] = int(nt_count_node.text.strip())
            except ValueError:
                pass

        _write_entry(
            out_dir=out_dir,
            source="abbott-smith",
            strongs=strongs,
            headword=headword,
            transliteration="",  # Abbott-Smith TEI doesn't carry transliteration as a separate field
            short_def=short_def,
            body_md=body,
            extra_meta=extra or None,
        )
        n += 1
    return n


# ---------- fetch ----------

def fetch(source: str, staging_raw: Path, *, timeout: float = 60.0) -> None:
    files = SOURCES[source]["files"]
    staging_raw.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for url, dest_name in files:
            print(f"  fetch {dest_name}", flush=True)
            r = client.get(url)
            r.raise_for_status()
            (staging_raw / dest_name).write_bytes(r.content)


# ---------- CLI ----------

EMITTERS = {
    "lsj": emit_lsj,
    "bdb": emit_bdb,
    "abbott-smith": emit_abbott_smith,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--source", action="append", choices=list(SOURCES.keys()),
        help="repeatable; default = all three",
    )
    ap.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    ap.add_argument("--no-fetch", action="store_true", help="use already-staged raw files; skip download")
    args = ap.parse_args()

    load_env()

    sources = args.source or list(SOURCES.keys())
    raw_dir = args.staging / "_raw"

    started = time.time()
    summary: dict[str, int] = {}
    for src in sources:
        out_dir = args.staging / src
        # Clean previous emit so a re-run with fewer entries doesn't leave stale files behind.
        if out_dir.is_dir():
            for old in out_dir.glob("*.md"):
                old.unlink()

        if not args.no_fetch:
            print(f"fetching {src}", flush=True)
            fetch(src, raw_dir)

        print(f"emitting markdown for {src}", flush=True)
        n = EMITTERS[src](raw_dir, out_dir)
        summary[src] = n
        print(f"  {src}: {n} entries → {out_dir}", flush=True)

    print(json.dumps({
        "elapsed_seconds": round(time.time() - started, 2),
        **summary,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
