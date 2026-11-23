"""The New Testament's syntax trees joined through the part-to-part links (plan section 9; local, unpublished).

    cd shoresh && .venv/bin/python -I -m macula.build_nt_tree_join \
        --cells heb_scg=DIR --cells heb_mod=DIR --tables internal-docs/aligner-tables/v0.2 \
        --spine SPINE.db --clauses macula/data/clause-tagger/export --glaux GLAUX_NT_XML_DIR \
        --crosswalk internal-docs/glaux-macula-nt-2026-11-22/out/crosswalk.tsv --out DIR

The links are the lexeme-aligner's (its cells: Greek part -> Hebrew token + level-2 piece); this script only joins.
The trees are MACULA Greek's (`trees-macula.db`, Nestle 1904), GLAUx's NT (PROIEL-style dependency trees, SBLGNT), and
hebrew-nt-analysis' clause segments on each Hebrew NT. The Hebrew NTs have no tree of their own beyond those segments: the
Greek trees are projected onto them through the links. Deterministic, no model.

DIR/by/ (CC BY 4.0: MACULA Greek, the Hebrew NT tables, the aligner's links):
  parts.parquet        Greek parts (word-parts v1.1 ids, through the aligner's spine) and Hebrew pieces (tables' part2_id)
  part_links.parquet   edition, greek_part_id, hebrew_piece_id, hebrew_ref (the paired Hebrew verse), prior, method, score
  nodes.parquet        MACULA Greek nodes (tree macula_grc: node id, parent, kind, cls, role, rule, first/last word) and
                       the Hebrew clause segments (tree <edition>_clauses)
  node_links.parquet   per Greek node and edition: its parts, linked parts, linked Hebrew tokens, their span, the share of
                       that span linked from inside the node, the smallest Hebrew clause segment over them (empty when they cross segments:
                       the tagger's segments do not nest) and how many segments they fall in; per Hebrew
                       segment: its linked Greek words and the smallest MACULA node over them, with coverage
DIR/by-sa/ (CC BY-SA 4.0: everything with GLAUx's ids):
  crosswalk.parquet    GLAUx NT word <-> MACULA Greek word (kind: same, accent, movable, replace, glaux_only, macula_only)
  glaux_words.parquet  GLAUx's words with head and relation (no `sense`: its values are English WordNet senses)
  glaux_node_links.parquet  per GLAUx word's subtree and edition: the Hebrew tokens linked, span, inside share, and the
                       smallest MACULA node over its words
DIR/report.json
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
BOOKS = ["MAT", "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL", "EPH", "PHP", "COL", "1TH", "2TH", "1TI", "2TI", "TIT",
         "PHM", "HEB", "JAS", "1PE", "2PE", "1JN", "2JN", "3JN", "JUD", "REV"]
BORD = {b: n for n, b in enumerate(BOOKS)}


def write(p: Path, rows: list[dict]) -> None:
    pq.write_table(pa.Table.from_pylist(rows), p)


def verse_key(v):
    return (BORD[v[0]], v[1], v[2])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cells", action="append", required=True, help="EDITION=DIR of the aligner's cells (*.jsonl)")
    ap.add_argument("--tables", type=Path, required=True, help="aligner tables folder (heb_scg/, heb_mod/ words.parquet)")
    ap.add_argument("--spine", type=Path, required=True, help="the aligner's parts spine (spine_words: idx -> part_id)")
    ap.add_argument("--trees", type=Path, default=HERE / "trees-macula.db")
    ap.add_argument("--clauses", type=Path, required=True, help="hebrew-nt-analysis export (<edition>/clauses.parquet)")
    ap.add_argument("--glaux", type=Path, required=True, help="GLAUx NT XML (0031-0nn.xml)")
    ap.add_argument("--crosswalk", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    out = a.out
    out.mkdir(parents=True, exist_ok=False)
    (out / "by").mkdir(); (out / "by-sa").mkdir()
    rep: dict = {"inputs": {"cells": a.cells, "tables": str(a.tables), "spine": str(a.spine), "glaux": str(a.glaux)}}

    # --- Greek: parts (spine idx -> part id), MACULA words and tree ---
    sp = sqlite3.connect(f"file:{a.spine.resolve()}?mode=ro", uri=True)
    gpart = {}                                           # (book, ch, v, idx) -> (part_id, word key, surface)
    for b, c, v, i, key, surf, pid in sp.execute("select book, chapter, verse, idx, key, surface, part_id from spine_words"):
        if b in BORD:
            gpart[(b, c, v, i)] = (pid, key.split(".")[0], surf)
    tr = sqlite3.connect(f"file:{a.trees.resolve()}?mode=ro", uri=True)
    wseq, seqw = {}, {}
    for seq, key in tr.execute("select seq, key from words where corpus='grc'"):
        wseq[key] = seq; seqw[seq] = key
    nodes = list(tr.execute("select id, parent, kind, cls, role, rule, lo, hi, book, chapter, verse from nodes where corpus='grc'"))
    parts_of_word = collections.defaultdict(list)
    for (b, c, v, i), (pid, w, s) in gpart.items():
        parts_of_word[w].append(pid)
    parts_rows = [{"unit": "grc", "id": pid, "word_id": w, "book": b, "chapter": c, "verse": v, "position": i, "text": s, "kind": ""}
                  for (b, c, v, i), (pid, w, s) in sorted(gpart.items(), key=lambda x: (verse_key(x[0][:3]), x[0][3]))]

    # smallest MACULA node over a set of word seqs: nodes sorted by span; climb from a word's innermost node
    parent = {n[0]: n[1] for n in nodes}
    span = {n[0]: (n[6], n[7]) for n in nodes}
    inner = {}                                           # seq -> innermost node
    for n in sorted(nodes, key=lambda n: n[7] - n[6], reverse=True):
        for s in range(n[6], n[7] + 1):
            inner[s] = n[0]

    def lca(seqs):
        if not seqs:
            return None
        lo, hi = min(seqs), max(seqs)
        n = inner.get(lo)
        while n is not None and not (span[n][0] <= lo and hi <= span[n][1]):
            n = parent.get(n)
        return n

    node_rows = [{"tree": "macula_grc", "node_id": f"grc:{n[0]}", "parent": f"grc:{n[1]}" if n[1] else "", "kind": n[2],
                  "cls": n[3] or "", "role": n[4] or "", "rule": n[5] or "", "first_word": seqw.get(n[6], ""),
                  "last_word": seqw.get(n[7], ""), "book": n[8], "chapter": n[9], "verse": n[10]} for n in nodes]

    # --- Hebrew: pieces per token, clause segments ---
    heb = {}
    for ed in ("heb_scg", "heb_mod"):
        tok = collections.defaultdict(dict)              # (b, c, v) -> i -> {"token", "pieces": {part: id}}
        for r in pq.read_table(a.tables / ed / "words.parquet").to_pylist():
            t = tok[(r["book"], r["chapter"], r["verse"])].setdefault(r["i"], {"token": r["token"], "pieces": {}})
            t["pieces"][r["part"]] = r["part2_id"]
            if r["part2_id"]:
                parts_rows.append({"unit": ed, "id": r["part2_id"], "word_id": r["part_id"][:-1], "book": r["book"],
                                   "chapter": r["chapter"], "verse": r["verse"], "position": r["i"], "text": r["text"],
                                   "kind": r["level2_kind"]})
        segs = collections.defaultdict(list)
        for r in pq.read_table(a.clauses / ed / "clauses.parquet").to_pylist():
            segs[(r["book"], r["chapter"], r["verse"])].append(r)
            node_rows.append({"tree": f"{ed}_clauses", "node_id": f"{ed}:{r['book']}.{r['chapter']}.{r['verse']}.{r['seg']}",
                              # the tagger's parent is an offset from the segment ("-1": the one before), or "none"
                              "parent": "" if not (r["parent"] or "").lstrip("-+").isdigit()
                              else f"{ed}:{r['book']}.{r['chapter']}.{r['verse']}.{r['seg'] + int(r['parent'])}",
                              "kind": r["kind"] or "", "cls": "", "role": "", "rule": r["rule"] or "",
                              "first_word": str(r["first_i"]), "last_word": str(r["last_i"]),
                              "book": r["book"], "chapter": r["chapter"], "verse": r["verse"]})
        heb[ed] = (tok, segs)

    # --- links from the aligner's cells ---
    links = []
    st = collections.Counter()
    by_greek = {ed: collections.defaultdict(set) for ed in heb}     # edition -> greek word key -> {(hverse, i)}
    by_htok = {ed: collections.defaultdict(set) for ed in heb}      # edition -> (hverse, i) -> {greek word key}
    for spec in a.cells:
        ed, d = spec.split("=", 1)
        tok, _ = heb[ed]
        for f in sorted(Path(d).glob("*.jsonl")):
            for line in open(f, encoding="utf-8"):
                r = json.loads(line)
                gv = (r["book"], r["chapter"], r["verse"])
                # the paired Hebrew verse: the one whose tokens match the pairs' target words best (remapped verses)
                cands = [gv, (gv[0], gv[1], gv[2] - 1), (gv[0], gv[1], gv[2] + 1)]
                def fit(hv):
                    T = tok.get(hv, {})
                    return sum(1 for p in r["pairs"] if p.get("target") and p["t_idx"]
                               and " ".join(T.get(i, {}).get("token", "?") for i in p["t_idx"]) == p["target"])
                hv = max(cands, key=lambda c: (fit(c), c == gv))
                st["records"] += 1
                if hv != gv:
                    st["records paired with a neighbour verse"] += 1
                T = tok.get(hv, {})
                for p in r["pairs"]:
                    g = gpart.get(gv + (p["h_idx"],))
                    if g is None:
                        st["greek part not in spine"] += 1; continue
                    if not p["t_parts"]:
                        links.append({"edition": ed, "greek_part_id": g[0], "hebrew_piece_id": "", "hebrew_ref": "",
                                      "prior": p.get("prior", ""), "method": p.get("method", ""), "score": p.get("score")})
                        st["greek parts linked to nothing"] += 1; continue
                    for t, q in p["t_parts"]:
                        tt = T.get(t)
                        if tt is None:
                            st["hebrew token not found"] += 1; continue
                        ids = [tt["pieces"][q]] if q is not None and q in tt["pieces"] else list(tt["pieces"].values())
                        for hid in ids:
                            if not hid:
                                st["link onto a fault row (no piece id)"] += 1; continue
                            links.append({"edition": ed, "greek_part_id": g[0], "hebrew_piece_id": hid,
                                          "hebrew_ref": f"{hv[0]} {hv[1]}:{hv[2]}", "prior": p.get("prior", ""),
                                          "method": p.get("method", ""), "score": p.get("score")})
                            st[f"links {ed}"] += 1
                        by_greek[ed][g[1]].add((hv, t))
                        by_htok[ed][(hv, t)].add(g[1])
    rep["links"] = dict(st)

    # global Hebrew token order (for spans over verse ends)
    order, seq_of = {}, {}
    for ed, (tok, _) in heb.items():
        seq_of[ed] = []
        for hv in sorted(tok, key=verse_key):
            for i in sorted(tok[hv]):
                order[(ed, hv, i)] = len(seq_of[ed]); seq_of[ed].append((hv, i))

    def heb_span(ed, toks, inside_words):
        """span of the linked tokens, share of the span's linked tokens that only words inside link, smallest segment"""
        if not toks:
            return None, None, 0, 0.0, "", 0
        o = sorted(order[(ed, hv, i)] for hv, i in toks)
        span_toks = seq_of[ed][o[0]:o[-1] + 1]
        linked_in_span = [k for k in span_toks if by_htok[ed].get(k)]
        own = [k for k in linked_in_span if by_htok[ed][k] <= inside_words]
        share = round(len(own) / len(linked_in_span), 3) if linked_in_span else 0.0
        seg = ""
        vs = {hv for hv, _ in toks}
        nseg = len({(hv, x["seg"]) for hv, i in toks for x in heb[ed][1].get(hv, []) if x["first_i"] <= i <= x["last_i"]})
        if len(vs) == 1:
            hv = next(iter(vs)); ii = [i for _, i in toks]
            best = None
            for s in heb[ed][1].get(hv, []):
                if s["first_i"] <= min(ii) and max(ii) <= s["last_i"] and (best is None or s["last_i"] - s["first_i"] < best["last_i"] - best["first_i"]):
                    best = s
            if best:
                seg = f"{ed}:{hv[0]}.{hv[1]}.{hv[2]}.{best['seg']}"
        return o[0], o[-1], len(o), share, seg, nseg

    # --- node links: MACULA Greek node -> Hebrew, Hebrew segment -> MACULA node ---
    nl = []
    for n in nodes:
        words = {seqw[s] for s in range(n[6], n[7] + 1) if s in seqw}
        np_ = sum(len(parts_of_word.get(w, [])) for w in words)
        for ed in heb:
            toks = set().union(*(by_greek[ed].get(w, set()) for w in words)) if words else set()
            lo, hi, k, share, seg, nseg = heb_span(ed, toks, words)
            nl.append({"direction": "grc_to_heb", "edition": ed, "node_id": f"grc:{n[0]}", "words": len(words), "parts": np_,
                       "linked_words": sum(1 for w in words if by_greek[ed].get(w)), "hebrew_tokens": k,
                       "hebrew_span": (hi - lo + 1) if k else 0, "inside_share": share, "other_node": seg, "hebrew_segments": nseg,
                       "coverage": None})
    for ed, (tok, segs) in heb.items():
        for hv, ss in segs.items():
            for s in ss:
                toks = [(hv, i) for i in range(s["first_i"], s["last_i"] + 1)]
                gw = set().union(*(by_htok[ed].get(t, set()) for t in toks))
                m = lca([wseq[w] for w in gw if w in wseq])
                cov = None
                if m is not None:
                    mw = {seqw[x] for x in range(span[m][0], span[m][1] + 1) if x in seqw}
                    cov = round(len(gw & mw) / len(mw), 3) if mw else None
                nl.append({"direction": "heb_to_grc", "edition": ed, "node_id": f"{ed}:{hv[0]}.{hv[1]}.{hv[2]}.{s['seg']}",
                           "words": len(toks), "parts": None, "linked_words": sum(1 for t in toks if by_htok[ed].get(t)),
                           "hebrew_tokens": len(toks), "hebrew_span": len(toks), "inside_share": None, "hebrew_segments": 1,
                           "other_node": f"grc:{m}" if m is not None else "", "coverage": cov})

    write(out / "by" / "parts.parquet", parts_rows)
    write(out / "by" / "part_links.parquet", links)
    write(out / "by" / "nodes.parquet", node_rows)
    write(out / "by" / "node_links.parquet", nl)

    # --- GLAUx (CC BY-SA) ---
    cw = list(csv.DictReader(open(a.crosswalk, encoding="utf-8"), delimiter="\t"))
    write(out / "by-sa" / "crosswalk.parquet", cw)
    g2m = {r["glaux_id"]: r["macula_id"] for r in cw if r["glaux_id"] and r["macula_id"]}
    gw_rows, kids = [], collections.defaultdict(list)
    for f in sorted(a.glaux.glob("0031-0*.xml")):
        for s in ET.parse(f).getroot().iter("sentence"):
            ids = {w.get("id") for w in s.iter("word")}
            for w in s.iter("word"):
                h = w.get("head") if w.get("head") in ids else ""
                gw_rows.append({"glaux_id": w.get("id"), "document": f.stem, "sentence": s.get("id"), "form": w.get("form"),
                                "lemma": w.get("lemma"), "postag": w.get("postag"), "head": h, "relation": w.get("relation"),
                                "artificial": w.get("artificial") or "", "macula_id": g2m.get(w.get("id"), "")})
                if h:
                    kids[h].append(w.get("id"))
    write(out / "by-sa" / "glaux_words.parquet", gw_rows)
    sub, cycles = {}, [0]

    def subtree(i):
        if i not in sub:
            acc, stack, seen = [], [i], set()
            while stack:
                x = stack.pop()
                if x in seen:
                    cycles[0] += 1; continue                # a head cycle in the source: each word once
                seen.add(x); acc.append(x); stack.extend(kids.get(x, []))
            sub[i] = acc
        return sub[i]

    gl = []
    for r in gw_rows:
        if not kids.get(r["glaux_id"]):
            continue                                       # leaves: the word itself is in part_links already
        words = {g2m[x] for x in subtree(r["glaux_id"]) if x in g2m}
        m = lca([wseq[w] for w in words if w in wseq])
        for ed in heb:
            toks = set().union(*(by_greek[ed].get(w, set()) for w in words)) if words else set()
            lo, hi, k, share, seg, nseg = heb_span(ed, toks, words)
            gl.append({"edition": ed, "glaux_id": r["glaux_id"], "relation": r["relation"], "subtree_words": len(words),
                       "hebrew_tokens": k, "hebrew_span": (hi - lo + 1) if k else 0, "inside_share": share,
                       "hebrew_segment": seg, "hebrew_segments": nseg, "macula_node": f"grc:{m}" if m is not None else ""})
    write(out / "by-sa" / "glaux_node_links.parquet", gl)
    rep["glaux_head_cycles_met"] = cycles[0]

    rep["rows"] = {"parts": len(parts_rows), "part_links": len(links), "nodes": len(node_rows), "node_links": len(nl),
                   "crosswalk": len(cw), "glaux_words": len(gw_rows), "glaux_node_links": len(gl)}
    (out / "report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(rep, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
