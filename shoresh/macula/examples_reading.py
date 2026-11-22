"""Stage 10 of the source examples (SPEC 1.0, 4.10 and 13): the files that close a build.

    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --stage 10 [--build b1]

Writes per language, in <build>/<lang>/:
  sources.json   every source with repository, path, pin (commit or release), the sha256 and size of every file read,
                 licence, and the method of an annotation the source took over from its makers; the builder's own files
                 (sha256) and the commit they stand on; the Python and pyarrow versions; the licence of the example as a
                 whole and why. Nothing in it depends on the time or on the build's name, so a rebuild gives the same bytes
                 while the sources and the builder are unchanged (the commit line changes when the user commits).
  COLUMNS.md     SPEC section 4 as it stands, then every file of the folder with its columns read from the file (name,
                 type, rows, filled, distinct values), and for every column with 40 or fewer distinct values its values
                 with their counts.
  READ-FIRST.md  the reading sheet (examples_read_sheet.py).
And the glossed chapters (examples_glossed.py): for build b1 into internal-docs/source-examples-work/glossed/, for any
other build into <build>/cache/glossed/ (so a rebuild can be compared file by file).
VALIDATION.md is not written here: validate_examples.py --upto 10 --write-md writes it from its own checks.

The source list is a table inside this builder (SOURCES). Every path in it is a file or a glob the builders of stages
02 to 09 read (their code names them); `reads` says where. The licence of each source is as its card or build.json
states it (cited in `licence_from`).
"""
import glob
import json
import os
import platform
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import examples_common as X  # noqa: E402
import examples_glossed  # noqa: E402
import examples_read_sheet  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ALIGNER = os.path.join(os.path.dirname(ROOT), "lexeme-aligner")
SPEC = os.path.join(ROOT, "internal-docs/source-examples-spec/SPEC.md")
GLOSSED = os.path.join(ROOT, "internal-docs/source-examples-work/glossed")
M = "shoresh/macula/"

