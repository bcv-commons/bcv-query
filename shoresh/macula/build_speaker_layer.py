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

    def subject_words(sg: dict) -> str:            # the Hebrew subject of a segment's clause, its nouns and names as lemmas
        cls = {tok[w]["cl"] for w in sg["words"] if w in tok and tok[w]["cl"] is not None}
        out = [tok[w]["lemma"] for w in sg["words"] if w in tok and tok[w]["role"] == "s" and tok[w]["class"] in ("noun", "pron")]
        for c in cls:
            for lo, hi in subj_of.get(c, []):
                out += [by_seq[q]["lemma"] for q in range(lo, hi + 1) if q in by_seq and by_seq[q]["class"] in ("noun", "pron")]
        return " ".join(dict.fromkeys(out))
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
    # refinement 2: pieces of one speech: the next span of the same speaker with nothing between them but a speaking formula
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

    # the work lists
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
    allq = sorted(spans + inner, key=lambda q: (q["first"], q["level"]))
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
        by_book[s["book"]].append((s, innermost[i], seg_q[i][1], level[i] if seg_q[i][0] else 0))
    for book, rows in by_book.items():
        with open(OUT / "segments" / f"{book}.tsv", "w", encoding="utf-8") as fh:
            fh.write("chapter\tverse\tseg\tclause_key\tquotation\tlevel\tspeaker\tshare\n")
            for s, q, share, lv in rows:
                fh.write(f"{s['chapter']}\t{s['verse']}\t{s['seg']}\t{s['clause_key']}\t{q['id'] if q else ''}\t{lv}\t"
                         f"{q['speaker'] if q else ''}\t{share:.2f}\n")
    frames_inside = frames_agree + frames_disagree

    fit = collections.Counter((sp["start_fit"], sp["end_fit"]) for sp in spans)
    in_q = sum(1 for sp, _ in seg_q if sp)
    split = sum(1 for sp, share in seg_q if sp and share < 1)
    lines = ["# Hebrew speaker layer: baseline report", "",
             f"- quotations: {len(spans)}; clause segments: {len(segs)}, of them in a quotation: {in_q} ({100 * in_q / max(1, len(segs)):.1f}%),"
             f" partly: {split}",
             "- edges: " + ", ".join(f"start {a} / end {b}: {n}" for (a, b), n in fit.most_common()),
             f"- refinement 1, quotations moved to start after their own inquit: {fixed_start}",
             f"- refinement 2, pieces of one speech joined (same speaker, nothing between but a speaking formula): {merged}",
             f"- quotations without a verb of saying, 'saying' or a speaking formula in the three segments before: {len(no_inquit)}",
             f"- third-person wayyiqtols of saying inside a quotation (an inner quotation, or the quotation runs too far): {len(inner_inquits)}",
             f"- other third-person wayyiqtols inside a quotation, outside the books of poems: {len(frames_inside)}; the layout also has them in a"
             f" speech (a story the speaker tells): {len(frames_agree)}; not (the sources disagree): {len(frames_disagree)}",
             f"- nested quotations from the layout: {len(inner)} (level 2: {sum(q['level'] == 2 for q in inner)}, deeper:"
             f" {sum(q['level'] > 2 for q in inner)}); with a speaker: {sum(bool(q['speaker'] or q['speaker_hebrew']) for q in inner)}"
             f" ('I': {sum(q['speaker'] not in ('', '(the one addressed)', '(they)', '(he/she)') for q in inner)}, the inquit's subject: "
             f"{sum(bool(q['speaker_hebrew']) for q in inner)}, 'you': {sum(q['speaker'] == '(the one addressed)' for q in inner)},"
             f" only in the verb: {sum(q['speaker'] in ('(they)', '(he/she)') for q in inner)})",
             f"- segments, Clear quotation / layout speech: both {agree[(True, True)]}, neither {agree[(False, False)]}, Clear only"
             f" {agree[(True, False)]}, layout only {agree[(False, True)]}; agreement"
             f" {100 * (agree[(True, True)] + agree[(False, False)]) / max(1, len(segs)):.1f}%",
             "- layout speech without a Clear quotation, by book: " + ", ".join(f"{b} {n}" for b, n in layout_only.most_common(10)),
             f"- first- or second-person finite verbs outside any quotation, in the narrative books: {len(voiced_outside)}", ""]
    for title, rows in (("Quotations without an inquit before them", no_inquit), ("Wayyiqtols of saying inside a quotation", inner_inquits),
                        ("Third-person wayyiqtols inside a quotation where the layout has no speech (sources disagree)", frames_disagree),
                        ("Third-person wayyiqtols inside a quotation that the layout has in a speech too", frames_agree),
                        ("First/second person outside quotations (narrative books)", voiced_outside)):
        lines += [f"## {title} ({len(rows)})", ""] + [f"- {a} [{b}] {c}" for a, b, c in rows[:60]] + [""]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:14]))


if __name__ == "__main__":
    main()
