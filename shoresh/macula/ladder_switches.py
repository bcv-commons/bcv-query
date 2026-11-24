"""Stage 59 of the Hebrew ladder: pilot-2 of the level switches (SPEC-ladder 6), written to hebrew-levels/pilot-2/.

The levels machinery of SPEC-levels 6 and 7 (levels_drafts.py: parts, rule AF, the draft, the host rules of R, the
assembly) rebuilt on build k1 over the ladder scope, with the mends of SPEC-ladder 6.2-6.5:
  R   NF2 (the name the text last used), FIN, NUM, OBJ, DEF (and 0854), DEM, KIND; GK in the editions (6.3)
  V   from the gloss bank (banks/gloss.parquet of hebrew-ladder/pilot-1), rule FIT and RARE (6.4)
  A   SPEC-levels 6.4 for hbo with FIN, NF2, DEF, NUM, KIND (6.5)
Levels: l0, r (all parts), zr_r and z_r_a (hbo). Every function is deterministic.
"""
import json
import random
import sys
import unicodedata as ud
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import levels_drafts as L  # noqa: E402
import levels_stage43 as L43  # noqa: E402
from levels_common import write_parquet, write_tsv  # noqa: E402

DATA = HERE / "data"
K1 = DATA / "source-examples" / "k1"
L.I1 = K1                      # the levels machinery reads k1 here (SPEC-ladder 6.1, L-19)
PILOT1 = DATA / "hebrew-levels" / "pilot-1"
GLOSS = DATA / "hebrew-ladder" / "pilot-1" / "banks" / "gloss.parquet"
SEED = "ladder-2026-11-24"
TEXTS = ("hbo", "heb_mod", "heb_scg")
LEVELS = {  # SPEC-ladder 6.1
    "l0": ((), TEXTS),
    "r": (("r_amb",), TEXTS),
    "zr_r": (("v_rare", "r_amb"), ("hbo",)),
    "z_r_a": (("v_all", "r_amb", "a"), ("hbo",)),
}
LEVEL_ORDER = ("l0", "r", "zr_r", "z_r_a")
PORTIONS = ("JON", "PSA1-41", "ISA40-55", "RUT", "GEN22-25", "MRK")
NAME_KINDS = ("person:", "group:", "deity:", "fauna:")
R_REASONS = ("model_input", "several_referents", "catch_all", "ent_kind", "demonstrative", "named_in_clause",
             "not_ambiguous", "greek_unlinked", "greek_who", "greek_person_number", "host_infinitive",
             "host_participle", "host_other", "form_ambiguous", "no_earlier_name", "indefinite", "number_mismatch",
             "form_unattested")
A_REASONS = ("model_input", "no_who", "several_referents", "person_1_2", "ent_kind", "said_in_clause", "taken_by_r",
             "role_other", "host_infinitive", "host_participle", "host_other", "no_earlier_name", "indefinite",
             "number_mismatch", "form_unattested")
V_REASONS = ("model_input", "lemma_phrase", "kind_other", "core_phrase", "no_change", "unattested", "form_other",
             "fused_article", "not_rare")
ATNACH = "֑"
S, I, B = pa.string(), pa.int64(), pa.bool_()
WORDS = L43.WORDS
PIECES = pa.schema([("t", I), ("n", I), ("text", S), ("kind", S), ("lexeme", S), ("class", S), ("marks", S), ("who", S),
                    ("who_basis", S), ("basis", S), ("op", S)])
LINKS = L43.LINKS
OPS = L43.OPS


def portion(book, chapter):
    if book == "JON": return "JON"
    if book == "RUT": return "RUT"
    if book == "PSA" and 1 <= chapter <= 41: return "PSA1-41"
    if book == "ISA" and 40 <= chapter <= 55: return "ISA40-55"
    if book == "GEN" and 22 <= chapter <= 25: return "GEN22-25"
    if book == "MRK": return "MRK"
    return ""


def point(text):
    """SPEC-levels 7.3 `point` of one word or piece (pointed without accents, NFD)."""
    out = []
    for ch in ud.normalize("NFD", text or ""):
        o = ord(ch)
        if 0x05D0 <= o <= 0x05EA or 0x05B0 <= o <= 0x05BC or o in (0x05C1, 0x05C2, 0x05C7):
            out.append(ch)
        elif ud.category(ch) == "Mn":
            continue
        else:
            out.append(" ")
    return " ".join("".join(out).split())


def cons(text):
    return "".join(c for c in ud.normalize("NFD", text or "") if "א" <= c <= "ת").translate(str.maketrans("ךםןףץ", "כמנפצ"))


# ------------------------------------------------------------------ the texts of the ladder scope

