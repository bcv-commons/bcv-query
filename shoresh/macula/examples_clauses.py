"""Stage 04 (clauses) of the source-examples build, SPEC 1.0 sections 3 (`clause` key), 4.1 (`words.clause`), 4.3,
4.4, D2p (constituent heads), D8.

Reads the stage-03 tables (words.parquet, pieces.parquet of hbo, arc, grc), the build's cache/morphid.parquet (the
Hebrew frame targets, as D7 resolves references) and the MACULA lowfat files (clauses, their children, roles, rules,
frames). Writes per language clauses.parquet and constituents.parquet, and words.parquet anew with `clause` filled.
Counts and exception lists go to cache/stage04-counts.json (through build_examples.py).

A clause is a lowfat `wg` with class="cl"; in Greek also a `w` with a `rule` (a one-word clause). The lowfat files are
read here with their own reader (`clause_elements`), because the stage-03 element cache keeps neither the Greek
`Rule` attribute nor `frame`. The reader is not cached: a full parse takes well under a minute.
"""
import collections as C
import multiprocessing as mp
import os
import re
import xml.etree.ElementTree as ET

import pyarrow as pa
import pyarrow.parquet as pq

import examples_common as X
import examples_src as S
import examples_words as EW

XID = S.XID
# SPEC 4.4: the constituent role codes (the source's role values, coded by C0), used by `pattern`
ROLE_CODES = ("adv", "aux", "io", "o", "o2", "p", "pp", "s", "v", "vc")

CLAUSE_COLS = [("clause", pa.string()), ("book", pa.string()), ("chapter", pa.int64()), ("verse", pa.int64()),
               ("first", pa.int64()), ("last", pa.int64()), ("gaps", pa.bool_()), ("words", pa.int64()),
               ("parent", pa.string()), ("depth", pa.int64()), ("via", pa.string()), ("rule", pa.string()),
               ("pattern", pa.string()), ("role", pa.string()), ("role_wrapped", pa.string()),
               ("pred", pa.int64()), ("pred_kind", pa.string()),
               # filled by stages 05 and 06: present and null until then
               ("marks", pa.string()), ("shared", pa.string()), ("quote", pa.string()), ("speaker", pa.string()),
               ("addressee", pa.string()), ("line", pa.string())]
CLAUSE_LATER = ("marks", "shared", "quote", "speaker", "addressee", "line")
CONST_COLS = [("clause", pa.string()), ("ord", pa.int64()), ("role", pa.string()), ("head", pa.int64()),
              ("first", pa.int64()), ("last", pa.int64()), ("class", pa.string()), ("frame_role", pa.string()),
              ("sem_role", pa.string()), ("prep", pa.string())]
CONST_LATER = ("sem_role",)
# SPEC 1.1, sections 4.3 and 4.4 (build c1): the same tables with the columns 1.1 adds; later stages fill them
CLAUSE_COLS_11 = CLAUSE_COLS[:-1] + [("speech_basis", pa.string()), ("line", pa.string()),
                                     ("quote_model", pa.string()), ("speaker_model", pa.string()),
                                     ("addressee_model", pa.string()), ("subject_model", pa.string())]
CONST_COLS_11 = CONST_COLS[:-1] + [("sem_role_basis", pa.string()), ("prep", pa.string())]


# ---- reading the lowfat files -----------------------------------------------------------------------------------

def _clause_file(path):
    """One lowfat file -> list of sentences; a sentence is a list of elements in preorder:
    (tag, role, class, rule, type, pids, parent index or -1, frame). `rule` is `rule`, or the Greek `Rule` where
    `rule` is absent; `frame` only on `w`. pids: every `w` under the element (letterless articles included)."""
    import sys
    sys.setrecursionlimit(20000)
    root = ET.parse(path).getroot()
    out = []
    both = 0
    for s in root.iter("sentence"):
        els = []

        def walk(el, parent):
            nonlocal both
            if el.tag not in ("wg", "w", "c"):
                pids = []
                for k in el:
                    pids.extend(walk(k, parent))
                return pids
            i = len(els)
            els.append(None)
            if el.tag == "w":
                pids = [el.get(XID)]
            else:
                pids = []
                for k in el:
                    pids.extend(walk(k, i))
            rule = el.get("rule")
            if rule is None:
                rule = el.get("Rule")
            elif el.get("Rule") is not None:
                both += 1
            els[i] = (el.tag, el.get("role"), el.get("class"), rule, el.get("type"), tuple(pids), parent,
                      el.get("frame") if el.tag == "w" else None)
            return pids

        for k in s:
            if k.tag in ("wg", "w", "c"):
                walk(k, -1)
        out.append(els)
    return os.path.basename(path), out, both


