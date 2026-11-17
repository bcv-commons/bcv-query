#!/usr/bin/env python3
"""Packet 32 to bcv-query: the Hebrew NT alignments (the user, 2026-11-17: hand results AND code over; original-language work of
lasting value is bcv-query's). Builds internal-docs/handover/bcv-query-2026-11-12/32-hebrew-nt-alignments/:

  remap        the 141 Delitzsch words whose split differs between research's unpointed tagger export (the parts the 2026-10-31
               alignment and review sit on) and bcv-commons/hebrew-nt-analysis v0.2 heb_mod -> remap_heb_mod_parts.tsv
               (old part -> new parts by character span; an unwritten part, text '', goes to the part holding the letter before it)
  byid         Delitzsch alignments-by-id (lexeme-aligner's builder on research's align-text run) remapped to v0.2 parts
               -> heb_mod/by-id/<BOOK>_<hash>.json (file names and hashes as the builder wrote them)
  records      the review layers: heb_scg as they are (their parts = hebrew-nt-analysis heb_scg, identical in v0.1 and v0.2),
               heb_mod remapped (link [[token, part]]; 'words' are whole tokens and need no remap) -> review/<ed>/corrections.jsonl,
               + calibration.json, marks.jsonl, claude.tsv, the blind reference judgments (check/) and spot checks (spot*/)
  match        each record's before.link against alignments-by-id v1.0 (9ab18f20) and v1.1 (bb56fae2) heb_scg, and against the
               remapped Delitzsch by-id -> match.json
  run          the align-text run record, logs, Jev v4 clause cells, compact / full layers, the USJ text -> heb_mod/align-text-run/
  code         the scripts and the design doc, copied as they are, + paths.json (the private paths they still read)
  manifest     sha256 of every file -> MANIFEST.sha256

    . ./env.sh; ~/sil-study/.venv/bin/python -I lab/bridge/handover_hebnt.py all"""
import collections, glob, hashlib, json, os, re, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRIV = os.environ["MAKE_TANAKH_PRIVATE"]; WP = os.environ["WORD_PARTS"]
OUT = os.path.join(ROOT, "internal-docs", "handover", "bcv-query-2026-11-12", "32-hebrew-nt-alignments")
OLD = os.path.join(PRIV, "rules", "bridge", "hebmod", "tagger", "export", "heb_mod", "words.parquet")
NEW = os.path.join(WP, "hebrew-nt-analysis", "heb_mod", "words.parquet")
BYID = os.path.join(PRIV, "rules", "data", "hebmod", "by-id")
REV = {"heb_scg": os.path.join(PRIV, "rules", "bridge", "scg_review"), "heb_mod": os.path.join(PRIV, "rules", "bridge", "hebmod", "review")}
CHK = {"heb_scg": os.path.join(PRIV, "rules", "bridge", "scg_check"), "heb_mod": os.path.join(PRIV, "rules", "bridge", "hebmod", "check")}
ABI = {"v1.0": "9ab18f20", "v1.1": "bb56fae2"}
CODE = ["lab/bridge/hebmod_byid.py", "lab/bridge/hebmod_parts.py", "lab/bridge/scg_check.py", "lab/bridge/scg_review.py",
        "lab/bridge/scg_export.py", "lab/bridge/witness_agree.py", "lab/bridge/key_bridge.py", "lab/bridge/scg_bridge_probe.py",
        "lab/bridge/handover_hebnt.py", "lab/bridge/hnt_function_sample.py", "docs/scg-review-design.md"]


def parts(p):
    import pyarrow.parquet as pq
    W = collections.defaultdict(list)
    for r in pq.read_table(p, columns=["book", "chapter", "verse", "i", "part", "text"]).to_pylist():
        W[(r["book"], r["chapter"], r["verse"], r["i"])].append((r["part"], r["text"] or ""))
    return {k: [t for _, t in sorted(v)] for k, v in W.items()}


def spans(ts):
    out, o = [], 0
    for t in ts:
        out.append((o, o + len(t))); o += len(t)
    return out


def remap_table():
    A, B = parts(OLD), parts(NEW)
    assert A.keys() == B.keys()
    R = {}
    for k in A:
        if A[k] == B[k]:
            continue
        sa, sb = spans(A[k]), spans(B[k]); m = {}
        for p, (a0, a1) in enumerate(sa):
            if a1 > a0:
                m[p] = [q for q, (b0, b1) in enumerate(sb) if b0 < a1 and a0 < b1]
            else:
                m[p] = [q for q, (b0, b1) in enumerate(sb) if b0 < a0 <= b1] or [0]
        R[k] = (A[k], B[k], m)
    return R


