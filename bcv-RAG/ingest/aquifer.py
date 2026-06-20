"""Aquifer ingest — BibleAquifer GitHub org content (multilingual).

BibleAquifer carries the same resource repos in many languages (study notes,
Bible dictionary, unfoldingWord TN/TW/TQ, key terms, …). For each requested
book and the requested language, scan every public BibleAquifer repo for
`<aquifer-dir>/json/<NN>.content.json` (NN = canonical Protestant book number,
two-digit zero-padded). Each text article becomes one staged Document.

Output: `ingest/_staging/aquifer/<lang>/<RepoName>/<content_id>.md` — namespaced
by language so the MarkdownAdapter's path-derived doc-id is unique per language
(otherwise the same content_id collides across languages). Build with
`indexer.build --source ingest/_staging/aquifer` (the per-language subdir is
part of each relative path). Stage every language you want, THEN build once.

Languages: pass our code (`--lang es`); mapped to Aquifer's ISO-639-3 dir via
`_AQUIFER_LANG`. Repos lacking a language simply yield nothing. Coverage (per
resources-map.md): study notes + dictionary + UW TN/TW/TQ in es/fr/pt/ru/ar/hi;
bn/as are thin (use Door43); ha is visual-only.

Auth: anonymous works for one-off ingest (GitHub allows 60 unauth req/hr).
Set `GITHUB_TOKEN` in `.env` to bump to 5000/hr for repeated runs.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser

from lang import canon, to_web
from pathlib import Path

import httpx

from indexer.references import BOOK_NAMES, BOOK_NUMBERS, NUMBER_TO_CODE

GITHUB_API = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"
ORG = "BibleAquifer"
# Map our language codes → BibleAquifer's ISO-639-3 content dir. Anything not
# here is passed through unchanged (so an aquifer dir like "swh"/"nep"/"zht"
# can be given directly). Repos without a given language's dir just 404 and skip.
_AQUIFER_LANG = {
    "en": "eng", "es": "spa", "fr": "fra", "pt": "por", "ru": "rus",
    "ar": "arb", "hi": "hin", "bn": "ben", "as": "asm", "ha": "hau",
}
BRANCH_CANDIDATES = ("main", "master")
TIMEOUT = 30.0
PARALLEL_FETCHERS = 16

# Per-repo content-kind classification. Mirrors the source-agnostic taxonomy
# emitted by `door43.py` (kind:scripture / kind:translator-note / etc.) so an
# eval or filter that asks for "scripture" picks up Berean Standard Bible AND
# Door43 ULT AND World English Bible without caring which provider supplied it.
_REPO_KIND: dict[str, str] = {
    # Bible text translations
    "BereanStandardBible": "scripture",
    "WorldEnglishBible": "scripture",
    "WorldEnglishBibleUpdated": "scripture",
    "unfoldingWordLiteral": "scripture",
    "unfoldingWordSimplified": "scripture",
    "ChineseUnionVersionTraditional": "scripture",
    "RussianSynodalBible": "scripture",
    "ReinaValera1909": "scripture",
    "LouisSegond1910": "scripture",
    "ArabicVanDyckBible": "scripture",
    "IndianRevisedVersion": "scripture",
    "NepaliUnlockedLiteralBible": "scripture",
    "OpenBislamaBibleRevised": "scripture",
    "OpenHindiContemporaryVersion": "scripture",
    "OpenKiswahiliContemporaryVersion": "scripture",
    "BiblicaOpenNepaliContemporaryVersion": "scripture",
    "BiblicaOpenNewArabicVersion2012": "scripture",
    "AquiferPortugueseBibleReferenceText": "scripture",
    "AquiferSpanishBibleReferenceText": "scripture",
    "GatewayLiteralTextHindi": "scripture",
    "GatewayLiteralTextIndonesian": "scripture",
    "GatewaySimplifiedTextHindi": "scripture",
    "GatewaySimplifiedTextIndonesian": "scripture",
    "IndianRevisedVersionGujarati": "scripture",
    "SBLGNT": "scripture",
    # Translator notes
    "SILOpenTranslatorsNotes": "translator-note",
    "UWTranslationNotes": "translator-note",
    # Comprehension questions
    "UWTranslationQuestions": "question",
    # Study notes / commentary
    "AquiferOpenStudyNotes": "study-note",
    "AquiferOpenStudyNotesProfiles": "study-note",
    "AquiferOpenStudyNotesThemes": "study-note",
    "BiblicaStudyNotes": "study-note",
    # Book introductions
    "AquiferOpenStudyNotesBookIntros": "book-intro",
    "AquiferOpenStudyNotesBookIntroSummaries": "book-intro",
    "BiblicaStudyNotesBookIntros": "book-intro",
    # Translation methodology
    "FIATranslationGuide": "methodology",
    # Term definitions / dictionaries
    "AquiferOpenBibleDictionary": "term",
    "BiblicaStudyNotesKeyTerms": "term",
    "DictionaryBibleThemes": "term",
    "FIAKeyTerms": "term",
    # Visual assets
    "FIAMaps": "map",
    "BiblicaOpenBibleMaps": "map",
    "FIAImages": "image",
}
_DEFAULT_KIND = "study-note"

# Repos to skip by default during ingest. Aquifer is intended as
# **supplementary breadth** — extra study notes, commentaries, and unique
# perspectives — not as a competing source of primary translation content.
# Two categories of repos are excluded by default:
#
#   1. Mirrors of Door43 unfoldingWord material we already ingest natively.
#      Indexing both produces near-duplicate chunks that crowd out the
#      Door43 originals from top-K under any narrow passage filter.
#
#   2. Alternative full-Bible translations (BSB, WEB, WEBu). Useful for
#      cross-translation comparison but they multiply scripture-text
#      coverage 4-5x, displacing study/commentary content from top-K on
#      thematic queries.
#
# Use `--include-skipped` (or `--repos <name>` for an explicit allowlist)
# to bring them back when needed.
_SKIP_BY_DEFAULT: set[str] = {
    # Door43 mirrors
    "unfoldingWordLiteral",
    "unfoldingWordSimplified",
    "UWTranslationNotes",
    "UWTranslationQuestions",
    # Alternative full-Bible translations
    "BereanStandardBible",
    "WorldEnglishBible",
    "WorldEnglishBibleUpdated",
}


# ---------- HTTP ----------

def _gh_headers() -> dict[str, str]:
    h = {"User-Agent": "bcv-query-ingest/1.0", "Accept": "application/vnd.github+json"}
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _list_repos() -> list[str]:
    """List public repo names in the BibleAquifer org."""
    out: list[str] = []
    page = 1
    while True:
        try:
            r = httpx.get(
                f"{GITHUB_API}/orgs/{ORG}/repos",
                params={"per_page": 100, "page": page, "type": "public"},
                headers=_gh_headers(),
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as e:
            print(f"  list_repos: {e}", file=sys.stderr)
            break
        if r.status_code != 200:
            print(f"  list_repos: {r.status_code} {r.text[:200]}", file=sys.stderr)
            break
        data = r.json()
        if not data:
            break
        for repo in data:
            name = repo.get("name", "")
            if name and not name.startswith("."):
                out.append(name)
        if len(data) < 100:
            break
        page += 1
    return out


def _content_file_url(repo: str, book_code: str, branch: str, lang_dir: str) -> str:
    book_num = BOOK_NUMBERS[book_code]
    return f"{RAW_BASE}/{ORG}/{repo}/{branch}/{lang_dir}/json/{book_num:02d}.content.json"


def _fetch_content_file(repo: str, book_code: str, lang_dir: str) -> list[dict] | None:
    """Fetch the per-book content file from one repo. None if absent / unparseable."""
    for branch in BRANCH_CANDIDATES:
        try:
            r = httpx.get(_content_file_url(repo, book_code, branch, lang_dir),
                          timeout=TIMEOUT, follow_redirects=True)
        except httpx.HTTPError:
            continue
        if r.status_code == 200:
            try:
                data = r.json()
                return data if isinstance(data, list) else None
            except json.JSONDecodeError:
                return None
    return None


# ---------- HTML → plain text ----------

class _TextExtractor(HTMLParser):
    """Minimal stdlib HTML stripper. Drops markup, keeps anchor text, normalizes whitespace."""

    _BLOCK = {"br", "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6",
              "tr", "blockquote", "section", "article", "table"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._BLOCK:
            self._chunks.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK:
            self._chunks.append(" ")

    def get_text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._chunks)).strip()


def _html_to_text(html_str: str) -> str:
    if not html_str:
        return ""
    p = _TextExtractor()
    try:
        p.feed(html_str)
    except Exception:
        # Malformed HTML — fall back to a regex strip.
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_str)).strip()
    return p.get_text()


# ---------- Reference parsing ----------

_RE_AQUIFER_REF = re.compile(r"^(\d{6,8})(?:-(\d{6,8}))?$")


def _parse_aquifer_ref(idx_ref: str) -> list[tuple[int, int]]:
    """Aquifer's index_reference is BBCCCVVV[-BBCCCVVV]. May omit leading 0."""
    if not idx_ref:
        return []
    m = _RE_AQUIFER_REF.match(idx_ref.strip())
    if not m:
        return []
    try:
        s = int(m.group(1))
        e = int(m.group(2)) if m.group(2) else s
    except ValueError:
        return []
    return [(s, e) if s <= e else (e, s)]


