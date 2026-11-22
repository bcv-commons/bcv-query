"""Stage 40, items 3, 4, 7, 8: reach of switches R, A, E, V; forms for E; precision of `added`; the pilot scope.

  shoresh/.venv/bin/python -I shoresh/macula/levels_feasibility_switches.py
    -> stdout, internal-docs/source-examples-work/levels/switches-counts.json, added-sample.md, pilot-lines.json
Needs explain-statements.jsonl from levels_feasibility_explain.py (for switch V's explanations).
"""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from levels_feasibility_common import (BUILD, OUT, PARTS, SCRATCH, consonants, dump, is_content, lexicon,  # noqa: E402
                                       pointed, table)

PILOT = {"GEN", "RUT", "JON"}
POSS = "בַּעַל שֶׁלֹּא נִזְכַּר"   # the hbo term of added_kind `possessor`
NT = ("heb_mod", "heb_scg")
PTC = {"participle_active", "participle_passive"}
INF = {"infinitive_construct", "infinitive_absolute"}
FINITE = {"qatal", "wayyiqtol", "yiqtol", "weqatal", "imperative", "jussive", "cohortative"}


def scope_of(part, book):
    if part in NT:
        return "nt"
    return "pilot" if book in PILOT else "rest"


class Part:
    def __init__(self, part):
        self.part = part
        w = table(part, "words", ("t", "book", "chapter", "verse", "text", "clause"))
        self.book = dict(zip(w["t"], w["book"]))
        self.text = dict(zip(w["t"], w["text"]))
        self.wclause = dict(zip(w["t"], w["clause"]))
        c = table(part, "clauses", ("clause", "first", "parent", "depth", "pred", "pred_kind"))
        self.clauses = {k: dict(first=f, parent=p, depth=d, pred=pr, pred_kind=pk)
                        for k, f, p, d, pr, pk in zip(c["clause"], c["first"], c["parent"], c["depth"], c["pred"],
                                                      c["pred_kind"])}
        self.order = sorted(self.clauses, key=lambda k: (self.clauses[k]["first"], k))
        self.pos = {k: i for i, k in enumerate(self.order)}
        self.cwords = defaultdict(list)
        for t, k in self.wclause.items():
            if k:
                self.cwords[k].append(t)
        p = table(part, "pieces", ("t", "n", "kind", "class", "lexeme", "marks", "who"))
        self.pieces = defaultdict(list)
        for t, n, k, cl, lx, m, who in zip(p["t"], p["n"], p["kind"], p["class"], p["lexeme"], p["marks"], p["who"]):
            self.pieces[t].append(dict(n=n, kind=k, cls=cl, lex=lx, marks=json.loads(m) if m else {},
                                       who=who.split() if who else []))
        with open(BUILD / part / "participants.tsv", encoding="utf-8") as fh:
            self.names = {r["ent"]: r["name"] for r in csv.DictReader(fh, delimiter="\t")}

    def stem(self, t):
        ps = [p for p in self.pieces.get(t, []) if p["kind"] == "stem"]
        return ps[0] if ps else None

    def window(self, clause, before=2, after=0):
        i = self.pos.get(clause)
        if i is None:
            return []
        return self.order[max(0, i - before): i + after + 1]

    def mentions(self, clauses, skip_t=None):
        """ent -> set of (gender, number) of the pieces that carry it in the clauses' words."""
        out = defaultdict(set)
        for k in clauses:
            for t in self.cwords.get(k, []):
                if t == skip_t:
                    continue
                for p in self.pieces.get(t, []):
                    for e in p["who"]:
                        out[e].add((p["marks"].get("gender", ""), p["marks"].get("number", "")))
        return out


