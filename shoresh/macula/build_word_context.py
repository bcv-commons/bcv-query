#!/usr/bin/env python3
"""A context key per content word, finer than its UBS sense (wave 2; research's word-choice breakdown 2026-11-13: about 0.38 of the
wrong content words are a choice inside one lexeme that UBS senses do not separate).

    cd shoresh && .venv/bin/python3 -m macula.build_word_context      (after build_arg_roles)

One row per noun, verb and adjective of the Hebrew Bible and the Greek NT:
  corpus, key, lemma (Strong's for Hebrew, lemma for Greek), sense (the UBS sense from word-senses-ubs, '' when none)
  lxx            Hebrew only: the Septuagint lemma MACULA aligns to the word (GLAUx lemma; '' when none)
  colloc_kind    for a noun / adjective heading a constituent: its relation to the clause's verb (subject, object, the preposition's
                 lemma for a preposition phrase ...); for a verb: obj (its object's head) or subj (its subject's head) or none
  colloc         the collocate: the verb's lemma for a noun, the object's (else subject's) head lemma for a verb ('' when none)
The learned use is a lexicon keyed (lemma, lxx) and (lemma, colloc_kind, colloc), each with a back-off to (lemma, sense) and the
lemma, as for the roles.
Output: macula/data/word-context/{words.tsv, checks.md, build.json} (git-ignored). Not read: BHSA, TBTA, English text.
"""
from __future__ import annotations

import collections
import csv
import datetime
import json
import subprocess

from macula.build_arg_roles import LOWFAT, MSPINE, _lxx_lookup, _ro
from macula.build_arg_roles import HERE

DATA = HERE / "data"
OUT = DATA / "word-context"
COLS = ["corpus", "key", "lemma", "sense", "lxx", "colloc_kind", "colloc"]
CONTENT = {"noun", "verb", "adj", "adjective"}


def main() -> int:
    m = _ro(MSPINE)
    info = {}
    for k, lang, cl, lem, st in m.execute("select key, lang, class, lemma, strong from macula_words"):
        info[k] = (lang, cl or "", (st or lem or "") if lang == "hbo" else (lem or ""))
    sense = {}
    for r in csv.DictReader(open(DATA / "word-senses-ubs/words.tsv", encoding="utf-8"), delimiter="\t"):
        sense.setdefault(r["key"], r["sense"])
    lxx, hpos = {}, {}
    for k, g, b, c, v in _ro(LOWFAT).execute("select key, greek, book, chapter, verse from lowfat_words where is_inserted=0"):
        lxx[k], hpos[k] = (g or "").strip('"'), (b, c, v)
    plain, lxx_verse, lxx_glob = _lxx_lookup()

    def lxx_lemma(k):
        g = lxx.get(k, "")
        if not g:
            return ""
        b, c, v = hpos[k]
        pl = plain(g.split()[-1])
        return (lxx_verse.get((b, c, v, pl)) or lxx_glob.get(pl, ("", "")))[0]
    noun_ctx, verb_obj, verb_subj = {}, {}, {}
    for r in csv.DictReader(open(DATA / "arg-roles/roles.tsv", encoding="utf-8"), delimiter="\t"):
        h, v = r["head"], r["verb"]
        if not h or not v:
            continue
        kind = r["prep_lemma"] or r["relation"] or r["macrorole"] or "arg"
        noun_ctx.setdefault(h, (kind, info.get(v, ("", "", ""))[2]))
        rel = (r["relation"] or "").lower()
        if r["macrorole"] == "undergoer" or rel in ("o", "object", "obj"):
            verb_obj.setdefault(v, info.get(h, ("", "", ""))[2])
        elif r["macrorole"] == "actor" or rel in ("s", "subject", "subj"):
            verb_subj.setdefault(v, info.get(h, ("", "", ""))[2])
    rows, st = [], collections.Counter()
    cells = collections.defaultdict(set)                         # (corpus, lemma, sense) -> distinct keys, to size the split
    for k, (lang, cl, lem) in info.items():
        if cl not in CONTENT:
            continue
        corpus = lang
        lx = lxx_lemma(k) if lang == "hbo" else ""
        if cl == "verb":
            if k in verb_obj:
                ck, co = "obj", verb_obj[k]
            elif k in verb_subj:
                ck, co = "subj", verb_subj[k]
            else:
                ck, co = "none", ""
        else:
            ck, co = noun_ctx.get(k, ("none", ""))
        s = sense.get(k, "")
        rows.append([corpus, k, lem, s, lx, ck, co])
        st[(corpus, cl, "lxx" if lx else "no_lxx")] += 1
        st[(corpus, cl, "colloc" if co else "no_colloc")] += 1
        if lx:
            cells[(corpus, "lxx", lem, s)].add(lx)
        if co:
            cells[(corpus, "colloc", lem, s)].add(co)
    rows.sort(key=lambda r: (r[0], r[1]))
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "words.tsv", "w", encoding="utf-8") as f:
        f.write("\t".join(COLS) + "\n")
        f.writelines("\t".join(r) + "\n" for r in rows)
    split = collections.Counter()
    for (corpus, kind, _, _), vals in cells.items():
        split[(corpus, kind, "cells")] += 1
        split[(corpus, kind, "cells_split")] += len(vals) > 1
    lines = ["# Word context: checks", "", f"Content words: {len(rows):,}.", "", "| corpus | class | value | words |", "|---|---|---|---|"]
    lines += [f"| {c} | {cl} | {v} | {n:,} |" for (c, cl, v), n in sorted(st.items())]
    lines += ["", "(lemma, sense) cells the key splits into more than one value:", "", "| corpus | key | cells | split |", "|---|---|---|---|"]
    for c in ("hbo", "grc"):
        for kind in ("lxx", "colloc"):
            if split[(c, kind, "cells")]:
                lines.append(f"| {c} | {kind} | {split[(c, kind, 'cells')]:,} | {split[(c, kind, 'cells_split')]:,} |")
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = subprocess.run(["git", "log", "-1", "--format=%h"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    (OUT / "build.json").write_text(json.dumps({"schema": 1, "built": datetime.date.today().isoformat(), "code": code,
                                                "not_read": ["BHSA", "TBTA", "English text"]}, indent=1) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
