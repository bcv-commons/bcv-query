"""Level-1 fixes for Delitzsch's unpointed אתם: the pronoun אַתֶּם ("you", whole) or את + ם ("them", "with them").

    cd shoresh && .venv/bin/python -I -m macula.hebrew_nt_level1_fixes --tables DIR --join DIR --greek-parts parts.tsv \
        --out FILE.tsv

hebrew-nt-analysis cuts Delitzsch's unpointed אתם without seeing the Greek. Each token is decided here, in this order:
1. greek2: a linked Greek word is second person: σύ, a 2nd-person plural verb, or nominative plural αὐτός (καὶ αὐτοί, "you
   yourselves") -> the pronoun, whole.
2. greek3: a linked Greek word is a 3rd-person plural pronoun (αὐτός, ἑαυτοῦ, οὗτος) outside the nominative -> את + ם; את is
   the preposition (with) for a dative or μετά / σύν, else the object marker.
3. Otherwise the analysis' cut stays (no row). Salkinson's pointed text is no guide: it renders such verses otherwise (3 of 3
   changes it gave were wrong, 2026-11-23: 1JN 4:4, ACT 4:8, LUK 11:47).
Writes one row per token whose cut changes: word_id ref position from_cut to_cut rule greek. The links are read through the
NT tree join (the aligner's cells on the table version given); build_text_ids --fixes applies the table.
"""
from __future__ import annotations

import argparse
import collections
import csv
import sqlite3
from pathlib import Path

import pyarrow.parquet as pq

THIRD = ("αὐτός", "ἑαυτοῦ", "οὗτος")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tables", type=Path, required=True, help="aligner tables folder (heb_mod, heb_scg words.parquet)")
    ap.add_argument("--join", type=Path, required=True, help="NT tree join folder (by/part_links, by/parts)")
    ap.add_argument("--greek-parts", type=Path, required=True, help="word-parts v1.1 greek/parts.tsv")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    feats, part_word = collections.defaultdict(set), {}
    with open(a.greek_parts, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            part_word[r["part_id"]] = r["word_id"]
            if r["features"]:
                feats[r["word_id"]].add(r["features"])
    db = sqlite3.connect(f"file:{Path(__file__).resolve().parent / 'trees-macula.db'}?mode=ro", uri=True)
    lemma = dict(db.execute("select key, lemma from words where lemma is not null"))

    tok = collections.defaultdict(list)
    for r in pq.read_table(a.tables / "heb_mod" / "words.parquet").to_pylist():
        tok[(r["book"], r["chapter"], r["verse"], r["i"])].append(r)
    A = {k: v for k, v in tok.items() if v[0]["token"] == "אתם"}
    piece_tok = {r["part2_id"]: k for k, v in A.items() for r in v}
    linked = collections.defaultdict(set)
    for l in pq.read_table(a.join / "by" / "part_links.parquet", filters=[("edition", "=", "heb_mod")],
                           columns=["greek_part_id", "hebrew_piece_id"]).to_pylist():
        k = piece_tok.get(l["hebrew_piece_id"])
        if k and l["greek_part_id"] in part_word:
            linked[k].add(part_word[l["greek_part_id"]])
    def case_number(f: str) -> tuple[str, str]:
        """P-APM -> (A, P); F-3GPM -> (G, P); P-2NP -> (N, P); anything else -> ('', '')."""
        p = f.split("-")
        if len(p) < 2 or p[0] not in ("P", "F", "D", "R"):
            return "", ""
        c = p[1].lstrip("123")
        return (c[0], c[1]) if len(c) >= 2 else ("", "")

    rows, st = [], collections.Counter()
    for k, v in sorted(A.items()):
        cut = "split" if len(v) == 2 else "whole"
        you = them = False
        them_prep = False
        for w in linked[k]:
            lm, fs = lemma.get(w, ""), feats.get(w, set())
            if lm == "σύ" or any(f.startswith("V-") and f.split("-")[-1][:2] == "2P" for f in fs):
                you = True
            if lm in THIRD:
                for c, n in map(case_number, fs):
                    if n != "P":
                        continue
                    if lm == "αὐτός" and c == "N":
                        you = True
                    elif c in ("A", "G", "D"):
                        them = True
                        them_prep |= c == "D"
            if lm in ("μετά", "σύν"):
                them_prep = True
        if you and not them:
            to, rule = "whole", "greek2"
        elif them and not you:
            to, rule = ("split_prep" if them_prep else "split_om"), "greek3"
        else:
            st["kept: no evidence"] += 1
            continue
        st[f"{rule}: {cut} -> {to.split('_')[0]}"] += 1
        if (to == "whole") != (cut == "whole"):
            rows.append({"word_id": f"del:{v[0]['part_id'][4:-1]}", "ref": f"{k[0]} {k[1]}:{k[2]}", "position": k[3],
                         "from_cut": cut, "to_cut": to, "rule": rule,
                         "greek": " ".join(sorted(lemma.get(w, "?") for w in linked[k]))})
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("word_id\tref\tposition\tfrom_cut\tto_cut\trule\tgreek\n")
        f.writelines("\t".join(str(r[c]) for c in ("word_id", "ref", "position", "from_cut", "to_cut", "rule", "greek")) + "\n"
                     for r in rows)
    for s, n in sorted(st.items()):
        print(f"{n:5}  {s}")
    print(f"{len(rows)} changes -> {a.out}")


if __name__ == "__main__":
    main()


FIXES = Path(__file__).resolve().parent / "text_faults" / "level1_fixes.tsv"
EDITION = "heb_mod"   # the table is Delitzsch's


def apply(ed: str, rows: list[dict]) -> list[dict]:
    """hebrew-nt-analysis rows of `ed` with the level-1 fixes of FIXES applied (source `rule`). Other editions as they are."""
    if ed != EDITION or not FIXES.exists():
        return rows
    fix = {}
    with open(FIXES, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            b, cv = r["ref"].split()
            c, v = cv.split(":")
            fix[(b, int(c), int(v), int(r["position"]))] = r["to_cut"]
    by = collections.defaultdict(list)
    for r in rows:
        by[(r["book"], r["chapter"], r["verse"], r["i"])].append(r)
    out, done = [], 0
    for k, ps in by.items():
        to = fix.get(k)
        if to is None:
            out += ps
            continue
        r0 = min(ps, key=lambda r: r["part"])
        if r0["token"] != "אתם":
            raise SystemExit(f"{FIXES.name}: {k} is {r0['token']!r}, not אתם")
        base = {**r0, "source": "rule", "form": None, "person": None, "role": None}
        if to == "whole":
            out.append({**base, "part": 0, "text": "אתם", "class": "pron", "lemma": "אַתֶּם", "lexeme": "hbo:0859a",
                        "strong": "0859a", "role": r0["role"]})
        else:
            prep = to == "split_prep"
            out.append({**base, "part": 0, "text": "את", "class": "prep" if prep else "om", "lemma": "אֵת",
                        "lexeme": "hbo:0854" if prep else "hbo:0853", "strong": "0854" if prep else "0853"})
            out.append({**base, "part": 1, "text": "ם", "class": "pron", "lemma": "הוּא", "lexeme": "hbo:2050c",
                        "strong": "2050c", "p_split": None})
        done += 1
    if done != len(fix):
        raise SystemExit(f"{FIXES.name}: {len(fix) - done} rows found no token")
    return out
