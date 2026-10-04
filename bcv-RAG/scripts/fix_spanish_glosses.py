#!/usr/bin/env python3
"""Replace Portuguese text that leaked into resources/word_glosses/hbo/Spanish.csv.

About 8% of the Spanish cells were Portuguese ("trabalhos", "servidão", "pão achatado"); half are exact
copies of Portuguese.csv, so the build fell back to Portuguese for these lexemes. Candidates: every cell
with Portuguese-only spelling (ç ã õ ê ô â, -ção, -ões, lh, nh, não/uma/da/do/em/ou) or identical to the
Portuguese cell. The model (claude -p, subscription; no API key used) sees the Hebrew lemma, the English
and Portuguese glosses, and returns the Spanish gloss, or the same text when it is already Spanish (names,
words spelled alike). Only those cells are rewritten; the CSV layout is kept.

  shoresh/.venv/bin/python3 bcv-RAG/scripts/fix_spanish_glosses.py            # dry run: count candidates
  shoresh/.venv/bin/python3 bcv-RAG/scripts/fix_spanish_glosses.py --run
"""
from __future__ import annotations

import concurrent.futures
import csv
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "shoresh"))
WG = ROOT / "resources" / "word_glosses" / "hbo"
SEED = ROOT / "resources" / "lexicons" / "heb_en.csv"
LOG = ROOT / "shoresh" / "macula" / "data" / "spanish_gloss_fix.jsonl"
MARK = re.compile(r"[çãõêôâ]|ção|ões|lh|nh|\bnão\b|\buma?\b|\bda\b|\bdo\b|\bem\b|\bou\b")
BATCH = 40
PROMPT = (
    "You are fixing a Spanish gloss table for Biblical Hebrew words. Some cells were filled with "
    "Portuguese by mistake. For each item you get the Hebrew lemma, the column (`default` = the word's "
    "gloss; otherwise a verb stem such as qal, nif, piel), the English gloss, and the current cell. Return "
    "the correct Spanish gloss in the same style and length as the current cell (keep commas, semicolons, "
    "parentheses and question marks). If the current cell is already correct Spanish, or a proper name, "
    "return it unchanged.\nReply with JSON only: a list of {\"id\": <id>, \"es\": <Spanish gloss>}.\n\n"
    "Items:\n")


def read(name: str) -> tuple[list[str], list[list[str]]]:
    with (WG / f"{name}.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    return rows[0], rows[1:]


def lemmas() -> dict[str, str]:
    out = {}
    with SEED.open(encoding="utf-8-sig", newline="") as fh:
        r = csv.DictReader(fh)
        for row in r:
            out[row["lex"]] = row["Lexeme"]
    return out


def candidates():
    head, es = read("Spanish")
    _, pt = read("Portuguese")
    _, en = read("English")
    pt_map = {r[0]: dict(zip(head, r)) for r in pt}
    en_head = read("English")[0]
    en_map = {r[0]: dict(zip(en_head, r)) for r in en}
    out = []
    for i, row in enumerate(es):
        lx = row[0]
        for j, col in enumerate(head[1:], start=1):
            v = row[j] if j < len(row) else ""
            if not v:
                continue
            same_pt = (pt_map.get(lx) or {}).get(col, "") == v
            en_v = (en_map.get(lx) or {}).get(col, "")
            if v == en_v:                     # names and words spelled alike in all three
                continue
            if MARK.search(v) or same_pt:
                out.append({"id": f"{i}:{j}", "lex": lx, "col": col, "es": v,
                            "en": (en_map.get(lx) or {}).get(col, "") or (en_map.get(lx) or {}).get("default", "")})
    return head, es, out


def main() -> int:
    run = "--run" in sys.argv
    head, es, cand = candidates()
    print(f"{len(cand)} candidate cells", file=sys.stderr)
    if not run:
        for c in cand[:15]:
            print(c)
        return 0
    from macula.usability_judge import call_claude_cli
    lem = lemmas()
    done = {}
    if LOG.exists():
        done = {r["id"]: r["es"] for r in map(json.loads, LOG.read_text(encoding="utf-8").splitlines()) if r}
    todo = [c for c in cand if c["id"] not in done]

    def call(batch):
        items = [{"id": c["id"], "hebrew": lem.get(c["lex"], c["lex"]), "column": c["col"],
                  "english": c["en"], "current": c["es"]} for c in batch]
        text, _i, _o = call_claude_cli(PROMPT + json.dumps(items, ensure_ascii=False, indent=1))
        m = re.search(r"\[.*\]", text, re.S)
        try:
            return {r["id"]: r["es"].strip() for r in json.loads(m.group(0)) if r.get("es")} if m else {}
        except (json.JSONDecodeError, AttributeError, TypeError):
            return {}

    LOG.parent.mkdir(parents=True, exist_ok=True)
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    with concurrent.futures.ThreadPoolExecutor(4) as pool, LOG.open("a", encoding="utf-8") as fh:
        for got in pool.map(call, batches):
            for iid, v in got.items():
                fh.write(json.dumps({"id": iid, "es": v}, ensure_ascii=False) + "\n")
                done[iid] = v
            fh.flush()
    changed = 0
    for c in cand:
        new = done.get(c["id"])
        if new and new != c["es"] and "\n" not in new:
            i, j = map(int, c["id"].split(":"))
            es[i][j] = new
            changed += 1
    eol = "\r\n" if b"\r\n" in (WG / "Spanish.csv").read_bytes()[:4096] else "\n"   # keep the file's line endings
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator=eol)
    w.writerow(head)
    w.writerows(es)
    (WG / "Spanish.csv").write_bytes(buf.getvalue().encode("utf-8"))
    print(f"answered {sum(c['id'] in done for c in cand)}/{len(cand)}; rewrote {changed} cells", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
