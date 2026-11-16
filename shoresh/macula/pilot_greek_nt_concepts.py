"""A pilot: can a model that reads the Greek verse give a Greek New Testament word the concept of the Hebrew lexeme it is rendered by?

The projection of build_greek_nt_concepts cannot (41.8% on the quoted words against 40.6% for the lexeme's commonest concept): the Greek
lexeme does not choose between a Hebrew lexeme's concepts. Here a model reads the occurrence. Each item is one Greek word; its inventory is
the concepts of the Hebrew lexeme(s) the two Hebrew New Testaments render it by, with the published definitions; the model chooses one.

Two sets with an answer to score against, both from build_greek_nt_concepts:
  quoted      the word stands in a stretch that follows a Tanakh verse; the answer is the label of the Tanakh word
  dominated   rule `both`, the first concept has 0.8 of the weight (86% right in the leave-one-out check on the Tanakh): agreement only

Sent to the model: the reference, the Greek verse with the word marked, its lemma and morphology (MACULA Greek), the Hebrew lexeme's number,
the definitions and their UBS sense ids. Not sent: the Hebrew New Testament's text, the Tanakh verse, glosses, translations.

    python -m macula.pilot_greek_nt_concepts --items                 write pilot/items.jsonl (no model call)
    python -m macula.pilot_greek_nt_concepts --run --max-usd 0.3     label until the money is spent; answers are kept, a rerun goes on
                                                  --judge claude-cli  the same model through the `claude` command (the subscription, no
                                                                      API money; --max-usd then counts the tokens at the API's price)
    python -m macula.pilot_greek_nt_concepts --report                pilot/report.json
    python -m macula.pilot_greek_nt_concepts --jev-items             pilot/jev_items.jsonl: the same items one per call, as the Hebrew
                                                                     labelling put them to Jev (state: lexeme, occurrence; a choice)
    python -m macula.pilot_greek_nt_concepts --report --jev FILE     also score a file of Jev's answers ({"id", "choice": "c<n>", "confidence"})

Outputs are local (macula/data/greek-nt-concepts/pilot); nothing here is released.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import hashlib
import json
import random
import re
import sqlite3
from pathlib import Path
from macula import build_greek_nt_concepts as g
from macula import build_hebrew_nt_bridge as b

HERE = Path(__file__).resolve().parent
OUT = g.OUT / "pilot"
MODEL = "claude-opus-5-5"
PRICE = (4.0, 20.0)                     # USD per million input and output tokens (thinking is output)
SEED = 20261116
BATCH = 12                              # occurrences per call; one call holds one inventory
DOMINATED = 0.8
MORPH = ("tense", "voice", "mood", "person", "number", "gender", "case_", "degree")
PROMPT = (
    "You are labelling words of the Greek New Testament with concepts of Biblical Hebrew lexemes. A Hebrew translation of the New "
    "Testament renders each target word below by the Hebrew lexeme named here, and the numbered concepts are that lexeme's concepts "
    "(with the id of the lexicon sense each belongs to). For every occurrence, read the Greek verse and choose exactly one concept: the "
    "one the target word (between ⟦ and ⟧) expresses there.\n"
    "Reply with JSON only, no prose: a list of objects {{\"id\": <occurrence id>, \"choice\": <concept number>, \"sure\": <true or false>}}; "
    "\"sure\" is false where two concepts fit about equally well.\n\n"
    "Hebrew lexeme: {lexemes}\nConcepts:\n{inventory}\n\nOccurrences (id | reference | lemma | morphology | verse):\n{lines}\n")


def definitions(folder: Path) -> dict[str, str]:
    f = folder / "definitions.tsv"
    if not f.exists():
        from huggingface_hub import hf_hub_download
        hf_hub_download("bcv-commons/hebrew-word-concepts-model", "definitions.tsv", repo_type="dataset", revision=g.REVISION, local_dir=folder)
    return dict(l.split("\t", 1) for l in f.read_text(encoding="utf-8").splitlines() if l and not l.startswith(("#", "code\t")))


def verses() -> tuple[dict, dict]:
    """greek id -> (reference, morphology), and reference -> [(id, text)] in order"""
    con = sqlite3.connect(f"file:{b.HERE / 'macula-spine.db'}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    word, verse = {}, collections.defaultdict(list)
    for r in con.execute("select * from macula_words where lang = 'grc' order by key"):
        ref = f"{r['book']} {r['chapter']}:{r['verse']}"
        word[r["xml_id"]] = (ref, " ".join([r["class"], *(r[m] for m in MORPH if r[m])]))
        verse[ref].append((r["xml_id"], r["text"]))
    return word, verse


def lexemes(con: g.Concepts) -> tuple[dict, dict]:
    """hebrew lexeme -> its concepts, and greek id -> the Hebrew lexemes of both editions that have concepts"""
    import pyarrow.parquet as pq
    of = collections.defaultdict(list)
    for c, h in con.lexeme.items():
        of[h].append(c)
    hebrew = collections.defaultdict(set)                               # as the builder reads the links
    for ed in g.EDITIONS:
        for r in pq.read_table(b.DATA / ed / "links.parquet").to_pylist():
            if r["link"] != "edited-wide" and r["hebrew_strong"] in of and r["hebrew_class"] in b.H_CONTENT:
                hebrew[r["greek_id"]].add(r["hebrew_strong"])
    return of, hebrew


def inventory(concepts, key: str) -> list[str]:
    """the concepts in the order shown to a model: one seeded order per inventory, the same in every call"""
    inv = sorted(concepts, key=lambda c: (c.split(".")[0], int(c.split(".")[1])))
    random.Random(f"{SEED} {key}").shuffle(inv)
    return inv


def build_items(folder: Path, n_dominated: int) -> list[dict]:
    """the quoted words and a seeded sample of the dominated ones"""
    import pyarrow.parquet as pq
    con, lxx = g.Concepts(folder), g.septuagint_words()
    sense = {r["code"]: r["ubs_sense"] for r in pq.read_table(folder / "data" / "concepts.parquet").to_pylist()}
    labeller = {r["key"]: r["labeller"] for r in pq.read_table(folder / "data" / "tokens.parquet").to_pylist()}
    of, hebrew = lexemes(con)
    word, _ = verses()
    rows = pq.read_table(g.OUT / "words.parquet").to_pylist()
    rnd = random.Random(SEED)
    dominated = [r for r in rows if r["basis"] == "both" and r["share"] >= DOMINATED]
    chosen = [r for r in rows if r["basis"] == "quoted"] + rnd.sample(dominated, min(n_dominated, len(dominated)))
    items = []
    for r in chosen:
        hs = sorted(hebrew[r["greek_id"]])
        inv = inventory((c for h in hs for c in of[h]), " ".join(hs))
        it = {"id": r["greek_id"], "set": "quoted" if r["basis"] == "quoted" else "dominated", "ref": word[r["greek_id"]][0],
              "greek_strong": r["greek_strong"], "lemma": r["greek_lemma"], "morph": word[r["greek_id"]][1], "hebrew": hs, "inventory": inv,
              "answer": r["concept"], "answer_sense": sense[r["concept"]], "share": r["share"]}
        if it["set"] == "quoted":
            pb, pc = con.project(r["greek_strong"], set(hs), (r["concept"], lxx.get(r["tanakh"])))
            it.update({"tanakh": r["tanakh"], "labeller": labeller[r["tanakh"]], "commonest": g.ranked(con.prior[con.lexeme[r["concept"]]])[0][0],
                       "projection": pc[0][0] if pc else ""})
        assert r["concept"] in inv, r
        items.append(it)
    return items


def batches(items: list[dict]) -> list[list[dict]]:
    """calls of one inventory each, the quoted words first; an item with one concept needs no call"""
    by = collections.defaultdict(list)
    for it in items:
        if len(it["inventory"]) > 1:
            by[(it["set"] != "quoted", *it["hebrew"])].append(it)
    out = [v[i:i + BATCH] for _, v in sorted(by.items()) for i in range(0, len(v), BATCH)]
    random.Random(SEED).shuffle(out)
    return sorted(out, key=lambda v: v[0]["set"] != "quoted")


def prompt(batch: list[dict], defs: dict, sense: dict, verse: dict) -> str:
    inv = batch[0]["inventory"]
    lines = []
    for it in batch:
        text = " ".join(f"⟦{t}⟧" if i == it["id"] else t for i, t in verse[it["ref"]])
        lines.append(f"{it['id']} | {it['ref']} | {it['lemma']} | {it['morph']} | {text}")
    return PROMPT.format(lexemes=", ".join(f"Strong {h}" for h in batch[0]["hebrew"]),
                         inventory="\n".join(f"{n}: {defs[c]} (UBS {sense[c]})" for n, c in enumerate(inv, 1)), lines="\n".join(lines))


def parse(text: str, batch: list[dict]) -> dict[str, dict]:
    """id -> {concept, sure}, for the ids asked and choices inside the inventory"""
    m = re.search(r"\[.*\]", text, re.S)
    try:
        rows = json.loads(m.group(0)) if m else []
    except json.JSONDecodeError:
        return {}
    inv, ids, out = batch[0]["inventory"], {it["id"] for it in batch}, {}
    for r in rows:
        if isinstance(r, dict) and r.get("id") in ids and isinstance(r.get("choice"), int) and 1 <= r["choice"] <= len(inv):
            out[r["id"]] = {"concept": inv[r["choice"] - 1], "sure": bool(r.get("sure", True))}
    return out


JEV = ("The occurrence is a word of the Greek New Testament (between ⟦ and ⟧ in its verse) that a Hebrew translation renders by this Hebrew "
       "lexeme. Which of the lexeme's concepts does this occurrence express? Choose exactly one.")


NONE = "none of the concepts above: the word expresses something else here, or is a name"


def jev_items(items: list[dict], folder: Path) -> list[dict]:
    """an item with `none` gets one more choice after its inventory (load_jev reads it as no concept)"""
    import pyarrow.parquet as pq
    defs = definitions(folder)
    sense = {r["code"]: r["ubs_sense"] for r in pq.read_table(folder / "data" / "concepts.parquet").to_pylist()}
    _, verse = verses()
    out = []
    for it in items:
        if len(it["inventory"]) > 1:
            text = " ".join(f"⟦{t}⟧" if i == it["id"] else t for i, t in verse[it["ref"]])
            out.append({"id": it["id"], "state": {"lexeme": ", ".join(f"Strong {h}" for h in it["hebrew"]),
                                                  "occurrence": f"{it['id']} | {it['ref']} | {it['lemma']} | {it['morph']} | verse: {text}"},
                        "question": {"type": "choice", "criteria": {f"c{n}": f"{defs[c]} (UBS {sense[c]})" for n, c in enumerate(it["inventory"], 1)},
                                     "instructions": it.get("instructions", JEV)}})
            if it.get("none"):
                out[-1]["question"]["criteria"][f"c{len(it['inventory']) + 1}"] = NONE
    return out


def load_jev(f: Path, items: list[dict]) -> dict[str, dict]:
    """id -> {concept, sure (confidence >= 0.8), confidence} from Jev's answers; concept "" = the item's choice "none of the concepts" """
    inv = {it["id"]: it["inventory"] + [""] * bool(it.get("none")) for it in items}
    out = {}
    for l in f.read_text(encoding="utf-8").splitlines():
        r = json.loads(l)
        m = re.fullmatch(r"c(\d+)", str(r.get("choice", "")))
        if m and r.get("id") in inv and 1 <= int(m.group(1)) <= len(inv[r["id"]]):
            out[r["id"]] = {"concept": inv[r["id"]][int(m.group(1)) - 1], "sure": float(r.get("confidence") or 0) >= 0.8, "confidence": r.get("confidence")}
    return out


def load_answers() -> tuple[dict, list[dict]]:
    f = OUT / "answers.jsonl"
    calls = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []
    return {i: a for c in calls for i, a in c["answers"].items()}, calls


def run(items: list[dict], folder: Path, max_usd: float, workers: int, judge: str) -> None:
    import pyarrow.parquet as pq
    from macula import usability_judge as uj
    uj._load_env()
    uj.MODELS[judge] = MODEL
    call = {"claude": uj.call_claude, "claude-cli": uj.call_claude_cli}[judge]
    defs = definitions(folder)
    sense = {r["code"]: r["ubs_sense"] for r in pq.read_table(folder / "data" / "concepts.parquet").to_pylist()}
    _, verse = verses()
    done, calls = load_answers()
    spent = sum(c["usd"] for c in calls)
    todo = [bt for bt in batches(items) if not all(it["id"] in done for it in bt)]
    print(f"[pilot] {len(todo)} calls to make, USD {spent:.2f} spent so far, limit {max_usd:.2f}")

    def one(bt: list[dict]) -> dict:
        p = prompt(bt, defs, sense, verse)
        text, i, o = call(p)
        return {"model": MODEL, "judge": judge, "prompt_sha256": hashlib.sha256(p.encode()).hexdigest(), "ids": [it["id"] for it in bt], "input_tokens": i,
                "output_tokens": o, "usd": round((i * PRICE[0] + o * PRICE[1]) / 1e6, 6), "answers": parse(text, bt)}

    with (OUT / "answers.jsonl").open("a", encoding="utf-8") as f, concurrent.futures.ThreadPoolExecutor(workers) as ex:
        for k in range(0, len(todo), workers):                          # a round of calls, then the money is counted before the next
            if spent >= max_usd:
                print(f"[pilot] stopped at the limit: {len(todo) - k} calls left")
                break
            failed = 0
            for c in ex.map(one, todo[k:k + workers]):
                if not c["input_tokens"]:                               # rejected or failed: not an answer, and no reason to go on
                    failed += 1
                    continue
                spent += c["usd"]
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
                f.flush()
            if failed:
                print(f"[pilot] stopped: {failed} calls of this round failed (see the messages above)")
                break
    done, calls = load_answers()
    print(f"[pilot] {len(done):,} answers, {len(calls)} calls, USD {sum(c['usd'] for c in calls):.2f}")


def share(n: int, d: int) -> float:
    return round(n / d, 4) if d else 0.0


def report(items: list[dict], folder: Path, done: dict | None = None) -> dict:
    """`done` = another labeller's answers to score in place of the model's (Jev's)"""
    import pyarrow.parquet as pq
    sense = {r["code"]: r["ubs_sense"] for r in pq.read_table(folder / "data" / "concepts.parquet").to_pylist()}
    mine, calls = load_answers()
    if done is None:
        done = mine
    else:
        calls = []
    rep: dict = {"model": MODEL, "effort": "low", "judges": sorted({c.get("judge", "claude") for c in calls}), "concepts": f"bcv-commons/hebrew-word-concepts-model@{g.REVISION}",
                 "calls": len(calls), "input_tokens": sum(c["input_tokens"] for c in calls), "output_tokens": sum(c["output_tokens"] for c in calls),
                 "usd at the API's price": round(sum(c["usd"] for c in calls), 2), "words asked": sum(len(c["ids"]) for c in calls), "words answered": len(done)}
    rep["usd per 1,000 words asked, at the API's price"] = round(1000 * sum(c["usd"] for c in calls) / max(rep["words asked"], 1), 2)
    for name in ("quoted", "dominated"):
        own = [it for it in items if it["set"] == name]
        one = [it for it in own if len(it["inventory"]) == 1]
        got = [it for it in own if it["id"] in done]
        s: dict = {"words": len(own), "one concept in the inventory (no call)": len(one), "answered": len(got),
                   "mean concepts in the inventory (answered)": round(sum(len(it["inventory"]) for it in got) / max(len(got), 1), 2)}

        def figures(sub: list[dict]) -> dict:
            f = {"words": len(sub), "model: same concept": share(sum(done[it["id"]]["concept"] == it["answer"] for it in sub), len(sub)),
                 "model: same UBS sense": share(sum(sense[done[it["id"]]["concept"]] == it["answer_sense"] for it in sub), len(sub))}
            if name == "quoted":
                f.update({"lexeme's commonest concept: same concept": share(sum(it["commonest"] == it["answer"] for it in sub), len(sub)),
                          "lexeme's commonest concept: same UBS sense": share(sum(sense[it["commonest"]] == it["answer_sense"] for it in sub), len(sub)),
                          "projection: same concept": share(sum(it["projection"] == it["answer"] for it in sub), len(sub))})
            return f

        s["answered words"] = figures(got)
        s["answered words, model sure"] = figures([it for it in got if done[it["id"]]["sure"]])
        s["answered words, model not sure"] = figures([it for it in got if not done[it["id"]]["sure"]])
        if name == "quoted":
            s["by the Tanakh word's labeller"] = {k: figures([it for it in got if it["labeller"] == k]) for k in sorted({it["labeller"] for it in got})}
            s["by the size of the inventory"] = {k: figures([it for it in got if lo <= len(it["inventory"]) <= hi])
                                                 for k, lo, hi in (("2-5", 2, 5), ("6-10", 6, 10), ("11-20", 11, 20), ("21+", 21, 999))}
            if len(got) + len(one) == len(own):                         # the whole set: the words with one concept are right by all three
                n = len(own)
                s["all words"] = {"words": n, "model: same concept": share(sum(done[it["id"]]["concept"] == it["answer"] for it in got) + len(one), n),
                                  "lexeme's commonest concept: same concept": share(sum(it["commonest"] == it["answer"] for it in own), n),
                                  "projection: same concept": share(sum(it["projection"] == it["answer"] for it in own), n)}
        rep[name] = s
    return rep


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--concepts", type=Path, default=g.CONCEPTS)
    ap.add_argument("--dominated", type=int, default=400, help="dominated words in the sample")
    ap.add_argument("--items", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--jev-items", action="store_true")
    ap.add_argument("--jev", type=Path, help="with --report: a file of Jev's answers to score beside the model's")
    ap.add_argument("--max-usd", type=float, default=0.3)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--judge", default="claude", choices=["claude", "claude-cli"])
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / "items.jsonl"
    if a.items or not f.exists():
        items = build_items(a.concepts, a.dominated)
        f.write_text("".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items), encoding="utf-8")
        n = collections.Counter((it["set"], len(it["inventory"]) > 1) for it in items)
        print(f"[pilot] {len(items):,} items -> {f}: {dict(n)}; {len(batches(items))} calls")
    items = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
    if a.run:
        run(items, a.concepts, a.max_usd, a.workers, a.judge)
    if a.report:
        rep = report(items, a.concepts)
        (OUT / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        if a.jev:
            jev, mine = load_jev(a.jev, items), load_answers()[0]
            rj = report(items, a.concepts, jev)
            rj.update({"model": "jev-latest", "judges": ["typesafe"], "effort": ""})
            shared = [it for it in items if it["id"] in jev and it["id"] in mine]
            rj["against the model"] = {"words with both": len(shared), "same concept": share(sum(jev[it["id"]]["concept"] == mine[it["id"]]["concept"] for it in shared), len(shared))}
            for k, sub_ in (("same", [it for it in shared if it["set"] == "quoted" and jev[it["id"]]["concept"] == mine[it["id"]]["concept"]]),
                            ("differ", [it for it in shared if it["set"] == "quoted" and jev[it["id"]]["concept"] != mine[it["id"]]["concept"]])):
                rj["against the model"][f"quoted, the two {k}"] = {"words": len(sub_), "jev right": share(sum(jev[it["id"]]["concept"] == it["answer"] for it in sub_), len(sub_)),
                                                                   "model right": share(sum(mine[it["id"]]["concept"] == it["answer"] for it in sub_), len(sub_))}
            (OUT / "report_jev.json").write_text(json.dumps(rj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(json.dumps(rj, ensure_ascii=False, indent=1))
    if a.jev_items:
        rows = jev_items(items, a.concepts)
        (OUT / "jev_items.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(f"[pilot] {len(rows):,} items for Jev -> {OUT / 'jev_items.jsonl'}")


if __name__ == "__main__":
    main()
