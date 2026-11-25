"""Package the two-pass mood-span reading (macula/mood_spans.py) as the dataset bcv-commons/passage-mood-spans-model.
Nothing is uploaded.

    python -I macula/release_passage_mood_spans_model.py --tag v0.1 --out DIR [--run macula/data/mood-spans/bible-1]
        [--sessions ../internal-docs/source-examples-work/sessions] [--allow-dirty]

The run folder (git-ignored) holds input/ (what the readers saw), checked/a|b/bNN.jsonl and .refused.tsv (mood_spans.py
check), spans.jsonl and source_notes.jsonl (mood_spans.py compare). The sessions folder holds one result.json per stage
(m01a ... m42b) with the cost. The run's own line numbers (`from`, `to`) are not published: they point into input/.

DIR gets data/spans.jsonl, data/source_notes.jsonl, moods_he.toml, README.md, SHA256SUMS.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import mood_spans as ms  # noqa: E402

CARD = HERE / "passage_mood_spans_model_card.md"
RUN = HERE / "data" / "mood-spans" / "bible-1"
SESSIONS = ROOT / "internal-docs" / "source-examples-work" / "sessions"
KEEP = ["id", "chapter", "book", "lang", "kind", "first", "last", "verses", "mood", "second", "strength", "because", "unit",
        "pass", "model", "agree", "other_mood", "moods_sha"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--run", type=Path, default=RUN)
    ap.add_argument("--sessions", type=Path, default=SESSIONS)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    code = [HERE / "release_passage_mood_spans_model.py", CARD, HERE / "mood_spans.py", ms.MOODS]
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *map(str, code)], cwd=ROOT, capture_output=True, text=True).stdout
    if dirty.strip() and not a.allow_dirty:
        raise SystemExit("uncommitted changes; commit first (or --allow-dirty):\n" + dirty)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; use a new folder")
    moods_sha = sha(ms.MOODS)[:12]
    if (a.run / "batches.json").exists():
        chapters = [c for b in json.loads((a.run / "batches.json").read_text(encoding="utf-8")).values() for c in b["chapters"]]
    else:
        chapters = [f.name[: -len(".keys.json")] for f in sorted((a.run / "input").glob("*.keys.json"))]
    lines = sum(sum(1 for _ in open(a.run / "input" / f"{c}.txt", encoding="utf-8")) - 1 for c in chapters)
    rows = [json.loads(l) for l in open(a.run / "spans.jsonl", encoding="utf-8")]
    bad = {r.get("moods_sha") for r in rows} - {moods_sha}
    if bad:
        raise SystemExit(f"rows read with another moods_he.toml: {bad} (now {moods_sha})")
    a_ch = {r["chapter"]: r["first"] for r in rows if r["kind"] == "chapter"}
    missing = [c for c in chapters if c not in a_ch]
    if missing:
        raise SystemExit(f"{len(missing)} chapters without a pass-a chapter row: {missing[:10]}")
    # pass b's chapter rows are not in spans.jsonl (compare keeps a's with other_mood); take them from checked/b
    b_files = sorted((a.run / "checked" / "b").glob("b*.jsonl")) or [a.run / "b.jsonl"]
    b_rows = [json.loads(l) for f in b_files for l in open(f, encoding="utf-8")]
    b_chapter = {r["chapter"]: r for r in b_rows if r["kind"] == "chapter"}
    for r in list(rows):
        if r["kind"] == "chapter" and r["pass"] == "a":
            o = b_chapter.get(r["chapter"])
            if o:
                rows.append({**o, "agree": o["mood"] == r["mood"], "other_mood": r["mood"]})
    langs = {c: "hbo" if len(a_ch[c]) == 12 else "grc" for c in chapters}          # MACULA Hebrew keys 12 digits, Greek 11
    order = {c: i for i, c in enumerate(sorted(chapters, key=lambda c: (int(a_ch[c][:2]), int(c.split(".")[1]))))}
    rows.sort(key=lambda r: (order[r["chapter"]], r["pass"], r["kind"] != "chapter", r.get("from", 0), r.get("to", 0)))
    n = collections.Counter()
    out = []
    for r in rows:
        k = (r["chapter"], r["pass"])
        r["id"] = f"{r['chapter']}.{r['pass']}{0 if r['kind'] == 'chapter' else n[k] + 1}"
        if r["kind"] == "span":
            n[k] += 1
        else:
            r["verses"] = None
        r["book"], r["lang"] = r["chapter"].split(".")[0], langs[r["chapter"]]
        out.append({f: r.get(f) for f in KEEP if f != "other_mood" or r["kind"] == "chapter"})
    (a.out / "data").mkdir(parents=True)
    with open(a.out / "data" / "spans.jsonl", "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    notes = [json.loads(l) for l in open(a.run / "source_notes.jsonl", encoding="utf-8")]
    notes.sort(key=lambda r: (order[r["chapter"]], r["first"], r["fact"]))
    with open(a.out / "data" / "source_notes.jsonl", "w", encoding="utf-8") as fh:
        for r in notes:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    shutil.copy(ms.MOODS, a.out / "moods_he.toml")
    # figures
    spans = [r for r in out if r["kind"] == "span"]
    fill = {"@TAG@": a.tag, "@CODE@": commit + (" (dirty)" if dirty.strip() else ""), "@MOODS_SHA@": moods_sha,
            "@CHAPTERS@": f"{len(chapters):,}", "@LINES@": f"{lines:,}"}
    for p in "ab":
        S = [r for r in spans if r["pass"] == p]
        st = collections.Counter(r["strength"] for r in S)
        rf = sorted((a.run / "checked" / p).glob("b*.refused.tsv")) or [a.run / f"{p}.refused.tsv"]
        ref = sum(1 for f in rf for l in open(f, encoding="utf-8") if l.strip())
        cost = 0.0
        for f in a.sessions.glob(f"m[0-9][0-9]{p}-try*/result.json"):
            cost += json.loads(f.read_text()).get("cost_usd") or 0
        P = p.upper()
        fill[f"@{P}_SPANS@"] = f"{len(S):,}"
        fill[f"@{P}_AGREE@"] = f"{sum(r['agree'] for r in S):,} ({sum(r['agree'] for r in S) / max(1, len(S)):.0%})"
        fill[f"@{P}_STR@"] = " / ".join(f"{st[k]:,} ({st[k] / max(1, len(S)):.0%})" for k in (3, 2, 1))
        fill[f"@{P}_REF@"] = f"{ref:,}"
        fill[f"@COST_{P}@"] = f"{cost:.2f}"
    ch = [r for r in out if r["kind"] == "chapter" and r["pass"] == "a"]
    fill["@CH_AGREE@"] = f"{sum(r['agree'] for r in ch):,} of {len(ch):,}"
    moods = tomllib.loads(ms.MOODS.read_text(encoding="utf-8"))["moods"]
    cnt = collections.Counter((r["pass"], r["mood"]) for r in spans)
    fill["@MOOD_ROWS@"] = "\n".join(f"| `{m}` {moods[m]['hebrew']} | {cnt['a', m]:,} | {cnt['b', m]:,} |" for m in moods)
    card = CARD.read_text(encoding="utf-8")
    for k, v in fill.items():
        card = card.replace(k, v)
    left = re.findall(r"@[A-Z_]+@", card)
    if left:
        raise SystemExit(f"unfilled card fields: {left}")
    (a.out / "README.md").write_text(card, encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (a.out / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(a.out)}\n" for p in files))
    print(a.out, len(chapters), "chapters;", len(spans), "spans; code", fill["@CODE@"])


if __name__ == "__main__":
    main()