class Text2(L.Text):
    def __init__(self, code, parts):
        self.code = code
        if code == "hbo":
            self.parts = {"hbo": parts["hbo"], "arc": parts["arc"]}
            ws = sorted((w["id"], pn, t) for pn in ("hbo", "arc") for t, w in self.parts[pn].words.items()
                        if portion(w["book"], w["chapter"]) and w["book"] != "MRK")
            self.order = [(pn, t) for _, pn, t in ws]
        else:
            self.parts = {code: parts[code]}
            self.order = [(code, t) for t in sorted(parts[code].words) if parts[code].words[t]["book"] == "MRK"]
        self.part_of = {t: pn for pn, t in self.order}
        self.scope = set(self.part_of)


# ------------------------------------------------------------------ rule NF2 (6.2)

class Names2:
    """Per part and ent: the mentions in text order (t), with the word test of SPEC-levels 6.6, verse-final and
    atnach words skipped."""

    def __init__(self, parts, name_lexemes):
        self.idx = {}
        for name, part in parts.items():
            last_w = {}
            for t, w in part.words.items():
                k = (w["book"], w["chapter"], w["verse"])
                last_w[k] = max(last_w.get(k, 0), w["w"])
            idx = defaultdict(list)
            for t in sorted(part.words):
                w = part.words[t]
                ps = part.pieces[t]
                st = [p for p in ps if p["kind"] == "stem"]
                if len(st) != 1 or st[0]["class"] != "noun" or not L.strict_who(st[0]):
                    continue
                s = st[0]
                if s["m"].get("state", "abs") not in ("abs", ""):
                    continue
                if any(p["kind"] == "suffix" for p in ps) or any(p["fused"] for p in ps):
                    continue
                if w["w"] == last_w[(w["book"], w["chapter"], w["verse"])] or ATNACH in w["text"]:
                    continue
                art = [p for p in ps if p["kind"] == "prefix" and p["class"] == "art"]
                pcs = art[-1:] + [s]
                ntext = "".join(p["text"] for p in pcs)
                # a proper noun: marks.type proper; where the piece has no type mark (the editions carry none on
                # nouns), the lexeme's k1/lexicon state `name` (DEF, SPEC-ladder 6.2; see the stage 59 report)
                if s["m"].get("type") == "proper":
                    proper = "type"
                elif not s["m"].get("type") and s["lexeme"] in name_lexemes:
                    proper = "lexicon"
                else:
                    proper = ""
                for e in L.ents(s["who"]):
                    idx[e].append((t, w["book"], w["chapter"], ntext, pcs, proper))
            self.idx[name] = idx

    def nf2(self, part_name, ent, head_t, book, chapter):
        rows = self.idx.get(part_name, {}).get(ent, ())
        best_c = best_b = None
        for r in rows:
            if r[0] >= head_t:
                break
            if r[1] != book:
                continue
            if r[2] == chapter:
                best_c = r
            elif book != "PSA":
                best_b = r
        r, tier = (best_c, "nf_chapter") if best_c else (best_b, "nf_book")
        if r is None:
            return None
        pcs = [{"text": p["text"], "kind": p["kind"], "lexeme": p["lexeme"], "class": p["class"],
                "marks": p["marks"], "m": p["m"]} for p in r[4]]
        return {"text": r[3], "pieces": pcs, "definite": bool(r[5]) or len(pcs) > 1, "proper": bool(r[5]),
                "proper_by": r[5], "tier": tier, "at": r[0]}


# ------------------------------------------------------------------ the Greek check (6.3)

class Greek:
    def __init__(self):
        self.pieces = {}
        for p in pq.read_table(K1 / "grc" / "pieces.parquet",
                               columns=["t", "kind", "class", "marks", "who", "who_basis"]).to_pylist():
            if p["kind"] == "stem":
                p["m"] = json.loads(p["marks"] or "{}")
                self.pieces[p["t"]] = p
        self.links = {}
        for e in ("heb_mod", "heb_scg"):
            m = defaultdict(set)
            for r in pq.read_table(K1 / e / "links.parquet").to_pylist():
                if r["other"] == "grc" and r["basis"] == "linked" and (r["agree"] or 0) >= 1:
                    m[r["t"]].add(r["s"])
            self.links[e] = m

    def check(self, edition, word_t, ent, head_m):
        """-> (reason or '', [greek t])"""
        gs = sorted(self.links[edition].get(word_t, ()))
        if not gs:
            return "greek_unlinked", []
        carry = [g for g in gs if g in self.pieces and self.pieces[g]["who"]
                 and self.pieces[g]["who_basis"] != "model" and ent in self.pieces[g]["who"].split()]
        if not carry:
            return "greek_who", gs
        for g in carry:
            gp = self.pieces[g]
            if gp["class"] not in ("verb", "pron"):
                continue
            for k in ("person", "number"):
                a, b = head_m.get(k, ""), gp["m"].get(k, "")
                if a and b and a != b:
                    return "greek_person_number", gs
        return "", gs


# ------------------------------------------------------------------ switch R (6.2)

