"""READ-FIRST.md of a source example (SPEC 1.0, 4.10): the reading sheet, so the examples give the normal ranges.

    shoresh/.venv/bin/python -I shoresh/macula/examples_read_sheet.py LANG_DIR LANG [--out FILE.md]

Adapted from internal-docs/source-examples-work/tools/read_sheet.py to the tables of the specification. It reads only
the built tables of one language and counts nothing against the source. Section 1 gives the whole-text figures a
description in this format can be read against (the normal ranges); section 2 the commonest written forms with what the
tables say of them; section 3 the forms that carry one participant nearly everywhere (a name belongs there, a small word
does not); section 4 the map onto the shared features. Every figure is a count of the tables; nothing is a score.
"""
import argparse
import collections as C
import json
import os
import statistics
import sys

import pyarrow.parquet as pq

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import examples_common as X  # noqa: E402

NAMES = {"hbo": "Hebrew of the Tanakh", "arc": "Aramaic of the Tanakh", "grc": "Greek of the New Testament"}


def _pc(x, y):
    return f"{x / y:.3f}" if y else "-"


def _tsv(path):
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    head = lines[0].split("\t")
    return [dict(zip(head, ln.split("\t"))) for ln in lines[1:] if ln]


def _split(counter, total, n=8):
    return ", ".join(f"`{'(empty)' if k in ('', None) else k}` {v:,} ({_pc(v, total)})" for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n])


def _quantiles(vals):
    if not vals:
        return "-"
    s = sorted(vals)
    q = lambda p: s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))]  # noqa: E731
    return f"median {q(0.5)}, 90% {q(0.9)}, 99% {q(0.99)}, max {s[-1]}"


