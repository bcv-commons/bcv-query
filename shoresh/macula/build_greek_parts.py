"""Greek parts, release 1: every word of MACULA Greek (Nestle 1904) cut into parts by the grammar-book stem rule, with a
part id of the same shape as MACULA Hebrew's morpheme ids (11-digit word id + one part digit).

The rule (decided 2026-11-22): the stem is the base form as grammars and lexicons give it (ποιε-, ὀνοματ-, σαρκ-); the
ending is the real ending; where stem and ending have merged in the letters (ποιῶ, ὄνομα, σάρξ, εἰμί) the rest of the word
after any preverb, augment or reduplication is ONE part of kind `fused`, carrying the word's parse.

Stem sources, by word (column `basis`):
  greek-inflexion  verbs: James Tauber's greek-inflexion, STEM_DATA/morphgnt_lexicon.yaml (MIT), the stem of the word's
                   principal part (its own PARTS table); the stem includes preverb, augment and reduplication, which the
                   route-a rules of build_word_parts.py cut off inside it
  dodson           nouns: Dodson's NT lexicon (public domain, CC0), the genitive minus its ending; -ευς nouns keep ε
  dodson-rule      adjectives: Dodson's citation form, the nominative ending (-ος, -ης) taken off
  rule             everything else, and where a source stem does not fit the form: the route-a cut of build_word_parts.py
                   (the stem every form of the lexeme shares), unchanged
  closed           πᾶς, εἷς, μηδείς, οὐδείς, τις, τίς: grammar-book stems written out here (CLOSED)
  irregular        Ἰησοῦς and the like (IRREGULAR): route a, on purpose
  whole            article, relative, elided, crasis, indeclinable, function words: one part (as route a)

  cd shoresh && .venv/bin/python -m macula.build_greek_parts [--src DIR] [--out DIR]

--src holds the pinned sources (morphgnt_lexicon.yaml, dodson.csv, pins.json; default ../internal-docs/greek-parts/sources);
--out defaults to ../internal-docs/greek-parts/v1. Writes parts.tsv (part_id, word_id, n, text, kind, features),
words.tsv (word_id, lead, surface, trail, lemma, morph, basis, cut, flags), checks.md, sample_200.tsv, build.json, SHA256SUMS.
Punctuation around a word is not a part: it sits in the word's lead / trail columns; lead + parts + trail = the surface."""
import argparse, collections, hashlib, json, random, re, unicodedata as ud
from pathlib import Path

from macula import build_word_parts as wp

HERE = Path(__file__).resolve().parent
SRC = HERE.parent.parent / "internal-docs" / "greek-parts" / "sources"
OUT = HERE.parent.parent / "internal-docs" / "greek-parts" / "v1"
IRREGULAR = {"Ἰησοῦς"}
CLOSED = {"πασ": ("παντ", "πασ"), "απασ": ("απαντ", "απασ"), "εισ": ("εν", "μι"), "μηδεισ": ("μηδεν", "μηδεμι"),
          "ουδεισ": ("ουδεν", "ουδεμι"), "τισ": ("τιν", "τιν")}   # grammar-book stems (masc./neuter, feminine) of a few
                                                                   # closed-class words, keyed by the plain lemma
ROUTE_A_ONLY = {"ending_unlisted", "suppletive_stem", "suppletive_alone", "stem_differs", "no_cut", "stem_not_in_form"}
MARKERS = re.compile(r"\{[^}]*\}")


# ---------------------------------------------------------------------------------------------------------- sources
def clean_stem(x):
    """a greek-inflexion stem as plain letters: markers {..} and its preverb seam | dropped ("ἐξ|ηλθ" -> εξηλθ)"""
    return wp.plain(MARKERS.sub("", x).replace("|", "").strip())