def switch_r(P, counts):
    """R: a pronoun suffix, independent pronoun or zero subject whose referent is ambiguous in the window."""
    wa = table(P.part, "who_account", ("t", "n", "head_kind", "state"))
    c = defaultdict(Counter)
    for t, n, hk, st in zip(wa["t"], wa["n"], wa["head_kind"], wa["state"]):
        if hk not in ("pronoun", "suffix", "verb_zero"):
            continue
        sc = scope_of(P.part, P.book.get(t))
        cc = c[sc]
        cc[f"heads:{hk}"] += 1
        piece = next((p for p in P.pieces.get(t, []) if p["n"] == n), None)
        if piece is None:
            cc["no_piece"] += 1
            continue
        pers = piece["marks"].get("person", "")
        if pers in ("1", "2"):
            cc["person_1_2"] += 1
            continue
        if st != "participant" or not piece["who"]:
            cc[f"no_referent:{st}"] += 1
            continue
        cc["referent"] += 1
        named = [e for e in piece["who"] if P.names.get(e)]
        g, nu = piece["marks"].get("gender", ""), piece["marks"].get("number", "")
        clause = P.wclause.get(t, "")
        if not clause:
            cc["referent_no_clause"] += 1
            continue
        men = P.mentions(P.window(clause), skip_t=None)
        agree = {e for e, gn in men.items() if any((g == "" or a in (g, "c", "b", "")) and
                                                   (nu == "" or b in (nu, "")) for a, b in gn)}
        agree |= set(piece["who"])
        amb = len(agree) >= 2
        cc["ambiguous" if amb else "unambiguous"] += 1
        if amb:
            cc["ambiguous_named" if named else "ambiguous_no_name"] += 1
            if len(piece["who"]) > 1:
                cc["ambiguous_several_referents"] += 1
    counts["R"] = {k: dict(v) for k, v in c.items()}


def switch_a(P, counts, sample_rows):
    """A: reach, and item 7's precision rule over every row of `added`."""
    a = table(P.part, "added")
    c = defaultdict(Counter)
    for i in range(len(a["clause"])):
        row = {k: a[k][i] for k in a}
        clause, verb = row["clause"], row["verb"]
        sc = scope_of(P.part, P.book.get(verb))
        cc = c[sc]
        cc[f"rows:{row['kind']}"] += 1
        who = row["who"].split() if row.get("who") else []
        named = bool(who) and all(P.names.get(e) for e in who)
        cc[f"{row['kind']}:{'who_named' if named else ('who_no_name' if who else 'no_who')}"] += 1
        # precision rule (FEASIBILITY.md section 7)
        if row["kind"] == POSS:
            verdict = "possessor_not_checked"
        elif not who and not row.get("antecedent"):
            verdict = "no_evidence"
        else:
            own = set(P.cwords.get(clause, []))
            win = P.window(clause, before=1, after=1)
            near = {t for k in win for t in P.cwords.get(k, [])} - own
            def said(ts):
                how = ""
                for t in ts:
                    if t == verb:
                        continue
                    for p in P.pieces.get(t, []):
                        if who and set(who) & set(p["who"]):
                            if p["kind"] == "stem":
                                return "word"
                            how = "suffix"
                if not who and row.get("antecedent"):
                    at = int(str(row["antecedent"]).split(".")[0])
                    return "antecedent" if at in ts else ""
                return how
            s1 = said(own)
            if s1:
                verdict = f"said_in_clause_{s1}"
            elif said(near):
                verdict = f"said_in_neighbour_{said(near)}"
            else:
                verdict = "unsaid_clause_and_neighbours"
        cc[f"verdict:{verdict}"] += 1
        cc[f"verdict:{row['kind']}:{verdict}"] += 1
        if P.part == "hbo":
            sample_rows.append((row, verdict))
    counts["A"] = {k: dict(v) for k, v in c.items()}


def form_index(parts):
    """(lexeme, stem, type) -> set of (person, gender, number) attested, over the forms tables of parts."""
    idx = defaultdict(set)
    for part in parts:
        f = table(part, "forms", ("lexeme", "marks"))
        for lx, m in zip(f["lexeme"], f["marks"]):
            d = json.loads(m)
            if d.get("type") in FINITE:
                idx[(lx, d.get("stem", ""), d["type"])].add((d.get("person", ""), d.get("gender", ""),
                                                             d.get("number", "")))
    return idx


