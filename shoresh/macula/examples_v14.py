"""SPEC 1.4 (stage 32, f builds): the tables new in 1.4, after the builders of 1.3 have built the build.

    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build f1 --stage 32        # everything
    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build f1 --stage 32.new    # this part alone

Writes:
  other/heb_mod/parts.parquet, other/heb_scg/parts.parquet   D23: a lexeme key for every part with letters
  lexicon/lexemes.tsv, pairs.parquet, groups.parquet           D24, D24n, D25, D25m, D26, D27
  lexicon/SAMPLE.md                                            D28
  lexicon/COLUMNS.md, READ-FIRST.md, categories.toml, sources.json
  arc/categories.toml, arc/sources.json                        the declarations of D24a (facts.equivalent_of kind)
  the reader's sample of 40 groups: internal-docs/source-examples-work/glossed-f1/equivalents-sample.md for f1,
  <build>/cache/reader-sample/equivalents-sample.md for any other build

Reads the build's own tables (hbo, arc, grc, other) and the pinned sources: MACULA Hebrew lowfat (greekstrong),
resources/lxx_bridge_tiers/greek_numbers.tsv, hebrew-nt-analysis v0.2 words.parquet (lexeme, lemma, strong, source),
aramaic-hebrew-equivalents v0.1.1 words.parquet. Nothing English is read; no model is asked.

Choices this module makes where SPEC 1.4 leaves a point open (each listed in the stage-32 report):
  - a lowfat greekstrong holding two numbers ("1722|1698": 8 pieces) is no Septuagint place (counted, listed);
  - nt_editions rows of basis `linked` are D24's rule over the parts of basis `derived` only; rows of basis `model`
    are the rule over all parts, where a part that carries the pair is `model` (so no strict row rests on a tagger
    part, not even through the test "the sets share no lexeme");
  - aramaic_list `a_other`: the Aramaic lexeme's list rows that pick no Hebrew key, or another one; for a `derived`
    row the `model` rows are left out of it;
  - D25m runs D25 and then D26 (the derived list rows) with the model places added, so that it differs from the
    strict groups only where the tagger's places make it differ;
  - an anchored lexeme that is a candidate but under 0.05 of its anchor's places is written `alone` (counted);
  - lexemes.tsv `group_model`: TSV has no null, so null is the empty field and the empty string is written `""`.
"""
import collections as C
import csv
import glob
import hashlib
import json
import multiprocessing as mp
import os
import re
import sys
import unicodedata as U
import xml.etree.ElementTree as ET

import pyarrow as pa
import pyarrow.parquet as pq

import examples_common as X
import examples_src as SRC

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
DOCS = os.path.join(ROOT, "internal-docs")
EDS = ("heb_mod", "heb_scg")
ANA_DIR = os.path.join(DOCS, "hebrew-nt-analysis-release/v0.2")
ANA_SHA = {"heb_mod": "cb3744d18efb73cf4b06142120506cff8a51ba33eda9e80c70f066548a429e5f",
           "heb_scg": "bf6aebcc96dcb330984b9ffc2d44a12b77f24aa91c8d7b654ef4f040a62224b5"}
GNUM = os.path.join(ROOT, "resources/lxx_bridge_tiers/greek_numbers.tsv")
GNUM_SHA = "ce0617b7b1a5ef39d32608a8610c50aa2a645de0797fc06181d68867a8bea082"
EQUIV = os.path.join(DOCS, "aramaic-hebrew-equivalents-release/v0.1.1/data/words.parquet")
EQUIV_SHA = "90f71ff81c4637fec8a3afe79efecce3c5b7b7732523fe3b587bbc1c87ce2b46"
GLOSSED_F1 = os.path.join(DOCS, "source-examples-work/glossed-f1")

ELIGIBLE_CLASS = ("noun", "verb", "adj", "adv")
NAME_TYPES = ("proper", "gentilic")
FUNCTION_TYPES = ("negative", "demonstrative", "interrogative", "affirmation", "indefinite", "exhortation",
                  "interjection")
MIN_PLACES, MIN_SHARE, MIN_MEMBER, MIN_PAIR = 5, 0.5, 0.05, 3
D24A_KIND = {"cognate_meaning": "derived", "domain": "derived", "greek_word": "derived", "greek_verse": "model"}
STATES = ("member", "nt_only", "function", "name", "no_number", "few_places", "spread", "alone")
KEY_RULES = ("K0", "K1", "K2", "K3", "K4", "K5")

PARTS_SCHEMA = pa.schema([("s", pa.int64()), ("p", pa.int64()), ("text", pa.string()), ("class", pa.string()),
                          ("lemma", pa.string()), ("strong", pa.string()), ("lexeme", pa.string()),
                          ("key_rule", pa.string()), ("basis", pa.string())])
PAIRS_SCHEMA = pa.schema([("a", pa.string()), ("b", pa.string()), ("evidence", pa.string()), ("basis", pa.string()),
                          ("via", pa.string()), ("count", pa.int64()), ("a_other", pa.int64()),
                          ("b_other", pa.int64()), ("ubs_depth", pa.int64()), ("places", pa.string())])