def read_inflexion(p):
    """{lemma (NFC): {"stems": {part: [stem, ...]}, "overrides": [(regex, [stem, ...]), ...]}} from greek-inflexion's
    lexicon; an override applies to the parse keys its regex matches (PAI.1S, XA[NP] ...); its stem "0" is skipped"""
    import yaml
    lex = {}
    for lemma, e in (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).items():
        e = e or {}
        st = e.get("stems") or {}
        ov = []
        for item in e.get("stem_overrides") or []:
            if isinstance(item, (list, tuple)) and len(item) == 2 and str(item[1]) != "0":
                ov.append((str(item[0]), [clean_stem(x) for x in str(item[1]).split("/") if clean_stem(x)]))
        lex[ud.normalize("NFC", lemma)] = {"stems": {k: [clean_stem(x) for x in str(v).split("/") if clean_stem(x)]
                                                     for k, v in st.items()}, "overrides": ov}
    return lex


def inflexion_key(w, part):
    """the parse key greek-inflexion's overrides match: TVM, then '.' and person-number or case-number-gender"""
    m = re.match(r"V-\d?([PIFARL])([AMPEDON])([ISOMNP])(?:-(\w+))?", w["morph"])
    if not m:
        return ""
    t = {"R": "X", "L": "Y"}.get(m[1], m[1]); v = {"E": "M", "D": "M", "N": "M", "O": "P"}.get(m[2], m[2])
    md = {"M": "D"}.get(m[3], m[3])
    if v == "P" and t not in "AF":
        v = "M"
    return t + v + md + ("." + m[4] if m[4] else "")


def inflexion_stems(e, w, part):
    key = inflexion_key(w, part)
    for rx, stems in e["overrides"]:
        if key and re.match(rx, key):
            return stems
    return e["stems"].get(part or "", [])


GEN_END = ("εωσ", "ουσ", "ου", "ησ", "ασ", "οσ", "ωσ")
NOM_END = ("οσ", "ον", "ησ", "ασ", "ισ", "υσ", "ευσ", "η", "α", "σ")


def read_dodson(p):
    """{strong: ('noun', stem, genitive ending) | ('adj', stem, '')} from Dodson's CSV (beta code headwords)"""
    import csv
    out = {}
    with open(p, encoding="utf-8") as f:
        r = csv.reader(f, delimiter="\t"); next(r)
        for row in r:
            strong, parts = row[0].lstrip("0"), [x.strip() for x in row[2].split(",")]
            head = wp.betacode(parts[0]) if parts else ""
            if len(parts) >= 3 and parts[-1].rstrip("(/=\\ ") in ("o", "h", "to"):          # a noun: headword, genitive, article
                gen = wp.betacode(parts[1])
                if not gen or not head:
                    continue
                if len(gen) >= len(head) - 1 and gen[:2] == head[:2]:
                    full = gen
                else:
                    i = head.rfind(gen[0], max(1, len(head) - 3))
                    if i > 0:
                        full = head[:i] + gen
                    else:
                        ne = next((e for e in NOM_END if head.endswith(e) and len(head) > len(e)), "")
                        full = head[:len(head) - len(ne)] + gen
                ge = next((e for e in GEN_END if full.endswith(e) and len(full) > len(e)), None)
                if not ge:
                    continue
                stem = full[:-len(ge)]
                if head.endswith("ευσ") and ge == "εωσ":
                    stem += "ε"                                     # βασιλε|ύς, βασιλέ|ως, βασιλε|ῖ: the ε every form has
                stems = [stem]
                if head.endswith("ηρ") and stem.endswith("ρ") and not stem.endswith("ερ") and len(stem) >= 3:
                    stems.append(head[:-2] + "ερ")                 # πατήρ: πατρ-ός and πατέρ-α (the vowel grades)
                out[strong] = ("noun", stems, ge)
            elif len(parts) >= 2 and head.endswith(("οσ", "ησ")) and len(head) > 3:            # an adjective: ἀγαθός, ή, όν
                out[strong] = ("adj", [head[:-2]], "")
    return out


