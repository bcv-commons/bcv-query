"""Refuse a release whose inputs come from private or TBTA material (decision 2026-11-13, development-phase plan section 7).

bcv-query may read TBTA's data read-only, for figures and checks only. No TBTA value, and nothing from the private folders of
make-tanakh-research or make-tanakh-grammar, may reach a published file. Every release script calls `check(args)` right after
parsing its arguments. The call refuses if any path argument (or the output folder) resolves into a forbidden place.

Forbidden:
- any `private/` folder of the make-tanakh-* repositories (TBTA export, decoded rules, lifted features, word links, editions);
- any path with a component that names TBTA or TaBiThA (`tbta`, `tabitha`, case-insensitive), wherever it lies.

Research's handover packets (`make-tanakh-research/internal-docs/handover/...`) are allowed. Packets carry figures and
source-derived tables only. A table derived from TBTA would have to be named as such, and would then be refused here.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

DEV = Path.home() / "dev"
PRIVATE_ROOTS = tuple(DEV / r / "private" for r in ("make-tanakh-research", "make-tanakh-grammar", "make-tanakh-work",
                                                     "make-tanakh-dev"))
NAMED = re.compile(r"tbta|tabitha", re.IGNORECASE)


def forbidden(path: str | Path) -> str | None:
    """Return why `path` may not feed a release, or None."""
    p = Path(path).expanduser()
    for cand in {p.absolute(), p.resolve()}:
        for root in PRIVATE_ROOTS:
            if cand == root or root in cand.parents:
                return f"{path}: inside {root} (private material)"
        for part in cand.parts:
            if NAMED.search(part):
                return f"{path}: path names TBTA ('{part}')"
    return None


def check(args: argparse.Namespace | dict) -> None:
    """Refuse (SystemExit) if any path-like argument is forbidden. Strings that are not paths are ignored."""
    values = vars(args) if isinstance(args, argparse.Namespace) else dict(args)
    bad = []
    for name, v in values.items():
        for item in (v if isinstance(v, (list, tuple)) else [v]):
            if isinstance(item, Path) or (isinstance(item, str) and ("/" in item or item.startswith("~"))):
                why = forbidden(item)
                if why:
                    bad.append(f"--{name.replace('_', '-')}: {why}")
    if bad:
        raise SystemExit("release refused: TBTA or private input (development-phase plan section 7)\n  " + "\n  ".join(bad))
