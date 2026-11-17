#!/usr/bin/env python3
"""Review of the heb_scg alignment, stages 2-3 of docs/scg-review-design.md: a Jev check per content Greek word, calibrated on
the blind reference set (scg_check.py rounds 1-2), a correction layer that attributes every decision, and batches for Claude.

  ask --set ref|pool [--max-usd X] [--limit N]   one Jev Choice per Greek word (cached in answers.jsonl; asks only what is missing).
                                                 Options: the current link ("cur"), each other Hebrew word of the verse ("w<n>"),
                                                 "none". Bridge renderings are marked in the state as evidence, never as the answer.
  calibrate [--target 0.95]                      on the reference words of the review pool (K+ is accepted by the bridge, never
                                                 Jev's), split in halves by Greek id (A: even hash, B: odd): per kind of decision
                                                 (keep, move, add, none) the lowest probability threshold whose decisions on A agree
                                                 with Claude's blind judgment at >= target (group-weighted, >= 8 decided) is tested
                                                 on B; a kind with no such threshold always goes to Claude; calibration.json
  layer                                          corrections.jsonl: one line per content Greek word with decided_by = published
                                                 (bridge-accepted) | jev-check-v1 | pending (to Claude) | claude-review-v1 (batches
                                                 judged); claude.tsv holds Claude's judgments
  batches [--size 20]                            the pending words, error-likely groups first, as batches/bNNNN.md for Claude
  mark --set ref|layer [--max-usd X]            how a link carries the Greek word (rules v2): lexical / phrase / free, one Jev
                                                 Choice per linked word (marks.jsonl). ref: the words Claude judged blind, linked to
                                                 Claude's rendering (gold mark from the note: free / phrase words, else lexical);
                                                 layer: every link Jev decided. mark-score: Jev vs the gold marks
  spot [--n 30]                                  the running check (held-out test of stage 2): N random words of each kind Jev
                                                 decided (keep, move, add, none), shown WITHOUT Jev's answer, for Claude to judge
                                                 blind by the hand-check rules (spot/judgments.tsv); spot-score scores Jev on them

A Jev answer is "right" against the reference when: cur and the link was judged right or partial; w<n> and n is in the judged
rendering; none and the judged rendering is "-". Never decided by Jev, always to Claude: moving or dropping a link the bridge
supports. Output under $MAKE_TANAKH_PRIVATE/rules/bridge/scg_review/ (SCG_EDITION=heb_mod: Delitzsch, bridge/hebmod/review/). TYPESAFE_API_KEY from the work repo's .env (never printed).
    . ./env.sh; set -a; . $MAKE_TANAKH_WORK/.env; set +a; ~/sil-study/.venv/bin/python lab/bridge/scg_review.py ask --set ref --max-usd 2"""
import argparse, collections, concurrent.futures as cf, hashlib, json, os, re, sys, threading, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scg_check as S  # noqa: E402

OUT = os.path.join(S.P, "bridge", "scg_review" if S.ED == "heb_scg" else "hebmod/review"); MODEL = "jev-latest"; RULES = "scg-review rules v2 (docs/scg-review-design.md)"; MARK_P = 0.7
PRICE_PER_M_INPUT = 0.042                       # USD per million input tokens, as lexeme-aligner's jev_clauses (2026-10)
ORDER = ("N+", "N-", "U-none", "E-", "K-", "U", "E+")   # error-likely first (RUN.md 2026-10-31)
INSTR = (f"`hebrew_verse` is the {S.E['name']} Hebrew translation of `greek_verse`. Which option renders the Greek word marked "
         "[[like this]], described in `greek_word`? A rendering carries the word's meaning in this verse: it may be another part of "
         "speech (a verb for a noun), a pronoun suffix, or part of a free paraphrase; choose the Hebrew word that carries it. Choose "
         "`cur` if the current link carries the meaning, even when it also takes in a small extra word. Choose `none` only if no Hebrew "
         "word carries this Greek word's meaning in this verse (a copula or auxiliary left out, a light verb absorbed into another "
         "word, the phrase placed in another verse). Words marked `bridge` are lexical equivalents of the Greek lexeme elsewhere in "
         "the Bible: evidence, not the answer; another occurrence or another word may be the rendering here.")


