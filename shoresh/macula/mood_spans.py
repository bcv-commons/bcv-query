"""Mood spans per chapter, read by a model against the moods of resources/passage_moods/moods_he.toml (asked by
bible-song-builder, 2026-11-24). The reader sees only the Hebrew or Greek clause lines and the Hebrew definitions.

    python -I macula/mood_spans.py prepare --out DIR [--chapters GEN.22 EXO.15 ...]
    python -I macula/mood_spans.py check   --out DIR --pass a --model claude-opus-5-5
    python -I macula/mood_spans.py compare --out DIR

prepare  writes DIR/input/<BOOK>.<ch>.txt (one numbered clause line per row: n, verse, quotation id, speaker, text) and
         DIR/input/<BOOK>.<ch>.keys.json (n -> first and last word key of the row, as in hebrew-clause-lines /
         greek-nt-clause-lines v0.3).
check    reads the reader's answers DIR/answers/<pass>/<BOOK>.<ch>.json and writes DIR/<pass>.jsonl, refusing what breaks a rule:
         an unknown mood id, a span outside the chapter, a strength not 1-3, a `because` whose words are not in the span's text,
         a `unit` that is not a quotation of the span.
compare  joins two passes: a span of pass a agrees where pass b has a span with the same mood (as mood or second) over at
         least half of its lines; writes DIR/spans.jsonl with `agree`, and the notes of sources that already name a mood
         (passage-facts mood, cue, delivery, psalm heading forms) by rule.
Answer file: {"chapter_mood": id | "none", "chapter_strength": 1-3, "chapter_because": "words of the chapter",
              "spans": [{"from": n, "to": n, "mood": id, "second": id | null, "strength": 1-3, "because": "words of the span",
                         "unit": quotation id | null}]}
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MOODS = ROOT / "resources" / "passage_moods" / "moods_he.toml"
LINES = {"hbo": HERE / "data" / "releases-2026-11-24" / "clause-lines-hbo-v0.3" / "data",
         "grc": HERE / "data" / "releases-2026-11-24" / "clause-lines-grc-v0.3" / "data"}
FACTS = HERE / "data" / "releases-2026-11-24" / "passage-facts-v0.3.4" / "data"
SAMPLE = "GEN.22 EXO.15 RUT.1 PSA.22 PSA.23 PSA.136 JON.2 LAM.1 MAT.27 LUK.1 REV.5".split()
NT = set("MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP COL 1TH 2TH 1TI 2TI TIT PHM HEB JAS 1PE 2PE 1JN 2JN 3JN JUD REV".split())


def mood_ids() -> set[str]:
    return set(tomllib.loads(MOODS.read_text(encoding="utf-8"))["moods"])


def norm(s: str) -> list[str]:
    """Words without points, accents, cantillation and punctuation, final letters as medial, Greek in lower case."""
    s = unicodedata.normalize("NFD", s.replace("־", " "))
    s = "".join(ch for ch in s if not unicodedata.category(ch).startswith("M")).lower()
    s = s.translate(str.maketrans("ךםןףץ", "כמנפצ"))
    return re.findall(r"[א-ת]+|[α-ωϲ]+", s)


def rows(book: str, ch: int) -> list[dict]:
    import pyarrow.parquet as pq
    lang = "grc" if book in NT else "hbo"
    t = pq.read_table(LINES[lang] / f"lines-{book}.parquet",
                      columns=["chapter", "verse", "seg", "line", "first", "last", "text", "quotation", "speaker"])
    out = [r for r in t.to_pylist() if r["chapter"] == ch]
    out.sort(key=lambda r: (r["seg"], r["line"]))
    return out


def prepare(a) -> None:
    inp = a.out / "input"
    inp.mkdir(parents=True, exist_ok=True)
    for c in a.chapters:
        book, ch = c.split(".")
        rs = rows(book, int(ch))
        assert rs, f"no lines for {c}"
        with open(inp / f"{c}.txt", "w", encoding="utf-8") as fh:
            fh.write("n\tverse\tquotation\tspeaker\ttext\n")
            for n, r in enumerate(rs, 1):
                fh.write(f"{n}\t{r['verse']}\t{r['quotation'] or '-'}\t{r['speaker'] or '-'}\t{r['text']}\n")
        keys = {n: {"first": r["first"], "last": r["last"], "verse": r["verse"], "quotation": r["quotation"]} for n, r in enumerate(rs, 1)}
        (inp / f"{c}.keys.json").write_text(json.dumps(keys, ensure_ascii=False) + "\n", encoding="utf-8")
        print(c, len(rs), "lines")


def check(a) -> int:
    ids, refused, out = mood_ids(), [], []
    for f in sorted((a.out / "input").glob("*.keys.json")):
        c = f.name[: -len(".keys.json")]
        keys = {int(k): v for k, v in json.loads(f.read_text(encoding="utf-8")).items()}
        text = {int(l.split("\t")[0]): l.rstrip("\n").split("\t")[4]
                for l in list(open(a.out / "input" / f"{c}.txt", encoding="utf-8"))[1:]}
        ans_f = a.out / "answers" / a.pass_ / f"{c}.json"
        if not ans_f.exists():
            refused.append((c, None, "no answer file"))
            continue
        ans = json.loads(ans_f.read_text(encoding="utf-8"))
        cm = ans.get("chapter_mood")
        allw = {w for n in text for w in norm(text[n])}
        if cm != "none" and cm not in ids:
            refused.append((c, "chapter", f"unknown mood {cm}"))
            cm = None
        cb = ans.get("chapter_because") or ""
        if cm not in (None, "none") and not (norm(cb) and set(norm(cb)) <= allw):
            refused.append((c, "chapter", "chapter_because not words of the chapter"))
        out.append({"chapter": c, "kind": "chapter", "mood": cm, "strength": ans.get("chapter_strength"), "because": cb,
                    "first": keys[1]["first"], "last": keys[max(keys)]["last"], "pass": a.pass_, "model": a.model})
        for i, s in enumerate(ans.get("spans") or []):
            why = None
            lo, hi = s.get("from"), s.get("to")
            if not (isinstance(lo, int) and isinstance(hi, int) and 1 <= lo <= hi <= max(keys)):
                why = f"span {lo}-{hi} outside 1-{max(keys)}"
            elif s.get("mood") not in ids or (s.get("second") not in (None, *ids)) or s.get("second") == s.get("mood"):
                why = f"mood {s.get('mood')} / second {s.get('second')}"
            elif s.get("strength") not in (1, 2, 3):
                why = f"strength {s.get('strength')}"
            else:
                span_w = {w for n in range(lo, hi + 1) for w in norm(text[n])}
                bw = norm(s.get("because") or "")
                if not bw or not set(bw) <= span_w:
                    why = "because not words of the span"
                elif s.get("unit") and s["unit"] not in {keys[n]["quotation"] for n in range(lo, hi + 1)}:
                    why = f"unit {s['unit']} not a quotation of the span"
            if why:
                refused.append((c, i, why))
                continue
            out.append({"chapter": c, "kind": "span", "from": lo, "to": hi, "first": keys[lo]["first"], "last": keys[hi]["last"],
                        "verses": [keys[lo]["verse"], keys[hi]["verse"]], "mood": s["mood"], "second": s.get("second"),
                        "strength": s["strength"], "because": s["because"], "unit": s.get("unit"), "pass": a.pass_, "model": a.model})
    with open(a.out / f"{a.pass_}.jsonl", "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(a.out / f"{a.pass_}.refused.tsv", "w", encoding="utf-8") as fh:
        for r in refused:
            fh.write("\t".join(map(str, r)) + "\n")
    n = sum(r["kind"] == "span" for r in out)
    print(f"pass {a.pass_}: {n} spans, {sum(r['kind'] == 'chapter' for r in out)} chapter readings, {len(refused)} refused")
    for r in refused:
        print("  refused", *r)
    return 1 if refused else 0


def source_notes(c: str, lo_key: str, hi_key: str) -> list[dict]:
    book = c.split(".")[0]
    f = FACTS / f"{book}.jsonl"
    out = []
    for l in open(f, encoding="utf-8"):
        r = json.loads(l)
        v = str(r.get("value") or "")
        if r["kind"] in ("mood", "cue", "delivery") or (r["kind"] == "form" and v[:6] in ("fm.ps.", "fm.gn.", "fm.pu.")):
            if r.get("first") and lo_key <= r["first"] <= hi_key:
                out.append({"fact": r["id"], "kind": r["kind"], "value": v, "first": r["first"], "last": r.get("last")})
    return out


def compare(a) -> None:
    A = [json.loads(l) for l in open(a.out / "a.jsonl", encoding="utf-8")]
    B = [json.loads(l) for l in open(a.out / "b.jsonl", encoding="utf-8")]
    out, stat = [], {"a spans": 0, "a agreed": 0, "b spans": 0, "b agreed": 0, "chapters": 0, "chapter agreed": 0}

    def agrees(s, others):
        lines = set(range(s["from"], s["to"] + 1))
        for o in others:
            if o["kind"] == "span" and o["chapter"] == s["chapter"] and s["mood"] in (o["mood"], o.get("second")):
                if len(lines & set(range(o["from"], o["to"] + 1))) * 2 >= len(lines):
                    return True
        return False

    for P, Q, name in ((A, B, "a"), (B, A, "b")):
        for s in P:
            if s["kind"] == "chapter":
                if name == "a":
                    o = next((x for x in Q if x["kind"] == "chapter" and x["chapter"] == s["chapter"]), None)
                    stat["chapters"] += 1
                    ok = bool(o) and o["mood"] == s["mood"]
                    stat["chapter agreed"] += ok
                    out.append({**s, "agree": ok, "other_mood": o["mood"] if o else None})
                continue
            ok = agrees(s, Q)
            stat[f"{name} spans"] += 1
            stat[f"{name} agreed"] += ok
            out.append({**s, "agree": ok})
    chapters = {s["chapter"]: (s["first"], s["last"]) for s in A if s["kind"] == "chapter"}
    with open(a.out / "spans.jsonl", "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(a.out / "source_notes.jsonl", "w", encoding="utf-8") as fh:
        for c, (lo, hi) in chapters.items():
            for n in source_notes(c, lo, hi):
                fh.write(json.dumps({"chapter": c, **n}, ensure_ascii=False) + "\n")
    print(stat)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["prepare", "check", "compare"])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--chapters", nargs="+", default=SAMPLE)
    ap.add_argument("--pass", dest="pass_", choices=["a", "b"])
    ap.add_argument("--model")
    a = ap.parse_args()
    if a.step == "prepare":
        prepare(a)
        return 0
    if a.step == "check":
        assert a.pass_ and a.model, "--pass and --model"
        return check(a)
    compare(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
