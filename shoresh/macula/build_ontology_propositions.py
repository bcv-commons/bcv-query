"""Source-side ontology, phase 3: propositions (internal-docs/ontology-design-note-2026-11-17.md). Local, not published.

    cd shoresh && .venv/bin/python -m macula.build_ontology_propositions --out macula/data/source-ontology

One proposition per clause of the Hebrew and the Greek NT clause layouts, `prop:<clause key>` (the clause's first MACULA word,
the key every clause dataset shares). From the published clause datasets (local copies; versions in build.json):
  clause-columns v1.2     predicate (the verb word), voice, negation and its scope, force, kind, speech level and speaker,
                          narrative line, genre, front and focus, subject switch
  argument-roles v0.2     arguments: the head word, the grammatical relation (s, o, o2, pp, adv, p) and the role
                          (actor, undergoer, location, recipient …) with the role's basis
  time-aspect v0.2        time and aspect, with basis
  clause-connectives v0.1 the connective word, its link type and relation (to the clause before, in text order)

OUT gets propositions.parquet (one row per proposition: features, each with the dataset it comes from in build.json) and
prop_relations.parquet (subject, relation, object, tier, source):
  has_predicate   prop -> mention (w:<verb word>)
  has_argument    prop -> mention (w:<head word>), tier = role or, without one, the relation; `relation` kept in `gram`
  linked_to       prop -> the clause it attaches to in the clause layout (Hebrew discourse_parent, Greek parent; local
                  builds), else the previous prop of the same book (`target_basis` layout | previous); tier = the link type,
                  `gram` = the relation, `word` = the connective as written
and prop_accuracy.parquet: S2's audit figures per language and feature (blind samples of 100 clauses judged from the text alone;
internal-docs/clause-structure-work/s2-figures-2026-11-17.md): feature, figure, n, sample, basis (a code: same_word,
verb_morphology, present, same_scope, both_named). A feature not listed (the roles of has_argument among them) has not been checked.
No English content: feature values are the datasets' codes; the connective is Hebrew or Greek.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS = HERE.parents[1] / "internal-docs"
INPUTS = {
    "clause-columns": ("v1.2", "32beff0b", DOCS / "clause-columns-release" / "v1.2" / "data"),
    "argument-roles": ("v0.2", "5065acab", DOCS / "argument-roles-release" / "v0.2" / "data"),
    "time-aspect": ("v0.2", "5d30d2c2", DOCS / "time-aspect-release" / "v0.2" / "data"),
    "clause-connectives": ("v0.1", "c26a84be", DOCS / "clause-connectives-release" / "v0.1" / "data"),
}
LAYOUT = {"hebrew": HERE / "data" / "clause-layout" / "clauses", "greek-nt": HERE / "data" / "nt-clause-layout" / "clauses"}


def layout_parents(side: str) -> dict[str, str]:
    """clause key -> the clause it attaches to in the clause layout (Hebrew `discourse_parent`, Greek `parent`; local builds)."""
    out = {}
    for f in LAYOUT[side].glob("*/*.jsonl"):
        for line in f.open(encoding="utf-8"):
            r = json.loads(line)
            k = r.get("clause_key") or r.get("clause")
            par = r.get("discourse_parent") if side == "hebrew" else r.get("parent")
            if k and par:
                out[k] = par
    return out


# S2 (clause-columns v1.1 Hebrew sample, seed 1119; v1.2 fresh Greek sample, seed 2611): exact agreement with the blind judge.
# Hebrew columns are unchanged from v1.1 to v1.2. person, number, gender, voice follow the main verb's MACULA morphology.
ACCURACY = [
    # lang, feature, figure, n, sample, basis
    ("hbo", "has_predicate", 0.97, 100, "s2:1119:v1.1", "same_word"),
    ("hbo", "voice", 0.97, 100, "s2:1119:v1.1", "verb_morphology"),
    ("hbo", "neg", 1.00, 100, "s2:1119:v1.1", "present"),
    ("hbo", "neg_scope", 0.98, 100, "s2:1119:v1.1", "same_scope"),
    ("hbo", "subj_switch", 0.931, 87, "s2:1119:v1.1", "both_named"),
    ("grc", "has_predicate", 1.00, 100, "s2:2611:v1.2", "same_word"),
    ("grc", "voice", 1.00, 100, "s2:2611:v1.2", "verb_morphology"),
    ("grc", "neg", 1.00, 100, "s2:2611:v1.2", "present"),
    ("grc", "neg_scope", 0.99, 100, "s2:2611:v1.2", "same_scope"),
    ("grc", "subj_switch", 0.954, 87, "s2:2611:v1.2", "both_named"),
]

FEATURES = ("ref", "voice", "neg", "neg_scope", "force", "kind", "interrog", "speech", "speaker_id", "line", "genre", "front",
            "focus", "subj_switch", "part_switch", "causative")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    import pyarrow as pa
    import pyarrow.parquet as pq
    props, rel = [], []
    st = collections.Counter()
    mention = lambda k: f"w:{k.lstrip('n')}" if k else None
    for side in ("hebrew", "greek-nt"):
        lang = "hbo" if side == "hebrew" else "grc"
        cc = pq.read_table(INPUTS["clause-columns"][2] / f"{side}.parquet").to_pylist()
        ta = {r["clause_key"]: r for r in pq.read_table(INPUTS["time-aspect"][2] / f"{side}.parquet").to_pylist()}
        cn = {r["clause_key"]: r for r in pq.read_table(INPUTS["clause-connectives"][2] / f"{side}.parquet").to_pylist()}
        prev_by_book: dict[str, str] = {}
        parents = layout_parents(side)
        known = {r["clause_key"] for r in cc}
        order = sorted(cc, key=lambda r: r["clause_key"])
        for r in order:
            k = r["clause_key"]
            p = f"prop:{k}"
            t = ta.get(k, {})
            row = {"prop": p, "lang": lang, **{f: r.get(f) for f in FEATURES},
                   "time": t.get("time"), "aspect": t.get("aspect"), "time_basis": t.get("basis")}
            for f in ("neg", "interrog", "causative"):
                if row[f] is not None:
                    row[f] = bool(row[f])
            if row["speech"] is not None:
                row["speech"] = int(row["speech"])
            props.append(row)
            st[lang, "props"] += 1
            if r.get("verb"):
                rel.append({"subject": p, "relation": "has_predicate", "object": mention(r["verb"]), "tier": "", "gram": "",
                            "word": "", "source": "clause-columns@v1.2", "target_basis": ""})
            book = (r.get("ref") or "").split()[0]
            c = cn.get(k)
            if c and book in prev_by_book and (c.get("link") or c.get("relation")):
                par = parents.get(k)
                target, basis = (f"prop:{par}", "layout") if par in known else (prev_by_book[book], "previous")
                rel.append({"subject": p, "relation": "linked_to", "object": target, "tier": c.get("link") or "",
                            "gram": c.get("relation") or "", "word": c.get("conn") or "", "source": "clause-connectives@v0.1",
                            "target_basis": basis})
                st[lang, "linked_to", basis] += 1
            prev_by_book[book] = p
        for r in pq.read_table(INPUTS["argument-roles"][2] / f"{side}.parquet").to_pylist():
            if not r.get("head"):
                continue
            rel.append({"subject": f"prop:{r['clause_key']}", "relation": "has_argument", "object": mention(r["head"]),
                        "tier": r.get("role") or r.get("relation") or "", "gram": r.get("relation") or "", "word": "",
                        "source": "argument-roles@v0.2", "target_basis": ""})
            st[lang, "has_argument"] += 1
    ids = {p["prop"] for p in props}
    dangling = sum(1 for r in rel if r["subject"] not in ids or (r["relation"] == "linked_to" and r["object"] not in ids))
    a.out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(props), a.out / "propositions.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(rel), a.out / "prop_relations.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist([dict(zip(("lang", "feature", "figure", "n", "sample", "basis"), r)) for r in ACCURACY]),
                   a.out / "prop_accuracy.parquet", compression="zstd")
    counts = {"props": {k[0]: v for k, v in st.items() if k[1] == "props"},
              "relations": dict(collections.Counter((r["relation"], r["source"].split("@")[0]) for r in rel).most_common()),
              "roles": dict(collections.Counter(r["tier"] for r in rel if r["relation"] == "has_argument").most_common(15)),
              "links": dict(collections.Counter(r["tier"] for r in rel if r["relation"] == "linked_to").most_common(12)),
              "linked_to_target": {f"{k[0]} {k[2]}": v for k, v in st.items() if k[1] == "linked_to"},
              "dangling": dangling}
    counts["relations"] = {f"{k[0]} ({k[1]})": v for k, v in counts["relations"].items()}
    (a.out / "build-propositions.json").write_text(json.dumps(
        {"inputs": {k: {"version": v[0], "revision": v[1]} for k, v in INPUTS.items()}, "counts": counts}, ensure_ascii=False,
        indent=1), encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
