"""Stage 03 (heads) of the source-examples build, SPEC 1.0: D2p, D2w, D3, D4.

Reads the stage-02 tables (words.parquet, pieces.parquet of hbo, arc, grc), the MACULA node files (the `Head` of every
branching node) and the lowfat files (the roles, for D3). Writes per language words.parquet and pieces.parquet anew
with `head`/`head_t`, `head_n`, `head_basis`, `rel`, `rel_shared` filled, and relmap.tsv. Counts and exception lists go
to cache/stage03-counts.json (through build_examples.py).
"""
import collections as C
import os

import pyarrow.parquet as pq

import examples_common as X
import examples_src as S
import examples_words as EW
from examples_relmap import RELMAP

CONJ_CATS = {"conj", "cj", "cjp"}   # D2p(a): "one conjunction and one other part"
SHARE = 0.001                       # D4: a label covering this share of the language's words must be mapped


def read_stage02(outdir, lang):
    d = os.path.join(outdir, lang)
    return (pq.read_table(os.path.join(d, "words.parquet")).to_pydict(),
            pq.read_table(os.path.join(d, "pieces.parquet")).to_pydict())


# ---- D3: the lowfat element with exactly a piece set -------------------------------------------------------------

def role_index(sent_els, ex, counts):
    """frozenset of pids -> (role of the outermost element with exactly these pieces, or None; whether an element
    further in has a usable role; the outermost element's tag and class)."""
    out = {}
    for tag, role, cls, rule, head, typ, pids, parent in sent_els:
        key = frozenset(pids)
        if key not in out:
            out[key] = [role, False, tag, cls]
        elif usable(role):
            out[key][1] = True
    return out


def usable(role):
    # converter error strings: 4 Greek values begin err__, one (LUK 9:4) err_ ; SPEC 4.4 counts all 5
    return role is not None and role != "" and not role.startswith("err_")


# ---- D2p over one sentence -------------------------------------------------------------------------------------

def sentence_edges(tops, nodes, leafcat, hidden, counts, ex, sref, v11=False, tanakh=False):
    """D2p for one sentence. Returns {pid: (head pid or None for a root/none, basis, node index or None, place)}
    over every leaf of the sentence (letterless articles included), and the root pid.
    `v11` (SPEC 1.1): D2p(d) at a Hebrew or Aramaic sentence node (the top node, Cat S, no Rule)."""
    if len(tops) != 1:
        raise ValueError(f"{sref}: {len(tops)} top nodes")
    headpiece = [None] * len(nodes)
    edges = {}
    if v11 and tanakh:
        t0 = nodes[tops[0]]
        if t0[0] == "S" and t0[1] is None:
            counts["D2p(d) sentence nodes (top node, Cat S, no Rule)"] += 1
            if t0[4] != "n" or len(t0[3]) < 2:
                counts["D2p(d) sentence nodes with one child (nothing to choose)"] += 1
        else:
            counts["D2p(d) Tanakh top nodes that are not a sentence node"] += 1
            ex["Tanakh top nodes that are not a sentence node (Cat S, no Rule)"].append(f"{sref} {t0[0]} {t0[1]}")
    # iterative post-order
    order, stack = [], [tops[0]]
    while stack:
        i = stack.pop()
        order.append(i)
        if nodes[i][4] == "n":
            stack.extend(nodes[i][3])
    for i in reversed(order):
        cat, rule, head, kids, kind = nodes[i]
        if kind == "w":
            headpiece[i] = kids[0]
            continue
        if kind == "c":
            # D2p(b): the first m is the head, the others depend on it
            if head is not None:
                counts["compounds that carry a Head"] += 1
            counts["D2p(b) compound nodes"] += 1
            headpiece[i] = kids[0]
            for place, p in enumerate(kids[1:], 1):
                edges[p] = (kids[0], "compound", i, place)
            continue
        if len(kids) == 1:          # a unary node is the same node as its child
            headpiece[i] = headpiece[kids[0]]
            continue
        kh = [headpiece[k] for k in kids]
        if v11 and tanakh and i == tops[0] and cat == "S" and rule is None:
            # D2p(d): the head child is the first child of Cat CL, else the first child
            kc = [nodes[k][0] for k in kids]
            h = kc.index("CL") if "CL" in kc else 0
            basis = "sentence"
            counts["D2p(d) branching sentence nodes"] += 1
            counts["D2p(d) head child: " + ("the first CL child" if "CL" in kc else "the first child (no CL)")] += 1
            if head != "0":
                counts["D2p(d) sentence nodes whose Head is not 0"] += 1
        elif head is not None:
            h = int(head)
            basis = "index"
            counts["branching nodes with Head"] += 1
        else:
            kc = [nodes[k][0] for k in kids]
            conj = [j for j, c in enumerate(kc) if c in CONJ_CATS]
            if len(kids) == 2 and len(conj) == 1:
                h = 1 - conj[0]
                basis = "conj"
                counts["D2p(a) conjunction nodes"] += 1
                counts[f"D2p(a) by rule: {rule}"] += 1
            else:
                h = None
                counts["D2p(c) nodes"] += 1
                ex["D2p(c) nodes (no Head, no rule of D2p a/b)"].append(f"{sref} {rule} {' '.join(map(str, kc))}")
        if h is None:
            headpiece[i] = kh[0]
            for place in range(1, len(kids)):
                edges[kh[place]] = (None, "none", i, place)
            continue
        headpiece[i] = kh[h]
        for place, p in enumerate(kh):
            if place != h:
                edges[p] = (kh[h], basis, i, place)
    root = headpiece[tops[0]]
    edges[root] = (None, "root", None, None)
    # every leaf has an entry
    leaves = set(leafcat)
    if set(edges) != leaves:
        raise ValueError(f"{sref}: leaves without an edge {sorted(leaves - set(edges))[:5]}")
    return edges, root


