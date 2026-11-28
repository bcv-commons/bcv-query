"""Speech inside speech in the Greek New Testament: the quotations inside a quotation of the speaker data.

The speaker data (resources/speaker_quotations) has no quotation inside another: a parable's people, a cited psalm, an angel
whose words Paul reports all stand as the outer speaker's words, said to the outer hearers. Here they are found from the Greek
text, with the translations as the second witness, as the Hebrew speaker layer does (macula/build_speaker_layer.py).

Witness 1, the Greek text. Inside a quotation, a verb of saying (SAYING; not a first person of the present, future or perfect:
"λέγω ὑμῖν" is the speaker's own word to the same hearers, "κἀγὼ εἶπον" reports an earlier speech) and a part of its clause
that follows it and that MACULA's tree gives as a clause or a group of clauses: its object (role o, o2), or a clause that hangs
on it with another role or none (οἱ δὲ δοῦλοι αὐτῷ λέγουσιν · Θέλεις οὖν …). That part is the candidate, from its first word
to its last. Its form: `direct` (a finite verb or no verb of its own), or opened by ὅτι, by a question word, by another word
that makes a clause depend (ἵνα, ὅπως, a relative …), or an infinitive or participle.

Witness 2, the translations. Clear's alignment-quotations files (macula/speaker_votes.py: eight translations; only the word id
and the quotation depth are read, never a word of English) give each Greek word a depth. A translation nests a word when its
depth there is greater than the depth of the quotation's own words in that translation; a word's vote is the share of the
translations that have it and nest it (at least MIN_VOTERS of them). The alignments are now and then one word off, and some
translations set a prayer or a citation as a block without marks, so a vote is a share, not a yes or no. Where a stretch
begins, the depth it is measured against is that of the three words before it (a quotation steps in from the words that lead
to it), and a translation that lacks a word stands it where it stands the word before.

The rule (`find`). A candidate is a quotation when
  - it is an object, direct in form, and at least a third of the translations nest its opening words (PLAIN), or the
    translations do not have its words at all (then the form alone decides; basis `text`);
  - it is an object opened by ὅτι or a question word, and most translations nest its opening (STRONG): ὅτι before direct speech,
    a direct question; a reported one they leave unmarked;
  - it hangs on the verb, is direct in form, and most translations nest its opening (STRONG).
  Its basis is `text+translations`. It ends where the translations stop nesting (a speech of several sentences runs on past the
  verb's own sentence; one the translations close earlier ends there), at the end of the quotation around it at the latest.
Outside these, a stretch of three words or more that most translations nest (LONE at its start) is a quotation too, basis
`translations`, when a verb of saying stands in the eight words before it in its sentence (the tree gives what is said as a
phrase, not a clause: ὁ δὲ εἶπεν · Ἑκατὸν κόρους σίτου; a citation after γέγραπται), or when it opens where a clause opens (a
citation after καὶ πάλιν, a cry with no verb of saying). A stretch that opens inside a clause with no such verb is left. The same is done inside each quotation found, so a quotation in a quotation in a quotation is level 3.

    inner, counts = greek_inner_speech.find(quotes, con)   # per book number: the new quotations (id = first word id, start, end,
                                                           #   level, parent, top, verb, basis, form; `speaker` empty)
    python macula/greek_inner_speech.py measure            # how the two witnesses agree
    python macula/greek_inner_speech.py find               # counts of the quotations found
"""
from __future__ import annotations

import argparse
import bisect
import collections
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

SHORESH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHORESH))

SAYING = {"λέγω", "εἶπον", "φημί", "ἀποκρίνομαι", "λαλέω", "κράζω", "ἐρωτάω", "ἐπερωτάω", "βοάω", "φωνέω", "ἐρῶ", "κελεύω",
          "παραγγέλλω", "ἀνακράζω", "κραυγάζω", "προσεύχομαι", "ἐπιτιμάω", "παρακαλέω", "διαστέλλω", "ὀμνύω", "γράφω", "προφητεύω",
          "μαρτυρέω", "ἐντέλλω", "διδάσκω", "ἀπαγγέλλω", "δέομαι", "ψάλλω", "προσφωνέω", "ἀποφθέγγομαι"}
