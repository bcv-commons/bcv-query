"""Package the model rescue of the mood layer (macula/mood_model.py) as the dataset bcv-commons/passage-moods-model. Nothing is
uploaded.

    python -m macula.release_passage_moods_model --tag v0.1 --out DIR [--run macula/.cache/mood-model/2026-11-18] [--allow-dirty]

The run folder (git-ignored) holds units.jsonl (what was asked), families.json (the lemmas shown), cli_raw.jsonl (the model's
answers as returned) and results.jsonl (collect-cli: word numbers turned into MACULA keys). The yardstick each unit carries (the
family a source's own word maps to) is used for the card's figures only and is not published, nor is any source word.

DIR gets data/moods.parquet, mood_families.tsv, README.md, SHA256SUMS.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CARD = HERE / "passage_moods_model_card.md"
RUN = HERE / ".cache" / "mood-model" / "2026-11-18"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    import pyarrow as pa
    import pyarrow.parquet as pq
    from macula import build_passage_facts as pf, mood_families as mf, mood_model
    code = [HERE / "release_passage_moods_model.py", CARD, HERE / "mood_model.py", HERE / "mood_families.py", mf.TABLE]
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *map(str, code)], cwd=ROOT, capture_output=True, text=True).stdout
    if dirty.strip() and not a.allow_dirty:
        raise SystemExit("uncommitted changes; commit first (or --allow-dirty):\n" + dirty)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; use a new folder")
    rows_in = [json.loads(l) for l in (a.run / "results.jsonl").open(encoding="utf-8")]
    raw = [json.loads(l) for l in (a.run / "cli_raw.jsonl").open(encoding="utf-8")]
    units = sum(1 for _ in (a.run / "units.jsonl").open(encoding="utf-8"))
    if len(rows_in) != units:
        raise SystemExit(f"{len(rows_in)} results for {units} units")
    books: dict[str, object] = {}
    order = {b: i for i, b in enumerate(pf.BOOKS)} if hasattr(pf, "BOOKS") else {}
    out, sc = [], collections.Counter()
    for r in sorted(rows_in, key=lambda r: (order.get(r["book"], 99), r["first"])):
        if r["book"] not in books:
            books[r["book"]] = pf.Book(r["book"])
        bk = books[r["book"]]
        hebrew = bk.hebrew
        moods = [{"family": m["family"], "head": mf.head(m["family"], hebrew), "marked_by": m["marked_by"]}
                 for m in r["moods"] if m["marked_by"]]
        out.append({"unit_id": r["id"], "book": r["book"], "first": r["first"], "last": r["last"], "ref": bk.ref(r["first"], r["last"]),
                    "lang": "hbo" if hebrew else "grc", "asked_because": {"scriptura": "source", "glyssen": "source", "rules": "hard"}[r["source"]],
                    "source": None if r["source"] == "rules" else r["source"], "moods": moods, "none": not moods})
        fams = [m["family"] for m in moods]
        src = r["source"]
        sc[src, "n"] += 1
        sc[src, "none"] += not fams
        sc[src, "hit"] += bool(set(fams) & set(r["yard"]))
        sc[src, "first"] += bool(fams) and fams[0] in r["yard"]
        for f in fams:
            sc["fam", f] += 1
    (a.out / "data").mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(out), a.out / "data" / "moods.parquet", compression="zstd")
    shutil.copy(mf.TABLE, a.out / "mood_families.tsv")
    usage = collections.Counter()
    for x in raw:
        for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"):
            usage[k] += (x.get("usage") or {}).get(k, 0) or 0
    pct = lambda src, k: f"{sc[src, k] / max(1, sc[src, 'n']):.2f}"
    fill = {"@TAG@": a.tag, "@CODE@": commit + (" (dirty)" if dirty.strip() else ""), "@MODEL@": mood_model.MODEL,
            "@EFFORT@": mood_model.EFFORT, "@UNITS@": f"{len(out):,}", "@RESULTS_SHA@": sha(a.run / "results.jsonl")[:12],
            "@WITH_MOOD@": f"{sum(not r['none'] for r in out):,}", "@NONE@": f"{sum(r['none'] for r in out):,}",
            "@COST@": f"{sum(x.get('cost_usd', 0) or 0 for x in raw):.2f}",
            "@OUT_TOKENS@": f"{usage['output_tokens']:,}",
            "@FAMILIES@": ", ".join(f"`{f}` {sc['fam', f]}" for f in mf.FAMILIES)}
    for src in ("scriptura", "glyssen", "rules"):
        S = src.upper()
        fill[f"@{S}_N@"] = f"{sc[src, 'n']:,}"
        fill[f"@{S}_HIT@"], fill[f"@{S}_FIRST@"], fill[f"@{S}_NONE@"] = pct(src, "hit"), pct(src, "first"), pct(src, "none")
    card = CARD.read_text(encoding="utf-8")
    for k, v in fill.items():
        card = card.replace(k, v)
    left = re.findall(r"@[A-Z_]+@", card)
    if left:
        raise SystemExit(f"unfilled card fields: {left}")
    (a.out / "README.md").write_text(card, encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (a.out / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(a.out)}\n" for p in files))
    print(a.out, len(out), "units;", fill["@WITH_MOOD@"], "with a mood; code", fill["@CODE@"])


if __name__ == "__main__":
    main()
