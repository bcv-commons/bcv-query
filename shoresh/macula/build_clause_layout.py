"""Build the Hebrew clause layout (proposed dataset bcv-commons/hebrew-clause-layout, phase 1): the Hebrew Bible one clause segment per
line, chapter by chapter, from MACULA Hebrew (CC BY 4.0) in trees-macula.db. No BHSA input.

A clause segment is a maximal run of whole words, inside one verse, that belongs to one MACULA clause:
- a word goes as a whole (prefixes included) to the clause of its last token, because MACULA sometimes puts a prefix (the ל of an
  infinitive) in the higher clause;
- a clause interrupted by an embedded clause gives two segments; a clause that crosses a verse boundary gives one per verse.
`depth` is the number of clause ancestors in the MACULA tree. It only reaches up to the verse (a MACULA sentence is one verse); the
text-level hierarchy (`discourse_parent`, `text_depth`) is phase 2 and is written as null here.

Text: MACULA's WLC surface forms and trailers. A word-final token with an empty trailer gets a space (MACULA leaves it empty at some
ketiv/qere words, which glues two words together); paseq is written ` ׀ `; the setuma/petucha marks after sof pasuq are dropped.
`verse_ref_en` comes from the bibles verse map org-to-eng (TVTMS, CC BY 4.0) through vrsmap; a Psalm title is `PSA 3:title`.
`ketiv_qere` is empty until the UHB reading is wired in.

  python -m macula.build_clause_layout [--books RUT,DAN] [--out macula/data/clause-layout]

Writes clauses/<BOOK>/<BOOK>_<CCC>.jsonl, layout/<BOOK>/<BOOK>_<CCC>.txt and build.json.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

SHORESH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHORESH))

import trees_macula  # noqa: E402
import vrsmap  # noqa: E402

FORMAT_VERSION = 1
LANG = {"H": "hbo", "A": "arc"}


def _clause_parents(con: sqlite3.Connection) -> dict[int, int | None]:
    """Clause id -> nearest clause ancestor that has words of its own (None at the top of the verse). Clauses without words of their own
    are MACULA's coordination groups (rule ClCl, ClCl2, ...): their members are siblings, so they add no level (as in the /scaffold API)."""
    nodes = {r[0]: (r[1], r[2]) for r in con.execute("SELECT id, parent, cls FROM nodes WHERE corpus='hbo'")}
    worded = {r[0] for r in con.execute("SELECT DISTINCT cl FROM words WHERE corpus='hbo' AND inserted=0 AND cl IS NOT NULL")}
    out = {}
    for nid, (_, cls) in nodes.items():
        if cls != "cl":
            continue
        p = nodes[nid][0]
        while p is not None and not (nodes.get(p, (None, None))[1] == "cl" and p in worded):
            p = nodes.get(p, (None, None))[0]
        out[nid] = p
    return out


def _depth(cid: int, parents: dict[int, int | None]) -> int:
    n = 0
    while parents.get(cid) is not None:
        cid = parents[cid]
        n += 1
    return n


def _trailer(after: str, word_final: bool) -> str:
    if after == "׀":
        return " ׀ "
    if after.startswith("׃"):
        return "׃"
    if after in ("ס", "פ"):                 # parashah mark inside a verse
        return " "
    if after == "" and word_final:
        return " "
    return after


def _eng(book: str, ch: int, v: int) -> str:
    refs = vrsmap.to_eng((book, ch, v), "org")
    return vrsmap.fmt(refs[0]) if refs else None