def leafsets(tops, nodes):
    """node index -> tuple of the pids under it (in node order)."""
    out = [None] * len(nodes)
    order, stack = [], [tops[0]]
    while stack:
        i = stack.pop()
        order.append(i)
        if nodes[i][4] == "n":
            stack.extend(nodes[i][3])
    for i in reversed(order):
        if nodes[i][4] in ("w", "c"):
            out[i] = tuple(nodes[i][3])
        else:
            out[i] = tuple(p for k in nodes[i][3] for p in out[k])
    return out


def d3_label(node, place, xset, roles, nodes, lang, counts, ex, where):
    """D3: the label of the edge from child `place` of node `node`, whose pieces are `xset`."""
    hit = roles.get(xset)
    if hit is not None:
        role, inner_role, tag, cls = hit
        if usable(role):
            code = X.c0(role)
            if code != role:
                counts["role values changed by C0"] += 1
            counts["D3 labels from a role"] += 1
            return code
        if role is not None:
            counts["D3 empty or err__ roles not used as labels"] += 1
            ex["D3 empty or err__ roles not used as labels"].append(f"{where} {role!r}")
        if inner_role:
            counts["D3 outermost element without role, an element further in has one"] += 1
            ex["D3 outermost element without role, an element further in has one"].append(where)
    cat, rule, head, kids, kind = nodes[node]
    if kind == "c":
        counts["D3 labels c:<place>"] += 1
        return f"c:{place}"
    if rule is None:
        counts["D3 labels run:<place>"] += 1
        if lang == "grc":
            ex["Greek branching nodes without Rule"].append(where)
        return f"run:{place}"
    counts["D3 labels <rule>:<place>"] += 1
    return f"{rule}:{place}"


# ---- lowfat against node files ---------------------------------------------------------------------------------

