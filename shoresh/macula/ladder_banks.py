"""Stage 58 of the Hebrew ladder: the paraphrase bank (Metzudat David) and the gloss bank (Metzudat Zion).

SPEC-ladder 4 and 5 (internal-docs/source-examples-spec/ladder/SPEC-ladder.md). Rule only, no model. Reads the two
Metzudot files as JSON only (untrusted downloaded data) and build k1 (`hbo`, `arc`, `lexicon`).
"""
import collections, json, random, re, unicodedata as ud
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from macula import ladder_abbrev

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
K1 = DATA / "source-examples" / "k1"
MD = DATA / "metzudat_david_chapters.jsonl"
MZ = DATA / "metzudat_zion_chapters.jsonl"

INVISIBLE = dict.fromkeys(map(ord, "‎‏​‌‍﻿"))
TAG = re.compile(r"<[^>]+>")
BOLD = re.compile(r"\s*<b>(.*?)</b>(.*)", re.S)
FINALS = str.maketrans("ךםןףץ", "כמנפצ")
MAQAF = "־"
PUNCT = ".:,;"
PREFIX_AB = "ובלמשכה"
GAPS = {"וגו׳", "וגומר", "וכו׳", "וכולי", "וגו", "וכו"}
TIERS = ("exact", "matres", "join", "final", "edge")
EDGE_LEAD = "והבלמכש"
PORTIONS = ("JON", "PSA1-41", "ISA40-55")
SEED = "ladder-2026-11-24"


def portion_of(book, chapter):
    if book == "JON": return "JON"
    if book == "PSA" and chapter <= 41: return "PSA1-41"
    if book == "ISA" and 40 <= chapter <= 55: return "ISA40-55"
    return ""


def cons(text):
    return "".join(c for c in ud.normalize("NFD", text or "") if "א" <= c <= "ת").translate(FINALS)


def nomat(c):
    return c[:1] + c[1:].replace("ו", "").replace("י", "") if c else c


def final_ha(c):
    return c[:-1] + "א" if c.endswith("ה") else c


def point(text):
    """SPEC-levels 7.3 `point` of one word: pointed without accents, NFD"""
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


# ---------------------------------------------------------------- inputs

def load_k1():
    """verse -> [(t, w, part, cons)], book order, word records for rule FIT, lexeme counts"""
    verse = collections.defaultdict(list); order = []; wrec = {}
    for part in ("hbo", "arc"):
        for r in pq.read_table(K1 / part / "words.parquet", columns=["t", "book", "chapter", "verse", "w", "text"]).to_pylist():
            verse[(r["book"], r["chapter"], r["verse"])].append((r["t"], r["w"], part, cons(r["text"])))
            wrec[r["t"]] = {"text": r["text"], "part": part, "pre": [], "suf": [], "stem": None}
    for part in ("hbo", "arc"):
        for r in pq.read_table(K1 / part / "pieces.parquet", columns=["t", "n", "kind", "lexeme", "class", "marks"]).to_pylist():
            rec = wrec[r["t"]]
            if r["kind"] == "prefix": rec["pre"].append((r["n"], r["lexeme"]))
            elif r["kind"] == "suffix":
                m = json.loads(r["marks"] or "{}")
                rec["suf"].append((r["n"], (m.get("person", ""), m.get("gender", ""), m.get("number", ""))))
            elif r["kind"] == "stem" and rec["stem"] is None:
                rec["stem"] = (r["n"], r["lexeme"], r["class"], json.loads(r["marks"] or "{}"))
    for k in verse: verse[k].sort()
    seen = set()
    for r in pq.read_table(K1 / "hbo" / "words.parquet", columns=["t", "book"]).to_pylist():
        if r["book"] not in seen: seen.add(r["book"]); order.append(r["book"])
    for rec in wrec.values():
        rec["pre"] = tuple(x[1] for x in sorted(rec["pre"]))
        rec["suf"] = tuple(x[1] for x in sorted(rec["suf"]))
    counts = {}
    with open(K1 / "lexicon" / "lexemes.tsv", encoding="utf-8") as f:
        head = f.readline().rstrip("\n").split("\t"); il, it = head.index("lexeme"), head.index("tanakh")
        for line in f:
            x = line.rstrip("\n").split("\t"); counts[x[il]] = int(x[it] or 0)
    return verse, order, wrec, counts


