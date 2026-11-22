"""Stage 23 (SPEC 1.2, D13a): placing the named Septuagint word, strict links first, in two passes.

1. Strict pass. The bridge's links with a strict `how` (sure, order, neighbours) are placed. Then, over the pieces
   MACULA names a Greek word for that still have no strict link, in text order: `form_near` (no number guard), then
   `verse_form`; each takes only a Septuagint word no strict link holds. The pieces' own Septuagint verses (and with
   them the neighbouring verses) are those of the strict bridge links: the strict pass reads nothing GLAUx's lemma made.
2. Model pass, only over pieces with no strict link. The bridge's `number` links of these pieces are rows with basis
   `model`. Then, over the pieces still without any link: `lemma`, `verse_lemma`, `verse_number`, each taking only a
   Septuagint word no link (strict or model) holds. Own and neighbouring verses here are those of all bridge links, as
   stage 08 (examples_links.py) states them.

A bridge `number` link of a piece that has a strict link is not a row: where it names a Septuagint word a strict link
of that piece holds, that strict row gets `agree_model` 1; else it is displaced (listed).

The prelude (the Septuagint words, the pieces, the bridge) is stage 08's, read through examples_links' own helpers.
"""
import collections as C

import examples_links as EL

STRICT_HOW = ("sure", "order", "neighbours")


def _own_neigh(hverse, links, vid_of, verse_words, vbook, st, tag):
    own = {hv: sorted({vid_of[s] for p in ps for s, _ in links.get(p[2], ())}) for hv, ps in hverse.items()}
    hbook_verses = C.defaultdict(list)
    for hv in hverse:
        hbook_verses[hv[0]].append(hv)
    neigh = {}
    for b, hvs in hbook_verses.items():
        hvs.sort(key=lambda k: (k[1], k[2]))
        for i, hv in enumerate(hvs):
            if own[hv]:
                ns = set()
                for g in own[hv]:
                    for d in (-1, 1):
                        if 0 <= g + d < len(verse_words) and vbook[g + d] == vbook[g]:
                            ns.add(g + d)
                neigh[hv] = sorted(ns - set(own[hv]))
                continue
            prev = next((own[h] for h in reversed(hvs[:i]) if own[h]), None)
            nxt = next((own[h] for h in hvs[i + 1:] if own[h]), None)
            if prev and nxt and vbook[prev[-1]] == vbook[nxt[0]] and 0 <= nxt[0] - prev[-1] <= 2:
                neigh[hv] = list(range(prev[-1], nxt[0] + 1))
            else:
                neigh[hv] = []
                st[f"{tag}: unlinked Hebrew verses with no neighbouring verses"] += 1
    st[f"{tag}: Hebrew verses with no bridge link"] = sum(1 for v in own.values() if not v)
    return own, neigh


