"""Door43 / unfoldingWord ingest.

v1 scope: English-only; ULT, UST, TN, TQ, TWL plus the TW articles and TA
modules referenced from the requested books' TWL / TN. One or more books per run.

Output: per-row markdown files staged under
`ingest/_staging/door43/<resource>/...`. Those staging files are then
consumed by `indexer.build` via the standard MarkdownAdapter — keeping
the indexer source-agnostic.

Resource layout:
  ULT/UST  one Document per verse        passage = the verse
  TN/TQ    one Document per row          passage = parsed from Reference field
  TWL      one Document per row (link)   passage = parsed from Reference field
  TW       one Document per article      passage = inherited from TWLs that link it
  TA       one Document per module       passage = inherited from TNs that reference it

URL conventions:
  ULT/UST verse texts: USFM at `<RAW>/<repo>/raw/branch/master/<NN>-<BBB>.usfm`
                       where NN is the Paratext file prefix (NT shifted +1
                       relative to canonical Protestant numbering).
  TN/TQ/TWL:           TSV at `<RAW>/<repo>/raw/branch/master/<res>_<BBB>.tsv`
  TW article:          `<RAW>/en_tw/raw/branch/master/<bible/cat/term>.md`
  TA module:           `<RAW>/en_ta/raw/branch/master/<section/module>/01.md`
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

import httpx

from indexer.references import BOOK_NAMES, BOOK_NUMBERS, NUMBER_TO_CODE, encode


def _book_tags_from_passages(passages: list[tuple[int, int]]) -> list[str]:
    """Derive `book:<CODE>` tags from BBCCCVVV passage ranges."""
    codes: set[str] = set()
    for s, e in passages:
        s_book, e_book = s // 1_000_000, e // 1_000_000
        for n in range(s_book, e_book + 1):
            code = NUMBER_TO_CODE.get(n)
            if code:
                codes.add(code)
    return [f"book:{c}" for c in sorted(codes)]

# Door43 / Paratext file numbering (NT books are shifted +1 vs. canonical
# Protestant numbering — Paratext reserves slot 40 for an apocrypha section).
_PARATEXT_FILE_NUM: dict[str, int] = {
    code: (n if n <= 39 else n + 1) for code, n in BOOK_NUMBERS.items()
}

RAW_BASE = "https://git.door43.org/unfoldingWord"
DEFAULT_BRANCH = "master"
TIMEOUT = 30.0
PARALLEL_FETCHERS = 8

# Per-book TSV/USFM resources. (repo_name, file_path_template).
PER_BOOK_RESOURCES: dict[str, tuple[str, str]] = {
    "ult": ("en_ult", "{paratext_num:02d}-{book_upper}.usfm"),
    "ust": ("en_ust", "{paratext_num:02d}-{book_upper}.usfm"),
    "tn":  ("en_tn",  "tn_{book_upper}.tsv"),
    "tq":  ("en_tq",  "tq_{book_upper}.tsv"),
    "twl": ("en_twl", "twl_{book_upper}.tsv"),
}

TW_REPO = "en_tw"   # files: bible/{kt,names,other}/<id>.md
TA_REPO = "en_ta"   # files: <section>/<module>/01.md  (also title.md)


# ---------- HTTP ----------

def _fetch_text(url: str) -> str | None:
    try:
        r = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
    except httpx.HTTPError as e:
        print(f"  fetch error: {url}: {e}", file=sys.stderr)
        return None
    if r.status_code == 200:
        return r.text
    print(f"  {r.status_code} {url}", file=sys.stderr)
    return None


def _resource_url(resource: str, book_code: str, branch: str = DEFAULT_BRANCH) -> str:
    repo, tmpl = PER_BOOK_RESOURCES[resource]
    file_path = tmpl.format(
        book_upper=book_code.upper(),
        book_lower=book_code.lower(),
        paratext_num=_PARATEXT_FILE_NUM[book_code.upper()],
    )
    return f"{RAW_BASE}/{repo}/raw/branch/{branch}/{file_path}"


# ---------- USFM parsing ----------
# Strip USFM markup down to plain reading text.

_RE_FILE_HDR   = re.compile(r"\\(?:id|ide|usfm|sts|h|toc\d|mt\d?|ms\d?|mr|cl|cd|rem)\b[^\n]*\n?")
_RE_FOOTNOTE   = re.compile(r"\\f\s+\+?[^\\]*?\\f\*", re.DOTALL)
_RE_XREF       = re.compile(r"\\x\s+\+?[^\\]*?\\x\*", re.DOTALL)
_RE_ZALN_OPEN  = re.compile(r"\\zaln-s\s+\|[^\\]*?\\\*")
_RE_ZALN_CLOSE = re.compile(r"\\zaln-e\\\*")
_RE_W_FULL     = re.compile(r"\\w\s+([^|\\]+)\|[^\\]*?\\w\*")
_RE_PARA_TAG   = re.compile(r"\\(?:p|q\d*|m|nb|li\d*|d|sp|pi\d*|s\d*|sr|r|b|sd\d*|pmo|pm|po|pmc|pr|cls)\b\s*")
_RE_OTHER_TAG  = re.compile(r"\\[a-z]\w*\d*\*?")


def _strip_usfm(text: str) -> str:
    text = _RE_FILE_HDR.sub("", text)
    text = _RE_FOOTNOTE.sub("", text)
    text = _RE_XREF.sub("", text)
    text = _RE_ZALN_OPEN.sub("", text)
    text = _RE_ZALN_CLOSE.sub("", text)
    text = _RE_W_FULL.sub(r"\1", text)
    text = re.sub(r"\\w\s+", "", text)
    text = re.sub(r"\\w\*", "", text)
    text = _RE_PARA_TAG.sub("", text)
    text = _RE_OTHER_TAG.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return text.strip()


def parse_usfm_verses(usfm_text: str) -> list[tuple[int, int, str]]:
    """Return [(chapter, verse, plaintext), …] for each verse in the document."""
    out: list[tuple[int, int, str]] = []
    parts = re.split(r"\\c\s+(\d+)\b", usfm_text)
    for i in range(1, len(parts), 2):
        chapter = int(parts[i])
        body = parts[i + 1] if i + 1 < len(parts) else ""
        sub = re.split(r"\\v\s+(\d+(?:-\d+)?)\b", body)
        for j in range(1, len(sub), 2):
            verse_label = sub[j]
            verse_text = sub[j + 1] if j + 1 < len(sub) else ""
            cleaned = _strip_usfm(verse_text)
            if not cleaned:
                continue
            verse = int(verse_label.split("-", 1)[0])
            out.append((chapter, verse, cleaned))
    return out


# ---------- TSV reference + link parsing ----------

_RE_VERSE_RANGE = re.compile(r"^(\d+)(?:-(\d+))?")
# rc://*/tw/dict/bible/<cat>/<word>
_RE_TW_LINK = re.compile(r"rc://[^/]+/tw/dict/(bible/[a-z]+/[a-z0-9-]+)\s*$", re.IGNORECASE)
# rc://*/ta/man/<section>/<module>
_RE_TA_LINK = re.compile(r"rc://[^/]+/ta/man/([a-z]+/[a-z0-9-]+)\s*$", re.IGNORECASE)


def _parse_book_ref(book_code: str, ref: str) -> tuple[int, int] | None:
    """Convert a book-relative TSV Reference like '1:1' / '1:1-3' to a BBCCCVVV pair.

    Returns None for book/chapter intros and unparseable forms — the row still
    indexes (FTS-discoverable) but isn't surfaced by passage range filters.
    """
    if not ref or ":" not in ref:
        return None
    ch_s, v_s = ref.split(":", 1)
    if not ch_s.isdigit():
        return None
    chapter = int(ch_s)
    m = _RE_VERSE_RANGE.match(v_s)
    if not m:
        return None
    vs = int(m.group(1))
    ve = int(m.group(2)) if m.group(2) else vs
    try:
        return encode(book_code, chapter, vs), encode(book_code, chapter, ve)
    except ValueError:
        return None


def _parse_tw_link(link: str) -> str | None:
    m = _RE_TW_LINK.match(link.strip())
    return m.group(1).lower() if m else None


def _parse_ta_link(link: str) -> str | None:
    m = _RE_TA_LINK.match(link.strip())
    return m.group(1).lower() if m else None


# ---------- Staging output ----------

def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")


def _yaml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _write_md(
    path: Path,
    *,
    title: str,
    tags: Iterable[str],
    passages: list[tuple[int, int]],
    body: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---", f'title: "{_yaml_escape(title)}"']
    tags = sorted(set(tags))
    if tags:
        lines.append("tags:")
        lines.extend(f"  - {t}" for t in tags)
    if passages:
        # dedup + sort
        unique = sorted({p for p in passages})
        lines.append("passages:")
        lines.extend(f"  - [{s}, {e}]" for s, e in unique)
    lines.append("---")
    body = body.strip()
    if body:
        lines.append("")
        lines.append(body)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------- Per-book resources ----------

def _ingest_usfm(staging: Path, book_code: str, resource: str) -> int:
    """One Document per verse for ULT/UST."""
    text = _fetch_text(_resource_url(resource, book_code))
    if text is None:
        return 0
    book_name = BOOK_NAMES[book_code]
    out_dir = staging / resource
    written = 0
    for chapter, verse, content in parse_usfm_verses(text):
        bbcccvvv = encode(book_code, chapter, verse)
        title = f"{resource.upper()} — {book_name} {chapter}:{verse}"
        tags = [f"resource:{resource}", "lang:en", "org:unfoldingWord", f"book:{book_code}", "kind:scripture"]
        path = out_dir / f"{book_code.lower()}_{chapter:03d}_{verse:03d}.md"
        _write_md(path, title=title, tags=tags, passages=[(bbcccvvv, bbcccvvv)], body=content)
        written += 1
    return written


def _ingest_tn(
    staging: Path, book_code: str
) -> tuple[int, dict[str, list[tuple[int, int]]]]:
    """One Document per Translation Note row.

    Returns (count, {ta_module_path: [passages, …]}) so the caller can fetch
    the referenced TA modules and inherit their passage refs.
    """
    text = _fetch_text(_resource_url("tn", book_code))
    if text is None:
        return 0, {}
    out_dir = staging / "tn"
    book_name = BOOK_NAMES[book_code]
    written = 0
    ta_passages: dict[str, list[tuple[int, int]]] = {}

    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    for row in reader:
        ref = (row.get("Reference") or "").strip()
        note_id = (row.get("ID") or "").strip()
        note = (row.get("Note") or "").strip()
        if not note or not note_id:
            continue
        passage = _parse_book_ref(book_code, ref)
        passages = [passage] if passage else []
        title = f"TN — {book_name} {ref} ({note_id})" if ref else f"TN — {book_name} ({note_id})"
        tags = ["resource:tn", "lang:en", "org:unfoldingWord", f"book:{book_code}", "kind:translator-note"]
        sup = (row.get("SupportReference") or "").strip()
        if sup:
            tags.append(f"support_ref:{sup}")
            ta_path = _parse_ta_link(sup)
            if ta_path and passage:
                ta_passages.setdefault(ta_path, []).append(passage)
        quote = (row.get("Quote") or "").strip()
        body = note if not quote else f"**{quote}**\n\n{note}"
        path = out_dir / f"{book_code.lower()}_{_safe_name(ref or 'na')}_{note_id}.md"
        _write_md(path, title=title, tags=tags, passages=passages, body=body)
        written += 1

    return written, ta_passages


def _ingest_tq(staging: Path, book_code: str) -> int:
    """One Document per Translation Question row."""
    text = _fetch_text(_resource_url("tq", book_code))
    if text is None:
        return 0
    out_dir = staging / "tq"
    book_name = BOOK_NAMES[book_code]
    written = 0
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    for row in reader:
        ref = (row.get("Reference") or "").strip()
        q_id = (row.get("ID") or "").strip()
        question = (row.get("Question") or "").strip()
        response = (row.get("Response") or "").strip()
        if not question or not q_id:
            continue
        passage = _parse_book_ref(book_code, ref)
        passages = [passage] if passage else []
        title = f"TQ — {book_name} {ref} ({q_id})" if ref else f"TQ — {book_name} ({q_id})"
        tags = ["resource:tq", "lang:en", "org:unfoldingWord", f"book:{book_code}", "kind:question"]
        body = f"**Question**: {question}\n\n**Response**: {response}" if response else f"**Question**: {question}"
        path = out_dir / f"{book_code.lower()}_{_safe_name(ref or 'na')}_{q_id}.md"
        _write_md(path, title=title, tags=tags, passages=passages, body=body)
        written += 1
    return written


def _ingest_twl(
    staging: Path, book_code: str
) -> tuple[int, dict[str, list[tuple[int, int]]]]:
    """Parse TWL but do NOT emit Document files.

    Why ingest-only: TWL rows are passage→term-article LINKS — pure cross-
    reference metadata. Their titles ("TWL — Ruth 1:22 → bethlehem") match
    common keywords exactly, so as searchable Documents they win FTS / title
    retrieval and crowd out substantive content — yet their bodies have
    zero answer-value (just "At <ref>, <word> maps to <link>"). The
    information they carry — which TW articles cover which passages — is
    already captured by `_ingest_referenced_tw`, which inherits the
    `tw_passages` map onto each downloaded TW article's passage_refs.

    Pattern: translation-helps-mcp style — *don't index what you can derive
    on demand*. See README "Three patterns from those MCPs" for context.

    Returns (0, {tw_article_path: [passages, …]}). The 0 keeps the same
    return shape as the other ingesters; the caller doesn't need to know.
    """
    text = _fetch_text(_resource_url("twl", book_code))
    if text is None:
        return 0, {}
    tw_passages: dict[str, list[tuple[int, int]]] = {}

    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    for row in reader:
        link = (row.get("TWLink") or "").strip()
        if not link:
            continue
        tw_path = _parse_tw_link(link)
        if not tw_path:
            continue
        passage = _parse_book_ref(book_code, (row.get("Reference") or "").strip())
        if passage:
            tw_passages.setdefault(tw_path, []).append(passage)

    return 0, tw_passages


# ---------- Cross-resource: TW & TA ----------

def _ingest_referenced_tw(staging: Path, paths_to_passages: dict[str, list[tuple[int, int]]]) -> int:
    """Fetch every TW article in paths_to_passages.keys(), inherit its passages."""
    if not paths_to_passages:
        return 0
    out_dir = staging / "tw"
    items = sorted(paths_to_passages.items())

    def fetch_one(path: str) -> tuple[str, str | None]:
        url = f"{RAW_BASE}/{TW_REPO}/raw/branch/{DEFAULT_BRANCH}/{path}.md"
        return path, _fetch_text(url)

    written = 0
    with ThreadPoolExecutor(max_workers=PARALLEL_FETCHERS) as pool:
        futures = {pool.submit(fetch_one, p): (p, ps) for p, ps in items}
        for fut in as_completed(futures):
            path, ps = futures[fut]
            _, text = fut.result()
            if text is None:
                continue
            category, term = path.split("/")[-2:]
            title = f"TW — {term.replace('-', ' ').title()} ({category})"
            # Strong's anchors from the term's gloss family — so this English
            # article is reachable from any language via the concept bridge
            # (e.g. Spanish "amor" → strongs:G0026 → tag_search). See
            # query.concept_expand.term_strongs / internal-docs/branch-denoising.md.
            from query.concept_expand import term_strongs
            tags = ["resource:tw", "lang:en", "org:unfoldingWord",
                    f"category:{category}", f"term:{term}", "kind:term",
                    *(f"strongs:{c}" for c in term_strongs(term.replace('-', ' '))),
                    *_book_tags_from_passages(ps)]
            out_path = out_dir / category / f"{term}.md"
            _write_md(out_path, title=title, tags=tags, passages=ps, body=text.strip())
            written += 1
    return written


def _ingest_referenced_ta(staging: Path, paths_to_passages: dict[str, list[tuple[int, int]]]) -> int:
    """Fetch each TA module's body (and title.md if present)."""
    if not paths_to_passages:
        return 0
    out_dir = staging / "ta"
    items = sorted(paths_to_passages.items())

    def fetch_one(path: str) -> tuple[str, str | None, str | None]:
        url_body = f"{RAW_BASE}/{TA_REPO}/raw/branch/{DEFAULT_BRANCH}/{path}/01.md"
        url_title = f"{RAW_BASE}/{TA_REPO}/raw/branch/{DEFAULT_BRANCH}/{path}/title.md"
        return path, _fetch_text(url_body), _fetch_text(url_title)

    written = 0
    with ThreadPoolExecutor(max_workers=PARALLEL_FETCHERS) as pool:
        futures = {pool.submit(fetch_one, p): (p, ps) for p, ps in items}
        for fut in as_completed(futures):
            path, ps = futures[fut]
            _, body, title_text = fut.result()
            if body is None:
                continue
            section, module = path.split("/", 1)
            title_text = (title_text or "").strip()
            title = f"TA — {title_text}" if title_text else f"TA — {module.replace('-', ' ')} ({section})"
            tags = ["resource:ta", "lang:en", "org:unfoldingWord",
                    f"section:{section}", f"module:{module}", "kind:methodology",
                    *_book_tags_from_passages(ps)]
            out_path = out_dir / section / f"{module}.md"
            _write_md(out_path, title=title, tags=tags, passages=ps, body=body.strip())
            written += 1
    return written


