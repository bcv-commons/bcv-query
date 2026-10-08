"""Convert a verse reference between numbering schemes, so the service can answer in the reader's own numbering.

Built ONLY on what the bibles project publishes at cdn.bibel.wiki (doc/vrs-maps.md, doc/vrs-index.md, doc/scheme-manifest.md in bcv-commons/bibles):

  _vrs/<scheme>.vrs                      the shape of a scheme: last verse of every chapter
  _vrs/map/<scheme>-to-eng.json          verse-precise crosswalk to English (TVTMS, CC BY); only differing verses are listed
  _vrs/map/<scheme>-to-eng.multiverse.json   relations between verse RANGES (Hebrew Num 25:19-26:1 = English 26:1, Synodal Ps 12:6 = English 13:5-6)
  dbt/_vrs/index.json                    the schemes, and the scheme of every classified edition (language -> scheme comes from here)

English is the hub: scheme A -> English -> scheme B. A reference is converted in four steps:
  1. a multi-verse relation, if the verse is part of one (ranges are expanded with the .vrs shapes);
  2. the verse's own row in the map;
  3. the GAP RULE of vrs-maps.md: a verse that keeps its number but changes chapter at a merge/split point has no row; it belongs to the target chapter of the
     rows on both sides of it (rso 114:9 sits between rows ending in English 116:8 and 116:10, so it is English 116:9);
  4. otherwise it keeps its reference.
A Psalm title is verse 0 in English, so a title that spans two Hebrew verses (Ps 51:1-2) is one English verse 0 and converts back to both.

Files are read from VERSIFICATION_MAP_DIR (default /data/vrs, then ./data/vrs next to this file), fetched from the CDN when missing and cached there with their ETag.
Each file is revalidated at most once a day with a conditional request: unchanged files answer 304 (a few hundred bytes), only a changed file is downloaded again and
the converted tables are rebuilt. Nothing is hard-coded: any scheme listed in the index works, and an unknown scheme is an error, not a guess.

  from vrsmap import convert
  convert(("PSA", 3, 1), "eng", "org")   # -> [("PSA", 3, 2)]
  convert(("PSA", 51, 0), "eng", "org")  # -> [("PSA", 51, 1), ("PSA", 51, 2)]
"""
from __future__ import annotations

import bisect
import collections
import csv
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path

Ref = tuple[str, int, int]
BASE = os.environ.get("VERSIFICATION_BASE", "https://cdn.bibel.wiki").rstrip("/")
HERE = Path(__file__).resolve().parent
HUB = "eng"
_REF = re.compile(r"^([A-Z0-9]{3}) (\d+):(\d+|title)$")
_RANGE = re.compile(r"^([A-Z0-9]{3}) (\d+):(\d+|title)(?:-(?:(\d+):)?(\d+))?$")
_SCHEME = re.compile(r"^[a-z][a-z0-9_]{1,15}$")
_lock = threading.Lock()
_failed: dict[str, float] = {}           # file name -> time of a failed fetch (retry later)
_RETRY = 600
_MAX_AGE = 86400                          # every cached file is revalidated at most daily (a 304 when nothing changed)


class UnknownScheme(ValueError):
    """The scheme is not one bibles publishes."""


# ---------------------------------------------------------------- files
def _dirs() -> list[Path]:
    env = os.environ.get("VERSIFICATION_MAP_DIR")
    return [Path(env)] if env else [Path("/data/vrs"), HERE / "data" / "vrs"]


def _path(name: str) -> Path | None:
    for d in _dirs():
        if (d / name).exists():
            return d / name
    return None


_changed = threading.Event()             # set when a revalidation brought different bytes: cached tables must be rebuilt


def _fetch(name: str, url: str, etag: str | None = None) -> tuple[bytes | None, str | None]:
    """(bytes, etag) of a changed or new file; (None, etag) when the CDN says 304 Not Modified; (None, None) when it cannot be reached."""
    with _lock:
        t0 = _failed.get(name)
        if t0 is not None and time.time() - t0 < _RETRY:
            return None, None
    headers = {"User-Agent": "bcv-query"}
    if etag:
        headers["If-None-Match"] = etag
    try:
        resp = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=8)
        raw, new_etag = resp.read(), resp.headers.get("ETag")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return None, etag
        with _lock:
            _failed[name] = time.time()
        return None, None
    except Exception:                                        # noqa: BLE001 - offline, DNS, ...: "not available"
        with _lock:
            _failed[name] = time.time()
        return None, None
    for d in _dirs():                                        # cache where we can write
        try:
            d.mkdir(parents=True, exist_ok=True)
            (d / name).write_bytes(raw)
            (d / (name + ".etag")).write_text(new_etag or "", encoding="utf-8")
            break
        except OSError:
            continue
    return raw, new_etag


