"""A dated snapshot of the Overview pages of Psalms: Layer by Layer (Scriptura, https://psalms.scriptura.org, CC BY 4.0).

Run by a person, deliberately, once per snapshot (not part of any build):

    cd shoresh && .venv/bin/python -m macula.fetch_scriptura            # all 150 psalms, about 75 minutes
    cd shoresh && .venv/bin/python -m macula.fetch_scriptura --psalms 3 23 88

It reads robots.txt first and keeps to it: only pages robots.txt allows, one request at a time, waiting its Crawl-delay (30 s
today) between requests. Pages are saved as they come (raw HTML, nothing parsed) in macula/.cache/scriptura/<date>/, with
manifest.tsv (psalm, url, HTTP status, bytes, sha256, time). A rerun into the same folder skips psalms already saved, so it can be
stopped and resumed. Parsing is a separate step (passage facts read the saved files; nothing here goes into a dataset by itself).

Attribution for anything built from it: "Psalms: Layer by Layer, Scriptura (psalms.scriptura.org), CC BY 4.0", with the snapshot
date.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from pathlib import Path

BASE = "https://psalms.scriptura.org"
PAGE = BASE + "/w/Psalm_{n}/Overview"
AGENT = "bcv-commons-snapshot/0.1 (one-off dated snapshot of public pages; CC BY 4.0 attribution kept)"
CACHE = Path(__file__).resolve().parent / ".cache" / "scriptura"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--psalms", type=int, nargs="*", default=list(range(1, 151)))
    ap.add_argument("--out", type=Path, default=CACHE / dt.date.today().isoformat())
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    robots = urllib.robotparser.RobotFileParser(BASE + "/robots.txt")
    robots.read()
    delay = max(30.0, float(robots.crawl_delay(AGENT) or robots.crawl_delay("*") or 0))
    manifest = a.out / "manifest.tsv"
    if not manifest.exists():
        manifest.write_text("psalm\turl\tstatus\tbytes\tsha256\tfetched\n", encoding="utf-8")
    done = {int(l.split("\t")[0]) for l in manifest.read_text(encoding="utf-8").splitlines()[1:] if l.strip()}
    todo = [n for n in a.psalms if n not in done]
    print(f"{len(todo)} pages to fetch, {delay:.0f} s apart (about {len(todo) * delay / 60:.0f} min) -> {a.out}", file=sys.stderr)

    for k, n in enumerate(todo):
        url = PAGE.format(n=n)
        if not robots.can_fetch(AGENT, url):
            print(f"Ps {n}: robots.txt disallows {url}; stopping", file=sys.stderr)
            return 1
        if k:
            time.sleep(delay)
        req = urllib.request.Request(url, headers={"User-Agent": AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                status, body = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read() or b""
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"Ps {n}: {e}; stopping (rerun to resume)", file=sys.stderr)
            return 1
        if status == 429 or status >= 500:
            print(f"Ps {n}: HTTP {status}; stopping (rerun later to resume)", file=sys.stderr)
            return 1
        (a.out / f"psalm_{n:03d}.html").write_bytes(body)
        with manifest.open("a", encoding="utf-8") as f:
            f.write(f"{n}\t{url}\t{status}\t{len(body)}\t{hashlib.sha256(body).hexdigest()}\t"
                    f"{dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}\n")
        print(f"Ps {n}: {status}, {len(body):,} bytes", file=sys.stderr)
    print("done", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
