"""Labels a probe clause needs beyond the clause scheme's own (grammar probes, the coverage of research's 17
features): the kind of a noun and of a verb, the frame a clause is said in, how many a plural covers, and the
inclusive or exclusive "we" carried to the Hebrew words. And a check of how right the sure clauses are.

  cd shoresh && .venv/bin/python -I macula/probe_labels.py build     # both editions: kinds, frames, plural_size, we
  cd shoresh && .venv/bin/python -I macula/probe_labels.py sure      # the Tanakh's test chapters by sureness

Written per edition into data/probe-labels/<edition>/ (parquet) with CHECKS.json. Keys are hebrew-nt-analysis's:
book, chapter, verse, i, part; a clause is the clause scheme's id.

kinds        one row per noun or verb part that stands for a Greek word with a UBS domain, or has an entity kind.
             `kind` is a Hebrew head word: for nouns אָדָם, מִשְׁפָּחָה, עַם, אֱלֹוהַּ, גּוּף, חַיָּה, צֶמַח, מַאֲכָל, כְּלִי,
             בִּנְיָן, מָקוֹם, חֹמֶר, and עִנְיָן for a noun of an event or abstract domain; for verbs אֲמִירָה, תְּנוּעָה, הֲוָיָה.
             The kind is the Greek word's at this very place (its UBS domain, through lexeme-aligner's links kept in
             the build): a reading of the place, not of the lexeme. `kind_basis`: greek_domain | entity (the entity
             kind of hebrew-nt-analysis at this place, used where the Greek gives no kind, and for beings the Greek
             files under an event: a teacher, a king) | entity_lexeme (no entity here, but the lexeme names a being
             in four of five places where one is known, at least five). `domain`, `greek`, `greek_class`, `link_basis`, `entity_kind` say where
             it came from.
frames       one row per clause: `frame` quotation | letter | none; speakers and hearers as entity ids, the hearers'
             kind and number, `basis` (the speech layer's, or `opening` for a letter: letter_frames.toml).
plural_size  one row per plural pronoun, suffix or verb whose number of referents the text states: `size` 2 | 3 |
             more; `basis` numeral_own (the numeral in the same word, שְׁנֵיהֶם), numeral (in one phrase with the
             antecedent), names (the antecedent is one of several names joined by וְ, and nothing more is joined to
             them). Third person only, and only an antecedent in the same verse or the one before, linked or of
             calibrated sureness 0.9 and more. Few rows: the text seldom says it.
we           one row per first person plural part: the inclusive-we layer's value for the Greek word it stands for
             (`carried_by` linked) or, without a link, for its verse when the verse has one value (`verse`).
             `source_key` is the Greek word's key: with it the value without a voting edition is read from the
             layer's `without` table (a language under test must not sit among its own voters).
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
import tomllib
import unicodedata
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyarrow as pa
import pyarrow.parquet as pq

from macula import clause_scheme as CS
from macula import hebrew_nt_clauses as N

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SPEECH = DATA / "hebrew-nt-speech" / "2026-11-26b"
WE = DATA / "we-layer" / "words.tsv"
OUT = DATA / "probe-labels"
EDITIONS = ("heb_scg", "heb_mod")
NF = lambda s: unicodedata.normalize("NFC", s)  # noqa: E731

# the Greek UBS domains (first three digits) that name a kind of thing
NOUN_KIND = {"001": "מָקוֹם", "002": "חֹמֶר", "003": "צֶמַח", "004": "חַיָּה", "005": "מַאֲכָל", "006": "כְּלִי",
             "007": "בִּנְיָן", "008": "גּוּף", "009": "אָדָם", "010": "מִשְׁפָּחָה", "011": "עַם", "012": "אֱלֹוהַּ"}
OTHER_NOUN = "עִנְיָן"
VERB_KIND = {"013": "הֲוָיָה", "015": "תְּנוּעָה", "016": "תְּנוּעָה", "033": "אֲמִירָה"}
ENTITY_KIND = {"person": "אָדָם", "realia": "כְּלִי", "place": "מָקוֹם", "group": "עַם", "fauna": "חַיָּה",
               "flora": "צֶמַח", "deity": "אֱלֹוהַּ"}
BEINGS = ("אָדָם", "אֱלֹוהַּ", "עַם")
TWO, THREE = ("8147",), ("7969", "7969a", "7970")
TWO_OF = ("שני", "שתי")
MORE = ("0702", "0705", "2568", "2572", "8337", "8346", "7651", "7657", "8083", "8084", "8672", "8673", "6235", "6240",
        "6242", "3967", "0505", "7239")                              # the numbers from four up
ORDINAL = ("י", "ית")                                                # שְׁלִישִׁי, שְׁלִישִׁית: no count
MIN_REFERENT = 0.9                                                   # a model's antecedent counts from this calibrated sureness


def rows(path, columns=None):
    return pq.read_table(path, columns=columns).to_pylist()


def write(path, table, cols):
    path.parent.mkdir(parents=True, exist_ok=True)
    types = {"chapter": pa.int64(), "verse": pa.int64(), "i": pa.int64(), "part": pa.int64(), "n_i": pa.int64(),
             "n_e": pa.int64(), "agree": pa.float64()}
    pq.write_table(pa.table({c: pa.array([r.get(c) for r in table], type=types.get(c, pa.string())) for c in cols}), path)


class Edition:
    """an edition's words with their features, tree pieces, referents, speech and Greek links"""

    def __init__(self, ed):
        self.ed = ed
        self.words = [w for w in rows(N.ANALYSIS / ed / "words.parquet") if w["class"] != "verse-number"]
        key = lambda r: (r["book"], r["chapter"], r["verse"], r["i"], r["part"])  # noqa: E731
        self.key = key
        self.feat = {key(r): r for r in rows(N.FEATURES / ed / "features.parquet")}
        self.piece = {key(r): r for r in rows(N.LAYERS / ed / "pieces.parquet")}
        self.ref = {key(r): r for r in rows(N.REFERENTS / ed / "referents.parquet")}
        self.speech = {(r["book"], r["chapter"], r["verse"], r["seg"]): r for r in rows(SPEECH / ed / "speech.parquet")}
        self.by_word = collections.defaultdict(list)
        self.by_verse = collections.defaultdict(list)
        for w in self.words:
            self.by_word[(w["book"], w["chapter"], w["verse"], w["i"])].append(w)
            self.by_verse[(w["book"], w["chapter"], w["verse"])].append(w)
        # the build's word numbers and its links to the Greek words
        self.t_of = {(r["book"], r["chapter"], r["verse"], r["w"]): r["t"] for r in rows(N.K1 / ed / "words.parquet")}
        self.links = collections.defaultdict(list)
        for r in rows(N.K1 / ed / "links.parquet"):
            if r["other"] == "grc":
                self.links[(r["t"], r["n"])].append(r)

    def F(self, w, k):
        return (self.feat.get(self.key(w)) or {}).get(k) or ""

    def greek(self, w):
        """the Greek words a part is linked to, a checked link first"""
        t = self.t_of.get((w["book"], w["chapter"], w["verse"], w["i"] + 1))
        return sorted(self.links.get((t, w["part"] + 1)) or [], key=lambda l: l["basis"] != "linked")


