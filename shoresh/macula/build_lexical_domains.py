"""Package bcv-commons/lexical-domains (M6): the UBS meaning-domain trees as codes, joined to MACULA words. Nothing is uploaded.

    cd shoresh && .venv/bin/python -m macula.build_lexical_domains --tag v0.1 --out DIR [--allow-dirty]

Trees: SDBH lexical domains (UBS Dictionary of Biblical Hebrew v0.9.3, 3-digit segments, 419 codes) and Louw-Nida domains and
subdomains (UBS Dictionary of the Greek NT v1.1, 738 codes), both from github.com/ubsicap/ubs-open-license at the commit pinned
in build_ubs_open.py. Words: bcv-commons/word-senses v0.1 (a MACULA word's UBS sense and its domain codes).
No English: the domain names stay in UBS's files (looked up by code); this dataset carries codes, the tree, counts and the
Hebrew and Greek lemmas found in each domain.

OUT gets data/domains.parquet, data/word_domains.parquet, README.md (lexical_domains_card.md), build.json, SHA256SUMS.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sqlite3
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORD_SENSES = ("v0.1", "00690ee3", ROOT / "internal-docs" / "word-senses-release" / "v0.1" / "data" / "words.parquet")
SPINE = HERE / "macula-spine.db"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def parent(system: str, code: str) -> str | None:
    """SDBH: drop the last 3-digit segment; Louw-Nida: a 6-digit subdomain's parent is its 3-digit domain."""
    return code[:-3] or None if len(code) > 3 else None


def trees() -> dict[tuple[str, str], dict]:
    from macula import build_ubs_open as U
    out = {}
    for system, key in (("sdbh", "hebrew_dom"), ("ln", "greek_dom_en")):
        for d in U.load(key):
            out[system, d["Code"]] = {"system": system, "code": d["Code"], "parent": parent(system, d["Code"]),
                                      "level": int(d["Level"]), "ubs_flag": bool(d["HasSubDomains"])}
    kids = collections.Counter((k[0], v["parent"]) for k, v in out.items() if v["parent"])
    for k, v in out.items():                       # from the tree: UBS's HasSubDomains is wrong for 3 SDBH codes (v0.9.3)
        v["has_subdomains"] = kids[k] > 0
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    import pyarrow as pa
    import pyarrow.parquet as pq
    from macula import build_ubs_open as U
    code = [HERE / "build_lexical_domains.py", HERE / "lexical_domains_card.md", HERE / "build_ubs_open.py"]
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *map(str, code)], cwd=ROOT, capture_output=True, text=True).stdout
    if dirty.strip() and not a.allow_dirty:
        raise SystemExit("uncommitted changes; commit first (or --allow-dirty):\n" + dirty)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    commit += " (dirty)" if dirty.strip() else ""
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; use a new folder")

    dom = trees()
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    lemma = {k: (l, s) for k, l, s in sp.execute("SELECT key, lemma, strong FROM macula_words")}
    st = collections.Counter()
    wd, senses = [], collections.defaultdict(set)
    direct = collections.Counter()
    lem = collections.defaultdict(collections.Counter)
    for r in pq.read_table(WORD_SENSES[2], columns=["key", "lang", "sense", "domains", "subdomains"]).to_pylist():
        if not r["sense"]:
            continue
        system = "sdbh" if r["lang"] == "hbo" else "ln"
        raw = (r["subdomains"] or r["domains"] or "") if system == "ln" else (r["domains"] or "")
        codes = sorted({x for c in raw.split() for x in c.split(";") if x})      # an SDBH "a;b" is two domains
        for c in codes:
            if (system, c) not in dom:
                st[system, "code_not_in_tree"] += 1
                continue
            wd.append({"key": r["key"], "lang": r["lang"], "system": system, "code": c, "sense": r["sense"]})
            direct[system, c] += 1
            senses[system, c].add(r["sense"])
            l, s = lemma.get(r["key"].lstrip("n"), (None, None))
            node = c
            while node:
                lem[system, node][(l or "", s or "")] += 1
                node = dom[system, node]["parent"] if (system, node) in dom else None
        st[system, "words"] += 1
    total = collections.Counter()
    for (system, c), n in direct.items():
        node = c
        while node and (system, node) in dom:
            total[system, node] += n
            node = dom[system, node]["parent"]
    rows = []
    for k in sorted(dom):
        d = dom[k]
        rows.append({**d, "senses": len(senses[k]), "words": direct[k], "words_with_narrower": total[k],
                     "lemmas": [{"lemma": l, "strong": s, "words": n} for (l, s), n in lem[k].most_common(12)]})
    for r in rows:
        st[r["system"], "domains"] += 1
        st[r["system"], "domains_used"] += r["words_with_narrower"] > 0
    bad_parent = sum(1 for r in rows if r["parent"] and (r["system"], r["parent"]) not in dom)
    flag_wrong = [f"{r['system']}:{r['code']}" for r in rows if r.pop("ubs_flag") != r["has_subdomains"]]

    (a.out / "data").mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows), a.out / "data" / "domains.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(wd), a.out / "data" / "word_domains.parquet", compression="zstd")
    counts = {f"{k[0]} {k[1]}": v for k, v in sorted(st.items())}
    build = {"tag": a.tag, "code": commit, "ubs_commit": U.COMMIT, "word_senses": {"version": WORD_SENSES[0], "revision": WORD_SENSES[1]},
             "counts": counts, "word_domain_rows": len(wd), "parents_missing": bad_parent,
             "ubs_has_subdomains_flag_wrong": flag_wrong}
    (a.out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1), encoding="utf-8")
    card = (HERE / "lexical_domains_card.md").read_text(encoding="utf-8")
    vals = {"@TAG@": a.tag, "@CODE@": commit, "@UBS@": U.COMMIT[:12], "@WS@": WORD_SENSES[1],
            "@SDBH@": st["sdbh", "domains"], "@SDBH_USED@": st["sdbh", "domains_used"], "@LN@": st["ln", "domains"],
            "@LN_USED@": st["ln", "domains_used"], "@HBO_WORDS@": f"{st['sdbh', 'words']:,}", "@GRC_WORDS@": f"{st['ln', 'words']:,}",
            "@ROWS@": f"{len(wd):,}"}
    for k, v in vals.items():
        card = card.replace(k, str(v))
    if re.findall(r"@[A-Z_]+@", card):
        raise SystemExit(f"unfilled card fields: {re.findall(r'@[A-Z_]+@', card)}")
    (a.out / "README.md").write_text(card, encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (a.out / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(a.out)}\n" for p in files))
    print(json.dumps(build, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