def host_kind(st):
    """FIN: a verb's type -> '' (finite) or a host reason."""
    if st is None or st["class"] != "verb":
        return "host_other"
    ty = st["m"].get("type", "")
    if ty in L.FINITE: return ""
    if ty in L.INFINITIVE: return "host_infinitive"
    if ty in L.PARTICIPLE: return "host_participle"
    return "host_other"


def has_article(ps):
    return any(p["kind"] == "prefix" and p["class"] == "art" for p in ps) or any(p["fused"] for p in ps)


def named_in_clause2(part, t, n, ent):
    """DEM: every noun or pronoun stem piece of the head's clause (any word, the head piece aside) with the ent."""
    cl = part.words[t]["clause"]
    if not cl:
        return False
    for wt in part.words_by_clause.get(cl, ()):
        for q in part.pieces[wt]:
            if (q["t"], q["n"]) == (t, n):
                continue
            if q["kind"] == "stem" and q["class"] in ("noun", "pron") and L.strict_who(q) and ent in L.ents(q["who"]):
                return True
    return False


def name_number(nf):
    return nf["pieces"][-1]["m"].get("number", "")


def switch_r2(ctx, D, ops, level, om_lx, X):
    T = ctx.T
    for pn, r, p in L.r_places(ctx):
        t = r["t"]
        part = T.parts[pn]
        w = part.words[t]
        op = L.base_op(T, level, "r", "amb", t, r["n"])
        op["before"] = w["text"]
        es = L.ents(p["who"])
        op["ent"] = " ".join(es)
        hk = r["head_kind"]
        model = r.get("basis") == "model" or not L.strict_piece(p) or p["who_basis"] == "model"
        stp = part.stem(t)
        if hk == "suffix" and stp is not None and not L.strict_piece(stp):
            model = True
        cands = L.window_candidates(ctx, pn, t, p, set(es)) if not model else []
        detail = {"window": cands}
        reason, nf, rule = "", None, ""
        head_m = p["m"]
        if model:
            reason = "model_input"
        elif len(es) != 1:
            reason = "several_referents"
        elif es[0] in ctx.catch_all:
            reason = "catch_all"
        elif hk == "verb_zero" and not es[0].startswith(NAME_KINDS):
            reason = "ent_kind"
        elif hk == "pronoun" and has_article(part.pieces[t]):
            reason = "demonstrative"
        elif named_in_clause2(part, t, r["n"], es[0]):
            reason = "named_in_clause"
        elif not cands:
            reason = "not_ambiguous"
        if not reason and T.code != "hbo":
            g, gs = X["greek"].check(T.code, t, es[0], head_m)
            detail["greek"] = gs
            reason = g
        if not reason:
            if hk == "verb_zero":
                reason = host_kind(D.cur_stem.get(t) or stp)
                rule = "r_subject"
            elif hk == "pronoun":
                rule = "r_pronoun"
            else:
                rule = L.r_rule(ctx, D, pn, r, p)
                if rule.startswith("host_"):
                    reason = rule
        if not reason and rule == "r_prep":
            st = D.cur_stem.get(t) or stp
            if st["lexeme"] in X["lex0854"]:
                reason = "form_ambiguous"
        if not reason:
            nf = X["names"].nf2(pn, es[0], t, w["book"], w["chapter"])
            if nf is None:
                reason = "no_earlier_name"
            elif not nf["definite"]:
                reason = "indefinite"
            elif head_m.get("number") == "pl" and name_number(nf) == "sg" and es[0].startswith("person:"):
                reason = "number_mismatch"
        op["detail"] = detail
        if reason:
            op["reason"] = reason
            ops.append(op)
            continue
        if nf is not None:
            op["detail"]["nf_at"] = nf["at"]
            if nf["proper_by"] == "lexicon" and len(nf["pieces"]) == 1:
                X["info"]["definite_by_lexicon/" + T.code + "/r"] += 1
        ok = write_r(ctx, D, ops, op, pn, r, rule, nf, es[0], om_lx)
        if not ok:
            op["reason"] = "form_unattested"
            op["_words"] = []
        ops.append(op)


