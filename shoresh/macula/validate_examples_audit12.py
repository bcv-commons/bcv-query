"""Stage 12 audit: independent recounts of the b1 source-example tables.

Written by the auditor of stage 12, without reading the builder's modules (examples_*.py), the validator's helpers or
the build's cache/. It reads MACULA's lowfat and node files, our entity files and the Septuagint bridge directly, makes
its own pieces, heads (D2p, D2w), labels (D3), clauses, constituents and a few statement tables, and compares them with
the tables of the build. Prints AGREES / DIFFERS with both numbers, ends non-zero when one differs.

    shoresh/.venv/bin/python -I shoresh/macula/validate_examples_audit12.py [--build b1]
"""
import argparse
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

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
HEB_LOW = os.path.join(HERE, ".lowfat-src/WLC/lowfat")
GRC_LOW = os.path.join(HERE, ".lowfat-src-grc")
HEB_NODES = os.path.join(HERE, "data/macula-nodes/hebrew/WLC/nodes")
GRC_NODES = os.path.join(HERE, "data/macula-nodes/greek/Nestle1904/nodes")
ENT = os.path.join(HERE, "data/entities")
BRIDGE = os.path.join(HERE, "../../internal-docs/hebrew-greek-cf-release/v0.2/bridges/lxx.parquet")
XID = "{http://www.w3.org/XML/1998/namespace}id"

CLOSED = {
    "gender": {"masculine": "m", "feminine": "f", "neuter": "n", "common": "c", "both": "b", "unknown: x": "x"},
    "number": {"singular": "sg", "plural": "pl", "dual": "du", "unknown: x": "x"},
    "person": {"first": "1", "second": "2", "third": "3", "unknown: x": "x"},
    "state": {"absolute": "abs", "construct": "cstr", "determined": "det"},
    "case": {"nominative": "nom", "genitive": "gen", "dative": "dat", "accusative": "acc", "vocative": "voc"},
    "tense": {"present": "pres", "imperfect": "impf", "future": "fut", "aorist": "aor", "perfect": "prf",
              "pluperfect": "plprf"},
    "voice": {"active": "act", "middle": "mid", "passive": "pass", "middlepassive": "midpass"},
    "mood": {"indicative": "ind", "subjunctive": "sbjv", "optative": "opt", "imperative": "imp", "infinitive": "inf",
             "participle": "ptcp"},
    "degree": {"comparative": "cmpr", "superlative": "sprl"},
}
CATS = {"heb": ["type", "stem", "person", "gender", "number", "state"],
        "grc": ["type", "tense", "voice", "mood", "person", "case", "gender", "number", "degree"]}
KIN = {"father", "mother", "offspring", "sibling", "partner", "tribe", "group_origin"}
TYPES = {"person", "place", "group", "deity", "realia", "flora", "fauna"}


def c0(v):
    return re.sub(r"[^a-z0-9]+", "_", v.lower()).strip("_")


def code(cat, v):
    return CLOSED.get(cat, {}).get(v, c0(v)) if cat in CLOSED else c0(v)


def jdump(d):
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def norm_heb(s):
    s = "".join(ch for ch in s if not (0x0591 <= ord(ch) <= 0x05AF or ord(ch) in (0x05BD, 0x05C4, 0x05C5)))
    return U.normalize("NFC", s)


# ---- lowfat ------------------------------------------------------------------------------------------------------

def read_lowfat(path):
    """-> list of sentences: (pieces in document order, clauses, constituents, cats with empty value)"""
    greek = "lowfat-src-grc" in path
    root = ET.parse(path).getroot()
    out = []
    for s in root.iter("sentence"):
        pieces = []
        clauses = []   # (clause idx, parent idx or -1, pids, rule, role, direct children [(role, pids, tag, cls)])
        empty_role_direct = C.Counter()
        role_not_direct = C.Counter()

        def walk(el, cl_stack, in_cl_direct):
            """returns pids under el (document order)"""
            pids = []
            is_cl = (el.get("class") == "cl") or (greek and el.tag == "w" and el.get("rule") is not None)
            my_idx = None
            if is_cl:
                my_idx = len(clauses)
                clauses.append([my_idx, cl_stack[-1] if cl_stack else -1, None, el.get("rule") or el.get("Rule"),
                                el.get("role"), []])
                stack = cl_stack + [my_idx]
            else:
                stack = cl_stack
            if el.tag == "w":
                a = dict(el.attrib)
                a["_text"] = el.text or ""
                a["_pid"] = el.get(XID)
                pieces.append(a)
                pids = [a["_pid"]]
            else:
                for k in el:
                    if k.tag not in ("w", "wg", "c"):
                        continue
                    kp = walk(k, stack, is_cl)
                    pids.extend(kp)
                    if is_cl:
                        r = k.get("role")
                        if r is None:
                            continue
                        if r == "" or r.startswith("err_"):
                            empty_role_direct["empty" if r == "" else "err"] += 1
                        else:
                            cls = k.get("class") or ("group" if greek else "run")
                            clauses[my_idx][5].append((r, kp, k.tag, cls))
            if is_cl:
                clauses[my_idx][2] = pids
            return pids

        for top in s:
            if top.tag in ("wg", "w", "c"):
                walk(top, [], False)
        out.append((pieces, clauses, empty_role_direct))
    return out