def sheet(d, lang):
    W = pq.read_table(os.path.join(d, "words.parquet"),
                      columns=["t", "sentence", "text", "clause", "head", "rel", "rel_shared"]).to_pylist()
    P = pq.read_table(os.path.join(d, "pieces.parquet"),
                      columns=["t", "n", "text", "kind", "class", "head_t", "who", "who_basis"]).to_pylist()
    CL = pq.read_table(os.path.join(d, "clauses.parquet"),
                       columns=["clause", "depth", "gaps", "words", "pred_kind", "marks", "quote", "speaker", "line"]).to_pylist()
    CO = pq.read_table(os.path.join(d, "constituents.parquet"), columns=["clause", "role", "sem_role", "frame_role"]).to_pylist()
    LA = pq.read_table(os.path.join(d, "link_account.parquet"), columns=["other", "state"]).to_pylist()
    PA = _tsv(os.path.join(d, "participants.tsv"))
    name = {r["ent"]: r["name"] for r in PA}
    nw, npc = len(W), len(P)
    pieces_of = C.Counter(p["t"] for p in P)
    stem = {p["t"]: p for p in P if p["kind"] == "stem"}
    who_w = {p["t"] for p in P if p["who"]}
    sents = len({w["sentence"] for w in W})
    roots = sum(1 for w in W if w["head"] == 0)
    dist = [abs(w["t"] - w["head"]) for w in W if w["head"] != 0]
    norm = X.norm_grc if lang == "grc" else X.norm_heb
    L = [f"# Reading sheet: {NAMES[lang]} (`{lang}`)", "",
         "Written by `build_examples.py --stage 10` (`examples_read_sheet.py`) from this folder's tables. No figure here is",
         "a score; every one is a count of the tables. Read sections 2 and 3 with a glossed chapter beside you",
         "(`internal-docs/source-examples-work/glossed/`). The columns are in `COLUMNS.md`, the exit conditions in",
         "`VALIDATION.md`. A description of another language in this format can be read against section 1: these are the",
         "ranges a closed text gives when every value comes from its sources.", "", "## 1. Whole text (the normal ranges)", ""]
    kinds = C.Counter(min(v, 3) for v in pieces_of.values())
    L += [f"- words: {nw:,}; pieces: {npc:,} ({npc / nw:.3f} per word; words of 1 piece {_pc(kinds[1], nw)}, of 2 "
          f"{_pc(kinds[2], nw)}, of 3 or more {_pc(kinds[3], nw)})",
          f"- pieces by kind: {_split(C.Counter(p['kind'] for p in P), npc)}",
          f"- sentences: {sents:,} ({nw / sents:.1f} words each); roots (words with head 0): {roots:,} ({_pc(roots, nw)}; "
          f"one per sentence would be {_pc(sents, nw)})",
          f"- distance from a word to its head, in words: {_quantiles(dist)}",
          f"- words whose head is the word next to it: {_pc(sum(1 for x in dist if x == 1), len(dist))}",
          f"- word labels (`rel`): {len({w['rel'] for w in W}):,} distinct; commonest: {_split(C.Counter(w['rel'] for w in W), nw, 6)}",
          f"- shared relation `none`: {sum(1 for w in W if w['rel_shared'] == 'none'):,} words "
          f"({_pc(sum(1 for w in W if w['rel_shared'] == 'none'), nw)}); commonest shared: "
          f"{_split(C.Counter(w['rel_shared'] for w in W), nw, 6)}",
          f"- word classes (stem piece): {_split(C.Counter(stem[t]['class'] for t in stem), nw, 10)}",
          f"- words outside every clause: {sum(1 for w in W if not w['clause']):,} ({_pc(sum(1 for w in W if not w['clause']), nw)})"]
    ncl = len(CL)
    marks = [json.loads(c["marks"]) for c in CL]
    one = sum(1 for c in CL if c["words"] == 1)
    L += [f"- clauses: {ncl:,} ({ncl / sents:.2f} per sentence); depth: {_split(C.Counter(min(c['depth'], 4) for c in CL), ncl, 5)} "
          "(4 = 4 or more)",
          f"- clauses with gaps: {sum(1 for c in CL if c['gaps']):,} ({_pc(sum(1 for c in CL if c['gaps']), ncl)}); "
          f"whose own words number 1: {one:,} ({_pc(one, ncl)}); with no own word: "
          f"{sum(1 for c in CL if c['words'] == 0):,}",
          f"- predicate kind: {_split(C.Counter(c['pred_kind'] for c in CL), ncl)}",
          f"- clause kind (`marks.kind`): {_split(C.Counter(m.get('kind', '') for m in marks), ncl)}",
          f"- clauses with any value in `marks`: {sum(1 for m in marks if m):,} ({_pc(sum(1 for m in marks if m), ncl)}); "
          f"with a `line`: {_pc(sum(1 for c in CL if c['line']), ncl)}",
          f"- clauses inside a quotation: {_pc(sum(1 for c in CL if c['quote']), ncl)}; with a speaker: "
          f"{_pc(sum(1 for c in CL if c['speaker']), ncl)}"]
    per = C.Counter(c["clause"] for c in CO)
    L += [f"- constituents: {len(CO):,} ({len(CO) / ncl:.2f} per clause; clauses with none: {ncl - len(per):,}); roles: "
          f"{_split(C.Counter(c['role'] for c in CO), len(CO), 10)}",
          f"- constituents with a frame role: {_pc(sum(1 for c in CO if c['frame_role']), len(CO))}; with a semantic role: "
          f"{_pc(sum(1 for c in CO if c['sem_role']), len(CO))}",
          f"- pieces with a participant: {sum(1 for p in P if p['who']):,} ({_pc(sum(1 for p in P if p['who']), npc)}); "
          f"words: {len(who_w):,} ({_pc(len(who_w), nw)}); by basis: "
          f"{_split(C.Counter(p['who_basis'] for p in P if p['who']), sum(1 for p in P if p['who']))}",
          f"- participants: {len(PA):,}; by type: {_split(C.Counter(r['type'] for r in PA), len(PA))}; with a name: "
          f"{_pc(sum(1 for r in PA if r['name']), len(PA))}"]
    for other in sorted({r["other"] for r in LA}):
        st = C.Counter(r["state"] for r in LA if r["other"] == other)
        L.append(f"- pieces against `{other}`: {_split(st, sum(st.values()))}")
    stats = []
    for tb in ("forms", "paradigms", "markers", "constructions", "orders", "agreement", "frames", "pairs", "clause_links"):
        t = pq.read_table(os.path.join(d, f"{tb}.parquet"), columns=["count", "against"]).to_pylist()
        c, a = sum(r["count"] for r in t), sum(r["against"] for r in t)
        stats.append(f"`{tb}` {len(t):,} rows (against {_pc(a, c + a)} of places)")
    L += ["- statement tables: " + "; ".join(stats)]
    prof = _tsv(os.path.join(d, "profile.tsv"))
    L += [f"- questionnaire rows answered from counts: {sum(1 for r in prof if r['value'] != '?')} of {len(prof)}", ""]

    by = C.defaultdict(list)
    for w in W:
        by[norm(w["text"])].append(w)
    top = sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:60]
    L += ["## 2. The 60 commonest written forms", "",
          "A form is the word's normalised text (SPEC 7). `root`: the share of its places with head 0. `participant`: the share "
          "with a participant on any piece, and the commonest one with its share of those.", "",
          "| form | places | class (share) | root | commonest label | participant | the commonest one |", "|---|---|---|---|---|---|---|"]
    for f, ws in top:
        cl = C.Counter(stem[w["t"]]["class"] for w in ws)
        rl = sorted(C.Counter(w["rel"] for w in ws).items(), key=lambda kv: (-kv[1], kv[0]))[0]
        wp = C.Counter()
        for w in ws:
            ents = sorted({e for p in pieces_by_t(P)[w["t"]] for e in p["who"].split() if e})
            if ents:
                wp[" ".join(ents)] += 1
        n_with = sum(wp.values())
        topwho = sorted(wp.items(), key=lambda kv: (-kv[1], kv[0]))[0] if wp else None
        L.append(f"| {f} | {len(ws):,} | " + ", ".join(f"{k} {_pc(v, len(ws))}" for k, v in sorted(cl.items(), key=lambda kv: (-kv[1], kv[0]))[:2])
                 + f" | {_pc(sum(1 for w in ws if w['head'] == 0), len(ws))} | "
                 + f"{rl[0]} {_pc(rl[1], len(ws))} | {_pc(n_with, len(ws))} | "
                 + (f"{_ent(topwho[0], name)} ({_pc(topwho[1], n_with)})" if topwho else "-") + " |")
    fixed = []
    for f, ws in by.items():
        wp = C.Counter()
        for w in ws:
            ents = sorted({e for p in pieces_by_t(P)[w["t"]] for e in p["who"].split() if e})
            if ents:
                wp[" ".join(ents)] += 1
        if len(ws) >= 20 and wp:
            k, v = sorted(wp.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            if v >= 0.95 * len(ws):
                cl = C.Counter(stem[w["t"]]["class"] for w in ws)
                fixed.append((len(ws), f, k, sorted(cl.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]))
    fixed.sort(key=lambda x: (-x[0], x[1]))
    L += ["", f"## 3. Forms with one participant in 0.95 or more of their places ({len(fixed)} forms of 20 places or more; "
          f"{sum(x[0] for x in fixed):,} words, {_pc(sum(x[0] for x in fixed), nw)} of the text)", "",
          "A name belongs in this list. A small word does not: it refers to whoever the clause is about, or to nobody.", "",
          "| form | places | class | the participant |", "|---|---|---|---|"]
    L += [f"| {f} | {k:,} | {c} | {_ent(p, name)} |" for k, f, p, c in fixed[:40]]
    rows = _tsv(os.path.join(d, "map.tsv"))
    vals = C.defaultdict(set)
    for r in rows:
        vals[(r["table"], r["category"], r["code"])].add("none" if r["feature"] == "none" else f"{r['feature']}={r['value']}")
    none = sorted(k for k, v in vals.items() if v == {"none"})
    multi = {k: v for k, v in vals.items() if len({x.split("=")[0] for x in v if x != "none"}) > 1}
    reasons = C.Counter(r["reason"] for r in rows if r["feature"] == "none")
    L += ["", "## 4. The map onto the shared features (`map.tsv`)", "",
          f"- codes: {len(vals)}; mapped: {len(vals) - len(none)}; `none`: {len(none)} (by reason: "
          + ", ".join(f"`{k}` {v}" for k, v in sorted(reasons.items())) + ")",
          "- one code on two or more features (look at each): "
          + ("; ".join(f"{'.'.join(k)} → {', '.join(sorted(v))}" for k, v in sorted(multi.items())) or "none"), ""]
    return "\n".join(L) + "\n"


_PBT = {}


def pieces_by_t(P):
    key = id(P)
    if key not in _PBT:
        m = C.defaultdict(list)
        for p in P:
            m[p["t"]].append(p)
        _PBT.clear()
        _PBT[key] = m
    return _PBT[key]


def _ent(keys, name):
    return " ".join(f"`{k}`" + (f" {name[k]}" if name.get(k) else "") for k in keys.split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("langdir")
    ap.add_argument("lang", choices=sorted(NAMES))
    ap.add_argument("--out")
    a = ap.parse_args()
    out = a.out or os.path.join(a.langdir, "READ-FIRST.md")
    X.write_text(out, sheet(a.langdir, a.lang))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
