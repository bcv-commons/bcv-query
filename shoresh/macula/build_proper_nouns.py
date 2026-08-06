#!/usr/bin/env python3
"""Proper-noun lexicon (roadmap N1) — localized name renderings per biblical name Strong's.

A name Strong's (person/place/other) → how that name is written across languages, from three signals:
  • **tipnr**    — the authoritative proper-name set: OT+NT, **typed** (person/place/other) + the
                   original Hebrew/Greek surface (`STEPBible-Data` TIPNR, CC-BY; staged via
                   `bcv-RAG/ingest/tipnr.py`). This is what brings **NT Greek names** in.
  • **gloss**    — the curated, localized name + transliteration (`strongs_gloss.tsv`, per language)
  • **aligned**  — names actually attested in real translations (`aligned_lex/<iso>.tsv`, empirical)

The proper-noun set is TIPNR ∪ STEPBible `Np` morph (`proper_strongs()`), so it now spans **OT + NT**.
The lexicon lets the analyzer recognize a name in a query (any language) → map to its Strong's → retrieve
+ drive the name-bridge; the `type` column distinguishes people/places/other.

  python -m macula.build_proper_nouns          # -> resources/proper_nouns/proper_nouns.tsv
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from macula.build_semantic_neighbors import proper_strongs  # noqa: E402

GLOSS = ROOT / "resources" / "strongs_gloss.tsv"
ALIGNED_DIR = ROOT / "resources" / "aligned_lex"
# aligned_lex_hf: bcv-commons/lexeme-alignments (HF), ~924 languages — automated complement to the
# manual ALIGNED_DIR (~10 languages). Same "never silently merge" rule as bcv-RAG's concept_expand.py/
# name_bridge.py: a language present in ALIGNED_DIR (manual, higher trust) is never mixed with its
# aligned_lex_hf counterpart — only languages absent from ALIGNED_DIR fall back to it.
ALIGNED_HF_DIR = ROOT / "resources" / "aligned_lex_hf"
TIPNR_DIR = ROOT / "bcv-RAG" / "ingest" / "_staging" / "tipnr"
TIPNR_FILES = {"person": "TIPNR_people.json", "place": "TIPNR_places.json", "other": "TIPNR_other.json"}
OUT_DIR = ROOT / "resources" / "proper_nouns"

MIN_COUNT = 2       # an aligned surface needs this many attestations (drop one-off alignment noise)
MIN_SHARE = 0.10    # …and this share of the Strong's alignments
TOPK = 8            # aligned surfaces kept per (strong, lang)
_TYPE_RANK = {"person": 3, "place": 2, "other": 1}   # if a code appears under several, keep the strongest


def _roll(code: str) -> str | None:
    """extendedStrongs 'H0671b' / 'G2953' -> rolled 'H0671' / 'G2953' (join key for gloss/aligned)."""
    m = re.match(r"^([HG])0*(\d+)", (code or "").strip())
    return f"{m.group(1)}{int(m.group(2)):04d}" if m else None


def _load_tipnr():
    """({rolled_strong: type}, {rolled_strong: [orig Hebrew/Greek surface, …]}) from staged TIPNR JSON.

    Empty if not staged (fetch via `python -m ingest.tipnr` in bcv-RAG). BOM-prefixed UTF-8."""
    types: dict = {}
    orig: dict = collections.defaultdict(list)
    for typ, fname in TIPNR_FILES.items():
        p = TIPNR_DIR / fname
        if not p.exists():
            continue
        for e in json.loads(p.read_text(encoding="utf-8-sig")):
            for nm in e.get("names", []):
                code = _roll(nm.get("extendedStrongs"))
                if not code:
                    continue
                if code not in types or _TYPE_RANK[typ] > _TYPE_RANK[types[code]]:
                    types[code] = typ
                hg = (nm.get("Hebrew_Greek") or "").strip()
                if hg and hg not in orig[code]:
                    orig[code].append(hg)
    return types, orig


def _load_glosses(proper):
    """{strong: {lang: [names]}} + {strong: translit} from strongs_gloss.tsv, restricted to names."""
    by: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    translit: dict = {}
    if not GLOSS.exists():
        return by, translit
    with GLOSS.open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 4 and p[0] in proper:
                strong, gloss, tr, lang = p[0], p[1].strip(), p[2].strip(), p[3].strip()
                if gloss:
                    by[strong][lang].append(gloss)
                if tr and strong not in translit:
                    translit[strong] = tr
    return by, translit


def _load_aligned(proper):
    """{strong: {lang: [(surface, share, count)]}} from aligned_lex/<iso>.tsv (manual, preferred) with
    aligned_lex_hf/<iso>.tsv (automated) filling in languages the manual set doesn't cover — names only,
    thresholded."""
    manual = {p.stem: p for p in ALIGNED_DIR.glob("*.tsv")}
    hf = {p.stem: p for p in (ALIGNED_HF_DIR.glob("*.tsv") if ALIGNED_HF_DIR.exists() else [])}
    paths = {**hf, **manual}   # manual wins on lang collision

    by: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    for lang, path in sorted(paths.items()):
        cand: dict = collections.defaultdict(list)
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("#") or line.startswith("surface"):
                    continue
                p = line.rstrip("\n").split("\t")
                if len(p) < 4:
                    continue
                surface, strong = p[0].strip(), p[1].strip()
                if strong not in proper or not surface:
                    continue
                try:
                    count, share = int(p[2]), float(p[3])
                except ValueError:
                    continue
                if count >= MIN_COUNT and share >= MIN_SHARE:
                    cand[strong].append((surface, share, count))
        for strong, rows in cand.items():
            by[strong][lang] = sorted(rows, key=lambda r: -r[1])[:TOPK]
    return by


def build():
    np_proper = proper_strongs()                       # STEPBible Np (Hebrew, untyped)
    tipnr_type, tipnr_orig = _load_tipnr()             # TIPNR (OT+NT, typed) + original surfaces
    proper = set(np_proper) | set(tipnr_type)
    gloss_by, translit = _load_glosses(proper)
    aligned_by = _load_aligned(proper)
    ng = sum(1 for s in proper if s.startswith("G"))
    print(f"[proper-nouns] {len(proper)} name Strong's ({ng} NT/Greek) · TIPNR-typed {len(tipnr_type)} · "
          f"{len(gloss_by)} with a gloss · {len(aligned_by)} with aligned surfaces", file=sys.stderr)

    rows = []
    for strong in sorted(proper):
        tr = translit.get(strong, "")
        typ = tipnr_type.get(strong, "name")           # 'name' = untyped (Np-only, no TIPNR entry)
        lang0 = "hbo" if strong.startswith("H") else "grc"
        seen: set = set()                              # (lang, surface) dedup across sources
        for orig in tipnr_orig.get(strong, []):        # original Hebrew/Greek spelling
            if (lang0, orig) not in seen:
                seen.add((lang0, orig))
                rows.append((strong, tr, typ, lang0, orig, "tipnr", 1.0))
        for lang, names in gloss_by.get(strong, {}).items():
            for name in names:
                if (lang, name) not in seen:
                    seen.add((lang, name))
                    rows.append((strong, tr, typ, lang, name, "gloss", 1.0))
        for lang, surfs in aligned_by.get(strong, {}).items():
            for surface, share, _c in surfs:
                if (lang, surface) not in seen:
                    seen.add((lang, surface))
                    rows.append((strong, tr, typ, lang, surface, "aligned", round(share, 3)))

    # One file per language (resources/proper_nouns/<lang>.tsv), not one merged table — mirrors
    # aligned_lex/aligned_lex_hf's own per-language layout. With ~930 languages now feeding this
    # (via aligned_lex_hf), a single merged file was a ~60MB blob that any one-language read had to
    # linearly scan; per-language files keep git diffs scoped to the languages that actually changed
    # and let consumers open just the language they need.
    by_lang: dict[str, list[tuple]] = collections.defaultdict(list)
    for strong, tr, typ, lang, surface, src, w in rows:
        by_lang[lang].append((strong, tr, typ, surface, src, w))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*.tsv"):
        old.unlink()
    for lang, lrows in by_lang.items():
        with (OUT_DIR / f"{lang}.tsv").open("w", encoding="utf-8") as fh:
            fh.write(f"# Proper-noun lexicon (roadmap N1), lang={lang}: biblical name Strong's -> "
                     f"localized renderings; shoresh macula.build_proper_nouns. "
                     f"OT+NT via TIPNR (CC-BY) ∪ STEPBible Np.\n")
            fh.write("strong\ttranslit\ttype\tsurface\tsource\tweight\n")
            for strong, tr, typ, surface, src, w in sorted(lrows):
                fh.write(f"{strong}\t{tr}\t{typ}\t{surface}\t{src}\t{w}\n")

    langs = sorted(by_lang)
    covered = len({r[0] for r in rows})
    bytype = collections.Counter(tipnr_type.get(s, "name") for s in {r[0] for r in rows})
    print(f"[proper-nouns] {len(rows)} renderings · {covered} names "
          f"({dict(bytype)}) · {len(langs)} langs -> {OUT_DIR}/<lang>.tsv", file=sys.stderr)

    _write_core(proper, tipnr_type, tipnr_orig, translit)
    return rows


def _write_core(proper, tipnr_type, tipnr_orig, translit) -> None:
    """resources/proper_nouns/core.tsv — export candidate #1 (bcv-commons-export-candidates.md):
    which Strong's are names, their type, and their ORIGINAL Hebrew/Greek spelling. Language-independent
    (no per-language renderings — that tier stays in the per-<lang>.tsv files above, which are NOT
    bcv-query-owned per the ownership-handoff decision). This is the part that IS bcv-query-native and
    export-worthy on its own: a real classification (person/place/other via TIPNR) + the actual
    original-language spelling, not a judgment call the way the synonym-pairs work is."""
    rows = []
    for strong in sorted(proper):
        typ = tipnr_type.get(strong, "name")
        tr = translit.get(strong, "")
        lang0 = "hbo" if strong.startswith("H") else "grc"
        origs = tipnr_orig.get(strong, [])
        if origs:
            for orig in origs:
                rows.append((strong, typ, tr, lang0, orig))
        else:
            rows.append((strong, typ, tr, lang0, ""))   # Np-only, no TIPNR original-spelling entry

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "core.tsv").open("w", encoding="utf-8") as fh:
        fh.write("# Proper-noun core (export candidate #1) — which Strong's are biblical names, their\n"
                  "# type (person/place/other via STEPBible TIPNR, CC-BY, ∪ STEPBible Np morph), and their\n"
                  "# ORIGINAL Hebrew/Greek spelling. Language-independent — no per-language renderings\n"
                  "# (those stay in proper_nouns/<lang>.tsv, a separate, larger, ownership-handoff tier).\n"
                  "# See build_proper_nouns.py.\n")
        fh.write("strong\ttype\ttranslit\toriginal_lang\toriginal_surface\n")
        for row in rows:
            fh.write("\t".join(row) + "\n")
    print(f"[proper-nouns] core: {len(rows)} rows ({len(proper)} distinct Strong's) -> {OUT_DIR}/core.tsv",
          file=sys.stderr)


if __name__ == "__main__":
    build()
