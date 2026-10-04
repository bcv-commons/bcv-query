#!/usr/bin/env python3
"""Re-source resources/semantic_domains/ from UBS's open release (CC BY-SA 4.0), replacing the
"used with permission" MARBLE data that came through MACULA and could not be redistributed.

Source (pinned): github.com/ubsicap/ubs-open-license @ COMMIT
  dictionaries/hebrew/JSON/UBSHebrewDic-v0.9.3-en.JSON      UBS Dictionary of Biblical Hebrew (from SDBH)
  dictionaries/greek/JSON/UBSGreekNTDic-v1.1-en.JSON         UBS Dictionary of the Greek NT (Louw-Nida)
  dictionaries/greek/JSON/UBSGreekNTDicLexicalDomains-v1.*   localized Louw-Nida domain names

Writes, same schema as before so shoresh and bcv-RAG need no change:
  semantic_domains/grc.tsv   sdbg  Louw-Nida domain per Greek Strong's (subdomain where given)
  semantic_domains/hbo.tsv   lex   SDBH lexical domain per Hebrew Strong's
                             sdbg  Louw-Nida via the LXX bridge (Hebrew -> Greek renderings -> grc.tsv)
  semantic_domains/domain_labels/{eng,spa,fra,cmn-Hans}.tsv   Louw-Nida domain names
(`ind` and `deu` label files are our own translations and are left as they are.)
  senses/hbo.tsv, senses/grc.tsv   Strong's-keyed sense inventories: one row per dictionary sense
                             (sense = its order in the entry, gloss = its first English gloss,
                             count = Scripture references UBS lists for it)

The open release has no SDBH core or contextual axis; those were retired (replaced by
resources/semantic_groups/). count = the number of Scripture references UBS lists for a sense; share =
count over the word's total for that axis; a word's primary domain is always kept, others when count >= 2
(as before).

  cd shoresh && .venv/bin/python3 -m macula.build_ubs_open
"""
from __future__ import annotations

import collections
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "resources" / "semantic_domains"
CACHE = HERE / "data" / "ubs_open"
COMMIT = "33dcc8c671511151551804e073f1d461bc5d5b1a"
RAW = f"https://raw.githubusercontent.com/ubsicap/ubs-open-license/{COMMIT}/dictionaries"
FILES = {
    "hebrew": "hebrew/JSON/UBSHebrewDic-v0.9.3-en.JSON",
    "greek": "greek/JSON/UBSGreekNTDic-v1.1-en.JSON",
    "greek_dom_en": "greek/JSON/UBSGreekNTDicLexicalDomains-v1.1-en.JSON",
    "greek_dom_es": "greek/JSON/UBSGreekNTDicLexicalDomains-v1.0-es.JSON",
    "greek_dom_fr": "greek/JSON/UBSGreekNTDicLexicalDomains-v1.1-fr.JSON",
    "greek_dom_zh": "greek/JSON/UBSGreekNTDicLexicalDomains-v1.0-zh-hans.JSON",
}
LABEL_FILES = {"eng": "greek_dom_en", "spa": "greek_dom_es", "fra": "greek_dom_fr", "cmn-Hans": "greek_dom_zh"}
MIN_COUNT = 2
ATTRIBUTION = ("UBS Dictionary of Biblical Hebrew / UBS Dictionary of the Greek New Testament, "
               "© United Bible Societies 2023, CC BY-SA 4.0 (github.com/ubsicap/ubs-open-license @ "
               f"{COMMIT[:12]})")


def fetch(key: str) -> Path:
    """Cached download; curl resumes partial files (raw.githubusercontent.com is slow from here)."""
    dest = CACHE / Path(FILES[key]).name
    CACHE.mkdir(parents=True, exist_ok=True)
    for _ in range(8):
        try:
            json.loads(dest.read_text(encoding="utf-8-sig"))
            return dest
        except (FileNotFoundError, json.JSONDecodeError):
            subprocess.run(["curl", "-sSL", "-C", "-", "--max-time", "280", "-o", str(dest),
                            f"{RAW}/{FILES[key]}"], check=False)
    sys.exit(f"could not download {FILES[key]}")


def load(key: str):
    return json.loads(fetch(key).read_text(encoding="utf-8-sig"))


def _strong(code: str, prefix: str) -> str | None:
    m = re.match(r"^[HAG]?(\d+)", code.strip())
    return f"{prefix}{int(m.group(1)):04d}" if m else None