def write_r(ctx, D, ops, op, pn, r, rule, nf, ent, om_lx):
    """The host rules of SPEC-levels 6.3 with OBJ (SPEC-ladder 6.2). Returns False where AF finds no form."""
    T = ctx.T
    t = r["t"]
    part = T.parts[pn]
    tmp = len(ops)
    ps = part.pieces[t]
    cur = D.body[t][0]["pieces"] if t in D.body else None
    host_pieces = cur if cur is not None else [L.src_piece_dict(q, pn) for q in ps]
    pre = [q for q in host_pieces if q["kind"] == "prefix"]
    head_link = (pn, r["t"], r["n"])
    form_rule = nf["tier"]
    if rule == "r_subject":
        nw = {"pieces": L.name_pieces(nf, ent, [head_link + ("insert",)]), "op": tmp, "after": None}
        D.insert(t, 0, nw)
        written = [nw]
    elif rule == "r_pronoun":
        new = [dict(q) for q in pre] + L.name_pieces(nf, ent, [head_link + ("replace",)])
        nw = {"pieces": new, "op": tmp, "after": None}
        D.body[t] = [nw]
        D.writer[t] = ("r", tmp)
        written = [nw]
    elif rule == "r_prep":
        st = D.cur_stem.get(t) or part.stem(t)
        spre = [q for q in ps if q["kind"] == "prefix"]
        ff = L.free_form(ctx, st["lexeme"], spre)
        if ff:
            rule = "r_prep_free"
            form_rule = ff[0]
            fw_pieces = [q for q in L.build_word_from_af(pn, ps, ff[1], st["who"], st["who_basis"]) if q["kind"] != "suffix"]
            fw = {"pieces": fw_pieces, "op": tmp,
                  "after": T.code == "hbo" and ctx.forms.free_after(T.code, st["lexeme"], L.word_text(ff[1])) or None}
            nw = {"pieces": L.name_pieces(nf, ent, [head_link + ("replace",)]), "op": tmp, "after": None}
            D.body[t] = [fw, nw]
            D.writer[t] = ("r", tmp)
            written = [fw, nw]
        elif st["class"] == "prep":
            rule = "r_prep_bound"
            got = L.bound_form(ctx, pn, ps, st, nf, ent, head_link, tmp)
            if got is None:
                return False
            form_rule, nw = got
            D.body[t] = [nw]
            D.writer[t] = ("r", tmp)
            written = [nw]
        else:
            return False
    elif rule == "r_construct":
        st = D.cur_stem.get(t) or part.stem(t)
        want = {"state": "cstr"}
        for k in ("number", "gender"):
            if st["m"].get(k):
                want[k] = st["m"][k]
        spre = [q for q in ps if q["kind"] == "prefix"]
        hit = ctx.forms.af(T.code, st["lexeme"], want, (), spre, any(q["fused"] for q in ps))
        if not hit:
            return False
        form_rule = hit[0]
        cw = [q for q in L.build_word_from_af(pn, ps, hit[1], st["who"], st["who_basis"]) if q["kind"] != "suffix"]
        if t in D.body:
            op["_over_v"] = True
        w1 = {"pieces": cw, "op": tmp, "after": None}
        nw = {"pieces": L.name_pieces(nf, ent, [head_link + ("replace",)]), "op": tmp, "after": None}
        D.body[t] = [w1, nw]
        D.writer[t] = ("r", tmp)
        written = [w1, nw]
    elif rule == "r_object":
        # OBJ: the verb without its object suffix (AF), then the object marker joined by maqaf to the name
        st = D.cur_stem.get(t) or part.stem(t)
        want = {k: st["m"][k] for k in ("stem", "type", "person", "gender", "number") if st["m"].get(k)}
        spre = [q for q in ps if q["kind"] == "prefix"]
        hit = ctx.forms.af(T.code, st["lexeme"], want, (), spre, any(q["fused"] for q in ps))
        ff = ctx.forms.af(T.code, om_lx, {}, (), [], False)
        if not hit or not ff:
            return False
        form_rule = hit[0]
        vw_pieces = [q for q in L.build_word_from_af(pn, ps, hit[1], st["who"], st["who_basis"]) if q["kind"] != "suffix"]
        if t in D.body:
            op["_over_v"] = True
        vw = {"pieces": vw_pieces, "op": tmp, "after": None}
        D.body[t] = [vw]
        D.writer[t] = ("r", tmp)
        omp = [L.new_piece(q, "", "", [head_link + ("insert",)]) for q in ff[1] if q["role"] == "stem"]
        ow = {"pieces": omp, "op": tmp, "after": "־" if T.code == "hbo" else None}
        nw = {"pieces": L.name_pieces(nf, ent, [head_link + ("insert",)]), "op": tmp, "after": None}
        D.insert(t, 1, ow)
        D.insert(t, 1, nw)
        written = [vw, ow, nw]
    else:
        return False
    op.update(state="applied", rule=rule, form_rule=form_rule)
    op["_words"] = written
    return True


# ------------------------------------------------------------------ switch V from the gloss bank (6.4)

