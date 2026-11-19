"""Package bcv-commons/source-ontology: builds both ontology parts fresh into OUT/data and writes the card. Nothing is uploaded.

    cd shoresh && .venv/bin/python -m macula.release_source_ontology --tag v0.1 --out DIR [--allow-dirty]

Parts: phases 1-2a (macula/build_source_ontology.py: lexemes, senses, domains, concepts, mentions, rendered_by, aligned_to) and
phase 3 (macula/build_ontology_propositions.py: one proposition per clause, its predicate, arguments, links, and S2's accuracy
figures). The release refuses a build whose integrity checks fail (dangling ids, broader cycles, Latin letters in lemmas).
OUT gets data/*.parquet, build.json (tag, code) with build-entities.json and build-propositions.json (each part's inputs
and counts), README.md (source_ontology_card.md), SHA256SUMS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from macula import release_guard  # refuses TBTA and private inputs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CARD = HERE / "source_ontology_card.md"
CODE = [HERE / "build_source_ontology.py", HERE / "build_ontology_propositions.py", Path(__file__).resolve(), CARD]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    ap.add_argument("--entities", required=True, help="an entity-mentions release folder (release_entity_mentions.py) to join (O5)")
    a = ap.parse_args()
    release_guard.check(a)
    out = Path(a.out)
    if out.exists():
        raise SystemExit(f"{out} exists; give a folder that does not exist yet")
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *map(str, CODE)], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty and not a.allow_dirty:
        raise SystemExit("uncommitted changes in the ontology's code or card; commit first (or --allow-dirty):\n" + dirty)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    commit += " (dirty)" if dirty else ""
    data = out / "data"
    for mod in ("macula.build_source_ontology", "macula.build_ontology_propositions"):
        subprocess.run([sys.executable, "-m", mod, "--out", str(data)], cwd=HERE.parent, check=True, capture_output=True)
    b1 = json.loads((data / "build.json").read_text())
    b2 = json.loads((data / "build-propositions.json").read_text())
    (data / "build.json").rename(out / "build-entities.json")
    (data / "build-propositions.json").rename(out / "build-propositions.json")
    ig = b1["counts"]["integrity"]
    if any(ig["dangling_by_relation"].values()) or ig["broader_cycles"] or ig["lemmas_with_latin_letters"] or b2["counts"]["dangling"]:
        raise SystemExit(f"integrity checks fail: {ig}, propositions dangling {b2['counts']['dangling']}")
    import pyarrow.parquet as pq
    acc = pq.read_table(data / "prop_accuracy.parquet").to_pylist()
    # O5: the referential side joins the same id space: entity classes, refers_to (mention -> entity), kinship
    import pyarrow as pa
    edir = Path(a.entities)
    eb = json.loads((edir / "build.json").read_text())
    ents = pq.read_table(edir / "data" / "entities.parquet").to_pylist()
    ecls = [{"id": "ent:" + e["entity"], "class": "entity", "type": e["type"], "gender": e["gender"], "lemmas": e["lemmas"]} for e in ents]
    erel = []
    wid = lambda k, lang: "w:" + k                     # the ontology's mention ids: MACULA keys without the Greek "n"
    for r in pq.read_table(edir / "data" / "mentions.parquet").to_pylist():
        erel.append({"subject": wid(r["key"], r["lang"]), "relation": "refers_to", "object": "ent:" + r["entity"], "kind": r["kind"],
                     "route": r["route"], "agree": r["agree"]})
    for r in pq.read_table(edir / "data" / "kinship.parquet").to_pylist():
        erel.append({"subject": "ent:" + r["entity"], "relation": "kin:" + r["relation"], "object": "ent:" + r["other"], "kind": "",
                     "route": "acai", "agree": ""})
    mids = set(pq.read_table(data / "mentions.parquet", columns=["mention"]).column(0).to_pylist())
    eids = {e["id"] for e in ecls}
    e_dangling = sum(1 for r in erel if r["object"] not in eids or (r["relation"] == "refers_to" and r["subject"] not in mids)
                     or (r["relation"] != "refers_to" and r["subject"] not in eids))
    if e_dangling:
        raise SystemExit(f"{e_dangling} entity relations point outside the id space")
    pq.write_table(pa.Table.from_pylist(ecls), data / "entities.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(erel), data / "entity_relations.parquet", compression="zstd")
    import collections
    ec = collections.Counter(r["relation"] if r["relation"] == "refers_to" else "kin" for r in erel)
    c1, c2 = b1["counts"], b2["counts"]
    rel = c1["relations"]
    f = lambda n: f"{n:,}"
    vals = {"@TAG@": a.tag, "@CODE@": commit,
            "@LEX@": f(c1["classes"].get("lexeme", 0)), "@SENSE@": f(c1["classes"].get("sense", 0)),
            "@DOM@": f(c1["classes"].get("domain", 0)), "@CON@": f(c1["classes"].get("concept", 0)),
            "@M_TAN@": f(c1["mentions"].get("tanakh", 0)), "@M_NT@": f(c1["mentions"].get("greek_nt", 0)),
            "@M_LXX@": f(c1["mentions"].get("septuagint", 0)),
            "@A_LXX@": f(c1["aligned"].get("septuagint", 0)), "@A_SCG@": f(c1["aligned"].get("heb_scg", 0)),
            "@A_MOD@": f(c1["aligned"].get("heb_mod", 0)),
            "@REL_TABLE@": "\n".join(f"| `{k.split(' (')[0]}` | {k.split(' (')[1].rstrip(')')} | {f(v)} |" for k, v in rel.items()),
            "@ENT@": f(len(ecls)), "@REFERS@": f(ec["refers_to"]), "@KIN@": f(ec["kin"]),
            "@EM_TAG@": eb["tag"], "@EM_CODE@": eb["code"],
            "@P_HBO@": f(c2["props"].get("hbo", 0)), "@P_GRC@": f(c2["props"].get("grc", 0)),
            "@PR_TABLE@": "\n".join(f"| `{k.split(' (')[0]}` | {k.split(' (')[1].rstrip(')')} | {f(v)} |" for k, v in c2["relations"].items()),
            "@ACC_TABLE@": "\n".join(f"| {r['lang']} | `{r['feature']}` | {r['figure']:.3f} | {r['n']} | `{r['sample']}` | `{r['basis']}` |" for r in acc),
            "@INPUTS@": "\n".join(f"- {k} {v['version']} ({v['revision']})" for k, v in {**b1["inputs"], **b2["inputs"]}.items())
                        + f"\n- the bridge corpus hebrew-greek-cf (build {b1['corpus']})"}
    card = CARD.read_text(encoding="utf-8")
    for k, v in vals.items():
        card = card.replace(k, str(v))
    if re.findall(r"@[A-Z_]+@", card):
        raise SystemExit(f"unfilled card fields: {re.findall(r'@[A-Z_]+@', card)}")
    (out / "README.md").write_text(card, encoding="utf-8")
    (out / "build.json").write_text(json.dumps({"tag": a.tag, "code": commit, "entity_mentions": {"tag": eb["tag"], "code": eb["code"]},
                                                "entity_rows": dict(ec), "parts": ["build-entities.json", "build-propositions.json"]},
                                               ensure_ascii=False, indent=1), encoding="utf-8")
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out).as_posix()}\n" for p in files))
    print(out, len(files), "files; code", commit)


if __name__ == "__main__":
    main()
