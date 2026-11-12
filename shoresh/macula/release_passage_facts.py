"""Package the dataset bcv-commons/passage-facts. Nothing is uploaded: the files are written to a folder for review.

    python -m macula.release_passage_facts --out DIR [--allow-dirty]

Builds the whole Bible twice with macula.build_passage_facts: all facts (data/, CC BY-SA 4.0) and the facts of non-share-alike sources
only (data-cc-by/, CC BY 4.0). Adds README.md (passage_facts_card.md filled in: the field and kind tables come from
resources/passage_facts/README.md, the source table from sources.tsv, the checks from build.json), codes.tsv, sources.tsv, build.json
and SHA256SUMS. The codes table must not change during the build (run the builder with --update-codes first if it would).
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

from macula import build_passage_facts as pf

HERE = Path(__file__).resolve().parent
CARD = HERE / "passage_facts_card.md"
BOOKS = ("GEN EXO LEV NUM DEU JOS JDG RUT 1SA 2SA 1KI 2KI 1CH 2CH EZR NEH EST JOB PSA PRO ECC SNG ISA JER LAM EZK DAN HOS JOL AMO OBA "
         "JON MIC NAM HAB ZEP HAG ZEC MAL MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP COL 1TH 2TH 1TI 2TI TIT PHM HEB JAS 1PE 2PE 1JN "
         "2JN 3JN JUD REV").split()


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def section(md: str, heading: str) -> str:
    """The body of a `## heading` section of the README (up to the next ## heading)."""
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    assert m, f"README has no section {heading!r}"
    return m[1].strip()


def table_after(md: str, first_cell: str) -> str:
    """The markdown table whose header row starts with `| first_cell |`."""
    lines = md.splitlines()
    i = next(n for n, l in enumerate(lines) if l.startswith(f"| {first_cell} |"))
    j = i
    while j < len(lines) and lines[j].startswith("|"):
        j += 1
    return "\n".join(lines[i:j])


def checks_table(build: dict) -> str:
    t = collections.Counter()
    for v in build["checks"].values():
        t["quotes"] += v["quotes"]; t["framed"] += v["quotes_with_frame"]; t["one_span"] += v["quotes_with_pieces_given_as_one_span"]
        n = v.get("tn_notes", {}); t["tn"] += n.get("placed", 0); t["tn_partial"] += n.get("of_them_partial", 0); t["tn_miss"] += n.get("not_found", 0)
        u = v.get("ult_alignment_words", {}); t["ult"] += u.get("placed", 0); t["ult_miss"] += u.get("not_found", 0)
        s = v.get("sections")
        if s:
            t["oshb"] += s["oshb"]; t["mam"] += s["mam"]; t["same_word"] += s["same_word"]; t["same_mark"] += s["same_word_same_mark"]
        e = v.get("nestle1904")
        if e:
            t["n_pass"] += e["passages"]; t["n_lines"] += e["with_printed_lines"]
    absent = sorted(b for b, v in build["checks"].items() if v.get("not_in_unfoldingword_release"))
    rows = [("Speeches with the verb that introduces them", f"{t['framed']:,} of {t['quotes']:,}"),
            ("Speeches the speaker layer joins across a speaking formula, given as one span (no pieces)", f"{t['one_span']:,}"),
            ("Translation Notes placed on the words they quote (of them partly: the quoted text differs a little) / not found",
             f"{t['tn']:,} ({t['tn_partial']:,}) / {t['tn_miss']:,}"),
            ("ULT alignment words placed / not found", f"{t['ult']:,} / {t['ult_miss']:,}"),
            ("Paragraph marks: Leningrad / MAM / at the same word / the same mark there",
             f"{t['oshb']:,} / {t['mam']:,} / {t['same_word']:,} / {t['same_mark']:,}"),
            ("Nestle 1904 passages with their printed lines", f"{t['n_lines']} of {t['n_pass']}"),
            ("Books not in unfoldingWord's release (no ULT lines or notes)", ", ".join(absent) or "none")]
    return "| Check | Whole Bible |\n|---|---|\n" + "\n".join(f"| {a} | {b} |" for a, b in rows) + \
        "\n\nPer book in `build.json` (`checks`)."


def sources_table(src: dict, used: set) -> str:
    rows = ["| Source | Licence | Share-alike | What it gives |", "|---|---|---|---|"]
    for s, r in src.items():
        if s in used:
            rows.append(f"| {r['name']} | {r['licence']} | {'yes' if r['share_alike'] == '1' else 'no'} | {r['gives']} |")
    return "\n".join(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    ours = ["macula/build_passage_facts.py", "macula/release_passage_facts.py", "macula/passage_facts_card.md", "macula/unfoldingword.py",
            "macula/mam.py", "macula/ubs.py", "macula/nestle1904_layout.py", "../resources/passage_facts"]
    code = subprocess.check_output(["git", "log", "-1", "--format=%h", "--", *ours], cwd=HERE.parent, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", *ours], cwd=HERE.parent, text=True).strip()
    assert a.allow_dirty or (code and not dirty), "commit the builder, its readers, the card and resources/passage_facts first (or --allow-dirty)"
    codes_before = pf.CODES.read_text(encoding="utf-8")
    a.out.mkdir(parents=True, exist_ok=False)
    tmp = a.out / "_by"
    assert pf.main(["--books", *BOOKS, "--out", str(a.out / "data")]) == 0
    assert pf.main(["--books", *BOOKS, "--out", str(tmp), "--licence", "by"]) == 0
    assert pf.CODES.read_text(encoding="utf-8") == codes_before, "codes.tsv changed during the build"
    (a.out / "data-cc-by").mkdir()
    for b in BOOKS:
        shutil.move(tmp / f"{b}.jsonl", a.out / "data-cc-by" / f"{b}.jsonl")
    by_build = json.loads((tmp / "build.json").read_text(encoding="utf-8"))
    shutil.rmtree(tmp)
    build = json.loads((a.out / "data" / "build.json").read_text(encoding="utf-8"))
    for name in ("codes.tsv", "sources.tsv", "build.json"):
        shutil.move(a.out / "data" / name, a.out / name)
    (a.out / "data" / "README.md").unlink()
    facts = sum(sum(v.values()) for v in build["books"].values())
    by_facts = sum(sum(v.values()) for v in by_build["books"].values())
    build.update(code=code, release={"data": "CC BY-SA 4.0", "data-cc-by": "CC BY 4.0", "facts": facts, "facts_cc_by": by_facts,
                                     "dropped_share_alike": by_build["dropped_share_alike"]})
    (a.out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    readme = pf.README.read_text(encoding="utf-8")
    src = pf.sources()
    card = CARD.read_text(encoding="utf-8")
    for k, v in {"@BUILT@": datetime.date.today().isoformat(), "@CODE@": code or "uncommitted", "@FACTS@": f"{facts:,}",
                 "@SA_FACTS@": f"{facts - by_facts:,}", "@BY_FACTS@": f"{by_facts:,}", "@SCHEMA@": str(pf.SCHEMA),
                 "@FIELDS@": table_after(section(readme, "A fact"), "Field"),
                 "@KINDS@": table_after(section(readme, "What each kind gives"), "Kind"),
                 "@SOURCES@": sources_table(src, set(build["sources"])), "@CHECKS@": checks_table(build)}.items():
        card = card.replace(k, v)
    assert not re.search(r"@[A-Z_]+@", card), "unfilled field in the card"
    (a.out / "README.md").write_text(card, encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(a.out)}\n" for p in files), encoding="utf-8")
    print(f"{facts:,} facts ({by_facts:,} CC BY) -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
