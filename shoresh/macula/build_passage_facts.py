"""Passage facts: who is heard, what kind of speech, how the text is set, each fact tied to Hebrew or Greek words and to its source.

    python -m macula.build_passage_facts --books EXO LUK --out DIR [--licence by-sa|by] [--update-codes]

Every fact is one value from one source (or one rule over sources) on one stretch of the Hebrew or Greek text. The data holds codes
only; resources/passage_facts/codes.tsv is the table from code to English, sources.tsv the sources with their licences and attribution,
README.md the export and its licence. No English and no model analysis enter the facts: speakers are named by Hebrew and Greek words
of the text, the rest are codes of the sources' own values or of fixed rules over the Hebrew and Greek grammar.

Inputs (all local, all CC BY 4.0, MIT or public domain; see sources.tsv):
  - Hebrew: the speaker layer (data/speaker-layer: quotations.tsv, segments/<BOOK>.tsv) and the clause layout (data/clause-layout);
  - Greek: Clear's spans (resources/speaker_quotations) and the Greek NT clause layout's speaker columns (data/nt-clause-layout);
  - both: Clear's delivery notes (Glyssen's, carried in Clear's data), MACULA words and verb frames (macula-spine.db), MACULA word types
    and punctuation (trees-macula.db), Leningrad Codex paragraph marks (resources/parashot), the Nestle 1904 printed layout
    (nestle1904_layout), the BSB's poetry lines (its USFM, ebible.org engbsb_usfm.zip);
  - TBTA (All the Word): read only when sources.tsv has `enabled` 1 for it (it is 0: no licence yet). $TBTA_EXPORT_DIR points at the
    export's json/ folder.

One JSON line per fact in <out>/<BOOK>.jsonl:
  {"id": "EXO.00012", "kind": "quote", "value": "qt.normal", "first": "020030040081", "last": "020030040112", "ref": "EXO 3:4",
   "basis": "b.source", "precision": "p.word", "src": ["clear", "layer"], "lic": "CC BY 4.0", ...kind-specific fields}
The anchor is always `first`..`last` (word keys: Hebrew 12 digits BBCCCVVVWWWP, Greek 11 digits BBCCCVVVWWW, in MACULA's order);
`pieces` lists the parts where words of another voice interrupt the span, `lines` the printed lines, `at` the words a rule read.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import functools
import csv
import datetime
import glob
import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from macula import mam, nestle1904_layout, ubs, unfoldingword

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PF = ROOT / "resources" / "passage_facts"
CODES, SOURCES, README = PF / "codes.tsv", PF / "sources.tsv", PF / "README.md"
SPEAKER_SPANS = ROOT / "resources" / "speaker_quotations" / "speaker_quotations.tsv"
PARASHOT = ROOT / "resources" / "parashot" / "parashot.tsv"
LAYER = HERE / "data" / "speaker-layer"
HEB_LAYOUT = HERE / "data" / "clause-layout" / "clauses"
GRC_LAYOUT = HERE / "data" / "nt-clause-layout" / "clauses"
SPINE, TREES = HERE / "macula-spine.db", HERE / "trees-macula.db"
BSB_URL = "https://ebible.org/Scriptures/engbsb_usfm.zip"
BSB_ZIP = Path(os.environ.get("BSB_USFM_ZIP", HERE / ".cache" / "bsb-usfm" / "engbsb_usfm.zip"))
SCHEMA = 1
NARRATIVE_NT = {"MAT", "MRK", "LUK", "JHN", "ACT"}

# The sources' own values -> codes (closed groups; a value missing here stops the build).
QUOTE_TYPE = {"Normal": "qt.normal", "Dialogue": "qt.dialogue", "Implicit": "qt.implicit", "Quotation": "qt.quotation",
              "Hypothetical": "qt.hypothetical", "nested": "qt.nested", "layout only": "qt.layout", "relayed message": "qt.relayed",
              "oracle": "qt.oracle", "commanded message": "qt.commanded", "song": "qt.song", "song or speech": "qt.song_speech",
              "titled psalm": "qt.titled", "review": "qt.review"}
FOUND = {"block": "qf.block", "referent": "qf.referent", "character": "qf.character", "correction": "qf.correction",
         "layout": "qf.layout", "voice": "qf.voice", "translations": "qf.translations", "inner inquit": "qf.inner",
         "relayed message": "qf.relayed", "review": "qf.review", "messenger formula": "qf.messenger", "oracle": "qf.oracle",
         "commanded message": "qf.commanded", "song": "qf.song", "titled psalm": "qf.titled"}
FROM_SOURCE = {"qf.block", "qf.referent", "qf.character", "qf.correction"}       # Clear's own spans
NAMED_BY = {"inquit": "sb.inquit", "review": "sb.review", "same speaker in book": "sb.book", "same speaker in Bible": "sb.bible",
            "same speaker in NT": "sb.nt"}
TN_SLUGS = {r["code"][3:] for r in csv.DictReader((l for l in open(Path(__file__).resolve().parents[2] / "resources" / "passage_facts" /
            "codes.tsv", encoding="utf-8") if not l.startswith("#")), delimiter="\t") if r["code"].startswith("tn.")}
POETRY_MARKERS = {"q", "q1", "q2", "q3", "q4", "qm1", "qm2", "qc", "qr"}
GRC_PARTICLES = {"ιδου", "ιδε", "αγε"}
GRC_MH = {"μη", "μηδε", "μηδεις", "μηκετι", "μητε", "μηδεποτε"}
GRC_SUBORDINATORS = {"ινα", "εαν", "οταν", "οπως", "ει", "ως", "καθως", "εως", "μηποτε", "μηπως", "πριν", "ωστε", "επει", "επαν", "οτε",
                     "διοτι", "ος", "οστις", "οπου", "οθεν", "αν", "εανπερ", "ειπερ", "ωσπερ", "καθαπερ", "οσος",
                     "μεχρι", "μεχρις", "αχρι", "αχρις"}
GRC_MH = {w.replace("ς", "σ") for w in GRC_MH}                # nestle1904_layout._norm casefolds a final ς to σ
GRC_SUBORDINATORS = {w.replace("ς", "σ") for w in GRC_SUBORDINATORS} | {"τίς?"}    # τίς with a subjunctive: a deliberative or indirect question


@functools.lru_cache(maxsize=1)
def _grc_nodes() -> dict:
    return dict(sqlite3.connect(TREES).execute("SELECT id, parent FROM nodes WHERE corpus='grc'"))    # ἰδού, ἴδε, ἄγε: imperative in form, particles in use; no command, no listener
HEB_FORCE = {"imperative": "fc.imp", "jussive": "fc.jus", "cohortative": "fc.coh", "interrogative": "fc.q"}
# Open groups: the source's wording is the English; new values get the next number with --update-codes, never renumbered.
OPEN = {"delivery": "dl", "listener": "tl", "attitude": "ta", "age_relation": "tg", "tb_force": "tf", "rhetorical": "tr",
        "sdbh": "sd", "louw_nida": "ln"}
OPEN_SRC = {"delivery": "glyssen", "sdbh": "ubs", "louw_nida": "ubs"}           # the rest: tbta
TBTA_FIELDS = {"listener": "Listener", "attitude": "Speaker`s Attitude", "age_relation": "Speaker-Listener Age",
               "tb_force": "Illocutionary Force", "rhetorical": "Rhetorical Question"}
TBTA_BOOKS = {"Genesis": "GEN", "Exodus": "EXO", "Leviticus": "LEV", "Numbers": "NUM", "Deuteronomy": "DEU", "Joshua": "JOS",
              "Judges": "JDG", "Ruth": "RUT", "1_Samuel": "1SA", "2_Samuel": "2SA", "1_Kings": "1KI", "2_Kings": "2KI", "Ezra": "EZR",
              "Nehemiah": "NEH", "Esther": "EST", "Job": "JOB", "Psalms": "PSA", "Proverbs": "PRO", "Daniel": "DAN", "Joel": "JOL",
              "Jonah": "JON", "Nahum": "NAM", "Habakkuk": "HAB", "Matthew": "MAT", "Mark": "MRK", "Luke": "LUK", "John": "JHN",
              "Acts": "ACT", "Romans": "ROM", "Ephesians": "EPH", "Philippians": "PHP", "Colossians": "COL", "1_Thessalonians": "1TH",
              "2_Thessalonians": "2TH", "Titus": "TIT", "Philemon": "PHM", "James": "JAS", "1_John": "1JN", "Revelation": "REV"}
NOT_APPLICABLE = {"", "Not Applicable", "None"}


def _tsv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader((l for l in f if not l.startswith("#")), delimiter="\t"))


OPEN_LICENCES = {"CC BY 4.0": False, "MIT": False, "Public Domain": False, "CC BY-SA 4.0": True}   # licence -> share-alike


def sources() -> dict[str, dict]:
    """sources.tsv. An enabled source must carry an open licence, and share_alike must agree with it."""
    out = {r["src"]: r for r in _tsv(SOURCES)}
    for s, r in out.items():
        if r["enabled"] == "1":
            assert r["licence"] in OPEN_LICENCES, f"sources.tsv: {s} is enabled but its licence is {r['licence']!r}"
            assert (r["share_alike"] == "1") == OPEN_LICENCES[r["licence"]], f"sources.tsv: {s}: share_alike does not match {r['licence']}"
    return out


def enabled(src: str) -> bool:
    return sources()[src]["enabled"] == "1"


class Codes:
    """codes.tsv: the closed codes, and the open groups (english -> code) that --update-codes may extend."""

    def __init__(self, path: Path = CODES):
        self.path, self.rows = path, _tsv(path)
        self.known = {r["code"] for r in self.rows}
        self.open = {g: {r["english"]: r["code"] for r in self.rows if r["code"].startswith(p + ".")} for g, p in OPEN.items()}
        self.new: dict[str, list[str]] = collections.defaultdict(list)
        self.notes: dict[tuple[str, str], str] = {}

    def of(self, kind: str, english: str, note: str = "") -> str | None:
        code = self.open[kind].get(english)
        if code is None:
            if english not in self.new[kind]:
                self.new[kind].append(english)
                self.notes[(kind, english)] = note
            return None
        return code

    def assign(self, src_of: dict[str, str]) -> int:
        """Append the new open values to codes.tsv (next free number per group)."""
        lines = []
        for kind, values in self.new.items():
            p = OPEN[kind]
            n = max([int(c.split(".")[1]) for c in self.open[kind].values()] or [0])
            for v in values:
                n += 1
                code = f"{p}.{n:03d}"
                self.open[kind][v] = code
                self.known.add(code)
                lines.append(f"{code}\t{kind}\t{v}\t{src_of[kind]}\t{self.notes.get((kind, v), '')}")
        if lines:
            text = self.path.read_text(encoding="utf-8")
            self.path.write_text(text.rstrip("\n") + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
        self.new.clear()
        return len(lines)


class Book:
    """A book's words in MACULA's key order, with the grammar the rules read."""

    def __init__(self, book: str):
        self.book = book
        sp = sqlite3.connect(SPINE)
        rows = sp.execute("SELECT key, lemma, person, number, mood, case_ FROM macula_words WHERE book=? ORDER BY key", (book,)).fetchall()
        self.cls = dict(sp.execute("SELECT key, class FROM macula_words WHERE book=?", (book,)))
        lens = collections.Counter(len(r[0]) for r in rows)
        self.hebrew = lens.most_common(1)[0][0] == 12
        rows = [r for r in rows if len(r[0]) == (12 if self.hebrew else 11)]
        self.keys = [r[0] for r in rows]
        self.pos = {k: i for i, k in enumerate(self.keys)}
        self.w = {r[0]: r for r in rows}
        self.num = self.keys[0][:2]
        tr = sqlite3.connect(TREES)
        corpus = "hbo" if self.hebrew else "grc"
        self.wtype = dict(tr.execute("SELECT key, wtype FROM words WHERE corpus=? AND key LIKE ? AND inserted=0 AND wtype IS NOT NULL", (corpus, self.num + "%")))
        self.after = dict(tr.execute("SELECT key, after FROM words WHERE corpus=? AND key LIKE ? AND inserted=0", (corpus, self.num + "%")))
        self.frames = collections.defaultdict(list)          # verb -> [(role, arg)]
        self.args = collections.defaultdict(list)            # arg -> [(role, verb)]
        for v, role, a in sp.execute("SELECT verb_key, role, arg_key FROM frames WHERE verb_key LIKE ?", (self.num + "%",)):
            if v in self.pos and a in self.pos:
                self.frames[v].append((role, a))
                self.args[a].append((role, v))
        self.wend = {}                                      # index of a word's first morpheme -> of its last
        self.verse_words: dict = collections.defaultdict(list)   # (chapter, verse) -> [(first index, normalised word)]
        surf = dict(tr.execute("SELECT key, surface FROM words WHERE corpus=? AND key LIKE ? AND inserted=0", (corpus, self.num + "%")))
        self.surf = surf
        for i, k in enumerate(self.keys):
            wid = k[:11]
            if i and self.keys[i - 1][:11] == wid:
                start = self._start
                self.wend[start] = i
                self.verse_words[self.cv(k)][-1] = (start, self.verse_words[self.cv(k)][-1][1] + unfoldingword.norm(surf.get(k, "")))
            else:
                self._start = i
                self.wend[i] = i
                self.verse_words[self.cv(k)].append((i, unfoldingword.norm(surf.get(k, ""))))
        self.verses = collections.OrderedDict()             # (chapter, verse) -> (first index, last index)
        for i, k in enumerate(self.keys):
            cv = self.cv(k)
            a, _ = self.verses.get(cv, (i, i))
            self.verses[cv] = (a, i)

    @staticmethod
    def cv(key: str) -> tuple[int, int]:
        return int(key[2:5]), int(key[5:8])

    def ref(self, first: str, last: str) -> str:
        (c1, v1), (c2, v2) = self.cv(first), self.cv(last)
        if (c1, v1) == (c2, v2):
            return f"{self.book} {c1}:{v1}"
        return f"{self.book} {c1}:{v1}-{v2}" if c1 == c2 else f"{self.book} {c1}:{v1}-{c2}:{v2}"

    def segments(self) -> list[dict]:
        """The clause layout's segments in order: {chapter, seg, words (keys), ...}."""
        base = HEB_LAYOUT if self.hebrew else GRC_LAYOUT
        out = []
        for f in sorted(glob.glob(str(base / self.book / f"{self.book}_*.jsonl"))):
            ch = int(Path(f).stem.split("_")[1])
            for line in open(f, encoding="utf-8"):
                r = json.loads(line)
                r.setdefault("chapter", ch)
                r["words"] = [k for k in r["words"] if k in self.pos]
                if r["words"]:
                    out.append(r)
        out.sort(key=lambda r: (r["chapter"], r["seg"]))
        return out


