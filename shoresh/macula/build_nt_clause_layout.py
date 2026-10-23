"""Build the Greek New Testament clause layout (phase 1): the Nestle 1904 text one clause segment per line, chapter by chapter, from
MACULA Greek (CC BY 4.0) in trees-macula.db. No BHSA input, no rules yet.

A clause segment is a maximal run of words, inside one verse, that belongs to one clause.
- MACULA Greek wraps many clauses in a clause node that holds only the word introducing them: a conjunction (Conj-CL: καί, δέ),
  a subordinator (sub-CL: ὅτι, ἵνα), the article of an articular infinitive (DetCL), a particle (PtclCL), or nothing but the
  coordinated clauses (CLaCL). Such a wrapper (own words only conj, ptcl, det or the adverbs οὐ, μή, καί, and a clause below it) is not a level: its words go
  with the clause they introduce (the next word's clause, or the previous word's for a postpositive δέ, γάρ, οὖν), and the clause
  takes the wrapper's rules as `via` and its role as `role`. AdvpCL (an adverb such as ὁμοίως over a clause) and that-VP
  (ὅτι, which MACULA tags as an adverb there) are wrappers too.
- A coordination node (CLaCL, Conj3CL, aCLaCL, EitherOr4CL, ...) is not a level either: its clauses are siblings. MACULA puts a short
  member straight into the node (ἀλλὰ ὁ ἀνήρ, καὶ διώξωσιν), so the node's own words are a segment of their own at the members'
  depth; a coordinating conjunction goes with the member it opens.
- A clause interrupted by an embedded clause gives two segments; a clause that crosses a verse boundary gives one per verse
  (a MACULA Greek sentence can run over several verses).
Rule (an expression, not a place): a bare articular participle, the article and the participle alone (οἱ πενθοῦντες, τῷ Ἠγαπημένῳ,
with μή at most), is a noun phrase in the line, not a line: MACULA makes every participle a clause, so it would otherwise stand alone
(μακάριοι / οἱ πενθοῦντες). It joins the segment before it in the verse (or the one after, at the start of a verse), and the clause
it interrupted is joined up again; the record lists it in `inline`. A participle with words of its own keeps its line.
Rule: a preposition, a conjunction that is not postpositive, the adverb καί "also, even" or a negation (οὐ, μή) that ends a segment, where the next segment in the verse is a clause below it,
goes with that clause, which it governs or introduces (εἰς || τὸ φαγεῖν, καὶ || οἱ κατοικοῦντες). MACULA puts it in the higher clause.
Rule: no line of function words alone (conjunctions, prepositions, articles, particles, οὐ, μή, καί) where the tree leaves one
(ἀλλὰ || τῇ κακίᾳ νηπιάζετε): such a segment goes with the next segment of the verse, which it introduces, or, when it opens with a
postpositive (δέ, γάρ, μέν, οὖν, τε: ἐγὼ || μὲν || γάρ), with the one before; the line takes that segment's clause.
`depth` is the number of clause ancestors in the sentence, wrappers not counted. `parent` is the parent clause's id; a clause is named
by the key of its first word. Verse numbers are Nestle 1904's.

  python -m macula.build_nt_clause_layout [--books MAT,ROM] [--out macula/data/nt-clause-layout]

Writes clauses/<BOOK>/<BOOK>_<CCC>.jsonl, layout/<BOOK>/<BOOK>_<CCC>.txt and build.json.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

SHORESH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHORESH))

import trees_macula  # noqa: E402

FORMAT_VERSION = 1
WRAPPER_CLASSES = {"conj", "ptcl", "det"}
WRAPPER_ADVERBS = {"οὐ", "μή", "καί"}                    # οὐ γάρ ... ἀλλά, καὶ γὰρ οὐκ: the negation or "also" of a coordination
ADVERB_WRAPPERS = {"AdvpCL", "that-VP"}               # ὁμοίως over a clause; ὅτι (tagged adv) over its clause
COORDINATION = re.compile(r"^(?:\d?a?CL.*CL|Conj\d+(?:CL|P)|EitherOr\d+CL|ClCl\d?|CLand.*)$")


class Tree:
    """The clause nodes of MACULA Greek, with the wrappers made transparent."""

    def __init__(self, con: sqlite3.Connection):
        self.node = {r["id"]: r for r in con.execute("SELECT id, parent, cls, rule, role, junction FROM nodes WHERE corpus='grc'")}
        own = collections.defaultdict(list)
        for cl, cls, lemma in con.execute("SELECT cl, class, lemma FROM words WHERE corpus='grc' AND cl IS NOT NULL"):
            own[cl].append((cls, lemma))
        has_clause_below = set()
        for nid, r in self.node.items():
            if r["cls"] == "cl":
                p = r["parent"]
                while p is not None:
                    has_clause_below.add(p)
                    p = self.node[p]["parent"]
        self.coord = {nid for nid, r in self.node.items() if r["cls"] == "cl" and nid in has_clause_below
                      and COORDINATION.match(r["rule"] or "")}
        self.wrapper = {nid for nid, r in self.node.items() if r["cls"] == "cl" and nid in has_clause_below and nid not in self.coord
                        and all(c in WRAPPER_CLASSES or (c == "adv" and (r["rule"] in ADVERB_WRAPPERS or lm in WRAPPER_ADVERBS))
                                for c, lm in own[nid])}
        self.parent: dict[int, int | None] = {}
        self.via: dict[int, list[str]] = {}
        self.role: dict[int, str | None] = {}
        for nid, r in self.node.items():
            if r["cls"] != "cl" or nid in self.wrapper:
                continue
            via, role, p = [], r["role"], r["parent"]
            while p is not None and not (self.node[p]["cls"] == "cl" and p not in self.wrapper and p not in self.coord):
                if p in self.wrapper or p in self.coord:
                    via.append(self.node[p]["rule"] or "-")
                    role = role or self.node[p]["role"]
                p = self.node[p]["parent"]
            self.parent[nid], self.via[nid], self.role[nid] = p, via[::-1], role

    def real(self, cl: int | None) -> int | None:
        """The nearest clause that is not a wrapper, from a word's clause."""
        while cl is not None and (self.node[cl]["cls"] != "cl" or cl in self.wrapper):
            cl = self.node[cl]["parent"]
        return cl

    def under(self, cl: int | None, anc: int) -> bool:
        while cl is not None:
            if cl == anc:
                return True
            cl = self.node[cl]["parent"]
        return False

    def depth(self, cl: int) -> int:
        n = 0
        while self.parent.get(cl) is not None:
            cl = self.parent[cl]
            n += 1
        return n


