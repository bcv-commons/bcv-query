#!/usr/bin/env python3
"""Extend book_names.json with localized Bible book names for more languages,
sourced from TWO references and merged (shortest usable form wins):

  (b) unfoldingWord / Door43 USFM  — authoritative per-translation names from the
      \\toc2 (short), \\h (header), \\toc1 (long) tags + manifest project titles.
  (a) Wikidata                     — labels (ar/hi/bn/as/ha…) for instances of
      "book of the Bible" (Q29154430), mapped to USFM codes via English label.

Per (lang, code) we collect every candidate string from both, then pick the
SHORTEST (fewest words, then chars) as the display name — users type short forms
("যোহন"), not formal ones ("যোহন লিখিত সুসমাচার") — and keep the rest as
extra_aliases. The reference parser (indexer/references.py) does longest-suffix
alias matching, so both short and formal forms resolve.

Non-Latin languages drop pure-ASCII candidates (e.g. the Latin \\toc3 "jhn").

Usage: python3 scripts/build_book_names.py            # default langs
       python3 scripts/build_book_names.py --langs ar,hi
Writes bcv-RAG/book_names.json (existing langs preserved).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from indexer.references import (  # noqa: E402
    NUMBER_TO_CODE, _ENGLISH_BOOK_NAMES, _normalize_alias)

OUT = HERE.parent / "resources" / "book_names.json"
CODES = set(NUMBER_TO_CODE.values())

# Door43 repos to mine per language (Door43-Catalog owner). Order doesn't matter;
# all candidates are pooled and the shortest wins.
UW_REPOS = {
    "hi": ["hi_irv"], "bn": ["bn_irv"], "as": ["as_irv"],
    "ha": ["ha_ulb"], "ar": ["ar_avd", "ar_nav"],
    "id": ["id_tb1", "id_ulb", "id_ayt"],
}
WD_BOOK_CLASS = "Q29154430"  # "book of the Bible"
UA = {"User-Agent": "bcv-query/1.0 (book-name builder)"}


def _get(url: str, t: int = 25) -> str:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                  timeout=t).read().decode("utf-8", "replace")


def _clean(s: str) -> str:
    return re.sub(r"[।॥.,:;]+$", "", (s or "").strip()).strip()


def _is_ascii(s: str) -> bool:
    return all(ord(c) < 128 for c in s)


# ---------------------------------------------------------------- unfoldingWord
def mine_unfoldingword(lang: str) -> tuple[dict[str, set[str]], bool]:
    """Returns (names, ok). ok is False if EVERY repo's manifest failed to load
    (network down) — the caller then keeps existing data instead of clobbering
    it with a Wikidata-only partial."""
    out: dict[str, set[str]] = {}
    ok = False
    for repo in UW_REPOS.get(lang, []):
        base = f"https://git.door43.org/Door43-Catalog/{repo}/raw/branch/master"
        try:
            man = yaml.safe_load(_get(f"{base}/manifest.yaml"))
            ok = True
        except Exception as e:
            print(f"  {repo}: manifest err {e}", file=sys.stderr)
            continue
        for p in man.get("projects", []):
            code = p["identifier"].upper()
            if code not in CODES:
                continue
            cands = {_clean(p.get("title", ""))}
            try:
                usfm = _get(f"{base}/{p['path'].lstrip('./')}")
                for tag in ("toc2", "h", "toc1"):
                    m = re.search(rf"\\{tag}\s+(.+)", usfm)
                    if m:
                        cands.add(_clean(m.group(1)))
            except Exception:
                pass
            out.setdefault(code, set()).update(c for c in cands if c)
    return out, ok


# -------------------------------------------------------------------- Wikidata
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _en_to_code() -> dict[tuple[str, str], str]:
    """(ordinal, core) -> code from our English names, for matching WD labels."""
    out: dict[tuple[str, str], str] = {}
    for code, name in _ENGLISH_BOOK_NAMES.items():
        m = re.match(r"([123])\s+(.*)", name)
        ordn, core = (m.group(1), m.group(2)) if m else ("", name)
        out[(ordn, _norm(core))] = code
    return out


_WRAP = re.compile(r"\b(the|of|book|gospel|epistle|letter|according|to|saint|st|"
                   r"paul|paul's|apostle|apostles|general|holy)\b", re.I)
_ORD = {"first": "1", "second": "2", "third": "3", "i": "1", "ii": "2", "iii": "3"}


def _label_to_code(label: str, lookup: dict[tuple[str, str], str]) -> str | None:
    s = label.lower()
    ordn = ""
    m = re.match(r"\s*(first|second|third|iii|ii|i|[123])\b", s)
    if m:
        ordn = _ORD.get(m.group(1), m.group(1))
        s = s[m.end():]
    core = _norm(_WRAP.sub(" ", s))
    return lookup.get((ordn, core)) or lookup.get(("", core))


def mine_wikidata(langs: list[str]) -> dict[str, dict[str, set[str]]]:
    sel = " ".join("?" + l for l in (["en"] + langs))
    opt = "".join(f'OPTIONAL{{?b rdfs:label ?{l} filter(lang(?{l})="{l}")}} '
                  for l in (["en"] + langs))
    q = f"SELECT ?b {sel} WHERE {{ ?b wdt:P31 wd:{WD_BOOK_CLASS} . {opt} }}"
    url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q)
    data = json.loads(urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=60).read())
    lookup = _en_to_code()
    out: dict[str, dict[str, set[str]]] = {l: {} for l in langs}
    mapped = 0
    for row in data["results"]["bindings"]:
        en = row.get("en", {}).get("value")
        if not en:
            continue
        code = _label_to_code(en, lookup)
        if not code:
            continue
        mapped += 1
        for l in langs:
            v = row.get(l, {}).get("value")
            if v:
                out[l].setdefault(code, set()).add(_clean(v))
    print(f"  wikidata: mapped {mapped} book items to codes", file=sys.stderr)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", default="ar,hi,bn,as,ha")
    args = ap.parse_args()
    langs = [l.strip() for l in args.langs.split(",") if l.strip()]

    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"names": {}, "extra_aliases": {}}
    data.setdefault("names", {})
    data.setdefault("extra_aliases", {})

    wd = mine_wikidata(langs)
    for lang in langs:
        print(f"=== {lang} ===", file=sys.stderr)
        uw, uw_ok = mine_unfoldingword(lang)
        if not uw_ok and lang in data["names"]:
            print(f"  unfoldingWord unreachable — keeping existing {lang} data",
                  file=sys.stderr)
            continue
        cand: dict[str, set[str]] = {}
        for code, names in uw.items():
            cand.setdefault(code, set()).update(names)
        for code, names in wd.get(lang, {}).items():
            cand.setdefault(code, set()).update(names)

        latin = lang == "ha"
        vals_by: dict[str, set[str]] = {}
        for code, raw in cand.items():
            vals = {v for v in raw if v and (latin or not _is_ascii(v))}
            if vals:
                vals_by[code] = vals

        # primary display name = shortest candidate (fewest words, then chars)
        names = {c: sorted(v, key=lambda s: (len(s.split()), len(s)))[0]
                 for c, v in vals_by.items()}

        # Conflict resolution: which codes claim each normalized form. An alias
        # is kept ONLY if it is unambiguous (claimed by exactly this code) and is
        # not another book's primary name — so an auto-merge mislabel (e.g. a
        # Genesis label leaking into Exodus's candidates) can't shadow the right
        # book in the flat, last-write-wins alias map.
        form_codes: dict[str, set[str]] = defaultdict(set)
        for c, v in vals_by.items():
            for s in v:
                form_codes[_normalize_alias(s)].add(c)
        prim_norm: dict[str, str] = {}
        for c, nm in names.items():
            k = _normalize_alias(nm)
            if k in prim_norm:
                print(f"  WARN {lang}: primary collision {nm!r} "
                      f"({prim_norm[k]} vs {c})", file=sys.stderr)
            prim_norm.setdefault(k, c)

        aliases: dict[str, list[str]] = {}
        short = dropped = 0
        for c, v in vals_by.items():
            if len(names[c].split()) <= 2:
                short += 1
            al = []
            for s in v:
                if s == names[c]:
                    continue
                k = _normalize_alias(s)
                if form_codes[k] == {c} and prim_norm.get(k, c) == c:
                    al.append(s)
                else:
                    dropped += 1
            if al:
                aliases[c] = sorted(set(al))
        data["names"][lang] = names
        if aliases:
            data["extra_aliases"][lang] = aliases
        print(f"  {len(names)}/66 named ({short} short ≤2 words; "
              f"{dropped} ambiguous aliases dropped)", file=sys.stderr)

    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT} — langs: {sorted(data['names'])}", file=sys.stderr)


if __name__ == "__main__":
    main()
