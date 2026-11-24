"""Stage 08 of the source examples: links to another text (SPEC 1.0, section 4.9, rule D13, `rendered_by` of 4.8).

Writes, per language folder:
  other/<text>/words.parquet   the other text's words: s, id, book, chapter, verse, w, text, lemma, class
  links.parquet                t, n, other, s, how, agree
  link_account.parquet         t, n, other, state, reason (one row per piece and other text; D13)
  facts.parquet                anew: the rows of earlier stages (kin relations) kept, `rendered_by` rows added

hbo and arc against the Septuagint (`lxx`): GLAUx's canonical books with Daniel as the Old Greek, as the bridge corpus
hebrew-greek-cf v0.2 has them (the Greek additions of Daniel 3:24-90 are not in it). The links are the bridge's
`bridges/lxx.parquet` (345,461 rows, `how` = sure, order, neighbours, number), then the rules of this stage for the
pieces MACULA names a Greek word for (lowfat `greek`, not the fillers ’’ and ^^^) that the bridge did not place.
Each rule only takes a Septuagint word no other piece is linked to ("free"), and runs over the still unplaced pieces
in text order, in this order:
  lemma        in the verse's own Septuagint verses (those the bridge's links of the Hebrew verse land in): the free
               words whose GLAUx lemma is the one lemma GLAUx gives the named form anywhere in this Septuagint;
               the nearest to where the verse's `sure` links point (the bridge's own `nearest`)
  form_near    in the same verses: the one free word whose plain form is one edit (letter changed, added or
               dropped) from the named form, and whose Greek numbers do not conflict with the named ones (one
               side has none, or they share one); named forms of 5 letters or more
  verse_form   in the neighbouring Septuagint verses (D: below): the one free word with the named plain form
  verse_lemma  there: the one free word with the named form's one lemma
  verse_number there: the one free word with one of the named Greek numbers (MACULA's number mapped to the NT's
               with resources/lxx_bridge_tiers/greek_numbers.tsv, as the bridge maps it)
The neighbouring verses of a Hebrew verse: the verse before and the verse after each of its own Septuagint verses,
in the same Septuagint book, not its own. A Hebrew verse with no bridge link at all has no own verses; its
neighbouring verses are the run from the last own verse of the Hebrew verse before it to the first own verse of the
Hebrew verse after it (same book on both sides, at most three verses), else none.

grc against the two Hebrew New Testaments (`heb_scg`, `heb_mod`): lexeme-aligner's compact alignments
(data/compact-alignments-11583082). Their companion files that the download lacks (the source keys `_index/<BOOK>_keys.json`,
the verse maps, the method sidecars `.meta.json`) are read from lexeme-aligner's publish folder, after checking that its
alignment and index files are byte-identical to the pinned ones. The texts: bible.helloao.org's chapters
(data/helloao/<edition>), verse text by bibles' verse-text rule, tokens by its tokenizer (vendor_bibles), the same code
the aligner's positions refer to; the book's text fingerprint must name a file of the pinned download. A Salkinson
verse that begins with its own number in letters has that token left out of the words (the aligner counts it).
`how` is the aligner's method of the entry. An entry whose only method is the gloss method (method g or G, conf 1)
on a Greek proper noun is not taken: the gloss method compares a name's English gloss with the romanised word.

`agree` = 1 on every row: no second alignment of these texts in this repository is free of a model (section
"For the specification" of the stage report). D13 as SPEC section 6 states it; the share for `never_a_word` is
counted over the whole Tanakh (hbo and arc together) and over the whole New Testament.
"""
import collections as C
import glob
import hashlib
import json
import multiprocessing as mp
import os
import pickle
import sqlite3
import sys
import unicodedata
import xml.etree.ElementTree as ET

import pyarrow as pa
import pyarrow.parquet as pq