# ---------------------------------------------------------------------------------------------------------- the cut
def inflexion_part(w):
    """greek-inflexion's principal part for a verb word (its PARTS table), from route a's own reading of the parse"""
    pp, t, m = wp.pp_of(w), w["tense"], w["mood"]
    ind = m == "indicative"
    return {"P": "1+" if t == "imperfect" else "1-", "F": "2-", "FP": "7-", "A": "3+" if ind else "3-",
            "AP": "6+" if ind else "6-", "R": "4+" if t == "pluperfect" else "4-",
            "RM": "5+" if t == "pluperfect" else "5-"}.get(pp)


def lemma_variants(lemma):
    l = ud.normalize("NFC", lemma)
    out = [l]
    if l.endswith("ομαι"):
        out.append(l[:-4] + "ω")
    elif l.endswith("ω"):
        out.append(l[:-1] + "ομαι")
    return out


def common_prefix(a, b):
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return i


def recut(r, a_parts, stem_plain):
    """the parts of a route-a row with the stem boundary taken from a source stem (plain, from the word's beginning, so
    it includes preverb, augment and reduplication). Returns (parts, flag) or (None, reason) when the stem does not fit."""
    gs = r["gs"]
    pl = [wp.gplain(g) for g in gs]
    form = "".join(pl)
    head = [p for p in a_parts if p[0] in ("preverb", "augment", "reduplication")]
    h = sum(len(p[1]) for p in head)
    head_plain = "".join(pl[:h])
    if form.startswith(stem_plain):
        b = wp.take_chars(pl, 0, len(stem_plain))
        if b is None or b < h or not stem_plain.startswith(head_plain):
            return None, "stem_cuts_head"
        parts = [(k, gs_, f) for k, gs_, f in head] + [("stem", gs[h:b], "")]
        if b < len(gs):
            parts.append(("ending", gs[b:], r["w"]["morph"]))
        return parts, ""
    # merged at the join: fused, when the form keeps most of the stem (σάρξ / σαρκ-, ὄνομα / ὀνοματ-, ποιῶ / ποιε-)
    need = len(stem_plain) - 2 if len(stem_plain) > 3 else 1      # the merge is at the join, not earlier (Ἰωάνης / Ἰωαννης-)
    if common_prefix(form, stem_plain) >= need and stem_plain.startswith(head_plain) \
            and form.startswith(head_plain) and h < len(gs):
        return [(k, gs_, f) for k, gs_, f in head] + [("fused", gs[h:], r["w"]["morph"])], "fused"
    return None, "stem_not_in_form"


