"""Builder of the source examples (SPEC: internal-docs/source-examples-spec/SPEC.md; stages 02-10 build version 1.0
into b builds, stages 14 on build version 1.1 into c builds; stage 23 builds version 1.2 into d builds).

    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --stage 02|03|04|05|06|07|08|09|10|14|15|16|17|18|19|20 [--lang hbo|arc|grc] [--build b1|c1]
    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build d1 --stage 23     # SPEC 1.2: every table
    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build d1 --stage 24     # SPEC 1.2: close (docs)
    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build e1 --stage 28     # SPEC 1.3: every table, with the
                                                                                            # mends of stage 28 (D12c, D16, D7r, D7n, D19)
    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build e1 --stage 29     # SPEC 1.3: close (docs)
    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build g1 --stage 35     # SPEC 1.5: the 1.4 builders
    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build h1 --stage 38     # SPEC 1.6: the 1.5 builders
                                                                                            # with the 1.6 rules (V16)
                                                                                            # with the 1.5 rules (V15)
    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build f1 --stage 32     # SPEC 1.4: the 1.3 builders
                                                                                            # (28, 29) with D24a, then the
                                                                                            # new tables (examples_v14.py)

A d build (SPEC 1.2) runs the stage builders of 1.1 in order (terms, 15, 16, 17, 18, 19, 20) with
examples_common.V12 set, so that each applies the 1.2 rules where CHANGES-1.2.md changes one, then the 1.2 terms
part of categories.toml. `--stage 23` runs them all; a single sub-stage (14 to 20) may be run on a d build for a
check (the validator's strict view does so). Counts go to cache/stage23.NN-counts.json. `--stage 24`
(examples_close12.py) closes a d build after stage 23: sources.json, COLUMNS.md, READ-FIRST.md and the glossed
chapters; counts to cache/stage24-counts.json.

Writes shoresh/macula/data/source-examples/<build>/<lang>/ (and <build>/cache/). Each stage reads the sources and
the tables of earlier stages and writes its own files anew. `--root` writes the build elsewhere (a rebuild check).
Parses of the source XML are cached under /tmp/claude-1000/source-examples/cache/, keyed by the sources' sha256;
an empty cache only makes the run slower.
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HERE)  # our own modules; appended so nothing shadows the standard library

import examples_words  # noqa: E402
import examples_heads  # noqa: E402
import examples_clauses  # noqa: E402
import examples_values  # noqa: E402
import examples_people  # noqa: E402
import examples_statements  # noqa: E402
import examples_links  # noqa: E402
import examples_shared  # noqa: E402
import examples_reading  # noqa: E402
import examples_terms  # noqa: E402
import examples_core  # noqa: E402
import examples_people11  # noqa: E402
import examples_model  # noqa: E402
import examples_links11  # noqa: E402
import examples_shared11  # noqa: E402
import examples_common  # noqa: E402
import examples_terms12  # noqa: E402
import examples_close12  # noqa: E402

STAGES = {"02": examples_words.build, "03": examples_heads.build, "04": examples_clauses.build,
          "05": examples_values.build, "06": examples_people.build, "07": examples_statements.build,
          "08": examples_links.build, "09": examples_shared.build, "10": examples_reading.build,
          "14": examples_terms.build, "15": examples_core.build,
          "16": examples_people11.build, "17": examples_model.build, "18": examples_statements.build11, "19": examples_links11.build,
          "20": examples_shared11.build}
LANGS = ("hbo", "arc", "grc")
SUB12 = ("14", "15", "16", "17", "18", "19", "20")      # the order of the sub-stages of stage 23


def write_counts(outdir, stage, langs, counts, ex):
    report = {"stage": stage, "langs": list(langs), "counts": counts,
              "exceptions": {k: {"count": len(v), "items": v} for k, v in sorted(ex.items())}}
    path = os.path.join(outdir, "cache", f"stage{stage}-counts.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")


def run12(outdir, stage, langs):
    """SPEC 1.2 (d builds): stage 23 = the sub-stages in order; or one sub-stage."""
    examples_common.V12 = True
    if stage == "24":
        t0 = time.time()
        counts = {}
        ex = examples_close12.build(outdir, langs, counts)
        write_counts(outdir, "24", langs, counts, ex)
        print(f"stage 24: built in {time.time() - t0:.0f} s, {len(counts)} counts, {len(ex)} exception lists", flush=True)
        return
    m = {"14": examples_terms12.build, **{k: STAGES[k] for k in SUB12[1:]}}
    for st in (SUB12 if stage == "23" else (stage,)):
        t0 = time.time()
        counts = {}
        ex = m[st](outdir, langs, counts)
        write_counts(outdir, f"23.{st}", langs, counts, ex)
        if st == "20":
            examples_terms12.append_terms_part(outdir, langs)
        print(f"stage 23.{st}: built in {time.time() - t0:.0f} s, {len(counts)} counts, {len(ex)} exception lists",
              flush=True)


SUB13 = ("14", "15", "16", "17", "18", "19", "20", "13")   # stage 27: the 1.2 sub-stages, then the 1.3 close


def run13(outdir, stage, langs):
    """SPEC 1.3 (e builds): stage 27 = the sub-stages of 1.2 with the 1.3 rules (examples_v13), then the 1.3 close;
    or one sub-stage. Counts go to cache/stage27.NN-counts.json."""
    import examples_v13
    m = {"14": examples_v13.terms, **{k: STAGES[k] for k in SUB12[1:]}, "13": examples_v13.close}
    if stage == "29":     # SPEC 1.3 section 14: close13 (sources.json, COLUMNS.md, READ-FIRST.md, glossed chapters)
        import examples_close13
        examples_v13.setup("99")
        t0 = time.time()
        counts = {}
        ex = examples_close13.build(outdir, langs, counts)
        write_counts(outdir, "29", langs, counts, ex)
        print(f"stage 29: built in {time.time() - t0:.0f} s, {len(counts)} counts, {len(ex)} exception lists", flush=True)
        return
    whole = stage in ("27", "28")     # 28 = 27 with the stage-28 mends, which an e build always applies (SPEC 1.3)
    for st in (SUB13 if whole else (stage,)):
        examples_v13.setup(st if st != "13" else "99")
        t0 = time.time()
        counts = {}
        ex = m[st](outdir, langs, counts)
        write_counts(outdir, f"{'28' if stage == '28' else '27'}.{st}", langs, counts, ex)
        if st == "20":
            examples_terms12.append_terms_part(outdir, langs)
        print(f"stage {'28' if stage == '28' else '27'}.{st}: built in {time.time() - t0:.0f} s, {len(counts)} counts, {len(ex)} exception lists",
              flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=sorted(STAGES) + ["23", "24", "27", "28", "29", "13", "32", "32.new", "35", "38", "49"])
    ap.add_argument("--lang", choices=LANGS, action="append")
    ap.add_argument("--build", default="b1")
    ap.add_argument("--root", default=os.path.join(HERE, "data/source-examples"))
    ap.add_argument("--cache", help="folder for the source parse cache (default: examples_src.CACHE)")
    a = ap.parse_args()
    if a.cache:
        import examples_src
        examples_src.CACHE = a.cache
    langs = tuple(a.lang or LANGS)
    ib = os.path.basename(os.path.normpath(a.build)).startswith("i")
    if ib and a.stage == "49":
        # SPEC 1.7 section 14: stage 49 copies hbo, arc, grc, other/, lexicon/ from h1 (section 13, sha256 checked)
        # and builds heb_mod/, heb_scg/ by D29 to D44 (examples_v17*.py); Greek is read only from <build>/grc
        import examples_v17
        outdir = os.path.join(a.root, a.build)
        src = os.path.join(a.root, "h1")
        t0 = time.time()
        counts = {}
        ex = examples_v17.build(outdir, src, counts)
        write_counts(outdir, "49", LANGS + examples_v17.EDS, counts, ex)
        print(f"stage 49 built in {time.time() - t0:.0f} s, {len(counts)} counts, {len(ex)} exception lists -> {outdir}")
        return
    hb = os.path.basename(os.path.normpath(a.build)).startswith(("h", "i"))     # an i build's 1.6 part is h1's
    if hb:
        # SPEC 1.6 section 14: stage 38 = every builder of 1.5 (stage 28, then 29, then examples_v14) with the 1.5 and
        # the 1.6 switch on (examples_v15 D18, examples_people11 SE5, examples_v15b D25 step 2b, examples_v14 D27)
        if a.stage != "38" and a.stage not in SUB13:
            raise SystemExit(f"an h build (SPEC 1.6) takes --stage 38 (or one sub-stage of 28 for a check), not {a.stage}")
        examples_common.V16 = True
        import examples_v14
        examples_v14.STATES = ("member", "nt_only", "function", "name", "no_number", "few_places", "spread",
                               "kept_out", "alone")     # SPEC 1.6 D27: kept_out between spread and alone
    if hb or os.path.basename(os.path.normpath(a.build)).startswith("g"):
        # SPEC 1.5 section 14: stage 35 = every builder of 1.4 (stage 28, then 29, then examples_v14) with the 1.5 switch
        # on, so that each applies the rules 1.5 changes where it writes the column (examples_v15, examples_v15b)
        if not hb and a.stage != "35" and a.stage not in SUB13:
            raise SystemExit(f"a g build (SPEC 1.5) takes --stage 35 (or one sub-stage of 28 for a check), not {a.stage}")
        if set(langs) != set(LANGS) and a.stage in ("35", "38"):
            raise SystemExit("stage 35 builds the three languages together")
        import examples_v14
        outdir = os.path.join(a.root, a.build)
        t0 = time.time()
        examples_common.V14 = True
        examples_common.V15 = True
        examples_v14.setup()
        if a.stage not in ("35", "38"):      # one sub-stage (the validator's strict view runs stage 16 so)
            run13(outdir, a.stage, langs)
            print(f"stage {a.stage} built in {time.time() - t0:.0f} s -> {outdir}")
            return
        for st in ("28", "29"):
            run13(outdir, st, langs)
        t1 = time.time()
        counts = {}
        ex = examples_v14.build(outdir, counts)
        write_counts(outdir, a.stage, langs, counts, ex)
        print(f"stage {a.stage} (lexicon): built in {time.time() - t1:.0f} s, {len(counts)} counts, {len(ex)} exception lists")
        print(f"stage {a.stage} built in {time.time() - t0:.0f} s -> {outdir}")
        return
    if os.path.basename(os.path.normpath(a.build)).startswith("f"):
        # SPEC 1.4 section 14: stage 32 = every builder of 1.3 (stage 28, then 29) with the 1.4 switch (D24a), then the
        # new tables (examples_v14: other/heb_*/parts.parquet, lexicon/); `--stage 32.new` runs the new part alone
        if a.stage not in ("32", "32.new"):
            raise SystemExit(f"an f build (SPEC 1.4) takes --stage 32 (or 32.new), not {a.stage}")
        if set(langs) != set(LANGS):
            raise SystemExit("stage 32 builds the three languages together")
        import examples_v14
        outdir = os.path.join(a.root, a.build)
        t0 = time.time()
        examples_common.V14 = True
        examples_v14.setup()
        if a.stage == "32":
            for st in ("28", "29"):
                run13(outdir, st, langs)
        t1 = time.time()
        counts = {}
        ex = examples_v14.build(outdir, counts)
        write_counts(outdir, "32", langs, counts, ex)
        print(f"stage 32 (new in 1.4): built in {time.time() - t1:.0f} s, {len(counts)} counts, {len(ex)} exception lists")
        print(f"stage {a.stage} built in {time.time() - t0:.0f} s -> {outdir}")
        return
    if os.path.basename(os.path.normpath(a.build)).startswith("e"):
        if a.stage not in ("27", "28", "29") and a.stage not in SUB13:
            raise SystemExit(f"an e build (SPEC 1.3) takes --stage 28, then 29 (or one of {', '.join(SUB13)}), not {a.stage}")
        if set(langs) != set(LANGS) and a.stage in ("27", "28", "29"):
            raise SystemExit(f"stage {a.stage} builds the three languages together")
        t0 = time.time()
        run13(os.path.join(a.root, a.build), a.stage, langs)
        print(f"stage {a.stage} built in {time.time() - t0:.0f} s -> {os.path.join(a.root, a.build)}")
        return
    if os.path.basename(os.path.normpath(a.build)).startswith("d"):
        if a.stage not in ("23", "24") and a.stage not in SUB12:
            raise SystemExit(f"a d build (SPEC 1.2) takes --stage 23, 24 (or one of {', '.join(SUB12)}), not {a.stage}")
        if set(langs) != set(LANGS) and a.stage in ("23", "24"):
            raise SystemExit(f"stage {a.stage} builds the three languages together")
        t0 = time.time()
        run12(os.path.join(a.root, a.build), a.stage, langs)
        print(f"stage {a.stage} built in {time.time() - t0:.0f} s -> {os.path.join(a.root, a.build)}")
        return
    if a.stage in ("23", "24"):
        raise SystemExit(f"stage {a.stage} builds version 1.2: use a d build")
    v11 = os.path.basename(os.path.normpath(a.build)).startswith("c")
    if v11 != (a.stage >= "14"):
        raise SystemExit(f"stage {a.stage} builds version {'1.1' if a.stage >= '14' else '1.0'}: "
                         f"use a {'c' if a.stage >= '14' else 'b'} build, not {a.build}")
    outdir = os.path.join(a.root, a.build)
    t0 = time.time()
    counts = {}
    ex = STAGES[a.stage](outdir, langs, counts)
    report = {"stage": a.stage, "langs": list(langs), "counts": counts,
              "exceptions": {k: {"count": len(v), "items": v} for k, v in sorted(ex.items())}}
    path = os.path.join(outdir, "cache", f"stage{a.stage}-counts.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    for k, v in counts.items():
        print(f"{k}: {v}")
    for k, v in sorted(ex.items()):
        print(f"exception: {k}: {len(v)}" + (f"  e.g. {v[:3]}" if v else ""))
    print(f"stage {a.stage} built in {time.time() - t0:.0f} s -> {outdir}")


if __name__ == "__main__":
    main()