def senses(entries: list, prefix: str, sub_first: bool):
    """Yield (strong, domain_code, label, n_refs) per sense and domain."""
    for e in entries:
        strongs = {s for s in (_strong(c, prefix) for c in e.get("StrongCodes") or []) if s}
        for bf in e.get("BaseForms") or []:
            for lm in bf.get("LEXMeanings") or []:
                doms = (lm.get("LEXSubDomains") or []) if sub_first else []
                doms = doms or lm.get("LEXDomains") or []
                n = len(lm.get("LEXReferences") or []) or 1
                for d in doms:
                    code = (d.get("DomainCode") or "").strip()
                    if code:
                        for s in strongs:
                            yield s, code, (d.get("Domain") or "").strip(), n


def aggregate(rows, axis: str) -> list[tuple]:
    agg: dict = collections.defaultdict(collections.Counter)
    label: dict = {}
    for s, code, lab, n in rows:
        agg[s][code] += n
        label.setdefault(code, lab)
    out = []
    for s, counter in agg.items():
        total = sum(counter.values())
        for i, (code, n) in enumerate(counter.most_common()):
            if i == 0 or n >= MIN_COUNT:
                out.append((s, axis, code, label[code], n, round(n / total, 3)))
    return out


def write(path: Path, rows: list[tuple]) -> None:
    rows.sort(key=lambda r: (r[0], r[1], -r[4]))
    with path.open("w", encoding="utf-8") as fh:
        fh.write("strong\tdomain_type\tdomain\tlabel\tcount\tshare\n")
        for s, dtype, code, lab, n, share in rows:
            fh.write(f"{s}\t{dtype}\t{code}\t{lab}\t{n}\t{share}\n")
    print(f"  wrote {path.relative_to(ROOT)}: {len({r[0] for r in rows})} words, {len(rows)} rows",
          file=sys.stderr)


def sense_rows(entries: list, prefix: str) -> list[tuple]:
    """(strong, sense, gloss, count, share) in the old senses/<lang>.tsv schema."""
    per: dict = collections.defaultdict(list)
    for e in entries:
        strongs = sorted({s for s in (_strong(c, prefix) for c in e.get("StrongCodes") or []) if s})
        meanings = [lm for bf in e.get("BaseForms") or [] for lm in bf.get("LEXMeanings") or []]
        for i, lm in enumerate(meanings, start=1):
            loc = next((x for x in lm.get("LEXSenses") or [] if x.get("LanguageCode") == "en"), None)
            gloss = ((loc or {}).get("Glosses") or [""])[0].strip()
            n = len(lm.get("LEXReferences") or [])
            if not gloss or n == 0:
                continue
            for s in strongs:
                per[s].append((str(i), gloss.replace("\t", " "), n))
    out = []
    for s, senses in per.items():
        total = sum(n for _i, _g, n in senses)
        for rank, (i, g, n) in enumerate(sorted(senses, key=lambda x: -x[2])):
            if rank == 0 or n >= MIN_COUNT:
                out.append((s, i, g, n, round(n / total, 3)))
    return sorted(out, key=lambda r: (r[0], -r[3]))


