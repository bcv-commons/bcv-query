"""Validator of the Hebrew ladder (SPEC-ladder 3.1, 12). Imports nothing from the builders; every rule it checks is
recomputed here with its own code. Prints each condition as PASS, SKIP or FAIL with its count; ends non-zero on a FAIL.

    shoresh/.venv/bin/python -I shoresh/macula/validate_ladder.py --build pilot-1 --upto 62 [--dir DIR] [--no-rebuild]

`--dir` validates a copy (the tamper test); `--no-rebuild` skips the two rebuilds. Writes VALIDATION.md into the build
folder (not into a `--dir` copy unless `--write` is given).
"""
import argparse, collections, hashlib, json, random, re, subprocess, sys, unicodedata
from pathlib import Path

import pyarrow.parquet as pq

MAC = Path(__file__).resolve().parent
REPO = MAC.parent.parent
DATA = MAC / "data"
K1 = DATA / "source-examples" / "k1"
SRC_MD = DATA / "metzudat_david_chapters.jsonl"
SRC_MZ = DATA / "metzudat_zion_chapters.jsonl"
LIC = "Public Domain, Sefaria, On Your Way"
SEED = "ladder-2026-11-24"
GENRE = {}
for _b in "JOS JDG 1SA 2SA 1KI 2KI 1CH 2CH EZR NEH DAN JON".split(): GENRE[_b] = "narrative"
for _b in "ISA JER EZK HOS JOL AMO OBA MIC NAM HAB ZEP HAG ZEC MAL".split(): GENRE[_b] = "prophets"
for _b in "PSA PRO JOB SNG ECC".split(): GENRE[_b] = "poetry+wisdom"

# the head of the abbreviation table as SPEC-ladder 4.4 writes it
SPEC_HEAD = {"ר״ל": "רצה לומר", "ה׳": "יהוה", "וכו׳": "וכולי", "וגו׳": "וגומר", "במ״ש": "במה שאמר", "כמ״ש": "כמו שאמר",
             "כ״א": "כל אחד", "א״כ": "אם כן", "עכו״ם": "עובדי כוכבים ומזלות", "ע״י": "על ידי", "עכ״ז": "עם כל זה",
             "נ״נ": "נבוכדנאצר", "מ״מ": "מכל מקום", "ז״ל": "זכרונו לברכה", "א״י": "ארץ ישראל", "כ״כ": "כל כך",
             "ע״ש": "על שם", "ארז״ל": "אמרו רבותינו זכרונם לברכה", "ע״פ": "על פי", "ב״ה": "בית המקדש", "אח״ז": "אחר זה",
             "קה״ק": "קודש הקדשים", "רז״ל": "רבותינו זכרונם לברכה", "במ״ב": "במה שאמר בו", "בה״מ": "בית המקדש",
             "כ״ש": "כל שכן", "א״א": "אי אפשר", "עי״ז": "על ידי זה", "בל׳": "בלשון", "במ״א": "במקום אחר", "אד׳": "אדני",
             "אלקים": "אלהים", "אלקי": "אלהי", "אלקיך": "אלהיך", "אלקינו": "אלהינו", "אלקיו": "אלהיו",
             "אלקיהם": "אלהיהם", "אלקיכם": "אלהיכם"}
SPEC_DIVINE = {"ה׳", "אד׳", "אלקים", "אלקי", "אלקיך", "אלקינו", "אלקיו", "אלקיהם", "אלקיכם"}

RESULTS = []
LOG = []


def say(s=""):
    print(s); LOG.append(s)


def cond(name, ok, detail):
    st = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
    RESULTS.append(st); say(f"{st}  {name}: {detail}")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ---------------------------------------------------------------- own text helpers

def letters(s):
    """consonants, final forms written plain"""
    m = {"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"}
    return "".join(m.get(c, c) for c in unicodedata.normalize("NFD", s or "") if 0x05D0 <= ord(c) <= 0x05EA)


def defective(s):
    if not s: return s
    return s[0] + re.sub("[וי]", "", s[1:])


def pointed(s):
    keep = set(range(0x05B0, 0x05BD)) | {0x05C1, 0x05C2, 0x05C7}
    buf = ""
    for c in unicodedata.normalize("NFD", s or ""):
        if 0x05D0 <= ord(c) <= 0x05EA or ord(c) in keep: buf += c
        elif unicodedata.category(c) != "Mn": buf += " "
    return re.sub(r"\s+", " ", buf).strip()


INVIS = re.compile("[‎‏​-‍﻿]")


def split_comment(raw):
    s = INVIS.sub("", raw)
    m = re.match(r"^\s*<b>", s)
    if not m: return None, re.sub(r"<[^>]+>", "", s).strip()
    close = s.find("</b>", m.end())
    lem = re.sub(r"<[^>]+>", "", s[m.end():close]).strip()
    while lem and lem[-1] in " .:": lem = lem[:-1]
    return lem.strip(), re.sub(r"<[^>]+>", "", s[close + 4:]).strip()


def source_strings(path):
    out = []
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        for v, cs in enumerate(r["verses"] or [], 1):
            for n, c in enumerate([cs] if isinstance(cs, str) else cs, 1):
                out.append((r["book"], int(r["chapter"]), v, n, c))
    return out


# ---------------------------------------------------------------- own abbreviation lookup