DEPENDENT = {"ἵνα", "ὅπως", "ὡς", "μήποτε", "ὅς", "ὅσος", "ὅστις", "καθώς", "διότι", "ἐάν", "ὅταν", "ὅτε"}
QUESTION = {"τίς", "πότε", "ποῦ", "πόθεν", "πῶς", "ποῖος", "πόσος", "εἰ"}        # a direct or a reported question: the translations say
FINITE = {"indicative", "subjunctive", "optative", "imperative"}
PAST = {"aorist", "imperfect", "pluperfect"}
MIN_VOTERS, PLAIN, STRONG, ON = 4, 1 / 3, 0.6, 0.5
LONE = 0.6                                                          # the translations alone, at the first word of a stretch
OPENING, MIN_RUN, MAX_LEVEL, LOOK_BACK, BEFORE = 8, 3, 5, 8, 3


def votes(keys: list[str]) -> tuple[dict[str, list[tuple[str, int]]], dict[str, str]]:
    """Greek word key -> (translation, quotation depth) for each translation that has the word (0: the narrator); and the
    files' SHA-256."""
    from macula import speaker_votes as V
    out: dict[str, list[tuple[str, int]]] = collections.defaultdict(list)
    shas, known = {}, set(keys)
    for t in V.CLEAR_VOTERS:
        raw = V._fetch(V.CLEAR_URL.format(commit=V.CLEAR_COMMIT, t=t), V.CACHE / f"alignment-quotations-{t}-{V.CLEAR_COMMIT[:12]}.tsv")
        shas[t] = hashlib.sha256(raw).hexdigest()
        seen = set()
        for line in raw.decode("utf-8").split("\n")[1:]:
            p = line.split("\t", 2)                                  # depth, id, …: the rest is not looked at
            if len(p) < 2 or len(p[1]) != 12 or not p[0].isdigit() or p[1][:2] < "40":
                continue
            k = p[1][:11]                                            # the word id; the twelfth digit is the part
            if k in known and k not in seen and int(p[0]) > 0:
                seen.add(k)
                out[k].append((t, int(p[0]) - 1))
    return out, shas


