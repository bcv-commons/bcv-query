#!/usr/bin/env python3
"""Speech framing per clause: where a quotation opens, and how the source introduces it (wave 2, development-phase plan; asked for
by make-tanakh-research 2026-11-13 for Swahili quotation introducers such as kwamba / akisema).

    cd shoresh && .venv/bin/python3 -m macula.build_quote_frames

One row per layout clause (Hebrew clause_key, Greek first, as in bcv-commons/clause-columns):
  quote          the quotation the clause stands in ('' in narration): Hebrew speaker-layer id, Greek layout quotation id
  level          quotation level (Hebrew speaker layer; Greek 1 inside a quotation)
  opens          1 when a quotation starts in this clause (its first clause), else 0
  inquit         1 for the clause that introduces the next opening quotation: the last clause before it in the same verse or the
                 verse before, outside that quotation, with a verb of speaking or the introducer לֵאמֹר / λέγων
  inquit_form    how the inquit is made: lemor (Hebrew לֵאמֹר, "saying"), legon (Greek λέγων / λέγοντες ... participle of λέγω),
                 hoti (Greek ὅτι opening the quotation, recitative), finite (a finite verb of speaking: וַיֹּאמֶר, εἶπεν), '' otherwise
  speech_verb    the inquit's verb of speaking (word id), '' when none
Output: macula/data/quote-frames/{clauses.tsv, checks.md, build.json} (git-ignored). Not read: BHSA, TBTA, English text.
"""
from __future__ import annotations

import collections
import csv
import datetime
import json
import sqlite3
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "quote-frames"
MSPINE = HERE / "macula-spine.db"
SPEAK_HBO = {"0559", "1696", "7121", "6680", "6030", "7592", "5046", "2199", "6817", "6419", "0560", "4449"}
SPEAK_GRC = {"λέγω", "εἶπον", "φημί", "λαλέω", "ἀποκρίνομαι", "κράζω", "ἐρωτάω", "ἐπερωτάω", "παρακαλέω", "κηρύσσω", "διδάσκω",
             "γράφω", "βοάω", "φωνέω", "προσεύχομαι", "ἀπαγγέλλω", "μαρτυρέω", "ὁμολογέω", "ἐντέλλομαι", "παραγγέλλω"}
COLS = ["corpus", "clause_key", "quote", "level", "opens", "inquit", "inquit_form", "speech_verb"]


def main() -> int:
    m = sqlite3.connect(f"file:{MSPINE}?mode=ro", uri=True)
    info = {k: (lang, cls or "", (st or "").zfill(4)[:4] if lang == "hbo" else "", lem or "", mood or "")
            for k, lang, cls, st, lem, mood in m.execute("select key, lang, class, strong, lemma, mood from macula_words")}
    seg = {}
    for f in sorted((DATA / "speaker-layer/segments").glob("*.tsv")):
        for r in csv.DictReader(open(f, encoding="utf-8"), delimiter="\t"):
            seg.setdefault(r["clause_key"], (r["quotation"], r["level"] or "0"))
    clauses = []                                                   # (corpus, key, words, quote, level, verse key)
    for corpus, sub, field in (("hbo", "clause-layout", "clause_key"), ("grc", "nt-clause-layout", "first")):
        for f in sorted((DATA / sub / "clauses").glob("*/*.jsonl")):
            acc = collections.OrderedDict()
            for line in open(f, encoding="utf-8"):
                r = json.loads(line)
                k = r[field]
                if k in acc:
                    acc[k][2].extend(r["words"])
                    continue
                if corpus == "hbo":
                    q, lv = seg.get(k, ("", "0"))
                else:
                    q, lv = (r["quotation"] or ""), ("1" if r["quotation"] else "0")
                acc[k] = [corpus, k, list(r["words"]), q, lv]
            clauses += list(acc.values())

    def speech(ws):
        """(form, verb) of the clause's way of introducing speech"""
        form, verb = "", ""
        for w in ws:
            lang, cls, st, lem, mood = info.get(w, ("", "", "", "", ""))
            if lang == "hbo" and cls == "verb" and st in SPEAK_HBO:
                verb = verb or w
            if lang == "grc" and cls == "verb" and lem in SPEAK_GRC:
                verb = verb or w
                if lem == "λέγω" and mood == "participle":
                    form = "legon"
        for w in ws:
            lang, cls, st, lem, mood = info.get(w, ("", "", "", "", ""))
            if lang == "hbo" and lem == "אָמַר" and cls == "verb" and w == verb and _infinitive(w):
                form = "lemor"
        return (form or ("finite" if verb else "")), verb
    lf = sqlite3.connect(f"file:{HERE / 'lowfat-hbo.db'}?mode=ro", uri=True)
    inf_c = {k for (k,) in lf.execute("select key from lowfat_words where morph like 'V_c%'")}
    global _infinitive
    _infinitive = lambda w: w in inf_c                       # noqa: E731
    rows, st = [], collections.Counter()
    prev_q = {}
    for i, (corpus, k, ws, q, lv) in enumerate(clauses):
        opens = bool(q) and prev_q.get(corpus) != q and not any(c[3] == q for c in clauses[max(0, i - 40):i] if c[0] == corpus)
        prev_q[corpus] = q
        rows.append([corpus, k, q, lv, "1" if opens else "0", "0", "", ""])
        if opens:
            st[(corpus, "opens")] += 1
            # the inquit: walk back over clauses outside this quotation, in the same or the previous verse
            hoti = corpus == "grc" and info.get(ws[0], ("", "", "", "", ""))[3] == "ὅτι"
            for j in range(i - 1, max(-1, i - 6), -1):
                c = clauses[j]
                if c[0] != corpus or c[3] == q or c[1][:5] != k[:5]:
                    break
                form, verb = speech(c[2])
                if verb or form:
                    form = "hoti" if hoti else form
                    rows[j][5], rows[j][6], rows[j][7] = "1", form, verb
                    st[(corpus, "inquit:" + form)] += 1
                    break
            else:
                st[(corpus, "no_inquit")] += 1
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "clauses.tsv", "w", encoding="utf-8") as f:
        f.write("\t".join(COLS) + "\n")
        f.writelines("\t".join(r) + "\n" for r in rows)
    lines = ["# Quotation frames: checks", "", f"Clauses: {len(rows):,}.", "", "| corpus | value | count |", "|---|---|---|"]
    lines += [f"| {c} | {v} | {n:,} |" for (c, v), n in sorted(st.items())]
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = subprocess.run(["git", "log", "-1", "--format=%h"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    (OUT / "build.json").write_text(json.dumps({"schema": 1, "built": datetime.date.today().isoformat(), "code": code,
                                                "not_read": ["BHSA", "TBTA", "English text"]}, indent=1) + "\n")
    print("\n".join(lines))
    return 0


def _infinitive(w):          # replaced in main once the Hebrew morph codes are read
    return False


if __name__ == "__main__":
    raise SystemExit(main())