class Abbrev:
    def __init__(self, path):
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        self.head = lines[0].split("\t")
        self.rows = [l.split("\t") for l in lines[1:]]
        self.t = {r[0]: (r[1], r[2]) for r in self.rows}
        cp = Path(path).parent / "abbrev_context.tsv"          # AB-CTX (OPEN-ladder 13, 2026-11-25)
        cl = cp.read_text(encoding="utf-8").splitlines() if cp.is_file() else ["abbrev\tcontext\twritten"]
        self.ctx_head = cl[0].split("\t")
        self.ctx = {(r[0], r[1]): r[2] for r in (l.split("\t") for l in cl[1:])}

    def find(self, tok):
        k = re.sub(r"[.:,;]+$", "", tok)
        if k in self.t: return k, ""
        for n in (1, 2):
            if len(k) > n and re.fullmatch("[ובלמשכה]{%d}" % n, k[:n]) and k[n:] in self.t: return k[n:], k[:n]
        return None

    def out(self, tok, ctx=""):
        """-> (abbrev column, written column) for a body token judged an abbreviation token"""
        f = self.find(tok)
        if not f: return "unknown", tok
        w, kind = self.t[f[0]]
        if kind in ("word", "divine_name"):
            pre = f[1].replace("ה", "") if ctx == "to_idol_possessive" else f[1]
            return f[0], pre + self.ctx.get((f[0], ctx), w)
        return f[0], tok


NEG = {"לא", "ולא", "שלא", "אין", "ואין", "שאין", "אינו", "אינה", "אינם", "אינן", "אינך", "אינני", "איננו", "בל", "בלי", "בלתי"}


def own_context(AB, toks, i):
    """AB-CTX recomputed: the context code at body token i (see ladder_abbrev.CONTEXT)"""
    f = AB.find(toks[i])
    if not f: return ""
    k = lambda x: re.sub(r"[.:,;]+$", "", x)
    if f[0] == "ב״ה" and i > 0 and letters(k(toks[i - 1])).endswith("מקומ"): return "after_makom"
    if f[0] == "כ״א":
        for j in range(i - 1, max(-1, i - 7), -1):
            if toks[j][-1:] in (":", "."): break
            if k(toks[j]) in NEG: return "after_negation"
    if f[0] == "עכו״ם" and i + 1 < len(toks) and k(toks[i + 1])[:2] == "של" and ("ל" in f[1] or (i > 0 and k(toks[i - 1]) in ("אל", "ואל"))):
        return "to_idol_possessive"
    return ""


def abbrev_token(tok):
    return bool(re.search("[׳״]", tok) or re.search("[א-ת][\"'][א-ת]", tok))


def body_tokens(body, AB):
    res, open_ = [], 0
    raw = body.split()
    for i, tok in enumerate(raw):
        in_p = open_ > 0 or "(" in tok
        open_ = max(0, open_ + tok.count("(") - tok.count(")"))
        if in_p: res.append((tok, "cite", "", tok)); continue
        if abbrev_token(tok):
            a, w = AB.out(tok, own_context(AB, raw, i)); res.append((tok, "body", a, w))
        else: res.append((tok, "body", "", tok))
    return res


# ---------------------------------------------------------------- own matcher (rule MA)

def lemma_toks(lemma, AB):
    segs = [[]]
    for tok in lemma.replace("־", " ").split():
        if re.sub(r"[.:,;]+$", "", tok).replace("'", "׳") in ("וגו׳", "וגומר", "וכו׳", "וכולי", "וגו", "וכו"):
            segs.append([]); continue
        f = AB.find(tok)
        if f and AB.t[f[0]][1] in ("divine_name", "match"): c = letters(f[1] + AB.t[f[0]][0])
        else: c = letters(tok)
        if c: segs[-1].append(c)
    return [s for s in segs if s]


def pair_ok(tier, a, b):
    """-> 0 (no), 1 (equal in this tier, no edge used), 2 (an edge difference)"""
    if tier == "exact": return 1 if a == b else 0
    da, db = defective(a), defective(b)
    if da == db: return 1
    if tier == "final":
        fa = a[:-1] + "א" if a.endswith("ה") else a
        fb = b[:-1] + "א" if b.endswith("ה") else b
        return 1 if (fa == fb or defective(fa) == defective(fb)) else 0
    if tier == "edge":
        long_, short = (da, db) if len(da) >= len(db) else (db, da)
        if len(long_) == len(short) + 1 and (long_[1:] == short and long_[0] in "והבלמכש" or long_[:-1] == short): return 2
        if len(long_) == len(short) and long_[:-1] == short[:-1]: return 2
    return 0


def ends_at(seg, wc, i, tier):
    states, ends = {(0, i, 0)}, set()
    while states:
        nxt = set()
        for li, vi, e in states:
            if li == len(seg): ends.add(vi); continue
            if vi < len(wc):
                k = pair_ok(tier, seg[li], wc[vi])
                if k == 1: nxt.add((li + 1, vi + 1, e))
                elif k == 2 and e == 0: nxt.add((li + 1, vi + 1, 1))
                if tier == "join":
                    if li + 1 < len(seg) and pair_ok("matres", seg[li] + seg[li + 1], wc[vi]): nxt.add((li + 2, vi + 1, e))
                    if vi + 1 < len(wc) and pair_ok("matres", seg[li], wc[vi] + wc[vi + 1]): nxt.add((li + 1, vi + 2, e))
        states = nxt
    return ends


def match(segs, wc, start):
    for tier in ("exact", "matres", "join", "final", "edge"):
        for st in sorted({start, 0}, reverse=True):
            for i in range(st, len(wc)):
                e = ends_at(segs[0], wc, i, tier)
                if not e: continue
                pos = min(e); good = True
                for s in segs[1:]:
                    hit = next((min(x) for x in (ends_at(s, wc, j, tier) for j in range(pos, len(wc))) if x), None)
                    if hit is None: good = False; break
                    pos = hit
                if good: return tier, i, pos
    return None


