#!/usr/bin/env python3
"""Aramaic -> Hebrew cognate map, so the Aramaic of Daniel and Ezra reaches tables keyed by Hebrew lexemes.

Daniel's Aramaic (2:4b-7:28) drafts far below its Hebrew: its 490 content lexemes have their own Strong's numbers, so almost none is
seen in training (research, 2026-11-14: 0.015 of tokens against 0.976 in the Hebrew span; a third drafted with no word at all).

    cd shoresh && .venv/bin/python3 -m macula.build_aramaic_cognates

One row per Aramaic lexeme in MACULA Hebrew (wlang A):
  aramaic_strong, aramaic_lemma, tokens, hebrew_strong, hebrew_lemma, basis, greek_check, domain_check (proper names left out)
  basis:
    strongs        Strong's dictionary: "(Aramaic) corresponding to H####" (public domain; OpenScriptures XML, CC BY 4.0)
    strongs_shifted Strong's: "corresponding to H#### in the sense of / through the idea of": same root, meaning moved (Aramaic
                   שְׁכַח "find" against Hebrew שָׁכַח "forget"); for root-level use only
    strongs_root   Strong's derives the Aramaic word "from" a Hebrew root, or from an Aramaic entry with a plain correspondent
    consonants     no Strong's link: a Hebrew content lexeme with the same consonants (after Aramaic -א / -ה endings and the
                   regular shifts ד/ז, ת/שׁ, ט/צ, ע/צ), the one whose Septuagint Greek overlaps most with the Aramaic word's
    ''             none found
  greek_check: where the Aramaic word and its Hebrew cognate both have Septuagint links (MACULA greekstrong), 1 if their most
    frequent Greek lexemes overlap, else 0; '' where either has none. A check, not evidence used for strongs rows.
    The Old Greek of Daniel 3-6 is free, so a 0 there often means nothing.
  domain_check: 1 if the two lexemes share a UBS (SDBH) domain code, 0 if both have domains and share none, else ''.
Output macula/data/aramaic-cognates/{cognates.tsv, checks.md, build.json} (git-ignored). Not read: BHSA, TBTA, English text
(Strong's glosses are not read or written; only its cross-reference numbers).
"""
from __future__ import annotations

import collections
import csv
import datetime
import json
import re
import sqlite3
import subprocess
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "aramaic-cognates"
REPO = "openscriptures/HebrewLexicon"
COMMIT = "21c9add13bc727d3a951361778e97e3ff7afd1ce"            # the same pin as build_bdb_roots.py
URL = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/HebrewStrong.xml"
CACHE = DATA / f"HebrewStrong-{COMMIT[:8]}.xml"
NS = "{http://openscriptures.github.com/morphhb/namespace}"
SHIFT = str.maketrans({"ד": "ז", "ת": "ש", "ט": "צ", "ע": "צ"})
FINAL = str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"})


def cons(s: str) -> str:
    return re.sub(r"[^א-ת]", "", unicodedata.normalize("NFD", s)).translate(FINAL)


def variants(c: str) -> set:
    out = {c}
    for base in list(out):
        if len(base) > 2 and base[-1] in "אה":
            out.add(base[:-1])
    for base in list(out):
        out.add(base.translate(SHIFT))
    return out


def norm(st: str) -> str:
    m = re.match(r"0*(\d+)", st or "")
    return m.group(1) if m else ""


