"""A model reads the stem (binyan) of verb forms in the Hebrew New Testaments whose stem the features table leaves empty.

The features table of bcv-commons/hebrew-nt-analysis gives a verb a stem only where its keys decide one. For the frame
label of a verb's subject and object (macula/build_frame_labels.py) the stem is the key, so the places whose label is
open for want of a stem are read here by a model, into a table of its own (model named, no human check); the features
table and the scheme tables are not changed.

What the model sees: the verb as written, the lemma where the word table has a lexeme (as a hint), and the words around
it in its verse, in Hebrew only (pointed without accents, or unpointed, as the edition writes). No gloss, no translation.
It answers with one of MACULA's stem names and how sure it is (sure / unsure / two: the written form allows two stems),
one short line per form, a hundred forms to a call. A form is read once, in the first place it stands; a form read as
`two`, and every repeated form of the unpointed edition, is read again in each further place (the same letters are
often two stems there: וַיִּפָּתַח and וַיִּפְתַּח are both ויפתח).

Two anchors are run before any entry is used:
  a1  Tanakh verbs with MACULA's stem hidden, the same words pointed and with the points stripped (the model may know the
      Tanakh, so this is an upper bound)
  a2  verbs of the two editions whose stem the features table does give (basis `form`), hidden and read by the model

    cd shoresh && .venv/bin/python3 -m macula.verb_stems_model prepare --out DIR      # items, no calls
    cd shoresh && .venv/bin/python3 -m macula.verb_stems_model run --out DIR --set a1|a2|main|tokens|tokens2 --cap USD
    cd shoresh && .venv/bin/python3 -m macula.verb_stems_model score --out DIR        # the anchors' figures
    cd shoresh && .venv/bin/python3 -m macula.verb_stems_model tokens --out DIR       # items per further token: forms read as `two`, and the unpointed edition
    cd shoresh && .venv/bin/python3 -m macula.verb_stems_model table --out DIR        # stems.parquet per edition, ACCOUNT.json
    cd shoresh && .venv/bin/python3 -m macula.verb_stems_model coverage --out DIR     # what the frame-label lookup settles with them

The calls go through Claude Code's headless mode (as macula/mood_model.py); `run` resumes from raw.jsonl and stops at the cap.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

SHORESH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHORESH))
HERE = SHORESH / "macula"
DATA = HERE / "data"
MODEL = "claude-opus-5-5"
EFFORT = "low"
BATCH = 100
SEED = 20261128
ACCENTS = re.compile("[\u0591-\u05AF\u05BD\u05C0\u05C3\u05C6]")      # cantillation, meteg, paseq, sof pasuq, nun hafukha
STEMS = ["qal", "niphal", "piel", "pual", "hiphil", "hophal", "hithpael", "polel", "polal", "hithpolel", "pilpel", "poel", "nithpael", "other"]
A1_STRATA = {"qal": 140, "niphal": 120, "piel": 100, "hiphil": 120, "hithpael": 50, "hophal": 25, "pual": 25, "polel": 10, "hithpolel": 5, "pilpel": 5}
A2_STRATA = {"qal": 130, "niphal": 80, "piel": 70, "hiphil": 80, "hithpael": 25, "hophal": 8, "pual": 7}
EDITIONS = (("heb_scg", "scg"), ("heb_mod", "del"))
FEATURES = DATA / "hebrew-nt-features" / "2026-11-26c"
SYSTEM = """You name the stem (binyan) of Hebrew verb forms.

Each item is one line: its number, the verb as it is written, then (where known) a dictionary lemma as a hint that may be wrong, then the words around the verb in its verse with the verb between ⟦ and ⟧. The Hebrew is biblical in style: the Hebrew Bible, or a Hebrew translation of the New Testament. It is either pointed or unpointed. The written verb may carry a conjunction, a preposition, the article or a pronoun suffix.

Answer with one line per item, in order, and nothing else: the item's number, the stem, and how sure, separated by one space.
- stem: one of qal, niphal, piel, pual, hiphil, hophal, hithpael, polel, polal, hithpolel, pilpel, poel, nithpael. A passive participle of the qal (כָּתוּב) is qal. Give "other" only when the word is not a Hebrew verb form at all.
- how sure: s when the form in its context leaves one stem; t when the written form allows two stems and the context does not decide between them (then add the second stem as a fourth word); u in any other case of doubt.