# ---------------------------------------------------------------- the checks of stage 58

def load_k1():
    verse = collections.defaultdict(list); words = {}
    for part in ("hbo", "arc"):
        for r in pq.read_table(K1 / part / "words.parquet", columns=["t", "book", "chapter", "verse", "w", "text"]).to_pylist():
            verse[(r["book"], r["chapter"], r["verse"])].append((r["t"], r["w"], part, letters(r["text"])))
            words[r["t"]] = r
    for k in verse: verse[k].sort()
    pieces = collections.defaultdict(list)
    for part in ("hbo", "arc"):
        for r in pq.read_table(K1 / part / "pieces.parquet", columns=["t", "n", "kind", "lexeme", "class", "marks"]).to_pylist():
            pieces[r["t"]].append(r)
    return verse, words, pieces


def anchors(table, srcs, verse, AB, key, prefix):
    """recompute MA for every row; return list of mismatches and the per-row recomputed results"""
    bad, recs, last = [], {}, {}
    rows = {r[key]: r for r in table}
    for b, c, v, n, raw in srcs:
        cid = f"{prefix}:{b}:{c}:{v}:{n}"
        lem, body = split_comment(raw)
        exp = {"anchor_state": "", "anchor_tier": "", "anchor_t": []}
        if lem is None: exp["anchor_state"] = "no_lemma"
        else:
            segs = lemma_toks(lem, AB)
            ws = verse.get((b, c, v), [])
            if not segs: exp["anchor_state"] = "empty_lemma"
            elif not ws: exp["anchor_state"] = "no_verse"
            else:
                m = match(segs, [x[3] for x in ws], last.get((b, c, v), 0))
                if not m: exp["anchor_state"] = "unanchored"
                else:
                    last[(b, c, v)] = m[2]
                    exp.update(anchor_state="anchored", anchor_tier=m[0], anchor_t=[x[0] for x in ws[m[1]:m[2]]])
        recs[cid] = (lem, body, exp)
        r = rows.get(cid)
        if r is None: bad.append((cid, "missing")); continue
        if (r["lemma"], r["body"]) != ((lem if lem is not None else ""), body): bad.append((cid, "lemma/body"))
        if (r["anchor_state"], r["anchor_tier"], json.loads(r["anchor_t"])) != (exp["anchor_state"], exp["anchor_tier"], exp["anchor_t"]):
            bad.append((cid, "anchor"))
    return bad, recs


