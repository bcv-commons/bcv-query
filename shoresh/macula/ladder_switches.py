"""Stage 59 of the Hebrew ladder: pilot-2 of the level switches (SPEC-ladder 6), written to hebrew-levels/pilot-2/.

The levels machinery of SPEC-levels 6 and 7 (levels_drafts.py: parts, rule AF, the draft, the host rules of R, the
assembly) rebuilt on build k1 over the ladder scope, with the mends of SPEC-ladder 6.2-6.5:
  R   NF2 (the name the text last used), FIN, NUM, OBJ, DEF (and 0854), DEM, KIND; GK in the editions (6.3)
  V   from the gloss bank (banks/gloss.parquet of hebrew-ladder/pilot-1), rule FIT and RARE (6.4)
  A   SPEC-levels 6.4 for hbo with FIN, NF2, DEF, NUM, KIND (6.5)
Levels: l0, r (all parts), zr_r and z_r_a (hbo). Every function is deterministic.

The rule mends of 2026-11-25 (OPEN-ladder F.1, items 1-8): REL, REL-ASYN, A-OBJ, NUM both ways, NF2-CHAIN, FIN-ART,
NIC-FORM, A-HAYAH, V-COUNT, V-FIX; each is named at its code below.
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
             "host_participle", "host_other", "relative_head", "name_just_before", "form_ambiguous", "no_earlier_name", "indefinite",
             "number_mismatch", "form_unattested", "name_chain_bound")
A_REASONS = ("model_input", "no_who", "several_referents", "person_1_2", "ent_kind", "said_in_clause", "taken_by_r",
             "role_other", "host_infinitive", "host_participle", "host_other", "relative_head", "name_just_before", "measure_hayah",
             "in_relative", "passive_stem", "object_is_subject", "speech_person", "no_earlier_name", "indefinite",
             "number_mismatch", "form_unattested")
V_REASONS = ("model_input", "lemma_phrase", "kind_other", "core_phrase", "no_change", "unattested", "form_other",
             "fused_article", "common", "fixed_phrase", "not_rare")
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


# ------------------------------------------------------------------ the rule mends of 2026-11-25 (OPEN-ladder F.1)
# Each mend is a named rule; the comment cites the item of internal-docs/source-examples-work/ladder/OPEN-ladder.md.

REL_VERB = ("NpRelp", "Relp", "NpCL")    # k1 word rel of a verb that heads a relative clause (NpCL: asyndetic)
PASSIVE_STEMS = {"niphal", "pual", "hophal", "qal_passive", "hithpael", "hithpolel", "hithpalpel", "nithpael",
                 "pulal", "polal", "poal", "polpal"}          # A-OBJ: not an active stem (OPEN 2)
MAJESTY = {"0430", "0136", "0113", "1167"}   # NUM-SG: plural-stem names a singular verb takes (אֱלֹהִים, אֲדֹנָי, אֲדֹנִים, בְּעָלִים)
HAYAH = "1961"
DIVINE = {"3068", "0430", "0410"}          # V-FIX: a word right before one of these is inside a formula (בָּרוּךְ יְהוָה)
V_COMMON = 100                           # V-COUNT: V at step 2 (level z_r_a) only below 100 Tanakh occurrences (OPEN 8)


def strong(lexeme):
    return (lexeme or "").rsplit(":", 1)[-1]


class Syntax:
    """k1 words' head and rel (levels_drafts reads neither), and the verse order of each part."""

    def __init__(self, parts):
        self.head, self.rel, self.verse = {}, {}, {}
        for pn, part in parts.items():
            h, r = {}, {}
            for x in pq.read_table(K1 / pn / "words.parquet", columns=["t", "head", "rel"]).to_pylist():
                h[x["t"]], r[x["t"]] = x["head"], (x["rel"] or "").split(":")[0]
            self.head[pn], self.rel[pn] = h, r
            v = defaultdict(list)
            for t in sorted(part.words):
                w = part.words[t]
                v[(w["book"], w["chapter"], w["verse"])].append(t)
            self.verse[pn] = v

    def antecedent(self, pn, part, t):
        """REL: the antecedent word of the relative clause whose verb is t (coordinated relatives followed back), or
        None when t heads no relative clause."""
        if not self.rel[pn].get(t, "").startswith(REL_VERB):
            return None
        seen, h = set(), self.head[pn].get(t)
        while h and h not in seen and h in part.words:
            seen.add(h)
            st = part.stem(h)
            if st is not None and st["class"] == "verb" and self.rel[pn].get(h, "").startswith(REL_VERB):
                h = self.head[pn].get(h)
                continue
            return h
        return None

    def ents_of(self, pn, part, h):
        """the ents of the stem pieces of word h and of the words in apposition with it (Np-Appos either way)"""
        ws = {h}
        if self.rel[pn].get(h) == "Np-Appos" and self.head[pn].get(h):
            ws.add(self.head[pn][h])
        w = part.words[h]
        for x in self.verse[pn][(w["book"], w["chapter"], w["verse"])]:
            if self.rel[pn].get(x) == "Np-Appos" and self.head[pn].get(x) in ws:
                ws.add(x)
        out = set()
        for x in ws:
            for q in part.pieces.get(x, ()):
                if q["kind"] == "stem":
                    out |= set(L.ents(q["who"]))
        return out

    def rel_same(self, pn, part, t, ent):
        """REL (OPEN 1): t heads a relative clause whose antecedent (or a word in apposition with it) carries ent."""
        h = self.antecedent(pn, part, t)
        return h is not None and ent in self.ents_of(pn, part, h)

    def before_same(self, pn, part, t, ent):
        """REL-ASYN (OPEN 1, the asyndetic case): the word right before t stands in another clause and is a noun whose
        stem carries ent."""
        w = part.words[t]
        vs = self.verse[pn][(w["book"], w["chapter"], w["verse"])]
        i = vs.index(t)
        if i == 0:
            return False
        p = vs[i - 1]
        if part.words[p]["clause"] == w["clause"]:
            return False
        st = part.stem(p)
        return st is not None and st["class"] == "noun" and ent in L.ents(st["who"])

    def speech_person(self, pn, part, t, ent):
        """A-OBJ (OPEN 2): the ent is spoken of in the first or second person in t's verse (the speaker or the
        addressee): a piece of the verse carries the ent with person 1 or 2."""
        w = part.words[t]
        for x in self.verse[pn][(w["book"], w["chapter"], w["verse"])]:
            for q in part.pieces.get(x, ()):
                if q["m"].get("person") in ("1", "2") and ent in L.ents(q["who"]):
                    return True
        return False