Judge from the Hebrew form and its context only. Example lines:
1 qal s
2 niphal t qal
3 piel u"""
SURE = {"s": "sure", "t": "two", "u": "unsure"}


def clean(t: str) -> str:
    return ACCENTS.sub("", unicodedata.normalize("NFC", t or ""))


def plain(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if c == " " or "א" <= c <= "ת" or c in "⟦⟧")


def window(words: list[str], at: int, before: int = 4, after: int = 4) -> str:
    lo, hi = max(0, at - before), min(len(words), at + after + 1)
    return " ".join(("⟦" + w + "⟧") if j == at else w for j, w in enumerate(words[lo:hi], lo))


def tanakh_items() -> list[dict]:
    """the first anchor: Tanakh verbs per stem, each as written (accents off) and with the points stripped"""
    con = sqlite3.connect(f"file:{HERE / 'macula-spine.db'}?mode=ro", uri=True)
    verse = collections.defaultdict(dict)                   # (book, chapter, verse) -> {word number: text}
    verbs = collections.defaultdict(list)
    for key, book, c, v, w, text, cls, stem, lemma, strong, wlang in con.execute(
            "select key, book, chapter, verse, word, text, class, stem, lemma, strong, wlang from macula_words where lang='hbo' order by key"):
        d = verse[(book, c, v)]
        d[w] = d.get(w, "") + clean(text)
        if cls == "verb" and wlang == "H" and stem in A1_STRATA:
            verbs[stem].append((book, c, v, w, lemma, strong))
    con.close()
    rng = random.Random(SEED)
    out = []
    for stem, n in A1_STRATA.items():
        seen, pool = set(), verbs[stem][:]
        rng.shuffle(pool)
        for book, c, v, w, lemma, strong in pool:
            ws = verse[(book, c, v)]
            order = sorted(ws)
            form = ws[w]
            if form in seen or len(order) < 3:
                continue
            seen.add(form)
            ctx = window([ws[x] for x in order], order.index(w))
            for kind in ("pointed", "plain"):
                out.append({"set": "a1", "key": f"a1:{kind}:{book}.{c}.{v}.{w}", "kind": kind, "gold": stem,
                            "form": form if kind == "pointed" else plain(form), "lemma": lemma if kind == "pointed" else plain(lemma),
                            "context": ctx if kind == "pointed" else plain(ctx)})
            if len(seen) >= n:
                break
    return out


def edition(ed: str, text: str):
    """the edition's verbs with their verse's words: [(word id, written word, lemma or "", lexeme, stem, stem basis, context, (book, c, v, i))]"""
    from macula.build_text_ids import wid
    words = pq.read_table(DATA / "clause-tagger" / "export" / ed / "words.parquet",
                          columns=["book", "chapter", "verse", "i", "part", "word", "class", "lemma", "lexeme"]).to_pylist()
    feat = {(r["book"], r["chapter"], r["verse"], r["i"], r["part"]): (r["stem"] or "", r["stem_basis"] or "")
            for r in pq.read_table(FEATURES / ed / "features.parquet", columns=["book", "chapter", "verse", "i", "part", "stem", "stem_basis"]).to_pylist()}
    verse = collections.defaultdict(dict)
    for r in words:
        if r["class"] != "verse-number":
            verse[(r["book"], r["chapter"], r["verse"])].setdefault(r["i"], clean(r["word"]))
    out = []
    for r in words:
        if r["class"] != "verb":
            continue
        ws = verse[(r["book"], r["chapter"], r["verse"])]
        order = sorted(ws)
        stem, basis = feat.get((r["book"], r["chapter"], r["verse"], r["i"], r["part"]), ("", ""))
        out.append((wid(text, r["book"], r["chapter"], r["verse"], r["i"]), ws[r["i"]], clean(r["lemma"]) if r["lexeme"] else "", r["lexeme"] or "",
                    stem, basis, window([ws[x] for x in order], order.index(r["i"])), (r["book"], r["chapter"], r["verse"], r["i"])))
    return out


def open_tokens(ed: str, verbs: list) -> set[str]:
    """word ids of the verbs without a stem whose subject's or object's frame label the lookup leaves open"""
    from macula.frame_labels_lookup import Frames
    F = Frames(str(DATA / "frame-labels" / "frames.parquet"))
    V = {v[0]: v for v in verbs}
    d = DATA / "clause-scheme" / "nt" / ed
    pred = {r["clause"]: r["pred"] for r in pq.read_table(d / "clauses.parquet", columns=["clause", "pred"]).to_pylist()}
    todo = [(pred[r["clause"]], "s" if r["role"] == "s" else "o") for r in pq.read_table(d / "constituents.parquet", columns=["clause", "role"]).to_pylist()
            if r["role"] in ("s", "o", "o2")]
    todo += [(r["verb"], "s") for r in pq.read_table(d / "added.parquet", columns=["verb"]).to_pylist()]
    return {v for v, role in todo if v in V and not V[v][4] and F.label(V[v][3], "", role)[0] is None}


def prepare(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    items = tanakh_items()
    rng = random.Random(SEED + 1)
    forms = {}
    for ed, text in EDITIONS:
        verbs = edition(ed, text)
        # the second anchor: distinct written forms whose stem the keys give
        by = collections.defaultdict(dict)
        for v in verbs:
            if v[5] == "form" and v[4] in A2_STRATA:
                by[v[4]].setdefault((v[1], v[3]), v)
        for stem, n in A2_STRATA.items():
            pool = sorted(by[stem])
            rng.shuffle(pool)
            for k in pool[:n]:
                v = by[stem][k]
                items.append({"set": "a2", "key": f"a2:{ed}:{v[0]}", "kind": ed, "gold": stem, "form": v[1], "lemma": v[2], "context": v[6]})
        # the main set: distinct (written form, lexeme) of the open tokens, with the context of the first place
        op = open_tokens(ed, verbs)
        first = {}
        for v in verbs:
            if v[0] in op:
                first.setdefault((v[1], v[3]), []).append(v)
        forms[ed] = {"forms": len(first), "tokens": sum(len(x) for x in first.values())}
        for (form, lex), vs in sorted(first.items()):
            items.append({"set": "main", "key": f"main:{ed}:{vs[0][0]}", "kind": ed, "form": form, "lemma": vs[0][2], "lexeme": lex,
                          "context": vs[0][6], "tokens": [v[0] for v in vs]})
    by_set = collections.defaultdict(list)
    for it in items:
        by_set[(it["set"], it["kind"])].append(it)
    units = []
    for (s, kind), its in sorted(by_set.items()):
        random.Random(SEED + 2).shuffle(its)                 # the anchors' strata mixed within a call
        for b in range(0, len(its), BATCH):
            units.append({"id": f"{s}.{kind}.{b // BATCH:03d}", "set": s, "kind": kind, "items": its[b:b + BATCH]})
    (out / "units.jsonl").write_text("".join(json.dumps(u, ensure_ascii=False) + "\n" for u in units), encoding="utf-8")
    print({k: len(v) for k, v in by_set.items()}, "| calls:", collections.Counter(u["set"] for u in units), "| main:", forms)


def prompt(u: dict) -> str:
    return "\n".join(f"{n}. {it['form']}" + (f" | lemma {it['lemma']}" if it.get("lemma") else "") + f" | {it['context']}" for n, it in enumerate(u["items"], 1))


def parse(text: str, n: int):
    """the answer's lines -> {"items": [...]} or None when a line is missing or out of form"""
    got = {}
    for line in text.splitlines():
        p = line.replace(".", " ").split()
        if len(p) >= 3 and p[0].isdigit() and p[1].isalpha() and p[2] in SURE:      # a stem name outside the list is kept as given
            got[int(p[0])] = {"n": int(p[0]), "stem": p[1].lower(), "sure": SURE[p[2]], "other_stem": p[3].lower() if len(p) > 3 and p[3].isalpha() else ""}
    return {"items": [got[i] for i in range(1, n + 1)]} if set(got) == set(range(1, n + 1)) else None