def check58(d, AB):
    verse, words, pieces = load_k1()
    P = pq.read_table(d / "banks" / "paraphrase.parquet").to_pylist()
    T = pq.read_table(d / "banks" / "paraphrase_tokens.parquet").to_pylist()
    G = pq.read_table(d / "banks" / "gloss.parquet").to_pylist()
    md, mz = source_strings(SRC_MD), source_strings(SRC_MZ)
    pil = lambda b, c: b == "JON" or (b == "PSA" and c <= 41) or (b == "ISA" and 40 <= c <= 55)

    say("## Rows")
    cond("one paraphrase row per comment string", len(P) == len(md) and len({r["comment"] for r in P}) == len(md),
         f"{len(P)} rows, {len(md)} source strings")
    cond("one gloss row per gloss string", len(G) == len(mz) and len({r["gloss"] for r in G}) == len(mz),
         f"{len(G)} rows, {len(mz)} source strings")

    say("\n## Abbreviation table")
    cond("abbrev.tsv header", AB.head == ["abbrev", "written", "kind"], "\t".join(AB.head))
    headok = all(k in AB.t and AB.t[k][0] == w and AB.t[k][1] == ("divine_name" if k in SPEC_DIVINE else "word")
                 for k, w in SPEC_HEAD.items())
    cond("the specification's head rows stand as written", headok, f"{len(SPEC_HEAD)} head rows")
    cond("at least 100 rows", len(AB.rows) >= 100, f"{len(AB.rows)} rows; kinds " +
         str(dict(collections.Counter(r[2] for r in AB.rows))))
    cond("abbrev_context.tsv: header, and the three context rows of OPEN-ladder 13 (AB-CTX)",
         AB.ctx_head == ["abbrev", "context", "written"] and AB.ctx == {("ב״ה", "after_makom"): "ברוך הוא",
                                                                         ("כ״א", "after_negation"): "כי אם",
                                                                         ("עכו״ם", "to_idol_possessive"): "עבודת כוכבים"},
         f"{len(AB.ctx)} rows")
    nums = [r for r in AB.rows if r[2] == "number"]
    cond("number rows keep the form as written", all(r[0] == r[1] for r in nums), f"{len(nums)} number rows")

    say("\n## Paraphrase bank: anchors (rule MA, recomputed by the validator's own matcher)")
    bad, recs = anchors(P, md, verse, AB, "comment", "md")
    cond("every anchor recomputed equal (state, tier, words)", not bad, f"{len(bad)} differ" + (f", first {bad[:5]}" if bad else ""))
    misses(P, recs, verse, AB, "comment")
    inorder = 0
    for r in P:
        if r["anchor_state"] != "anchored": continue
        ts = json.loads(r["anchor_t"]); vw = [x[0] for x in verse.get((r["book"], r["chapter"], r["verse"]), [])]
        ok = all(t in vw for t in ts) and [vw.index(t) for t in ts] == list(range(vw.index(ts[0]), vw.index(ts[0]) + len(ts)))
        ok = ok and r["anchor_w_from"] == words[ts[0]]["w"] and r["anchor_w_to"] == words[ts[-1]]["w"]
        inorder += not ok
    cond("every anchor's words lie in its verse, in order, w_from/w_to right", inorder == 0, f"{inorder} bad")
    report_anchors(P, "paraphrase (Metzudat David)", pil)

    say("\n## Paraphrase bank: tokens and abbreviations (rule AB, recomputed)")
    tk = collections.defaultdict(list)
    for t in T: tk[t["comment"]].append(t)
    tbad = 0; trace_bad = 0; unk = collections.Counter(); pcount = collections.Counter()
    for r in P:
        lem, body, _ = recs[r["comment"]]
        exp = body_tokens(body, AB); got = sorted(tk.get(r["comment"], []), key=lambda x: x["i"])
        if [x["text"] for x in got] != body.split(): trace_bad += 1
        for i, (e, g) in enumerate(zip(exp, got), 1):
            w = e[3] if e[2] not in ("", "unknown") and AB.t[e[2]][1] in ("word", "divine_name") else e[0]
            if (g["i"], g["part"], g["abbrev"], g["written"], g["words"]) != (i, e[1], e[2], w, len(w.split())): tbad += 1
            if e[2] == "unknown": unk[re.sub(r"[.:,;]+$", "", e[0])] += 1
            if e[1] == "body" and e[2]:
                kind = "unknown" if e[2] == "unknown" else AB.t[e[2]][1]
                pcount["all", kind] += 1
                if pil(r["book"], r["chapter"]): pcount["pilot", kind] += 1
        if len(exp) != len(got): tbad += 1
        if r["tokens"] != sum(1 for e in exp if e[1] == "body") or r["abbrev_unknown"] != sum(1 for e in exp if e[2] == "unknown"): tbad += 1
    cond("every token traced to its comment body (texts in order equal the body's words)", trace_bad == 0, f"{trace_bad} comments differ; {len(T)} tokens")
    cond("token part/abbrev/written/words and the row counts recomputed equal", tbad == 0, f"{tbad} differ")
    for sc in ("all", "pilot"):
        n = sum(v for (s, k), v in pcount.items() if s == sc)
        wo = pcount[sc, "word"] + pcount[sc, "divine_name"]
        cond(f"abbreviation tokens written out >= 90% ({'whole bank' if sc == 'all' else 'step-1 scope'})", n > 0 and wo / n >= .9,
             f"{wo} of {n} ({wo / max(1, n):.1%}); word {pcount[sc, 'word']}, divine_name {pcount[sc, 'divine_name']}, "
             f"number {pcount[sc, 'number']}, unknown {pcount[sc, 'unknown']}")
    allb = sum(1 for t in T if t["part"] == "body")
    say(f"      body tokens {allb}; abbreviation tokens {sum(v for (s, k), v in pcount.items() if s == 'all')} "
        f"({sum(v for (s, k), v in pcount.items() if s == 'all') / allb:.1%} of body tokens)")
    ul = [l.split("\t") for l in (d / "banks" / "unknown_abbrev.tsv").read_text(encoding="utf-8").splitlines()]
    got = {x[0]: int(x[1]) for x in ul[1:]}
    exok = all(any(t["comment"] == x[2] and re.sub(r"[.:,;]+$", "", t["text"]) == x[0] and t["abbrev"] == "unknown"
                   for t in tk.get(x[2], [])) for x in ul[1:])
    cond("unknown_abbrev.tsv lists every unknown with its count and a true example", ul[0] == ["abbrev", "count", "example"]
         and got == dict(unk) and exok, f"{len(got)} forms, {sum(got.values())} tokens (recomputed {len(unk)} / {sum(unk.values())})")

    say("\n## Paraphrase bank: markers (rule FIG, recomputed)")
    mbad = 0; mc = collections.Counter()
    for r in P:
        _, body, _ = recs[r["comment"]]
        exp = own_markers(body_tokens(body, AB))
        if json.loads(r["markers"]) != exp or r["figure"] != ("figure" in exp): mbad += 1
        for m in exp:
            mc["all", m] += 1
            if pil(r["book"], r["chapter"]): mc["pilot", m] += 1
        if r["in_pilot"] != pil(r["book"], r["chapter"]): mbad += 1
    cond("markers, figure and in_pilot recomputed equal", mbad == 0, f"{mbad} differ")
    for m in ("figure", "as_if", "para", "repeat", "cite", "refers"):
        say(f"      {m}: all {mc['all', m]}, step-1 scope {mc['pilot', m]}")

    say("\n## Gloss bank: anchors (rule MA, recomputed)")
    bad, grecs = anchors(G, mz, verse, AB, "gloss", "mz")
    cond("every gloss anchor recomputed equal", not bad, f"{len(bad)} differ" + (f", first {bad[:5]}" if bad else ""))
    misses(G, grecs, verse, AB, "gloss")
    report_anchors(G, "gloss (Metzudat Zion)", pil)

    say("\n## Gloss bank: kind and core (rule ZC), fit (FIT), rare (RARE)")
    zbad = trace = 0; kc = collections.Counter()
    for r in G:
        _, body, _ = grecs[r["gloss"]]
        kind, src = own_zc(body)
        core = " ".join(AB.out(w)[1] if abbrev_token(w) else w for w in src) if kind == "gloss" else ""
        if (r["kind"], r["core"], r["core_words"]) != (kind, core, len(src) if kind == "gloss" else 0): zbad += 1
        if kind == "gloss":
            bw = [re.sub(r"[.:,;]+$", "", w) for w in body.split()]
            if not any(bw[i:i + len(src)] == src for i in range(len(bw))): trace += 1
        kc[r["book"], r["kind"], r["fit"]] += 1
    cond("kind, core and core_words recomputed equal", zbad == 0, f"{zbad} differ")
    cond("every core traced to a run of words of its gloss body", trace == 0, f"{trace} not found")
    idx = collections.defaultdict(list)
    for t, w in words.items(): idx[letters(w["text"])].append(t)
    lex = {}
    with open(K1 / "lexicon" / "lexemes.tsv", encoding="utf-8") as f:
        h = f.readline().rstrip("\n").split("\t")
        for line in f:
            x = line.rstrip("\n").split("\t"); lex[x[h.index("lexeme")]] = int(x[h.index("tanakh")] or 0)
    others = sorted(r["gloss"] for r in G if not r["in_pilot"])
    sample = set(random.Random(SEED).sample(others, 1000))
    fbad = []; nchk = 0
    for r in G:
        if not (r["in_pilot"] or r["gloss"] in sample): continue
        nchk += 1
        exp = own_fit(r, grecs[r["gloss"]], verse, words, pieces, idx, AB)
        if exp != (r["fit"], r["fit_form"], r["fit_lexeme"]): fbad.append((r["gloss"], exp, (r["fit"], r["fit_form"])))
    cond("fit, fit_form, fit_lexeme recomputed (step-1 scope + 1,000 others, seed ladder-2026-11-24)", not fbad,
         f"{nchk} rows checked, {len(fbad)} differ" + (f", first {fbad[:3]}" if fbad else ""))
    rbad = 0; ftrace = 0
    for r in G:
        _, _, e = grecs[r["gloss"]]
        st = None
        if e["anchor_state"] == "anchored" and len(e["anchor_t"]) == 1 and sum(len(s) for s in lemma_toks(grecs[r["gloss"]][0], AB)) == 1:
            stems = sorted((p for p in pieces[e["anchor_t"][0]] if p["kind"] == "stem"), key=lambda p: p["n"])
            st = stems[0] if stems else None
        expc = lex.get(st["lexeme"]) if st else None
        exp = (e["anchor_t"][0] if st else None, st["n"] if st else None, st["lexeme"] if st else "", expc, expc is not None and expc < 20)
        if (r["src_t"], r["src_n"], r["src_lexeme"], r["src_count"], r["rare"]) != exp: rbad += 1
        if r["fit"] == "fits" and not any(pointed(words[t]["text"]) == r["fit_form"] for t in idx.get(letters(r["core"]), [])): ftrace += 1
        if r["in_pilot"] != pil(r["book"], r["chapter"]): rbad += 1
    cond("src_t, src_n, src_lexeme, src_count, rare, in_pilot recomputed for every row", rbad == 0, f"{rbad} differ")
    cond("every fit_form traced to a Tanakh word of the core's consonants", ftrace == 0, f"{ftrace} not found")
    say("      counts per book x kind x fit (fit '' = not decided):")
    for b in sorted({k[0] for k in kc}, key=lambda b: (GENRE.get(b, "z"), b)):
        cells = ", ".join(f"{k[1]}/{k[2] or '-'} {v}" for k, v in sorted(kc.items()) if k[0] == b)
        say(f"      {b}: {cells}")
    tot = collections.Counter()
    for (b, k, f), v in kc.items(): tot[k] += v; tot["fit:" + (f or "-")] += v
    say(f"      all: {dict(sorted(tot.items()))}")
    for sc, sel in (("step-1 scope", lambda r: r["in_pilot"]), ("all", lambda r: True)):
        c = collections.Counter(r["fit"] for r in G if sel(r)); rr = sum(1 for r in G if sel(r) and r["rare"])
        say(f"      {sc}: fits {c['fits']}, form_other {c['form_other']}, unattested {c['unattested']}, phrase {c['phrase']}, rare {rr}, rare+fits {sum(1 for r in G if sel(r) and r['rare'] and r['fit'] == 'fits')}")

    say("\n## Latin-letter check (text columns)")
    lat = re.compile("[A-Za-z]")
    nl = sum(1 for r in P for c in ("lemma", "body") if lat.search(r[c] or ""))
    nl += sum(1 for r in T for c in ("text", "written") if lat.search(r[c] or ""))
    nl += sum(1 for r in G for c in ("lemma", "body", "core", "fit_form") if lat.search(r[c] or ""))
    nl += sum(1 for r in AB.rows for c in r[:2] if lat.search(c))
    nl += sum(1 for x in ul[1:] if lat.search(x[0]))
    cond("no letter A-Z or a-z in a text column", nl == 0, f"{nl} values")

    say("\n## Sealed sample, sources, build.json")
    sl = [l.split("\t") for l in (d / "sealed" / "chooser_sample.tsv").read_text(encoding="utf-8").splitlines()]
    rng = random.Random(SEED); exp = []
    for p, sel in (("JON", lambda b, c: b == "JON"), ("PSA1-41", lambda b, c: b == "PSA" and c <= 41), ("ISA40-55", lambda b, c: b == "ISA" and 40 <= c <= 55)):
        ids = sorted(r["comment"] for r in P if r["anchor_state"] == "anchored" and sel(r["book"], r["chapter"]))
        exp += [[p, c] for c in rng.sample(ids, 20)]
    bj = json.loads((d / "build.json").read_text(encoding="utf-8"))
    cond("sealed/chooser_sample.tsv: 60 rows, 20 per portion, drawn as 5.5", sl[0] == ["portion", "comment"] and sl[1:] == exp
         and collections.Counter(x[0] for x in sl[1:]) == {"JON": 20, "PSA1-41": 20, "ISA40-55": 20}, f"{len(sl) - 1} rows")
    cond("its sha256 in build.json (sealed_chooser)", bj.get("sealed_chooser") == sha(d / "sealed" / "chooser_sample.tsv"), bj.get("sealed_chooser", "")[:16])
    sj = json.loads((d / "sources.json").read_text(encoding="utf-8"))
    ok = all(sj.get(str(p.relative_to(REPO)), {}).get("license") == LIC and sj[str(p.relative_to(REPO))]["sha256"] == sha(p) for p in (SRC_MD, SRC_MZ))
    ok = ok and all(v["sha256"] == sha(REPO / k) for k, v in sj.items())
    cond("sources.json pins both Metzudot files (sha256, 'Public Domain, Sefaria, On Your Way') and every input", ok, f"{len(sj)} inputs")
    fb = [k for k, v in bj.get("files", {}).items() if not (d / k).is_file() or sha(d / k) != v]
    cond("build.json's file checksums equal the files", not fb and len(bj.get("files", {})) >= 8, f"{len(bj.get('files', {}))} files, {len(fb)} differ")
    return bj


