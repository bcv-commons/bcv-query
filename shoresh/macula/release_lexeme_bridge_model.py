"""Package bcv-commons/hebrew-greek-lexeme-bridge-model: a model's choice of a Hebrew <-> Greek lexeme partner for lexemes the
Septuagint tiers (resources/lxx_bridge_tiers) leave without one. Nothing is uploaded.

    python -m macula.release_lexeme_bridge_model --tag v0.1 --answers macula/data/handover/p33b/data/answers.json --out DIR [--min-p 0.5] [--allow-dirty]
    python -m macula.release_lexeme_bridge_model --tag v0.2 \
        --run 33b=macula/data/handover/p33b/data/answers.json=macula/data/bridge-candidates/candidates.json \
        --run vector=macula/data/handover/vector-judge-2026-11-17/answers.json=macula/data/handover/vector-judge-2026-11-17/vector-candidates.json \
        --out DIR

--run NAME=ANSWERS=CANDIDATES (repeatable, in order): a later run's answer for the same lexeme replaces the earlier one (the vector
run asked 49 lexemes again that the 33b run had answered "none" or below --min-p, with their earlier candidates first). Each answer
in answers.json gets `run`: NAME.

Candidates: macula/build_bridge_candidates.py (the Hebrew NT bridges and the Septuagint co-occurrence at Dice >= 0.08; no English).
Judge: Jev (TypeSafe, jev-1.14.0), run by make-tanakh-research on 2026-11-17 (its bridge_jev.py judge-orig; packet copy in macula/data/handover/p33b), shown the
lexeme, its count, up to three verses in its own language and each candidate's lemma, count and evidence; no glosses; "none" allowed.
Handed over as packet 33b. It replaces research's earlier Jev tier, whose candidates were found by English glosses (held back).

DIR gets pairs.tsv (side, hebrew_strong, greek_strong, hebrew_lemma, greek_lemma, p, evidence: hnt count, dice), answers.json (every
answer, also "none" and below --min-p), candidates.json, README.md (lexeme_bridge_model_card.md filled in), SHA256SUMS.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from macula import release_guard  # refuses TBTA and private inputs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CARD = HERE / "lexeme_bridge_model_card.md"
CANDS = HERE / "data" / "bridge-candidates" / "candidates.json"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--answers", type=Path)
    ap.add_argument("--run", action="append", default=[])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-p", type=float, default=0.5)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    code = [Path(__file__).resolve(), CARD, HERE / "build_bridge_candidates.py", HERE / "build_vector_candidates.py", HERE / "hnt_review"]
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *map(str, code)], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty and not a.allow_dirty:
        raise SystemExit("uncommitted changes; commit first (or --allow-dirty):\n" + dirty)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    runs = [r.split("=", 2) for r in a.run] or [["33b", str(a.answers), str(CANDS)]]
    cand, ans, lexemes = {}, {}, set()
    for name, af, cf in runs:
        C = json.loads(Path(cf).read_text(encoding="utf-8"))
        for side, es in C.items():
            for e in es:
                cand[(side, e["strong"])] = {c["strong"]: c for c in e["candidates"]}
                lexemes.add((side, e["strong"]))
        for k, x in json.loads(Path(af).read_text(encoding="utf-8")).items():
            ans[k] = {**x, "run": name}
    rows, none, low = [], 0, 0
    for x in ans.values():
        if x["choice"] == "none":
            none += 1
            continue
        t = x["candidates"][x["choice"]]
        p = x["probabilities"][x["choice"]]
        if t not in cand[(x["side"], x["strong"])]:
            raise SystemExit(f"{x['side']} {x['strong']}: chosen {t} is not in candidates.json (another candidate file?)")
        if p < a.min_p:
            low += 1
            continue
        c = cand[(x["side"], x["strong"])][t]
        h, g = (t, x["strong"]) if x["side"] == "nt" else (x["strong"], t)
        hl, gl = (c["lemma"], x["lemma"]) if x["side"] == "nt" else (x["lemma"], c["lemma"])
        ev = c["evidence"]
        vec = ev.get("vector") or {}
        rows.append((x["side"], f"H{h:04d}", f"G{g:04d}", hl or "", gl or "", f"{p:.2f}", str(sum(ev.get("hnt", {}).values()) or ""),
                     str(ev.get("dice", "")), str(vec.get("rank", "")), x["run"]))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "pairs.tsv").write_text("side\thebrew_strong\tgreek_strong\thebrew_lemma\tgreek_lemma\tp\thnt_links\tlxx_dice\tvector_rank\trun\n" +
                                     "".join("\t".join(r) + "\n" for r in rows), encoding="utf-8")
    (a.out / "answers.json").write_text(json.dumps(ans, ensure_ascii=False, indent=1), encoding="utf-8")
    merged = {}
    for (s, st), cs in sorted(cand.items()):
        merged.setdefault(s, []).append({"strong": st, "candidates": list(cs.values())})
    (a.out / "candidates.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    vec_run = [x for x in ans.values() if x["run"] == "vector"]
    vec_pairs = sum(1 for r in rows if r[-1] == "vector")
    side = lambda s: sum(1 for r in rows if r[0] == s)
    fill = {"@TAG@": a.tag, "@BUILT@": datetime.date.today().isoformat(), "@COMMIT@": commit, "@ASKED@": f"{len(ans):,}",
            "@NONE@": f"{none:,}", "@LOW@": f"{low:,}", "@PAIRS@": f"{len(rows):,}", "@NT@": f"{side('nt'):,}", "@OT@": f"{side('ot'):,}",
            "@MINP@": f"{a.min_p:g}", "@LEXEMES@": f"{len(lexemes):,}",
            "@VEC_ASKED@": f"{len(vec_run):,}", "@VEC_PAIRS@": f"{vec_pairs:,}",
            "@VEC_NONE@": f"{sum(1 for x in vec_run if x['choice'] == 'none'):,}",
            "@VEC_BYVEC@": f"{sum(1 for r in rows if r[-1] == 'vector' and r[8]):,}"}
    card = CARD.read_text(encoding="utf-8")
    for k, v in fill.items():
        card = card.replace(k, v)
    assert "@" not in card.replace("@v", ""), [l for l in card.splitlines() if "@" in l]
    (a.out / "README.md").write_text(card, encoding="utf-8")
    files = sorted(x for x in a.out.rglob("*") if x.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(x.read_bytes()).hexdigest()}  {x.relative_to(a.out).as_posix()}\n" for x in files))
    print(f"{a.out}: {len(rows)} pairs (nt {side('nt')}, ot {side('ot')}); none {none}, below {a.min_p} {low}; code {commit}")


if __name__ == "__main__":
    main()
