"""A dated snapshot of the Hebrew Psalms commentaries used by hebrew-commentary-terms (P2), from Sefaria's API.

    cd shoresh && .venv/bin/python -m macula.fetch_sefaria_psalms [--works rashi,radak,...] [--date 2026-11-18]

One JSON file per work and psalm in macula/.cache/sefaria/<date>/<work>/<n>.json: Sefaria's v3 text response for the Hebrew
version(s). Resumable; about one request per 0.5 s. Only versions with an open licence (Public Domain, CC0, CC-BY, CC-BY-SA)
are used downstream; the licence is kept with each file.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKS = {"rashi": "Rashi on Psalms", "radak": "Radak on Psalms", "ibn_ezra": "Ibn Ezra on Psalms",
         "metzudat_david": "Metzudat David on Psalms", "meiri": "Meiri on Psalms", "malbim": "Malbim on Psalms",
         "midrash_tehillim": "Midrash Tehillim"}           # sections per psalm, not per verse
API = "https://www.sefaria.org/api/v3/texts/"


def get(ref: str) -> dict | None:
    url = API + urllib.parse.quote(ref) + "?version=hebrew%7Call"
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"user-agent": "bcv-query/1.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except Exception:
            time.sleep(min(2 ** attempt * 2, 30))
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--works", default=",".join(WORKS))
    ap.add_argument("--date", default="2026-11-18")
    a = ap.parse_args()
    for w in a.works.split(","):
        d = HERE / ".cache" / "sefaria" / a.date / w
        d.mkdir(parents=True, exist_ok=True)
        got = 0
        for n in range(1, 151):
            p = d / f"{n}.json"
            if p.exists() and p.stat().st_size > 50:
                continue
            r = get(f"{WORKS[w]}.{n}")
            if r is not None:
                p.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
                got += 1
            time.sleep(0.5)
        print(w, "fetched", got, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