def misses(rows, recs, verse, AB, key):
    """every row not anchored, by kind: abbrev_in_lemma, neighbour_verse, partial, absent (and no_lemma, empty_lemma)"""
    kinds = collections.Counter(); lines = []
    for r in rows:
        if r["anchor_state"] == "anchored": continue
        lem = recs[r[key]][0]
        if r["anchor_state"] != "unanchored": k = r["anchor_state"]
        else:
            segs = lemma_toks(lem, AB); flat = [t for s in segs for t in s]
            wc = [x[3] for x in verse.get((r["book"], r["chapter"], r["verse"]), [])]
            if any(re.sub(r"[.:,;]+$", "", t).replace("'", "׳") in ("כו׳", "כו") for t in lem.split()): k = "gap_kw"
            elif any(match(segs, [x[3] for x in verse.get((r["book"], r["chapter"], r["verse"] + dv), [])], 0) for dv in (-1, 1)):
                k = "neighbour_verse"
            elif all(any(pair_ok("matres", t, w) for w in wc) for t in flat):
                k = "list_comma" if "," in lem else "order"
            elif any(pair_ok("matres", t, w) for t in flat for w in wc): k = "list_comma" if "," in lem else "partial"
            else: k = "absent"
        kinds[k] += 1
        lines.append(f"        {r[key]}  {k}  [{lem if lem is not None else ''}]  {(r['body'][:40] if k in ('no_lemma',) else '')}")
    say(f"      not anchored, by kind: {dict(kinds)}")
    for l in lines: say(l)


