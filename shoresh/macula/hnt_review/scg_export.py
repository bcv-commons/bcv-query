#!/usr/bin/env python3
"""The heb_scg review (scg_review.py layer -> corrections.jsonl) as review records for lexeme-aligner's alignments-by-id, NOT a copy
of their alignment: one alignment stays theirs, and they apply the records in their build (user 2026-10-31: publishing their format
beside theirs would make two alignments of one text). Output, under $MAKE_TANAKH_PRIVATE/hf/alignment-reviews/n1904/h/heb/heb_scg/:
  <BOOK>.jsonl    one line per reviewed Greek word: every field of corrections.jsonl unchanged (the attestation: before, after, how,
                  decided_by, evidence, note, rules, model, date), plus `positions` in their notation:
                    {"verse": "c:v", "before": <their link's positions, exactly as in their file, or null = in `none`>,
                     "after": "same" | null (not rendered) | [whole tokens]}
                  `before` is the staleness key: a record applies only while their link of that word still equals it.
  manifest.json   their source files by name and sha256, the parts analysis pinned, counts, the classes, the checks run.
Positions: an integer is the whole token, "t.p" part p of token t (tokenizer v2; parts of hebrew-nt-analysis v0.1, the file they
pin). A changed link is given as whole tokens (choosing the part is the open version 2 question). `apply` (also run here as a test,
written only to the private bridge folder for our own use) shows the records applied to their files: the reviewed words get the
class `review-jev` or `review-claude`, freed tokens go to `added`. Checks (nothing is written on failure): each record's `before` is
its word's link in their file; the attestation reads back identical; applying keeps every Greek id once per verse and every
position in the word analysis, no verse-number token linked. SCG_EDITION=heb_mod does the same for Delitzsch (our
alignments-by-id build, hebmod_byid.py, and our unpointed parts, hebmod_parts.py).
    . ./env.sh; [SCG_EDITION=heb_mod] ~/sil-study/.venv/bin/python lab/bridge/scg_export.py"""
import collections, copy, glob, hashlib, json, os
import pandas as pd

P = os.environ["MAKE_TANAKH_PRIVATE"]; W = os.environ["MAKE_TANAKH_WORK"]; ED = os.environ.get("SCG_EDITION", "heb_scg")
B = os.path.join(P, "rules", "bridge")
EDITIONS = {
    "heb_scg": dict(src=os.path.join(P, "rules", "data", "hebnt", "dl"),    # their published files (identical to lexeme-aligner's)
                    rev=os.path.join(B, "scg_review"), words=os.path.join(W, "download", "hebrew-nt-analysis", "heb_scg", "words.parquet"),
                    source="bcv-commons/alignments-by-id n1904/h/heb/heb_scg (the 2026-10-23 build; files by sha256 above)",
                    parts={"dataset": "bcv-commons/hebrew-nt-analysis", "revision": "v0.1", "file": "heb_scg/words.parquet"}),
    "heb_mod": dict(src=os.path.join(P, "rules", "data", "hebmod", "by-id"), rev=os.path.join(B, "hebmod", "review"),
                    words=os.path.join(B, "hebmod", "tagger", "export", "heb_mod", "words.parquet"),
                    source="lexeme-aligner's alignments_by_id.build run here on our align-text run of heb_mod (chain by parts + Jev v4 "
                           "by clause, 2026-10-31; make-tanakh-grammar lab/bridge/hebmod_byid.py); files by sha256 above",
                    parts={"dataset": "make-tanakh-grammar (local): bcv-query clause tagger retrained unpointed (lab/bridge/hebmod_parts.py)",
                           "revision": "2026-10-31", "file": "heb_mod/words.parquet"})}
E = EDITIONS[ED]
SRC = E["src"]; REV = os.path.join(E["rev"], "corrections.jsonl"); WORDS = E["words"]
OUT = os.path.join(P, "hf", "alignment-reviews", "n1904", "h", "heb", ED)
APPLIED = os.path.join(E["rev"], "applied")
CLASS = {"jev-check-v1": "review-jev", "claude-review-v1": "review-claude", "published": None}
tok = lambda x: int(str(x).split(".")[0])
key = lambda x: (tok(x), int(str(x).partition(".")[2])) if "." in str(x) else (tok(x), None)


def after(r):
    """'same' = the link stands; None = not rendered; else whole tokens."""
    a = r.get("after") or {}
    if r["decided_by"] == "published" or a.get("status") == "kept" or a.get("verdict") == "right":
        return "same"
    return sorted(a["words"]) or None


def apply(data, recs):
    """Their book files with the records applied (a reader's view; the published thing is the records)."""
    out = copy.deepcopy(data); st = collections.Counter()
    for r in recs:
        cls = CLASS[r["decided_by"]]; pos = r["positions"]; e = out[pos["verse"]]; g = r["gid"]
        if cls is None:
            st["published"] += 1; continue
        old = next((L for L in e["links"] if g in L[1]), None)
        if pos["after"] == "same":
            if old is not None:
                if len(old[1]) == 1:
                    old[2] = cls
                else:
                    old[1].remove(g); e["links"].append([list(old[0]), [g], cls])
            st[f"{cls} confirmed"] += 1; continue
        before = {tok(x) for L in e["links"] for x in L[0]}
        if old is not None:
            old[1].remove(g)
            if not old[1]:
                e["links"].remove(old)
        else:
            e["none"].remove(g)
        if pos["after"]:
            e["links"].append([pos["after"], [g], cls]); st[f"{cls} {'changed' if old else 'added'}"] += 1
        else:
            e["none"].append(g); st[f"{cls} not rendered"] += 1
        now = {tok(x) for L in e["links"] for x in L[0]}
        added = [x for x in e["added"] if tok(x) not in now] + [t for t in sorted(before - now) if t not in {tok(x) for x in e["added"]}]
        e["added"] = sorted(added, key=key)
    for e in out.values():
        if isinstance(e, dict) and "none" in e:
            e["none"].sort()
    return out, st


