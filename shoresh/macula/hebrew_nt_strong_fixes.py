"""Strong's-number fixes for hebrew-nt-analysis v0.2: model-made parts whose number the Tanakh contradicts.

    cd shoresh && .venv/bin/python -I -m macula.hebrew_nt_strong_fixes            -> text_faults/strong_fixes.tsv
    from macula import hebrew_nt_strong_fixes as SF; rows = SF.apply(ed, rows)     # the analysis' rows, fixed

The tagger gives a part a lexeme (lemma, lexeme id, Strong's number) without seeing the Tanakh's numbering. A part is fixed
when all of these hold (the "likely wrong" rule of the check of 2026-11-24, internal-docs/hebrew-nt-analysis-checks/):
  - it is a content part (noun, verb, adj, adv, num) made by the tagger (source `model`) and has a number, of three
    letters or more (a shorter "content" part is mostly a split fault, which a number cannot mend);
  - MACULA's Tanakh has its consonantal surface at least 3 times, and gives one number (sub-entry letters ignored) at
    least 90% of the time;
  - the part's number is not among the Tanakh's numbers for the surface;
  - the Tanakh's lemma fits the surface's letters and the part's own lemma does not (letters in order; matres and a
    final ה dropped).
The fix takes the Tanakh's commonest lexeme for the surface (lemma, lexeme id, number) and gives the row source `rule`.
Everything else stays as the analysis has it: a wrong word whose letters still fit is not caught (a lower bound).
Surfaces in EXCLUDE are never fixed: the reading of examples 1.8 (OPEN-1.8 Y5) found the Tanakh's commonest lexeme
wrong for them in the New Testament, and they keep the analysis's value.
Writes one row per fixed part: edition book chapter verse i part text from_strong from_lemma to_strong to_lemma to_lexeme.
"""
from __future__ import annotations

import collections
import csv
import re
import sqlite3
import unicodedata as ud
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ANALYSIS = HERE / "data" / "bridge-corpus" / "inputs" / "hebrew-nt-analysis@v0.2"
SPINE = HERE / "lexeme-spine-macula.db"
FIXES = HERE / "text_faults" / "strong_fixes.tsv"
CONTENT = {"noun", "verb", "adj", "adv", "num"}
COLS = ["edition", "book", "chapter", "verse", "i", "part", "text", "from_strong", "from_lemma", "to_strong", "to_lemma",
        "to_lexeme"]
FIN = str.maketrans("ךםןףץ", "כמנפצ")
EXCLUDE = {
    "מגרש": "a participle of גָּרַשׁ 'drives out', not the noun מִגְרָשׁ",
    "צידה": "in the New Testament the second part of Bethsaida, a name with no Tanakh number",
    "יחי": "a split fault of יְחִידוֹ (יָחִיד), not חָיָה",
}


def cons(t: str | None) -> str:
    return "".join(x for x in ud.normalize("NFD", t or "") if "א" <= x <= "ת").translate(FIN)


def num(s) -> str:
    """'0571' -> '571', '3162a' -> '3162'"""
    return re.sub(r"[a-z]+$", "", str(s or "")).lstrip("0")


def fits(lemma: str, text: str) -> bool:
    """the lemma's letters (inner ו / י and a final ה dropped) occur in order in the text's letters"""
    c = cons(lemma)
    c = c[:-1] if len(c) > 2 and c[-1] == "ה" else c
    skel = c[:1] + c[1:].replace("ו", "").replace("י", "")
    it = iter(cons(text))
    return bool(skel) and all(ch in it for ch in skel)


def tanakh() -> dict[str, collections.Counter]:
    """consonantal surface -> Counter of (lexeme id, lemma) over MACULA's Tanakh word parts"""
    out: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    for surf, lex, lemma in db.execute("select surface, lexeme, lemma from spine_words where length(key) = 12 and lexeme like 'hbo:%'"):
        out[cons(surf)][(lex, lemma)] += 1
    return out


def build() -> list[dict]:
    tan = tanakh()
    rows = []
    for ed in ("heb_scg", "heb_mod"):
        for r in pq.read_table(ANALYSIS / ed / "words.parquet").to_pylist():
            if r["class"] not in CONTENT or not r["strong"] or r["source"] != "model":
                continue
            c = cons(r["text"])
            if len(c) < 3 or c in EXCLUDE:        # one- and two-letter parts: mostly a split fault, not a number fault
                continue
            t = tan.get(c)
            if not t:
                continue
            by_num = collections.Counter()
            for (lex, _), k in t.items():
                by_num[num(lex[4:])] += k
            n = num(r["strong"])
            total = sum(by_num.values())
            if n in by_num or total < 3:
                continue
            top, k = by_num.most_common(1)[0]
            if k / total < 0.9:
                continue
            (lex, lemma), _ = max(((x, v) for x, v in t.items() if num(x[0][4:]) == top), key=lambda xv: xv[1])
            if not fits(lemma, c) or fits(r["lemma"] or "", c):
                continue
            rows.append({"edition": ed, "book": r["book"], "chapter": r["chapter"], "verse": r["verse"], "i": r["i"],
                         "part": r["part"], "text": r["text"], "from_strong": r["strong"], "from_lemma": r["lemma"] or "",
                         "to_strong": lex[4:], "to_lemma": lemma, "to_lexeme": lex})
    return rows


def load(ed: str) -> dict[tuple, dict]:
    if not FIXES.exists():
        return {}
    with open(FIXES, encoding="utf-8", newline="") as f:
        return {(r["book"], int(r["chapter"]), int(r["verse"]), int(r["i"]), int(r["part"])): r
                for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE) if r["edition"] == ed}


def apply(ed: str, rows: list[dict]) -> list[dict]:
    """hebrew-nt-analysis rows of `ed` with the number fixes applied (lemma, lexeme, strong; source `rule`)."""
    fix = load(ed)
    if not fix:
        return rows
    out, done = [], 0
    for r in rows:
        f = fix.get((r["book"], r["chapter"], r["verse"], r["i"], r["part"]))
        if f is None:
            out.append(r)
            continue
        if r["text"] != f["text"] or (r["strong"] or "") != f["from_strong"]:
            raise SystemExit(f"{FIXES.name}: {ed} {r['book']} {r['chapter']}:{r['verse']} {r['i']}.{r['part']} is "
                             f"{r['text']!r} {r['strong']!r}, not {f['text']!r} {f['from_strong']!r}")
        out.append({**r, "strong": f["to_strong"], "lemma": f["to_lemma"], "lexeme": f["to_lexeme"], "source": "rule"})
        done += 1
    if done != len(fix):
        raise SystemExit(f"{FIXES.name}: {len(fix) - done} {ed} rows found no part")
    return out


def main() -> None:
    rows = build()
    with open(FIXES, "w", encoding="utf-8") as f:
        f.write("\t".join(COLS) + "\n")
        f.writelines("\t".join(str(r[c]) for c in COLS) + "\n" for r in rows)
    n = collections.Counter(r["edition"] for r in rows)
    print(f"{len(rows)} fixes ({dict(n)}) -> {FIXES}")


if __name__ == "__main__":
    main()