import examples_common as X
import bridge_corpus_lxx as BL
from examples_people import FACT_SCHEMA

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
XID = "{http://www.w3.org/XML/1998/namespace}id"
HEB_LOWFAT = os.path.join(HERE, ".lowfat-src/WLC/lowfat")
BRIDGE = os.path.join(ROOT, "internal-docs/hebrew-greek-cf-release/v0.2/bridges/lxx.parquet")
BRIDGE_SHA = "e5f540efb684ad918dbd6c3df353abc3acdc2bc96c346b9130e462b1185621dc"
GLAUX = os.path.join(ROOT, "shoresh/lxx/data/lxx-glaux.db")
GLAUX_SHA = "42f00ecfc31e502d9b41ba6d687830c1773b15bfe4dcd90eff53f41f086c5b31"
NUMBERS = os.path.join(ROOT, "resources/lxx_bridge_tiers/greek_numbers.tsv")
COMPACT = os.path.join(HERE, "data/compact-alignments-11583082")
PUBLISH = os.path.expanduser("~/dev/bcv-commons/lexeme-aligner/publish/compact-alignments")
HELLOAO = os.path.join(HERE, "data/helloao")
VENDOR = os.path.join(HERE, "vendor_bibles")
FILLERS = {"’’", "^^^"}
ADDITIONS = ("DAN", 3, 24, 90)
EDITIONS = ("heb_scg", "heb_mod")
NT_CONTENT = {"noun", "verb", "adj"}          # the classes the compact alignment links (CHANGES B1)
HOW_NT = {"E": "eflomal_09", "e": "eflomal_06", "G": "gloss_strong", "g": "gloss_weak", "f": "gapfill",
          "x": "spanext", "r": "residual"}
NAW_SHARE = 0.05
GREEK_SIGNS = {0x02B9}                          # the Greek numeral sign (U+0374 becomes U+02B9 under NFC)


def in_script(value, script):
    """True when every letter of value is a letter of the script (GREEK, HEBREW); marks, signs, punctuation pass."""
    for ch in value or "":
        if unicodedata.category(ch)[0] == "L" and not unicodedata.name(ch, "").startswith(script) \
                and ord(ch) not in GREEK_SIGNS:
            return False
    return True


def scripted(value, script, what, ex):
    """value, or None where it holds a letter of another script (SPEC 10, no English); listed in ex"""
    if value is None or in_script(value, script):
        return value
    ex.setdefault(what, []).append(value)
    return None

OTHER_SCHEMA = pa.schema([("s", pa.int64()), ("id", pa.string()), ("book", pa.string()), ("chapter", pa.int64()),
                          ("verse", pa.int64()), ("w", pa.int64()), ("text", pa.string()), ("lemma", pa.string()),
                          ("class", pa.string())])
LINK_SCHEMA = pa.schema([("t", pa.int64()), ("n", pa.int64()), ("other", pa.string()), ("s", pa.int64()),
                         ("how", pa.string()), ("agree", pa.int64())])
ACCOUNT_SCHEMA = pa.schema([("t", pa.int64()), ("n", pa.int64()), ("other", pa.string()), ("state", pa.string()),
                            ("reason", pa.string())])
STATES = ("linked", "outside_alignment", "never_a_word", "unplaced", "no_counterpart")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def cache_dir(outdir):
    d = os.path.join(outdir, "cache", "s08")
    os.makedirs(d, exist_ok=True)
    return d


# ---- MACULA Hebrew's named Septuagint word per piece ------------------------------------------------------------

def _greek_file(path):
    out = []
    for _, el in ET.iterparse(path):
        if el.tag == "w":
            out.append((el.get(XID), el.get("greek"), el.get("greekstrong")))
            el.clear()
    return out


def lowfat_greek(outdir):
    """{xml:id: (greek, greekstrong)} of every lowfat word. SPEC 1.8 D13a (M4, fault F0016): with V18 set, every form is
    read through text_faults.macula_greek() (after the cache, so that no pickle brings the swapped forms back)."""
    out = _lowfat_greek_raw(outdir)
    if getattr(X, "V18", False):
        import text_faults
        out = {k: (text_faults.macula_greek(g) if g else g, s) for k, (g, s) in out.items()}
    return out


def _lowfat_greek_raw(outdir):
    files = sorted(glob.glob(os.path.join(HEB_LOWFAT, "*-lowfat.xml")))
    h = hashlib.sha256()
    for f in files:
        h.update(os.path.basename(f).encode())
        h.update(sha256(f).encode())
    path = os.path.join(cache_dir(outdir), f"lowfat-greek-{h.hexdigest()[:16]}.pkl")
    if os.path.exists(path):
        with open(path, "rb") as fh:
            return pickle.load(fh)
    with mp.get_context("fork").Pool(7) as pool:
        res = pool.map(_greek_file, files, chunksize=8)
    out = {i: (g, s) for r in res for i, g, s in r}
    tmp = path + f".tmp{os.getpid()}"
    with open(tmp, "wb") as fh:
        pickle.dump(out, fh, protocol=5)
    os.replace(tmp, path)
    return out


# ---- our tables -------------------------------------------------------------------------------------------------

def read_lang(outdir, lang):
    d = os.path.join(outdir, lang)
    W = pq.read_table(os.path.join(d, "words.parquet"), columns=["t", "id", "book", "chapter", "verse"]).to_pylist()
    P = pq.read_table(os.path.join(d, "pieces.parquet"), columns=["t", "n", "pid", "class", "lexeme", "marks"]).to_pylist()
    return W, P


