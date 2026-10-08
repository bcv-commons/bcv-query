"""Which verse numbering does the reader of this language use? (Passage cards and the verse tools pass it to shoresh `/verse?versification=`.)

Nothing is decided here: the answer comes from the edition index bibles publishes (cdn.bibel.wiki/dbt/_vrs/index.json: 1,494 editions, each classified
into one of its numbering schemes). A language's scheme is the one most of its classified editions use; `agreement` says how many of them agree,
`editions` how many there are. A language with no classified edition is served as `eng` and reported `assumed`, never silently guessed.
The index is cached on disk (BTMCP_VRS_CACHE, default /tmp/bcv-vrs-index.json) and refreshed daily; a stale copy beats no copy.
"""
from __future__ import annotations

import collections
import json
import os
import threading
import time
import urllib.request
from pathlib import Path

DEFAULT_SCHEME = "eng"
INDEX_URL = os.environ.get("VERSIFICATION_INDEX_URL", "https://cdn.bibel.wiki/dbt/_vrs/index.json")
CACHE = Path(os.environ.get("BTMCP_VRS_CACHE", "/tmp/bcv-vrs-index.json"))
_MAX_AGE, _RETRY = 86400, 600
_lock = threading.Lock()
_state: dict = {"index": None, "at": 0.0, "failed": 0.0}


def _index() -> dict:
    with _lock:
        now = time.time()
        if _state["index"] is not None and now - _state["at"] < _MAX_AGE:
            return _state["index"]
        if _state["index"] is None and CACHE.exists():
            try:
                _state["index"], _state["at"] = json.loads(CACHE.read_text("utf-8")), CACHE.stat().st_mtime
            except (OSError, ValueError):
                pass
            if _state["index"] is not None and now - _state["at"] < _MAX_AGE:
                return _state["index"]
        if now - _state["failed"] > _RETRY:
            try:
                raw = urllib.request.urlopen(urllib.request.Request(INDEX_URL, headers={"User-Agent": "bcv-rag"}), timeout=6).read()
                _state["index"], _state["at"] = json.loads(raw), now
                try:
                    CACHE.write_bytes(raw)
                except OSError:
                    pass
            except Exception:                                # noqa: BLE001 - offline: keep what we have
                _state["failed"] = now
        if _state["index"] is None:
            _state["index"] = {"l": {}}
            _state["at"] = now - _MAX_AGE + _RETRY            # try again soon
        return _state["index"]


def scheme_for_lang(lang: str | None) -> dict:
    """{scheme, assumed, editions, agreement} for a reader language code (ISO 639-1 or 639-3; none = English)."""
    from lang import canon
    code = (lang or "en").strip().lower()
    wanted = {code, canon(code)}
    counts = collections.Counter(v for k, v in (_index().get("l") or {}).items()
                                 if "/" in k and k.split("/")[0].lower() in wanted and v != "undetermined")
    if not counts:
        return {"scheme": DEFAULT_SCHEME, "assumed": True, "editions": 0, "agreement": None}
    scheme, n = counts.most_common(1)[0]
    total = sum(counts.values())
    return {"scheme": scheme, "assumed": False, "editions": total, "agreement": round(n / total, 2)}
