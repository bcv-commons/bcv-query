"""Fetch a Hebrew NT edition's chapters for `macula.clause_tagger export`, by the route bcv-commons/bibles names for it.

    python -m macula.fetch_hebrew_nt --edition heb_mod [--out macula/data/helloao/heb_mod]

All Bible text comes from bcv-commons/bibles. Its catalog (cdn.bibel.wiki/catalog/h/heb/text-route.json) gives the reading route of
each edition; for the Hebrew NTs we publish an analysis of (`h:heb_scg` Salkinson-Ginsburg, `h:heb_mod` Delitzsch as eBible's
"Modern Hebrew Bible" has it) the route is `helloao`: helloAO's chapter JSON, read with bibles' verse-text rule (vendor_bibles).
This script refuses an edition whose route is another one. It writes <BOOK>_<chapter>.json, as export reads them, and fetch.json
with the catalog entry, the date and the sha256 of every chapter file. Only the 27 NT books are fetched.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG = "https://cdn.bibel.wiki/catalog/h/heb/"
API = "https://bible.helloao.org/api/"
NT = ["MAT", "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL", "EPH", "PHP", "COL", "1TH", "2TH", "1TI", "2TI", "TIT", "PHM", "HEB",
      "JAS", "1PE", "2PE", "1JN", "2JN", "3JN", "JUD", "REV"]


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "bcv-tools/1.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 + 3 * attempt)
    raise AssertionError


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--edition", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    out = Path(a.out) if a.out else HERE / "data" / "helloao" / a.edition
    route = json.loads(get(CATALOG + "text-route.json"))["entries"]["heb:nt"].get(f"h:{a.edition}")
    if not route or route.get("route") != "helloao":
        raise SystemExit(f"h:{a.edition}: bibles' catalog gives no helloao route for it ({route})")
    struct = json.loads(get(CATALOG + "edition-struct.json"))["editions"].get(f"h:{a.edition}", {})
    books = {b["id"]: b for b in json.loads(get(f"{API}{a.edition}/books.json"))["books"]}
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for b in NT:
        if b not in books:
            raise SystemExit(f"{a.edition}: no {b}")
        for ch in range(1, books[b]["numberOfChapters"] + 1):
            data = get(f"{API}{a.edition}/{b}/{ch}.json")
            json.loads(data)
            (out / f"{b}_{ch}.json").write_bytes(data)
            files[f"{b}_{ch}.json"] = hashlib.sha256(data).hexdigest()
        print(f"[fetch_hebrew_nt] {a.edition} {b}: {books[b]['numberOfChapters']} chapters", flush=True)
    (out / "fetch.json").write_text(json.dumps({"edition": a.edition, "catalog": CATALOG, "route": route, "edition_struct": struct,
                                                "fetched": datetime.date.today().isoformat(), "files": files}, ensure_ascii=False, indent=1) + "\n")
    print(f"[fetch_hebrew_nt] {len(files)} chapters -> {out}")


if __name__ == "__main__":
    main()