def greek_side():
    """Greek word number -> (id, UBS domain, class, entity ids) of its stem piece; and the Greek words by place"""
    gw = {r["t"]: r for r in rows(N.K1 / "grc" / "words.parquet")}
    g = {}
    for r in rows(N.K1 / "grc" / "pieces.parquet"):
        if r["kind"] == "stem":
            w = gw[r["t"]]
            g[r["t"]] = {"id": w["id"], "domain": r["domain"] or "", "class": r["class"], "who": r["who"] or "",
                         "lexeme": r["lexeme"], "book": w["book"], "chapter": w["chapter"], "verse": w["verse"]}
    return g


# ---------------------------------------------------------------- kinds
def kinds(E, G, n):
    out = []
    seen = collections.defaultdict(collections.Counter)             # noun lexeme -> entity kinds of its tokens
    for w in E.words:
        if w["class"] == "noun" and w["strong"]:
            ek = (E.piece.get(E.key(w)) or {}).get("who_kind") or "-"
            if ek != "-":
                seen[w["strong"]][ENTITY_KIND[ek]] += 1
    being = {}                                                       # a lexeme that names a being in 4 of 5 known tokens
    for lex, c in seen.items():
        k, m = c.most_common(1)[0]
        if k in BEINGS and sum(c.values()) >= 5 and m / sum(c.values()) >= 0.8:
            being[lex] = k
    for w in E.words:
        if w["class"] not in ("noun", "verb"):
            continue
        ek = (E.piece.get(E.key(w)) or {}).get("who_kind") or ""
        ek = "" if ek == "-" else ek
        ls = [(G[l["s"]], l) for l in E.greek(w) if l["s"] in G and G[l["s"]]["domain"]]
        ls.sort(key=lambda x: x[0]["class"] != w["class"])           # a Greek word of the same class first
        cls = w["class"]
        n[f"{cls}s"] += 1
        g, l = ls[0] if ls else (None, None)
        kind = basis = ""
        if g is not None:
            n[f"{cls}s with a Greek domain"] += 1
            if cls == "noun" and g["class"] == "noun":
                kind, basis = NOUN_KIND.get(g["domain"][:3], OTHER_NOUN), "greek_domain"
            elif cls == "verb" and g["class"] == "verb":
                kind, basis = VERB_KIND.get(g["domain"][:3], ""), "greek_domain"
        if cls == "noun" and ek:
            e = ENTITY_KIND[ek]
            if kind and kind != OTHER_NOUN:
                n["nouns with both kinds"] += 1
                n["nouns with both kinds, the same"] += kind == e or {kind, e} <= {"אָדָם", "מִשְׁפָּחָה", "עַם"}
            if not kind or (kind == OTHER_NOUN and e in BEINGS):
                kind, basis = e, "entity"
        if cls == "noun" and kind in ("", OTHER_NOUN) and w["strong"] in being and (kind or g is None or g["class"] == "noun"):
            kind, basis = being[w["strong"]], "entity_lexeme"
        if not kind and g is None:
            continue
        if kind:
            n[f"{cls}s with a kind"] += 1
            n[f"{cls} kind {kind}"] += 1
            n[f"{cls} kind by {basis}"] += 1
        out.append({"book": w["book"], "chapter": w["chapter"], "verse": w["verse"], "i": w["i"], "part": w["part"],
                    "class": cls, "kind": kind or None, "kind_basis": basis or None,
                    "domain": g["domain"] if g else None, "greek": g["id"] if g else None,
                    "greek_class": g["class"] if g else None, "link_basis": l["basis"] if l else None,
                    "entity_kind": ENTITY_KIND.get(ek)})
    return out