def host_kind_art(st, ps):
    """FIN-ART (OPEN 5): a verb with an article prefix is a participle (הַשָּׁבָה), whatever its type says."""
    if st is not None and st["class"] == "verb" and any(p["kind"] == "prefix" and p["class"] == "art" for p in ps):
        return "host_participle"
    return host_kind(st)


def named_before(part, t, nf):
    """NIC-FORM (OPEN 6): a word before the host in the host's clause has a noun stem written as the name NF2 found
    (by consonants; the editions' names often carry no `who`)."""
    cl = part.words[t]["clause"]
    if not cl:
        return False
    want = cons(nf["head_text"])
    for wt in part.words_by_clause.get(cl, ()):
        if wt >= t:
            break
        for q in part.pieces[wt]:
            if q["kind"] == "stem" and q["class"] == "noun" and cons(q["text"]) == want:
                return True
    return False


def num_mismatch(num, nf, ent):
    """NUM both ways (OPEN 3, 4): a plural host and a person's name that is not plural (proper names carry no
    number); a singular host and a name whose stem is plural, unless an אֱלֹהִים-like lexeme."""
    if num == "pl" and ent.startswith("person:") and nf["number"] != "pl":
        return True
    if num == "sg" and nf["number"] == "pl" and strong(nf["head_lexeme"]) not in MAJESTY:
        return True
    return False