def compare_lowfat(sref, els, tops, nodes, lsets, edges, roles, counts, ex, lang):
    """Disagreements between the node files and the lowfat files of one sentence, counted."""
    node_sets = {}
    for i, s in enumerate(lsets):
        node_sets.setdefault(frozenset(s), []).append(i)
    pid_nodes = {p for i, n in enumerate(nodes) if n[4] in ("w", "c") for p in n[3]}
    pid_low = {p for e in els if e[0] == "w" for p in e[6]}
    if pid_nodes != pid_low:
        counts[f"{lang} sentences whose pieces differ between node and lowfat files"] += 1
        ex["sentences whose pieces differ between node and lowfat files"].append(sref)
    # the head child of each node, as a piece set: set of (parent set, child set)
    head_pairs = set()
    for i, (cat, rule, head, kids, kind) in enumerate(nodes):
        if kind != "n" or len(kids) < 2:
            continue
        ps = frozenset(lsets[i])
        if head is not None:
            head_pairs.add((ps, frozenset(lsets[kids[int(head)]])))
        else:
            for k in kids:   # D2p(a): the non-conjunction child
                if nodes[k][0] not in CONJ_CATS:
                    head_pairs.add((ps, frozenset(lsets[k])))
    for j, (tag, role, cls, rule, head, typ, pids, parent) in enumerate(els):
        s = frozenset(pids)
        if tag == "wg" and s not in node_sets:
            counts[f"{lang} lowfat groups with no node of the same pieces"] += 1
            counts[f"{lang} lowfat groups with no node of the same pieces, class {cls or typ or '-'}"] += 1
        if lang != "grc" and tag == "wg" and parent >= 0:
            pset = frozenset(els[parent][6])
            in_nodes = (pset, s) in head_pairs
            if pset == s:
                continue
            marked = head == "true"
            key = {(True, True): "agree: marked head, node head child",
                   (False, False): "agree: unmarked, not the node head child",
                   (True, False): "DISAGREE: lowfat head=\"true\", not the node head child",
                   (False, True): "DISAGREE: node head child, lowfat not marked"}[(marked, in_nodes)]
            counts[f"{lang} lowfat head=\"true\" vs node Head: {key}"] += 1
            if key.startswith("DISAGREE"):
                ex[f"{lang} lowfat head vs node Head: {key[10:]}"].append(
                    f"{sref} {cls or '-'} {rule or '-'} in {els[parent][2] or '-'} {els[parent][3] or '-'} "
                    f"{pids[0]}")
        if lang != "grc" and tag == "wg" and parent < 0 and head is not None:
            counts[f"{lang} lowfat top groups with head attribute"] += 1
        if usable(role):
            # where does a role-bearing element stand in the node tree?
            if s not in node_sets and tag != "w":
                counts[f"{lang} roles on lowfat groups with no node of the same pieces"] += 1
                ex[f"{lang} roles on lowfat groups with no node of the same pieces"].append(
                    f"{sref} {role} {pids[0]}")


# ---- build -----------------------------------------------------------------------------------------------------

def fallback_label(nodes, node, place):
    """D3 without the role: `c:<place>`, `run:<place>` or `<rule>:<place>` (used for Greek one-word clauses, 1.1)."""
    cat, rule, head, kids, kind = nodes[node]
    if kind == "c":
        return f"c:{place}"
    return f"run:{place}" if rule is None else f"{rule}:{place}"


def compute(lang_tables, trees, lowfat_els, langs_here, counts, ex, v11=False, fall=None):
    """D2p and D3 over a whole text. `lang_tables`: lang -> (W, P). Returns pid -> (head pid or None, basis, rel).
    `fall` (1.1): a dict that receives pid -> (the label D3 gives without a role, whether the edge's dependent child
    holds exactly that one piece, the tag of the outermost lowfat element with exactly that piece set)."""
    hidden = set()
    for lang, (W, P) in lang_tables.items():
        hidden.update(f for f in P["fused"] if f)
    tag = "grc" if "grc" in langs_here else "tan"
    edge_of = {}
    sent_low = [s for _, ss in lowfat_els for s in ss]
    sent_nodes = [(sref, tops, nodes, leafcat) for _, ss in trees for sref, tops, nodes, leafcat in ss]
    if len(sent_low) != len(sent_nodes):
        raise ValueError(f"sentences: lowfat {len(sent_low)}, node files {len(sent_nodes)}")
    counts[f"{tag} sentences (node files)"] = len(sent_nodes)
    for (sref, tops, nodes, leafcat), els in zip(sent_nodes, sent_low):
        edges, root = sentence_edges(tops, nodes, leafcat, hidden, counts, ex, sref, v11=v11, tanakh=tag == "tan")
        lsets = leafsets(tops, nodes)
        roles = role_index(els, ex, counts)
        compare_lowfat(sref, els, tops, nodes, lsets, edges, roles, counts, ex, tag)
        for p, (h, basis, node, place) in edges.items():
            if basis == "root":
                edge_of[p] = (None, "root", "root")
                continue
            if fall is not None:
                xs = frozenset([p]) if nodes[node][4] == "c" else frozenset(lsets[nodes[node][3][place]])
                hit = roles.get(xs)
                fall[p] = (fallback_label(nodes, node, place), xs == frozenset([p]), hit[2] if hit else None)
            if basis == "none":
                edge_of[p] = (None, "none", d3_label(node, place, frozenset(lsets[nodes[node][3][place]])
                                                     if nodes[node][4] == "n" else frozenset([p]),
                                                     roles, nodes, tag, counts, ex, f"{sref} {p}"))
                continue
            if nodes[node][4] == "c":
                xset = frozenset([p])
            else:
                xset = frozenset(lsets[nodes[node][3][place]])
            edge_of[p] = (h, basis, d3_label(node, place, xset, roles, nodes, tag, counts, ex, f"{sref} {p}"))
    # letterless articles: their own edges are not carried; a piece whose head is one takes its head instead
    for p in hidden:
        counts["letterless article edges not carried"] += 1
        if edge_of[p][1] == "root":
            ex["letterless article at the root"].append(p)
    for p, (h, basis, rel) in list(edge_of.items()):
        if p in hidden or h is None or h not in hidden:
            continue
        seen = set()
        while h in hidden:
            if h in seen:
                raise ValueError(f"loop through letterless articles at {p}")
            seen.add(h)
            h = edge_of[h][0]
        counts["pieces whose head was a letterless article (took its head)"] += 1
        ex["pieces whose head was a letterless article (took its head)"].append(p)
        edge_of[p] = (h, basis, rel)
    return edge_of, hidden