def word_clauses(rows: list[sqlite3.Row], tree: Tree) -> list[int | None]:
    """The clause each word goes with: its own, or for a wrapper's word (and a coordinating conjunction) the clause it introduces.
    Right to left, so that a run of such words (εἰ μή, ὁμοίως δέ) moves together; a word with nothing of its node after it goes with
    the word before (a postpositive δέ, γάρ, οὖν after the clause's first word)."""
    def movable(r: sqlite3.Row) -> bool:
        return r["cl"] in tree.wrapper or (r["cl"] in tree.coord and r["class"] == "conj")
    res = [r["cl"] for r in rows]
    for i in range(len(rows) - 2, -1, -1):
        r, nxt = rows[i], rows[i + 1]
        if movable(r) and nxt["sent"] == r["sent"] and res[i + 1] != r["cl"] and tree.under(res[i + 1], r["cl"]):
            res[i] = res[i + 1]
    for i in range(1, len(rows)):
        r = rows[i]
        nxt_in = i + 1 < len(rows) and rows[i + 1]["sent"] == r["sent"] and tree.under(res[i + 1], r["cl"])
        if movable(r) and res[i] == r["cl"] and not nxt_in and rows[i - 1]["sent"] == r["sent"] and res[i - 1] != r["cl"] \
                and tree.under(res[i - 1], r["cl"]):
            res[i] = res[i - 1]
    return [tree.real(c) for c in res]


def chapter_segments(rows: list[sqlite3.Row], tree: Tree) -> list[dict]:
    cids = word_clauses(rows, tree)
    segs: list[dict] = []
    for r, cid in zip(rows, cids):
        if segs and segs[-1]["verse"] == r["verse"] and segs[-1]["_cl"] == cid:
            segs[-1]["_rows"].append(r)
        else:
            segs.append({"verse": r["verse"], "_cl": cid, "_rows": [r], "_inline": []})
    for n, s in enumerate(segs, 1):
        s["seg"] = n
    return segs