def switch_e(P, counts, idx_tanakh):
    """E: clauses with a participle or infinitive predicate, the finite form each would need, and attestation."""
    added = table(P.part, "added", ("clause", "verb", "role", "person", "number", "gender"))
    subj = {}
    for k, v, r, pe, nu, ge in zip(added["clause"], added["verb"], added["role"], added["person"],
                                   added["number"], added["gender"]):
        if r in ("A0", "AA"):
            subj.setdefault((k, v), (pe, ge, nu))
    own = form_index([P.part]) if P.part in NT else idx_tanakh
    c = defaultdict(Counter)
    cells = defaultdict(set)
    for k, cl in P.clauses.items():
        pred = cl["pred"]
        st = P.stem(pred) if pred else None
        if not st or st["cls"] != "verb":
            continue
        ty = st["marks"].get("type", "")
        if ty not in PTC | INF:
            continue
        sc = scope_of(P.part, P.book.get(pred))
        cc = c[sc]
        kind = "participle" if ty in PTC else "infinitive"
        cc[f"clauses:{kind}:{'embedded' if cl['parent'] else 'top'}"] += 1
        if not cl["parent"]:
            continue
        par = P.clauses.get(cl["parent"], {})
        pst = P.stem(par.get("pred", 0)) if par.get("pred") else None
        pty = pst["marks"].get("type", "") if pst and pst["cls"] == "verb" else ""
        form = pty if pty in FINITE else "qatal"
        cc[f"form_from:{'parent' if pty in FINITE else 'default_qatal'}"] += 1
        if (k, pred) in subj and subj[(k, pred)][0]:
            pe, ge, nu = subj[(k, pred)]
            cc["pgn_from:added_subject"] += 1
        elif kind == "participle" and st["marks"].get("number"):
            pe, ge, nu = "3", st["marks"].get("gender", ""), st["marks"].get("number", "")
            cc["pgn_from:participle_3rd"] += 1
        else:
            pe, ge, nu = "3", "m", "sg"
            cc["pgn_from:default_3ms"] += 1
        if form == "imperative":
            pe = "2"
        stem = st["marks"].get("stem", "")
        need = (st["lex"], stem, form, pe, ge, nu)
        cells[sc].add(need)
        att = own.get((st["lex"], stem, form), set())
        ok = any(a == pe and (b == ge or b in ("c", "b", "") or ge in ("c", "")) and n == nu for a, b, n in att)
        if P.part in NT and not ok:
            att2 = idx_tanakh.get((st["lex"], stem, form), set())
            ok2 = any(a == pe and (b == ge or b in ("c", "b", "") or ge in ("c", "")) and n == nu for a, b, n in att2)
            cc["places_attested_in_tanakh_only" if ok2 else "places_unattested_anywhere"] += int(ok2) or 1
        cc["places_attested" if ok else "places_unattested"] += 1
        any_form = any(key[0] == st["lex"] and key[1] == stem for key in own)
        cc["places_lexeme_stem_has_some_finite_form" if any_form else "places_lexeme_stem_no_finite_form"] += 1
    out = {}
    for sc, cc in c.items():
        d = dict(cc)
        cs = cells[sc]
        att = sum(1 for (lx, stem, form, pe, ge, nu) in cs
                  if any(a == pe and (b == ge or b in ("c", "b", "") or ge in ("c", "")) and n == nu
                         for a, b, n in own.get((lx, stem, form), set())))
        d["cells_needed"] = len(cs)
        d["cells_attested"] = att
        out[sc] = d
    counts["E"] = out


def switch_v(P, counts, explained, grp_head):
    """V: content tokens of lexemes under a frequency cut; inputs: a commoner group head, an explanation."""
    lx = lexicon()
    freq = Counter()
    for ts in P.pieces.values():
        for p in ts:
            if p["kind"] == "stem" and p["lex"] and is_content(p["lex"], p["cls"]):
                freq[p["lex"]] += 1
    tot = {l: int(lx[l]["tanakh"] or 0) + int(lx[l]["heb_mod"] or 0) + int(lx[l]["heb_scg"] or 0)
           for l in freq if l in lx}
    out = {}
    for cut in (5, 20, 100):
        c = defaultdict(Counter)
        for t, ps in P.pieces.items():
            for p in ps:
                if p["kind"] != "stem" or not p["lex"] or not is_content(p["lex"], p["cls"]):
                    continue
                sc = scope_of(P.part, P.book.get(t))
                c[sc]["content_tokens"] += 1
                if tot.get(p["lex"], 0) >= cut:
                    continue
                c[sc]["below_cut"] += 1
                h = grp_head.get(p["lex"])
                head_ok = h and h != p["lex"] and tot.get(h, int(lx.get(h, {}).get("tanakh") or 0)) >= cut
                ex = explained.get(p["lex"], [])
                ex_ok = any(all((int(lx[y]["tanakh"] or 0) + int(lx[y]["heb_mod"] or 0) + int(lx[y]["heb_scg"] or 0))
                                >= cut for y in ys) for ys in ex if ys)
                if head_ok:
                    c[sc]["input:group_head"] += 1
                if ex_ok:
                    c[sc]["input:explanation_all_above_cut"] += 1
                if head_ok or ex_ok:
                    c[sc]["input:either"] += 1
                else:
                    st = lx.get(p["lex"], {}).get("state", "?")
                    c[sc][f"no_input:state:{st}" + (":has_explanation_below_cut" if ex else "")] += 1
        out[f"cut<{cut}"] = {k: dict(v) for k, v in c.items()}
    counts["V"] = out