# ---------- Public API ----------

def ingest_book(book_code: str, staging: Path) -> dict:
    """Fetch + stage one book's per-book resources.

    Returns a dict with `counts` for each per-book resource and the
    `tw_refs` / `ta_refs` maps that should be combined across books before
    a single TW/TA fetch pass at the end.
    """
    book_code = book_code.upper()
    if book_code not in BOOK_NUMBERS:
        raise ValueError(f"unknown book code: {book_code}")

    counts: dict[str, int] = {}
    # ULT/UST scripture ingest disabled — BSB covers all 66 books as the
    # single English Bible source. Re-enable when adding multi-language or
    # multi-version support.
    # counts["ult"] = _ingest_usfm(staging, book_code, "ult")
    # counts["ust"] = _ingest_usfm(staging, book_code, "ust")
    counts["tn"], ta_refs = _ingest_tn(staging, book_code)
    counts["tq"] = _ingest_tq(staging, book_code)
    # TWL is parsed for its cross-references only — no Documents emitted.
    # The link metadata flows into TW articles' inherited passage refs.
    _, tw_refs = _ingest_twl(staging, book_code)
    return {"counts": counts, "tw_refs": tw_refs, "ta_refs": ta_refs}


def ingest_books(book_codes: list[str], staging: Path) -> dict[str, int]:
    """Ingest one or more books + their referenced TW/TA articles."""
    counts: dict[str, int] = {}
    tw_refs: dict[str, list[tuple[int, int]]] = {}
    ta_refs: dict[str, list[tuple[int, int]]] = {}

    for book in book_codes:
        result = ingest_book(book, staging)
        for k, v in result["counts"].items():
            counts[k] = counts.get(k, 0) + v
        for path, ps in result["tw_refs"].items():
            tw_refs.setdefault(path, []).extend(ps)
        for path, ps in result["ta_refs"].items():
            ta_refs.setdefault(path, []).extend(ps)

    counts["tw_refs"] = len(tw_refs)
    counts["ta_refs"] = len(ta_refs)
    counts["tw"] = _ingest_referenced_tw(staging, tw_refs)
    counts["ta"] = _ingest_referenced_ta(staging, ta_refs)
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", action="append", help="USFM book code (repeatable, e.g. --book TIT --book RUT)")
    ap.add_argument("--all-books", action="store_true",
                    help="ingest all 66 books — full TN/TQ/TW/TA + the complete "
                         "referenced TW term-article set (BSB already covers scripture).")
    ap.add_argument("--lang", default="en", help="language (only 'en' supported in v1)")
    ap.add_argument("--staging", type=Path,
                    default=Path(__file__).resolve().parent / "_staging" / "door43")
    args = ap.parse_args()
    if not args.book and not args.all_books:
        ap.error("pass --book <CODE> (repeatable) or --all-books")

    from indexer.env import load_env
    load_env()

    from lang import canon
    if canon(args.lang) != "eng":
        print("v1: English only", file=sys.stderr)
        return 2
    if args.all_books:
        books = [NUMBER_TO_CODE[n] for n in range(1, 67) if n in NUMBER_TO_CODE]
    else:
        books = [b.upper() for b in args.book]
    counts = ingest_books(books, args.staging)
    print(json.dumps({
        "books": books,
        "staged_files": counts,
        "staging_dir": str(args.staging),
    }, indent=2))
    return 0


if __name__ == "__main__":
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.exit(main())