# ---------------------------------------------------------------- frames
def letter_frames(G):
    """book -> (writers' entity ids, readers' entity ids, readers' number), names resolved in the opening's verses"""
    spec = tomllib.loads((HERE / "letter_frames.toml").read_text(encoding="utf-8"))
    names = collections.defaultdict(dict)
    for g in G.values():
        if g["chapter"] == 1 and g["book"] in spec and spec[g["book"]]["verses"][0] <= g["verse"] <= spec[g["book"]]["verses"][1]:
            ids = [x for x in g["who"].split() if x.startswith("person:")]
            if len(ids) == 1:
                names[g["book"]].setdefault(NF(g["lexeme"].split(":", 2)[2]), ids[0])
    out = {}
    for book, s in spec.items():
        got = {}
        for side in ("from", "to"):
            got[side] = []
            for name in s[side]:
                if NF(name) not in names[book]:
                    raise SystemExit(f"letter_frames.toml: {name} is not a named person in {book} 1:{s['verses']}")
                got[side].append(names[book][NF(name)])
        out[book] = (got["from"], got["to"], s["to_number"])
    return out


def frames(E, G, n):
    letters = letter_frames(G)
    S = CS.SCHEME_OUT / "nt" / E.ed
    first_seg = {}
    for r in rows(S / "segments.parquet"):
        first_seg.setdefault(r["clause"], r)
    out = []
    for c in rows(S / "clauses.parquet", ["clause", "book", "chapter", "verse"]):
        sg = first_seg[c["clause"]]
        sp = E.speech.get((c["book"], c["chapter"], c["verse"], sg["seg"]))
        r = {"clause": c["clause"], "frame": "none", "quote": None, "speakers": None, "hearers": None,
             "hearer_kind": None, "hearer_number": None, "basis": None}
        if sp and sp["quote"]:
            r.update(frame="quotation", quote=sp["quote"], speakers=sp["speaker"] or None, hearers=sp["addressee"] or None,
                     hearer_kind=ENTITY_KIND.get((sp["addressee"] or "").split(":")[0]),
                     hearer_number=sp["addressee_number"] or None, basis=sp["speech_basis"] or None)
        elif c["book"] in letters:
            fr, to, num = letters[c["book"]]
            r.update(frame="letter", speakers=" ".join(fr) or None, hearers=" ".join(to) or None,
                     hearer_kind="אָדָם" if num == "singular" else "עַם", hearer_number=num, basis="opening")
        n[f"clauses, frame {r['frame']}"] += 1
        n["clauses with a hearer or the hearers' number"] += bool(r["hearers"] or r["hearer_number"])
        out.append(r)
    return out