def write_senses(path: Path, rows: list[tuple]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        fh.write("strong\tsense\tgloss\tcount\tshare\n")
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")
    print(f"  wrote {path.relative_to(ROOT)}: {len({r[0] for r in rows})} words, {len(rows)} senses",
          file=sys.stderr)


_POINTS = re.compile(r"[\u0591-\u05C7]")


def relation_rows(entries: list, prefix: str) -> list[tuple]:
    """(strong, sense, lemma, relation, other_lemma, other_strongs) for every LEXSynonyms / LEXAntonyms
    link; `sense` numbers meanings as sense_rows does. The other word is given as a lemma: resolved to
    Strong's by the dictionary's own headwords, exact first, then consonants only if unambiguous."""
    exact: dict = collections.defaultdict(set)
    bare: dict = collections.defaultdict(set)
    for e in entries:
        strongs = {s for s in (_strong(c, prefix) for c in e.get("StrongCodes") or []) if s}
        for lem in [e.get("Lemma") or ""] + list(e.get("AlternateLemmas") or []):
            lem = lem if isinstance(lem, str) else (lem.get("Lemma") or "")
            if lem:
                exact[lem].update(strongs)
                bare[_POINTS.sub("", lem)].add(frozenset(strongs))
    # who links to whom (lemma level), to prefer the homograph that links back
    links: dict = collections.defaultdict(set)
    for e in entries:
        for bf in e.get("BaseForms") or []:
            for lm in bf.get("LEXMeanings") or []:
                for field in ("LEXSynonyms", "LEXAntonyms"):
                    for other in lm.get(field) or []:
                        links[e.get("Lemma") or ""].add(_POINTS.sub("", str(other).strip()))
    strongs_of_lemma: dict = collections.defaultdict(set)
    for e in entries:
        for s in (_strong(c, prefix) for c in e.get("StrongCodes") or []):
            if s:
                strongs_of_lemma[s].add(e.get("Lemma") or "")
    freq = _strong_freq(prefix)
    out = []
    for e in entries:
        strongs = sorted({s for s in (_strong(c, prefix) for c in e.get("StrongCodes") or []) if s})
        meanings = [lm for bf in e.get("BaseForms") or [] for lm in bf.get("LEXMeanings") or []]
        me = _POINTS.sub("", e.get("Lemma") or "")
        for i, lm in enumerate(meanings, start=1):
            for rel, field in (("synonym", "LEXSynonyms"), ("antonym", "LEXAntonyms")):
                for other in lm.get(field) or []:
                    other = (other if isinstance(other, str) else str(other)).strip()
                    if not other:
                        continue
                    hit = exact.get(other)
                    if not hit:
                        cands = bare.get(_POINTS.sub("", other), set())
                        hit = set(next(iter(cands))) if len(cands) == 1 else set()
                    # several homographs: the one whose entry links back first, then the more frequent word
                    back = lambda s: any(me in links.get(lem, set()) for lem in strongs_of_lemma.get(s, ()))
                    ordered = sorted(hit, key=lambda s: (not back(s), -freq.get(s, 0), s))
                    for s in strongs:
                        out.append((s, str(i), e.get("Lemma") or "", rel, other, ",".join(ordered)))
    return out


def _strong_freq(prefix: str) -> dict:
    import sqlite3
    db = sqlite3.connect(f"file:{HERE / 'lexeme-spine.db'}?mode=ro", uri=True)
    lang = "hbo" if prefix == "H" else "grc"
    return {f"{prefix}{int(s):04d}": n for s, n in db.execute(
        f"SELECT strong, COUNT(*) FROM spine_words WHERE lexeme LIKE '{lang}:%' AND strong IS NOT NULL GROUP BY strong")}


def write_relations(path: Path, rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"# source={ATTRIBUTION}; synonym and antonym links between dictionary senses. `sense` numbers\n"
                 "# the word's meanings as resources/senses/ does; other_strongs is empty where the linked lemma\n"
                 "# could not be resolved (phrases, ambiguous spellings). Built by shoresh/macula/build_ubs_open.py.\n")
        fh.write("strong\tsense\tlemma\trelation\tother_lemma\tother_strongs\n")
        for r in sorted(set(rows)):
            fh.write("\t".join(r) + "\n")
    n_res = sum(1 for r in set(rows) if r[5])
    print(f"  wrote {path.relative_to(ROOT)}: {len(set(rows))} links, {n_res} resolved to Strong's", file=sys.stderr)


def write_labels(lang: str, key: str) -> None:
    out = {}
    for d in load(key):
        loc = (d.get("SemanticDomainLocalizations") or [{}])[0]
        if d.get("Code") and loc.get("Label"):
            out[d["Code"]] = loc["Label"].strip()
    path = OUT / "domain_labels" / f"{lang}.tsv"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"# source={ATTRIBUTION}; Louw-Nida domain names\ncode\tlabel\n")
        for code in sorted(out):
            fh.write(f"{code}\t{out[code]}\n")
    print(f"  wrote {path.relative_to(ROOT)}: {len(out)} labels", file=sys.stderr)


def main() -> int:
    sys.path.insert(0, str(ROOT / "bcv-RAG"))
    from scripts.build_semantic_domains import _bridge_rows

    write(OUT / "grc.tsv", aggregate(senses(load("greek"), "G", sub_first=True), "sdbg"))
    hbo = aggregate(senses(load("hebrew"), "H", sub_first=False), "lex")
    bridge = _bridge_rows(str(OUT / "grc.tsv"), str(ROOT / "resources" / "lxx_bridge.tsv"))
    write(OUT / "hbo.tsv", hbo + bridge)
    for lang, key in LABEL_FILES.items():
        write_labels(lang, key)
    senses_dir = ROOT / "resources" / "senses"
    write_senses(senses_dir / "grc.tsv", sense_rows(load("greek"), "G"))
    write_senses(senses_dir / "hbo.tsv", sense_rows(load("hebrew"), "H"))
    write_relations(ROOT / "resources" / "lexical_relations" / "hbo.tsv", relation_rows(load("hebrew"), "H"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
