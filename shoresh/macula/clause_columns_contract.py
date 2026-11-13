"""Contract check: our clause columns (macula.build_clause_columns) against make-tanakh-research's published bcv-commons/clause-columns.

    python -m macula.build_clause_columns --check-only --check <snapshot of bcv-commons/clause-columns at 8a132e44>

Writes into the build's folder:
  contract.tsv   one row per (testament, column): joined rows compared, agreements, rate, verdict
  examples.tsv   up to 10 clause keys per main disagreement type (keys only)
  checks.md      join rate, then per column the agreement, the confusion table of disagreements, the diagnostics and the verdict

Rows join by clause key (Hebrew clause_key; Greek the segment's first word). Research's closed chapters (GEN 22, 37, 44) have no
layer columns in its table and are left out of the comparison. A value is compared as text; null and "" are the same.
"""
from __future__ import annotations

import collections
import csv
import glob
import json
import os
from pathlib import Path

from macula import build_clause_columns as bc

# columns compared, per testament; "id" columns (word ids, lemmas, forms) get kinds of disagreement instead of value pairs
HEB = ["verb", "conj", "voice", "neg", "speech", "speaker", "frame", "genre", "line", "actor", "undergoer", "args", "subj", "subj_switch",
       "lxx_form", "lxx_tense", "lxx_mood", "neg_scope", "subj_form", "part", "part_switch", "front", "focus", "m_trans", "subj_role",
       "recip"]
GRC = ["verb", "conj", "voice", "neg", "speech", "speaker", "genre", "line", "actor", "undergoer", "neg_scope", "subj_form", "part",
       "part_switch", "front", "focus", "m_trans", "subj_role", "recip"]
LAYOUT_HEB = {"kind": "kind", "rule": "rule", "relation": "relation", "parent": "parent_key", "depth": "depth"}
LAYOUT_GRC = {"kind": "kind", "rule": "rule", "parent": "parent", "depth": "depth"}
IDS = {"verb", "speaker", "frame", "args", "subj", "lxx_form", "part", "rule", "parent"}

# Verdicts, written after reading the figures of the 2026-11-13 run (checks.md carries the evidence for each).
SPLIT = ("differs by error (research's): a clause the layout splits into several segments (2,263 keys) is read from one segment "
         "(verb from the last, word order from the first); research's reading replicated from our stores agrees 1.0000")
VERDICT = {("hebrew", c): SPLIT for c in HEB}
VERDICT.update({
    ("hebrew", "genre"): "equal",
    ("hebrew", "lxx_form"): SPLIT + "; 2 clauses: MACULA revision (our store has no Septuagint form there)",
    ("hebrew", "lxx_tense"): SPLIT + "; plus differs by design: the parse of the form in its own GLAUx verse first (lxx_basis verse)",
    ("hebrew", "lxx_mood"): SPLIT + "; plus differs by design: the parse of the form in its own GLAUx verse first (lxx_basis verse)",
})
VERDICT.update({("hebrew", f"layout.{c}"): "equal (same layout, v0.37)" for c in LAYOUT_HEB})
VERDICT.update({("greek-nt", c): "equal" for c in GRC})
VERDICT.update({("greek-nt", f"layout.{c}"): "equal" for c in LAYOUT_GRC})
VERDICT.update({
    ("greek-nt", "speaker"): "differs by design: our current Greek layout's speaker ids; every disagreement is the v0.5 layout's id",
    ("greek-nt", "actor"): "differs by design: MACULA tree roles and Greek frames (A0 inside / outside the clause, subjref), as the "
                           "Hebrew definition; research's word-own-role rule replicated from our stores agrees 1.0000",
    ("greek-nt", "undergoer"): "differs by design: tree roles o / o2 and Greek frames (A1 inside overt, outside implicit), as the "
                               "Hebrew definition; research's word-own-role rule replicated from our stores agrees 1.0000",
})
NOTES: dict[tuple[str, str], str] = {}


def _norm(x) -> str:
    if x is None:
        return ""
    if isinstance(x, bool):
        return str(int(x))
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)


def _read(path: Path) -> dict[str, dict]:
    import pyarrow.parquet as pq
    return {r["clause_key"]: r for r in pq.read_table(path).to_pylist()}


def _kind(a: str, b: str) -> str:
    if not a:
        return "ours empty"
    if not b:
        return "research empty"
    return "both filled, differ"


def _multi_segment_keys() -> set[str]:
    c = collections.Counter()
    for f in glob.glob(str(bc.HEB_LAYOUT / "*" / "*.jsonl")):
        for l in open(f, encoding="utf-8"):
            c[json.loads(l)["clause_key"]] += 1
    return {k for k, n in c.items() if n > 1}


def _layout_first(root: Path, key: str) -> dict[str, dict]:
    out = {}
    for f in glob.glob(str(root / "*" / "*.jsonl")):
        for l in open(f, encoding="utf-8"):
            r = json.loads(l)
            out.setdefault(r[key], r)
    return out