NEGATIONS = {"μή", "οὐ"}
HAS_CHILD: set[int] = set()                                # clauses with a clause below them (filled in main)


def bare_participle(seg: dict, whole: dict[int, int], mood: dict[str, str]) -> bool:
    """Article and participle alone, the whole clause, and no clause below it (οἱ λέγοντες ὅτι ... keeps its line)."""
    rows = seg["_rows"]
    verbs = [r for r in rows if r["class"] == "verb"]
    return (seg["_cl"] is not None and len(rows) == whole.get(seg["_cl"]) and seg["_cl"] not in HAS_CHILD and rows[0]["class"] == "det" and len(verbs) == 1
            and mood.get(verbs[0]["key"]) == "participle"
            and all(r["class"] in ("det", "verb") or r["lemma"] in NEGATIONS for r in rows))


def inline_participles(segs: list[dict], whole: dict[int, int], mood: dict[str, str]) -> list[dict]:
    out: list[dict] = []
    i = 0
    while i < len(segs):
        s = segs[i]
        if bare_participle(s, whole, mood) and out and out[-1]["verse"] == s["verse"]:
            host = out[-1]
            host["_rows"] += s["_rows"]
            host["_inline"].append((s["_cl"], s["_rows"][0]["key"]))
            nxt = segs[i + 1] if i + 1 < len(segs) else None
            if nxt and nxt["verse"] == host["verse"] and nxt["_cl"] == host["_cl"]:
                host["_rows"] += nxt["_rows"]
                host["_inline"] += nxt["_inline"]
                i += 1
        elif (bare_participle(s, whole, mood) and i + 1 < len(segs) and segs[i + 1]["verse"] == s["verse"]
              and (not out or out[-1]["verse"] != s["verse"])):
            nxt = segs[i + 1]
            out.append({**nxt, "_rows": s["_rows"] + nxt["_rows"], "_inline": [(s["_cl"], s["_rows"][0]["key"])] + nxt["_inline"]})
            i += 1
        else:
            out.append(s)
        i += 1
    for n, s in enumerate(out, 1):
        s["seg"] = n
    return out


def carried(r: sqlite3.Row) -> bool:
    return (r["class"] == "prep" or (r["class"] == "adv" and (r["lemma"] in WRAPPER_ADVERBS or r["lemma"] == "ὅτι"))
            or (r["class"] == "conj" and r["lemma"] not in POSTPOSITIVE))


def carry_forward(segs: list[dict], tree: Tree) -> list[dict]:
    for a, b in zip(segs, segs[1:]):
        while (a["_rows"] and a["verse"] == b["verse"] and b["_cl"] is not None and a["_cl"] is not None and b["_cl"] != a["_cl"]
               and tree.under(b["_cl"], a["_cl"])
               and carried(a["_rows"][-1])):
            b["_rows"].insert(0, a["_rows"].pop())
    out = no_function_lines([s_ for s_ in segs if s_["_rows"]])
    for n, s_ in enumerate(out, 1):
        s_["seg"] = n
    return out


POSTPOSITIVE = {"δέ", "γάρ", "μέν", "οὖν", "τε"}


def _function_word(r: sqlite3.Row) -> bool:
    return r["class"] in ("conj", "prep", "det", "ptcl") or (r["class"] == "adv" and r["lemma"] in WRAPPER_ADVERBS)