def one(u: dict, cwd: str) -> dict:
    import subprocess
    import time
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    cmd = ["claude", "-p", "--model", MODEL, "--effort", EFFORT, "--no-session-persistence", "--output-format", "json",
           "--system-prompt", SYSTEM, "--tools", ""]
    err = ""
    for attempt in range(4):
        try:
            proc = subprocess.run(cmd, input=prompt(u), capture_output=True, text=True, env=env, cwd=cwd, timeout=900)
            res = json.loads(proc.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            err = str(e)[:200]
            time.sleep(min(2 ** attempt * 10, 120))
            continue
        if res.get("is_error"):
            err = str(res.get("result"))[:300]
            if any(x in err.lower() for x in ("login", "limit", "credit")):
                return {"id": u["id"], "error": err, "fatal": True}
            time.sleep(min(2 ** attempt * 10, 120))
            continue
        so = parse(res.get("result") or "", len(u["items"]))
        if so is None:
            err = "answer not in form: " + (res.get("result") or "")[:200]
        return {"id": u["id"], "answer": so, "error": err if so is None else "", "cost_usd": res.get("total_cost_usd", 0), "usage": res.get("usage", {})}
    return {"id": u["id"], "error": err}


def load(out: Path):
    units = [json.loads(l) for name in ("units.jsonl", "units-tokens.jsonl") if (out / name).exists() for l in (out / name).open(encoding="utf-8")]
    done, spent, calls = {}, 0.0, 0
    if (out / "raw.jsonl").exists():
        for l in (out / "raw.jsonl").open(encoding="utf-8"):
            x = json.loads(l)
            spent += x.get("cost_usd", 0) or 0
            calls += 1
            if x.get("answer") is not None:
                done[x["id"]] = x
    return units, done, spent, calls


def run(out: Path, which: str, cap: float, limit: int | None, workers: int) -> None:
    import concurrent.futures
    import tempfile
    units, done, spent, _ = load(out)
    todo = [u for u in units if u["set"] == which and u["id"] not in done][: limit or None]
    print(f"{len(done)} done (USD {spent:.2f} over all sets); {len(todo)} to run in {which}; cap USD {cap}", flush=True)
    cwd = tempfile.mkdtemp(prefix="verb-stems-model-")
    stop, it, running = False, iter(todo), set()
    with (out / "raw.jsonl").open("a", encoding="utf-8") as f, concurrent.futures.ThreadPoolExecutor(workers) as ex:
        while True:
            while not stop and len(running) < workers:
                u = next(it, None)
                if u is None:
                    break
                running.add(ex.submit(one, u, cwd))
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
    print(f"stopped={stop}; reported USD {spent:.2f}")


def answers(out: Path):
    """(unit, item, answer) for every answered item"""
    units, done, _, _ = load(out)
    for u in units:
        x = done.get(u["id"])
        if x:
            for it, a in zip(u["items"], x["answer"]["items"]):
                yield u, it, a


def score(out: Path) -> dict:
    res = collections.defaultdict(lambda: collections.Counter())
    miss = collections.Counter()
    for u, it, a in answers(out):
        if u["set"] not in ("a1", "a2"):
            continue
        k = (u["set"], it["kind"])
        for key in ("all", it["gold"]):
            res[(*k, key)]["n"] += 1
            res[(*k, key)]["right"] += a["stem"] == it["gold"]
            res[(*k, key)][a["sure"]] += 1
            res[(*k, key)]["sure_right"] += a["sure"] == "sure" and a["stem"] == it["gold"]
            res[(*k, key)]["second_right"] += a["sure"] == "two" and a.get("other_stem") == it["gold"]
        if a["stem"] != it["gold"]:
            miss[(*k, it["gold"], a["stem"])] += 1
    fig = {}
    for (s, kind, key), c in sorted(res.items()):
        fig[f"{s}|{kind}|{key}"] = {"n": c["n"], "right": c["right"], "sure": c["sure"], "sure_right": c["sure_right"], "two": c["two"],
                                    "two_second_right": c["second_right"], "unsure": c["unsure"]}
    # weighted to the stems the features table reads in the edition (the open forms' own mix is not known)
    for kind, ed in (("pointed", "heb_scg"), ("plain", "heb_mod"), ("heb_scg", "heb_scg"), ("heb_mod", "heb_mod")):
        s = "a1" if kind in ("pointed", "plain") else "a2"
        mix = collections.Counter(r for r in pq.read_table(FEATURES / ed / "features.parquet", columns=["stem"]).column(0).to_pylist() if r)
        got = [(mix[st], fig[f"{s}|{kind}|{st}"]) for st in mix if f"{s}|{kind}|{st}" in fig]
        tot = sum(w for w, _ in got)
        if tot:
            fig[f"{s}|{kind}|weighted"] = {"right": round(sum(w * x["right"] / x["n"] for w, x in got) / tot, 4),
                                           "sure_share": round(sum(w * x["sure"] / x["n"] for w, x in got) / tot, 4),
                                           "sure_right": round(sum(w * (x["sure_right"] / x["sure"] if x["sure"] else 0) for w, x in got) / tot, 4)}
    for k, x in fig.items():
        if k.endswith("weighted"):
            print(f"{k}: right {x['right']:.1%}; sure {x['sure_share']:.1%} of the forms, right {x['sure_right']:.1%} where sure")
        else:
            print(f"{k}: {x['right']}/{x['n']} = {x['right'] / x['n']:.1%}; sure {x['sure']} ({x['sure_right'] / x['sure'] if x['sure'] else 0:.1%} right), "
                  f"two {x['two']} (second right {x['two_second_right']}), unsure {x['unsure']}")
    print("commonest misses (set, kind, gold, read):", miss.most_common(14))
    return {"figures": fig, "misses": [[*k, n] for k, n in miss.most_common(40)]}


def tokens(out: Path) -> None:
    """one item per further token, each with its own context: of the forms read as `two` (set tokens), and of every other
    form of the unpointed edition, where one written form may be two stems in two places (set tokens2)"""
    ctx = {}
    for ed, text in EDITIONS:
        ctx.update({v[0]: v for v in edition(ed, text)})
    its = collections.defaultdict(list)
    for u, it, a in answers(out):
        if u["set"] == "main" and (a["sure"] == "two" or it["kind"] == "heb_mod"):
            which = "tokens" if a["sure"] == "two" else "tokens2"
            for t in it["tokens"][1:]:
                v = ctx[t]
                its[(which, it["kind"])].append({"set": which, "key": f"{which}:{it['kind']}:{t}", "kind": it["kind"], "form": v[1], "lemma": v[2], "lexeme": v[3],
                                                 "context": v[6], "tokens": [t]})
    units = [{"id": f"{which}.{kind}.{b // BATCH:03d}", "set": which, "kind": kind, "items": x[b:b + BATCH]} for (which, kind), x in sorted(its.items()) for b in range(0, len(x), BATCH)]
    (out / "units-tokens.jsonl").write_text("".join(json.dumps(u, ensure_ascii=False) + "\n" for u in units), encoding="utf-8")
    print({k: len(v) for k, v in its.items()}, "items in", len(units), "calls")


def table(out: Path) -> None:
    rows = collections.defaultdict(dict)
    per_token = {}
    for u, it, a in answers(out):
        if u["set"] in ("tokens", "tokens2"):
            per_token[it["tokens"][0]] = a
    for u, it, a in answers(out):
        if u["set"] != "main":
            continue
        for n, t in enumerate(it["tokens"]):
            b = per_token.get(t, a) if n else a
            rows[it["kind"]][t] = {"word": t, "written": it["form"], "lexeme": it["lexeme"], "stem": "" if b["stem"] == "other" else b["stem"],
                                   "sureness": b["sure"], "other_stem": (b.get("other_stem") or "") if b["sure"] == "two" else "",
                                   "read": "token" if (n == 0 or t in per_token) else "form", "model": MODEL}
    units, done, spent, calls = load(out)
    acc = {"model": MODEL, "effort": EFFORT, "calls": calls, "answered_calls": len(done), "reported_cost_usd": round(spent, 2),
           "anchors": score(out), "editions": {}}
    for ed, r in rows.items():
        (out / ed).mkdir(exist_ok=True)
        tab = sorted(r.values(), key=lambda x: x["word"])
        pq.write_table(pa.Table.from_pylist(tab), out / ed / "stems.parquet", compression="zstd")
        acc["editions"][ed] = {"tokens": len(tab), "forms": len({(x["written"], x["lexeme"]) for x in tab}),
                               "sureness": dict(collections.Counter(x["sureness"] for x in tab)),
                               "stems": dict(collections.Counter(x["stem"] or "none" for x in tab).most_common()),
                               "no_verb_form": sum(1 for x in tab if not x["stem"])}
    (out / "ACCOUNT.json").write_text(json.dumps(acc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in acc.items() if k != "anchors"}, ensure_ascii=False, indent=1))