def _bytes(name: str, url: str, *, optional: bool = False, max_age: float | None = None) -> bytes | None:
    """The file's bytes. A cached copy older than max_age is revalidated with a conditional request (ETag): unchanged files cost a 304, only
    changed files are downloaded again. Without max_age a cached copy is used as is."""
    p = _path(name)
    if p is not None and (max_age is None or time.time() - p.stat().st_mtime < max_age):
        return p.read_bytes()
    etag = None
    if p is not None:
        try:
            etag = (p.parent / (p.name + ".etag")).read_text(encoding="utf-8").strip() or None
        except OSError:
            pass
    raw, _ = _fetch(name, url, etag if p is not None else None)
    if raw is not None:
        _changed.set()
        return raw
    if p is not None:                                        # 304, or unreachable: keep the copy and restart its age
        try:
            os.utime(p)
        except OSError:
            pass
        return p.read_bytes()
    if optional:
        return None
    raise UnknownScheme(name)


# ---------------------------------------------------------------- the index: schemes and editions
@lru_cache(maxsize=1)
def _index_cached(bucket: int) -> dict:
    raw = _bytes("index.json", f"{BASE}/dbt/_vrs/index.json", optional=True, max_age=_MAX_AGE)
    if raw is None:
        return {"schemes": [], "l": {}, "vrs_base": f"{BASE}/_vrs/", "map_base": f"{BASE}/_vrs/map/", "maps": []}
    return json.loads(raw)


