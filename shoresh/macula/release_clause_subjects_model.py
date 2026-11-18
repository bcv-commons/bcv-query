"""Package make-tanakh-research's packet 34 (Jev-chosen subject participants of clauses without one) as the dataset
bcv-commons/clause-subjects-model (plan step K4, the user's decision 4, 2026-11-17). Nothing is uploaded.

    python -m macula.release_clause_subjects_model --tag v0.1 --out DIR [--packet macula/data/handover/p34] [--allow-dirty]

The packet (git-ignored, MANIFEST.sha256 checked here) holds research's answers keyed by the clause's first MACULA word id, which is
the clause key of bcv-commons/clause-columns (Hebrew: the Hebrew layout's clause_key; Greek: the segment's first word). Its code
calls a model service and reads research's private files, so it does not run here and is not in git (README provenance only).

English-step check (2026-11-17): the prompt carries the clause's Hebrew or Greek words, the previous clauses' words and their
participants (lemmas), and candidate lemmas; the candidates' `gloss` field is always empty (clause_part_jev.py builds it with
`if False`). The instructions are English; no English is evidence.

Hebrew participants that research's layer names by Strong's number (3068 ...) get the MACULA lemma of that number (the commonest
`lemma` for it in MACULA Hebrew), and the number is kept in `participant_strong`.

DIR gets data/hebrew.parquet, data/greek-nt.parquet, README.md, SHA256SUMS.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CARD = HERE / "clause_subjects_model_card.md"
COLUMNS = HERE / "data" / "clause-columns"
BAR = 0.7


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--packet", type=Path, default=HERE / "data" / "handover" / "p34")
    ap.add_argument("--macula-hbo", required=True, help="MACULA Hebrew TSV (for Strong's number -> lemma)")
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    import pyarrow as pa
    import pyarrow.parquet as pq
    code = [HERE / "release_clause_subjects_model.py", CARD]
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *map(str, code)], cwd=ROOT, capture_output=True, text=True).stdout
    if dirty.strip() and not a.allow_dirty:
        raise SystemExit("uncommitted changes; commit first (or --allow-dirty):\n" + dirty)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    for line in (a.packet / "MANIFEST.sha256").read_text().splitlines():
        h, n = line.split("  ", 1)
        if sha(a.packet / n) != h:
            raise SystemExit(f"packet file changed: {n}")
    lemma_of = collections.defaultdict(collections.Counter)
    with open(a.macula_hbo, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            s = (r.get("strongnumberx") or "").strip()
            if s and r.get("lemma"):
                lemma_of[s.lstrip("0")][r["lemma"]] += 1
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; use a new folder")
    (a.out / "data").mkdir(parents=True)
    stats = {}
    for side, name, lang in (("ot", "hebrew", "hbo"), ("nt", "greek-nt", "grc")):
        ans = json.load(open(a.packet / "data" / f"clause_part_jev_{side}.json", encoding="utf-8"))
        ref = {r["clause_key"]: r["ref"] for r in pq.read_table(COLUMNS / f"{name}.parquet", columns=["clause_key", "ref"]).to_pylist()}
        missing = [k for k in ans if k not in ref]
        if missing:
            raise SystemExit(f"{side}: {len(missing)} keys not in clause-columns, e.g. {missing[:3]}")
        rows, mapped = [], 0
        for k in sorted(ans, key=lambda x: (ref[x].split()[0], x)):
            v = ans[k]
            part, strong = (v.get("lemma") or ""), ""
            if re.fullmatch(r"[0-9]+[a-z]?", part):
                strong = "H" + part.rstrip("abcdefgh").zfill(4)
                c = lemma_of.get(part.lstrip("0")) or lemma_of.get(part.rstrip("abcdefgh").lstrip("0"))
                part = c.most_common(1)[0][0] if c else ""
                mapped += 1
            none = v.get("choice") == "none"
            conf = float(v.get("confidence") or 0)
            rows.append({"clause_key": k, "ref": ref[k], "participant": None if none else (part or None),
                         "participant_strong": None if none else (strong or None), "choice": v.get("choice"),
                         "p": float(v.get("p") or 0), "confidence": conf, "candidates": int(v.get("n_cands") or 0),
                         "usable": (not none) and conf >= BAR})
        pq.write_table(pa.Table.from_pylist(rows), a.out / "data" / f"{name}.parquet", compression="zstd")
        stats[side] = {"asked": len(rows), "named": sum(1 for r in rows if r["participant"]), "usable": sum(r["usable"] for r in rows),
                       "none": sum(1 for r in rows if r["choice"] == "none"), "by_number": mapped,
                       "unmapped": sum(1 for r in rows if r["choice"] != "none" and not r["participant"])}
    fill = {"@TAG@": a.tag, "@CODE@": commit + (" (dirty)" if dirty.strip() else ""),
            "@PACKET_SHA@": sha(a.packet / "MANIFEST.sha256")[:12]}
    for side, s in stats.items():
        for k, v in s.items():
            fill[f"@{side.upper()}_{k.upper()}@"] = f"{v:,}"
    card = CARD.read_text(encoding="utf-8")
    for k, v in fill.items():
        card = card.replace(k, v)
    left = re.findall(r"@[A-Z_]+@", card)
    if left:
        raise SystemExit(f"unfilled card fields: {left}")
    (a.out / "README.md").write_text(card, encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (a.out / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(a.out)}\n" for p in files))
    print(a.out, json.dumps(stats), "code", fill["@CODE@"])


if __name__ == "__main__":
    main()
