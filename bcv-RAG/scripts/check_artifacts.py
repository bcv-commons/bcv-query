#!/usr/bin/env python3
"""Artifact unit-acceptance checks for the Strong's-anchored core (Phase 5).

Fast, dependency-free assertions over the generated TSVs — locks in the
correctness verified during the build (H/G de-collision, code padding, keyness,
elaboration/importance, TW links). No server / corpus needed. Run after
build_all.py (e.g. in CI).

Usage: python3 scripts/check_artifacts.py   # exit 0 = all pass
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg, file=sys.stderr)
    if not cond:
        fails.append(msg)


def load(name: str) -> tuple[list[str], dict[str, list[str]]]:
    """Return (header, {first_col: row_fields})."""
    path = HERE / name
    if not path.exists():
        fails.append(f"{name} missing")
        return [], {}
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    rows = {}
    for ln in lines[1:]:
        f = ln.split("\t")
        rows[f[0]] = f
    return header, rows


def main() -> None:
    # ---- concepts.tsv (the registry) ----
    hdr, con = load("concepts.tsv")
    col = {c: i for i, c in enumerate(hdr)}
    check(len(con) == 14061, f"concepts: 14061 rows (got {len(con)})")
    check(all(c in col for c in ("strong", "lemma", "keyness", "is_function",
              "tw_kt", "elaboration", "importance")),
          "concepts: has expected columns")

    def cval(code, c):
        return con.get(code, [""] * len(hdr))[col[c]] if code in con else None

    # H/G de-collision: both exist, distinct
    check("H3588" in con and "G3588" in con, "H3588 and G3588 both present (de-collided)")
    # code padding: low Greek code present padded, keyness resolves
    check("G0026" in con, "G0026 present (padded)")
    check(cval("G0026", "keyness") not in (None, ""), "G0026 keyness resolves (padding fix)")
    # no unpadded low codes leaked in
    check(not any(re.match(r"^[HG][0-9]{1,3}$", k) for k in con),
          "no unpadded low codes in concepts")
    # importance/elaboration: love high via elaboration, function words zero
    check(int(cval("G0026", "elaboration") or 0) >= 10, "G0026 (love) elaboration >= 10")
    check(float(cval("G0026", "importance") or 0) >= 3.0, "G0026 (love) importance >= 3.0")
    check(float(cval("G2532", "importance") or 9) == 0.0, "G2532 (kai, function) importance == 0")
    check(cval("G5485", "keyness") not in (None, "") and float(cval("G5485", "keyness")) > 0.5,
          "G5485 (grace) keyness > 0.5")
    # is_function: function particles flagged, content not
    check(cval("H0834", "is_function") == "1", "H0834 (asher) is_function == 1")
    check(cval("G0026", "is_function") == "0", "G0026 (love) is_function == 0")
    # tw_kt: content key-term flagged, function word not
    check(cval("G0026", "tw_kt") == "1", "G0026 (love) tw_kt == 1")
    check(cval("H0834", "tw_kt") == "0", "H0834 (function) tw_kt == 0")

    # ---- strong_lemma.tsv ----
    _, lem = load("strong_lemma.tsv")
    check(len(lem) == 14061, f"strong_lemma: 14061 codes (got {len(lem)})")
    check(lem.get("H2617", ["", "", ""])[2] != "", "H2617 has a lemma")

    # ---- forms.tsv (morphology cluster) ----
    _, forms = load("forms.tsv")
    h2617_forms = sum(1 for k in (Path(HERE / "forms.tsv").read_text(encoding="utf-8")
                                  .splitlines()[1:]) if k.startswith("H2617\t"))
    check(h2617_forms >= 50, f"H2617 has >= 50 surface forms (got {h2617_forms})")

    # ---- tw_links.tsv ----
    tw_path = HERE / "tw_links.tsv"
    if tw_path.exists():
        n_tw = len(tw_path.read_text(encoding="utf-8").splitlines()) - 1
        check(n_tw > 100000, f"tw_links: >100k token-rows (got {n_tw})")
    else:
        check(False, "tw_links.tsv present")

    # ---- cross-file consistency: concepts codes are a subset of strong_lemma ----
    check(set(con) <= set(lem), "all concept codes exist in strong_lemma")

    print(f"\n{len(fails)} failure(s)" if fails else "\nAll artifact checks passed.",
          file=sys.stderr)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
