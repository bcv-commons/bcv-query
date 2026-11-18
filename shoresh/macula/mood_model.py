"""Model rescue for the mood layer (from v0.3.1): a model reads the Hebrew or Greek text of a passage and names the mood families
the text marks there, with the words that mark them. Output only for the separate `passage-moods-model` dataset (the model named,
no human check); passage-facts itself keeps only the moods its rules find marked.

    cd shoresh && .venv/bin/python -m macula.mood_model prepare --facts <dry build>/data --out <dir>     # units.jsonl, no calls
    cd shoresh && .venv/bin/python -m macula.mood_model estimate --out <dir>                             # offline estimate, no calls
    cd shoresh && .venv/bin/python -m macula.mood_model count --out <dir>      # exact input tokens (count_tokens; free, no generation)
    cd shoresh && .venv/bin/python -m macula.mood_model submit --out <dir>     # Message Batches API: ONLY after the user's go
    cd shoresh && .venv/bin/python -m macula.mood_model collect --out <dir>    # results.jsonl, checked

Units (prepare):
  - source: a passage where a source names a feeling (Scriptura's At-a-Glance for a psalm section, a Glyssen delivery for a
    speech) but no Hebrew or Greek word in it marks that feeling's family by our rules;
  - hard: a rule-layer unit (macula/mood_rules.py) whose painful and pleasant evidence are within 1.5x of each other.
What the model sees: the text (pointed Hebrew without accents, or Greek), each word numbered "chapter:verse.word", and the
families by id and Hebrew/Greek head word with their commonest Hebrew and Greek lemmas. No English: no glosses, no definitions,
and never the source's own mood word (the source family is kept beside the unit only as the yardstick).
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

from macula import build_passage_facts as pf, mood_families as mf, mood_rules, scriptura

MODEL = "claude-opus-5-5"
EFFORT = "medium"
MAX_TOKENS = 8000
ACCENTS = re.compile(r"[֑-ֽ֯׀׃׆]")      # cantillation, meteg, paseq, sof pasuq, nun hafukha


def _text(book: str) -> dict[str, list[tuple[int, int, int, str, list[str]]]]:
    """Word (key without its part digit) -> (chapter, verse, word number, surface, [MACULA keys])."""
    sp = sqlite3.connect(pf.SPINE)
    words: dict[tuple, list] = {}
    for key, c, v, w, text in sp.execute("SELECT key, chapter, verse, word, text FROM macula_words WHERE book=? ORDER BY key", (book,)):
        k = (c, v, w)
        if k not in words:
            words[k] = ["", []]
        words[k][0] += ACCENTS.sub("", unicodedata.normalize("NFC", text or ""))
        words[k][1].append(key)
    return words


def lemmas_per_family(n: int = 8) -> dict[str, tuple[list[str], list[str]]]:
    """The commonest Hebrew and Greek lemmas each family's words have, to show the model (original-language only)."""
    sp = sqlite3.connect(pf.SPINE)
    cnt = {"h": collections.defaultdict(collections.Counter), "g": collections.defaultdict(collections.Counter)}
    for (b,) in sp.execute("SELECT DISTINCT book FROM macula_words"):
        bk = pf.Book(b)
        lem = dict(sp.execute("SELECT key, lemma FROM macula_words WHERE book=?", (b,)))
        for i, ms in mf.word_marks(b, bk).items():
            for f, _ in ms:
                cnt["h" if bk.hebrew else "g"][f][lem.get(bk.keys[i])] += 1
    return {f: ([l for l, _ in cnt["h"][f].most_common(n)], [l for l, _ in cnt["g"][f].most_common(n)]) for f in mf.FAMILIES}