# ---------------------------------------------------------------------------------------------------------------------- quotes

def hebrew_quotes(bk: Book, segs: list[dict], spans: list[dict]) -> list[dict]:
    """The speaker layer's quotations of the book, with their pieces where words of another voice interrupt them."""
    rows = [r for r in _tsv(LAYER / "quotations.tsv") if r["first"][:2] == bk.num]
    lay = {(int(r["chapter"]), int(r["seg"])): r for r in _tsv(LAYER / "segments" / f"{bk.book}.tsv")}
    seg_at = {(s["chapter"], s["seg"]): i for i, s in enumerate(segs)}
    out = []
    for r in rows:
        q = {"src_id": r["id"], "level": int(r["level"]), "parent_src": r["parent"] or None, "first": r["first"], "last": r["last"],
             "type": r["quote_type"], "found": r["basis"], "speaker": r["speaker"] or None,
             "speaker_ref": r["speaker_ref"].split() if r["speaker_ref"] else [], "named_by": r["speaker_basis"] or None,
             "speaker_id": r["speaker_id"] or None, "speaker_name": r["speaker_name"] or None,
             "speaker_name_ref": r["speaker_name_ref"].split() if r["speaker_name_ref"] else [],
             "members": r["speaker_members"].split() if r["speaker_members"] else [], "divine": r["divine"] == "Y",
             "pieces": None, "note": ""}
        if int(r["pieces"] or 1) > 1:
            # the layer joins spans of one speaker with only a speaking formula between them: the pieces are Clear's spans inside it
            lo, hi = bk.pos[r["first"]], bk.pos[r["last"]]
            inside = sorted({(bk.pos[x["word_start"][1:]], bk.pos[x["word_end"][1:]]) for x in spans
                             if x["word_start"][:1] == "o" and x["word_start"][1:] in bk.pos and x["word_end"][1:] in bk.pos
                             and lo <= bk.pos[x["word_start"][1:]] and bk.pos[x["word_end"][1:]] <= hi})
            top = [s for s in inside if not any(o != s and o[0] <= s[0] and s[1] <= o[1] for o in inside)]
            if len(top) == int(r["pieces"]):
                top[0] = (lo, top[0][1])
                top[-1] = (top[-1][0], hi)
                q["pieces"] = [(bk.keys[x], bk.keys[y]) for x, y in top]
            else:                                         # quotations the layer made itself: the runs of its segments
                mine = sorted(seg_at[k] for k, sg in lay.items() if k in seg_at and sg["quotation"]
                              and (sg["quotation"] == r["id"] or sg["quotation"].startswith(r["id"] + ".")))
                runs: list[list[int]] = []
                for i in mine:
                    if runs and i == runs[-1][-1] + 1:
                        runs[-1].append(i)
                    else:
                        runs.append([i])
                sp = [(max(lo, bk.pos[segs[run[0]]["words"][0]]), min(hi, bk.pos[segs[run[-1]]["words"][-1]])) for run in runs]
                sp = [(x, y) for x, y in sp if x <= y]
                if len(sp) == int(r["pieces"]):
                    sp[0], sp[-1] = (lo, sp[0][1]), (sp[-1][0], hi)
                    q["pieces"] = [(bk.keys[x], bk.keys[y]) for x, y in sp]
                else:
                    q["note"] = f"pieces: {r['pieces']} in the layer; neither Clear's spans ({len(top)}) nor its segments ({len(sp)}) give them; one span"
        out.append(q)
    return out


