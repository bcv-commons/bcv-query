"""The Septuagint in the bridge corpus (plan step 3, sections 4.3 and 4.6): its words, sections and parallel verses; the `lxx` edges from
the Hebrew word parts to the Septuagint words; the clause lines carried over from the Hebrew clause layout.

Texts: the canonical books of GLAUx's Septuagint (`lxx-glaux-2026-10-10`, `canonical` = 1); Daniel twice, the Old Greek (GLAUx 0527-056,
which MACULA's word links point to) and Theodotion (0527-057, from `lxx-glaux-dan-theodotion-2026-11-14`), both without the Greek additions
of chapter 3 (3:24-90 in GLAUx's numbering). Sections LXX.<BOOK>, and LXX.DAN-TH for Theodotion; `book` stays the plain name.

Words: text (GLAUx surface), lang grc, lemma and strong keyed as the Greek NT keys them (plan 4.7): where GLAUx's number is a number of the
Greek NT, the NT's lemma and number; otherwise GLAUx's lemma, and its number if it has one. pos in the Greek NT's classes (from GLAUx's
part of speech). GLAUx's own values under glx_ (lemma, strong, pos, morph, id).

`lxx` edges: MACULA Hebrew gives each Hebrew word part the Greek form it was aligned to (lexeme-spine-macula-2026-10-27, `greek` and
`greekstrong`), not its position. The Septuagint verse comes from lxx_verses (the two numbering schemes through the English one). In the
verse the form is placed, and the edge's value says how:
  sure        the form occurs once in the verse
  order       several occurrences and as many Hebrew parts claim the form: in order
  neighbours  several occurrences and fewer or more claims: the occurrence nearest to where the neighbouring sure links point
  number      the form is not in the verse, but a word with the same Greek number is (MACULA's number mapped to the NT's with
              resources/lxx_bridge_tiers/greek_numbers.tsv; a compound number such as 1722|1698 counts each part): the nearest such word
Not placed: neither form nor number in the verse, or no verse.

Carried lines: the Septuagint words a Hebrew layout line's parts are linked to are a Greek line when they form one stretch in which no
word is linked from another Hebrew line; the stretch takes the unlinked words inside it. A line that fails gets no unit (counted). Each
carried line has a `carried` edge to its Hebrew line.
"""
from __future__ import annotations

import collections
import re
import sqlite3
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
POS = {"N": "noun", "V": "verb", "A": "adj", "D": "adv", "C": "conj", "P": "prep", "RA": "det", "RP": "pron", "RD": "pron", "RR": "pron",
       "RI": "pron", "RX": "pron", "M": "num", "I": "intj", "X": "ptcl"}
ADDITIONS = ("DAN", 3, 24, 90)                                           # Daniel 3:24-90 in GLAUx's numbering: the Greek additions


def plain(s: str | None) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch)).replace("ς", "σ").strip(".,;·:!?'’\"")


def numbers(s) -> list[str]:
    """the numbers of a Strong's value, without leading zeros: '1722|1698' -> ['1722', '1698'], 'G0040' -> ['40']"""
    return [m.lstrip("0") or "0" for m in re.findall(r"\d+", str(s or ""))]


def nt_numbers() -> dict[str, str]:
    """MACULA Hebrew's Greek number -> the Greek NT's number, where they differ (greek_numbers.tsv)"""
    out = {}
    for line in (ROOT / "resources" / "lxx_bridge_tiers" / "greek_numbers.tsv").read_text().splitlines()[1:]:
        f = line.split("\t")
        if f[1]:
            out[numbers(f[0])[0]] = numbers(f[1])[0]
    return out


def nearest(hpos: int, cands: list[int], anchors: list[tuple[int, int]], n_greek: int, n_hebrew: int) -> int:
    """the candidate nearest to where the sure links around Hebrew position hpos point"""
    before = [a for a in anchors if a[0] < hpos]
    after = [a for a in anchors if a[0] > hpos]
    if before and after:
        (h0, g0), (h1, g1) = before[-1], after[0]
        want = g0 + (g1 - g0) * (hpos - h0) / (h1 - h0)
    elif before:
        want = before[-1][1] + (hpos - before[-1][0])
    elif after:
        want = after[0][1] - (after[0][0] - hpos)
    else:
        want = hpos * n_greek / max(n_hebrew, 1)
    return min(cands, key=lambda j: (abs(j - want), j))


