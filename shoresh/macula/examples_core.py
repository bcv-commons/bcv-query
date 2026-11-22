"""Stage 15 (core) of the source-examples build, SPEC 1.1 (build c1): sections 3, 4.1, 4.2, 4.3, 4.4, 4.6, 4.10 and
the rules D1, D2p (with (d)), D2w (the `cj` prefix rule), D3 (Greek one-word clauses), D5, D8 (B5), B3, B6.

Writes per language (hbo, arc, grc): words.parquet (all columns but `rel_shared`), pieces.parquet (`t` ... `domain`,
`head_t`, `head_n`, `head_basis`, `rel`), lexemes.tsv, clauses.parquet (`clause` ... `pred_kind`), constituents.parquet
(all but `sem_role`, `sem_role_basis`) and categories.toml (the piece part and the coded columns of 4.1 to 4.4).
Every column a later stage fills is present and null. Writes cache/morphid.parquet (the node files' morphId -> pid
map). Counts and exception lists go to cache/stage15-counts.json (through build_examples.py).

It runs the code of the 1.0 stages 02, 03 and 04 (examples_words, examples_heads, examples_clauses) with their 1.1
switches on, in one pass: words and pieces, then heads (D2p, D2w), then clauses (which read the word heads for B5),
then the D3 labels of the Greek one-word clauses (which read `role_wrapped`). Nothing is read from build b1.
"""
import collections as C
import json
import os
import re

import pyarrow as pa

import examples_common as X
import examples_src as S
import examples_words as EW
import examples_heads as EH
import examples_clauses as EC

PIECE_COLS_11 = EW.PIECE_COLS + [("concept", pa.string()), ("concept_by", pa.string())]
WORD_COLS_11 = EW.WORD_COLS
ROLE_CODES = EC.ROLE_CODES


# ---- categories.toml (SPEC 4.10; B13) ---------------------------------------------------------------------------

def _section(out, name, column, basis, source, values=None, pattern=None, note=None):
    out.append(f"[{name}]")
    out.append(f"column = {X.toml_str(column)}")
    out.append(f"basis = {X.toml_str(basis)}")
    out.append(f"source = {X.toml_str(source)}")
    if note:
        out.append(f"note = {X.toml_str(note)}")
    if pattern is not None:
        pat, forms = pattern
        out.append(f"pattern = {X.toml_str(pat)}")
        out.append(f"distinct = {forms['distinct']}")
        out.append("forms = [")
        for f, n in forms["by form"]:
            out.append(f"  {{ form = {X.toml_str(f)}, count = {n} }},")
        out.append("]")
    if values is not None:
        out.append("values = [")
        for code, value, rule, n in values:
            out.append(f"  {{ code = {X.toml_str(code)}, value = {X.toml_str(value)}, rule = {X.toml_str(rule)}, "
                       f"count = {n} }},")
        out.append("]")
    out.append("")


HEAD_BASIS = {"index": "D2p: the node's Head", "conj": "D2p (a)", "compound": "D2p (b)", "none": "D2p (c)",
              "sentence": "D2p (d)", "root": "D2p: the top node's head piece"}
PRED_KIND = {"v": "the first v child (not a one-word clause); rule v2cl (B3)", "vc": "the first vc child; rule vc2cl",
             "p": "the first p child; rule p2cl", "none": "no v, vc, p child"}


def _label_forms(labels):
    """`rel` labels by form: a role code, `<rule>:<place>`, `run:<place>`, `c:<place>`, `root`."""
    by = C.Counter()
    for v in labels:
        if v == "root":
            by["root"] += 1
        elif v in ROLE_CODES:
            by[f"role {v}"] += 1
        elif re.fullmatch(r"run:\d+", v):
            by["run:<place>"] += 1
        elif re.fullmatch(r"c:\d+", v):
            by["c:<place>"] += 1
        elif re.fullmatch(r"[^:\s]+:\d+", v):
            by["<rule>:<place>"] += 1
        else:
            by[f"OTHER {v}"] += 1
    return {"distinct": len(set(labels)), "by form": sorted(by.items())}


def _class_value(code, src_values):
    if code == "group":
        return 'type="group" without class', "SPEC 4.3"
    if code == "run":
        return "wg without class", "SPEC 4.3"
    if code == "compound":
        return "c element", "SPEC 4.4 (B6)"
    return src_values.get(code, code), "C0"