def greek_quotes(bk: Book, segs: list[dict], spans: list[dict]) -> list[dict]:
    """Clear's spans of the book, nested by containment, with the Greek layout's speaker columns."""
    by_q: dict[str, dict] = {}
    for s in segs:
        if s.get("quotation") and s["quotation"] not in by_q and (s.get("speaker") or s.get("speaker_id")):
            by_q[s["quotation"]] = s
    rows = sorted((r for r in spans if r["word_start"][1:3] == bk.num and r["word_start"][0] == "n"),
                  key=lambda r: (bk.pos.get(r["word_start"][1:], -1), -bk.pos.get(r["word_end"][1:], -1)))
    out, stack = [], []
    for r in rows:
        first, last = r["word_start"][1:], r["word_end"][1:]
        if first not in bk.pos or last not in bk.pos:
            continue
        a, b = bk.pos[first], bk.pos[last]
        while stack and bk.pos[stack[-1]["last"]] < a:
            stack.pop()
        parent = stack[-1] if stack and bk.pos[stack[-1]["last"]] >= b else None
        s = by_q.get(first, {})
        q = {"src_id": "n" + first, "level": parent["level"] + 1 if parent else 1, "parent_src": parent["src_id"] if parent else None,
             "first": first, "last": last, "type": r["quote_type"], "found": r["speaker_basis"], "speaker": s.get("speaker"),
             "speaker_ref": s.get("speaker_ref") or [], "named_by": s.get("speaker_basis") or None, "speaker_id": s.get("speaker_id"),
             "speaker_name": s.get("speaker_name"), "speaker_name_ref": [s["speaker_name_ref"]] if s.get("speaker_name_ref") else [],
             "members": s.get("speaker_members") or [], "divine": r["divine"] == "Y", "pieces": None, "note": ""}
        out.append(q)
        stack.append(q)
    return out


# ---------------------------------------------------------------------------------------------------------------------- the build