def lxx_place12(outdir, ex, st):
    langs = ("hbo", "arc")
    tab = {lang: EL.read_lang(outdir, lang) for lang in langs}
    book_order = list(dict.fromkeys(w["book"] for lang in langs for w in sorted(tab[lang][0], key=lambda w: w["t"])))
    rows = EL.septuagint(book_order)
    BL = EL.BL
    to_nt = BL.nt_numbers()
    key2s, words = {}, []
    plain, lemma, nums, vid_of, vbook = [None], [None], [None], [None], []
    verse_words, vindex = [], {}
    for s, (b, c, v, idx, surface, lem, pos, strong, gid) in enumerate(rows, start=1):
        key2s[f"lxx {b} {c}:{v} {idx}"] = s
        words.append((s, str(gid), b, c, v, idx,
                      EL.scripted(surface, "GREEK", "lxx text emptied: a letter of another script", ex),
                      EL.scripted(lem or None, "GREEK", "lxx lemma emptied: a letter of another script", ex),
                      EL.X.c0(pos) if pos else None))
        plain.append(BL.plain(surface))
        lemma.append(lem)
        nums.append([to_nt.get(x, x) for x in BL.numbers(strong)])
        k = (b, c, v)
        if k not in vindex:
            vindex[k] = len(verse_words)
            verse_words.append([])
            vbook.append(b)
        verse_words[vindex[k]].append(s)
        vid_of.append(vindex[k])
    if len({w[1] for w in words}) != len(words):
        raise SystemExit("GLAUx ids are not unique")
    st["lxx words"] = len(words)
    lem_of_form = C.defaultdict(set)
    for s in range(1, len(plain)):
        lem_of_form[plain[s]].add(lemma[s])
    named = EL.lowfat_greek(outdir)
    pieces = []
    for lang in langs:
        W, P = tab[lang]
        wv = {w["t"]: (w["book"], w["chapter"], w["verse"]) for w in W}
        for p in P:
            pieces.append((p["t"], p["n"], p["pid"], p["class"], p["lexeme"], lang, wv[p["t"]]))
    pieces.sort()
    by_pid = {p[2]: p for p in pieces}
    if len(by_pid) != len(pieces):
        raise SystemExit("piece ids are not unique over hbo and arc")
    if EL.sha256(EL.BRIDGE) != EL.BRIDGE_SHA:
        raise SystemExit(f"{EL.BRIDGE}: sha256 is not the pinned one")
    bridge = EL.pq.read_table(EL.BRIDGE).to_pylist()
    hverse = C.OrderedDict()
    for p in pieces:
        hverse.setdefault(p[6], []).append(p)

    def want(p):
        g = named.get(p[2], (None, None))
        return g if g[0] and g[0] not in EL.FILLERS else None

    # ---- pass 1: strict -------------------------------------------------------------------------------------
    strict = C.defaultdict(list)            # pid -> [(s, how)]
    held = set()                            # Septuagint words a strict link holds
    numrows = []                            # (pid, s) of the bridge's number links
    allb = C.defaultdict(list)
    for r in bridge:
        pid = "o" + r["hebrew_mid"]
        s = key2s.get(r["lxx_key"])
        if pid not in by_pid or s is None:
            raise SystemExit(f"bridge row does not resolve: {r}")
        allb[pid].append((s, r["how"]))
        if r["how"] in STRICT_HOW:
            strict[pid].append((s, r["how"]))
            held.add(s)
        elif r["how"] == "number":
            numrows.append((pid, s))
        else:
            raise SystemExit(f"bridge how {r['how']!r} not in SPEC D13a")
    st["bridge rows"] = len(bridge)
    st.update({f"bridge how {k}": v for k, v in sorted(C.Counter(r["how"] for r in bridge).items())})
    own, neigh = _own_neigh(hverse, strict, vid_of, verse_words, vbook, st, "strict pass")
    todo = [p for p in pieces if p[2] not in strict and want(p)]
    st["strict pass: named, no strict bridge link"] = len(todo)
    guard_refused, guard_alone = [], 0
    for rule in ("form_near", "verse_form"):
        left = []
        for p in todo:
            form, gs = want(p)
            f = BL.plain(form)
            hv = p[6]
            got = None
            if rule == "form_near":
                if len(f) >= 5:
                    gw = [s for g in own[hv] for s in verse_words[g]]
                    cands = [s for s in gw if s not in held and EL.lev1(plain[s], f)]
                    ns = {to_nt.get(x, x) for x in BL.numbers(gs)}
                    if len(cands) == 1:
                        got = cands[0]
                        if ns and nums[got] and not ns.intersection(nums[got]):
                            guard_refused.append(f"{p[2]} {got}")
                    elif len(cands) > 1 and len([s for s in cands if not ns or not nums[s]
                                                 or ns.intersection(nums[s])]) == 1:
                        guard_alone += 1        # the 1.1 guard would have chosen one word here; no strict link now
            else:
                nw = [s for g in neigh[hv] for s in verse_words[g] if s not in held]
                cands = [s for s in nw if plain[s] == f]
                if len(cands) == 1:
                    got = cands[0]
            if got is None:
                left.append(p)
            else:
                strict[p[2]].append((got, rule))
                held.add(got)
                st[f"strict pass: placed by {rule}"] += 1
        todo = left
    st["strict pass: form_near links the 1.1 number guard would have refused"] = len(guard_refused)
    st["strict pass: pieces the 1.1 number guard would have placed by form_near (several free words of the form; "
       "no strict link now)"] = guard_alone
    ex["lxx form_near links the 1.1 number guard would have refused (pid s)"] = guard_refused

    # ---- pass 2: model ----------------------------------------------------------------------------------------
    model = C.defaultdict(list)
    agree = C.defaultdict(set)              # pid -> {s} of strict links a number link confirms
    displaced, shared_word = [], 0
    for pid, s in numrows:
        if pid in strict:
            if s in {x for x, _ in strict[pid]}:
                agree[pid].add(s)
            else:
                displaced.append(f"{pid} {s}")
            continue
        model[pid].append((s, "number"))
        if s in held:
            shared_word += 1
    st["model pass: bridge number links that are rows (piece with no strict link)"] = sum(len(v) for v in model.values())
    st["model pass: bridge number links that agree with a strict link of the piece"] = sum(len(v) for v in agree.values())
    st["model pass: bridge number links displaced (the piece's strict link names another word)"] = len(displaced)
    st["model pass: bridge number rows on a Septuagint word a strict link of another piece holds"] = shared_word
    ex["lxx bridge number links displaced by a strict link (pid s)"] = displaced
    taken = set(held) | {s for v in model.values() for s, _ in v}
    own2, neigh2 = _own_neigh(hverse, allb, vid_of, verse_words, vbook, st, "model pass")
    todo = [p for p in pieces if p[2] not in strict and p[2] not in model and want(p)]
    st["model pass: named, still without a link"] = len(todo)
    for rule in ("lemma", "verse_lemma", "verse_number"):
        left = []
        for p in todo:
            form, gs = want(p)
            f = BL.plain(form)
            ls = lem_of_form.get(f, set())
            one_lemma = next(iter(ls)) if len(ls) == 1 else None
            hv = p[6]
            got = None
            if rule == "lemma":
                gw = [s for g in own2[hv] for s in verse_words[g]]
                if one_lemma is not None:
                    cands = [i for i, s in enumerate(gw) if s not in taken and lemma[s] == one_lemma]
                    if cands:
                        vp = hverse[hv]
                        hpos = vp.index(p)
                        pos_of = {s: i for i, s in enumerate(gw)}
                        anchors = sorted((j, pos_of[s]) for j, q in enumerate(vp) for s, how in allb.get(q[2], ())
                                         if how == "sure" and s in pos_of)
                        got = gw[BL.nearest(hpos, cands, anchors, len(gw), len(vp))]
            else:
                nw = [s for g in neigh2[hv] for s in verse_words[g] if s not in taken]
                if rule == "verse_lemma":
                    cands = [s for s in nw if one_lemma is not None and lemma[s] == one_lemma]
                else:
                    ns = {to_nt.get(x, x) for x in BL.numbers(gs)}
                    cands = [s for s in nw if ns.intersection(nums[s])]
                if len(cands) == 1:
                    got = cands[0]
            if got is None:
                left.append(p)
            else:
                model[p[2]].append((got, rule))
                taken.add(got)
                st[f"model pass: placed by {rule}"] += 1
        todo = left
    st["named, still not placed"] = len(todo)
    return {"words": words, "pieces": pieces, "strict": strict, "model": model, "agree": agree, "want": want,
            "displaced": displaced, "numrows": len(numrows)}


