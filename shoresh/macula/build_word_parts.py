#!/usr/bin/env python3
"""Every source word cut into its parts (make-tanakh-research's packet 17; production's preparation plan, section 5.1,
`src_part`): Greek NT words into preverb, augment, reduplication, stem and ending; Hebrew words read from MACULA's own
morphemes. Keyed by MACULA ids. Unpublished; two routes are built so that the licence can be chosen at the end:

  route a  rules over MACULA alone (CC BY 4.0). The stem is what stays the same across a lexeme's forms in the NT, per
           principal part (Morpheus's convention: σάρξ = σαρ + ξ, σαρ + κος); the ending is what varies. The endings a
           parse allows are learned from the lexemes with several forms; preverbs are found from the lemma (the rest is
           another NT verb, or an augmented form shows the augment inside); augment and reduplication by tense.
  route b  route a, plus MorphGNT's morphological lexicon (preverb analyses, ending paradigms) and Perseus Morpheus's
           noun stems, both CC BY-SA 3.0, so its output is share-alike.

    cd shoresh && .venv/bin/python3 -m macula.build_word_parts --route a|b [--out DIR] [--grc DIR] [--morph DIR]

Outputs in DIR (default ../internal-docs/word-parts/<route>/):
  src_part_grc.tsv   key, n, text, kind, features (one row per part; the parts of a word rebuild its surface exactly)
  src_part_hbo.tsv   key (the written word, 11 digits), n, token (MACULA's 12-digit morpheme id), text, kind, features
  words_grc.tsv      key, surface, lemma, morph, group, cut, flags (one row per word; for audits)
  checks.md          the acceptance figures; sample_200.tsv  a sample to read by hand; build.json  sources and route
Kinds: preverb, augment, reduplication, stem, ending, particle (a function word or a Hebrew prefix), suffix (a Hebrew
pronominal suffix). A temporal augment or reduplication (a lengthened vowel) cannot be cut; the stem carries it as a
feature. Tense formants (σ, θη, κ, ...) stay in the stem of their principal part: the stem is per lexeme and principal
part."""
import argparse, collections, hashlib, json, os, random, re, sqlite3, sys, time, unicodedata as ud
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRC_DIR = HERE / ".lowfat-src-grc"
MORPH_DIR = Path(os.environ.get("GRC_MORPH_DIR", Path.home() / "dev/make-tanakh-research/external/grammar-data/grc"))
XID = "{http://www.w3.org/XML/1998/namespace}id"

# ---------------------------------------------------------------------------------------------------------- letters
def graphemes(s):
    out = []
    for ch in ud.normalize("NFD", s):
        if ud.combining(ch) and out:
            out[-1] += ch
        else:
            out.append(ch)
    return out


SUBSCRIPT = {"α": "ᾳ", "η": "ῃ", "ω": "ῳ"}


def gplain(g):
    """one plain character per grapheme: lower case, no accents or breathings, final sigma as σ; a vowel with iota
    subscript stays one character (ᾳ ῃ ῳ), so that a cut never falls inside a letter"""
    b = g[0].lower()
    b = "σ" if b == "ς" else b
    return SUBSCRIPT.get(b, b) if "\u0345" in g else b


def plain(s):
    return "".join(gplain(g) for g in graphemes(s))


def nfc(gs):
    return ud.normalize("NFC", "".join(gs))


VOWELS = set("αεηιουωᾳῃῳ")
LONG = {"α": ["η"], "ε": ["η", "ει"], "ο": ["ω"], "αι": ["ῃ"], "ει": ["ῃ"], "οι": ["ῳ"], "αυ": ["ηυ"], "ευ": ["ηυ"],
        "ι": ["ι"], "υ": ["υ"]}
DEASP = {"φ": "π", "θ": "τ", "χ": "κ"}

PREVERB = {"αμφι": ["αμφι", "αμφ"], "ανα": ["ανα", "αν"], "αντι": ["αντι", "αντ", "ανθ"], "απο": ["απο", "απ", "αφ"],
           "δια": ["δια", "δι"], "εισ": ["εισ"], "εκ": ["εκ", "εξ"], "εν": ["εν", "εμ", "εγ", "ελ"],
           "επι": ["επι", "επ", "εφ"], "κατα": ["κατα", "κατ", "καθ"], "μετα": ["μετα", "μετ", "μεθ"],
           "παρα": ["παρα", "παρ"], "περι": ["περι"], "προ": ["προ"], "προσ": ["προσ"],
           "συν": ["συν", "συμ", "συγ", "συλ", "συσ", "συ", "συρ"], "υπερ": ["υπερ"], "υπο": ["υπο", "υπ", "υφ"]}