class Builder:
    def __init__(self, book: str, codes: Codes):
        self.bk, self.codes, self.facts, self.src = Book(book), codes, [], sources()
        self.segs = self.bk.segments()
        self.seg_of = {k: i for i, s in enumerate(self.segs) for k in s["words"]}
        self.sdbh = ubs.hebrew(book) if self.bk.hebrew and enabled("ubs") else {}

    def add(self, kind: str, value, first: str, last: str, basis: str, src: list[str], precision: str = "p.word", **extra) -> dict:
        lic = sorted({self.src[s]["licence"] for s in src})
        f = {"id": f"{self.bk.book}.{len(self.facts) + 1:05d}", "kind": kind, "value": value, "first": first, "last": last,
             "ref": self.bk.ref(first, last), "basis": basis, "precision": precision, "src": src,
             "lic": "CC BY-SA 4.0" if any(self.src[s]["share_alike"] == "1" for s in src) else " + ".join(lic)}
        f.update({k: v for k, v in extra.items() if v not in (None, [], "")})
        self.facts.append(f)
        return f

    def span_idx(self, q: dict) -> list[tuple[int, int]]:
        p = q.get("pieces") or [(q["first"], q["last"])]
        return [(self.bk.pos[a], self.bk.pos[b]) for a, b in p]

    def build(self, spans: list[dict]) -> list[dict]:
        bk = self.bk
        quotes = hebrew_quotes(bk, self.segs, spans) if bk.hebrew else greek_quotes(bk, self.segs, spans)
        self.quotes(quotes)
        self.voices(quotes)
        self.delivery(spans)
        self.force_and_addressee(quotes)
        self.sections()
        self.forms()
        self.notes(quotes)
        self.tbta()
        return self.facts

    def quotes(self, quotes: list[dict]):
        self.level_at = [0] * len(self.bk.keys)          # the deepest quote level each word stands in
        for q in quotes:
            for a, b in self.span_idx(q):
                for i in range(a, b + 1):
                    self.level_at[i] = max(self.level_at[i], q["level"])
        by_src: dict[str, dict] = {}
        for q in sorted(quotes, key=lambda q: (q["level"], self.bk.pos[q["first"]])):
            qt, qf = QUOTE_TYPE.get(q["type"]), FOUND.get(q["found"])
            sb = NAMED_BY.get(q["named_by"]) if q["named_by"] else None
            missing = [v for v, c in ((q["type"], qt), (q["found"], qf)) if v and not c] + ([q["named_by"]] if q["named_by"] and not sb else [])
            assert not missing, f"{self.bk.book} {q['src_id']}: no code for {missing}"
            basis = "b.review" if qf == "qf.review" or qt == "qt.review" else "b.source" if qf in FROM_SOURCE else "b.rule"
            src = ["clear"] if not self.bk.hebrew else ["clear", "layer"] if qf in FROM_SOURCE else ["layer"]
            if self.bk.hebrew or q["speaker"]:
                src = sorted(set(src) | {"layer"})
            parent = by_src.get(q["parent_src"]) if q["parent_src"] else None
            f = self.add("quote", qt, q["first"], q["last"], basis, src, level=q["level"], parent=parent["id"] if parent else None,
                         quote=q["src_id"], found=qf, speaker=q["speaker"], speaker_ref=q["speaker_ref"], speaker_by=sb,
                         speaker_id=q["speaker_id"], speaker_name=q["speaker_name"], speaker_name_ref=q["speaker_name_ref"],
                         members=q["members"], divine=True if q["divine"] else None, pieces=q["pieces"], note=q["note"])
            q["fact"] = f
            by_src[q["src_id"]] = f
            self.frame(q, f)

    def frame(self, q: dict, f: dict):
        """The verb that introduces a quote: the nearest verb in the 15 words before it that is not inside another quote of the same
        level or deeper, with no Greek sentence end (. ;) between; a Hebrew infinitive לֵאמֹר ("saying") gives way to the verb before
        it in the same clause (וַיְדַבֵּר … לֵאמֹר). Its A2 argument (Greek), or the object of אֶל in its clause (Hebrew), is the one
        spoken to (ad.named)."""
        bk = self.bk
        lo, hi = bk.pos[q["first"]], bk.pos[q["last"]]
        verb = None
        for i in range(lo - 1, max(-1, lo - 16), -1):
            k = bk.keys[i]
            if self.level_at[i] >= q["level"]:
                break
            if not bk.hebrew and re.search(r"[.;]", bk.after.get(k) or ""):
                break
            if bk.cls.get(k) == "verb":
                verb = k
                break
        if verb is None:
            return
        if bk.hebrew and bk.w[verb][1] == "אָמַר" and bk.wtype.get(verb) == "infinitive construct":
            seg = self.seg_of.get(verb)
            for i in range(bk.pos[verb] - 1, max(-1, bk.pos[verb] - 12), -1):
                k = bk.keys[i]
                if self.seg_of.get(k) != seg or self.level_at[i] >= q["level"]:
                    break
                if bk.cls.get(k) == "verb":
                    verb = k
                    break
        fr = self.add("frame", bk.w[verb][1], verb, verb, "b.rule", ["layer", "macula"], of=f["id"])
        if enabled("ubs"):
            if bk.hebrew:
                dom = self.sdbh.get(verb)
                code = self.codes.of("sdbh", dom, "SDBH lexical domain") if dom else None
            else:
                dom = ubs.greek().get(verb)
                code = self.codes.of("louw_nida", dom[0], f"Louw-Nida {'subdomain' if len(dom[1]) > 3 else 'domain'} {dom[1]}") if dom else None
            if dom:
                self.add("domain", code, verb, verb, "b.source", ["ubs"], of=f["id"], verb=fr["id"])
        for role, a in bk.frames[verb]:
            if role == "A2" and not lo <= bk.pos[a] <= hi:
                self.add("addressee", "ad.named", a, a, "b.rule", ["macula"], of=f["id"], verb=fr["id"])
                return
        if bk.hebrew:
            # MACULA Hebrew has almost no A2: the one spoken to is the object of אֶל in the inquit's clause, before the quote
            # (its pronoun suffix, אֵלָיו, or the next word, אֶל־מֹשֶׁה)
            seg, v = self.seg_of.get(verb), bk.pos[verb]
            for i in range(v + 1, lo):
                k = bk.keys[i]
                if self.seg_of.get(k) != seg:
                    break
                if bk.w[k][1] != "אֶל":
                    continue
                same = [j for j in range(i + 1, lo) if bk.keys[j][:11] == k[:11]]
                if not same:
                    nxt = bk.keys[i + 1][:11] if i + 1 < lo else None
                    same = [j for j in range(i + 1, lo) if bk.keys[j][:11] == nxt]
                if same:
                    self.add("addressee", "ad.named", bk.keys[same[0]], bk.keys[same[-1]], "b.rule", ["macula", "layout"],
                             of=f["id"], verb=fr["id"])
                break

    def voices(self, quotes: list[dict]):
        """Who is heard outside the level-1 quotes: the narrator, or the frame speaker the speaker layer gives (a psalm's psalmist)."""
        bk = self.bk
        if not bk.hebrew and bk.book not in NARRATIVE_NT:
            return                                       # letters and Revelation: the author's voice; not yet modelled
        quoted = bytearray(len(bk.keys))
        for q in quotes:
            if q["level"] == 1:
                for a, b in self.span_idx(q):
                    quoted[a:b + 1] = b"\x01" * (b - a + 1)
        frame_of = {}
        if bk.hebrew:
            lay = {(int(r["chapter"]), int(r["seg"])): r["frame"] for r in _tsv(LAYER / "segments" / f"{bk.book}.tsv")}
            for s in self.segs:
                fr = lay.get((s["chapter"], s["seg"]))
                if fr:
                    for k in s["words"]:
                        frame_of[k] = fr
        run: list[int] = []

        def flush():
            if run:
                a, b = run[0], run[-1]
                fr = frame_of.get(bk.keys[a])
                if fr:
                    self.add("voice", "vc.frame", bk.keys[a], bk.keys[b], "b.rule", ["layer"], speaker=fr)
                else:
                    self.add("voice", "vc.narrator", bk.keys[a], bk.keys[b], "b.rule", ["layer"] if bk.hebrew else ["clear"])
                run.clear()

        for i, k in enumerate(bk.keys):
            if quoted[i]:
                flush()
                continue
            if run and (bk.cv(bk.keys[run[-1]])[0] != bk.cv(k)[0] or frame_of.get(bk.keys[run[-1]]) != frame_of.get(k)):
                flush()
            run.append(i)
        flush()

    def delivery(self, spans: list[dict]):
        bk = self.bk
        pre = "o" if bk.hebrew else "n"
        quote_at = {f["first"]: f for f in self.facts if f["kind"] == "quote"}
        for r in spans:
            if not r["delivery"] or r["word_start"][:1] != pre or r["word_start"][1:3] != bk.num:
                continue
            first, last = r["word_start"][1:], r["word_end"][1:]
            if first not in bk.pos or last not in bk.pos:
                continue
            values = [r["delivery"]] if r["delivery"] in self.codes.open["delivery"] else [v.strip() for v in r["delivery"].split(",")]
            q = quote_at.get(first)
            for v in values:
                self.add("delivery", self.codes.of("delivery", v), first, last, "b.source", ["clear", "glyssen"],
                         of=q["id"] if q else None)

    def force_codes(self, inner: list | None = None) -> dict[int, list[str]]:
        """Word index -> force codes, by the grammar, everywhere (inside and outside speech).
        Hebrew: imperative, jussive, cohortative, interrogative (wtype); אַל before a jussive, cohortative or yiqtol of the same segment
        (no verb between) is a prohibition (fc.proh, in place of fc.jus / fc.coh).
        Greek: imperative; μή (μηδέ, μηδείς, μηκέτι, μήτε) before an imperative of the same segment (no verb between; not εἰ δὲ μή) is a
        prohibition, and so is μή before a second-person aorist subjunctive in a main clause (not οὐ μή); a first-person plural
        subjunctive in a main clause is an exhortation (fc.hort); a vocative; every word from the stop before to a question mark is
        a question (fc.q), counting only words in the same quotation as the mark (or, like it, in none), so an inquit with no stop
        before the speech is no question (correction by make-tanakh-research). Not after μή ποτε / μή πως ("lest") or a subordinator earlier in the segment. A main clause: no subordinator (ἵνα, ἐάν, ὅταν, ὡς, ὅς ἄν ...) in its own tree node or any node above it.
        ἰδού, ἴδε, ἄγε are left out. Not taken: οὐ + future as a command, לֹא + yiqtol (whether they command is a reading)."""
        bk = self.bk
        out: dict[int, list[str]] = collections.defaultdict(list)
        finite = {"imperative", "indicative", "subjunctive", "optative", "jussive", "cohortative", "yiqtol", "qatal", "wayyiqtol", "weqatal"}
        verbs = {i for i, k in enumerate(bk.keys) if bk.cls.get(k) == "verb" and (bk.w[k][4] in finite or bk.wtype.get(k) in finite)}

        def neg_before(i, neg):                     # a negation earlier in the segment with no verb between
            s = self.seg_of.get(bk.keys[i])
            j = i - 1
            while j >= 0 and self.seg_of.get(bk.keys[j]) == s and j not in verbs:
                if neg(j):
                    return j
                j -= 1
            return None
        if bk.hebrew:
            for i, k in enumerate(bk.keys):
                wt = bk.wtype.get(k)
                if wt in ("jussive", "cohortative", "yiqtol") and neg_before(i, lambda j: bk.w[bk.keys[j]][1] == "אַל") is not None:
                    out[i].append("fc.proh")
                elif wt in HEB_FORCE:
                    out[i].append(HEB_FORCE[wt])
            return out
        tr = sqlite3.connect(TREES)
        info = {k: (cl, tense) for k, cl, tense in tr.execute(
            "SELECT key, cl, tense FROM words WHERE corpus='grc' AND key LIKE ? AND inserted=0", (bk.num + "%",))}
        parent = _grc_nodes()
        norm = lambda k: "τίς?" if bk.w[k][1] == "τίς" else nestle1904_layout._norm(bk.w[k][1] or "")   # τίς, not the indefinite τὶς
        has_sub: dict = {}                         # node -> position of its first subordinator word
        for i, k in enumerate(bk.keys):
            if k in info and norm(k) in GRC_SUBORDINATORS:
                has_sub.setdefault(info[k][0], i)

        def main(k):                                # in its own node only a subordinator before the verb counts
            n, steps = info.get(k, (None, None))[0], 0
            while n is not None and steps < 80:
                if n in has_sub and (steps or has_sub[n] < bk.pos[k]):
                    return False
                n, steps = parent.get(n), steps + 1
            return True
        question, start = set(), 0
        for i, k in enumerate(bk.keys):
            after = self.surface(k) + (bk.after.get(k) or "")          # the mark is sometimes part of the surface (ἀνθρώπων;)
            if ";" in after or "\u037e" in after:          # the question: back to the stop before, in the mark's own quotation only
                question.update(j for j in range(start, i + 1) if inner is None or inner[j] is inner[i] or
                                (inner[j] is not None and inner[i] is not None and inner[j]["level"] == inner[i]["level"]))
                # (a quote the speaker data splits in two, JHN 4:27 Τί ζητεῖς / τί λαλεῖς ...; one mark: one question)
            if any(c in after for c in ".;·\u0387\u037e"):
                start = i + 1
        lest = lambda j: j + 1 < len(bk.keys) and norm(bk.keys[j + 1]) in ("ποτε", "πωσ", "που")      # μή ποτε, μή πως: "lest"
        def sub_before(i):                          # a subordinator earlier in the segment (ὅπως μή, ἕως οὗ, παρ' ᾧ)
            s, j = self.seg_of.get(bk.keys[i]), i - 1
            while j >= 0 and self.seg_of.get(bk.keys[j]) == s:
                if norm(bk.keys[j]) in GRC_SUBORDINATORS or (norm(bk.keys[j]) == "μη" and lest(j)):
                    return True
                j -= 1
            return False
        is_mh = lambda j: not lest(j) and norm(bk.keys[j]) in GRC_MH and not (j >= 1 and norm(bk.keys[j - 1]) in ("ει", "δε") and
                                                              (norm(bk.keys[j - 1]) == "ει" or (j >= 2 and norm(bk.keys[j - 2]) == "ει")))
        for i, k in enumerate(bk.keys):
            if nestle1904_layout._norm(self.surface(k)) in GRC_PARTICLES:
                continue
            _, lemma, person, number, mood, case = bk.w[k]
            if mood == "imperative":
                out[i].append("fc.proh" if neg_before(i, is_mh) is not None else "fc.imp")
            elif mood == "subjunctive" and i not in question and main(k) and not sub_before(i):
                m = neg_before(i, is_mh)
                if person in ("second", "2") and info.get(k, (0, ""))[1] == "aorist" and m is not None and \
                        not (m >= 1 and norm(bk.keys[m - 1]) == "ου"):
                    out[i].append("fc.proh")
                elif person in ("first", "1") and number == "plural" and not (m is not None and m >= 1 and norm(bk.keys[m - 1]) == "ου"):
                    out[i].append("fc.hort")
            if case == "vocative":
                out[i].append("fc.voc")
            if i in question:
                out[i].append("fc.q")
        return out

    def force_and_addressee(self, quotes: list[dict]):
        """Force per clause segment, by the grammar, inside and outside speech (force_codes); and, inside the quotes, the number of the
        second-person forms per quote (its own words, not those of quotes inside it)."""
        bk = self.bk
        inner = [None] * len(bk.keys)
        for q in sorted(quotes, key=lambda q: q["level"]):
            for a, b in self.span_idx(q):
                for i in range(a, b + 1):
                    inner[i] = q
        found: dict[tuple, list[str]] = collections.defaultdict(list)
        p2: dict[int, set] = collections.defaultdict(set)
        p2_at: dict[int, list] = collections.defaultdict(list)
        for i, codes in self.force_codes(inner).items():
            q = inner[i]
            for c in codes:
                found[(id(q) if q else None, self.seg_of.get(bk.keys[i], -1), c)].append(bk.keys[i])
        for i, k in enumerate(bk.keys):
            q = inner[i]
            if q is None:
                continue
            _, lemma, person, number, mood, case = bk.w[k]
            if not bk.hebrew and nestle1904_layout._norm(self.surface(k)) in GRC_PARTICLES:
                continue
            if person in ("second", "2") and number in ("singular", "plural"):
                p2[id(q)].add(number)
                p2_at[id(q)].append(k)
        qmap = {id(q): q for q in quotes}
        for (qid, si, code), at in found.items():
            q = qmap.get(qid)
            lo, hi = (bk.pos[q["first"]], bk.pos[q["last"]]) if q else (0, len(bk.keys) - 1)
            if si >= 0:
                s = self.segs[si]["words"]
                a, b = max(lo, bk.pos[s[0]]), min(hi, bk.pos[s[-1]])
            else:
                a = b = bk.pos[at[0]]
            if code in ("fc.voc", "fc.q"):
                a, b = bk.pos[at[0]], bk.pos[at[-1]]
            extra = {"of": q["fact"]["id"]} if q else {}
            self.add("force", code, bk.keys[a], bk.keys[b], "b.text", ["macula"] if si < 0 else ["macula", "layout"], at=at, **extra)
        for qid, nums in p2.items():
            q = qmap[qid]
            code = "ad.both" if len(nums) == 2 else "ad.sg" if "singular" in nums else "ad.pl"
            self.add("addressee", code, q["first"], q["last"], "b.text", ["macula"], of=q["fact"]["id"], at=p2_at[qid],
                     pieces=q["pieces"])

    def sections(self):
        bk = self.bk
        if not bk.hebrew:
            return
        for r in _tsv(PARASHOT):
            if r["book"] != bk.book:
                continue
            cv = (int(r["chapter"]), int(r["verse"]))
            if cv in bk.verses:
                k = bk.keys[bk.verses[cv][1]]
                self.add("section", "sc.pe" if r["mark"] == "petucha" else "sc.sa", k, k, "b.source", ["oshb"], after=k)
        if enabled("mam"):
            for mark, i in mam.sections(bk.book, bk.verse_words):
                k = bk.keys[bk.wend[i]]
                self.add("section", "sc." + mark, k, k, "b.source", ["mam"], after=k)

    def forms(self):
        bk = self.bk
        if not bk.hebrew and bk.book in nestle1904_layout.FILES:
            words = [(k, self.surface(k)) for k in bk.keys]
            for r in nestle1904_layout.passages(bk.book, words):
                if not r["first"]:
                    continue
                code = {"lines": "fm.ed.lines", "block": "fm.ed.block", "qlines": "fm.ed.qlines"}[r["class"]]
                self.add("form", code, r["first"], r["last"], "b.source", ["nestle1904"], r["precision"],
                         lines=r["line_spans"], printed_lines=int(r["lines"]) if r["lines"] else None, leaf=r["leaf"], note=r["note"])
        if bk.hebrew and enabled("mam"):
            for song in mam.songs(bk.book, bk.verse_words):
                lines = [(bk.keys[a], bk.keys[bk.wend[b]]) for a, b in song["lines"]]
                self.add("form", "fm.ms.song", lines[0][0], lines[-1][1], "b.source", ["mam"], lines=lines)
            for poem in mam.poem_lines(bk.book, bk.verse_words):
                lines = [(bk.keys[a], bk.keys[bk.wend[b]]) for a, b in poem["lines"]]
                self.add("form", "fm.ms.lines", lines[0][0], lines[-1][1], "b.source", ["mam"], lines=lines, markers=poem["markers"])
        if enabled("ult"):
            self.ult_forms()
        for (c1, v1), (c2, v2), start, end in bsb_poetry(bk):
            a, b = bk.verses[(c1, v1)][0], bk.verses[(c2, v2)][1]
            self.add("form", "fm.tr.poetry", bk.keys[a], bk.keys[b], "b.source", ["bsb"], "p.verse", start=start, end=end)

    def ult_forms(self):
        """The ULT's runs of poetic paragraphs, each printed line on the Hebrew or Greek words aligned to it (p.word)."""
        bk = self.bk
        paras = unfoldingword.ult_lines(bk.book, bk.verse_words, bk.hebrew)
        runs, cur = [], []
        for p in paras:
            if p["marker"] in POETRY_MARKERS:
                cur.append(p)
            elif cur:
                runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
        for run in runs:
            lines = [(min(p["words"]), bk.wend[max(p["words"])]) for p in run]
            a, b = min(x for x, _ in lines), max(y for _, y in lines)
            self.add("form", "fm.tr.poetry", bk.keys[a], bk.keys[b], "b.source", ["ult"], lines=[(bk.keys[x], bk.keys[y]) for x, y in lines],
                     markers=[p["marker"] for p in run])

    def notes(self, quotes: list[dict]):
        """unfoldingWord Translation Notes of the speech, address and poetry articles, on the words they quote."""
        if not enabled("tn"):
            return
        bk = self.bk
        spans = sorted(((bk.pos[q["first"]], bk.pos[q["last"]], q) for q in quotes), key=lambda x: x[1] - x[0])
        for n in unfoldingword.notes(bk.book, bk.verse_words, bk.hebrew, TN_SLUGS):
            ws = sorted(n["words"])
            a, b = ws[0], bk.wend[ws[-1]]
            q = next((q for lo, hi, q in spans if lo <= a and b <= hi), None)
            self.add("note", "tn." + n["slug"], bk.keys[a], bk.keys[b], "b.source", ["tn"], at=[bk.keys[i] for i in ws],
                     tn_id=n["id"], of=q["fact"]["id"] if q else None, fit="partial" if n["fit"] == "partial" else None)

    def surface(self, k: str) -> str:
        if not hasattr(self, "_surf"):
            self._surf = dict(sqlite3.connect(TREES).execute("SELECT key, surface FROM words WHERE corpus='grc' AND key LIKE ? AND inserted=0",
                                                             (self.bk.num + "%",)))
        return self._surf.get(k, "")

    def tbta(self):
        """TBTA's clause features on the verses (p.verse; its clauses are not yet matched to ours). Off until sources.tsv enables it."""
        if not enabled("tbta"):
            return
        for (c, v), feats in tbta_verses(self.bk).items():
            if (c, v) not in self.bk.verses:
                continue
            a, b = self.bk.verses[(c, v)]
            for kind, value in sorted(feats):
                self.add(kind, self.codes.of(kind, value), self.bk.keys[a], self.bk.keys[b], "b.source", ["tbta"], "p.verse")