def coverage(out: Path) -> dict:
    """what the frame-label lookup settles on the two editions: with the features table's stems, and further with the
    stems read here (those places rest on a model's reading), per role"""
    from macula.frame_labels_lookup import Frames
    F = Frames(str(DATA / "frame-labels" / "frames.parquet"))
    res = {}
    for ed, text in EDITIONS:
        V = {v[0]: v for v in edition(ed, text)}
        model = {r["word"]: r for r in pq.read_table(out / ed / "stems.parquet").to_pylist()}
        src = {}
        from macula.build_text_ids import wid
        for r in pq.read_table(DATA / "clause-tagger" / "export" / ed / "words.parquet", columns=["book", "chapter", "verse", "i", "class", "source"]).to_pylist():
            if r["class"] == "verb":
                src[wid(text, r["book"], r["chapter"], r["verse"], r["i"])] = r["source"]
        d = DATA / "clause-scheme" / "nt" / ed
        pred = {r["clause"]: r["pred"] for r in pq.read_table(d / "clauses.parquet", columns=["clause", "pred"]).to_pylist()}
        cons = pq.read_table(d / "constituents.parquet", columns=["clause", "role"]).to_pylist()
        has_o = {r["clause"] for r in cons if r["role"] in ("o", "o2")}
        todo = [(pred[r["clause"]], r["clause"], "s" if r["role"] == "s" else "o") for r in cons if r["role"] in ("s", "o", "o2") and pred[r["clause"]] in V]
        todo += [(r["verb"], r["clause"], "s") for r in pq.read_table(d / "added.parquet", columns=["verb", "clause"]).to_pylist() if r["verb"] in V]
        c = collections.Counter()
        for v, clause, role in todo:
            lex, stem = V[v][3], V[v][4]
            c[(role, "places")] += 1
            got, step, _ = F.label(lex, stem, role, clause in has_o)
            if got:
                c[(role, "settled without the model")] += 1
                continue
            m = model.get(v)
            if stem or m is None:
                c[(role, "open: " + ("the Tanakh does not settle it" if stem else "no stem, not read"))] += 1
            elif not m["stem"]:
                c[(role, "open: read as no verb form")] += 1
            else:
                got, step, _ = F.label(lex, m["stem"], role, clause in has_o)
                if got is None:
                    c[(role, "open: stem read, the Tanakh does not settle it")] += 1
                else:
                    c[(role, f"settled on a model-read stem ({m['sureness']})")] += 1
                    c[(role, f"  of these by step {step}")] += 1
                    if step != "stem+object" and src.get(v) != "macula":
                        c[(role, "  of these on a lexeme the word table's model gave")] += 1
        res[ed] = {f"{role}|{k}": n for (role, k), n in sorted(c.items())}
        for role in ("s", "o"):
            tot = c[(role, "places")]
            base = c[(role, "settled without the model")]
            sure = c[(role, "settled on a model-read stem (sure)")]
            rest = c[(role, "settled on a model-read stem (unsure)")] + c[(role, "settled on a model-read stem (two)")]
            print(f"{ed} {role}: {tot:,} places; settled without the model {base / tot:.1%}; with stems read sure {(base + sure) / tot:.1%}; with every read stem {(base + sure + rest) / tot:.1%}")
            print("    ", {k: n for (r, k), n in sorted(c.items()) if r == role and k != "places"})
    acc = json.loads((out / "ACCOUNT.json").read_text(encoding="utf-8"))
    acc["frame_label_coverage"] = res
    (out / "ACCOUNT.json").write_text(json.dumps(acc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=["prepare", "run", "score", "tokens", "table", "coverage"])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--set", default="a1")
    ap.add_argument("--cap", type=float, default=10.0, help="stop when the reported cost over all sets (USD) reaches this")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    if a.step == "prepare":
        prepare(a.out)
    elif a.step == "run":
        run(a.out, a.set, a.cap, a.limit, a.workers)
    elif a.step == "score":
        score(a.out)
    elif a.step == "tokens":
        tokens(a.out)
    elif a.step == "table":
        table(a.out)
    else:
        coverage(a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