class GlossV:
    def __init__(self, parts, lexicon):
        self.rows = [r for r in pq.read_table(GLOSS).to_pylist()
                     if r["anchor_state"] == "anchored" and portion(r["book"], r["chapter"])]
        self.strong = {r["lexeme"]: r["strong"] for r in lexicon.values()}
        self.parts = parts
        self.by_cons = defaultdict(list)
        for pn in ("hbo", "arc"):
            part = parts[pn]
            for t in sorted(part.words):
                self.by_cons[cons(part.words[t]["text"])].append((pn, t))

    def shape(self, pn, t):
        ps = self.parts[pn].pieces[t]
        st = [p for p in ps if p["kind"] == "stem"]
        return (tuple(p["lexeme"] for p in ps if p["kind"] == "prefix"),
                tuple((p["m"].get("person", ""), p["m"].get("gender", ""), p["m"].get("number", ""))
                      for p in ps if p["kind"] == "suffix"), st[0] if st else None)

    def attested(self, row, src_pn, src_t):
        """The first Tanakh word (text order) that FIT took: same cons as the core, same shape, pointed text the
        row's fit_form, stem lexeme its fit_lexeme. -> its pieces as AF pieces (texts in the `point` form)."""
        pre0, suf0, st0 = self.shape(src_pn, src_t)
        for pn, t in self.by_cons.get(cons(row["core"]), ()):
            pre, suf, st = self.shape(pn, t)
            if st is None or pre != pre0 or suf != suf0 or st["class"] != st0["class"]:
                continue
            if st["lexeme"] != row["fit_lexeme"] or point(self.parts[pn].words[t]["text"]) != row["fit_form"]:
                continue
            ok = True
            for k in ("type", "person", "gender", "number", "state"):
                v = st0["m"].get(k)
                if v and not L.marks_agree({k: v}, st["m"]):
                    ok = False
            if not ok:
                continue
            out = []
            for p in self.parts[pn].pieces[t]:
                role = "pre" if p["kind"] == "prefix" else "stem" if p["kind"] == "stem" else "suf"
                out.append({"text": point(p["text"]), "kind": p["kind"], "lexeme": p["lexeme"], "class": p["class"],
                            "marks": p["marks"], "m": p["m"], "role": role})
            return out
        return None


def lemma_words(lemma):
    return [x for x in (lemma or "").replace("־", " ").split() if x]


def switch_v2(ctx, D, ops, level, setting, X):
    T = ctx.T
    G = X["gloss"]
    for r in G.rows:
        if r["src_t"] is not None:
            t, n = r["src_t"], r["src_n"]
        else:
            t = json.loads(r["anchor_t"])[0]
            st = T.parts[T.part_of[t]].stem(t) if t in T.part_of else None
            n = st["n"] if st else 1
        if t not in T.scope:
            continue
        pn = T.part_of[t]
        part = T.parts[pn]
        ps = part.pieces[t]
        p = [q for q in ps if q["n"] == n][0]
        op = L.base_op(T, level, "v", setting, t, n)
        op["before"] = part.words[t]["text"]
        op["lexeme_before"] = p["lexeme"]
        op["detail"] = {"gloss": r["gloss"]}
        op["tier"], op["chosen_by"] = "gloss", ["mz"]
        if not L.strict_piece(p):
            reason = "model_input"
        elif len(lemma_words(r["lemma"])) > 1 or r["src_t"] is None:
            reason = "lemma_phrase"
        elif r["kind"] != "gloss":
            reason = "kind_other"
        elif r["core_words"] >= 2:
            reason = "core_phrase"
        elif r["fit"] == "fits" and (r["fit_lexeme"] == r["src_lexeme"]
                                     or (G.strong.get(r["fit_lexeme"]) and
                                         G.strong.get(r["fit_lexeme"]) == G.strong.get(r["src_lexeme"]))):
            reason = "no_change"
        elif r["fit"] == "unattested":
            reason = "unattested"
        elif r["fit"] == "form_other":
            reason = "form_other"
        elif any(q["fused"] for q in ps):
            reason = "fused_article"
        elif setting == "rare" and not r["rare"]:
            reason = "not_rare"
        elif r["fit"] != "fits":
            reason = "unattested"           # not reached in pilot-2 (counted in build.json)
            X["info"]["v_fit_blank"] += 1
        elif t in D.body:
            reason = "no_change"            # a second gloss on a word V already wrote (counted in build.json)
            X["info"]["v_second_gloss"] += 1
        else:
            reason = ""
        if not reason:
            pcs = G.attested(r, pn, t)
            if pcs is None:
                reason = "unattested"
                X["info"]["v_no_attested_word"] += 1
        if reason:
            op["reason"] = reason
            ops.append(op)
            continue
        new = L.build_word_from_af(pn, ps, pcs, p["who"], p["who_basis"])
        op.update(state="applied", rule="v_gloss", lexeme_after=r["fit_lexeme"], form_rule="whole")
        word = {"pieces": new, "op": len(ops), "after": None}
        D.body[t] = [word]
        D.writer[t] = ("v", len(ops))
        D.cur_stem[t] = [q for q in new if q["kind"] == "stem"][0]
        op["_words"] = [word]
        ops.append(op)


# ------------------------------------------------------------------ switch A (6.5)