def read_nodes(path):
    """-> list per sentence: (edges {dep pid: (head pid, basis, place, rule)}, root pid, letterless set, strong of
    leaf pids, cnt, node groups for constructions)"""
    greek = "greek" in path
    root = ET.parse(path).getroot()
    res = []
    cnt = C.Counter()
    cons = C.Counter()   # constructions: (lang, level, rule, children, head index) -> nodes
    sys.setrecursionlimit(100000)
    for s in root.iter("Sentence"):
        edges, letterless, strong = {}, set(), {}

        def head_of(n):
            """-> (head pid, [pids])"""
            kids = [k for k in n if k.tag == "Node"]
            if not kids:
                if greek:
                    p = n.get(XID)
                    return p, [p]
                c = n.find("c")
                if c is not None:
                    ms = [m.get(XID) for m in c.findall("m")]
                    for m in ms:
                        strong[m] = n.get("StrongNumberX")
                    cnt["compound leaves"] += 1
                    cnt["compound pieces"] += len(ms)
                    for j, m in enumerate(ms[1:], 1):
                        edges[m] = (ms[0], "compound", j, None, n)
                    return ms[0], ms
                m = n.find("m")
                p = m.get(XID)
                strong[p] = n.get("StrongNumberX")
                if not (m.text or "").strip():
                    letterless.add(p)
                return p, [p]
            got = [head_of(k) for k in kids]
            if len(kids) == 1:
                return got[0]
            h = n.get("Head")
            if h is not None:
                hi, basis = int(h), "index"
            else:
                cats = [k.get("Cat") for k in kids]
                cnt[f"no Head: {n.get('Rule')} kids={len(kids)} cats={'/'.join(map(str, cats))}"] += 1
                cj = [j for j, c in enumerate(cats) if c in ("conj", "cj")]
                if len(kids) == 2 and len(cj) == 1:
                    hi, basis = 1 - cj[0], "conj"
                else:
                    hi, basis = None, "none"
            if greek:
                lang = "grc"
            else:
                lc = C.Counter(m.get("lang") for m in n.iter("m") if (m.text or "").strip())
                lang = {"H": "hbo", "A": "arc"}[sorted(lc.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]]
            rule = n.get("Rule") or ("run" if h is not None else "")
            cons[(lang, "clause" if n.get("Cat") == "CL" else "phrase", rule,
                  " ".join((k.get("Cat") or "").lower() for k in kids), hi)] += 1
            hp = got[hi][0] if hi is not None else None
            for j, (p, _) in enumerate(got):
                if hi is None and j == 0:
                    continue
                if j != hi:
                    edges[p] = (hp, basis, j, n.get("Rule"), n)
            return (hp if hp is not None else got[0][0]), [x for _, ps in got for x in ps]

        trees = [k for t in s.iter("Tree") for k in t if k.tag == "Node"]
        cnt[f"trees per sentence {len(trees)}"] += 1
        rp, allp = head_of(trees[0])
        # keep only what pickles: drop element refs, keep rule
        e2 = {d: (h, b, j, r) for d, (h, b, j, r, _) in edges.items()}
        res.append((e2, rp, letterless, strong, allp))
    return res, cnt, cons


def node_labels(path, lowfat_sents):
    """D3 per dependent pid: the role of the outermost lowfat element with exactly the dependent child's pieces, else
    rule:place / run:place / c:place. Recomputed in a second pass so that element sets are known."""
    greek = "greek" in path
    root = ET.parse(path).getroot()
    labels = {}
    for s, low in zip(root.iter("Sentence"), lowfat_sents):
        outer = {}
        for key, role in low:
            if key not in outer:
                outer[key] = role

        def lab(n):
            kids = [k for k in n if k.tag == "Node"]
            if not kids:
                if greek:
                    return n.get(XID), [n.get(XID)]
                c = n.find("c")
                if c is not None:
                    ms = [m.get(XID) for m in c.findall("m")]
                    for j, m in enumerate(ms[1:], 1):
                        r = outer.get(frozenset([m]))
                        labels[m] = r if (r and not r.startswith("err_")) else f"c:{j}"
                    return ms[0], ms
                p = n.find("m").get(XID)
                return p, [p]
            got = [lab(k) for k in kids]
            if len(kids) == 1:
                return got[0]
            h = n.get("Head")
            if h is None:
                cats = [k.get("Cat") for k in kids]
                cj = [j for j, c in enumerate(cats) if c in ("conj", "cj")]
                hi = 1 - cj[0] if (len(kids) == 2 and len(cj) == 1) else None
            else:
                hi = int(h)
            for j, (p, ps) in enumerate(got):
                if j == hi or (hi is None and j == 0):
                    continue
                r = outer.get(frozenset(ps))
                if r and not r.startswith("err_"):
                    labels[p] = c0(r)
                else:
                    labels[p] = f"{n.get('Rule') or 'run'}:{j}"
            return (got[hi][0] if hi is not None else got[0][0]), [x for _, ps in got for x in ps]

        trees = [k for t in s.iter("Tree") for k in t if k.tag == "Node"]
        rp, _ = lab(trees[0])
        labels[rp] = "root"
    return labels


