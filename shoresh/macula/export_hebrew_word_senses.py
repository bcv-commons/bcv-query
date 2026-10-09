"""Export bcv-commons/hebrew-word-senses: a BHSA-free Hebrew sense inventory, split by translation.

Replaces the 2026-08 release (BHSA lexeme ids, senses clustered on BHSA clauses, CC BY-NC-SA). Senses come
from build_rendering_senses.py: occurrences of a MACULA lexeme that translators in ten languages render
alike share a sense (Clear-Bible/Alignments, CC BY 4.0). Keyed on MACULA lexemes (CC BY 4.0).

  python -m macula.build_rendering_senses --gbt --out macula/data/rendering_senses   # if not built yet
  python -m macula.export_hebrew_word_senses       # -> macula/data/hf_cards/hebrew-word-senses/
"""
from __future__ import annotations

import collections
import sqlite3
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = HERE / "data" / "rendering_senses"
OUT = HERE / "data" / "hf_cards" / "hebrew-word-senses"
SPINE = HERE / "lexeme-spine-macula.db"


def distinctive_labels(sense_of: dict, counts: collections.Counter) -> dict:
    """For words with several senses: label each sense by its most DISTINCTIVE English rendering (share in
    this sense minus the highest share in another sense), so two senses never both read "land"."""
    from macula.build_rendering_senses import load_features, token_surface
    feats, eng_raw = load_features()
    multi = {lx for (lx, _s) in counts if sum(1 for (l, _x) in counts if l == lx) > 1}
    eng = collections.defaultdict(collections.Counter)
    n = collections.Counter()
    toks = collections.defaultdict(list)
    for key, (lx, sense) in sense_of.items():
        if lx not in multi:
            continue
        toks[(lx, sense)].append(key)
        n[(lx, sense)] += 1
        for lang, f in feats.get(key, ()):
            if lang == "eng":
                eng[(lx, sense)][f] += 1
    # the surface a label shows is the one this sense's own tokens carry: the English normaliser keeps five letters, so sanctify / sanctified / sanctuary are one form
    # and the corpus-wide most common surface labelled a verb "sanctuary" (fixed 2026-10-09)
    raw = lambda f, lx, s_: token_surface(f, toks[(lx, s_)]) or (eng_raw[f].most_common(1)[0][0] if eng_raw.get(f) else f)
    out = {}
    for lx in multi:
        senses = sorted((s_ for (l, s_) in n if l == lx), key=lambda s_: -n[(lx, s_)])   # largest first
        used = set()                       # forms already naming a larger sense
        for s_ in senses:
            share = {f: c / n[(lx, s_)] for f, c in eng[(lx, s_)].items()}
            def score(f):
                other = max((eng[(lx, o)][f] / n[(lx, o)] for o in senses if o != s_ and n[(lx, o)]), default=0)
                return share[f] - other
            # the main sense: its most frequent rendering; smaller senses: the most distinctive rendering not
            # already a label of a larger sense of this word
            order = (sorted(share, key=lambda f: -share[f]) if s_ == senses[0]
                     else sorted(share, key=score, reverse=True))
            for f in order:
                if f not in used:
                    out[(lx, s_)] = raw(f, lx, s_)
                    used.add(f)
                    break
            else:
                if order:                      # every English rendering already names a larger sense
                    out[(lx, s_)] = f"{raw(order[0], lx, s_)} ({senses.index(s_) + 1})"
    return out


def surface_labels(labels: dict, sense_of: dict) -> dict:
    """Keep each published label's form, read its surface from the sense's own tokens (see distinctive_labels). Labels whose form no token carries stay as they are."""
    import re
    from macula.build_rendering_senses import norm, token_surface
    toks = collections.defaultdict(list)
    for key, (lx, sense) in sense_of.items():
        toks[(lx, str(sense))].append(key)
    out, changed = {}, 0
    for (lx, sense), label in labels.items():
        m = re.match(r"^(.*?)( \(\d+\))?$", label or "")
        surf = token_surface(norm("eng", m.group(1)), toks.get((lx, str(sense)), ())) if m and m.group(1) else ""
        out[(lx, sense)] = (surf + (m.group(2) or "")) if surf else label
        changed += out[(lx, sense)] != label
    print(f"[hebrew-word-senses] {changed} labels re-read from their own tokens", file=sys.stderr)
    return out


STEM_DB = HERE / "verse-senses-stem.db"


