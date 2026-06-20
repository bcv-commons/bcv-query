"""Strategy 2: LXX bridge expansion — Hebrew Strong's → Greek Strong's.

When concept expansion (Strategy 1) produces Hebrew Strong's tags, this
calls shoresh `/bridge/{strong}` to find the top Greek translations via
the Septuagint, and adds those as additional `strongs:` tags.

Effect: an OT Hebrew concept like H2617 (chesed) automatically expands
to G1656 (eleos/mercy) — its LXX translation — so NT content tagged with
the Greek equivalent surfaces alongside OT results.

Runs at $0, ~50ms (single network call to shoresh per Hebrew tag).
Only fires when Hebrew Strong's tags are present.
"""
from __future__ import annotations

import logging
import os
import re

import httpx

logger = logging.getLogger("bcv-rag.lxx_expand")

SHORESH_URL = os.environ.get("SHORESH_URL", "").rstrip("/")


def _normalize_code(code: str) -> str:
    m = re.match(r"^([HG])(\d+)$", code)
    if not m:
        return code
    return f"{m.group(1)}{int(m.group(2)):04d}"


def expand_lxx(tags: list[str], max_greek_per_hebrew: int = 2,
               max_total: int = 4) -> list[str]:
    """Given existing tags, find Hebrew Strong's and expand via LXX bridge."""
    if not SHORESH_URL:
        return []

    h_tags = [t for t in tags if t.startswith("strongs:H")]
    if not h_tags:
        return []

    existing = set(tags)
    new_tags: list[str] = []

    try:
        with httpx.Client(base_url=SHORESH_URL, timeout=5.0) as client:
            for tag in h_tags:
                strong = tag.replace("strongs:", "")
                strong = re.sub(r"^H0*", "H", strong)
                try:
                    resp = client.get(f"/bridge/{strong}")
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    translations = data.get("greek_translations", [])
                    added = 0
                    for t in translations:
                        if added >= max_greek_per_hebrew:
                            break
                        gcode = t.get("greek_strong", "")
                        if not gcode or t.get("count", 0) < 3:
                            continue
                        gtag = f"strongs:{_normalize_code(gcode)}"
                        if gtag not in existing and gtag not in new_tags:
                            new_tags.append(gtag)
                            added += 1
                except Exception:
                    continue
                if len(new_tags) >= max_total:
                    break
    except Exception as e:
        logger.debug("LXX bridge expansion failed: %s", e)

    return new_tags[:max_total]