def categories_text(lang, P, W, crows, krows, coder, class_src):
    out = [f"# categories.toml, {lang}: SPEC 1.1, section 4.10. Written by build_examples.py --build c1 --stage 15:",
           "# the categories of pieces, and the coded columns of words, pieces, clauses and constituents (B13).",
           "# `rule`: `list` = the code list of 4.10, `C0` = rule C0, or the rule of section 6 that makes the code.",
           "# `count` = rows of this language's table with the value. Stage 16 adds the clause categories (D9).", ""]
    use = EW.category_use(P)
    for cat in list(X.MARK_CATS[lang]) + ["class", "kind"]:
        if cat not in use:
            continue
        col = "marks" if cat in X.MARK_CATS[lang] else cat
        vals = [(code, coder.seen[(cat, code)], "D5" if cat == "kind" else coder.rule[(cat, code)], use[cat][code])
                for code in sorted(use[cat])]
        _section(out, f"pieces.{cat}", col, "derived" if cat == "kind" else "given",
                 EW.CAT_SOURCE.get(cat, f"MACULA lowfat attribute {cat}"), vals)
    for tab, D in (("pieces", P), ("words", W)):
        hb = C.Counter(D["head_basis"])
        _section(out, f"{tab}.head_basis", "head_basis", "derived",
                 "rule D2p" if tab == "pieces" else "rule D2w (the head_basis of the word's top piece)",
                 [(k, HEAD_BASIS[k], "SPEC 4.2", hb[k]) for k in sorted(hb)])
        _section(out, f"{tab}.rel", "rel", "derived",
                 "rule D3: MACULA lowfat role, else the node files' Rule and the child's place",
                 pattern=("a role code of SPEC 4.4 | <rule>:<place> | run:<place> | c:<place> | root",
                          _label_forms(D["rel"])))
    rc = C.Counter(r["rule"] for r in crows)
    _section(out, "clauses.rule", "rule", "given", "MACULA lowfat attribute rule (Greek: rule, else Rule)",
             pattern=("the source's rule name, as written", {"distinct": len(rc), "by form": [
                 ("rule names", sum(rc.values()))]}))
    pc = C.Counter(r["pattern"] for r in crows if r["pattern"])
    _section(out, "clauses.pattern", "pattern", "given", "MACULA lowfat attribute rule",
             pattern=("the rule, where each part between hyphens is a role code of 4.4 in capitals; else empty",
                      {"distinct": len(pc), "by form": [("rules that are a pattern", sum(pc.values()))]}))
    for col, src in (("via", "MACULA lowfat class (or type) of the outermost group between the clause and its parent"),
                     ("role", "MACULA lowfat attribute role"),
                     ("role_wrapped", "rule D8: the role of the via group, or of the slot (Greek one-word clause)"),
                     ("pred_kind", "SPEC 4.3 (B3)")):
        cc = C.Counter(r[col] for r in crows if r[col])
        if col == "pred_kind":
            vals = [(k, PRED_KIND[k], "SPEC 4.3", cc[k]) for k in sorted(cc)]
        elif col == "via":
            vals = [(k, *_class_value(k, class_src), cc[k]) for k in sorted(cc)]
        else:
            vals = [(k, k, "C0", cc[k]) for k in sorted(cc)]
        basis = "derived" if col == "role_wrapped" else "given"
        _section(out, f"clauses.{col}", col, basis, src, vals,
                 note="empty: " + {"via": "a direct child of its parent, or no parent",
                                   "role": "no role in the source (a Greek one-word clause: always empty, B2)",
                                   "role_wrapped": "an own role, or D8 gives none",
                                   "pred_kind": "never empty"}[col] + f" ({sum(1 for r in crows if not r[col])})")
    kc = C.Counter(r["role"] for r in krows)
    _section(out, "constituents.role", "role", "given", "MACULA lowfat attribute role (direct children of a clause)",
             [(k, k, "C0", kc[k]) for k in sorted(kc)])
    kl = C.Counter(r["class"] for r in krows)
    _section(out, "constituents.class", "class", "given", "MACULA lowfat class (or type) of the part",
             [(k, *_class_value(k, class_src), kl[k]) for k in sorted(kl) if k],
             note=f"empty: no class, no type group ({kl.get('', 0)})")
    fl = C.Counter(x for r in krows for x in r["frame_role"].split())
    _section(out, "constituents.frame_role", "frame_role", "given",
             "MACULA lowfat attribute frame on the stem piece of the clause's pred word (labels, separated by a space)",
             [(k, k, "given", fl[k]) for k in sorted(fl)],
             note=f"count = labels; rows with two or more labels: "
                  f"{sum(1 for r in krows if ' ' in r['frame_role'])}")
    return "\n".join(out)


