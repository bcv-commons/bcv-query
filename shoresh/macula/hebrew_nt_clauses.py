"""The clause tables of a Hebrew New Testament in the clause scheme (request 41, rows 1-5), read from the Hebrew.

  cd shoresh && .venv/bin/python -I macula/hebrew_nt_clauses.py build [--books MRK]    # both editions, validated
  cd shoresh && .venv/bin/python -I macula/hebrew_nt_clauses.py compare                # the editions with each other
  cd shoresh && .venv/bin/python -I macula/hebrew_nt_clauses.py read --every 400 --dest FILE.md

What is read (all of hebrew-nt-analysis as released, v0.8; nothing of it is changed):
  words and segments   clause_tagger export (words.parquet, clauses.parquet): parts, classes, lexemes, verb forms,
                       segments with depth and parent
  the tree             hebrew_nt_layers export (pieces.parquet): head and relation per part, semantic role and
                       reference status on heads. The constituents stand on this tree, the one already published
  ten clause marks     the same export (clauses.parquet, released as clause_marks.parquet)
  features, referents  hebrew_nt_features, hebrew_nt_referents
What is new: the scheme model (clause_scheme.py scheme-train, a copy of the second tagger with further values per
segment) gives `continues`, the role of a clause's head, and the marks `transitivity`, `line_kind`, `subject_switch`;
the rules of clause_scheme.py give the constituents and the marks `kind`, `pattern`, `fronted`, `subject_form`,
`neg_scope`.

Written per edition into data/clause-scheme/nt/<edition>/: clauses, segments, constituents, added, orders,
clause_join (.parquet, the scheme's columns), VALIDATION.json (validate_scheme.py) and BUILD.json (counts).

Ids. A clause: `cl:<edition>:<BOOK>.<chapter>.<verse>.<seg>`, seg the number of its first segment in
hebrew-nt-analysis. A word: the id standard of 2026-11-23 (`scg:` / `del:` + BBCCCVVVWWW, WWW = the word's position `i`
in hebrew-nt-analysis + 1; build_text_ids.py). A part: the word id, a dot, the part's number from 1 (`part` + 1).
`first_w` / `last_w` of a segment are `i` + 1, the last three digits of the word id.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import tomllib
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from macula import clause_scheme as CS
from macula.build_text_ids import NUMBER as CS_BOOK, TEXTS, wid

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
ANALYSIS = DATA / "clause-tagger" / "export"
LAYERS = DATA / "hebrew-nt-layers" / "2026-11-26"
FEATURES = DATA / "hebrew-nt-features" / "2026-11-26c"
REFERENTS = DATA / "hebrew-nt-referents" / "2026-11-26c"
K1 = CS.K1
OUT = CS.SCHEME_OUT / "nt"
OLD_MARKS = ("force", "polarity", "mood", "time", "time_abs", "aspect", "relation", "voice", "negator", "connective")
MODEL_MARKS = ("transitivity", "line_kind", "subject_switch")       # the scheme model's; the others of the new by rule
PERSON = {"first": "1", "second": "2", "third": "3"}
NUMBER = {"singular": "sg", "plural": "pl", "dual": "du"}
GENDER = {"masculine": "m", "feminine": "f", "common": "c"}          # `both` (the form leaves it open): empty
REF_FORM = {"noun": "noun", "pron": "pronoun", "adj": "adjective", "num": "number"}


def rows_of(path, books, columns=None):
    t = pq.read_table(path, columns=columns)
    return t.filter(pc.is_in(t.column("book"), pa.array(books))).to_pylist()


def lexeme_keys():
    """Strong number -> the Tanakh build's lexeme key (the commonest lexeme of the number)"""
    best = {}
    lines = (K1 / "hbo" / "lexemes.tsv").read_text().split("\n")
    head = lines[0].split("\t")
    for line in lines[1:]:
        if line:
            r = dict(zip(head, line.split("\t")))
            if r["strong"] and int(r["count"] or 0) > best.get(r["strong"], ("", -1))[1]:
                best[r["strong"]] = (r["lexeme"], int(r["count"] or 0))
    return {k: v[0] for k, v in best.items()}