GROUPS_SCHEMA = pa.schema([("group", pa.string()), ("lexeme", pa.string()), ("head", pa.bool_()),
                           ("anchor", pa.string()), ("joined_by", pa.string()), ("members", pa.int64()),
                           ("count", pa.int64()), ("against", pa.int64()), ("same_strong", pa.string()),
                           ("basis", pa.string())])
LEX_HEADER = ["lexeme", "lemma", "strong", "lang", "class", "tanakh", "heb_mod", "heb_scg", "heb_mod_model",
              "heb_scg_model", "places", "anchor", "anchor_share", "group", "state", "group_model"]


def setup():
    """Before the 1.3 builders run in an f build: the basis of the Aramaic list as D24a states it."""
    import examples_close13
    examples_close13.BASIS["aramaic-hebrew-equivalents"] = "derived; model where the row's evidence is greek_verse (D24a, M7)"


def nfc(s):
    return U.normalize("NFC", s or "")


def digits(s):
    return re.sub(r"[^0-9]", "", s or "").lstrip("0")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def pinned(path, want):
    got = sha(path)
    if got != want:
        raise SystemExit(f"{os.path.relpath(path, ROOT)}: sha256 {got}, pinned {want}")
    return got


def tsv(path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


def jd(v):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def gkey(g):
    return f"g:{g}"


# ---- MACULA Hebrew lowfat: greekstrong per piece ------------------------------------------------------------------

def _greekstrong_file(path):
    root = ET.parse(path).getroot()
    return [(w.get(SRC.XID), w.get("greekstrong")) for w in root.iter("w") if w.get("greekstrong")]


def greekstrong():
    """{piece xml:id: greekstrong as written}, from the pinned lowfat files (cached by their sha256)."""
    res = SRC._cached("heb-greekstrong", SRC.heb_lowfat_files(), _greekstrong_file)
    out = {}
    for lst in res:
        for xid, g in lst:
            if xid in out:
                raise SystemExit(f"lowfat: piece {xid} twice")
            out[xid] = g
    return out


# ---- D23 ------------------------------------------------------------------------------------------------------------

def tanakh_lexicon(outdir):
    lex = {}
    for lang in ("hbo", "arc"):
        for r in tsv(os.path.join(outdir, lang, "lexemes.tsv")):
            r = dict(r)
            r["lang"] = lang
            lex[r["lexeme"]] = r
    return lex


def key_steps(lex):
    exact = {"hbo": C.defaultdict(list), "arc": C.defaultdict(list)}
    lem_dig = C.defaultdict(list)
    dig = C.defaultdict(list)
    for k, r in lex.items():
        exact[r["lang"]][(nfc(r["lemma"]), r["strong"])].append(k)
        if r["lang"] == "hbo":
            lem_dig[(nfc(r["lemma"]), digits(r["strong"]))].append(k)
            dig[digits(r["strong"])].append(k)
    return exact, lem_dig, dig


def key_part(lemma, strong, lexeme, steps, ex, where):
    """D23: (rule, key) of one part."""
    exact, lem_dig, dig = steps
    lem = nfc(lemma)
    if not lexeme:
        return "K0", f"ntx:hbo:{lem}"
    for rule, found in (("K1", exact["hbo"].get((lem, strong or ""), [])),
                        ("K2", exact["arc"].get((lem, strong or ""), [])),
                        ("K3", lem_dig.get((lem, digits(strong)), [])),
                        ("K4", dig.get(digits(strong), []) if digits(strong) else [])):
        if len(found) == 1:
            return rule, found[0]
        if len(found) > 1:
            ex[f"D23 step {rule} found several keys (fails the build)"].append(f"{where} {lem} {strong}: {found}")
            raise SystemExit(f"D23: step {rule} finds {len(found)} keys for {where} {lem} {strong}")
    return "K5", f"ntx:hbo:{lem}"


def build_parts(outdir, lex, cnt, ex):
    steps = key_steps(lex)
    parts = {}
    for ed in EDS:
        path = os.path.join(ANA_DIR, ed, "words.parquet")
        pinned(path, ANA_SHA[ed])
        ana = C.defaultdict(list)
        for r in pq.read_table(path).to_pylist():
            ana[(r["book"], r["chapter"], r["verse"], r["i"])].append(r)
        W = pq.read_table(os.path.join(outdir, "other", ed, "words.parquet"),
                          columns=["s", "book", "chapter", "verse", "w", "text", "analysis", "analysis_basis"]).to_pylist()
        rows = []
        c = C.Counter()
        joined = set()
        for w in W:
            k = (w["book"], w["chapter"], w["verse"], w["w"])
            if w["analysis"] is None:
                c["words left out: English token (analysis null)"] += 1
                if k in ana:
                    joined.add(k)
                continue
            if k not in ana:
                raise SystemExit(f"{ed}: word s={w['s']} has an analysis but no row of hebrew-nt-analysis")
            joined.add(k)
            src = {r["source"] for r in ana[k]}
            want = {"macula": "derived", "model": "model"}
            if len(src) != 1 or want.get(src.pop()) != w["analysis_basis"]:
                raise SystemExit(f"{ed}: word s={w['s']}: the analysis's source is not its analysis_basis")
            c["words joined"] += 1
            allk = True
            for r in sorted(ana[k], key=lambda r: r["part"]):
                if not r["text"]:
                    c["letterless parts left out (article after a preposition)"] += 1
                    continue
                rule, key = key_part(r["lemma"], r["strong"], r["lexeme"], steps, ex, f"{ed} s={w['s']} p={r['part']}")
                allk &= not key.startswith("ntx:")
                cls = "" if r["class"] == "-" else (r["class"] or "")
                rows.append({"s": w["s"], "p": int(r["part"]), "text": r["text"], "class": cls,
                             "lemma": r["lemma"] or "", "strong": r["strong"] or "", "lexeme": key, "key_rule": rule,
                             "basis": w["analysis_basis"]})
                c[f"parts {rule} {w['analysis_basis']}"] += 1
                if rule == "K0":
                    c[f"K0 parts class {cls or '-'}"] += 1
                if rule == "K5":
                    ex[f"{ed} K5 parts (a MACULA lexeme named, no key fits)"].append(
                        f"s={w['s']} p={r['part']} {r['lemma']} {r['strong']} {r['lexeme']} ({w['analysis_basis']})")
            c[f"words with every part on a Tanakh key, {w['analysis_basis']}"] += allk
            c[f"words {w['analysis_basis']}"] += 1
        for k, lst in ana.items():
            if k in joined:
                continue
            if all(r["class"] == "verse-number" for r in lst):
                c["analysis tokens left out: verse number"] += 1
            else:
                ex[f"{ed} analysis words not joined to other/{ed}"].append(" ".join(map(str, k)))
        rows.sort(key=lambda r: (r["s"], r["p"]))
        c["parts"] = len(rows)
        c["distinct ntx keys"] = len({r["lexeme"] for r in rows if r["lexeme"].startswith("ntx:")})
        cnt[f"D23 {ed}"] = dict(sorted(c.items()))
        parts[ed] = rows
    if getattr(X, "V15", False):      # SPEC 1.5 D23: H0, H1, H2 (heb_mod), then K6
        import examples_v15b as V15B
        V15B.keys15(outdir, parts, cnt, ex)
        for ed in EDS:
            cnt[f"D23 1.5 {ed} parts by key_rule and basis"] = dict(sorted(C.Counter(
                f"{r['key_rule']} {r['basis']}" for r in parts[ed]).items()))
            cnt[f"D23 1.5 {ed} distinct ntx keys"] = len({r["lexeme"] for r in parts[ed] if r["lexeme"].startswith("ntx:")})
    for ed in EDS:
        rows = parts[ed]
        X.write_parquet(os.path.join(outdir, "other", ed, "parts.parquet"),
                        {f.name: [r[f.name] for r in rows] for f in PARTS_SCHEMA}, PARTS_SCHEMA)
    return parts


# ---- D24: eligibility, places, pairs --------------------------------------------------------------------------------

def read_pieces(outdir):
    P = []
    for lang in ("hbo", "arc"):
        t = pq.read_table(os.path.join(outdir, lang, "pieces.parquet"), columns=["t", "n", "pid", "lexeme", "kind", "marks"])
        for r in t.to_pylist():
            r["lang"] = lang
            P.append(r)
    P.sort(key=lambda r: (r["t"], r["n"]))
    return P


def eligibility(lex, P, cnt):
    types = C.defaultdict(C.Counter)
    stem_types = C.defaultdict(C.Counter)
    for r in P:
        ty = json.loads(r["marks"]).get("type", "")
        types[r["lexeme"]][ty] += 1
        if r["kind"] == "stem":
            stem_types[r["lexeme"]][ty] += 1
    name, function, elig = set(), set(), set()
    for k, r in lex.items():
        tc = types.get(k, C.Counter())
        if sum(tc[t] for t in NAME_TYPES) * 2 > sum(tc.values()):
            name.add(k)
        st = stem_types.get(k)
        if st:
            top = sorted(st.items(), key=lambda x: (-x[1], x[0]))[0][0]
            if top in FUNCTION_TYPES:
                function.add(k)
        if r["class"] in ELIGIBLE_CLASS and k not in name and k not in function:
            elig.add(k)
    cnt["D24 eligibility"] = {"lexemes": len(lex), "name (more than half proper or gentilic)": len(name),
                              "function word by type": len(function),
                              "function word by type, in an eligible class": sum(1 for k in function if lex[k]["class"] in ELIGIBLE_CLASS),
                              "eligible": len(elig)}
    return elig, name, function


def gnum_map(cnt):
    pinned(GNUM, GNUM_SHA)
    m, without = {}, []
    for r in tsv(GNUM):
        src = digits(r["source_strong"])
        if r["nt_strong"]:
            m[src] = digits(r["nt_strong"])
        else:
            without.append(src)
    cnt["D24n numbers listed"] = len(m) + len(without)
    cnt["D24n numbers listed without nt_strong (stay)"] = len(without)
    return m, set(without)


def sept_places(P, gs, gmap, gwithout, cnt, ex):
    """[(lexeme, number, t, n)] of every piece with one greekstrong number, read through D24n."""
    out = []
    c = C.Counter()
    pids = set()
    for r in P:
        pids.add(r["pid"])
        g = gs.get(r["pid"])
        if g is None:
            continue
        c[f"{r['lang']} pieces with greekstrong"] += 1
        if not re.fullmatch(r"[0-9]+", g):
            c["pieces whose greekstrong holds more than one number (no place)"] += 1
            ex["D24 greekstrong with more than one number (no place)"].append(f"{r['pid']} {r['t']}.{r['n']} {g}")
            continue
        g = digits(g)
        if g in gmap and gmap[g] != g:
            c["D24n pieces moved to the New Testament number"] += 1
            g = gmap[g]
        elif g in gwithout:
            c["D24n pieces under a listed number without nt_strong (stay)"] += 1
        out.append((r["lexeme"], g, r["t"], r["n"]))
    c["lowfat elements with greekstrong that are no piece (letterless articles)"] = sum(1 for x in gs if x not in pids)
    c["lowfat elements with greekstrong"] = len(gs)
    cnt["D24 Septuagint places"] = dict(sorted(c.items()))
    return out


def nt_places(outdir, parts, elig, cnt):
    """[(lexeme, number, basis, grc t, edition, s, p)] per strict link and eligible part; and the links per Greek piece."""
    gl = {r["t"]: r["lexeme"] for r in pq.read_table(os.path.join(outdir, "grc", "pieces.parquet"),
                                                       columns=["t", "lexeme"]).to_pylist()}
    gstrong = {r["lexeme"]: r["strong"] for r in tsv(os.path.join(outdir, "grc", "lexemes.tsv"))}
    by_s = {ed: C.defaultdict(list) for ed in EDS}
    for ed in EDS:
        for r in parts[ed]:
            by_s[ed][r["s"]].append(r)
    out = []
    per_greek = C.defaultdict(lambda: {ed: [] for ed in EDS})
    c = C.Counter()
    for r in pq.read_table(os.path.join(outdir, "grc", "links.parquet"), columns=["t", "other", "s", "basis"]).to_pylist():
        if r["other"] not in EDS:
            continue
        if r["basis"] != "linked":
            c["model links (D13m), not read"] += 1
            continue
        c["strict links"] += 1
        per_greek[r["t"]][r["other"]].append(r["s"])
        st = gstrong.get(gl[r["t"]], "")
        if not re.fullmatch(r"[0-9]+", st or "") or not digits(st):
            c["strict links whose Greek lexeme has no single number (left out)"] += 1
            if st and not digits(st):
                c["  of which the Greek lexeme's number is 0"] += 1
            continue
        for p in by_s[r["other"]].get(r["s"], []):
            if p["lexeme"] in elig:
                out.append((p["lexeme"], digits(st), p["basis"], r["t"], r["other"], p["s"], p["p"]))
                c[f"places, part basis {p['basis']}"] += 1
    cnt["D24 New Testament places"] = dict(sorted(c.items()))
    return out, per_greek, gl, by_s


def ubs_depth(da, db):
    if not da or not db:
        return None
    best = 0
    for x in da:
        for y in db:
            d = 0
            while 3 * d + 3 <= min(len(x), len(y)) and x[3 * d:3 * d + 3] == y[3 * d:3 * d + 3]:
                d += 1
            best = max(best, d)
    return best


def domains_of(lex):
    return {k: [x.split(":")[0] for x in r["domains"].split()] for k, r in lex.items()}


def pairs_sept(sp, elig, dom):
    by = C.defaultdict(C.Counter)          # lexeme -> number -> pieces
    plc = C.defaultdict(list)              # (lexeme, number) -> [(t, n)]
    for lx, g, t, n in sp:
        if lx in elig:
            by[lx][g] += 1
            plc[(lx, g)].append((t, n))
    at = C.defaultdict(list)
    for lx, gc in by.items():
        for g, n in gc.items():
            if n >= MIN_PAIR:
                at[g].append(lx)
    vias = C.defaultdict(list)
    for g, ls in at.items():
        ls = sorted(ls)
        for i in range(len(ls)):
            for j in range(i + 1, len(ls)):
                vias[(ls[i], ls[j])].append(g)
    rows = []
    for (a, b), gs in vias.items():
        gs = sorted(gs, key=int)
        ca = sum(by[a][g] for g in gs)
        cb = sum(by[b][g] for g in gs)
        pl = sorted(p for g in gs for lx in (a, b) for p in plc[(lx, g)])[:3]
        rows.append({"a": a, "b": b, "evidence": "sept_number", "basis": "given", "via": jd([gkey(g) for g in gs]),
                     "count": ca + cb, "a_other": sum(by[a].values()) - ca, "b_other": sum(by[b].values()) - cb,
                     "ubs_depth": ubs_depth(dom[a], dom[b]), "places": " ".join(f"{t}.{n}" for t, n in pl)})
    return rows


def pairs_nt(per_greek, by_s, gl, elig, dom, cnt):
    """nt_editions: `linked` over derived parts only; `model` over all parts where a carrying part is model."""
    rows = []
    c = C.Counter()
    for basis in ("linked", "model"):
        cnt_pair = C.Counter()
        vias = C.defaultdict(set)
        places = C.defaultdict(list)
        hold = C.Counter()       # (lexeme, side) pieces where its side holds it and the other side is non-empty
        hold_with = C.Counter()  # (x, y): pieces where one side holds x and the other side holds y
        seen = []
        for t in sorted(per_greek):
            sets, carriers = {}, {}
            for ed in EDS:
                S, car = set(), C.defaultdict(list)
                for s in sorted(set(per_greek[t][ed])):
                    for p in by_s[ed].get(s, []):
                        if p["lexeme"] in elig and (basis == "model" or p["basis"] == "derived"):
                            S.add(p["lexeme"])
                            car[p["lexeme"]].append(p)
                sets[ed], carriers[ed] = S, car
            A, B = sets["heb_mod"], sets["heb_scg"]
            if not A or not B:
                if basis == "linked":
                    c["Greek pieces with eligible lexemes in one edition only (derived parts)"] += bool(A or B)
                continue
            if basis == "linked":
                c["Greek pieces with eligible lexemes in both editions (derived parts)"] += 1
                c["  equal" if A == B else "  overlapping" if A & B else "  disjoint"] += 1
            seen.append((t, A, B))
            if A & B:
                continue
            for x in sorted(A):
                for y in sorted(B):
                    px, py = carriers["heb_mod"][x], carriers["heb_scg"][y]
                    is_model = any(p["basis"] == "model" for p in px + py)
                    if basis == "model" and not is_model:
                        continue
                    a, b = (x, y) if x < y else (y, x)
                    cnt_pair[(a, b)] += 1
                    vias[(a, b)].add(gl[t])
                    if len(places[(a, b)]) < 3:
                        p1, p2 = px[0], py[0]
                        places[(a, b)].append(f"heb_mod:{p1['s']}.{p1['p']}+heb_scg:{p2['s']}.{p2['p']}")
        # the count against: pieces where A or B holds a and the other set is non-empty and does not hold b
        lex_in = C.defaultdict(set)
        for (a, b) in cnt_pair:
            lex_in[a].add((a, b))
            lex_in[b].add((a, b))
        a_other2, b_other2 = C.Counter(), C.Counter()
        for t, A, B in seen:
            U_ = A | B
            for x in U_:
                for (a, b) in lex_in.get(x, ()):
                    y = b if x == a else a
                    holds = (x in A and y not in B) or (x in B and y not in A)
                    if holds:
                        (a_other2 if x == a else b_other2)[(a, b)] += 1
        for (a, b), n in cnt_pair.items():
            rows.append({"a": a, "b": b, "evidence": "nt_editions", "basis": basis,
                         "via": jd(sorted(vias[(a, b)])), "count": n,
                         "a_other": a_other2[(a, b)], "b_other": b_other2[(a, b)],
                         "ubs_depth": ubs_depth(dom[a], dom[b]), "places": " ".join(places[(a, b)])})
    cnt["D24 nt_editions"] = dict(sorted(c.items()))
    return rows


def resolve_equiv(lex, cnt, ex):
    """The list rows resolved to (arc lexeme, hbo key or None, basis or None) per Aramaic piece, as 1.3 resolves them."""
    pinned(EQUIV, EQUIV_SHA)
    hb = [r for r in lex.values() if r["lang"] == "hbo"]
    exact, dg = C.defaultdict(list), C.defaultdict(list)
    for r in hb:
        lem = nfc(r["lemma"])
        exact[(lem, r["strong"].lstrip("0"))].append(r["lexeme"])
        dg[(lem, re.sub(r"[a-z]", "", r["strong"]).lstrip("0"))].append(r["lexeme"])
    return exact, dg


def pairs_aramaic(outdir, lex, elig, dom, cnt, ex):
    pinned(EQUIV, EQUIV_SHA)
    exact, dg = resolve_equiv(lex, cnt, ex)
    A = {r["pid"]: (r["lexeme"], r["t"], r["n"]) for r in
         pq.read_table(os.path.join(outdir, "arc", "pieces.parquet"), columns=["pid", "lexeme", "t", "n"]).to_pylist()}
    picks = C.defaultdict(list)       # arc lexeme -> [(hbo key or None, basis or None, t, n)]
    c = C.Counter()
    for r in pq.read_table(EQUIV).to_pylist():
        pid = "o" + r["key"]
        if pid not in A:
            c["list rows: key is no arc piece"] += 1
            continue
        ax, t, n = A[pid]
        hx, basis = None, None
        if r["hebrew_strong"] and r["hebrew_lemma"]:
            k = (nfc(r["hebrew_lemma"]), r["hebrew_strong"].lstrip("0"))
            if len(exact.get(k, [])) == 1:
                hx = exact[k][0]
            elif not exact.get(k) and len(dg.get(k, [])) == 1:
                hx = dg[k][0]
            basis = D24A_KIND[r["evidence"]] if hx else None
            c["list rows: resolved" if hx else "list rows: pick not resolved to one hbo key"] += 1
        else:
            c["list rows: no pick"] += 1
        picks[ax].append((hx, basis, t, n))
    rows, left = [], C.Counter()
    for ax in sorted(picks):
        lst = picks[ax]
        by = C.defaultdict(list)
        for hx, basis, t, n in lst:
            if hx:
                by[(hx, basis)].append((t, n))
        for (hx, basis), pl in sorted(by.items()):
            if ax not in elig or hx not in elig:
                left[f"{'arc' if ax not in elig else 'hbo'} lexeme not eligible, basis {basis}"] += 1
                continue
            other = sum(1 for h, b, _, _ in lst if h != hx and (basis == "model" or b != "model"))
            rows.append({"a": ax, "b": hx, "evidence": "aramaic_list", "basis": basis, "via": "[]",
                         "count": len(pl), "a_other": other, "b_other": 0,
                         "ubs_depth": ubs_depth(dom[ax], dom[hx]),
                         "places": " ".join(f"{t}.{n}" for t, n in sorted(pl)[:3])})
    c.update({f"(arc, hbo, basis) left out: {k}": v for k, v in left.items()})
    cnt["D24 aramaic_list"] = dict(sorted(c.items()))
    return rows, picks


# ---- D25, D25m, D26 ----------------------------------------------------------------------------------------------

def profiles(sp, ntp, elig, with_model):
    prof = C.defaultdict(C.Counter)
    for lx, g, _, _ in sp:
        if lx in elig:
            prof[lx][g] += 1
    for lx, g, basis, *_ in ntp:
        if basis == "derived" or with_model:
            prof[lx][g] += 1
    return prof


def anchor_of(prof):
    tot = sum(prof.values())
    if tot < MIN_PLACES:
        return None, None
    g, n = sorted(prof.items(), key=lambda x: (-x[1], int(x[0])))[0]
    if n / tot >= MIN_SHARE:
        return g, n / tot
    return None, None


def size_of(lex, counts, k):
    return int(lex[k]["count"]) + counts[("heb_mod", k)] + counts[("heb_scg", k)]


def head_of(members, lex, counts):
    return sorted(members, key=lambda k: (-size_of(lex, counts, k), k))[0]


def make_groups(prof, elig, lex, counts, picks, prefix, cnt_key, cnt):
    anchors = {}
    for lx in sorted(elig):
        g, share = anchor_of(prof.get(lx, C.Counter()))
        if g is not None:
            anchors[lx] = (g, share)
    cand = C.defaultdict(list)
    for lx, (g, _) in anchors.items():
        cand[(g, lex[lx]["class"])].append(lx)
    groups = {}       # key -> {"anchor": g or "", "members": {lexeme: (joined_by, count, against)}}
    member_of = {}
    weak = []
    for (g, cl), ls in sorted(cand.items()):
        allg = sum(prof[lx][g] for lx in ls)
        mem = [lx for lx in ls if prof[lx][g] >= MIN_MEMBER * allg]
        if len(mem) >= 2:
            weak += [lx for lx in ls if lx not in mem]
            h = head_of(mem, lex, counts)
            key = f"{prefix}:{h}"
            groups[key] = {"anchor": gkey(g), "members": {lx: ("anchor", prof[lx][g], sum(prof[lx].values()) - prof[lx][g])
                                                          for lx in mem}}
            for lx in mem:
                member_of[lx] = key
    # D26: Aramaic lexemes through the list's derived rows
    joins = C.defaultdict(list)
    d26 = C.Counter()
    for ax in sorted(picks):
        if ax not in elig or ax in member_of or lex[ax]["lang"] != "arc":
            continue
        pieces = int(lex[ax]["count"])
        per = C.Counter(hx for hx, b, _, _ in picks[ax] if hx and b == "derived" and hx in elig)
        top = [hx for hx, n in per.items() if n * 2 >= pieces]
        if len(top) > 1:
            d26["arc lexemes with two Hebrew picks at half (not joined)"] += 1
            continue
        if top:
            hx = top[0]
            other = sum(1 for h, b, _, _ in picks[ax] if h != hx and b != "model")
            joins[hx].append((ax, per[hx], other))
    for hx in sorted(joins):
        if hx in member_of:
            key = member_of[hx]
            for ax, n, o in joins[hx]:
                groups[key]["members"][ax] = ("aramaic_list", n, o)
                member_of[ax] = key
            d26["arc lexemes joined to a group of D25"] += len(joins[hx])
        else:
            mem = {hx: ("aramaic_list", sum(n for _, n, _ in joins[hx]), 0)}
            for ax, n, o in joins[hx]:
                mem[ax] = ("aramaic_list", n, o)
            h = head_of(list(mem), lex, counts)
            key = f"{prefix}:{h}"
            if key in groups:
                raise SystemExit(f"D26: group key {key} twice")
            groups[key] = {"anchor": "", "members": mem}
            for lx in mem:
                member_of[lx] = key
            d26["groups formed by D26"] += 1
            d26["arc lexemes in groups formed by D26"] += len(joins[hx])
    sizes = C.Counter(len(v["members"]) for v in groups.values())
    by_anchor = {k: v for k, v in groups.items() if v["anchor"]}
    asz = C.Counter(sum(1 for m in v["members"].values() if m[0] == "anchor") for v in by_anchor.values())
    cnt[cnt_key + ", D25 alone (groups by anchor)"] = {
        "groups": len(by_anchor), "members joined by the anchor": sum(asz[k] * k for k in asz),
        "by size (members joined by the anchor)": {str(k): v for k, v in sorted(asz.items())},
        "with an arc member joined by the anchor": sum(1 for v in by_anchor.values()
                                                       if any(lex[m]["lang"] == "arc" and j[0] == "anchor" for m, j in v["members"].items()))}
    cnt[cnt_key] = {"anchored lexemes": len(anchors), "groups": len(groups),
                    "members": sum(len(v["members"]) for v in groups.values()),
                    "groups by size": {str(k): v for k, v in sorted(sizes.items())},
                    "groups with an arc member": sum(1 for v in groups.values() if any(lex[m]["lang"] == "arc" for m in v["members"])),
                    "anchored candidates under 0.05 of their anchor (written alone)": len(weak), **dict(sorted(d26.items()))}
    return groups, member_of, anchors, set(weak)


def group_rows(groups, lex, counts, basis):
    rows = []
    for key in sorted(groups):
        g = groups[key]
        mem = g["members"]
        h = key.split(":", 1)[1]
        for lx in sorted(mem):
            jb, n, o = mem[lx]
            sd = sorted(m for m in mem if m != lx and lex[m]["lang"] == lex[lx]["lang"]
                        and digits(lex[m]["strong"]) == digits(lex[lx]["strong"]))
            rows.append({"group": key, "lexeme": lx, "head": lx == h, "anchor": g["anchor"], "joined_by": jb,
                         "members": len(mem), "count": n, "against": o, "same_strong": jd(sd), "basis": basis})
    return rows


# ---- the stage -----------------------------------------------------------------------------------------------------

def build(outdir, counts):
    ex = C.defaultdict(list)
    lex = tanakh_lexicon(outdir)
    parts = build_parts(outdir, lex, counts, ex)
    P = read_pieces(outdir)
    elig, name, function = eligibility(lex, P, counts)
    gs = greekstrong()
    gmap, gwithout = gnum_map(counts)
    sp = sept_places(P, gs, gmap, gwithout, counts, ex)
    ntp, per_greek, gl, by_s = nt_places(outdir, parts, elig, counts)
    dom = domains_of(lex)
    v15 = getattr(X, "V15", False)
    if v15:      # SPEC 1.5 D25 step 1: a place on a function number is no place
        import examples_v15b as V15B
        fnum = V15B.function_numbers(outdir, sys.modules[__name__])
        n0, m0 = len(sp), len(ntp)
        sp = [x for x in sp if x[1] not in fnum]
        ntp = [x for x in ntp if x[1] not in fnum]
        gstrong = {r["lexeme"]: r["strong"] for r in tsv(os.path.join(outdir, "grc", "lexemes.tsv"))}
        drop_t = [t for t in per_greek if digits(gstrong.get(gl[t], "") or "") in fnum
                  and re.fullmatch(r"[0-9]+", gstrong.get(gl[t], "") or "")]
        for t in drop_t:
            del per_greek[t]
        counts["D25 1.5 function numbers"] = {"numbers": len(fnum), "Septuagint places dropped": n0 - len(sp),
                                              "of Septuagint places": n0, "New Testament places dropped": m0 - len(ntp),
                                              "of New Testament places": m0, "Greek pieces left out of nt_editions": len(drop_t)}
    pr = pairs_sept(sp, elig, dom) + pairs_nt(per_greek, by_s, gl, elig, dom, counts)
    ar, picks = pairs_aramaic(outdir, lex, elig, dom, counts, ex)
    pr += ar
    pr.sort(key=lambda r: (r["evidence"], r["basis"], r["a"], r["b"]))
    counts["pairs by evidence and basis"] = {f"{e} {b}": n for (e, b), n in
                                              sorted(C.Counter((r["evidence"], r["basis"]) for r in pr).items())}
    # part counts per key
    pc = C.Counter()
    ntx_class = C.defaultdict(C.Counter)
    ntx_lemma = {}
    for ed in EDS:
        for r in parts[ed]:
            pc[(ed if r["basis"] == "derived" else ed + "_model", r["lexeme"])] += 1
            if r["lexeme"].startswith("ntx:"):
                ntx_class[r["lexeme"]][r["class"]] += 1
                ntx_lemma[r["lexeme"]] = r["lexeme"][len("ntx:hbo:"):]
    sizes = C.Counter({(ed, k): v for (ed, k), v in pc.items() if not ed.endswith("_model")})
    prof_s = profiles(sp, ntp, elig, False)
    prof_m = profiles(sp, ntp, elig, True)
    if v15:
        ev = V15B.list_evidence(outdir, sys.modules[__name__], lex, counts, ex)
        v16 = getattr(X, "V16", False)     # SPEC 1.6 D25 step 2b (and D25m with it)
        groups, member_of, anchors, weak, under = V15B.make_groups15(
            sys.modules[__name__], prof_s, elig, lex, sizes, picks, ev, dom, "cg",
            "D25 and D26 strict (1.6)" if v16 else "D25 and D26 strict (1.5)", counts, pairs=pr if v16 else None)
        mall, mall_of, _, _, _ = V15B.make_groups15(
            sys.modules[__name__], prof_m, elig, lex, sizes, picks, ev, dom, "cgm",
            "D25m with D26 (1.6)" if v16 else "D25m with D26 (1.5)", counts, pairs=pr if v16 else None)
        ps = V15B.senses_profile(outdir, sp)
        V15B.UNDER = set(under)
    else:
        groups, member_of, anchors, weak = make_groups(prof_s, elig, lex, sizes, picks, "cg", "D25 and D26 strict", counts)
        mall, mall_of, _, _ = make_groups(prof_m, elig, lex, sizes, picks, "cgm", "D25m with D26", counts)
    strict_sets = {frozenset(v["members"]) for v in groups.values()}
    mgroups = {k: v for k, v in mall.items() if frozenset(v["members"]) not in strict_sets}
    mmember_of = {lx: k for k, v in mgroups.items() for lx in v["members"]}
    in_some_model = set(mall_of)
    counts["D25m groups written (members not those of a strict group)"] = len(mgroups)
    rows_g = group_rows(groups, lex, sizes, "derived") + group_rows(mgroups, lex, sizes, "model")
    rows_g.sort(key=lambda r: (r["group"], r["lexeme"]))
    schema_g = GROUPS_SCHEMA
    if v15:      # SPEC 1.5 4.14: ubs_depth and senses_out per member
        schema_g = pa.schema(V15B.GROUPS15)
        for r in rows_g:
            h = r["group"].split(":", 1)[1]
            r["ubs_depth"] = None if r["head"] else ubs_depth(dom.get(r["lexeme"]), dom.get(h))
            r["senses_out"] = V15B.senses_out(sys.modules[__name__], r["lexeme"], r["anchor"], ps)
        strict = [r for r in rows_g if r["basis"] == "derived" and not r["head"]]
        counts["D25 1.5 strict members (not heads) by ubs_depth"] = dict(sorted(C.Counter(
            "null" if r["ubs_depth"] is None else str(min(r["ubs_depth"], 3)) + ("+" if r["ubs_depth"] >= 3 else "")
            for r in strict).items()))
        counts["D25 1.5 strict members with senses_out"] = dict(sorted(C.Counter(
            "null" if r["senses_out"] is None else ("[]" if r["senses_out"] == "[]" else "some")
            for r in rows_g if r["basis"] == "derived").items()))
        counts["D25 1.5 strict members joined under the floor"] = len(under)
    # lexemes.tsv
    keys = set(r["lexeme"] for r in P) | {r["lexeme"] for ed in EDS for r in parts[ed]}
    lrows = []
    st = C.Counter()
    for k in sorted(keys):
        if k.startswith("ntx:"):
            cl = sorted(ntx_class[k].items(), key=lambda x: (-x[1], x[0]))[0][0]
            base = [k, ntx_lemma[k], "", "hbo", cl, 0]
        else:
            r = lex[k]
            base = [k, r["lemma"], r["strong"], r["lang"], r["class"], int(r["count"])]
        nums = [pc[("heb_mod", k)], pc[("heb_scg", k)], pc[("heb_mod_model", k)], pc[("heb_scg_model", k)]]
        if k in elig:
            places = sum(prof_s.get(k, C.Counter()).values())
            a = anchors.get(k)
            anc, share = (gkey(a[0]), f"{a[1]:.4f}") if a else ("", "")
        else:
            places, anc, share = "", "", ""
        if k in member_of:
            state = "member"
        elif k.startswith("ntx:"):
            state = "nt_only"
        elif lex[k]["class"] not in ELIGIBLE_CLASS or k in function:
            state = "function"
        elif k in name:
            state = "name"
        elif places == 0:
            state = "no_number"
        elif places < MIN_PLACES:
            state = "few_places"
        elif not a:
            state = "spread"
        elif getattr(X, "V16", False) and k in V15B.STEP2B["cg"]["kept_out"]:
            state = "kept_out"     # SPEC 1.6 D27 (R9): kept out of its anchor's members by a rule of D25
        else:
            state = "alone"
        if k in mmember_of:
            gm = mmember_of[k]
        elif k in member_of and k not in in_some_model:
            gm = '""'
        else:
            gm = ""
        st[(base[3], state, int(base[5]) >= MIN_PLACES)] += 1
        lrows.append(base + nums + [places, anc, share, member_of.get(k, ""), state, gm])
    counts["D27 states (lang, state)"] = {f"{l} {s}": sum(v for (l2, s2, _), v in st.items() if (l2, s2) == (l, s))
                                          for (l, s) in sorted({(l, s) for l, s, _ in st})}
    counts["D27 states, Tanakh lexemes with 5 or more pieces (lang, state)"] = {
        f"{l} {s}": v for (l, s, big), v in sorted(st.items()) if big}
    counts["D27 alone that are candidates under 0.05 of a group's anchor"] = len(weak)
    L = os.path.join(outdir, "lexicon")
    os.makedirs(L, exist_ok=True)
    X.write_tsv(os.path.join(L, "lexemes.tsv"), LEX_HEADER, lrows)
    X.write_parquet(os.path.join(L, "pairs.parquet"), {f.name: [r[f.name] for r in pr] for f in PAIRS_SCHEMA}, PAIRS_SCHEMA)
    X.write_parquet(os.path.join(L, "groups.parquet"), {f.name: [r[f.name] for r in rows_g] for f in schema_g},
                    schema_g)
    import examples_v14doc as DOC
    DOC.write_all(outdir, counts, ex)
    counts["sources read"] = {"hebrew-nt-analysis v0.2 heb_mod words.parquet": ANA_SHA["heb_mod"],
                              "hebrew-nt-analysis v0.2 heb_scg words.parquet": ANA_SHA["heb_scg"],
                              "greek_numbers.tsv": GNUM_SHA, "aramaic-hebrew-equivalents v0.1.1 words.parquet": EQUIV_SHA,
                              "MACULA Hebrew lowfat (files)": len(SRC.heb_lowfat_files())}
    return dict(ex)