def write_remap(R):
    with open(os.path.join(OUT, "remap_heb_mod_parts.tsv"), "w", encoding="utf-8") as f:
        f.write("book\tchapter\tverse\ti\tparts_research\tparts_v0.2\tmap(old->new)\n")
        for (b, c, v, i), (a, n, m) in sorted(R.items()):
            f.write(f"{b}\t{c}\t{v}\t{i}\t{'|'.join(a)}\t{'|'.join(n)}\t{json.dumps(m)}\n")


def new_pos(R, b, c, v, x):
    t, _, p = str(x).partition(".")
    key = (b, c, v, int(t))
    if not p or key not in R:
        return [x]
    a, n, m = R[key]
    return [int(t)] if len(n) == 1 else [f"{t}.{q}" for q in m[int(p)]]


def byid(R):
    od = os.path.join(OUT, "heb_mod", "by-id"); os.makedirs(od, exist_ok=True); st = collections.Counter()
    for f in sorted(glob.glob(os.path.join(BYID, "*.json"))):
        b = os.path.basename(f)[:3]; d = json.load(open(f, encoding="utf-8"))
        for cv, e in d.items():
            if not re.fullmatch(r"\d+:\d+", cv):
                continue
            c, v = map(int, cv.split(":"))
            for L in e["links"]:
                ps = []
                for x in L[0]:
                    for y in new_pos(R, b, c, v, x):
                        if y not in ps:
                            ps.append(y)
                st["positions changed"] += ps != L[0]; L[0] = ps; st["links"] += 1
        json.dump(d, open(os.path.join(od, os.path.basename(f)), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        st["files"] += 1
    shutil.copytree(os.path.join(os.path.dirname(BYID), "by-id-root"), os.path.join(OUT, "heb_mod", "by-id-root"), dirs_exist_ok=True)
    return dict(st)


def gid_verse():
    """Greek id -> the Delitzsch verse whose by-id entry links it (the Hebrew edition's numbering; verses can shift)"""
    out = {}
    for f in sorted(glob.glob(os.path.join(BYID, "*.json"))):
        b = os.path.basename(f)[:3]
        for cv, e in json.load(open(f, encoding="utf-8")).items():
            if re.fullmatch(r"\d+:\d+", cv):
                c, v = map(int, cv.split(":"))
                for pos, gids, cls in e["links"]:
                    for g in gids:
                        out.setdefault(g, (b, c, v))
    return out


def records(R):
    st = {}; GV = gid_verse()
    for ed, src in REV.items():
        od = os.path.join(OUT, "review", ed); os.makedirs(od, exist_ok=True); n = collections.Counter()
        with open(os.path.join(od, "corrections.jsonl"), "w", encoding="utf-8") as out:
            for l in open(os.path.join(src, "corrections.jsonl"), encoding="utf-8"):
                r = json.loads(l)
                if ed == "heb_mod":
                    bcv = GV.get(r["gid"])
                    for side in ("before", "after"):
                        if "link" in r[side] and r[side]["link"]:
                            assert bcv, r["gid"]
                            b, c, v = bcv; nl = []
                            for t, p in r[side]["link"]:
                                for y in new_pos(R, b, c, v, f"{t}.{p}"):
                                    tt, _, pp = str(y).partition(".")
                                    pair = [int(tt), int(pp) if pp else 0]
                                    if pair not in nl:
                                        nl.append(pair)
                            n["links remapped"] += nl != r[side]["link"]; r[side]["link"] = nl
                n[r["decided_by"]] += 1
                out.write(json.dumps(r, ensure_ascii=False) + "\n")
        for fn in ("calibration.json", "marks.jsonl", "claude.tsv", "answers.jsonl"):
            if os.path.exists(os.path.join(src, fn)):
                shutil.copy2(os.path.join(src, fn), od)
        for sub in ("spot", "spot2"):
            if os.path.isdir(os.path.join(src, sub)):
                shutil.copytree(os.path.join(src, sub), os.path.join(od, sub), dirs_exist_ok=True)
        if os.path.isdir(CHK[ed]):
            shutil.copytree(CHK[ed], os.path.join(od, "check"), dirs_exist_ok=True)
        st[ed] = dict(n)
    return st


def links_by_gid(files, H):
    """Greek id -> sorted [[token, part]] as scg_check.keys_of reads a by-id file (a whole token = all its parts)"""
    out = {}
    for f in files:
        b = os.path.basename(f)[:3]
        for cv, e in json.load(open(f, encoding="utf-8")).items():
            if not re.fullmatch(r"\d+:\d+", cv):
                continue
            c, v = map(int, cv.split(":")); hv = H.get((b, c, v), {})
            for pos, gids, cls in e["links"]:
                ks = []
                for x in pos:
                    t, _, p = str(x).partition(".")
                    ks += [[int(t), int(p)]] if p else [[int(t), q] for q in range(hv.get(int(t), 1))]
                for g in gids:
                    out.setdefault(g, []).extend(ks)
    return {g: sorted(map(list, {tuple(k) for k in ks})) for g, ks in out.items()}


def match():
    from huggingface_hub import snapshot_download
    res = {}
    for ed, pq_path, srcs in (("heb_scg", os.path.join(WP, "hebrew-nt-analysis", "heb_scg", "words.parquet"),
                               {v: (lambda rev: lambda: sorted(glob.glob(os.path.join(snapshot_download("bcv-commons/alignments-by-id", repo_type="dataset", revision=rev, allow_patterns=["n1904/h/heb/heb_scg/*"]), "n1904/h/heb/heb_scg/*.json"))))(rev) for v, rev in ABI.items()}),
                              ("heb_mod", NEW, {"research by-id, remapped to v0.2": lambda: sorted(glob.glob(os.path.join(OUT, "heb_mod", "by-id", "*.json")))})):
        P = parts(pq_path); H = collections.defaultdict(dict)
        for (b, c, v, i), ts in P.items():
            H[(b, c, v)][i] = len(ts)
        recs = [json.loads(l) for l in open(os.path.join(OUT, "review", ed, "corrections.jsonl"), encoding="utf-8")]
        for name, fs in srcs.items():
            L = links_by_gid(fs(), H); n = collections.Counter()
            for r in recs:
                cur = L.get(r["gid"], [])
                n["equal" if sorted(r["before"]["link"]) == cur else "differs"] += 1
            res[f"{ed} vs {name}"] = dict(n, records=len(recs))
    json.dump(res, open(os.path.join(OUT, "match.json"), "w"), indent=1)
    return res


def code():
    od = os.path.join(OUT, "code"); os.makedirs(od, exist_ok=True)
    for p in CODE:
        shutil.copy2(os.path.join(ROOT, p), od)
    paths = {}
    for p in CODE:
        s = open(os.path.join(ROOT, p), encoding="utf-8").read()
        hits = sorted(set(re.findall(r"(MAKE_TANAKH_PRIVATE|MAKE_TANAKH_WORK|BCV_COMMONS|WORD_PARTS|TYPESAFE_API_KEY|private/[\w/.-]+)", s)))
        if hits:
            paths[os.path.basename(p)] = hits
    json.dump(paths, open(os.path.join(od, "paths.json"), "w"), indent=1)


def run_record():
    """the align-text run that made the Delitzsch alignment: its record (settings with sha256, lexeme-aligner commit, steps),
    logs, the Jev v4 clause cells (the paid output: the by-id builder re-runs from them without new spend), the compact and
    full-alignments-llm layers, and the edition's USJ text (eBible `heb`, public domain). The parts view (211 MB) is left out:
    it is rebuilt from the USJ and the split file by the run's first step."""
    A = os.path.join(PRIV, "align", "heb_mod"); od = os.path.join(OUT, "heb_mod", "align-text-run"); os.makedirs(od, exist_ok=True)
    for f in ("out/align-text-run.json", "out/parts-pin.json", "run.log", "run_jev.log"):
        shutil.copy2(os.path.join(A, f), od)
    for f in glob.glob(os.path.join(A, "out", "align_llm_jevC.*")):
        shutil.copy2(f, os.path.join(od, "jevC")) if os.path.isdir(os.path.join(od, "jevC")) else (os.makedirs(os.path.join(od, "jevC")), shutil.copy2(f, os.path.join(od, "jevC")))
    for d in ("compact", "full-alignments-llm"):
        shutil.copytree(os.path.join(A, "out", d), os.path.join(od, d), dirs_exist_ok=True)
    shutil.copytree(os.path.join(A, "usj"), os.path.join(od, "usj"), dirs_exist_ok=True)


def manifest():
    rows = []
    for dp, _, fs in os.walk(OUT):
        for f in sorted(fs):
            p = os.path.join(dp, f); rel = os.path.relpath(p, OUT)
            if rel != "MANIFEST.sha256":
                rows.append(f"{hashlib.sha256(open(p, 'rb').read()).hexdigest()}  {rel}")
    open(os.path.join(OUT, "MANIFEST.sha256"), "w").write("\n".join(sorted(rows, key=lambda r: r.split("  ")[1])) + "\n")
    return len(rows)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    R = remap_table(); write_remap(R); print("remap words", len(R))
    print("byid", byid(R)); print("records", records(R)); print("match", json.dumps(match(), indent=1))
    run_record(); code(); print("manifest files", manifest())