def hayah_measure(part, t, clause):
    """A-HAYAH (OPEN 7): a form of הָיָה whose clause holds a noun with the preposition כְּ (a measure: כְּאֵיפָה)."""
    st = part.stem(t)
    if st is None or strong(st["lexeme"]) != HAYAH:
        return False
    for wt in part.words_by_clause.get(clause, ()):
        ps = part.pieces[wt]
        if any(q["kind"] == "prefix" and q["class"] == "prep" and cons(q["text"]) == "כ" for q in ps) and \
                any(q["kind"] == "stem" and q["class"] == "noun" for q in ps):
            return True
    return False


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
    atnach words skipped. NF2-CHAIN (OPEN-ladder 4): also the construct chains `noun (cstr) + proper name` whose
    head carries the ent (מַלְאַךְ יְהוָה), in `chains`."""

    def __init__(self, parts, name_lexemes):
        self.idx, self.chains = {}, {}
        for name, part in parts.items():
            last_w = {}
            for t, w in part.words.items():
                k = (w["book"], w["chapter"], w["verse"])
                last_w[k] = max(last_w.get(k, 0), w["w"])

            def pausal(w):
                return w["w"] == last_w[(w["book"], w["chapter"], w["verse"])] or ATNACH in w["text"]

            def proper_of(s):
                # a proper noun: marks.type proper; where the piece has no type mark (the editions carry none on
                # nouns), the lexeme's k1/lexicon state `name` (DEF, SPEC-ladder 6.2; see the stage 59 report)
                if s["m"].get("type") == "proper":
                    return "type"
                if not s["m"].get("type") and s["lexeme"] in name_lexemes:
                    return "lexicon"
                return ""

            idx, chains = defaultdict(list), defaultdict(list)
            ts = sorted(part.words)
            for i, t in enumerate(ts):
                w = part.words[t]
                ps = part.pieces[t]
                st = [p for p in ps if p["kind"] == "stem"]
                if len(st) != 1 or st[0]["class"] != "noun" or not L.strict_who(st[0]):
                    continue
                s = st[0]
                if any(p["kind"] == "suffix" for p in ps) or any(p["fused"] for p in ps):
                    continue
                if s["m"].get("state", "abs") not in ("abs", ""):
                    # NF2-CHAIN: a construct head with no prefix, then a proper name of one stem, no prefix or suffix,
                    # in the same verse; the rectum may not be verse-final or carry the atnach
                    if s["m"].get("state") != "cstr" or any(p["kind"] == "prefix" for p in ps) or i + 1 >= len(ts):
                        continue
                    t2 = ts[i + 1]
                    w2, ps2 = part.words[t2], part.pieces[t2]
                    if (w2["book"], w2["chapter"], w2["verse"]) != (w["book"], w["chapter"], w["verse"]) or pausal(w2):
                        continue
                    if len(ps2) != 1 or ps2[0]["kind"] != "stem" or ps2[0]["class"] != "noun" or ps2[0]["fused"]:
                        continue
                    if ps2[0]["m"].get("state", "abs") not in ("abs", "") or not proper_of(ps2[0]):
                        continue
                    for e in L.ents(s["who"]):
                        chains[e].append((t, w["book"], w["chapter"], [[s], [ps2[0]]], w["after"]))
                    continue
                if pausal(w):
                    continue
                art = [p for p in ps if p["kind"] == "prefix" and p["class"] == "art"]
                pcs = art[-1:] + [s]
                ntext = "".join(p["text"] for p in pcs)
                proper = proper_of(s)
                for e in L.ents(s["who"]):
                    idx[e].append((t, w["book"], w["chapter"], ntext, pcs, proper))
            self.idx[name] = idx
            self.chains[name] = chains

    @staticmethod
    def _pcs(ps):
        return [{"text": p["text"], "kind": p["kind"], "lexeme": p["lexeme"], "class": p["class"],
                 "marks": p["marks"], "m": p["m"]} for p in ps]

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
        if best_c is None:
            # NF2-CHAIN (OPEN 4): the nearest construct chain of the chapter before a name of another chapter
            ch = None
            for r in self.chains.get(part_name, {}).get(ent, ()):
                if r[0] >= head_t:
                    break
                if r[1] == book and r[2] == chapter:
                    ch = r
            if ch is not None:
                words = [self._pcs(ws) for ws in ch[3]]
                head = words[0][-1]
                return {"text": " ".join("".join(p["text"] for p in ws) for ws in words), "words": words,
                        "pieces": words[0] + words[1], "first_after": ch[4], "definite": True, "proper": True,
                        "proper_by": "chain", "tier": "nf_chain", "at": ch[0], "number": head["m"].get("number", ""),
                        "head_text": head["text"], "head_lexeme": head["lexeme"]}
        r, tier = (best_c, "nf_chapter") if best_c else (best_b, "nf_book")
        if r is None:
            return None
        pcs = self._pcs(r[4])
        return {"text": r[3], "words": [pcs], "pieces": pcs, "first_after": None, "definite": bool(r[5]) or len(pcs) > 1,
                "proper": bool(r[5]), "proper_by": r[5], "tier": tier, "at": r[0], "number": pcs[-1]["m"].get("number", ""),
                "head_text": pcs[-1]["text"], "head_lexeme": pcs[-1]["lexeme"]}


def name_words(T, nf, ent, links, tmp, pre=()):
    """the word(s) of a written name: one word, or the two words of a construct chain (NF2-CHAIN); `pre` (copied
    prefix pieces) go on the first word"""
    out = []
    for i, ws in enumerate(nf["words"]):
        pcs = [L.new_piece(p, ent, "inserted", list(links)) for p in ws]
        if i == 0 and pre:
            pcs = [dict(q) for q in pre] + pcs
        after = None
        if i == 0 and len(nf["words"]) > 1 and T.code == "hbo" and nf["first_after"] == "־":
            after = "־"
        out.append({"pieces": pcs, "op": tmp, "after": after})
    return out


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
    return nf["number"]


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
                reason = host_kind_art(D.cur_stem.get(t) or stp, part.pieces[t])
                rule = "r_subject"
                if not reason and X["syn"].rel_same(pn, part, t, es[0]):
                    reason = "relative_head"            # REL (OPEN 1)
                elif not reason and X["syn"].before_same(pn, part, t, es[0]):
                    reason = "name_just_before"         # REL-ASYN (OPEN 1)
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
            elif named_before(part, t, nf):
                reason = "named_in_clause"              # NIC-FORM (OPEN 6)
            elif not nf["definite"]:
                reason = "indefinite"
            elif num_mismatch(head_m.get("number", ""), nf, es[0]):
                reason = "number_mismatch"              # NUM both ways (OPEN 3, 4)
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
        if ok is not True:
            op["reason"] = ok or "form_unattested"
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
        written = name_words(T, nf, ent, [head_link + ("insert",)], tmp)
        for nw in written:
            D.insert(t, 0, nw)
    elif rule == "r_pronoun":
        written = name_words(T, nf, ent, [head_link + ("replace",)], tmp, pre)
        D.body[t] = list(written)
        D.writer[t] = ("r", tmp)
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
            nws = name_words(T, nf, ent, [head_link + ("replace",)], tmp)
            D.body[t] = [fw] + nws
            D.writer[t] = ("r", tmp)
            written = [fw] + nws
        elif st["class"] == "prep":
            rule = "r_prep_bound"
            if len(nf["words"]) > 1:
                return "name_chain_bound"       # NF2-CHAIN (OPEN 4): a chain is not bound to a preposition
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
        nws = name_words(T, nf, ent, [head_link + ("replace",)], tmp)
        D.body[t] = [w1] + nws
        D.writer[t] = ("r", tmp)
        written = [w1] + nws
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
        nws = name_words(T, nf, ent, [head_link + ("insert",)], tmp)
        D.insert(t, 1, ow)
        for nw in nws:
            D.insert(t, 1, nw)
        written = [vw, ow] + nws
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


def fixed_phrase(syn, pn, part, t, p):
    """V-FIX (OPEN 8): the glossed word stands in a fixed formula with a divine name: it is not a finite verb (a noun,
    an adjective, a participle) and the next word of the verse is יהוה, אֱלֹהִים or אֵל with no prefix (בָּרוּךְ יְהוָה,
    עֶבֶד יְהוָה). A finite verb before the name (נִאֵץ יְהוָה) and other construct chains keep their gloss."""
    if p["class"] == "verb" and p["m"].get("type", "") not in L.PARTICIPLE:
        return False
    w = part.words[t]
    vs = syn.verse[pn][(w["book"], w["chapter"], w["verse"])]
    i = vs.index(t)
    if i + 1 < len(vs):
        nxt = part.pieces[vs[i + 1]]
        st = [q for q in nxt if q["kind"] == "stem"]
        if st and strong(st[0]["lexeme"]) in DIVINE and not any(q["kind"] == "prefix" for q in nxt):
            return True
    return False


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
        elif setting == "all" and (r["src_count"] or 0) >= V_COMMON:
            reason = "common"                   # V-COUNT (OPEN 8)
        elif setting == "all" and fixed_phrase(X["syn"], pn, part, t, p):
            reason = "fixed_phrase"             # V-FIX (OPEN 8)
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

def a_mends(syn, pn, part, r, st, ent, subj):
    """the A rules of 2026-11-25, in this order -> reason or ''.
    subject: REL (OPEN 1) `relative_head`, REL-ASYN (OPEN 1) `name_just_before`; A-HAYAH (OPEN 7) `measure_hayah`.
    object (A-OBJ, OPEN 2, the narrowed `a_object`): `in_relative` (the verb heads a relative clause),
    `passive_stem` (not an active stem), `object_is_subject` (the name is the clause's subject: the verb's own ent or
    the subject row of `added`), `speech_person` (the ent is the speaker or the addressee in the verse)."""
    v = r["verb"]
    if subj:
        if syn.rel_same(pn, part, v, ent):
            return "relative_head"
        if syn.before_same(pn, part, v, ent):
            return "name_just_before"
        if hayah_measure(part, v, r["clause"]):
            return "measure_hayah"
        return ""
    if syn.antecedent(pn, part, v) is not None:
        return "in_relative"
    if st["m"].get("stem", "") in PASSIVE_STEMS:
        return "passive_stem"
    sr = part._subj_role[(v, r["clause"])]
    if ent in L.ents(st["who"]) or any(x["verb"] == v and x["clause"] == r["clause"] and x["role"] == sr
                                       and ent in L.ents(x["who"]) for x in part.added):
        return "object_is_subject"
    if syn.speech_person(pn, part, v, ent):
        return "speech_person"
    return ""


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
            reason = host_kind_art(D.cur_stem.get(r["verb"]) or st, part.pieces[r["verb"]])     # FIN, FIN-ART (OPEN 5)
        if not reason:
            reason = a_mends(X["syn"], pn, part, r, st, es[0], subj)
        if not reason:
            nf = X["names"].nf2(pn, es[0], r["verb"], w["book"], w["chapter"])
            if nf is None:
                reason = "no_earlier_name"
            elif not nf["definite"]:
                reason = "indefinite"
            else:
                num = (D.cur_stem.get(r["verb"]) or st)["m"].get("number", "") if subj else r["number"]
                if num_mismatch(num, nf, es[0]):
                    reason = "number_mismatch"          # NUM both ways (OPEN 3, 4)
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
        nws = name_words(T, nf, es[0], [link], tmp)
        if subj:
            for nw in nws:
                D.insert(r["verb"], 0, nw)
            written, rule = nws, "a_subject"
        else:
            omp = [L.new_piece(q, "", "", [link]) for q in ff[1] if q["role"] == "stem"]
            ow = {"pieces": omp, "op": tmp, "after": "־" if T.code == "hbo" else None}
            D.insert(r["verb"], 1, ow)
            for nw in nws:
                D.insert(r["verb"], 1, nw)
            written, rule = [ow] + nws, "a_object"
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
         "info": Counter(), "syn": Syntax(parts)}
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