def lev1(a, b):
    """True when a and b are exactly one edit apart (one letter changed, added or dropped)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


# ---- the Septuagint -----------------------------------------------------------------------------------------------

def septuagint(book_order):
    """GLAUx's canonical books, Daniel's Greek additions left out, in the bridge's order."""
    if sha256(GLAUX) != GLAUX_SHA:
        raise SystemExit(f"{GLAUX}: sha256 is not the pinned one")
    con = sqlite3.connect(f"file:{GLAUX}?mode=ro", uri=True)
    rows = con.execute("select book, chapter, verse, idx, surface, lemma, pos, strong, glaux_id from lxx_words "
                       "where canonical = 1").fetchall()
    b0, c0, lo, hi = ADDITIONS
    rank = {b: i for i, b in enumerate(book_order)}
    missing = sorted({r[0] for r in rows} - set(rank))
    if missing:
        raise SystemExit(f"Septuagint books not in the Tanakh's order: {missing}")
    rows = [r for r in rows if not (r[0] == b0 and r[1] == c0 and lo <= r[2] <= hi)]
    rows.sort(key=lambda r: (rank[r[0]], r[1], r[2], r[3]))
    return rows


RULES = ("lemma", "form_near", "verse_form", "verse_lemma", "verse_number")


def lxx_place(outdir, ex, st, skip=frozenset(), decisive=None):
    """The Septuagint words and the placement of stage 08 (bridge, then RULES). -> dict.
    skip: bridge `how` values and rules left out (stage 19's figure of what rests on them; the default is stage 08).
    decisive: a set that gets the pid of every `form_near` link whose number guard removed a candidate (stage 19)."""
    langs = ("hbo", "arc")
    tab = {lang: read_lang(outdir, lang) for lang in langs}
    book_order = list(dict.fromkeys(w["book"] for lang in langs for w in sorted(tab[lang][0], key=lambda w: w["t"])))
    rows = septuagint(book_order)
    to_nt = BL.nt_numbers()
    # the other text's words
    key2s, words = {}, []
    plain, lemma, nums, vid_of, vbook = [None], [None], [None], [None], []
    verse_words = []                                   # verse index -> [s]
    vindex = {}
    for s, (b, c, v, idx, surface, lem, pos, strong, gid) in enumerate(rows, start=1):
        key2s[f"lxx {b} {c}:{v} {idx}"] = s
        words.append((s, str(gid), b, c, v, idx, scripted(surface, "GREEK", "lxx text emptied: a letter of another script", ex),
                      scripted(lem or None, "GREEK", "lxx lemma emptied: a letter of another script", ex),
                      X.c0(pos) if pos else None))
        plain.append(BL.plain(surface))
        lemma.append(lem)
        nums.append([to_nt.get(x, x) for x in BL.numbers(strong)])
        k = (b, c, v)
        if k not in vindex:
            vindex[k] = len(verse_words)
            verse_words.append([])
            vbook.append(b)
        verse_words[vindex[k]].append(s)
        vid_of.append(vindex[k])
    if len({w[1] for w in words}) != len(words):
        raise SystemExit("GLAUx ids are not unique")
    st["lxx words"] = len(words)
    st["lxx verses"] = len(verse_words)
    st["lxx words without a lemma"] = sum(1 for w in words if w[7] is None)
    lem_of_form = C.defaultdict(set)
    for s in range(1, len(plain)):
        lem_of_form[plain[s]].add(lemma[s])
    # the pieces of both Tanakh tables, in text order
    named = lowfat_greek(outdir)
    pieces = []                                        # (t, n, pid, class, lexeme, lang, (book, ch, v))
    for lang in langs:
        W, P = tab[lang]
        wv = {w["t"]: (w["book"], w["chapter"], w["verse"]) for w in W}
        for p in P:
            pieces.append((p["t"], p["n"], p["pid"], p["class"], p["lexeme"], lang, wv[p["t"]]))
    pieces.sort()
    by_pid = {p[2]: p for p in pieces}
    if len(by_pid) != len(pieces):
        raise SystemExit("piece ids are not unique over hbo and arc")
    # the bridge
    if sha256(BRIDGE) != BRIDGE_SHA:
        raise SystemExit(f"{BRIDGE}: sha256 is not the pinned one")
    bridge = pq.read_table(BRIDGE).to_pylist()
    links = C.defaultdict(list)                        # pid -> [(s, how)]
    taken = set()
    for r in bridge:
        pid = "o" + r["hebrew_mid"]
        s = key2s.get(r["lxx_key"])
        if pid not in by_pid or s is None:
            raise SystemExit(f"bridge row does not resolve: {r}")
        if r["how"] in skip:
            continue
        links[pid].append((s, r["how"]))
        taken.add(s)
    st["bridge rows"] = len(bridge)
    st.update({f"bridge how {k}": v for k, v in sorted(C.Counter(r["how"] for r in bridge).items())})
    # Hebrew verses, their pieces, their own Septuagint verses
    hverse = C.OrderedDict()
    for p in pieces:
        hverse.setdefault(p[6], []).append(p)
    own = {}
    for hv, ps in hverse.items():
        own[hv] = sorted({vid_of[s] for p in ps for s, _ in links.get(p[2], ())})
    hbook_verses = C.defaultdict(list)
    for hv in hverse:
        hbook_verses[hv[0]].append(hv)
    neigh = {}
    for b, hvs in hbook_verses.items():
        hvs.sort(key=lambda k: (k[1], k[2]))
        for i, hv in enumerate(hvs):
            if own[hv]:
                ns = set()
                for g in own[hv]:
                    for d in (-1, 1):
                        if 0 <= g + d < len(verse_words) and vbook[g + d] == vbook[g]:
                            ns.add(g + d)
                neigh[hv] = sorted(ns - set(own[hv]))
                continue
            prev = next((own[h] for h in reversed(hvs[:i]) if own[h]), None)
            nxt = next((own[h] for h in hvs[i + 1:] if own[h]), None)
            if prev and nxt and vbook[prev[-1]] == vbook[nxt[0]] and 0 <= nxt[0] - prev[-1] <= 2:
                neigh[hv] = list(range(prev[-1], nxt[0] + 1))
            else:
                neigh[hv] = []
                st["unlinked Hebrew verses with no neighbouring verses"] += 1
    st["Hebrew verses"] = len(hverse)
    st["Hebrew verses with no bridge link"] = sum(1 for v in own.values() if not v)

    def want(p):
        g = named.get(p[2], (None, None))
        return g if g[0] and g[0] not in FILLERS else None

    todo = [p for p in pieces if p[2] not in links and want(p)]
    st["named, not placed by the bridge"] = len(todo)
    placed_by = C.Counter()
    for rule in RULES:
        if rule in skip:
            continue
        left = []
        for p in todo:
            form, gs = want(p)
            f = BL.plain(form)
            ls = lem_of_form.get(f, set())
            one_lemma = next(iter(ls)) if len(ls) == 1 else None
            hv = p[6]
            got = None
            if rule in ("lemma", "form_near"):
                gw = [s for g in own[hv] for s in verse_words[g]]
                if rule == "lemma" and one_lemma is not None:
                    cands = [i for i, s in enumerate(gw) if s not in taken and lemma[s] == one_lemma]
                    if cands:
                        vp = hverse[hv]
                        hpos = vp.index(p)
                        pos_of = {s: i for i, s in enumerate(gw)}
                        anchors = sorted((j, pos_of[s]) for j, q in enumerate(vp) for s, how in links.get(q[2], ())
                                         if how == "sure" and s in pos_of)
                        got = gw[BL.nearest(hpos, cands, anchors, len(gw), len(vp))]
                elif rule == "form_near" and len(f) >= 5:
                    ns = {to_nt.get(x, x) for x in BL.numbers(gs)}
                    cands = [s for s in gw if s not in taken and lev1(plain[s], f)
                             and (not ns or not nums[s] or ns.intersection(nums[s]))]
                    if len(cands) == 1:
                        got = cands[0]
                        if decisive is not None and sum(1 for s in gw if s not in taken and lev1(plain[s], f)) > 1:
                            decisive.add(p[2])
            else:
                nw = [s for g in neigh[hv] for s in verse_words[g] if s not in taken]
                if rule == "verse_form":
                    cands = [s for s in nw if plain[s] == f]
                elif rule == "verse_lemma":
                    cands = [s for s in nw if one_lemma is not None and lemma[s] == one_lemma]
                else:
                    ns = {to_nt.get(x, x) for x in BL.numbers(gs)}
                    cands = [s for s in nw if ns.intersection(nums[s])]
                if len(cands) == 1:
                    got = cands[0]
            if got is None:
                left.append(p)
            else:
                links[p[2]].append((got, rule))
                taken.add(got)
                placed_by[rule] += 1
        todo = left
    st.update({f"placed by rule {k}": placed_by[k] for k in ("lemma", "form_near", "verse_form", "verse_lemma",
                                                            "verse_number")})
    st["named, still not placed"] = len(todo)
    return {"words": words, "pieces": pieces, "links": links, "want": want, "langs": langs}