def plain_of(ed):
    return "unpointed" in json.loads((LAYERS / ed / "export.json").read_text())["model"]


def load(ed, books):
    """the edition's verses in the form clause_scheme.clauses_of_verse reads, with the released tree beside them"""
    plain = plain_of(ed)
    L = CS.layers()
    norm = L.unpointed if plain else L.pointed
    by_verse = collections.OrderedDict()
    for r in rows_of(ANALYSIS / ed / "words.parquet", books):
        if r["source"] is not None:
            by_verse.setdefault((r["book"], r["chapter"], r["verse"]), collections.OrderedDict()).setdefault(r["i"], []).append(r)
    segs = collections.defaultdict(list)
    for s in rows_of(ANALYSIS / ed / "clauses.parquet", books):
        segs[(s["book"], s["chapter"], s["verse"])].append(s)
    piece = {(r["book"], r["chapter"], r["verse"], r["i"], r["part"]): r for r in rows_of(LAYERS / ed / "pieces.parquet", books)}
    verses, trees, n = [], [], collections.Counter()
    for vk, ws in by_verse.items():
        words, flat, ipos = [], {}, {}
        for i, parts in ws.items():
            parts = sorted((p for p in parts if p["text"]), key=lambda p: p["part"])
            if not parts:
                n["words without a part"] += 1
                continue
            ipos[i] = len(words)
            for p in parts:
                flat[(i, p["part"])] = len(flat)
            words.append({"i": i, "text": norm(parts[0]["word"]) or parts[0]["word"], "shown": parts[0]["word"],
                          "form": next((p["form"] for p in parts if p["form"]), None),
                          "parts": [{"text": norm(p["text"]) or p["text"], "class": p["class"], "lexeme": p["lexeme"] or "",
                                     "part": p["part"], "shown": p["text"]} for p in parts]})
        tree = []
        for (i, part), k in flat.items():
            r = piece.get(vk + (i, part))
            if r is None:
                n["parts without a tree row"] += 1
                tree.append((0, "", None, None))
                continue
            h = flat.get((r["head_i"], r["head_part"])) if r["head_i"] is not None else None
            tree.append((0 if h is None else h + 1, r["rel"], r["head_p"], r["rel_p"]))
        sl = []
        for s in sorted(segs.get(vk, []), key=lambda s: s["seg"]):
            wis = [ipos[i] for i in range(s["first_i"], s["last_i"] + 1) if i in ipos]
            if wis:
                sl.append({"words": wis, "depth": s["depth"], "seg": s["seg"], "parent": s["parent"], "rule": s["rule"]})
        verses.append({"key": vk, "words": words, "segments": sl})
        trees.append(tree)
    return verses, trees, piece, n


