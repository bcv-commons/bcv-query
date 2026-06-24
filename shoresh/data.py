"""Read-only access to the original-language word stores (lxx.db + spine.db).

Both carry per-word rows keyed by (book, chapter, verse, idx) with a Strong's
number, so two deterministic, $0 views fall out:

- **verse**: the Greek (LXX) and Hebrew/Greek (spine) words of one verse,
  side by side — a cross-language interlinear the English RAG can't produce.
- **concordance**: every occurrence of a Strong's number. Greek (`G####`)
  spans LXX (OT) + UGNT (NT) for a full-Bible Greek concordance; Hebrew
  (`H####`) spans the spine's OT.

Strong's is stored as a bare int in both DBs; language is disambiguated by
book (OT books = Hebrew, NT books = Greek). Glosses come from the spine's
`strongs_gloss.tsv` (both languages).
"""
from __future__ import annotations

import csv
import os
import sqlite3
from functools import lru_cache
from pathlib import Path

from spine.common import FILENUM
from references import encode, decode

HERE = Path(__file__).resolve().parent
LXX_DB = HERE / "lxx" / "lxx.db"
SPINE_DB = HERE / "spine" / "spine.db"
GLOSS_TSV = HERE / "spine" / "strongs_gloss.tsv"


def _tw_tsv_path() -> Path:
    """Locate strongs_tw.tsv (Strong's → Translation-Words article map).

    Canonical copy is the shared `resources/strongs_tw.tsv` at the repo root
    (built by bcv-RAG/scripts/build_strongs_tw.py). Resolution order:
      1. $STRONGS_TW_TSV (explicit override)
      2. repo-root resources/ — works in a dev checkout (shoresh is a sibling)
      3. shoresh/data/strongs_tw.tsv — the prod copy synced into the image at
         build time (data/ is gitignored, so this is NOT a tracked duplicate)
    """
    env = os.environ.get("STRONGS_TW_TSV")
    if env:
        return Path(env)
    dev = HERE.parent / "resources" / "strongs_tw.tsv"
    if dev.exists():
        return dev
    return HERE / "data" / "strongs_tw.tsv"


TW_TSV = _tw_tsv_path()


def _speaker_tsv_path() -> Path:
    """Locate speaker_quotations.tsv (S1 — who speaks where). Same resolution as
    _tw_tsv_path: $SPEAKER_QUOTATIONS_TSV → repo-root resources/ (dev) →
    shoresh/data/ (prod copy synced into the image; data/ is gitignored)."""
    env = os.environ.get("SPEAKER_QUOTATIONS_TSV")
    if env:
        return Path(env)
    dev = HERE.parent / "resources" / "speaker_quotations" / "speaker_quotations.tsv"
    if dev.exists():
        return dev
    return HERE / "data" / "speaker_quotations.tsv"


SPEAKER_TSV = _speaker_tsv_path()

OT_BOOKS = {c for c, n in FILENUM.items() if n <= 39}
NT_BOOKS = {c for c, n in FILENUM.items() if n >= 40}

# Canonical ordering for concordance results. FILENUM order (66 books) +
# LXX-only deuterocanon appended, so every real book gets a position and
# INSTR(ORDER_STR, ...) sorts canonically (alphabetical book codes would put
# 1SA before GEN).
_LXX_EXTRA = ["1ES", "TOB", "JDT", "PSS", "WIS", "SIR", "LJE", "BAR",
              "SUS", "BEL", "ODA", "1MA", "2MA", "3MA", "4MA"]
ORDER_STR = "," + ",".join(
    [c for c, _ in sorted(FILENUM.items(), key=lambda kv: kv[1])] + _LXX_EXTRA) + ","