def chapter_segments(rows: list[sqlite3.Row], nodes: dict[int, sqlite3.Row], parents: dict[int, int | None]) -> list[dict]:
    words: list[list[sqlite3.Row]] = []
    for r in rows:
        if words and (words[-1][-1]["verse"], words[-1][-1]["word"]) == (r["verse"], r["word"]):
            words[-1].append(r)
        else:
            words.append([r])
    segs: list[dict] = []
    for i, w in enumerate(words):
        last = w[-1]
        cid = next((t["cl"] for t in reversed(w) if t["cl"] is not None), None)
        text = "".join(t["surface"] + (t["after"] or "") for t in w[:-1]) + last["surface"] + _trailer(last["after"] or "", True)
        keys = [t["key"] for t in w]
        if segs and segs[-1]["verse"] == last["verse"] and segs[-1]["clause"] == cid:
            s = segs[-1]
            s["words"] += [k for k in keys if k != s["words"][-1]]
            s["text"] += text
            s["_lang"].update(t["wlang"] for t in w)
        else:
            segs.append({"verse": last["verse"], "clause": cid, "words": list(dict.fromkeys(keys)), "text": text,
                         "_lang": collections.Counter(t["wlang"] for t in w)})
    out = []
    for n, s in enumerate(segs, 1):
        cid, node = s["clause"], nodes.get(s["clause"])
        lang = s.pop("_lang").most_common(1)[0][0]
        own = [r for r in rows if r["cl"] == cid]
        out.append({"verse": s["verse"], "seg": n, "clause": cid, "parent": parents.get(cid), "sentence": own[0]["sent"] if own else None,
                    "depth": _depth(cid, parents) if cid is not None else 0, "discourse_parent": None, "text_depth": None,
                    "kind": trees_macula._clause_kind(own) if own else None, "rule": (node["rule"] if node else None) or None,
                    "language": LANG.get(lang, "hbo"), "first": s["words"][0], "last": s["words"][-1], "words": s["words"],
                    "text": " ".join(s["text"].split()).replace(" ׀ ", " ׀ "), "ketiv_qere": []})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--books", help="comma-separated USFM codes (default: all Hebrew books)")
    ap.add_argument("--out", default=str(SHORESH / "macula" / "data" / "clause-layout"))
    a = ap.parse_args()
    out = Path(a.out)
    tp = trees_macula.trees_path()
    con = sqlite3.connect(f"file:{tp}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    nodes = {r["id"]: r for r in con.execute("SELECT id, rule FROM nodes WHERE corpus='hbo' AND cls='cl'")}
    parents = _clause_parents(con)
    books = a.books.upper().split(",") if a.books else [r[0] for r in con.execute("SELECT book FROM words WHERE corpus='hbo' GROUP BY book ORDER BY MIN(seq)")]
    n_seg = n_ch = 0
    for book in books:
        chapters = [r[0] for r in con.execute("SELECT DISTINCT chapter FROM words WHERE corpus='hbo' AND book=? ORDER BY chapter", (book,))]
        for ch in chapters:
            rows = con.execute("SELECT * FROM words w WHERE corpus='hbo' AND book=? AND chapter=? AND inserted=0 ORDER BY " + trees_macula.TEXT_ORDER,
                               (book, ch)).fetchall()
            segs = chapter_segments(rows, nodes, parents)
            eng = {}
            for s in segs:
                if s["verse"] not in eng:
                    eng[s["verse"]] = _eng(book, ch, s["verse"])
            full = [{"book": book, "chapter": ch, "verse": s["verse"], "seg": s["seg"], "verse_ref_en": eng[s["verse"]], **{k: v for k, v in s.items() if k not in ("verse", "seg")}}
                    for s in segs]
            for d in ("clauses", "layout"):
                (out / d / book).mkdir(parents=True, exist_ok=True)
            with open(out / "clauses" / book / f"{book}_{ch:03d}.jsonl", "w", encoding="utf-8") as f:
                for r in full:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            lines = [f"{book} {ch}"] + [f"{r['verse']}:{r['depth']} {r['text']}" for r in full]
            (out / "layout" / book / f"{book}_{ch:03d}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            n_seg += len(full)
            n_ch += 1
        print(f"{book}: {len(chapters)} chapters")
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    build = {"format_version": FORMAT_VERSION, "built": datetime.date.today().isoformat(), "books": len(books), "chapters": n_ch, "segments": n_seg,
             "trees_macula": {"built": meta.get("built"), "source": meta.get("source_hbo"), "sha256": hashlib.sha256(Path(tp).read_bytes()).hexdigest()},
             "versification": {"map": "org-to-eng (bcv-commons/bibles, from STEPBible TVTMS, CC BY 4.0)", "tvtms_rev": vrsmap.revision("org")},
             "depth": "clause ancestors in the MACULA tree, within the verse", "discourse_rules": None,
             "licence": "CC BY-SA 4.0; MACULA Hebrew (CC BY 4.0), versification TVTMS (CC BY 4.0)"}
    (out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{n_ch} chapters, {n_seg} segments -> {out}")


if __name__ == "__main__":
    main()
