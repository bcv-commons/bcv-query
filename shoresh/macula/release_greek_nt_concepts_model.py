"""Package bcv-commons/greek-nt-concepts-model: a model layer of Hebrew concepts for Greek NT words, from label_greek_nt_concepts'
table (labelling/words.parquet and report.json, built by --build, with --opus for Opus's choices).

    cd shoresh && .venv/bin/python3 -m macula.release_greek_nt_concepts_model --version v0.1 --out DIR [--allow-dirty]

Nothing is uploaded. DIR gets data/words.parquet, report.json, README.md (greek_nt_concepts_model_card.md filled in), build.json and
SHA256SUMS.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pyarrow.parquet as pq
from macula import release_guard  # refuses TBTA and private inputs
from macula.label_greek_nt_concepts import OUT

ROOT = Path(__file__).resolve().parents[2]
CARD = Path(__file__).with_name("greek_nt_concepts_model_card.md")
SCHEMA = 1
COLUMNS = ["greek_id", "greek_strong", "greek_lemma", "set", "concept", "hebrew_strong", "n_concepts", "confidence", "none", "labeller",
           "jev_concept", "opus_sure"]
VERSIONS = {"v0.1": "v0.1: Jev on every word with more than one concept (one run, 2026-11-16).",
            "v0.2": "v0.2: as v0.1, and Claude Opus 5.5 chooses again where Jev's confidence is below 0.8 (`labeller` = `opus`)."}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quality(rep: dict) -> str:
    q = rep["quoted words"]
    out = [f"- all: {q['same concept']:.1%} the same concept as the Tanakh word"]
    for k, v in q.items():
        if isinstance(v, dict) and v["words"]:
            j = v.get("jev's own")
            own = f" (Jev's own choice {j:.1%})" if j is not None and j != v["same concept"] else ""
            out.append(f"- Jev's {k}: {v['words']:,} words, {v['same concept']:.1%}{own}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, choices=sorted(VERSIONS))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "shoresh/macula"], cwd=ROOT, text=True).strip()
    if dirty and not a.allow_dirty:
        raise SystemExit(f"uncommitted changes in shoresh/macula:\n{dirty}")
    code = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=ROOT, text=True).strip() + ("+uncommitted" if dirty else "")
    t = pq.read_table(OUT / "words.parquet")
    rep = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert t.schema.names == COLUMNS, t.schema.names
    rows = t.to_pylist()
    who = collections.Counter(r["labeller"] for r in rows)
    opus = who.get("opus", 0) > 0
    assert opus == (a.version != "v0.1"), f"{a.version} with {dict(who)}"
    assert len({r["greek_id"] for r in rows}) == len(rows)
    for r in rows:
        assert r["none"] == (r["concept"] == ""), r
        assert r["labeller"] != "opus" or (r["confidence"] < 0.8 and r["opus_sure"] is not None), r
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "data").mkdir()
    shutil.copyfile(OUT / "words.parquet", a.out / "data/words.parquet")
    pub = {k: v for k, v in rep.items() if k != "answers"}
    (a.out / "report.json").write_text(json.dumps(pub, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    models = "Jev (jev-latest, TypeSafe System One), one run" + ("; Claude Opus 5.5 (Anthropic), low effort, one run" if opus else "")
    build = {"schema": SCHEMA, "version": a.version, "built": datetime.date.today().isoformat(), "code": code, "licence": "CC BY-SA 4.0",
             "layer": "model (not fact); no human check", "models": models,
             "inputs": {"concepts": "bcv-commons/hebrew-word-concepts-model v0.5 (5a7af303)", "hebrew_nt": "bcv-commons/hebrew-nt-bridge v0.1 (525db08f)",
                        "words": "MACULA Greek (Nestle 1904), macula-spine-2026-10-07"},
             "counts": {"words": len(rows), "labeller": dict(who), "set": dict(collections.Counter(r["set"] for r in rows)),
                        "none": sum(r["none"] for r in rows)}}
    (a.out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    labellers = ("Jev (TypeSafe System One) chose for every word with more than one concept"
                 + ("; Claude Opus 5.5 chose again where Jev's confidence was below 0.8." if opus else "."))
    card = CARD.read_text(encoding="utf-8")
    for k, v in {"@VERSION@": a.version, "@CODE@": code, "@BUILT@": build["built"], "@WORDS@": f"{len(rows):,}", "@LABELLERS@": labellers,
                 "@QUOTED@": f"{rep['quoted words']['words']:,}", "@QUALITY@": quality(rep), "@MODELS@": models,
                 "@VERSIONS@": "\n".join(f"- {VERSIONS[v]}" for v in sorted(VERSIONS) if v <= a.version)}.items():
        card = card.replace(k, v)
    assert "@" not in card, [l for l in card.splitlines() if "@" in l]
    (a.out / "README.md").write_text(card, encoding="utf-8")
    sums = sorted(p for p in a.out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(a.out)}\n" for p in sums), encoding="utf-8")
    print(f"bcv-commons/greek-nt-concepts-model {a.version} -> {a.out}: {len(rows):,} words, {dict(who)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
