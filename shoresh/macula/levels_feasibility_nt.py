"""Stage 40, item 5: what each Hebrew New Testament edition carries in build i1, and where the two choose different
lexemes for the same Greek word.

  shoresh/.venv/bin/python -I shoresh/macula/levels_feasibility_nt.py -> stdout, levels/nt-counts.json
"""
import json
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from levels_feasibility_common import BUILD, dump, is_content, table  # noqa: E402

import pyarrow.parquet as pq  # noqa: E402

NT = ("heb_mod", "heb_scg")


def has_points(s):
    return any(0x05B0 <= ord(c) <= 0x05C7 and unicodedata.combining(c) for c in unicodedata.normalize("NFD", s or ""))


def main():
    out = {}
    greek_choice = {}
    for e in NT:
        c = {}
        ow = pq.read_table(BUILD / "other" / e / "words.parquet", columns=["text", "analysis_basis"]).to_pydict()
        op = pq.read_table(BUILD / "other" / e / "parts.parquet", columns=["basis", "key_rule", "lexeme"]).to_pydict()
        c["source_words"] = len(ow["text"])
        c["source_words_with_points"] = sum(1 for t in ow["text"] if has_points(t))
        c["analysis_basis"] = {str(k): v for k, v in Counter(ow["analysis_basis"]).items()}
        c["parts"] = len(op["basis"])
        c["parts_basis"] = dict(Counter(op["basis"]))
        c["parts_key_rule"] = dict(Counter(op["key_rule"]))
        c["parts_ntx_or_empty_lexeme"] = sum(1 for l in op["lexeme"] if not l or l.startswith("lex:ntx"))
        w = table(e, "words", ("t", "clause", "clause_basis", "head_basis", "from_t"))
        c["words"] = len(w["t"])
        c["words_clause_basis"] = dict(Counter(w["clause_basis"]))
        c["words_head_basis"] = dict(Counter(w["head_basis"]))
        c["words_one_to_one_greek"] = sum(1 for x in w["from_t"] if x is not None)
        c["clauses"] = len(table(e, "clauses", ("clause",))["clause"])
        c["constituents"] = len(table(e, "constituents", ("clause",))["clause"])
        c["added"] = len(table(e, "added", ("clause",))["clause"])
        wa = table(e, "who_account", ("state", "basis"))
        c["who_account"] = dict(Counter(zip(wa["state"], wa["basis"])).most_common())
        c["who_account"] = {f"{a}/{b}": n for (a, b), n in c["who_account"].items()}
        p = table(e, "pieces", ("t", "n", "kind", "class", "lexeme", "basis", "who", "who_basis"))
        c["pieces_basis"] = dict(Counter(p["basis"]))
        c["pieces_with_who"] = dict(Counter(b for w_, b in zip(p["who"], p["who_basis"]) if w_))
        l = table(e, "links", ("t", "n", "s", "basis"))
        c["links"] = dict(Counter(l["basis"]))
        c["links_hebrew_words"] = len(set(l["t"]))
        # per Greek word: the edition's content lexemes on the Hebrew words linked to it
        lex_of = {(t, n): (lx, cl, b) for t, n, k, cl, lx, b in zip(p["t"], p["n"], p["kind"], p["class"],
                                                                    p["lexeme"], p["basis"])}
        per = defaultdict(set)
        per_basis = defaultdict(set)
        for t, n, s, b in zip(l["t"], l["n"], l["s"], l["basis"]):
            if b != "linked":       # strict links only; the model links of heb_scg carry nothing (SPEC 4.15)
                continue
            lx, cl, pb = lex_of.get((t, n), ("", "", ""))
            if lx and is_content(lx, cl):
                per[s].add(lx)
                per_basis[s].add(pb)
        greek_choice[e] = (per, per_basis)
        fo = table(e, "forms", ("lexeme",))
        c["forms_rows"] = len(fo["lexeme"])
        c["paradigms_rows"] = len(table(e, "paradigms", ("id",))["id"])
        out[e] = c
        print(e, json.dumps(c, ensure_ascii=False))
    (pm, bm), (ps, bs) = greek_choice["heb_mod"], greek_choice["heb_scg"]
    both = set(pm) & set(ps)
    st = Counter()
    st_derived = Counter()
    for s in both:
        a, b = pm[s], ps[s]
        k = "same" if a == b else ("overlap" if a & b else "disjoint")
        st[k] += 1
        if bm[s] == {"derived"} and bs[s] == {"derived"}:
            st_derived[k] += 1
    out["greek_words_content_linked"] = {"heb_mod": len(pm), "heb_scg": len(ps), "both": len(both),
                                         "choice": dict(st), "choice_both_derived": dict(st_derived)}
    d = table("heb_mod", "differ", ("state", "basis"))
    out["differ_heb_mod"] = {f"{a}/{b}": n for (a, b), n in Counter(zip(d["state"], d["basis"])).items()}
    print(json.dumps({k: out[k] for k in ("greek_words_content_linked", "differ_heb_mod")}, ensure_ascii=False))
    dump("nt-counts.json", out)


if __name__ == "__main__":
    main()
