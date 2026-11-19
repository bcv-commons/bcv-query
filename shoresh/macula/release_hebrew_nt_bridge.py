"""Package the Hebrew NT bridge as a release of the dataset bcv-commons/hebrew-nt-bridge. Nothing is uploaded: the files are written
to a folder for review, and published by hand.

    python -m macula.release_hebrew_nt_bridge --tag v0.1 --out DIR [--allow-dirty]

DIR (which must not exist yet) gets:
  README.md                     the dataset card (macula/hebrew_nt_bridge_card.md with the figures of report.json filled in)
  pairs/<edition>.tsv           the lexeme pairs of resources/hebrew_nt_bridge (count >= 3)
  quotes/<edition>.tsv          the Hebrew NT verses that follow a Tanakh verse (resources/hebrew_nt_bridge/quotes)
  links/<edition>.parquet       one row per Greek word and linked Hebrew word part (macula/data/hebrew-nt-bridge/<edition>/links.parquet)
  articles/<edition>.parquet    (from v0.3) every Greek article with its Hebrew part by rule (macula/hebrew_nt_articles.py, S1b)
  function_words/<edition>.parquet  (from v0.3) every Greek preposition, pronoun and conjunction with its Hebrew part(s) by rule
                                (macula/hebrew_nt_function_words.py, S1c)
  report.json                   the figures: per edition, the two editions against each other, each against the Septuagint tiers
  SHA256SUMS

The files must come from committed code and committed pair files (`git status` clean for the builder, the tagger, the card, this
script and resources/hebrew_nt_bridge), unless --allow-dirty. The links files are rebuilt outputs (not in git): run
`python -m macula.build_hebrew_nt_bridge` on the committed code first; the release checks that their pair counts equal the pair files.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from macula import build_hebrew_nt_bridge as b
from macula import release_guard  # refuses TBTA and private inputs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CARD = HERE / "hebrew_nt_bridge_card.md"
CODE = [HERE / "build_hebrew_nt_bridge.py", HERE / "clause_tagger.py", HERE / "hebrew_nt_articles.py", HERE / "hebrew_nt_function_words.py", Path(__file__).resolve(), CARD, b.OUT]
EDITIONS = ("heb_scg", "heb_mod")
FIELD = {"heb_scg": "SCG", "heb_mod": "MOD"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    out = Path(a.out)
    if out.exists():
        raise SystemExit(f"{out} exists; give a folder that does not exist yet")
    if not a.allow_dirty:
        dirty = subprocess.run(["git", "status", "--porcelain", "--", *map(str, CODE)], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        if dirty:
            raise SystemExit("uncommitted changes in the bridge's code, card or pair files; commit first (or --allow-dirty):\n" + dirty)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    report = json.loads((b.OUT / "report.json").read_text())
    import pyarrow.parquet as pq
    (out / "pairs").mkdir(parents=True)
    (out / "links").mkdir()
    (out / "quotes").mkdir()
    (out / "articles").mkdir()
    (out / "function_words").mkdir()
    from macula import hebrew_nt_function_words as F
    fw_stats = {}
    from macula import hebrew_nt_articles as A
    import pyarrow as pa
    art_stats = {}
    files = []
    for ed in EDITIONS:
        rows = pq.read_table(b.DATA / ed / "links.parquet").to_pylist()
        tsv = b.HEADER + "".join("\t".join(map(str, r)) + "\n" for r in b.tier(rows, ed))
        if tsv != (b.OUT / f"{ed}.tsv").read_text():
            raise SystemExit(f"{ed}: the links file does not give the committed pair file; rebuild with macula.build_hebrew_nt_bridge")
        bad = collections.Counter(k for r in rows for k, v in r.items() if isinstance(v, str) and k not in
                                  ("greek_lemma", "hebrew_lemma") and not v.isascii())
        if bad:
            raise SystemExit(f"{ed}: non-ASCII values outside the lemma columns: {dict(bad)}")
        shutil.copy(b.OUT / f"{ed}.tsv", out / "pairs" / f"{ed}.tsv")
        shutil.copy(b.DATA / ed / "links.parquet", out / "links" / f"{ed}.parquet")
        shutil.copy(b.OUT / "quotes" / f"{ed}.tsv", out / "quotes" / f"{ed}.tsv")
        if {r["tanakh"] for r in rows if r["tanakh"]} - {l.split("\t")[1] for l in (b.OUT / "quotes" / f"{ed}.tsv").read_text().splitlines()[1:]}:
            raise SystemExit(f"{ed}: the links file marks Tanakh verses the committed quotes file lacks; rebuild")
        files += [out / "pairs" / f"{ed}.tsv", out / "links" / f"{ed}.parquet", out / "quotes" / f"{ed}.tsv"]
        hw = {(r["book"], r["chapter"], r["verse"], r["i"], r["part"]): r for r in
              pq.read_table(A.ANALYSIS / ed / "words.parquet", columns=["book", "chapter", "verse", "i", "part", "text", "lemma", "strong", "class"]).to_pylist()}
        arows = []
        for gid, x in sorted(A.links(ed).items()):
            book, ch, vs = x["verse"]
            for i, part in x["parts"] or [(None, None)]:
                w = hw.get((book, ch, vs, i, part), {}) if i is not None else {}
                arows.append({"edition": ed, "greek_id": gid, "book": book, "chapter": ch, "verse": vs, "i": i, "part": part,
                              "hebrew_text": w.get("text"), "hebrew_lemma": w.get("lemma"), "hebrew_strong": w.get("strong"),
                              "hebrew_class": w.get("class"), "status": x["status"], "by": x["by"]})
        pq.write_table(pa.Table.from_pylist(arows), out / "articles" / f"{ed}.parquet", compression="zstd")
        files.append(out / "articles" / f"{ed}.parquet")
        c = collections.Counter((r["by"], r["status"]) for r in {r["greek_id"]: r for r in arows}.values())   # articles, not rows
        art_stats[ed] = {"articles": len({r["greek_id"] for r in arows}), **{f"{k[0]} {k[1]}": v for k, v in c.items()}}
        frows = []
        for gid, x in sorted(F.links(ed).items()):
            book, ch, vs = x["verse"]
            for i, part in x["parts"] or [(None, None)]:
                w = hw.get((book, ch, vs, i, part), {}) if i is not None and part is not None else {}
                frows.append({"edition": ed, "greek_id": gid, "greek_class": x["cls"], "book": book, "chapter": ch, "verse": vs,
                              "i": i, "part": part, "hebrew_text": w.get("text"), "hebrew_lemma": w.get("lemma"),
                              "hebrew_strong": w.get("strong"), "hebrew_class": w.get("class"), "by": x["by"]})
        pq.write_table(pa.Table.from_pylist(frows), out / "function_words" / f"{ed}.parquet", compression="zstd")
        files.append(out / "function_words" / f"{ed}.parquet")
        fc = collections.Counter((r["greek_class"], r["by"]) for r in {r["greek_id"]: r for r in frows}.values())
        fw_stats[ed] = {f"{k[0]} {k[1]}": v for k, v in fc.items()}
        fw_stats[ed]["whole word rows"] = sum(1 for r in frows if r["i"] is not None and r["part"] is None)
    shutil.copy(b.OUT / "report.json", out / "report.json")
    files.append(out / "report.json")
    fields = {"@TAG@": a.tag, "@BUILT@": datetime.date.today().isoformat(), "@COMMIT@": commit,
              "@BY_ID@": report["inputs"]["by_id"].split("@")[1], "@COMPACT@": report["inputs"]["compact"].split("@")[1]}
    for ed, f in FIELD.items():
        e = report["editions"][ed]
        t = e["tier"]
        fields.update({f"@{f}_FORM@": e["form"], f"@{f}_ROWS@": f"{e['link_rows']:,}", f"@{f}_CONTENT@": f"{e['greek content words']:,}",
                       f"@{f}_LINKED@": f"{e['greek content words linked to a Hebrew part']:,}",
                       f"@{f}_LEXEME@": f"{e['greek content words with a Hebrew lexeme']:,}",
                       f"@{f}_PAIRS@": f"{t['pairs']:,}", f"@{f}_HEB@": f"{t['hebrew lexemes']:,}", f"@{f}_GRC@": f"{t['greek lexemes']:,}",
                       f"@{f}_IN_LXX@": f"{t['pairs also in a Septuagint tier']:,}", f"@{f}_IN_LXX_SHARE@": f"{t['share of pairs']:.1%}",
                       f"@{f}_IN_LXX_LINKS@": f"{t['share of links on those pairs']:.1%}", f"@{f}_NEW@": f"{t['pairs new to the Septuagint tiers']:,}",
                       f"@{f}_NEW_GRC@": f"{t['NT greek lexemes with no Septuagint pair that gain one']:,}",
                       f"@{f}_NEW_GRC_WORDS@": f"{t['NT words of those greek lexemes']:,}",
                       f"@{f}_NEW_HEB@": f"{t['hebrew lexemes with no Septuagint pair that gain one']:,}",
                       f"@{f}_MODEL_SHA@": e["analysis_model"]["sha256"],
                       f"@{f}_Q_LISTED@": f"{e['quotes']['pairs of verses listed']:,}", f"@{f}_Q_VERSES@": f"{e['quotes']['NT verses with a marked stretch']:,}",
                       f"@{f}_Q_PARTS@": f"{e['quotes']['hebrew parts in a marked stretch']:,}",
                       f"@{f}_Q_LINKS@": f"{e['quotes']['counted links in a marked stretch']:,}",
                       f"@{f}_Q_IN@": f"{e['quotes']['of them on a Septuagint pair']:.1%}",
                       f"@{f}_Q_OUT@": f"{e['quotes']['of them on a Septuagint pair (outside)']:.1%}",
                       f"@{f}_Q_LOST@": f"{e['quotes']['pairs with fewer than 3 links outside the marked stretches']:,}"})
    ag, ca = report["agreement"], report["editions"]["heb_scg"]["compact_against_by_id"]
    mc = report["editions"]["heb_mod"].get("compact_against_by_id")
    if not mc:
        raise SystemExit("heb_mod has no by-id links: build with --by-id-local heb_mod=<packet 32 heb_mod/by-id>")
    for ed, f in FIELD.items():
        s_ = art_stats[ed]
        fields.update({f"@{f}_ART@": f"{s_['articles']:,}", f"@{f}_ART_RULE@": f"{sum(v for k, v in s_.items() if k.startswith('rule')):,}",
                       f"@{f}_ART_PRIMARY@": f"{s_.get('rule primary', 0):,}", f"@{f}_ART_IMPLIED@": f"{s_.get('rule implied', 0):,}",
                       f"@{f}_ART_NONE@": f"{s_.get('rule not_rendered', 0):,}", f"@{f}_ART_ALIGNER@": f"{sum(v for k, v in s_.items() if k.startswith('aligner')):,}"})
    for ed, f in FIELD.items():
        s_ = fw_stats[ed]
        for cls, short in (("prep", "PREP"), ("pron", "PRON"), ("conj", "CONJ")):
            n = sum(v for k, v in s_.items() if k.startswith(cls + " "))
            fields.update({f"@{f}_{short}@": f"{n:,}", f"@{f}_{short}_RULE@": f"{s_.get(cls + ' rule', 0):,}",
                           f"@{f}_{short}_ALIGNER@": f"{s_.get(cls + ' aligner', 0):,}", f"@{f}_{short}_NONE@": f"{s_.get(cls + ' none', 0):,}"})
    fields.update({"@MODCAL_N@": f"{mc['greek content words with a Hebrew lexeme in both']:,}", "@MODCAL_SAME@": f"{mc['share same']:.1%}"})
    fields.update({"@AGREE_N@": f"{ag['greek content words with a Hebrew lexeme in both']:,}", "@AGREE_SAME@": f"{ag['share same']:.1%}",
                   "@AGREE_COMMON@": f"{ag['share with a lexeme in common']:.1%}",
                   "@CAL_N@": f"{ca['greek content words with a Hebrew lexeme in both']:,}", "@CAL_SAME@": f"{ca['share same']:.1%}",
                   "@Q_BOTH@": f"{ag['NT verses with a marked stretch in both']:,}", "@Q_EITHER@": f"{ag['in either']:,}",
                   "@Q_LIST@": f"{report['quote_rule']['listed_from_weight']:g}", "@Q_MARK@": f"{report['quote_rule']['marked_from_weight']:g}"})
    card = CARD.read_text(encoding="utf-8")
    for k, v in fields.items():
        card = card.replace(k, v)
    left = [w for w in card.split() if w.strip("`(),.*|").startswith("@") and w.strip("`(),.*|").endswith("@") and len(w.strip("`(),.*|")) > 2]
    if left:
        raise SystemExit(f"the card has fields that were not filled in: {left[:5]}")
    (out / "README.md").write_text(card, encoding="utf-8")
    files.append(out / "README.md")
    sums = [(hashlib.sha256(f.read_bytes()).hexdigest(), f.relative_to(out).as_posix()) for f in sorted(files)]
    (out / "SHA256SUMS").write_text("".join(f"{h}  {n}\n" for h, n in sums), encoding="utf-8")
    print(f"{out}: {len(files)} files (code {commit})")


if __name__ == "__main__":
    main()
