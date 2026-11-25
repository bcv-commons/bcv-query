"""Mood spans per chapter, read by a model against the moods of resources/passage_moods/moods_he.toml (asked by
bible-song-builder, 2026-11-24). The reader sees only the Hebrew or Greek clause lines and the Hebrew definitions.

    python -I macula/mood_spans.py prepare --out DIR [--chapters GEN.22 EXO.15 ... | all] [--batch-lines 3000]
    python -I macula/mood_spans.py check   --out DIR --pass a --model claude-opus-5-5 [--batch b01] [--max-share3 0.3]
    python -I macula/mood_spans.py compare --out DIR

prepare  writes DIR/input/<BOOK>.<ch>.txt (one numbered clause line per row: n, verse, quotation id, speaker, text) and
         DIR/input/<BOOK>.<ch>.keys.json (n -> first and last word key of the row, as in hebrew-clause-lines /
         greek-nt-clause-lines v0.3). With --batch-lines, also DIR/batches.json: the chapters in batches of about that many
         lines, in Bible order, the sample chapters first (batch b01), so the first batch tests the rules on known chapters.
check    reads the reader's answers DIR/answers/<pass>/<BOOK>.<ch>.json and writes DIR/<pass>.jsonl, refusing what breaks a rule:
         an unknown mood id, a span outside the chapter, a strength not 1-3, a `because` whose words are not in the span's text,
         a `unit` that is not a quotation of the span. With --batch, only that batch's chapters, written to
         DIR/checked/<pass>/<batch>.jsonl; --max-share3 also fails the check where more than that share of spans has strength 3.
compare  joins two passes: a span of pass a agrees where pass b has a span with the same mood (as mood or second) over at
         least half of its lines; writes DIR/spans.jsonl with `agree`, and the notes of sources that already name a mood
         (passage-facts mood, cue, delivery, psalm heading forms) by rule.
Answer file: {"chapter_mood": id | "none", "chapter_strength": 1-3, "chapter_because": "words of the chapter",
              "spans": [{"from": n, "to": n, "mood": id, "second": id | null, "strength": 1-3, "because": "words of the span",
                         "unit": quotation id | null}]}
"""
from __future__ import annotations

import argparse
import functools
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


@functools.lru_cache(maxsize=4)
def book_rows(book: str) -> list[dict]:
    import pyarrow.parquet as pq
    lang = "grc" if book in NT else "hbo"
    return pq.read_table(LINES[lang] / f"lines-{book}.parquet",
                         columns=["chapter", "verse", "seg", "line", "first", "last", "text", "quotation", "speaker"]).to_pylist()


def all_chapters() -> list[str]:
    out = []
    for lang in ("hbo", "grc"):
        for f in LINES[lang].glob("lines-*.parquet"):
            book = f.stem[len("lines-"):]
            rs = book_rows(book)
            first = min(r["first"] for r in rs)
            out += [(first[:2], ch, f"{book}.{ch}") for ch in sorted({r["chapter"] for r in rs})]
    return [c for _, _, c in sorted(out)]


def rows(book: str, ch: int) -> list[dict]:
    out = [r for r in book_rows(book) if r["chapter"] == ch]
    out.sort(key=lambda r: (r["seg"], r["line"]))
    return out


def prepare(a) -> None:
    inp = a.out / "input"
    inp.mkdir(parents=True, exist_ok=True)
    if a.chapters == ["all"]:
        a.chapters = all_chapters()
    size = {}
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
        size[c] = len(rs)
    print(len(size), "chapters,", sum(size.values()), "lines")
    if a.batch_lines:
        order = [c for c in SAMPLE if c in size] + [c for c in a.chapters if c not in SAMPLE]
        batches, cur, n = [], [], 0
        for c in order:
            if cur and n + size[c] > a.batch_lines:
                batches.append({"chapters": cur, "lines": n})
                cur, n = [], 0
            cur.append(c)
            n += size[c]
        if cur:
            batches.append({"chapters": cur, "lines": n})
        out = {f"b{i:02d}": b for i, b in enumerate(batches, 1)}
        (a.out / "batches.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(len(out), "batches")


def check(a) -> int:
    ids, refused, out = mood_ids(), [], []
    want = None
    if a.batch:
        want = set(json.loads((a.out / "batches.json").read_text(encoding="utf-8"))[a.batch]["chapters"])
    for f in sorted((a.out / "input").glob("*.keys.json")):
        c = f.name[: -len(".keys.json")]
        if want is not None and c not in want:
            continue
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
    if a.batch:
        (a.out / "checked" / a.pass_).mkdir(parents=True, exist_ok=True)
        dest, rdest = a.out / "checked" / a.pass_ / f"{a.batch}.jsonl", a.out / "checked" / a.pass_ / f"{a.batch}.refused.tsv"
    else:
        dest, rdest = a.out / f"{a.pass_}.jsonl", a.out / f"{a.pass_}.refused.tsv"
    import hashlib
    sha = hashlib.sha256(MOODS.read_bytes()).hexdigest()[:12]
    for r in out:
        r["moods_sha"] = sha
    with open(dest, "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(rdest, "w", encoding="utf-8") as fh:
        for r in refused:
            fh.write("\t".join(map(str, r)) + "\n")
    n = sum(r["kind"] == "span" for r in out)
    print(f"pass {a.pass_}: {n} spans, {sum(r['kind'] == 'chapter' for r in out)} chapter readings, {len(refused)} refused")
    for r in refused:
        print("  refused", *r)
    spans = [r for r in out if r["kind"] == "span"]
    share3 = sum(r["strength"] == 3 for r in spans) / max(1, len(spans))
    print(f"strength 3: {share3:.0%} of spans")
    if a.max_share3 is not None and share3 > a.max_share3:
        print(f"strength 3 above {a.max_share3:.0%}: the strength rule is not followed")
        return 1
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
    def load(p):
        if (a.out / "checked" / p).is_dir():
            return [json.loads(l) for f in sorted((a.out / "checked" / p).glob("b*.jsonl")) for l in open(f, encoding="utf-8")]
        return [json.loads(l) for l in open(a.out / f"{p}.jsonl", encoding="utf-8")]
    A, B = load("a"), load("b")
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
    ap.add_argument("--batch")
    ap.add_argument("--batch-lines", type=int)
    ap.add_argument("--max-share3", type=float)
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