def report_anchors(rows, name, pil):
    by = collections.defaultdict(collections.Counter)
    for r in rows:
        by[r["book"]][r["anchor_state"]] += 1
        if r["anchor_tier"]: by[r["book"]]["t_" + r["anchor_tier"]] += 1
    worst = []
    say(f"      {name}: book, anchored / with a lemma (target >= 90%), tiers exact/matres/join/final/edge, states unanchored/no_verse/no_lemma/empty_lemma")
    for b in sorted(by, key=lambda b: (GENRE.get(b, "z"), b)):
        c = by[b]; n = c["anchored"] + c["unanchored"] + c["no_verse"]
        if n: worst.append((c["anchored"] / n, b))
        say(f"      {b:4} {c['anchored']:5} / {n:5} {c['anchored'] / max(1, n):6.1%}  "
            f"{c['t_exact']}/{c['t_matres']}/{c['t_join']}/{c['t_final']}/{c['t_edge']}  "
            f"{c['unanchored']}/{c['no_verse']}/{c['no_lemma']}/{c['empty_lemma']}")
    low = [w for w in worst if w[0] < .9]
    cond(f"{name}: anchored >= 90% of the comments with a lemma in every book", worst and not low,
         f"lowest {min(worst)[1]} {min(worst)[0]:.1%}; {len(low)} books under 90%")
    anch = sum(c["anchored"] for c in by.values()); edge = sum(c["t_edge"] for c in by.values())
    cond(f"{name}: edge tier <= 1% of the anchored", anch and edge / anch <= .01, f"{edge} of {anch} ({edge / max(1, anch):.2%})")
    for p, sel in (("JON", lambda r: r["book"] == "JON"), ("PSA1-41", lambda r: r["book"] == "PSA" and r["chapter"] <= 41),
                   ("ISA40-55", lambda r: r["book"] == "ISA" and 40 <= r["chapter"] <= 55), ("RUT", lambda r: r["book"] == "RUT"),
                   ("GEN22-25", lambda r: r["book"] == "GEN")):
        c = collections.Counter(); [c.update([r["anchor_state"], "t_" + r["anchor_tier"]]) for r in rows if sel(r)]
        say(f"      portion {p}: rows {sum(v for k, v in c.items() if not k.startswith('t_'))}, anchored {c['anchored']} "
            f"(exact {c['t_exact']}, matres {c['t_matres']}, join {c['t_join']}, final {c['t_final']}, edge {c['t_edge']}), "
            f"unanchored {c['unanchored']}, no_lemma {c['no_lemma']}")
    g = collections.defaultdict(collections.Counter)
    for r in rows:
        g[GENRE.get(r["book"], "other")]["rows"] += 1; g[GENRE.get(r["book"], "other")][r["anchor_state"]] += 1
    for k in ("narrative", "prophets", "poetry+wisdom", "other"):
        c = g[k]; n = c["anchored"] + c["unanchored"] + c["no_verse"]
        say(f"      genre {k}: rows {c['rows']}, anchored {c['anchored']} of {n} with a lemma ({c['anchored'] / max(1, n):.1%})")