def main() -> int:
    if not CACHE.exists():
        CACHE.write_bytes(urllib.request.urlopen(URL, timeout=60).read())
    root = ET.parse(CACHE).getroot()
    corr, figur, src_from, lang = {}, {}, {}, {}
    for e in root.iter(f"{NS}entry"):
        sid = e.get("id", "")[1:]
        w = e.find(f"{NS}w")
        lang[sid] = (w.get("{http://www.w3.org/XML/1998/namespace}lang") if w is not None else "") or ""
        s = e.find(f"{NS}source")
        if s is None:
            continue
        text = "".join(s.itertext())
        refs = [x.get("src", "")[1:] for x in s.iter(f"{NS}w") if x.get("src", "").startswith("H")]
        t = re.sub(r"\s+", " ", text).strip()
        # "(Aramaic) or חֲזָה; (Aramaic), corresponding to 2372;" and "(Aramaic) or לָה; (Aramaic) (Daniel 4:32), corresponding to 3808":
        # a spelling variant first, then the same plain statement
        t = re.sub(r"^\(Aramaic\) or [^;]+; \(Aramaic\)(?: \([^)]*\))?,? \(?", "(Aramaic) ", t)
        if refs and re.match(r"^\(Aramaic\) (corresponding to|the same as) \S+?;?$", t):
            corr[sid] = refs[0]                                       # a plain cognate
        elif refs and re.match(r"^\(Aramaic\) corresponding to ", t) and re.search(r"sense|idea", t):
            figur[sid] = refs[0]                                      # a cognate whose meaning moved ("in the sense of", "through the idea of")
        elif refs:
            src_from[sid] = refs[0]

    m = sqlite3.connect(f"file:{HERE / 'macula-spine.db'}?mode=ro", uri=True)
    lf = sqlite3.connect(f"file:{HERE / 'lowfat-hbo.db'}?mode=ro", uri=True)
    greek = collections.defaultdict(collections.Counter)            # (wlang, strong) -> Greek lexemes
    gk = {k[:12]: g for k, g in lf.execute("select key, greekstrong from lowfat_words where greekstrong != ''")}
    aram, heb = collections.Counter(), collections.Counter()
    lemma = {}
    proper = {k[:12] for (k,) in lf.execute("select key from lowfat_words where type = 'proper'")}
    doms = {}
    for r in csv.DictReader(open(DATA / "word-senses-ubs/words.tsv", encoding="utf-8"), delimiter="\t"):
        if r["lang"] == "hbo" and r["domains"]:
            doms[r["key"]] = r["domains"]
    ldom = collections.defaultdict(collections.Counter)            # (wlang, strong) -> UBS domain codes
    for k, wl, lem, st, cl in m.execute("select key, wlang, lemma, strong, class from macula_words where lang = 'hbo'"):
        if cl not in ("noun", "verb", "adj", "adv") or k in proper:
            continue
        s = norm(st)
        if not s:
            continue
        key = (wl, s)
        (aram if wl == "A" else heb)[s] += 1
        lemma.setdefault(key, unicodedata.normalize("NFC", lem or ""))
        if k in gk:
            greek[key][norm(gk[k].split()[0])] += 1
        for d in (doms.get(k) or "").split(";"):
            if d:
                ldom[key][d] += 1
    by_cons = collections.defaultdict(list)
    for s, n in heb.items():
        by_cons[cons(lemma[("H", s)])].append(s)

    def overlap(a: str, h: str) -> float:
        ga, gh = greek.get(("A", a)), greek.get(("H", h))
        if not ga or not gh:
            return -1.0
        ta, th = sum(ga.values()), sum(gh.values())
        return sum(min(ga[g] / ta, gh[g] / th) for g in ga if g in gh)

    rows, st = [], collections.Counter()
    for a, n in aram.most_common():
        h, basis = "", ""
        c = corr.get(a)
        if c and norm(c) in heb:
            h, basis = norm(c), "strongs"
        elif a in figur and norm(figur[a]) in heb:
            h, basis = norm(figur[a]), "strongs_shifted"
        elif a in src_from and corr.get(norm(src_from[a])) and norm(corr[norm(src_from[a])]) in heb:
            h, basis = norm(corr[norm(src_from[a])]), "strongs_root"
        elif a in src_from and norm(src_from[a]) in heb and lang.get(norm(src_from[a])) == "heb":
            h, basis = norm(src_from[a]), "strongs_root"
        else:
            cands = {x for v in variants(cons(lemma[("A", a)])) for x in by_cons.get(v, [])}
            scored = sorted(((overlap(a, x), heb[x], x) for x in cands), reverse=True)
            if scored and scored[0][0] > 0:
                h, basis = scored[0][2], "consonants"
        chk, dchk = "", ""
        if h:
            o = overlap(a, h)
            chk = "" if o < 0 else ("1" if o > 0 else "0")
            da, dh = ldom.get(("A", a)), ldom.get(("H", h))
            if da and dh:
                dchk = "1" if set(da) & set(dh) else "0"
        rows.append([a, lemma[("A", a)], str(n), h, lemma.get(("H", h), "") if h else "", basis, chk, dchk])
        st[("lexemes", basis or "none")] += 1
        st[("tokens", basis or "none")] += n
        if chk:
            st[("greek_check:" + basis, chk)] += 1
        if dchk:
            st[("domain_check:" + basis, dchk)] += 1
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "cognates.tsv", "w", encoding="utf-8") as f:
        f.write("aramaic_strong\taramaic_lemma\ttokens\thebrew_strong\thebrew_lemma\tbasis\tgreek_check\tdomain_check\n")
        f.writelines("\t".join(r) + "\n" for r in rows)
    tot = sum(aram.values())
    lines = ["# Aramaic cognates: checks", "", f"Aramaic content lexemes: {len(aram):,}; tokens: {tot:,}.", "",
             "| what | value | count |", "|---|---|---|"]
    lines += [f"| {a} | {b} | {n:,} |" for (a, b), n in sorted(st.items())]
    linked = sum(n for (a, b), n in st.items() if a == "tokens" and b != "none")
    lines += ["", f"Tokens with a Hebrew cognate: {linked / tot:.3f}."]
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = subprocess.run(["git", "log", "-1", "--format=%h"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    (OUT / "build.json").write_text(json.dumps({"schema": 1, "built": datetime.date.today().isoformat(), "code": code,
                                                "strongs": f"{REPO}@{COMMIT}", "not_read": ["BHSA", "TBTA", "English text"]},
                                               indent=1) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
