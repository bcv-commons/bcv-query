"""Stage 02 (words-pieces) of the source-examples build, SPEC 1.0 sections 3, 4.1, 4.2, 4.6, 4.10, D1, D5.

Writes per language (hbo, arc, grc): words.parquet, pieces.parquet, lexemes.tsv, categories.toml (piece part).
Writes into the build's cache/: morphid.parquet (the node files' morphId -> pid map, used by stages 04 and 06) and
stage02-counts.json (the counts and exception lists of this stage).
"""
import collections as C
import csv
import json
import os
import re

import pyarrow as pa

import examples_common as X
import examples_src as S

WORD_COLS = [("t", pa.int64()), ("id", pa.string()), ("book", pa.string()), ("chapter", pa.int64()),
             ("verse", pa.int64()), ("w", pa.int64()), ("text", pa.string()), ("after", pa.string()),
             ("sentence", pa.int64()),
             # filled by stages 03, 04: present and null until then
             ("clause", pa.string()), ("head", pa.int64()), ("head_basis", pa.string()), ("rel", pa.string()),
             ("rel_shared", pa.string())]
WORD_LATER = ("clause", "head", "head_basis", "rel", "rel_shared")

PIECE_COLS = [("t", pa.int64()), ("n", pa.int64()), ("pid", pa.string()), ("text", pa.string()),
              ("kind", pa.string()), ("lexeme", pa.string()), ("class", pa.string()), ("marks", pa.string()),
              ("fused", pa.string()),
              ("head_t", pa.int64()), ("head_n", pa.int64()), ("head_basis", pa.string()), ("rel", pa.string()),
              ("who", pa.string()), ("who_basis", pa.string()),
              ("sense", pa.string()), ("domain", pa.string()),
              ("shared", pa.string())]
PIECE_LATER = ("head_t", "head_n", "head_basis", "rel", "who", "who_basis", "shared")

LEX_HEADER = ["lexeme", "lemma", "strong", "class", "count", "forms", "books", "senses", "domains", "first"]

UBS = os.path.join(S.HERE, "data/word-senses-ubs/words.tsv")
REF_ATTRS = ("frame", "participantref", "subjref")


def parse_ref(ref):
    book, rest = ref.split(" ", 1)
    cv, w = rest.split("!")
    c, v = cv.split(":")
    return book, int(c), int(v), int(w)


def d5_stem(lp):
    """D5: index of the stem among the word's pieces with letters (writing order), or None."""
    last = len(lp) - 1
    st = None
    for i, p in enumerate(lp):
        if p.get("pos") == "suffix":
            continue
        if p.get("type") == "definite article" and i == last and i > 0:
            continue
        st = i
    return st