def no_function_lines(segs: list[dict]) -> list[dict]:
    segs = list(segs)
    i = len(segs) - 1
    while i >= 0:
        s_ = segs[i]
        if all(_function_word(r) for r in s_["_rows"]):
            prev_ok = i > 0 and segs[i - 1]["verse"] == s_["verse"]
            next_ok = i + 1 < len(segs) and segs[i + 1]["verse"] == s_["verse"]
            if prev_ok and (s_["_rows"][0]["lemma"] in POSTPOSITIVE or not next_ok):
                segs[i - 1] = {**segs[i - 1], "_rows": segs[i - 1]["_rows"] + s_["_rows"], "_inline": segs[i - 1]["_inline"] + s_["_inline"]}
                del segs[i]
            elif next_ok:
                segs[i + 1] = {**segs[i + 1], "_rows": s_["_rows"] + segs[i + 1]["_rows"], "_inline": s_["_inline"] + segs[i + 1]["_inline"]}
                del segs[i]
        i -= 1
    # a postpositive merged backwards can leave the line before it of function words only: one more pass
    if any(all(_function_word(r) for r in s_["_rows"]) and j + 1 < len(segs) and segs[j + 1]["verse"] == s_["verse"]
           and s_["_rows"][0]["lemma"] not in POSTPOSITIVE for j, s_ in enumerate(segs)):
        return no_function_lines(segs)
    return segs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--books", help="comma-separated USFM codes (default: all NT books)")
    ap.add_argument("--out", default=str(SHORESH / "macula" / "data" / "nt-clause-layout"))
    a = ap.parse_args()
    out = Path(a.out)
    tp = trees_macula.trees_path()
    con = trees_macula._con()                              # trees-macula.db with the lexeme spine (for the participles' mood)
    tree = Tree(con)
    HAS_CHILD.update(p_ for p_ in tree.parent.values() if p_ is not None)
    mood = dict(con.execute("SELECT w.key, s.mood FROM words w JOIN sp.spine_words s ON s.key=w.key WHERE w.corpus='grc' "
                            "AND w.class='verb'").fetchall())
    books = a.books.upper().split(",") if a.books else [r[0] for r in con.execute(
        "SELECT book FROM words WHERE corpus='grc' GROUP BY book ORDER BY MIN(seq)")]
    chapters: list[tuple[str, int, list[dict]]] = []
    for book in books:
        for (ch,) in con.execute("SELECT DISTINCT chapter FROM words WHERE corpus='grc' AND book=? ORDER BY chapter", (book,)).fetchall():
            rows = con.execute("SELECT * FROM words w WHERE corpus='grc' AND book=? AND chapter=? ORDER BY " + trees_macula.TEXT_ORDER,
                               (book, ch)).fetchall()
            segs = chapter_segments(rows, tree)
            whole = collections.Counter(s_["_cl"] for s_ in segs for _ in s_["_rows"])
            chapters.append((book, ch, carry_forward(inline_participles(segs, whole, mood), tree)))
    key_of: dict[int, str] = {}                            # stable clause ids: the key of the clause's first word
    for _, _, segs in chapters:
        for s in segs:
            if s["_cl"] is not None:
                key_of.setdefault(s["_cl"], s["_rows"][0]["key"])
    stats = collections.Counter()
    depths = collections.Counter()
    for book, ch, segs in chapters:
        recs, lines = [], []
        for s in segs:
            cid, rows = s["_cl"], s["_rows"]
            own = [r for r in rows if r["cl"] == cid]
            depth = tree.depth(cid) if cid is not None else 0
            text = " ".join(r["surface"] + (r["after"] or "").strip() for r in rows)
            rec = {"verse": s["verse"], "seg": s["seg"], "clause": key_of.get(cid), "parent": key_of.get(tree.parent.get(cid)),
                   "depth": depth, "kind": trees_macula._clause_kind(own or rows) if cid is not None else None,
                   "rule": tree.node[cid]["rule"] if cid is not None else None, "role": tree.role.get(cid),
                   "via": tree.via.get(cid, []), "junction": tree.node[cid]["junction"] if cid is not None else None,
                   "sentence": rows[0]["sent"], "first": rows[0]["key"], "last": rows[-1]["key"],
                   "inline": [k for _, k in s["_inline"]], "words": [r["key"] for r in rows], "text": text}
            recs.append(rec)
            lines.append(f"{ch}:{s['verse']}\t{'    ' * depth}{text}")
            stats["segments"] += 1
            stats["words"] += len(rows)
            stats["no_clause"] += cid is None
            stats["inline_participles"] += len(s["_inline"])
            depths[depth] += 1
        d = out / "clauses" / book
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{book}_{ch:03d}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
        d = out / "layout" / book
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{book}_{ch:03d}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    meta = dict(con.execute("SELECT * FROM meta").fetchall())
    build = {"format_version": FORMAT_VERSION, "built": datetime.date.today().isoformat(), "source": meta.get("source_grc"),
             "trees_db_built": meta.get("built"), "trees_db_sha256": hashlib.sha256(Path(tp).read_bytes()).hexdigest(),
             "books": len(books), "chapters": len(chapters), "clauses": len(key_of), "wrappers": len(tree.wrapper),
             "coordinations": len(tree.coord), **stats,
             "depth": dict(sorted(depths.items()))}
    (out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in build.items() if k != "trees_db_sha256"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