# key -> what it is; `langs` the tables that read it; `paths` globs relative to the repository root ("@aligner/" =
# the lexeme-aligner checkout beside it). `facts_key`: the key used in facts.parquet `source`, where one is used.
SOURCES = [
    dict(key="macula-hebrew", langs=("hbo", "arc"), name="MACULA Hebrew, WLC lowfat trees", repository="Clear-Bible/macula-hebrew",
         pin="commit 47db250", licence="CC BY 4.0", licence_from="SPEC 5; MACULA's LICENSE",
         reads="stages 02-08 (examples_src.py, examples_links.py): words, pieces, morphology, classes, roles, clauses, rules, "
               "frames, references, the Septuagint word per piece. Not read: sdbh, lexdomain, coredomain, contextualdomain, "
               "sensenumber, domain, ln, gloss, english, mandarin",
         paths=[M + ".lowfat-src/WLC/lowfat/*.xml"]),
    dict(key="macula-hebrew-nodes", langs=("hbo", "arc"), name="MACULA Hebrew, WLC node trees", repository="Clear-Bible/macula-hebrew",
         pin="commit 47db250 (fetched 2026-11-20)", licence="CC BY 4.0", licence_from="SPEC 5",
         reads="stages 02, 03, 07: the Head of every branching node, morphId of every piece, compound StrongNumberX",
         paths=[M + "data/macula-nodes/hebrew/WLC/nodes/*"]),
    dict(key="macula-greek", langs=("grc",), name="MACULA Greek, Nestle 1904 lowfat trees", repository="Clear-Bible/macula-greek",
         pin="commit 8423afe", licence="CC BY 4.0", licence_from="SPEC 5",
         reads="stages 02-07 and the Greek speech rebuild (greek_speakers.py)", paths=[M + ".lowfat-src-grc/*.xml"]),
    dict(key="macula-greek-nodes", langs=("grc",), name="MACULA Greek, Nestle 1904 node trees", repository="Clear-Bible/macula-greek",
         pin="commit 8423afe (fetched 2026-11-20)", licence="CC BY 4.0", licence_from="SPEC 5",
         reads="stages 03, 07: the Head of every branching node", paths=[M + "data/macula-nodes/greek/Nestle1904/nodes/*"]),
    dict(key="word-senses-ubs", langs=("hbo", "arc", "grc"), name="UBS senses and domains per MACULA word (ours, from UBS's open release)",
         repository="bcv-commons/bcv-query (data/word-senses-ubs), from ubsicap/ubs-open-license", pin="ubs-open-license commit 33dcc8c; word-senses v0.1",
         licence="CC BY-SA 4.0", licence_from="data/word-senses-ubs/build.json",
         reads="stage 02 (pieces.sense, pieces.domain), stage 09 (in_domain, sense_of)",
         paths=[M + "data/word-senses-ubs/words.tsv", M + "data/word-senses-ubs/build.json"]),
    dict(key="clause-layout", langs=("hbo", "arc"), name="our Hebrew clause layout (segments)", repository="bcv-commons/bcv-query (data/clause-layout)",
         pin="the files as hashed here", licence="CC BY-SA 4.0", licence_from="data/clause-layout/build.json",
         reads="stage 05 (D9 join, D11 line), stage 06 (D10 join)", paths=[M + "data/clause-layout/clauses/**/*"]),
    dict(key="nt-clause-layout", langs=("grc",), name="our Greek New Testament clause layout (segments, quotations, speakers)",
         repository="bcv-commons/bcv-query (data/nt-clause-layout)", pin="the files as hashed here", licence="CC BY 4.0",
         licence_from="internal-docs/greek-nt-clause-layout-release/v0.1/README.md",
         reads="stage 05 (D9, D11), stage 06 (D10: quotation and speaker_id, no review rows)", paths=[M + "data/nt-clause-layout/clauses/**/*"]),
    dict(key="clause-columns", langs=("hbo", "arc", "grc"), name="our clause columns", repository="bcv-commons/bcv-query (data/clause-columns)",
         pin="v1.2 files as hashed here", licence="CC BY-SA 4.0", licence_from="data/clause-columns/build.json",
         reads="stage 05 (D9: kind, force, interrog, neg, neg_scope, voice, m_trans, subj_form, subj_switch, front)",
         paths=[M + "data/clause-columns/hebrew.parquet", M + "data/clause-columns/greek-nt.parquet", M + "data/clause-columns/build.json"]),
    dict(key="time-aspect", langs=("hbo", "arc", "grc"), name="our time-aspect", repository="bcv-commons/bcv-query (data/time-aspect)",
         pin="the files as hashed here", licence="CC BY-SA 4.0", licence_from="internal-docs/time-aspect-release/v0.1/README.md",
         reads="stage 05 (D9: time, aspect, band; values withheld as English readings, see report 05)",
         paths=[M + "data/time-aspect/clauses.tsv", M + "data/time-aspect/build.json"]),
    dict(key="connectives", langs=("hbo", "arc", "grc"), name="our clause connectives", repository="bcv-commons/bcv-query (data/connectives)",
         pin="the files as hashed here", licence="CC BY-SA 4.0", licence_from="internal-docs/clause-connectives-release/v0.1/README.md",
         reads="stage 05 (D9: conn; relation withheld)", paths=[M + "data/connectives/clauses.tsv", M + "data/connectives/build.json"]),
    dict(key="clause-extras", langs=("hbo", "arc", "grc"), name="our clause extras", repository="bcv-commons/bcv-query (data/clause-extras)",
         pin="the files as hashed here", licence="CC BY-SA 4.0", licence_from="internal-docs/clause-extras-release/v0.1/README.md",
         reads="stage 05 (D9: polarity)", paths=[M + "data/clause-extras/clauses.tsv", M + "data/clause-extras/build.json"]),
    dict(key="trees-macula", langs=("hbo", "arc", "grc"), name="our tree store of MACULA and the lexeme spine", repository="bcv-commons/bcv-query (build_trees.py, the spine)",
         pin="the files as hashed here", licence="CC BY 4.0", licence_from="shoresh/trees_macula.py docstring (both CC BY, no BHSA input)",
         reads="stage 05 (D9 rank check), stage 06 (the speech rebuilds)",
         paths=[M + "trees-macula.db", M + "lexeme-spine-macula.db", M + "macula-spine.db"]),
    dict(key="speaker-layer-inputs", langs=("hbo", "arc"), name="the inputs of build_speaker_layer.py --no-review (rebuilt into the build's cache)",
         repository="bcv-commons/bcv-query (resources/, data/speaker-layer/_cache) and lexeme-aligner (BSB tables)", pin="the files as hashed here",
         licence="CC BY 4.0", licence_from="internal-docs/hebrew-speaker-layer-release/v0.16/README.md",
         reads="stage 06 (D10). English translations are evidence here (quotation spans and votes, English speaker labels); "
               "no English value enters a table (report 06, point 6). Not read: resources/speaker_layer/review.tsv",
         paths=["resources/speaker_quotations/speaker_quotations.tsv", "resources/speaker_layer/characters.tsv",
                "resources/speaker_layer/corrections.tsv", "resources/speaker_layer/prophets.tsv", "resources/proper_nouns/eng.tsv",
                M + "data/speaker-layer/_cache/*", "@aligner/pipeline/vendor/bsb/tables/bsb_tables.tsv"]),
    dict(key="speaker-layer-published", langs=("hbo", "arc"), name="our published speaker layer (with its review rows)",
         repository="bcv-commons/bcv-query (data/speaker-layer)", pin="the files as hashed here", licence="CC BY 4.0",
         licence_from="internal-docs/hebrew-speaker-layer-release/v0.16/README.md",
         reads="stage 06, only to count the difference with and without the review rows (D10); no value is taken from it",
         paths=[M + "data/speaker-layer/quotations.tsv", M + "data/speaker-layer/segments/*.tsv"]),
    dict(key="nt-speech-inputs", langs=("grc",), name="the inputs of the Greek speech rebuild (no review rows)",
         repository="bcv-commons/bcv-query (resources/speaker_quotations)", pin="the files as hashed here", licence="CC BY 4.0",
         licence_from="internal-docs/greek-nt-clause-layout-release/v0.1/README.md",
         reads="stage 06 (D10). Not read: resources/speaker_quotations/nt_review.tsv",
         paths=["resources/speaker_quotations/speaker_quotations.tsv", "resources/speaker_quotations/nt_characters.tsv"]),
    dict(key="acai", langs=("hbo", "arc", "grc"), name="our entities (from ACAI and MACULA's references)", repository="bcv-commons/bcv-query (data/entities)",
         pin="the files as hashed here", licence="CC BY-SA 4.0", licence_from="data/entities/build.json",
         reads="stage 06 (D7 who, participants.tsv, D10 speaker through characters.tsv, kin facts)",
         paths=[M + "data/entities/entity_words.tsv", M + "data/entities/entities.tsv", M + "data/entities/characters.tsv",
                M + "data/entities/kinship.tsv", M + "data/entities/build.json"]),
    dict(key="addressees", langs=("hbo", "arc", "grc"), name="our addressees", repository="bcv-commons/bcv-query (data/addressees)",
         pin="the files as hashed here", licence="CC BY-SA 4.0", licence_from="internal-docs/addressees-release/v0.1/README.md",
         reads="stage 06 (D10 addressee)", paths=[M + "data/addressees/quotations.tsv"]),
    dict(key="arg-roles", langs=("hbo", "arc", "grc"), name="our argument roles", repository="bcv-commons/bcv-query (data/arg-roles)",
         pin="the files as hashed here", licence="CC BY-SA 4.0", licence_from="data/arg-roles/build.json",
         reads="stage 05 (D12 sem_role)", paths=[M + "data/arg-roles/roles.tsv", M + "data/arg-roles/build.json"]),
    dict(key="hebrew-greek-cf", langs=("hbo", "arc"), name="our bridge corpus, Septuagint links", repository="bcv-commons/bcv-query (hebrew-greek-cf v0.2)",
         pin="v0.2", licence="CC BY-SA 4.0", licence_from="internal-docs/hebrew-greek-cf-release/v0.1/README.md",
         reads="stage 08 (links to lxx, rendered_by)", paths=["internal-docs/hebrew-greek-cf-release/v0.2/bridges/lxx.parquet",
                                                              "resources/lxx_bridge_tiers/greek_numbers.tsv"]),
    dict(key="glaux-lxx", langs=("hbo", "arc"), name="GLAUx's Septuagint (words, lemmas, classes)", repository="bcv-commons/spine-releases",
         pin="releases lxx-glaux-2026-10-10, lxx-glaux-dan-theodotion-2026-11-14", licence="CC BY-SA 4.0",
         licence_from="report 08 (GLAUx)", method="lemma and class are GLAUx's own, made automatically by its makers",
         reads="stage 08 (other/lxx/words.parquet)", paths=["shoresh/lxx/data/lxx-glaux.db"]),
    dict(key="compact-alignments", langs=("grc",), name="lexeme-aligner's compact alignments, editions heb_scg and heb_mod",
         repository="bcv-commons/lexeme-aligner", pin="download 11583082 (data/compact-alignments-11583082), with the companion "
         "files of the local publish folder (checked byte-identical where both hold a file, report 08)", licence="CC0 1.0",
         licence_from="lexeme-aligner/publish/compact-alignments/README.md",
         method="links placed by the aligner: eflomal (statistical), gloss rules, gap fill, span extension (links.how)",
         reads="stage 08 (links to heb_scg, heb_mod; rendered_by)",
         paths=[M + "data/compact-alignments-11583082/**/*", "@aligner/publish/compact-alignments/_index/*",
                "@aligner/publish/compact-alignments/h/heb/heb_scg/*", "@aligner/publish/compact-alignments/h/heb/heb_mod/*"]),
    dict(key="helloao", langs=("grc",), name="the two Hebrew New Testaments' texts (eBible hebsg, heb via bible.helloao.org)",
         repository="bible.helloao.org (local copy in data/helloao)", pin="the files as hashed here", licence="public domain",
         licence_from="helloao translation.license; internal-docs/hebrew-nt-analysis-release/v0.2/README.md",
         reads="stage 08 (other/heb_scg, other/heb_mod words, with bibles' tokenizer in vendor_bibles)",
         paths=[M + "data/helloao/heb_scg/*.json", M + "data/helloao/heb_mod/*.json", M + "vendor_bibles/**/*.py"]),
    dict(key="aramaic-hebrew-equivalents", langs=("arc",), name="our published Aramaic equivalents list",
         repository="bcv-commons/bcv-query (aramaic-hebrew-equivalents v0.1.1)", pin="v0.1.1", licence="CC BY-SA 4.0",
         licence_from="internal-docs/aramaic-hebrew-equivalents-release/v0.1.1/README.md", reads="stage 09 (equivalent_of; its build.json names no model)",
         paths=["internal-docs/aramaic-hebrew-equivalents-release/v0.1.1/data/words.parquet",
                "internal-docs/aramaic-hebrew-equivalents-release/v0.1.1/build.json"]),
    dict(key="grambank-questionnaire", langs=("hbo", "arc", "grc"), name="the questionnaire (Grambank's 195 rows, as the describing pipeline holds them)",
         repository="bcv-commons/bcv-query (internal-docs/source-examples-work/tools)", pin="the file as hashed here",
         licence="CC BY 4.0 (Grambank)", licence_from="Grambank", reads="stage 09 (profile.tsv: id, question)",
         paths=["internal-docs/source-examples-work/tools/team_parameters.tsv"]),
]
EXAMPLE_LICENCE = ("CC BY-SA 4.0. The tables hold values of CC BY-SA 4.0 sources (UBS senses and domains, ACAI's entities, "
                   "our clause columns and argument roles, GLAUx's Septuagint words and the bridge links for hbo and arc), so "
                   "ShareAlike holds for the whole. The CC BY 4.0 sources (MACULA, our layouts and speaker layer) ask for "
                   "attribution, which `sources` gives. The Hebrew New Testament texts are public domain, the compact "
                   "alignments CC0 1.0.")