def index() -> dict:
    """The edition/scheme index, revalidated daily. When the CDN served anything new (the index or a file it lists), the parsed tables are rebuilt."""
    idx = _index_cached(int(time.time() // 86400))
    if _changed.is_set():
        _changed.clear()
        table.cache_clear(); shape.cache_clear()
    return idx


def schemes() -> list[str]:
    """The numbering schemes bibles publishes (always includes the English hub)."""
    s = list(index().get("schemes") or [])
    return s if HUB in s or not s else s + [HUB]


def _urls(index_: dict) -> tuple[str, str]:
    return index_.get("vrs_base") or f"{BASE}/_vrs/", index_.get("map_base") or f"{BASE}/_vrs/map/"


# ---------------------------------------------------------------- shapes (.vrs)
def parse_vrs(text: str) -> dict[tuple[str, int], int]:
    """{(book, chapter): last verse} from a .vrs file: lines like `GEN 1:31 2:25 ...`; comments (#) and mapping lines (=) are skipped."""
    out: dict[tuple[str, int], int] = {}
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" in ln or ln.startswith("-"):
            continue
        parts = ln.split()
        if not re.fullmatch(r"[A-Z0-9]{3}", parts[0]):
            continue
        for tok in parts[1:]:
            m = re.fullmatch(r"(\d+):(\d+)", tok)
            if m:
                out[(parts[0], int(m.group(1)))] = int(m.group(2))
    return out


@lru_cache(maxsize=16)
def shape(scheme: str) -> dict[tuple[str, int], int]:
    vrs_base, _ = _urls(index())
    return parse_vrs(_bytes(f"{scheme}.vrs", f"{vrs_base}{scheme}.vrs", max_age=_MAX_AGE).decode("utf-8"))


# ---------------------------------------------------------------- references and ranges
def _ref(s: str) -> Ref:
    m = _REF.match(s)
    if not m:
        raise ValueError(f"unparsable reference in a versification map: {s!r}")
    return m.group(1), int(m.group(2)), 0 if m.group(3) == "title" else int(m.group(3))


def expand(rng: str, sh: dict[tuple[str, int], int]) -> list[Ref]:
    """'PSA 13:5-6' -> [13:5, 13:6]; 'NUM 25:19-26:1' -> 25:19 .. last verse of 25, then 26:1; a single verse stays a single verse."""
    m = _RANGE.match(rng)
    if not m:
        raise ValueError(f"unparsable range in a versification map: {rng!r}")
    book, c1, v1 = m.group(1), int(m.group(2)), (0 if m.group(3) == "title" else int(m.group(3)))
    if m.group(5) is None:
        return [(book, c1, v1)]
    c2, v2 = (int(m.group(4)) if m.group(4) else c1), int(m.group(5))
    out: list[Ref] = []
    c, v = c1, v1
    while (c, v) <= (c2, v2) and len(out) < 400:
        out.append((book, c, v))
        last = sh.get((book, c))
        if last is not None and v >= last and (c, v) < (c2, v2):
            c, v = c + 1, 1
        else:
            v += 1
    return out


# ---------------------------------------------------------------- one scheme's table
class Table:
    """fwd: every verse of the scheme -> English verse(s); inv: English verse -> scheme verse(s)."""
    def __init__(self, scheme: str, fwd: dict, inv: dict, rev: str | None, notes: dict):
        self.scheme, self.fwd, self.inv, self.rev, self.notes = scheme, fwd, inv, rev, notes


def _gap_target(r: Ref, rows: list[tuple[tuple[int, int], Ref]], taken: set[Ref]) -> Ref | None:
    """The gap rule (doc/vrs-maps.md): r has no row. If the nearest rows before and after it (in r's chapter, or the next one) both map into one
    OTHER chapter, r keeps its verse number in that chapter, provided no row already claims that target."""
    b, c, v = r
    keys = [k for k, _ in rows]
    i = bisect.bisect_left(keys, (c, v))
    if i == 0 or i >= len(rows):
        return None
    (pc, _pv), pt = rows[i - 1]
    (nc, _nv), nt = rows[i]
    if pc == c and nc in (c, c + 1) and pt[0] == nt[0] == b and pt[1] == nt[1] != c:
        tgt = (b, pt[1], v)
        if tgt not in taken:
            return tgt
    return None


@lru_cache(maxsize=16)
def table(scheme: str) -> Table:
    if scheme == HUB:
        return Table(HUB, {}, {}, None, {"hub": True})
    if not _SCHEME.match(scheme) or scheme not in schemes():
        raise UnknownScheme(scheme)
    _, map_base = _urls(index())
    sh = shape(scheme)
    eng_sh = shape(HUB)
    data = json.loads(_bytes(f"{scheme}-to-eng.json", f"{map_base}{scheme}-to-eng.json", max_age=_MAX_AGE).decode("utf-8"))
    explicit: dict[Ref, list[Ref]] = {}
    for r in data.get("map", []):
        explicit.setdefault(_ref(r["s"]), []).append(_ref(r["t"]))
    multi: dict[Ref, list[Ref]] = {}
    mraw = _bytes(f"{scheme}-to-eng.multiverse.json", f"{map_base}{scheme}-to-eng.multiverse.json", optional=True, max_age=_MAX_AGE)
    n_multi = 0
    if mraw:
        for r in json.loads(mraw.decode("utf-8")).get("map", []):
            src, tgt = expand(r["s"], sh), expand(r["t"], eng_sh)
            n_multi += 1
            for s in src:
                multi[s] = tgt
    by_book: dict[str, list] = collections.defaultdict(list)
    for s, ts in explicit.items():
        by_book[s[0]].append(((s[1], s[2]), ts[0]))
    for rows in by_book.values():
        rows.sort()
    fwd: dict[Ref, list[Ref]] = {}
    pending: list[Ref] = []
    for (b, c), last in sh.items():
        for v in range(1, last + 1):
            r = (b, c, v)
            if r in multi:
                fwd[r] = list(multi[r])
            elif r in explicit:
                fwd[r] = list(explicit[r])
            else:
                fwd[r] = [r]
                pending.append(r)
    # the gap rule, second pass: only where no other verse already lands on the target (so it can never create a collision)
    landed = collections.Counter(t for r, ts in fwd.items() for t in ts)
    gap = 0
    for r in pending:
        g = _gap_target(r, by_book.get(r[0], []), set())
        if g is not None and landed[g] == 0 and g != r:
            landed[r] -= 1; landed[g] += 1
            fwd[r] = [g]; gap += 1
    for s, ts in explicit.items():                          # rows for verses outside the shape are kept as published
        fwd.setdefault(s, list(ts))
    inv: dict[Ref, list[Ref]] = {}
    for s, ts in fwd.items():
        for t in ts:
            inv.setdefault(t, []).append(s)
    for v in inv.values():
        v.sort()
    return Table(scheme, fwd, inv, data.get("tvtms_rev"), {"rows": len(explicit), "multiverse": n_multi, "gap_filled": gap})


def available(scheme: str) -> bool:
    try:
        table(scheme)
        return True
    except UnknownScheme:
        return False


# ---------------------------------------------------------------- conversion
def to_eng(ref: Ref, scheme: str) -> list[Ref]:
    if scheme == HUB:
        return [ref]
    return list(table(scheme).fwd.get(ref, [ref]))


def from_eng(ref: Ref, scheme: str) -> list[Ref]:
    if scheme == HUB:
        return [ref]
    return list(table(scheme).inv.get(ref, [ref]))


def convert(ref: Ref, src: str, dst: str) -> list[Ref]:
    """The verse(s) of scheme `dst` that are the verse `ref` of scheme `src` (usually one; a Psalm title can be two Hebrew verses)."""
    if src == dst:
        return [ref]
    out: list[Ref] = []
    for e in to_eng(ref, src):
        for r in from_eng(e, dst):
            if r not in out:
                out.append(r)
    return out


def revision(scheme: str) -> str | None:
    return None if scheme == HUB else table(scheme).rev


def fmt(ref: Ref) -> str:
    return f"{ref[0]} {ref[1]}:{ref[2] if ref[2] else 'title'}"


# ---------------------------------------------------------------- the reader's language -> scheme (from bibles' edition index)
@lru_cache(maxsize=1)
def _iso_table() -> dict[str, str]:
    """ISO 639-1 -> 639-3 (and 639-3 -> itself) from resources/related_langs/languages.tsv."""
    out: dict[str, str] = {}
    for base in (os.environ.get("BCV_RESOURCES_DIR"), "/app/resources", str(HERE.parent / "resources")):
        p = Path(base or "") / "related_langs" / "languages.tsv"
        if p.exists():
            with p.open(encoding="utf-8") as fh:
                for row in csv.DictReader(fh, delimiter="\t"):
                    i3, i1 = (row.get("iso639_3") or "").strip().lower(), (row.get("iso639_1") or "").strip().lower()
                    if i3:
                        out[i3] = i3
                        if i1:
                            out[i1] = i3
            break
    return out


def iso3(code: str | None) -> str | None:
    c = (code or "").strip().lower().split("-")[0].split("_")[0]
    if not c:
        return None
    return _iso_table().get(c) or (c if len(c) == 3 else None)


def scheme_for_language(code: str | None) -> dict | None:
    """The numbering scheme editions of this language use, from bibles' classification of 231 DBT editions in 149 languages:
    {scheme, editions, agreement, counts}; None when no classified edition of the language exists (then the caller must say it assumed)."""
    i3 = iso3(code)
    if not i3:
        return None
    counts = collections.Counter(v for k, v in (index().get("l") or {}).items() if k.split("/")[0] == i3 and "/" in k and v != "undetermined")
    if not counts:
        return None
    scheme, n = counts.most_common(1)[0]
    return {"scheme": scheme, "editions": sum(counts.values()), "agreement": round(n / sum(counts.values()), 2), "counts": dict(counts)}


# ---------------------------------------------------------------- self-check against the published shapes
def check(scheme: str) -> dict:
    """Does the scheme's table agree with the published shapes? Every verse of the scheme must map into the English shape (or be its title);
    verses sharing one English verse (collisions) and English verses nobody maps to (unreached) are reported, excluding titles."""
    t, eng_sh, sh = table(scheme), shape(HUB), shape(scheme)
    outside, hits = [], collections.defaultdict(set)
    for r, ts in t.fwd.items():
        for e in ts:
            if e[2] == 0:
                continue
            if e[2] > eng_sh.get((e[0], e[1]), 0):
                outside.append((r, e))
            hits[e].add(r)
    books = {b for b, _ in sh}
    collisions = {e: sorted(s) for e, s in hits.items() if len(s) > 1}
    unreached = [(b, c, v) for (b, c), last in eng_sh.items() if b in books for v in range(1, last + 1) if (b, c, v) not in hits]
    return {"verses": len(t.fwd), "outside_english": outside, "collisions": collisions, "unreached": unreached, "notes": t.notes}
