"""Stage 43 of the Hebrew levels: level texts, the operations log, verse lines, changed verses, measurements 1, 2, 4, 5,
the error-anatomy join table, the pack and the reader's sample (SPEC-levels 6 to 9, 10 stage 43)."""
import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa

import levels_drafts as L
from levels_common import CONTENT, I1, ROOT, jdump, sha256, write_parquet, write_text, write_tsv

S, I, B = pa.string(), pa.int64(), pa.bool_()
WORDS = pa.schema([("t", I), ("book", S), ("chapter", I), ("verse", I), ("w", I), ("text", S), ("after", S),
                   ("sentence", I), ("clause", S), ("op", S)])
PIECES = pa.schema([("t", I), ("n", I), ("text", S), ("kind", S), ("lexeme", S), ("class", S), ("marks", S), ("who", S),
                    ("who_basis", S), ("op", S)])
LINKS = pa.schema([("t", I), ("n", I), ("s", I), ("agree", I), ("agree_model", I), ("other", S), ("how", S),
                   ("basis", S), ("s_n", I)])
OPS = pa.schema([("op", S), ("level", S), ("text", S), ("switch", S), ("setting", S), ("key", S),
                 ("scoring_closed", B), ("src_t", I), ("src_n", I), ("added_clause", S), ("added_role", S),
                 ("state", S), ("reason", S), ("detail", S), ("rule", S), ("before", S), ("after", S),
                 ("lexeme_before", S), ("lexeme_after", S), ("ent", S), ("tier", S), ("chosen_by", S),
                 ("routes_all", S), ("grade", S), ("form_rule", S), ("draft_t", S)])
KEPT = pa.schema([("level", S), ("text", S), ("clause", S), ("key", S), ("scoring_closed", B), ("covered", B),
                  ("who_kept", B), ("roles_kept", B), ("event_kept", B), ("links_kept", B), ("anchor_kept", B),
                  ("ok", B)])
PAIR = pa.schema([("level", S), ("g", I), ("edited", S), ("state_l0", S), ("state_mod", S), ("state_scg", S),
                  ("state_both", S)])
REFS = pa.schema([("level", S), ("text", S), ("key", S), ("scoring_closed", B), ("src_t", I), ("src_n", I),
                  ("ent", S), ("person", S), ("form_src", S), ("form_draft", S), ("right", B)])
ANAT = pa.schema([("text", S), ("key", S), ("t", I), ("n", I), ("scoring_closed", B), ("piece_text", S), ("kind", S),
                  ("class", S), ("lexeme", S), ("level", I), ("level_kind", S), ("band", S), ("sense", S),
                  ("sense_level", I), ("domain", S), ("ref_status", S), ("ref_form", S), ("who", S),
                  ("who_basis", S), ("layout", S), ("line_kind", S), ("in_quote", B), ("changed_in", S), ("ops", S)])
KEEP_POINT = set(range(0x05B0, 0x05BD)) | {0x05C1, 0x05C2, 0x05C7}


# ------------------------------------------------------------------ rule IN (7.3)