# ---------------------------------------------------------------------------------------------------------------------- BSB, TBTA

def _bsb_zip() -> bytes:
    if not BSB_ZIP.exists():
        BSB_ZIP.parent.mkdir(parents=True, exist_ok=True)
        BSB_ZIP.write_bytes(urllib.request.urlopen(BSB_URL, timeout=120).read())
    return BSB_ZIP.read_bytes()


def bsb_verses(book: str) -> dict[tuple[int, int], list[str]]:
    """English verse -> the kinds of paragraph its text stands in, in order ('q' poetry, 'p' prose), from the BSB's USFM."""
    z = zipfile.ZipFile(io.BytesIO(_bsb_zip()))
    name = next(n for n in z.namelist() if re.search(rf"\d+-{book}engbsb\.usfm$", n))
    out: dict[tuple[int, int], list[str]] = collections.defaultdict(list)
    c = v = 0
    para = "p"
    for m in re.finditer(r"\\(\w+)\*?\s*([^\\]*)", z.read(name).decode("utf-8")):
        tag, text = m[1], m[2]
        if tag == "c":
            c, v = int(text.split()[0]), 0
            continue
        if re.fullmatch(r"q\d?|qc|qr|qm\d?", tag):
            para = "q"
        elif re.fullmatch(r"p|m|pi\d?|pmo|pm|nb|li\d?|mi|pc|pr", tag):
            para = "p"
        elif tag in ("s1", "s2", "s3", "r", "d", "ms", "mr", "sp", "qa", "b", "mt1", "mt2", "h", "toc1", "toc2", "toc3", "id", "ide"):
            para = "-"
            continue
        elif tag in ("f", "fr", "ft", "fq", "fqa", "x", "xo", "xt"):
            continue                                     # notes: their text is not the verse's
        if tag == "v":
            v = int(re.match(r"\d+", text)[0])
            text = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""
        if c and v and para in ("p", "q") and re.search(r"\w", text):
            kinds = out[(c, v)]
            if not kinds or kinds[-1] != para:
                kinds.append(para)
    return out


