"""Greek prepositions, pronouns and conjunctions linked to their Hebrew parts in the Hebrew NTs by rule (S1c, 2026-11-19:
internal-docs/clause-structure-work/s1c-figures-2026-11-19.md; rules registered before the sealed sample was scored, scored once).

    from macula import hebrew_nt_function_words as F
    F.links(edition)   # -> {greek id: {"cls", "verse", "parts": [(i, part | None)], "by": "rule" | "aligner" | "none"}}
    python -m macula.hebrew_nt_function_words --check   # the rules on the sealed sample: must give the recorded figures

The aligner's link is the by-id form (bcv-commons/alignments-by-id for Salkinson, research's packet 32 run for Delitzsch), which
keeps whether a link points at a whole Hebrew word or at one of its parts. part None = a whole word the rule could not narrow.
  prep  the aligner's link resolved: a whole word -> its leading run of preposition / object-marker parts (else part 0); a part
        -> that part plus the preposition / object-marker parts right after it (מֵ|אֵת); a same-word פָּנִים joins (לִ|פְנֵי); a
        following separate prepositional noun word joins (עַל יְדֵי, עַל פִּי). No link: the first content word after the
        preposition, its reviewed Hebrew word's prefixed preposition, else the word before it when that is a lone preposition
        word, else none.
  pron  the content word before the pronoun in its phrase (else its clause's verb): its reviewed Hebrew word's last pronoun
        suffix. Else the aligner's link resolved to its pronoun suffix (else pronoun / relative) part.
  conj  the first content word after the conjunction: its reviewed Hebrew word's leading conjunction part, else the word before
        it when that holds one. Else the aligner's link resolved to its conjunction (or relative) part.
Sealed figures (exact match with blind judges, ~200 per class and edition; Salkinson / Delitzsch): prep 0.720 / 0.835, pron
0.693 / 0.704, conj 0.709 / 0.725; the aligner 0.505 / 0.550, 0.588 / 0.588, 0.497 / 0.450.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from macula import hebrew_nt_articles as A

HERE = Path(__file__).resolve().parent
BY_ID = {"heb_scg": HERE / "data" / "alignments-by-id-v1.1" / "n1904" / "h" / "heb" / "heb_scg",
         "heb_mod": HERE / "data" / "handover" / "p32" / "heb_mod" / "by-id"}
CLASSES = ("prep", "pron", "conj")
FAM = {"prep": {"prep", "om"}, "pron": {"pron", "rel"}, "conj": {"cj", "rel"}}
# פנים יד פה תוך עבר בעד למען נגד תחת אחר על: nouns (and על) that make a compound preposition with the one before them
PREP_NOUNS = {"6440", "3027", "6310", "8432", "5676", "1157", "4616", "5048", "8478", "310", "5921"}


def _lemmas(ed: str) -> dict:
    import pyarrow.parquet as pq
    L = {}
    for r in pq.read_table(A.ANALYSIS / ed / "words.parquet", columns=["book", "chapter", "verse", "i", "part", "strong", "class"]).to_pylist():
        L[(r["book"], r["chapter"], r["verse"], r["i"], r["part"])] = ((r["strong"] or "").rstrip("abcdefgh").lstrip("0"), r["class"])
    return L


def _by_id(ed: str):
    """greek id -> (edition verse, [position strings "w" or "w.p"])"""
    out = {}
    for f in sorted(BY_ID[ed].glob("*_*.json")):
        if f.name.endswith(".meta.json"):
            continue
        b = f.name.split("_")[0]
        for cv, e in json.loads(f.read_text(encoding="utf-8")).items():
            if ":" not in cv:
                continue
            c, v = map(int, cv.split(":"))
            for pos, gids, _ in e["links"]:
                for g in gids:
                    out[g] = ((b, c, v), [str(x) for x in pos])
    return out


def _before_content(key: str) -> str | None:
    W, SEQ, span, parent = A._greek()
    seq, cls, par, _ = W[key]
    lo, hi = span.get(par, (seq, seq))
    for s in range(seq - 1, lo - 1, -1):
        k, c = SEQ.get(s, (None, None))
        if c in {"noun", "adj", "verb", "num"}:
            return k
    return None


def _clause_verb(key: str) -> str | None:
    W, SEQ, span, parent = A._greek()
    seq, cls, par, _ = W[key]
    p = par
    for _ in range(4):
        lo, hi = span.get(p, (seq, seq))
        for s in range(lo, hi + 1):
            k, c = SEQ.get(s, (None, None))
            if c == "verb":
                return k
        p = parent.get(p)
    return None


def _prep_link(link, verse, vkey, L) -> set[str]:
    out = set()
    for x in link:
        w, p = (int(x), None) if "." not in x else map(int, x.split("."))
        ps = sorted(verse.get(w, []))
        if p is None:
            run = []
            for q, k in ps:
                if k in ("prep", "om"):
                    run.append(q)
                elif run or k not in ("cj",):
                    break
            got = run or [ps[0][0] if ps else 0]
        else:
            got = [p] + [q for q, k in ps if q > p and k in ("prep", "om") and all(kk in ("prep", "om") for qq, kk in ps if p < qq < q)]
        out |= {f"{w}.{q}" for q in got}
        rest = [q for q, k in ps if q > max(got)]
        if rest and L.get((*vkey, w, rest[0]), ("", ""))[0] == "6440":
            out.add(f"{w}.{rest[0]}")
        if got and max(got) == (ps[-1][0] if ps else 0):
            nxt = sorted(verse.get(w + 1, []))
            if nxt and L.get((*vkey, w + 1, nxt[0][0]), ("", ""))[0] in PREP_NOUNS and L[(*vkey, w + 1, nxt[0][0])][1] == "noun":
                out.add(f"{w + 1}.{nxt[0][0]}")
    return out


def decide(cls: str, key: str, link: list[str], verse: dict, vkey: tuple, rec: dict, L: dict) -> tuple[set[str], str]:
    """The rule for one Greek word (key without the "n"); returns position strings and what decided them."""
    parts = lambda w, fam: [f"{w}.{p}" for p, k in sorted(verse.get(w, [])) if k in fam]

    def resolve(x):
        if "." in x:
            return x
        ps = parts(int(x), FAM[cls] | ({"pron"} if cls == "prep" else set()))
        if cls == "pron":
            ps = [p for p in ps if int(p.split(".")[1]) > 0] or ps
        return ps[0] if ps else x
    a = set(link)
    anc = (_before_content(key) or _clause_verb(key)) if cls == "pron" else A.head(key)
    hw = A._head_word(rec.get("n" + anc)) if anc else None
    rule = None
    if hw is not None:
        first = sorted(verse.get(hw, []))
        if cls == "prep":
            pre = [f"{hw}.{p}" for p, k in first if k == "prep" and p < max([q for q, kk in first if kk not in ("prep", "cj", "art")] or [0])]
            prev = parts(hw - 1, {"prep", "om"}) if hw > 1 else []
            rule = set(pre[:1]) or (set(prev[:1]) if prev and len(verse.get(hw - 1, [])) == 1 else set())
        elif cls == "pron":
            suf = [x for x in parts(hw, {"pron"}) if int(x.split(".")[1]) > 0]
            rule = set(suf[-1:]) if suf else None
        else:
            prev = parts(hw - 1, {"cj"}) if hw > 1 else []
            rule = {f"{hw}.0"} if first and first[0][1] == "cj" else (set(prev[:1]) if prev else None)
    if cls == "prep":
        return (_prep_link(a, verse, vkey, L), "aligner") if a else (rule or set(), "rule" if rule else "none")
    if rule is not None:
        return rule, "rule"
    return {resolve(x) for x in a}, ("aligner" if a else "none")


def _parse(xs: set[str]) -> list[tuple[int, int | None]]:
    return sorted(((int(x), None) if "." not in x else tuple(map(int, x.split(".")))) for x in xs)


def links(ed: str) -> dict:
    """Every Greek preposition, pronoun and conjunction of the NT."""
    W, *_ = A._greek()
    H = A._hebrew(ed)
    rec = A._records(ed)
    L = _lemmas(ed)
    byid = _by_id(ed)
    verse_of = {}                                    # a Greek verse -> the edition verse its links mostly lie in
    vc = collections.defaultdict(collections.Counter)
    for g, (hv, _) in byid.items():
        if g[1:] in W:
            vc[W[g[1:]][3]][hv] += 1
    for gv, c in vc.items():
        verse_of[gv] = c.most_common(1)[0][0]
    out = {}
    for key, (seq, cls, par, ref) in W.items():
        if cls not in CLASSES:
            continue
        gid = "n" + key
        hv, link = byid.get(gid, (verse_of.get(ref, ref), []))
        hv = tuple(hv)
        got, by = decide(cls, key, link, H.get(hv, {}), hv, rec, L)
        out[gid] = {"cls": cls, "verse": hv, "parts": _parse(got), "by": by}
    return out


def check() -> None:
    import csv
    W2 = A.ROOT / "internal-docs" / "clause-structure-work"
    for ed in ("heb_scg", "heb_mod"):
        H = A._hebrew(ed); rec = A._records(ed); L = _lemmas(ed)
        items = json.load(open(W2 / "s1c-judge-2026-11-19" / "score" / ed / "items.json"))["items"]
        judged = {r["item"]: r for r in csv.DictReader(open(W2 / "s1c-judge-2026-11-19" / "score" / ed / "judgments.tsv",
                                                            encoding="utf-8"), delimiter="\t")}
        c = collections.Counter()
        for i in items:
            if i["cls"] not in CLASSES:
                continue
            j = judged[i["item"]]["rendering"].strip()
            gold = set() if j in ("-", "") else {x.strip() for x in j.split(",")}
            hv = tuple(i["hebrew_verse"])
            got, _ = decide(i["cls"], i["gid"][1:], i["link"], H[hv], hv, rec, L)
            c[i["cls"], "n"] += 1
            c[i["cls"], "right"] += got == gold
        print(ed, {k: f"{c[k, 'right']}/{c[k, 'n']} = {c[k, 'right'] / c[k, 'n']:.3f}" for k in CLASSES})


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    if ap.parse_args().check:
        check()
