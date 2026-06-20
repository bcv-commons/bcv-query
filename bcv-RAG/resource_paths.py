"""Locate the shared `resources/` data directory — robustly, no fixed-depth paths.

Resolution order:
  1. ``$BCV_RESOURCES_DIR`` if set — the Docker image sets it explicitly
     (``ENV BCV_RESOURCES_DIR=/app/resources``); also lets you point at a mounted
     volume without code changes.
  2. otherwise walk UP from this file to the nearest ancestor that contains a
     ``resources/`` directory (dev → ``<repo>/resources``).

This replaces brittle ``Path(__file__).parent.parent[.parent]`` traversal: it's
depth-independent (works from any file/cwd) and explicit.

Used by the runtime packages (query/indexer/server). Build scripts under
``scripts/`` may import this too, or compute the repo-root directly.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def resources_root() -> Path:
    env = os.environ.get("BCV_RESOURCES_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "resources"
        if cand.is_dir():
            return cand
    return here.parent / "resources"  # last resort (may not exist)


def resource_path(name: str) -> Path:
    """Path to a shared resource (file or dir) under the resources root."""
    return resources_root() / name