def clause_elements(files):
    with mp.get_context("fork").Pool(S.PROCS) as pool:
        res = pool.map(_clause_file, files, chunksize=2)
    return res


# ---- helpers ----------------------------------------------------------------------------------------------------

def usable(role):
    # as stage 03: empty roles and converter error strings (err__..., one err_...) are not roles
    return role is not None and role != "" and not role.startswith("err_")


def is_clause(el, greek):
    tag, role, cls, rule = el[0], el[1], el[2], el[3]
    if tag == "wg":
        return cls == "cl"
    return greek and tag == "w" and rule is not None


def group_class(el, greek, v11=False):
    """`via` / constituent `class`: the source's class code; `group` for a Greek type="group" without class; `run`
    for a Hebrew group without class; (1.1, B6) `compound` for a `c` element; None where none of these applies
    (counted by the caller)."""
    tag, role, cls, rule, typ = el[:5]
    if v11 and tag == "c" and not cls:
        return "compound"
    if cls:
        return X.c0(cls)
    if greek and typ == "group":
        return "group"
    if not greek and tag == "wg":
        return "run"
    return None


def _class_src(keep, el):
    """Record the source class value behind a class code (for categories.toml); two values for one code raise."""
    if keep is None or not el[2]:
        return
    m = keep.setdefault("class_src", {})
    code = X.c0(el[2])
    if m.setdefault(code, el[2]) != el[2]:
        raise ValueError(f"two class values give one code: {m[code]!r} {el[2]!r}")


def pattern_of(rule):
    if not rule:
        return ""
    parts = rule.split("-")
    if all(p and p == p.upper() and p.lower() in ROLE_CODES for p in parts):
        return rule
    return ""


def parse_frame(frame):
    """MACULA frame -> list of (label, [target ids]). Hebrew `A0:id; A1:id;id;`, Greek `A0:id A1:id;id`."""
    out = []
    for tok in (frame or "").split():
        m = re.match(r"([A-Za-z0-9]+):(.*)$", tok)
        if not m:
            raise ValueError(f"frame entry not understood: {tok!r} in {frame!r}")
        out.append((m.group(1), [x for x in m.group(2).split(";") if x]))
    return out


def heads_group(d, via_el, pred, tn_of, wordhead):
    """D8 (1.1): the clause heads its via group when its pred word's edge (else its first word's) leaves the group
    (a root word, head 0, leaves it)."""
    w = pred if pred else tn_of[d["pids"][0]][0]
    group_words = {tn_of[p][0] for p in via_el[5] if p in tn_of}
    h = wordhead[w]
    return h == 0 or h not in group_words