def lowfat_elsets(path):
    """per sentence: [(frozenset of pids, role)] in document (pre-)order over w, wg, c"""
    root = ET.parse(path).getroot()
    out = []
    for s in root.iter("sentence"):
        lst = []
        for el in s.iter():
            if el.tag == "w":
                lst.append((frozenset([el.get(XID)]), el.get("role")))
            elif el.tag in ("wg", "c"):
                lst.append((frozenset(w.get(XID) for w in el.iter("w")), el.get("role")))
        out.append(lst)
    return out


def labels_file(pair):
    npath, lpath = pair
    return node_labels(npath, lowfat_elsets(lpath))


# ---- the audit -----------------------------------------------------------------------------------------------------

class Rep:
    def __init__(self):
        self.differ = 0
        self.lines = []

    def cmp(self, name, mine, table):
        ok = mine == table
        if not ok:
            self.differ += 1
        line = f"{'AGREES ' if ok else 'DIFFERS'} {name}: mine {mine}, table {table}"
        print(line, flush=True)
        self.lines.append(line)

    def info(self, name, v):
        line = f"INFO    {name}: {v}"
        print(line, flush=True)
        self.lines.append(line)


def tab(build, lang, name, cols=None):
    return pq.read_table(os.path.join(build, lang, name), columns=cols).to_pydict()


def audit_tanakh(R, build, pool):
    lf = sorted(glob.glob(os.path.join(HEB_LOW, "*-lowfat.xml")))
    nf = sorted(glob.glob(os.path.join(HEB_NODES, "*.xml")))
    low = pool.map(read_lowfat, lf, chunksize=4)
    nodes = pool.map(read_nodes, nf, chunksize=4)
    labs = pool.map(labels_file, list(zip(nf, lf)), chunksize=4)
    return build_and_compare(R, build, "heb", low, nodes, labs)


def audit_greek(R, build, pool):
    lf = sorted(glob.glob(os.path.join(GRC_LOW, "*.xml")))
    nf = sorted(glob.glob(os.path.join(GRC_NODES, "*.xml")))
    low = pool.map(read_lowfat, lf, chunksize=2)
    nodes = pool.map(read_nodes, nf, chunksize=2)
    labs = pool.map(labels_file, list(zip(nf, lf)), chunksize=2)
    return build_and_compare(R, build, "grc", low, nodes, labs)


