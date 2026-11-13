"""Package the word-parts datasets: every Greek NT word cut into preverb, augment, reduplication, stem and ending, and every Hebrew
word in MACULA's morphemes (macula/build_word_parts.py). Two datasets, one per route (the user, 2026-11-13: both are published, for
different uses):

  route a -> bcv-commons/word-parts      from MACULA alone, CC BY 4.0
  route b -> bcv-commons/word-parts-sa   route a plus MorphGNT's morphological lexicon and Perseus Morpheus's noun stems, CC BY-SA 4.0

    cd shoresh && .venv/bin/python3 -m macula.release_word_parts --route a|b --out DIR [--allow-dirty]

Nothing is uploaded. DIR gets data/src_part_grc.parquet, data/src_part_hbo.parquet, data/words_grc.parquet, exceptions_grc.tsv,
README.md (the card), build.json (with `schema`: raised only when a column is renamed, dropped or changes meaning) and SHA256SUMS.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from macula import build_word_parts as B
from macula import build_passage_facts as pf
from macula import release_guard  # refuses TBTA and private inputs

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 1
VERSION = "v0.1"
REPO = {"a": "bcv-commons/word-parts", "b": "bcv-commons/word-parts-sa"}
LICENCE = {"a": ("cc-by-4.0", "CC BY 4.0"), "b": ("cc-by-sa-4.0", "CC BY-SA 4.0")}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def table(rows, names, types):
    cols = list(zip(*rows)) if rows else [[] for _ in names]
    return pa.table({n: pa.array(list(c), type=t) for n, c, t in zip(names, cols, types)})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", choices=("a", "b"), required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "shoresh/macula"], cwd=ROOT, text=True).strip()
    if dirty and not a.allow_dirty:
        raise SystemExit(f"uncommitted changes in shoresh/macula:\n{dirty}")
    code = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=ROOT, text=True).strip() + ("+uncommitted" if dirty else "")
    words = B.read_grc(B.GRC_DIR)
    assert len(words) == 137779, len(words)
    srcb = B.read_route_b(B.MORPH_DIR) if a.route == "b" else None
    parts, wrows, rows, stems, _ = B.build_grc(words, a.route, srcb)
    hbo = B.build_hbo(pf.TREES)
    fails = sum("rebuild_failed" in w[6] for w in wrows)
    assert fails == 0, f"{fails} Greek words do not rebuild from their parts"
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "data").mkdir()
    S, I = pa.string(), pa.int16()
    pq.write_table(table(parts, ["key", "n", "text", "kind", "features"], [S, I, S, S, S]), a.out / "data/src_part_grc.parquet")
    pq.write_table(table(hbo, ["key", "n", "token", "text", "kind", "features"], [S, I, S, S, S, S]), a.out / "data/src_part_hbo.parquet")
    pq.write_table(table(wrows, ["key", "surface", "lemma", "morph", "group", "cut", "flags"], [S] * 7), a.out / "data/words_grc.parquet")
    # the exceptions, as the builder lists them
    tmp = a.out / ".build"
    import contextlib, io, sys
    argv = sys.argv
    sys.argv = ["build_word_parts", "--route", a.route, "--out", str(tmp)]
    with contextlib.redirect_stdout(io.StringIO()):
        B.main()
    sys.argv = argv
    (tmp / "exceptions_grc.tsv").rename(a.out / "exceptions_grc.tsv")
    checks = (tmp / "checks.md").read_text(encoding="utf-8")
    for p in tmp.iterdir():
        p.unlink()
    tmp.rmdir()
    meta = dict(sqlite3.connect(pf.TREES).execute("SELECT key, value FROM meta").fetchall())
    grc_files = sorted(B.GRC_DIR.glob("*.xml"))
    grc_sha = hashlib.sha256(b"".join(hashlib.sha256(p.read_bytes()).digest() for p in grc_files)).hexdigest()
    sources = {
        "macula_greek": {"name": "MACULA Greek, Nestle 1904 lowfat", "licence": "CC BY 4.0", "share_alike": "0",
                         "attribution": "MACULA Greek Linguistic Datasets, © 2022 by Clear Bible, Inc, https://github.com/Clear-Bible/macula-greek",
                         "files": len(grc_files), "sha256_of_file_hashes": grc_sha},
        "macula_hebrew": {"name": "MACULA Hebrew, WLC lowfat (through bcv-commons' trees database)", "licence": "CC BY 4.0",
                          "share_alike": "0",
                          "attribution": "MACULA Hebrew Linguistic Datasets, © 2022 by Clear Bible, Inc, https://github.com/Clear-Bible/macula-hebrew",
                          "trees_database": Path(pf.TREES).name, "trees_built": meta.get("built"), "trees_sha256": sha256(Path(pf.TREES))},
    }
    if srcb:
        sources["morphgnt_lexicon"] = {"name": "MorphGNT Morphological Lexicon: preverb analyses, verb ending paradigms, nominal endings",
                                       "licence": "CC BY-SA 3.0", "share_alike": "1",
                                       "attribution": "James K. Tauber et al., morphological-lexicon, https://github.com/morphgnt/morphological-lexicon",
                                       "files": {k: v for k, v in srcb["hashes"].items() if "morphological" in k}}
        sources["morpheus"] = {"name": "Perseus Morpheus stemlib: Greek noun stems", "licence": "CC BY-SA 3.0 US", "share_alike": "1",
                               "attribution": "Perseus Digital Library, Morpheus, https://github.com/perseids-tools/morpheus"}
    n_kinds = {}
    for p in parts:
        n_kinds[p[3]] = n_kinds.get(p[3], 0) + 1
    build = {"schema": SCHEMA, "version": VERSION, "route": a.route, "built": datetime.date.today().isoformat(), "code": code,
             "licence": LICENCE[a.route][1], "sources": sources,
             "counts": {"greek_words": len(wrows), "greek_parts": len(parts), "greek_parts_by_kind": n_kinds,
                        "hebrew_words": len({r[0] for r in hbo}), "hebrew_parts": len(hbo)}}
    (a.out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    card = (Path(__file__).with_name("word_parts_card.md")).read_text(encoding="utf-8")
    other = REPO["b" if a.route == "a" else "a"]
    rep = {"@LICENCE_ID@": LICENCE[a.route][0], "@LICENCE@": LICENCE[a.route][1], "@REPO@": REPO[a.route], "@OTHER@": other,
           "@VERSION@": VERSION, "@CODE@": code, "@BUILT@": build["built"], "@ROUTE@": a.route,
           "@GRC_WORDS@": f"{len(wrows):,}", "@GRC_PARTS@": f"{len(parts):,}", "@HBO_WORDS@": f"{build['counts']['hebrew_words']:,}",
           "@HBO_PARTS@": f"{len(hbo):,}", "@CHECKS@": checks.split("\n", 2)[2].replace("## ", "### "),
           "@ROUTE_TEXT@": ROUTE_TEXT[a.route], "@SOURCES@": SOURCES_TEXT[a.route]}
    for k, v in rep.items():
        card = card.replace(k, v)
    left = [k for k in ("@LICENCE", "@REPO", "@ROUTE", "@CHECKS", "@SOURCES", "@VERSION", "@CODE") if k in card]
    assert not left, f"card placeholders left: {left}"
    (a.out / "README.md").write_text(card, encoding="utf-8")
    sums = sorted(p for p in a.out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(a.out)}\n" for p in sums), encoding="utf-8")
    print(f"{REPO[a.route]} {VERSION} -> {a.out}: {len(wrows):,} Greek words, {len(parts):,} parts; {len(hbo):,} Hebrew parts")
    return 0


ROUTE_TEXT = {
    "a": "This is **route a**: built from MACULA alone, so it is CC BY 4.0. Its sister dataset "
         "[bcv-commons/word-parts-sa](https://huggingface.co/datasets/bcv-commons/word-parts-sa) (route b) adds MorphGNT's preverb "
         "analyses and endings and Morpheus's noun stems, and is therefore share-alike.",
    "b": "This is **route b**: route a (MACULA's own forms) with three additions from share-alike sources, so it is CC BY-SA 4.0: "
         "MorphGNT's preverb analyses decide which verbs are compounds; MorphGNT's verb and noun endings are added to the endings "
         "learned from the text; and a Perseus Morpheus noun stem is preferred where it fits as well as the learned one. Its sister "
         "dataset [bcv-commons/word-parts](https://huggingface.co/datasets/bcv-commons/word-parts) (route a) uses MACULA alone and is "
         "CC BY 4.0. The two cut 97.9 % of the Greek words alike; most of the rest is the third-declension boundary (route b: "
         "Morpheus's αἰῶ\\|νος; route a: αἰῶν\\|ος) and 534 words whose preverb route b splits and route a does not.",
}
SOURCES_TEXT = {
    "a": "| MACULA Greek (Nestle 1904 lowfat) | CC BY 4.0 | the Greek words, their lemmas and parsing |\n"
         "| MACULA Hebrew (WLC lowfat) | CC BY 4.0 | the Hebrew morphemes |",
    "b": "| MACULA Greek (Nestle 1904 lowfat) | CC BY 4.0 | the Greek words, their lemmas and parsing |\n"
         "| MACULA Hebrew (WLC lowfat) | CC BY 4.0 | the Hebrew morphemes |\n"
         "| [MorphGNT Morphological Lexicon](https://github.com/morphgnt/morphological-lexicon) (James K. Tauber et al.) | CC BY-SA 3.0 | "
         "preverb analyses (`projects/preverbs/verbs.txt`), verb ending paradigms, nominal endings |\n"
         "| [Perseus Morpheus](https://github.com/perseids-tools/morpheus) stemlib (Perseus Digital Library) | CC BY-SA 3.0 US | Greek "
         "noun stems |",
}

if __name__ == "__main__":
    raise SystemExit(main())