def pilot_lines():
    out = {}
    for part in ("hbo", "arc"):
        w = table(part, "words", ("book", "chapter", "verse", "text", "after"))
        for b, ch, v, x, af in zip(w["book"], w["chapter"], w["verse"], w["text"], w["after"]):
            if b in PILOT:
                out.setdefault(("hbo", f"{b} {ch}:{v}"), []).append(x + (af or ""))
    for part in NT:
        w = table(part, "words", ("book", "chapter", "verse", "text"))
        for b, ch, v, x in zip(w["book"], w["chapter"], w["verse"], w["text"]):
            out.setdefault((part, f"{b} {ch}:{v}"), []).append(x)
    res = defaultdict(Counter)
    chars = defaultdict(set)
    for (part, k), toks in out.items():
        raw = ("".join(toks) if part == "hbo" else " ".join(toks))
        con, poi = consonants(raw), pointed(raw)
        r = res[part + (":" + k.split()[0] if part == "hbo" else "")]
        r["verse_lines"] += 1
        r["empty_consonants"] += int(not con)
        r["pointed_equals_consonants"] += int(con == poi)
        chars[part + ":con"] |= set(con)
        chars[part + ":poi"] |= set(poi)
    ok = {k: sorted(f"U+{ord(c):04X}" for c in v if not ("א" <= c <= "ת" or c == " ")) for k, v in chars.items()}
    return {k: dict(v) for k, v in res.items()}, ok


def main():
    statements = [json.loads(l) for l in open(SCRATCH / "explain-statements.jsonl", encoding="utf-8")]
    explained = defaultdict(list)
    for r in statements:
        if r.get("state") == "statement" and r.get("x") and r["x"][0] and r["kind"] not in ("class", "literal", "targum"):
            explained[r["x"][0]].append(r["y_content"])
    g = table("lexicon", "groups", ("group", "lexeme", "head"))
    heads = {gr: lx for gr, lx, h in zip(g["group"], g["lexeme"], g["head"]) if h}
    grp_head = {lx: heads.get(gr) for gr, lx in zip(g["group"], g["lexeme"])}
    idx_tanakh = form_index(["hbo", "arc"])
    allc = {}
    sample_rows = []
    for part in PARTS:
        P = Part(part)
        counts = {}
        switch_r(P, counts)
        switch_a(P, counts, sample_rows)
        switch_e(P, counts, idx_tanakh)
        switch_v(P, counts, explained, grp_head)
        allc[part] = counts
        print("==", part)
        for k, v in counts.items():
            print(" ", k, json.dumps(v, ensure_ascii=False, sort_keys=True))
        if part == "hbo":
            HB = P
    lines, badchars = pilot_lines()
    allc["pilot_lines"] = lines
    allc["pilot_chars_outside"] = badchars
    print("== pilot lines", json.dumps(lines), json.dumps(badchars))
    dump("switches-counts.json", allc)

    # item 7 sample: 40 hbo rows, fixed rule: every k-th row of `added` in file order (k = rows // 40)
    k = max(1, len(sample_rows) // 40)
    md = ["# `added` precision: 40 hbo rows (fixed rule)", "",
          f"Rule: rows of `i1/hbo/added.parquet` in file order; rows 0, k, 2k, ... with k = {k}. The clause is written out;",
          "the verb is marked [ ]; `who` names are from participants.tsv.", "",
          "| # | clause | role | kind | who (name) | verdict | clause text |", "|---|---|---|---|---|---|---|"]
    for i, (row, verdict) in enumerate(sample_rows[::k][:40]):
        ts = sorted(HB.cwords.get(row["clause"], []))
        txt = " ".join(("[" + HB.text[t] + "]") if t == row["verb"] else HB.text[t] for t in ts)
        who = " ".join(f"{e}({HB.names.get(e, '')})" for e in (row["who"] or "").split())
        md.append(f"| {i + 1} | {row['clause']} | {row['role']} | {row['kind']} | {who or '—'} | {verdict} | {txt} |")
    (OUT / "added-sample.md").write_text("\n".join(md) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