def build_lxx(outdir, counts, ex):
    st = C.Counter()
    R = lxx_place(outdir, ex, st)
    words, pieces, links, want, langs = R["words"], R["pieces"], R["links"], R["want"], R["langs"]
    # D13 over the whole Tanakh
    cls_all, cls_linked = C.Counter(), C.Counter()
    for p in pieces:
        cls_all[p[3]] += 1
        cls_linked[p[3]] += p[2] in links
    share = {c: cls_linked[c] / cls_all[c] for c in cls_all}
    naw = {c for c, v in share.items() if v < NAW_SHARE}
    counts["lxx class shares (hbo+arc)"] = {c: [cls_linked[c], cls_all[c], round(share[c], 4)] for c in sorted(cls_all)}
    counts["lxx never_a_word classes"] = sorted(naw)
    # write per language
    ws_cols = {f.name: [w[i] for w in words] for i, f in enumerate(OTHER_SCHEMA)}
    for lang in langs:
        d = os.path.join(outdir, lang)
        X.write_parquet(os.path.join(d, "other", "lxx", "words.parquet"), ws_cols, OTHER_SCHEMA)
        lrows, arows = [], []
        for p in pieces:
            if p[5] != lang:
                continue
            t, n, pid = p[0], p[1], p[2]
            for s, how in sorted(links.get(pid, ())):
                lrows.append((t, n, "lxx", s, how, 1))
            g = want(p)
            if pid in links:
                state, reason = "linked", ""
            elif p[3] in naw:
                state, reason = "never_a_word", p[3]
            elif g:
                state, reason = "unplaced", g[0]
            else:
                state, reason = "no_counterpart", ""
            arows.append((t, n, "lxx", state, reason))
        write_links(d, lang, lrows, arows, counts)
    counts["lxx"] = dict(st)