NOT_READ = ["BHSA and everything derived from it", "TBTA", "every model-made dataset (-model) and vector table (-similar)",
            "MACULA's inline sdbh, lexdomain, coredomain, contextualdomain, sensenumber, domain, ln, gloss, english, mandarin",
            "alignments-by-id and the links of hebrew-nt-bridge (model-reviewed)", "the Hebrew New Testament analysis (tagger)",
            "resources/speaker_layer/review.tsv, resources/speaker_quotations/nt_review.tsv and every other review file",
            "the English labels alt_eng"]
BUILDER = ["build_examples.py", "examples_*.py"]

_SHA = {}


def _sha(path):
    if path not in _SHA:
        _SHA[path] = X_sha(path)
    return _SHA[path]


def X_sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def _expand(pattern):
    if pattern.startswith("@aligner/"):
        base, rel = ALIGNER, pattern[len("@aligner/"):]
        label = "../lexeme-aligner/"
    else:
        base, rel, label = ROOT, pattern, ""
    hits = sorted(p for p in glob.glob(os.path.join(base, rel), recursive=True) if os.path.isfile(p))
    return [(label + os.path.relpath(p, base), p) for p in hits]


def _git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def sources_doc(lang, counts):
    srcs = {}
    for s in SOURCES:
        if lang not in s["langs"]:
            continue
        files = {}
        for pat in s["paths"]:
            got = _expand(pat)
            if not got:
                raise SystemExit(f"sources.json: {s['key']}: nothing matches {pat}")
            for label, p in got:
                files[label] = {"bytes": os.path.getsize(p), "sha256": _sha(p)}
        entry = {k: s[k] for k in ("name", "repository", "pin", "licence", "licence_from", "reads")}
        if s.get("method"):
            entry["method"] = s["method"]
        entry["files"] = dict(sorted(files.items()))
        srcs[s["key"]] = entry
        counts[f"{lang} sources.json {s['key']} files"] = len(files)
    tracked = set((_git("ls-files", "--", "shoresh/macula") or "").split("\n"))
    changed = set((_git("diff", "--name-only", "HEAD", "--", "shoresh/macula") or "").split("\n"))
    bfiles = {}
    for pat in BUILDER:
        for p in sorted(glob.glob(os.path.join(HERE, pat))):
            rel = os.path.relpath(p, ROOT)
            bfiles[rel] = {"sha256": _sha(p), "committed": rel in tracked and rel not in changed}
    return {
        "language": lang,
        "builder": {"repository": "bcv-commons/bcv-query", "commit": _git("rev-parse", "HEAD"),
                    "note": "the builder files below are those of this build; `committed` = tracked and unchanged against "
                            "`commit` when the build ran", "files": bfiles,
                    "entry": "shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --stage 02 ... 10"},
        "python": platform.python_version(), "pyarrow": pa.__version__,
        "specification": {"path": "internal-docs/source-examples-spec/SPEC.md", "version": "1.0", "sha256": _sha(SPEC)},
        "sources": srcs, "not_read": NOT_READ, "licence": EXAMPLE_LICENCE,
    }