def place(hebrew: list[tuple], greek: list[tuple]) -> dict:
    """hebrew: the verse's parts in order, (key, plain Greek form or '', [Greek numbers]); greek: the Septuagint verse's words in order,
    (plain form, [numbers]). -> key -> (index into greek, how)"""
    occ, num = collections.defaultdict(list), collections.defaultdict(list)
    for j, (form, ns) in enumerate(greek):
        occ[form].append(j)
        for n in ns:
            num[n].append(j)
    claim = collections.defaultdict(list)
    for pos, (key, form, _) in enumerate(hebrew):
        if form:
            claim[form].append(pos)
    anchors = sorted((p, occ[f][0]) for f, ps in claim.items() if len(occ.get(f, ())) == 1 for p in ps)
    out = {}
    for f, ps in claim.items():
        js = occ.get(f, [])
        for i, p in enumerate(ps):
            key = hebrew[p][0]
            if len(js) == 1:
                out[key] = (js[0], "sure")
            elif len(js) > 1 and len(ps) == len(js):
                out[key] = (js[i], "order")
            elif js:
                out[key] = (nearest(p, js, anchors, len(greek), len(hebrew)), "neighbours")
            else:
                cands = sorted({j for n in hebrew[p][2] for j in num.get(n, ())})
                if cands:
                    out[key] = (nearest(p, cands, anchors, len(greek), len(hebrew)), "number")
    return out


def carry(lines: list[set[int]], links: dict[int, int]) -> list[tuple[int, int, int] | None]:
    """lines: the Hebrew lines' word numbers; links: Hebrew word -> Septuagint word (both numbers in text order).
    -> per line (first, last Septuagint word, line index) of its clean stretch, or None"""
    owner = collections.defaultdict(set)
    for i, sl in enumerate(lines):
        for s in sl:
            if s in links:
                owner[links[s]].add(i)
    out = []
    for i, sl in enumerate(lines):
        ts = {links[s] for s in sl if s in links}
        if not ts:
            out.append(None)
            continue
        lo, hi = min(ts), max(ts)
        clean = all(owner.get(g, {i}) <= {i} for g in range(lo, hi + 1))
        out.append((lo, hi, i) if clean else None)
    return out


def rows(db: Path, theodotion: bool):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    sql = "select * from lxx_words where book = 'DAN'" if theodotion else "select * from lxx_words where canonical = 1"
    b, c, lo, hi = ADDITIONS
    return [r for r in con.execute(sql + " order by chapter, verse, idx" if theodotion else sql)
            if not (r["book"] == b and r["chapter"] == c and lo <= r["verse"] <= hi)]