# ---------------------------------------------------------------- how many a plural covers
def plural_size(E, n):
    def numeral(ws):
        for w in ws:
            if w["class"] != "num" or NF(w["lemma"] or "").endswith(ORDINAL):
                continue
            if w["strong"] in TWO or w["token"] in TWO_OF:           # שְׁנֵי, שְׁתֵּי: at times filed under שָׁנָה below
                return "2"
            return "3" if w["strong"] in THREE else "more" if w["strong"] in MORE else None
        return None

    def starts_and(book, ch, vs, j):                                 # word j begins with וְ
        ws = E.by_word.get((book, ch, vs, j), ())
        return bool(ws) and ws[0]["class"] == "cj" and ws[0]["strong"] == "2050b"

    def more_joined(book, ch, vs, i, reach=4):
        """a further noun or phrase joined by וְ within the next words: the group is larger than the phrase at i"""
        for j in range(i + 1, i + 1 + reach):
            ws = E.by_word.get((book, ch, vs, j), ())
            if starts_and(book, ch, vs, j) and not any(x["class"] == "verb" for x in ws):
                return True
        return False

    def names_run(book, ch, vs, i):
        """the names joined by וְ around word i: how many"""
        def is_name(j):
            return any(w["class"] == "noun" and E.F(w, "definite") == "name" for w in E.by_word.get((book, ch, vs, j), ()))

        def joined(j):
            return starts_and(book, ch, vs, j)
        if not is_name(i):
            return 0
        k, hi = 1, i
        while is_name(hi + 1) and joined(hi + 1):
            k, hi = k + 1, hi + 1
        lo = i
        while joined(lo) and is_name(lo - 1):
            k, lo = k + 1, lo - 1
        if joined(lo) or joined(hi + 1):                             # a further member the rule cannot count
            return 0
        return k

    def numeral_of(book, ch, vs, ai):
        """a numeral in one phrase with word ai: its tree head is that word, or that word's head is the numeral"""
        heads = {x["part"]: (E.piece.get(E.key(x)) or {}).get("head_i") for x in E.by_word.get((book, ch, vs, ai), ())}
        if more_joined(book, ch, vs, ai):
            return None
        for j in (ai - 1, ai + 1, ai - 2, ai + 2):
            for x in E.by_word.get((book, ch, vs, j), ()):
                if x["class"] != "num":
                    continue
                hx = (E.piece.get(E.key(x)) or {}).get("head_i")
                if hx == ai + 1 or (j + 1) in heads.values():        # head_i counts words from 1
                    return numeral([x])
        # the antecedent is the numeral itself, said of a group: שְׁנַיִם מֵהֶם
        nxt = E.by_word.get((book, ch, vs, ai + 1), ())
        if nxt and nxt[0]["class"] == "prep" and nxt[0]["strong"] == "4480":
            return numeral([x for x in E.by_word.get((book, ch, vs, ai), ()) if x["class"] == "num"])
        return None

    out = []
    for w in E.words:
        if w["class"] not in ("pron", "verb") or E.F(w, "number") != "plural":
            continue
        n["plural pronouns, suffixes and verbs"] += 1
        key = E.key(w)
        size = basis = None
        own = numeral([x for x in E.by_word[key[:4]] if x is not w])
        if own in ("2", "3") and w["class"] == "pron":
            size, basis = own, "numeral_own"
        r = E.ref.get(key)
        third = (E.F(w, "person") or w.get("person") or "") == "third"
        if size is None and third and r and r["antecedent_i"] is not None and r["antecedent_verse"]:
            ch, vs = (int(x) for x in r["antecedent_verse"].split(":"))
            sure_ref = r["referent_basis"] == "linked" or (r["referent_p_calibrated"] or 0) >= MIN_REFERENT
            near = ch == w["chapter"] and 0 <= w["verse"] - vs <= 1
            if not sure_ref or not near:
                n["antecedent unsure or further than one verse back (no size)"] += 1
            else:
                ai = r["antecedent_i"]
                num = numeral_of(w["book"], ch, vs, ai)
                k = names_run(w["book"], ch, vs, ai)
                if num:
                    size, basis = num, "numeral"
                elif k >= 2:
                    size, basis = ("2" if k == 2 else "3" if k == 3 else "more"), "names"
        if size:
            n[f"size {size}"] += 1
            n[f"size by {basis}"] += 1
            out.append({"book": w["book"], "chapter": w["chapter"], "verse": w["verse"], "i": w["i"], "part": w["part"],
                        "class": w["class"], "size": size, "basis": basis, "referent": (r or {}).get("referent")})
    return out


