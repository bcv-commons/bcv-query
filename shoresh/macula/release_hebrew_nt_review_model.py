"""Package bcv-commons/hebrew-nt-review-model: a model's review of the Hebrew NT word links, one record per Greek noun, verb and
adjective of the NT, for Salkinson-Ginsburg (heb_scg) and Delitzsch (heb_mod). Made by make-tanakh-research (2026-10-31) and handed
over to bcv-query (packet 32, 2026-11-17; provenance in macula/hnt_review/README.md). Nothing is uploaded.

    python -m macula.release_hebrew_nt_review_model --tag v0.1 --packet macula/data/handover/p32 --checks DIR --out DIR [--allow-dirty]

DIR gets:
  records/<edition>.jsonl     the review records as handed over (corrections.jsonl): gid, before (the link at review time = the
                              staleness key), after, how, decided_by, evidence, and for the model's review note, rules, model, date.
                              Notes are the reviewer's working notes; English words quoted or in brackets (glosses) are removed.
  calibration/<edition>.json  Jev's thresholds per kind of decision, and how they were set
  checks/function-words/<edition>/{items.json,judgments.tsv,score.json}   the blind function-word check of 2026-11-17 (bcv-query)
  README.md (hebrew_nt_review_model_card.md filled in), SHA256SUMS
"""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from macula import release_guard  # refuses TBTA and private inputs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CARD = HERE / "hebrew_nt_review_model_card.md"
EDITIONS = ("heb_scg", "heb_mod")
NOT_LATIN = r"Ͱ-Ͽἀ-῿֐-׿"
QUOTED = re.compile(r"\s*(\"[^\"]*[A-Za-z][^\"]*\"|'[^']*[A-Za-z][^']*'|‘[^’]*[A-Za-z][^’]*’|“[^”]*[A-Za-z][^”]*”)")
BRACKET = re.compile(rf"\s*\((?![1-3]?\s?[A-Z][a-z]{{1,3}}\.? \d+:\d+\))[^()" + NOT_LATIN + r"]*[A-Za-z][^()" + NOT_LATIN + r"]*\)")


def clean(note: str | None) -> str | None:
    if not note:
        return note
    return re.sub(r"\s{2,}", " ", BRACKET.sub("", QUOTED.sub(" …", note))).strip() or None


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--packet", type=Path, required=True)
    ap.add_argument("--checks", type=Path, required=True, help="the function-word check folder: <edition>/{items.json,judgments.tsv,score.json}")
    ap.add_argument("--gloss-tier", type=Path, required=True, help="research's Jev tier (packet 33 data/strong_bridge_jev.tsv): its pairs were found by English glosses")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    code = [HERE / "release_hebrew_nt_review_model.py", CARD, HERE / "hnt_review"]
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *map(str, code)], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty and not a.allow_dirty:
        raise SystemExit("uncommitted changes; commit first (or --allow-dirty):\n" + dirty)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    man = dict(reversed(l.split("  ", 1)) for l in (a.packet / "MANIFEST.sha256").read_text().splitlines())
    for ed in EDITIONS:
        rel = f"review/{ed}/corrections.jsonl"
        if sha256(a.packet / rel) != man[rel]:
            raise SystemExit(f"{rel}: not the handed-over file")
    import pyarrow.parquet as pq
    from macula import build_hebrew_nt_bridge as hb
    gloss = {tuple(l.split("\t")[:2]) for l in a.gloss_tier.read_text().splitlines()[1:]}
    other = set()
    for f in (ROOT / "resources" / "lxx_bridge_tiers" / "macula.tsv", ROOT / "resources" / "lxx_bridge_tiers" / "glaux.tsv", ROOT / "resources" / "lxx_bridge.tsv"):
        other |= {tuple(l.split("\t")[:2]) for l in f.read_text().splitlines()[1:]}
    a.out.mkdir(parents=True, exist_ok=False)
    fields = {"@TAG@": a.tag, "@BUILT@": datetime.date.today().isoformat(), "@COMMIT@": commit}
    stats = {}
    for ed in EDITIONS:
        (a.out / "records").mkdir(exist_ok=True)
        n, how, cleaned, flagged = collections.Counter(), collections.Counter(), 0, 0
        pairs = collections.defaultdict(set)
        for r in pq.read_table(hb.DATA / ed / "links.parquet", columns=["greek_id", "greek_strong", "i", "part", "hebrew_strong"]).to_pylist():
            if r["hebrew_strong"]:
                pairs[(r["greek_id"], r["i"], r["part"])].add((r["hebrew_strong"], r["greek_strong"]))
        with open(a.out / "records" / f"{ed}.jsonl", "w", encoding="utf-8") as f:
            for l in open(a.packet / "review" / ed / "corrections.jsonl", encoding="utf-8"):
                r = json.loads(l)
                if r.get("note"):
                    c = clean(r["note"])
                    cleaned += c != r["note"]
                    r["note"] = c
                if r["decided_by"] == "published":
                    prs = set().union(*(pairs.get((r["gid"], t, p), set()) for t, p in r["before"]["link"]))
                    if prs & gloss and not prs & other:
                        r["evidence"]["bridge_pair_from_glosses"] = True
                        flagged += 1
                n[r["decided_by"]] += 1
                how[r.get("how") or "not rendered"] += 1
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        (a.out / "calibration").mkdir(exist_ok=True)
        shutil.copy(a.packet / "review" / ed / "calibration.json", a.out / "calibration" / f"{ed}.json")
        cd = a.out / "checks" / "function-words" / ed
        cd.mkdir(parents=True)
        for fn in ("items.json", "judgments.tsv", "score.json"):
            shutil.copy(a.checks / ed / fn, cd / fn)
        score = json.loads((a.checks / ed / "score.json").read_text())
        stats[ed] = {"records": sum(n.values()), "decided_by": dict(n), "how": dict(how), "notes cleaned": cleaned, "accepted on a gloss-found pair only": flagged, "function words": score}
        k = ed.split("_")[1].upper()
        fields.update({f"@{k}_N@": f"{sum(n.values()):,}", f"@{k}_PUB@": f"{n['published']:,}", f"@{k}_JEV@": f"{n['jev-check-v1']:,}",
                       f"@{k}_CLAUDE@": f"{n['claude-review-v1']:,}", f"@{k}_LEX@": f"{how['lexical']:,}", f"@{k}_PHRASE@": f"{how['phrase']:,}",
                       f"@{k}_FREE@": f"{how['free']:,}", f"@{k}_UNC@": f"{how['uncertain']:,}", f"@{k}_NONE@": f"{how['not rendered']:,}", f"@{k}_GLOSS@": f"{flagged:,}"})
    (a.out / "build.json").write_text(json.dumps({"tag": a.tag, "code": commit, "packet": "make-tanakh-research packet 32 (2026-11-17)",
                                                  "editions": stats}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    card = CARD.read_text(encoding="utf-8")
    for k, v in fields.items():
        card = card.replace(k, v)
    assert not re.search(r"@[A-Z_]+@", card), re.findall(r"@[A-Z_]+@", card)
    (a.out / "README.md").write_text(card, encoding="utf-8")
    files = sorted(x for x in a.out.rglob("*") if x.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(x)}  {x.relative_to(a.out).as_posix()}\n" for x in files), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False)[:800], "->", a.out)


if __name__ == "__main__":
    main()
