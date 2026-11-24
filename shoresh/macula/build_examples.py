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
sys.path.append(os.path.dirname(HERE))  # the `macula` package (bridge_corpus_lxx imports macula.text_faults since F0016)

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


# ---- SPEC 1.8, stage 52: the replay on a copy of i1 (report 52) ------------------------------------------------------
# Two inputs that i1 read are gone from the disk since i1 was built (data/arg-roles/roles.tsv 4c494ac9…, rebuilt for
# argument-roles v0.3 and v0.4; the aligner's republished heb_scg alignments and sidecars). So j1 is not built from
# nothing: it is a sha-checked copy of i1, on which the sub-stages the mends reach run again with the 1.8 switch, in
# the order of stage 38 and 49. After each sub-stage, every file it wrote outside the reach of section 13 (1.8) is put
# back from i1 (what the builder wrote is recorded by sha256 in cache/stage52-replay.json). `--mends off` runs the same
# replay with the switch off: it must give i1 back byte for byte (the proof that the lost inputs reach no file of the
# reach).
REPLAY_SUBS = ("16", "17", "18", "19", "20", "13")
FIVE = ("hbo", "arc", "grc", "other", "lexicon")
STMT = ("forms", "paradigms", "markers", "constructions", "orders", "agreement", "frames", "pairs", "clause_links",
        "exceptions")
DECL = ("sources.json", "categories.toml", "COLUMNS.md", "READ-FIRST.md", "VALIDATION.md")


def in_reach18(rel):
    """SPEC 1.8 section 13: the files of j1 that may differ from i1's."""
    parts = rel.split("/")
    if parts[0] in ("heb_mod", "heb_scg", "cache", "lexicon"):
        return True
    f = parts[-1]
    if f in DECL:
        return True
    if parts[0] == "other":
        return len(parts) == 3 and parts[1] in ("heb_mod", "heb_scg") and f in ("words.parquet", "parts.parquet")
    if parts[0] in ("hbo", "arc", "grc") and len(parts) == 2:
        if f == "added.parquet" or f == "profile.tsv" or f[:-8] in STMT:
            return True
        if parts[0] in ("hbo", "arc") and f in ("links.parquet", "link_account.parquet"):
            return True
    return False


def _sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _files(d):
    out = {}
    for sub in FIVE + ("heb_mod", "heb_scg"):
        for root, _ds, fs in os.walk(os.path.join(d, sub)):
            for f in fs:
                p = os.path.join(root, f)
                out[os.path.relpath(p, d)] = p
    return out