# ---------------------------------------------------------------- "we"
def we(E, G, n):
    layer = {}
    by_verse = collections.defaultdict(set)
    for r in csv.DictReader(open(WE, encoding="utf-8"), delimiter="\t"):
        if r["lang"] == "grc":
            layer["n" + r["key"]] = r
            by_verse[(r["book"], int(r["chapter"]), int(r["verse"]))].add(r["key"])
    out = []
    for w in E.words:
        if E.F(w, "person") != "first" or E.F(w, "number") != "plural":
            continue
        n["first person plural parts"] += 1
        hit = [layer[G[l["s"]]["id"]] for l in E.greek(w) if l["s"] in G and G[l["s"]]["id"] in layer]
        how = "linked"
        if not hit:
            keys = by_verse.get((w["book"], w["chapter"], w["verse"]), ())
            vals = {layer["n" + k]["value"] for k in keys}
            if len(vals) != 1:
                n["no value: no link" + (", verse has several values" if vals else ", verse has no Greek we")] += 1
                continue
            hit, how = [layer["n" + sorted(keys)[0]]], "verse"
        r = hit[0]
        n[f"carried by {how}"] += 1
        n[f"value {r['value']}"] += 1
        out.append({"book": w["book"], "chapter": w["chapter"], "verse": w["verse"], "i": w["i"], "part": w["part"],
                    "value": r["value"], "alternative": r["alternative"] or None, "basis": r["basis"] or None,
                    "n_i": int(r["n_i"]), "n_e": int(r["n_e"]), "agree": float(r["agree"]) if r["agree"] else None,
                    "source_key": r["key"], "carried_by": how})
    return out


