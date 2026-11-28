"""Build the verb frame table: which of MACULA's frame labels the subject and the object of a Hebrew verb carry.

MACULA Hebrew gives a verb's arguments frame labels (A0, A1, AA, A2); the clause scheme carries them as `frame_role` on
the Tanakh's constituents and unsaid subjects. The Hebrew New Testaments have no such labels, and the stem alone does
not give them (a niphal's subject is A1 for one verb and A0 for another). This build counts the Tanakh's labels per verb
and per stem, so that a label elsewhere is looked up from MACULA's own practice and left open where the Tanakh does not
settle it. No model, no English: the verb's lexeme and stem are MACULA's, the roles and labels the clause scheme's.

Reads the Tanakh in the clause scheme (macula/data/clause-scheme/tanakh, the tables of bcv-commons/tanakh-clause-scheme)
and MACULA's Hebrew words (macula-spine.db: lexeme, lemma, stem). Hebrew only.

Rows (frames.parquet), one per step, key and role (see frame_labels_lookup.py for the order they are read in):
  step      verb | verb+object | stem+object | lexeme
  lexeme    `hbo:` + MACULA's Strong's key ("" on a stem row);  lemma  MACULA's lemma (the commonest spelling)
  stem      MACULA's stem name ("" on a lexeme row: all the lexeme's stems together, for a word whose stem is not known)
  role      s (the subject, said or unsaid) | o (an object)
  object    "" | with | without: whether the clause has an object (role s only)
  n, n_A0, n_A1, n_AA, n_A2   places in the Tanakh with a label, and per label
  label, share   the commonest label and its share of n
  settled   n and share reach the step's thresholds

Writes macula/data/frame-labels/: frames.parquet, ACCOUNT.json (counts, thresholds, the cross-check: each tenth of the
Tanakh's chapters looked up in a table built from the other nine), report.md.

    cd shoresh && .venv/bin/python3 -m macula.build_frame_labels [--out DIR]
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import zlib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from macula.frame_labels_lookup import Frames

HERE = Path(__file__).resolve().parent
SPINE = HERE / "macula-spine.db"
TANAKH = HERE / "data" / "clause-scheme" / "tanakh"
NT = HERE / "data" / "clause-scheme" / "nt"
OUT = HERE / "data" / "frame-labels"
LABELS = ("A0", "A1", "AA", "A2")
# a row is settled from this many places and this share of one label
MIN_N = {"verb": 5, "verb+object": 5, "stem+object": 100, "lexeme": 5}
MIN_SHARE = {"verb": 0.90, "verb+object": 0.90, "stem+object": 0.97, "lexeme": 0.95}
FOLDS = 10


def verbs():
    """Hebrew verbs of the Tanakh: local word id -> (lexeme, stem), and lexeme -> lemma"""
    con = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    out, lemmas = {}, collections.defaultdict(collections.Counter)
    for key, strong, stem, lemma in con.execute(
            "select key, strong, stem, lemma from macula_words where lang='hbo' and class='verb' and wlang='H'"):
        if strong and stem and not stem.startswith("unknown"):
            out["o" + key[:11]] = out["wlc:" + key[:11]] = (f"hbo:{strong}", stem)   # the build's id and the release's
            lemmas[f"hbo:{strong}"][lemma] += 1
    con.close()
    return out, {k: max(c.items(), key=lambda kv: (any("ְ" <= ch <= "ׇ" for ch in kv[0]), kv[1]))[0] for k, c in lemmas.items()}


def places(src: Path = TANAKH):
    """(fold, lexeme, stem, role, the clause has an object, label) for every labelled subject and object of a verb"""
    verb, lemma = verbs()
    cl = {r["clause"]: r for r in pq.read_table(src / "clauses.parquet", columns=["clause", "book", "chapter", "pred"]).to_pylist()}
    cons = pq.read_table(src / "constituents.parquet", columns=["clause", "role", "frame_role"]).to_pylist()
    has_o = {r["clause"] for r in cons if r["role"] in ("o", "o2")}
    fold = lambda c: zlib.crc32(f"{c['book']}.{c['chapter']}".encode()) % FOLDS
    out, unlabelled = [], collections.Counter()
    for r in cons:
        c = cl[r["clause"]]
        if r["role"] not in ("s", "o", "o2") or c["pred"] not in verb:
            continue
        role = "s" if r["role"] == "s" else "o"
        if r["frame_role"] not in LABELS:
            unlabelled[role] += 1
            continue
        out.append((fold(c), *verb[c["pred"]], role, r["clause"] in has_o, r["frame_role"]))
    for r in pq.read_table(src / "added.parquet", columns=["clause", "verb", "role", "frame_role"]).to_pylist():
        if r["role"] == "s" and r["verb"] in verb and r["clause"] in cl and r["frame_role"] in LABELS:
            out.append((fold(cl[r["clause"]]), *verb[r["verb"]], "s", r["clause"] in has_o, r["frame_role"]))
    return out, lemma, dict(unlabelled)


def table(rows, lemma) -> list[dict]:
    count = collections.defaultdict(collections.Counter)
    for _, lex, stem, role, obj, label in rows:
        o = ("with" if obj else "without") if role == "s" else ""
        count[("verb", lex, stem, role, "")][label] += 1
        if role == "s":
            count[("verb+object", lex, stem, role, o)][label] += 1
        count[("stem+object", "", stem, role, o)][label] += 1
        count[("lexeme", lex, "", role, "")][label] += 1
    out = []
    for (step, lex, stem, role, o), c in sorted(count.items()):
        n = sum(c.values())
        label, k = max(c.items(), key=lambda kv: (kv[1], kv[0]))
        out.append({"step": step, "lexeme": lex, "lemma": lemma.get(lex, ""), "stem": stem, "role": role, "object": o, "n": n,
                    **{f"n_{x}": c.get(x, 0) for x in LABELS}, "label": label, "share": round(k / n, 4),
                    "settled": n >= MIN_N[step] and k / n >= MIN_SHARE[step]})
    return out


def cross_check(rows, lemma) -> dict:
    """each tenth of the chapters looked up in a table of the other nine: per role, step and stem, how many and how many right"""
    res = collections.defaultdict(lambda: [0, 0])
    for f in range(FOLDS):
        F = Frames(table([r for r in rows if r[0] != f], lemma))
        for _, lex, stem, role, obj, label in (r for r in rows if r[0] == f):
            blind, how, _ = F.label(lex, "", role, obj)                # the same place with its stem not known
            for key in ((role, "stem hidden: " + ("lexeme" if blind else "open"), "all"), (role, "stem hidden: " + ("lexeme" if blind else "open"), stem)):
                res[key][0] += 1
                res[key][1] += blind == label if blind else 0
            got, step, _ = F.label(lex, stem, role, obj)
            for key in ((role, step, "all"), (role, step, stem), (role, "any step" if got else "open", "all"), (role, "any step" if got else "open", stem),
                        (role, "the stem's commonest label", stem), (role, "the stem's commonest label", "all")):
                if key[1] == "the stem's commonest label":
                    base = F.row.get(("stem+object", "", stem, role, "")) if role == "o" else None
                    if role == "s":                                   # without the object: the two stem rows together
                        c = collections.Counter()
                        for o in ("with", "without"):
                            r = F.row.get(("stem+object", "", stem, "s", o))
                            for x in LABELS:
                                c[x] += r[f"n_{x}"] if r else 0
                        top = max(c.items(), key=lambda kv: kv[1])[0] if sum(c.values()) else None
                    else:
                        top = base["label"] if base else None
                    res[key][0] += 1
                    res[key][1] += top == label
                    continue
                res[key][0] += 1
                res[key][1] += got == label if got else 0
    return {f"{role}|{step}|{stem}": {"places": n, "right": ok} for (role, step, stem), (n, ok) in sorted(res.items())}


def nt_coverage(F: Frames) -> dict:
    """how many subjects and objects of the Hebrew New Testaments' clause scheme the table settles, and why not the others"""
    from macula.build_text_ids import wid
    out = {}
    for ed, text in (("heb_scg", "scg"), ("heb_mod", "del")):
        d = NT / ed
        words = HERE / "data" / "clause-tagger" / "export" / ed / "words.parquet"
        feats = HERE / "data" / "hebrew-nt-features" / "2026-11-26c" / ed / "features.parquet"
        if not (d / "clauses.parquet").exists() or not words.exists() or not feats.exists():
            continue
        stem = {(r["book"], r["chapter"], r["verse"], r["i"], r["part"]): r["stem"]
                for r in pq.read_table(feats, columns=["book", "chapter", "verse", "i", "part", "stem"]).to_pylist()}
        V = {wid(text, r["book"], r["chapter"], r["verse"], r["i"]): (r["lexeme"] or "", stem.get((r["book"], r["chapter"], r["verse"], r["i"], r["part"])) or "", r["lemma"])
             for r in pq.read_table(words, columns=["book", "chapter", "verse", "i", "part", "class", "lemma", "lexeme"]).to_pylist() if r["class"] == "verb"}
        pred = {r["clause"]: r["pred"] for r in pq.read_table(d / "clauses.parquet", columns=["clause", "pred"]).to_pylist()}
        cons = pq.read_table(d / "constituents.parquet", columns=["clause", "role"]).to_pylist()
        has_o = {r["clause"] for r in cons if r["role"] in ("o", "o2")}
        todo = [(pred[r["clause"]], r["clause"], "s" if r["role"] == "s" else "o") for r in cons if r["role"] in ("s", "o", "o2") and pred[r["clause"]] in V]
        todo += [(r["verb"], r["clause"], "s") for r in pq.read_table(d / "added.parquet", columns=["verb", "clause"]).to_pylist() if r["verb"] in V]
        how, by_stem, open_verbs = collections.Counter(), collections.Counter(), collections.Counter()
        for v, c, role in todo:
            lex, st, lemma = V[v]
            got, step, _ = F.label(lex, st, role, c in has_o)
            if got is None and st and not lex:
                step = "open: a verb the Tanakh does not have"
            how[(role, step)] += 1
            if got is None:
                by_stem[(role, st or "no stem")] += 1
                if st:
                    open_verbs[(lex or lemma, st)] += 1
        n = collections.Counter(role for _, _, role in todo)
        out[ed] = {"subjects": n["s"], "objects": n["o"],
                   "by_step": {f"{role}|{step}": k for (role, step), k in sorted(how.items(), key=lambda kv: -kv[1])},
                   "open_by_stem": {f"{role}|{st}": k for (role, st), k in sorted(by_stem.items(), key=lambda kv: -kv[1])},
                   "open_verbs_with_a_stem": len(open_verbs), "open_places_with_a_stem": sum(open_verbs.values())}
    return out


