"""Strategy 2: LXX bridge expansion — Hebrew Strong's → Greek Strong's.

When concept expansion (Strategy 1) produces Hebrew Strong's tags, this
calls shoresh `/bridge/{strong}` to find the top Greek translations via
the Septuagint, and adds those as additional `strongs:` tags.

Effect: an OT Hebrew concept like H2617 (chesed) automatically expands
to G1656 (eleos/mercy) — its LXX translation — so NT content tagged with
the Greek equivalent surfaces alongside OT results.

The bridge is STATIC, so it is precomputed into resources/lxx_bridge.tsv
(scripts/build_lxx_bridge.py) and read locally — ZERO network on the hot path.
shoresh is only contacted as a dev fallback when that table is absent.

Two guards keep this on-signal:
  • Frequency skip: maximally-frequent Hebrew lemmas (H0430 "God", H3068
    "LORD", …) bridge only to GENERIC Greek (G2316 theos) — noise, not
    signal — so we skip any Hebrew code whose spine frequency ≥
    LXX_BRIDGE_MAX_FREQ (also why the precomputed table omits them). See
    resources/strongs_freq.tsv.
  • In-process cache on the network fallback: bridge results are static, so
    each code is fetched at most once per process (failures are NOT cached).

Only fires when Hebrew Strong's tags are present.
"""
from __future__ import annotations

import logging
import os
import re
from threading import Lock

import httpx

from resource_paths import resource_path

logger = logging.getLogger("bcv-rag.lxx_expand")

SHORESH_URL = os.environ.get("SHORESH_URL", "").rstrip("/")

# Skip the LXX bridge for Hebrew lemmas at/above this spine frequency. Default
# 1500 skips the generic high-frequency nouns (God 2598, LORD 6827, son, land,
# day, king, …) whose LXX renderings are generic, while keeping mid-frequency
# theological terms (chesed 247 → mercy). Env-tunable.
LXX_BRIDGE_MAX_FREQ = int(os.environ.get("LXX_BRIDGE_MAX_FREQ", "1500"))

_FREQ_PATH = resource_path("strongs_freq.tsv")
_TABLE_PATH = resource_path("lxx_bridge.tsv")

# Static bridge results, cached per Hebrew code for the process lifetime.
# Only successful fetches are stored, so a transient shoresh hiccup isn't
# remembered. Guarded by a lock for the (rare) concurrent first-fetch.
_bridge_cache: dict[str, tuple[tuple[str, int], ...]] = {}
_bridge_lock = Lock()
_freq_cache: dict[str, int] | None = None
_table_cache: dict[str, tuple[tuple[str, int], ...]] | None = None


def _normalize_code(code: str) -> str:
    m = re.match(r"^([HG])(\d+)$", code)
    if not m:
        return code
    return f"{m.group(1)}{int(m.group(2)):04d}"


def _hebrew_freq() -> dict[str, int]:
    """Padded Hebrew code → spine frequency, from strongs_freq.tsv (lazy)."""
    global _freq_cache
    if _freq_cache is not None:
        return _freq_cache
    freq: dict[str, int] = {}
    if _FREQ_PATH.exists():
        with _FREQ_PATH.open(encoding="utf-8") as fh:
            next(fh, None)  # header
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2 and parts[0].startswith("H"):
                    try:
                        freq[_normalize_code(parts[0])] = int(parts[1])
                    except ValueError:
                        continue
    _freq_cache = freq
    return freq


def _bridge_table() -> dict[str, tuple[tuple[str, int], ...]]:
    """Padded Hebrew code → `(greek, count)` pairs, from the precomputed
    resources/lxx_bridge.tsv (lazy). Empty dict if the table is absent."""
    global _table_cache
    if _table_cache is not None:
        return _table_cache
    tbl: dict[str, list[tuple[str, int]]] = {}
    if _TABLE_PATH.exists():
        with _TABLE_PATH.open(encoding="utf-8") as fh:
            next(fh, None)  # header
            for line in fh:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 3:
                    try:
                        tbl.setdefault(_normalize_code(p[0]), []).append(
                            (_normalize_code(p[1]), int(p[2])))
                    except ValueError:
                        continue
    _table_cache = {h: tuple(v) for h, v in tbl.items()}
    return _table_cache


def _bridge_for(padded: str) -> tuple[tuple[str, int], ...]:
    """`(greek, count)` pairs for a Hebrew code. Prefers the precomputed local
    table (no network); falls back to live shoresh only when the table is
    absent (dev)."""
    table = _bridge_table()
    if table:
        return table.get(padded, ())
    return _fetch_bridge(padded)


def _fetch_bridge(padded: str) -> tuple[tuple[str, int], ...]:
    """`(greek_strong, count)` pairs for a padded Hebrew code, via shoresh.

    Cached for the process lifetime; failures return () and are NOT cached."""
    if not SHORESH_URL:
        return ()
    cached = _bridge_cache.get(padded)
    if cached is not None:
        return cached
    url_code = re.sub(r"^H0*", "H", padded)  # shoresh wants H430, not H0430
    try:
        resp = httpx.get(f"{SHORESH_URL}/bridge/{url_code}", timeout=5.0)
        if resp.status_code != 200:
            return ()
        translations = resp.json().get("greek_translations", [])
    except Exception as e:
        logger.debug("LXX bridge fetch failed for %s: %s", padded, e)
        return ()
    result = tuple((t.get("greek_strong", ""), int(t.get("count", 0)))
                   for t in translations)
    with _bridge_lock:
        _bridge_cache[padded] = result
    return result


def expand_lxx(tags: list[str], max_greek_per_hebrew: int = 2,
               max_total: int = 4) -> list[str]:
    """Given existing tags, find Hebrew Strong's and expand via LXX bridge."""
    h_tags = [t for t in tags if t.startswith("strongs:H")]
    if not h_tags:
        return []

    freq = _hebrew_freq()
    existing = set(tags)
    new_tags: list[str] = []

    for tag in h_tags:
        padded = _normalize_code(tag.replace("strongs:", ""))
        # Generic high-frequency lemma → noisy bridge; skip (also absent from
        # the precomputed table).
        if freq.get(padded, 0) >= LXX_BRIDGE_MAX_FREQ:
            continue
        added = 0
        for gcode, count in _bridge_for(padded):
            if added >= max_greek_per_hebrew:
                break
            if not gcode or count < 3:
                continue
            gtag = f"strongs:{_normalize_code(gcode)}"
            if gtag not in existing and gtag not in new_tags:
                new_tags.append(gtag)
                added += 1
        if len(new_tags) >= max_total:
            break

    return new_tags[:max_total]