def write_links(d, lang, lrows, arows, counts):
    """Write links.parquet and link_account.parquet for one language (the rows of all its other texts)."""
    path_l = os.path.join(d, "links.parquet")
    path_a = os.path.join(d, "link_account.parquet")
    lrows = sorted(lrows, key=lambda r: (r[2], r[0], r[1], r[3]))
    arows = sorted(arows, key=lambda r: (r[2], r[0], r[1]))
    X.write_parquet(path_l, {f.name: [r[i] for r in lrows] for i, f in enumerate(LINK_SCHEMA)}, LINK_SCHEMA)
    X.write_parquet(path_a, {f.name: [r[i] for r in arows] for i, f in enumerate(ACCOUNT_SCHEMA)}, ACCOUNT_SCHEMA)
    counts[f"{lang} links rows"] = len(lrows)
    counts[f"{lang} links by other and how"] = {f"{o} {h}": v for (o, h), v in
                                               sorted(C.Counter((r[2], r[4]) for r in lrows).items())}
    counts[f"{lang} account by other and state"] = {f"{o} {s}": v for (o, s), v in
                                                   sorted(C.Counter((r[2], r[3]) for r in arows).items())}


# ---- the Hebrew New Testaments ------------------------------------------------------------------------------------

def heb_numeral(n):
    units, tens = "אבגדהוזחט", "יכלמנסעפצ"
    out = "ק" * (n // 100)
    n %= 100
    if n in (15, 16):
        return out + ("טו" if n == 15 else "טז")
    return out + (tens[n // 10 - 1] if n >= 10 else "") + (units[n % 10 - 1] if n % 10 else "")


def pointed_tokens(text):
    toks, cur = [], []
    for ch in unicodedata.normalize("NFC", text):
        if unicodedata.category(ch)[0] in ("L", "M"):
            cur.append(ch)
        elif cur:
            toks.append("".join(cur))
            cur = []
    if cur:
        toks.append("".join(cur))
    return [t for t in toks if any(unicodedata.category(c)[0] == "L" for c in t)]


def edition_text(ed, books, st, ex):
    """-> (verses {(book, c, v): [(i, token or None)]}, words rows, file hash per book)"""
    if VENDOR not in sys.path:
        sys.path.append(VENDOR)
    import bcv_tokenize
    import helloao_to_usj
    import verse_text
    by_book = C.defaultdict(list)
    for f in sorted(glob.glob(os.path.join(HELLOAO, ed, "*_*.json"))):
        b = os.path.basename(f).rsplit("_", 1)[0]
        with open(f, encoding="utf-8") as fh:
            by_book[b].append(json.load(fh))
    if set(by_book) != set(books):
        raise SystemExit(f"{ed}: books differ from the Greek New Testament: {sorted(set(by_book) ^ set(books))}")
    verses, rows, hashes = {}, [], {}
    s = 0
    for b in books:
        chs = sorted(by_book[b], key=lambda dd: dd["chapter"]["number"])
        vt = verse_text.extract_usj(helloao_to_usj.merge_book_usj(b, chs))
        vv = {(int(c), int(x["verse"])): x["text"] for c, vs in vt.items() for x in vs}
        fp, _ = bcv_tokenize.fingerprints(vv)
        hashes[b] = bcv_tokenize.file_hash(fp)
        for (c, v), text in sorted(vv.items()):
            toks = bcv_tokenize.tokenize(text)
            pts = pointed_tokens(text)
            if [bcv_tokenize.strip_marks(x) for x in pts] != toks:
                st[f"{ed} verses whose pointed words differ from the tokens (tokens taken)"] += 1
                pts = toks
            label = bool(toks) and toks[0] == heb_numeral(v) and pts[0] == toks[0]
            out = []
            for i, tok in enumerate(pts):
                if i == 0 and label:
                    st[f"{ed} verse-number tokens left out"] += 1
                    out.append((i, None))
                    continue
                s += 1
                rows.append((s, f"{ed} {b} {c}:{v} {i}", b, c, v, i,
                             scripted(tok, "HEBREW", f"{ed} text emptied: a letter of another script", ex), None, None))
                out.append((i, s))
            verses[(b, c, v)] = out
    st[f"{ed} words"] = len(rows)
    return verses, rows, hashes


def same_file(a, b):
    return os.path.exists(a) and os.path.exists(b) and sha256(a) == sha256(b)


def nt_compute(outdir, ex, st, counts):
    """The Hebrew New Testaments' words, links and account (stage 08). -> (links, account, words, P)"""
    W, P = read_lang(outdir, "grc")
    books = list(dict.fromkeys(w["book"] for w in sorted(W, key=lambda w: w["t"])))
    t_of = {w["id"]: w["t"] for w in W}
    piece = {p["t"]: p for p in P}
    proper = {p["t"] for p in P if json.loads(p["marks"] or "{}").get("type") == "proper"}
    with open(os.path.join(COMPACT, "manifest.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    all_l, all_a = [], []
    other_words = {}
    for ed in EDITIONS:
        E = man["languages"]["heb"]["editions"][ed]
        verses, rows, hashes = edition_text(ed, books, st, ex)
        other_words[ed] = rows
        vmap_path = os.path.join(PUBLISH, "_index", E["verse_map"])
        with open(vmap_path, encoding="utf-8") as fh:
            vmap = json.load(fh)["map"]
        links = set()
        for b in books:
            fa = os.path.join(COMPACT, "h", "heb", ed, f"{b}_{hashes[b]}.json")
            fl = os.path.join(COMPACT, "_index", f"{b}_lexemes.json")
            if not os.path.exists(fa):
                raise SystemExit(f"{fa}: the text's fingerprint names no file of the pinned download")
            for a, bb in ((fa, os.path.join(PUBLISH, "h", "heb", ed, os.path.basename(fa))),
                          (fl, os.path.join(PUBLISH, "_index", os.path.basename(fl)))):
                if not same_file(a, bb):
                    if getattr(X, "REPLAY18", False):
                        # SPEC 1.8 replay (stage 52, report 52): the aligner republished this file after i1, and its
                        # sidecar of i1's day is gone; the NT links of this run are not kept (j1 holds i1's), so the
                        # republished pair is read only to let the stage run; counted
                        X.REPLAY18_DRIFT.append(os.path.relpath(bb, os.path.dirname(PUBLISH)))
                        if a == fa:
                            fa = bb
                        continue
                    raise SystemExit(f"{bb}: not byte-identical to the pinned {a}")
            with open(fa, encoding="utf-8") as fh:
                arr = json.load(fh)
            with open(fl, encoding="utf-8") as fh:
                lex = json.load(fh)
            with open(os.path.join(PUBLISH, "_index", f"{b}_keys.json"), encoding="utf-8") as fh:
                keys = json.load(fh)
            with open(os.path.join(PUBLISH, "h", "heb", ed, f"{b}_{hashes[b]}.meta.json"), encoding="utf-8") as fh:
                meta = json.load(fh)
            refs = list(lex)
            if not (len(arr) == len(refs) == len(meta["method"]) == len(meta["conf"])):
                raise SystemExit(f"{ed} {b}: alignment, index and sidecar lengths differ")
            for k, (ref, line) in enumerate(zip(refs, arr)):
                if not line:
                    continue
                items = line.split()
                meth, conf = meta["method"][k], meta["conf"][k]
                kv = keys.get(ref, [])
                if len(meth) != len(items) or len(conf) != len(items) or len(kv) != len(lex[ref]):
                    raise SystemExit(f"{ed} {ref}: entries, sidecar or keys differ in length")
                tgt = vmap.get(ref, ref)
                if tgt.split(" ", 1)[1].endswith(":title"):
                    st[f"{ed} entries in a verse the edition leaves unnumbered"] += len(items)
                    continue
                tb, tcv = tgt.split(" ", 1)
                tc, tv = map(int, tcv.split(":"))
                if ref != tgt:
                    st[f"{ed} entries read from a mapped verse"] += len(items)
                toks = dict(verses.get((tb, tc, tv), []))
                if (tb, tc, tv) not in verses:
                    st[f"{ed} entries whose verse is not in the text"] += len(items)
                    continue
                for j, item in enumerate(items):
                    o, span = item.split(":")
                    gks = kv[int(o)].split("+")
                    ts = [t_of.get("n" + g) for g in gks]
                    if None in ts:
                        st[f"{ed} source keys not in the Greek words"] += 1
                        ts = [t for t in ts if t is not None]
                    how = HOW_NT.get(meth[j])
                    if how is None:
                        raise SystemExit(f"{ed} {ref}: unknown method {meth[j]!r}")
                    st[f"{ed} entries {how} conf {conf[j]}"] += 1
                    if meth[j] in "gG" and conf[j] == "1" and any(t in proper for t in ts):
                        st[f"{ed} entries not taken: gloss only, on a proper noun"] += 1
                        ex.setdefault(f"{ed} gloss-only proper-noun entries", []).append(f"{ref} {item}")
                        continue
                    pos = []
                    for pc in span.split(","):
                        a0, _, z = pc.partition("-")
                        pos.extend(range(int(a0), int(z or a0) + 1))
                    for p_ in pos:
                        if p_ not in toks:
                            st[f"{ed} positions outside the verse"] += 1
                            continue
                        if toks[p_] is None:
                            st[f"{ed} positions on a verse-number token"] += 1
                            continue
                        for t in ts:
                            links.add((t, toks[p_], how))
        # one link per (t, s): a pair that two entries give keeps the `how` that comes first by code point
        best = {}
        for t, s, how in sorted(links):
            best.setdefault((t, s), how)
        st[f"{ed} (word, word) pairs given by two entries"] = len(links) - len(best)
        lrows = [(t, 1, ed, s, how, 1) for (t, s), how in sorted(best.items())]
        all_l.extend(lrows)
        linked_t = {r[0] for r in lrows}
        cls_all, cls_linked = C.Counter(), C.Counter()
        for p in P:
            cls_all[p["class"]] += 1
            cls_linked[p["class"]] += p["t"] in linked_t
        share = {c: cls_linked[c] / cls_all[c] for c in cls_all}
        naw = {c for c in cls_all if c in NT_CONTENT and share[c] < NAW_SHARE}
        counts[f"{ed} class shares (grc)"] = {c: [cls_linked[c], cls_all[c], round(share[c], 4)] for c in sorted(cls_all)}
        counts[f"{ed} never_a_word classes"] = sorted(naw)
        for p in P:
            if p["t"] in linked_t:
                state, reason = "linked", ""
            elif p["class"] not in NT_CONTENT:
                state, reason = "outside_alignment", p["class"]
            elif p["class"] in naw:
                state, reason = "never_a_word", p["class"]
            else:
                state, reason = "no_counterpart", ""
            all_a.append((p["t"], p["n"], ed, state, reason))
        # the alignment's own content slots against our classes (the card's classes)
        slotted = set()
        for f in glob.glob(os.path.join(PUBLISH, "_index", "*_keys.json")):
            bk = os.path.basename(f).split("_")[0]
            if bk in books and not os.path.basename(f).endswith("_fn_keys.json"):
                with open(f, encoding="utf-8") as fh:
                    for ks in json.load(fh).values():
                        for k_ in ks:
                            slotted.update(t_of.get("n" + g) for g in k_.split("+"))
        st["grc content words (noun, verb, adj) with no slot in the alignment"] = sum(
            1 for p in P if p["class"] in NT_CONTENT and p["t"] not in slotted)
        st["grc other words with a slot in the alignment"] = sum(
            1 for p in P if p["class"] not in NT_CONTENT and p["t"] in slotted)
    return all_l, all_a, other_words, P


def build_nt(outdir, counts, ex):
    st = C.Counter()
    all_l, all_a, other_words, P = nt_compute(outdir, ex, st, counts)
    piece = {p["t"]: p for p in P}
    d = os.path.join(outdir, "grc")
    for ed in EDITIONS:
        rows = other_words[ed]
        X.write_parquet(os.path.join(d, "other", ed, "words.parquet"),
                        {f.name: [r[i] for r in rows] for i, f in enumerate(OTHER_SCHEMA)}, OTHER_SCHEMA)
    write_links(d, "grc", all_l, all_a, counts)
    forms = {ed: {r[0]: X.norm_heb(r[6]) if r[6] else None for r in other_words[ed]} for ed in EDITIONS}
    counts["nt"] = dict(st)
    return all_l, forms, piece


# ---- rendered_by -----------------------------------------------------------------------------------------------

def write_facts(d, lang, lrows, object_of, lexeme_of, source_of, counts):
    """facts.parquet anew: earlier rows that are not rendered_by, then rendered_by from the links."""
    path = os.path.join(d, "facts.parquet")
    old = [r for r in pq.read_table(path).to_pylist() if r["relation"] != "rendered_by"]
    pair = C.Counter()
    for t, n, other, s, how, agree in lrows:
        o = object_of[other](s)
        if o is None:                      # the other word's text and lemma were emptied (another script)
            counts[f"{lang} links giving no rendered_by (word emptied)"] = counts.get(
                f"{lang} links giving no rendered_by (word emptied)", 0) + 1
            continue
        pair[(lexeme_of[(t, n)], other, o)] += 1
    total = C.Counter()
    for (lx, other, _), v in pair.items():
        total[(lx, other)] += v
    new = [{"subject": lx, "relation": "rendered_by", "object": obj, "kind": "linked", "method": "links.parquet",
            "source": source_of[other], "confidence": None, "count": v, "share": v / total[(lx, other)], "tier": ""}
           for (lx, other, obj), v in pair.items()]
    rows = sorted(old + new, key=lambda r: (r["subject"], r["relation"], r["object"]))
    X.write_parquet(path, {f.name: [r[f.name] for r in rows] for f in FACT_SCHEMA}, FACT_SCHEMA)
    counts[f"{lang} facts rendered_by rows"] = len(new)
    counts[f"{lang} facts other rows kept"] = len(old)


def build(outdir, langs, counts):
    ex = {}
    if set(langs) & {"hbo", "arc"}:
        if not {"hbo", "arc"} <= set(langs):
            raise SystemExit("stage 08 builds hbo and arc together (one Tanakh against one Septuagint)")
        build_lxx(outdir, counts, ex)
        lxx_words = pq.read_table(os.path.join(outdir, "hbo", "other", "lxx", "words.parquet"),
                                  columns=["s", "lemma", "text"]).to_pylist()
        lem = {w["s"]: w["lemma"] for w in lxx_words}
        frm = {w["s"]: X.norm_grc(w["text"]) if w["text"] else None for w in lxx_words}
        obj = {"lxx": lambda s: f"lxx:{lem[s]}" if lem[s] else f"lxx:form:{frm[s]}" if frm[s] else None}
        for lang in ("hbo", "arc"):
            d = os.path.join(outdir, lang)
            lrows = [tuple(r.values()) for r in pq.read_table(os.path.join(d, "links.parquet")).to_pylist()]
            P = pq.read_table(os.path.join(d, "pieces.parquet"), columns=["t", "n", "lexeme"]).to_pylist()
            write_facts(d, lang, lrows, obj, {(p["t"], p["n"]): p["lexeme"] for p in P},
                        {"lxx": "hebrew-greek-cf"}, counts)
    if "grc" in langs:
        lrows, forms, piece = build_nt(outdir, counts, ex)
        obj = {ed: (lambda s, ed=ed: f"{ed}:form:{forms[ed][s]}" if forms[ed][s] else None) for ed in EDITIONS}
        write_facts(os.path.join(outdir, "grc"), "grc", lrows, obj,
                    {(t, 1): piece[t]["lexeme"] for t in piece}, {ed: "compact-alignments" for ed in EDITIONS}, counts)
    counts["sources read"] = {
        "bridge lxx.parquet": BRIDGE_SHA, "lxx-glaux.db": GLAUX_SHA, "greek_numbers.tsv": sha256(NUMBERS),
        "licences": {"lxx": "CC BY-SA 4.0 (GLAUx; text may be copied; lemma and class are GLAUx's own, made "
                            "automatically by its makers)",
                     "heb_scg": "public domain (eBible hebsg via bible.helloao.org; text may be copied)",
                     "heb_mod": "public domain (eBible heb via bible.helloao.org; text may be copied)"}}
    return ex