def replay18(outdir, base, mends, langs):
    import shutil
    import examples_v14
    import examples_v17
    if os.path.exists(outdir):
        raise SystemExit(f"{outdir} exists: stage 52 builds into a new folder (no rm; move the old one to trash-<date>/)")
    t0 = time.time()
    examples_common.REPLAY18 = True
    examples_common.V18 = mends
    examples_common.V14 = examples_common.V15 = examples_common.V16 = True
    examples_v14.STATES = ("member", "nt_only", "function", "name", "no_number", "few_places", "spread",
                           "kept_out", "alone")
    examples_v14.setup()
    # 1. the copy of i1's five folders and the cache items the 1.6 builders and stage 49 read
    bf = _files(base)
    ish = {}
    for rel, p in sorted(bf.items()):
        if rel.split("/")[0] in ("heb_mod", "heb_scg"):
            continue
        q = os.path.join(outdir, rel)
        os.makedirs(os.path.dirname(q), exist_ok=True)
        shutil.copyfile(p, q)
        ish[rel] = _sha(p)
        if _sha(q) != ish[rel]:
            raise SystemExit(f"copy of {rel}: sha256 differs")
    for rel in bf:
        if rel.split("/")[0] in ("heb_mod", "heb_scg"):
            ish[rel] = _sha(bf[rel])
    cdir = os.path.join(outdir, "cache")
    os.makedirs(cdir, exist_ok=True)
    for name in sorted(os.listdir(os.path.join(base, "cache"))):
        if name in examples_v17.CACHE_COPIED:
            p = os.path.join(base, "cache", name)
            (shutil.copytree if os.path.isdir(p) else shutil.copyfile)(p, os.path.join(cdir, name))
    print(f"stage 52: copied {len(ish)} files of i1 in {time.time() - t0:.0f} s", flush=True)
    log = {"base": "i1", "mends": mends, "copied": len(ish), "steps": []}

    def after(step):
        now = _files(outdir)
        wrote, back = {}, []
        for rel, p in sorted(now.items()):
            if rel not in ish:
                wrote[rel] = {"i1": None, "built": _sha(p), "reach": in_reach18(rel)}
                continue
            s = _sha(p)
            if s != ish[rel]:
                wrote[rel] = {"i1": ish[rel], "built": s, "reach": in_reach18(rel)}
                if not in_reach18(rel):
                    keep = os.path.join(cdir, "stage52-outside", step.split()[0], rel)
                    os.makedirs(os.path.dirname(keep), exist_ok=True)
                    shutil.copyfile(p, keep)        # what the builder wrote, for the report (section 13: not widened)
                    shutil.copyfile(bf[rel], p)
                    back.append(rel)
        log["steps"].append({"step": step, "differ_from_i1": wrote, "put_back_from_i1": back})
        print(f"stage 52 after {step}: {len(wrote)} files differ from i1 ({sum(1 for v in wrote.values() if v['reach'])} "
              f"in the reach); {len(back)} put back from i1", flush=True)
        return wrote

    for st in REPLAY_SUBS:
        run13(outdir, st, langs)
        after(f"28.{st}")
    run13(outdir, "29", langs)
    after("29")
    counts = {}
    ex = examples_v14.build(outdir, counts)
    write_counts(outdir, "52.38", langs, counts, ex)
    after("38 (lexicon)")
    counts = {}
    ex = examples_v17.build(outdir, None, counts)
    write_counts(outdir, "52.49", LANGS + examples_v17.EDS, counts, ex)
    after("49 (editions)")
    log["nt guard: republished aligner files read in place of the pinned ones (links not kept)"] = sorted(
        set(examples_common.REPLAY18_DRIFT))
    with open(os.path.join(cdir, "stage52-replay.json"), "w", encoding="utf-8") as fh:
        json.dump(log, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"stage 52 (mends {'on' if mends else 'off'}) built in {time.time() - t0:.0f} s -> {outdir}")


# ---- SPEC 1.9, stage 55: the replay on a copy of j1 (report 55) ------------------------------------------------------
# k1 is built on j1 as j1 was built on i1 (replay18): a sha-checked copy of j1, the sub-stages the mends reach run again
# with V18 on and the 1.9 switch (examples_common.V19: N1 to N5) on or off. After each sub-stage a file outside the reach
# is put back from j1. N6 (section 13, 1.9): with the mends on, hbo and arc facts.parquet, the three source_errors.tsv
# and the three map.tsv are in the reach from the sub-stage that writes them whole (as stage 52's log shows: the
# source_errors at 28.16, facts at 28.19, map at 28.13); an earlier partial write is put back from j1. k0 (--mends off)
# reads the 1.8 Strong's table (585a53c3…, from the repository's history into k0/cache/) and must give j1 back.
N6_FROM = {"28.16": ("hbo/source_errors.tsv", "arc/source_errors.tsv", "grc/source_errors.tsv"),
           "28.19": ("hbo/facts.parquet", "arc/facts.parquet"),
           "28.13": ("hbo/map.tsv", "arc/map.tsv", "grc/map.tsv")}
STRONG18_SHA = "585a53c3"


def strong18(cdir):
    """The 1.8 Strong's table from the repository's history (read only) into the build's cache; its sha checked."""
    import hashlib
    import subprocess
    rel = "shoresh/macula/text_faults/strong_fixes.tsv"
    root = os.path.dirname(os.path.dirname(HERE))
    cmd = ["git"]
    for c in subprocess.run(cmd + ["log", "--format=%H", "--", rel], cwd=root, capture_output=True, text=True,
                            check=True).stdout.split():
        b = subprocess.run(cmd + ["show", f"{c}:{rel}"], cwd=root, capture_output=True, check=True).stdout
        if hashlib.sha256(b).hexdigest().startswith(STRONG18_SHA):
            q = os.path.join(cdir, "strong_fixes-1.8.tsv")
            with open(q, "wb") as fh:
                fh.write(b)
            return q, c
    raise SystemExit(f"strong_fixes.tsv {STRONG18_SHA}… not found in the history")