def from_stem_db(path: Path) -> tuple[dict, dict, dict]:
    """(labels, sense_of, stem_of) from build_stem_senses' database: lexeme-level senses everywhere except the verbs that occur in 2+ stems, whose senses are per stem.
    A token of such a verb that has no translation evidence (so no sense of its own) takes the largest sense of its stem."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    labels = {(lx, str(s)): lab for lx, s, lab in con.execute("SELECT lexeme, sense, label FROM senses")}
    sense_of = {k: (lx, str(s)) for k, lx, s in con.execute("SELECT key, lexeme, sense FROM occ")}
    stem_of = {(lx, str(s)): st for lx, s, st in con.execute("SELECT lexeme, sense, stem FROM sense_stem")}
    first = {}                                                           # (lexeme, stem) -> its largest sense (numbered by size within a stem)
    for (lx, s), st in sorted(stem_of.items(), key=lambda kv: int(kv[0][1])):
        first.setdefault((lx, st), s)
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    filled = 0
    for key, lx, st in sp.execute("SELECT key, lexeme, stem FROM spine_words WHERE lexeme LIKE 'hbo:%' AND stem!='' AND stem IS NOT NULL"):
        if key not in sense_of and (lx, st) in first:
            sense_of[key] = (lx, first[(lx, st)])
            filled += 1
    print(f"[hebrew-word-senses] {len(stem_of)} stem-bound senses; {filled} evidence-less verb tokens given their stem's largest sense", file=sys.stderr)
    return labels, sense_of, stem_of


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stem-db", type=Path, default=None, help="publish the per-stem senses of build_stem_senses (adds a `stem` column to senses.tsv)")
    args = ap.parse_args()
    prior = {r["lexeme"]: r for r in pq.read_table(ROOT / "resources" / "prior_pack" / "prior_pack.parquet",
                                                    columns=["lexeme", "strong", "lemma"]).to_pylist()}
    stem_of: dict = {}
    labels = {}
    for line in (SRC / "senses.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        lexeme, sense, label, _n, _sh = line.split("\t")
        labels[(lexeme, sense)] = label
    sense_of = {}
    for line in (SRC / "occurrences.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        key, lexeme, sense = line.split("\t")
        # names keep their splits: translations often spell same-named people or places differently
        # (Abimelech of Gerar / son of Gideon), and merging them lowered agreement with UBS 0.317 -> 0.289
        sense_of[key] = (lexeme, sense)
    if args.stem_db:
        labels, sense_of, stem_of = from_stem_db(args.stem_db)
    db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    occ = collections.defaultdict(list)
    for key, book, ch, vs, word, lexeme in db.execute(
            "SELECT key, book, chapter, verse, idx, lexeme FROM spine_words WHERE lexeme LIKE 'hbo:%'"):
        if key in sense_of and sense_of[key][0] == lexeme:
            occ["key"].append(key)
            occ["book"].append(book)
            occ["chapter"].append(ch)
            occ["verse"].append(vs)
            occ["lexeme"].append(lexeme)
            occ["sense"].append(int(sense_of[key][1]))
    OUT.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(occ), OUT / "occurrences.parquet", compression="zstd")

    counts = collections.Counter(zip(occ["lexeme"], occ["sense"]))
    totals = collections.Counter(occ["lexeme"])
    if not args.stem_db:                                  # the stem database carries final labels
        labels.update(distinctive_labels(sense_of, counts))
        labels = surface_labels(labels, sense_of)
    with (OUT / "senses.tsv").open("w", encoding="utf-8") as fh:
        fh.write("lexeme\tstrong\tlemma\tsense\tlabel\tcount\tshare" + ("\tstem" if args.stem_db else "") + "\n")
        for (lexeme, sense), n in sorted(counts.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            p = prior.get(lexeme, {})
            fh.write(f"{lexeme}\t{p.get('strong') or ''}\t{p.get('lemma') or ''}\t{sense}\t"
                     f"{labels.get((lexeme, str(sense)), '')}\t{n}\t{n / totals[lexeme]:.3f}" + (f"\t{stem_of.get((lexeme, str(sense)), '')}" if args.stem_db else "") + "\n")
    n_multi = sum(1 for lx in totals if len({s for (l, s) in counts if l == lx}) > 1)
    print(f"[hebrew-word-senses] {len(totals)} lexemes, {len(counts)} senses, {n_multi} lexemes with >1 sense, "
          f"{len(occ['key'])} occurrences -> {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