def compare(name, ours, theirs, cols, layout=None, layout_map=None, diag=None):
    """-> (join stats, per-column results)"""
    t_rows = {k: v for k, v in theirs.items() if v.get("genre") is not None}      # rows with layer columns
    closed = len(theirs) - len(t_rows)
    o_rows = {k: v for k, v in ours.items() if (v["ref"].split()[0], int(v["ref"].split()[1].split(":")[0])) not in bc.NEVER}
    joined = sorted(set(t_rows) & set(o_rows))
    join = dict(research_rows=len(theirs), research_closed_chapters=closed, research_compared=len(t_rows), ours_rows=len(ours),
                ours_outside_closed=len(o_rows), joined=len(joined), research_only=len(set(t_rows) - set(o_rows)),
                ours_only=len(set(o_rows) - set(t_rows)), join_rate_research=len(joined) / max(1, len(t_rows)),
                join_rate_ours=len(joined) / max(1, len(o_rows)))
    res = []
    items = [(c, c, "ours") for c in cols] + [(c, src, "layout") for c, src in (layout_map or {}).items()]
    for col, src, side in items:
        conf, ex, agree = collections.Counter(), collections.defaultdict(list), 0
        for k in joined:
            a = _norm(o_rows[k].get(src)) if side == "ours" else _norm((layout.get(k) or {}).get(src))
            b = _norm(t_rows[k].get(col))
            if a == b:
                agree += 1
                continue
            t = _kind(a, b) if col in IDS else f"{a or '∅'} / {b or '∅'}"
            conf[t] += 1
            if len(ex[t]) < 10:
                ex[t].append(k)
        d = diag(col, joined, o_rows, t_rows) if diag else None
        res.append(dict(testament=name, column=col if side == "ours" else f"layout.{col}", n=len(joined), agree=agree,
                        rate=agree / max(1, len(joined)), confusion=conf, examples=ex, diag=d))
    return join, res


def _heb_diag(multi, replica):
    def diag(col, joined, ours, theirs):
        out = []
        if col not in ours[joined[0]]:
            return out
        dis = [k for k in joined if _norm(ours[k].get(col)) != _norm(theirs[k].get(col))]
        rep = sum(1 for k in joined if _norm(replica[k].get(col)) == _norm(theirs[k].get(col)))
        out.append(f"replica of research's reading (split clauses read as research reads them, layer's last row per key, Septuagint "
                   f"parse by form only), from our stores: agrees on {rep:,} of {len(joined):,} ({rep / len(joined):.4f})")
        if not dis:
            return out
        m = sum(1 for k in dis if k in multi)
        out.append(f"{m} of {len(dis)} disagreements are on clause keys the layout splits into several segments "
                   f"({len(multi & set(joined))} of {len(joined)} joined keys are such)")
        if col in ("lxx_tense", "lxx_mood"):
            by = collections.Counter(ours[k].get("lxx_basis") or "" for k in dis)
            allb = collections.Counter(ours[k].get("lxx_basis") or "" for k in joined)
            out.append("disagreements by our basis: " + ", ".join(f"{b or '∅'} {n} of {allb[b]}" for b, n in by.most_common()))
        if col == "undergoer":
            fr = sum(1 for k in dis if _norm(ours[k][col]) == "implicit" and _norm(theirs[k][col]) == "none")
            out.append(f"{fr} of {len(dis)}: ours implicit, research none")
        return out
    return diag


def _grc_diag(S):
    def diag(col, joined, ours, theirs):
        out = []
        dis = [k for k in joined if _norm(ours[k].get(col)) != _norm(theirs[k].get(col))]
        if dis and col == "speaker":
            v05 = _greek_v05_speakers()
            if v05:
                same = sum(1 for k in dis if v05.get(k, "") == _norm(theirs[k][col]))
                out.append(f"{same} of {len(dis)} disagreements are the Greek layout v0.5's speaker_id (HF 22143094), the layout "
                           "research's table was built on")
            return out
        if not dis or col not in ("actor", "undergoer"):
            return out
        # research's rule: the word's own role only (MACULA Greek word role), no frames
        agree = 0
        for k in joined:
            r = ours[k]
            roles = {S.G.get(w, [""] * 12)[11] for w in _words(k)}
            finite = (r.get("conj") or "").split("_")[-1] in bc.FINITE_G
            if col == "actor":
                v = "overt" if "s" in roles else ("implicit" if finite else "none")
            else:
                v = "overt" if roles & {"o", "o2"} else "none"
            agree += v == _norm(theirs[k][col])
        out.append(f"research's rule (word's own role, no tree, no frames) recomputed from our stores agrees on {agree} of "
                   f"{len(joined)} ({agree / len(joined):.4f})")
        return out
    return diag


def _greek_v05_speakers() -> dict[str, str]:
    import pyarrow.parquet as pq
    out = {}
    for f in glob.glob(os.path.expanduser("~/.cache/huggingface/hub/datasets--bcv-commons--greek-nt-clause-layout/snapshots/"
                                          "22143094*/data/*.parquet")):
        for r in pq.read_table(f, columns=["first", "speaker_id"]).to_pylist():
            out[r["first"]] = r["speaker_id"] or ""
    return out


_GW: dict[str, list] = {}