def prepare(facts: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    units = []
    for p in sorted(facts.glob("*.jsonl")):
        book = p.stem
        rows = [json.loads(l) for l in p.open(encoding="utf-8")]
        bk = pf.Book(book)
        moods = [f for f in rows if f["kind"] == "mood"]
        published = {(f["first"], f["last"], f["value"]) for f in moods}
        from_delivery = {x for f in moods for x in f.get("from_facts") or []}
        label = {}
        for f in rows:
            if f["kind"] != "delivery" or f.get("scope") == "chapter" or f["id"] in from_delivery:
                continue
            m = _delivery_mood(f["value"])
            fam = mf.source_family(m) if m else None
            if fam:
                units.append({"id": f"{book}.s.{f['id']}", "book": book, "first": f["first"], "last": f["last"], "kind": "source",
                              "source": "glyssen", "yard": [fam], "context_before": True})
        if book == "PSA":
            last = collections.Counter()
            for c, v in bk.verses:
                last[c] = max(last[c], v)
            for n in range(1, 151):
                r = scriptura.read(n)
                for k, (a, nxt, labels) in enumerate((r or {}).get("moods", [])):
                    end = (nxt[0] - 1 if not nxt[1] or nxt[1] == "a" else nxt[0]) if nxt else last[n]
                    if (n, a[0]) not in bk.verses or (n, max(a[0], end)) not in bk.verses:
                        continue
                    first, lst = bk.keys[bk.verses[(n, a[0])][0]], bk.keys[bk.verses[(n, max(a[0], end))][1]]
                    fams = sorted({mf.source_family(x) for x in scriptura.mood_labels(labels)} - {None})
                    missing = [f for f in fams if (first, lst, f) not in published]
                    if missing:
                        units.append({"id": f"PSA.s.{n}.{k}", "book": book, "first": first, "last": lst, "kind": "source",
                                      "source": "scriptura", "yard": fams, "context_before": False})
        for r in mood_rules.run(facts, book):
            s = r["sides"]
            hi, lo = max(s.get("painful", 0), s.get("pleasant", 0)), min(s.get("painful", 0), s.get("pleasant", 0))
            if r["status"] == "mixed" and lo and hi <= 1.5 * lo:
                units.append({"id": f"{book}.h.{r['first']}", "book": book, "first": r["first"], "last": r["last"], "kind": "hard",
                              "source": "rules", "yard": r["moods"], "context_before": False})
    seen, uniq = set(), []
    for u in units:
        k = (u["first"], u["last"])
        if k not in seen:
            seen.add(k)
            uniq.append(u)
    (out / "units.jsonl").write_text("".join(json.dumps(u, ensure_ascii=False) + "\n" for u in uniq), encoding="utf-8")
    fams = lemmas_per_family()
    (out / "families.json").write_text(json.dumps(fams, ensure_ascii=False, indent=1), encoding="utf-8")
    c = collections.Counter((u["kind"], u["source"]) for u in uniq)
    print(len(uniq), "units", dict(c))


_DELIVERY = None


def _delivery_mood(code: str) -> str | None:
    """dl.* code -> the mood word the builder maps it to (Builder.DELIVERY_MOOD), via codes.tsv."""
    global _DELIVERY
    if _DELIVERY is None:
        name = {}
        for line in pf.CODES.read_text(encoding="utf-8").splitlines():
            x = line.split("\t")
            if len(x) > 2 and x[0].startswith("dl."):
                name[x[0]] = x[2]
        word = {l: m for m, ls in pf.Builder.DELIVERY_MOOD.items() for l in ls}
        _DELIVERY = {c: word.get(n) for c, n in name.items()}
    return _DELIVERY.get(code)


def system_prompt(out: Path) -> str:
    fams = json.loads((out / "families.json").read_text(encoding="utf-8"))
    lines = []
    for fid, r in mf.FAMILIES.items():
        h, g = fams[fid]
        lines.append(f"{fid}  {r['head_hbo']} / {r['head_grc']}   Hebrew: {' '.join(h)}   Greek: {' '.join(g)}")
    return ("You read a passage of the Hebrew Bible or the Greek New Testament and say which feelings the text itself marks there, "
            "and by which words. The feelings are these families, each named by a Hebrew and a Greek head word and shown with the "
            "lemmas that most often mark it:\n\n" + "\n".join(lines) + "\n\n"
            "A family counts only where words of this passage carry it: a feeling word, a cry, a weeping, a curse or a blessing, "
            "an exclamation, an act that shows the feeling. A word may carry a family although it is not in the lists. Give at "
            "most three families, the strongest first, and for each the numbers of the words that carry it (\"chapter:verse.word\", "
            "as numbered in the passage). Lines marked \"context\" may hold a carrying word (the narrator's frame of a speech). "
            "If the text marks no feeling, give an empty list. Answer only in the JSON form asked for.")


SCHEMA = {"type": "object", "additionalProperties": False, "required": ["moods"],
          "properties": {"moods": {"type": "array", "items": {
              "type": "object", "additionalProperties": False, "required": ["family", "words"],
              "properties": {"family": {"type": "string", "enum": list(mf.FAMILIES)},
                             "words": {"type": "array", "items": {"type": "string"}}}}}}}


def user_text(u: dict, words: dict) -> tuple[str, dict[str, list[str]]]:
    """The passage as numbered lines, and number -> MACULA keys."""
    a, z = u["first"], u["last"]
    span = [(k, w) for k, w in words.items() if any(a <= x <= z for x in w[1])]
    keys_of: dict[str, list[str]] = {}
    lines: list[str] = []
    first_cv = span[0][0][:2] if span else None
    if u.get("context_before") and first_cv:
        c, v = first_cv
        ctx = [(k, w) for k, w in words.items() if k[:2] == (c, v - 1) or (k[:2] == (c, v) and w[1][-1] < a)]
        if ctx:
            lines.append("context: " + " ".join(f"{k[0]}:{k[1]}.{k[2]} {w[0]}" for k, w in ctx))
            keys_of.update({f"{k[0]}:{k[1]}.{k[2]}": w[1] for k, w in ctx})
    cur, buf = None, []
    for k, w in span:
        if k[:2] != cur:
            if buf:
                lines.append(" ".join(buf))
            cur, buf = k[:2], []
        buf.append(f"{k[0]}:{k[1]}.{k[2]} {w[0]}")
        keys_of[f"{k[0]}:{k[1]}.{k[2]}"] = w[1]
    if buf:
        lines.append(" ".join(buf))
    return f"{u['book']}\n" + "\n".join(lines), keys_of


def requests(out: Path) -> list[dict]:
    sys_text = system_prompt(out)
    units = [json.loads(l) for l in (out / "units.jsonl").open(encoding="utf-8")]
    texts: dict[str, dict] = {}
    reqs = []
    for u in units:
        if u["book"] not in texts:
            texts[u["book"]] = _text(u["book"])
        t, _ = user_text(u, texts[u["book"]])
        reqs.append({"custom_id": u["id"].replace(".", "_")[:64], "params": {
            "model": MODEL, "max_tokens": MAX_TOKENS, "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
            "system": [{"type": "text", "text": sys_text, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": t}]}})
    return reqs


def _cli_one(r: dict, cwd: str) -> dict:
    """One unit through Claude Code's headless mode (the user's subscription, not API credit): no tools, our system prompt,
    structured output by SCHEMA. ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN are removed so the subscription login is used."""
    import os
    import subprocess
    import time
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    p = r["params"]
    cmd = ["claude", "-p", "--model", MODEL, "--effort", EFFORT, "--no-session-persistence", "--output-format", "json",
           "--system-prompt", p["system"][0]["text"], "--tools", "", "--json-schema", json.dumps(SCHEMA)]
    err = ""
    for attempt in range(4):
        try:
            proc = subprocess.run(cmd, input=p["messages"][0]["content"], capture_output=True, text=True, env=env, cwd=cwd, timeout=900)
            out = json.loads(proc.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            err = str(e)[:200]
            time.sleep(min(2 ** attempt * 10, 120))
            continue
        if out.get("is_error"):
            err = str(out.get("result"))[:300]
            if any(x in err.lower() for x in ("login", "limit", "credit")):
                return {"custom_id": r["custom_id"], "error": err, "fatal": True}
            time.sleep(min(2 ** attempt * 10, 120))
            continue
        so = out.get("structured_output")
        if so is None:
            try:
                so = json.loads(out.get("result") or "{}")
            except json.JSONDecodeError:
                so = None
        return {"custom_id": r["custom_id"], "answer": so, "cost_usd": out.get("total_cost_usd", 0), "usage": out.get("usage", {}),
                "raw": None if so is not None else (out.get("result") or "")[:500]}
    return {"custom_id": r["custom_id"], "error": err}


def collect_cli(out: Path) -> int:
    """cli_raw.jsonl -> results.jsonl (word numbers -> MACULA keys, numbers outside the passage kept apart) and a score of the
    source units against their yardstick (the source's family, mapped from its own word; never shown to the model)."""
    units = {u["id"].replace(".", "_")[:64]: u for u in (json.loads(l) for l in (out / "units.jsonl").open(encoding="utf-8"))}
    raw = {}
    for l in (out / "cli_raw.jsonl").open(encoding="utf-8"):
        x = json.loads(l)
        if "answer" in x and x["answer"] is not None:
            raw[x["custom_id"]] = x
    texts: dict[str, dict] = {}
    rows, sc = [], collections.Counter()
    for cid, x in raw.items():
        u = units[cid]
        if u["book"] not in texts:
            texts[u["book"]] = _text(u["book"])
        _, keys_of = user_text(u, texts[u["book"]])
        moods = []
        for m in x["answer"].get("moods", []):
            ks = list(dict.fromkeys(k for w in m["words"] for k in keys_of.get(w, [])))
            moods.append({"family": m["family"], "marked_by": ks, "unknown_words": [w for w in m["words"] if w not in keys_of]})
        rows.append({**u, "moods": moods, "cost_usd": x.get("cost_usd", 0)})
        fams = [m["family"] for m in moods if m["marked_by"]]
        sc[u["source"], "n"] += 1
        sc[u["source"], "none"] += not fams
        sc[u["source"], "hit"] += bool(set(fams) & set(u["yard"]))
        sc[u["source"], "first"] += bool(fams) and fams[0] in u["yard"]
        sc["unknown_words"] += sum(len(m["unknown_words"]) for m in moods)
    (out / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    for src in ("scriptura", "glyssen", "rules"):
        n = sc[src, "n"]
        if n:
            print(f"{src}: {n} units; yard family among the model's {sc[src, 'hit'] / n:.2f}, first {sc[src, 'first'] / n:.2f}, "
                  f"none {sc[src, 'none'] / n:.2f}")
    print("word numbers outside the passage:", sc["unknown_words"], "; USD reported", round(sum(r["cost_usd"] for r in rows), 2))
    return 0


def run_cli(a, reqs: list[dict]) -> int:
    import concurrent.futures
    import tempfile
    done_path = a.out / "cli_raw.jsonl"
    done = {}
    if done_path.exists():
        for l in done_path.open(encoding="utf-8"):
            x = json.loads(l)
            if "answer" in x:
                done[x["custom_id"]] = x
    spent = sum(x.get("cost_usd", 0) for x in done.values())
    rank = lambda r: 0 if r["custom_id"].startswith("PSA_s_") else 2 if "_h_" in r["custom_id"] else 1   # Scriptura, Glyssen, hard
    todo = sorted((r for r in reqs if r["custom_id"] not in done), key=rank)[: a.limit or None]
    print(f"{len(done)} done (USD {spent:.2f} reported); {len(todo)} to run; cap USD {a.cap}", flush=True)
    cwd = tempfile.mkdtemp(prefix="mood-model-")
    stop = False
    with done_path.open("a", encoding="utf-8") as f, concurrent.futures.ThreadPoolExecutor(a.workers) as ex:
        it = iter(todo)
        running = set()
        while True:
            while not stop and len(running) < a.workers:
                r = next(it, None)
                if r is None:
                    break
                running.add(ex.submit(_cli_one, r, cwd))
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
                if spent >= a.cap:
                    stop = True
            print(f"  USD {spent:.2f}", flush=True) if fin else None
    print(f"stopped={stop}; reported USD {spent:.2f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["prepare", "estimate", "count", "submit", "collect", "cli", "collect-cli"])
    ap.add_argument("--cap", type=float, default=15.0, help="cli: stop when the CLI's reported cost (USD, API-equivalent) reaches this")
    ap.add_argument("--limit", type=int, help="cli: at most this many new units (a pilot)")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--facts", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    if a.step == "prepare":
        prepare(a.facts, a.out)
        return 0
    reqs = requests(a.out)
    if a.step == "estimate":
        sys_chars = len(reqs[0]["params"]["system"][0]["text"])
        user_chars = sum(len(r["params"]["messages"][0]["content"]) for r in reqs)
        print(f"{len(reqs)} requests; system prompt {sys_chars} chars (cached after the first); user text {user_chars} chars in all")
        (a.out / "requests_preview.json").write_text(json.dumps(reqs[:3], ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    if a.step == "cli":
        return run_cli(a, reqs)
    if a.step == "collect-cli":
        return collect_cli(a.out)
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):          # as usability_judge does, but only this one key; never printed
        env = Path(__file__).resolve().parent.parent / ".env"
        for line in (env.read_text(encoding="utf-8").splitlines() if env.exists() else []):
            k, _, v = line.strip().partition("=")
            if k.strip() == "ANTHROPIC_API_KEY" and v.strip():
                os.environ["ANTHROPIC_API_KEY"] = v.strip().strip('"').strip("'")
    import anthropic
    client = anthropic.Anthropic(max_retries=6)
    if a.step == "count":
        total = 0
        for r in reqs:
            p = r["params"]
            total += client.messages.count_tokens(model=MODEL, system=p["system"], messages=p["messages"]).input_tokens
        print(f"{len(reqs)} requests, {total} input tokens in all (system prompt included in each)")
        return 0
    if a.step == "submit":
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request
        b = client.messages.batches.create(requests=[Request(custom_id=r["custom_id"], params=MessageCreateParamsNonStreaming(**r["params"]))
                                                     for r in reqs])
        (a.out / "batch.json").write_text(json.dumps({"id": b.id}), encoding="utf-8")
        print("batch", b.id, b.processing_status)
        return 0
    if a.step == "collect":
        bid = json.loads((a.out / "batch.json").read_text())["id"]
        units = {u["id"].replace(".", "_")[:64]: u for u in (json.loads(l) for l in (a.out / "units.jsonl").open(encoding="utf-8"))}
        texts: dict[str, dict] = {}
        rows, usage = [], collections.Counter()
        for res in client.messages.batches.results(bid):
            u = units[res.custom_id]
            if res.result.type != "succeeded":
                rows.append({"id": u["id"], "error": res.result.type})
                continue
            msg = res.result.message
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                usage[k] += getattr(msg.usage, k, 0) or 0
            if u["book"] not in texts:
                texts[u["book"]] = _text(u["book"])
            _, keys_of = user_text(u, texts[u["book"]])
            text = next((b.text for b in msg.content if b.type == "text"), "{}")
            got = json.loads(text).get("moods", [])
            moods = []
            for m in got:
                ks = [k for w in m["words"] for k in keys_of.get(w, [])]
                bad = [w for w in m["words"] if w not in keys_of]
                moods.append({"family": m["family"], "marked_by": ks, "unknown_words": bad})
            rows.append({**u, "moods": moods, "stop": msg.stop_reason})
        (a.out / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(len(rows), "results;", dict(usage))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