def build(words, lex, dod):
    a_out_parts, a_out_words, rows, stems, allowed = wp.build_grc(words, "a", None)
    a_by_key = collections.defaultdict(list)
    for key, n, text, kind, feat in a_out_parts:
        a_by_key[key].append((kind, text, feat))
    out_parts, out_words, stat = [], [], collections.Counter()
    # a source stem counts for a lexeme only if some attested form of it begins with the stem (a lexicon's spelling,
    # Ἰωάννης, against Nestle 1904's Ἰωάνης, is not a merge at the join)
    attested = collections.defaultdict(set)
    for r in rows:
        w = r["w"]
        f = "".join(wp.gplain(g) for g in r["gs"])
        attested[("n", (w["strong"] or "").lstrip("G0"))].add(f)
        if w["cls"] == "verb":
            attested[("v", w["lemma"], inflexion_part(w))].add(f)
    def seen(k, stems):
        """verbs: some attested form of the principal part begins with the stem; nouns and adjectives: at least half
        of the lexeme's distinct forms do (Dodson's Μωσῆς against Nestle 1904's Μωϋσῆς, Μωϋσέως ... is a spelling)"""
        fs = attested[k]
        if k[0] == "v":
            return [x for x in stems if any(f.startswith(x) for f in fs)]
        return [x for x in stems if sum(1 for f in fs if f.startswith(x)) >= 0.5 * len(fs)] if len(stems) == 1 else \
               ([x for x in stems if any(f.startswith(x) for f in fs)]
                if sum(1 for f in fs if any(f.startswith(x) for x in stems)) >= 0.5 * len(fs) else [])
    for r in rows:
        w = r["w"]; key = w["key"]
        flags = [f for f in r["flags"]]
        # route a's parts as grapheme lists (marks dropped: they go to lead / trail)
        a_parts, pos = [], 0
        for kind, text, feat in a_by_key[key]:
            if kind == "mark":
                continue
            n = len(wp.graphemes(text))
            a_parts.append((kind, r["gs"][pos:pos + n], feat)); pos += n
        basis, parts = "rule", a_parts
        if r["kind"] in ("whole", "particle", "empty"):
            basis = "whole"
        elif w["lemma"] in IRREGULAR:
            basis = "irregular"
        elif w["cls"] in ("adj", "pron", "num") and wp.plain(w["lemma"]) in CLOSED:
            mn, fe = CLOSED[wp.plain(w["lemma"])]
            got, why = recut(r, a_parts, fe if w["gender"] == "feminine" else mn)
            if got is not None:
                basis, parts = "closed", got
                if why: flags.append(why)
        elif w["cls"] == "verb":
            pt = inflexion_part(w)
            cands = []
            for lv in lemma_variants(w["lemma"]):
                cands = inflexion_stems(lex[lv], w, pt) if lv in lex else []
                if cands:
                    break
            cands = seen(("v", w["lemma"], pt), cands) if cands else cands
            if not cands:
                stat["verb: no greek-inflexion stem (or none attested)"] += 1
            else:
                form = "".join(wp.gplain(g) for g in r["gs"])
                fit = sorted((s for s in cands if form.startswith(s)), key=len, reverse=True) or sorted(cands, key=len, reverse=True)
                got, why = recut(r, a_parts, fit[0])
                if got is None:
                    stat[f"verb: greek-inflexion stem not used ({why})"] += 1; flags.append(why)
                else:
                    basis, parts = "greek-inflexion", got
                    if why: flags.append(why)
        elif w["cls"] in ("noun", "adj"):
            d = dod.get((w["strong"] or "").lstrip("G0"))
            want = "noun" if w["cls"] == "noun" else "adj"
            dst = seen(("n", (w["strong"] or "").lstrip("G0")), d[1]) if d and d[0] == want else []
            if not dst:
                stat[f"{want}: no Dodson stem (or none attested)"] += 1
            else:
                form = "".join(wp.gplain(g) for g in r["gs"])
                fit = sorted((x for x in dst if form.startswith(x)), key=len, reverse=True) or dst
                got, why = recut(r, a_parts, fit[0])
                if got is None:
                    stat[f"{want}: Dodson stem not used ({why})"] += 1; flags.append(why)
                else:
                    basis, parts = ("dodson" if want == "noun" else "dodson-rule"), got
                    if why: flags.append(why)
        if basis in ("greek-inflexion", "dodson", "dodson-rule", "closed"):
            flags = [f for f in flags if f not in ROUTE_A_ONLY]
        texts = [wp.nfc(p[1]) for p in parts]
        lead, trail = wp.nfc(r["lead"]), wp.nfc(r["trail"])
        if lead + "".join(texts) + trail != ud.normalize("NFC", w["surface"]):
            flags.append("rebuild_failed")
        if len(parts) > 9:
            flags.append("more_than_9_parts")
        for n, (p, t) in enumerate(zip(parts, texts), 1):
            out_parts.append((f"{key}{n}", key, n, t, p[0], p[2]))
        out_words.append((key, lead, w["surface"], trail, w["lemma"], w["morph"], basis, "|".join(texts),
                          ",".join(f for f in flags if f)))
        stat[f"basis={basis}"] += 1
    return out_parts, out_words, stat


