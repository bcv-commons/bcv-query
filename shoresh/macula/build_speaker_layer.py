"""Build the Hebrew speaker layer (proposed dataset bcv-commons/hebrew-speaker-layer): the baseline and its nesting.

Who speaks where in the Hebrew Bible, on MACULA's Hebrew words and on the clause segments of the clause layout
(macula/data/clause-layout). The baseline is Clear's quotation spans (resources/speaker_quotations: "MACULA Quotation and Speaker
Data", CC BY 4.0, projected from the quotation marks of an English translation onto the Hebrew words through the alignment), with
their speakers (FCBH / Glyssen, refined per quotation). This step puts them on the Hebrew text as it is and reports where they are
doubtful; nesting and corrections are the next steps.

Edges: a span edge given as a word part MACULA doesn't have (Clear counts a part such as the article inside "בָּאָרֶץ" that MACULA
merges) moves to the nearest token of the same word. A clause segment belongs to a quotation when most of its words are in it.

Writes macula/data/speaker-layer/:
  quotations.tsv        one row per quotation: id, speaker, the Hebrew word keys of its first and last word, verses, how the edges fit
  segments/<BOOK>.tsv   one row per clause segment: its quotation (or none), speaker, and the share of its words in the quotation
  report.md             the baseline's figures and the lists of doubtful places (the work list for the next steps)

  python -m macula.build_speaker_layer [--books GEN,JER]
"""
from __future__ import annotations

import argparse
import bisect
import collections
import csv
import json
import sqlite3
import sys
from pathlib import Path

SHORESH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHORESH))

import trees_macula  # noqa: E402
from macula import discourse_rules as D  # noqa: E402
from macula.build_clause_layout import _verb_person  # noqa: E402

SPANS = SHORESH.parent / "resources" / "speaker_quotations" / "speaker_quotations.tsv"
LAYOUT = SHORESH / "macula" / "data" / "clause-layout" / "clauses"
OUT = SHORESH / "macula" / "data" / "speaker-layer"


GLYSSEN_URL = "https://raw.githubusercontent.com/sillsdev/Glyssen/master/GlyssenCharacters/Resources/CharacterVerse.txt"


def glyssen() -> tuple[dict, str]:
    """Glyssen's characters per verse (SIL / FCBH, MIT), English numbering: (book, chapter, verse) -> character names; and the file's
    sha256. Cached in the output folder."""
    import hashlib
    import urllib.request
    cache = OUT / "_cache" / "CharacterVerse.txt"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(GLYSSEN_URL, timeout=120) as r:
            cache.write_bytes(r.read())
    raw = cache.read_bytes()
    chars: dict = collections.defaultdict(set)
    for line in raw.decode("utf-8").splitlines():
        p = line.split("\t")
        if line.startswith("#") or len(p) < 4 or not p[1].isdigit():
            continue
        try:
            lo, hi = (int(x) for x in (p[2].split("-")[0], p[2].split("-")[-1]))
        except ValueError:
            continue
        for v in range(lo, hi + 1):
            chars[(p[0], int(p[1]), v)].add(p[3])
    return chars, hashlib.sha256(raw).hexdigest()