def _book_tags_from_passages(passages: list[tuple[int, int]]) -> list[str]:
    codes: set[str] = set()
    for s, e in passages:
        for n in range(s // 1_000_000, e // 1_000_000 + 1):
            code = NUMBER_TO_CODE.get(n)
            if code:
                codes.add(code)
    return [f"book:{c}" for c in sorted(codes)]


# ---------- Output staging ----------

def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")


def _yaml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _write_md(
    path: Path,
    *,
    title: str,
    tags: list[str],
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
        lines.append("passages:")
        lines.extend(f"  - [{s}, {e}]" for s, e in sorted(set(passages)))
    lines.append("---")
    body = body.strip()
    if body:
        lines.append("")
        lines.append(body)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _stage_articles(staging: Path, repo: str, articles: list[dict], lang: str) -> int:
    # Namespace by language: <staging>/<lang>/<repo>/<id>.md. The lang segment
    # makes the adapter's path-relative doc-id unique across languages (same
    # content_id otherwise collides and later languages overwrite earlier ones).
    out_dir = staging / lang / repo
    written = 0
    for article in articles:
        content_id = str(article.get("content_id", "")).strip()
        if not content_id:
            continue
        media_type = (article.get("media_type") or "").strip().lower()
        if media_type and media_type != "text":
            # Skip image/audio/video articles — bodies are URLs, not prose.
            continue
        passages = _parse_aquifer_ref(article.get("index_reference") or "")
        body = _html_to_text(article.get("content") or "")
        if not body:
            continue  # pure-metadata article — nothing to embed or read
        title_raw = (article.get("title") or "").strip() or f"Article {content_id}"
        title = f"Aquifer {repo} — {title_raw}"
        kind = _REPO_KIND.get(repo, _DEFAULT_KIND)
        tags = ["resource:aquifer", f"aquifer:{repo}", f"lang:{to_web(canon(lang))}", f"kind:{kind}",
                *_book_tags_from_passages(passages)]
        for entry in (article.get("associations") or {}).get("acai") or []:
            entity_id = entry.get("id")
            if entity_id:
                tags.append(f"acai:{str(entity_id).lower()}")
        out_path = out_dir / f"{_safe(content_id)}.md"
        _write_md(out_path, title=title, tags=tags, passages=passages, body=body)
        written += 1
    return written


# ---------- Public API ----------

def ingest_books(
    book_codes: list[str],
    staging: Path,
    *,
    lang: str = "en",
    repos: list[str] | None = None,
    include_skipped: bool = False,
) -> dict[str, int]:
    """Stage every Aquifer article in `lang` that covers one of `book_codes`.

    `lang` is our code (es, fr, …), mapped to the Aquifer content dir via
    `_AQUIFER_LANG`. By default skips Aquifer repos that mirror Door43 content
    or are alternative full-Bible translations (see `_SKIP_BY_DEFAULT`). Pass
    `include_skipped=True` to ingest those too, or pass `repos=[…]` for an
    explicit allowlist (skip filter does NOT apply when `repos` is given).
    """
    lang_dir = _AQUIFER_LANG.get(lang, lang)
    book_codes = [b.upper() for b in book_codes]
    for code in book_codes:
        if code not in BOOK_NUMBERS:
            raise ValueError(f"unknown book code: {code}")

    if repos is None:
        print(f"listing {ORG} repos…", file=sys.stderr)
        repos = _list_repos()
        print(f"  {len(repos)} repos in org", file=sys.stderr)
        if not include_skipped:
            before = len(repos)
            # Skip the explicit list AND every Bible-text / media repo by kind:
            # Aquifer is for STUDY breadth (notes, dictionaries, key terms), not
            # primary Bible text (we ingest Bibles via the aligned pipeline) or
            # binary assets. Bring them back with --include-skipped / --repos.
            repos = [r for r in repos if r not in _SKIP_BY_DEFAULT
                     and _REPO_KIND.get(r) not in {"scripture", "map", "image"}]
            skipped = before - len(repos)
            if skipped:
                print(f"  {skipped} repos skipped by default (Bibles / media / mirrors)", file=sys.stderr)
    if not repos:
        return {"repos_scanned": 0, "repos_with_content": 0, "articles": 0}

    pairs = [(repo, book) for repo in repos for book in book_codes]
    print(f"fetching {len(pairs)} (repo, book) content files…", file=sys.stderr)

    counts = {"repos_scanned": len(repos), "repos_with_content": 0, "articles": 0}
    repos_with_content: set[str] = set()

    def fetch_one(pair: tuple[str, str]):
        repo, book = pair
        return repo, book, _fetch_content_file(repo, book, lang_dir)

    with ThreadPoolExecutor(max_workers=PARALLEL_FETCHERS) as pool:
        futures = [pool.submit(fetch_one, p) for p in pairs]
        for fut in as_completed(futures):
            repo, book, articles = fut.result()
            if not articles:
                continue
            staged = _stage_articles(staging, repo, articles, lang)
            if staged > 0:
                repos_with_content.add(repo)
                counts["articles"] += staged

    counts["repos_with_content"] = len(repos_with_content)
    return counts


def ingest_book(book_code: str, staging: Path) -> dict:
    """Single-book convenience wrapper. Door43-shaped return signature."""
    counts = ingest_books([book_code], staging)
    return {"counts": counts, "tw_refs": {}, "ta_refs": {}}


# ---------- CLI ----------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", action="append",
                    help="USFM book code (repeatable, e.g. --book TIT). Default: all 66 books")
    ap.add_argument("--lang", default="en",
                    help="our language code (en, es, fr, pt, ru, ar, hi, …); mapped to "
                         "the Aquifer ISO-639-3 dir. An aquifer dir (swh, nep, …) also works")
    ap.add_argument("--repos", action="append",
                    help="restrict to specific BibleAquifer repos (repeatable; default: all minus the skip list)")
    ap.add_argument("--include-skipped", action="store_true",
                    help="include the default-skipped Aquifer repos (Door43 mirrors + alternative full-Bible translations)")
    ap.add_argument("--staging", type=Path,
                    default=Path(__file__).resolve().parent / "_staging" / "aquifer")
    args = ap.parse_args()

    from indexer.env import load_env
    load_env()

    books = [b.upper() for b in args.book] if args.book else \
        sorted(BOOK_NUMBERS, key=BOOK_NUMBERS.get)

    counts = ingest_books(
        books,
        args.staging,
        lang=args.lang,
        repos=args.repos,
        include_skipped=args.include_skipped,
    )
    print(json.dumps({
        "lang": args.lang,
        "books": len(books),
        "staged": counts,
        "staging_dir": str(args.staging / args.lang),
        "build_with": f"python -m indexer.build --source {args.staging}",
    }, indent=2))
    return 0


if __name__ == "__main__":
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.exit(main())
