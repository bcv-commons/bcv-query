#!/usr/bin/env python3
"""Full-OT Strong's reconciliation: UHB vs BHSA (via the OpenHebrewBible crosswalk).

For each OT book, aligns the UHB content-Strong's sequence to BHSA's
content-Strong's sequence (BHSA gets Strong's from the `002` crosswalk
CSV) and reports the match rate + the residual (Strong's numbers that
don't line up). The residual feeds spine/strongs_equivalence.tsv.

Requires: cfabric + a local BHSA (the text-fabric corpus the bcv-RAG corpus
engine also uses), httpx. Point BHSA_LOC at your local text-fabric checkout if
it isn't at the default ~/text-fabric-data location.
"""
import csv
import os
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE / "reconciliation"
# Local BHSA text-fabric checkout. Defaults to the standard text-fabric path;
# override with BHSA_LOC for a non-default location.
BHSA_LOC = os.environ.get(
    "BHSA_LOC",
    str(Path.home() / "text-fabric-data/github/ETCBC/bhsa/tf/2021"),
)
CROSSWALK_URL = ("https://raw.githubusercontent.com/eliranwong/OpenHebrewBible/"
                 "master/002-BHS-with-Strong-no/BHS-with-Strong-no.csv")
# pinned to match the spine parser (see spine/common.py and docs/spine-parser.md)
UHB_URL = "https://git.door43.org/unfoldingWord/hbo_uhb/raw/tag/v2.1.32/{nn:02d}-{code}.usfm"

# BHSA (Hebrew-canon) order -> USFM file number in the UHB repo (Protestant numbering)
HEB_ORDER = ["GEN","EXO","LEV","NUM","DEU","JOS","JDG","1SA","2SA","1KI","2KI",
             "ISA","JER","EZK","HOS","JOL","AMO","OBA","JON","MIC","NAM","HAB",
             "ZEP","HAG","ZEC","MAL","PSA","JOB","PRO","RUT","SNG","ECC","LAM",
             "EST","DAN","EZR","NEH","1CH","2CH"]
FILENUM = {"GEN":1,"EXO":2,"LEV":3,"NUM":4,"DEU":5,"JOS":6,"JDG":7,"RUT":8,"1SA":9,
           "2SA":10,"1KI":11,"2KI":12,"1CH":13,"2CH":14,"EZR":15,"NEH":16,"EST":17,
           "JOB":18,"PSA":19,"PRO":20,"ECC":21,"SNG":22,"ISA":23,"JER":24,"LAM":25,
           "EZK":26,"DAN":27,"HOS":28,"JOL":29,"AMO":30,"OBA":31,"JON":32,"MIC":33,
           "NAM":34,"HAB":35,"ZEP":36,"HAG":37,"ZEC":38,"MAL":39}


def norm(s):
    m = re.search(r"[HG](\d+)", s or "")
    return int(m.group(1)) if m else None


def load_equivalences():
    eq = {}
    p = HERE / "strongs_equivalence.tsv"
    if not p.exists():
        return eq
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip() or line.startswith("uhb_strong"):
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            a, b = norm(parts[0]), norm(parts[1])
            if a and b:
                eq[a] = b
    return eq


def fetch_crosswalk():
    DATA.mkdir(parents=True, exist_ok=True)
    local = DATA / "BHS-with-Strong-no.csv"
    if not local.exists():
        print("downloading crosswalk...", file=sys.stderr)
        local.write_bytes(httpx.get(CROSSWALK_URL, timeout=120, follow_redirects=True).content)
    rows = []
    with open(local, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            rows.append(norm(row["StrongNo"]))   # content Strong's only (particles -> None)
    return rows  # global BHS-order sequence of Strong's (None for particles)


def bhsa_book_wordcounts():
    import cfabric
    CF = cfabric.Fabric(locations=BHSA_LOC, silent="deep")
    api = CF.loadAll(silent="deep")
    counts = []
    for b in api.F.otype.s("book"):
        counts.append(len(api.L.d(b, otype="word")))
    return counts  # in BHSA (Hebrew-canon) order, 39 entries


def uhb_book_strongs(code):
    t = httpx.get(UHB_URL.format(nn=FILENUM[code], code=code), timeout=120, follow_redirects=True).text
    out = []
    for m in re.finditer(r'\\w [^|]*\|[^\\]*?strong="([^"]+)"', t):
        s = norm(m.group(1).split(":")[-1])
        if s is not None:
            out.append(s)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    eq = load_equivalences()
    print("loading BHSA word counts...", file=sys.stderr)
    bcounts = bhsa_book_wordcounts()
    print("loading crosswalk...", file=sys.stderr)
    xwalk = fetch_crosswalk()

    per_book = []
    residual = Counter()
    pairs = Counter()      # (uhb_strong, bhsa_strong) substitutions -> equivalence candidates
    cur = 0
    for i, code in enumerate(HEB_ORDER):
        n = bcounts[i]
        bhsa_strong = [s for s in xwalk[cur:cur+n] if s is not None]
        cur += n
        uhb_strong = [eq.get(s, s) for s in uhb_book_strongs(code)]
        bhsa_eq = [eq.get(s, s) for s in bhsa_strong]
        sm = SequenceMatcher(None, uhb_strong, bhsa_eq, autojunk=False)
        matched = sum(b.size for b in sm.get_matching_blocks())
        per_book.append((code, len(uhb_strong), len(bhsa_eq), matched))
        for tag, a1, a2, b1, b2 in sm.get_opcodes():
            if tag in ("replace", "delete"):
                for j in range(b1, b2):
                    residual[bhsa_eq[j]] += 1
            if tag == "replace" and (a2-a1) == (b2-b1):   # clean 1:1 substitutions
                for u, b in zip(uhb_strong[a1:a2], bhsa_eq[b1:b2]):
                    pairs[(u, b)] += 1
        print(f"  {code}: {matched}/{len(bhsa_eq)} = {100*matched/max(1,len(bhsa_eq)):.1f}%", file=sys.stderr)

    # write outputs
    with open(OUT / "per_book.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["book", "uhb_strongs", "bhsa_strongs", "matched", "pct"])
        for code, u, b, m in per_book:
            w.writerow([code, u, b, m, f"{100*m/max(1,b):.2f}"])
    with open(OUT / "residual_strongs.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bhsa_strong", "unmatched_count"])
        for s, c in residual.most_common():
            w.writerow([f"H{s:04d}", c])
    with open(OUT / "residual_pairs.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["uhb_strong", "bhsa_strong", "count"])
        for (u, b), c in pairs.most_common():
            w.writerow([f"H{u:04d}", f"H{b:04d}", c])

    tot_b = sum(b for _, _, b, _ in per_book)
    tot_m = sum(m for _, _, _, m in per_book)
    print(f"\nOT TOTAL: {tot_m}/{tot_b} BHSA content-Strong's matched = {100*tot_m/tot_b:.2f}%")
    print(f"distinct residual Strong's: {len(residual)} | total residual words: {sum(residual.values())}")
    print(f"top residual: {residual.most_common(12)}")
    print(f"outputs in {OUT}/")


if __name__ == "__main__":
    main()
