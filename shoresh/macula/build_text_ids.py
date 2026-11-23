"""Word ids for the texts that have none: the two Hebrew New Testaments and Brenton's Septuagint (the id standard of
2026-11-23, D2). Local, unpublished.

    cd shoresh && .venv/bin/python -m macula.build_text_ids [--out DIR]

An id is minted ONCE from the edition's verse text as bibles gives it (helloao route, verse-text rule and tokenizer of
macula/vendor_bibles; the tokenizer version and every book's text fingerprint are written to manifest.json), and is then
frozen: a later text or tokenizer change moves only the map from positions to ids, never the ids.

Shape: `<text>:BBCCCVVVWWW`, MACULA's word-id shape (Brenton: BBCCCVVVWWWW, four digits for the word, since its 1 Kings
12:24 holds the Greek addition 24a-z, 1,012 words). text = scg (Salkinson-Ginsburg), del (Delitzsch), bre (Brenton).
BB = the book number (MACULA's: 01-39 the Hebrew canon, 40-66 the NT; Brenton's ESG is Esther 17, DAG Daniel 27, EZR its
Esdras B with Nehemiah as chapters 11-23, as Brenton numbers it; the books outside the Hebrew canon: BOOKS_EXTRA, 67 up),
CCC chapter, VVV verse, WWW the word's position in the verse from 1 (the tokenizer's 0-based position + 1, so the
lexeme-aligner's target position p is word p + 1).

Hebrew NT parts: hebrew-nt-analysis v0.2's parts of each word (MACULA-style level 1: prefixed particles, stem, suffix), id =
word id + part digit (its `part` + 1): `scg:400010010021`. Level 2 (the Tanakh's inflection cut) will add one sub-part digit.

Writes, per text, words.tsv (word_id, book, chapter, verse, position (0-based, the aligner's), token as the tokenizer gives
it; Hebrew NTs also `class` from hebrew-nt-analysis, verse-number tokens included since the aligner counts them) and, for the
Hebrew NTs, parts.tsv (part_id, word_id, part, text as hebrew-nt-analysis cuts it, class); manifest.json; checks.md.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "internal-docs" / "text-ids" / "v0.1"
HELLOAO = HERE / "data" / "helloao"
ANALYSIS = HERE / "data" / "bridge-corpus" / "inputs" / "hebrew-nt-analysis@v0.2"
BOOKS = ("GEN EXO LEV NUM DEU JOS JDG RUT 1SA 2SA 1KI 2KI 1CH 2CH EZR NEH EST JOB PSA PRO ECC SNG ISA JER LAM EZK DAN HOS JOL AMO "
         "OBA JON MIC NAM HAB ZEP HAG ZEC MAL MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP COL 1TH 2TH 1TI 2TI TIT PHM HEB JAS 1PE "
         "2PE 1JN 2JN 3JN JUD REV").split()
NUMBER = {b: i for i, b in enumerate(BOOKS, 1)}
NUMBER.update({"ESG": 17, "DAG": 27})
BOOKS_EXTRA = ["TOB", "JDT", "WIS", "SIR", "BAR", "LJE", "SUS", "BEL", "1MA", "2MA", "3MA", "4MA", "1ES", "MAN"]
NUMBER.update({b: 67 + i for i, b in enumerate(BOOKS_EXTRA)})
TEXTS = {"heb_scg": "scg", "heb_mod": "del", "grc_bre": "bre"}


WORD_DIGITS = {"scg": 3, "del": 3, "bre": 4}   # Brenton: 4 (its 1 Kings 12:24 holds 24a-z, 1,012 words)


def wid(text: str, book: str, c: int, v: int, pos: int) -> str:
    w = WORD_DIGITS[text]
    if not (c < 1000 and v < 1000 and pos + 1 < 10 ** w):
        raise SystemExit(f"{text} {book} {c}:{v} position {pos}: outside the id shape")
    return f"{text}:{NUMBER[book]:02d}{c:03d}{v:03d}{pos + 1:0{w}d}"


def verses(edition: str):
    sys.path.insert(0, str(HERE / "vendor_bibles"))
    import bcv_tokenize, helloao_to_usj, verse_text
    by = collections.defaultdict(list)
    for f in (HELLOAO / edition).glob("*_*.json"):
        by[f.stem.rsplit("_", 1)[0]].append(json.loads(f.read_text()))
    out, fps = {}, {}
    for b, chs in sorted(by.items()):
        chs.sort(key=lambda d: d["chapter"]["number"])
        vt = verse_text.extract_usj(helloao_to_usj.merge_book_usj(b, chs))
        vs = {(int(c), int(x["verse"])): x["text"] for c, xs in vt.items() for x in xs}
        fps[b] = bcv_tokenize.fingerprints(vs)[0]
        for (c, v), t in vs.items():
            out[(b, c, v)] = bcv_tokenize.tokenize(t)
    return out, fps, bcv_tokenize.TOKENIZER_VERSION, (HERE / "vendor_bibles" / "VERSION").read_text().strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    if a.out.exists() and any(a.out.iterdir()):
        raise SystemExit(f"{a.out} is not empty; give a fresh folder")
    manifest, L = {"standard": "internal-docs/text-part-id-standard-draft-2026-11-23.md", "texts": {}}, ["# Word ids: checks", ""]
    for ed, text in TEXTS.items():
        d = a.out / text
        d.mkdir(parents=True)
        vs, fps, tv, vtv = verses(ed)
        fetch = json.loads((HELLOAO / ed / "fetch.json").read_text())
        st = collections.Counter()
        if text in ("scg", "del"):
            t = pq.read_table(ANALYSIS / ed / "words.parquet").to_pylist()
            words, parts = {}, []
            for r in sorted(t, key=lambda r: (NUMBER[r["book"]], r["chapter"], r["verse"], r["i"], r["part"])):
                w = wid(text, r["book"], r["chapter"], r["verse"], r["i"])
                if w not in words:
                    words[w] = (r["book"], r["chapter"], r["verse"], r["i"], r["token"], r["class"] if r["part"] == 0 else "")
                if r["part"] > 8:
                    raise SystemExit(f"{w}: more than 9 parts")
                parts.append((f"{w}{r['part'] + 1}", w, r["part"], r["text"], r["class"] or ""))
            # the analysis' tokens must be the tokenizer's, verse by verse
            per = collections.defaultdict(list)
            for k, x in sorted(words.items()):
                per[x[:3]].append(x[4])
            bad = [k for k, toks in vs.items() if per.get(k, []) != toks]
            st["verses"], st["words"], st["parts"], st["verses whose tokens differ from the tokenizer's"] = len(vs), len(words), len(parts), len(bad)
            with open(d / "words.tsv", "w", encoding="utf-8") as f:
                f.write("word_id\tbook\tchapter\tverse\tposition\ttoken\tclass\n")
                f.writelines("\t".join(map(str, (w, *x))) + "\n" for w, x in words.items())
            with open(d / "parts.tsv", "w", encoding="utf-8") as f:
                f.write("part_id\tword_id\tpart\ttext\tclass\n")
                f.writelines("\t".join(map(str, p)) + "\n" for p in parts)
            ids = [p[0] for p in parts]
        else:
            rows = []
            for (b, c, v), toks in sorted(vs.items(), key=lambda kv: (NUMBER[kv[0][0]], kv[0][1], kv[0][2])):
                for i, tok in enumerate(toks):
                    rows.append((wid(text, b, c, v, i), b, c, v, i, tok))
            st["verses"], st["words"] = len(vs), len(rows)
            with open(d / "words.tsv", "w", encoding="utf-8") as f:
                f.write("word_id\tbook\tchapter\tverse\tposition\ttoken\n")
                f.writelines("\t".join(map(str, r)) + "\n" for r in rows)
            ids = [r[0] for r in rows]
        st["duplicate ids"] = len(ids) - len(set(ids))
        manifest["texts"][text] = {"edition": f"h:{ed}", "route": fetch["route"], "fetched": fetch["fetched"],
                                   "chapter_files_sha256": hashlib.sha256(json.dumps(fetch["files"], sort_keys=True).encode()).hexdigest(),
                                   "tokenizer_version": tv, "bibles_verse_text": vtv, "book_text_fingerprints": fps,
                                   "analysis": "bcv-commons/hebrew-nt-analysis v0.2 (0c9132c3)" if text != "bre" else None,
                                   **dict(st)}
        L += [f"## {text} ({ed})", ""] + [f"- {k}: {v:,}" for k, v in st.items()] + [""]
    (a.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (a.out / "checks.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
