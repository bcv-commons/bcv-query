"""Clause-keyed retrieval columns for research's ranking test (example-graph plan, A2): per clause its argument roles, its
connective relation and its speech level, read from a source-ontology release. Nothing is uploaded.

    cd shoresh && .venv/bin/python -m macula.export_clause_keys --ontology DIR --out OUT

OUT gets clause_keys.parquet and build.json (the ontology's tag and code, its inputs, the file's sha256). Columns:
  clause     MACULA clause key (its first word; Tanakh 12 digits, Greek NT 11), as in every bcv-commons clause dataset
  lang       hbo / grc
  speech     speech level (0 = narration), clause-columns
  roles      the semantic roles of the clause's arguments, sorted, joined by "+" (argument-roles; empty where none is assigned)
  pp_roles   the same for prepositional constituents only
  grams      the grammatical relations of its arguments, sorted with repeats, joined by "+"
  link_type, relation, connective, link_basis   the clause's link to another clause (clause-connectives): type, relation,
             the connective as written, and whether the target is the layout's or the previous clause
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

GRAMS = {"pp", "s", "o", "adv", "p", "io", "o2"}        # where no role is assigned the ontology repeats the relation


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ontology", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    src, out = Path(a.ontology), Path(a.out)
    if out.exists():
        raise SystemExit(f"{out} exists; give a folder that does not exist yet")
    import pyarrow as pa
    import pyarrow.parquet as pq
    roles, pp, grams, link = collections.defaultdict(set), collections.defaultdict(set), collections.defaultdict(list), {}
    for r in pq.read_table(src / "data" / "prop_relations.parquet").to_pylist():
        k = r["subject"][5:]
        if r["relation"] == "has_argument":
            grams[k].append(r["gram"])
            if r["tier"] and r["tier"] not in GRAMS:
                roles[k].add(r["tier"])
                if r["gram"] == "pp":
                    pp[k].add(r["tier"])
        elif r["relation"] == "linked_to":
            link[k] = (r["tier"], r["gram"], r["word"], r["target_basis"])
    rows = []
    for p in pq.read_table(src / "data" / "propositions.parquet", columns=["prop", "lang", "speech"]).to_pylist():
        k = p["prop"][5:]
        lt, rel, word, basis = link.get(k, ("", "", "", ""))
        rows.append({"clause": k, "lang": p["lang"], "speech": p["speech"], "roles": "+".join(sorted(roles[k])),
                     "pp_roles": "+".join(sorted(pp[k])), "grams": "+".join(sorted(grams[k])),
                     "link_type": lt, "relation": rel, "connective": word, "link_basis": basis})
    out.mkdir(parents=True)
    f = out / "clause_keys.parquet"
    pq.write_table(pa.Table.from_pylist(rows), f, compression="zstd")
    b = json.loads((src / "build.json").read_text())
    bp = json.loads((src / "build-propositions.json").read_text())
    n = collections.Counter(r["lang"] for r in rows)
    build = {"source_ontology": {"tag": b["tag"], "code": b["code"]}, "inputs": bp["inputs"], "rows": dict(n),
             "with_roles": sum(1 for r in rows if r["roles"]), "with_pp_roles": sum(1 for r in rows if r["pp_roles"]),
             "with_relation": sum(1 for r in rows if r["relation"]),
             "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}
    (out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(build, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
