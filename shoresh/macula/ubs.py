"""UBS dictionaries (CC BY-SA 4.0) on MACULA's words: the meaning domain the dictionary gives a word in its place.

    from macula import ubs
    ubs.hebrew("EXO")   # -> {morpheme key: SDBH lexical domain}            (index_wlc: UBS's own word index on the WLC)
    ubs.greek()         # -> {word key: (Louw-Nida subdomain, its code)}    (the dictionary's references per sense)

Files: macula/data/ubs_open (macula.build_ubs_open downloads them from github.com/ubsicap/ubs-open-license at its COMMIT).
Greek references are BBBCCCVVVWWWWW with the word position doubled; MACULA's key is BBCCCVVVWWW.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIR = HERE / "data" / "ubs_open"


def hebrew(book: str) -> dict[str, str]:
    p = DIR / "index_wlc" / f"{book}.json"
    if not p.exists():
        return {}
    out = {}
    for x in json.loads(p.read_text(encoding="utf-8")):
        links = [l for l in x.get("LexicalLinks") or [] if l.startswith("SDBH:")]
        if links:
            dom = links[0].split(":")[3]
            if dom:
                out[x["ID"][1:]] = dom
    return out


@functools.lru_cache(maxsize=1)
def greek() -> dict[str, tuple[str, str]]:
    d = json.loads((DIR / "UBSGreekNTDic-v1.1-en.JSON").read_text(encoding="utf-8"))
    out: dict[str, tuple[str, str]] = {}
    for e in d:
        for bf in e.get("BaseForms") or []:
            for m in bf.get("LEXMeanings") or []:
                dom = (m.get("LEXSubDomains") or m.get("LEXDomains") or [None])[0]
                if not dom:
                    continue
                for r in m.get("LEXReferences") or []:
                    if len(r) == 14:
                        out.setdefault(f"{r[1:3]}{r[3:6]}{r[6:9]}{int(r[9:]) // 2:03d}", (dom["Domain"], dom["DomainCode"]))
    return out
