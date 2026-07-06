#!/usr/bin/env python3
"""Phase A of languages.db — build the code-keyed language REGISTRY for all ISO 639-3
languages from authoritative open datasets (see internal-docs/languages-db-design.md).

Superset of the hand-curated resources/related_langs/languages.tsv, keyed by the same
iso639_3. Fills the linguistic columns for every language:
  iso639_3  iso639_1  name  glottocode  stock  group  branch  scripts  macrolanguage
- iso639_3, iso639_1, name, macrolanguage  <- ISO 639-3 tables (SIL, free)
- glottocode, stock                        <- Glottolog CLDF (CC-BY-SA), joined on ISO code
- group / branch / scripts                 <- LEFT EMPTY here (Phase-A follow-ups:
    group/branch need the Glottolog classification path; scripts need CLDR languageData)

Also emits code_alias.tsv (retired ISO code -> current code) from the retirements table.

Availability-agnostic: this is PURE linguistics — no is_source/available/gloss_names columns
(those are served-language, derived data reconciled at cutover, Phase C). Writes to
resources/languages/ (the eventual home of languages.db), NOT the live related_langs/ registry.

  python -m scripts.build_languages_registry            # download (cached) + build
  python -m scripts.build_languages_registry --no-net   # build from the _raw/ cache only

Sources cached under resources/languages/_raw/ (gitignored); re-runs are offline.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "resources" / "languages"
RAW = OUT / "_raw"

SOURCES = {
    "iso6393.tab": "https://iso639-3.sil.org/sites/iso639-3/files/downloads/iso-639-3.tab",
    "iso_macro.tab": "https://iso639-3.sil.org/sites/iso639-3/files/downloads/iso-639-3-macrolanguages.tab",
    "iso_ret.tab": "https://iso639-3.sil.org/sites/iso639-3/files/downloads/iso-639-3_Retirements.tab",
    "glottolog.csv": "https://raw.githubusercontent.com/glottolog/glottolog-cldf/master/cldf/languages.csv",
    "glottolog_values.csv": "https://raw.githubusercontent.com/glottolog/glottolog-cldf/master/cldf/values.csv",
    "cldr_languagedata.json": "https://raw.githubusercontent.com/unicode-org/cldr-json/main/cldr-json/cldr-core/supplemental/languageData.json",
}


def _fetch(name: str, no_net: bool) -> Path:
    """Return the cached path for a source, downloading it if absent (unless --no-net)."""
    p = RAW / name
    if p.exists():
        return p
    if no_net:
        sys.exit(f"missing cached source {p} and --no-net set — run once online first")
    RAW.mkdir(parents=True, exist_ok=True)
    print(f"downloading {name} …", file=sys.stderr)
    r = httpx.get(SOURCES[name], timeout=120.0, follow_redirects=True)
    r.raise_for_status()
    p.write_bytes(r.content)
    return p


def _rows(path: Path, delim: str) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=delim))


def build(no_net: bool = False) -> None:
    iso = _rows(_fetch("iso6393.tab", no_net), "\t")
    macro = _rows(_fetch("iso_macro.tab", no_net), "\t")
    ret = _rows(_fetch("iso_ret.tab", no_net), "\t")
    glot = _rows(_fetch("glottolog.csv", no_net), ",")
    gvalues = _rows(_fetch("glottolog_values.csv", no_net), ",")
    cldr = json.loads(_fetch("cldr_languagedata.json", no_net).read_text(encoding="utf-8"))

    # individual language -> its macrolanguage code
    indiv_to_macro = {m["I_Id"]: m["M_Id"] for m in macro}

    # CLDR languageData: subtag -> [scripts]. Skip the -alt-secondary variants (primary only).
    cldr_scripts: dict[str, list[str]] = {}
    for subtag, info in cldr["supplemental"]["languageData"].items():
        if "-alt-" in subtag:
            continue
        scr = info.get("_scripts")
        if scr:
            cldr_scripts[subtag] = scr

    # Glottolog classification: glottocode -> path of ancestor glottocodes (stock ... parent).
    class_by_glotto = {v["Language_ID"]: v["Value"]
                       for v in gvalues if v["Parameter_ID"] == "classification" and v["Value"]}

    # Glottolog: ISO 639-3 code -> (glottocode, stock).  stock = the Family node's Name.
    # Prefer language-level nodes; fall back to dialect-level for ISO codes Glottolog only
    # carries as dialects (e.g. srp/hrv = Serbian/Croatian Standard, dialects of Serbo-Croatian).
    glot_by_id = {g["ID"]: g for g in glot}
    iso_to_glot: dict[str, tuple[str, str]] = {}
    for level in ("language", "dialect"):
        for g in glot:
            if g["Level"] != level:
                continue
            code = g["ISO639P3code"]
            if not code or code in iso_to_glot:
                continue
            fam = glot_by_id.get(g["Family_ID"])
            stock = fam["Name"] if fam else ("Isolate" if g.get("Is_Isolate") == "true" else "")
            iso_to_glot[code] = (g["Glottocode"], stock)

    # Glottolog keys INDIVIDUAL languages, not ISO macrolanguage codes, so a macro row
    # (ara, swa, …) has no direct stock. A macrolanguage's members share a family, so
    # inherit the stock from a member individual (first member that has one).
    macro_stock: dict[str, str] = {}
    for indiv, mac in indiv_to_macro.items():
        _, st = iso_to_glot.get(indiv, ("", ""))
        if st and mac not in macro_stock:
            macro_stock[mac] = st

    def gname(gc: str) -> str:
        row = glot_by_id.get(gc)
        return row["Name"] if row else ""

    # Registry rows: ISO 639-3 individual (I) + macrolanguage (M) scopes (skip Special).
    out_rows: list[dict] = []
    for r in iso:
        if r["Scope"] not in ("I", "M"):
            continue
        code = r["Id"]
        glottocode, stock = iso_to_glot.get(code, ("", ""))
        if not stock and r["Scope"] == "M":          # macrolanguage: inherit member stock
            stock = macro_stock.get(code, "")
        # group / branch = the two classification levels just below the stock (Glottolog path
        # = stock/group/branch/…/language). Depth varies; fill what the path has.
        path = class_by_glotto.get(glottocode, "").split("/") if glottocode else []
        group = gname(path[1]) if len(path) > 1 else ""
        branch = gname(path[2]) if len(path) > 2 else ""
        # scripts (ISO 15924) from CLDR languageData, keyed by 639-1 where present else 639-3.
        scr = cldr_scripts.get(r["Part1"]) or cldr_scripts.get(code) or []
        out_rows.append({
            "iso639_3": code,
            "iso639_1": r["Part1"],
            "name": r["Ref_Name"],
            "glottocode": glottocode,
            "stock": stock,
            "group": group,
            "branch": branch,
            "scripts": ",".join(scr),
            "macrolanguage": indiv_to_macro.get(code, ""),
            # full Glottolog ancestor path (glottocodes, stock→parent) — lets consumers rank
            # "nearest AVAILABLE" by shared-prefix tree distance, not just a fixed top-K.
            "classification": "/".join(path),
        })
    # CLDR keys scripts by the 639-1 macro code (zh/ar/sw); a member individual with no CLDR
    # entry of its own (cmn/arb/swh) inherits its macrolanguage's scripts.
    scripts_by_code = {r["iso639_3"]: r["scripts"] for r in out_rows if r["scripts"]}
    for r in out_rows:
        if not r["scripts"] and r["macrolanguage"]:
            r["scripts"] = scripts_by_code.get(r["macrolanguage"], "")

    out_rows.sort(key=lambda x: x["iso639_3"])

    # code_alias: retired code -> its single successor (skip splits with no one successor)
    aliases = [(r["Id"], r["Change_To"]) for r in ret if r.get("Change_To")]
    aliases.sort()

    OUT.mkdir(parents=True, exist_ok=True)
    cols = ["iso639_3", "iso639_1", "name", "glottocode", "stock", "group", "branch",
            "scripts", "macrolanguage", "classification"]
    with (OUT / "languages.tsv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter="\t")
        w.writeheader()
        w.writerows(out_rows)
    with (OUT / "code_alias.tsv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["old_code", "current_code"])
        w.writerows(aliases)

    def _n(col):
        return sum(1 for r in out_rows if r[col])
    print(f"languages.tsv: {len(out_rows)} languages "
          f"(glottocode={_n('glottocode')}, stock={_n('stock')}, group={_n('group')}, "
          f"branch={_n('branch')}, scripts={_n('scripts')})", file=sys.stderr)
    print(f"code_alias.tsv: {len(aliases)} retired→current mappings", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-net", action="store_true", help="build from the _raw/ cache only")
    build(ap.parse_args().no_net)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
