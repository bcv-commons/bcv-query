"""Model reading of the Psalms commentaries' openings (hebrew-commentary-terms P2): what each commentator says a psalm is.

    cd shoresh && .venv/bin/python -m macula.commentary_model prepare --out DIR          # units.jsonl (psalm x witness), no calls
    cd shoresh && .venv/bin/python -m macula.commentary_model cli --out DIR [--limit N] [--cap USD] [--workers 3]
    cd shoresh && .venv/bin/python -m macula.commentary_model collect --out DIR          # statements.jsonl, checked

The model (Claude Opus through Claude Code's headless mode, the user's subscription) reads one commentator's comments on a
psalm's first two verses (Hebrew, as Sefaria's open-licence version prints them) and lists what the commentator states the psalm
is: its kind, its voice, the occasion it was said on, a turn inside it. Every statement must copy the commentator's own words:
`term` (1-4 words) inside `quote` inside the text, and a `citation` inside the text that parses as a Tanakh verse. Anything
that fails the check is dropped and counted. No English is given to the model or kept; the instructions are English.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

from macula import build_commentary_terms as ct, hebrew_refs

MODEL = "claude-opus-5-5"
EFFORT = "medium"
MAX_CHARS = 3500
SAYS = ["kind", "voice", "occasion", "turn"]
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["statements"],
          "properties": {"statements": {"type": "array", "items": {
              "type": "object", "additionalProperties": False,
              "required": ["says", "term", "quote", "citation", "register", "at_verse"],
              "properties": {"says": {"type": "string", "enum": SAYS}, "term": {"type": "string"}, "quote": {"type": "string"},
                             "citation": {"type": "string"}, "register": {"type": "string", "enum": ["peshat", "derash"]},
                             "at_verse": {"type": "integer"}}}}}}
SYSTEM = ("You read the opening comments of a classical Hebrew commentary on one psalm and record what the commentator states "
          "about the psalm as a whole. Kinds of statement (says):\n"
          "- kind: what the psalm is (for example a prayer, praise, thanksgiving, lament, rebuke, prophecy), in the commentator's word;\n"
          "- voice: who says the psalm or in whose name (David, the exile, any person in distress, Israel, the days to come …);\n"
          "- occasion: the event or situation it was said on;\n"
          "- turn: where the commentator says the psalm turns from one matter or mood to another (at_verse = that verse).\n"
          "For each statement copy the commentator's own words exactly: term = the 1-4 words that name it; quote = the part of the "
          "sentence that states it (at most 25 words, containing the term); citation = the parenthesised verse reference the "
          "statement gives, copied exactly with its parentheses, or an empty string. register = derash where the commentator "
          "gives it as a midrash or the sages' reading, else peshat. at_verse = 0 except for turn. Explanations of single words "
          "or of the heading's musical terms are not statements about the psalm. If the comments state none of these, return an "
          "empty list. Answer only in the JSON form asked for.")


def _n(s: str) -> str:
    return re.sub(r"\s+", " ", hebrew_refs.norm(s)).strip()


def prepare(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    units = []
    for work in ct.PSALM_WORKS:
        for n in range(1, 151):
            got = ct.psalm_opening(work, n)
            if not got or not got[0]:
                continue
            comments, lic = got
            text, loci = "", []
            for locus, t in comments:
                if len(text) + len(t) > MAX_CHARS and text:
                    break
                text += t + "\n"
                loci.append(locus)
            units.append({"id": f"{work}_{n}", "work": work, "psalm": n, "loci": loci, "licence": lic, "text": text.strip()})
    (out / "units.jsonl").write_text("".join(json.dumps(u, ensure_ascii=False) + "\n" for u in units), encoding="utf-8")
    print(len(units), "units;", sum(len(u["text"]) for u in units), "chars")


def _one(u: dict, cwd: str) -> dict:
    import os
    import subprocess
    import time
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    cmd = ["claude", "-p", "--model", MODEL, "--effort", EFFORT, "--no-session-persistence", "--output-format", "json",
           "--system-prompt", SYSTEM, "--tools", "", "--json-schema", json.dumps(SCHEMA)]
    prompt = f"תהלים {u['psalm']}\n\n{u['text']}"
    err = ""
    for attempt in range(4):
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, env=env, cwd=cwd, timeout=900)
            out = json.loads(proc.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            err = str(e)[:200]
            time.sleep(min(2 ** attempt * 10, 120))
            continue
        if out.get("is_error"):
            err = str(out.get("result"))[:300]
            if any(x in err.lower() for x in ("login", "limit", "credit")):
                return {"id": u["id"], "error": err, "fatal": True}
            time.sleep(min(2 ** attempt * 10, 120))
            continue
        so = out.get("structured_output")
        if so is None:
            try:
                so = json.loads(out.get("result") or "{}")
            except json.JSONDecodeError:
                so = None
        return {"id": u["id"], "answer": so, "cost_usd": out.get("total_cost_usd", 0), "usage": out.get("usage", {})}
    return {"id": u["id"], "error": err}


def cli(out: Path, cap: float, limit: int | None, workers: int) -> None:
    import concurrent.futures
    import tempfile
    units = [json.loads(l) for l in (out / "units.jsonl").open(encoding="utf-8")]
    raw = out / "raw.jsonl"
    done = {}
    if raw.exists():
        for l in raw.open(encoding="utf-8"):
            x = json.loads(l)
            if x.get("answer") is not None:
                done[x["id"]] = x
    spent = sum(x.get("cost_usd", 0) or 0 for x in done.values())
    todo = [u for u in units if u["id"] not in done][: limit or None]
    print(f"{len(done)} done (USD {spent:.2f}); {len(todo)} to run; cap USD {cap}", flush=True)
    cwd = tempfile.mkdtemp(prefix="commentary-model-")
    stop, it, running = False, iter(todo), set()
    with raw.open("a", encoding="utf-8") as f, concurrent.futures.ThreadPoolExecutor(workers) as ex:
        while True:
            while not stop and len(running) < workers:
                u = next(it, None)
                if u is None:
                    break
                running.add(ex.submit(_one, u, cwd))
            if not running:
                break
            fin, running = concurrent.futures.wait(running, return_when=concurrent.futures.FIRST_COMPLETED)
            for fu in fin:
                x = fu.result()
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
                f.flush()
                spent += x.get("cost_usd", 0) or 0
                if x.get("fatal"):
                    print("fatal:", x["error"], flush=True)
                    stop = True
                if spent >= cap:
                    stop = True
            print(f"  USD {spent:.2f}", flush=True)
    print(f"stopped={stop}; USD {spent:.2f}")


def collect(out: Path) -> dict:
    units = {u["id"]: u for u in (json.loads(l) for l in (out / "units.jsonl").open(encoding="utf-8"))}
    raw = {}
    for l in (out / "raw.jsonl").open(encoding="utf-8"):
        x = json.loads(l)
        if x.get("answer") is not None:
            raw[x["id"]] = x
    rows, st = [], collections.Counter()
    for uid, x in raw.items():
        u = units[uid]
        text = _n(u["text"])
        span = ct.psalm_span(u["psalm"])
        for s in x["answer"].get("statements", []):
            st["given"] += 1
            term, quote, cit = _n(s["term"]), _n(s["quote"]), _n(s["citation"])
            if not term or term not in quote or quote not in text:
                st["dropped_not_copied"] += 1
                continue
            if len(term.split()) > 4:
                st["dropped_long_term"] += 1
                continue
            obj = (None, None)
            if cit:
                refs = hebrew_refs.find(cit) if cit in text else []
                if not refs:
                    st["citation_dropped"] += 1
                else:
                    b, c, v = refs[0][2:]
                    obj = ct.verse_span(b, c, v) or (None, None)
                    st["citation_kept" if obj[0] else "citation_unresolved"] += 1
            if s["says"] == "turn" and not (1 <= s["at_verse"] <= 200):
                st["dropped_turn_no_verse"] += 1
                continue
            locus = next((l for l in u["loci"]), None)
            subj = span
            if s["says"] == "turn":
                vs = ct.verse_span("PSA", u["psalm"], s["at_verse"])
                if not vs:
                    st["dropped_turn_no_verse"] += 1
                    continue
                subj = vs
            rows.append({"subject_first": subj[0], "subject_last": subj[1], "says": s["says"], "term": term,
                         "object_first": obj[0], "object_last": obj[1], "witness": u["work"], "locus": locus,
                         "formula": "", "register": s["register"], "anchor": "model", "quote": quote,
                         "citation": cit or None, "licence": u["licence"]})
            st["kept", s["says"]] += 1
    with (out / "statements.jsonl").open("w", encoding="utf-8") as f:
        for i, r in enumerate(rows, start=1):
            f.write(json.dumps({"id": f"m{i:06d}", **r}, ensure_ascii=False) + "\n")
    cost = sum(x.get("cost_usd", 0) or 0 for x in raw.values())
    res = {"units_answered": len(raw), "statements": len(rows), "usd_reported": round(cost, 2), **{str(k): v for k, v in st.items()}}
    (out / "collect.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["prepare", "cli", "collect"])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cap", type=float, default=15.0)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    if a.step == "prepare":
        prepare(a.out)
    elif a.step == "cli":
        cli(a.out, a.cap, a.limit, a.workers)
    else:
        print(json.dumps(collect(a.out), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
