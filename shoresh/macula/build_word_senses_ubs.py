#!/usr/bin/env python3
"""The UBS dictionaries' sense and meaning domain on every MACULA word that has one, as codes (wave 0.1, development-phase plan 2026-11-13).

Source: UBS's open release (github.com/ubsicap/ubs-open-license at macula.build_ubs_open.COMMIT, CC BY-SA 4.0), files in macula/data/ubs_open:
- Hebrew: UBS's own word index on the WLC (`index_wlc/<BOOK>.json`).
  - Each word's `LexicalLinks` entry reads `SDBH:<lemma>:<NNNMMM>:<domain name>`.
  - NNN is the base form and MMM the meaning, both counted from 0 within the dictionary entry of <lemma>.
  - So the sense's LEXID is the entry's MainId[:6] + (NNN+1) + (MMM+1) + "000"; this was checked against the domain name.
  - The index's domain name sometimes follows an older label set ("Quantity|Frequency" for "Quantity"). We publish the
    dictionary's codes, not the index's names.
- Greek: the dictionary's own references per meaning (`LEXReferences`, BBBCCCVVVWWWWW with the word position doubled), as in
  macula.ubs.greek(). The Louw-Nida number is the meaning's `LEXEntryCode`.

MACULA's inline copies of the UBS fields (sdbh, lexdomain, sensenumber, ln, domain ...) are not read (resources/LICENSES.md, rule 1).

Output, macula/data/word-senses-ubs/ (git-ignored until a release):
- words.tsv: key, lang, entry, sense, ln, domains, subdomains, basis, part.
  - `domains` and `subdomains` are ';'-joined DomainCodes; `part` is "i/n" when UBS links one sense to n MACULA words, else "".
  - A word UBS links to two senses gets two rows.
- domains.tsv: domain code -> the dictionary's English name (the code table; data columns hold codes only).
- checks.md, build.json.

    cd shoresh && .venv/bin/python3 -m macula.build_word_senses_ubs
"""
from __future__ import annotations

import collections
import datetime
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

from macula.build_ubs_open import COMMIT

HERE = Path(__file__).resolve().parent
SRC = HERE / "data" / "ubs_open"
OUT = HERE / "data" / "word-senses-ubs"
SPINE = HERE / "macula-spine.db"
HBO_DIC = SRC / "UBSHebrewDic-v0.9.3-en.JSON"
GRC_DIC = SRC / "UBSGreekNTDic-v1.1-en.JSON"
COLS = ["key", "lang", "entry", "sense", "ln", "domains", "subdomains", "basis", "part"]


def meanings(dic):
    """LEXID -> (entry MainId, LEXEntryCode, domain codes, subdomain codes, references); and lemma -> [MainId]; and code -> name"""
    lex, by_lemma, names = {}, collections.defaultdict(list), {}
    for e in dic:
        by_lemma[e["Lemma"]].append(e["MainId"])
        for bf in e.get("BaseForms") or []:
            for m in bf.get("LEXMeanings") or []:
                doms, subs = m.get("LEXDomains") or [], m.get("LEXSubDomains") or []
                for x in doms + subs:
                    if x.get("DomainCode"):
                        names.setdefault(x["DomainCode"], x.get("Domain") or "")
                lex[m["LEXID"]] = (e["MainId"], m.get("LEXEntryCode") or "", [x["DomainCode"] for x in doms if x.get("DomainCode")],
                                   [x["DomainCode"] for x in subs if x.get("DomainCode")], m.get("LEXReferences") or [])
    return lex, by_lemma, names


def hebrew(lex, by_lemma, st):
    rows = []
    for f in sorted((SRC / "index_wlc").glob("*.json")):
        for x in json.loads(f.read_text(encoding="utf-8")):
            keys = [i[1:] for i in x["ID"].split()]
            for link in x.get("LexicalLinks") or []:
                p = link.split(":")
                if p[0] != "SDBH" or len(p) < 4:
                    st["hbo_link_other"] += 1
                    continue
                st["hbo_links"] += 1
                bf, mm = divmod(int(p[2]), 1000)
                ids = [m[:6] + f"{bf + 1:03d}{mm + 1:03d}000" for m in by_lemma.get(p[1], [])]
                ids = [i for i in ids if i in lex]
                if len(ids) != 1:
                    st["hbo_no_sense" if not ids else "hbo_ambiguous"] += 1
                    continue
                entry, ln, doms, subs, _ = lex[ids[0]]
                for i, k in enumerate(keys):
                    rows.append([k, "hbo", entry, ids[0], ln, ";".join(doms), ";".join(subs), "index",
                                 f"{i + 1}/{len(keys)}" if len(keys) > 1 else ""])
    return rows