def pool_items(gr):
    out = []
    for g, its in gr.items():
        if g == "K+":
            continue
        for it in its:
            out.append(dict(it, group=("U-none" if g == "U" and it["cls"] == "none" else g)))
    return out


def ref_items():
    out = {}
    for d in (S.OUT, os.path.join(S.OUT, "round2")):
        key = json.load(open(os.path.join(d, "key.json"))); J = S.judgments(d)
        for iid, it in key.items():
            j = J[iid]; ren = [int(x) for x in j[2].split(",")] if j[2] != "-" else []
            grp = it["group"] if it["group"] != "U" or it["cls"] != "none" else "U-none"
            out[it["g"]] = dict(it, group=grp, gold=dict(link=j[1], rendering=ren, note=j[3] if len(j) > 3 else ""))
    return out


def question(it, B, G, H, byv):
    vk = (it["book"], it["ch"], it["v"]); hv = H[vk]; gw = G[it["g"]]
    cand = {h for h, *_ in B.get(str(gw["strong"]), [])}
    toks = collections.OrderedDict()
    for (t, p), x in sorted(hv.items()):
        toks.setdefault(t, {"n": t, "word": x["word"], "parts": []})
        toks[t]["parts"].append(x["text"])
        if x["strong"] in cand:
            toks[t]["bridge"] = True
    link = sorted({t for t, p in map(tuple, it["link"])})
    greek = " ".join(f"[[{x['text']}]]" if k in it["gids"] else x["text"] for k, x in byv[vk])
    crit = {}
    if link:
        crit["cur"] = "the current link: Hebrew word(s) " + ", ".join(f"{t} {toks[t]['word']}" for t in link if t in toks)
    for t, x in toks.items():
        if t not in link:
            crit[f"w{t}"] = f"Hebrew word {t}: {x['word']}"
    crit["none"] = "not rendered: no Hebrew word in this verse carries the marked Greek word's meaning"
    state = {"greek_verse": greek, "greek_word": {"text": gw["text"], "lemma": gw["lemma"], "strong": gw["strong"], "class": gw["cls"]},
             "hebrew_verse": list(toks.values()), "current_link": {"words": link, "parts": [f"{t}.{p}" for t, p in map(tuple, it["link"])]}}
    return state, {"type": "choice", "criteria": crit, "instructions": INSTR}, cand