def switch_a2(ctx, D, ops, level, kind_code, om_lx, r_subjects, X):
    T = ctx.T
    for pn, _, r in L.a_places(ctx, kind_code):
        part = T.parts[pn]
        st = part.stem(r["verb"])
        w = part.words[r["verb"]]
        op = L.base_op(T, level, "a", "", r["verb"], st["n"])
        op["added_clause"], op["added_role"] = r["clause"], r["role"]
        op["before"] = w["text"]
        es = L.ents(r["who"])
        op["ent"] = " ".join(es)
        subj = r["role"] == part._subj_role[(r["verb"], r["clause"])]
        reason, nf = "", None
        if r.get("own_basis") == "model":
            reason = "model_input"
        elif not es:
            reason = "no_who"
        elif len(es) > 1:
            reason = "several_referents"
        elif r["person"] in ("1", "2"):
            reason = "person_1_2"
        elif subj and not es[0].startswith(NAME_KINDS):
            reason = "ent_kind"
        elif L.said_in_clause(part, r, es):
            reason = "said_in_clause"
        elif subj and r["verb"] in r_subjects:
            reason = "taken_by_r"
        elif not subj and r["role"] != "A1":
            reason = "role_other"
        if not reason:
            reason = host_kind(D.cur_stem.get(r["verb"]) or st)
        if not reason:
            nf = X["names"].nf2(pn, es[0], r["verb"], w["book"], w["chapter"])
            if nf is None:
                reason = "no_earlier_name"
            elif not nf["definite"]:
                reason = "indefinite"
            else:
                num = (D.cur_stem.get(r["verb"]) or st)["m"].get("number", "") if subj else r["number"]
                if num == "pl" and name_number(nf) == "sg" and es[0].startswith("person:"):
                    reason = "number_mismatch"
        ff = None
        if not reason and not subj:
            ff = ctx.forms.af(T.code, om_lx, {}, (), [], False)
            if not ff:
                reason = "form_unattested"
        if reason:
            op["reason"] = reason
            ops.append(op)
            continue
        op["detail"] = {"nf_at": nf["at"]}
        if nf["proper_by"] == "lexicon" and len(nf["pieces"]) == 1:
            X["info"]["definite_by_lexicon/" + T.code + "/a"] += 1
        tmp = len(ops)
        link = (pn, st["t"], st["n"], "insert")
        nw = {"pieces": L.name_pieces(nf, es[0], [link]), "op": tmp, "after": None}
        if subj:
            D.insert(r["verb"], 0, nw)
            written, rule = [nw], "a_subject"
        else:
            omp = [L.new_piece(q, "", "", [link]) for q in ff[1] if q["role"] == "stem"]
            ow = {"pieces": omp, "op": tmp, "after": "־" if T.code == "hbo" else None}
            D.insert(r["verb"], 1, ow)
            D.insert(r["verb"], 1, nw)
            written, rule = [ow, nw], "a_object"
        op.update(state="applied", rule=rule, form_rule=nf["tier"])
        op["_words"] = written
        ops.append(op)


# ------------------------------------------------------------------ a level

def run_level(ctx, level, kind_code, om_lx, X):
    T = ctx.T
    D = L.Draft(T)
    ops = []
    for sw in LEVELS[level][0]:
        if sw.startswith("v_"):
            switch_v2(ctx, D, ops, level, sw[2:], X)
        elif sw == "r_amb":
            switch_r2(ctx, D, ops, level, om_lx, X)
        elif sw == "a":
            r_subj = {o["src_t"] for o in ops if o["switch"] == "r" and o["rule"] == "r_subject"}
            switch_a2(ctx, D, ops, level, kind_code, om_lx, r_subj, X)
    return L.assemble(T, D), ops


def piece_basis(q, src_basis):
    lk = q["links"]
    if lk and all(h == "copy" for _, _, _, h in lk) and len(lk) == 1:
        part, s, s_n, _ = lk[0]
        return src_basis.get((part, s, s_n), "given")
    return "derived"


