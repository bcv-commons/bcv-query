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
    from macula.build_rendering_senses import load_features
    feats, eng_raw = load_features()
    multi = {lx for (lx, _s) in counts if sum(1 for (l, _x) in counts if l == lx) > 1}
    eng = collections.defaultdict(collections.Counter)
    n = collections.Counter()
    for key, (lx, sense) in sense_of.items():
        if lx not in multi:
            continue
        n[(lx, sense)] += 1
        for lang, f in feats.get(key, ()):
            if lang == "eng":
                eng[(lx, sense)][f] += 1
    out = {}
    for lx in multi:
        senses = [s_ for (l, s_) in n if l == lx]
        for s_ in senses:
            share = {f: c / n[(lx, s_)] for f, c in eng[(lx, s_)].items()}
            def score(f):
                other = max((eng[(lx, o)][f] / n[(lx, o)] for o in senses if o != s_ and n[(lx, o)]), default=0)
                return share[f] - other
            if share:
                best = max(share, key=score)
                out[(lx, s_)] = eng_raw[best].most_common(1)[0][0] if eng_raw.get(best) else best
    return out


def main() -> int:
    prior = {r["lexeme"]: r for r in pq.read_table(ROOT / "resources" / "prior_pack" / "prior_pack.parquet",
                                                    columns=["lexeme", "strong", "lemma"]).to_pylist()}
    labels = {}
    for line in (SRC / "senses.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        lexeme, sense, label, _n, _sh = line.split("\t")
        labels[(lexeme, sense)] = label
    sense_of = {}
    for line in (SRC / "occurrences.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        key, lexeme, sense = line.split("\t")
        sense_of[key] = (lexeme, sense)
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
    labels.update(distinctive_labels(sense_of, counts))
    with (OUT / "senses.tsv").open("w", encoding="utf-8") as fh:
        fh.write("lexeme\tstrong\tlemma\tsense\tlabel\tcount\tshare\n")
        for (lexeme, sense), n in sorted(counts.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            p = prior.get(lexeme, {})
            fh.write(f"{lexeme}\t{p.get('strong') or ''}\t{p.get('lemma') or ''}\t{sense}\t"
                     f"{labels.get((lexeme, str(sense)), '')}\t{n}\t{n / totals[lexeme]:.3f}\n")
    n_multi = sum(1 for lx in totals if len({s for (l, s) in counts if l == lx}) > 1)
    print(f"[hebrew-word-senses] {len(totals)} lexemes, {len(counts)} senses, {n_multi} lexemes with >1 sense, "
          f"{len(occ['key'])} occurrences -> {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
