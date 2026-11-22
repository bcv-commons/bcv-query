"""Rules W2 (defining vocabulary), W3 (level of a lexeme), W4 (level of a sense): SPEC-levels 4.3 to 4.5."""
from collections import Counter, defaultdict

from levels_common import band, level_by_count, lexicon, model_count, strict_count, table
from levels_explain import explaining

DV_MIN_USES = 2   # D-1


def vocabulary(rows):
    """-> {lexeme: {uses, sources, explains, in_dv}} for every lexeme with at least one use."""
    uses, srcs, expl = Counter(), defaultdict(set), defaultdict(set)
    for r in explaining(rows):
        for y in r["y_content"]:
            uses[y] += 1
            srcs[y].add(r["source"])
            expl[y].add(r["x_lexeme"])
    return {lx: {"uses": n, "sources": " ".join(sorted(srcs[lx])), "explains": len(expl[lx]),
                 "in_dv": n >= DV_MIN_USES} for lx, n in uses.items()}


def single_senses():
    """(lexeme, sense) -> Tanakh pieces whose sense holds exactly that one code (hbo and arc)."""
    c = Counter()
    for part in ("hbo", "arc"):
        p = table(part, "pieces", ("lexeme", "sense"))
        for lx, s in zip(p["lexeme"], p["sense"]):
            if lx and s and len(s.split()) == 1:
                c[(lx, s)] += 1
    return c


def kind_of(r, voc):
    if r["state"] == "name":
        return "name"
    if r["state"] == "function" or r["class"] not in ("noun", "verb", "adj", "adv", "num"):
        return "function"
    if r["class"] == "num":
        return "number"
    if voc.get(r["lexeme"], {}).get("in_dv"):
        return "dv"
    return None


def levels(rows, voc, senses):
    """-> list of levels.tsv rows (dicts), sorted by lexeme."""
    expl_n, one_n = Counter(), Counter()
    for r in explaining(rows):
        if r["y_content"]:
            expl_n[r["x_lexeme"]] += 1
            if r["one_word"]:
                one_n[r["x_lexeme"]] += 1
    n_senses = Counter(lx for lx, _ in senses)
    out = []
    for lx in sorted(lexicon()):
        r = lexicon()[lx]
        cnt, cm = strict_count(lx), model_count(lx)
        kind = kind_of(r, voc) or ("explained" if expl_n[lx] else "unexplained")

        def lev(n):
            if n == 0:
                return None
            if kind in ("name", "function", "number"):
                return 0
            if kind == "dv":
                return 1
            return level_by_count(n)

        level = lev(cnt)
        lm = lev(cm)
        out.append({
            "lexeme": lx, "lemma": r["lemma"], "lang": r["lang"], "class": r["class"], "state": r["state"],
            "count": cnt, "band": band(cnt), "kind": kind, "level": level, "uses": voc.get(lx, {}).get("uses", 0),
            "explanations": expl_n[lx], "one_word": one_n[lx], "senses": n_senses[lx], "count_model": cm,
            "level_model": lm if lm != level else None,
        })
    return out


def sense_levels(senses, level_rows):
    lev = {r["lexeme"]: r["level"] for r in level_rows}
    out = []
    for (lx, s), n in sorted(senses.items()):
        tan = int(lexicon()[lx]["tanakh"] or 0)
        own = level_by_count(n)
        base = lev.get(lx)
        level = max(x for x in (base, own) if x is not None) if (base is not None or own is not None) else None
        out.append({"lexeme": lx, "sense": s, "count": n, "share": n / tan if tan else None, "level": level})
    return out