def add_septuagint(c, stores: dict) -> None:
    """c: the Corpus of build_bridge_corpus (Tanakh and its layout lines already in)"""
    from macula import lxx_verses as lv
    st = collections.Counter()
    to_nt = nt_numbers()
    spine = sqlite3.connect(f"file:{stores['links']}?mode=ro", uri=True)
    nt = collections.defaultdict(collections.Counter)                   # Greek NT number -> lemma
    for k, s in c.slot.items():
        if c.F["lang"].get(s) == "grc" and k[:2] >= "40" and len(k) == 11 and c.F["strong"].get(s):
            nt[numbers(c.F["strong"][s])[0]][c.F["lemma"][s]] += 1
    nt_lemma = {n: cnt.most_common(1)[0][0] for n, cnt in nt.items()}
    order = list(dict.fromkeys(r[0] for r in spine.execute("select book from spine_words where key < '40' order by key")))
    og = rows(stores["septuagint"], False)
    th = rows(stores["theodotion"], True)
    by_book = collections.defaultdict(list)
    for r in og:
        by_book[(r["book"], "og")].append(r)
    for r in th:
        by_book[("DAN", "th")].append(r)
    seq = [(b, v) for b in order for v in ("og", "th") if (b, v) in by_book]
    verses = collections.OrderedDict()
    greek_of = {}                                                        # Septuagint word number -> (plain form, [NT numbers])
    for b, ver in seq:
        for r in sorted(by_book[(b, ver)], key=lambda r: (r["chapter"], r["verse"], r["idx"])):
            key = f"lxx{'-th' if ver == 'th' else ''} {b} {r['chapter']}:{r['verse']} {r['idx']}"
            s = c.slot[key] = len(c.slot) + 1
            n = numbers(r["strong"])
            n = [to_nt.get(x, x) for x in n]
            c.F["lkey"][s], c.F["text"][s], c.F["lang"][s], c.F["trailer"][s] = key, r["surface"], "grc", " "
            if n and n[0] in nt_lemma:
                c.F["lemma"][s], c.F["strong"][s] = nt_lemma[n[0]], n[0]
                st["words keyed by the NT's lemma"] += 1
            else:
                c.F["lemma"][s] = r["lemma"]
                if n:
                    c.F["strong"][s] = n[0]
                st["words keyed by GLAUx's lemma"] += 1
            for col, feat in (("lemma", "glx_lemma"), ("strong", "glx_strong"), ("pos", "glx_pos"), ("morph", "glx_morph"), ("glaux_id", "glx_id")):
                if r[col] not in (None, ""):
                    c.F[feat][s] = r[col] if col != "strong" else str(r[col])
            if POS.get(r["pos"]):
                c.F["pos"][s] = POS[r["pos"]]
            greek_of[s] = (plain(r["surface"]), n)
            verses.setdefault((ver, b, r["chapter"], r["verse"]), []).append(s)
    for k in ("lkey", "glx_lemma", "glx_strong", "glx_pos", "glx_morph", "glx_id"):
        c.origin[k] = "septuagint"
    chapters, books = collections.OrderedDict(), collections.OrderedDict()
    english = collections.defaultdict(list)                             # English-scheme verse -> Tanakh verse handles
    for k, h in c.at["verse"].items():
        if k[0] == "tanakh":
            for e in lv.hebrew_keys(*k[1:]):
                english[e].append(h)
    gverse = collections.defaultdict(list)                              # English-scheme key -> Old Greek words in order (for placing)
    for (ver, b, ch, v), sl in verses.items():
        h = c.node("verse", sl, ("septuagint" if ver == "og" else "theodotion", b, ch, v))
        c.F["book"][h], c.F["chapter"][h], c.F["verse"][h] = b, ch, v
        chapters.setdefault((ver, b, ch), []).extend(sl)
        if ver == "th":
            hv = lv.dan_hebrew_verse(ch, v)
            tv = [c.at["verse"].get(("tanakh", "DAN", *hv))] if hv else []
        else:
            tv = list(dict.fromkeys(t for e in lv.greek_keys(b, ch, v) for t in english.get(e, ())))
            for e in lv.greek_keys(b, ch, v):
                gverse[e].extend(sl)
        placed = [c.edge("parallel", h, t, None, "septuagint") for t in tv if t]
        st["verses"] += 1
        st["verses with a parallel Tanakh verse"] += any(placed)
    for (ver, b, ch), sl in chapters.items():
        h = c.node("chapter", sl, ("septuagint" if ver == "og" else "theodotion", b, ch))
        c.F["book"][h], c.F["chapter"][h] = b, ch
        books.setdefault((ver, b), []).extend(sl)
    for (ver, b), sl in books.items():
        h = c.node("book", sl, ("septuagint" if ver == "og" else "theodotion", b))
        c.F["book"][h], c.F["sec"][h] = b, f"LXX.{b}" if ver == "og" else "LXX.DAN-TH"
        c.F["glx_document"][h] = "0527-057" if ver == "th" else "0527-056" if b == "DAN" else ""
        if not c.F["glx_document"][h]:
            del c.F["glx_document"][h]
    c.origin["glx_document"] = "septuagint"
    c.F["name"][c.node("text", list(greek_of), "septuagint")] = "septuagint"
    st["words"] = len(greek_of)
    st["of them Daniel by Theodotion"] = sum(len(sl) for (ver, *_), sl in verses.items() if ver == "th")
    # lxx edges
    links: dict[int, int] = {}
    hverse = collections.defaultdict(list)
    for key, b, ch, v, form, gs in spine.execute("select key, book, chapter, verse, greek, greekstrong from spine_words where key < '40' order by key"):
        if key in c.slot:
            hverse[(b, ch, v)].append((key, plain(form), [to_nt.get(x, x) for x in numbers(gs)]))
    how = collections.Counter()
    for (b, ch, v), hw in hverse.items():
        n_form = sum(1 for w in hw if w[1])
        if not n_form:
            continue
        gw = [s for e in lv.hebrew_keys(b, ch, v) for s in gverse.get(e, ())]
        gw = list(dict.fromkeys(gw))
        if not gw:
            how["no verse"] += n_form
            continue
        got = place(hw, [greek_of[s] for s in gw])
        for key, (j, kind) in got.items():
            c.edge("lxx", c.slot[key], gw[j], kind, "links")
            links[c.slot[key]] = gw[j]
            how[kind] += 1
        how["not placed"] += n_form - len(got)
    st["hebrew parts with a Greek form"] = sum(how.values())
    st.update({f"lxx: {k}": v for k, v in how.items()})
    # carried lines: the Tanakh's layout lines
    n_hbo = c.report["words"]["hbo"]
    heb = [(i, sl) for i, sl in enumerate(c.nodes["line"]) if min(sl) <= n_hbo]
    res = carry([sl for _, sl in heb], links)
    inside = set()
    for r in res:
        if r is None:
            continue
        lo, hi, i = r
        h = c.node("line", range(lo, hi + 1))
        c.edge("carried", h, ("line", heb[i][0]), None, "links")
        inside.update(range(lo, hi + 1))
    st["hebrew lines"] = len(heb)
    st["hebrew lines with a placed Greek word"] = sum(1 for _, sl in heb if any(s in links for s in sl))
    st["carried lines"] = sum(r is not None for r in res)
    st["Old Greek words inside a carried line"] = len(inside)
    c.report["layers"]["septuagint"] = dict(st)
