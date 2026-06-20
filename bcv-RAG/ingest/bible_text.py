"""(a) OT text completion for the NT-only aligned Bibles (fr/pt/as/bn).

Aligned OT does not exist for these languages (unfoldingWord aligns only the NT
of the national GLs; only en_ult is full-OT aligned), so the OT is added as PLAIN
TEXT — searchable (FTS), displayable, embeddable (vector), but with NO strongs:
tags. The aligned NT (from the Clear-Bible pipeline) is left untouched.

Each OT verse is tagged with a DISTINCT edition id (see bible_editions.json) so the
OT-vs-NT translation/source/alignment difference is recorded honestly, e.g.
fr OT = resource:lsg-ot (Aquifer, unaligned) vs NT resource:lsg (Clear-Bible, aligned).

Only OT books (1-39) are emitted; NT is already indexed. Output: kind:bible verse
markdown under ingest/_staging/bibletext/<edition>/<USFM>/<ch>/… (the edition
segment keeps the doc-id hash unique). Build with:
  python -m indexer.build --source ingest/_staging/bibletext

Sources (per resources-map.md): fr = already-downloaded Aquifer LSG (.md);
as/bn = Door43 *_irv master USFM (full text); pt = open-bibles Almeida (USFX).

Usage: python -m ingest.bible_text --lang fr          (or as/bn/pt; default all)
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from lang import canon, to_web

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from indexer.references import BOOK_NUMBERS, NUMBER_TO_CODE, decode, encode  # noqa: E402

STAGING = REPO_ROOT / "ingest" / "_staging" / "bibletext"
UA = {"User-Agent": "bcv-query/1.0 (OT text completion)"}
_OT = set(range(1, 40))  # book numbers 1..39

# lang -> {edition, source-kind + locator}
CONFIG: dict[str, dict] = {
    "fr": {"edition": "lsg-ot", "kind": "aquifer_md",
           "path": REPO_ROOT / "ingest" / "_staging" / "aquifer_alt" / "fr" / "LouisSegond1910"},
    "as": {"edition": "irvasm-ot", "kind": "usfm", "repo": "Door43-Catalog/as_irv"},
    "bn": {"edition": "irvben-ot", "kind": "usfm", "repo": "Door43-Catalog/bn_irv"},
    "pt": {"edition": "almeida", "kind": "usfx",
           "url": "https://raw.githubusercontent.com/seven1m/open-bibles/master/por-almeida.usfx.xml"},
}


def _get(url: str, t: int = 60) -> str:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                  timeout=t).read().decode("utf-8", "replace")


# ---------------------------------------------------------------- source readers
def read_aquifer_md(path: Path):
    """Yield (bbcccvvv, text) for OT verses from staged Aquifer scripture .md."""
    for f in path.glob("*.md"):
        raw = f.read_text(encoding="utf-8")
        m = re.search(r"passages:\s*\n\s*-\s*\[(\d+)\s*,", raw)
        if not m:
            continue
        ref = int(m.group(1))
        if ref // 1_000_000 not in _OT:
            continue
        body = raw.split("---", 2)[-1].strip()
        body = re.sub(r"^\d+\s+", "", body)   # drop leading verse-number prefix
        if body:
            yield ref, body


_USFM_NOTE = re.compile(r"\\(f|x|fe)\b.*?\\\1\*", re.S | re.I)
_USFM_WORD = re.compile(r"\\w\s+([^\\|]*?)(?:\|[^\\]*?)?\\w\*", re.S)
_USFM_ZALN = re.compile(r"\\zaln-[se]\b[^\n\\]*?(?:\\\*)?")


def read_usfm(repo: str):
    """Yield (bbcccvvv, text) for OT verses from a Door43 repo's USFM."""
    base = f"https://git.door43.org/{repo}/raw/branch/master"
    man = yaml.safe_load(_get(f"{base}/manifest.yaml"))
    for p in man.get("projects", []):
        code = p["identifier"].upper()
        if code not in BOOK_NUMBERS or BOOK_NUMBERS[code] not in _OT:
            continue
        try:
            usfm = _get(f"{base}/{p['path'].lstrip('./')}")
        except Exception as e:
            print(f"  {repo} {code}: {e}", file=sys.stderr)
            continue
        usfm = _USFM_NOTE.sub("", usfm)
        usfm = _USFM_ZALN.sub("", usfm)
        usfm = _USFM_WORD.sub(r"\1", usfm)         # keep word text, drop attrs
        toks = list(re.finditer(r"\\(c|v)\s+(\d+)", usfm))
        chap = 0
        for i, m in enumerate(toks):
            if m.group(1) == "c":
                chap = int(m.group(2))
                continue
            verse = int(m.group(2))
            end = toks[i + 1].start() if i + 1 < len(toks) else len(usfm)
            text = re.sub(r"\\[a-z0-9]+\*?", " ", usfm[m.end():end])  # strip residual markers
            text = re.sub(r"\s+", " ", text).strip()
            if chap and text:
                try:
                    yield encode(code, chap, verse), text
                except ValueError:
                    continue