class Text:
    """MACULA Greek's words and tree, and the translations' depths."""

    def __init__(self, con: sqlite3.Connection):
        self.words = {r["key"]: r for r in con.execute(
            "SELECT w.key, w.seq, w.class, w.lemma, w.parent, w.cl, w.sent, w.role, w.tense, s.person, s.mood FROM words w "
            "LEFT JOIN sp.spine_words s ON s.key=w.key WHERE w.corpus='grc'")}
        self.keys = sorted(self.words)
        self.by_seq = {r["seq"]: k for k, r in self.words.items()}
        self.node = {r["id"]: r for r in con.execute("SELECT id, parent, cls, role, rule, lo, hi FROM nodes WHERE corpus='grc'")}
        self.kids = collections.defaultdict(list)
        for i, r in self.node.items():
            if r["parent"] is not None:
                self.kids[r["parent"]].append(i)
        self.votes, self.vote_sha = votes(self.keys)
        self.local: dict[str, dict[str, int]] = {}
        self.clause_start = set()                                   # the first word of each clause, in the order of the text
        for i, r in self.node.items():
            if r["cls"] == "cl":
                ws = [self.by_seq[s] for s in range(r["lo"], r["hi"] + 1) if s in self.by_seq]
                if ws:
                    self.clause_start.add(min(ws))

    def enter(self, q: dict) -> None:
        """Inside the quotation q, a translation that lacks a word is taken to stand it where it stands the word before (the
        alignments leave words out; a vote that counts only the translations that happen to have a word swings with them)."""
        ws = self.between(q["start"], q["end"])
        by_t: dict[str, dict[str, int]] = collections.defaultdict(dict)
        for k in ws:
            for t, d in self.votes.get(k, ()):
                by_t[t][k] = d
        self.local = {k: {} for k in ws}
        for t, got in by_t.items():
            if len(got) * 2 < len(ws):                              # a translation without half the quotation's words: no voter
                for k, d in got.items():
                    self.local[k][t] = d
                continue
            last = None
            for k in ws:
                last = got.get(k, last)
                if last is not None:
                    self.local[k][t] = last

    def between(self, a: str, b: str) -> list[str]:
        return self.keys[bisect.bisect_left(self.keys, a):bisect.bisect_right(self.keys, b)]

    def span(self, node: int) -> list[str]:
        """the node's words in the order of the text"""
        r = self.node[node]
        return sorted(self.by_seq[s] for s in range(r["lo"], r["hi"] + 1) if s in self.by_seq)

    def holds_clause(self, node: int) -> bool:
        stack = [node]
        while stack:
            n = stack.pop()
            if self.node[n]["cls"] == "cl":
                return True
            stack += self.kids[n]
        return False

    def hanging(self, verb: str) -> list[tuple[int, str]]:
        """the clauses, or groups of clauses, of the verb's clause that follow the verb: (node, `object` or `hangs`)"""
        c, seq = self.words[verb]["cl"], self.words[verb]["seq"]
        if c is None:
            return []
        out, stack = [], list(self.kids[c])
        while stack:
            n = stack.pop()
            r = self.node[n]
            if r["cls"] not in ("cl", None) or not self.holds_clause(n) or r["lo"] <= seq <= r["hi"]:
                if r["cls"] is None and r["role"] is None and r["lo"] <= seq <= r["hi"]:
                    stack += self.kids[n]                           # a group around the verb and its speech
                continue
            if r["hi"] < seq:
                continue
            if r["role"] in ("o", "o2"):
                out.append((n, "object"))
            elif r["cls"] is None and r["role"] is None and not any(self.node[k]["cls"] == "cl" for k in self.kids[n]):
                stack += self.kids[n]
            else:
                out.append((n, "hangs"))
        return sorted(out, key=lambda x: self.node[x[0]]["lo"])

    def base(self, ws: list[str], floor: dict[str, int] | None = None, share: float = 0.05) -> dict[str, int]:
        """per translation, the depth of a quotation's own words: the lowest depth inside a quotation (not the narrator's 0, not
        under the quotation around it) that at least `share` of its words stand at there (a speech may open with one word of its
        own before a citation: Γέγραπται …)"""
        got: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        for k in ws:
            for t, d in self.local.get(k, {}).items():
                if d >= max(1, (floor or {}).get(t, 1)):
                    got[t][d] += 1
        return {t: min(d for d, n in c.items() if n >= max(1, sum(c.values()) * share)) for t, c in got.items()}

    def before(self, start: str, q: dict, base: dict[str, int]) -> dict[str, int]:
        """per translation, where the words stand just before `start` inside the quotation q: the lowest depth of the last
        BEFORE words there, not under the quotation's own. What follows is nested when it stands deeper than that: a quotation
        steps in from the words that lead to it, whatever else the translation nests around both."""
        i = bisect.bisect_left(self.keys, start)
        out = dict(base)
        seen: dict[str, list[int]] = collections.defaultdict(list)
        for k in reversed(self.keys[max(0, i - BEFORE):i]):
            if k < q["start"]:
                break
            for t, d in self.local.get(k, {}).items():
                seen[t].append(d)
        for t, ds in seen.items():
            if t in base:
                out[t] = max(base[t], min(ds))
        return out

    def nested(self, k: str, base: dict[str, int]) -> float | None:
        """the share of the translations that have the word and stand it deeper than the base; None under MIN_VOTERS"""
        v = [(t, d) for t, d in self.local.get(k, {}).items() if t in base]
        if len(v) < MIN_VOTERS:
            return None
        return sum(d > base[t] for t, d in v) / len(v)

    def verb_before(self, k: str, after: str, taken: list[tuple[str, str]]) -> str | None:
        """the nearest verb of saying in the LOOK_BACK words before k, in the same sentence and the same quotation"""
        i = bisect.bisect_left(self.keys, k)
        for x in reversed(self.keys[max(0, i - LOOK_BACK):i]):
            if x <= after or self.words[x]["sent"] != self.words[k]["sent"] or any(a <= x <= b for a, b in taken):
                return None
            if saying(self, x):
                return x
        return None

    def opens_clause(self, k: str, after: str, taken: list[tuple[str, str]]) -> str | None:
        """the first word of a stretch the translations nest from k on: k where a clause opens there, the word before where a
        clause opens there or ὅτι stands before it (the alignments are a word off now and then), else None"""
        if k in self.clause_start:
            return k
        i = bisect.bisect_left(self.keys, k) - 1
        prev = self.keys[i] if i >= 0 else None
        if prev is None or prev <= after or any(a <= prev <= b for a, b in taken):
            return None
        if prev in self.clause_start or (i > 0 and self.words[self.keys[i - 1]]["lemma"] == "ὅτι"):
            return prev
        return None

    def opening(self, ws: list[str], base: dict[str, int]) -> float | None:
        """the mean vote of the first OPENING words the translations can say about"""
        got = [x for x in (self.nested(k, base) for k in ws) if x is not None][:OPENING]
        return sum(got) / len(got) if got else None

    def form(self, obj: int) -> str:
        """`direct`, `ὅτι`, `question`, `dependent`, `infinitive`, `participle`: by the first word and by the verbs of the
        clauses that stand highest in it"""
        ws = self.span(obj)
        lead = self.words[ws[0]]
        if lead["class"] in ("conj", "adv", "ptcl", "pron", "adj"):
            if lead["lemma"] == "ὅτι":
                return "ὅτι"
            if lead["lemma"] in QUESTION:
                return "question"
            if lead["lemma"] in DEPENDENT:
                return "dependent"

        def depth(k: str) -> int:
            n, c = 0, self.words[k]["cl"]
            while c is not None and c != obj:
                n, c = n + 1, self.node[c]["parent"]
            return n
        verbs = [(depth(k), self.words[k]["mood"]) for k in ws if self.words[k]["class"] == "verb" and self.words[k]["mood"]]
        top = [m for d, m in verbs if d == min(x for x, _ in verbs)] if verbs else []
        if top and not any(m in FINITE for m in top):
            return "infinitive" if "infinitive" in top else "participle"
        return "direct"

    def run(self, start: str, limit: str, base: dict[str, int], bar: float) -> tuple[str | None, int]:
        """from `start`, the last word of the stretch the translations nest (one word under the bar between two over it is
        passed over), not past `limit`; and how many of its words they can say about"""
        end, n, miss = None, 0, 0
        for k in self.between(start, limit):
            v = self.nested(k, base)
            if v is None:
                continue
            if v >= bar:
                end, n, miss = k, n + 1, 0
            else:
                miss += 1
                if miss > 1:
                    break
        return end, n