def d8(d, role, via_el, via, pred, clauses, place, tn_of, wordhead, greek, lang, v11, cnt, ex):
    """D8: role_wrapped. 1.0: the via group's role, else (Greek one-word clause) the slot of the parent's rule.
    1.1 (B5): the via group's role only where the clause heads the group; else empty, counted by via."""
    role_wrapped = ""
    if not role:
        if via_el is not None and usable(via_el[1]):
            if not v11 or heads_group(d, via_el, pred, tn_of, wordhead):
                role_wrapped = X.c0(via_el[1])
                cnt[f"{lang} D8: role from the via group"] += 1
            else:
                cnt[f"{lang} D8: the via group has a role, the clause does not head it (empty), via {via}"] += 1
                ex[f"{lang} D8: the via group has a role, the clause does not head it"].append(
                    f"{d['key']} via {via} {X.c0(via_el[1])}")
                if d["one_word"]:
                    cnt["grc D8: one-word clauses that do not head their via group (empty, no slot)"] += 1
        elif d["one_word"] and d["parent_ix"] is not None:
            par = clauses[d["parent_ix"]]
            slot_child = d["path"][-1]
            pk = par["kids"]
            pslots = par["rule"].split("-") if pattern_of(par["rule"]) else None
            if pslots is not None and len(pslots) == len(pk):
                role_wrapped = X.c0(pslots[pk.index(slot_child)])
                cnt["grc D8: one-word clause, role from the slot of the parent's rule"] += 1
                if v11 and via_el is not None and not heads_group(d, via_el, pred, tn_of, wordhead):
                    cnt["grc D8: one-word clauses given their slot's role though they do not head the via "
                        "group (via without a role)"] += 1
                    ex["grc D8: one-word clauses given a slot role without heading the via group"].append(
                        f"{d['key']} via {via} slot {role_wrapped}")
            else:
                cnt["grc D8: one-word clause, parent rule not a slot rule of as many slots as children "
                    "(no role)"] += 1
                ex["grc D8: one-word clause without a slot"].append(f"{d['key']} in {par['rule']}")
    if role:
        cnt[f"{lang} clauses with an own role"] += 1
    elif not role_wrapped:
        cnt[f"{lang} clauses with neither role nor role_wrapped"] += 1
    return role_wrapped


# ---- build one text (hbo+arc together, or grc) ------------------------------------------------------------------