VARIANT_OF = {v: p for p, vs in PREVERB.items() for v in vs}
ELIDED = {"αμφ", "αν", "αντ", "ανθ", "απ", "αφ", "δι", "επ", "εφ", "κατ", "καθ", "μετ", "μεθ", "παρ", "υπ", "υφ"}


def variant_fits(v, rest):
    """the sound rules for a preverb variant before what follows"""
    if not rest:
        return False
    r0 = rest[0]
    if v in ELIDED:
        return r0 in VOWELS
    if v in ("εμ", "συμ"):
        return r0 in "βπφμψ"
    if v in ("εγ", "συγ"):
        return r0 in "γκχξ"
    if v in ("ελ", "συλ"):
        return r0 == "λ"
    if v == "συσ":
        return r0 == "σ"
    if v == "συ":
        return r0 in "σζ"
    if v == "συρ":
        return r0 == "ρ"
    if v == "εξ":
        return r0 in VOWELS
    if v == "εκ":
        return r0 not in VOWELS
    if v in ("εν", "συν"):
        return r0 not in "βπφμψγκχξλρ" or v == "εν" and r0 == "ρ"
    return True


# ---------------------------------------------------------------------------------------------------------- reading
def read_grc(d):
    words = []
    for f in sorted(d.glob("*.xml")):
        for el in ET.parse(f).getroot().iter("w"):
            words.append(dict(key=el.get(XID)[1:], surface=(el.text or "").strip(), lemma=el.get("lemma") or "",
                              cls=el.get("class") or "", morph=el.get("morph") or "", strong=el.get("strong") or "",
                              tense=el.get("tense"), voice=el.get("voice"), mood=el.get("mood"),
                              person=el.get("person"), number=el.get("number"), case=el.get("case"),
                              gender=el.get("gender"), after=el.get("after") or "", wtype=el.get("type")))
    return words


def vletter(w):
    m = re.match(r"V-2?[PIFARLX]([AMPEDON])", w["morph"])
    return m.group(1) if m else ""


def passive_stem(w):
    """an aorist or future form on the passive stem: MACULA's voice, Robinson's P / O, or a deponent (D, N, E, M) whose
    form has the passive formant θη / θε / θω near its end (ἀπεκρίθη beside ἀπεκρίνατο, both "ADI")"""
    if w["tense"] not in ("aorist", "future"):
        return False
    vl = vletter(w)
    if w["voice"] == "passive" or vl in ("P", "O"):
        return True
    return vl in ("D", "N", "E", "M") and re.search("θ(η|ε|ω)", plain(w["surface"])[-8:]) is not None


def pp_of(w):
    t = w["tense"]
    if t in ("present", "imperfect"):
        return "P"
    if t == "future":
        return "FP" if passive_stem(w) else "F"
    if t == "aorist":
        return "AP" if passive_stem(w) else "A"
    if t in ("perfect", "pluperfect"):
        return "R" if vletter(w) in ("A", "") and w["voice"] == "active" else "RM"
    return "?"


def vgroup(w):
    if passive_stem(w):
        return "pass"
    return "act" if w["voice"] == "active" else "mp"


def pkey(w):
    """the parse an ending answers to"""
    if w["cls"] == "verb":
        m = w["mood"]
        if m == "participle":
            return ("ptc", w["tense"], vgroup(w), w["case"], w["number"], w["gender"])
        if m == "infinitive":
            return ("inf", w["tense"], vgroup(w))
        return ("fin", w["tense"], vgroup(w), m, w["person"], w["number"])
    return ("nom", w["case"], w["number"], w["gender"])


FUNCTION = {"conj", "prep", "ptcl", "intj"}
INDECLINABLE = re.compile(r"^[NA]-(PRI|NUI|LI|OI)\b")


# ---------------------------------------------------------------------------------------------------------- route b sources
def betacode(s):
    m = dict(zip("abgdezhqiklmncoprstufxyw", "αβγδεζηθικλμνξοπρστυφχψω"))
    out = []
    for ch in s.lower():
        if ch in m:
            out.append(m[ch])
        elif ch == "|" and out:
            out[-1] = SUBSCRIPT.get(out[-1], out[-1])
    return "".join(out)