def finish(T, level, dwords, ops, src_basis):
    order = sorted(range(len(ops)), key=lambda i: (ops[i]["src_t"], ops[i]["src_n"], ops[i]["switch"],
                                                   ops[i]["added_role"], ops[i]["added_clause"]))
    key_of = {i: f"op:{level}:{T.code}:{j}" for j, i in enumerate(order, 1)}
    t_of, W, P, K = {}, [], [], []
    wpos = Counter()
    for t, dw in enumerate(dwords, 1):
        src = dw["src"]
        vk = (src["book"], src["chapter"], src["verse"])
        wpos[vk] += 1
        t_of[id(dw["obj"])] = t
        opk = key_of[dw["op"]] if dw["op"] is not None else ""
        W.append({"t": t, "book": src["book"], "chapter": src["chapter"], "verse": src["verse"], "w": wpos[vk],
                  "text": dw["text"], "after": dw["after"], "sentence": src["sentence"], "clause": src["clause"],
                  "op": opk})
        for n, q in enumerate(dw["pieces"], 1):
            P.append({"t": t, "n": n, "text": q["text"], "kind": q["kind"], "lexeme": q["lexeme"], "class": q["class"],
                      "marks": q["marks"], "who": q["who"], "who_basis": q["who_basis"],
                      "basis": "derived" if opk else piece_basis(q, src_basis), "op": opk})
            for part, s, s_n, how in q["links"]:
                K.append({"t": t, "n": n, "s": s, "agree": 1, "agree_model": None, "other": part, "how": how,
                          "basis": "derived", "s_n": s_n})
    rows = []
    for i in order:
        o = ops[i]
        r = {k: v for k, v in o.items() if not k.startswith("_")}
        r["op"] = key_of[i]
        r["detail"] = L43.jdump(o["detail"])
        r["chosen_by"] = L43.jdump(o["chosen_by"] if o["chosen_by"] is not None else [])
        r["routes_all"] = L43.jdump(o["routes_all"] if o["routes_all"] is not None else [])
        dts = [t_of[id(w)] for w in o["_words"]]
        r["draft_t"] = L43.jdump(dts)
        r["after"] = " ".join(W[t - 1]["text"] for t in dts)
        rows.append(r)
    return W, P, K, rows, sum(1 for o in ops if o.get("_over_v"))


# ------------------------------------------------------------------ the comparison with pilot-1 (6.6)

P1_LEVEL = {"r": ("r", "r"), "a": ("v2_r_a", "z_r_a"), "v": ("v2", "z_r_a")}
SHARED = ("GEN22-25", "RUT", "JON", "MRK")


def compare_pilot1(all_ops, p1_ops, id_same):
    """per switch and text: pilot-1 applied, pilot-2 applied, kept, changed form, dropped by pilot-2's reason,
    new by pilot-1's reason; over the shared places (GEN 22-25, RUT, JON, MRK)."""
    def shared(r):
        b, c = r["key"].split()[0], int(r["key"].split()[1].split(":")[0])
        return portion(b, c) in SHARED
    out = {}
    for sw, (l1, l2) in P1_LEVEL.items():
        for tx in TEXTS:
            if sw == "a" and tx != "hbo":
                continue
            a = {}
            for r in p1_ops:
                if r["level"] == l1 and r["text"] == tx and r["switch"] == sw and shared(r):
                    a.setdefault((r["src_t"], r["src_n"], r["added_role"]), r)
            l2x = l2 if not (sw == "v" and tx != "hbo") else "r"
            b = {}
            for r in all_ops:
                if r["level"] == l2x and r["text"] == tx and r["switch"] == sw and shared(r):
                    b.setdefault((r["src_t"], r["src_n"], r["added_role"]), r)
            c = Counter()
            dropped, new = Counter(), Counter()
            for k, r in a.items():
                if r["state"] != "applied":
                    continue
                c["p1_applied"] += 1
                q = b.get(k)
                if q is None:
                    dropped["no_place_in_pilot2"] += 1
                elif q["state"] == "applied":
                    c["kept"] += 1
                    if q["after"] != r["after"]:
                        c["kept_other_form"] += 1
                else:
                    dropped[q["reason"]] += 1
            for k, q in b.items():
                if q["state"] != "applied":
                    continue
                c["p2_applied"] += 1
                r = a.get(k)
                if r is None:
                    new["no_place_in_pilot1"] += 1
                elif r["state"] != "applied":
                    new[r["reason"]] += 1
            c["dropped"] = sum(dropped.values())
            c["new"] = sum(new.values())
            out[f"{sw}/{tx}"] = {"levels": [l1, l2x], "counts": dict(sorted(c.items())),
                                 "dropped_by_pilot2_reason": dict(sorted(dropped.items())),
                                 "new_by_pilot1_reason": dict(sorted(new.items()))}
    out["_t_keys_same"] = id_same
    return out


def same_ids():
    """pilot-1 read i1, pilot-2 k1: are the word keys t the same words (by MACULA id) in the scope?"""
    res = {}
    for part in TEXTS:
        a = pq.read_table(DATA / "source-examples" / "i1" / part / "words.parquet", columns=["t", "id", "book"]).to_pylist()
        b = {r["t"]: r["id"] for r in pq.read_table(K1 / part / "words.parquet", columns=["t", "id"]).to_pylist()}
        res[part] = sum(1 for r in a if b.get(r["t"]) != r["id"])
    return res


# ------------------------------------------------------------------ the run

