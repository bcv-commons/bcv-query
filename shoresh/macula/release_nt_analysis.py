"""Package exported Hebrew NT analyses as a release of the dataset bcv-commons/hebrew-nt-analysis. Nothing is uploaded: the files are
written to a folder for review, and published by hand.

    python -m macula.release_nt_analysis --tag v0.6 --out DIR [--editions heb_scg,heb_mod] [--src macula/data/clause-tagger/export]
        [--features macula/data/hebrew-nt-features/2026-11-26b] [--layers macula/data/hebrew-nt-layers/2026-11-26]
        [--speech macula/data/hebrew-nt-speech/2026-11-26b] [--referents macula/data/hebrew-nt-referents/2026-11-26b] [--allow-dirty]

DIR gets:
  README.md                  the dataset card (macula/nt_analysis_card.md with the version fields filled in)
  <edition>/words.parquet    one row per word part, from `python -m macula.clause_tagger export`
  <edition>/clauses.parquet  one row per clause segment
  <edition>/manifest.json    the text fingerprints, the model's sha256, the tokenizer and verse-text versions
  <edition>/features.parquet person, number, gender, state, definiteness (v0.3), verb stem (v0.4) per word part (`hebrew_nt_features.py`)
  <edition>/pieces.parquet   head, relation, semantic role, reference status, referent kind per word part (`hebrew_nt_layers.py`; v0.3)
  <edition>/clause_marks.parquet  the clause marks per clause segment (`hebrew_nt_layers.py`, its clauses.parquet; v0.3)
  <edition>/speech.parquet   speaker, addressee and the addressee's number per quotation segment (`hebrew_nt_speech.py`; v0.4)
  <edition>/referents.parquet referent and antecedent per pronoun, suffix and finite verb (`hebrew_nt_referents.py`; v0.5)
  <edition>/entities.parquet the entity ids of speech.parquet (and of k1's `who`): kind, Hebrew type word, name (v0.4)
  SHA256SUMS                 SHA-256 of every file

The export must come from committed code (`git status` clean for macula/clause_tagger.py, macula/fetch_hebrew_nt.py,
macula/vendor_bibles/, macula/hebrew_nt_morph.py, macula/hebrew_nt_features.py, macula/hebrew_nt_layers.py,
macula/hebrew_nt_speech.py, macula/hebrew_nt_referents.py, this script and the card), unless --allow-dirty. DIR must not exist yet. The v0.3 files must stand on the keys of the words and clauses released with
them: every key of features.parquet and pieces.parquet a word part of words.parquet, the keys of clause_marks.parquet those of
clauses.parquet, and those of speech.parquet clause segments.

`heb_scg/words.parquet` is pinned by sha256 in lexeme-aligner (the part numbers of bcv-commons/alignments-by-id are its). The release
refuses another file than the pinned one, unless --allow-heb-scg-change (then tell lexeme-aligner before publishing).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
import tomllib
from pathlib import Path
from macula import release_guard  # refuses TBTA and private inputs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CARD = HERE / "nt_analysis_card.md"
CODE = [HERE / "clause_tagger.py", HERE / "fetch_hebrew_nt.py", HERE / "vendor_bibles", HERE / "hebrew_nt_morph.py",
        HERE / "hebrew_nt_features.py", HERE / "hebrew_nt_layers.py", HERE / "hebrew_nt_speech.py",
        HERE / "hebrew_nt_referents.py", Path(__file__).resolve(), CARD]
ADDED = {"features.parquet": ("features", "features.parquet"), "pieces.parquet": ("layers", "pieces.parquet"),
         "clause_marks.parquet": ("layers", "clauses.parquet"), "speech.parquet": ("speech", "speech.parquet"),
         "entities.parquet": ("speech", "entities.parquet"), "referents.parquet": ("referents", "referents.parquet")}    # released name -> (source folder, file there)
KEYS = ("book", "chapter", "verse", "i", "part")
EDITIONS = {"heb_scg": "Salkinson–Ginsburg Hebrew New Testament (1885/86), public domain; text from bible.helloao.org (from eBible.org, hebsg)",
            "heb_mod": "Delitzsch's Hebrew New Testament as eBible's \"Modern Hebrew Bible\" has it, without vowel points, public domain; text from "
                       "bible.helloao.org (from eBible.org, heb)"}
PINNED = {"heb_scg/words.parquet": "bf6aebcc96dcb330984b9ffc2d44a12b77f24aa91c8d7b654ef4f040a62224b5"}    # lexeme-aligner config/target_parts.json
FIELD = {"heb_scg": "SCG", "heb_mod": "MOD"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--editions", default="heb_scg,heb_mod")
    ap.add_argument("--src", default=str(HERE / "data" / "clause-tagger" / "export"))
    ap.add_argument("--features", default=str(HERE / "data" / "hebrew-nt-features" / "2026-11-26b"))
    ap.add_argument("--speech", default=str(HERE / "data" / "hebrew-nt-speech" / "2026-11-26b"))
    ap.add_argument("--referents", default=str(HERE / "data" / "hebrew-nt-referents" / "2026-11-26b"))
    ap.add_argument("--layers", default=str(HERE / "data" / "hebrew-nt-layers" / "2026-11-26"))
    ap.add_argument("--allow-dirty", action="store_true")
    ap.add_argument("--allow-heb-scg-change", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    src, out = Path(a.src), Path(a.out)
    if not a.allow_dirty:
        dirty = subprocess.run(["git", "status", "--porcelain", "--", *map(str, CODE)], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        if dirty:
            raise SystemExit("uncommitted changes in the tagger's code or card; commit first (or --allow-dirty):\n" + dirty)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if out.exists():
        raise SystemExit(f"{out} exists; give a folder that does not exist yet")
    files = []
    stats = {}
    import pyarrow.parquet as pq
    for ed in a.editions.split(","):
        if ed not in EDITIONS:
            raise SystemExit(f"{ed}: not an edition this card describes")
        (out / ed).mkdir(parents=True)
        for name in ("words.parquet", "clauses.parquet", "manifest.json"):
            shutil.copy(src / ed / name, out / ed / name)
            files.append(out / ed / name)
            want = PINNED.get(f"{ed}/{name}")
            if want and hashlib.sha256((out / ed / name).read_bytes()).hexdigest() != want and not a.allow_heb_scg_change:
                raise SystemExit(f"{ed}/{name} is not the file lexeme-aligner pins (sha256 {want[:12]}…); see --allow-heb-scg-change")
        for name, (folder, from_name) in ADDED.items():
            shutil.copy(Path(getattr(a, folder)) / ed / from_name, out / ed / name)
            files.append(out / ed / name)
        words = pq.read_table(out / ed / "words.parquet", columns=["book", "chapter", "verse", "i", "part", "class", "source"]).to_pylist()
        part_keys = {tuple(r[k] for k in KEYS) for r in words if r["class"] != "verse-number"}
        seg_keys = {tuple(r.values()) for r in pq.read_table(out / ed / "clauses.parquet", columns=["book", "chapter", "verse", "seg"]).to_pylist()}
        added = {}
        for name, want_keys, cols in (("features.parquet", part_keys, KEYS), ("pieces.parquet", part_keys, KEYS),
                                      ("referents.parquet", part_keys, KEYS),
                                      ("clause_marks.parquet", seg_keys, ("book", "chapter", "verse", "seg")),
                                      ("speech.parquet", seg_keys, ("book", "chapter", "verse", "seg"))):
            got = [tuple(r.values()) for r in pq.read_table(out / ed / name, columns=list(cols)).to_pylist()]
            if len(set(got)) != len(got) or not set(got) <= want_keys:
                raise SystemExit(f"{ed}/{name}: keys repeat or are not keys of the released words/clauses")
            if name == "clause_marks.parquet" and set(got) != want_keys:
                raise SystemExit(f"{ed}/{name}: not one row per clause segment")
            added[name] = len(got)
        tokens = {(r["book"], r["chapter"], r["verse"], r["i"]): r for r in words if r["class"] != "verse-number"}
        stats[ed] = {"parts": len(words), "words": len(tokens), "macula": sum(r["source"] == "macula" for r in tokens.values()),
                     "segments": pq.read_metadata(out / ed / "clauses.parquet").num_rows, "added": added,
                     "word_parts": len(part_keys),
                     "manifest": json.loads((out / ed / "manifest.json").read_text())}
    missing = [e for e in FIELD if e not in stats]
    if missing:
        raise SystemExit(f"the card describes {', '.join(FIELD)}; not exported: {', '.join(missing)}")
    s = stats["heb_scg"]
    pin = tomllib.loads((HERE / "clause_layout.toml").read_text())["sources"]["macula_hebrew"]
    fields = {"@TAG@": a.tag, "@BUILT@": datetime.date.today().isoformat(), "@COMMIT@": commit,
              "@VERSE_TEXT@": s["manifest"]["bibles_verse_text"], "@TOKENIZER@": str(s["manifest"]["tokenizer_version"]),
              "@MACULA_COMMIT@": pin["commit"][:7]}
    for ed, f in FIELD.items():
        e = stats[ed]
        fields.update({f"@{f}_WORDS@": f"{e['words']:,}", f"@{f}_PARTS@": f"{e['parts']:,}", f"@{f}_SEGMENTS@": f"{e['segments']:,}",
                       f"@{f}_MACULA_WORDS@": f"{e['macula']:,}", f"@{f}_MACULA_SHARE@": f"{e['macula'] / e['words']:.1%}",
                       f"@{f}_MODEL_WORDS@": f"{e['words'] - e['macula']:,}", f"@{f}_MODEL_SHA@": e["manifest"]["model"]["sha256"],
                       f"@{f}_FEATURE_ROWS@": f"{e['added']['features.parquet']:,}", f"@{f}_PIECE_ROWS@": f"{e['added']['pieces.parquet']:,}",
                       f"@{f}_WORD_PARTS@": f"{e['word_parts']:,}", f"@{f}_SPEECH_ROWS@": f"{e['added']['speech.parquet']:,}",
                       f"@{f}_REFERENT_ROWS@": f"{e['added']['referents.parquet']:,}"})
    card = CARD.read_text(encoding="utf-8")
    for k, v in fields.items():
        card = card.replace(k, v)
    if any(w.strip("`(),.") .startswith("@") and w.strip("`(),.").endswith("@") and len(w.strip("`(),.")) > 2 for w in card.split()):
        raise SystemExit("the card has a field that was not filled in")
    (out / "README.md").write_text(card, encoding="utf-8")
    files.append(out / "README.md")
    sums = [(hashlib.sha256(f.read_bytes()).hexdigest(), f.relative_to(out).as_posix()) for f in sorted(files)]
    (out / "SHA256SUMS").write_text("".join(f"{h}  {n}\n" for h, n in sums), encoding="utf-8")
    print(f"{out}: {len(files)} files (code {commit}); " + "; ".join(f"{ed} {e['words']:,} words, {e['parts']:,} parts, {e['segments']:,} segments"
                                                                    for ed, e in stats.items()))


if __name__ == "__main__":
    main()
