"""Passages for a review pass over the speaker layer: where its own sources disagree or a rule is known to be weak, one passage at a
time, with the evidence laid out (no BHSA; the translations only as quotation depths, numbers).

Kinds of work (bsb-add-books' proposal, v0.8 check):
  split       most translations neither clearly nest nor clearly don't (a vote between 0.35 and 0.65)
  layout      a quotation inside a quotation that only the clause layout gives (the weakest basis)
  oracle      a quotation of God's words the layer made in a prophetic book where the source had none: its start, end and speaker
  parallel    a parallel text (Samuel-Kings // Chronicles, Isa 36-39 // 2 Kgs 18-20, ...) where the layer gives different levels
  notes       unfoldingWord's notes mark a quotation inside a quotation where the layer has none
  unnamed     a quotation inside a quotation without a named speaker

Writes macula/data/speaker-layer/_work/review/: passages/<id>.md (the passage and the question), conventions.md, worklist.tsv.

    python -m macula.speaker_review [--per-kind 8]
    python -m macula.speaker_review --merge [--source agent:<model>:<prompt version>]
        compares the two reviewers' answers (answers-A.jsonl, answers-B.jsonl): the rows both give go to
        resources/speaker_layer/review.tsv (replacing earlier rows of the same source); the passages where they differ are listed in
        _work/review/disagreements.md for a decision
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
LAYER = HERE / "data" / "speaker-layer"
WORK = LAYER / "_work"
OUT = WORK / "review"
TN = HERE.parents[1] / "bcv-RAG" / "ingest" / "_staging" / "door43" / "tn"
MAX_SEGS = 40

QUESTIONS = {
    "split": "The translations split on whether the marked segments are a quotation inside the quotation around them. Is there a "
             "quotation inside a quotation here? If so, where does it start and end, and who speaks it?",
    "layout": "The marked quotation inside a quotation comes from the clause layout alone. Is it a quotation (direct speech, with its "
              "own speaker), and does it start and end in the right place? Who speaks it?",
    "oracle": "The marked quotation of God's words was made by the layer (the source had none). Is the stretch God speaking (in the "
              "first person, or announced by a formula), or the prophet? Does it start and end in the right place?",
    "parallel": "The same words stand in a parallel text (shown below) at other levels or with another speaker. Unless the Hebrew "
                "differs, both should agree. Which is right, and what should change in this passage?",
    "notes": "A translators' note marks a quotation inside a quotation in the marked verse, where the layer has none (with the frame "
             "counted as a level). Is there one? If so, give its start, end and speaker.",
    "unnamed": "The marked quotation inside a quotation has no named speaker. Who speaks it, by the Hebrew (the inquit's subject, the "
               "person of the verbs, who 'I' is)?",
}

CONVENTIONS = """# Conventions for the speaker layer (decided by the project; follow them, don't revisit them)

1. A quotation is direct speech with its own speaker. Indirect speech ("he told them to go", an infinitive after a verb of saying)
   is not a quotation.
2. Levels: 0 is the narrative; a quotation is 1; a quotation inside it 2; and so on.
3. The frame is a field, not a level: a text that is someone's speech from its first line has that person as its frame (a psalm's
   psalmist; a memoir's narrator; a prophetic book's prophet). A reader may count it as one level. Don't change levels to express
   a frame.
4. A prophetic book is its prophet's speech (the frame); God's words in it are always a quotation (level 1 and deeper). Where the
   prophet speaks in his own voice (speaks of God in the third person, prays, laments), that stretch is not God's quotation.
5. Ezekiel and the first-person accounts (Ezra 9, Neh 13, Dan 8-10): the narrator's account is the frame; God's (or anyone's) words
   in it are quotations at level 1.
6. A first-person retelling inside a speech (Moses in Deut 1-3) stays inside the speech; what it quotes is one level deeper.
7. A message someone is told to deliver ("וְאָמַרְתָּ אֲלֵהֶם …", "אִמְרוּ אֶל־…") is a quotation inside the command; its speaker is the
   one who is to say it.
8. A messenger formula ("כֹּה אָמַר X") belongs to the one who says it; X's words after it are one level deeper.
9. Parallel texts take the same levels and speakers unless the Hebrew differs.
10. Speakers: a name where the Hebrew gives one (the inquit's subject; who "I" is); otherwise "(he/she)", "(they)", "(the one
    addressed)". Use the names already used in the passage where they fit.
11. Evidence: decide from the Hebrew. The translations' votes are only a hint (how many of nine translations put the words in
    deeper quotation marks); never use an English translation's text. Do not use BHSA/ETCBC data.