def load_spans() -> list[dict]:
    with open(SPANS, encoding="utf-8") as fh:
        rows = list(csv.DictReader((line for line in fh if not line.startswith("#")), delimiter="\t"))
    return [r for r in rows if r["word_start"].startswith("o") and r["word_end"].startswith("o")]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--books", help="comma-separated USFM codes (default: all)")
    a = ap.parse_args()
    only = set(a.books.upper().split(",")) if a.books else None

    # the clause segments, in text order
    segs: list[dict] = []
    for f in sorted(LAYOUT.glob("*/*.jsonl")):
        rows = [json.loads(line) for line in open(f, encoding="utf-8")]
        if only and rows and rows[0]["book"] not in only:
            continue
        segs += rows
    order = {}
    for i, s in enumerate(segs):
        for w in s["words"]:
            order[w] = i
    keys = sorted(order)
    by_word = collections.defaultdict(list)          # word (first 11 digits) -> its token keys
    for k in keys:
        by_word[k[:11]].append(k)

    con = sqlite3.connect(f"file:{trees_macula.trees_path()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    tok = {r["key"]: r for r in con.execute("SELECT key, class, lemma, strong, wtype, cl, seq, role FROM words WHERE corpus='hbo' AND inserted=0")}
    subj_of: dict[int, list[tuple[int, int]]] = collections.defaultdict(list)      # clause node -> its subject phrases (word seq ranges)
    for r in con.execute("SELECT parent, lo, hi FROM nodes WHERE corpus='hbo' AND role='s'"):
        subj_of[r["parent"]].append((r["lo"], r["hi"]))
    by_seq = {r["seq"]: r for r in tok.values()}

    def subject_tokens(sg: dict) -> list:          # the subject of a segment's clause: its nouns, names and pronouns
        cls = {tok[w]["cl"] for w in sg["words"] if w in tok and tok[w]["cl"] is not None}
        out = [tok[w] for w in sg["words"] if w in tok and tok[w]["role"] == "s" and tok[w]["class"] in ("noun", "pron")]
        for c in cls:
            for lo, hi in subj_of.get(c, []):
                out += [by_seq[q] for q in range(lo, hi + 1) if q in by_seq and by_seq[q]["class"] in ("noun", "pron")]
        return list({t["key"]: t for t in out}.values())

    def subject_words(sg: dict) -> str:
        return " ".join(dict.fromkeys(t["lemma"] for t in subject_tokens(sg)))

    names = {}                                     # Strong's -> English name (resources/proper_nouns/eng.tsv, gloss rows)
    pn = SHORESH.parent / "resources" / "proper_nouns" / "eng.tsv"
    if pn.exists():
        for line in open(pn, encoding="utf-8"):
            p = line.rstrip("\n").split("\t")
            if len(p) >= 5 and p[4] == "gloss" and p[2] == "person":
                names.setdefault(p[0], p[3])
    import vrsmap
    chars, glyssen_sha = glyssen()

    def english_speaker(sg: dict) -> str:          # the subject as one of Glyssen's characters for the verse, or its English name
        cands = set()
        for r in vrsmap.to_eng((sg["book"], sg["chapter"], sg["verse"]), "org") or [(sg["book"], sg["chapter"], sg["verse"])]:
            cands |= chars.get(tuple(r)[:3], set())
        toks = subject_tokens(sg)
        if any(D._strong(t) in D.DIVINE for t in toks):
            return "God"
        for t in toks:
            if t["wtype"] != "proper":                 # names only from proper nouns ("אָב" is no one's name)
                continue
            st = D._strong(t)
            name = names.get(f"H{int(st):04d}") if st and st.isdigit() else None
            if name:
                hit = next((c for c in sorted(cands) if c == name or c.startswith(name + " ") or name in c.split("/")), None)
                return hit or name
        return ""
    person, number = _verb_person(con, {k for k, r in tok.items() if r["class"] in ("verb", "pron")})

    def snap(key: str, end: bool) -> tuple[str | None, str]:
        if key in order:
            return key, "exact"
        ks = by_word.get(key[:11])
        if ks:
            return (ks[-1] if end else ks[0]), "same word"
        return None, "not found"

    def verb(s: dict) -> dict | None:              # the first finite verb of a segment
        for w in s["words"]:
            t = tok.get(w)
            if t is not None and t["class"] == "verb" and t["wtype"] in D.FINITE:
                return {"form": t["wtype"], "person": person.get(w), "number": number.get(w), "strong": D._strong(t)}
        return None

    def saying(s: dict) -> bool:
        return any((t := tok.get(w)) is not None and t["class"] == "verb" and D._strong(t) in D.SAY for w in s["words"])

    spans = []
    for n, r in enumerate(load_spans(), 1):
        a0, af = snap(r["word_start"][1:], False)
        b0, bf = snap(r["word_end"][1:], True)
        if a0 is None or b0 is None or (only and segs and not (a0 in order and b0 in order)):
            continue
        sa, sb = segs[order[a0]], segs[order[b0]]
        spans.append({"id": f"q{n:05d}", "speaker": r["speaker"], "alt_speaker": r["alt_speaker"], "divine": r["divine"],
                      "quote_type": r["quote_type"], "basis": r["speaker_basis"], "first": a0, "last": b0,
                      "start_fit": af if af != "exact" else ("segment start" if a0 == sa["first"] else "inside a segment"),
                      "end_fit": bf if bf != "exact" else ("segment end" if b0 == sb["last"] else "inside a segment"),
                      "from": f"{sa['book']} {sa['chapter']}:{sa['verse']}", "to": f"{sb['book']} {sb['chapter']}:{sb['verse']}"})
    spans.sort(key=lambda s: s["first"])

    def is_inquit(sg: dict) -> bool:               # a segment that only introduces speech: a verb of saying, "saying", a speaking formula
        return saying(sg) or any(D._n(tok[w]["lemma"]) in D.FORMULA for w in sg["words"] if w in tok) \
            or (len(sg["words"]) <= 3 and any(D._strong(tok[w]) in D.SAY_INF and tok[w]["wtype"] == "infinitive construct" for w in sg["words"] if w in tok))

    # refinement 1: a quotation that starts on its own inquit ("וַתֹּאמֶר", "לֵאמֹר") starts after it
    fixed_start = 0
    for sp in spans:
        i = order[sp["first"]]
        while segs[i]["first"] == sp["first"] and is_inquit(segs[i]) and i + 1 < len(segs) and segs[i + 1]["first"] <= sp["last"] \
                and segs[i + 1]["verse"] == segs[i]["verse"] or (segs[i]["first"] == sp["first"] and is_inquit(segs[i])
                                                                 and i + 1 < len(segs) and segs[i + 1]["first"] <= sp["last"]):
            sp["first"], sp["start_fit"] = segs[i + 1]["first"], "after its inquit"
            fixed_start += 1
            i += 1
    # refinement 2: an edge inside a clause segment that only leaves out a prefix, particle or suffix of the segment (the English word
    # order put the quotation mark there: "הֲ", "וְ", the article, "כִּי", "הִנֵּה", the object marker, a pronoun suffix) moves to the
    # segment's edge; a start after an inquit in the same segment moves to the next segment
    FUNCTION = {"cj", "ptcl", "art", "prep", "pron", "intj", "ij", "om", "rel"}
    LEAD_IN = {D._n(x) for x in ("הִנֵּה", "הֵן")}

    def functional(ws: list[str]) -> bool:
        return all(w not in tok or tok[w]["class"] in FUNCTION or D._n(tok[w]["lemma"]) in LEAD_IN or not tok[w]["lemma"] for w in ws)
    snapped = collections.Counter()
    for sp in spans:
        sg = segs[order[sp["first"]]]
        pre = sg["words"][:sg["words"].index(sp["first"])]
        if pre:
            if saying({"words": pre}) and order[sp["first"]] + 1 < len(segs) and segs[order[sp["first"]] + 1]["first"] <= sp["last"]:
                sp["first"], sp["start_fit"] = segs[order[sp["first"]] + 1]["first"], "after its inquit"
                snapped["start after an inquit in its segment"] += 1
            elif functional(pre):
                sp["first"], sp["start_fit"] = sg["first"], "snapped to segment start"
                snapped["start snapped back over a prefix or particle"] += 1
        sg = segs[order[sp["last"]]]
        post = sg["words"][sg["words"].index(sp["last"]) + 1:]
        if post and functional(post):
            sp["last"], sp["end_fit"] = sg["last"], "snapped to segment end"
            snapped["end snapped over a suffix or particle"] += 1

    # refinement 3: pieces of one speech: the next span of the same speaker with nothing between them but a speaking formula
    merged, out_spans = 0, []
    for sp in spans:
        prev = out_spans[-1] if out_spans else None
        if prev and prev["speaker"] == sp["speaker"]:
            gap = range(order[prev["last"]] + 1, order[sp["first"]])
            if all(any(D._n(tok[w]["lemma"]) in D.FORMULA for w in segs[g]["words"] if w in tok) for g in gap) \
                    and order[sp["first"]] >= order[prev["last"]]:
                prev["last"], prev["end_fit"], prev["to"] = sp["last"], sp["end_fit"], sp["to"]
                prev["pieces"] = prev.get("pieces", 1) + 1
                merged += 1
                continue
        out_spans.append(sp)
    spans = out_spans
    starts = [s["first"] for s in spans]

    def span_at(k: str) -> dict | None:
        i = bisect.bisect_right(starts, k) - 1
        return spans[i] if i >= 0 and spans[i]["first"] <= k <= spans[i]["last"] else None

    # segments -> quotation
    seg_q: list[tuple[dict | None, float]] = []
    for s in segs:
        hits = collections.Counter(sp["id"] if (sp := span_at(w)) else None for w in s["words"])
        q, n = hits.most_common(1)[0]
        sp = next((x for x in spans if x["id"] == q), None) if q else None
        seg_q.append((sp, n / len(s["words"])))

    # corrections (resources/speaker_layer/corrections.tsv): hand corrections with their reasons, applied to the outer quotations
    corr_path = SHORESH.parent / "resources" / "speaker_layer" / "corrections.tsv"
    applied = 0
    if corr_path.exists():
        with open(corr_path, encoding="utf-8") as fh:
            corr = list(csv.DictReader((line for line in fh if not line.startswith("#")), delimiter="\t"))
        by_first = {sp["first"]: sp for sp in spans}
        for c in corr:
            sp = by_first.get(c["first"])
            if sp is None or not c.get("reason"):
                continue
            if c["field"] == "drop":
                spans.remove(sp)
            elif c["field"] in ("speaker", "first", "last") and c["value"]:
                sp[c["field"]] = c["value"]
                sp["basis"] = "correction"
            applied += 1
        spans.sort(key=lambda q: q["first"])
        starts[:] = [q["first"] for q in spans]
        seg_q[:] = []
        for sg in segs:
            hits = collections.Counter(q["id"] if (q := span_at(w)) else None for w in sg["words"])
            q, n = hits.most_common(1)[0]
            seg_q.append((next((x for x in spans if x["id"] == q), None) if q else None, n / len(sg["words"])))

    # the layout's speech structure, a second source: how many speeches a segment's clause stands in (relation "speech" links up its
    # discourse_parent chain in macula/data/clause-layout)
    par, rel = {}, {}
    for sg in segs:
        par.setdefault(sg["clause_key"], sg.get("discourse_parent"))
        rel.setdefault(sg["clause_key"], sg.get("relation"))
    memo: dict[str, int] = {}

    def sdepth(k: str) -> int:
        seen, x = [], k
        while x is not None and x not in memo and x not in seen:
            seen.append(x)
            x = par.get(x)
        base = memo.get(x, 0)
        for y in reversed(seen):
            base += rel.get(y) == "speech"
            memo[y] = base
        return memo.get(k, 0)
    first_seg = {}
    for i, sg in enumerate(segs):
        first_seg.setdefault(sg["clause_key"], i)

    def inquit_of(k: str) -> dict | None:          # the segment of the clause a speech hangs on (through "saying" to its clause)
        x, seen = k, set()
        while x is not None and rel.get(x) != "speech" and x not in seen:
            seen.add(x)
            x = par.get(x)
        q = par.get(x) if x is not None else None
        iq = segs[first_seg[q]] if q in first_seg else None
        if iq and len(iq["words"]) <= 3 and any(D._strong(tok[w]) in D.SAY_INF and tok[w]["wtype"] == "infinitive construct"
                                                 for w in iq["words"] if w in tok) and par.get(q) in first_seg:
            iq = segs[first_seg[par[q]]]
        return iq

    # refinement 4: in the narrative books, a stretch the layout has as speech, with no Clear quotation and with a first- or second-person
    # verb in it, is a quotation Clear lacks (1 Chr 16:8-35, 1 Sam 3:6); speaker from its inquit
    added = 0
    i = 0
    while i < len(segs):
        if seg_q[i][0] is None and sdepth(segs[i]["clause_key"]) > 0 and segs[i]["book"] not in D.GROUPS["poetic"] \
                and segs[i]["book"] not in D.GROUPS["memoirs"]:
            j = i
            while j + 1 < len(segs) and seg_q[j + 1][0] is None and sdepth(segs[j + 1]["clause_key"]) > 0 \
                    and (segs[j + 1]["book"], segs[j + 1]["chapter"]) == (segs[i]["book"], segs[i]["chapter"]):
                j += 1
            if any((v := verb(segs[x])) and v["person"] in ("first", "second") for x in range(i, j + 1)):
                iq = inquit_of(segs[i]["clause_key"])
                v = verb(iq) if iq else None
                who = english_speaker(iq) if iq else ""
                if not who and v:
                    who = {"second": "(the one addressed)"}.get(v["person"], "(they)" if v.get("number") == "plural" else "(he/she)")
                added += 1
                sp = {"id": f"L{added:05d}", "speaker": who, "speaker_hebrew": subject_words(iq) if iq else "", "alt_speaker": "",
                      "divine": "Y" if who == "God" else "", "quote_type": "layout only", "basis": "layout", "first": segs[i]["first"],
                      "last": segs[j]["last"], "from": f"{segs[i]['book']} {segs[i]['chapter']}:{segs[i]['verse']}",
                      "to": f"{segs[j]['book']} {segs[j]['chapter']}:{segs[j]['verse']}", "start_fit": "segment start",
                      "end_fit": "segment end", "pieces": 1, "inquit": iq["text"] if iq else ""}
                spans.append(sp)
                for x in range(i, j + 1):
                    seg_q[x] = (sp, 1.0)
            i = j + 1
        else:
            i += 1

    def voiced(sg: dict) -> bool:                  # a finite verb in the first or second person
        return any(w in tok and tok[w]["class"] == "verb" and tok[w]["wtype"] in D.FINITE and person.get(w) in ("first", "second")
                   for w in sg["words"])
    narrative_book = lambda b: b not in D.GROUPS["poetic"] and b not in D.GROUPS["first_person_narrator"]  # noqa: E731

    # refinement 5: in the narrative books, a run outside quotations in which at least three verses speak in the first or second
    # person is a song or speech (1 Chr 16:8-35, David's psalm); speaker from the nearest frame before it with a named subject
    songs = 0
    i = 0
    while i < len(segs):
        if seg_q[i][0] is None and narrative_book(segs[i]["book"]):
            j = i
            while j + 1 < len(segs) and seg_q[j + 1][0] is None and (segs[j + 1]["book"], segs[j + 1]["chapter"]) == (segs[i]["book"], segs[i]["chapter"]):
                j += 1
            vx = [x for x in range(i, j + 1) if voiced(segs[x])]
            if len({segs[x]["verse"] for x in vx}) >= 3:
                a, b = vx[0], vx[-1]
                while a > i and segs[a - 1]["verse"] == segs[a]["verse"] and not saying(segs[a - 1]):
                    a -= 1
                while b < j and segs[b + 1]["verse"] == segs[b]["verse"]:
                    b += 1
                frame = next((segs[x] for x in range(a - 1, max(-1, a - 40), -1) if english_speaker(segs[x])), None)
                who = english_speaker(frame) if frame else ""
                songs += 1
                sp = {"id": f"S{songs:05d}", "speaker": who, "speaker_hebrew": subject_words(frame) if frame else "", "alt_speaker": "",
                      "divine": "Y" if who == "God" else "", "quote_type": "song or speech", "basis": "voice", "first": segs[a]["first"],
                      "last": segs[b]["last"], "from": f"{segs[a]['book']} {segs[a]['chapter']}:{segs[a]['verse']}",
                      "to": f"{segs[b]['book']} {segs[b]['chapter']}:{segs[b]['verse']}", "start_fit": "segment start",
                      "end_fit": "segment end", "pieces": 1, "inquit": frame["text"] if frame else ""}
                spans.append(sp)
                for x in range(a, b + 1):
                    seg_q[x] = (sp, 1.0)
            i = j + 1
        else:
            i += 1

    # refinement 6: a quotation that ends on an inquit ("וַיֹּאמֶר …" as its last line: the English quotation mark closed after it)
    # ends before it; the inquit introduces the next speech (the mirror of refinement 1). A quotation that goes on after a
    # "וַיֹּאמֶר" is left as it is: that can be a story the speaker tells (Micaiah's vision, 1 Kgs 22:19-23; Jotham's fable)
    split = 0
    for i in range(1, len(segs)):
        q = seg_q[i][0]
        if q is None or seg_q[i - 1][0] is not q or (i + 1 < len(segs) and seg_q[i + 1][0] is q):
            continue
        v = verb(segs[i])
        if v and v["form"] == "wayyiqtol" and saying(segs[i]):
            q["last"], q["to"] = segs[i - 1]["last"], f"{segs[i - 1]['book']} {segs[i - 1]['chapter']}:{segs[i - 1]['verse']}"
            q["end_fit"] = "before its closing inquit"
            seg_q[i] = (None, 0.0)
            split += 1

    # nesting: inside a quotation, a stretch where the layout stands a speech level deeper than at the quotation's start is a quotation
    # inside it, opened by the clause its first line hangs on as speech (the inquit)
    level = [0] * len(segs)
    inner: list[dict] = []
    innermost: list[dict | None] = [sp for sp, _ in seg_q]
    by_id = {sp["id"]: sp for sp in spans}
    for sp in spans:
        sp["level"], sp["parent"] = 1, ""
        idx = [i for i in range(order[sp["first"]], order[sp["last"]] + 1) if seg_q[i][0] is sp]
        if not idx:
            continue
        base = sdepth(segs[idx[0]]["clause_key"])
        for i in idx:
            level[i] = 1 + max(0, sdepth(segs[i]["clause_key"]) - base)
        stack: list[dict] = [sp]
        n = 0
        for i in idx:
            want = level[i]
            while len(stack) > want:
                stack.pop()
            while len(stack) < want:
                n += 1
                outer = stack[-1]
                k = segs[i]["clause_key"]
                inquit = par.get(k) if rel.get(k) == "speech" else None
                iq = segs[first_seg[inquit]] if inquit in first_seg else None
                if iq and len(iq["words"]) <= 3 and any(D._strong(tok[w]) in D.SAY_INF and tok[w]["wtype"] == "infinitive construct" for w in iq["words"] if w in tok) \
                        and par.get(inquit) in first_seg:
                    iq = segs[first_seg[par[inquit]]]           # "saying": the speaker is in the clause it hangs on
                v = verb(iq) if iq else None
                who = outer["speaker"] if v and v["person"] == "first" else ""
                who_he = subject_words(iq) if iq else ""
                if not who and iq:
                    who = english_speaker(iq)
                if not who and not who_he and v and v["person"] == "second":
                    who = "(the one addressed)"
                elif not who and not who_he and v and v["person"] == "third":
                    who = "(they)" if v.get("number") == "plural" else "(he/she)"   # the subject is only in the verb
                q = {"id": f"{sp['id']}.{n}", "speaker": who, "speaker_hebrew": who_he, "level": len(stack) + 1, "parent": outer["id"], "first": segs[i]["first"],
                     "last": segs[i]["last"], "from": f"{segs[i]['book']} {segs[i]['chapter']}:{segs[i]['verse']}",
                     "inquit": iq["text"] if iq else "", "alt_speaker": "", "divine": "", "quote_type": "nested", "basis": "layout",
                     "start_fit": "segment start", "end_fit": "segment end", "pieces": 1}
                inner.append(q)
                stack.append(q)
            for q in stack[1:]:
                q["last"], q["to"] = segs[i]["last"], f"{segs[i]['book']} {segs[i]['chapter']}:{segs[i]['verse']}"
            innermost[i] = stack[-1]

    # nesting by the messenger formula: inside a quotation, "כֹּה אָמַר X" opens X's words, one level deeper, to the end of the
    # quotation, where the layout hasn't nested them already (2 Kgs 19:20-34, Josh 24:2-13, Judg 11:15-27)
    messenger = 0
    for sp in spans:
        idx = [i for i in range(order[sp["first"]], order[sp["last"]] + 1) if seg_q[i][0] is sp]
        for pos, m in enumerate(idx[:-1]):
            sg = segs[m]
            if not (any(D._n(tok[w]["lemma"]) == D.KO for w in sg["words"][:3] if w in tok)
                    and any(w in tok and tok[w]["class"] == "verb" and D._strong(tok[w]) in D.SAY and tok[w]["wtype"] == "qatal"
                            for w in sg["words"])):
                continue
            rest = [x for x in idx[pos + 1:] if level[x] <= level[m]]
            if not rest or rest != idx[pos + 1:pos + 1 + len(rest)]:
                continue
            messenger += 1
            outer = innermost[m] or sp
            who = english_speaker(sg) or ""
            q = {"id": f"{sp['id']}.m{messenger}", "speaker": who, "speaker_hebrew": subject_words(sg), "level": level[m] + 1,
                 "parent": outer["id"], "first": segs[rest[0]]["first"], "last": segs[rest[-1]]["last"],
                 "from": f"{segs[rest[0]]['book']} {segs[rest[0]]['chapter']}:{segs[rest[0]]['verse']}",
                 "to": f"{segs[rest[-1]]['book']} {segs[rest[-1]]['chapter']}:{segs[rest[-1]]['verse']}", "inquit": sg["text"],
                 "alt_speaker": "", "divine": "Y" if who == "God" else "", "quote_type": "nested", "basis": "messenger formula",
                 "start_fit": "segment start", "end_fit": "segment end", "pieces": 1}
            inner.append(q)
            for x in rest:
                level[x] += 1
                innermost[x] = q
            break

    def is_messenger(sg: dict) -> bool:
        return any(D._n(tok[w]["lemma"]) == D.KO for w in sg["words"][:3] if w in tok) and any(
            w in tok and tok[w]["class"] == "verb" and D._strong(tok[w]) in D.SAY and tok[w]["wtype"] == "qatal" for w in sg["words"])

    def wrap(first: int, last: int, who: str, iq: dict | None, kind: str) -> dict:
        """a new outer quotation over segments first..last: what stood in quotations there moves one level in, under it"""
        global_id = f"W{len(wrapped) + 1:05d}"
        w = {"id": global_id, "speaker": who, "speaker_hebrew": subject_words(iq) if iq else "", "level": 1, "parent": "",
             "alt_speaker": "", "divine": "Y" if who == "God" else "", "quote_type": kind, "basis": kind, "first": segs[first]["first"],
             "last": segs[last]["last"], "from": f"{segs[first]['book']} {segs[first]['chapter']}:{segs[first]['verse']}",
             "to": f"{segs[last]['book']} {segs[last]['chapter']}:{segs[last]['verse']}", "start_fit": "segment start",
             "end_fit": "segment end", "pieces": 1, "inquit": iq["text"] if iq else ""}
        wrapped.append(w)
        moved = set()
        for x in range(first, last + 1):
            if seg_q[x][0] is None:
                seg_q[x], level[x], innermost[x] = (w, 1.0), 1, w
            else:
                level[x] += 1
                for q in {id(seg_q[x][0]): seg_q[x][0], id(innermost[x]): innermost[x]}.values():
                    if q is not None and id(q) not in moved:
                        q["level"] = q.get("level", 1) + 1
                        if q.get("level") == 2:
                            q["parent"] = global_id
                        moved.add(id(q))
                seg_q[x] = (w, 1.0) if False else seg_q[x]
        return w
    wrapped: list[dict] = []

    frame_of: dict = {}                           # (book, chapter) -> the person its title names with "לְ" (לְדָוִד, לְאָסָף, לִבְנֵי־קֹרַח)
    for sg in segs:
        if sg["book"] in D.GROUPS["frame_poems"] and sg["verse"] == 1 and (sg["book"], sg["chapter"]) not in frame_of:
            ws = [w for w in sg["words"] if w in tok]
            for a, b in zip(ws, ws[1:]):
                if D._n(tok[a]["lemma"]) == D.LE and tok[b]["wtype"] == "proper" and D._strong(tok[b]).isdigit():
                    name = names.get(f"H{int(D._strong(tok[b])):04d}")
                    if name:
                        frame_of[(sg["book"], sg["chapter"])] = name
                        break
    # relayed messages: a messenger formula outside any quotation ("וַיֹּאמֶר יְהוֹשֻׁעַ … כֹּה־אָמַר יְהוָה", Josh 24:2; "וַיִּשְׁלַח מֹשֶׁה
    # מַלְאָכִים … כֹּה אָמַר אָחִיךָ יִשְׂרָאֵל", Num 20:14) right before a quotation: the formula line is the messenger's speech (level 1),
    # and the quotations that follow without a break are the sender's words inside it (level 2) (bsb-add-books: the reference's layout
    # in Josh 24, Judg 11, Exod 10, Num 20, Josh 22)
    relayed = 0
    for f in range(1, len(segs) - 1):
        if seg_q[f][0] is not None or seg_q[f + 1][0] is None or not is_messenger(segs[f]) or not narrative_book(segs[f]["book"]):
            continue
        frame_seg = next((segs[x] for x in range(f - 1, max(-1, f - 4), -1) if english_speaker(segs[x]) or verb(segs[x])), None)
        who = english_speaker(frame_seg) if frame_seg else ""
        sender = english_speaker(segs[f]) or ""
        # the sender's words run on through the quotations that follow without a break (a stop at the sender named in the third
        # person failed: God names himself in the third person in his own speech, Josh 24:7)
        last, x = f + 1, f + 1
        while x + 1 < len(segs) and seg_q[x + 1][0] is not None and (segs[x + 1]["book"], segs[x + 1]["chapter"]) == (segs[f]["book"], segs[f]["chapter"]):
            x += 1
        last = x
        pieces = {id(seg_q[y][0]): seg_q[y][0] for y in range(f + 1, last + 1)}
        for q in pieces.values():
            if sender:
                q["speaker"] = sender             # the sender's words, whatever voice FCBH cast for them
        if not who and frame_seg and (v := verb(frame_seg)):
            who = "(they)" if v.get("number") == "plural" else "(he/she)"
        wrap(f, last, who, frame_seg, "relayed message")
        relayed += 1

    # a psalm whose title ends with an inquit ("וַיֹּאמַר" in its title or opening its first line after it, Ps 18:1-2) is a quotation
    # opened by it, not speech from its start
    titled = 0
    titled_chapters: set = set()
    i = 0
    while i < len(segs):
        sg = segs[i]
        first_line_after_title = sg["verse"] == 2 and i > 0 and segs[i - 1]["verse"] == 1 and (segs[i - 1]["chapter"] == sg["chapter"])
        if sg["book"] in D.GROUPS["frame_poems"] and (sg["verse"] == 1 or first_line_after_title) and (v := verb(sg)) \
                and v["form"] == "wayyiqtol" and saying(sg):
            j = i + 1
            while j < len(segs) and (segs[j]["book"], segs[j]["chapter"]) == (sg["book"], sg["chapter"]):
                j += 1
            if j - 1 > i:
                head = next((x for x in segs if (x["book"], x["chapter"], x["verse"]) == (sg["book"], sg["chapter"], 1)), sg)
                wrap(i + 1, j - 1, frame_of.get((sg["book"], sg["chapter"]), "Psalmist"), head, "titled psalm")
                titled += 1
                titled_chapters.add((sg["book"], sg["chapter"]))
            i = j
        else:
            i += 1

    # the frame: a psalm is its psalmist's speech from its first line; per segment, the speaker of the frame (not a level)
    frame = [""] * len(segs)
    for i, sg in enumerate(segs):
        if sg["book"] in D.GROUPS["frame_poems"] and (sg["book"], sg["chapter"]) not in titled_chapters:
            frame[i] = frame_of.get((sg["book"], sg["chapter"]), "Psalmist")

    # the work lists
    no_inquit, frames_agree, frames_disagree, voiced_outside, inner_inquits = [], [], [], [], []
    agree = collections.Counter()
    layout_only = collections.Counter()
    for i, s in enumerate(segs):
        sp, share = seg_q[i]
        prev = seg_q[i - 1][0] if i else None
        v = verb(s)
        ref = f"{s['book']} {s['chapter']}:{s['verse']}"
        in_layout = sdepth(s["clause_key"]) > 0
        agree[(bool(sp), in_layout)] += 1
        if in_layout and not sp:
            layout_only[s["book"]] += 1
        if sp and (prev is None or prev["id"] != sp["id"]):                           # a quotation starts here
            before = [segs[j] for j in range(max(0, i - 3), i)]
            if not any(saying(b) for b in before) \
                    and not any(D._n(tok[w]["lemma"]) in D.FORMULA for b in before for w in b["words"] if w in tok):
                no_inquit.append((ref, sp["speaker"], s["text"]))
        inside = sp and prev and prev["id"] == sp["id"]
        if inside and v and v["form"] == "wayyiqtol" and v["person"] == "third" and saying(s):
            inner_inquits.append((ref, sp["speaker"], s["text"]))                       # "and he said" inside a quotation
        elif inside and v and v["form"] == "wayyiqtol" and v["person"] == "third" and not D.active("poem_wayyiqtol_continues", s["book"]):
            (frames_agree if in_layout else frames_disagree).append((ref, sp["speaker"], s["text"]))
        if not sp and v and v["person"] in ("first", "second") and s["book"] not in D.GROUPS["first_person_narrator"] \
                and s["book"] not in D.GROUPS["poetic"]:
            voiced_outside.append((ref, v["person"], s["text"]))

    OUT.mkdir(parents=True, exist_ok=True)
    for sp in spans:
        sp.setdefault("pieces", 1)
        sp.setdefault("inquit", "")
    allq = sorted(spans + inner + wrapped, key=lambda q: (q["first"], q["level"]))
    cols = ["id", "level", "parent", "speaker", "speaker_hebrew", "alt_speaker", "divine", "quote_type", "basis", "first", "last", "from", "to", "start_fit",
            "end_fit", "pieces", "inquit"]
    with open(OUT / "quotations.tsv", "w", encoding="utf-8") as fh:
        fh.write("# Hebrew speaker layer (steps 1-2): Clear's quotation spans (CC BY 4.0) on MACULA's Hebrew words, with the quotations\n")
        fh.write("# nested inside them from the clause layout's speech structure (basis 'layout'; speaker: the outer speaker for an 'I' inquit,\n")
        fh.write("# speaker_hebrew: the inquit's subject as MACULA lemmas)\n")
        fh.write("\t".join(cols) + "\n")
        for q in allq:
            fh.write("\t".join(str(q.get(c, "")) for c in cols) + "\n")
    (OUT / "segments").mkdir(exist_ok=True)
    by_book = collections.defaultdict(list)
    for i, s in enumerate(segs):
        by_book[s["book"]].append((s, innermost[i], seg_q[i][1], level[i] if seg_q[i][0] else 0, frame[i]))
    for book, rows in by_book.items():
        with open(OUT / "segments" / f"{book}.tsv", "w", encoding="utf-8") as fh:
            fh.write("chapter\tverse\tseg\tclause_key\tquotation\tlevel\tspeaker\tshare\tframe\n")
            for s, q, share, lv, fr in rows:
                fh.write(f"{s['chapter']}\t{s['verse']}\t{s['seg']}\t{s['clause_key']}\t{q['id'] if q else ''}\t{lv}\t"
                         f"{q['speaker'] if q else ''}\t{share:.2f}\t{fr}\n")
    frames_inside = frames_agree + frames_disagree

    # check: the outer speakers against Glyssen's characters for the quotation's first verse (Hebrew numbering -> English)
    gcheck, gmiss = collections.Counter(), []
    for sp in spans:
        b, cv = sp["from"].split(" ")
        c, v = (int(x) for x in cv.split(":"))
        names = set()
        for r in vrsmap.to_eng((b, c, v), "org") or [(b, c, v)]:
            names |= chars.get(tuple(r)[:3], set())
        if not names:
            gcheck["verse not in Glyssen"] += 1
        elif sp["speaker"] in names:
            gcheck["listed"] += 1
        elif any(sp["speaker"] in n.split("/") or n in sp["speaker"].split("/") for n in names):
            gcheck["listed in a group"] += 1
        else:
            gcheck["not listed"] += 1
            gmiss.append((sp["from"], sp["speaker"], "Glyssen: " + "; ".join(sorted(n for n in names if not n.startswith("narrator"))[:4])))

    fit = collections.Counter((sp["start_fit"], sp["end_fit"]) for sp in spans)
    in_q = sum(1 for sp, _ in seg_q if sp)
    split = sum(1 for sp, share in seg_q if sp and share < 1)
    lines = ["# Hebrew speaker layer: report", "",
             f"- quotations: {len(spans)}; clause segments: {len(segs)}, of them in a quotation: {in_q} ({100 * in_q / max(1, len(segs)):.1f}%),"
             f" partly: {split}",
             "- edges: " + ", ".join(f"start {a} / end {b}: {n}" for (a, b), n in fit.most_common()),
             f"- refinement 1, quotations moved to start after their own inquit: {fixed_start}",
             "- refinement 2, edges inside a segment: " + ", ".join(f"{k} {v}" for k, v in snapped.items()),
             f"- refinement 3, pieces of one speech joined (same speaker, nothing between but a speaking formula): {merged}",
             f"- refinement 4, quotations from the layout where Clear has none (narrative books, with a first- or second-person verb): {added}",
             f"- refinement 5, songs or speeches without any quotation (three or more verses in the first or second person): {songs}",
             f"- refinement 6, quotations that ended on an inquit end before it: {split}",
             f"- corrections applied (resources/speaker_layer/corrections.tsv): {applied}",
             f"- quotations without a verb of saying, 'saying' or a speaking formula in the three segments before: {len(no_inquit)}",
             f"- third-person wayyiqtols of saying inside a quotation (an inner quotation, or the quotation runs too far): {len(inner_inquits)}",
             f"- other third-person wayyiqtols inside a quotation, outside the books of poems: {len(frames_inside)}; the layout also has them in a"
             f" speech (a story the speaker tells): {len(frames_agree)}; not (the sources disagree): {len(frames_disagree)}",
             f"- nested quotations from the layout: {len(inner)} (level 2: {sum(q['level'] == 2 for q in inner)}, deeper:"
             f" {sum(q['level'] > 2 for q in inner)}); with a speaker: {sum(bool(q['speaker'] or q['speaker_hebrew']) for q in inner)}"
             f" (named: {sum(q['speaker'] not in ('', '(the one addressed)', '(they)', '(he/she)') for q in inner)}, a Hebrew subject only: "
             f"{sum(bool(q['speaker_hebrew']) and q['speaker'] in ('', '(they)', '(he/she)', '(the one addressed)') for q in inner)}, 'you': {sum(q['speaker'] == '(the one addressed)' for q in inner)},"
             f" only in the verb: {sum(q['speaker'] in ('(they)', '(he/she)') for q in inner)}); of them opened by a messenger formula"
             f" inside a quotation: {messenger}",
             f"- relayed messages (a messenger formula before a quotation: the formula level 1, the sender's words level 2): {relayed};"
             f" psalms opened by an inquit in their title: {titled}",
             f"- frame (a psalm is its psalmist's speech, a field, not a level): {sum(1 for f in frame if f)} segments;"
             f" titles naming a person: {len(frame_of)}",
             f"- segments, Clear quotation / layout speech: both {agree[(True, True)]}, neither {agree[(False, False)]}, Clear only"
             f" {agree[(True, False)]}, layout only {agree[(False, True)]}; agreement"
             f" {100 * (agree[(True, True)] + agree[(False, False)]) / max(1, len(segs)):.1f}%",
             f"- speakers against Glyssen's characters of the quotation's first verse (sha256 {glyssen_sha[:12]}): "
             + ", ".join(f"{k} {v}" for k, v in gcheck.most_common()),
             "- layout speech without a Clear quotation, by book: " + ", ".join(f"{b} {n}" for b, n in layout_only.most_common(10)),
             f"- first- or second-person finite verbs outside any quotation, in the narrative books: {len(voiced_outside)}", ""]
    for title, rows in (("Quotations without an inquit before them", no_inquit), ("Wayyiqtols of saying inside a quotation", inner_inquits),
                        ("Third-person wayyiqtols inside a quotation where the layout has no speech (sources disagree)", frames_disagree),
                        ("Third-person wayyiqtols inside a quotation that the layout has in a speech too", frames_agree),
                        ("First/second person outside quotations (narrative books)", voiced_outside),
                        ("Speakers Glyssen doesn't list for the verse", gmiss)):
        lines += [f"## {title} ({len(rows)})", ""] + [f"- {a} [{b}] {c}" for a, b, c in rows[:60]] + [""]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:23]))


if __name__ == "__main__":
    main()