def read_route_b(md):
    src = {}
    comp = {}
    p = md / "morphological-lexicon/projects/preverbs/verbs.txt"
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if "|" not in line or "@@@" in line:
            continue
        lem, an = line.split("|", 1)
        parts = [x.strip() for x in an.split("+")]
        if len(parts) > 1:
            comp[plain(lem.strip())] = [plain(x) for x in parts]
    src["compounds"] = comp
    # verb indicative endings by tense-voice
    TEN = {"P": "present", "I": "imperfect", "F": "future", "A": "aorist", "X": "perfect", "Y": "pluperfect"}
    VO = {"A": "act", "M": "mp", "P": "mp"}
    inv = collections.defaultdict(set)
    for line in (md / "morphological-lexicon/projects/principal_parts/ending-paradigms.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if ":" not in line:
            continue
        tv, ends = line.split(":", 1)
        tv = tv.strip()
        if len(tv) != 2 or tv[0] not in TEN:
            continue
        tense, vg = TEN[tv[0]], VO.get(tv[1], "mp")
        if tv[1] == "P" and tense in ("aorist", "future"):
            vg = "pass"
        for (per, num), e in zip([("first", "singular"), ("second", "singular"), ("third", "singular"), ("first", "plural"),
                                  ("second", "plural"), ("third", "plural")], ends.split(",")):
            for x in re.findall(r"[^\s/]+", e.strip()):
                base = plain(x.replace("(ν)", "").replace("(", "").replace(")", ""))
                inv[("fin", tense, vg, "indicative", per, num)].add(base)
                if "(ν)" in x:
                    inv[("fin", tense, vg, "indicative", per, num)].add(base + "ν")
    # nominal endings: NS GS AS DS VS NP GP AP DP VP, gender in the comment
    CASES = [("nominative", "singular"), ("genitive", "singular"), ("accusative", "singular"), ("dative", "singular"),
             ("vocative", "singular"), ("nominative", "plural"), ("genitive", "plural"), ("accusative", "plural"),
             ("dative", "plural"), ("vocative", "plural")]
    GEN = {"M": "masculine", "F": "feminine", "N": "neuter"}
    for line in (md / "morphological-lexicon/nominal-endings.txt").read_text(encoding="utf-8").splitlines():
        if "#" not in line:
            continue
        cols, com = line.split("#", 1)
        cols = cols.split()
        gens = {GEN[g] for g in re.findall(r"\[([MFN])\]", com)}
        if len(cols) != 10 or not gens:
            continue
        for (c, n), e in zip(CASES, cols):
            for x in e.split("/"):
                if x == "?":
                    continue
                for g in gens:
                    inv[("nom", c, n, g)].add(plain(x.replace("(ν)", "")))
                    if "(ν)" in x:
                        inv[("nom", c, n, g)].add(plain(x.replace("(ν)", "ν")))
    src["inventory"] = inv
    # Morpheus noun stems (beta code): ":le:" lemma then ":no:" stem lines
    stems = collections.defaultdict(set)
    sd = md / "morpheus/stemlib/Greek/stemsrc"
    for f in sorted(sd.glob("nom0[1-7]")) + [sd / "nom.irreg", sd / "lsj.nom"]:
        if not f.exists():
            continue
        lem = None
        for line in f.read_text(encoding="latin-1").splitlines():
            if line.startswith(":le:"):
                lem = betacode(line[4:].split(",")[0].strip())
            elif line.startswith(":no:") and lem:
                st = line[4:].split()[0] if line[4:].split() else ""
                stems[lem].add(betacode(st))
            elif not line.strip():
                lem = None
    src["stems"] = stems
    src["hashes"] = {str(p.relative_to(md)): hashlib.sha256(p.read_bytes()).hexdigest()[:16] for p in
                     [md / "morphological-lexicon/projects/preverbs/verbs.txt",
                      md / "morphological-lexicon/projects/principal_parts/ending-paradigms.txt",
                      md / "morphological-lexicon/nominal-endings.txt"]}
    return src


# ---------------------------------------------------------------------------------------------------------- the cut
def lemma_preverbs(lp, verb_lemmas, aug_forms, comp_b):
    """the preverbs of a verb lemma (plain): [(preverb, variant in the lemma)], the base"""
    if comp_b is not None and lp in comp_b:
        parts = comp_b[lp]
        out, rest = [], lp
        for p in parts[:-1]:
            pv = VARIANT_OF.get(p) or next((k for k in PREVERB if p.startswith(k[:3]) and len(p) <= len(k) + 1), None)
            pv = p if p in PREVERB else pv
            if pv is None:
                break
            v = next((v for v in sorted(PREVERB[pv], key=len, reverse=True) if rest.startswith(v)), None)
            if v is None:
                break
            out.append((pv, v))
            rest = rest[len(v):]
        if out:
            return out, rest
    out, rest = [], lp
    while True:
        hit = None
        for v in sorted(VARIANT_OF, key=len, reverse=True):
            r = rest[len(v):]
            if not rest.startswith(v) or len(r) < 3 or not variant_fits(v, r):
                continue
            p = VARIANT_OF[v]
            sub_pv, sub_base = lemma_preverbs(r, verb_lemmas, set(), None)
            ok = r in verb_lemmas or bool(sub_pv) and sub_base in verb_lemmas
            if not ok:   # evidence: an augmented form keeps the preverb at its head
                for f in aug_forms:
                    for v2 in PREVERB[p]:
                        if f.startswith("".join(x[1] for x in out) + v2) if out else f.startswith(v2):
                            after = f[len("".join(x[1] for x in out)) + len(v2):] if out else f[len(v2):]
                            if after[:1] == "ε" and r[:1] != "ε" or any(after.startswith(L) for L in LONG.get(r[:1], [])
                                                                        if r[:1] in VOWELS and L != r[:1]):
                                ok = True
                                break
                    if ok:
                        break
            if ok:
                hit = (p, v, r)
                break
        if not hit:
            return out, rest
        out.append((hit[0], hit[1]))
        rest = hit[2]


def temporal(base, r):
    """r begins with the lengthened initial vowel of base: (len in r, len in base) or None"""
    for short in sorted(LONG, key=len, reverse=True):
        if base.startswith(short):
            for L in LONG[short]:
                if L != short and r.startswith(L):
                    return len(L), len(short)
    return None


def is_letter(g):
    return ud.category(g[0]).startswith("L")


def take_chars(pl, pos, nchars):
    """the number of graphemes from pos that cover nchars plain characters, or None"""
    acc, k = 0, pos
    while acc < nchars and k < len(pl):
        acc += len(pl[k]); k += 1
    return k - pos if acc == nchars else None


def preverb_cut(r, info):
    """the preverbs at the head of a verb form: r['head'], r['pos'], r['rest'] (plain, after them)"""
    pl = [gplain(g) for g in r["gs"]]
    rest = "".join(pl)
    for p, _ in info["preverbs"]:
        v = next((v for v in sorted(PREVERB[p], key=len, reverse=True) if rest.startswith(v)
                  and (v == p or variant_fits(v, rest[len(v):]))), None)
        if v is None:
            r["flags"].append("preverb_not_in_form"); break
        n = take_chars(pl, r["pos"], len(v))
        if n is None:
            r["flags"].append("preverb_cut"); break
        r["head"].append(("preverb", n, f"preverb={p}")); r["pos"] += n; rest = rest[len(v):]
    r["rest"] = rest


def aug_redup(r, base, lemma_plain):
    """augment and reduplication after the preverbs, against the principal part's base. Sets r['comp'] (the rest, a
    lengthened initial vowel given back the base's vowel, so that the forms of a group compare) and r['aug']"""
    w, rest = r["w"], r["rest"]
    pl = [gplain(g) for g in r["gs"]]
    comp = rest
    def cut(kind, nchars, feat):
        nonlocal rest, comp
        n = take_chars(pl, r["pos"], nchars)
        r["head"].append((kind, n, feat)); r["pos"] += n; rest = rest[nchars:]; comp = rest
    t, m = w["tense"], w["mood"]
    aug_tense = t in ("aorist", "imperfect", "pluperfect") and m == "indicative"
    r["aug"] = None
    if aug_tense and base:
        if base[0] not in VOWELS:
            if rest[:1] in ("ε", "η") and len(rest) > 1 and (rest[1] in (base[0], DEASP.get(base[0])) or
                                                             rest[1:3] == "ρρ" and base[0] == "ρ"):
                cut("augment", 1, "augment=syllabic"); r["aug"] = "syllabic"
            else:
                r["aug"] = "none"
        else:
            tl = temporal(base, rest)
            if rest.startswith(base[:2]) or rest.startswith(base[:1]) and base[:1] in "ιυ":
                r["aug"] = "unchanged"
            elif tl:
                comp = base[:tl[1]] + rest[tl[0]:]; r["aug"] = "temporal"
            elif rest[:1] == "ε" and rest[1:].startswith(base[:2]):
                cut("augment", 1, "augment=syllabic"); r["aug"] = "syllabic"
            else:
                r["aug"] = "none"
    r["redup"] = None
    if t in ("perfect", "pluperfect") and base and lemma_plain != "οιδα":
        b0 = base[0]
        if b0 not in VOWELS:
            if rest[:1] == DEASP.get(b0, b0) and rest[1:2] == "ε" and rest[2:3] == b0:
                cut("reduplication", 2, "reduplication=consonant"); r["redup"] = "consonant"
            elif rest[:2] == "ει" and b0 in "λμ":
                cut("reduplication", 2, "reduplication=ει"); r["redup"] = "ει"
            elif rest[:1] == "ε" and rest[1:2] != "ε" and (rest[1:2] == b0 or b0 in "σζξψγ" or rest[1:3] == "ρρ"):
                cut("reduplication", 1, "reduplication=ε"); r["redup"] = "ε"
            else:
                r["redup"] = "none"
        else:
            tl = temporal(base, rest)
            if tl:
                comp = base[:tl[1]] + rest[tl[0]:]; r["redup"] = "temporal"
            elif rest.startswith(base[:2]):
                r["redup"] = "unchanged"
            else:
                r["redup"] = "none"
    r["comp"] = comp


def lcp(strs):
    if not strs:
        return ""
    a, b = min(strs), max(strs)
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return a[:i]


CIT_ENDINGS = {"ω", "ομαι", "μι", "μαι", "ος", "η", "α", "ον", "ης", "ας", "ς", "υς", "ις", "ευς", "ους", "ων", "ηρ", "ωρ", "ην", ""}


def build_grc(words, route, srcb):
    verb_lemmas = {plain(w["lemma"]) for w in words if w["cls"] == "verb"}
    aug_forms = collections.defaultdict(set)
    for w in words:
        if w["cls"] == "verb" and w["mood"] == "indicative" and w["tense"] in ("aorist", "imperfect", "pluperfect"):
            aug_forms[plain(w["lemma"])].add(plain(w["surface"]))
    comp_b = srcb["compounds"] if srcb else None
    lemma_info = {}
    for lp in verb_lemmas:
        pv, base = lemma_preverbs(lp, verb_lemmas, aug_forms[lp], comp_b)
        lemma_info[lp] = dict(preverbs=pv, base=base, lemma_plain=lp)
    rows = []
    for w in words:
        g_all = graphemes(w["surface"])
        i = 0
        while i < len(g_all) and not is_letter(g_all[i]):
            i += 1
        j = len(g_all)
        while j > i and not is_letter(g_all[j - 1]):
            j -= 1
        r = dict(w=w, gs=g_all[i:j], lead=g_all[:i], trail=g_all[j:], head=[], pos=0, flags=[], group=None, kind="cut")
        lp = plain(w["lemma"])
        if not r["gs"]:
            r["kind"] = "empty"
        elif w["cls"] == "det":
            r["kind"] = "whole"; r["flags"].append("article")
        elif w["cls"] == "pron" and w["wtype"] == "relative" and lp in ("οσ", "οστισ", "οσπερ"):
            r["kind"] = "whole"; r["flags"].append("relative")   # declined like the article: the breathing vowel is the ending
        elif w["cls"] in FUNCTION:
            r["kind"] = "particle"
        elif w["after"].startswith("’"):
            r["kind"] = "whole"; r["flags"].append("elided")
        elif w["morph"].endswith("-K"):
            r["kind"] = "whole"; r["flags"].append("crasis")
        elif INDECLINABLE.match(w["morph"]):
            r["kind"] = "whole"; r["flags"].append("indeclinable")
        elif w["cls"] == "verb":
            r["group"] = (lp, pp_of(w))
            preverb_cut(r, lemma_info[lp])
        elif w["cls"] in ("noun", "adj", "pron", "num"):
            r["group"] = (lp, "N"); r["comp"] = "".join(gplain(g) for g in r["gs"])
        else:
            r["kind"] = "whole"
        rows.append(r)
    groups = collections.defaultdict(list)
    for r in rows:
        if r["kind"] == "cut":
            groups[r["group"]].append(r)
    # the base a principal part's augment and reduplication are read against: the present's is the lemma's (after its
    # preverbs); another part's is what its unaugmented forms share (εἶπον: εἰπεῖν, εἰπών; ἔφαγον: φαγεῖν), else the lemma's
    for g, rs in groups.items():
        lp, pp = g
        if pp == "N":
            continue
        base = lemma_info[lp]["base"]
        if pp != "P" and base.endswith("μι") and len(base) > 4 and base[1] == "ι" and base[0] not in VOWELS:
            base = base[2:]          # a μι-verb's present reduplication: τί-θημι, δί-δωμι, πί-μπλημι -> θη-, δω-, μπλη-
        elif pp != "P" and base.startswith("ιστη"):
            base = base[1:]          # ἵ-στημι -> στη-
        if pp in ("A", "AP", "F", "FP"):
            un = [r["rest"] for r in rs if not (r["w"]["mood"] == "indicative" and r["w"]["tense"] in ("aorist", "imperfect"))]
            b = lcp(un) if un else ""
            if len(b) >= 2:
                base = b
        for r in rs:
            aug_redup(r, base, lp)
    citation = {}
    for g, rs in groups.items():
        lp, pp = g
        if pp == "P":
            citation[g] = (lemma_info[lp]["base"], ("cit", "verb"))
        elif pp == "N":
            citation[g] = (lp, ("cit", "nom"))
    # 1. the endings a parse allows, learned from the groups with several forms: what varies after their common part
    inv = collections.defaultdict(collections.Counter)
    for g, rs in groups.items():
        forms = {r["comp"] for r in rs}
        if len(forms) < 3:
            continue
        L = len(lcp(list(forms | ({citation[g][0]} if g in citation else set()))))
        if L < 2:
            continue
        seen = set()
        for r in rs:
            k = (pkey(r["w"]), r["comp"][L:])
            if k not in seen:
                seen.add(k); inv[k[0]][k[1]] += 1
    MINLEX = 3
    def allow(inv):
        al = {k: {e for e, n in c.items() if n >= MINLEX} for k, c in inv.items()}
        if srcb:
            for k, es in srcb["inventory"].items():
                al.setdefault(k, set()).update(es)
        return al
    allowed = allow(inv)
    def ok(key, e):
        if key[0] == "cit":
            return e in CIT_ENDINGS
        return e in allowed.get(key, ())
    # 2. per group, the stem: a beginning that at least COVER of the group's forms share (at least two letters, one
    # for a lemma of three letters or fewer); of those, the one after which the most forms have an allowed ending; on
    # a tie, the one whose endings are the commoner (μισθ|ός, not μισθό|ς), then the longer; with none allowed, the
    # longest shared. A group with no such beginning is suppletive (ἐγώ / μου, πολύς / πλείων): it takes several
    # stems, each shared by at least two forms with allowed endings (or three forms); a form with none stays whole.
    def choose_stems():
        stems = {}
        COVER = 0.6
        for g, rs in groups.items():
            members = sorted({(r["comp"], pkey(r["w"])) for r in rs}, key=repr)
            if g in citation:
                members.append(citation[g])
            n = len(members)
            minlen = 1 if len(g[0]) <= 3 else 2
            best = None              # (score, L, stem)
            for L in range(minlen, max(len(c) for c, _ in members) + 1):
                cnt = collections.Counter(c[:L] for c, _ in members if len(c) >= L)
                if not cnt:
                    break
                st, cov = cnt.most_common(1)[0]
                if cov < COVER * n:
                    break
                score = sum(1 for c, k in members if c.startswith(st) and ok(k, c[L:]))
                freq = sum(inv[k][c[L:]] for c, k in members if c.startswith(st) and ok(k, c[L:]) and k[0] != "cit")
                if best is None or (score, freq, L) >= best[:3]:
                    best = (score, freq, L, st)
            basis = "shared"
            if srcb and g[1] == "N" and best:
                for st in sorted(srcb["stems"].get(g[0], ()), key=len, reverse=True):
                    if not st:
                        continue
                    cov = sum(1 for c, _ in members if c.startswith(st))
                    score = sum(1 for c, k in members if c.startswith(st) and ok(k, c[len(st):]))
                    if cov >= COVER * n and score >= best[0] and score:
                        best = (score, 0, len(st), st); basis = "morpheus"; break
            supp = best is None
            alts = []
            if supp:   # several stems (πολύς: πολ- and πλει-; καταβαίνω's aorist: βη- and βα-): take the beginning most
                rest = [m for m in members]                 # forms share, then again among the forms left
                while len(rest) >= 2:
                    top = None
                    for L in range(minlen, max(len(c) for c, _ in rest) + 1):
                        for st, cov in collections.Counter(c[:L] for c, _ in rest if len(c) >= L).items():
                            if cov < 2:
                                continue
                            score = sum(1 for c, k in rest if c.startswith(st) and ok(k, c[L:]))
                            if score < 2 and not (cov >= 3 and L >= 2):
                                continue
                            freq = sum(inv[k][c[L:]] for c, k in rest if c.startswith(st) and ok(k, c[L:]))
                            if top is None or (cov, score, freq, L) > top[:4]:
                                top = (cov, score, freq, L, st)
                    if top is None:
                        break
                    alts.append(top[4])
                    rest = [m for m in rest if not m[0].startswith(top[4])]
            stems[g] = dict(stem=best[3] if best else "", score=best[0] if best else 0, n=n, basis=basis, suppletive=supp,
                            alts=alts)
        return stems
    stems = choose_stems()
    # 2b. the endings again, now from every group's chosen stem (so that λόγ|ου outweighs a group whose forms all had
    # an ο: λογο|υ), and the stems once more
    inv = collections.defaultdict(collections.Counter)
    for g, rs in groups.items():
        st = stems[g]
        if st["suppletive"]:
            continue
        for k, e in {(pkey(r["w"]), r["comp"][len(st["stem"]):]) for r in rs if r["comp"].startswith(st["stem"])}:
            inv[k][e] += 1
    allowed = allow(inv)
    stems = choose_stems()
    # 3. the parts of each word
    out_parts, out_words = [], []
    for r in rows:
        w, gs = r["w"], r["gs"]
        parts = [("mark", r["lead"], "")] if r["lead"] else []
        if r["kind"] == "empty":
            pass
        elif r["kind"] in ("whole", "particle"):
            parts.append(("particle" if r["kind"] == "particle" else "stem", gs, ""))
        elif stems[r["group"]]["suppletive"] and not any(r["comp"].startswith(a) for a in stems[r["group"]]["alts"]):
            r["flags"].append("suppletive_alone")
            parts.append(("stem", gs, f"pp={r['group'][1]}" if r["group"][1] != "N" else ""))
        else:
            st = stems[r["group"]]
            if st["suppletive"]:
                r["flags"].append("suppletive_stem")
                S = max((a for a in st["alts"] if r["comp"].startswith(a)), key=len)
            else:
                S = st["stem"]
            comp, key = r["comp"], pkey(w)
            if S and comp.startswith(S) and len(comp) > len(S) - 1:
                e = comp[len(S):]
                if not ok(key, e):
                    r["flags"].append("ending_unlisted")
            else:
                e = max((x for x in allowed.get(key, ()) if x and comp.endswith(x) and len(comp) > len(x)),
                        key=lambda x: (inv[key][x], len(x)), default=None)
                r["flags"].append("stem_differs" if e is not None else "no_cut")
                e = e or ""
            pos = 0
            for kind, n, feat in r["head"]:
                parts.append((kind, gs[pos:pos + n], feat)); pos += n
            acc, k = 0, len(gs)
            while acc < len(e) and k > pos:
                k -= 1; acc += len(gplain(gs[k]))
            if acc != len(e) or (e and k <= pos):
                r["flags"].append("ending_not_aligned"); k = len(gs)
            feat = [f"pp={r['group'][1]}"] if r["group"][1] != "N" else []
            if r.get("aug") in ("temporal",) or r.get("redup") == "temporal":
                feat.append("lengthened=temporal")
            parts.append(("stem", gs[pos:k], ";".join(feat)))
            if k < len(gs):
                parts.append(("ending", gs[k:], w["morph"]))
        if r["trail"]:
            parts.append(("mark", r["trail"], ""))
        texts = [nfc(p[1]) for p in parts]
        if "".join(texts) != ud.normalize("NFC", w["surface"]):
            r["flags"].append("rebuild_failed")
        for n, (p, t) in enumerate(zip(parts, texts), 1):
            out_parts.append((w["key"], n, t, p[0], p[2]))
        r["texts"] = texts
        out_words.append((w["key"], w["surface"], w["lemma"], w["morph"], "/".join(r["group"]) if r["group"] else "",
                          "|".join(texts), ",".join(r["flags"])))
    return out_parts, out_words, rows, stems, allowed


def build_hbo(trees):
    c = sqlite3.connect(trees)
    by = collections.defaultdict(list)
    for key, part, surf, cls, wtype in c.execute(
            "SELECT key, part, surface, class, wtype FROM words WHERE corpus='hbo' AND inserted=0 ORDER BY key"):
        by[key[:11]].append((key[:11], part, key, surf, cls, wtype))
    rows = []
    for k, rs in by.items():
        for i, (wk, part, tok, surf, cls, wtype) in enumerate(rs):
            if cls == "pron" and wtype == "pronominal" and i > 0:
                kind = "suffix"
            elif i < len(rs) - 1 and cls in ("prep", "cj", "art", "rel", "intg", "ptcl"):
                kind = "particle"
            else:
                kind = "stem"
            rows.append((wk, part, tok, surf, kind, f"class={cls}"))
    return rows


# ---------------------------------------------------------------------------------------------------------- checks
def checks(words, out_words, rows, stems, route):
    lines = [f"# Word parts, route {route}: acceptance figures", ""]
    fl = collections.Counter(f for w in out_words for f in w[6].split(",") if f)
    n = len(out_words)
    lines.append(f"Greek words: {n:,}. Rebuild failures (the parts joined against the surface): {fl['rebuild_failed']}.")
    aug, red = collections.Counter(), collections.Counter()
    for r in rows:
        w = r["w"]
        if w["cls"] != "verb" or r["kind"] != "cut":
            continue
        if w["mood"] == "indicative" and w["tense"] in ("aorist", "imperfect", "pluperfect"):
            aug[r.get("aug")] += 1
        elif any(k == "augment" for k, _, _ in r["head"]):
            aug["augment cut outside an augmented tense (error)"] += 1
        if w["tense"] in ("perfect", "pluperfect"):
            red[r.get("redup")] += 1
    NAMES = {"syllabic": "syllabic augment cut", "temporal": "temporal (lengthened vowel, not cut)",
             "unchanged": "initial vowel unchanged (ει-, ευ-, ου-, ι-, υ-)", "none": "none found", None: "οἶδα (a perfect in form, no reduplication)",
             "consonant": "consonant + ε cut", "ε": "ε cut", "ει": "ει cut"}
    lines += ["", "## Augment against MACULA's tense (indicative aorist, imperfect, pluperfect; suppletive εἰμί and "
              "function words left out)", ""] + [f"- {NAMES.get(k, k)}: {v:,}" for k, v in aug.most_common()]
    lines += ["", "## Reduplication (perfect, pluperfect)", ""] + [f"- {NAMES.get(k, k)}: {v:,}" for k, v in red.most_common()]
    tok = collections.Counter(); grp = collections.defaultdict(set)
    for r in rows:
        if r["kind"] != "cut":
            continue
        st = stems[r["group"]]
        if st["suppletive"]:
            tok["suppletive group: form has one of the group's stems" if any(r["comp"].startswith(a) for a in st["alts"])
                else "suppletive group: form alone (whole)"] += 1
            continue
        follows = r["comp"].startswith(st["stem"])
        tok["form has its group's stem" if follows else "form's stem differs"] += 1
        grp[r["group"]].add(follows)
    allg = len(grp); good = sum(1 for v in grp.values() if v == {True})
    lines += ["", "## Stem consistency per lexeme and principal part", "",
              f"- groups (lexeme + principal part; nominals: lexeme): {allg:,}; every form with the group's stem: "
              f"{good:,} ({good / max(1, allg):.3f})",
              f"- suppletive groups (no beginning shared by 0.6 of the forms; several stems taken): "
              f"{sum(1 for s in stems.values() if s['suppletive']):,}"]
    lines += [f"- tokens, {k}: {v:,}" for k, v in tok.most_common()]
    lines += ["", "## Flags", ""] + [f"- {k}: {v:,}" for k, v in fl.most_common()]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--route", choices=("a", "b"), required=True)
    ap.add_argument("--grc", type=Path, default=GRC_DIR)
    ap.add_argument("--morph", type=Path, default=MORPH_DIR)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    from macula import build_passage_facts as pf
    out = a.out or HERE.parent.parent / "internal-docs" / "word-parts" / a.route
    out.mkdir(parents=True, exist_ok=True)
    words = read_grc(a.grc)
    srcb = read_route_b(a.morph) if a.route == "b" else None
    parts, wrows, rows, stems, allowed = build_grc(words, a.route, srcb)
    with open(out / "src_part_grc.tsv", "w", encoding="utf-8") as f:
        f.write("key\tn\ttext\tkind\tfeatures\n")
        for p in parts:
            f.write("\t".join(map(str, p)) + "\n")
    with open(out / "words_grc.tsv", "w", encoding="utf-8") as f:
        f.write("key\tsurface\tlemma\tmorph\tgroup\tcut\tflags\n")
        for p in wrows:
            f.write("\t".join(map(str, p)) + "\n")
    hbo = build_hbo(pf.TREES)
    with open(out / "src_part_hbo.tsv", "w", encoding="utf-8") as f:
        f.write("key\tn\ttoken\ttext\tkind\tfeatures\n")
        for p in hbo:
            f.write("\t".join(map(str, p)) + "\n")
    (out / "checks.md").write_text(checks(words, wrows, rows, stems, a.route), encoding="utf-8")
    exc = collections.Counter(); ex1 = {}
    for r in rows:
        w = r["w"]
        why = [f for f in r["flags"] if f not in ("article", "relative", "indeclinable", "suppletive_stem")]
        if r.get("aug") == "none":
            why.append("augment_none")
        if r.get("redup") == "none":
            why.append("reduplication_none")
        for f in why:
            k = (f, w["lemma"], r["group"][1] if r["group"] else "")
            exc[k] += 1; ex1.setdefault(k, (w["surface"], w["morph"], "|".join(r["texts"])))
    with open(out / "exceptions_grc.tsv", "w", encoding="utf-8") as f:
        f.write("flag\tlemma\tpp\ttokens\texample\tmorph\tcut\n")
        for k, n in sorted(exc.items(), key=lambda x: (x[0][0], -x[1])):
            f.write("\t".join([*k, str(n), *ex1[k]]) + "\n")
    rnd = random.Random(17)
    cand = [w for w in wrows if w[4]]
    with open(out / "sample_200.tsv", "w", encoding="utf-8") as f:
        f.write("key\tsurface\tlemma\tmorph\tcut\tflags\n")
        for w in sorted(rnd.sample(cand, 200)):
            f.write("\t".join([w[0], w[1], w[2], w[3], w[5], w[6]]) + "\n")
    meta = dict(route=a.route, built=time.strftime("%Y-%m-%d"),
                licence="CC BY 4.0 (MACULA Greek and Hebrew only)" if a.route == "a" else
                "CC BY-SA (uses MorphGNT morphological-lexicon and Perseus Morpheus stemlib, both CC BY-SA 3.0)",
                source_grc="Clear-Bible/macula-greek Nestle1904/lowfat (CC BY 4.0)", trees=str(pf.TREES),
                route_b_sources=srcb["hashes"] if srcb else None, words=len(wrows), parts=len(parts), hbo_parts=len(hbo))
    (out / "build.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print((out / "checks.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
