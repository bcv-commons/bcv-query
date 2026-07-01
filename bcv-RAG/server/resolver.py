"""Chunk-id resolver + tree-path derivation + cross-references.

Centralizes the logic that turns an internal chunk_id into a user-facing
record with tree paths, cross-refs, and the canonical permalink. Used by
both REST handlers and MCP tools.
"""
from __future__ import annotations

import json
import re
import sqlite3

from indexer.references import BOOK_NUMBERS, NUMBER_TO_CODE, decode, human
from lang import canon

# rc://*/ta/man/<section>/<module>
_RE_TA_LINK = re.compile(r"ta/man/([a-z]+)/([a-z0-9-]+)", re.IGNORECASE)


# ---------- tag helpers ----------

def kind_from_tags(tags: list[str]) -> str | None:
    for t in tags:
        if t.startswith("kind:"):
            return t[len("kind:"):]
    return None


def first_tag(tags: list[str], prefix: str) -> str | None:
    for t in tags:
        if t.startswith(prefix):
            return t[len(prefix):]
    return None


def tags_with_prefix(tags: list[str], prefix: str) -> list[str]:
    return [t[len(prefix):] for t in tags if t.startswith(prefix)]


# ---------- DB lookups ----------

def fetch_doc_tags(db: sqlite3.Connection, doc_id: str) -> list[str]:
    return [r[0] for r in db.execute(
        "SELECT tag FROM tags WHERE doc_id = ? ORDER BY tag", (doc_id,)
    ).fetchall()]


def fetch_doc_passages(db: sqlite3.Connection, doc_id: str) -> list[tuple[int, int]]:
    return [(r[0], r[1]) for r in db.execute(
        "SELECT start_bbcccvvv, end_bbcccvvv FROM passage_refs WHERE doc_id = ? "
        "ORDER BY start_bbcccvvv",
        (doc_id,),
    ).fetchall()]


# ---------- tree paths ----------

def derive_tree_paths(
    tags: list[str],
    passages: list[tuple[int, int]],
    *,
    lang: str = "en",
) -> list[str]:
    """Return ordered tree paths for a chunk. First entry = primary.

    Ordering rule: a chunk's natural home depends on its kind. Term articles
    live primarily under /term, methodology articles under /methodology, and
    scripture under /scripture. Inherited passage refs (e.g., a TW article
    that picked up Titus 1:6 from a TWL link) become alternate paths, not
    the primary one — otherwise a TW article would appear to "live" at a
    Bible verse.
    """
    lang = canon(lang)
    paths: list[str] = []
    seen: set[str] = set()

    def add(p: str) -> None:
        if p not in seen:
            paths.append(p)
            seen.add(p)

    kind = kind_from_tags(tags)

    # ---- 1. Kind-natural primary path ----
    if kind == "term":
        cat = first_tag(tags, "category:")
        term = first_tag(tags, "term:")
        if cat and term:
            add(f"/{lang}/term/{cat}/{term}")
    elif kind == "methodology":
        sec = first_tag(tags, "section:")
        mod = first_tag(tags, "module:")
        if sec and mod:
            add(f"/{lang}/methodology/{sec}/{mod}")

    # ---- 2. Scripture path(s) ----
    # Always added (when passages exist) but rank below the kind-natural
    # path for non-scripture kinds.
    for s, e in passages:
        try:
            s_code, s_chap, s_verse = decode(s)
        except ValueError:
            continue
        n = BOOK_NUMBERS[s_code]
        testament = "ot" if n <= 39 else "nt"
        if (e - s) < 999:
            add(f"/{lang}/scripture/{testament}/{s_code}/{s_chap}/{s_verse}")
        else:
            add(f"/{lang}/scripture/{testament}/{s_code}")

    # ---- 3. Source path ----
    is_aquifer = "resource:aquifer" in tags
    if is_aquifer:
        repo = first_tag(tags, "aquifer:")
        add(f"/{lang}/source/aquifer/{repo}" if repo else f"/{lang}/source/aquifer")
    else:
        for resource in ("ult", "ust", "tn", "tq", "tw", "ta", "twl"):
            if f"resource:{resource}" in tags:
                sub = ""
                if resource in ("ult", "ust", "tn", "tq", "twl"):
                    book = first_tag(tags, "book:")
                    if book:
                        sub = f"/{book}"
                elif resource == "tw":
                    cat = first_tag(tags, "category:")
                    term = first_tag(tags, "term:")
                    if cat and term:
                        sub = f"/{cat}/{term}"
                    elif cat:
                        sub = f"/{cat}"
                elif resource == "ta":
                    sec = first_tag(tags, "section:")
                    mod = first_tag(tags, "module:")
                    if sec and mod:
                        sub = f"/{sec}/{mod}"
                    elif sec:
                        sub = f"/{sec}"
                add(f"/{lang}/source/door43/{resource}{sub}")
                break

    # ---- 4. Kind generic path ----
    if kind:
        add(f"/{lang}/kind/{kind}")

    # ---- 5. Pericope (only for narrow, verbatim ranges) ----
    for s, e in passages:
        if (e - s) < 999_999:
            add(f"/{lang}/pericope/{s}-{e}")

    return paths