def bsb_poetry(bk: Book) -> list[tuple[tuple[int, int], tuple[int, int], str, str]]:
    """Runs of the book's verses (in its own numbering) that the BSB sets as poetry, with cv.all / cv.part at each end. A run goes on into
    the next verse when the verse ends in poetry and the next one starts in poetry."""
    from vrsmap import from_eng
    kinds: dict[tuple[int, int], list[str]] = {}
    for (c, v), ks in bsb_verses(bk.book).items():
        if "q" in ks:
            for _, c2, v2 in (from_eng((bk.book, c, v), "org") if bk.hebrew else [(bk.book, c, v)]):
                if (c2, v2) in bk.verses:
                    kinds[(c2, v2)] = kinds.get((c2, v2), []) + ks
    runs, cur = [], []
    for cv in bk.verses:
        ks = kinds.get(cv)
        if cur and ks and kinds[cur[-1]][-1] == "q" and ks[0] == "q":
            cur.append(cv)
            continue
        if cur:
            runs.append(cur)
        cur = [cv] if ks else []
    if cur:
        runs.append(cur)
    cover = lambda cv: "cv.all" if set(kinds[cv]) == {"q"} else "cv.part"
    return [(r[0], r[-1], cover(r[0]), cover(r[-1])) for r in runs]