def compute(tables, files, greek, bym, cnt, ex, keep=None, v11=False):
    """tables: lang -> (W, P). Returns per lang (clause rows, constituent rows) and words.clause per lang.
    `keep` (stage 05): a dict that receives `clauses` = [(key, rule, lang, depth, piece ids in text order)] in
    document order, and `const` = {(clause key, ord): (head piece id, piece ids in text order)}."""
    tag = "grc" if greek else "tan"
    # piece rows: pid -> (lang, row, t, n); text-order rank over the whole text
    place = {}
    for lang, (W, P) in tables.items():
        for i, pid in enumerate(P["pid"]):
            place[pid] = (lang, i, P["t"][i], P["n"][i])
    order = sorted(place, key=lambda p: (place[p][2], place[p][3]))
    rank = {p: r for r, p in enumerate(order)}
    tn_of = {p: (v[2], v[3]) for p, v in place.items()}
    head_tn = {}
    for lang, (W, P) in tables.items():
        for i, pid in enumerate(P["pid"]):
            head_tn[pid] = (P["head_t"][i], P["head_n"][i])
    word_of_t = {}
    for lang, (W, P) in tables.items():
        for j, t in enumerate(W["t"]):
            word_of_t[t] = (lang, j)
    wordhead = {}
    for lang, (W, P) in tables.items():
        if W.get("head") is not None:
            wordhead.update(zip(W["t"], W["head"]))
    stem_pid = {}
    for lang, (W, P) in tables.items():
        for i, pid in enumerate(P["pid"]):
            if P["kind"][i] == "stem":
                stem_pid[P["t"][i]] = pid
    pclass = {pid: tables[v[0]][1]["class"][v[1]] for pid, v in place.items()}
    plex = {pid: tables[v[0]][1]["lexeme"][v[1]] for pid, v in place.items()}

    parsed = clause_elements(files)
    cnt[f"{tag} lowfat elements with both rule and Rule"] = sum(b for _, _, b in parsed)
    sents = [s for _, ss, _ in parsed for s in ss]

    clauses = []      # dicts, in document order over the whole text
    frames = {}       # pid -> frame string
    for si, els in enumerate(sents):
        kids = C.defaultdict(list)
        for j, el in enumerate(els):
            if el[6] >= 0:
                kids[el[6]].append(j)
            if el[0] == "w" and el[7]:
                frames[el[5][0]] = el[7]
        isc = [is_clause(el, greek) for el in els]
        for j, el in enumerate(els):
            if el[0] == "w" and el[3] is not None and not greek:
                ex["Hebrew w elements with a rule (not taken as clauses)"].append(el[5][0])
        # role-bearing elements that are not direct children of a clause
        for j, el in enumerate(els):
            if usable(el[1]) and not (el[6] >= 0 and isc[el[6]]):
                cnt[f"{tag} role-bearing elements not direct children of a clause"] += 1
                cnt[f"{tag} role-bearing elements not direct children of a clause, role {el[1]}"] += 1
                ex[f"{tag} role-bearing elements not direct children of a clause"].append(
                    f"{el[0]} {el[1]} {el[2] or el[4] or '-'} {el[5][0]}")
        cl_index = {}
        for j, el in enumerate(els):
            if not isc[j]:
                continue
            # nearest clause above, the path to it, the number of clauses above
            path, x, parent, depth = [j], el[6], None, 0
            while x >= 0:
                if isc[x]:
                    if parent is None:
                        parent = x
                    depth += 1
                if parent is None:
                    path.append(x)
                x = els[x][6]
            rows = [p for p in el[5] if p in place]
            if not rows:
                raise ValueError(f"a clause without piece rows: {el[5][:3]}")
            rows.sort(key=rank.get)
            d = dict(sent=si, el=j, tag=el[0], rule=el[3] or "", role_src=el[1], cls=el[2], pids=rows,
                     parent_el=parent, depth=depth, path=path, kids=kids[j], one_word=el[0] == "w")
            cl_index[j] = len(clauses)
            clauses.append(d)
        for d in clauses[len(clauses) - len(cl_index):]:
            d["parent_ix"] = cl_index[d["parent_el"]] if d["parent_el"] is not None else None
            d["els"] = els

    # ---- keys (SPEC 3): cl:<pid of first piece>:<pieces>, :2, :3 further in --------------------------------------
    same = C.defaultdict(list)
    for ix, d in enumerate(clauses):
        same[(d["pids"][0], len(d["pids"]))].append(ix)
    for (pid, n), ixs in same.items():
        ixs.sort(key=lambda ix: clauses[ix]["depth"])
        if len({clauses[ix]["depth"] for ix in ixs}) != len(ixs):
            raise ValueError(f"two clauses with the same pieces at the same depth: {pid} {n}")
        for k, ix in enumerate(ixs, 1):
            clauses[ix]["key"] = f"cl:{pid}:{n}" + (f":{k}" if k > 1 else "")
        if len(ixs) > 1:
            cnt[f"{tag} clauses sharing their pieces with a clause around them (key :2, :3)"] += len(ixs) - 1
            ex[f"{tag} clauses sharing their pieces with a clause around them"].append(
                " ".join(clauses[ix]["key"] + "/" + clauses[ix]["rule"] for ix in ixs))
            for ix in ixs[1:]:
                if clauses[ix]["one_word"]:
                    ex["grc one-word clauses whose key is not cl:<pid>:1 (a clause around them has the same "
                       "piece)"].append(clauses[ix]["key"])
    keys = [d["key"] for d in clauses]
    if len(set(keys)) != len(keys):
        raise ValueError("clause keys repeat")

    # ---- language of each clause (majority of its pieces) ------------------------------------------------------
    for d in clauses:
        lc = C.Counter(place[p][0] for p in d["pids"])
        if greek:
            d["lang"] = "grc"
        else:
            d["lang"] = "arc" if lc["arc"] * 2 > len(d["pids"]) else "hbo"
            if len(lc) > 1:
                cnt["tan clauses whose pieces are in both languages"] += 1
                first = d["pids"][0]
                lg, i, t, n = place[first]
                W = tables[lg][0]
                j = word_of_t[t][1]
                ex["tan clauses whose pieces are in both languages"].append(
                    f"{d['key']} {W['book'][j]} {W['chapter'][j]}:{W['verse'][j]} rule {d['rule']} "
                    f"hbo {lc['hbo']} arc {lc['arc']} -> {d['lang']}")

    # ---- words.clause: the innermost clause that holds the word's stem piece ------------------------------------
    innermost = {}
    for ix, d in enumerate(clauses):
        for p in d["pids"]:
            cur = innermost.get(p)
            if cur is None or clauses[cur]["depth"] < d["depth"]:
                innermost[p] = ix
    wclause = {lang: [""] * len(W["t"]) for lang, (W, P) in tables.items()}
    nwords = C.Counter()
    for t, pid in stem_pid.items():
        ix = innermost.get(pid)
        lang, j = word_of_t[t]
        if ix is None:
            cl = tables[lang][1]["class"][place[pid][1]]
            cnt[f"{lang} words in no clause"] += 1
            cnt[f"{lang} words in no clause, class {cl}"] += 1
            continue
        wclause[lang][j] = clauses[ix]["key"]
        nwords[ix] += 1
    for p in place:
        if p not in innermost:
            cnt[f"{place[p][0]} pieces in no clause"] += 1

    # ---- per clause: place, span, gaps, parent, via, roles, pred; constituents --------------------------------
    out = {lang: ([], []) for lang in tables}
    if keep is not None:
        keep["clauses"] = [(d["key"], d["rule"], d["lang"], d["depth"], tuple(d["pids"])) for d in clauses]
        keep["const"] = {}
    for ix, d in enumerate(clauses):
        els = d["els"]
        lang = d["lang"]
        first_pid, last_pid = d["pids"][0], d["pids"][-1]
        lg, i, t0, n0 = place[first_pid]
        W = tables[lg][0]
        j = word_of_t[t0][1]
        ranks = [rank[p] for p in d["pids"]]
        gaps = ranks[-1] - ranks[0] + 1 != len(ranks)
        if gaps:
            cnt[f"{lang} clauses with gaps"] += 1
            ex[f"{lang} clauses with gaps"].append(d["key"])
        parent = clauses[d["parent_ix"]]["key"] if d["parent_ix"] is not None else ""
        # via: the element just below the parent on the path from the clause up (path[-1]); empty when that is
        # the clause itself or there is no parent
        via = ""
        via_el = None
        if d["parent_ix"] is not None and len(d["path"]) > 1:
            via_el = els[d["path"][-1]]
            via = group_class(via_el, greek, v11)
            _class_src(keep, via_el)
            if via is None:
                via = ""
                cnt[f"{lang} clauses whose via group has no class, no type group"] += 1
                ex[f"{lang} clauses whose via group has no class (via left empty)"].append(
                    f"{d['key']} {via_el[0]} type={via_el[4]} rule={via_el[3]}")
        rule = d["rule"]
        pattern = pattern_of(rule)
        role = ""
        rsrc = d["role_src"]
        if d["one_word"]:
            # the role on a one-word clause is its role inside its own clause (SPEC sources, section 8); its
            # role in the clause around it is not written on it
            if rsrc is not None:
                cnt[f"grc one-word clauses: role inside their own clause (not taken as role), {rsrc}"] += 1
        elif usable(rsrc):
            role = X.c0(rsrc)
        elif rsrc is not None:
            cnt[f"{lang} clauses whose role is empty or an error string"] += 1
            ex[f"{lang} clauses whose role is empty or an error string"].append(f"{d['key']} {rsrc!r}")
        # constituents: direct children with a usable role
        crow = []
        kid_info = []
        for k in d["kids"]:
            el = els[k]
            if not usable(el[1]):
                if el[1] is not None:
                    cnt[f"{lang} direct children of clauses with an empty or error role (excluded)"] += 1
                    ex[f"{lang} direct children of clauses with an empty or error role"].append(
                        f"{d['key']} {el[0]} {el[1]!r}")
                continue
            rows = sorted((p for p in el[5] if p in place), key=rank.get)
            if not rows:
                raise ValueError(f"a constituent without piece rows: {el[5]}")
            inside = {tn_of[p] for p in rows}
            outs = [p for p in rows if head_tn[p] == (0, 0) or head_tn[p] not in inside]
            if len(outs) != 1:
                cnt[f"{lang} constituents whose head pieces (head outside the part) are not exactly one"] += 1
                ex[f"{lang} constituents whose head pieces are not exactly one"].append(
                    f"{d['key']} {el[1]} {len(outs)}")
            if not outs:
                raise ValueError(f"a constituent whose every piece's head lies inside it: {d['key']}")
            hp = outs[0]
            kid_info.append((rank[rows[0]], k, el, rows, hp))
        for ordn, (r0, k, el, rows, hp) in enumerate(kid_info, 1):
            rc = X.c0(el[1])
            gcl = group_class(el, greek, v11)
            _class_src(keep, el)
            if gcl is None:
                gcl = ""
                cnt[f"{lang} constituents without a class code"] += 1
                ex[f"{lang} constituents without a class code"].append(f"{d['key']} {el[0]} type={el[4]}")
            prep = ""
            if rc == "pp" or gcl == "pp":
                pp = [p for p in rows if pclass[p] == "prep"]
                if pp:
                    prep = plex[pp[0]]
                else:
                    cnt[f"{lang} pp constituents without a prep piece"] += 1
                    ex[f"{lang} pp constituents without a prep piece"].append(f"{d['key']} {ordn}")
            crow.append(dict(clause=d["key"], ord=ordn, role=rc, head=tn_of[hp][0], first=tn_of[rows[0]][0],
                             last=tn_of[rows[-1]][0], **{"class": gcl}, frame_role="", sem_role=None,
                             sem_role_basis=None, prep=prep,
                             _rows=set(rows), _one_word=el[0] == "w" and greek and el[3] is not None))
            if keep is not None:
                keep["const"][(d["key"], ordn)] = (hp, tuple(rows))
        # pred: the first v child (text order) that is not a one-word clause; else the first vc; else the first p
        pred, pred_kind = 0, "none"
        by_text = sorted(crow, key=lambda c: (rank[min(c["_rows"], key=rank.get)]))
        for kind in ("v", "vc", "p"):
            cand = [c for c in by_text if c["role"] == kind and not (kind == "v" and c["_one_word"])]
            if cand:
                pred, pred_kind = cand[0]["head"], kind
                break
        if v11 and d["one_word"] and rule in ("v2cl", "vc2cl", "p2cl"):
            # B3: a one-word clause of these rules is its own predicate
            pred, pred_kind = tn_of[d["pids"][0]][0], rule[:-3]
            cnt[f"grc B3: one-word clauses that are their own predicate, {pred_kind}"] += 1
        if pred_kind == "none":
            cnt[f"{lang} clauses without a predicate"] += 1
            cnt[f"{lang} clauses without a predicate, rule {rule}"] += 1
        else:
            cnt[f"{lang} clauses pred_kind {pred_kind}"] += 1
        role_wrapped = d8(d, role, via_el, via, pred, clauses, place, tn_of, wordhead, greek, lang, v11, cnt, ex)
        nv = sum(1 for c in crow if c["role"] == "v")
        if nv > 1:
            cnt[f"{lang} clauses with several v constituents"] += 1
        # frame_role: the frame on the stem piece of the predicate word
        if pred:
            sp = stem_pid[pred]
            fr = frames.get(sp)
            if fr:
                cnt[f"{lang} clauses whose predicate word carries a frame"] += 1
                for label, targets in parse_frame(fr):
                    tp = set()
                    for tg in targets:
                        if greek:
                            if tg == "n00000000000":
                                cnt["grc frame targets n00000000000 (no word)"] += 1
                                continue
                            hit = [tg]
                        else:
                            hit = bym.get(tg)
                            if hit is None:
                                cnt[f"{lang} frame targets that do not resolve through morphId"] += 1
                                continue
                        hit = [h for h in hit if h in place]
                        if not hit:
                            cnt[f"{lang} frame targets naming no piece row"] += 1
                            continue
                        tp.update(hit)
                    placed = False
                    for c in crow:
                        if tp & c["_rows"]:
                            c.setdefault("_labels", set()).add(label)
                            placed = True
                    if not placed and tp:
                        cnt[f"{lang} frame entries whose targets lie in no constituent of the clause"] += 1
        for c in crow:
            c["frame_role"] = " ".join(sorted(c.pop("_labels", ())))
            c.pop("_rows")
            c.pop("_one_word")
            cnt[f"{lang} constituents, role {c['role']}"] += 1
        if keep is not None and d["one_word"]:
            keep.setdefault("oneword", {})[d["pids"][0]] = (d["key"], role_wrapped)
        if d["one_word"]:
            cnt["grc one-word clauses"] += 1
            cnt[f"grc one-word clauses, rule {rule}"] += 1
        cnt[f"{lang} clauses"] += 1
        out[lang][0].append(dict(clause=d["key"], book=W["book"][j], chapter=W["chapter"][j], verse=W["verse"][j],
                                 first=tn_of[first_pid][0], last=tn_of[last_pid][0], gaps=gaps, words=nwords[ix],
                                 parent=parent, depth=d["depth"], via=via, rule=rule, pattern=pattern, role=role,
                                 role_wrapped=role_wrapped, pred=pred, pred_kind=pred_kind,
                                 marks=None, shared=None, quote=None, speaker=None, addressee=None, line=None,
                                 speech_basis=None, quote_model=None, speaker_model=None, addressee_model=None,
                                 subject_model=None))
        out[lang][1].extend(crow)
        if parent and clauses[d["parent_ix"]]["lang"] != lang:
            cnt[f"{lang} clauses whose parent is in the other Tanakh table"] += 1
            ex["tan clauses whose parent is in the other Tanakh table"].append(f"{d['key']} -> {parent}")
        if via:
            cnt[f"{lang} via {via}"] += 1
    return out, wclause