def build_lxx12(outdir, counts, ex, cnt):
    """As examples_links11.build_lxx, over the two passes: -> (per-language rows, objects, words)."""
    st = C.Counter()
    R = lxx_place12(outdir, ex, st)
    words, pieces, strict, model, agree, want = (R["words"], R["pieces"], R["strict"], R["model"], R["agree"],
                                                 R["want"])
    counts["lxx placement (SPEC 1.2 D13a, two passes)"] = dict(sorted(st.items()))
    cnt["lxx bridge rows: strict rows + model number rows + agreeing + displaced"] = (
        sum(1 for v in strict.values() for _, h in v if h in STRICT_HOW)
        + sum(1 for v in model.values() for _, h in v if h == "number")
        + sum(len(v) for v in agree.values()) + len(R["displaced"]))
    cls_all, cls_linked = C.Counter(), C.Counter()
    for p in pieces:
        cls_all[p[3]] += 1
        cls_linked[p[3]] += p[2] in strict
    share = {c: cls_linked[c] / cls_all[c] for c in cls_all}
    naw = {c for c, v in share.items() if v < EL.NAW_SHARE}
    counts["lxx class shares over strict links (hbo+arc)"] = {c: [cls_linked[c], cls_all[c], round(share[c], 4)]
                                                              for c in sorted(cls_all)}
    counts["lxx never_a_word classes"] = sorted(naw)
    import examples_links11 as L11
    L11.write_rows(EL.os.path.join(outdir, "other", "lxx", "words.parquet"), words, L11.OTHER_SCHEMA)
    out = {}
    for lang in ("hbo", "arc"):
        lrows, arows = [], []
        for p in pieces:
            if p[5] != lang:
                continue
            t, n, pid = p[0], p[1], p[2]
            for s, how in sorted(strict.get(pid, ())):
                lrows.append((t, n, "lxx", s, how, 1, "linked", 1 if s in agree.get(pid, ()) else 0))
            for s, how in sorted(model.get(pid, ())):
                lrows.append((t, n, "lxx", s, how, 0, "model", None))
            g = want(p)
            if pid in strict:
                state, reason = "linked", ""
            elif p[3] in naw:
                state, reason = "never_a_word", p[3]
            elif g:
                state, reason = "unplaced", g[0]
            else:
                state, reason = "no_counterpart", ""
            arows.append((t, n, "lxx", state, reason, "linked" if pid in model else None))
        out[lang] = (lrows, arows)
    lem = {w[0]: w[7] for w in words}
    frm = {w[0]: EL.X.norm_grc(w[6]) if w[6] else None for w in words}

    def objects(s):
        o = []
        if frm[s]:
            o.append((f"lxx:form:{frm[s]}", "linked", "links.parquet", "hebrew-greek-cf"))
        if lem[s]:
            o.append((f"lxx:{lem[s]}", "model", "links.parquet:glaux_lemma", "glaux"))
        return o
    return out, objects, {w[0]: w for w in words}