def main():
    recs = [json.loads(l) for l in open(REV, encoding="utf-8")]
    assert not any(r["decided_by"] == "pending" for r in recs), "pending words left"
    w = pd.read_parquet(WORDS, columns=["book", "chapter", "verse", "i", "part", "class"])
    H = collections.defaultdict(set); VN = set()
    for b, c, v, i, p, cl in w.itertuples(index=False):
        H[(b, c, v)].add((int(i), int(p)))
        if cl == "verse-number":
            VN.add((b, c, v, int(i)))
    books = {os.path.basename(f)[:3]: f for f in sorted(glob.glob(os.path.join(SRC, "*.json")))}
    data = {b: json.load(open(f, encoding="utf-8")) for b, f in books.items()}
    where = {}
    for b, d in data.items():
        for cv, e in d.items():
            if ":" in cv:
                for L in e["links"]:
                    for g in L[1]:
                        where[g] = (b, cv, L[0])
                for g in e["none"]:
                    where[g] = (b, cv, None)
    by_book = collections.defaultdict(list); seen = set()
    for r in recs:
        g = r["gid"]; assert g not in seen; seen.add(g)
        b, cv, pos = where[g]
        c, v = map(int, cv.split(":")); hv = H[(b, c, v)]
        exp = sorted({k for x in pos for k in ([key(x)] if "." in str(x) else sorted(k for k in hv if k[0] == tok(x)))}) if pos else []
        assert exp == sorted(map(tuple, r["before"]["link"])), (g, "before differs from their file")
        out = dict(r); out["positions"] = {"verse": cv, "before": pos, "after": after(r)}
        by_book[b].append(out)
    # apply as a test, and check
    st = collections.Counter()
    os.makedirs(APPLIED, exist_ok=True)
    for b, f in books.items():
        res, s = apply(data[b], by_book.get(b, [])); st.update(s)
        for cv, e in res.items():
            if ":" not in cv:
                continue
            c, v = map(int, cv.split(":")); hv = H[(b, c, v)]; toks = {t for t, p in hv}
            ids = [g for L in e["links"] for g in L[1]] + e["none"]
            orig = [g for L in data[b][cv]["links"] for g in L[1]] + data[b][cv]["none"]
            assert sorted(ids) == sorted(orig) and len(set(ids)) == len(ids), (b, cv, "ids")
            for L in e["links"]:
                for x in L[0]:
                    k = key(x)
                    assert (k in hv) if k[1] is not None else (k[0] in toks and (b, c, v, k[0]) not in VN), (b, cv, x)
        json.dump(res, open(os.path.join(APPLIED, os.path.basename(f)), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    os.makedirs(OUT, exist_ok=True); man = {"books": {}}
    for b, f in books.items():
        with open(os.path.join(OUT, f"{b}.jsonl"), "w", encoding="utf-8") as fo:
            for r in by_book.get(b, []):
                fo.write(json.dumps(r, ensure_ascii=False) + "\n")
        man["books"][b] = {"source_file": os.path.basename(f), "source_sha256": hashlib.sha256(open(f, "rb").read()).hexdigest(),
                           "records": len(by_book.get(b, []))}
    back = {}
    for fn in glob.glob(os.path.join(OUT, "*.jsonl")):
        for l in open(fn, encoding="utf-8"):
            r = json.loads(l); p = r.pop("positions"); back[r["gid"]] = r
    assert len(back) == len(recs) and all(back[r["gid"]] == r for r in recs), "attestation round trip"
    th = json.load(open(os.path.join(E["rev"], "calibration.json")))["thresholds"]
    man.update(edition=ED, source=E["source"], parts=dict(E["parts"], sha256=hashlib.sha256(open(WORDS, "rb").read()).hexdigest()),
               rules="scg-review rules v2 (make-tanakh-grammar docs/scg-review-design.md)", records=len(recs),
               decided_by=dict(collections.Counter(r["decided_by"] for r in recs)), applied=dict(st),
               classes={"published": "the published link, a content word whose link agrees with the lexeme bridge; no class change",
                        "review-jev": "decided by Jev (TypeSafe), check v1, thresholds " + ", ".join(f"{k} {v}" for k, v in th.items() if v is not None),
                        "review-claude": "decided by Claude (claude-opus-5-5), review v1; precision not yet measured"},
               checks=["each record's positions.before equals the word's link in the source file",
                       "every field of each review record reads back identical",
                       "applied: every Greek id once per verse, the same ids as the source; every position in the word analysis; no verse-number token linked"])
    json.dump(man, open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: man[k] for k in ("records", "decided_by", "applied")}, ensure_ascii=False, indent=1), "->", OUT)


if __name__ == "__main__":
    main()
