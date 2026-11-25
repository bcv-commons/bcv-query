"""The Hebrew ladder: one entry point, grown stage by stage (SPEC-ladder 3.1).

    cd shoresh && .venv/bin/python -I macula/build_ladder.py --build pilot-1 --stage 58 [--out DIR]

Stage 58 writes banks/ and sealed/chooser_sample.tsv, sources.json, COLUMNS.md and build.json (SPEC-ladder 4, 5, 12).
Stage 59 writes hebrew-levels/pilot-2/ (SPEC-ladder 6; ladder_stage59.py, ladder_switches.py):
    cd shoresh && .venv/bin/python -I macula/build_ladder.py --build pilot-1 --stage 59 [--out DIR]
`--out` writes the same files into another folder (used by the validator's rebuild test).
Stage 60 (SPEC-ladder 7; ladder_stage60.py): `--prepare` writes chooser/input/ and the reading view in cache/; the
session writes chooser/decisions/<BOOK>.tsv; `--check` applies rule SP and writes chooser/choices_model.parquet:
    cd shoresh && .venv/bin/python -I macula/build_ladder.py --build pilot-1 --stage 60 --prepare [--batch N]
    cd shoresh && .venv/bin/python -I macula/build_ladder.py --build pilot-1 --stage 60 --check [--out DIR]
Stage 61 (SPEC-ladder 8, 9, 11; ladder_stage61.py) writes the steps, changes, lines, layout and the sealed step sample:
    cd shoresh && .venv/bin/python -I macula/build_ladder.py --build pilot-1 --stage 61 [--out DIR]
Rebuild order from nothing: --stage 58, --stage 59, --stage 60 --prepare, (the decisions), --stage 60 --check,
--stage 61.
Stage 62 (SPEC-ladder 10; ladder_stage62.py), the English aid: `--prepare` writes the session's input per chapter in
cache/english/input/; `--ingest FILE...` merges the session's chapter answers into english/raw/; `--check` builds
english/english_model.parquet and the credit:
    cd shoresh && .venv/bin/python -I macula/build_ladder.py --build pilot-1 --stage 62 --prepare
    cd shoresh && .venv/bin/python -I macula/build_ladder.py --build pilot-1 --stage 62 --ingest FILE...
    cd shoresh && .venv/bin/python -I macula/build_ladder.py --build pilot-1 --stage 62 --check --spend USD [--out DIR]
"""
import argparse, hashlib, json, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from macula import ladder_banks as LB

ROOT = LB.DATA / "hebrew-ladder"
SPEC = "Ladder specification, version 0.3"
CODE = ["shoresh/macula/build_ladder.py", "shoresh/macula/ladder_banks.py", "shoresh/macula/ladder_abbrev.py"]
REPO = LB.HERE.parent.parent

COLUMNS_58 = """# Columns (stage 58: the banks)

Bases as SPEC-ladder 2.3: `given` (stands in the source), `derived` (a rule named in SPEC-ladder), `linked`, `model`.
Rules: 4.1 parse, MA anchor (4.2), FIG markers (4.3), AB abbreviations (4.4), ZC kind and core (5.2), FIT (5.3), RARE.

## banks/paraphrase.parquet (Metzudat David, one row per comment string)

| column | basis | rule |
|---|---|---|
| comment | derived | key `md:<BOOK>:<ch>:<v>:<n>` |
| book, chapter, verse, n, key | given | place in the source file |
| lemma | given | 4.1 (bold part, tags and invisible marks removed, closing `.` `:` stripped) |
| body | given | 4.1 |
| anchor_state, anchor_tier, anchor_part, anchor_t, anchor_w_from, anchor_w_to | derived | MA |
| markers, figure | derived | FIG |
| tokens, abbrev_unknown | derived | AB |
| in_pilot | derived | the step-1 scope (JON, PSA 1-41, ISA 40-55) |

## banks/paraphrase_tokens.parquet (one row per body token)

| column | basis | rule |
|---|---|---|
| comment, i | derived | key |
| text | given | the token as written after 4.1's cleaning |
| part | derived | `body`, `cite` (inside parentheses) |
| abbrev | derived | AB: the table row matched, `""` or `unknown` |
| written | derived | AB |
| words | derived | the number of words in `written` |

## banks/gloss.parquet (Metzudat Zion, one row per gloss string)

| column | basis | rule |
|---|---|---|
| gloss | derived | key `mz:<BOOK>:<ch>:<v>:<n>` |
| book, chapter, verse, n, key, lemma, body | given | as above |
| anchor_* | derived | MA |
| kind, core, core_words | derived | ZC (core written out by AB) |
| fit, fit_form, fit_lexeme | derived | FIT |
| src_t, src_n | derived | the glossed word's stem piece |
| src_lexeme, src_count | given | k1 pieces, k1/lexicon/lexemes.tsv `tanakh` |
| rare | derived | RARE (`src_count` < 20) |
| in_pilot | derived | as above |

## banks/abbrev.tsv, banks/abbrev_context.tsv, banks/unknown_abbrev.tsv, sealed/chooser_sample.tsv

`abbrev` given; `written`, `kind` derived (the fixed table of `ladder_abbrev.py`). `abbrev_context.tsv` (rule AB-CTX,
2026-11-25): `abbrev`, `context`, `written`: the row's abbreviation is written so in that context (`after_makom`,
`after_negation`, `to_idol_possessive`; `ladder_abbrev.py` defines them). `unknown_abbrev.tsv`: `abbrev`,
`count`, `example` (a comment id), derived. `chooser_sample.tsv`: `portion`, `comment`, derived (5.5).
"""


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def rel(p):
    return str(Path(p).resolve().relative_to(REPO))