def ask_jev(state, q):
    body = json.dumps({"model": MODEL, "state": state, "questions": {"q": q}}).encode("utf-8")
    req = urllib.request.Request("https://api.typesafe.ai/v1/systemone", data=body, method="POST",
                                 headers={"Authorization": "Bearer " + os.environ["TYPESAFE_API_KEY"], "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:                        # noqa: BLE001
            if attempt == 3:
                raise
            print("retry", attempt, type(e).__name__, file=sys.stderr); time.sleep(2 * (attempt + 1))


def answers():
    p = os.path.join(OUT, "answers.jsonl"); out = {}
    if os.path.exists(p):
        for l in open(p, encoding="utf-8"):
            x = json.loads(l); out[x["gid"]] = x
    return out


def ask(a):
    B, G, H = S.load(); os.makedirs(OUT, exist_ok=True)
    byv = collections.defaultdict(list)
    for k, x in G.items():
        byv[(x["book"], x["ch"], x["v"])].append((k, x))
    items = list(ref_items().values()) if a.set == "ref" else sorted(pool_items(S.groups(B, G, H)), key=lambda it: ORDER.index(it["group"]))
    have = answers(); todo = [it for it in items if it["g"] not in have]
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(items)} words, {len(todo)} to ask", file=sys.stderr)
    lock = threading.Lock(); spent = collections.Counter(); f = open(os.path.join(OUT, "answers.jsonl"), "a", encoding="utf-8")

    def one(it):
        with lock:
            if spent["tokens"] / 1e6 * PRICE_PER_M_INPUT >= a.max_usd:
                return "capped"
        state, q, cand = question(it, B, G, H, byv)
        r = ask_jev(state, q); ans = r["answers"]["q"]; u = r.get("usage", {})
        rec = {"gid": it["g"], "ref": f"{it['book']} {it['ch']}:{it['v']}", "group": it["group"], "class": it["cls"],
               "link": it["link"], "choice": ans["choice"], "confidence": ans.get("confidence"), "probabilities": ans.get("probabilities"),
               "bridge_words": sorted(x["n"] for x in state["hebrew_verse"] if x.get("bridge")), "model": r.get("model"),
               "date": time.strftime("%Y-%m-%d")}
        with lock:
            spent["tokens"] += u.get("input_tokens", 0); spent["asked"] += 1
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
            if spent["asked"] % 200 == 0:
                print(spent["asked"], f"${spent['tokens'] / 1e6 * PRICE_PER_M_INPUT:.3f}", file=sys.stderr)
        return "ok"

    with cf.ThreadPoolExecutor(a.workers) as ex:
        res = collections.Counter(ex.map(one, todo))
    print(dict(res), f"input tokens {spent['tokens']:,}", f"spent ${spent['tokens'] / 1e6 * PRICE_PER_M_INPUT:.3f}")


def p_of(x):
    return (x.get("probabilities") or {}).get(x["choice"], x.get("confidence") or 0)


def right(x, gold):
    c = x["choice"]
    if c == "cur":
        return gold["link"] in ("right", "partial") and bool(x["link"])
    if c == "none":
        return not gold["rendering"]
    return int(c[1:]) in gold["rendering"]


def to_claude(x):
    """moving or dropping a link the bridge supports is never Jev's decision"""
    linked = {t for t, p in map(tuple, x["link"])}
    return x["choice"] != "cur" and bool(linked & set(x["bridge_words"]))


def half(gid):
    return "A" if int(hashlib.sha1(gid.encode()).hexdigest(), 16) % 2 == 0 else "B"


def weights():
    B, G, H = S.load(); gr = S.groups(B, G, H)
    pop = collections.Counter(it["group"] for it in pool_items(gr)); pop["K+"] = len(gr["K+"]); return pop


def kind(x):
    return "keep" if x["choice"] == "cur" else ("none" if x["choice"] == "none" else ("move" if x["link"] else "add"))


def decided(x, th):
    t = th.get(kind(x)) if isinstance(th, dict) else th
    return t is not None and p_of(x) >= t and not to_claude(x)


def precision(xs, R, pop, th):
    """group-weighted share right among the decided; decided share; n decided. th: one threshold or {kind: threshold or None}"""
    by = collections.defaultdict(lambda: [0, 0, 0])
    for x in xs:
        g = R[x["gid"]]["group"]; by[g][2] += 1
        if decided(x, th):
            by[g][0] += 1; by[g][1] += right(x, R[x["gid"]]["gold"])
    num = sum(pop[g] * c / n for g, (d, c, n) in by.items() if n)
    den = sum(pop[g] * d / n for g, (d, c, n) in by.items() if n)
    tot = sum(pop[g] for g, (d, c, n) in by.items() if n)
    return (num / den if den else 0), (den / tot if tot else 0), sum(d for d, c, n in by.values())


def calibrate(a):
    R = {g: r for g, r in ref_items().items() if r["group"] != "K+"}; A = answers(); pop = weights()
    xs = [A[g] for g in R if g in A]
    ha = [x for x in xs if half(x["gid"]) == "A"]; hb = [x for x in xs if half(x["gid"]) == "B"]
    print(f"review-pool reference words: {len(xs)} (A {len(ha)}, B {len(hb)})")
    print("| kind | answers (right/all) | threshold (chosen on A) | A: right/decided | B: right/decided |\n|---|---|---|---|---|")
    th = {}
    for k in ("keep", "move", "add", "none"):
        ka = [x for x in ha if kind(x) == k]; kb = [x for x in hb if kind(x) == k]; ks = ka + kb
        th[k] = None
        for t in [i / 100 for i in range(30, 100)]:
            dec = [x for x in ka if decided(x, t)]
            if len(dec) >= 8 and sum(right(x, R[x["gid"]]["gold"]) for x in dec) / len(dec) >= a.target:
                th[k] = t; break
        ra = [x for x in ka if decided(x, th[k])]; rb = [x for x in kb if decided(x, th[k])]
        f = lambda xs: f"{sum(right(x, R[x['gid']]['gold']) for x in xs)}/{len(xs)}"
        print(f"| {k} | {f(ks)} | {th[k] if th[k] is not None else 'none: always Claude'} | {f(ra)} | {f(rb)} |")
    for name, h in (("A", ha), ("B", hb)):
        pr, share, n = precision(h, R, pop, th)
        print(f"{name}: group-weighted precision of Jev's decisions {pr:.1%}, decided share {share:.1%} (n {n})")
    for x in xs:
        if decided(x, th) and not right(x, R[x["gid"]]["gold"]):
            print("  decided but disagrees:", x["ref"], x["group"], x["choice"], round(p_of(x), 2), R[x["gid"]]["gold"]["note"])
    json.dump({"thresholds": th, "target": a.target, "model": MODEL, "date": time.strftime("%Y-%m-%d"),
               "note": "per kind, chosen on half A of the review-pool reference words, tested on half B"},
              open(os.path.join(OUT, "calibration.json"), "w"), indent=1)


MARK_INSTR = (f"`hebrew_verse` is the {S.E['name']} Hebrew translation of `greek_verse`. The Hebrew word(s) marked [[like this]] "
              "carry the meaning of the Greek word marked [[like this]] (described in `greek_word`). How do they carry it?")
MARK_CRIT = {
    "lexical": "a translation of the Greek word itself: a Hebrew word of the same meaning, whatever the grammar (a participle as a finite "
               "verb, an adjective as a noun, a pronoun suffix for a Greek pronoun, a proper name)",
    "phrase": "the Greek word is part of a unit that the Hebrew renders as a whole: a light or helping verb (συμβούλιον ἔλαβον = they "
              "consulted; ἦν with a participle; πληγὰς ἐπιθέντες = struck), 'have' expressed by the preposition ל, an idiom, or a word "
              "left out in the Hebrew and carried by the same word of a parallel clause",
    "free": "the Hebrew rewords the thought: the marked Hebrew word takes the Greek word's place in the sentence but with another "
            "meaning (οὐκ ἔστιν ἐκ πίστεως = does not seek faith; a pronoun suffix standing for a Greek noun)"}
MARKS_RE = (("free", re.compile(r"\bfree\b")),
            ("phrase", re.compile(r"phrase|idiom|light verb|periphrastic|possession|shared|pronoun copula|copula הוא|no word of its own")))


def gold_mark(note):
    for m, rx in MARKS_RE:
        if rx.search(note or ""):
            return m
    return "lexical"


def mark_question(it, words, B, G, H, byv):
    vk = (it["book"], it["ch"], it["v"]); gw = G[it["g"]]; hv = H[vk]; toks = collections.OrderedDict()
    for (t, p), x in sorted(hv.items()):
        toks.setdefault(t, x["word"])
    greek = " ".join(f"[[{x['text']}]]" if k in it["gids"] else x["text"] for k, x in byv[vk])
    heb = " ".join(f"[[{w}]]" if t in words else w for t, w in toks.items())
    state = {"greek_verse": greek, "greek_word": {"text": gw["text"], "lemma": gw["lemma"], "class": gw["cls"]}, "hebrew_verse": heb}
    return state, {"type": "choice", "criteria": MARK_CRIT, "instructions": MARK_INSTR}


def marks():
    p = os.path.join(OUT, "marks.jsonl"); out = {}
    if os.path.exists(p):
        for l in open(p, encoding="utf-8"):
            x = json.loads(l); out[x["gid"]] = x
    return out


def mark_targets(a, B, G, H):
    """[(item, linked Hebrew words, gold mark or None)]"""
    items = {it["g"]: it for it in pool_items(S.groups(B, G, H))}; out = []
    if a.set == "ref":
        for gid, r in ref_items().items():
            if r["gold"]["rendering"]:
                out.append((r, set(r["gold"]["rendering"]), gold_mark(r["gold"]["note"])))
        for d in ("spot", "spot2"):
            key = json.load(open(os.path.join(OUT, d, "key.json"))); J = S.judgments(os.path.join(OUT, d))
            for iid, k in key.items():
                j = J.get(iid)
                if j and j[2] != "-":
                    out.append((items[k["gid"]], {int(v) for v in j[2].split(",")}, gold_mark(j[3] if len(j) > 3 else "")))
        return out
    for l in open(os.path.join(OUT, "corrections.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        if r["decided_by"] != "jev-check-v1":
            continue
        aft = r["after"]; w = set(aft["words"]) if "words" in aft else {t for t, p in map(tuple, aft["link"])}
        if w:
            out.append((items[r["gid"]], w, None))
    return out


def mark(a):
    B, G, H = S.load(); byv = collections.defaultdict(list)
    for k, x in G.items():
        byv[(x["book"], x["ch"], x["v"])].append((k, x))
    have = marks(); todo = [t for t in mark_targets(a, B, G, H) if t[0]["g"] not in have]
    print(len(todo), "to ask", file=sys.stderr)
    lock = threading.Lock(); spent = collections.Counter(); f = open(os.path.join(OUT, "marks.jsonl"), "a", encoding="utf-8")

    def one(t):
        it, words, gold = t
        with lock:
            if spent["tokens"] / 1e6 * PRICE_PER_M_INPUT >= a.max_usd:
                return "capped"
        state, q = mark_question(it, words, B, G, H, byv); r = ask_jev(state, q); ans = r["answers"]["q"]
        rec = {"gid": it["g"], "words": sorted(words), "mark": ans["choice"], "probabilities": ans.get("probabilities"), "gold": gold,
               "model": r.get("model"), "date": time.strftime("%Y-%m-%d")}
        with lock:
            spent["tokens"] += r.get("usage", {}).get("input_tokens", 0); spent["asked"] += 1
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
            if spent["asked"] % 1000 == 0:
                print(spent["asked"], f"${spent['tokens'] / 1e6 * PRICE_PER_M_INPUT:.3f}", file=sys.stderr)
        return "ok"

    with cf.ThreadPoolExecutor(a.workers) as ex:
        res = collections.Counter(ex.map(one, todo))
    print(dict(res), f"spent ${spent['tokens'] / 1e6 * PRICE_PER_M_INPUT:.3f}")


def mark_score(a):
    M = [x for x in marks().values() if x.get("gold")]; conf = collections.Counter((x["gold"], x["mark"]) for x in M)
    print(f"Jev vs Claude's marks: {sum(conf[(m, m)] for m in MARK_CRIT)}/{len(M)}")
    print("| Claude \\ Jev | " + " | ".join(MARK_CRIT) + " |\n|---|---|---|---|")
    for g in MARK_CRIT:
        print(f"| {g} | " + " | ".join(str(conf[(g, m)]) for m in MARK_CRIT) + " |")
    for t in (0.5, 0.7, 0.9):
        d = [x for x in M if x["probabilities"].get(x["mark"], 0) >= t]
        print(f"p >= {t}: {sum(x['gold'] == x['mark'] for x in d)}/{len(d)}")


def claude():
    p = os.path.join(OUT, "claude.tsv"); out = {}
    if os.path.exists(p):
        for l in open(p, encoding="utf-8"):
            if l.strip() and not l.startswith("#"):
                f = l.rstrip("\n").split("\t"); out[f[0]] = f
    return out


def claude_how(note):
    """The mark of a Claude judgment: its note's prefix (rules v2), else the note read as gold_mark reads it."""
    pre = (note or "").split(":", 1)[0].strip()
    return pre if pre in MARK_CRIT else gold_mark(note)


def jev_how(m, words):
    """Jev's mark when it is sure (MARK_P, calibrated 237/250 on Claude's marks) and was asked about these words."""
    if not m or set(m["words"]) != set(words):
        return "uncertain"
    return m["mark"] if (m.get("probabilities") or {}).get(m["mark"], 0) >= MARK_P else "uncertain"


def layer(a):
    B, G, H = S.load(); gr = S.groups(B, G, H); A = answers(); C = claude(); MK = marks()
    th = json.load(open(os.path.join(OUT, "calibration.json")))["thresholds"]
    st = collections.Counter(); hw = collections.Counter()
    with open(os.path.join(OUT, "corrections.jsonl"), "w", encoding="utf-8") as f:
        for it in gr["K+"]:
            f.write(json.dumps({"gid": it["g"], "before": {"link": it["link"], "class": it["cls"]}, "after": {"link": it["link"], "status": "kept"},
                                "how": "lexical", "decided_by": "published", "evidence": {"bridge": "agrees"}}, ensure_ascii=False) + "\n")
            st["published"] += 1; hw[("published", "lexical")] += 1
        for it in pool_items(gr):
            x = A.get(it["g"]); rec = {"gid": it["g"], "ref": f"{it['book']} {it['ch']}:{it['v']}", "group": it["group"],
                                       "before": {"link": it["link"], "class": it["cls"]}}
            if x:
                rec["evidence"] = {"bridge": x["bridge_words"], "jev": {"choice": x["choice"], "p": round(p_of(x), 3),
                                                                       "model": x["model"], "date": x["date"]}}
            if it["g"] in C:
                c = C[it["g"]]; rec["after"] = {"words": [int(v) for v in c[2].split(",")] if c[2] != "-" else [], "verdict": c[1]}
                note = c[3] if len(c) > 3 else ""
                rec.update(how=claude_how(note) if rec["after"]["words"] else None, decided_by="claude-review-v1", note=note, rules=RULES,
                           model=c[4] if len(c) > 4 else "", date=c[5] if len(c) > 5 else "")
            elif x and decided(x, th):
                ch = x["choice"]
                rec["after"] = ({"link": it["link"], "status": "kept"} if ch == "cur" else {"words": [], "status": "not rendered"} if ch == "none"
                                else {"words": [int(ch[1:])], "status": "changed" if it["link"] else "added"})
                w = rec["after"]["words"] if "words" in rec["after"] else [t for t, p in map(tuple, it["link"])]
                m = MK.get(it["g"])
                if m and w:
                    rec.setdefault("evidence", {})["mark"] = {"choice": m["mark"], "p": (m.get("probabilities") or {}).get(m["mark"]),
                                                              "model": m.get("model"), "date": m.get("date")}
                rec.update(how=jev_how(m, w) if w else None, decided_by="jev-check-v1", threshold=th[kind(x)])
            else:
                rec.update(decided_by="pending")
            st[rec["decided_by"]] += 1; hw[(rec["decided_by"], rec.get("how") or "-")] += 1
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(dict(st))
    for (d, h), n in sorted(hw.items()):
        print(f"  {d:18} {h:10} {n}")


def batches(a):
    B, G, H = S.load(); A = answers(); C = claude()
    byv = collections.defaultdict(list)
    for k, x in G.items():
        byv[(x["book"], x["ch"], x["v"])].append((k, x))
    items = {it["g"]: it for it in pool_items(S.groups(B, G, H))}
    pend = [json.loads(l) for l in open(os.path.join(OUT, "corrections.jsonl"), encoding="utf-8")]
    pend = sorted((r for r in pend if r["decided_by"] == "pending" and r["gid"] not in C), key=lambda r: ORDER.index(r["group"]))
    d = os.path.join(OUT, "batches"); os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    for b in range(0, len(pend), a.size):
        md = []
        for r in pend[b:b + a.size]:
            it = items[r["gid"]]; state, q, cand = question(it, B, G, H, byv); x = A.get(r["gid"])
            top = sorted((x or {}).get("probabilities", {}).items(), key=lambda kv: -kv[1])[:2]
            md += [f"## {r['gid']}  {r['ref']}  ({r['group']})", f"Greek word: **{state['greek_word']['text']}** ({state['greek_word']['lemma']}, {state['greek_word']['class']})",
                   f"Greek: {state['greek_verse']}",
                   "Hebrew: " + " ".join(f"{w['n']}:{w['word']}{'*' if w.get('bridge') else ''}" for w in state["hebrew_verse"]),
                   f"Linked: {state['current_link']['words'] or '-'} (parts {', '.join(state['current_link']['parts']) or '-'})",
                   "Jev: " + (", ".join(f"{k} {v:.2f}" for k, v in top) or "-") + "   (* = bridge rendering)", ""]
        open(os.path.join(d, f"b{b // a.size + 1:04d}.md"), "w", encoding="utf-8").write("\n".join(md))
    print(len(pend), "pending words in", -(-len(pend) // a.size), "batches ->", d)


def spot(a):
    B, G, H = S.load(); A = answers(); th = json.load(open(os.path.join(OUT, "calibration.json")))["thresholds"]
    byv = collections.defaultdict(list)
    for k, x in G.items():
        byv[(x["book"], x["ch"], x["v"])].append((k, x))
    items = {it["g"]: it for it in pool_items(S.groups(B, G, H))}; R = ref_items(); rnd = S.random.Random(31)
    by = collections.defaultdict(list)
    for g, x in A.items():
        if g in items and g not in R and decided(x, th):
            by[kind(x)].append(g)
    pick = []
    for k in ("keep", "move", "add", "none"):
        gs = sorted(by[k]); rnd.shuffle(gs); pick += gs[:a.n]
    rnd.shuffle(pick); d = os.path.join(OUT, "spot"); os.makedirs(d, exist_ok=True); md = []; key = {}
    for i, g in enumerate(pick, 1):
        iid = f"s{i:03d}"; it = items[g]; key[iid] = {"gid": g, "kind": kind(A[g]), "group": it["group"]}
        state, q, cand = question(it, B, G, H, byv)
        md += [f"## {iid}  {it['book']} {it['ch']}:{it['v']}", f"Greek word: **{state['greek_word']['text']}** ({state['greek_word']['lemma']}, {state['greek_word']['class']})",
               f"Greek: {state['greek_verse']}", "Hebrew: " + " ".join(f"{w['n']}:{w['word']}" for w in state["hebrew_verse"]),
               f"Linked: {state['current_link']['words'] or '-'} (parts {', '.join(state['current_link']['parts']) or '-'})", ""]
    open(os.path.join(d, "items.md"), "w", encoding="utf-8").write("\n".join(md)); json.dump(key, open(os.path.join(d, "key.json"), "w"))
    print({k: min(len(v), a.n) for k, v in by.items()}, "->", d)


def spot_score(a):
    d = os.path.join(OUT, "spot"); key = json.load(open(os.path.join(d, "key.json"))); J = S.judgments(d); A = answers()
    st = collections.defaultdict(collections.Counter)
    for iid, k in key.items():
        if iid not in J:
            continue
        j = J[iid]; gold = {"link": j[1], "rendering": [int(v) for v in j[2].split(",")] if j[2] != "-" else []}
        x = A[k["gid"]]; ok = right(x, gold); st[k["kind"]]["n"] += 1; st[k["kind"]]["right"] += ok
        if not ok:
            print("  disagrees:", iid, x["ref"], k["kind"], x["choice"], round(p_of(x), 2), j[3] if len(j) > 3 else "")
    for k in ("keep", "move", "add", "none"):
        n, r = st[k]["n"], st[k]["right"]
        if n:
            print(f"{k}: Jev agrees with Claude's blind judgment on {r}/{n} ({S.ci(r, n)})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["ask", "calibrate", "layer", "batches", "spot", "spot-score", "mark", "mark-score"])
    ap.add_argument("--set", choices=["ref", "pool", "layer"], default="ref"); ap.add_argument("--max-usd", type=float, default=0.0)
    ap.add_argument("--limit", type=int, default=0); ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--target", type=float, default=0.95); ap.add_argument("--size", type=int, default=20); ap.add_argument("--n", type=int, default=30)
    a = ap.parse_args(); {"ask": ask, "calibrate": calibrate, "layer": layer, "batches": batches, "spot": spot, "spot-score": spot_score, "mark": mark, "mark-score": mark_score}[a.cmd](a)