def _ro(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


@lru_cache(maxsize=1)
def _glosses() -> dict[str, tuple[str, str]]:
    """{'H7225': (gloss, translit)} from the spine gloss table."""
    out: dict[str, tuple[str, str]] = {}
    if not GLOSS_TSV.exists():
        return out
    with GLOSS_TSV.open(encoding="utf-8") as fh:
        next(fh, None)  # header
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2:
                out[parts[0]] = (parts[1], parts[2] if len(parts) > 2 else "")
    return out


def gloss_of(code: str) -> dict | None:
    g = _glosses().get(code)
    return {"gloss": g[0], "translit": g[1]} if g else None


@lru_cache(maxsize=1)
def _tw_articles() -> dict[str, list[dict]]:
    """{'G0026': [{tw_article, category, is_kt, lemma, n}, ...]} ranked by n.

    From the shared strongs_tw.tsv. Empty if the file isn't present (the
    endpoint then simply returns no matches).
    """
    out: dict[str, list[dict]] = {}
    if not TW_TSV.exists():
        return out
    with TW_TSV.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            strong = (row.get("strong") or "").strip()
            if not strong:
                continue
            out.setdefault(strong, []).append({
                "tw_article": row.get("tw_article", ""),
                "category": row.get("category", ""),
                "is_kt": row.get("is_kt", "") == "1",
                "lemma": row.get("lemma", ""),
                "n": int(row.get("n") or 0),
            })
    # rows are already strong-then-n-desc, but sort defensively
    for v in out.values():
        v.sort(key=lambda a: -a["n"])
    return out


def tw_articles(strong: str) -> dict:
    """Translation-Words article(s) explaining a Strong's number, ranked."""
    articles = _tw_articles().get(strong.strip(), [])
    return {"strong": strong, "count": len(articles), "articles": articles}


# ---------- S1: speaker / red-letter index ----------

@lru_cache(maxsize=1)
def _speakers() -> list[dict]:
    """All quotation ranges: [{speaker, alt_speaker, start, end, quote_type,
    delivery, divine}, ...] sorted by start. Empty if the file is absent."""
    out: list[dict] = []
    if not SPEAKER_TSV.exists():
        return out
    with SPEAKER_TSV.open(encoding="utf-8") as fh:
        cols = None
        for line in fh:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if cols is None:  # header
                cols = {c: i for i, c in enumerate(parts)}
                continue
            try:
                out.append({
                    "speaker": parts[cols["speaker"]],
                    "alt_speaker": parts[cols["alt_speaker"]],
                    "start": int(parts[cols["start_bbcccvvv"]]),
                    "end": int(parts[cols["end_bbcccvvv"]]),
                    "quote_type": parts[cols["quote_type"]],
                    "delivery": parts[cols["delivery"]],
                    "divine": parts[cols["divine"]] == "Y",
                })
            except (KeyError, ValueError, IndexError):
                continue
    return out


@lru_cache(maxsize=1)
def _speaker_index() -> dict[str, list[dict]]:
    """{speaker_lower: [range, ...]}."""
    idx: dict[str, list[dict]] = {}
    for r in _speakers():
        idx.setdefault(r["speaker"].lower(), []).append(r)
    return idx


def speaker_ranges(name: str, *, limit: int = 1000) -> dict:
    """Every verse range a speaker speaks — for "what did Jesus say"."""
    ranges = _speaker_index().get(name.strip().lower(), [])
    return {
        "speaker": name,
        "count": len(ranges),
        "divine": bool(ranges) and ranges[0]["divine"],
        "ranges": [
            {"start": decode(r["start"]), "end": decode(r["end"]),
             "start_bbcccvvv": r["start"], "end_bbcccvvv": r["end"],
             "quote_type": r["quote_type"]}
            for r in ranges[:limit]
        ],
    }


def speakers_at(book: str, chapter: int, vrs: int) -> dict:
    """Who speaks at a verse — the speaker(s) whose quotation range covers it.
    Powers red-letter annotation of `/verse`."""
    try:
        ref = encode(book, chapter, vrs)
    except (ValueError, KeyError):
        return {"book": book, "chapter": chapter, "verse": vrs, "speakers": []}
    hits = [{"speaker": r["speaker"], "divine": r["divine"],
             "start_bbcccvvv": r["start"], "end_bbcccvvv": r["end"]}
            for r in _speakers() if r["start"] <= ref <= r["end"]]
    return {"book": book.upper(), "chapter": chapter, "verse": vrs, "speakers": hits}


def speakers_list() -> dict:
    """All speakers with quotation-range counts (discovery)."""
    counts: dict[str, dict] = {}
    for r in _speakers():
        c = counts.setdefault(r["speaker"], {"speaker": r["speaker"],
                                             "divine": r["divine"], "count": 0})
        c["count"] += 1
    ordered = sorted(counts.values(), key=lambda c: -c["count"])
    return {"count": len(ordered), "speakers": ordered}


def databases_status() -> dict:
    return {"lxx": LXX_DB.exists(), "spine": SPINE_DB.exists(),
            "glosses": GLOSS_TSV.exists(), "tw_articles": TW_TSV.exists(),
            "speaker_quotations": SPEAKER_TSV.exists()}


def _strong_code(word_lang: str, strong: int | None) -> str | None:
    if strong is None:
        return None
    return f"{'H' if word_lang == 'hbo' else 'G'}{strong}"


def verse(book: str, chapter: int, vrs: int) -> dict:
    """Greek (LXX) + Hebrew/Greek (spine) words for one verse."""
    book = book.upper()
    spine_lang = "hbo" if book in OT_BOOKS else "grc"
    result: dict = {"book": book, "chapter": chapter, "verse": vrs,
                    "lxx": None, "spine": None}

    lcon = _ro(LXX_DB)
    if lcon:
        rows = lcon.execute(
            "SELECT idx, surface, plain, strong, morph, pos FROM lxx_words "
            "WHERE book=? AND chapter=? AND verse=? ORDER BY idx",
            (book, chapter, vrs)).fetchall()
        lcon.close()
        if rows:
            result["lxx"] = {"language": "grc", "words": [
                {"idx": r["idx"], "surface": r["surface"], "plain": r["plain"],
                 "strong": _strong_code("grc", r["strong"]), "morph": r["morph"],
                 **(gloss_of(_strong_code("grc", r["strong"])) or {})}
                for r in rows]}

    scon = _ro(SPINE_DB)
    if scon:
        rows = scon.execute(
            "SELECT idx, surface, strong, lemma, morph FROM spine_words "
            "WHERE book=? AND chapter=? AND verse=? ORDER BY idx",
            (book, chapter, vrs)).fetchall()
        scon.close()
        if rows:
            result["spine"] = {"language": spine_lang, "words": [
                {"idx": r["idx"], "surface": r["surface"], "lemma": r["lemma"],
                 "strong": _strong_code(spine_lang, r["strong"]), "morph": r["morph"],
                 **(gloss_of(_strong_code(spine_lang, r["strong"])) or {})}
                for r in rows]}
    return result


@lru_cache(maxsize=1)
def _reverse_glosses() -> dict[str, list[dict]]:
    """Inverted index: English gloss → [{strong, translit, lang, count}, ...]."""
    from collections import defaultdict
    inv: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for code, (gloss, translit) in _glosses().items():
        for word in gloss.lower().split():
            inv[word].append((code, translit))
    scon = _ro(SPINE_DB)
    lcon = _ro(LXX_DB)
    counts: dict[str, int] = {}
    if scon:
        # spine_words.strong is a bare int and the table holds BOTH testaments,
        # so the same int means a different word in Hebrew (OT books → H) vs
        # Greek (NT books → G). Split by testament — same as concordance() —
        # otherwise NT Greek counts get mislabeled H and conflated with Hebrew.
        ot_ph = ",".join("?" * len(OT_BOOKS))
        nt_ph = ",".join("?" * len(NT_BOOKS))
        for r in scon.execute(
            f"SELECT strong, COUNT(*) c FROM spine_words "
            f"WHERE strong IS NOT NULL AND book IN ({ot_ph}) GROUP BY strong",
            tuple(sorted(OT_BOOKS))):
            counts[f"H{r['strong']}"] = counts.get(f"H{r['strong']}", 0) + r["c"]
        for r in scon.execute(
            f"SELECT strong, COUNT(*) c FROM spine_words "
            f"WHERE strong IS NOT NULL AND book IN ({nt_ph}) GROUP BY strong",
            tuple(sorted(NT_BOOKS))):
            counts[f"G{r['strong']}"] = counts.get(f"G{r['strong']}", 0) + r["c"]
        scon.close()
    if lcon:
        # LXX is Greek (OT) — merge into the G space.
        for r in lcon.execute(
            "SELECT strong, COUNT(*) c FROM lxx_words "
            "WHERE strong IS NOT NULL GROUP BY strong"):
            counts[f"G{r['strong']}"] = counts.get(f"G{r['strong']}", 0) + r["c"]
        lcon.close()
    result: dict[str, list[dict]] = {}
    for word, entries in inv.items():
        seen = set()
        items = []
        for code, translit in entries:
            if code in seen:
                continue
            seen.add(code)
            g = _glosses().get(code)
            lang = "hbo" if code.startswith("H") else "grc"
            items.append({"strong": code, "gloss": g[0] if g else "",
                          "translit": translit, "lang": lang,
                          "count": counts.get(code, 0)})
        items.sort(key=lambda x: -x["count"])
        result[word] = items
    return result


def gloss_lookup(word: str) -> dict:
    """Find all Hebrew/Greek lemmas behind an English gloss word."""
    word = word.strip().lower()
    idx = _reverse_glosses()
    entries = idx.get(word, [])
    return {"gloss": word, "matches": entries, "total": len(entries)}


def concordance(strong: str, limit: int = 200) -> dict:
    """Every occurrence of a Strong's number across the original-language stores."""
    strong = strong.strip().upper()
    lang = "hbo" if strong.startswith("H") else "grc" if strong.startswith("G") else None
    if lang is None or not strong[1:].isdigit():
        return {"error": "strong must look like 'H7225' or 'G2316'"}
    num = int(strong[1:])
    occ: list[dict] = []

    if lang == "grc":
        lcon = _ro(LXX_DB)
        if lcon:
            for r in lcon.execute(
                "SELECT book, chapter, verse, surface, morph FROM lxx_words "
                "WHERE strong=? ORDER BY INSTR(?, ','||book||','), chapter, verse LIMIT ?",
                (num, ORDER_STR, limit)).fetchall():
                occ.append({"corpus": "LXX", "ref": f"{r['book']} {r['chapter']}:{r['verse']}",
                            "surface": r["surface"], "morph": r["morph"]})
            lcon.close()

    scon = _ro(SPINE_DB)
    if scon:
        books = NT_BOOKS if lang == "grc" else OT_BOOKS
        qmarks = ",".join("?" * len(books))
        for r in scon.execute(
            f"SELECT book, chapter, verse, surface, morph FROM spine_words "
            f"WHERE strong=? AND book IN ({qmarks}) "
            f"ORDER BY INSTR(?, ','||book||','), chapter, verse LIMIT ?",
            (num, *sorted(books), ORDER_STR, limit)).fetchall():
            occ.append({"corpus": "spine", "ref": f"{r['book']} {r['chapter']}:{r['verse']}",
                        "surface": r["surface"], "morph": r["morph"]})
        scon.close()

    return {"strong": strong, "language": lang, **(gloss_of(strong) or {}),
            "count": len(occ), "truncated": len(occ) >= limit, "occurrences": occ}


# -- Bridge 3: morphological pattern search --

MORPH_PATTERNS = {
    "imperative": "%v%",
    "participle": "%r%",
    "perfect": "He,Vqp%",
    "imperfect": "He,Vqi%",
    "infinitive": "%a%",
    "noun": "%,N%",
    "adjective": "%,A%",
    "verb": "%,V%",
}


def morph_search(pattern: str, book: str | None = None,
                 chapter: int | None = None, limit: int = 100) -> dict:
    """Search spine for words matching a morphology pattern."""
    morph_like = MORPH_PATTERNS.get(pattern.lower(), f"%{pattern}%")
    scon = _ro(SPINE_DB)
    if not scon:
        return {"error": "spine.db not available"}
    sql = ("SELECT book, chapter, verse, idx, surface, strong, lemma, morph "
           "FROM spine_words WHERE morph LIKE ?")
    params: list = [morph_like]
    if book:
        sql += " AND book = ?"
        params.append(book.upper())
    if chapter is not None:
        sql += " AND chapter = ?"
        params.append(chapter)
    sql += " ORDER BY INSTR(?, ','||book||','), chapter, verse, idx LIMIT ?"
    params.extend([ORDER_STR, limit])
    rows = scon.execute(sql, params).fetchall()
    scon.close()
    results = []
    for r in rows:
        code = _strong_code("hbo", r["strong"])
        results.append({
            "ref": f"{r['book']} {r['chapter']}:{r['verse']}",
            "surface": r["surface"], "lemma": r["lemma"],
            "strong": code, "morph": r["morph"],
            **(gloss_of(code) or {}),
        })
    return {"pattern": pattern, "morph_like": morph_like,
            "book": book, "chapter": chapter,
            "count": len(results), "results": results}


# -- Bridge 5: LXX Hebrew↔Greek bridge --

def lxx_bridge(strong: str, limit: int = 50) -> dict:
    """Given a Hebrew Strong's number, find how the LXX translates it.

    For each OT verse containing the Hebrew word, finds the positionally
    closest Greek content word in the LXX — the one most likely to be the
    actual translation. Then ranks Greek Strong's numbers by frequency.
    """
    strong = strong.strip().upper()
    if not strong.startswith("H") or not strong[1:].isdigit():
        return {"error": "provide a Hebrew Strong's number (e.g. H2617)"}
    hnum = int(strong[1:])
    scon = _ro(SPINE_DB)
    lcon = _ro(LXX_DB)
    if not scon or not lcon:
        return {"error": "both spine.db and lxx.db required"}

    nt_qmarks = ",".join("?" * len(NT_BOOKS))
    hwords = scon.execute(
        f"SELECT book, chapter, verse, idx FROM spine_words "
        f"WHERE strong = ? AND book NOT IN ({nt_qmarks})",
        (hnum, *sorted(NT_BOOKS))).fetchall()
    scon.close()

    from collections import Counter
    greek_counts: Counter = Counter()
    sample_verses: dict[int, list[str]] = {}
    seen_verses: set[tuple] = set()
    total_hebrew = len(hwords)

    for hw in hwords:
        vkey = (hw["book"], hw["chapter"], hw["verse"])
        if vkey in seen_verses:
            continue
        seen_verses.add(vkey)

        hcount = sum(1 for h in hwords
                     if (h["book"], h["chapter"], h["verse"]) == vkey)
        grows = lcon.execute(
            "SELECT idx, strong FROM lxx_words "
            "WHERE book=? AND chapter=? AND verse=? "
            "AND strong IS NOT NULL AND is_content=1 "
            "ORDER BY idx",
            vkey).fetchall()
        if not grows:
            continue
        hidxs = sorted(h["idx"] for h in hwords
                       if (h["book"], h["chapter"], h["verse"]) == vkey)
        gidxs = [(g["idx"], g["strong"]) for g in grows]
        total_g = len(gidxs)
        for hi, hidx in enumerate(hidxs):
            frac = hidx / max(1, hcount + total_g)
            target_gidx = int(frac * total_g)
            target_gidx = min(target_gidx, total_g - 1)
            best_g = gidxs[target_gidx][1]
            greek_counts[best_g] += 1
            ref = f"{vkey[0]} {vkey[1]}:{vkey[2]}"
            if best_g not in sample_verses:
                sample_verses[best_g] = []
            if len(sample_verses[best_g]) < 3 and ref not in sample_verses[best_g]:
                sample_verses[best_g].append(ref)
    lcon.close()

    translations = []
    for gnum, count in greek_counts.most_common(limit):
        gcode = f"G{gnum}"
        translations.append({
            "greek_strong": gcode, "count": count,
            **(gloss_of(gcode) or {}),
            "sample_refs": sample_verses.get(gnum, []),
        })
    return {
        "hebrew_strong": strong,
        **(gloss_of(strong) or {}),
        "hebrew_verses": len(seen_verses),
        "greek_translations": translations,
    }
