"""Candidates for the fixed-pair list: Greek words that a Hebrew NT renders with two words, of which the aligner links one.

    cd shoresh && .venv/bin/python -I -m macula.nt_pair_candidates --tables DIR --join DIR --greek-parts parts.tsv --out FILE.tsv

Two rules, on the aligner's links as the NT tree join holds them (tables version given):
  A construct   a Greek word's only linked content word is a noun in construct (level-2 state c), and the next word, a noun or
                adjective, has no link at all (רב המסבה, מבקשי חן).
  B salkinson   Salkinson links the Greek word to two or more content words and Delitzsch to one; a content word of Delitzsch's
                verse with one of the missing Strong's numbers has no link.
Rows are grouped by Greek lemma and the Hebrew Strong's pair (in text order). `tanakh_pairs` counts the pair in MACULA Hebrew
as for pairs v0.1: the second word within two parts of the first, skipping the article, the conjunction, the prepositions
ב ל מן, כל, את and אשר. The list is for reading, not for use as is: every pair taken into the fixed pairs is read first.
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
import sqlite3
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
SKIP = {1886, 2050, 871, 3807, 3605, 4480, 853, 3588, 834, 854}
CONTENT = ("noun", "verb", "adj", "adjv", "propn", "ptcp")


def snum(s) -> int | None:
    m = re.match(r"\d+", str(s or ""))
    return int(m.group()) if m else None


def tokens(tables: Path, ed: str) -> tuple[dict, dict]:
    """token key -> {strong, cls, construct, text}; piece id -> token key (content tokens only carry a strong)."""
    tok, piece = {}, {}
    by = collections.defaultdict(list)
    for r in pq.read_table(tables / ed / "words.parquet").to_pylist():
        k = (r["book"], r["chapter"], r["verse"], r["i"])
        by[k].append(r)
        if r["part2_id"]:
            piece[r["part2_id"]] = k
    for k, rs in by.items():
        host = [r for r in rs if (r["class"] or "") in CONTENT]
        h = host[0] if host else None
        feats = [r["level2_features"] or "" for r in rs if r["part_id"] == (h or {}).get("part_id")]
        tok[k] = {"strong": snum(h["strong"]) if h else None, "cls": h["class"] if h else "", "text": rs[0]["token"],
                  "construct": any(f[:1] in ("N", "A") and f.endswith("c") for f in feats)}
    return tok, piece


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tables", type=Path)
    ap.add_argument("--join", type=Path)
    ap.add_argument("--greek-parts", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pairs", type=Path, help="instead: fill tanakh_pairs, lxx_with_greek_lemma and support of a chosen pair "
                    "list (greek_lemma greek_strong hebrew_pair hebrew_strongs) in the fixed-pairs format, to --out; with --tables, --join and --greek-parts also nt_strongs: the NT "
                    "analyses' commonest numbers for the pair where they differ from MACULA's")
    a = ap.parse_args()
    if a.pairs:
        return fill_pairs(a.pairs, a.out, a.tables, a.join, a.greek_parts)

    part_word = {}
    with open(a.greek_parts, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            part_word[r["part_id"]] = r["word_id"]
    db = sqlite3.connect(f"file:{HERE / 'trees-macula.db'}?mode=ro", uri=True)
    glem = {k: (l, s) for k, l, s in db.execute("select key, lemma, strong from words where lemma is not null")}

    T, P, G = {}, {}, {}
    for ed in ("heb_scg", "heb_mod"):
        T[ed], P[ed] = tokens(a.tables, ed)
        g = collections.defaultdict(set)          # (verse, greek word) -> linked token keys
        linked = set()
        for l in pq.read_table(a.join / "by" / "part_links.parquet", filters=[("edition", "=", ed)],
                               columns=["greek_part_id", "hebrew_piece_id"]).to_pylist():
            k = P[ed].get(l["hebrew_piece_id"])
            w = part_word.get(l["greek_part_id"])
            if k and w:
                g[w].add(k)
                linked.add(k)
        G[ed] = (g, linked)

    cand = collections.defaultdict(lambda: {"A": 0, "B": 0, "refs": []})

    def add(rule, w, k1, k2, ed):
        t = T[ed]
        s1, s2 = t[k1]["strong"], t[k2]["strong"]
        if not s1 or not s2 or s1 == s2:
            return
        lm, gs = glem.get(w, ("?", ""))
        c = cand[(lm, gs, s1, s2)]
        c[rule] += 1
        c.setdefault("pair", f"{t[k1]['text']} {t[k2]['text']}")
        if len(c["refs"]) < 4:
            c["refs"].append(f"{ed[4:]} {k1[0]} {k1[1]}:{k1[2]}")

    for ed in ("heb_scg", "heb_mod"):
        g, linked = G[ed]
        t = T[ed]
        for w, ks in g.items():
            content = [k for k in ks if t[k]["strong"]]
            if len(content) != 1:
                continue
            k = content[0]
            nxt = (k[0], k[1], k[2], k[3] + 1)
            if t[k]["construct"] and nxt in t and t[nxt]["cls"] in ("noun", "adj", "adjv") and nxt not in linked:
                add("A", w, k, nxt, ed)
    gs_, _ = G["heb_scg"]
    gd, linked_d = G["heb_mod"]
    td, ts = T["heb_mod"], T["heb_scg"]
    by_verse = collections.defaultdict(list)
    for k in td:
        by_verse[k[:3]].append(k)
    for w, kd in gd.items():
        cd = [k for k in kd if td[k]["strong"]]
        cs = [k for k in gs_.get(w, ()) if ts[k]["strong"]]
        if len(cd) != 1 or len(cs) < 2:
            continue
        missing = {ts[k]["strong"] for k in cs} - {td[cd[0]]["strong"]}
        for k2 in by_verse[cd[0][:3]]:
            if td[k2]["strong"] in missing and k2 not in linked_d:
                a1, a2 = sorted((cd[0], k2), key=lambda k: k[3])
                add("B", w, a1, a2, "heb_mod")

    tan = tanakh_counts({(k[2], k[3]) for k in cand})
    write_candidates(a.out, cand, tan)


def tanakh_counts(want: set, greek: dict | None = None) -> collections.Counter:
    """(s1, s2) -> times s2 follows s1 in MACULA Hebrew (within two parts, skipping SKIP); with `greek` ({(s1, s2): greek
    strong}), also (s1, s2, 'lxx') -> how many of those MACULA's Septuagint word renders with that Greek word."""
    sp = sqlite3.connect(f"file:{HERE / 'lexeme-spine-macula.db'}?mode=ro", uri=True)
    verse = collections.defaultdict(list)
    for b, c, v, s, gs in sp.execute("select book, chapter, verse, strong, greekstrong from spine_words where length(key) = 12 "
                                     "order by book, chapter, verse, idx"):    # Hebrew rows only (Greek keys have 11 digits)
        verse[(b, c, v)].append((s, str(gs or "")))
    tan = collections.Counter()
    for ss in verse.values():
        for i, (s, g1) in enumerate(ss):
            if s in SKIP:
                continue
            seen = 0
            for s2, g2 in ss[i + 1:]:
                if s2 in SKIP:
                    continue
                seen += 1
                if (s, s2) in want:
                    tan[(s, s2)] += 1
                    if greek and greek.get((s, s2)) in (g1, g2):
                        tan[(s, s2, "lxx")] += 1
                if seen >= 2:
                    break
    return tan