def replay19(outdir, base, mends, langs):
    import shutil
    from pathlib import Path
    import examples_v14
    import examples_v17
    import hebrew_nt_strong_fixes as SF
    if os.path.exists(outdir):
        raise SystemExit(f"{outdir} exists: stage 55 builds into a new folder (no rm; move the old one to trash-<date>/)")
    t0 = time.time()
    examples_common.REPLAY18 = True
    examples_common.V18 = True
    examples_common.V19 = mends
    examples_common.BASE19 = base
    examples_common.V14 = examples_common.V15 = examples_common.V16 = True
    examples_v14.STATES = ("member", "nt_only", "function", "name", "no_number", "few_places", "spread",
                           "kept_out", "alone")
    examples_v14.setup()
    bf = _files(base)
    jsh = {}
    for rel, p in sorted(bf.items()):
        if rel.split("/")[0] in ("heb_mod", "heb_scg"):
            continue
        q = os.path.join(outdir, rel)
        os.makedirs(os.path.dirname(q), exist_ok=True)
        shutil.copyfile(p, q)
        jsh[rel] = _sha(p)
        if _sha(q) != jsh[rel]:
            raise SystemExit(f"copy of {rel}: sha256 differs")
    for rel in bf:
        if rel.split("/")[0] in ("heb_mod", "heb_scg"):
            jsh[rel] = _sha(bf[rel])
    cdir = os.path.join(outdir, "cache")
    os.makedirs(cdir, exist_ok=True)
    for name in sorted(os.listdir(os.path.join(base, "cache"))):
        if name in examples_v17.CACHE_COPIED:
            p = os.path.join(base, "cache", name)
            (shutil.copytree if os.path.isdir(p) else shutil.copyfile)(p, os.path.join(cdir, name))
    log = {"base": os.path.basename(os.path.normpath(base)), "mends": mends, "copied": len(jsh), "steps": []}
    if not mends:
        q, c = strong18(cdir)
        SF.FIXES = Path(q)
        log["strong_fixes.tsv (1.8)"] = {"commit": c, "sha256": _sha(q)}
    log["strong_fixes.tsv read"] = {"file": os.path.relpath(str(SF.FIXES), os.path.dirname(os.path.dirname(HERE))),
                                    "sha256": _sha(str(SF.FIXES))}
    print(f"stage 55: copied {len(jsh)} files of {log['base']} in {time.time() - t0:.0f} s; strong_fixes "
          f"{log['strong_fixes.tsv read']['sha256'][:8]}", flush=True)
    n6 = set()

    def after(step):
        if mends:
            n6.update(N6_FROM.get(step, ()))
        now = _files(outdir)
        wrote, back = {}, []
        for rel, p in sorted(now.items()):
            reach = in_reach18(rel) or rel in n6
            if rel not in jsh:
                wrote[rel] = {"j1": None, "built": _sha(p), "reach": reach}
                continue
            sh = _sha(p)
            if sh != jsh[rel]:
                wrote[rel] = {"j1": jsh[rel], "built": sh, "reach": reach}
                if not reach:
                    keep = os.path.join(cdir, "stage55-outside", step.split()[0], rel)
                    os.makedirs(os.path.dirname(keep), exist_ok=True)
                    shutil.copyfile(p, keep)
                    shutil.copyfile(bf[rel], p)
                    back.append(rel)
        log["steps"].append({"step": step, "differ_from_j1": wrote, "put_back_from_j1": back,
                             "n6_in_reach": sorted(n6)})
        print(f"stage 55 after {step}: {len(wrote)} files differ from {log['base']} "
              f"({sum(1 for v in wrote.values() if v['reach'])} in the reach); {len(back)} put back", flush=True)

    for st in REPLAY_SUBS:
        run13(outdir, st, langs)
        after(f"28.{st}")
    run13(outdir, "29", langs)
    after("29")
    counts = {}
    ex = examples_v14.build(outdir, counts)
    write_counts(outdir, "55.38", langs, counts, ex)
    after("38 (lexicon)")
    counts = {}
    ex = examples_v17.build(outdir, None, counts)
    write_counts(outdir, "55.49", LANGS + examples_v17.EDS, counts, ex)
    after("49 (editions)")
    log["nt guard: republished aligner files read in place of the pinned ones (links not kept)"] = sorted(
        set(examples_common.REPLAY18_DRIFT))
    with open(os.path.join(cdir, "stage55-replay.json"), "w", encoding="utf-8") as fh:
        json.dump(log, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"stage 55 (1.9 mends {'on' if mends else 'off'}) built in {time.time() - t0:.0f} s -> {outdir}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=sorted(STAGES) + ["23", "24", "27", "28", "29", "13", "32", "32.new", "35", "38", "49", "52", "55"])
    ap.add_argument("--lang", choices=LANGS, action="append")
    ap.add_argument("--build", default="b1")
    ap.add_argument("--root", default=os.path.join(HERE, "data/source-examples"))
    ap.add_argument("--cache", help="folder for the source parse cache (default: examples_src.CACHE)")
    ap.add_argument("--mends", choices=("on", "off"), default="on", help="stage 52: the 1.8 switch (off: the proof run)")
    ap.add_argument("--base", help="stage 52: the build replayed (default: i1 beside the build)")
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
    kb = os.path.basename(os.path.normpath(a.build)).startswith("k")
    if kb and a.stage == "55":
        # SPEC 1.9 section 15: stage 55 = the replay of stage 52 on j1 with the 1.9 switch (replay19)
        if set(langs) != set(LANGS):
            raise SystemExit("a k build (SPEC 1.9) takes --stage 55, the three languages together")
        replay19(os.path.join(a.root, a.build), a.base or os.path.join(HERE, "data/source-examples", "j1"),
                 a.mends == "on", langs)
        return
    if kb:
        # one sub-stage of 28 for a check (the strict view of stage 17): the 1.8 and 1.9 switches on, N3 reads j1
        if a.stage not in SUB13:
            raise SystemExit(f"a k build (SPEC 1.9) takes --stage 55 (or one sub-stage of 28 for a check), not {a.stage}")
        examples_common.V19 = True
        examples_common.BASE19 = a.base or os.path.join(HERE, "data/source-examples", "j1")
    jb = os.path.basename(os.path.normpath(a.build)).startswith(("j", "k"))
    if jb and a.stage == "52":
        if set(langs) != set(LANGS):
            raise SystemExit("stage 52 builds the three languages together")
        replay18(os.path.join(a.root, a.build), a.base or os.path.join(HERE, "data/source-examples", "i1"),
                 a.mends == "on", langs)
        return
    if jb:
        # SPEC 1.8 section 13, 14: stage 52 = every builder of h1 (stage 38: 28, 29, the lexicon) and then the 1.7 entry
        # of i1's editions (examples_v17, no copy), all with the 1.8 switch on (examples_common.V18: M1 to M5)
        if a.stage not in ("52",) and a.stage not in SUB13:
            raise SystemExit(f"a j build (SPEC 1.8) takes --stage 52 (or one sub-stage of 28 for a check), not {a.stage}")
        examples_common.V18 = True
    hb = os.path.basename(os.path.normpath(a.build)).startswith(("h", "i", "j", "k"))     # an i build's 1.6 part is h1's
    if hb:
        # SPEC 1.6 section 14: stage 38 = every builder of 1.5 (stage 28, then 29, then examples_v14) with the 1.5 and
        # the 1.6 switch on (examples_v15 D18, examples_people11 SE5, examples_v15b D25 step 2b, examples_v14 D27)
        if a.stage not in ("38", "52") and a.stage not in SUB13:
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
        if set(langs) != set(LANGS) and a.stage in ("35", "38", "52"):
            raise SystemExit("stage 35 builds the three languages together")
        import examples_v14
        outdir = os.path.join(a.root, a.build)
        t0 = time.time()
        examples_common.V14 = True
        examples_common.V15 = True
        examples_v14.setup()
        if a.stage not in ("35", "38", "52"):      # one sub-stage (the validator's strict view runs stage 16 so)
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
        if jb:      # SPEC 1.8: then the editions, by the 1.7 builders over this build's own folders (nothing copied)
            import examples_v17
            t2 = time.time()
            counts = {}
            ex = examples_v17.build(outdir, None, counts)
            write_counts(outdir, "52.49", LANGS + examples_v17.EDS, counts, ex)
            print(f"stage 52.49 (editions): built in {time.time() - t2:.0f} s, {len(counts)} counts, {len(ex)} exception lists")
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