def comments(path):
    """(book, chapter, verse, n, raw string) in the source's order"""
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        for vi, cs in enumerate(r["verses"] or [], 1):
            if isinstance(cs, str): cs = [cs]
            for n, c in enumerate(cs, 1):
                yield r["book"], int(r["chapter"]), vi, n, c


def parse(raw):
    """4.1: (lemma or None, body)"""
    s = raw.translate(INVISIBLE)
    m = BOLD.match(s)
    if not m: return None, TAG.sub("", s).strip()
    return TAG.sub("", m.group(1)).strip().rstrip(" .:").strip(), TAG.sub("", m.group(2)).strip()


# ---------------------------------------------------------------- rule AB

TABLE = {a: (w, k) for a, w, k in ladder_abbrev.rows()}


def is_abbrev_token(tok):
    if "״" in tok or "׳" in tok: return True
    return re.search(r"[א-ת][\"'][א-ת]", tok) is not None


def lookup(tok):
    """-> (row abbrev, prefixes, written, kind) or None; trailing punctuation set apart"""
    core = tok.rstrip(PUNCT)
    if core in TABLE: return core, "", TABLE[core][0], TABLE[core][1]
    for k in (1, 2):
        pre, rest = core[:k], core[k:]
        if len(core) > k and all(c in PREFIX_AB for c in pre) and rest in TABLE:
            return rest, pre, TABLE[rest][0], TABLE[rest][1]
    return None


def tokens(body):
    """4.4: [(text, part, abbrev, written, words)]"""
    out = []; depth = 0
    for tok in body.split():
        cite = depth > 0 or "(" in tok
        depth = max(0, depth + tok.count("(") - tok.count(")"))
        if cite:
            out.append((tok, "cite", "", tok, len(tok.split()))); continue
        ab, written = "", tok
        if is_abbrev_token(tok):
            hit = lookup(tok)
            if hit is None: ab = "unknown"
            else:
                ab = hit[0]
                if hit[3] in ("word", "divine_name"):
                    w = hit[2].split(); w[0] = hit[1] + w[0]; written = " ".join(w)
        out.append((tok, "body", ab, written, len(written.split())))
    return out


# ---------------------------------------------------------------- rule MA

def lemma_segments(lemma):
    segs, cur = [], []
    for tok in lemma.replace(MAQAF, " ").split():
        g = tok.rstrip(PUNCT).replace("'", "׳")
        if g in GAPS:
            if cur: segs.append(cur); cur = []
            continue
        hit = lookup(tok)
        c = cons(hit[1] + hit[2]) if hit and hit[3] in ("divine_name", "match") else cons(tok)
        if c: cur.append(c)
    if cur: segs.append(cur)
    return segs


def edge_pair(a, b):
    x, y = nomat(a), nomat(b)
    if x == y: return False
    for p, q in ((x, y), (y, x)):
        if len(p) == len(q) + 1 and p[0] in EDGE_LEAD and p[1:] == q: return True
        if len(p) == len(q) + 1 and p[:-1] == q: return True
    return len(x) == len(y) and len(x) > 0 and x[:-1] == y[:-1]


def base_eq(a, b):
    return a == b or nomat(a) == nomat(b)


def seg_ends(seg, wc, i, tier):
    """every end e such that lemma tokens seg match verse tokens wc[i:e] in this tier"""
    ends = set()

    def go(li, vi, edges):
        if li == len(seg): ends.add(vi); return
        if vi >= len(wc): return
        l, w = seg[li], wc[vi]
        if tier == "exact":
            if l == w: go(li + 1, vi + 1, edges)
            return
        if base_eq(l, w): go(li + 1, vi + 1, edges)
        elif tier == "final" and base_eq(final_ha(l), final_ha(w)): go(li + 1, vi + 1, edges)
        elif tier == "edge" and edges == 0 and edge_pair(l, w): go(li + 1, vi + 1, 1)
        if tier == "join":
            if li + 1 < len(seg) and base_eq(l + seg[li + 1], w): go(li + 2, vi + 1, edges)
            if vi + 1 < len(wc) and base_eq(l, w + wc[vi + 1]): go(li + 1, vi + 2, edges)
    go(0, i, 0)
    return ends