def read_ubs():
    """(lang, key) -> (sorted senses, sorted domains). Keys: Hebrew pid without 'o', Greek id without 'n'."""
    senses, domains = C.defaultdict(set), C.defaultdict(set)
    with open(UBS, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            k = (r["lang"], r["key"])
            if r["sense"]:
                senses[k].add(r["sense"])
            # UBS joins several domains of a place with ";"; SPEC 4.2 writes them separated by a space (mended in stage 10)
            for d in r["domains"].replace(";", " ").split():
                domains[k].add(d)
    keys = set(senses) | set(domains)
    return {k: (sorted(senses[k]), sorted(domains[k])) for k in keys}


# ---- Hebrew and Aramaic ----------------------------------------------------------------------------------------

def tanakh(counts):
    """Words and pieces of the Tanakh in text order, split later by language."""
    files = S.heb_lowfat()
    nodes = S.heb_nodes()
    leaves = [x for _, out in nodes for x in out]
    comp_strong = {pid: strong for pid, mid, wref, strong, rank, text in leaves if rank}
    node_text = {pid: text for pid, mid, wref, strong, rank, text in leaves}

    words, verses = [], []
    ex = C.defaultdict(list)
    t = 0
    sentence = 0
    lowfat_compound = set()
    for fname, milestones, sents in files:
        verses.extend(milestones)
        for pieces, compounds in sents:
            sentence += 1
            for comp in compounds:
                lowfat_compound.update(comp)
            byw = C.defaultdict(list)
            for p in pieces:
                byw[p["id"][:12]].append(p)
            sent_verse = None
            for wid in sorted(byw):
                ps = sorted(byw[wid], key=lambda p: p["id"])
                if [p["doc"] for p in ps] != sorted(p["doc"] for p in ps):
                    ex["pieces whose document order differs from id order"].append(wid)
                refs = {p["ref"] for p in ps}
                if len(refs) != 1:
                    raise ValueError(f"pieces of {wid} carry several refs: {refs}")
                book, ch, vs, wn = parse_ref(ps[0]["ref"])
                if sent_verse is None:
                    sent_verse = (book, ch, vs)
                elif sent_verse != (book, ch, vs):
                    ex["words in a sentence of another verse"].append(wid)
                lp, fused_of = [], {}
                for i, p in enumerate(ps):
                    if p["text"]:
                        lp.append(p)
                        continue
                    # a letterless piece: must be a hidden article after a piece with letters
                    if p.get("type") != "definite article" or not p["id"].endswith("ה"):
                        raise ValueError(f"letterless piece that is not an article: {p['id']}")
                    if not lp or i == 0 or not ps[i - 1]["text"]:
                        raise ValueError(f"hidden article without a piece before it: {p['id']}")
                    before = ps[i - 1]
                    if before["id"] in fused_of:
                        raise ValueError(f"two hidden articles on one piece: {before['id']}")
                    fused_of[before["id"]] = p["id"]
                    if before.get("class") != "prep":
                        ex["hidden article after a piece that is not a preposition"].append(p["id"])
                st = d5_stem(lp)
                if st is None:
                    raise ValueError(f"word without a stem under D5: {wid}")
                for p in lp[:-1]:
                    if p.get("after"):
                        ex["pieces before the last with an `after`"].append(p["id"])
                langs = {p["lang"] for p in lp}
                t += 1
                wlang = X.LANG_OF[lp[st]["lang"]]
                if len(langs) > 1:
                    ex["words whose pieces differ in language"].append(f"{t} {wid} {book} {ch}:{vs} "
                                                                       + "".join(p["text"] for p in lp))
                words.append(dict(t=t, id=wid, book=book, chapter=ch, verse=vs, w=wn, sentence=sentence,
                                  lang=wlang, text="".join(p["text"] for p in lp), after=lp[-1].get("after", ""),
                                  pieces=lp, stem=st, fused=fused_of))
    counts["tanakh words"] = len(words)
    counts["tanakh sentences"] = sentence
    counts["tanakh verse milestones"] = len(verses)
    counts["lowfat pieces (w elements)"] = sum(len(ps) for _, _, ss in files for ps, _ in ss)
    counts["hidden articles"] = sum(len(w["fused"]) for w in words)
    counts["compound pieces (lowfat c)"] = len(lowfat_compound)
    counts["compound pieces (node files)"] = len(comp_strong)
    if lowfat_compound != set(comp_strong):
        raise ValueError("the compound pieces of lowfat and node files differ")
    counts["compound elements (lowfat c)"] = sum(len(c) for _, _, ss in files for _, c in ss)
    return words, ex, comp_strong, node_text, leaves


def morphid_map(leaves, letter_pids, out_path, counts):
    rows = sorted((mid, pid, rank, pid in letter_pids) for pid, mid, wref, strong, rank, text in leaves)
    X.write_parquet(out_path, {"morphid": [r[0] for r in rows], "pid": [r[1] for r in rows],
                               "compound_rank": [r[2] for r in rows], "row": [r[3] for r in rows]},
                    pa.schema([("morphid", pa.string()), ("pid", pa.string()), ("compound_rank", pa.int64()),
                               ("row", pa.bool_())]))
    bym = C.defaultdict(list)
    for mid, pid, rank, row in rows:
        bym[mid].append(pid)
    counts["morphId map rows"] = len(rows)
    counts["morphIds"] = len(bym)
    counts["morphIds naming a compound (several pids)"] = sum(1 for v in bym.values() if len(v) > 1)
    counts["pieces whose morphId differs from their xml:id"] = sum(1 for mid, pid, _, _ in rows if "o" + mid != pid)
    return bym


def reference_repair(words, bym, letter_pids, counts, ex):
    """SPEC 10 'references': every Hebrew target resolves through the morphId map; what xml:id would give."""
    all_pids = set(letter_pids)
    for w in words:
        all_pids.update(w["fused"].values())
    res = C.Counter()
    for w in words:
        for p in w["pieces"]:
            for a in REF_ATTRS:
                for tok in re.findall(r"\d{12}", p.get(a) or ""):
                    hit = bym.get(tok)
                    o = "o" + tok
                    res[(a, "targets")] += 1
                    if hit is None:
                        res[(a, "unresolved through morphId")] += 1
                        ex["unresolved reference targets"].append(f"{p['id']} {a} {tok}")
                    else:
                        if len(hit) > 1:
                            res[(a, "names a compound (several pieces)")] += 1
                        if not any(h in letter_pids for h in hit):
                            res[(a, "names a letterless article")] += 1
                    if o in all_pids:
                        if hit is None or o not in hit:
                            res[(a, "as xml:id: resolves to another piece")] += 1
                    else:
                        res[(a, "as xml:id: does not resolve")] += 1
    for (a, k), v in sorted(res.items()):
        counts[f"references {a}: {k}"] = v
    for k in ("targets", "unresolved through morphId", "names a compound (several pieces)",
              "names a letterless article", "as xml:id: resolves to another piece", "as xml:id: does not resolve"):
        counts[f"references all: {k}"] = sum(v for (a, kk), v in res.items() if kk == k)


def heb_rows(words, lang, comp_strong, ubs, coder, counts, ex):
    W = {k: [] for k, _ in WORD_COLS}
    P = {k: [] for k, _ in PIECE_COLS}
    lex = {}
    for w in words:
        if w["lang"] != lang:
            continue
        for k in ("t", "id", "book", "chapter", "verse", "w", "text", "after", "sentence"):
            W[k].append(w[k])
        for k in WORD_LATER:
            W[k].append(None)
        st = w["stem"]
        for i, p in enumerate(w["pieces"]):
            n = i + 1
            plang = X.LANG_OF[p["lang"]]
            strong = p.get("strongnumberx") or comp_strong.get(p["id"])
            if not strong:
                ex["pieces without a Strong's value"].append(p["id"])
                strong = ""
            lexeme = f"lex:{plang}:{p['lemma']}:{strong}"
            marks = {}
            for cat in X.MARK_CATS[lang]:
                v = p.get(cat)
                if v is None:
                    continue
                if v == "":
                    ex[f"empty `{cat}` values"].append(p["id"])
                    continue
                marks[cat] = coder.code(cat, v)
            cls = coder.code("class", p["class"])
            kind = "stem" if i == st else ("prefix" if i < st else "suffix")
            coder.code("kind", kind)
            sense, domain = ubs.get(("hbo", p["id"][1:]), ((), ()))
            row = dict(t=w["t"], n=n, pid=p["id"], text=p["text"], kind=kind, lexeme=lexeme, **{"class": cls},
                       marks=X.jdump(marks), fused=w["fused"].get(p["id"], ""),
                       sense=" ".join(sense), domain=" ".join(domain))
            for k, _ in PIECE_COLS:
                P[k].append(row.get(k))
            L = lex.setdefault(lexeme, dict(lemma=p["lemma"], strong=strong, cls=C.Counter(), forms=set(),
                                            books=set(), senses=C.Counter(), domains=C.Counter(), count=0,
                                            first=f"{w['t']}.{n}"))
            L["count"] += 1
            L["cls"][cls] += 1
            L["forms"].add(X.norm_heb(p["text"]))
            L["books"].add(w["book"])
            L["senses"].update(sense)
            L["domains"].update(domain)
    return W, P, lex


# ---- Greek -----------------------------------------------------------------------------------------------------

def greek(ubs, coder, counts, ex):
    files = S.grc_lowfat()
    W = {k: [] for k, _ in WORD_COLS}
    P = {k: [] for k, _ in PIECE_COLS}
    lex = {}
    t = sentence = 0
    verses = []
    for fname, milestones, sents in files:
        verses.extend(milestones)
        for pieces, _ in sents:
            sentence += 1
            if [p["doc"] for p in sorted(pieces, key=lambda p: p["id"])] != list(range(len(pieces))):
                ex["sentences whose document order differs from id order"].append(pieces[0]["id"])
            for p in sorted(pieces, key=lambda p: p["id"]):
                t += 1
                book, ch, vs, wn = parse_ref(p["ref"])
                if p["text"] != p["text"].strip() or any(ch_.isspace() for ch_ in p["text"]):
                    ex["words with space in their text"].append(p["id"])
                if re.search(r"[^\ẁ-ͯ᾽᾿῾’]", p["text"]):
                    ex["words whose own text holds punctuation"].append(f"{t} {p['id']} {p['ref']} "
                                                                         f"{p['text']} after={p['after']!r}")
                row_w = dict(t=t, id=p["id"], book=book, chapter=ch, verse=vs, w=wn, text=p["text"],
                             after=p.get("after", ""), sentence=sentence)
                for k, _ in WORD_COLS:
                    W[k].append(row_w.get(k))
                marks = {}
                for cat in X.MARK_CATS["grc"]:
                    v = p.get(cat)
                    if v is None:
                        continue
                    if v == "":
                        ex[f"empty `{cat}` values"].append(p["id"])
                        continue
                    marks[cat] = coder.code(cat, v)
                cls = coder.code("class", p["class"])
                coder.code("kind", "stem")
                lexeme = f"lex:grc:{p['lemma']}"
                sense, domain = ubs.get(("grc", p["id"][1:]), ((), ()))
                row = dict(t=t, n=1, pid=p["id"], text=p["text"], kind="stem", lexeme=lexeme, **{"class": cls},
                           marks=X.jdump(marks), fused="", sense=" ".join(sense), domain=" ".join(domain))
                for k, _ in PIECE_COLS:
                    P[k].append(row.get(k))
                L = lex.setdefault(lexeme, dict(lemma=p["lemma"], strongs=set(), cls=C.Counter(), forms=set(),
                                                books=set(), senses=C.Counter(), domains=C.Counter(), count=0,
                                                first=f"{t}.1"))
                L["count"] += 1
                L["cls"][cls] += 1
                L["strongs"].add(p["strong"])
                L["forms"].add(X.norm_grc(p["normalized"]))
                L["books"].add(book)
                L["senses"].update(sense)
                L["domains"].update(domain)
    counts["greek words"] = t
    counts["greek sentences"] = sentence
    counts["greek verse milestones"] = len(verses)
    counts["greek verses (distinct milestones)"] = len(set(verses))
    return W, P, lex


# ---- writing ---------------------------------------------------------------------------------------------------

def code_counts(cc):
    return " ".join(f"{c}:{n}" for c, n in sorted(cc.items(), key=lambda x: (-x[1], x[0])))


def write_lexemes(path, lex):
    rows = []
    for key in sorted(lex):
        L = lex[key]
        cls = sorted(L["cls"].items(), key=lambda x: (-x[1], x[0]))[0][0]
        strong = L["strong"] if "strong" in L else " ".join(sorted(L["strongs"]))
        rows.append([key, L["lemma"], strong, cls, L["count"], len(L["forms"]), len(L["books"]),
                     code_counts(L["senses"]), code_counts(L["domains"]), L["first"]])
    X.write_tsv(path, LEX_HEADER, rows)
    return len(rows)


CAT_SOURCE = {"class": "MACULA lowfat attribute class", "kind": "rule D5"}


def category_use(P):
    """Counts per category and code over the pieces of one table (for the piece part of categories.toml)."""
    use = C.defaultdict(C.Counter)
    for m in P["marks"]:
        for cat, code in json.loads(m).items():
            use[cat][code] += 1
    use["class"].update(P["class"])
    use["kind"].update(P["kind"])
    return use


def categories_text(lang, use, coder):
    out = [f"# categories.toml, {lang}: the categories of pieces (SPEC 1.0, section 4.10). Written by",
           "# build_examples.py --stage 02. `rule`: `list` = the code list of section 4.10, `C0` = rule C0.",
           "# `count` = pieces of this table with the value. The clause part is added by stage 05.", ""]
    order = list(X.MARK_CATS[lang]) + ["class", "kind"]
    for cat in order:
        if cat not in use:
            continue
        col = "marks" if cat in X.MARK_CATS[lang] else cat
        basis = "derived" if cat == "kind" else "given"
        src = CAT_SOURCE.get(cat, f"MACULA lowfat attribute {cat}")
        out.append(f"[pieces.{cat}]")
        out.append(f"column = {X.toml_str(col)}")
        out.append(f"basis = {X.toml_str(basis)}")
        out.append(f"source = {X.toml_str(src)}")
        out.append("values = [")
        for code in sorted(use[cat]):
            value = coder.seen[(cat, code)]
            rule = "D5" if cat == "kind" else coder.rule[(cat, code)]
            out.append(f"  {{ code = {X.toml_str(code)}, value = {X.toml_str(value)}, rule = {X.toml_str(rule)}, "
                       f"count = {use[cat][code]} }},")
        out.append("]")
        out.append("")
    return "\n".join(out)


def write_lang(outdir, lang, W, P, lex, coder, counts):
    d = os.path.join(outdir, lang)
    X.write_parquet(os.path.join(d, "words.parquet"), W, pa.schema(WORD_COLS))
    X.write_parquet(os.path.join(d, "pieces.parquet"), P, pa.schema(PIECE_COLS))
    counts[f"{lang} lexemes"] = write_lexemes(os.path.join(d, "lexemes.tsv"), lex)
    use = category_use(P)
    X.write_text(os.path.join(d, "categories.toml"), categories_text(lang, use, coder))
    counts[f"{lang} words"] = len(W["t"])
    counts[f"{lang} pieces"] = len(P["t"])
    counts[f"{lang} pieces with a sense"] = sum(1 for s in P["sense"] if s)
    counts[f"{lang} pieces with two or more senses"] = sum(1 for s in P["sense"] if " " in s)
    counts[f"{lang} pieces with a domain"] = sum(1 for s in P["domain"] if s)
    counts[f"{lang} pieces with fused"] = sum(1 for s in P["fused"] if s)
    counts[f"{lang} kinds"] = dict(sorted(C.Counter(P["kind"]).items()))
    counts[f"{lang} stem classes"] = dict(sorted(C.Counter(
        c for c, k in zip(P["class"], P["kind"]) if k == "stem").items()))


def build(outdir, langs, counts):
    ex = C.defaultdict(list)
    ubs = read_ubs()
    ubs_used = set()
    cache = os.path.join(outdir, "cache")
    if {"hbo", "arc"} & set(langs):
        words, ex_t, comp_strong, node_text, leaves = tanakh(counts)
        for k, v in ex_t.items():
            ex[k].extend(v)
        letter_pids = {p["id"] for w in words for p in w["pieces"]}
        for w in words:
            for p in w["pieces"]:
                if node_text.get(p["id"]) != p["text"]:
                    ex["pieces whose node-file text differs from lowfat"].append(p["id"])
        bym = morphid_map(leaves, letter_pids, os.path.join(cache, "morphid.parquet"), counts)
        reference_repair(words, bym, letter_pids, counts, ex)
        counts["compound words"] = sum(1 for w in words if any(p["id"] in comp_strong for p in w["pieces"]))
        for lang in ("hbo", "arc"):
            if lang not in langs:
                continue
            coder = X.Coder()
            W, P, lex = heb_rows(words, lang, comp_strong, ubs, coder, counts, ex)
            ubs_used.update(("hbo", pid[1:]) for pid in P["pid"])
            write_lang(outdir, lang, W, P, lex, coder, counts)
            for (cat, value), code in sorted(coder.c0_closed.items()):
                ex[f"{lang}: closed-category values coded by C0"].append(f"{cat} {value!r} -> {code}")
            counts[f"{lang} hidden articles in fused"] = sum(1 for f in P["fused"] if f)
    if "grc" in langs:
        coder = X.Coder()
        W, P, lex = greek(ubs, coder, counts, ex)
        ubs_used.update(("grc", pid[1:]) for pid in P["pid"])
        write_lang(outdir, "grc", W, P, lex, coder, counts)
        for (cat, value), code in sorted(coder.c0_closed.items()):
            ex["grc: closed-category values coded by C0"].append(f"{cat} {value!r} -> {code}")
    for lang in ("hbo", "grc"):
        if (lang == "hbo" and {"hbo", "arc"} <= set(langs)) or (lang == "grc" and "grc" in langs):
            miss = sorted(k for k in ubs if k[0] == lang and k not in ubs_used)
            counts[f"UBS {lang} keys that name no piece"] = len(miss)
            ex[f"UBS {lang} keys that name no piece"] = [k[1] for k in miss]
    return ex
