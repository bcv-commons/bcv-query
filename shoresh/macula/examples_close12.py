"""Stage 24 of the source examples (SPEC 1.2, section 14: close12). It closes a d build that stage 23 has built.

    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build d1 --stage 24

Writes, per language folder (`hbo`, `arc`, `grc`):
  sources.json     anew, by the same rule as stage 23's sub-stage 20 (examples_shared11.sources_doc11): every source
                   with repository, pin, licence and the sha256 of every file read (now with terms-notes.md beside
                   terms.tsv), the model part that stages 23.17 and 23.19 wrote (kept), the builder files and commit,
                   Python and pyarrow, SPEC 1.2 with its sha256, what is not read, the licence of the example
  COLUMNS.md       SPEC section 4 (version 1.2) as it stands, then every table file with its columns read from the file
  READ-FIRST.md    the reading sheet (examples_read_sheet.py) with the normal ranges, and section 5: what is model,
                   and how much (with the terms a model named)
And the eight glossed chapters: for d1 into internal-docs/source-examples-work/glossed-d1/, for any other build into
<build>/cache/glossed/ (so that a rebuild can be compared file by file).

It reads only the build's own tables and the files sources.json hashes; it changes no table. VALIDATION.md is the
validator's (validate_examples.py --build d1 --upto 24 --compare d2 --write-md).
"""
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import examples_common as X  # noqa: E402
import examples_shared11 as S20  # noqa: E402

LANGS = ("hbo", "arc", "grc")
NEED = ("words.parquet", "pieces.parquet", "clauses.parquet", "constituents.parquet", "links.parquet", "terms.tsv",
        "terms-notes.md", "categories.toml", "sources.json", "source_errors.tsv", "profile.tsv")


def build(outdir, langs, counts):
    if set(langs) != set(LANGS):
        raise SystemExit("stage 24 closes hbo, arc and grc together")
    if not X.V12:
        raise SystemExit("stage 24 closes a d build (SPEC 1.2)")
    missing = [f"{lg}/{f}" for lg in LANGS for f in NEED if not os.path.exists(os.path.join(outdir, lg, f))]
    if missing:
        raise SystemExit(f"stage 24: stage 23 has not built {missing[:5]} ({len(missing)} files); run --stage 23 first")
    ex = {}
    for lang in LANGS:
        d = os.path.join(outdir, lang)
        doc = S20.sources_doc11(lang, d, counts)
        X.write_text(os.path.join(d, "sources.json"), json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        counts[f"{lang} sources"] = len(doc["sources"])
        counts[f"{lang} model sources"] = len(doc["model"])
        counts[f"{lang} files hashed"] = sum(len(s["files"]) for s in doc["sources"].values())
        unc = [k for k, v in doc["builder"]["files"].items() if not v["committed"]]
        if unc:
            ex[f"{lang} builder files not committed when built"] = unc
    S20.write_docs(outdir, counts)
    for lang in LANGS:
        for f in ("COLUMNS.md", "READ-FIRST.md"):
            counts[f"{lang} {f} bytes"] = os.path.getsize(os.path.join(outdir, lang, f))
    return ex