def fill(lang, W, P, edge_of, place_of, word_lang, counts, ex):
    """Fill the head columns of one language's tables from the piece edges (D2p) by D2w."""
    n = len(P["pid"])
    P["head_t"], P["head_n"], P["head_basis"], P["rel"] = [None] * n, [None] * n, [None] * n, [None] * n
    for i, pid in enumerate(P["pid"]):
        h, basis, rel = edge_of[pid]
        if h is None:
            P["head_t"][i], P["head_n"][i] = 0, 0
            if basis == "none":
                counts[f"{lang} pieces with head_basis none (D2p c)"] += 1
        else:
            P["head_t"][i], P["head_n"][i] = place_of[h]
        P["head_basis"][i], P["rel"][i] = basis, rel
        counts[f"{lang} pieces head_basis {basis}"] += 1
    return P


def depth_of(edge_of, hidden):
    """Steps up to the root over the pieces that are rows (letterless articles are skipped by construction)."""
    depth = {}
    for p in edge_of:
        if p in hidden:
            continue
        chain, x = [], p
        while x is not None and x not in depth:
            chain.append(x)
            x = edge_of[x][0]
        base = depth[x] if x is not None else -1
        for y in reversed(chain):
            base += 1
            depth[y] = base
    return depth


def _top_piece(idx, P, depth):
    md = min(depth[P["pid"][i]] for i in idx)
    tied = [i for i in idx if depth[P["pid"][i]] == md]
    stem = [i for i in tied if P["kind"][i] == "stem"]
    return (stem[0] if stem else tied[0]), tied


def words_fill(lang, W, P, edge_of, depth, place_of, word_of_t, counts, ex, v11=False):
    """D2w. Hebrew and Aramaic: the top piece; Greek: the one piece.
    `v11` (SPEC 1.1): a `prefix` piece of class `cj` is left out wherever another piece of the word has its head
    outside the word (a head 0, the root, counts as outside)."""
    byt = C.defaultdict(list)
    for i, t in enumerate(P["t"]):
        byt[t].append(i)
    m = len(W["t"])
    W["head"], W["head_basis"], W["rel"] = [None] * m, [None] * m, [None] * m
    widx = {t: j for j, t in enumerate(W["t"])}
    for t, idx in byt.items():
        idx.sort(key=lambda i: P["n"][i])
        if lang == "grc":
            top = idx[0]
        else:
            top, tied = _top_piece(idx, P, depth)
            if v11:
                old_top = top
                cand = [i for i in idx if not (P["kind"][i] == "prefix" and P["class"][i] == "cj" and any(
                    j != i and P["head_t"][j] != t for j in idx))]
                if not cand:
                    raise ValueError(f"word {t}: D2w leaves no piece")
                top, tied = _top_piece(cand, P, depth)
                if top != old_top:
                    counts[f"{lang} D2w: words whose edge moves off their cj prefix (1.1)"] += 1
                    if P["kind"][old_top] != "prefix" or P["class"][old_top] != "cj":
                        raise ValueError(f"word {t}: the top piece moved off a piece that is not a cj prefix")
                if P["kind"][old_top] == "prefix" and P["class"][old_top] == "cj":
                    counts[f"{lang} D2w: words whose top piece by 1.0's rule is a cj prefix"] += 1
                    if top == old_top:
                        counts[f"{lang} D2w: words whose cj prefix stays the top piece (no other piece leaves "
                               "the word)"] += 1
            if len(tied) > 1:
                counts[f"{lang} words with a tie for the top piece"] += 1
            if P["kind"][top] != "stem":
                counts[f"{lang} words whose top piece is not the stem"] += 1
                counts[f"{lang} words whose top piece is not the stem, class {P['class'][top]}"] += 1
            # edges of other pieces that leave the word: kept in pieces only
            for i in idx:
                if i == top:
                    continue
                ht = P["head_t"][i]
                if ht != t:
                    counts[f"{lang} piece edges leaving the word not carried at the word level"] += 1
        j = widx[t]
        ht = P["head_t"][top]
        if ht == t:
            raise ValueError(f"word {t}: the top piece's head lies in the word")
        W["head"][j] = ht
        W["head_basis"][j] = P["head_basis"][top]
        W["rel"][j] = P["rel"][top]
    return W