def anchor(segs, wc, start):
    """-> (tier, first index, end index) or None"""
    for tier in TIERS:
        for st in ((start, 0) if start > 0 else (0,)):
            for i in range(st, len(wc)):
                e = seg_ends(segs[0], wc, i, tier)
                if not e: continue
                end = min(e); ok = True
                for s in segs[1:]:
                    nxt = None
                    for j in range(end, len(wc)):
                        e2 = seg_ends(s, wc, j, tier)
                        if e2: nxt = min(e2); break
                    if nxt is None: ok = False; break
                    end = nxt
                if ok: return tier, i, end
    return None


# ---------------------------------------------------------------- rule FIG

def _w(*xs): return [list(x.split()) for x in xs]
MARKERS = {
    "figure": _w("מליצה", "משל", "דרך השאלה", "לשון השאלה"),
    "as_if": _w("כאלו", "כאילו"),
    "para": _w("ר״ל", 'ר"ל', "רצה לומר", "כלומר", "כאומר", "כאילו אמר", "כאלו אמר"),
    "repeat": _w("כפל"),
    "cite": _w("כמ״ש", 'כמ"ש', "כמו שנאמר", "וכן נאמר", "עיין"),
    "refers": _w("מוסב", "חוזר", "מקרא קצר"),
}
BOOKS = set("""בראשית שמות ויקרא במדבר דברים יהושע שופטים שמואל מלכים ישעיה ישעיהו ירמיה ירמיהו יחזקאל הושע יואל עמוס
עובדיה יונה מיכה נחום חבקוק צפניה חגי זכריה מלאכי תהלים תהילים משלי איוב שה״ש רות איכה קהלת אסתר דניאל עזרא נחמיה
דה״א דה״ב ד״ה ש״א ש״ב מ״א מ״ב""".split())


def word_is(tok, target, first):
    if tok == target: return True
    return first and len(tok) > 1 and tok[0] in "ובהכלש" and tok[1:] == target


def markers(toks):
    body = [t[0].rstrip(PUNCT) for t in toks if t[1] == "body"]
    found = set()
    for code, phrases in MARKERS.items():
        for ph in phrases:
            for i in range(len(body) - len(ph) + 1):
                if all(word_is(body[i + j], ph[j], j == 0) for j in range(len(ph))):
                    found.add(code); break
            if code in found: break
    for t in toks:
        if t[1] == "cite":
            x = t[0].strip("().:,;")
            if x in BOOKS or (len(x) > 1 and x[0] in "ובהכלש" and x[1:] in BOOKS): found.add("cite")
    return sorted(found)


# ---------------------------------------------------------------- rule ZC and FIT

OPENERS = {"ענין", "עניינו", "ענינו", "הוא", "היא", "הם", "הן", "כן", "גם", "זה", "זו"}
STOPS = {"כמו", "וכן", "ודומה", "ר״ל", "מלשון", "והוא", "ומזה", "ועל", "כי"}


def zc(body):
    """-> (kind, source core words, why) ; why notes the case of an empty core"""
    words = body.split(); k = 0
    while k < len(words) and words[k].rstrip(PUNCT) in OPENERS: k += 1
    if k == len(words): return "none", [], "nothing_left"
    first = words[k].rstrip(PUNCT)
    if first in ("מלשון", "מל׳"): return "root", [], ""
    if first in ("כמו", "וכן", "ודומה", "עיין") or words[k].startswith("("): return "cite_only", [], ""
    core = []
    for w in words[k:]:
        if "(" in w: break
        s = w.rstrip(PUNCT)
        if s in STOPS: break
        if s: core.append(s)
        if s != w: break
    if not core: return "none", [], "stop_first"
    return ("gloss" if len(core) <= 3 else "long"), core, ""


def write_core(core):
    out = []
    for w in core:
        if is_abbrev_token(w):
            hit = lookup(w)
            if hit and hit[3] in ("word", "divine_name"):
                x = hit[2].split(); x[0] = hit[1] + x[0]; out.append(" ".join(x)); continue
        out.append(w)
    return " ".join(out)


MARK_KEYS = ("type", "person", "gender", "number", "state")


def mark_ok(key, g, w):
    if w is None or w == "": return False
    if g == w: return True
    return key == "gender" and {g, w} <= {"m", "f", "c", "b"} and bool({g, w} & {"c", "b"})


def agrees(W, G):
    if W["stem"] is None or G["stem"] is None: return False
    if W["stem"][2] != G["stem"][2] or W["pre"] != G["pre"] or W["suf"] != G["suf"]: return False
    gm, wm = G["stem"][3], W["stem"][3]
    return all(mark_ok(k, gm[k], wm.get(k)) for k in MARK_KEYS if gm.get(k))


