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
`spine_glosses.tsv` — spine-scoped English glosses of both original languages
(distinct from bcv-RAG's multilingual `resources/strongs_gloss.tsv`).
"""
from __future__ import annotations

import collections
import csv
import os
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

from spine.common import FILENUM
from references import encode, decode

HERE = Path(__file__).resolve().parent
LXX_DB = HERE / "lxx" / "lxx.db"
SPINE_DB = HERE / "spine" / "spine.db"
GLOSS_TSV = HERE / "spine" / "spine_glosses.tsv"


def _resources_dir() -> Path:
    """The shared `resources/` root — single source of truth, same convention as
    bcv-RAG. `$BCV_RESOURCES_DIR` (set in the image to /app/resources, where the
    repo-root resources/ is baked) wins; otherwise the repo-root resources/ of a
    dev checkout (shoresh is a sibling of resources/)."""
    env = os.environ.get("BCV_RESOURCES_DIR")
    return Path(env) if env else HERE.parent / "resources"


# Non-answerable placeholders that some lexicons use for function words instead of a
# translatable gloss: empty, a dash, or an ALL-CAPS label/transliteration (Greek "ART";
# Hebrew "ZH"/"MH"/"KJ" transliterations, "UKENDT"=unknown). A learner can't type these,
# so they are treated as "no gloss" — the lexeme drops out of the /words pool.
_GLOSS_PLACEHOLDER = re.compile(r"^[A-ZÆØÅ]{2,}$")


def _real_gloss(v: str | None) -> str:
    """The gloss if it's answerable, else '' (empty / '-' / an all-caps placeholder)."""
    v = (v or "").strip()
    return "" if (not v or v == "-" or _GLOSS_PLACEHOLDER.match(v)) else v


def _gloss_dir(src: str) -> Path:
    """resources/word_glosses/<src>/ — per source-language (hbo / grc). Each <Lang>.csv
    is keyed by `lex` (the value /words returns) with columns: lex, default, then one
    column per verbal stem (qal, nif, piel, …)."""
    return _resources_dir() / "word_glosses" / src


def gloss_languages(src: str) -> list[str]:
    """Available gloss languages for a source language — English (always, inline from
    the corpus) plus every <Lang>.csv present. Drives the client's language dropdown."""
    base = _gloss_dir(src)
    # English is always offered as the inline corpus gloss; an English.csv (per-stem,
    # used by study features) must not double-list it in the dropdown.
    extra = sorted(p.stem for p in base.glob("*.csv") if p.stem != "English") if base.exists() else []
    return ["English"] + extra


@lru_cache(maxsize=16)
def _gloss_table(src: str, lang: str) -> tuple:
    """({lex: {col: gloss}}, stem_cols, gloss_cols) from resources/word_glosses/<src>/
    <lang>.csv. gloss_cols = every column except `lex` (default first); stem_cols = those
    minus `default`. Empty if the file is absent."""
    path = _gloss_dir(src) / f"{lang}.csv"
    if not path.exists():
        return {}, (), ()
    rows: dict[str, dict] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header:
            return {}, (), ()
        cols = [c.strip() for c in header]
        lex_i = cols.index("lex") if "lex" in cols else 0
        # gloss columns = every NAMED column except `lex` (skip an unnamed leading
        # index column, as in pandas-exported CSVs). default first, then the stems.
        gloss_cols = tuple(c for i, c in enumerate(cols) if c and i != lex_i)
        stem_cols = tuple(c for c in gloss_cols if c != "default")
        for row in reader:
            if len(row) <= lex_i or not row[lex_i].strip():
                continue
            rows[row[lex_i].strip()] = {
                cols[i]: (row[i].strip() if i < len(row) else "") for i in range(len(cols))
            }
    return rows, stem_cols, gloss_cols


def gloss_lexemes(src: str, lang: str) -> set:
    """The `lex` keys that actually HAVE a (non-empty) gloss in this language — used to
    filter /words. Files commonly list every lexeme with mostly-empty rows, so a row
    must carry at least one non-empty gloss column to count."""
    table, _stem_cols, gloss_cols = _gloss_table(src, lang)
    return {lex for lex, row in table.items()
            if any(_real_gloss(row.get(c)) for c in gloss_cols)}


def resolve_word_gloss(src: str, lang: str, lex: str, stem: str | None) -> str | None:
    """The gloss for a word in `lang`, replicating the client rule exactly:
    verb (stem != NA) → the word's stem column, else the first non-empty stem column;
    non-verb → the `default` column, else the first non-empty column. Returns the FULL
    gloss string unmodified (caller may split on '; ' / ', '), or None if no entry."""
    table, stem_cols, gloss_cols = _gloss_table(src, lang)
    row = table.get(lex)
    if not row:
        return None

    def _first(cols):
        for c in cols:
            g = _real_gloss(row.get(c))
            if g:
                return g
        return None

    # Stem-aware only when the file actually has stem columns (Hebrew verbs). Greek
    # files are single-gloss (lex, default) → everything falls through to `default`.
    # Placeholder values ('-', labels) are skipped, so a real gloss in another column wins.
    if stem_cols and stem and stem != "NA":   # verb
        return _real_gloss(row.get(stem)) or _first(stem_cols)
    return _real_gloss(row.get("default")) or _first(gloss_cols)


def _tw_tsv_path() -> Path:
    """strongs_tw.tsv (Strong's → Translation-Words article map). `$STRONGS_TW_TSV`
    overrides; else from the shared resources/ root (see `_resources_dir`)."""
    env = os.environ.get("STRONGS_TW_TSV")
    return Path(env) if env else _resources_dir() / "strongs_tw.tsv"


TW_TSV = _tw_tsv_path()


def _speaker_tsv_path() -> Path:
    """speaker_quotations.tsv (S1 — who speaks where). `$SPEAKER_QUOTATIONS_TSV`
    overrides; else from the shared resources/ root."""
    env = os.environ.get("SPEAKER_QUOTATIONS_TSV")
    return Path(env) if env else _resources_dir() / "speaker_quotations" / "speaker_quotations.tsv"


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


def _spine_code(code: str) -> str:
    """Spine glosses key on UNPADDED codes (G26, H157); resources use padded
    (G0026, H0157). Normalize to the spine form for lookups."""
    if not code:                          # some spine words carry no strong (→ no gloss); don't crash
        return code
    m = re.match(r"^([GgHh])0*(\d+)", code.strip())
    return f"{m.group(1).upper()}{int(m.group(2))}" if m else code


def gloss_of(code: str) -> dict | None:
    g = _glosses().get(code) or _glosses().get(_spine_code(code))
    return {"gloss": g[0], "translit": g[1]} if g else None


# ---------- semantic domains (S2 / word-study) ----------

@lru_cache(maxsize=1)
def _domain_index() -> dict:
    """{(domain_type, domain_code): [(strong, label, count, share)]} from the shared
    resources/semantic_domains/{grc,hbo}.tsv (SDBG Greek + SDBH Hebrew + bridged sdbg)."""
    idx: dict = collections.defaultdict(list)
    base = _resources_dir() / "semantic_domains"
    for lang in ("grc", "hbo"):
        p = base / f"{lang}.tsv"
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 6:
                    s, dtype, code, label, count, share = parts[:6]
                    idx[(dtype, code)].append((s, label, int(count), float(share)))
    return idx


def domain_lexemes(code: str, axis: str = "sdbg", limit: int = 200) -> dict:
    """Every lexeme in a semantic domain, glossed — "every word in Love/Affection".
    axis: sdbg (Louw-Nida, Greek + LXX-bridged Hebrew) | core | lex | ctx (native SDBH)."""
    members = _domain_index().get((axis, code.strip()), [])
    lexemes = []
    for s, _label, count, share in sorted(members, key=lambda m: (-m[2], -m[3]))[:limit]:
        g = gloss_of(s) or {}
        lexemes.append({
            "strong": s, "lang": "grc" if s.startswith("G") else "hbo",
            "gloss": g.get("gloss"), "translit": g.get("translit"),
            "count": count, "share": round(share, 3),
        })
    return {
        "domain": code, "axis": axis,
        "label": members[0][1] if members else None,
        "count": len(members), "lexemes": lexemes,
    }


@lru_cache(maxsize=1)
def _strong_domains() -> dict:
    """strong -> [(axis, code, label, share)] (inverse of _domain_index)."""
    out: dict = collections.defaultdict(list)
    for (axis, code), members in _domain_index().items():
        for s, label, _count, share in members:
            out[s].append((axis, code, label, share))
    return out


@lru_cache(maxsize=1)
def _strong_senses() -> dict:
    out: dict = collections.defaultdict(list)
    base = _resources_dir() / "senses"
    for lang in ("grc", "hbo"):
        p = base / f"{lang}.tsv"
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                c = line.rstrip("\n").split("\t")
                if len(c) >= 5:
                    out[c[0]].append({"sense": c[1], "gloss": c[2],
                                      "count": int(c[3]), "share": float(c[4])})
    return out


@lru_cache(maxsize=1)
def _lxx_pairs() -> tuple:
    """(forward H->[(G,count)], reverse G->[(H,count)]) from lxx_bridge.tsv."""
    fwd: dict = collections.defaultdict(list)
    rev: dict = collections.defaultdict(list)
    p = _resources_dir() / "lxx_bridge.tsv"
    if p.exists():
        with p.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                c = line.rstrip("\n").split("\t")
                if len(c) >= 3:
                    fwd[c[0]].append((c[1], int(c[2])))
                    rev[c[1]].append((c[0], int(c[2])))
    return fwd, rev


@lru_cache(maxsize=1)
def _keyness() -> dict:
    """{strong: (keyness, anchor, modern_he, koine_general)} from strongs_keyness.tsv —
    how distinctively biblical a word is (zipf_bible − zipf_general; high = covenant/cultic
    vocab, ~0 = common everywhere). anchor 'he' = modern-Hebrew denominator; 'grc' =
    pagan-Koine denominator (LAGT). modern_he / koine_general = the lemma's raw frequency
    in that general corpus (zipf; 0 = absent from it); exactly one is set per row."""
    out: dict = {}
    p = _resources_dir() / "strongs_keyness.tsv"
    if p.exists():
        with p.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                c = line.rstrip("\n").split("\t")
                if len(c) >= 3:
                    mh = float(c[3]) if len(c) >= 4 and c[3] != "" else None
                    kg = float(c[4]) if len(c) >= 5 and c[4] != "" else None
                    out[c[0]] = (float(c[1]), c[2], mh, kg)
    return out


def keyness_of(code: str) -> dict | None:
    """Biblical-salience for a Strong's, or None. For Hebrew (anchor 'he') carries
    `modern_he` + `archaic` (absent from modern Hebrew). For Greek (anchor 'grc')
    carries `koine_general` + `scripture_only` (absent from secular/pagan Koine). Both
    presence flags are robust even for rare words where `score` is noisy."""
    k = _keyness().get(_norm_strong(code))
    if not k:
        return None
    score, anchor, mh, kg = k
    out = {"score": round(score, 2), "anchor": anchor, "proxy": anchor == "en"}
    if mh is not None:
        out["modern_he"] = mh
        out["archaic"] = mh == 0.0
    if kg is not None:
        out["koine_general"] = kg
        out["scripture_only"] = kg == 0.0
    return out


def _norm_strong(s: str) -> str:
    m = re.match(r"^([GgHh])0*(\d+)", s.strip())
    return f"{m.group(1).upper()}{int(m.group(2)):04d}" if m else s.strip().upper()


@lru_cache(maxsize=1)
def _strong_to_lex() -> dict[str, list[str]]:
    """{padded Strong's: [BHSA lex, ...]} — reverse of word_freq/hbo_strong.tsv. Lets a
    Strong's-keyed card recover the distinct lexemes (homographs) a single Strong's conflates
    — 733 Hebrew Strong's codes cover 2+ lexemes — and thus their per-stem (binyan) senses."""
    path = _resources_dir() / "word_freq" / "hbo_strong.tsv"
    out: dict[str, list[str]] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[0]:
                out.setdefault(_norm_strong(parts[1]), []).append(parts[0])
    return out


def _stem_senses(code: str) -> list[dict]:
    """Per-lexeme, per-stem (binyan) English senses behind a Hebrew Strong's — the lex-anchored
    granularity Strong's can't express. Each entry: {lex, senses: {qal: …, nif: …}}; only verb
    lexemes (≥1 stem gloss) are included. Empty for Greek / non-verbs."""
    if not code.startswith("H"):
        return []
    table, stem_cols, _gc = _gloss_table("hbo", "English")
    out = []
    for lex in _strong_to_lex().get(code, []):
        row = table.get(lex)
        if not row:
            continue
        senses = {c: _real_gloss(row.get(c)) for c in stem_cols if _real_gloss(row.get(c))}
        if senses:
            out.append({"lex": lex, "senses": senses})
    return out


@lru_cache(maxsize=1)
def _lex_sense_table() -> dict:
    """{lex: {stem: [{sense, gloss, share}]}} — the Hebrew-context-derived sense inventory
    (resources/senses/hbo_lex.tsv). Sense identity decided in Hebrew usage; gloss is the
    label. stem '' = non-verb."""
    out: dict = collections.defaultdict(dict)
    p = _resources_dir() / "senses" / "hbo_lex.tsv"
    if p.exists():
        with p.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                c = line.rstrip("\n").split("\t")
                if len(c) == 6:
                    out[c[0]].setdefault(c[1], []).append(
                        {"sense": c[2], "gloss": c[3], "share": round(float(c[5]), 3)})
    return out


def _lex_senses(code: str, lang: str = "English") -> list[dict]:
    """Per-lexeme, per-stem Hebrew-context senses behind a Hebrew Strong's (homographs split,
    binyan-aware). Each: {lex, stems: {qal: [{sense,gloss,share}], …}}. The DOMINANT sense's
    label is the curated per-stem gloss in `lang` (multilingual — sense identity is Hebrew,
    label is pluggable); sub-senses keep the English (cleaned-MACULA) label. Empty for Greek."""
    if not code.startswith("H"):
        return []
    table = _lex_sense_table()
    out = []
    for lex in _strong_to_lex().get(code, []):
        if lex not in table:
            continue
        stems = {}
        for stem, senses in table[lex].items():
            ss = [dict(s) for s in senses]
            if lang != "English" and ss:                       # relabel the dominant sense
                g = resolve_word_gloss("hbo", lang, lex, stem or None)
                if g:
                    ss[0] = {**ss[0], "gloss": g}
            stems[stem] = ss
        out.append({"lex": lex, "stems": stems})
    return out


def word_study(strong: str, gloss_lang: str = "English") -> dict:
    """Composite word-study: gloss + keyness (how distinctively biblical) +
    semantic domain(s) + co-domain siblings + senses (polysemy) + cross-language
    equivalent — from the shared resources. `gloss_lang` localizes the lex_senses labels."""
    code = _norm_strong(strong)
    domains = [{"axis": a, "domain": d, "label": lab, "share": round(sh, 3)}
               for a, d, lab, sh in sorted(_strong_domains().get(code, []), key=lambda x: -x[3])]
    siblings = []
    prim = next((d for d in domains if d["axis"] == "sdbg"), None)
    if prim:
        siblings = [lx for lx in domain_lexemes(prim["domain"], axis="sdbg", limit=8)["lexemes"]
                    if lx["strong"] != code][:6]
    fwd, rev = _lxx_pairs()
    cross = ([{"strong": g, "count": c, **(gloss_of(g) or {})} for g, c in fwd.get(code, [])][:3]
             or [{"strong": h, "count": c, **(gloss_of(h) or {})} for h, c in rev.get(code, [])][:3])
    head = gloss_of(code) or {}                        # headline gloss — localize it too (Hebrew)
    if code.startswith("H") and gloss_lang and gloss_lang != "English":
        for lex in _strong_to_lex().get(code, []):
            loc = resolve_word_gloss("hbo", gloss_lang, lex, None)
            if loc:
                head = {**head, "gloss": re.split(r"[;,]", loc)[0].strip()}
                break
    return {
        "strong": code, **head,
        "keyness": keyness_of(code),                   # how distinctively biblical
        "tw": tw_articles(code).get("articles", []),  # nudge 1: study the concept
        "domains": domains, "siblings": siblings,      # nudge 3: related words
        "senses": _strong_senses().get(code, []), "cross_language": cross,
        "stems": _stem_senses(code),                   # lex-anchored: per-binyan glosses + homographs
        "lex_senses": _lex_senses(code, gloss_lang),   # Hebrew-context-derived senses (per lex, per stem)
        # per-stem/sense occurrence distribution + sample refs (hbo.db); [] for Greek / db absent
        "sense_distribution": (sense_concordance(code).get("senses", []) if code.startswith("H") else []),
    }


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


def verse(book: str, chapter: int, vrs: int, gloss_lang: str = "English") -> dict:
    """Greek (LXX) + Hebrew/Greek (spine) words for one verse. `gloss_lang` localizes the per-word
    binyan-correct sense."""
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
            senses = _verse_sense_map(book, chapter, vrs, gloss_lang) if spine_lang == "hbo" else {}
            doms = _strong_domains() if spine_lang == "grc" else {}   # NT: Louw-Nida domain per word
            words = []
            for r in rows:
                code = _strong_code(spine_lang, r["strong"])
                w = {"idx": r["idx"], "surface": r["surface"], "lemma": r["lemma"],
                     "strong": code, "morph": r["morph"], **(gloss_of(code) or {})}
                if senses.get(code):                       # binyan-correct sense (OT, hbo.db)
                    w["sense"] = senses[code]
                dd = doms.get(_pad_strong(code)) if code else None
                if dd:                                     # dominant Louw-Nida domain (Greek, per-strong)
                    w["domain"] = max(dd, key=lambda d: d[3])[2]
                words.append(w)
            result["spine"] = {"language": spine_lang, "words": words}
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

    if lang == "hbo":                                  # attach the binyan-correct sense per occurrence
        by_ref = _strong_sense_by_ref(strong)
        for o in occ:
            label = by_ref.get(o["ref"])
            if label:
                o["sense"] = label

    return {"strong": strong, "language": lang, **(gloss_of(strong) or {}),
            "count": len(occ), "truncated": len(occ) >= limit, "occurrences": occ}


# ---------- OT linguistic core (hbo.db): sense-concordance + lexeme profile ----------
# hbo.db = per-occurrence BHSA (ref, lex, stem, strong, sense). Hebrew/OT only; shipped as a host
# data volume (HBO_DB_PATH), NOT baked. See internal-docs/roadmap.md (Phase 1).

def _hbo_path() -> Path:
    env = os.environ.get("HBO_DB_PATH")
    return Path(env) if env else _resources_dir() / "occurrences" / "hbo.db"


def _pad_strong(s: str) -> str:
    """hbo.db keys Strong's zero-padded to 4 digits (H0430); normalize any input to match."""
    s = s.strip().upper()
    return f"{s[0]}{int(s[1:]):04d}" if len(s) > 1 and s[1:].isdigit() else s


def _sense_groups(rows) -> list[dict]:
    """Group occurrence rows (lex/stem/sense + book/chapter/verse) by (lex, stem, sense) → each a
    binyan-correct sense with its label, count, and sample refs. Count-sorted."""
    labels = _lex_sense_table()                       # {lex: {stem: [{sense, gloss, share}]}}
    groups: dict = collections.OrderedDict()
    for r in rows:
        stem, sense = r["stem"] or "", r["sense"] or ""
        key = (r["lex"], stem, sense)
        g = groups.get(key)
        if g is None:
            label = next((s["gloss"] for s in labels.get(r["lex"], {}).get(stem, [])
                          if s["sense"] == sense), None)
            g = groups[key] = {"lex": r["lex"], "stem": stem, "sense": sense,
                               "label": label, "count": 0, "refs": []}
        g["count"] += 1
        if len(g["refs"]) < 6:
            g["refs"].append(f"{r['book']} {r['chapter']}:{r['verse']}")
    return sorted(groups.values(), key=lambda x: -x["count"])


def sense_concordance(strong: str, limit: int = 5000) -> dict:
    """Occurrences of a Hebrew Strong's GROUPED by binyan/sense (hbo.db) — e.g. H6942 → piel
    'consecrate' (63×) · niphal 'be shown holy' (9×) · qal 'be holy' (7×). Hebrew/OT only."""
    strong = strong.strip().upper()
    if not (strong.startswith("H") and strong[1:].isdigit()):
        return {"error": "sense-concordance is Hebrew-only (H####)"}
    con = _ro(_hbo_path())
    if con is None:
        return {"error": "hbo.db unavailable (OT linguistic core not shipped)"}
    rows = con.execute(
        "SELECT book, chapter, verse, lex, stem, sense FROM occurrence WHERE strong=? "
        "ORDER BY node LIMIT ?", (_pad_strong(strong), limit)).fetchall()
    con.close()
    return {"strong": strong, "language": "hbo", **(gloss_of(strong) or {}),
            "senses": _sense_groups(rows)}


def lexeme_profile(lex: str) -> dict:
    """A BHSA-lexeme profile (the granular anchor a shared Strong's conflates): every stem × sense ×
    count × sample refs, from hbo.db."""
    con = _ro(_hbo_path())
    if con is None:
        return {"error": "hbo.db unavailable (OT linguistic core not shipped)"}
    rows = con.execute(
        "SELECT book, chapter, verse, lex, stem, sense, strong FROM occurrence WHERE lex=? "
        "ORDER BY node", (lex,)).fetchall()
    con.close()
    if not rows:
        return {"error": f"no occurrences for lex {lex!r}"}
    return {"lex": lex, "strong": sorted({r["strong"] for r in rows if r["strong"]}),
            "total": len(rows), "senses": _sense_groups(rows)}


def _verse_sense_map(book: str, chapter: int, vrs: int, gloss_lang: str = "English") -> dict:
    """{strong: binyan-correct sense label} for a verse's Hebrew words (hbo.db ⋈ sense inventory).
    `gloss_lang` localizes the label via the per-stem multilingual gloss (falls back to the English
    sense). First occurrence of a strong wins. Empty when hbo.db is unavailable / the verse is non-OT."""
    con = _ro(_hbo_path())
    if con is None:
        return {}
    english = _lex_sense_table()
    localize = bool(gloss_lang) and gloss_lang != "English"
    rows = con.execute(
        "SELECT strong, lex, stem, sense FROM occurrence WHERE book=? AND chapter=? AND verse=?",
        (book, chapter, vrs)).fetchall()
    con.close()
    out: dict = {}
    for r in rows:
        code = _spine_code(r["strong"]) if r["strong"] else None   # unpad (H0430→H430) → spine word code
        if not code or code in out:
            continue
        label = resolve_word_gloss("hbo", gloss_lang, r["lex"], r["stem"] or None) if localize else None
        if not label:
            label = next((s["gloss"] for s in english.get(r["lex"], {}).get(r["stem"] or "", [])
                          if s["sense"] == (r["sense"] or "")), None)
        if label:
            out[code] = label
    return out


def _strong_sense_by_ref(strong: str) -> dict:
    """{'BOOK C:V': sense label} for a Hebrew strong (hbo.db ⋈ inventory) — attaches the sense to each
    occurrence of a concordance. First sense per verse wins."""
    con = _ro(_hbo_path())
    if con is None:
        return {}
    labels = _lex_sense_table()
    out: dict = {}
    for r in con.execute(
            "SELECT book, chapter, verse, lex, stem, sense FROM occurrence WHERE strong=? ORDER BY node",
            (_pad_strong(strong),)):
        ref = f"{r['book']} {r['chapter']}:{r['verse']}"
        if ref in out:
            continue
        label = next((s["gloss"] for s in labels.get(r["lex"], {}).get(r["stem"] or "", [])
                      if s["sense"] == (r["sense"] or "")), None)
        if label:
            out[ref] = label
    con.close()
    return out


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

    from collections import Counter, defaultdict
    greek_counts: Counter = Counter()
    sample_verses: dict[int, list[str]] = {}

    # Group Hebrew occurrences by verse in ONE pass. The previous version
    # rescanned all of `hwords` per verse (two O(n) comprehensions inside the
    # per-verse loop → O(verses × occurrences)), which made frequent lemmas
    # multi-second on the wire (H0430 "God" ≈ 2.4s, H3068 "LORD" far worse).
    # Insertion order == first-occurrence order, so iteration order (and thus
    # the output) is unchanged. Now O(occurrences).
    by_verse: dict[tuple, list[int]] = defaultdict(list)
    for hw in hwords:
        by_verse[(hw["book"], hw["chapter"], hw["verse"])].append(hw["idx"])

    for vkey, idxs in by_verse.items():
        grows = lcon.execute(
            "SELECT idx, strong FROM lxx_words "
            "WHERE book=? AND chapter=? AND verse=? "
            "AND strong IS NOT NULL AND is_content=1 "
            "ORDER BY idx",
            vkey).fetchall()
        if not grows:
            continue
        hcount = len(idxs)
        hidxs = sorted(idxs)
        gidxs = [(g["idx"], g["strong"]) for g in grows]
        total_g = len(gidxs)
        for hidx in hidxs:
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
        "hebrew_verses": len(by_verse),
        "greek_translations": translations,
    }