def relmap_rows(lang, W):
    """D4: relmap.tsv rows (label, shared, count of words) and rel_shared for every word."""
    use = C.Counter(W["rel"])
    total = len(W["rel"])
    rows, missing = [], []
    for label in sorted(use):
        shared = RELMAP.get(lang, {}).get(label) or RELMAP["all"].get(label) or "none"
        if shared == "none" and use[label] / total >= SHARE:
            missing.append((label, use[label]))
        rows.append([label, shared, use[label]])
    shared_of = {r[0]: r[1] for r in rows}
    W["rel_shared"] = [shared_of[r] for r in W["rel"]]
    return rows, missing


def build(outdir, langs, counts):
    ex = C.defaultdict(list)
    cnt = C.Counter()
    groups = []
    if {"hbo", "arc"} & set(langs):
        if not {"hbo", "arc"} <= set(langs):
            raise SystemExit("stage 03: hbo and arc are built together (heads cross them in GEN 31:47, DAN 2:4)")
        groups.append((("hbo", "arc"), S.heb_trees, S.heb_lowfat_elements))
    if "grc" in langs:
        groups.append((("grc",), S.grc_trees, S.grc_lowfat_elements))
    for gl, trees_f, els_f in groups:
        tables = {lang: read_stage02(outdir, lang) for lang in gl}
        for lang, (W, P) in tables.items():
            if any(v is not None for v in P["head_t"]):
                cnt[f"{lang}: head columns were filled before (rebuilt)"] += 1
        edge_of, hidden = compute(tables, trees_f(), els_f(), gl, cnt, ex)
        place_of = {}
        for lang, (W, P) in tables.items():
            for i, pid in enumerate(P["pid"]):
                place_of[pid] = (P["t"][i], P["n"][i])
        rows_pids = set(place_of)
        if set(edge_of) - hidden != rows_pids:
            raise ValueError("piece rows and node-file leaves differ")
        depth = depth_of(edge_of, hidden)
        for lang, (W, P) in tables.items():
            fill(lang, W, P, edge_of, place_of, None, cnt, ex)
            words_fill(lang, W, P, edge_of, depth, place_of, None, cnt, ex)
            rows, missing = relmap_rows(lang, W)
            for label, n in missing:
                ex[f"{lang} labels at or above 0.1% of words without a shared name"].append(f"{label} {n}")
            d = os.path.join(outdir, lang)
            X.write_parquet(os.path.join(d, "words.parquet"), W, EW.pa.schema(EW.WORD_COLS))
            X.write_parquet(os.path.join(d, "pieces.parquet"), P, EW.pa.schema(EW.PIECE_COLS))
            X.write_tsv(os.path.join(d, "relmap.tsv"), ["label", "shared", "count"], rows)
            nwords = len(W["t"])
            cnt[f"{lang} words"] = nwords
            cnt[f"{lang} distinct word labels"] = len(rows)
            cnt[f"{lang} word labels mapped (not none)"] = sum(1 for r in rows if r[1] != "none")
            cnt[f"{lang} words with rel_shared none"] = sum(1 for v in W["rel_shared"] if v == "none")
            cnt[f"{lang} words with rel_shared none, share"] = round(
                sum(1 for v in W["rel_shared"] if v == "none") / nwords, 4)
            for b, k in C.Counter(W["head_basis"]).items():
                cnt[f"{lang} words head_basis {b}"] = k
            cnt[f"{lang} word roots"] = sum(1 for v in W["head"] if v == 0)
    for k in sorted(cnt):
        counts[k] = cnt[k]
    return ex