def best(counter):
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


# ---------------------------------------------------------------- the build

def anchor_fields(lemma, verse, book, ch, v, starts):
    """-> dict of the anchor columns, the number of lemma words, the matched word records"""
    out = {"anchor_state": "", "anchor_tier": "", "anchor_part": "", "anchor_t": "[]", "anchor_w_from": None, "anchor_w_to": None}
    if lemma is None: out["anchor_state"] = "no_lemma"; return out, 0, []
    segs = lemma_segments(lemma)
    nlem = sum(len(s) for s in segs)
    if not segs: out["anchor_state"] = "empty_lemma"; return out, nlem, []
    ws = verse.get((book, ch, v))
    if not ws: out["anchor_state"] = "no_verse"; return out, nlem, []
    a = anchor(segs, [x[3] for x in ws], starts.get((book, ch, v), 0))
    if a is None: out["anchor_state"] = "unanchored"; return out, nlem, []
    tier, i, e = a; starts[(book, ch, v)] = e
    span = ws[i:e]
    out.update(anchor_state="anchored", anchor_tier=tier, anchor_part=span[0][2],
               anchor_t=json.dumps([x[0] for x in span]), anchor_w_from=span[0][1], anchor_w_to=span[-1][1])
    return out, nlem, span


def build(out_dir):
    out_dir = Path(out_dir); banks = out_dir / "banks"; sealed = out_dir / "sealed"
    banks.mkdir(parents=True, exist_ok=True); sealed.mkdir(parents=True, exist_ok=True)
    verse, order, wrec, counts = load_k1()
    rank = {b: i for i, b in enumerate(order)}
    info = collections.Counter()

    # paraphrase bank
    rows, trows = [], []
    unknown = collections.Counter(); unknown_ex = {}
    starts = {}
    src = sorted(comments(MD), key=lambda r: (rank[r[0]], r[1], r[2], r[3]))
    for book, ch, v, n, raw in src:
        lemma, body = parse(raw)
        cid = f"md:{book}:{ch}:{v}:{n}"
        a, _, span = anchor_fields(lemma, verse, book, ch, v, starts)
        if span and len({x[2] for x in span}) > 1: info["md_anchor_mixed_part"] += 1
        toks = tokens(body)
        for i, t in enumerate(toks, 1):
            trows.append({"comment": cid, "i": i, "text": t[0], "part": t[1], "abbrev": t[2], "written": t[3], "words": t[4]})
            if t[2] == "unknown":
                k = t[0].rstrip(PUNCT); unknown[k] += 1; unknown_ex.setdefault(k, cid)
        mk = markers(toks)
        rows.append({"comment": cid, "book": book, "chapter": ch, "verse": v, "n": n, "key": f"{book} {ch}:{v}",
                     "lemma": lemma if lemma is not None else "", "body": body, **a, "markers": json.dumps(mk),
                     "figure": "figure" in mk, "tokens": sum(1 for t in toks if t[1] == "body"),
                     "abbrev_unknown": sum(1 for t in toks if t[2] == "unknown"),
                     "in_pilot": portion_of(book, ch) != ""})
    trows.sort(key=lambda r: (r["comment"], r["i"]))
    S = pa.string(); I = pa.int64()
    pschema = pa.schema([("comment", S), ("book", S), ("chapter", I), ("verse", I), ("n", I), ("key", S), ("lemma", S),
                         ("body", S), ("anchor_state", S), ("anchor_tier", S), ("anchor_part", S), ("anchor_t", S),
                         ("anchor_w_from", I), ("anchor_w_to", I), ("markers", S), ("figure", pa.bool_()), ("tokens", I),
                         ("abbrev_unknown", I), ("in_pilot", pa.bool_())])
    tschema = pa.schema([("comment", S), ("i", I), ("text", S), ("part", S), ("abbrev", S), ("written", S), ("words", I)])
    pq.write_table(pa.Table.from_pylist(rows, schema=pschema), banks / "paraphrase.parquet")
    pq.write_table(pa.Table.from_pylist(trows, schema=tschema), banks / "paraphrase_tokens.parquet")
    with open(banks / "abbrev.tsv", "w", encoding="utf-8", newline="\n") as f:
        f.write("abbrev\twritten\tkind\n")
        for r in ladder_abbrev.rows(): f.write("\t".join(r) + "\n")
    with open(banks / "unknown_abbrev.tsv", "w", encoding="utf-8", newline="\n") as f:
        f.write("abbrev\tcount\texample\n")
        for k, c in sorted(unknown.items(), key=lambda kv: (-kv[1], kv[0])): f.write(f"{k}\t{c}\t{unknown_ex[k]}\n")

    # gloss bank
    forms = collections.defaultdict(list)
    for t, rec in wrec.items(): forms[cons(rec["text"])].append(t)
    grows = []; starts = {}
    src = sorted(comments(MZ), key=lambda r: (rank[r[0]], r[1], r[2], r[3]))
    for book, ch, v, n, raw in src:
        lemma, body = parse(raw)
        a, nlem, span = anchor_fields(lemma, verse, book, ch, v, starts)
        if span and len({x[2] for x in span}) > 1: info["mz_anchor_mixed_part"] += 1
        kind, core, why = zc(body) if lemma is not None else zc(body)
        if why: info["zc_none_" + why] += 1
        core_text = write_core(core) if kind == "gloss" else ""
        r = {"gloss": f"mz:{book}:{ch}:{v}:{n}", "book": book, "chapter": ch, "verse": v, "n": n, "key": f"{book} {ch}:{v}",
             "lemma": lemma if lemma is not None else "", "body": body, **a, "kind": kind, "core": core_text,
             "core_words": len(core) if kind == "gloss" else 0, "fit": "", "fit_form": "", "fit_lexeme": "",
             "src_t": None, "src_n": None, "src_lexeme": "", "src_count": None, "rare": False,
             "in_pilot": portion_of(book, ch) != ""}
        if a["anchor_state"] == "anchored" and nlem == 1 and len(span) == 1:
            G = wrec[span[0][0]]
            if G["stem"] is not None:
                r["src_t"], r["src_n"], r["src_lexeme"] = span[0][0], G["stem"][0], G["stem"][1]
                r["src_count"] = counts.get(G["stem"][1])
                r["rare"] = r["src_count"] is not None and r["src_count"] < 20
        elif a["anchor_state"] == "anchored" and nlem == 1:
            info["fit_one_word_lemma_two_words"] += 1
        if kind == "gloss" and a["anchor_state"] == "anchored":
            if 2 <= nlem <= 3 or 2 <= len(core) <= 3: r["fit"] = "phrase"
            elif nlem == 1 and len(core) == 1 and r["src_t"] is not None:
                cand = forms.get(cons(core_text), [])
                if not cand: r["fit"] = "unattested"
                else:
                    ok = [t for t in cand if agrees(wrec[t], G)]
                    if not ok: r["fit"] = "form_other"
                    else:
                        r["fit"] = "fits"
                        f = best(collections.Counter(point(wrec[t]["text"]) for t in ok))
                        r["fit_form"] = f
                        r["fit_lexeme"] = best(collections.Counter(wrec[t]["stem"][1] for t in ok if point(wrec[t]["text"]) == f))
            elif nlem == 1 and len(core) == 1: info["fit_blank_no_single_src"] += 1
            else: info["fit_blank_lemma_over_3"] += 1
        grows.append(r)
    gschema = pa.schema([("gloss", S), ("book", S), ("chapter", I), ("verse", I), ("n", I), ("key", S), ("lemma", S),
                         ("body", S), ("anchor_state", S), ("anchor_tier", S), ("anchor_part", S), ("anchor_t", S),
                         ("anchor_w_from", I), ("anchor_w_to", I), ("kind", S), ("core", S), ("core_words", I), ("fit", S),
                         ("fit_form", S), ("fit_lexeme", S), ("src_t", I), ("src_n", I), ("src_lexeme", S),
                         ("src_count", I), ("rare", pa.bool_()), ("in_pilot", pa.bool_())])
    pq.write_table(pa.Table.from_pylist(grows, schema=gschema), banks / "gloss.parquet")

    # the sealed sample of the chooser (5.5)
    rng = random.Random(SEED); srows = []
    for p in PORTIONS:
        ids = sorted(r["comment"] for r in rows if r["anchor_state"] == "anchored" and portion_of(r["book"], r["chapter"]) == p)
        for c in rng.sample(ids, 20): srows.append((p, c))
    with open(sealed / "chooser_sample.tsv", "w", encoding="utf-8", newline="\n") as f:
        f.write("portion\tcomment\n")
        for p, c in srows: f.write(f"{p}\t{c}\n")
    return dict(info)