def build(outdir, langs, counts):
    ex = C.defaultdict(list)
    cnt = C.Counter()
    groups = []
    if {"hbo", "arc"} & set(langs):
        if not {"hbo", "arc"} <= set(langs):
            raise SystemExit("stage 04: hbo and arc are built together (clauses cross them in DAN 2:4)")
        groups.append((("hbo", "arc"), S.heb_lowfat_files(), False))
    if "grc" in langs:
        groups.append((("grc",), S.grc_lowfat_files(), True))
    bym = None
    for gl, files, greek in groups:
        tables = {}
        for lang in gl:
            d = os.path.join(outdir, lang)
            tables[lang] = (pq.read_table(os.path.join(d, "words.parquet")).to_pydict(),
                            pq.read_table(os.path.join(d, "pieces.parquet")).to_pydict())
            if any(v is None for v in tables[lang][1]["head_t"]):
                raise SystemExit(f"stage 04 needs stage 03's heads ({lang} pieces.head_t is null)")
        if not greek:
            m = pq.read_table(os.path.join(outdir, "cache", "morphid.parquet")).to_pydict()
            bym = C.defaultdict(list)
            for mid, pid in zip(m["morphid"], m["pid"]):
                bym[mid].append(pid)
        out, wclause = compute(tables, files, greek, bym, cnt, ex)
        for lang in gl:
            W, P = tables[lang]
            W["clause"] = wclause[lang]
            rows, crows = out[lang]
            d = os.path.join(outdir, lang)
            X.write_parquet(os.path.join(d, "words.parquet"), W, pa.schema(EW.WORD_COLS))
            X.write_parquet(os.path.join(d, "clauses.parquet"),
                            {k: [r[k] for r in rows] for k, _ in CLAUSE_COLS}, pa.schema(CLAUSE_COLS))
            X.write_parquet(os.path.join(d, "constituents.parquet"),
                            {k: [r[k] for r in crows] for k, _ in CONST_COLS}, pa.schema(CONST_COLS))
            cnt[f"{lang} constituents"] = len(crows)
            cnt[f"{lang} words with a clause"] = sum(1 for v in wclause[lang] if v)
    for k in sorted(cnt):
        counts[k] = cnt[k]
    return ex