def build(ed, books, out):
    plain = plain_of(ed)
    text = TEXTS[ed]
    n = collections.Counter()
    verses, trees, piece, n0 = load(ed, books)
    n.update(n0)
    L = CS.layers()
    CS.PLAIN[0] = plain
    model, bat, device, ck = L.load_model(plain)
    CS.clauses_of_verse(L, model, bat, device, verses, trees=trees)
    del model
    LEX = lexeme_keys()
    scheme = tomllib.loads((CS.SCHEME_OUT / "clause-scheme.toml").read_text())
    CLASSES = set(scheme["values"]["constituents.class"]["codes"])
    cats = tomllib.loads((K1 / "hbo" / "categories.toml").read_text())
    IN_VERB = next(v["term"] for v in cats["added"]["kind"]["values"] if v["code"] == "in_verb")
    released = {(r["book"], r["chapter"], r["verse"], r["seg"]): r for r in rows_of(LAYERS / ed / "clauses.parquet", books)}
    feat = {(r["book"], r["chapter"], r["verse"], r["i"], r["part"]): r for r in rows_of(FEATURES / ed / "features.parquet", books)}
    refs = {(r["book"], r["chapter"], r["verse"], r["i"], r["part"]): r for r in rows_of(REFERENTS / ed / "referents.parquet", books)
            if r["target"] == "verb"}
    out_c, out_s, out_k, out_a = [], [], [], []
    with_row = set()                                                 # verbs that have their unsaid subject
    word_clause, og = {}, collections.defaultdict(lambda: ([], []))
    val = lambda x: None if x in (None, "", "-", "other") else x
    for v in verses:
        b, ch, vs = v["key"]
        W = lambda wi: wid(text, b, ch, vs, v["words"][wi]["i"])
        cid_of = {}
        for c in v["out"]:
            c["id"] = f"cl:{ed}:{b}.{ch}.{vs}.{v['segments'][c['segments'][0]]['seg']}"
            for j in c["segments"]:
                cid_of[j] = c["id"]
        tree = v["tree"]
        for c in v["out"]:
            j0 = c["segments"][0]
            sg0 = v["segments"][j0]
            n["clauses"] += 1
            for wi in c["own"]:
                word_clause[(b, ch, vs, v["words"][wi]["i"])] = c["id"]
            par = None
            if sg0["parent"] not in (None, "none", "-"):
                j = j0 + int(sg0["parent"].rstrip("+"))
                if 0 <= j < len(v["segments"]) and cid_of.get(j) != c["id"]:
                    par = cid_of.get(j)
                else:
                    n["parent outside the verse or in the clause itself"] += 1
            jm = next((j for j in c["segments"] if c["pred"] is not None and c["pred"] in v["segments"][j]["words"]), j0)
            rel = released.get((b, ch, vs, v["segments"][jm]["seg"]), {})
            row = {"clause": c["id"], "edition": ed, "book": b, "chapter": ch, "verse": vs, "segments": len(c["segments"]),
                   "parent": par, "depth": sg0["depth"], "rule": val(sg0["rule"]),
                   "pattern": c["marks"].get("pattern", ("",))[0] or None,
                   "pred": W(c["pred"]) if c["pred"] is not None else None, "pred_kind": c["pred_kind"], "source_clause": None}
            for k in ("parent", "rule"):
                if row[k]:
                    row[k + "_basis"] = "model"
            if row["pattern"]:
                row["pattern_basis"] = "derived"
            row["pred_kind_basis"] = "derived"
            for k in OLD_MARKS:
                x = val(rel.get(k))
                if x is None:
                    continue
                row[k] = x.split("+") if CS.LEXEME_MARKS.get(k) == "list" else x
                row[k + "_basis"], row[k + "_p"] = "model", rel.get(k + "_p")
            for k, (x, p_, basis) in c["marks"].items():
                if k in OLD_MARKS or k == "pattern" or val(x) is None:
                    continue
                if (k in MODEL_MARKS) != (basis == "model"):
                    continue                                         # a rule's mark from the rule, a model's from the model
                row[k], row[k + "_basis"], row[k + "_p"] = x, basis, p_
            out_c.append(row)
            last = None
            for j, cont, cp in zip(c["segments"], c["continues"], c["continues_p"]):
                sg = v["segments"][j]
                r = {"clause": c["id"], "seg": sg["seg"], "book": b, "chapter": ch, "verse": vs,
                     "first_w": v["words"][sg["words"][0]]["i"] + 1, "last_w": v["words"][sg["words"][-1]]["i"] + 1,
                     "continues": last}
                if last is not None:
                    r["continues_basis"], r["continues_p"] = "model", cp
                    n["segments joined"] += 1
                last = sg["seg"]
                out_s.append(r)
            has_s = any(r["role"] == "s" for r in c["rows"])
            for o, r in enumerate(c["rows"], 1):
                hp = tree.parts[r["part"]]
                hw = v["words"][r["part"][0]]
                key = (b, ch, vs, hw["i"], hw["parts"][r["part"][1]]["part"])
                pr = piece.get(key, {}) if r["role"] != "v" else {}     # a verb's part may carry the role of its clause
                if r["basis"] == "relation":
                    rp = (hp.get("head_p") or 0) * (hp.get("rel_p") or 0)
                else:
                    rp = c["head_role"][1]
                strong = CS.strong(r["prep"]) if r["prep"] else ""
                if strong and strong not in LEX:
                    n["prepositions without a Tanakh lexeme"] += 1
                if val(r["cls"]) and r["cls"] not in CLASSES:
                    n[f"constituents of a class outside the scheme's (left empty): {r['cls']}"] += 1
                k = {"clause": c["id"], "ord": o, "role": r["role"], "role_basis": "model", "role_p": round(rp, 3) if rp is not None else None,
                     "head": W(r["head"]), "first": W(r["first"]), "last": W(r["last"]),
                     "class": r["cls"] if r["cls"] in CLASSES else None,
                     "prep": LEX.get(strong), "frame_role": None, "sem_role": val(pr.get("sem_role")),
                     "ref_status": val(pr.get("ref_status")), "ref_form": None}
                if k["sem_role"]:
                    k["sem_role_basis"], k["sem_role_p"] = "model", pr.get("sem_role_p")
                if k["ref_status"]:
                    k["ref_status_basis"], k["ref_status_p"] = "model", pr.get("ref_status_p")
                    k["ref_form"] = "suffix" if hp["kind"] == "suffix" else REF_FORM.get(hp["cls"])
                out_k.append(k)
                n["constituents"] += 1
                n[f"role {r['role']}"] += 1
            if not has_s:                                            # the subject a finite verb carries in its ending
                for r in c["rows"]:
                    if r["role"] != "v" or tree.parts[r["part"]]["vtype"] not in CS.FINITE:
                        continue
                    hw = v["words"][r["part"][0]]
                    key = (b, ch, vs, hw["i"], hw["parts"][r["part"][1]]["part"])
                    if key[:4] in with_row:
                        n["a verb word twice a predicate (one row kept)"] += 1
                        continue
                    with_row.add(key[:4])
                    f, rf = feat.get(key, {}), refs.get(key)
                    a = {"clause": c["id"], "verb": W(r["head"]), "role": "s", "frame_role": None, "kind": IN_VERB,
                         "where": "none", "form": "ending", "person": PERSON.get(f.get("person")),
                         "number": NUMBER.get(f.get("number")), "gender": GENDER.get(f.get("gender")),
                         "antecedent": None, "who": None, "who_reason": None}
                    if rf is not None:
                        if rf["antecedent_i"] is not None and rf["antecedent_verse"]:
                            ac, av = (int(x) for x in rf["antecedent_verse"].split(":"))
                            a["antecedent"] = f"{wid(text, b, ac, av, rf['antecedent_i'])}.{(rf['antecedent_part'] or 0) + 1}"
                            a["where"] = "earlier_clause" if (ac, av, rf["antecedent_i"]) < (ch, vs, hw["i"]) else "later_clause"
                        a["who_reason"] = rf["referent_basis"] or None
                        if rf["referent"] and not rf["referent"].startswith("x:"):
                            a["who"] = rf["referent"]
                            a["who_basis"] = {"linked": "linked", "speech": "derived"}.get(rf["referent_basis"], "model")
                            a["who_p"] = rf["referent_p_calibrated"]
                    else:
                        n["unsaid subjects without a referent row"] += 1
                    out_a.append(a)
        # order statements: each word against the word it depends on
        stem = {}
        for k, p_ in tree.parts.items():
            if p_["kind"] == "stem" or k[0] not in stem:
                stem[k[0]] = p_["cls"]
        for wi in range(len(v["words"])):
            outward = [k for k in tree.of_word[wi] if tree.parts[k]["head"] is not None and tree.parts[k]["head"][0] != wi]
            if not outward:
                continue
            k = next((k for k in outward if tree.parts[k]["kind"] == "stem"), outward[0])
            h = tree.parts[k]["head"][0]
            if not tree.parts[k]["rel"]:
                n["word edges without a relation (in no order row)"] += 1
                continue
            og[(tree.parts[k]["rel"] or "", stem.get(h) or "", stem.get(wi) or "")][0 if wi < h else 1].append(W(wi))
    out_o = []
    for i, key in enumerate(sorted(og), 1):
        bf, af = og[key]
        pro = bf if len(bf) >= len(af) else af
        out_o.append({"id": f"orders:{i}", "rel": key[0] or None, "head_class": key[1] or None, "dep_class": key[2] or None,
                      "before": len(bf), "after": len(af), "count": len(pro), "against": len(bf) + len(af) - len(pro),
                      "places": pro[:3]})
    # the join to the clauses carried from the Greek
    own = collections.defaultdict(set)
    for w in rows_of(K1 / ed / "words.parquet", books, ["book", "chapter", "verse", "w", "clause"]):
        if w["clause"]:
            own[w["clause"]].add((w["book"], w["chapter"], w["verse"], w["w"] - 1))
    here = collections.defaultdict(set)
    for wk, cid in word_clause.items():
        here[cid].add(wk)
    out_j = []
    for kc, ws in own.items():
        hit = collections.Counter(word_clause[w] for w in ws if w in word_clause)
        if not hit:
            n["carried clauses with no word in a clause here"] += 1
        for cid, shared in hit.items():
            kind = "same" if ws == here[cid] else "split" if here[cid] < ws else "merged" if ws < here[cid] else "partial"
            n[f"join {kind}"] += 1
            out_j.append({"carried_clause": kc, "clause": cid, "kind": kind, "shared": shared})
    folder = out / ed
    for name, rows in (("clauses", out_c), ("segments", out_s), ("constituents", out_k), ("added", out_a),
                       ("orders", out_o), ("clause_join", out_j)):
        n[name] = CS.write_scheme_table(folder, name, rows)
    from macula.validate_scheme import validate
    res = validate(CS.SCHEME_OUT / "clause-scheme.toml", folder)
    (folder / "VALIDATION.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n")
    filled = {k: sum(1 for r in out_c if r.get(k)) for k in CS.SCHEME_MARKS + ("pattern", "pred", "parent")}
    info = {"edition": ed, "books": books, "scheme": CS.SCHEME_VERSION, "model": "unpointed" if plain else "pointed",
            "validation": res["result"], "verses": len(verses),
            "constituents per clause": round(n["constituents"] / max(n["clauses"], 1), 2),
            "clauses without a constituent": sum(1 for v in verses for c in v["out"] if not c["rows"]),
            "counts": dict(n), "clauses with a value": filled}
    (folder / "BUILD.json").write_text(json.dumps(info, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(info, ensure_ascii=False, indent=1))
    if res["result"] != "PASS":
        print(json.dumps(res["fails"], ensure_ascii=False, indent=1))
    return verses


# ---------------------------------------------------------------- the editions against each other and the carried
def tables(folder):
    return {f.stem: pq.read_table(f).to_pylist() for f in sorted(Path(folder).glob("*.parquet"))}


def greek_of(ed, books):
    """word id -> the Greek word it was carried from (the Tanakh build's `from_t`), for words that alone hold it"""
    text = TEXTS[ed]
    by = collections.defaultdict(list)
    for w in rows_of(K1 / ed / "words.parquet", books, ["book", "chapter", "verse", "w", "from_t"]):
        if w["from_t"]:
            by[w["from_t"]].append(wid(text, w["book"], w["chapter"], w["verse"], w["w"] - 1))
    return {v[0]: g for g, v in by.items() if len(v) == 1}


def compare(books, out):
    eds = ("heb_scg", "heb_mod")
    T = {ed: tables(out / ed) for ed in eds}
    res = {}
    # 1. the two editions through the Greek word both words stand for
    g = {ed: greek_of(ed, books) for ed in eds}
    back = {t: w for w, t in g["heb_mod"].items()}
    pairs = {w: back[t] for w, t in g["heb_scg"].items() if t in back}
    roles = {ed: collections.defaultdict(list) for ed in eds}
    for ed in eds:
        for r in T[ed]["constituents"]:
            roles[ed][r["head"]].append(r["role"])
    c = collections.Counter()
    per = collections.defaultdict(collections.Counter)
    for a, b in pairs.items():
        ra, rb = roles["heb_scg"].get(a), roles["heb_mod"].get(b)
        c["pairs"] += 1
        if ra or rb:
            c["a head in one edition at least"] += 1
            c["a head in both"] += bool(ra and rb)
        if ra and rb:
            same = any(x in rb for x in ra)                         # a word may head two (a verb: `v`, and its clause as `o`)
            c["same role"] += same
            c["the same roles, all"] += sorted(ra) == sorted(rb)
            per[ra[0]]["both heads"] += 1
            per[ra[0]]["same role"] += same
    res["editions, constituents"] = {**c, "head in both, of heads in one": round(c["a head in both"] / max(c["a head in one edition at least"], 1), 4),
                                     "same role, of heads in both": round(c["same role"] / max(c["a head in both"], 1), 4),
                                     "per role (heb_scg's)": {k: {"both heads": v["both heads"], "same role": round(v["same role"] / v["both heads"], 4)}
                                                               for k, v in sorted(per.items(), key=lambda kv: -kv[1]["both heads"])}}
    pred = {ed: {r["pred"]: r for r in T[ed]["clauses"] if r["pred"]} for ed in eds}
    m = collections.defaultdict(collections.Counter)
    for a, b in pairs.items():
        ca, cb = pred["heb_scg"].get(a), pred["heb_mod"].get(b)
        if not (ca and cb):
            continue
        for k in CS.SCHEME_MARKS + ("pattern", "pred_kind", "depth"):
            va, vb = ca.get(k), cb.get(k)
            if va in (None, "", []) and vb in (None, "", []):
                continue
            m[k]["n"] += 1
            m[k]["same"] += va == vb
    res["editions, clauses whose predicates stand for one Greek word"] = {
        k: {"n": v["n"], "same": round(v["same"] / v["n"], 4)} for k, v in m.items()}
    # 2. against the values carried from the Greek
    for ed in eds:
        text = TEXTS[ed]
        w_of = {w["t"]: wid(text, w["book"], w["chapter"], w["verse"], w["w"] - 1)
                for w in rows_of(K1 / ed / "words.parquet", books, ["t", "book", "chapter", "verse", "w"])}
        books_of = {w["t"] for w in rows_of(K1 / ed / "words.parquet", books, ["t", "book"])}
        car = collections.defaultdict(list)
        kc = pq.read_table(K1 / ed / "constituents.parquet", columns=["head", "role", "clause"]).to_pylist()
        for r in kc:
            if r["head"] in books_of:
                car[w_of[r["head"]]].append(r["role"])
        c = collections.Counter()
        per = collections.defaultdict(collections.Counter)
        for w, rs in car.items():
            c["carried heads"] += 1
            mine = roles[ed].get(w)
            c["a head here too"] += bool(mine)
            if mine:
                same = any(x in mine for x in rs)
                c["same role"] += same
                per[rs[0]]["n"] += 1
                per[rs[0]]["same"] += same
        nclauses = len({r["clause"] for r in kc if r["head"] in books_of})
        res[f"{ed} against the carried constituents"] = {
            **c, "a head here too, share": round(c["a head here too"] / max(c["carried heads"], 1), 4),
            "same role, of those": round(c["same role"] / max(c["a head here too"], 1), 4),
            "carried constituents": sum(len(v) for v in car.values()), "constituents here": len(T[ed]["constituents"]),
            "carried clauses with a constituent": nclauses, "clauses here": len(T[ed]["clauses"]),
            "per carried role": {k: {"n": v["n"], "same": round(v["same"] / v["n"], 4)} for k, v in sorted(per.items(), key=lambda kv: -kv[1]["n"])}}
    (out / "COMPARE.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(res, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- a sheet to read
def read(books, out, every, dest):
    eds = ("heb_scg", "heb_mod")
    lines = ["# The Hebrew New Testaments in the clause scheme: a sheet to read", "",
             f"Every {every}th verse, both editions. Per clause: its id's last number, depth, pattern, its words; then the",
             "constituents (role, class, words), the marks, and an unsaid subject where there is one. `*` marks a value",
             "of the taggers with a sureness under 0.8.", ""]
    shown = {}
    for ed in eds:
        verses, _, _, _ = load(ed, books)
        T = tables(out / ed)
        text = TEXTS[ed]
        word = {}
        for v in verses:
            b, ch, vs = v["key"]
            for w in v["words"]:
                word[wid(text, b, ch, vs, w["i"])] = w["shown"]
        seg = collections.defaultdict(list)
        for r in T["segments"]:
            seg[r["clause"]].append(r)
        con = collections.defaultdict(list)
        for r in T["constituents"]:
            con[r["clause"]].append(r)
        add = collections.defaultdict(list)
        for r in T["added"]:
            add[r["clause"]].append(r)
        span = lambda a, b_: " ".join(word.get(f"{a[:-3]}{k:03d}", "") for k in range(int(a[-3:]), int(b_[-3:]) + 1)).strip()
        for r in T["clauses"]:
            if r["book"] not in books:
                continue
            vk = (r["book"], r["chapter"], r["verse"])
            base = f"{text}:{CS_BOOK[r['book']]:02d}{r['chapter']:03d}{r['verse']:03d}"
            ws = " … ".join(" ".join(word.get(f"{base}{k:03d}", "") for k in range(s["first_w"], s["last_w"] + 1)).strip()
                             for s in sorted(seg[r["clause"]], key=lambda s: s["seg"]))
            star = lambda k: "*" if r.get(k + "_p") is not None and r[k + "_p"] < 0.8 else ""
            marks = ", ".join(f"{k} {r[k] if not isinstance(r[k], list) else '+'.join(x.split(':')[2] for x in r[k])}{star(k)}"
                              for k in ("kind", "fronted", "subject_form", "transitivity", "neg_scope", "line_kind", "subject_switch",
                                        "force", "polarity", "mood", "time", "aspect", "relation", "voice", "connective")
                              if r.get(k) not in (None, "", []))
            block = [f"- **{r['clause'].rsplit('.', 1)[1]}** d{r['depth']} `{r['pattern'] or '-'}` {ws}"]
            for k in con[r["clause"]]:
                low = "*" if k["role_p"] is not None and k["role_p"] < 0.8 else ""
                extra = " ".join(x for x in (k["sem_role"], k["ref_status"]) if x)
                block.append(f"    - {k['role']}{low} [{k['class'] or ''}] {span(k['first'], k['last'])}" + (f"  ({extra})" if extra else ""))
            for a in add[r["clause"]]:
                block.append(f"    - unsaid s: {a['person'] or ''}{a['number'] or ''}{a['gender'] or ''}, antecedent "
                             f"{word.get((a['antecedent'] or '').split('.')[0], '-')}, who {a['who'] or '-'} ({a['who_reason'] or '-'})")
            block.append(f"    - {marks}")
            shown.setdefault(vk, {}).setdefault(ed, []).extend(block)
    keys = sorted(shown, key=lambda k: (CS_BOOK[k[0]], k[1], k[2]))
    for vk in keys[::every]:
        lines += [f"## {vk[0]} {vk[1]}:{vk[2]}", ""]
        for ed in eds:
            lines += [f"**{ed}**", ""] + shown[vk].get(ed, ["- (no clause)"]) + [""]
    Path(dest).write_text("\n".join(lines) + "\n")
    print(f"[hebrew_nt_clauses] {dest}: {len(keys[::every])} verses")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["build", "compare", "read"])
    ap.add_argument("--books", default="all", help="book codes with commas, or `all`")
    ap.add_argument("--skip", default="", help="read: books left out of the sheet")
    ap.add_argument("--editions", default="heb_scg,heb_mod")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--every", type=int, default=40)
    ap.add_argument("--dest", type=Path)
    a = ap.parse_args()
    books = a.books.split(",")
    if books == ["all"]:
        books = list(dict.fromkeys(pq.read_table(ANALYSIS / "heb_scg" / "words.parquet", columns=["book"]).column(0).to_pylist()))
    if a.cmd == "build":
        for ed in a.editions.split(","):
            build(ed, books, a.out)
    elif a.cmd == "compare":
        compare(books, a.out)
    else:
        read([b for b in books if b not in a.skip.split(",")], a.out, a.every, a.dest or a.out / "READ.md")


if __name__ == "__main__":
    main()