def write_candidates(out: Path, cand: dict, tan: collections.Counter) -> None:
    rows = []
    for (lm, gs, s1, s2), c in cand.items():
        n = c["A"] + c["B"]
        if n >= 2 or tan[(s1, s2)] >= 2:
            rows.append((lm, gs, c["pair"], f"{s1} {s2}", c["A"], c["B"], tan[(s1, s2)], "; ".join(c["refs"])))
    rows.sort(key=lambda r: -(r[4] + r[5]))
    with open(out, "w", encoding="utf-8") as f:
        f.write("greek_lemma\tgreek_strong\thebrew_pair\thebrew_strongs\trule_a\trule_b\ttanakh_pairs\trefs\n")
        f.writelines("\t".join(map(str, r)) + "\n" for r in rows)
    print(f"{len(cand)} candidate pairs, {len(rows)} kept (2+ cases or Tanakh support) -> {out}")


def cons(t: str) -> str:
    import unicodedata as ud
    c = "".join(x for x in ud.normalize("NFD", t) if "\u05d0" <= x <= "\u05ea")
    return c.translate(str.maketrans("ךםןףץ", "כמנפצ"))


def nt_numbers(tables: Path, join: Path, greek_parts: Path, rows: list[dict]) -> dict:
    """pair index -> the NT analyses' commonest Strong's numbers for its two words, read where the aligner links the pair's
    Greek word to a word with the first word's consonants and the second word (by consonants) is within two words after it.
    Words, not pieces: the number is the word's content part's."""
    part_word = {}
    with open(greek_parts, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            part_word[r["part_id"]] = r["word_id"]
    db = sqlite3.connect(f"file:{HERE / 'trees-macula.db'}?mode=ro", uri=True)
    glem = dict(db.execute("select key, lemma from words where lemma is not null"))
    want = collections.defaultdict(list)                         # greek lemma -> pair indexes
    for i, r in enumerate(rows):
        for l in r["greek_lemma"].split(" / "):
            want[l.strip()].append(i)
    bare = lambda t: t[1:] if len(t) > 3 and t[0] in "והבלמכש" else t
    seen = collections.defaultdict(lambda: (collections.Counter(), collections.Counter()))
    for ed in ("heb_scg", "heb_mod"):
        tok, piece = tokens(tables, ed)
        for l in pq.read_table(join / "by" / "part_links.parquet", filters=[("edition", "=", ed)],
                               columns=["greek_part_id", "hebrew_piece_id"]).to_pylist():
            k = piece.get(l["hebrew_piece_id"])
            lm = glem.get(part_word.get(l["greek_part_id"], ""), "")
            if not k or lm not in want:
                continue
            for i in want[lm]:
                w1, w2 = (cons(w) for w in rows[i]["hebrew_pair"].split())
                t1 = cons(tok[k]["text"])
                if not (bare(bare(t1)).startswith(w1.rstrip("יתה")[:3]) or t1.startswith(w1.rstrip("יתה")[:3])):
                    continue
                for d in (1, 2):
                    k2 = (*k[:3], k[3] + d)
                    if k2 in tok and bare(bare(cons(tok[k2]["text"]))).startswith(bare(w2)[:3]):
                        seen[i][0][tok[k]["strong"]] += 1
                        seen[i][1][tok[k2]["strong"]] += 1
                        break
    return {i: tuple(c.most_common(1)[0][0] for c in v) for i, v in seen.items()}


def fill_pairs(src: Path, out: Path, tables: Path | None = None, join: Path | None = None, greek_parts: Path | None = None) -> None:
    with open(src, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))
    key = lambda r: tuple(int(x.lstrip("H")) for x in r["hebrew_strongs"].split())
    tan = tanakh_counts({key(r) for r in rows}, {key(r): r["greek_strong"] for r in rows})
    nt = nt_numbers(tables, join, greek_parts, rows) if tables else {}
    with open(out, "w", encoding="utf-8") as f:
        f.write("greek_lemma\tgreek_strong\thebrew_pair\thebrew_strongs\ttanakh_pairs\tlxx_with_greek_lemma\tsupport"
                + ("\tnt_strongs" if tables else "") + "\n")
        for i, r in enumerate(rows):
            k = key(r)
            t = tan[k]
            cells = [r["greek_lemma"], r["greek_strong"], r["hebrew_pair"], " ".join(f"H{x}" for x in k), str(t),
                     str(tan[(*k, "lxx")]), "tanakh" if t >= 2 else "nt_only"]
            if tables:
                n = nt.get(i)
                m = tuple(x or y for x, y in zip(n, k)) if n else k        # no NT number (a function word): MACULA's
                cells.append("" if m == k else " ".join(f"H{x}" for x in m))
            f.write("\t".join(cells) + "\n")
    print(f"{len(rows)} pairs -> {out}")


if __name__ == "__main__":
    main()