def saying(T: Text, k: str) -> bool:
    w = T.words[k]
    return w["class"] == "verb" and w["lemma"] in SAYING and not (w["person"] == "first" and w["tense"] not in PAST)


def candidates(T: Text, q: dict, base: dict[str, int]) -> list[dict]:  # noqa: C901
    """witness 1 inside the quotation q (start, end), with what witness 2 says of each"""
    out = []
    for k in T.between(q["start"], q["end"]):
        if not saying(T, k):
            continue
        for obj, kind in T.hanging(k):
            ws = [x for x in T.span(obj) if q["start"] < x <= q["end"]]
            if len(ws) < 2 or ws[0] <= k:
                continue
            here = T.before(ws[0], q, base)
            out.append({"verb": k, "start": ws[0], "end": ws[-1], "words": len(ws), "kind": kind, "form": T.form(obj),
                        "opening": T.opening(ws, here), "here": here})
    return out


def accept(c: dict) -> tuple[str, float]:
    """(basis, the bar its words must pass in the translations) for a candidate that is a quotation, else ('', 0)"""
    v = c["opening"]
    if c["kind"] == "object" and c["form"] == "direct":
        if v is None:
            return "text", ON
        return ("text+translations", PLAIN) if v >= PLAIN else ("", 0.0)
    if (c["kind"] == "object" and c["form"] in ("ὅτι", "question")) or (c["kind"] == "hangs" and c["form"] == "direct"):
        return ("text+translations", ON) if v is not None and v >= STRONG else ("", 0.0)
    return "", 0.0