def _spec_section4():
    with open(SPEC, encoding="utf-8") as fh:
        text = fh.read()
    a = text.index("## 4. The tables")
    b = text.index("## 5. Sources")
    return text[a:b].rstrip() + "\n"


def _describe_parquet(path):
    t = pq.read_table(path)
    rows = []
    for name in t.column_names:
        vals = t.column(name).to_pylist()
        filled = sum(1 for v in vals if v is not None and v != "")
        distinct = {}
        for v in vals:
            distinct[v] = distinct.get(v, 0) + 1
        rows.append((name, str(t.schema.field(name).type), filled, distinct))
    return t.num_rows, rows


def _describe_tsv(path):
    with open(path, encoding="utf-8") as fh:
        lines = [ln for ln in fh.read().split("\n") if ln]
    head = lines[0].split("\t")
    body = [ln.split("\t") for ln in lines[1:]]
    rows = []
    for i, name in enumerate(head):
        distinct = {}
        for r in body:
            distinct[r[i]] = distinct.get(r[i], 0) + 1
        rows.append((name, "string (TSV)", sum(1 for r in body if r[i] != ""), distinct))
    return len(body), rows


def columns_md(d, lang):
    L = [f"# COLUMNS: `{lang}`", "",
         "Written by `build_examples.py --stage 10` (`examples_reading.py`). Part 1 is section 4 of the specification",
         "(`internal-docs/source-examples-spec/SPEC.md`, version 1.0) as it stands. Part 2 lists every file of this folder",
         "with its columns as read from the file: type, rows filled (not null, not empty), distinct values; a column with 40",
         "or fewer distinct values has them listed with their counts. Codes of the categories are in `categories.toml`,",
         "labels in `relmap.tsv`, shared features in `map.tsv`.", "", "## Part 1. The specification, section 4", "",
         _spec_section4().replace("\n## ", "\n### ").replace("\n### 4.", "\n#### 4."), "## Part 2. The files as built", ""]
    files = sorted(f for f in os.listdir(d) if f.endswith((".parquet", ".tsv")))
    others = sorted(os.path.join("other", o, "words.parquet") for o in os.listdir(os.path.join(d, "other")))
    for f in files + others:
        p = os.path.join(d, f)
        n, cols = _describe_parquet(p) if f.endswith(".parquet") else _describe_tsv(p)
        L += [f"### `{f}`: {n:,} rows, {len(cols)} columns", "", "| column | type | filled | distinct | values (40 or fewer) |",
              "|---|---|---|---|---|"]
        for name, typ, filled, distinct in cols:
            vals = ""
            if len(distinct) <= 40:
                vals = ", ".join(f"`{'' if k is None else k}` {v:,}" for k, v in
                                 sorted(distinct.items(), key=lambda kv: (-kv[1], str(kv[0]))))
                vals = vals.replace("|", "\\|")
            L.append(f"| `{name}` | {typ} | {filled:,} | {len(distinct):,} | {vals} |")
        L.append("")
    for f in ("categories.toml", "sources.json", "READ-FIRST.md", "VALIDATION.md"):
        L.append(f"- `{f}`: " + {"categories.toml": "the categories with their codes (stages 02, 05)",
                                 "sources.json": "the sources and their pins (stage 10)",
                                 "READ-FIRST.md": "the reading sheet (stage 10)",
                                 "VALIDATION.md": "the exit conditions with their counts (validate_examples.py --upto 10 --write-md)"}[f])
    return "\n".join(L) + "\n"


def build(outdir, langs, counts):
    ex = {}
    for lang in langs:
        d = os.path.join(outdir, lang)
        doc = sources_doc(lang, counts)
        X.write_text(os.path.join(d, "sources.json"), json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        X.write_text(os.path.join(d, "COLUMNS.md"), columns_md(d, lang))
        X.write_text(os.path.join(d, "READ-FIRST.md"), examples_read_sheet.sheet(d, lang))
        counts[f"{lang} sources"] = len(doc["sources"])
        counts[f"{lang} files hashed"] = sum(len(s["files"]) for s in doc["sources"].values())
        uncommitted = [k for k, v in doc["builder"]["files"].items() if not v["committed"]]
        if uncommitted:
            ex[f"{lang} builder files not committed when built"] = uncommitted
    if set(langs) == {"hbo", "arc", "grc"}:
        gl = GLOSSED if os.path.basename(os.path.normpath(outdir)) == "b1" else os.path.join(outdir, "cache", "glossed")
        examples_glossed.build_all(outdir, gl, counts)
        counts["glossed folder"] = os.path.relpath(gl, ROOT)
    return ex