def read_usfx(url: str):
    """Yield (bbcccvvv, text) for OT verses from a USFX XML Bible (milestones)."""
    xml = _get(url)
    for bm in re.finditer(r'<book\s+id="([A-Za-z0-9]{3})"\s*>(.*?)</book>', xml, re.S):
        code = bm.group(1).upper()
        if code not in BOOK_NUMBERS or BOOK_NUMBERS[code] not in _OT:
            continue
        body = re.sub(r"<f\b.*?</f>", "", bm.group(2), flags=re.S)   # footnotes
        body = re.sub(r"<x\b.*?</x>", "", body, flags=re.S)           # cross-refs
        toks = list(re.finditer(r'<c\s+id="(\d+)"\s*/?>|<v\s+id="([\d-]+)"[^>]*?/?>', body))
        chap = 0
        for i, m in enumerate(toks):
            if m.group(1):
                chap = int(m.group(1))
                continue
            v = m.group(2).split("-")[0]
            end = toks[i + 1].start() if i + 1 < len(toks) else len(body)
            text = re.sub(r"<[^>]+>", " ", body[m.end():end])         # strip tags (incl <ve/>)
            text = re.sub(r"\s+", " ", text).strip()
            if chap and v.isdigit() and text:
                try:
                    yield encode(code, chap, int(v)), text
                except ValueError:
                    continue


# ------------------------------------------------------------------------- emit
def emit(lang: str, cfg: dict) -> int:
    edition = cfg["edition"]
    out_root = STAGING / edition
    if out_root.is_dir():
        for old in out_root.rglob("*.md"):
            old.unlink()
    if cfg["kind"] == "aquifer_md":
        verses = read_aquifer_md(cfg["path"])
    elif cfg["kind"] == "usfm":
        verses = read_usfm(cfg["repo"])
    else:
        verses = read_usfx(cfg["url"])

    n = 0
    for ref, text in verses:
        book, chap, vnum = decode(ref)
        tags = [f"resource:{edition}", "kind:bible", f"book:{book}", f"lang:{to_web(canon(lang))}"]
        front = {"title": f"{edition} — {book} {chap}:{vnum}",
                 "tags": sorted(tags), "passages": [[ref, ref]]}
        d = out_root / book / str(chap)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{chap:03d}_{vnum:03d}.md").write_text(
            "---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
            + "\n---\n\n" + text + "\n", encoding="utf-8")
        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", action="append", choices=list(CONFIG),
                    help="language(s) to complete; default all (fr, as, bn, pt)")
    args = ap.parse_args()
    langs = args.lang or list(CONFIG)
    for lang in langs:
        cfg = CONFIG[lang]
        print(f"=== {lang} OT → resource:{cfg['edition']} ({cfg['kind']}) ===", file=sys.stderr)
        try:
            n = emit(lang, cfg)
            print(f"  {n} OT verses → {STAGING / cfg['edition']}", file=sys.stderr)
        except Exception as e:
            print(f"  FAILED {lang}: {e}", file=sys.stderr)
    print(f"next: python -m indexer.build --source {STAGING}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