def greek(lex, st):
    rows = []
    for lid, (entry, ln, doms, subs, refs) in lex.items():
        for r in refs:
            if len(r) != 14:
                st["grc_ref_other"] += 1
                continue
            st["grc_refs"] += 1
            rows.append([f"{r[1:3]}{r[3:6]}{r[6:9]}{int(r[9:]) // 2:03d}", "grc", entry, lid, ln, ";".join(doms), ";".join(subs),
                         "references", ""])
    return rows


def main() -> int:
    st = collections.Counter()
    hl, hb, hn = meanings(json.loads(HBO_DIC.read_text(encoding="utf-8")))
    gl, _, gn = meanings(json.loads(GRC_DIC.read_text(encoding="utf-8")))
    rows = hebrew(hl, hb, st) + greek(gl, st)
    rows = sorted({tuple(r) for r in rows})
    con = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    spine, lemma = {}, {}
    for k, lang, cls, lem in con.execute("SELECT key, lang, class, lemma FROM macula_words"):
        spine[k], lemma[k] = (lang, cls), lem
    known = [r for r in rows if r[0] in spine]
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "words.tsv", "w", encoding="utf-8") as f:
        f.write("\t".join(COLS) + "\n")
        f.writelines("\t".join(r) + "\n" for r in known)
    with open(OUT / "domains.tsv", "w", encoding="utf-8") as f:
        f.write("code\tlang\tname\n")
        for lang, names in (("hbo", hn), ("grc", gn)):
            f.writelines(f"{c}\t{lang}\t{n}\n" for c, n in sorted(names.items()))
    # checks
    per_word = collections.Counter(r[0] for r in known)
    cover = collections.Counter()
    for k, (lang, cls) in spine.items():
        cover[(lang, cls, k in per_word)] += 1
    lines = ["# UBS senses per MACULA word: checks", "",
             f"Source ubs-open-license {COMMIT[:8]}; spine {SPINE.name}.", "",
             "| | count |", "|---|---|"]
    lines += [f"| {k} | {v:,} |" for k, v in sorted(st.items())]
    lines += [f"| rows (word, sense) | {len(rows):,} |", f"| rows whose key is not a MACULA spine word (dropped) | {len(rows) - len(known):,} |",
              f"| words with a sense | {len(per_word):,} |", f"| words with two or more senses | {sum(1 for v in per_word.values() if v > 1):,} |", "",
              "Coverage of MACULA words by class (words with at least one sense / all):", "", "| lang | class | with sense | all | share |",
              "|---|---|---|---|---|"]
    for lang in ("hbo", "grc"):
        for cls in sorted({c for (l, c, _) in cover if l == lang}):
            y, n = cover[(lang, cls, True)], cover[(lang, cls, False)]
            lines.append(f"| {lang} | {cls} | {y:,} | {y + n:,} | {y / (y + n):.3f} |")
    miss, tot = collections.Counter(), collections.Counter()
    for k, (lang, cls) in spine.items():
        if cls in ("noun", "verb", "adj"):
            tot[(lang, lemma[k])] += 1
            if k not in per_word:
                miss[(lang, lemma[k])] += 1
    lines += ["", "Largest gaps: content-word lemmas (noun, verb, adjective) with occurrences that have no sense. Hebrew gaps are mostly",
              "lemmas the open SDBH release (v0.9.3) has no entry for, or that its word index leaves unlinked.", "",
              "| lang | lemma | without sense | occurrences |", "|---|---|---|---|"]
    lines += [f"| {l} | {m} | {n:,} | {tot[(l, m)]:,} |" for (l, m), n in miss.most_common(30)]
    for lang in ("hbo", "grc"):
        whole = sum(1 for (l, m), n in miss.items() if l == lang and n == tot[(l, m)])
        lines.append(f"\n{lang}: {sum(n for (l, _), n in miss.items() if l == lang):,} content-word occurrences without a sense; "
                     f"{whole} lemmas have none at all.")
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    dirty = subprocess.run(["git", "status", "--porcelain", "--", str(Path(__file__))], capture_output=True, text=True).stdout.strip()
    code = subprocess.run(["git", "log", "-1", "--format=%h"], capture_output=True, text=True).stdout.strip() + ("+uncommitted" if dirty else "")
    build = {"schema": 1, "built": datetime.date.today().isoformat(), "code": code, "licence": "CC BY-SA 4.0",
             "source": {"repo": "github.com/ubsicap/ubs-open-license", "commit": COMMIT,
                        "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (HBO_DIC, GRC_DIC)}},
             "counts": {"rows": len(known), "words": len(per_word), **st}}
    (OUT / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{OUT}: {len(known):,} rows on {len(per_word):,} words; {dict(st)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