# ---- the build --------------------------------------------------------------------------------------------------

def empty_frame_entries(words, cnt, ex):
    """SPEC 10 'references': frame entries with no target, counted and listed (Hebrew, Aramaic)."""
    for w in words:
        for p in w["pieces"]:
            for label, targets in EC.parse_frame(p.get("frame")):
                if not targets:
                    cnt["references: frame entries with no target"] += 1
                    cnt[f"references: frame entries with no target, {label}:;"] += 1
                    ex["references: frame entries with no target"].append(f"{p['id']} {label}:;")
            for tok in (p.get("frame") or "").split():
                if ":;" in tok and re.search(r"\d{12}", tok):
                    # an empty slot before a target: the entry has a target (SPEC 10 counted 1,292 `:;` in all)
                    cnt["references: frame entries with an empty slot before their target"] += 1
                    ex["references: frame entries with an empty slot before their target"].append(
                        f"{p['id']} {tok}")


def relabel_one_word(P, W, edge_of, fall, oneword, cnt, ex):
    """D3 (1.1): the edge of a Greek one-word clause takes its role_wrapped where filled, else <rule>:<place>."""
    row = {pid: i for i, pid in enumerate(P["pid"])}
    wrow = {t: j for j, t in enumerate(W["t"])}
    for pid, (key, rw) in sorted(oneword.items()):
        i = row[pid]
        old = P["rel"][i]
        if P["head_basis"][i] == "root":
            cnt["grc D3: one-word clauses at the root (label root kept)"] += 1
            continue
        fb, single, outer_tag = fall[pid]
        if not single:
            # the edge belongs to a larger child whose head piece this is; its label is that child's
            cnt["grc D3: one-word clause pieces whose edge is that of a larger part (label kept)"] += 1
            continue
        new = rw if rw else fb
        cnt["grc D3: one-word clause edges, label from " + ("role_wrapped" if rw else "<rule>:<place>")] += 1
        if outer_tag != "w":
            cnt[f"grc D3: one-word clause edges whose outermost element of the same piece is a {outer_tag}"] += 1
            ex["grc D3: one-word clause edges whose outermost element of the same piece is not the w"].append(
                f"{key} {outer_tag} {old} -> {new}")
        if new != old:
            cnt["grc D3: one-word clause edges whose label changes"] += 1
            cnt[f"grc D3: one-word clause edges whose label changes, from {old if old in ROLE_CODES else 'other'}"] += 1
        h, basis, _ = edge_of[pid]
        edge_of[pid] = (h, basis, new)
        P["rel"][i] = new
        W["rel"][wrow[P["t"][i]]] = new