# ---------- cross references ----------

def derive_cross_refs(
    db: sqlite3.Connection,
    doc_id: str,
    tags: list[str],
    passages: list[tuple[int, int]],
    *,
    lang: str = "en",
    limit: int = 10,
) -> dict[str, list[dict]]:
    """Compute three cross-reference lists: passage / support_ref / term."""
    out: dict[str, list[dict]] = {"passage": [], "support_ref": [], "term": []}

    if passages:
        where = " OR ".join(
            "(passage_refs.start_bbcccvvv <= ? AND passage_refs.end_bbcccvvv >= ?)"
            for _ in passages
        )
        params: list = []
        for s, e in passages:
            params.extend([e, s])
        rows = db.execute(
            f"""
            SELECT DISTINCT documents.id
            FROM documents
            JOIN passage_refs ON passage_refs.doc_id = documents.id
            WHERE documents.id != ?
              AND ({where})
            LIMIT ?
            """,
            [doc_id, *params, limit],
        ).fetchall()
        for (did,) in rows:
            preview = chunk_summary(db, did, lang=lang)
            if preview:
                out["passage"].append(preview)

    sup_refs = [t for t in tags if t.startswith("support_ref:")]
    if sup_refs:
        for ref in sup_refs:
            m = _RE_TA_LINK.search(ref)
            if not m:
                continue
            section, module = m.group(1).lower(), m.group(2).lower()
            rows = db.execute(
                """
                SELECT documents.id
                FROM documents
                JOIN tags AS t1 ON t1.doc_id = documents.id AND t1.tag = ?
                JOIN tags AS t2 ON t2.doc_id = documents.id AND t2.tag = ?
                LIMIT ?
                """,
                (f"section:{section}", f"module:{module}", limit),
            ).fetchall()
            for (did,) in rows:
                preview = chunk_summary(db, did, lang=lang)
                if preview:
                    out["support_ref"].append(preview)

    term_tags = [t for t in tags if t.startswith("term:") or t.startswith("acai:")]
    if term_tags:
        placeholders = ",".join("?" * len(term_tags))
        rows = db.execute(
            f"""
            SELECT DISTINCT documents.id
            FROM documents
            JOIN tags ON tags.doc_id = documents.id
            WHERE documents.id != ?
              AND tags.tag IN ({placeholders})
            LIMIT ?
            """,
            [doc_id, *term_tags, limit],
        ).fetchall()
        for (did,) in rows:
            preview = chunk_summary(db, did, lang=lang)
            if preview:
                out["term"].append(preview)

    return out


# ---------- chunk preview / full ----------