def norm_cons(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn").replace("־", " ")
    s = "".join(ch if ("א" <= ch <= "ת" or ch == " ") else " " for ch in s)
    return " ".join(s.split())


def norm_point(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn" or ord(ch) in KEEP_POINT).replace("־", " ")
    s = "".join(ch if ("א" <= ch <= "ת" or ch == " " or ord(ch) in KEEP_POINT) else " " for ch in s)
    return " ".join(s.split())


def raw_lines(text, words):
    """(book, chapter, verse) -> raw line, in text order; words: dicts with book, chapter, verse, text, after."""
    out, order = defaultdict(list), []
    for w in words:
        k = (w["book"], w["chapter"], w["verse"])
        if k not in out:
            order.append(k)
        out[k].append(w["text"] + w["after"] if text == "hbo" else w["text"])
    return [(k, "".join(out[k]) if text == "hbo" else " ".join(out[k])) for k in order]


# ------------------------------------------------------------------ one (level, text)

def finish_level(T, level, dwords, ops):
    """Sort and key the ops, number the draft, and make the rows of words, pieces, links and the op rows."""
    order = sorted(range(len(ops)), key=lambda i: (ops[i]["src_t"], ops[i]["src_n"], ops[i]["switch"],
                                                   ops[i]["added_role"], ops[i]["added_clause"]))
    key_of = {}
    for j, i in enumerate(order, 1):
        key_of[i] = f"op:{level}:{T.code}:{j}"
    t_of = {}
    W, P, K = [], [], []
    wpos = Counter()
    for t, dw in enumerate(dwords, 1):
        src = dw["src"]
        vk = (src["book"], src["chapter"], src["verse"])
        wpos[vk] += 1
        t_of[id(dw["obj"])] = t
        opk = key_of[dw["op"]] if dw["op"] is not None else ""
        W.append({"t": t, "book": src["book"], "chapter": src["chapter"], "verse": src["verse"], "w": wpos[vk],
                  "text": dw["text"], "after": dw["after"], "sentence": src["sentence"], "clause": src["clause"],
                  "op": opk})
        for n, q in enumerate(dw["pieces"], 1):
            P.append({"t": t, "n": n, "text": q["text"], "kind": q["kind"], "lexeme": q["lexeme"], "class": q["class"],
                      "marks": q["marks"], "who": q["who"], "who_basis": q["who_basis"], "op": opk})
            for part, s, s_n, how in q["links"]:
                K.append({"t": t, "n": n, "s": s, "agree": 1, "agree_model": None, "other": part, "how": how,
                          "basis": "derived", "s_n": s_n})
    rows = []
    for i in order:
        o = ops[i]
        r = {k: v for k, v in o.items() if not k.startswith("_")}
        r["op"] = key_of[i]
        r["detail"] = jdump(o["detail"])
        r["chosen_by"] = jdump(o["chosen_by"] if o["chosen_by"] is not None else [])
        r["routes_all"] = jdump(o["routes_all"] if o["routes_all"] is not None else [])
        dts = [t_of[id(w)] for w in o["_words"]]
        r["draft_t"] = jdump(dts)
        r["after"] = " ".join(W[t - 1]["text"] for t in dts)
        rows.append(r)
    extra = {"over_v": sum(1 for o in ops if o.get("_over_v"))}
    return W, P, K, rows, extra


def cols(rows, schema):
    return {f.name: [r[f.name] for r in rows] for f in schema}


def lexemes_tsv(P, lexicon):
    cnt = Counter(p["lexeme"] for p in P if p["lexeme"])
    return [(lx, lexicon.get(lx, {}).get("lemma", ""), lexicon.get(lx, {}).get("class", ""), cnt[lx]) for lx in sorted(cnt)]


# ------------------------------------------------------------------ measurements

def content_lexeme(lex, lx):
    r = lex.get(lx)
    return bool(r) and r["class"] in CONTENT and r["state"] not in ("name", "function")


def m1_kept(T, level, W, P, K, ops, grc):
    """Measurement 1 (8.1) for one (level, text)."""
    applied = [o for o in ops if o["state"] == "applied"]
    clauses, seen = [], set()
    for o in applied:
        pn = T.part_of[o["src_t"]]
        for c in (T.word(o["src_t"])["clause"], o["added_clause"]):
            if c and (pn, c) not in seen:
                seen.add((pn, c))
                clauses.append((pn, c, o["src_t"]))
    wop = {w["t"]: w["op"] for w in W}
    reach = defaultdict(list)          # (part, s, s_n) -> [(t, n)]
    for k in K:
        reach[(k["other"], k["s"], k["s_n"])].append((k["t"], k["n"]))
    reach_t = defaultdict(set)         # (part, s) -> {draft t}
    for k in K:
        reach_t[(k["other"], k["s"])].add(k["t"])
    dp = {(p["t"], p["n"]): p for p in P}
    dwords_by_clause = defaultdict(list)
    for w in W:
        dwords_by_clause[w["clause"]].append(w["t"])
    dpieces_by_t = defaultdict(list)
    for p in P:
        dpieces_by_t[p["t"]].append(p)
    a_ents = defaultdict(set)
    for o in applied:
        if o["switch"] == "a":
            a_ents[o["added_clause"]].update(L.ents(o["ent"]))
    v_ok = {(o["src_t"], o["src_n"]) for o in applied if o["switch"] == "v" and o["grade"] in ("d2", "d3")}
    rows = []
    for pn, c, ot in clauses:
        part = T.parts[pn]
        cl = part.clauses.get(c)
        swords = part.words_by_clause.get(c, [])
        spieces = [q for t in swords for q in part.pieces[t]]
        covered = all(reach.get((pn, q["t"], q["n"])) for q in spieces)
        who_src = {e for q in spieces for e in L.ents(q["who"])}
        who_draft = {e for t in dwords_by_clause.get(c, ()) for p in dpieces_by_t[t] for e in L.ents(p["who"])}
        who_kept = who_src <= who_draft and (who_draft - who_src) <= a_ents.get(c, set())
        roles = True
        for con in part.constituents.get(c, ()):
            D = set()
            for s in range(con["first"], con["last"] + 1):
                D |= reach_t.get((pn, s), set())
            if D:
                for x in range(min(D), max(D) + 1):
                    if x not in D and wop[x] == "":
                        roles = False
        event = True
        if cl and cl["pred"]:
            stp = part.stem(cl["pred"])
            event = False
            if stp is not None:
                for (t, n) in reach.get((pn, stp["t"], stp["n"]), ()):
                    d = dp[(t, n)]
                    if d["kind"] == "stem" and (d["lexeme"] == stp["lexeme"] or (stp["t"], stp["n"]) in v_ok):
                        event = True
        links = True
        if cl:
            neg = cl["m"].get("negator") or ""
            conn = cl["m"].get("connective") or []
            for q in spieces:
                if q["lexeme"] and (q["lexeme"] == neg or q["lexeme"] in conn):
                    if not any(dp[x]["lexeme"] == q["lexeme"] for x in reach.get((pn, q["t"], q["n"]), ())):
                        links = False
        anchor = True
        if T.code != "hbo" and cl and cl.get("from_clause"):
            g_ents = grc["clause_ents"].get(cl["from_clause"], set())
            anchor = (g_ents & who_src) <= who_draft
        w0 = part.words[swords[0]] if swords else T.word(ot)
        rows.append({"level": level, "text": T.code, "clause": c, "key": L.vkey(w0["book"], w0["chapter"], w0["verse"]),
                     "scoring_closed": L.scoring_closed(w0["book"], w0["chapter"]), "covered": covered,
                     "who_kept": who_kept, "roles_kept": roles, "event_kept": event, "links_kept": links,
                     "anchor_kept": anchor, "ok": covered and who_kept and roles and event and links and anchor})
    return rows


def m5_referents(T, level, P, K, ops):
    reach = defaultdict(list)
    for k in K:
        reach[(k["other"], k["s"], k["s_n"])].append((k["t"], k["n"], k["how"]))
    dp = {(p["t"], p["n"]): p for p in P}
    name_at = defaultdict(set)
    new_at = defaultdict(set)
    for o in ops:
        if o["state"] != "applied" or o["switch"] not in ("r", "a"):
            continue
        name_at[(o["src_t"], o["src_n"])] |= set(L.ents(o["ent"]))
    rows = []
    for pn, part in T.parts.items():
        for r in part.who_account:
            if r["t"] not in T.scope or r["state"] != "participant":
                continue
            p = part._by[(r["t"], r["n"])]
            es = set(L.ents(p["who"]))
            fs = {"noun": "noun", "pronoun": "pronoun", "suffix": "suffix", "verb_zero": "ending"}[r["head_kind"]]
            hits = [dp[(t, n)] for t, n, how in reach.get((pn, r["t"], r["n"]), ()) if how in ("copy", "replace")]
            ins = [dp[(t, n)] for t, n, how in reach.get((pn, r["t"], r["n"]), ())
                   if how == "insert" and dp[(t, n)]["who_basis"] == "inserted" and set(L.ents(dp[(t, n)]["who"])) & es]
            if es and es <= name_at.get((r["t"], r["n"]), set()):
                fd = "name"
            elif fs == "noun" and any(d["kind"] == "stem" and d["class"] == "noun" and es <= set(L.ents(d["who"]))
                                      for d in hits):
                fd = "noun"
            elif any(es <= set(L.ents(d["who"])) for d in hits):
                fd = fs
            else:
                fd = "lost"
            got = {e for d in hits + ins for e in L.ents(d["who"])}
            w = part.words[r["t"]]
            rows.append({"level": level, "text": T.code, "key": L.vkey(w["book"], w["chapter"], w["verse"]),
                         "scoring_closed": L.scoring_closed(w["book"], w["chapter"]), "src_t": r["t"], "src_n": r["n"],
                         "ent": " ".join(sorted(es)), "person": p["m"].get("person", ""), "form_src": fs,
                         "form_draft": fd, "right": got == es})
    rows.sort(key=lambda x: (x["src_t"], x["src_n"]))
    return rows


def reach_rows(all_ops):
    cnt = Counter()
    for o in all_ops:
        scopes = ["all"]
        if o["text"] == "hbo" and o["key"].startswith("GEN "):
            scopes.append("genesis")
        if not o["scoring_closed"]:
            scopes.append("open")
        for s in scopes:
            cnt[(o["level"], o["text"], o["switch"], o["setting"], s, o["state"], o["reason"])] += 1
    order = {"all": 0, "genesis": 1, "open": 2}
    keys = sorted(cnt, key=lambda k: (k[0], k[1], k[2], order[k[4]], k[5], k[6], k[3]))
    return [k + (cnt[k],) for k in keys]


def m2_pair(drafts, lex, dist_strict):
    """Measurement 2 (8.2). drafts[(level, text)] = (W, P, K)."""
    src_links = {}
    for e in ("heb_mod", "heb_scg"):
        m = defaultdict(set)
        for r in L._rows(e, "links"):
            if r["other"] == "grc" and r["basis"] == "linked":
                m[(r["t"], r["n"])].add(r["s"])
        src_links[e] = m

    def S(e, level):
        W, P, K = drafts[(level, e)]
        dp = {(p["t"], p["n"]): p for p in P}
        out, edited = defaultdict(set), set()
        for k in K:
            gs = src_links[e].get((k["s"], k["s_n"]))
            if not gs:
                continue
            d = dp[(k["t"], k["n"])]
            if d["kind"] == "stem" and content_lexeme(lex, d["lexeme"]):
                for g in gs:
                    out[g].add(d["lexeme"])
            if d["op"]:
                edited.update(gs)
        return out, edited

    def state(a, b):
        if a == b:
            return "same"
        if a & b:
            return "overlap"
        for x in a:
            for y in b:
                if dist_strict.get((min(x, y), max(x, y))) in ("d2", "d3"):
                    return "near"
        return "disjoint"

    levels = [lv for lv in L.LEVEL_ORDER if (lv, "heb_mod") in drafts and (lv, "heb_scg") in drafts]
    base = {e: S(e, "l0")[0] for e in ("heb_mod", "heb_scg")}
    gs = sorted(set(base["heb_mod"]) & set(base["heb_scg"]))
    rows = []
    for lv in levels:
        sm, em = S("heb_mod", lv)
        ss, es = S("heb_scg", lv)
        for g in gs:
            ed = [e for e, x in (("heb_mod", em), ("heb_scg", es)) if g in x]
            rows.append({"level": lv, "g": g, "edited": jdump(ed),
                         "state_l0": state(base["heb_mod"][g], base["heb_scg"][g]),
                         "state_mod": state(sm.get(g, set()), base["heb_scg"][g]),
                         "state_scg": state(base["heb_mod"][g], ss.get(g, set())),
                         "state_both": state(sm.get(g, set()), ss.get(g, set()))})
    return rows


def anatomy_rows(T, W42, sense_lv, ops_all):
    reached = defaultdict(set)
    for (level, text), (W, P, K, ops) in ops_all.items():
        if text != T.code:
            continue
        pop = {(p["t"], p["n"]): p["op"] for p in P}
        for k in K:
            o = pop[(k["t"], k["n"])]
            if o:
                reached[(k["other"], k["s"], k["s_n"])].add((level, o))
    rows = []
    for pn, t in T.order:
        part = T.parts[pn]
        w = part.words[t]
        head_con = None
        for c in part._cons_by_head.get(t, ()):
            if c["first"] <= t <= c["last"]:
                head_con = c
                break
        lay = ""
        for kind, a, b in part._layout:
            if a <= t <= b:
                lay = kind
                break
        cl = part.clauses.get(w["clause"]) if w["clause"] else None
        inq = False
        x = cl
        seen = 0
        while x is not None and seen < 100:
            if x["quote"]:
                inq = True
                break
            x = part.clauses.get(x["parent"]) if x["parent"] else None
            seen += 1
        for q in part.pieces[t]:
            lv = W42.lev.get(q["lexeme"]) if q["lexeme"] else None
            ss = L.single_sense(q["sense"]) if T.code == "hbo" else ""
            rs = sorted(reached.get((pn, t, q["n"]), ()))
            rows.append({"text": T.code, "key": L.vkey(w["book"], w["chapter"], w["verse"]), "t": t, "n": q["n"],
                         "scoring_closed": L.scoring_closed(w["book"], w["chapter"]), "piece_text": q["text"],
                         "kind": q["kind"], "class": q["class"], "lexeme": q["lexeme"],
                         "level": int(lv["level"]) if lv and lv["level"] != "" else None,
                         "level_kind": lv["kind"] if lv else "", "band": lv["band"] if lv else "",
                         "sense": ss, "sense_level": sense_lv.get((q["lexeme"], ss)) if ss else None,
                         "domain": q["domain"] if T.code == "hbo" else "",
                         "ref_status": head_con["ref_status"] if head_con else "",
                         "ref_form": head_con["ref_form"] if head_con else "",
                         "who": q["who"], "who_basis": q["who_basis"], "layout": lay,
                         "line_kind": (cl["m"].get("line_kind", "") if cl else ""), "in_quote": inq,
                         "changed_in": jdump(sorted({lv_ for lv_, _ in rs})), "ops": jdump(sorted({o for _, o in rs}))})
    return rows


def prepare_anatomy(T):
    for part in T.parts.values():
        cb = defaultdict(list)
        for c, cons in part.constituents.items():
            for con in cons:
                cb[con["head"]].append(con)
        for h in cb:
            cb[h].sort(key=lambda c: (c["last"] - c["first"], c["clause"], c["ord"]))
        part._cons_by_head = cb
        kinds = ("song", "lines") if T.code == "hbo" else ("ed_lines", "ed_block", "ed_qlines")
        part._layout = sorted(((p["kind"], p["first"], p["last"]) for p in part.passages if p["kind"] in kinds),
                              key=lambda x: (kinds.index(x[0]), x[1], x[2]))


# ------------------------------------------------------------------ the run

def run(out, sample_path):
    import levels_pack43
    out = Path(out)
    parts = {n: L.Part(n) for n in ("hbo", "arc", "heb_mod", "heb_scg")}
    forms, names = L.Forms(parts), L.Names(parts)
    W42 = L.Words42(out)
    lexicon = {r["lexeme"]: r for r in L.read_tsv(I1 / "lexicon" / "lexemes.tsv")}
    terms = L.read_tsv(I1 / "hbo" / "terms.tsv")
    kind_code = L.added_code(terms)
    om_lx = L.om_lexeme(forms)
    sense_lv = {(r["lexeme"], r["sense"]): int(r["level"]) for r in L.read_tsv(out / "words" / "sense_levels.tsv")}
    dist_strict = {k: d["grade_strict"] for k, d in W42.dist.items()}
    grc = grc_tables()
    all_ops, drafts, kept, refs, lines_meta, counts = [], {}, [], [], {}, {"over_v": {}}
    ops_all = {}
    texts = {}
    for code in L.TEXTS:
        T = L.Text(code, parts)
        texts[code] = T
        ctx = L.Ctx(T, forms, names, W42)
        L.prepare_a(T)
        for level in L.LEVEL_ORDER:
            if code not in L.LEVELS[level][1]:
                continue
            dwords, ops = L.run_level(ctx, level, kind_code, om_lx)
            W, P, K, rows, extra = finish_level(T, level, dwords, ops)
            counts["over_v"][f"{level}/{code}"] = extra["over_v"]
            d = out / "texts" / level / code
            write_parquet(d / "words.parquet", cols(W, WORDS), WORDS)
            write_parquet(d / "pieces.parquet", cols(P, PIECES), PIECES)
            write_parquet(d / "links.parquet", cols(K, LINKS), LINKS)
            write_tsv(d / "lexemes.tsv", ["lexeme", "lemma", "class", "count"], lexemes_tsv(P, lexicon))
            all_ops += rows
            drafts[(level, code)] = (W, P, K)
            ops_all[(level, code)] = (W, P, K, rows)
            changed = {r["key"] for r in rows if r["state"] == "applied"}
            raws = raw_lines(code, W)
            for form, fn in (("cons", norm_cons), ("point", norm_point)):
                recs = []
                for (b, c, v), raw in raws:
                    k = L.vkey(b, c, v)
                    recs.append((k, code, level, form, L.scoring_closed(b, c), k in changed, fn(raw)))
                write_tsv(out / "lines" / level / f"{code}.{form}.tsv",
                          ["key", "text", "level", "form", "scoring_closed", "changed", "line"], recs)
                lines_meta[(level, code, form)] = recs
            if level != "l0":
                kept += m1_kept(T, level, W, P, K, rows, grc)
            refs += m5_referents(T, level, P, K, rows)
    all_ops.sort(key=lambda r: (r["level"], r["text"], r["src_t"], r["src_n"], r["switch"], r["added_role"],
                                r["added_clause"]))
    write_parquet(out / "ops.parquet", cols(all_ops, OPS), OPS)
    # changed verses (7.5)
    cv = []
    for level in sorted({r["level"] for r in all_ops}):
        for code in sorted({r["text"] for r in all_ops if r["level"] == level}):
            by = defaultdict(list)
            for r in all_ops:
                if r["level"] == level and r["text"] == code and r["state"] == "applied":
                    by[r["key"]].append(r)
            for k, _, _, _, closed, _, _ in lines_meta[(level, code, "cons")]:
                if k in by:
                    cv.append((level, code, k, closed, jdump(sorted({r["switch"] for r in by[k]})), len(by[k])))
    write_tsv(out / "changed_verses.tsv", ["level", "text", "key", "scoring_closed", "switches", "ops"], cv)
    # measurements
    kept.sort(key=lambda r: (r["level"], r["text"], r["clause"]))
    write_parquet(out / "measures" / "kept.parquet", cols(kept, KEPT), KEPT)
    pair = m2_pair(drafts, lexicon, dist_strict)
    write_parquet(out / "measures" / "pair.parquet", cols(pair, PAIR), PAIR)
    reach = reach_rows(all_ops)
    write_tsv(out / "measures" / "reach.tsv", ["level", "text", "switch", "setting", "scope", "state", "reason", "places"],
              reach)
    refs.sort(key=lambda r: (r["level"], r["text"], r["src_t"], r["src_n"]))
    write_parquet(out / "measures" / "referents.parquet", cols(refs, REFS), REFS)
    write_tsv(out / "measures" / "referents_by_ent.tsv",
              ["level", "text", "ent", "places", "name", "noun", "pronoun", "suffix", "ending", "lost", "wrong"],
              by_ent(refs))
    # anatomy (8.6)
    anat = []
    for code in L.TEXTS:
        prepare_anatomy(texts[code])
        anat += anatomy_rows(texts[code], W42, sense_lv, ops_all)
    anat.sort(key=lambda r: (r["text"], r["t"], r["n"]))
    write_parquet(out / "anatomy.parquet", cols(anat, ANAT), ANAT)
    counts.update(summary_counts(all_ops, cv, kept, pair, refs, anat, lines_meta))
    counts["pair_participants"] = pair_participants(drafts, texts)
    counts["paragraph_marks"] = sum(1 for (_, raw) in raw_lines("hbo", drafts[("l0", "hbo")][0])
                                    if raw.rstrip().endswith(("ס", "פ")))
    counts["joined_forms"] = Counter(f"{r['level']}/{r['text']}/{r['rule']}/{r['form_rule']}" for r in all_ops
                                     if r["state"] == "applied" and r["form_rule"] in ("joined", "joined_tanakh"))
    counts["joined_forms"] = dict(sorted(counts["joined_forms"].items()))
    sample_md(sample_path, cv, lines_meta)
    levels_pack43.finish(out, counts, all_ops, cv, reach, sample_path)
    return counts


def by_ent(refs):
    agg = defaultdict(Counter)
    for r in refs:
        for e in r["ent"].split():
            a = agg[(r["level"], r["text"], e)]
            a["places"] += 1
            a[r["form_draft"]] += 1
            if not r["right"]:
                a["wrong"] += 1
    return [k + tuple(agg[k][c] for c in ("places", "name", "noun", "pronoun", "suffix", "ending", "lost", "wrong"))
            for k in sorted(agg)]


def grc_tables():
    import pyarrow.parquet as pq
    w = pq.read_table(I1 / "grc" / "words.parquet", columns=["t", "clause"]).to_pydict()
    p = pq.read_table(I1 / "grc" / "pieces.parquet", columns=["t", "who"]).to_pydict()
    cl = dict(zip(w["t"], w["clause"]))
    ce = defaultdict(set)
    for t, who in zip(p["t"], p["who"]):
        if who and cl.get(t):
            ce[cl[t]].update(who.split())
    return {"clause_ents": ce}


def pair_participants(drafts, texts):
    """8.2, participants as a pair: shared(l0) within shared(L) for every Greek clause carried into both editions."""
    out = {}
    fc = {}
    for e in ("heb_mod", "heb_scg"):
        part = texts[e].parts[e]
        fc[e] = {c: r.get("from_clause", "") for c, r in part.clauses.items()}
    for lv in L.LEVEL_ORDER:
        if (lv, "heb_mod") not in drafts or (lv, "heb_scg") not in drafts:
            continue
        shared = {}
        for e in ("heb_mod", "heb_scg"):
            W, P, K = drafts[(lv, e)]
            wc = {w["t"]: w["clause"] for w in W}
            m = defaultdict(set)
            for p in P:
                g = fc[e].get(wc[p["t"]], "")
                if g:
                    m[g].update(L.ents(p["who"]))
            shared[e] = m
        out[lv] = {g: shared["heb_mod"][g] & shared["heb_scg"][g] for g in set(shared["heb_mod"]) & set(shared["heb_scg"])}
    base = out.get("l0", {})
    res = {}
    for lv, m in out.items():
        exc = sorted(g for g in base if not base[g] <= m.get(g, set()))
        res[lv] = {"clauses": len(base), "exceptions": len(exc), "first": exc[:10]}
    return res


def summary_counts(all_ops, cv, kept, pair, refs, anat, lines_meta):
    c = {}
    c["ops"] = Counter(f"{r['level']}/{r['text']}/{r['switch']}/{r['state']}/{r['reason'] or r['rule']}" for r in all_ops)
    c["ops_genesis"] = Counter(f"{r['level']}/{r['switch']}/{r['state']}/{r['reason'] or r['rule']}" for r in all_ops
                               if r["text"] == "hbo" and r["key"].startswith("GEN "))
    c["changed_verses"] = Counter(f"{r[0]}/{r[1]}" for r in cv)
    c["kept"] = {f"{lv}/{tx}": [sum(1 for r in kept if r["level"] == lv and r["text"] == tx),
                                sum(1 for r in kept if r["level"] == lv and r["text"] == tx and r["ok"])]
                 for lv, tx in sorted({(r["level"], r["text"]) for r in kept})}
    c["pair_rows"] = len(pair)
    c["referents"] = Counter(f"{r['level']}/{r['text']}/{r['form_draft']}/{'right' if r['right'] else 'wrong'}"
                             for r in refs)
    c["anatomy"] = len(anat)
    c["lines"] = {f"{k[0]}/{k[1]}/{k[2]}": len(v) for k, v in lines_meta.items()}
    return {k: dict(sorted(v.items())) if isinstance(v, Counter) else v for k, v in c.items()}


def sample_md(path, cv, lines_meta):
    """sample-43.md (10, stage 43): per text, every k-th changed verse of v2_r (v2_r_a for hbo), k = rows // 20."""
    out = ["# Sample of stage 43: changed verses and their levels",
           "",
           "Rule: for each text, the rows of `changed_verses.tsv` of level `v2_r_a` (`hbo`) or `v2_r` (editions), in text",
           "order; k = rows // 20; rows 0, k, 2k, ... (the first 20). Under each verse: the source line (`l0`) and the line",
           "of every level of that text, in the `point` form (rule IN). A level marked * changed the verse.", ""]
    for code in L.TEXTS:
        lv = "v2_r_a" if code == "hbo" else "v2_r"
        rows = [r for r in cv if r[0] == lv and r[1] == code]
        k = max(1, len(rows) // 20)
        pick = rows[::k][:20]
        out.append(f"## {code} (level {lv}: {len(rows)} changed verses; k = {k})")
        out.append("")
        idx = {lev: {r[0]: r for r in lines_meta[(lev, code, "point")]}
               for lev in L.LEVEL_ORDER if (lev, code, "point") in lines_meta}
        for r in pick:
            out.append(f"### {r[2]}")
            out.append("")
            for lev in idx:
                x = idx[lev][r[2]]
                mark = "*" if x[5] else ""
                out.append(f"- `{lev}`{mark}: {x[6]}")
            out.append("")
    write_text(path, "\n".join(out) + "\n")
