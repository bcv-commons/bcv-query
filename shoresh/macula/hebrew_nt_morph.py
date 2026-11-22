"""Morphology for the Hebrew New Testaments, taken from MACULA Hebrew where the word is a known Tanakh form.

hebrew-nt-analysis gives every word part a class, a lemma and a Strong's number, and verbs a form and a person, but no stem,
number, gender or state. This step adds them without a model: a Hebrew NT word whose written form occurs in the Tanakh with the
same analysis (the same parts with the same class, lemma and Strong's number) takes the morphology MACULA gives that form, where
at least `--share` of those Tanakh occurrences agree on it. Salkinson's text is pointed, so its forms are matched with their
vowel points; Delitzsch's edition here is unpointed and is matched on consonants, which leaves more forms ambiguous.

  python -m macula.hebrew_nt_morph --analysis DIR --out OUT [--share 0.9]

DIR is a hebrew-nt-analysis release folder (heb_scg/words.parquet, heb_mod/words.parquet, each with a manifest.json).
Writes OUT/<edition>/morph.parquet (one row per word part: book, chapter, verse, i, part, stem, person, number, gender, state,
basis, share, n) and OUT/build.json with the counts. `basis`, strongest first: `form` (the whole word is a Tanakh form and
its analysis was a Tanakh lookup), `form_model` (the tagger's own analysis matches a Tanakh analysis of this form), `part`
(only this part, with its class and lemma, is a Tanakh part: the word as a whole is not attested, e.g. another prefix),
`part_model` (the same where the analysis is the tagger's), or empty (no morphology).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sqlite3
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from macula.clause_tagger import pointed, unpointed

HERE = Path(__file__).resolve().parent
FEATS = ("stem", "person", "number", "gender", "state")
MORPH_CLASSES = {"noun", "verb", "adj", "pron", "ptcl", "num"}


def tanakh_table(plain: bool) -> tuple[dict, dict]:
    """(written form, analysis) -> Counter of morphologies; analysis = ((class, lemma, strong) per part),
    morphology = ((stem, person, number, gender, state) per part). And the same per single part:
    (written part, class, lemma, strong) -> Counter of that part's morphology."""
    spine = sqlite3.connect(HERE / "macula-spine.db")
    morph = {k: tuple(v or "" for v in rest) for k, *rest in
             spine.execute("select key, stem, person, number, gender, state from macula_words where lang = 'hbo'")}
    form = unpointed if plain else pointed
    table: dict = collections.defaultdict(collections.Counter)
    part_table: dict = collections.defaultdict(collections.Counter)
    cur_key, text, ana, mor = None, "", [], []

    def flush() -> None:
        if cur_key is not None and form(text):
            table[(form(text), tuple(ana))][tuple(mor)] += 1

    import unicodedata
    for b, ch, v, w, s, key, cls, lemma, strong in sqlite3.connect(HERE / "trees-macula.db").execute(
            "select book, chapter, verse, word, surface, key, class, lemma, strong from words where corpus = 'hbo' "
            "order by book, chapter, verse, word, part"):
        k = (b, ch, v, w)
        if k != cur_key:
            flush()
            cur_key, text, ana, mor = k, "", [], []
        text += s
        ana.append((cls or "-", unicodedata.normalize("NFC", lemma or "-"), strong or ""))
        mor.append(morph.get(key, ("",) * len(FEATS)))
        if form(s):
            part_table[(form(s),) + ana[-1]][mor[-1]] += 1
    flush()
    return table, part_table


def run(analysis: Path, out: Path, share: float) -> None:
    build = {"share": share, "analysis": str(analysis.name), "editions": {}}
    for ed_dir in sorted(p for p in analysis.iterdir() if (p / "words.parquet").exists()):
        ed = ed_dir.name
        manifest = json.loads((ed_dir / "manifest.json").read_text())
        plain = manifest["model"].get("vowel_points", "read") == "stripped"      # older manifests: pointed
        table, part_table = tanakh_table(plain)
        form = unpointed if plain else pointed
        rows = pq.read_table(ed_dir / "words.parquet").to_pylist()
        words: dict = collections.OrderedDict()
        for r in rows:
            if r["source"] is None:                            # the verse number some texts carry
                continue
            words.setdefault((r["book"], r["chapter"], r["verse"], r["i"]), []).append(r)
        out_rows, n = [], collections.Counter()
        for (b, ch, v, i), parts in words.items():
            parts.sort(key=lambda r: r["part"])
            ana = tuple((r["class"] or "-", r["lemma"] or "-", r["strong"] or "") for r in parts)
            c = table.get((form(parts[0]["word"]), ana))
            got, sh, tot = None, None, 0
            if c:
                best, k = c.most_common(1)[0]
                tot = sum(c.values())
                if k / tot >= share and len(best) == len(parts):
                    got, sh = best, round(k / tot, 3)
            basis = "" if got is None else ("form" if parts[0]["source"] == "macula" else "form_model")
            content = any(r["class"] in MORPH_CLASSES for r in parts)
            n["words"] += 1
            n[f"words_{parts[0]['source']}"] += 1
            n["content_words"] += content
            if got is not None:
                n[f"morph_{basis}"] += 1
                n["content_morph"] += content
            elif c:
                n["ambiguous"] += 1
            for j, r in enumerate(parts):
                m, pb, psh, pn = (got[j], basis, sh, tot) if got is not None else (("",) * len(FEATS), "", None, None)
                if got is None and r["text"]:
                    pc = part_table.get((form(r["text"]),) + ana[j])
                    if pc:
                        best, k = pc.most_common(1)[0]
                        if k / sum(pc.values()) >= share:
                            m, psh, pn = best, round(k / sum(pc.values()), 3), sum(pc.values())
                            pb = "part" if r["source"] == "macula" else "part_model"
                            n[f"parts_{pb}"] += 1
                out_rows.append({"book": b, "chapter": ch, "verse": v, "i": i, "part": r["part"], **dict(zip(FEATS, m)),
                                 "basis": pb, "share": psh, "n": pn})
                if r["class"] == "verb":
                    n["verb_parts"] += 1
                    n["verb_stem"] += bool(m[0])
                if r["class"] in ("noun", "adj"):
                    n["nominal_parts"] += 1
                    n["nominal_number"] += bool(m[2])
        schema = pa.schema([("book", pa.string()), ("chapter", pa.int16()), ("verse", pa.int16()), ("i", pa.int16()), ("part", pa.int8()),
                            *[(f, pa.string()) for f in FEATS], ("basis", pa.string()), ("share", pa.float32()), ("n", pa.int32())])
        (out / ed).mkdir(parents=True, exist_ok=True)
        f = out / ed / "morph.parquet"
        pq.write_table(pa.Table.from_pylist(out_rows, schema=schema), f, compression="zstd")
        build["editions"][ed] = {"matched_on": "consonants" if plain else "pointed form", "rows": len(out_rows), **dict(n),
                                 "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}
        print(f"[hebrew_nt_morph] {ed}: {dict(n)}")
    (out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--analysis", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--share", type=float, default=0.9)
    a = ap.parse_args()
    run(a.analysis, a.out, a.share)


if __name__ == "__main__":
    main()