def own_markers(toks):
    bw = [re.sub(r"[.:,;]+$", "", t[0]) for t in toks if t[1] == "body"]
    def at(i, word, pre):
        return bw[i] == word or (pre and len(bw[i]) > 1 and bw[i][0] in "ובהכלש" and bw[i][1:] == word)
    def has(*phrases):
        for ph in phrases:
            ws = ph.split()
            if any(all(at(i + j, w, j == 0) for j, w in enumerate(ws)) for i in range(len(bw) - len(ws) + 1)): return True
        return False
    m = set()
    if has("מליצה", "משל", "דרך השאלה", "לשון השאלה"): m.add("figure")
    if has("כאלו", "כאילו"): m.add("as_if")
    if has("ר״ל", 'ר"ל', "רצה לומר", "כלומר", "כאומר", "כאילו אמר", "כאלו אמר"): m.add("para")
    if has("כפל"): m.add("repeat")
    if has("כמ״ש", 'כמ"ש', "כמו שנאמר", "וכן נאמר", "עיין"): m.add("cite")
    if has("מוסב", "חוזר", "מקרא קצר"): m.add("refers")
    books = set("בראשית שמות ויקרא במדבר דברים יהושע שופטים שמואל מלכים ישעיה ישעיהו ירמיה ירמיהו יחזקאל הושע יואל עמוס "
                "עובדיה יונה מיכה נחום חבקוק צפניה חגי זכריה מלאכי תהלים תהילים משלי איוב שה״ש רות איכה קהלת אסתר דניאל "
                "עזרא נחמיה דה״א דה״ב ד״ה ש״א ש״ב מ״א מ״ב".split())
    for t in toks:
        if t[1] != "cite": continue
        x = re.sub(r"^[(]+|[().:,;]+$", "", t[0]).replace("(", "").replace(")", "")
        if x in books or (len(x) > 1 and x[0] in "ובהכלש" and x[1:] in books): m.add("cite")
    return sorted(m)


def own_zc(body):
    ws = body.split()
    strip = lambda w: re.sub(r"[.:,;]+$", "", w)
    i = 0
    while i < len(ws) and strip(ws[i]) in {"ענין", "עניינו", "ענינו", "הוא", "היא", "הם", "הן", "כן", "גם", "זה", "זו"}: i += 1
    if i >= len(ws): return "none", []
    if strip(ws[i]) in ("מלשון", "מל׳"): return "root", []
    if strip(ws[i]) in ("כמו", "וכן", "ודומה", "עיין") or ws[i][:1] == "(": return "cite_only", []
    core = []
    for w in ws[i:]:
        if "(" in w or strip(w) in {"כמו", "וכן", "ודומה", "ר״ל", "מלשון", "והוא", "ומזה", "ועל", "כי"}: break
        if strip(w): core.append(strip(w))
        if re.search(r"[.:,;]$", w): break
    if not core: return "none", []
    return ("gloss", core) if len(core) <= 3 else ("long", core)


def own_fit(r, rec, verse, words, pieces, idx, AB):
    lem, body, e = rec
    kind, src = own_zc(body)
    nlem = sum(len(s) for s in lemma_toks(lem, AB)) if lem is not None else 0
    if kind != "gloss" or e["anchor_state"] != "anchored": return ("", "", "")
    if 2 <= nlem <= 3 or 2 <= len(src) <= 3: return ("phrase", "", "")
    if not (nlem == 1 and len(src) == 1 and len(e["anchor_t"]) == 1): return ("", "", "")

    def shape(t):
        ps = sorted(pieces[t], key=lambda p: p["n"])
        st = [p for p in ps if p["kind"] == "stem"]
        if not st: return None
        return (st[0]["class"], tuple(p["lexeme"] for p in ps if p["kind"] == "prefix"),
                tuple((json.loads(p["marks"] or "{}").get("person", ""), json.loads(p["marks"] or "{}").get("gender", ""),
                       json.loads(p["marks"] or "{}").get("number", "")) for p in ps if p["kind"] == "suffix"),
                json.loads(st[0]["marks"] or "{}"), st[0]["lexeme"])
    g = shape(e["anchor_t"][0])
    if g is None: return ("", "", "")
    core = AB.out(src[0])[1] if abbrev_token(src[0]) else src[0]
    cand = idx.get(letters(core), [])
    if not cand: return ("unattested", "", "")
    good = []
    for t in cand:
        w = shape(t)
        if w is None or w[:3] != g[:3]: continue
        fine = True
        for k in ("type", "person", "gender", "number", "state"):
            gv = g[3].get(k)
            if not gv: continue
            wv = w[3].get(k)
            if not wv: fine = False; break
            if gv != wv and not (k == "gender" and {gv, wv} <= {"m", "f", "c", "b"} and {gv, wv} & {"c", "b"}): fine = False; break
        if fine: good.append((pointed(words[t]["text"]), w[4]))
    if not good: return ("form_other", "", "")
    fc = collections.Counter(x[0] for x in good)
    form = min(fc, key=lambda f: (-fc[f], f))
    lc = collections.Counter(x[1] for x in good if x[0] == form)
    return ("fits", form, min(lc, key=lambda l: (-lc[l], l)))