def stage58(out):
    out.mkdir(parents=True, exist_ok=True)
    info = LB.build(out)
    srcs = {rel(LB.MD): {"sha256": sha(LB.MD), "license": "Public Domain, Sefaria, On Your Way",
                         "work": "Metzudat David (David Altschuler)"},
            rel(LB.MZ): {"sha256": sha(LB.MZ), "license": "Public Domain, Sefaria, On Your Way",
                         "work": "Metzudat Zion (Yechiel Hillel Altschuler)"}}
    for part in ("hbo", "arc"):
        for f in ("words.parquet", "pieces.parquet"):
            p = LB.K1 / part / f; srcs[rel(p)] = {"sha256": sha(p)}
    p = LB.K1 / "lexicon" / "lexemes.tsv"; srcs[rel(p)] = {"sha256": sha(p)}
    (out / "sources.json").write_text(json.dumps(srcs, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "COLUMNS.md").write_text(COLUMNS_58, encoding="utf-8")
    files = {}
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name not in ("build.json", "VALIDATION.md") and "cache" not in p.relative_to(out).parts:
            files[str(p.relative_to(out))] = sha(p)
    bj = {"build": "pilot-1", "spec": SPEC, "stage": 58,
          "entry": "shoresh/.venv/bin/python -I shoresh/macula/build_ladder.py --build pilot-1 --stage 58",
          "code": {c: sha(REPO / c) for c in CODE}, "files": files,
          "sealed_chooser": files["sealed/chooser_sample.tsv"], "notes": info}
    (out / "build.json").write_text(json.dumps(bj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return bj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default="pilot-1")
    ap.add_argument("--stage", required=True)
    ap.add_argument("--out")
    ap.add_argument("--prepare", action="store_true"); ap.add_argument("--check", action="store_true")
    ap.add_argument("--batch", type=int, default=150); ap.add_argument("--ingest", nargs="+"); ap.add_argument("--spend", type=float)
    a = ap.parse_args()
    out = Path(a.out) if a.out else ROOT / a.build
    if a.stage == "59":
        from macula import ladder_stage59
        out = Path(a.out) if a.out else LB.DATA / "hebrew-levels" / "pilot-2"
        bj = ladder_stage59.stage59(out, sha, rel, REPO)
        print(json.dumps({"out": str(out), "files": len(bj["files"])}, ensure_ascii=False))
        return
    if a.stage == "60":
        from macula import ladder_stage60 as L60
        src = ROOT / a.build
        if a.prepare:
            print(json.dumps(L60.prepare(out, a.batch), ensure_ascii=False)); return
        if a.ingest:
            print(json.dumps({"ingested": L60.ingest(src, a.ingest[0])})); return
        if not a.check: sys.exit("stage 60: --prepare, --ingest BATCH or --check")
        out.mkdir(parents=True, exist_ok=True)
        res = L60.check(src, out)
        if "rows" not in res:
            print(json.dumps(res, ensure_ascii=False)); sys.exit(1)
        L60.finish(src, out, sha, rel, REPO)
        print(json.dumps(res, ensure_ascii=False)); return
    if a.stage == "61":
        from macula import ladder_stage61 as L61
        src = ROOT / a.build
        info = L61.build(src, out)
        bj = L61.finish(src, out, sha, rel, REPO, info)
        print(json.dumps({"out": str(out), "files": len(bj["files"]), "notes": info}, ensure_ascii=False)); return
    if a.stage == "62":
        from macula import ladder_stage62 as L62
        src = ROOT / a.build
        if a.prepare:
            print(json.dumps(L62.prepare(src), ensure_ascii=False)); return
        if a.ingest:
            r = L62.ingest(src, a.ingest)
            print(json.dumps(r, ensure_ascii=False)); sys.exit(1 if any("rows" not in x for x in r) else 0)
        if not a.check: sys.exit("stage 62: --prepare, --ingest FILE... or --check --spend USD")
        if a.spend is None: sys.exit("stage 62 --check: give --spend USD (the session's spend, for the credit)")
        out.mkdir(parents=True, exist_ok=True)
        res = L62.check(src, out)
        if "rows" not in res:
            print(json.dumps(res, ensure_ascii=False)); sys.exit(1)
        L62.finish(src, out, sha, rel, REPO, a.spend)
        print(json.dumps(res, ensure_ascii=False)); return
    if a.stage != "58":
        sys.exit(f"stage {a.stage} is not built yet")
    bj = stage58(out)
    print(json.dumps({"out": str(out), "files": len(bj["files"]), "notes": bj["notes"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