def chunk_summary(
    db: sqlite3.Connection,
    doc_id: str,
    *,
    lang: str = "en",
) -> dict | None:
    """Compact preview for cross-ref lists. chunk_index=0 only."""
    row = db.execute(
        """
        SELECT chunks.id, documents.title
        FROM chunks
        JOIN documents ON documents.id = chunks.doc_id
        WHERE chunks.doc_id = ? AND chunks.chunk_index = 0
        """,
        (doc_id,),
    ).fetchone()
    if not row:
        return None
    chunk_id, title = row
    tags = fetch_doc_tags(db, doc_id)
    passages = fetch_doc_passages(db, doc_id)
    paths = derive_tree_paths(tags, passages, lang=lang)
    return {
        "chunk_id": chunk_id,
        "title": title,
        "kind": kind_from_tags(tags),
        "passage": humanize_passages(passages),
        "primary_path": paths[0] if paths else None,
        "permalink": f"/c/{chunk_id}",
    }


def humanize_passages(passages: list[tuple[int, int]]) -> str | None:
    if not passages:
        return None
    s, e = passages[0]
    try:
        return human(s, e)
    except Exception:
        return None


def chunk_preview_from_card(card, lang: str = "en") -> dict:
    """Convert a SourceLead to the API's compact chunk preview shape."""
    paths = derive_tree_paths_from_card(card, lang=lang)
    kind = kind_from_tags(card.tags)
    out = {
        "chunk_id": card.chunk_id,
        "title": card.document_title,
        "kind": kind,
        "passage": card.passage,
        "tags": card.tags,
        "excerpt": card.excerpt,
        "primary_path": paths[0] if paths else None,
        "permalink": f"/c/{card.chunk_id}",
    }
    # Bible chunks: resolve resource:<edition_id> to registry metadata so the
    # correct version is cited per testament. A language's Bible may be a
    # composite (aligned NT + plain-text OT from a different edition/source),
    # so the raw id ("lsg-ot") becomes a proper label ("Louis Segond 1910 (OT)").
    if kind == "bible":
        from server.editions import edition_citation, edition_label
        eid = first_tag(card.tags, "resource:")
        ed = edition_citation(eid) if eid else None
        if ed:
            out["edition"] = ed
            ref = card.document_title.split(" — ", 1)
            if len(ref) > 1:
                out["title"] = f"{edition_label(eid)} — {ref[1]}"
    return out


def derive_tree_paths_from_card(card, *, lang: str = "en") -> list[str]:
    """Convenience: derive tree paths from a SourceLead's tags + decoded passage."""
    # Re-encode the card's human passage back to BBCCCVVV pairs is messy;
    # the card already has tags. Build a synthetic [(start,end)] list from the
    # human passage where possible, otherwise leave empty (paths fall back to
    # source/kind alone).
    passages: list[tuple[int, int]] = []
    if card.passage:
        from indexer.references import parse_references
        passages = parse_references(card.passage)
    return derive_tree_paths(card.tags, passages, lang=lang)


def resolve_chunk(
    db: sqlite3.Connection,
    chunk_id: str,
    *,
    lang: str = "en",
    include_cross_refs: bool = True,
) -> dict | None:
    """Full chunk resolver: body + tree paths + cross-refs."""
    row = db.execute(
        """
        SELECT chunks.id, chunks.doc_id, chunks.body,
               documents.title, documents.source_path, documents.metadata
        FROM chunks
        JOIN documents ON documents.id = chunks.doc_id
        WHERE chunks.id = ?
        """,
        (chunk_id,),
    ).fetchone()
    if not row:
        return None

    cid, doc_id, body, title, source_path, meta_json = row
    try:
        meta = json.loads(meta_json) if meta_json else {}
    except json.JSONDecodeError:
        meta = {}
    tags = fetch_doc_tags(db, doc_id)
    passages = fetch_doc_passages(db, doc_id)
    paths = derive_tree_paths(tags, passages, lang=lang)

    out = {
        "chunk_id": cid,
        "doc_id": doc_id,
        "title": title,
        "body": body,
        "passage": humanize_passages(passages),
        "passage_refs": [list(p) for p in passages],
        "tags": tags,
        "kind": kind_from_tags(tags),
        "source": source_path,
        "metadata": meta,
        "primary_path": paths[0] if paths else None,
        "all_paths": paths,
        "permalink": f"/c/{cid}",
    }
    if include_cross_refs:
        out["cross_refs"] = derive_cross_refs(db, doc_id, tags, passages, lang=lang)
    return out
