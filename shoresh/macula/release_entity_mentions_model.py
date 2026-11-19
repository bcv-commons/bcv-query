"""Package bcv-commons/entity-mentions-model: the model's answer for pronouns neither ACAI nor MACULA's reference chain
resolves (macula/pronoun_model.py). Nothing is uploaded.

    cd shoresh && .venv/bin/python -m macula.release_entity_mentions_model --tag v0.1 --run RUN --em DIR --out OUT [--allow-dirty]

RUN is a pronoun_model run folder after `collect` (answers.jsonl, collect.json, units.jsonl, raw.jsonl) with its sealed check
scored (sealed-1119/score.json). DIR is the entity-mentions release the candidates came from (its build.json names the tag).
OUT gets data/answers.parquet, build.json, README.md (entity_mentions_model_card.md), SHA256SUMS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from macula import pronoun_model as pm
from macula import release_guard  # refuses TBTA and private inputs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CARD = HERE / "entity_mentions_model_card.md"
CODE = [HERE / "pronoun_model.py", Path(__file__).resolve(), CARD]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--em", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    out, run, em = Path(a.out), Path(a.run), Path(a.em)
    if out.exists():
        raise SystemExit(f"{out} exists; give a folder that does not exist yet")
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *map(str, CODE)], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty and not a.allow_dirty:
        raise SystemExit("uncommitted changes; commit first (or --allow-dirty):\n" + dirty)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    commit += " (dirty)" if dirty else ""
    import pyarrow as pa
    import pyarrow.parquet as pq

    col = pm.collect(run)                                       # re-collect from raw.jsonl: the release never trusts a stale file
    rows = [json.loads(l) for l in (run / "answers.jsonl").open(encoding="utf-8")]
    known = set(pq.read_table(em / "data" / "entities.parquet", columns=["entity"]).column(0).to_pylist())
    if any(r["entity"] and r["entity"] not in known for r in rows):
        raise SystemExit("an answer names an entity entity-mentions does not have")
    emb = json.loads((em / "build.json").read_text())
    prep = json.loads((run / "prepare.json").read_text())
    score = json.loads((run / "sealed-1119" / "score.json").read_text())
    (out / "data").mkdir(parents=True)
    keep = ["key", "lang", "entity", "none_reason", "candidates"]
    pq.write_table(pa.Table.from_pylist([{k: r[k] for k in keep} for r in rows]), out / "data" / "answers.parquet", compression="zstd")
    pin = json.loads((pm.RS / "PIN.json").read_text())
    build = {"tag": a.tag, "code": commit, "model": pm.MODEL, "effort": pm.EFFORT, "run": run.name,
             "raw_sha256": sha(run / "raw.jsonl"), "units_sha256": sha(run / "units.jsonl"),
             "inputs": {"entity-mentions": {"tag": emb["tag"], "code": emb["code"]},
                        "reference-status": {"tag": pin["tag"], "commit": pin["commit"]}},
             "scope": prep, "collect": col, "check": score}
    (out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1), encoding="utf-8")
    f = lambda n: f"{n:,}"
    by = lambda lang, cond: sum(1 for r in rows if r["lang"] == lang and cond(r))
    vals = {"@TAG@": a.tag, "@CODE@": commit, "@MODEL@": pm.MODEL, "@EFFORT@": pm.EFFORT, "@USD@": f"{col['usd_reported']:.2f}",
            "@EM_TAG@": emb["tag"], "@RS_TAG@": pin["tag"], "@RS_COMMIT@": pin["commit"][:8], "@ROWS@": f(len(rows)),
            "@UNITS@": f(col["units"]), "@OUT_H@": f(prep["out_of_scope_by_lang"].get("hbo", 0)),
            "@OUT_G@": f(prep["out_of_scope_by_lang"].get("grc", 0)), "@RAW@": build["raw_sha256"][:12]}
    for lang, L in (("hbo", "H"), ("grc", "G")):
        vals[f"@{L}_N@"] = f(by(lang, lambda r: True))
        vals[f"@{L}_ENT@"] = f(by(lang, lambda r: r["entity"]))
        for reason in ("proposition", "not_listed", "unclear"):
            vals[f"@{L}_{reason.upper()}@"] = f(by(lang, lambda r, x=reason: r["none_reason"] == x))
    for g, L in (("hbo", "H"), ("grc", "G"), ("all", "A")):
        s = score[g]
        for k in ("agree_A", "agree_B", "agree_where_judges_agree", "judges_agree"):
            vals[f"@{L}_{k.upper()}@"] = f"{s[k]:.3f}"
        vals[f"@{L}_JN@"] = str(s["n_judges_agree"])
        vals[f"@{L}_SN@"] = str(s["n"])
    vals["@E_N@"], vals["@E_SAME@"] = str(score["entity_items"]["n"]), str(score["entity_items"]["all_three_same"])
    card = CARD.read_text(encoding="utf-8")
    for k, v in vals.items():
        card = card.replace(k, str(v))
    if re.findall(r"@[A-Z_]+@", card):
        raise SystemExit(f"unfilled card fields: {re.findall(r'@[A-Z_]+@', card)}")
    (out / "README.md").write_text(card, encoding="utf-8")
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(out).as_posix()}\n" for p in files))
    print(json.dumps({k: build[k] for k in ("tag", "code", "collect", "check")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