def run(out):
    out = Path(out)
    parts = {n: L.Part(n) for n in ("hbo", "arc", "heb_mod", "heb_scg")}
    forms = L.Forms(parts)
    lexicon = {r["lexeme"]: r for r in L.read_tsv(K1 / "lexicon" / "lexemes.tsv")}
    terms = L.read_tsv(K1 / "hbo" / "terms.tsv")
    kind_code = L.added_code(terms)
    om_lx = L.om_lexeme(forms)
    lex0854 = sorted(lx for lx, r in lexicon.items() if r["strong"] == "0854" and r["class"] == "prep")
    name_lexemes = {lx for lx, r in lexicon.items() if r["state"] == "name"}
    X = {"names": Names2(parts, name_lexemes), "greek": Greek(), "gloss": GlossV(parts, lexicon), "lex0854": set(lex0854),
         "info": Counter()}
    src_basis = {}
    for pn, part in parts.items():
        for t, ps in part.pieces.items():
            for q in ps:
                src_basis[(pn, t, q["n"])] = q.get("basis") or "given"
    all_ops, lines_meta, info = [], {}, {"over_v": {}, "lex0854": lex0854, "om_lexeme": om_lx}
    model_pieces = Counter()
    for code in TEXTS:
        T = Text2(code, parts)
        ctx = L.Ctx(T, forms, None, None)
        L.prepare_a(T)
        for level in LEVEL_ORDER:
            if code not in LEVELS[level][1]:
                continue
            dwords, ops = run_level(ctx, level, kind_code, om_lx, X)
            W, P, K, rows, over_v = finish(T, level, dwords, ops, src_basis)
            info["over_v"][f"{level}/{code}"] = over_v
            model_pieces[f"{level}/{code}"] = sum(1 for p in P if p["basis"] == "model")
            d = out / "texts" / level / code
            write_parquet(d / "words.parquet", L43.cols(W, WORDS), WORDS)
            write_parquet(d / "pieces.parquet", L43.cols(P, PIECES), PIECES)
            write_parquet(d / "links.parquet", L43.cols(K, LINKS), LINKS)
            write_tsv(d / "lexemes.tsv", ["lexeme", "lemma", "class", "count"], L43.lexemes_tsv(P, lexicon))
            all_ops += rows
            changed = {r["key"] for r in rows if r["state"] == "applied"}
            raws = L43.raw_lines(code, W)
            for form, fn in (("cons", L43.norm_cons), ("point", L43.norm_point)):
                recs = []
                for (b, c, v), raw in raws:
                    k = L.vkey(b, c, v)
                    recs.append((k, code, level, form, L.scoring_closed(b, c), k in changed, fn(raw)))
                write_tsv(out / "lines" / level / f"{code}.{form}.tsv",
                          ["key", "text", "level", "form", "scoring_closed", "changed", "line"], recs)
                lines_meta[(level, code, form)] = recs
    all_ops.sort(key=lambda r: (r["level"], r["text"], r["src_t"], r["src_n"], r["switch"], r["added_role"],
                                r["added_clause"]))
    write_parquet(out / "ops.parquet", L43.cols(all_ops, OPS), OPS)
    cv = []
    for level in sorted({r["level"] for r in all_ops}):
        for code in sorted({r["text"] for r in all_ops if r["level"] == level}):
            by = defaultdict(list)
            for r in all_ops:
                if r["level"] == level and r["text"] == code and r["state"] == "applied":
                    by[r["key"]].append(r)
            for k, _, _, _, closed, _, _ in lines_meta[(level, code, "cons")]:
                if k in by:
                    cv.append((level, code, k, closed, L43.jdump(sorted({r["switch"] for r in by[k]})), len(by[k])))
    write_tsv(out / "changed_verses.tsv", ["level", "text", "key", "scoring_closed", "switches", "ops"], cv)
    # the sealed sample per switch (for stage 63; op ids only)
    pools = {"r": ("r", None), "a": ("z_r_a", "hbo"), "v": ("z_r_a", "hbo")}
    rng = random.Random(SEED)
    srows = []
    for sw in ("r", "a", "v"):
        lv, tx = pools[sw]
        ids = sorted(r["op"] for r in all_ops if r["level"] == lv and r["switch"] == sw and r["state"] == "applied"
                     and (tx is None or r["text"] == tx))
        pick = rng.sample(ids, 30) if len(ids) > 30 else list(ids)
        srows += [(sw, lv, o) for o in pick]
    write_tsv(out / "sealed" / "switch_sample.tsv", ["switch", "level", "op"], srows)
    p1 = pq.read_table(PILOT1 / "ops.parquet", columns=["level", "text", "switch", "key", "src_t", "src_n",
                                                         "added_role", "state", "reason", "after"]).to_pylist()
    info["compare_pilot1"] = compare_pilot1(all_ops, p1, same_ids())
    info["model_pieces"] = dict(sorted(model_pieces.items()))
    info["v"] = dict(sorted(X["info"].items()))
    info["ops"] = dict(sorted(Counter(f"{r['level']}/{r['text']}/{r['switch']}/{r['state']}/{r['reason'] or r['rule']}"
                                      for r in all_ops).items()))
    info["changed_verses"] = dict(sorted(Counter(f"{r[0]}/{r[1]}" for r in cv).items()))
    info["lines"] = {f"{k[0]}/{k[1]}/{k[2]}": len(v) for k, v in sorted(lines_meta.items())}
    return info