def tbta_verses(bk: Book) -> dict[tuple[int, int], set[tuple[str, str]]]:
    """(chapter, verse) in the book's numbering -> {(kind, TBTA value)} of the clauses that have a Speaker."""
    from vrsmap import from_eng
    d = os.environ.get("TBTA_EXPORT_DIR")
    assert d, "TBTA is enabled in sources.tsv: set TBTA_EXPORT_DIR to the export's json/ folder"
    names = {v: k for k, v in TBTA_BOOKS.items()}
    out: dict[tuple[int, int], set] = collections.defaultdict(set)
    if bk.book not in names:
        return out

    def walk(n):
        if isinstance(n, list):
            for x in n:
                yield from walk(x)
        elif isinstance(n, dict):
            yield n
            yield from walk(n.get("Children", []))

    for f in glob.glob(os.path.join(d, f"*_{names[bk.book]}.json")):
        m = re.match(r"\d+_(\d+)_(\d+)_", os.path.basename(f))
        c, v = int(m[1]), int(m[2])
        refs = from_eng((bk.book, c, v), "org") if bk.hebrew else [(bk.book, c, v)]
        for n in walk(json.load(open(f, encoding="utf-8"))):
            if n.get("Part") != "Clause" or n.get("Speaker", "Not Applicable") in NOT_APPLICABLE:
                continue
            for kind, field in TBTA_FIELDS.items():
                val = n.get(field, "")
                if val not in NOT_APPLICABLE and not (kind == "rhetorical" and val.startswith("No")):
                    for _, c2, v2 in refs:
                        out[(c2, v2)].add((kind, val))
    return out