def build(editions):
    G = greek_side()
    for ed in editions:
        E, checks = Edition(ed), {}
        for name, fn, cols in (
                ("kinds", lambda n: kinds(E, G, n), ["book", "chapter", "verse", "i", "part", "class", "kind", "kind_basis",
                                                     "domain", "greek", "greek_class", "link_basis", "entity_kind"]),
                ("frames", lambda n: frames(E, G, n), ["clause", "frame", "quote", "speakers", "hearers", "hearer_kind",
                                                       "hearer_number", "basis"]),
                ("plural_size", lambda n: plural_size(E, n), ["book", "chapter", "verse", "i", "part", "class", "size",
                                                              "basis", "referent"]),
                ("we", lambda n: we(E, G, n), ["book", "chapter", "verse", "i", "part", "value", "alternative", "basis",
                                               "n_i", "n_e", "agree", "source_key", "carried_by"])):
            n = collections.Counter()
            table = fn(n)
            write(OUT / ed / f"{name}.parquet", table, cols)
            checks[name] = {"rows": len(table), **{k: v for k, v in sorted(n.items())}}
        (OUT / ed / "CHECKS.json").write_text(json.dumps(checks, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(ed, json.dumps(checks, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- how right the sure clauses are
def sure(plain, split="test"):
    """The Tanakh's test chapters, the clause layout's cut, the tagger's own tree and head role (as the New Testament
    is read): a short clause's sureness is the lowest among its constituents' (head sureness times relation
    sureness; the head role's for the clause's head). Per threshold: the clauses kept, how many of those have every
    constituent right, and the constituents' precision; and each of the tagger's marks by its own sureness."""
    L = CS.layers()
    wd, sent, clauses, cons = CS.tanakh()
    meta = {p["key"]: p for parts in sent.values() for p in parts}
    by_ref = collections.defaultdict(list)
    for w in wd.values():
        by_ref[f"{w['book']} {w['chapter']}:{w['verse']}"].append(w)
    model, bat, device, ck = L.load_model(plain)
    data = L.load(split, plain)
    pred = L.predict(model, bat, data, device)
    T = (0.0, 0.5, 0.7, 0.8, 0.9, 0.95)
    cl, rw, mk = [], [], collections.defaultdict(list)             # (sureness, all right), (sureness, right), mark -> same
    for v, pr in zip(data, pred):
        ws = sorted(by_ref[v["ref"]], key=lambda w: w["w"])
        order = []
        for w in ws:
            order.extend(sorted(k for k in ((w["t"], i) for i in range(1, 12)) if k in meta))
        if len(order) != len(pr["pieces"]):
            continue
        seg_of = {}
        for j, c in enumerate(v["clauses"]):
            for wi in c["words"]:
                seg_of[ws[wi]["t"]] = j
        parts = []
        for i, k in enumerate(order):
            q = dict(meta[k])
            p = pr["pieces"][i]
            q["head"] = order[p["head"] - 1] if 0 < p["head"] <= len(order) and p["head"] - 1 != i else None
            q["rel"] = p["rel"] if p["rel"] not in ("-", "other") else ""
            q["head_p"], q["rel_p"] = p["head_p"], p["rel_p"]
            j = seg_of.get(k[0])
            q["depth"] = v["clauses"][j]["depth"] if j is not None else 0
            parts.append(q)
        tree = CS.Tree(parts)
        group = list(range(len(v["clauses"])))
        for j, c in enumerate(v["clauses"]):
            x = c["marks"]["continues"]
            if x not in ("none", "-", "other") and j - int(x.strip("-+")) >= 0:
                group[j] = group[j - int(x.strip("-+"))]
        for j0 in sorted(set(group)):
            segs = [j for j in range(len(group)) if group[j] == j0]
            c0 = v["clauses"][j0]
            if c0["k1"] not in clauses or len(segs) != 1 or not 2 <= len(c0["words"]) <= 6:
                continue
            own = [k for k in order if seg_of.get(k[0]) in segs]
            said = pr["clauses"][j0] or {}
            hr = said.get("head_role", ("none", 0.0))
            pd, pk, drows = CS.derive(tree, own, "", c0["depth"], head_role=hr[0])
            gold = collections.Counter((r["role"], r["head"]) for r in cons.get(c0["k1"], []))
            ps = []
            for r in drows:
                q = tree.parts[r["part"]]
                p = (q.get("head_p") or 0) * (q.get("rel_p") or 0) if r["basis"] == "relation" else (hr[1] or 0)
                ps.append(p)
                rw.append((p, gold.get((r["role"], r["head"]), 0) > 0))
            d = collections.Counter((r["role"], r["head"]) for r in drows)
            cl.append((min(ps) if ps else 0.0, d == gold))
            gm = c0["marks"]
            if gm.get("kind") != "-":
                for k, x in said.items():
                    if k in gm and k not in ("head_role", "continues") and isinstance(x, (tuple, list)) and x[1] is not None:
                        mk[k].append((x[1], x[0] == gm[k]))
    res = {"text": "without points" if plain else "pointed", "short clauses": len(cl), "constituents": len(rw),
           "by clause sureness": {}, "by constituent sureness": {}, "marks by their own sureness": {}}
    for t in T:
        a = [ok for p, ok in cl if p >= t]
        res["by clause sureness"][str(t)] = {"kept": round(len(a) / max(len(cl), 1), 4), "clauses": len(a),
                                            "every constituent right": round(sum(a) / max(len(a), 1), 4)}
        b = [ok for p, ok in rw if p >= t]
        res["by constituent sureness"][str(t)] = {"kept": round(len(b) / max(len(rw), 1), 4),
                                                 "right": round(sum(b) / max(len(b), 1), 4)}
    for k, xs in sorted(mk.items()):
        res["marks by their own sureness"][k] = {str(t): [round(len([1 for p, ok in xs if p >= t]) / max(len(xs), 1), 3),
                                                         round(sum(ok for p, ok in xs if p >= t) / max(len([1 for p, ok in xs if p >= t]), 1), 4)]
                                                 for t in T}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"sure-{'unpointed' if plain else 'pointed'}-{split}.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "sure"])
    ap.add_argument("--editions", default=",".join(EDITIONS))
    ap.add_argument("--plain", action="store_true")
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.editions.split(","))
    else:
        sure(a.plain)


if __name__ == "__main__":
    main()
