"""MACULA's syntax trees in the bridge corpus, for the Tanakh and the Greek NT (store trees-macula-2026-10-08, the one the Hebrew clause
layout pins): the source's trailers and two unit types.

trailer   the text after a word as the source prints it (`after`): a space, nothing inside a written word, maqaf ־, sof pasuq ׃, paseq ׀,
          the open and closed section marks ׃פ / ׃ס, and the Greek NT's punctuation. A space is added after punctuation and the marks that
          the source gives without one. Replaces the space-or-nothing of the word store.
sentence  MACULA's sentence node.
wordgroup MACULA's word group (`wg`): tr_cls (cl, np, pp, vp, ...), tr_role, tr_rule, tr_type, tr_junction, tr_clausetype, tr_articular,
          tr_head (1 where the group is the head of its parent group, Hebrew only), tr_ord (its place among its parent's children);
          edge tr_parent from a group to its parent group or sentence (a group can span the same words as its parent, so containment
          alone does not give the tree).
The words MACULA inserts into the Hebrew tree (6,435, `inserted` = 1, carrying the key of the word before them) have no slot; a group made only of them gets
no unit (counted).
"""
from __future__ import annotations

import collections
import sqlite3

COLS = ("cls", "role", "rule", "type", "junction", "clausetype", "articular", "head", "ord")


def add_trees(c, db) -> None:
    st = collections.Counter()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    slot_of_seq = {}
    for seq, key, after, inserted in con.execute("select seq, key, after, inserted from words order by seq"):
        s = c.slot.get(key)
        if inserted or s is None:                                         # an inserted word repeats the key of the word before it
            st["tree words not in the word store (inserted)"] += 1
            continue
        slot_of_seq[seq] = s
        if after is not None:                                             # punctuation and ׃ / ׀ come without the space after them
            c.F["trailer"][s] = after if after in ("", "־") or after.endswith(" ") else after + " "
            st["trailers"] += 1
    seqs = sorted(slot_of_seq)
    import bisect
    handle = {}
    rows = list(con.execute("select * from nodes order by id"))
    for r in rows:
        i, j = bisect.bisect_left(seqs, r["lo"]), bisect.bisect_right(seqs, r["hi"])
        sl = [slot_of_seq[q] for q in seqs[i:j]]
        typ = "sentence" if r["kind"] == "sentence" else "wordgroup"
        h = c.node(typ, sl)
        if h is None:
            st[f"{typ} without a word in the store"] += 1
            continue
        handle[r["id"]] = h
        st[typ] += 1
        if typ == "wordgroup":
            for col in COLS:
                v = r[col]
                if col == "head":
                    v = 1 if v == "true" else None
                c.set(f"tr_{col}", h, v, "trees")
    for r in rows:
        if r["parent"] is not None:
            st["tr_parent edges"] += c.edge("tr_parent", handle.get(r["id"]), handle.get(r["parent"]), None, "trees")
    c.report["layers"]["trees"] = dict(st)
