"""Clause arguments: MACULA's verb frames, referent links and unexpressed-argument marks in one per-clause record, keyed by the
clause layouts' clause keys (development plan 2026-11-13, wave 0, step 0.2). A fact layer: MACULA (CC BY 4.0) only, no judgement.

Sources, read directly from MACULA's lowfat XML (the TSV that macula-spine.db is built from drops the Hebrew empty frames `A0:;`
and the Greek clause attribute `predication`; macula-spine.db is used only as a cross-check):
- Hebrew: macula/.lowfat-src/WLC/lowfat (Clear-Bible/macula-hebrew), word attributes `frame`, `subjref`, `participantref`;
- Greek: macula/.lowfat-src-grc (Clear-Bible/macula-greek Nestle1904/lowfat), word attributes `frame`, `subjref`, `referent`, and
  `predication` (verbless / elided) on `<wg class="cl">`;
- the clause keys: the built layouts macula/data/clause-layout (Hebrew `clause_key`) and macula/data/nt-clause-layout (Greek `clause`;
  for its 9 rows without a tree clause the row's first word, as the anchor spec says). A word belongs to the layout clause whose
  segment lists it in `words`.

Pointers. MACULA writes `A0:<id>;<id> A1:<id>`; `subjref` / `participantref` / `referent` hold ids separated by spaces (Greek
also by `;` in four cells). Ids are normalised to digits (Hebrew 12, Greek 11), as everywhere in shoresh.
- Greek `n00000000000` is the null argument: kept as the mark `-` with place `unexpressed`.
- Hebrew `A0:;` (a role with no id) is the empty frame: one row with the mark `-`, place `unexpressed`, and the clause's
  `empty_frame` flag.
- A Hebrew id whose part digit does not exist (2,389 ref pointers; MACULA's old numbering, macula-hebrew issue 13) is resolved to
  the same word: its noun / adjective / pronoun part if it has one, else its last part; such rows carry `note=part_fallback`.

Writes macula/data/clause-args/ (git-ignored): args.tsv, refs.tsv, clauses.tsv, codes.tsv, checks.md, build.json. No English content
values: codes and keys only (codes.tsv describes the codes in English).

  cd shoresh && .venv/bin/python3 -m macula.build_clause_args [--out macula/data/clause-args]
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import glob
import hashlib
import json
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
HBO_LOWFAT = HERE / ".lowfat-src" / "WLC" / "lowfat"
GRC_LOWFAT = HERE / ".lowfat-src-grc"
LAYOUT = {"hbo": HERE / "data" / "clause-layout", "grc": HERE / "data" / "nt-clause-layout"}
SPINE_DB = HERE / "macula-spine.db"
TREES_DB = HERE / "trees-macula.db"
OUT = HERE / "data" / "clause-args"
XID = "{http://www.w3.org/XML/1998/namespace}id"
NULL = "-"
REFKINDS = {"hbo": ("subjref", "participantref"), "grc": ("subjref", "referent")}
SCHEMA = 1


def _key(x: str) -> str:
    return re.sub(r"\D", "", x or "")


def _is_null(k: str) -> bool:
    return k != "" and k.strip("0") == ""


# ---------------------------------------------------------------- word types (codes)
def word_type(corpus: str, w: dict) -> str:
    c, pos, t = w.get("class"), w.get("pos"), w.get("type")
    if corpus == "hbo":
        if c == "pron" and pos == "suffix":
            return "suffix"
        if t == "demonstrative":
            return "demonstrative"
        if c == "pron" and pos == "pronoun":
            return "pronoun"
        if c == "verb" and pos == "verb":
            return "verb"
        if c == "verb":                                   # a verb-class word MACULA tags with a nominal pos (participles)
            return "verb"
    else:
        if c == "pron":
            return {"personal": "pronoun", "demonstrative": "demonstrative", "relative": "relative", "indefinite": "indefinite",
                    "interrogative": "interrogative"}.get(t or "", "pronoun")
        if c == "adj" and t == "possessive":
            return "possessive"
        if c == "det":
            return "article"
        if c == "verb":
            return "verb"
    return {"noun": "noun", "adj": "adjective", "num": "numeral", "adv": "adverb", "rel": "relative", "verb": "verb",
            "cj": "conjunction", "conj": "conjunction", "prep": "preposition", "art": "article", "ptcl": "particle",
            "ij": "interjection", "pron": "pronoun", "om": "object_marker"}.get(c or "", "other")


# ---------------------------------------------------------------- lowfat
def read_lowfat(corpus: str):
    """Words (key -> attributes, in file order), MACULA clauses (id -> info), and the sha256 of the files read."""
    files = sorted(glob.glob(str((HBO_LOWFAT if corpus == "hbo" else GRC_LOWFAT) / "*.xml")))
    if not files:
        raise SystemExit(f"no lowfat files for {corpus}")
    h = hashlib.sha256()
    words: dict[str, dict] = {}
    clauses: dict[int, dict] = {}
    nid = [0]

    def walk(el, cl):
        for ch in el:
            if ch.tag == "w":
                k = _key(ch.get(XID))
                a = {x: ch.get(x) for x in ("class", "pos", "type", "voice", "mood", "stem", "role", "frame", "subjref",
                                              "participantref", "referent", "ref")}
                a["cl"] = cl
                words[k] = a
                if cl is not None:
                    clauses[cl]["own"].append(k)
            elif ch.tag == "wg":
                if ch.get("class") == "cl":
                    nid[0] += 1
                    c = nid[0]
                    clauses[c] = {"predication": ch.get("predication"), "parent": cl, "own": [],
                                  "has_s": any(g.get("role") == "s" for g in ch)}
                    walk(ch, c)
                else:
                    walk(ch, cl)
            else:                                          # book / sentence / p / milestone wrappers
                walk(ch, cl)

    for f in files:
        h.update(Path(f).read_bytes())
        walk(ET.parse(f).getroot(), None)
    return words, clauses, h.hexdigest()


def resolve(corpus: str, k: str, words: dict, by_word: dict) -> tuple[str, str]:
    """A pointer id -> (word key, note). Hebrew ids with a missing part fall back to the same word."""
    if k in words:
        return k, ""
    if corpus == "hbo" and len(k) == 12:
        parts = by_word.get(k[:11], [])
        if parts:
            pref = [p for p in parts if words[p].get("class") in ("noun", "adj", "pron")]
            return (pref[-1] if pref else parts[-1]), "part_fallback"
    return k, "dangling"


# ---------------------------------------------------------------- layout
def read_layout(corpus: str):
    """word key -> clause key; clause key -> order index; and the layout's build.json."""
    w2c: dict[str, str] = {}
    keys: set[str] = set()
    field = "clause_key" if corpus == "hbo" else "clause"
    for f in sorted(glob.glob(str(LAYOUT[corpus] / "clauses" / "*" / "*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            ck = r.get(field) or r["first"]
            keys.add(ck)
            for w in r["words"]:
                w2c[w] = ck
    order = {k: i for i, k in enumerate(sorted(keys))}      # keys are fixed-width word ids: sorted = text order
    meta = json.loads((LAYOUT[corpus] / "build.json").read_text(encoding="utf-8"))
    return w2c, order, meta


def place(src_ck, tgt_ck, order) -> tuple[str, str]:
    if tgt_ck is None:
        return "no_clause", ""
    if src_ck is None:
        return "no_clause", ""
    if src_ck == tgt_ck:
        return "same_clause", "0"
    d = order[tgt_ck] - order[src_ck]
    dist = str(abs(d)) if src_ck[:2] == tgt_ck[:2] else ""      # within one book
    return ("earlier_clause" if d < 0 else "later_clause"), dist


# ---------------------------------------------------------------- build
def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    args_rows, ref_rows, clause_rows = [], [], []
    stats: dict = {}
    sources: dict = {}
    checks: list[str] = []
    for corpus in ("hbo", "grc"):
        words, mcl, sha = read_lowfat(corpus)
        by_word: dict[str, list] = collections.defaultdict(list)
        for k in words:
            by_word[k[:11]].append(k)
        w2c, order, lmeta = read_layout(corpus)
        S = collections.Counter()
        notes = collections.Counter()
        # ---- refs
        subj_of: dict[str, list] = collections.defaultdict(list)      # verb -> its subjref targets
        refs_from_clause = collections.Counter()
        for k, w in words.items():
            for kind in REFKINDS[corpus]:
                for raw in re.split(r"[\s;]+", w.get(kind) or ""):
                    tk = _key(raw)
                    if not tk:
                        continue
                    S[f"refs.{kind}"] += 1
                    if _is_null(tk):
                        S[f"refs.{kind}.null"] += 1
                        continue
                    tk, note = resolve(corpus, tk, words, by_word)
                    notes[f"ref.{note}"] += bool(note)
                    sc, tc = w2c.get(k), w2c.get(tk)
                    pl, dist = place(sc, tc, order)
                    st = word_type(corpus, w)
                    tt = word_type(corpus, words[tk]) if tk in words else "other"
                    ref_rows.append((corpus, k, kind, tk, st, tt, sc or "", tc or "", pl, dist, note))
                    if kind == "subjref":
                        subj_of[k].append(tk)
                    if sc:
                        refs_from_clause[sc] += 1
        # ---- frames
        per_clause: dict[str, dict] = collections.defaultdict(lambda: {"verbs": [], "present": set(), "unexpressed": set(),
                                                                         "subj": [], "empty": False, "pred": set(), "unframed": []})
        null_vm = collections.Counter()
        null_verbs = set()
        null_role_vm = collections.Counter()
        empty_verbs, empty_only = set(), set()
        empty_detail = collections.Counter()
        for k, w in words.items():
            ck = w2c.get(k)
            fr = (w.get("frame") or "").split()
            if w.get("class") == "verb" and not fr and ck:
                per_clause[ck]["unframed"].append(k)
            if not fr:
                continue
            S["frame_words"] += 1
            if ck is None:
                S["frame_words_no_layout_clause"] += 1
            pc = per_clause[ck] if ck else None
            if pc is not None:
                pc["verbs"].append(k)
                pc["subj"] += [t for t in subj_of.get(k, []) if t not in pc["subj"]]
            for tok in fr:
                role, _, rest = tok.partition(":")
                ids = [x for x in rest.split(";") if x]
                S[f"role.{role}"] += 1
                keys, places, forms, dists, rnotes = [], [], [], [], []
                if not ids:                                    # Hebrew empty frame A0:;
                    empty_verbs.add(k)
                    empty_detail[role] += 1
                    keys, places, forms, dists = [NULL], ["unexpressed"], ["empty"], [""]
                for x in ids:
                    ak = _key(x)
                    if _is_null(ak):
                        null_verbs.add(k)
                        null_role_vm[(role, w.get("voice"), w.get("mood"))] += 1
                        keys.append(NULL); places.append("unexpressed"); forms.append("null"); dists.append("")
                        continue
                    S["frame_args"] += 1
                    ak, note = resolve(corpus, ak, words, by_word)
                    if note:
                        notes[f"arg.{note}"] += 1
                        rnotes.append(note)
                    pl, dist = place(ck, w2c.get(ak), order)
                    if pl == "same_clause":
                        pl = "in_clause"
                    form = "verb_itself" if ak == k else (word_type(corpus, words[ak]) if ak in words else "other")
                    keys.append(ak); places.append(pl); forms.append(form); dists.append(dist)
                kinds = set(places)
                where = kinds.pop() if len(kinds) == 1 else "mixed"
                subj_in_verb = int(role in ("A0", "A1", "AA") and any(a in subj_of.get(k, []) for a in keys)
                                   and not any(p == "in_clause" for p in places))
                args_rows.append((corpus, ck or "", k, role, " ".join(keys), " ".join(places), " ".join(forms), " ".join(dists),
                                  where, subj_in_verb, " ".join(sorted(set(rnotes)))))
                if pc is not None:
                    if any(p != "unexpressed" for p in places):
                        pc["present"].add(role)
                    if "unexpressed" in places:
                        pc["unexpressed"].add(role)
                    if not ids:
                        pc["empty"] = True
            if fr == ["A0:;"]:
                empty_only.add(k)
            if k in null_verbs:
                null_vm[(w.get("voice"), w.get("mood"))] += 1
        # ---- predication (Greek)
        pred_assign = collections.Counter()
        for cid, c in mcl.items():
            if not c["predication"]:
                continue
            S[f"predication.{c['predication']}"] += 1
            cks = collections.Counter(w2c.get(k) for k in c["own"] if w2c.get(k))
            if not cks:
                pred_assign["no_own_words_in_layout"] += 1
                continue
            pred_assign["one_layout_clause" if len(cks) == 1 else "several_layout_clauses"] += 1
            per_clause[cks.most_common(1)[0][0]]["pred"].add(c["predication"])
        # ---- clauses
        ncl_frame = 0
        for ck in sorted(order):
            pc = per_clause.get(ck)
            if pc is None:
                pc = {"verbs": [], "present": set(), "unexpressed": set(), "subj": [], "empty": False, "pred": set(), "unframed": []}
            ncl_frame += bool(pc["verbs"])
            clause_rows.append((corpus, ck, " ".join(pc["verbs"]), " ".join(pc["unframed"]), " ".join(sorted(pc["present"])),
                                " ".join(sorted(pc["unexpressed"])), " ".join(pc["subj"]), " ".join(sorted(pc["pred"])),
                                int(pc["empty"]) if corpus == "hbo" else "", refs_from_clause.get(ck, 0)))
        stats[corpus] = {"S": S, "notes": notes, "null_vm": null_vm, "null_role_vm": null_role_vm, "null_verbs": len(null_verbs),
                         "empty_verbs": len(empty_verbs), "empty_only": len(empty_only), "empty_detail": empty_detail,
                         "pred_assign": pred_assign, "layout_clauses": len(order), "clauses_with_frame": ncl_frame,
                         "words": len(words), "words_in_layout": sum(k in w2c for k in words), "layout_words": len(w2c),
                         "mcl": mcl, "words_d": words, "w2c": w2c, "null_set": null_verbs, "empty_set": empty_only, "subj_of": subj_of}
        sources[corpus] = {"lowfat_sha256": sha, "lowfat_files": len(glob.glob(str((HBO_LOWFAT if corpus == "hbo" else GRC_LOWFAT) / "*.xml"))),
                           "layout": str(LAYOUT[corpus].relative_to(HERE.parent)), "layout_built": lmeta.get("built"),
                           "layout_segmentation": (lmeta.get("segmentation") or {}).get("version"),
                           "layout_lowfat_grc_sha256": lmeta.get("lowfat_grc_sha256")}
    # ---------------------------------------------------------------- write
    def tsv(name, header, rows):
        with open(out / name, "w", encoding="utf-8", newline="") as fh:
            wr = csv.writer(fh, delimiter="\t", lineterminator="\n")
            wr.writerow(header)
            wr.writerows(rows)

    tsv("args.tsv", ["corpus", "clause_key", "verb_key", "role", "arg_keys", "arg_places", "arg_forms", "arg_distances", "where",
                     "subject_in_verb", "note"], args_rows)
    tsv("refs.tsv", ["corpus", "src_key", "kind", "tgt_key", "src_type", "tgt_type", "src_clause", "tgt_clause", "position",
                     "distance", "note"], ref_rows)
    tsv("clauses.tsv", ["corpus", "clause_key", "verbs", "verbs_no_frame", "roles_present", "roles_unexpressed", "subject_ref",
                        "predication", "empty_frame", "refs_from"], clause_rows)
    write_codes(out)
    write_checks(out, stats, args_rows, ref_rows)
    git = _git_commit(HERE / ".lowfat-src")
    build_json = {
        "dataset": "clause-args", "schema": SCHEMA, "built": datetime.date.today().isoformat(),
        "code": {"file": "shoresh/macula/build_clause_args.py", "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        "licence": "CC BY 4.0 (MACULA Hebrew and Greek, Clear Bible); layout keys from bcv-commons clause layouts",
        "sources": {
            "macula_hebrew": {"repository": "https://github.com/Clear-Bible/macula-hebrew", "path": "WLC/lowfat", "commit": git,
                              "lowfat_sha256": sources["hbo"]["lowfat_sha256"], "files": sources["hbo"]["lowfat_files"]},
            "macula_greek": {"repository": "https://github.com/Clear-Bible/macula-greek", "path": "Nestle1904/lowfat",
                             "commit": None, "commit_note": "downloaded file by file on 2026-10-08 (build_trees); no commit recorded",
                             "lowfat_sha256": sources["grc"]["lowfat_sha256"], "files": sources["grc"]["lowfat_files"],
                             "same_as_nt_layout_build": sources["grc"]["lowfat_sha256"] == sources["grc"]["layout_lowfat_grc_sha256"]},
            "hebrew_layout": {k: sources["hbo"][k] for k in ("layout", "layout_built", "layout_segmentation")},
            "greek_layout": {k: sources["grc"][k] for k in ("layout", "layout_built")},
            "cross_check": {"macula-spine.db": _db_meta(SPINE_DB), "trees-macula.db": _db_meta(TREES_DB)},
        },
        "rows": {"args": len(args_rows), "refs": len(ref_rows), "clauses": len(clause_rows)},
    }
    (out / "build.json").write_text(json.dumps(build_json, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(build_json["rows"]))


def _git_commit(repo: Path):
    try:
        import subprocess
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None


def _db_meta(p: Path) -> dict:
    con = sqlite3.connect(p)
    try:
        meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.Error:
        meta = {"note": "no meta table"}
    con.close()
    return meta


CODES = [
    ("corpus", "hbo", "Hebrew Bible (WLC, MACULA Hebrew); Aramaic words included"),
    ("corpus", "grc", "Greek New Testament (Nestle 1904, MACULA Greek)"),
    ("role", "A0", "MACULA frame role: argument with features of a prototypical agent"),
    ("role", "A1", "MACULA frame role: argument with features of a prototypical patient"),
    ("role", "A2", "MACULA frame role: prototypical recipient (third argument; documented in macula-greek issue 2, not in the PDFs)"),
    ("role", "AA", "MACULA frame role (Hebrew): agent of an induced action, the causer who makes A0 act (Hiphil causer)"),
    ("role", "AA2", "MACULA frame role (Greek, 90 cases): undocumented; MACULA's own issue 30 asks whether it means A2"),
    ("arg_keys", "-", "no argument id: Greek null id n00000000000, or a Hebrew role with no id (A0:;)"),
    ("arg_places", "in_clause", "the argument word is in the verb's layout clause"),
    ("arg_places", "earlier_clause", "the argument word is in an earlier layout clause"),
    ("arg_places", "later_clause", "the argument word is in a later layout clause"),
    ("arg_places", "no_clause", "the argument word is in no layout clause (not expected)"),
    ("arg_places", "unexpressed", "MACULA marks the role but names no word (null id or empty role)"),
    ("arg_forms", "null", "Greek null argument id n00000000000"),
    ("arg_forms", "empty", "Hebrew role with no id (A0:;)"),
    ("arg_forms", "verb_itself", "the argument id is the verb's own id"),
    ("where", "mixed", "the role's several arguments have different places"),
    ("subject_in_verb", "1", "the argument is outside the clause and is also the verb's subjref target: the clause expresses it only "
                             "in the verb's inflection"),
    ("position", "same_clause", "source and target of a referent link are in the same layout clause"),
    ("position", "earlier_clause", "the target is in an earlier layout clause (anaphora)"),
    ("position", "later_clause", "the target is in a later layout clause (cataphora)"),
    ("position", "no_clause", "source or target is in no layout clause"),
    ("distance", "", "number of layout clauses between source and target in text order (0 = same clause); empty across books"),
    ("kind", "subjref", "MACULA subjref: the implied subject of a verb, pointing at a word naming it"),
    ("kind", "participantref", "MACULA Hebrew participantref (documented as Ref): the nearest nominal antecedent of a pronoun or suffix"),
    ("kind", "referent", "MACULA Greek referent (Ref in the full trees): the antecedent of a pronoun, article, adjective or adverb"),
    ("src_type/tgt_type/arg_forms", "suffix", "Hebrew pronominal suffix"),
    ("src_type/tgt_type/arg_forms", "pronoun", "independent personal pronoun (Greek pronoun without type also)"),
    ("src_type/tgt_type/arg_forms", "demonstrative", "demonstrative pronoun"),
    ("src_type/tgt_type/arg_forms", "relative", "relative pronoun or particle"),
    ("src_type/tgt_type/arg_forms", "indefinite", "Greek indefinite pronoun"),
    ("src_type/tgt_type/arg_forms", "interrogative", "Greek interrogative pronoun"),
    ("src_type/tgt_type/arg_forms", "possessive", "Greek possessive adjective"),
    ("src_type/tgt_type/arg_forms", "article", "Greek article (determiner)"),
    ("src_type/tgt_type/arg_forms", "verb", "verb (finite, infinitive or participle)"),
    ("src_type/tgt_type/arg_forms", "noun", "noun (common or proper)"),
    ("src_type/tgt_type/arg_forms", "adjective", "adjective"),
    ("src_type/tgt_type/arg_forms", "numeral", "numeral"),
    ("src_type/tgt_type/arg_forms", "adverb", "adverb"),
    ("src_type/tgt_type/arg_forms", "other", "any other word class"),
    ("predication", "verbless", "MACULA Greek clause with no verb: identification or attribution without a copula (ClType Verbless)"),
    ("predication", "elided", "MACULA Greek clause whose verb is understood from another clause (ClType VerbElided)"),
    ("empty_frame", "1", "a Hebrew verb of the clause has a role with no id (A0:;)"),
    ("note", "part_fallback", "Hebrew pointer to a part number that does not exist; resolved to the same word's noun/adj/pron part, "
                              "else its last part"),
    ("note", "dangling", "pointer to an id that does not exist and could not be resolved"),
]


def write_codes(out: Path) -> None:
    with open(out / "codes.tsv", "w", encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh, delimiter="\t", lineterminator="\n")
        wr.writerow(["column", "code", "description"])
        wr.writerows(CODES)


def _pct(a, b):
    return f"{a:,} / {b:,} ({100 * a / b:.1f} %)" if b else f"{a:,} / 0"


def write_checks(out: Path, stats: dict, args_rows, ref_rows) -> None:
    L = ["# clause-args: checks", "", f"Built {datetime.date.today().isoformat()} by shoresh/macula/build_clause_args.py.", ""]
    con = sqlite3.connect(SPINE_DB)
    for corpus in ("hbo", "grc"):
        st = stats[corpus]
        S = st["S"]
        A = [r for r in args_rows if r[0] == corpus]
        R = [r for r in ref_rows if r[0] == corpus]
        L += [f"## {corpus}", "", "### Counts", ""]
        L.append(f"- lowfat words {st['words']:,}; in a layout clause {_pct(st['words_in_layout'], st['words'])}")
        L.append(f"- layout clauses {st['layout_clauses']:,}; with at least one framed verb {_pct(st['clauses_with_frame'], st['layout_clauses'])}")
        L.append(f"- framed verbs {S['frame_words']:,}; in no layout clause {S['frame_words_no_layout_clause']}")
        L.append(f"- (verb, role) rows {len(A):,}; roles: " + ", ".join(f"{k[5:]} {v:,}" for k, v in sorted(S.items()) if k.startswith("role.")))
        L.append(f"- frame argument ids (non-null) {S['frame_args']:,}")
        wh = collections.Counter(r[8] for r in A)
        L.append("- where (per verb-role row): " + ", ".join(f"{k} {v:,}" for k, v in wh.most_common()))
        pl = collections.Counter(p for r in A for p in r[5].split())
        L.append("- argument places (per argument): " + ", ".join(f"{k} {v:,}" for k, v in pl.most_common()))
        fo = collections.Counter(f for r in A for f in r[6].split())
        L.append("- argument forms: " + ", ".join(f"{k} {v:,}" for k, v in fo.most_common()))
        L.append(f"- subject_in_verb = 1: {sum(r[9] for r in A):,}")
        L.append("- referent links: " + ", ".join(f"{k[5:]} {v:,}" for k, v in sorted(S.items()) if k.startswith("refs.")))
        L.append("- pointer notes: " + (", ".join(f"{k} {v:,}" for k, v in st["notes"].items() if v) or "none"))
        L += ["", "### Join with the layout", ""]
        L.append(f"- frame rows whose verb is in a layout clause: {_pct(sum(bool(r[1]) for r in A), len(A))}")
        nn = [p for r in A for p in r[5].split() if p != "unexpressed"]
        L.append(f"- frame arguments in a layout clause: {_pct(sum(p != 'no_clause' for p in nn), len(nn))}")
        L.append(f"- referent links with both ends in a layout clause: {_pct(sum(r[8] != 'no_clause' for r in R), len(R))}")
        pos = collections.Counter(r[8] for r in R)
        L.append("- referent link positions: " + ", ".join(f"{k} {v:,}" for k, v in pos.most_common()))
        for kind in REFKINDS[corpus]:
            d = [int(r[9]) for r in R if r[2] == kind and r[9] not in ("",)]
            if d:
                d.sort()
                L.append(f"- {kind} distance in clauses: median {d[len(d) // 2]}, 90th percentile {d[int(len(d) * .9)]}, max {d[-1]}")
        # cross-check against macula-spine.db (built from MACULA's TSV)
        lang_pref = "4" if corpus == "grc" else None
        db_frames = {(v, r, a) for v, r, a in con.execute("SELECT verb_key, role, arg_key FROM frames")
                     if (len(v) == 11) == (corpus == "grc")}
        mine = set()
        for r in A:
            for a in r[4].split():
                mine.add((r[2], r[3], "00000000000" if (a == NULL and corpus == "grc") else a))
        mine = {m for m in mine if m[2] != NULL}
        L.append(f"- macula-spine.db frames ({corpus}): {len(db_frames):,} distinct rows; in this build {_pct(len(db_frames & mine), len(db_frames))}; "
                 f"this build's not in the db {len(mine - db_frames):,} (Hebrew part fallbacks and TSV/lowfat version differences)")
        db_refs = collections.Counter(k for s, t, k in con.execute("SELECT src_key, tgt_key, kind FROM refs") if (len(s) == 11) == (corpus == "grc"))
        L.append("- macula-spine.db refs: " + ", ".join(f"{k} {v:,}" for k, v in db_refs.items()))
        L += ["", "### Word types of referent links", ""]
        tt = collections.Counter((r[2], r[4], r[5]) for r in R)
        L += ["| kind | source type | target type | links |", "|---|---|---|---|"]
        L += [f"| {k} | {s} | {t} | {n:,} |" for (k, s, t), n in tt.most_common(25)]
        nn_links = sum(n for (k, s, t), n in tt.items() if s == "noun" and t == "noun")
        L += ["", f"Noun-to-noun links (source and target both nouns): {nn_links:,} of {len(R):,}; "
              f"source a noun at all: {sum(n for (k, s, t), n in tt.items() if s == 'noun'):,}.", ""]
        words, mcl, w2c = st["words_d"], st["mcl"], st["w2c"]
        if corpus == "grc":
            L += ["### Greek null arguments (n00000000000)", ""]
            L.append(f"- verbs with a null argument: {st['null_verbs']:,}; null role instances: {sum(st['null_role_vm'].values()):,}")
            L += ["", "| role | voice | mood | instances |", "|---|---|---|---|"]
            L += [f"| {r} | {v} | {m} | {n:,} |" for (r, v, m), n in st["null_role_vm"].most_common()]
            L += ["", "Per verb (voice, mood): " + ", ".join(f"{v}/{m} {n:,}" for (v, m), n in st["null_vm"].most_common()), ""]
            nv = st["null_set"]
            has_subj = sum(bool(st["subj_of"].get(k)) for k in nv)
            has_s = sum(bool(words[k]["cl"] and mcl[words[k]["cl"]]["has_s"]) for k in nv)
            L.append(f"- of these verbs: with a subjref {has_subj:,}; whose MACULA clause has an explicit subject (role s) {has_s:,}")
            a0n = [r for r in A if r[3] == "A0" and NULL in r[4].split()]
            a0n_s = sum(bool(words[r[2]]["cl"] and mcl[words[r[2]]["cl"]]["has_s"]) for r in a0n)
            L.append(f"- null A0 rows {len(a0n):,}; clause has an explicit subject {a0n_s:,}")
            L += ["", "### Greek predication", ""]
            L.append("- " + ", ".join(f"{k[12:]} {v:,}" for k, v in S.items() if k.startswith("predication.")))
            L.append("- assigned to layout clauses: " + ", ".join(f"{k} {v:,}" for k, v in st["pred_assign"].items()))
            L.append("")
        else:
            L += ["### Hebrew empty frames (A0:;)", ""]
            L.append(f"- verbs with any role without an id: {st['empty_verbs']:,} (roles: "
                     + ", ".join(f"{k} {v:,}" for k, v in st["empty_detail"].items()) + f"); frame exactly `A0:;`: {st['empty_only']:,}")
            ev = st["empty_set"]
            L.append(f"- of the `A0:;`-only verbs: with a subjref {sum(bool(st['subj_of'].get(k)) for k in ev):,}; "
                     f"whose MACULA clause has an explicit subject (role s) {sum(bool(words[k]['cl'] and mcl[words[k]['cl']]['has_s']) for k in ev):,}")
            fs = collections.Counter((words[k].get("stem"), words[k].get("type")) for k in ev)
            L.append("- stem / form: " + ", ".join(f"{s}/{t} {n:,}" for (s, t), n in fs.most_common(12)))
            L.append("")
    con.close()
    (out / "checks.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    build(a.out)


if __name__ == "__main__":
    main()