# ---------------------------------------------------------------------------------------------------------- checks
def checks(out_parts, out_words, stat, words):
    L = ["# Greek parts, release 1: acceptance figures", ""]
    n = len(out_words)
    fl = collections.Counter(f for w in out_words for f in w[8].split(",") if f)
    ids = [p[0] for p in out_parts]
    L += [f"Words: {n:,}. Parts: {len(out_parts):,}. Rebuild failures (lead + parts + trail against the surface): "
          f"{fl['rebuild_failed']}. Words with more than 9 parts: {fl['more_than_9_parts']}. "
          f"Duplicate part ids: {len(ids) - len(set(ids))}. Part ids not 12 digits: {sum(1 for i in ids if not re.fullmatch(r'\d{12}', i))}.", ""]
    L += ["## Basis (which source cut the word)", ""] + [f"- {k[6:]}: {v:,}" for k, v in sorted(stat.items()) if k.startswith("basis=")]
    L += ["", "## Source stems not used", ""] + [f"- {k}: {v:,}" for k, v in sorted(stat.items()) if not k.startswith("basis=")]
    kinds = collections.Counter(p[4] for p in out_parts)
    L += ["", "## Parts by kind", ""] + [f"- {k}: {v:,}" for k, v in kinds.most_common()]
    cls = {w["key"]: w["cls"] for w in words}
    fused = collections.Counter(cls[w[0]] for w in out_words if "fused" in w[8].split(","))
    L += ["", "## Fused words by class", ""] + [f"- {k}: {v:,}" for k, v in fused.most_common()]
    L += ["", "## Flags", ""] + [f"- {k}: {v:,}" for k, v in fl.most_common()]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=SRC)
    ap.add_argument("--grc", type=Path, default=wp.GRC_DIR)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    words = wp.read_grc(a.grc)
    lex = read_inflexion(a.src / "morphgnt_lexicon.yaml")
    dod = read_dodson(a.src / "dodson.csv")
    out_parts, out_words, stat = build(words, lex, dod)
    with open(a.out / "parts.tsv", "w", encoding="utf-8") as f:
        f.write("part_id\tword_id\tn\ttext\tkind\tfeatures\n")
        f.writelines("\t".join(map(str, p)) + "\n" for p in out_parts)
    with open(a.out / "words.tsv", "w", encoding="utf-8") as f:
        f.write("word_id\tlead\tsurface\ttrail\tlemma\tmorph\tbasis\tcut\tflags\n")
        f.writelines("\t".join(map(str, w)) + "\n" for w in out_words)
    (a.out / "checks.md").write_text(checks(out_parts, out_words, stat, words), encoding="utf-8")
    rnd = random.Random(20261122)
    sample = rnd.sample([w for w in out_words if w[6] != "whole"], 200)
    with open(a.out / "sample_200.tsv", "w", encoding="utf-8") as f:
        f.write("word_id\tsurface\tlemma\tmorph\tbasis\tcut\tflags\tverdict\n")
        f.writelines("\t".join([w[0], w[2], w[4], w[5], w[6], w[7], w[8], ""]) + "\n" for w in sorted(sample))
    pins = json.loads((a.src / "pins.json").read_text())
    grc_hash = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(a.grc.glob("*.xml")))).hexdigest()
    build_json = {"release": "greek-parts 1 (local, unpublished)", "built": "2026-11-22", "licence": "CC BY 4.0",
                  "rule": "grammar-book stems; merged forms one part, kind fused",
                  "macula_greek": "Clear-Bible/macula-greek Nestle1904/lowfat, 27 XML files, sha256 of their concatenation " + grc_hash,
                  "greek_inflexion": {"commit": pins["greek-inflexion"], "file": "STEM_DATA/morphgnt_lexicon.yaml", "licence": "MIT, (c) James Tauber"},
                  "dodson": {"commit": pins["dodson"], "file": "dodson.csv", "licence": "public domain (CC0), Jeffrey Dodson; biblicalhumanities"},
                  "words": len(out_words), "parts": len(out_parts)}
    (a.out / "build.json").write_text(json.dumps(build_json, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    sums = [f"{hashlib.sha256((a.out / n).read_bytes()).hexdigest()}  {n}" for n in
            ("parts.tsv", "words.tsv", "checks.md", "sample_200.tsv", "build.json")]
    (a.out / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print((a.out / "checks.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