def build_and_compare(R, build, fam, low, nodes, labs):
    greek = fam == "grc"
    langs = ["grc"] if greek else ["hbo", "arc"]
    # ---- words and pieces from lowfat
    words = []          # dict per word: id, pieces [attr dicts], sent
    sent_of = {}
    clauses_src = []    # (sent no, parent global idx or -1, pids, rule, role, children)
    empty_roles = C.Counter()
    sno = 0
    for f in low:
        for pieces, cls, er in f:
            sno += 1
            empty_roles.update(er)
            byw = C.OrderedDict()
            for p in pieces:
                wid = p["_pid"] if greek else "o" + p["_pid"][1:12]
                byw.setdefault(wid, []).append(p)
            for wid in sorted(byw):
                ps = sorted(byw[wid], key=lambda a: a["_pid"])
                words.append({"id": wid, "all": ps, "sent": sno})
            base = len(clauses_src)
            for idx, par, pids, rule, role, kids in cls:
                clauses_src.append((sno, base + par if par >= 0 else -1, pids, rule, role, kids))
    # letters / letterless
    letterless = set()
    piece_of = {}  # pid -> (t, n)
    t = 0
    for wd in words:
        t += 1
        wd["t"] = t
        ps = [p for p in wd["all"] if p["_text"] != ""]
        for p in wd["all"]:
            if p["_text"] == "":
                letterless.add(p["_pid"])
        wd["ps"] = ps
        for n, p in enumerate(ps, 1):
            piece_of[p["_pid"]] = (t, n)
        # D5
        stem = None
        for i, p in enumerate(ps):
            if p.get("pos") == "suffix":
                continue
            if (p.get("type") == "definite article" and i == len(ps) - 1 and i > 0):
                continue
            stem = i
        wd["stem"] = stem
        wd["lang"] = "grc" if greek else {"H": "hbo", "A": "arc"}[ps[stem]["lang"]]
        for p in wd["all"]:
            sent_of[p["_pid"]] = wd["sent"]
    # node strongs + edges
    edges, roots, strong, nletterless = {}, [], {}, set()
    ncnt = C.Counter()
    ncons = C.Counter()
    for f, cnt, cons in nodes:
        ncnt.update(cnt)
        ncons.update(cons)
        for e, rp, ll, st, allp in f:
            edges.update(e)
            roots.append(rp)
            strong.update(st)
            nletterless |= ll
    labels = {}
    for d in labs:
        labels.update(d)

    def lexeme(p, lang):
        if greek:
            return f"lex:grc:{p.get('lemma')}"
        sn = p.get("strongnumberx") or strong.get(p["_pid"]) or ""
        return f"lex:{lang}:{p.get('lemma')}:{sn}"

    def marks(p):
        d = {}
        for c in CATS["grc" if greek else "heb"]:
            v = p.get(c)
            if v is not None and v != "":
                d[c] = code(c, v)
        return jdump(d)

    # per language source rows
    S = {}
    for lang in langs:
        S[lang] = {"words": [w for w in words if w["lang"] == lang]}
    R.info(f"{fam}: written words by language (mine)", {l: len(S[l]["words"]) for l in langs})

    # piece heads (D2p) with letterless articles passed through
    def phead(pid):
        h = edges.get(pid)
        if h is None:
            return None
        hp, basis, j, rule = h
        seen = 0
        while hp is not None and hp in letterless:
            hp = edges.get(hp, (None,))[0] if hp in edges else None
            seen += 1
        return hp, basis

    rootset = set(roots)
    my_ph = {}
    for wd in words:
        for p in wd["ps"]:
            pid = p["_pid"]
            if pid in rootset:
                my_ph[pid] = ((0, 0), "root", "root")
            else:
                hb = phead(pid)
                if hb is None or hb[0] is None:
                    my_ph[pid] = ((0, 0), hb[1] if hb else "missing", labels.get(pid))
                else:
                    my_ph[pid] = (piece_of[hb[0]], hb[1], labels.get(pid))
    # D2w: steps to root
    by_tn = {piece_of[pid]: pid for pid in my_ph}
    depth_memo = {}

    def steps(pid):
        path = []
        x = pid
        while x not in depth_memo:
            h = my_ph[x][0]
            if h == (0, 0):
                depth_memo[x] = 0
                break
            path.append(x)
            x = by_tn[h]
        d = depth_memo[x]
        for y in reversed(path):
            d += 1
            depth_memo[y] = d
        return depth_memo[pid]

    my_wh = {}
    for wd in words:
        ds = [steps(p["_pid"]) for p in wd["ps"]]
        m = min(ds)
        tied = [i for i, d in enumerate(ds) if d == m]
        top = wd["stem"] if wd["stem"] in tied else tied[0]
        tp = wd["ps"][top]["_pid"]
        (ht, hn), basis, rel = my_ph[tp]
        my_wh[wd["t"]] = (ht, basis, rel)

    out = {}
    for lang in langs:
        W = S[lang]["words"]
        tw = tab(build, lang, "words.parquet")
        tp = tab(build, lang, "pieces.parquet", ["t", "n", "pid", "text", "kind", "lexeme", "class", "marks",
                                                 "head_t", "head_n", "head_basis", "rel", "who", "who_basis"])
        # --- words
        R.cmp(f"{lang} words: rows", len(W), len(tw["t"]))
        R.cmp(f"{lang} words: the set of ids", sorted(w["id"] for w in W) == sorted(tw["id"]), True)
        tidx = {i: k for k, i in enumerate(tw["id"])}
        R.cmp(f"{lang} words: t by id equals my text-order number (words differing)",
              sum(1 for w in W if tw["t"][tidx[w["id"]]] != w["t"]), 0)
        R.cmp(f"{lang} words: text equals the concatenated lowfat w texts (words differing)",
              sum(1 for w in W if tw["text"][tidx[w["id"]]] != "".join(p["_text"] for p in w["ps"])), 0)
        R.cmp(f"{lang} words: after equals the last piece's after (words differing)",
              sum(1 for w in W if tw["after"][tidx[w["id"]]] != (w["all"][-1].get("after") or "")), 0)
        R.cmp(f"{lang} words: sentences (distinct)", len({w["sent"] for w in W}), len(set(tw["sentence"])))
        # --- pieces
        mine_p = {}
        for w in W:
            for n, p in enumerate(w["ps"], 1):
                kind = "stem" if n - 1 == w["stem"] else ("prefix" if n - 1 < w["stem"] else "suffix")
                mine_p[(w["t"], n)] = (p["_pid"], p["_text"], kind, lexeme(p, lang if greek else
                                       {"H": "hbo", "A": "arc"}[p["lang"]]), c0(p.get("class", "")), marks(p))
        tpk = {(a, b): k for k, (a, b) in enumerate(zip(tp["t"], tp["n"]))}
        R.cmp(f"{lang} pieces: rows", len(mine_p), len(tp["t"]))
        for col, j in (("pid", 0), ("text", 1), ("kind", 2), ("lexeme", 3), ("class", 4), ("marks", 5)):
            bad = [k for k, v in mine_p.items() if k not in tpk or tp[col][tpk[k]] != v[j]]
            R.cmp(f"{lang} pieces: {col} equals my reading of the lowfat w (pieces differing)", len(bad), 0)
            if bad:
                R.info(f"{lang} pieces: {col} first differences",
                       [(k, mine_p[k][j], tp[col][tpk[k]] if k in tpk else None) for k in bad[:5]])
        R.cmp(f"{lang} pieces: words with exactly one stem", sum(1 for w in W if w["stem"] is not None),
              sum(1 for k in tp["kind"] if k == "stem"))
        # lexemes.tsv
        lx = list(csv.DictReader(open(os.path.join(build, lang, "lexemes.tsv"), encoding="utf-8"), delimiter="\t"))
        mycnt = C.Counter(v[3] for v in mine_p.values())
        R.cmp(f"{lang} lexemes.tsv: rows = distinct lexemes of the pieces", len(mycnt), len(lx))
        R.cmp(f"{lang} lexemes.tsv: count column (lexemes differing)",
              sum(1 for r in lx if int(r["count"]) != mycnt.get(r["lexeme"], -1)), 0)
        clsc = C.defaultdict(C.Counter)
        for v in mine_p.values():
            clsc[v[3]][v[4]] += 1
        mycls = {l: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for l, c in clsc.items()}
        R.cmp(f"{lang} lexemes.tsv: class = commonest class, tie smaller code (lexemes differing)",
              sum(1 for r in lx if mycls.get(r["lexeme"]) != r["class"]), 0)
        # --- heads (D2p)
        bad_h, bad_b, bad_r = [], [], []
        for k, v in mine_p.items():
            (ht, hn), basis, rel = my_ph[v[0]]
            i = tpk[k]
            if (tp["head_t"][i], tp["head_n"][i]) != (ht, hn):
                bad_h.append(k)
            if tp["head_basis"][i] != basis:
                bad_b.append(k)
            if tp["rel"][i] != rel:
                bad_r.append((k, rel, tp["rel"][i]))
        R.cmp(f"{lang} pieces: head_t, head_n equal my D2p (pieces differing)", len(bad_h), 0)
        R.cmp(f"{lang} pieces: head_basis equals my D2p (pieces differing)", len(bad_b), 0)
        R.cmp(f"{lang} pieces: rel equals my D3 (pieces differing)", len(bad_r), 0)
        if bad_r:
            R.info(f"{lang} pieces: rel first differences", bad_r[:5])
        R.cmp(f"{lang} pieces: roots (head 0, basis root)",
              sum(1 for v in mine_p.values() if my_ph[v[0]][1] == "root"),
              sum(1 for b in tp["head_basis"] if b == "root"))
        R.info(f"{lang} pieces: head_basis counts (mine)", dict(C.Counter(my_ph[v[0]][1] for v in mine_p.values())))
        # --- D2w
        bad_w = sum(1 for w in W if (tw["head"][tidx[w["id"]]], tw["head_basis"][tidx[w["id"]]],
                                      tw["rel"][tidx[w["id"]]]) != my_wh[w["t"]])
        R.cmp(f"{lang} words: head, head_basis, rel equal my D2w (words differing)", bad_w, 0)
        # roots by class of the root word's stem (finding A1 of FINAL)
        rc = C.Counter(mine_p[(w["t"], w["stem"] + 1)][4] for w in W if my_wh[w["t"]][0] == 0)
        R.info(f"{lang} words: root words by class of stem (mine)", dict(rc.most_common(8)))
        out[lang] = (W, mine_p, tw, tidx, tp, tpk)

    # ---- clauses
    # key: cl:<pid of first piece>:<pieces with letters>
    keys = []
    seen = C.Counter()
    cl_lang = []
    for sno_, par, pids, rule, role, kids in clauses_src:
        lp = sorted((piece_of[p] for p in pids if p not in letterless))
        first_pid = by_tn[lp[0]]
        base = f"cl:{first_pid}:{len(lp)}"
        seen[base] += 1
        keys.append(base if seen[base] == 1 else f"{base}:{seen[base]}")
        cl_lang.append(lp)
    # language by majority of pieces
    lang_of_piece = {}
    for w in words:
        for n, p in enumerate(w["ps"], 1):
            lang_of_piece[(w["t"], n)] = "grc" if greek else {"H": "hbo", "A": "arc"}[p["lang"]]
    tcl = {l: tab(build, l, "clauses.parquet", ["clause", "parent", "depth", "pred", "pred_kind", "role", "rule",
                                                 "words"]) for l in langs}
    mine_cl = {l: {} for l in langs}
    depth = []
    for i, (sno_, par, pids, rule, role, kids) in enumerate(clauses_src):
        cnt = C.Counter(lang_of_piece[x] for x in cl_lang[i])
        lang = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        d = 0 if par < 0 else depth[par] + 1
        depth.append(d)
        mine_cl[lang][keys[i]] = (keys[par] if par >= 0 else "", d, rule or "", role or "")
    for l in langs:
        T = tcl[l]
        R.cmp(f"{l} clauses: rows", len(mine_cl[l]), len(T["clause"]))
        R.cmp(f"{l} clauses: the set of keys equal", set(mine_cl[l]) == set(T["clause"]), True)
        ti = {k: j for j, k in enumerate(T["clause"])}
        R.cmp(f"{l} clauses: parent (clauses differing)",
              sum(1 for k, v in mine_cl[l].items() if k in ti and T["parent"][ti[k]] != v[0]), 0)
        R.cmp(f"{l} clauses: depth (clauses differing)",
              sum(1 for k, v in mine_cl[l].items() if k in ti and T["depth"][ti[k]] != v[1]), 0)
        R.cmp(f"{l} clauses: rule (clauses differing)",
              sum(1 for k, v in mine_cl[l].items() if k in ti and T["rule"][ti[k]] != v[2]), 0)
        R.cmp(f"{l} clauses: role, C0 of the source's (clauses differing)",
              sum(1 for k, v in mine_cl[l].items() if k in ti and T["role"][ti[k]] != c0(v[3])), 0)
    # pred and constituents
    my_ph_tn = {piece_of[pid]: v for pid, v in my_ph.items()}

    def part_head_word(pids):
        tn = [piece_of[p] for p in pids if p not in letterless]
        s = set(tn)
        out_ = sorted(x for x in tn if my_ph_tn[x][0] not in s)
        return (out_[0][0] if out_ else sorted(tn)[0][0]), len(out_)

    oneword = set(i for i, c in enumerate(clauses_src) if greek and len(c[2]) == 1 and c[5] == [])
    owpids = {clauses_src[i][2][0] for i in oneword}
    roles = C.Counter()
    heads_cons = {}
    preds = {}
    multi_head = 0
    for i, (sno_, par, pids, rule, role, kids) in enumerate(clauses_src):
        kk = sorted(kids, key=lambda k: min(piece_of[p] for p in k[1] if p not in letterless))
        for ordn, (r, kp, tag, cls) in enumerate(kids, 1):
            roles[r] += 1
            hw, nout = part_head_word(kp)
            if nout != 1:
                multi_head += 1
            heads_cons[(keys[i], ordn)] = (c0(r), hw)
        pred = (0, "none")
        for want in ("v", "vc", "p"):
            cand = [k for k in kk if k[0] == want and not (want == "v" and tag_is_ow(k, owpids))]
            if cand:
                pred = (part_head_word(cand[0][1])[0], want)
                break
        preds[keys[i]] = pred
    tcons = {l: tab(build, l, "constituents.parquet", ["clause", "ord", "role", "head"]) for l in langs}
    trole = C.Counter(r for l in langs for r in tcons[l]["role"])
    for r in sorted(set(roles) | set(trole)):
        R.cmp(f"{fam} constituents: role {r} rows", roles.get(r, 0), trole.get(r, 0))
    R.info(f"{fam} direct children of clauses with an empty role / err string (mine)", dict(empty_roles))
    tc = {}
    for l in langs:
        for k, o, r, h in zip(tcons[l]["clause"], tcons[l]["ord"], tcons[l]["role"], tcons[l]["head"]):
            tc[(k, o)] = (r, h)
    R.cmp(f"{fam} constituents: (clause, ord) -> (role, head) equal mine (rows differing)",
          sum(1 for k, v in heads_cons.items() if tc.get(k) != v), 0)
    R.info(f"{fam} constituents with not exactly one piece whose head lies outside (mine)", multi_head)
    tp_all = {}
    for l in langs:
        T = tcl[l]
        for k, p, pk in zip(T["clause"], T["pred"], T["pred_kind"]):
            tp_all[k] = (p, pk)
    badp = [(k, v, tp_all.get(k)) for k, v in preds.items() if tp_all.get(k) != v]
    R.cmp(f"{fam} clauses: pred, pred_kind equal mine (clauses differing)", len(badp), 0)
    if badp:
        R.info(f"{fam} clauses: pred first differences", badp[:6])

    # ---- statements from my own tables: forms, paradigms, orders, agreement
    for lang in langs:
        W, mine_p, tw, tidx, tp, tpk = out[lang]
        forms = C.Counter()
        par_ = C.defaultdict(lambda: [0, set(), set()])
        for w in W:
            for n_, p in enumerate(w["ps"], 1):
                v = mine_p[(w["t"], n_)]
                form = U.normalize("NFC", (p.get("normalized") or "").lower()) if greek else norm_heb(p["_text"])
                forms[(v[3], v[5], form)] += 1
                pr = par_[(v[4], v[5])]
                pr[0] += 1
                pr[1].add(v[3])
                pr[2].add(form)
        tf = tab(build, lang, "forms.parquet", ["lexeme", "marks", "form", "count"])
        tfd = {(a, b, c): d for a, b, c, d in zip(tf["lexeme"], tf["marks"], tf["form"], tf["count"])}
        R.cmp(f"{lang} forms: rows", len(forms), len(tfd))
        R.cmp(f"{lang} forms: (lexeme, marks, form) -> count equal (rows differing)",
              sum(1 for k, v in forms.items() if tfd.get(k) != v), 0)
        tpa = tab(build, lang, "paradigms.parquet", ["class", "marks", "count", "lexemes", "forms"])
        tpd = {(a, b): (c, d, e) for a, b, c, d, e in zip(tpa["class"], tpa["marks"], tpa["count"], tpa["lexemes"],
                                                            tpa["forms"])}
        R.cmp(f"{lang} paradigms: rows", len(par_), len(tpd))
        R.cmp(f"{lang} paradigms: count, lexemes, forms equal (rows differing)",
              sum(1 for k, v in par_.items() if tpd.get(k) != (v[0], len(v[1]), len(v[2]))), 0)
        # word classes and marks of every word of the family (head may be in the other table)
        wcls, wmk = {}, {}
        for l2 in langs:
            for w in out[l2][0]:
                v = out[l2][1][(w["t"], w["stem"] + 1)]
                wcls[w["t"]] = v[4]
                wmk[w["t"]] = json.loads(v[5])
        orders = C.defaultdict(lambda: [0, 0])
        agr = C.defaultdict(lambda: [0, 0, 0])
        for w in W:
            ht, basis, rel = my_wh[w["t"]]
            if ht == 0:
                continue
            o = orders[(rel, wcls[ht], wcls[w["t"]])]
            o[0 if w["t"] < ht else 1] += 1
            for cat in ("gender", "number", "person", "case", "state"):
                a, b = wmk[ht].get(cat), wmk[w["t"]].get(cat)
                if a is not None and b is not None:
                    agr[(rel, cat)][0 if a == b else 1] += 1
                elif (a is None) != (b is None):
                    agr[(rel, cat)][2] += 1
        to = tab(build, lang, "orders.parquet", ["rel", "head_class", "dep_class", "before", "after"])
        tod = {(a, b, c): [d, e] for a, b, c, d, e in zip(to["rel"], to["head_class"], to["dep_class"], to["before"],
                                                          to["after"])}
        R.cmp(f"{lang} orders: rows", len(orders), len(tod))
        R.cmp(f"{lang} orders: before, after equal (rows differing)",
              sum(1 for k, v in orders.items() if tod.get(k) != v), 0)
        ta = tab(build, lang, "agreement.parquet", ["rel", "category", "agree", "differ", "n_a"])
        tad = {(a, b): [c, d, e] for a, b, c, d, e in zip(ta["rel"], ta["category"], ta["agree"], ta["differ"],
                                                         ta["n_a"])}
        agr = {k: v for k, v in agr.items() if v[0] + v[1] >= 1}
        R.cmp(f"{lang} agreement: rows", len(agr), len(tad))
        R.cmp(f"{lang} agreement: agree, differ, n_a equal (rows differing)",
              sum(1 for k, v in agr.items() if tad.get(k) != v), 0)
        # exceptions of orders and agreement: one row per place against
        te = tab(build, lang, "exceptions.parquet", ["statement"])
        tec = C.Counter(st.split(":")[0] for st in te["statement"])
        R.cmp(f"{lang} exceptions: rows of orders = my sum of the smaller side (after where tied)",
              sum(min(v) if v[0] != v[1] else v[1] for v in orders.values()), tec.get("orders", 0))
        R.cmp(f"{lang} exceptions: rows of agreement = my sum of differ", sum(v[1] for v in agr.values()),
              tec.get("agreement", 0))
        # pairs: (head stem lexeme, rel, own stem lexeme), at least twice
        wlex = {}
        for l2 in langs:
            for w in out[l2][0]:
                wlex[w["t"]] = out[l2][1][(w["t"], w["stem"] + 1)][3]
        pairs = C.Counter((wlex[my_wh[w["t"]][0]], my_wh[w["t"]][2], wlex[w["t"]]) for w in W if my_wh[w["t"]][0])
        pairs = {k: v for k, v in pairs.items() if v >= 2}
        tpp = tab(build, lang, "pairs.parquet", ["head", "rel", "dep", "count"])
        tpd = {(a, b, c): d for a, b, c, d in zip(tpp["head"], tpp["rel"], tpp["dep"], tpp["count"])}
        R.cmp(f"{lang} pairs: rows", len(pairs), len(tpd))
        R.cmp(f"{lang} pairs: count equal (rows differing)", sum(1 for k, v in pairs.items() if tpd.get(k) != v), 0)
        # relmap.tsv: one row per word label, count = words with it
        rmap = list(csv.DictReader(open(os.path.join(build, lang, "relmap.tsv"), encoding="utf-8"), delimiter="\t"))
        myrel = C.Counter(my_wh[w["t"]][2] for w in W)
        R.cmp(f"{lang} relmap.tsv: rows = distinct word labels", len(myrel), len(rmap))
        R.cmp(f"{lang} relmap.tsv: count = words with the label (rows differing)",
              sum(1 for r in rmap if int(r["count"]) != myrel.get(r["label"], -1)), 0)
        # constructions, compounds left aside
        g = C.defaultdict(C.Counter)
        for (lg, level, rule, kids, hi), v in ncons.items():
            if lg == lang:
                g[(level, rule, kids)][hi] += v
        mine_c = {}
        for k, c in g.items():
            hi, n = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            mine_c[k] = (hi, n, sum(c.values()) - n)
        tc_ = tab(build, lang, "constructions.parquet", ["level", "rule", "children", "head_at", "count", "against"])
        tcd = {(a, b, c): (d, e, f) for a, b, c, d, e, f in zip(tc_["level"], tc_["rule"], tc_["children"],
                                                               tc_["head_at"], tc_["count"], tc_["against"])
               if b != "compound"}
        R.cmp(f"{lang} constructions: rows (compounds aside)", len(mine_c), len(tcd))
        bad = [(k, v, tcd.get(k)) for k, v in mine_c.items() if tcd.get(k) != v]
        R.cmp(f"{lang} constructions: head_at, count, against equal (rows differing)", len(bad), 0)
        if bad:
            R.info(f"{lang} constructions: first differences", bad[:4])

    # ---- participants: step 1 (explicit) and the kin facts
    ent_types = {}
    for r in csv.DictReader(open(os.path.join(ENT, "entities.tsv"), encoding="utf-8"), delimiter="\t"):
        ent_types[r["entity"]] = r["type"]

    def ent(acai):
        typ = acai.split(":", 1)[0]
        return f"{typ}:e{hashlib.sha1(acai.encode('utf-8')).hexdigest()[:10]}"

    expl = C.defaultdict(set)
    for r in csv.DictReader(open(os.path.join(ENT, "entity_words.tsv"), encoding="utf-8"), delimiter="\t"):
        if r["kind"] != "explicit":
            continue
        if r["entity"].split(":", 1)[0] not in TYPES:
            continue
        key = r["word"] if not greek else "n" + r["word"]
        expl[key].add(ent(r["entity"]))
    for lang in langs:
        W, mine_p, tw, tidx, tp, tpk = out[lang]
        mine_ex = {}
        for k, v in mine_p.items():
            key = v[0] if greek else v[0][1:]
            if key in expl:
                mine_ex[k] = " ".join(sorted(expl[key]))
        tab_ex = {(a, b): w for a, b, w, wb in zip(tp["t"], tp["n"], tp["who"], tp["who_basis"]) if wb == "explicit"}
        R.cmp(f"{lang} pieces: pieces with who_basis explicit", len(mine_ex), len(tab_ex))
        R.cmp(f"{lang} pieces: who of explicit pieces equal (pieces differing)",
              sum(1 for k, v in mine_ex.items() if tab_ex.get(k) != v), 0)
        parts = list(csv.DictReader(open(os.path.join(build, lang, "participants.tsv"), encoding="utf-8"),
                                    delimiter="\t"))
        tcl2 = tab(build, lang, "clauses.parquet", ["speaker", "addressee"])
        used = {e for w in tp["who"] for e in w.split()} | set(tcl2["speaker"]) | set(tcl2["addressee"])
        used.discard("")
        R.cmp(f"{lang} participants.tsv: rows = distinct ents in who, speaker, addressee", len(used), len(parts))
        perword = C.defaultdict(set)
        for t_, w in zip(tp["t"], tp["who"]):
            for e in w.split():
                perword[e].add(t_)
        R.cmp(f"{lang} participants.tsv: words column (rows differing)",
              sum(1 for r in parts if int(r["words"]) != len(perword.get(r["ent"], ()))), 0)
        pset = {r["ent"] for r in parts}
        kin = set()
        for r in csv.DictReader(open(os.path.join(ENT, "kinship.tsv"), encoding="utf-8"), delimiter="\t"):
            if r["relation"] in KIN and ent(r["entity"]) in pset and ent(r["other"]) in pset:
                kin.add((ent(r["entity"]), r["relation"], ent(r["other"])))
        tf = tab(build, lang, "facts.parquet", ["subject", "relation", "object"])
        tkin = {(s, r, o) for s, r, o in zip(tf["subject"], tf["relation"], tf["object"]) if r in KIN}
        R.cmp(f"{lang} facts: kin rows from kinship.tsv between participants", len(kin), len(tkin))
        R.cmp(f"{lang} facts: kin rows the same set", kin == tkin, True)
        # has_class from my pieces
        hc = C.Counter((v[3], v[4]) for v in mine_p.values())
        tf2 = tab(build, lang, "facts.parquet", ["subject", "relation", "object", "count"])
        thc = {(s, o): c for s, r, o, c in zip(tf2["subject"], tf2["relation"], tf2["object"], tf2["count"])
               if r == "has_class"}
        R.cmp(f"{lang} facts: has_class rows", len(hc), len(thc))
        R.cmp(f"{lang} facts: has_class counts (rows differing)", sum(1 for k, v in hc.items() if thc.get(k) != v), 0)

    # ---- links
    for lang in langs:
        W, mine_p, tw, tidx, tp, tpk = out[lang]
        la = tab(build, lang, "link_account.parquet", ["t", "n", "other", "state"])
        others = sorted(set(la["other"]))
        R.cmp(f"{lang} link_account: rows = pieces x other texts ({others})", len(mine_p) * len(others),
              len(la["t"]))
        R.cmp(f"{lang} link_account: (t, n, other) once each", len(set(zip(la["t"], la["n"], la["other"]))),
              len(la["t"]))
        lk = tab(build, lang, "links.parquet", ["t", "n", "other", "s"])
        nlinked = C.Counter(o for o, s in zip(la["other"], la["state"]) if s == "linked")
        lk_pieces = C.Counter(o for o in {(a, b, c) for a, b, c in zip(lk["t"], lk["n"], lk["other"])})
        R.cmp(f"{lang} link_account linked = distinct linked pieces in links.parquet",
              dict(sorted(nlinked.items())), dict(sorted(C.Counter(k[2] for k in
                                                                     set(zip(lk["t"], lk["n"], lk["other"]))).items())))
    if not greek:
        br = pq.read_table(BRIDGE).to_pydict()
        cols = list(br.keys())
        R.info("bridge columns", cols)
        R.info("bridge rows", len(br[cols[0]]))
        tot = 0
        hows = C.Counter()
        for lang in langs:
            lk = tab(build, lang, "links.parquet", ["how"])
            hows.update(lk["how"])
        R.info("Tanakh links by how (hbo+arc)", dict(hows))
        bh = C.Counter(br["how"]) if "how" in br else {}
        R.cmp("Tanakh: links with a bridge how = bridge rows",
              sum(v for k, v in hows.items() if k in bh), len(br[cols[0]]))
    R.info(f"{fam} node files: counts (mine)", {k: v for k, v in ncnt.items() if not k.startswith("no Head")})
    R.info(f"{fam} node files: nodes without Head (mine)",
           dict(C.Counter({k: v for k, v in ncnt.items() if k.startswith("no Head")}).most_common(12)))
    return out


def tag_is_ow(k, owpids):
    r, kp, tag, cls = k
    return tag == "w" and len(kp) == 1 and kp[0] in owpids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default="b1")
    ap.add_argument("--only", choices=["heb", "grc"])
    a = ap.parse_args()
    build = os.path.join(HERE, "data/source-examples", a.build)
    R = Rep()
    with mp.get_context("fork").Pool(8) as pool:
        if a.only in (None, "grc"):
            audit_greek(R, build, pool)
        if a.only in (None, "heb"):
            audit_tanakh(R, build, pool)
    print(f"== {R.differ} differ", flush=True)
    sys.exit(1 if R.differ else 0)


if __name__ == "__main__":
    main()