def main_into(out: Path, rows, lemma, unlabelled, tab) -> list[str]:
    """write the table, its account and its report into `out`"""
    cc = cross_check(rows, lemma)
    F = Frames(tab)
    out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(tab), out / "frames.parquet", compression="zstd")
    by = collections.Counter((r["step"], r["role"], r["settled"]) for r in tab)
    account = {
        "places": {"subjects": sum(1 for r in rows if r[3] == "s"), "objects": sum(1 for r in rows if r[3] == "o"),
                   "without_a_label_left_out": unlabelled},
        "labels": {role: dict(collections.Counter(r[5] for r in rows if r[3] == role).most_common()) for role in ("s", "o")},
        "thresholds": {"min_places": MIN_N, "min_share": MIN_SHARE},
        "rows": {f"{step}|{role}": {"rows": by[(step, role, True)] + by[(step, role, False)], "settled": by[(step, role, True)]}
                 for step in ("verb", "verb+object", "stem+object", "lexeme") for role in ("s", "o") if by[(step, role, True)] + by[(step, role, False)]},
        "stem_rows": [{k: r[k] for k in ("stem", "role", "object", "n", "label", "share", "settled")} for r in tab if r["step"] == "stem+object" and r["n"] >= 20],
        "cross_check": {"folds": FOLDS, "split": "crc32 of book.chapter, modulo 10", "figures": cc},
        "new_testament": nt_coverage(F),
    }
    (out / "ACCOUNT.json").write_text(json.dumps(account, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def pct(key):
        x = cc.get(key)
        return f"{x['right'] / x['places']:.1%} of {x['places']:,}" if x and x["places"] else "-"

    lines = ["# Verb frame table", "", f"Places with a label: subjects {account['places']['subjects']:,}, objects {account['places']['objects']:,}.", "",
             "## Cross-check (each tenth of the chapters against a table of the other nine)", "",
             "| role | stem | the stem's commonest label | settled by a step | right where settled | open |", "|---|---|---|---|---|---|"]
    for role in ("s", "o"):
        stems = sorted({k.split("|")[2] for k in cc if k.startswith(role + "|")}, key=lambda s: -(cc.get(f"{role}|the stem's commonest label|{s}", {"places": 0})["places"]))
        for st in stems[:9]:
            tot = cc[f"{role}|the stem's commonest label|{st}"]["places"]
            got = cc.get(f"{role}|any step|{st}", {"places": 0, "right": 0})
            lines.append(f"| {role} | {st} | {pct(f'{role}|the stem' + chr(39) + f's commonest label|{st}')} | {got['places'] / tot:.1%} | "
                         f"{(got['right'] / got['places'] if got['places'] else 0):.1%} | {cc.get(f'{role}|open|{st}', {'places': 0})['places'] / tot:.1%} |")
    lines += ["", "## Per step", ""] + [f"- {k}: {pct(k)}" for k in cc if k.endswith("|all")]
    lines += ["", "## Stem rows (20 places and more)", ""] + [f"- {r['stem']} {r['role']} {r['object'] or '-'}: {r['label']} {r['share']:.1%} of {r['n']:,}{'' if r['settled'] else ' (not settled)'}" for r in account["stem_rows"]]
    for ed, x in account["new_testament"].items():
        lines += ["", f"## {ed}: subjects {x['subjects']:,}, objects {x['objects']:,}", ""] + [f"- {k}: {v:,}" for k, v in x["by_step"].items()]
        lines += [f"- open with a stem: {x['open_places_with_a_stem']:,} places in {x['open_verbs_with_a_stem']:,} verbs", "- open by stem: " + ", ".join(f"{k} {v:,}" for k, v in list(x["open_by_stem"].items())[:12])]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    rows, lemma, unlabelled = places()
    lines = main_into(a.out, rows, lemma, unlabelled, table(rows, lemma))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
