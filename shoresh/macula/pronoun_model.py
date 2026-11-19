"""Model step of the entity layer: which entity a pronoun refers to, where neither ACAI nor MACULA's reference chain says
(reference-status `unresolved`). Becomes bcv-commons/entity-mentions-model.

    cd shoresh && .venv/bin/python -m macula.pronoun_model prepare --em DIR --out RUN     # units.jsonl, no calls
    cd shoresh && .venv/bin/python -m macula.pronoun_model cli --out RUN [--limit N] [--cap USD] [--workers 3]
    cd shoresh && .venv/bin/python -m macula.pronoun_model collect --out RUN              # answers.jsonl, checked
    cd shoresh && .venv/bin/python -m macula.pronoun_model sample --out RUN               # sealed judge sample (no calls)

Scope: the unresolved words whose lemma is a personal, demonstrative, reflexive, reciprocal or relative pronoun (SCOPE).
Interrogatives (מָה, מִי, τίς), indefinites (τὶς) and words of quantity or quality (ὅσος, τοιοῦτος) are left out: they do not
refer to an entity.

One unit = up to 25 such words of one chapter. The model (Claude Opus through Claude Code's headless mode, the user's
subscription) gets the Hebrew or Greek text of each word's verse and the three verses before it, the words marked, every word
that entity-mentions links to an entity tagged with a candidate number, and the candidate list (the entities entity-mentions
has in this chapter and the one before: type, gender, Hebrew/Aramaic or Greek lemmas). It picks one candidate per word or
`none` with a reason code. Answers that name no listed candidate or no asked word are dropped and counted. No English text is
given to the model or kept; the instructions are English.
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPINE = HERE / "macula-spine.db"
RS = HERE / "data" / "bridge-corpus" / "inputs" / "reference-status@v0.2"
MODEL = "claude-opus-5-5"
EFFORT = "medium"
PER_UNIT = 25
BEFORE = 3
SCOPE = {"hbo": {"הוּא", "הִיא", "אֲנִי", "אָנֹכִי", "אַתָּה", "אַתְּ", "אַתֶּם", "אַתֵּן", "הֵם", "הֵמָּה", "הֵן", "הֵנָּה",
                 "אֲנַחְנוּ", "נַחְנוּ", "זֶה", "זֹאת", "אֵלֶּה"},
         "grc": {"αὐτός", "οὗτος", "ἐκεῖνος", "ὅδε", "ἐγώ", "σύ", "ἑαυτοῦ", "σεαυτοῦ", "ἐμαυτοῦ", "ἀλλήλων", "ὅς", "ὅστις"}}
REASONS = ["", "proposition", "not_listed", "unclear"]
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answers"],
          "properties": {"answers": {"type": "array", "items": {
              "type": "object", "additionalProperties": False, "required": ["item", "choice", "none_reason"],
              "properties": {"item": {"type": "integer"}, "choice": {"type": "string"},
                             "none_reason": {"type": "string", "enum": REASONS}}}}}}
SYSTEM = ("You read a passage of the Hebrew Bible or the Greek New Testament in its original language. Some words are marked "
          "⟦n word⟧ (n = item number); each is a pronoun or a pronoun suffix. Words already known to refer to an entity carry a "
          "tag ⟨cK⟩ after them, naming candidate cK. The candidate list gives each candidate's type, gender and lemmas. For "
          "every marked item decide which listed candidate the pronoun refers to, from the passage alone. choice = the "
          "candidate id (for example c3), or none. A first or second person pronoun refers to the speaker or the one spoken "
          "to. A relative pronoun refers to what its antecedent refers to. Plural pronouns: pick a group candidate only if "
          "it is the group meant; a plural that gathers several listed individuals gets none with not_listed. If none: "
          "none_reason = proposition (it points at a statement, event or matter, not an entity), not_listed (it refers to an "
          "entity that is not in the list), or unclear. If a candidate is chosen, none_reason is an empty string. Answer every "
          "item, only in the JSON form asked for.")


def _words():
    m = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    return {k: (b, c, v, t or "", lem or "", cl or "") for k, b, c, v, t, lem, cl in
            m.execute("select key, book, chapter, verse, text, lemma, class from macula_words")}


def prepare(out: Path, em: Path) -> None:
    import pyarrow.parquet as pq
    out.mkdir(parents=True, exist_ok=True)
    W = _words()
    verse_words = collections.defaultdict(list)
    for k, (b, c, v, *_) in W.items():
        verse_words[b, c, v].append(k)
    for ks in verse_words.values():
        ks.sort()
    ment = collections.defaultdict(list)                       # word key -> entity codes (any route)
    by_ch = collections.defaultdict(collections.Counter)        # (book, chapter) -> entity -> mentions
    named = collections.defaultdict(collections.Counter)        # (book, chapter, entity) -> lemmas of its noun mentions
    for r in pq.read_table(em / "data" / "mentions.parquet").to_pylist():
        if r["key"] in W:
            if r["entity"] not in ment[r["key"]]:
                ment[r["key"]].append(r["entity"])
            by_ch[W[r["key"]][:2]][r["entity"]] += 1
            if W[r["key"]][5] == "noun":
                named[W[r["key"]][:2] + (r["entity"],)][W[r["key"]][4]] += 1
                named[r["lang"], r["entity"]][W[r["key"]][4]] += 1
    ents = {e["entity"]: e for e in pq.read_table(em / "data" / "entities.parquet").to_pylist()}
    items = collections.defaultdict(list)
    skipped = collections.Counter()
    for f, lang in (("hebrew", "hbo"), ("greek-nt", "grc")):
        for r in pq.read_table(RS / "data" / f"{f}.parquet").to_pylist():
            if r["status"] != "unresolved":
                continue
            k = r["head"].lstrip("n")
            if W[k][4] not in SCOPE[lang]:
                skipped[lang, W[k][4]] += 1
                continue
            items[lang, W[k][0], W[k][1]].append(k)
    chapters = {}
    for b, c, _ in verse_words:
        chapters.setdefault(b, set()).add(c)
    units = []
    for (lang, b, c), ks in sorted(items.items()):
        ks.sort()
        prev = max((x for x in chapters[b] if x < c), default=None)
        cand_ents = [e for e, _ in (by_ch[b, c] + (by_ch[b, prev] if prev else collections.Counter())).most_common()]
        cid = {e: f"c{i}" for i, e in enumerate(cand_ents, start=1)}
        pre = "el:" if lang == "grc" else ("he:", "arc:")
        cands = []
        for e in cand_ents:
            x = ents[e]
            lem = list(dict.fromkeys(l.split(":", 1)[1] for l in x["lemmas"] if l.startswith(pre)))
            if not lem:                                          # ACAI has no lemma in this language: the chapter's own nouns
                got = named[b, c, e] + (named[b, prev, e] if prev else collections.Counter())
                lem = [l for l, _ in (got or named[lang, e]).most_common(3)]
            cands.append({"id": cid[e], "entity": e, "type": x["type"], "gender": x["gender"], "lemmas": lem[:4]})
        for i in range(0, len(ks), PER_UNIT):
            part = ks[i:i + PER_UNIT]
            num = {k: n for n, k in enumerate(part, start=1)}
            vs = sorted({x for k in part for x in range(max(1, W[k][2] - BEFORE), W[k][2] + 1) if (b, c, x) in verse_words})
            lines, last = [], None
            for v in vs:
                if last is not None and v != last + 1:
                    lines.append("…")
                last = v
                toks, cur = [], None
                for k in verse_words[b, c, v]:
                    word = k[:11] if lang == "hbo" else k
                    piece = f"⟦{num[k]} {W[k][3]}⟧" if k in num else W[k][3]
                    piece += "".join(f"⟨{cid[e]}⟩" for e in ment.get(k, []) if e in cid)
                    if word == cur:
                        toks[-1] += piece
                    else:
                        toks.append(piece)
                    cur = word
                lines.append(f"{v} " + " ".join(toks))
            units.append({"id": f"{lang}_{b}_{c}_{i // PER_UNIT}", "lang": lang, "book": b, "chapter": c,
                          "items": [{"item": num[k], "key": k} for k in part], "candidates": cands, "text": "\n".join(lines)})
    (out / "units.jsonl").write_text("".join(json.dumps(u, ensure_ascii=False) + "\n" for u in units), encoding="utf-8")
    sk = collections.Counter()
    for (lang, _), n in skipped.items():
        sk[lang] += n
    info = {"units": len(units), "items": sum(len(u["items"]) for u in units),
            "items_by_lang": dict(collections.Counter(u["lang"] for u in units for _ in u["items"])),
            "out_of_scope_by_lang": dict(sk), "chars": sum(len(_prompt(u)) for u in units)}
    (out / "prepare.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))


def _prompt(u: dict) -> str:
    cl = "\n".join(f"{c['id']} | {c['type']} | {c['gender'] or '-'} | {' '.join(c['lemmas'])}" for c in u["candidates"])
    return (f"{u['book']} {u['chapter']}\n\n{u['text']}\n\nCandidates:\n{cl or '(none)'}\n\n"
            f"Items: {', '.join(str(x['item']) for x in u['items'])}")


def _one(u: dict, cwd: str) -> dict:
    import os
    import subprocess
    import time
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    cmd = ["claude", "-p", "--model", MODEL, "--effort", EFFORT, "--no-session-persistence", "--output-format", "json",
           "--system-prompt", SYSTEM, "--tools", "", "--json-schema", json.dumps(SCHEMA)]
    err = ""
    for attempt in range(4):
        try:
            proc = subprocess.run(cmd, input=_prompt(u), capture_output=True, text=True, env=env, cwd=cwd, timeout=900)
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
    done, spent = {}, 0.0
    if raw.exists():
        for l in raw.open(encoding="utf-8"):
            x = json.loads(l)
            spent += x.get("cost_usd", 0) or 0
            if x.get("answer") is not None:
                done[x["id"]] = x
    todo = [u for u in units if u["id"] not in done][: limit or None]
    print(f"{len(done)} done (USD {spent:.2f}); {len(todo)} to run; cap USD {cap}", flush=True)
    cwd = tempfile.mkdtemp(prefix="pronoun-model-")
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
    raw, cost = {}, 0.0
    for l in (out / "raw.jsonl").open(encoding="utf-8"):
        x = json.loads(l)
        cost += x.get("cost_usd", 0) or 0
        if x.get("answer") is not None:
            raw[x["id"]] = x
    rows, st = [], collections.Counter()
    for uid, x in raw.items():
        u = units[uid]
        keys = {i["item"]: i["key"] for i in u["items"]}
        cands = {c["id"]: c["entity"] for c in u["candidates"]}
        seen = set()
        for a in x["answer"].get("answers", []):
            st["given"] += 1
            if a["item"] not in keys or a["item"] in seen:
                st["dropped_no_such_item"] += 1
                continue
            ch = a["choice"].strip()
            if ch != "none" and ch not in cands:
                st["dropped_no_such_candidate"] += 1
                continue
            seen.add(a["item"])
            ent = cands.get(ch)
            reason = "" if ent else (a["none_reason"] or "unclear")
            rows.append({"key": keys[a["item"]], "lang": u["lang"], "entity": ent, "none_reason": reason,
                         "candidates": len(cands), "unit": uid})
            st["kept_entity" if ent else f"kept_none_{reason}"] += 1
        st["items_unanswered"] += len(keys) - len(seen)
    rows.sort(key=lambda r: r["key"])
    with (out / "answers.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    res = {"units": len(units), "units_answered": len(raw), "rows": len(rows), "usd_reported": round(cost, 2), **dict(st)}
    (out / "collect.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def sample(out: Path, n: int = 60, seed: int = 1119) -> None:
    """A sealed sample per language for blind judges: the same unit text and candidates, one marked item each."""
    units = [json.loads(l) for l in (out / "units.jsonl").open(encoding="utf-8")]
    rnd = random.Random(seed)
    picked = []
    for lang in ("hbo", "grc"):
        pool = [(u, i) for u in units if u["lang"] == lang for i in u["items"]]
        picked += rnd.sample(pool, n)
    sd = out / f"sealed-{seed}"
    sd.mkdir()
    rows = []
    for j, (u, i) in enumerate(picked, start=1):
        rows.append({"sid": f"s{j:03d}", "key": i["key"], "lang": u["lang"], "unit": u["id"], "item": i["item"],
                     "prompt": _prompt(u).rsplit("\n\nItems:", 1)[0] + f"\n\nItems: {i['item']}"})
    (sd / "items.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(sd, len(rows))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=["prepare", "cli", "collect", "sample"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--em", help="an entity-mentions release folder (prepare)")
    ap.add_argument("--cap", type=float, default=45.0)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    out = Path(a.out)
    if a.step == "prepare":
        prepare(out, Path(a.em))
    elif a.step == "cli":
        cli(out, a.cap, a.limit, a.workers)
    elif a.step == "collect":
        print(json.dumps(collect(out), ensure_ascii=False, indent=1))
    else:
        sample(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
