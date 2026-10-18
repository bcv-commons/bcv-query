"""Build the Hebrew speaker layer (dataset bcv-commons/hebrew-speaker-layer): the baseline and its nesting.

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
from macula import speaker_votes  # noqa: E402

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
                if hit is None and any(D._n(x["lemma"]) == D.MELEK for x in toks):     # "מֶלֶךְ אַשּׁוּר": Glyssen's "…, king of Assyria"
                    hit = next((c for c in sorted(cands) if f"king of {name}" in c), f"king of {name}")
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
    frame_fixed: dict = {}                        # (book number, chapter) -> the frame a correction sets ("" for none)
    sender_last: dict = {}                        # a relayed message's formula (first word) -> the last word of the sender's words
    if corr_path.exists():
        with open(corr_path, encoding="utf-8") as fh:
            corr = list(csv.DictReader((line for line in fh if not line.startswith("#")), delimiter="\t"))
        by_first = {sp["first"]: sp for sp in spans}
        for c in corr:
            if c["field"] == "sender_last" and c.get("reason"):
                sender_last[c["first"]] = c["value"]
                applied += 1
                continue
            if c["field"] == "frame" and c.get("reason"):
                frame_fixed[(c["first"][:2], int(c["first"][2:5]))] = c["value"]   # the chapter that starts with this word
                applied += 1
                continue
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

    # refinement 7: Glyssen's "Implicit" pieces are one speech: where a quotation touches the one before it (no segment between them, no
    # inquit) and carries a voice implied in that speech (quote type "Implicit"; or one added from the layout after an Implicit piece),
    # it is part of the earlier one, whose speaker keeps the speech.
    # Moses' speeches in Deuteronomy alternate between Moses and God verse by verse in the source (the Decalogue, Deut 5:6-21; God's
    # words in 3:26 and in the Song, 32:41); as one speech of Moses, the words of God in it are nested by the translations' votes below
    implicit = 0
    for i in range(1, len(segs)):
        a, b = seg_q[i - 1][0], seg_q[i][0]
        if a is None or b is None or a is b or segs[i]["book"] != segs[i - 1]["book"]:
            continue
        if b["quote_type"] not in ("Implicit", "layout only") or (b["quote_type"] == "layout only" and a["quote_type"] != "Implicit"
                                                                   and not a.get("_implicit")) \
                or a["quote_type"] not in ("Normal", "Implicit", "layout only") or is_inquit(segs[i]):
            continue
        j = i
        while j < len(segs) and seg_q[j][0] is b:
            seg_q[j] = (a, seg_q[j][1])
            j += 1
        a["last"], a["to"], a["end_fit"] = b["last"], b["to"], b["end_fit"]
        a["pieces"], a["_implicit"] = a.get("pieces", 1) + b.get("pieces", 1), True
        spans.remove(b)
        implicit += 1

    # the translations' votes (macula/speaker_votes.py): within a quotation, a word is nested in a translation when its quotation depth
    # there is greater than the translation's usual depth over the quotation's first three segments (the absolute depth is the
    # translation's convention); a segment's vote is the share of translations that nest its words, where five or more have them
    votes, vote_shas = speaker_votes.depths(con)

    def seg_votes(idx: list[int]) -> dict[int, float]:
        base = {}
        for t, d in votes.items():
            ds = [d[w] for i in idx[:3] for w in segs[i]["words"] if w in d]
            if ds:
                c = collections.Counter(ds)
                base[t] = min(c, key=lambda x: (-c[x], x))
        out = {}
        for i in idx:
            fr = []
            for w in segs[i]["words"]:
                vs = [votes[t][w] > b for t, b in base.items() if w in votes[t]]
                if len(vs) >= 5:
                    fr.append(sum(vs) / len(vs))
            if fr:
                out[i] = sum(fr) / len(fr)
        return out

    def opens_speech(iq: dict | None) -> bool:     # the line a nested stretch hangs on introduces speech
        return bool(iq) and (saying(iq) or is_inquit(iq) or is_messenger(iq))

    def is_messenger(sg: dict) -> bool:
        return any(D._n(tok[w]["lemma"]) == D.KO for w in sg["words"][:3] if w in tok) and any(
            w in tok and tok[w]["class"] == "verb" and D._strong(tok[w]) in D.SAY and tok[w]["wtype"] == "qatal" for w in sg["words"])

    # nesting: inside a quotation, a stretch where the layout stands a speech level deeper than at the quotation's start is a quotation
    # inside it, opened by the clause its first line hangs on as speech (the inquit). A stretch is kept when that line introduces
    # speech (a verb of saying, "לֵאמֹר", a messenger formula) or when most translations nest it too; otherwise it is the layout's
    # depth inside one speech (a vocative "בֶּן־אָדָם", a "כִּי" clause of the same saying: Ezek 33:10, 2 Sam 5:6) and is not a
    # quotation. Where the translations nest its start and then, for two segments or more, clearly not, it ends there (1 Kgs 2:43,
    # 2 Kgs 9:3, Neh 6:7: the quoted words end and the speaker goes on)
    def iq_of(i: int) -> dict | None:
        k = segs[i]["clause_key"]
        inquit = par.get(k) if rel.get(k) == "speech" else None
        if inquit is None:
            iq = inquit_of(k)
        else:
            iq = segs[first_seg[inquit]] if inquit in first_seg else None
            if iq and len(iq["words"]) <= 3 and any(D._strong(tok[w]) in D.SAY_INF and tok[w]["wtype"] == "infinitive construct"
                                                     for w in iq["words"] if w in tok) and par.get(inquit) in first_seg:
                iq = segs[first_seg[par[inquit]]]
        return iq
    kept_layout = collections.Counter()
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
        sv = seg_votes(idx)
        sp["_votes"] = sv
        p = 0
        while p < len(idx):
            prev = level[idx[p - 1]] if p else 1
            if level[idx[p]] <= prev:
                p += 1
                continue
            delta, run = level[idx[p]] - prev, [p]
            while run[-1] + 1 < len(idx) and level[idx[run[-1] + 1]] >= level[idx[p]]:
                run.append(run[-1] + 1)
            got = [sv[idx[x]] for x in run if idx[x] in sv]
            supported = bool(got) and sum(got) / len(got) >= 0.5
            opener = opens_speech(iq_of(idx[p])) or (idx[p] > 0 and opens_speech(segs[idx[p] - 1]))
            if not supported and not opener:
                for x in run:
                    level[idx[x]] -= delta
                kept_layout["dropped (no speech opener, no translation support)"] += 1
                continue
            kept_layout["kept: " + ("speech opener and translations" if supported and opener else "speech opener" if opener else "translations")] += 1
            if sv.get(idx[p], 0) >= 0.5:
                last = max(x for x in run if sv.get(idx[x], 0) >= 0.5)
                tail = [x for x in run if x > last]
                if len(tail) >= 2 and all(idx[x] in sv and sv[idx[x]] < 0.2 for x in tail[:2]):
                    for x in tail:
                        level[idx[x]] -= delta
                    kept_layout["ended where the translations end it"] += 1
            p = run[-1] + 1
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

    # nesting the translations see and the Hebrew structure doesn't mark: inside a quotation, a stretch at the quotation's own level that
    # most translations nest is a quotation inside it (a saying quoted in a speech, "אַתָּה אָמַרְתָּ אֲדֹנִיָּהוּ יִמְלֹךְ", 1 Kgs 1:24;
    # God's words in Moses' speeches, Deut 1:35, 5:6-21; a letter, Ezra 5:7-17; the vision's voice, Job 4:17-21). Speaker: from an
    # inquit line right before it, else the one character other than the outer speaker that Glyssen gives for its first verse
    def glyssen_other(i: int, outer: str) -> str:
        cands = set()
        for r in vrsmap.to_eng((segs[i]["book"], segs[i]["chapter"], segs[i]["verse"]), "org") or [(segs[i]["book"], segs[i]["chapter"], segs[i]["verse"])]:
            cands |= chars.get(tuple(r)[:3], set())
        other = {c for c in cands if c != outer and not c.startswith("narrator")}
        return next(iter(other)) if len(other) == 1 else ""
    spine = SHORESH / "macula" / "macula-spine.db"            # MACULA's participant references (built by the spine; optional here)
    sref = sqlite3.connect(f"file:{spine}?mode=ro", uri=True) if spine.exists() else None

    def referent_speaker(a: int, b: int) -> str:   # "I" in the quotation, through MACULA's reference chain to a name or the divine name
        if sref is None:
            return ""
        for w in (w for x in range(a, b + 1) for w in segs[x]["words"]):
            if person.get(w) != "first":
                continue
            k, seen = w, set()
            while k not in seen:
                seen.add(k)
                r = sref.execute("SELECT tgt_key FROM refs WHERE src_key=? AND kind IN ('participantref','subjref')", (k,)).fetchone()
                if r is None:
                    break
                k = r[0]
            t = tok.get(k)
            if k == w or t is None:
                continue
            if D._strong(t) in D.DIVINE:
                return "God"
            st = D._strong(t)
            if t["wtype"] == "proper" and st.isdigit() and names.get(f"H{int(st):04d}"):
                return names[f"H{int(st):04d}"]
        return ""
    voted = 0
    for sp in spans:
        sv = sp.get("_votes") or {}
        idx = [i for i in range(order[sp["first"]], order[sp["last"]] + 1) if seg_q[i][0] is sp]
        p = 1
        while p < len(idx):
            if level[idx[p]] != 1 or sv.get(idx[p], 0) < 0.5:
                p += 1
                continue
            run = [p]
            while run[-1] + 1 < len(idx) and level[idx[run[-1] + 1]] == 1 and sv.get(idx[run[-1] + 1], 0) >= 0.5:
                run.append(run[-1] + 1)
            a, b = idx[run[0]], idx[run[-1]]
            iq = segs[a - 1] if level[a - 1] >= 1 and (saying(segs[a - 1]) or is_inquit(segs[a - 1])) else None
            if iq and not verb(iq) and a >= 2 and level[a - 2] >= 1:
                iq = segs[a - 2]                                # "לֵאמֹר": the speaker is in the line it belongs to
            v = verb(iq) if iq else None
            who = sp["speaker"] if v and v["person"] == "first" else (english_speaker(iq) if iq else "")
            if not who and v and v["person"] == "second":
                who = "(the one addressed)"
            if not who:
                who = glyssen_other(a, sp["speaker"])
            if not who:
                who = referent_speaker(a, b)
            if not who and v and v["person"] == "third" and not subject_words(iq):
                who = "(they)" if v.get("number") == "plural" else "(he/she)"   # the subject is only in the verb
            voted += 1
            q = {"id": f"{sp['id']}.t{voted}", "speaker": who, "speaker_hebrew": subject_words(iq) if iq else "", "level": 2, "parent": sp["id"],
                 "first": segs[a]["first"], "last": segs[b]["last"], "from": f"{segs[a]['book']} {segs[a]['chapter']}:{segs[a]['verse']}",
                 "to": f"{segs[b]['book']} {segs[b]['chapter']}:{segs[b]['verse']}", "inquit": iq["text"] if iq else "", "alt_speaker": "",
                 "divine": "Y" if who == "God" else "", "quote_type": "nested", "basis": "translations", "start_fit": "segment start",
                 "end_fit": "segment end", "pieces": 1}
            inner.append(q)
            for x in run:
                level[idx[x]], innermost[idx[x]] = 2, q
            p = run[-1] + 1

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
    # A speaker who tells messengers what to say ("אִמְרוּ־נָא אֶל־חִזְקִיָּהוּ כֹּה־אָמַר הַמֶּלֶךְ הַגָּדוֹל", Isa 36:4, 2 Kgs 18:19) speaks
    # the command line at level 1, the formula is what is to be said (level 2), and the sender's words are inside that (level 3). In
    # the prophets the rule applies to a sender who is not God (the ordinary "כֹּה אָמַר יְהוָה" opens an oracle there).
    prophet_books = D.GROUPS["poetic"] - D.GROUPS["poems"]
    relayed = repeated = commanded = 0
    for f in range(1, len(segs) - 1):
        if not is_messenger(segs[f]) or seg_q[f + 1][0] is None:
            continue
        if not (narrative_book(segs[f]["book"]) or (segs[f]["book"] in prophet_books and english_speaker(segs[f]) != "God")):
            continue
        lq = seg_q[f][0]
        if lq is not None:                         # a quotation the layout added that only carries the command and the formula
            if lq["basis"] != "layout" or lq["last"] != segs[f]["last"] or seg_q[f + 1][0] is lq:
                continue
            for y in range(order[lq["first"]], f + 1):
                seg_q[y], level[y], innermost[y] = (None, 0.0), 0, None
            spans.remove(lq)
            inner[:] = [q for q in inner if not q["id"].startswith(lq["id"] + ".")]
        c0 = f
        while c0 > 0 and seg_q[c0 - 1][0] is None and segs[c0 - 1]["verse"] == segs[f]["verse"] and (v0 := verb(segs[c0 - 1])) \
                and v0["form"] == "imperative" and saying(segs[c0 - 1]):
            c0 -= 1                                # the command to say it, in the same verse
        frame_seg = next((segs[x] for x in range(c0 - 1, max(-1, c0 - 4), -1) if english_speaker(segs[x]) or verb(segs[x])), None)
        who = english_speaker(frame_seg) if frame_seg else ""
        sender = english_speaker(segs[f]) or ""
        # the sender's words run on through the quotations that follow without a break (a stop at the sender named in the third
        # person failed: God names himself in the third person in his own speech, Josh 24:7)
        last, x = f + 1, f + 1
        while x + 1 < len(segs) and seg_q[x + 1][0] is not None and (segs[x + 1]["book"], segs[x + 1]["chapter"]) == (segs[f]["book"], segs[f]["chapter"]):
            x += 1
        # where the sender's words end before the quoted stretch does, a hand correction says so (field sender_last, keyed on the
        # formula's first word: Josh 24:14-15 is Joshua's own appeal). A verse-initial "וְעַתָּה" is no signal: in Judg 11:23, 2 Chr
        # 21:15 and 32:15 the sender's words go on after it (bsb-add-books, speaker layer v0.6)
        end_key = sender_last.get(segs[f]["first"])
        stop = next((y + 1 for y in range(f + 1, x + 1) if end_key in segs[y]["words"]), None) if end_key else None
        if stop is not None and stop > x:
            stop = None
        if stop is not None:
            for y in range(stop, x + 1):
                seg_q[y] = (None, 0.0)
            for q in {id(seg_q[y][0]): seg_q[y][0] for y in range(f + 1, stop) if seg_q[y][0]}.values():
                if q["last"] >= segs[stop]["first"]:
                    q["last"], q["to"] = segs[stop - 1]["last"], f"{segs[stop - 1]['book']} {segs[stop - 1]['chapter']}:{segs[stop - 1]['verse']}"
            spans[:] = [q for q in spans if q["first"] < segs[stop]["first"] or q["first"] > segs[x]["last"]]
        last = x
        pieces = {id(seg_q[y][0]): seg_q[y][0] for y in range(f + 1, last + 1) if seg_q[y][0] is not None}
        for q in pieces.values():
            if sender:
                q["speaker"] = sender             # the sender's words, whatever voice FCBH cast for them
        if not who and frame_seg and (v := verb(frame_seg)):
            who = "(they)" if v.get("number") == "plural" else "(he/she)"
        if c0 < f:
            w = wrap(f, x, "(the one addressed)", segs[c0], "relayed message")
            wrap(c0, x, who, frame_seg, "commanded message")
            commanded += 1
        else:
            w = wrap(f, x, who, frame_seg, "relayed message")
        # a messenger formula again inside the message ("כִּי־כֹה אָמַר יְהוָה", 2 Kgs 3:17) is the messenger's own line, at level 1; the
        # sender's words go on after it at level 2
        for y in range(f + 2, x + 1):
            if is_messenger(segs[y]) and level[y] >= 2:
                base = level[y]
                level[y], innermost[y] = 1, w
                repeated += 1
                for z in range(y + 1, x + 1):      # the layout's own speech level under this formula is the message's level 2 already
                    if level[z] > base:
                        level[z] -= 1
                        if innermost[z] is not None and innermost[z] is not w:
                            innermost[z]["level"] = level[z]
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
    # a first-person account (the memoirs of Ezra and Nehemiah, Daniel's visions): a chapter outside the poetic books, in a book whose
    # narrator speaks in the first person, where most wayyiqtols outside quotations are in the first person: its frame is the narrator
    # ("narrator (I)"); a prayer or speech inside it then stands one level in from the frame
    narr = collections.defaultdict(collections.Counter)
    for i, sg in enumerate(segs):
        if sg["book"] in D.GROUPS["first_person_narrator"] and sg["book"] not in D.GROUPS["poetic"] and seg_q[i][0] is None:
            v = verb(sg)
            if v and v["form"] == "wayyiqtol":
                narr[(sg["book"], sg["chapter"])][v["person"]] += 1
    memoir_frame = {k: "narrator (I)" for k, c in narr.items() if c["first"] > c["third"]}
    frame = [""] * len(segs)
    for i, sg in enumerate(segs):
        if sg["book"] in D.GROUPS["frame_poems"] and (sg["book"], sg["chapter"]) not in titled_chapters:
            frame[i] = frame_of.get((sg["book"], sg["chapter"]), "Psalmist")
        if not frame[i] and memoir_frame.get((sg["book"], sg["chapter"])):
            frame[i] = memoir_frame[(sg["book"], sg["chapter"])]
        fixed = frame_fixed.get((sg["first"][:2], sg["chapter"]))
        if fixed is not None:
            frame[i] = fixed

    # the prophets: an oracle is God's speech from the line after a divine messenger formula ("כֹּה אָמַר יְהוָה") or the word-event
    # formula ("הָיָה דְבַר־יְהוָה אֵלַי") to the next one; its frame is the speaker, as a field, so the levels stay as Clear has them
    def opener(sg: dict) -> str:
        toks = [tok[w] for w in sg["words"] if w in tok]
        if not any(D._strong(t) in D.DIVINE for t in toks):
            return ""
        if is_messenger(sg):
            return "messenger formula"
        if any(t["class"] == "verb" and t["wtype"] in D.FINITE and D._strong(t) in D.BE_VERB for t in toks) \
                and any(D._strong(t) in D.WORD_NOUN for t in toks):
            return "word-event formula"
        return ""
    prophets = D.GROUPS["poetic"] - D.GROUPS["poems"]
    oracle_breaks, opener_of = [], {}
    open_i, fresh = None, False
    for i, sg in enumerate(segs):
        if open_i is not None and segs[open_i]["book"] != sg["book"]:
            open_i = None
        if sg["book"] not in prophets:
            continue
        if kind := opener(sg):
            open_i, opener_of[i], fresh = i, kind, True
            continue
        if open_i is None or (fresh and is_inquit(sg)):          # "saying" right after the formula belongs to the formula
            continue
        fresh = False
        v = verb(sg)
        if seg_q[i][0] is None and v and v["form"] == "wayyiqtol" and v["person"] == "third" and sdepth(sg["clause_key"]) == 0:
            oracle_breaks.append((open_i, i))                       # prose narrative the layout does not have in a speech: the oracle ends
            open_i = None
            continue
        if not frame[i]:
            frame[i] = "God"

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
             f"- nested quotations (from the layout, a messenger formula or the translations' votes): {len(inner)} (level 2: {sum(q['level'] == 2 for q in inner)}, deeper:"
             f" {sum(q['level'] > 2 for q in inner)}); with a speaker: {sum(bool(q['speaker'] or q['speaker_hebrew']) for q in inner)}"
             f" (named: {sum(q['speaker'] not in ('', '(the one addressed)', '(they)', '(he/she)') for q in inner)}, a Hebrew subject only: "
             f"{sum(bool(q['speaker_hebrew']) and q['speaker'] in ('', '(they)', '(he/she)', '(the one addressed)') for q in inner)}, 'you': {sum(q['speaker'] == '(the one addressed)' for q in inner)},"
             f" only in the verb: {sum(q['speaker'] in ('(they)', '(he/she)') for q in inner)}); of them opened by a messenger formula"
             f" inside a quotation: {messenger}",
             f"- refinement 7, touching pieces of a voice implied in the outer speech (Glyssen's Implicit) joined into one speech: {implicit}",
             f"- translations' votes (macula/speaker_votes.py; Clear's alignment-quotations at {speaker_votes.CLEAR_COMMIT[:12]}, BSB tables"
             f" sha256 {vote_shas.get('bsb', '')[:12]}): layout-nested stretches " + ", ".join(f"{k} {v}" for k, v in kept_layout.most_common())
             + f"; quotations nested by the translations alone: {voted}",
             f"- relayed messages (a messenger formula before a quotation: the formula level 1, the sender's words level 2): {relayed};"
             f" repeated formulas inside them back at level 1: {repeated}; of them told to messengers by a speaker (three levels): {commanded}; psalms opened by an inquit in their title: {titled}",
             f"- frame (a psalm is its psalmist's speech, a first-person account its narrator's; a field, not a level): {sum(1 for f in frame if f)} segments;"
             f" titles naming a person: {len(frame_of)}; first-person accounts: {len(memoir_frame)} chapters ("
             + ", ".join(f"{b} {c}" for b, c in sorted(memoir_frame)) + ")",
             f"- oracles in the prophets (frame God from the line after a divine formula to the next one): {len(opener_of)}, of them"
             f" {sum(k == 'messenger formula' for k in opener_of.values())} messenger formulas; {sum(1 for i, f in enumerate(frame) if f == 'God')}"
             f" segments in an oracle; third-person wayyiqtols outside quotations inside an oracle: {len(oracle_breaks)}",
             f"- segments, Clear quotation / layout speech: both {agree[(True, True)]}, neither {agree[(False, False)]}, Clear only"
             f" {agree[(True, False)]}, layout only {agree[(False, True)]}; agreement"
             f" {100 * (agree[(True, True)] + agree[(False, False)]) / max(1, len(segs)):.1f}%",
             f"- speakers against Glyssen's characters of the quotation's first verse (sha256 {glyssen_sha[:12]}): "
             + ", ".join(f"{k} {v}" for k, v in gcheck.most_common()),
             "- layout speech without a Clear quotation, by book: " + ", ".join(f"{b} {n}" for b, n in layout_only.most_common(10)),
             f"- first- or second-person finite verbs outside any quotation, in the narrative books: {len(voiced_outside)}", ""]
    breaks = [(f"{segs[i]['book']} {segs[i]['chapter']}:{segs[i]['verse']}", "", segs[i]["text"]) for _, i in oracle_breaks]
    for title, rows in (("Third-person wayyiqtols outside quotations inside an oracle (the prophet narrates, or the oracle ends)", breaks),
                        ("Quotations without an inquit before them", no_inquit), ("Wayyiqtols of saying inside a quotation", inner_inquits),
                        ("Third-person wayyiqtols inside a quotation where the layout has no speech (sources disagree)", frames_disagree),
                        ("Third-person wayyiqtols inside a quotation that the layout has in a speech too", frames_agree),
                        ("First/second person outside quotations (narrative books)", voiced_outside),
                        ("Speakers Glyssen doesn't list for the verse", gmiss)):
        lines += [f"## {title} ({len(rows)})", ""] + [f"- {a} [{b}] {c}" for a, b, c in rows[:60]] + [""]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:23]))


if __name__ == "__main__":
    main()