def build(outdir, langs, counts):
    ex = C.defaultdict(list)
    cnt = C.Counter()
    langs = set(langs)
    if {"hbo", "arc"} & langs and not {"hbo", "arc"} <= langs:
        raise SystemExit("stage 15: hbo and arc are built together (heads and clauses cross them)")
    ubs = EW.read_ubs()
    ubs_used = set()
    cache = os.path.join(outdir, "cache")
    groups = []
    if "hbo" in langs:
        words, ex_t, comp_strong, node_text, leaves = EW.tanakh(cnt)
        for k, v in ex_t.items():
            ex[k].extend(v)
        letter_pids = {p["id"] for w in words for p in w["pieces"]}
        for w in words:
            for p in w["pieces"]:
                if node_text.get(p["id"]) != p["text"]:
                    ex["pieces whose node-file text differs from lowfat"].append(p["id"])
        bym = EW.morphid_map(leaves, letter_pids, os.path.join(cache, "morphid.parquet"), cnt)
        EW.reference_repair(words, bym, letter_pids, cnt, ex)
        empty_frame_entries(words, cnt, ex)
        cnt["compound words"] = sum(1 for w in words if any(p["id"] in comp_strong for p in w["pieces"]))
        tabs, lexes, coders = {}, {}, {}
        for lang in ("hbo", "arc"):
            coder = X.Coder()
            W, P, lex = EW.heb_rows(words, lang, comp_strong, ubs, coder, cnt, ex)
            ubs_used.update(("hbo", pid[1:]) for pid in P["pid"])
            tabs[lang], lexes[lang], coders[lang] = (W, P), lex, coder
        groups.append((("hbo", "arc"), tabs, lexes, coders, S.heb_trees, S.heb_lowfat_elements,
                       S.heb_lowfat_files(), False, bym))
    if "grc" in langs:
        coder = X.Coder()
        W, P, lex = EW.greek(ubs, coder, cnt, ex)
        ubs_used.update(("grc", pid[1:]) for pid in P["pid"])
        groups.append((("grc",), {"grc": (W, P)}, {"grc": lex}, {"grc": coder}, S.grc_trees,
                       S.grc_lowfat_elements, S.grc_lowfat_files(), True, None))
    for lang, cond in (("hbo", "hbo" in langs), ("grc", "grc" in langs)):
        if cond:
            miss = sorted(k for k in ubs if k[0] == lang and k not in ubs_used)
            cnt[f"UBS {lang} keys that name no piece"] = len(miss)
            ex[f"UBS {lang} keys that name no piece"] = [k[1] for k in miss]

    for gl, tabs, lexes, coders, trees_f, els_f, files, greek, bym in groups:
        # heads: D2p (with (d)), D3, D2w (with the cj rule)
        fall = {}
        edge_of, hidden = EH.compute(tabs, trees_f(), els_f(), gl, cnt, ex, v11=True, fall=fall)
        place_of = {pid: (P["t"][i], P["n"][i]) for lang, (W, P) in tabs.items() for i, pid in enumerate(P["pid"])}
        if set(edge_of) - hidden != set(place_of):
            raise ValueError("piece rows and node-file leaves differ")
        depth = EH.depth_of(edge_of, hidden)
        for lang, (W, P) in tabs.items():
            EH.fill(lang, W, P, edge_of, place_of, None, cnt, ex)
            EH.words_fill(lang, W, P, edge_of, depth, place_of, None, cnt, ex, v11=True)
        # clauses and constituents (B3, B5, B6), words.clause
        keep = {}
        out, wclause = EC.compute(tabs, files, greek, bym, cnt, ex, keep=keep, v11=True)
        if greek:
            W, P = tabs["grc"]
            relabel_one_word(P, W, edge_of, fall, keep.get("oneword", {}), cnt, ex)
        # the source's class values behind the codes of via and constituent class
        class_src = keep.get("class_src", {})
        for lang in gl:
            W, P = tabs[lang]
            W["clause"] = wclause[lang]
            for k in ("concept", "concept_by"):
                P[k] = [None] * len(P["t"])
            crows, krows = out[lang]
            d = os.path.join(outdir, lang)
            X.write_parquet(os.path.join(d, "words.parquet"), W, pa.schema(WORD_COLS_11))
            X.write_parquet(os.path.join(d, "pieces.parquet"), P, pa.schema(PIECE_COLS_11))
            cnt[f"{lang} lexemes"] = EW.write_lexemes(os.path.join(d, "lexemes.tsv"), lexes[lang])
            X.write_parquet(os.path.join(d, "clauses.parquet"),
                            {k: [r[k] for r in crows] for k, _ in EC.CLAUSE_COLS_11}, pa.schema(EC.CLAUSE_COLS_11))
            X.write_parquet(os.path.join(d, "constituents.parquet"),
                            {k: [r[k] for r in krows] for k, _ in EC.CONST_COLS_11}, pa.schema(EC.CONST_COLS_11))
            X.write_text(os.path.join(d, "categories.toml"),
                         categories_text(lang, P, W, crows, krows, coders[lang], class_src))
            for (cat, value), code in sorted(coders[lang].c0_closed.items()):
                ex[f"{lang}: closed-category values coded by C0"].append(f"{cat} {value!r} -> {code}")
            cnt[f"{lang} words"] = len(W["t"])
            cnt[f"{lang} pieces"] = len(P["t"])
            cnt[f"{lang} clauses"] = len(crows)
            cnt[f"{lang} constituents"] = len(krows)
            cnt[f"{lang} words with a clause"] = sum(1 for v in wclause[lang] if v)
            cnt[f"{lang} word roots"] = sum(1 for v in W["head"] if v == 0)
            for b, k in C.Counter(W["head_basis"]).items():
                cnt[f"{lang} words head_basis {b}"] = k
            cnt[f"{lang} hidden articles in fused"] = sum(1 for f in P["fused"] if f)
    for k in sorted(cnt):
        counts[k] = cnt[k]
    return ex