def _words(k):
    if not _GW:
        for f in glob.glob(str(bc.GRC_LAYOUT / "*" / "*.jsonl")):
            for l in open(f, encoding="utf-8"):
                r = json.loads(l)
                _GW[r["first"]] = r["words"]
    return _GW.get(k, [])


def run(out: Path, snap: Path) -> None:
    heb_o, grc_o = _read(out / "hebrew.parquet"), _read(out / "greek-nt.parquet")
    heb_t, grc_t = _read(snap / "data" / "hebrew.parquet"), _read(snap / "data" / "greek-nt.parquet")
    multi = _multi_segment_keys()
    S = bc.Stores()
    replica = {r["clause_key"]: r for r in bc.hebrew(S, replica=True)}
    hj, hr = compare("hebrew", heb_o, heb_t, HEB, _layout_first(bc.HEB_LAYOUT, "clause_key"), LAYOUT_HEB, _heb_diag(multi, replica))
    gj, gr = compare("greek-nt", grc_o, grc_t, GRC, _layout_first(bc.GRC_LAYOUT, "first"), LAYOUT_GRC, _grc_diag(S))
    results = hr + gr
    with open(out / "contract.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["testament", "column", "joined", "agree", "rate", "verdict"])
        for r in results:
            w.writerow([r["testament"], r["column"], r["n"], r["agree"], f"{r['rate']:.4f}",
                        VERDICT.get((r["testament"], r["column"]), "")])
    with open(out / "examples.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["testament", "column", "disagreement (ours / research)", "count", "clause_keys"])
        for r in results:
            for t, n in r["confusion"].most_common(5):
                w.writerow([r["testament"], r["column"], t, n, " ".join(r["examples"][t])])
    md = ["# Clause columns: contract check against bcv-commons/clause-columns (revision 8a132e44)", "",
          "Ours: `macula/build_clause_columns.py` (this folder's hebrew.parquet, greek-nt.parquet). Research's: the published table, "
          "built 2026-11-02 from the Hebrew layout v0.37 (514a8832) and the Greek layout v0.5 (22143094). Join by clause key; "
          "research's closed chapters (GEN 22, 37, 44) carry no layer columns and are left out. Values compared as text (null = \"\"). "
          "Example clause keys per disagreement type are in examples.tsv.", "", "## Join", "",
          "| | research rows | of them closed chapters | compared | ours | ours outside closed chapters | joined | research only | "
          "ours only | join rate (of research) | join rate (of ours) |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, j in (("hebrew", hj), ("greek-nt", gj)):
        md.append(f"| {n} | {j['research_rows']:,} | {j['research_closed_chapters']:,} | {j['research_compared']:,} | {j['ours_rows']:,} | "
                  f"{j['ours_outside_closed']:,} | {j['joined']:,} | {j['research_only']:,} | {j['ours_only']:,} | "
                  f"{j['join_rate_research']:.4f} | {j['join_rate_ours']:.4f} |")
    md += ["", "## Agreement per column", "", "| testament | column | joined | agree | rate | verdict |", "|---|---|---|---|---|---|"]
    for r in results:
        md.append(f"| {r['testament']} | `{r['column']}` | {r['n']:,} | {r['agree']:,} | {r['rate']:.4f} | "
                  f"{VERDICT.get((r['testament'], r['column']), '')} |")
    md += ["", "Columns of ours with no counterpart in research's table (not compared): Hebrew `speaker_id` (the layer's character id, "
           "as the Greek layout uses), `lxx_basis` (verse | form); Greek `args`, `subj`, `subj_switch` (from the Greek frames and "
           "references). Research columns not rebuilt here: copies of layout columns (`kind`, `rule`, `relation`, `discourse`, `via`, "
           "`role`, `junction`, `parent`, `depth`: checked above as layout identity), morphology (`stem`, `person`, `number`, "
           "`gender`, `strong`, `causative`, `interrog`: in the spine), `force` / `legal_future` (the layouts' own `force` codes), "
           "`juncture` / `nexus` (wave 2, clause relation), `akt` / `akt_p` / `juss_p` (Jev model answers: model layer, not source "
           "facts), `heb_form` (research's private Delitzsch alignment and tagger).", "", "## Disagreements", ""]
    for r in results:
        if not r["confusion"] and not r["diag"]:
            continue
        md += [f"### {r['testament']} `{r['column']}`: {r['n'] - r['agree']:,} disagreements", ""]
        if NOTES.get((r["testament"], r["column"])):
            md += [NOTES[(r["testament"], r["column"])], ""]
        md += ["| ours / research | clauses | examples |", "|---|---|---|"]
        for t, n in r["confusion"].most_common(8):
            md.append(f"| {t} | {n:,} | {' '.join(r['examples'][t][:3])} |")
        if r["diag"]:
            md += [""] + [f"- {x}" for x in r["diag"]]
        md.append("")
    (out / "checks.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    for r in results:
        print(f"{r['testament']:9} {r['column']:16} {r['rate']:.4f}  {dict(r['confusion'].most_common(4))}")
        for d in r["diag"] or []:
            print("           ", d)
    print(json.dumps({"hebrew": hj, "greek-nt": gj}, indent=1))