def find(quotes: dict[str, list[dict]], con: sqlite3.Connection, T: Text | None = None) -> tuple[dict[str, list[dict]], dict]:
    """The quotations inside each quotation of `quotes` (per book number, as build_nt_clause_layout.load_quotations gives them
    after close_gaps). Returns them per book number (level 2 and deeper, `parent` the quotation around) and counts."""
    T = T or Text(con)
    n: collections.Counter = collections.Counter()
    out: dict[str, list[dict]] = collections.defaultdict(list)

    def inside(q: dict, level: int, top: dict, base: dict[str, int]) -> None:
        if level >= MAX_LEVEL:
            return
        found: list[dict] = []
        for c in sorted(candidates(T, q, base), key=lambda c: (c["start"], -c["words"])):
            if found and c["start"] <= found[-1]["end"]:          # inside a quotation found here: looked at one level further in
                continue
            basis, bar = accept(c)
            if not basis:
                continue
            end = c["end"]
            if c["opening"] is not None:
                last, _ = T.run(c["start"], q["end"], c["here"], bar)
                if last is not None:
                    rest = [T.nested(k, c["here"]) for k in T.between(last, c["end"])[1:]]
                    end = last if last > c["end"] or any(v is not None for v in rest) else c["end"]
            n["ends before its clause does, by the translations"] += end < c["end"]
            n["runs on past its clause, by the translations"] += end > c["end"]
            found.append({"id": c["start"], "start": c["start"], "end": end, "speaker": "", "level": level + 1, "parent": q["id"],
                          "top": top["id"], "verb": c["verb"], "basis": basis, "form": c["form"], "kind": c["kind"]})
        taken = [(f["start"], f["end"]) for f in found]
        run: list[str] = []
        here: dict[str, int] = {}
        for k in T.between(q["start"], q["end"])[1:] + [None]:     # what the translations nest where the text gave no quotation
            v = None
            if k is not None and not any(a <= k <= b for a, b in taken):
                if not run:
                    here = T.before(k, q, base)
                v = T.nested(k, here)
                if v is None and run:
                    continue
            if v is not None and v >= (ON if run else LONE):
                run.append(k)
                continue
            if len(run) >= MIN_RUN:
                verb = T.verb_before(run[0], q["start"], taken)
                first = T.opens_clause(run[0], verb or q["start"], taken) or (run[0] if verb else None)
                if first is not None:
                    found.append({"id": first, "start": first, "end": run[-1], "speaker": "", "level": level + 1, "parent": q["id"],
                                  "top": top["id"], "verb": verb, "basis": "translations", "form": "",
                                  "kind": "after a verb of saying" if verb else "a clause"})
                else:
                    n["stretches the translations nest that open inside a clause, left"] += 1
            run = []
        for f in sorted(found, key=lambda f: f["start"]):
            out[f["start"][:2]].append(f)
            n[f"level {f['level']}"] += 1
            n[f"basis {f['basis']}"] += 1
            inside(f, level + 1, top, T.base(T.between(f["start"], f["end"]), floor=base, share=0.25))

    for qs in quotes.values():
        for q in qs:
            T.enter(q)
            inside(q, 1, q, T.base(T.between(q["start"], q["end"])))
    return dict(out), dict(n)


def outer_quotations(T: Text) -> dict[str, list[dict]]:
    from macula import build_nt_clause_layout as L
    quotes = L.load_quotations()
    L.close_gaps(quotes, T.keys, {k: w["lemma"] for k, w in T.words.items()},
                 {k: w["mood"] for k, w in T.words.items() if w["class"] == "verb"})
    return quotes


def measure(con: sqlite3.Connection) -> dict:
    """how the two witnesses agree, over every quotation of the speaker data (level 2 only)"""
    T = Text(con)
    table: dict = collections.defaultdict(collections.Counter)
    runs = collections.Counter()
    for qs in outer_quotations(T).values():
        for q in qs:
            T.enter(q)
            base = T.base(T.between(q["start"], q["end"]))
            cs = candidates(T, q, base)
            for c in cs:
                v = c["opening"]
                band = "no vote" if v is None else "0.8 and more" if v >= 0.8 else "0.6 to 0.8" if v >= STRONG else \
                    "a third to 0.6" if v >= PLAIN else "0.1 to a third" if v >= 0.1 else "under 0.1"
                table[f"{c['kind']}, {c['form']}"][band] += 1
            covered = set()
            for c in cs:
                covered.update(T.between(c["start"], c["end"]))
            run: list[str] = []
            here: dict[str, int] = {}
            for k in T.between(q["start"], q["end"])[1:] + [None]:
                if k and not run:
                    here = T.before(k, q, base)
                v = T.nested(k, here) if k else 0.0
                if v is None and run:
                    continue
                if v is not None and v >= (ON if run else LONE):
                    run.append(k)
                    continue
                if len(run) >= MIN_RUN:
                    at = any(c["start"] in run[:3] for c in cs)
                    runs["stretches most translations nest"] += 1
                    runs["of them opening where a candidate opens"] += at
                    runs["of them inside a candidate, not at its start"] += (not at) and run[0] in covered
                    runs["of them with no candidate"] += (not at) and run[0] not in covered
                run = []
    return {"candidates of the text by kind and form, against the translations' vote on their opening": {k: dict(v) for k, v in sorted(table.items())},
            "the translations alone": dict(runs)}


def main() -> None:
    import trees_macula
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["measure", "find"])
    a = ap.parse_args()
    con = trees_macula._con()
    if a.cmd == "measure":
        print(json.dumps(measure(con), ensure_ascii=False, indent=1))
    else:
        T = Text(con)
        inner, n = find(outer_quotations(T), con, T)
        print(json.dumps({"quotations found": sum(len(v) for v in inner.values()), **dict(sorted(n.items()))}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