def rebuild(d, bj):
    """build twice into fresh scratch folders and compare every file's sha256 with the build's"""
    base = Path("/tmp/claude-1000/source-examples/ladder58")
    n = 1
    while (base / f"rebuild-{n}").exists(): n += 1
    sums = []
    for k in (n, n + 1):
        out = base / f"rebuild-{k}"
        subprocess.run([sys.executable, "-I", str(MAC / "build_ladder.py"), "--build", "pilot-1", "--stage", "58", "--out", str(out)],
                       check=True, capture_output=True)
        sums.append({str(p.relative_to(out)): sha(p) for p in out.rglob("*") if p.is_file() and p.name != "VALIDATION.md"})
    mine = {str(p.relative_to(d)): sha(p) for p in d.rglob("*") if p.is_file() and p.name != "VALIDATION.md"
            and "cache" not in p.relative_to(d).parts}
    # a build that carries stage 60 has the chooser's files and has extended sources.json, COLUMNS.md and build.json:
    # those three must hold stage 58's content whole (a subset or a prefix); the chooser's own files are stage 60's check
    later = "stage60" in bj
    out = base / f"rebuild-{n}"
    def kept58(k):
        a, b = (out / k).read_text(encoding="utf-8"), (d / k).read_text(encoding="utf-8")
        if k == "COLUMNS.md": return b.startswith(a)
        ja, jb = json.loads(a), json.loads(b)
        if k == "sources.json": return all(jb.get(x) == v for x, v in ja.items())
        for x, v in ja.items():
            if x == "files":
                if any(jb["files"].get(f) != h for f, h in v.items() if f not in ("sources.json", "COLUMNS.md")): return False
            elif x == "code":
                if any(jb["code"].get(f) != h for f, h in v.items()): return False
            elif jb.get(x) != v: return False
        return True
    diff = []
    for k in sorted(set(sums[0]) | set(mine)):
        if sums[0].get(k) != sums[1].get(k): diff.append(k)
        elif later and k not in sums[0] and (k.startswith("chooser/") or k == "categories.toml"): continue
        elif "stage61" in bj and k not in sums[0] and (k.split("/")[0] in ("texts", "lines", "layout") or k in (
                "profiles.toml", "changes.parquet", "differ.tsv", "thin.tsv", "sealed/step_sample.tsv", "GUIDE.md", "README.md")):
            continue        # stage 61's files: its own check (validate_ladder61)
        elif "stage62" in bj and k not in sums[0] and k.split("/")[0] == "english":
            continue        # stage 62's files: its own check (validate_ladder62)
        elif k == "pack/README.md" and k not in sums[0] and (d / k).stat().st_size > 0:
            continue        # stage 63's prose note for research (no builder writes it; stage 62's 6-word scan reads it)
        elif later and k in ("sources.json", "COLUMNS.md", "build.json") and k in mine:
            if not kept58(k): diff.append(k)
        elif sums[0].get(k) != mine.get(k): diff.append(k)
    cond("two rebuilds give the same sha256 for every file (and equal the build" + (
         "; sources.json, COLUMNS.md and build.json hold stage 58's content whole" if later else "") + ")", not diff,
         f"{len(sums[0])} files; differ: {diff[:6]} (scratch rebuild-{n}, rebuild-{n + 1})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default="pilot-1"); ap.add_argument("--upto", type=int, required=True)
    ap.add_argument("--dir"); ap.add_argument("--dir59"); ap.add_argument("--no-rebuild", action="store_true"); ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    d = Path(a.dir) if a.dir else DATA / "hebrew-ladder" / a.build
    say(f"# Validation of the Hebrew ladder, build {a.build}, up to stage {a.upto}\n\nfolder: {d}\n")
    if a.upto >= 58:
        say("# Stage 58: the banks\n")
        AB = Abbrev(d / "banks" / "abbrev.tsv")
        bj = check58(d, AB)
        if a.no_rebuild: cond("two rebuilds give the same sha256", None, "skipped (--no-rebuild)")
        else: rebuild(d, bj)
    d59 = Path(a.dir59) if a.dir59 else DATA / "hebrew-levels" / "pilot-2"
    if a.upto >= 59:
        sys.path.insert(0, str(MAC))
        import validate_ladder59
        validate_ladder59.Check59(d59, cond, say).run(rebuild=not a.no_rebuild)
    if a.upto >= 60:
        sys.path.insert(0, str(MAC))
        import validate_ladder60
        validate_ladder60.Check60(d, cond, say).run(rebuild=not a.no_rebuild)
    if a.upto >= 61:
        sys.path.insert(0, str(MAC))
        import validate_ladder61
        validate_ladder61.Check61(d, d59, cond, say).run(rebuild=not a.no_rebuild)
    if a.upto >= 62:
        sys.path.insert(0, str(MAC))
        import validate_ladder62
        validate_ladder62.Check62(d, cond, say).run(rebuild=not a.no_rebuild)
    if a.upto >= 63:
        cond("stages after 62", False, "not built yet")
    c = collections.Counter(RESULTS)
    say(f"\nPASS {c['PASS']}, SKIP {c['SKIP']}, FAIL {c['FAIL']}")
    if (not a.dir and not a.dir59) or a.write:
        (d / "VALIDATION.md").write_text("\n".join(LOG) + "\n", encoding="utf-8")
    if a.upto >= 59 and (not a.dir59 or a.write) and d59.is_dir():
        (d59 / "VALIDATION.md").write_text("\n".join(LOG) + "\n", encoding="utf-8")
    sys.exit(1 if c["FAIL"] else 0)


if __name__ == "__main__":
    main()
