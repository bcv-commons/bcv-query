"""Precompute lexeme frequency rank from the TF corpora → resources/word_freq/.

Writes one TSV per corpus (`lex<TAB>count<TAB>rank`, rank 0 = most frequent):
  resources/word_freq/hbo.tsv   BHSA (Hebrew + Aramaic share one corpus)
  resources/word_freq/grc.tsv   Nestle1904 (Greek)

Why a baked artifact and not a runtime scan:
  /words returns a frequency `rank` per word. Computing it means scanning the
  whole corpus (BHSA ~426k words, Nestle1904 ~138k). Doing that per request is
  wasteful; even memoized it costs a multi-hundred-k scan on the first request
  after every restart. Baking it makes the rank a cheap dict load and a
  reviewable, diffable resource.

  The rank is corpus-INTERNAL by construction (BHSA's own freq_lex for Hebrew;
  occurrence count of `lemma` for Greek, which ships no frequency feature), so it
  always joins cleanly to the `lex`/`lemma` the same corpus returns — unlike an
  external frequency list keyed to a different lemmatization.

  NOTE: Aramaic shares the BHSA corpus, so Aramaic ranks are positioned within
  the combined Hebrew+Aramaic frequency list, not Aramaic-only.

Run on any machine that has the TF corpus available (mounted volume on the host,
or ~/text-fabric-data on a dev box):
  python -m corpus_engine.build_freq
then commit resources/word_freq/.
"""
from __future__ import annotations

import os
from pathlib import Path

from corpus_engine import engine
from corpus_engine.cf_engine import WORD_FEATURES, WORD_TYPE

# corpus id -> output stem (the loader maps the same way; keep in sync).
CORPUS_STEM = {"hebrew": "hbo", "greek": "grc"}


def _resources_dir() -> Path:
    env = os.environ.get("BCV_RESOURCES_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2] / "resources"


def _counts(api, corpus: str) -> dict[str, int]:
    """{lex: count} — freq_lex when the corpus has it (BHSA), else count `lemma`
    occurrences (Nestle1904). Mirrors CFEngine._rank_map exactly."""
    feat_map = WORD_FEATURES.get(corpus, WORD_FEATURES["hebrew"])
    lex_obj = api.Fs(feat_map.get("lexeme", "lex"))
    wtype = WORD_TYPE.get(corpus, "word")
    freq_obj = api.Fs("freq_lex")
    out: dict[str, int] = {}
    if freq_obj is not None:
        for w in api.F.otype.s(wtype):
            lex = lex_obj.v(w)
            if not lex or lex in out:
                continue
            freq = freq_obj.v(w)
            if freq is not None:
                out[str(lex)] = int(freq)
    else:
        for w in api.F.otype.s(wtype):
            lex = lex_obj.v(w)
            if lex:
                k = str(lex)
                out[k] = out.get(k, 0) + 1
    return out


def build() -> None:
    out_dir = _resources_dir() / "word_freq"
    out_dir.mkdir(parents=True, exist_ok=True)
    for corpus, stem in CORPUS_STEM.items():
        api = engine._ensure_loaded(corpus)
        counts = _counts(api, corpus)
        ranked = sorted(counts.items(), key=lambda x: -x[1])
        path = out_dir / f"{stem}.tsv"
        with path.open("w", encoding="utf-8") as fh:
            fh.write("lex\tcount\trank\n")
            for rank, (lex, count) in enumerate(ranked):
                fh.write(f"{lex}\t{count}\t{rank}\n")
        print(f"  {corpus:7s} -> {path.relative_to(_resources_dir().parent)} "
              f"({len(ranked)} lexemes, top: {ranked[0][0]}={ranked[0][1]})")


if __name__ == "__main__":
    print("building word-frequency resources ...")
    build()
    print("done.")