"""


def load_evidence() -> list[dict]:
    return [json.loads(line) for line in open(WORK / "evidence.jsonl", encoding="utf-8")]


def tn_verses() -> set:
    out = set()
    books = {}
    for f in TN.glob("*.md") if TN.exists() else []:
        s = f.read_text(encoding="utf-8")
        if "figs-quotesinquotes" not in s:
            continue
        m = re.search(r"\[(\d+), (\d+)\]", s)
        if m:
            k = m.group(1).zfill(8)
            out.add((int(k[:2]), int(k[2:5]), int(k[5:])))
    return out


def _norm(v: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (v or "").lower())[:14]


def _key(c: dict) -> tuple:
    v = _norm(c.get("value", "")) if c["field"] in ("speaker", "add", "frame") else (c.get("value") or "")
    return (c["field"], c.get("first", ""), v, c.get("last", "") if c["field"] in ("add", "level") else "")


def merge(source: str) -> int:
    ans = {}
    for side in ("A", "B"):
        f = OUT / f"answers-{side}.jsonl"
        ans[side] = {}
        for line in open(f, encoding="utf-8") if f.exists() else []:
            if line.strip():
                r = json.loads(line)
                ans[side].setdefault(r["id"], r)
    ids = [l.split("\t")[0] for l in open(OUT / "worklist.tsv", encoding="utf-8").read().splitlines()[1:]]
    agreed, differ, st = [], [], collections.Counter()
    for pid in ids:
        a, b = ans["A"].get(pid), ans["B"].get(pid)
        if not a or not b:
            st["missing"] += 1
            continue
        ka = {_key(c): c for c in a["changes"]}
        kb = {_key(c): c for c in b["changes"]}
        both = set(ka) & set(kb)
        for k in sorted(both):
            agreed.append((pid, ka[k], kb[k]))
        if set(ka) == set(kb):
            st["agree" if ka else "agree: no change"] += 1
        else:
            st["differ"] += 1
            differ.append((pid, a, b, set(ka) - set(kb), set(kb) - set(ka)))
    path = HERE.parents[1] / "resources" / "speaker_layer" / "review.tsv"
    head = [l for l in open(path, encoding="utf-8").read().splitlines() if l.startswith("#") or l.startswith("first\t")]
    keep = [l for l in open(path, encoding="utf-8").read().splitlines()[len(head):] if l and l.split("\t")[6:7] != [source]]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(head + keep) + "\n")
        for pid, c, c2 in agreed:
            reason = c["reason"].replace("\t", " ").replace("\n", " ")
            conf = c["confidence"] if c["confidence"] == c2["confidence"] else "medium"
            fh.write("\t".join([c["first"], c["field"], c.get("value") or "", f"{reason} [{pid}]", c.get("last") or "",
                                 c.get("parent") or "", source, conf]) + "\n")
    lines = ["# Review pilot: where the two reviewers differ", ""]
    for pid, a, b, only_a, only_b in differ:
        lines += [f"## {pid}", ""]
        for side, ans_, only in (("A", a, only_a), ("B", b, only_b)):
            lines.append(f"**Reviewer {side}:** " + (ans_["no_change_reason"] if not ans_["changes"] else ""))
            for c in ans_["changes"]:
                mark = " (only this reviewer)" if _key(c) in only else ""
                lines.append(f"- {c['field']} {c['first']} → {c.get('value')} {c.get('last') or ''}{mark}: {c['reason']} ({c['confidence']})")
            lines.append("")
    (OUT / "disagreements.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    conv = [c for side in ans.values() for r in side.values() for c in r.get("new_conventions", [])]
    (OUT / "new_conventions.md").write_text("\n".join(f"- {c}" for c in conv) + "\n", encoding="utf-8")
    print(dict(st), f"; {len(agreed)} agreed rows -> {path}; {len(differ)} passages differ -> {OUT / 'disagreements.md'};"
          f" {len(conv)} proposed conventions")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--per-kind", type=int, default=8)
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--source", default="agent:claude-opus-5-5:review-v1")
    a = ap.parse_args()
    if a.merge:
        return merge(a.source)
    ev = load_evidence()
    quotes = {r["id"]: r for r in csv.DictReader((l for l in open(LAYER / "quotations.tsv", encoding="utf-8") if not l.startswith("#")),
                                                  delimiter="\t")}
    seg_of_word: dict = {}
    for e in ev:
        seg_of_word[e["first"]] = e["i"]
    last_word = {}
    import sqlite3
    import trees_macula
    con = sqlite3.connect(f"file:{trees_macula.trees_path()}?mode=ro", uri=True)
    layout = HERE / "data" / "clause-layout" / "clauses"
    for e in ev:
        pass
    for f in sorted(layout.glob("*/*.jsonl")):
        for line in open(f, encoding="utf-8"):
            c = json.loads(line)
            last_word[c["first"]] = c["last"]
    book_num = {e["book"]: int(e["first"][:2]) for e in ev}

    def ref(e: dict) -> str:
        return f"{e['book']} {e['chapter']}:{e['verse']}"

    # candidates per kind: (anchor segment index, anchor end index, extra)
    cand = collections.defaultdict(list)
    for e in ev:                                                 # split votes
        if e["votes"] and e["level"] >= 1 and e["level"] <= 3 and 0.35 <= e["votes"][e["level"] - 1] <= 0.65:
            cand["split"].append((e["i"], e["i"], ""))
    for q in quotes.values():
        i = seg_of_word.get(q["first"])
        if i is None:
            continue
        j = max(i, seg_of_word.get(q["last"], i) or i)
        for x in range(i, min(i + 60, len(ev))):
            if ev[x]["first"] <= q["last"]:
                j = x
        if q["basis"] == "layout" and q["level"] not in ("", "1"):
            cand["layout"].append((i, j, q["id"]))
        if q["basis"] == "oracle":
            cand["oracle"].append((i, j, q["id"]))
        if q["level"] not in ("", "1") and (not q["speaker"] or q["speaker"].startswith("(")):
            cand["unnamed"].append((i, j, q["id"]))
    skip = re.compile(r"^EXO (2[5-9]|3[0-9])|^EXO 20|^DEU 5")
    seen_par = set()
    for r in csv.DictReader(open(LAYER / "parallels.tsv", encoding="utf-8"), delimiter="\t"):
        if skip.match(r["passage_a"]) or skip.match(r["passage_b"]) or int(r["words"]) < 4:
            continue
        b, cv = r["passage_a"].split(" ")
        c, v = map(int, cv.split(":"))
        i = next((e["i"] for e in ev if e["book"] == b and e["chapter"] == c and e["verse"] == v), None)
        if i is None or (b, c) in seen_par:
            continue
        seen_par.add((b, c))
        cand["parallel"].append((i, i, f"{r['passage_a']} // {r['passage_b']}"))
    tn = tn_verses()
    by_verse = collections.defaultdict(list)
    for e in ev:
        by_verse[(book_num[e["book"]], e["chapter"], e["verse"])].append(e)
    for v in sorted(tn):
        es = by_verse.get(v)
        if es and not any(e["level"] >= 2 or (e["frame"] and e["level"] >= 1) for e in es):
            cand["notes"].append((es[0]["i"], es[-1]["i"], ""))

    def spread(xs: list, n: int) -> list:
        xs = sorted(xs)
        return [xs[int(k * len(xs) / n)] for k in range(n)] if len(xs) > n else xs

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "passages").mkdir(exist_ok=True)
    (OUT / "conventions.md").write_text(CONVENTIONS, encoding="utf-8")
    work = []
    for kind in QUESTIONS:
        for n, (i, j, extra) in enumerate(spread(cand[kind], a.per_kind), 1):
            lo = i
            while lo > 0 and i - lo < 15 and not (ev[lo]["level"] == 0 and ev[lo]["inquit"]) and ev[lo - 1]["book"] == ev[i]["book"]:
                lo -= 1
            hi = j
            while hi + 1 < len(ev) and hi - lo < MAX_SEGS - 1 and ev[hi + 1]["book"] == ev[i]["book"] and (
                    ev[hi + 1]["level"] >= max(1, ev[i]["level"] - 1) or hi - j < 3):
                hi += 1
            pid = f"{kind}-{n:02d}"
            lines = [f"# Passage {pid}: {ref(ev[lo])} to {ref(ev[hi])}", "", f"Kind: {kind}. {QUESTIONS[kind]}", ""]
            if extra:
                lines += [f"Marked: {extra}", ""]
            lines += [f"The marked segments are {ref(ev[i])} (segment {ev[i]['i']}) to {ref(ev[j])} (segment {ev[j]['i']}).", "",
                      "Columns: segment, verse, first word key, last word key, level, quotation, speaker, frame, basis, votes (share of",
                      "the translations nesting it at least 1/2/3 levels deeper than the quotation's start), main verb, subject, who",
                      "'I' is (MACULA's references), marks (inquit, messenger formula, word-event/oracle opener), Glyssen's characters",
                      "for the verse, Hebrew.", "",
                      "| seg | verse | first | last | lvl | quotation | speaker | frame | basis | votes | verb | subject | I= | marks | glyssen | Hebrew |",
                      "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
            for x in range(lo, hi + 1):
                e = ev[x]
                mark = ">>" if i <= x <= j else ""
                marks = ",".join(k for k in ("inquit", "messenger", "opener") if e[k])
                lines.append(f"| {mark}{x} | {ref(e)} | {e['first']} | {last_word.get(e['first'], '')} | {e['level']} | {e['quotation']} | "
                             f"{e['speaker']} | {e['frame']} | {e['basis']} | {'/'.join(map(str, e['votes'])) if e['votes'] else ''} | "
                             f"{e['verb']} | {e['subject']} | {e['i_is']} | {marks} | {'; '.join(e['glyssen'])} | {e['text']} |")
            qs = sorted({ev[x]["quotation"] for x in range(lo, hi + 1) if ev[x]["quotation"]})
            if qs:
                lines += ["", "Quotations in the passage:", "", "| id | level | parent | speaker | basis | first | last | from | to |", "|---|---|---|---|---|---|---|---|---|"]
                for qid in qs:
                    q = quotes.get(qid, {})
                    lines.append(f"| {qid} | {q.get('level', '')} | {q.get('parent', '')} | {q.get('speaker', '')} | {q.get('basis', '')} | "
                                 f"{q.get('first', '')} | {q.get('last', '')} | {q.get('from', '')} | {q.get('to', '')} |")
            if kind == "parallel":
                pb = extra.split(" // ")[1]
                b, cv = pb.split(" ")
                c, v = map(int, cv.split(":"))
                pe = [e for e in ev if e["book"] == b and e["chapter"] == c and abs(e["verse"] - v) <= 2]
                lines += ["", f"The parallel text ({b} {c}:{v - 2}-{v + 2}):", "", "| seg | verse | first | lvl | quotation | speaker | Hebrew |", "|---|---|---|---|---|---|---|"]
                for e in pe:
                    lines.append(f"| {e['i']} | {ref(e)} | {e['first']} | {e['level']} | {e['quotation']} | {e['speaker']} | {e['text']} |")
            (OUT / "passages" / f"{pid}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            work.append((pid, kind, ref(ev[i]), ref(ev[lo]), ref(ev[hi]), extra))
    with open(OUT / "worklist.tsv", "w", encoding="utf-8") as fh:
        fh.write("id\tkind\tanchor\tfrom\tto\tnote\n")
        for w in work:
            fh.write("\t".join(w) + "\n")
    print({k: len(v) for k, v in cand.items()}, "->", len(work), "passages in", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