# ---------------------------------------------------------------------------------------------------------------------- main

def book_checks(facts: list[dict], uw: collections.Counter) -> dict:
    """How well each source landed on the words, for build.json (computed before the licence filter)."""
    c = collections.Counter
    quotes = [f for f in facts if f["kind"] == "quote"]
    framed = {f["of"] for f in facts if f["kind"] == "frame"}
    frames = c(f["value"] for f in facts if f["kind"] == "frame")
    out = {"quotes": len(quotes), "quotes_with_frame": sum(q["id"] in framed for q in quotes),
           "frame_verbs_top": dict(frames.most_common(5)),
           "quotes_with_pieces_given_as_one_span": sum(1 for q in quotes if q.get("note", "").startswith("pieces"))}
    if uw["tn_found"] or uw["tn"]:
        notes = [f for f in facts if f["kind"] == "note"]
        out["tn_notes"] = {"placed": uw["tn_found"], "of_them_partial": sum(f.get("fit") == "partial" for f in notes), "not_found": uw["tn"]}
    if uw["ult_book_absent"] or uw["tn_book_absent"]:
        out["not_in_unfoldingword_release"] = [n for n, k in (("ULT", "ult_book_absent"), ("Translation Notes", "tn_book_absent")) if uw[k]]
    if uw["ult_found"] or uw["ult"]:
        out["ult_alignment_words"] = {"placed": uw["ult_found"], "not_found": uw["ult"]}
    secs = {}
    for f in facts:
        if f["kind"] == "section":
            secs.setdefault(f["src"][0], set()).add((f["after"], f["value"]))
    if len(secs) == 2:
        a, b = secs.get("oshb", set()), secs.get("mam", set())
        out["sections"] = {"oshb": len(a), "mam": len(b), "same_word_same_mark": len(a & b),
                           "same_word": len({w for w, _ in a} & {w for w, _ in b})}
    forms = [f for f in facts if f["kind"] == "form" and "nestle1904" in f["src"]]
    if forms:
        out["nestle1904"] = {"passages": len(forms), "with_printed_lines": sum(1 for f in forms if f.get("lines") or f["value"] == "fm.ed.block"),
                             "span_only": sum(1 for f in forms if f.get("note"))}
    return out


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--licence", choices=["by-sa", "by"], default="by-sa",
                    help="by-sa (default): all facts, the export under CC BY-SA 4.0; by: only facts from sources that are not share-alike")
    ap.add_argument("--update-codes", action="store_true", help="give new open values (delivery, TBTA) the next code in codes.tsv")
    a = ap.parse_args(argv)
    codes, src = Codes(), sources()
    spans = [r for r in _tsv(SPEAKER_SPANS) if r["word_start"]]
    a.out.mkdir(parents=True, exist_ok=True)
    counts, dropped, checks = {}, collections.Counter(), {}
    for book in a.books:
        before = collections.Counter(unfoldingword.misses)
        facts = Builder(book, codes).build(spans)
        checks[book] = book_checks(facts, collections.Counter(unfoldingword.misses) - before)
        if codes.new:
            if not a.update_codes:
                raise SystemExit(f"new values without a code (run with --update-codes): {dict(codes.new)}")
            src_of = {k: OPEN_SRC.get(k, "tbta") for k in OPEN}
            print(f"{codes.assign(src_of)} codes added to {CODES}")
            facts = Builder(book, Codes()).build(spans)
        known = Codes().known
        for f in facts:
            for v in [f["value"], f["basis"], f["precision"], f.get("found"), f.get("speaker_by"), f.get("start"), f.get("end")]:
                assert v is None or v in known or f["kind"] == "frame", f"{f['id']}: {v} not in codes.tsv"
            assert all(s in src and src[s]["enabled"] == "1" for s in f["src"]), f"{f['id']}: source not enabled: {f['src']}"
        if a.licence == "by":
            keep = [f for f in facts if all(src[s]["share_alike"] == "0" for s in f["src"])]
            dropped[book] = len(facts) - len(keep)
            facts = keep
        with open(a.out / f"{book}.jsonl", "w", encoding="utf-8") as fh:
            for f in facts:
                fh.write(json.dumps(f, ensure_ascii=False, separators=(",", ":")) + "\n")
        counts[book] = dict(collections.Counter(f["kind"] for f in facts))
        print(book, len(facts), counts[book])
    used = sorted({s for b in a.books for f in map(json.loads, open(a.out / f"{b}.jsonl", encoding="utf-8")) for s in f["src"]})
    code = subprocess.run(["git", "log", "-1", "--format=%h", "--", "macula/build_passage_facts.py"], cwd=HERE.parent, text=True,
                          capture_output=True).stdout.strip()
    build = {"schema": SCHEMA, "built": datetime.date.today().isoformat(), "code": code,
             "licence": "CC BY-SA 4.0" if a.licence == "by-sa" else "CC BY 4.0",
             "sources": {s: {k: src[s][k] for k in ("name", "licence", "share_alike", "attribution")} for s in used},
             "inputs": {"macula-spine.db": sha256(SPINE), "trees-macula.db": sha256(TREES),
                        "speaker-layer quotations.tsv": sha256(LAYER / "quotations.tsv"), "speaker_quotations.tsv": sha256(SPEAKER_SPANS),
                        "nestle1904_layout.tsv": sha256(nestle1904_layout.TABLE), "nestle1904 xhtml": nestle1904_layout.PIN,
                        "engbsb_usfm.zip": sha256(BSB_ZIP) if BSB_ZIP.exists() else None,
                        "unfoldingWord": f"en_ult, en_tn tag {unfoldingword.TAG}", "MAM": f"MAM-basics {mam.PIN}"},
             "unmatched": dict(unfoldingword.misses),
             "tbta": "enabled" if src["tbta"]["enabled"] == "1" else "disabled (no licence)",
             "books": counts, "dropped_share_alike": dict(dropped), "checks": checks}
    (a.out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for p in (CODES, SOURCES, README):
        if p.exists():
            (a.out / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
