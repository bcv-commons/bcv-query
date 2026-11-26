"""Person, number, gender, state, definiteness and verb stem for every word part of the Hebrew New Testaments (request 39,
rows 1-2; request 40, row 2).

`hebrew_nt_morph.py` takes the morphology MACULA Hebrew gives a whole Tanakh form (or one Tanakh part). Where a Hebrew NT
form is not a Tanakh form, or is ambiguous there, it leaves the part empty. This step fills those parts by rule from the
Hebrew form itself, with no model: the affix tables below are counted on the MACULA Hebrew Tanakh (the written ending of
the part, its prefix letter, the host of a pronoun suffix, the article and suffix in the word, the verb's form and person
as the analysis gives them), and a value is taken from the most specific key that has at least `--min` Tanakh cases of
which at least `--share` agree. Each feature is decided on its own, so a verb may get its number when its gender is not
sure. Salkinson's text is pointed and is matched with its points; Delitzsch's edition here is unpointed and is matched on
consonants (the tables are then counted on consonants too).

`stem` (the binyan, MACULA's strings: qal, niphal, piel, ...) is decided for verbs the same way; before the other verb
keys come keys on the verb's lexeme (Strong's number) with its form, its written beginning and ending, since the stem is
mostly the lexeme's and is marked at the start of the word (request 40, row 2).

`definite` is a rule over the word's parts, not a table: `article` (an article part stands before the noun or adjective in
its word, also the article hidden after a preposition, which the analysis keeps as an empty part), `suffix` (a pronoun
suffix follows it), `name` (a proper noun, i.e. a noun part whose Strong's number is a Tanakh proper noun), else empty.

  cd shoresh && .venv/bin/python -I macula/hebrew_nt_features.py --analysis DIR --morph DIR --out OUT [--share 0.9 --min 20]

DIR (analysis) is a hebrew-nt-analysis folder (<edition>/words.parquet, manifest.json); DIR (morph) is a
`hebrew_nt_morph.py` output. Writes OUT/<edition>/features.parquet, one row per word part on the analysis's keys
(book, chapter, verse, i, part): person, number, gender, state, definite, and for each of the five a `<feature>_basis`:
`form`, `form_model`, `part`, `part_model` (as in morph.parquet: a Tanakh lookup of the word or the part), `affix` (this
step's tables, on a part MACULA's own lexicon gave the analysis), `affix_model` (the same on a part whose class and lemma
are the tagger's), `rule` (definite), or empty. `rule_key` says which table key decided (for `affix*`). Values are MACULA's
strings (third, singular, masculine, construct, ...). And OUT/build.json with the counts and the hold-out check: the
tables applied to the parts that the Tanakh lookup did fill, against that lookup's values.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sqlite3
import sys
import unicodedata
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyarrow as pa
import pyarrow.parquet as pq

from macula.clause_tagger import pointed, unpointed

HERE = Path(__file__).resolve().parent
FEATS = ("person", "number", "gender", "state", "stem")
TARGET = {"verb": ("person", "number", "gender", "stem"), "noun": ("number", "gender", "state"),
          "adj": ("number", "gender", "state"), "num": ("number", "gender", "state"),
          "pron": ("person", "number", "gender")}
ONLY = {"nlex": "gender", "nc": "state", "nf": "state", "vsl": "stem", "vsb": "stem"}                  # keys that decide one feature only
HOSTS = {"noun", "verb", "prep", "om", "adj", "num", "adv", "ptcl", "ij", "cj", "rel"}


def _nfc(s):
    return unicodedata.normalize("NFC", s or "")


def keys(cls, form, person, text, host, sfx_after, art_before, plain, strong="", nxt=""):
    """the table keys of one part, most specific first; text and host already normalised"""
    if not text:
        return []
    out = []
    if cls == "pron" and host is not None:                         # a pronoun suffix
        for L in (2, 1):
            out.append(("sfx", text, host[-L:] if host else ""))
        out.append(("sfx", text))
        cons = unpointed((host or "") + text)                     # a suffix cut at another letter: its consonants
        for L in (3, 2):
            if len(cons) >= L:
                out.append(("sfxc", cons[-L:]))
        return out
    if cls == "pron":
        return [("pron", text)]
    if cls == "verb":
        pre = text[:1]
        beg = text[:2] if plain else text[:4]                  # the first letters (with their points where read)
        if strong:                                             # stem keys: the lexeme, its form, beginning and ending
            for L in (2, 1):
                out.append(("vsl", strong, form or "", beg, text[-L:]))
            out.append(("vsl", strong, form or "", beg))
            out.append(("vsl", strong, form or ""))
            out.append(("vsl", strong))
        for L in (2, 1):                                       # without the lexeme
            out.append(("vsb", form or "", beg, text[-L:]))
        for p in ([person, "*"] if person else ["*"]):        # "*": any person (a verb the analysis gives none)
            for L in (4, 3, 2, 1):
                out.append(("vpe", form or "", p, pre, text[-L:]))   # prefix letter and ending
            for L in (3, 2, 1):
                out.append(("ve", form or "", p, text[-L:]))         # ending
            out.append(("vp", form or "", p, pre))                   # prefix letter only
            out.append(("v", form or "", p))
        return out
    if cls in ("noun", "adj", "num"):
        if cls == "noun" and strong:
            out.append(("nlex", strong))                       # a noun's gender is the lexeme's (used for gender only)
        out.append(("nf", cls, text, sfx_after, art_before, nxt))   # the written form and the next word (state only)
        for L in (4, 3, 2, 1):                                 # the next word's first part (used for state only)
            out.append(("nc", cls, sfx_after, art_before, nxt, text[-L:]))
        for L in (4, 3, 2, 1):
            out.append(("n", cls, sfx_after, art_before, text[-L:]))
        out.append(("n", cls, sfx_after, art_before))
        return out
    return []


def word_context(parts, norm):
    """per part: (text, host, sfx_after, art_before), parts in order; host = the previous part's text for a pronoun
    that follows another part of the word (a suffix), else None"""
    ctx = []
    for j, (cls, text) in enumerate(parts):
        host = None
        if cls == "pron" and j > 0 and parts[j - 1][0] in HOSTS:
            host = norm(parts[j - 1][1])
        sfx_after = any(c == "pron" for c, _ in parts[j + 1:]) and j + 1 < len(parts) and parts[j + 1][0] == "pron"
        art_before = any(c == "art" for c, _ in parts[:j])
        ctx.append((norm(text), host, sfx_after, art_before))
    return ctx


def tanakh_tables(plain):
    norm = unpointed if plain else pointed
    spine = sqlite3.connect(HERE / "macula-spine.db")
    morph = {k: dict(zip(FEATS, (v or "" for v in rest))) for k, *rest in
             spine.execute("select key, person, number, gender, state, stem from macula_words where lang = 'hbo'")}
    tables = {f: collections.defaultdict(collections.Counter) for f in FEATS}
    both = collections.defaultdict(collections.Counter)
    words = collections.OrderedDict()
    for b, ch, v, w, s, key, cls, wtype, strong in sqlite3.connect(HERE / "trees-macula.db").execute(
            "select book, chapter, verse, word, surface, key, class, wtype, strong from words where corpus = 'hbo' "
            "order by book, chapter, verse, word, part"):
        words.setdefault((b, ch, v, w), []).append((cls or "-", s or "", key, wtype, strong or ""))
    wl = list(words.items())
    for wi, (wk, parts) in enumerate(wl):
        nxt = wl[wi + 1][1][0][0] if wi + 1 < len(wl) and wl[wi + 1][0][:3] == wk[:3] else ""
        ctx = word_context([(c, s) for c, s, _, _, _ in parts], norm)
        for (cls, s, key, wtype, strong), (text, host, sa, ab) in zip(parts, ctx):
            if cls not in TARGET:
                continue
            m = morph.get(key, {})
            form = wtype if cls == "verb" else ""
            if cls in ("noun", "adj") and m.get("state") in ("absolute", "construct") and not ab and not sa:
                both[(cls, text)][m["state"]] += 1
            for k in keys(cls, form, m.get("person", "") if cls == "verb" else "", text, host, sa, ab, plain, strong, nxt):
                for f in TARGET[cls]:
                    if ONLY.get(k[0], f) != f:
                        continue
                    tables[f][k][m.get(f, "")] += 1
    tables["both"] = {k for k, c in both.items() if len(c) == 2 and min(c.values()) >= 3
                      and min(c.values()) / sum(c.values()) >= 0.05}
    return tables


def decide(tables, f, ks, share, mn):
    for k in ks:
        c = tables[f].get(k)
        if not c:
            continue
        tot = sum(c.values())
        if tot < mn:
            continue
        val, n = c.most_common(1)[0]
        if n / tot >= share:
            return val, k, round(n / tot, 3), tot
        return None                                     # the most specific key with enough cases disagrees: no value
    return None


def overrides(k):
    """may this table key replace the analysis's person? prefix + ending (for a qatal or weqatal an ending of at least
    3 written characters); an ending alone only in a qatal or weqatal; never a prefix alone (research's Swahili
    check, 2026-11-26)"""
    if k[0] == "vpe":
        return k[1] not in ("qatal", "weqatal") or len(k[-1]) >= 3
    if k[0] == "ve":                                    # an ending alone: only where the person is in the ending
        return k[1] in ("qatal", "weqatal") and len(k[-1]) >= 3
    return False


def share_of(tables, f, ks, val, mn):
    """the share of `val` at the most specific key with at least mn cases, or None"""
    for k in ks:
        c = tables[f].get(k)
        if c and sum(c.values()) >= mn:
            return c[val] / sum(c.values())
    return None


PERSON = {"first": "first", "second": "second", "third": "third"}


def run(analysis, morph_dir, out, share, mn):
    build = {"share": share, "min": mn, "analysis": str(analysis.name), "morph": str(morph_dir.name), "editions": {}}
    proper = {s for s, in sqlite3.connect(HERE / "trees-macula.db").execute(
        "select distinct strong from words where corpus = 'hbo' and wtype = 'proper'") if s}
    for ed_dir in sorted(p for p in analysis.iterdir() if (p / "words.parquet").exists()):
        ed = ed_dir.name
        manifest = json.loads((ed_dir / "manifest.json").read_text())
        plain = manifest["model"].get("vowel_points", "read") == "stripped"
        norm = unpointed if plain else pointed
        tables = tanakh_tables(plain)
        mrows = {(r["book"], r["chapter"], r["verse"], r["i"], r["part"]): r
                 for r in pq.read_table(morph_dir / ed / "morph.parquet").to_pylist()}
        words = collections.OrderedDict()
        for r in pq.read_table(ed_dir / "words.parquet").to_pylist():
            if r["source"] is None:
                continue
            words.setdefault((r["book"], r["chapter"], r["verse"], r["i"]), []).append(r)
        rows, n = [], collections.Counter()
        check = collections.defaultdict(collections.Counter)
        wl = list(words.items())
        for wi, ((b, ch, v, i), parts) in enumerate(wl):
            parts.sort(key=lambda r: r["part"])
            nxt = ""
            if wi + 1 < len(wl) and wl[wi + 1][0][:3] == (b, ch, v):
                nxt = min(wl[wi + 1][1], key=lambda r: r["part"])["class"] or "-"
            ctx = word_context([(r["class"] or "-", r["text"] or "") for r in parts], norm)
            for j, (r, (text, host, sa, ab)) in enumerate(zip(parts, ctx)):
                cls = r["class"] or "-"
                m = mrows.get((b, ch, v, i, r["part"]), {})
                row = {"book": b, "chapter": ch, "verse": v, "i": i, "part": r["part"], "rule_key": ""}
                person = PERSON.get(r["person"] or "", "") if cls == "verb" else ""
                person_by = ""
                if cls == "verb":                               # the person the prefix and ending allow, not the tagger's
                    star = keys(cls, r["form"] or "", "", text, host, sa, ab, plain)
                    dp = decide(tables, "person", star, share, mn) if star else None
                    if dp is not None and dp[0] and dp[0] != person and person and not overrides(dp[1]):
                        n["verb_person_kept"] += 1                 # a key without the person ending does not override
                    elif dp is not None and dp[0] and dp[0] != person:
                        n["verb_person_" + ("corrected" if person else "added")] += 1
                        person, person_by = dp[0], "person:" + "|".join(map(str, dp[1]))
                    elif person and dp is None and star:
                        sh = share_of(tables, "person", star, person, mn)
                        if sh is not None and sh < 0.02:        # the form never has this person in the Tanakh
                            n["verb_person_dropped"] += 1
                            person, person_by = "", "dropped"
                ks = keys(cls, r["form"] if cls == "verb" else "", person, text, host, sa, ab, plain, r["strong"] or "", nxt) if cls in TARGET else []
                for f in FEATS:
                    val, basis = (m.get(f) or ""), (m.get("basis") or "") if m.get(f) else ""
                    if cls == "verb" and f == "person":         # decided above, never from a person-keyed table
                        if val and dp is not None and dp[0]:
                            check[("verb", "person")]["agree" if dp[0] == val else "differ"] += 1
                        if not val and person:
                            if person_by and person_by != "dropped":
                                val, basis = person, "affix" if r["source"] == "macula" else "affix_model"
                                row["rule_key"] = person_by
                            else:
                                val, basis = person, "form" if r["source"] == "macula" else "form_model"
                        row[f], row[f + "_basis"] = val, basis
                        n[f"{cls}_{f}_{'has' if val else 'none'}"] += 1
                        continue
                    if cls in TARGET and f in TARGET[cls]:
                        fk = [k for k in ks if ONLY.get(k[0], f) == f]
                        d = decide(tables, f, fk, share, mn) if fk else None
                        if val and d is not None:                       # hold-out: the tables against the lookup
                            check[(cls, f)]["agree" if d[0] == val else "differ"] += 1
                        if not val and d is not None and d[0]:
                            val, basis = d[0], "affix" if r["source"] == "macula" else "affix_model"
                            row["rule_key"] = (row["rule_key"] + " " if row["rule_key"] else "") + f + ":" + "|".join(map(str, d[1]))
                            n[f"filled_{cls}_{f}"] += 1
                    row[f], row[f + "_basis"] = val, basis
                    if cls in TARGET and f in TARGET[cls]:
                        n[f"{cls}_{f}_{'has' if val else 'none'}"] += 1
                definite = ""
                if cls in ("noun", "adj", "num"):
                    if ab:
                        definite = "article"
                    elif sa:
                        definite = "suffix"
                    elif cls == "noun" and r["strong"] in proper:
                        definite = "name"
                row["definite"], row["definite_basis"] = definite, "rule" if definite else ""
                row["state_both"] = cls in ("noun", "adj") and not ab and not sa and (cls, text) in tables["both"]
                if row["state_both"]:
                    n["state_both"] += 1
                    d = decide(tables, "state", [k for k in ks if k[0] == "nf"], share, mn)
                    if d is not None and d[0] and d[0] != row["state"]:
                        n[f"state_by_context_{'over' if row['state'] else 'fill'}"] += 1
                        row["state"], row["state_basis"] = d[0], "affix" if r["source"] == "macula" else "affix_model"
                        row["rule_key"] = (row["rule_key"] + " " if row["rule_key"] else "") + "state:" + "|".join(map(str, d[1]))
                if definite:
                    n[f"definite_{definite}"] += 1
                rows.append(row)
        cols = [("book", pa.string()), ("chapter", pa.int16()), ("verse", pa.int16()), ("i", pa.int16()), ("part", pa.int8())]
        for f in FEATS + ("definite",):
            cols += [(f, pa.string()), (f + "_basis", pa.string())]
        cols += [("state_both", pa.bool_()), ("rule_key", pa.string())]
        (out / ed).mkdir(parents=True, exist_ok=True)
        fp = out / ed / "features.parquet"
        pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema(cols)), fp, compression="zstd")
        hold = {f"{c}.{f}": {**dict(v), "agree_share": round(v["agree"] / max(1, v["agree"] + v["differ"]), 4)}
                for (c, f), v in sorted(check.items())}
        build["editions"][ed] = {"matched_on": "consonants" if plain else "pointed form", "rows": len(rows),
                                 "counts": dict(sorted(n.items())), "holdout": hold,
                                 "sha256": hashlib.sha256(fp.read_bytes()).hexdigest()}
        print(f"[hebrew_nt_features] {ed}: rows {len(rows)}; holdout " +
              ", ".join(f"{k} {v['agree_share']}" for k, v in hold.items()))
    (out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--analysis", type=Path, required=True)
    ap.add_argument("--morph", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--share", type=float, default=0.9)
    ap.add_argument("--min", type=int, default=20)
    a = ap.parse_args()
    run(a.analysis, a.morph, a.out, a.share, a.min)


if __name__ == "__main__":
    main()
