"""The frame label of a verb's subject or object, looked up in the table of bcv-commons/hebrew-verb-frame-labels.

Stands alone (pyarrow only) and is shipped with the dataset as `lookup.py`. The table counts, over the Hebrew of the
Tanakh, which of MACULA's frame labels (A0, A1, AA, A2) the subject and the object of a verb carry: per verb (its lexeme
with its stem), per verb and whether the clause has an object, per stem and whether the clause has an object, and per
lexeme over all its stems. A row is `settled` when it has enough places and one label holds nearly all of them (the
thresholds are in ACCOUNT.json).

    from lookup import Frames
    F = Frames("data/frames.parquet")
    F.label("hbo:5221", "hiphil", "s", has_object=True)   ->  ("AA", "stem+object", 0.977)   label, step, share
    F.label("hbo:9999", "niphal", "s", has_object=False)  ->  (None, "open", None)

The steps, in order; the first settled row gives the label, and no settled row means no label (never a guess):
  verb          the lexeme with its stem
  verb+object   the lexeme with its stem, and whether the clause has an object (role `s` only)
  stem+object   the stem, and whether the clause has an object (also for a verb the Tanakh does not have)
A word whose stem is not known is read in one row only:
  lexeme        the lexeme over all its stems (settled where they carry the same label)

    python lookup.py FRAMES_PARQUET LEXEME STEM ROLE [with|without]
"""
from __future__ import annotations

import sys

import pyarrow.parquet as pq

STEPS = ("verb", "verb+object", "stem+object", "lexeme")


class Frames:
    def __init__(self, table):
        rows = table if isinstance(table, list) else pq.read_table(table).to_pylist()
        self.row = {(r["step"], r["lexeme"], r["stem"], r["role"], r["object"]): r for r in rows}

    def label(self, lexeme, stem, role, has_object=None):
        """(label, step, share of the Tanakh's places with that label) or (None, why it is open, None)"""
        if not stem:
            r = self.row.get(("lexeme", lexeme or "", "", role, ""))
            if r is not None and r["settled"]:
                return r["label"], "lexeme", r["share"]
            return None, "open: no stem", None
        obj = "" if role != "s" or has_object is None else ("with" if has_object else "without")
        seen = False
        for step, key in (("verb", (lexeme or "", stem, role, "")),
                          ("verb+object", (lexeme or "", stem, role, obj)),
                          ("stem+object", ("", stem, role, obj))):
            if step == "verb+object" and not obj:
                continue
            if step != "stem+object" and not lexeme:
                continue
            r = self.row.get((step, *key))
            if r is None:
                continue
            seen = seen or step != "stem+object"
            if r["settled"]:
                return r["label"], step, r["share"]
        return None, ("open: two labels in the Tanakh" if seen else "open: no settled row"), None


def main():
    if len(sys.argv) < 5:
        raise SystemExit(__doc__)
    obj = {"with": True, "without": False}.get(sys.argv[5]) if len(sys.argv) > 5 else None
    print(*Frames(sys.argv[1]).label(sys.argv[2], sys.argv[3], sys.argv[4], obj))


if __name__ == "__main__":
    main()
