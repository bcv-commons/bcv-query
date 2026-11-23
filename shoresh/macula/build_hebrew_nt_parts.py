"""Hebrew New Testament parts, level 2 (the id standard of 2026-11-23, D4): the Tanakh's inflection cut (word-parts v1.1,
macula.build_hebrew_parts) inside hebrew-nt-analysis v0.2's level-1 parts of Salkinson-Ginsburg and Delitzsch. Local,
unpublished.

    cd shoresh && .venv/bin/python -m macula.build_hebrew_nt_parts plan   --edition heb_scg|heb_mod
    cd shoresh && .venv/bin/python -m macula.build_hebrew_nt_parts ask    --edition ... [--max-usd N]   (Jev; key in env)
    cd shoresh && .venv/bin/python -m macula.build_hebrew_nt_parts finish --edition ... --ids DIR

Two routes, per level-1 part:
  tanakh   the part's form occurs in the Tanakh as a MACULA part (Salkinson: the form without cantillation; Delitzsch, which
           bibles gives unpointed: its consonants), and at least 90% of those Tanakh parts have one level-2 cut: the part
           takes that cut, letter for letter (the same consonant counts per piece, kinds and features).
  jev      otherwise, for a noun, verb or adjective part: Jev (TypeSafe System One) is asked, one request per verse, the
           gender, number and state of the part and whether it is a proper name; with hebrew-nt-analysis' verb form and
           person this makes a MACULA morph code, and build_hebrew_parts.cut() (the Tanakh's own tables) cuts the part. The
           lemma is MACULA's lemma of the part's Strong's number, else the part itself. A proper name is not cut, as in the
           Tanakh. These pieces are a model's parse (basis `jev`), not MACULA's.
  whole    anything else (particles, pronouns, numerals, verse numbers; parts with no Tanakh form outside the jev
           classes): sub-part 1, not cut.
Ids: the part id of build_text_ids (`scg:BBCCCVVVWWWP`) + one sub-part digit, numbered from the left, as in the Tanakh.

Writes data/hebrew-nt-parts/<edition>/{jev_items.jsonl, jev_answers.jsonl}, and with finish DIR/<text>/parts2.tsv,
checks.md. Nothing is sent but the Hebrew New Testament text (public domain): no English, no other text.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import re
import sys
import time
import unicodedata as ud
import urllib.request
from pathlib import Path

import pyarrow.parquet as pq

from macula import build_hebrew_parts as hp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ANALYSIS = HERE / "data" / "bridge-corpus" / "inputs" / "hebrew-nt-analysis@v0.2"
TANAKH_L2 = ROOT / "internal-docs" / "word-parts-release" / "v1.1" / "hebrew" / "parts.tsv"
ROOTS = ROOT / "resources" / "bdb_roots" / "root_groups.tsv"
OUT = HERE / "data" / "hebrew-nt-parts"
TEXT = {"heb_scg": "scg", "heb_mod": "del"}
JEV_CLASSES = {"noun", "verb", "adj"}
SHARE = 0.9
CANT = re.compile("[֑-ֽ֯׀׃׆׳״]")
TYPE = {"qatal": "p", "weqatal": "q", "yiqtol": "i", "wayyiqtol": "w", "jussive": "j", "cohortative": "h", "imperative": "v",
        "participle active": "r", "participle passive": "s", "infinitive construct": "c", "infinitive absolute": "a"}
PERSON = {"first": "1", "second": "2", "third": "3"}
csv.field_size_limit(sys.maxsize)


def key(ed, s):
    s = CANT.sub("", ud.normalize("NFC", s or "")).replace("־", "")
    return hp.skel(s) if ed == "heb_mod" else s


def tanakh(ed):
    """{form key: Counter(pattern)}; pattern = ((consonants, kind, features), ...) of the MACULA part's level-2 pieces"""
    by = collections.defaultdict(list)
    with open(TANAKH_L2, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            by[r["macula_id"]].append((int(r["n"]), r["text"], r["kind"], r["features"]))
    out = collections.defaultdict(collections.Counter)
    for ps in by.values():
        ps.sort()
        pat = tuple((len(hp.skel(t)), k, ft) for _, t, k, ft in ps)
        out[key(ed, "".join(t for _, t, _, _ in ps))][pat if len(ps) > 1 else "whole"] += 1
    return out


def apply(text, pat):
    """the part's letters cut at the pattern's consonant counts, or None when they do not fit"""
    gs = hp.letters(text)
    out, i = [], 0
    for n, kind, ft in pat:
        j, c = i, 0
        while j < len(gs) and c < n:
            c += 1 if hp.cons(gs[j]) else 0
            j += 1
        while j < len(gs) and not hp.cons(gs[j]):
            j += 1
        if c < n:
            return None
        out.append((kind, "".join(gs[i:j]), ft)); i = j
    return out if i == len(gs) and all(p[1] for p in out) else None


def rows(ed):
    t = pq.read_table(ANALYSIS / ed / "words.parquet").to_pylist()
    t.sort(key=lambda r: (r["book"], r["chapter"], r["verse"], r["i"], r["part"]))
    return t


def plan(ed):
    T = tanakh(ed)
    items, cnt = collections.OrderedDict(), collections.Counter()
    verse_words = collections.defaultdict(dict)
    for r in rows(ed):
        verse_words[(r["book"], r["chapter"], r["verse"])][r["i"]] = r["word"]
    for r in rows(ed):
        if r["class"] == "verse-number":
            continue
        c = T.get(key(ed, r["text"]))
        if c and c.most_common(1)[0][1] / sum(c.values()) >= SHARE:
            cnt["tanakh"] += 1; continue
        if r["class"] not in JEV_CLASSES:
            cnt["whole"] += 1; continue
        cnt["jev"] += 1
        v = (r["book"], r["chapter"], r["verse"])
        it = items.setdefault(v, {"id": f"{ed}:{v[0]} {v[1]}:{v[2]}", "verse": " ".join(w for _, w in sorted(verse_words[v].items())),
                                  "parts": {}})
        it["parts"][f"p{r['i']}_{r['part']}"] = {"word": r["word"], "part": r["text"], "class": r["class"],
                                                 "form": r["form"] or "", "person": r["person"] or ""}
    return list(items.values()), cnt


def ask_one(item, model):
    qs = {}
    for k, p in item["parts"].items():
        what = f"the part {p['part']} of the word {p['word']} ({p['class']}{', ' + p['form'] if p['form'] else ''})"
        qs[f"{k}.name"] = {"type": "choice", "criteria": {"name": "a proper name (a person, people or place)", "common": "not a name"},
                           "instructions": f"In this verse, is {what} a proper name?"}
        qs[f"{k}.gender"] = {"type": "choice", "criteria": {"m": "masculine", "f": "feminine", "c": "common (both)", "none": "no gender"},
                             "instructions": f"The grammatical gender of {what} in this verse, as the Hebrew grammars parse it."}
        qs[f"{k}.number"] = {"type": "choice", "criteria": {"s": "singular", "p": "plural", "d": "dual", "none": "no number"},
                             "instructions": f"The grammatical number of {what} in this verse."}
        if p["class"] != "verb" or p["form"].startswith("participle"):
            qs[f"{k}.state"] = {"type": "choice", "criteria": {"a": "absolute", "c": "construct"},
                                "instructions": f"The state of {what} in this verse: construct (bound to the following word) or absolute."}
    body = json.dumps({"model": model, "state": {"hebrew_verse": item["verse"]}, "questions": qs}).encode("utf-8")
    req = urllib.request.Request("https://api.typesafe.ai/v1/systemone", data=body, method="POST",
                                 headers={"Authorization": "Bearer " + os.environ["TYPESAFE_API_KEY"], "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                raise
            print("retry", attempt, e, file=sys.stderr)
            time.sleep(2 * (attempt + 1))


def cmd_ask(out, max_usd, model, price_in, price_out):
    items = [json.loads(l) for l in (out / "jev_items.jsonl").read_text(encoding="utf-8").splitlines()]
    ans_p = out / "jev_answers.jsonl"
    done = {json.loads(l)["id"] for l in ans_p.read_text(encoding="utf-8").splitlines()} if ans_p.exists() else set()
    spent, n, usage = 0.0, 0, collections.Counter()
    with open(ans_p, "a", encoding="utf-8") as f:
        for it in items:
            if it["id"] in done:
                continue
            if spent >= max_usd:
                print(f"stopped at the cap: USD {spent:.2f}"); break
            r = ask_one(it, model)
            u = r.get("usage", {}); usage.update({k: v for k, v in u.items() if isinstance(v, (int, float))})
            spent += u.get("input_tokens", 0) / 1e6 * price_in + u.get("output_tokens", 0) / 1e6 * price_out
            f.write(json.dumps({"id": it["id"], "model": r.get("model"),
                                "answers": {q: {"choice": a.get("choice"), "probabilities": a.get("probabilities")}
                                            for q, a in r["answers"].items()}}, ensure_ascii=False) + "\n")
            n += 1
            if n % 100 == 0:
                f.flush(); print(n, f"USD {spent:.2f}", dict(usage), file=sys.stderr)
    print(f"asked {n}, USD {spent:.2f} at the stated price, usage {dict(usage)}")


def morph(p, a):
    g = {"m": "m", "f": "f", "c": "c"}.get(a.get("gender"), "")
    n = {"s": "s", "p": "p", "d": "d"}.get(a.get("number"), "")
    s = a.get("state", "a")
    if p["class"] == "verb":
        t = TYPE.get(p["form"], "")
        if t in ("r", "s"):
            return f"Vx{t}{g}{n}{s}" if g and n else ""
        if t in "pqiwjhv" and t:
            per = PERSON.get(p["person"], "2" if t == "v" else "")
            # MACULA's paradigm has common gender in the 1st person, and in the qatal's 3rd plural (3cp); Jev answers m/f
            if g and (per == "1" or (t in "pq" and per == "3" and n == "p")):
                g = "c"
            return f"Vx{t}{per}{g}{n}" if per and g and n else ""
        return f"Vx{t}" if t else ""
    if not (g and n):
        return ""
    return ("Nc" if p["class"] == "noun" else "Aa") + g + n + s


def cmd_finish(ed, out, ids):
    T = tanakh(ed)
    strongs, strong_lemma = hp.read_strongs(hp.LOWFAT)
    roots = hp.read_roots(ROOTS, strong_lemma)
    ans = {}
    p_ans = out / "jev_answers.jsonl"
    for l in (p_ans.read_text(encoding="utf-8").splitlines() if p_ans.exists() else []):
        j = json.loads(l)
        for q, a in j["answers"].items():
            k, f = q.split(".")
            ans.setdefault((j["id"], k), {})[f] = a["choice"]
    text = TEXT[ed]
    from macula.build_text_ids import NUMBER
    res, cnt = [], collections.Counter()
    for r in rows(ed):
        pid = f"{text}:{NUMBER[r['book']]:02d}{r['chapter']:03d}{r['verse']:03d}{r['i'] + 1:03d}{r['part'] + 1}"
        pieces, basis = None, ("verse_number" if r["class"] == "verse-number" else "whole")
        c = T.get(key(ed, r["text"])) if r["class"] != "verse-number" else None
        if c and c.most_common(1)[0][1] / sum(c.values()) >= SHARE:
            pat = c.most_common(1)[0][0]
            basis = "tanakh"
            if pat != "whole":
                pieces = apply(r["text"], pat)
                if pieces is None:
                    basis = "tanakh_unfit"
        elif r["class"] in JEV_CLASSES:
            a = ans.get((f"{ed}:{r['book']} {r['chapter']}:{r['verse']}", f"p{r['i']}_{r['part']}"))
            if a is None:
                basis = "jev_unasked"
            elif a.get("name") == "name":
                basis = "jev_name"
            else:
                m = morph({"class": r["class"], "form": r["form"] or "", "person": r["person"] or ""}, a)
                sk = hp.strong_key(r["strong"])
                lemma = strong_lemma.get(sk) or r["text"]
                basis = "jev" if m else "jev_no_parse"
                if m:
                    pieces = hp.cut(r["text"], m, lemma, roots.get(sk))
                    if pieces and len(pieces) == 1 and pieces[0][0] == "fused" and lemma == r["text"]:
                        # no lemma known, and the form taken as its own lemma makes the ending look like a root letter
                        # (דָחֲפוּ): cut without a lemma
                        pieces = hp.cut(r["text"], m, "", roots.get(sk))
                    if not pieces and m[-1:] in ("a", "c") and (m[:2] in ("Nc", "Aa") or m[2:3] in ("r", "s")):
                        # the written ending decides the state when Jev's state finds none (פְקִידִים said construct)
                        pieces = hp.cut(r["text"], m[:-1] + ("c" if m[-1] == "a" else "a"), lemma, roots.get(sk))
                    if pieces and pieces[-1][0] == "ending" and hp.skel(pieces[-1][1]) in ("ה", "ת") and c:
                        # the Tanakh has this form but cuts it more than one way (so it came to Jev): if most of its
                        # occurrences keep the last ה/ת in the stem (אוֹת, רָעָה), so does this one
                        cut_end = sum(n for pat, n in c.items() if pat != "whole" and pat[-1][1] == "ending" and pat[-1][0] == 1)
                        if cut_end <= 0.5 * sum(c.values()):     # a tie keeps it whole (MACULA cuts אוֹת in 40 of 80)
                            pieces = None
                    if pieces and pieces[-1][0] == "ending" and hp.skel(pieces[-1][1]) in ("ם", "מ") and pieces[-1][2][4:5] == "p":
                        # a bare ם after a noun is the pronoun "them" (כֻּלָּם, כֹּחָם), not a plural ending (that is ים)
                        pieces = None
                    if hp.skel(r["text"]) == "אפתח" and (r["book"], r["chapter"], r["verse"]) == ("MRK", 7, 34):
                        pieces = None   # ephphatha: the Aramaic word written out, not a 1st-person Hebrew verb
        cnt[basis + (" (cut)" if pieces else "")] += 1
        pieces = pieces or [("whole", r["text"], "")]
        start = 0
        for n, (kind, t, ft) in enumerate(pieces, 1):
            ln = len(hp.letters(t))
            res.append((f"{pid}{n}", pid, n, start, start + ln, t, kind, ft, basis))
            start += ln
    d = ids / text
    with open(d / "parts2.tsv", "w", encoding="utf-8") as f:
        f.write("part2_id\tpart_id\tn\tstart\tend\ttext\tkind\tfeatures\tbasis\n")
        f.writelines("\t".join(map(str, x)) + "\n" for x in res)
    dup = len(res) - len({x[0] for x in res})
    L = [f"# {text} level 2: checks", "", f"level-1 parts: {sum(cnt.values()):,}; level-2 pieces: {len(res):,}; duplicate ids: {dup}", ""]
    L += [f"- {k}: {v:,} ({v / sum(cnt.values()):.1%})" for k, v in sorted(cnt.items())]
    (d / "checks2.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("plan", "ask", "finish"))
    ap.add_argument("--edition", required=True, choices=sorted(TEXT))
    ap.add_argument("--ids", type=Path, help="build_text_ids' folder (finish writes <text>/parts2.tsv there)")
    ap.add_argument("--max-usd", type=float, default=2.0)
    ap.add_argument("--model", default="jev-latest")
    ap.add_argument("--price-in", type=float, default=0.04)
    ap.add_argument("--price-out", type=float, default=0.15)
    a = ap.parse_args()
    out = OUT / a.edition
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "plan":
        items, cnt = plan(a.edition)
        (out / "jev_items.jsonl").write_text("".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items), encoding="utf-8")
        print(dict(cnt), f"{len(items)} verses, {sum(len(i['parts']) for i in items)} parts for Jev -> {out}")
    elif a.cmd == "ask":
        cmd_ask(out, a.max_usd, a.model, a.price_in, a.price_out)
    else:
        cmd_finish(a.edition, out, a.ids)


if __name__ == "__main__":
    main()
