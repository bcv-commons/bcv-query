#!/usr/bin/env python3
"""Build the gloss family of the standalone Strong's->words dataset.

Type-level companion to build_strongs_words.py (the alignment family): one
canonical *word* per Strong's per language, rather than attested surface forms.
Same design rules — anchored on Hebrew/Greek (strong + lemma, never via English),
one language per file, every gloss marked with how it was generated.

Merges the two existing gloss sources into resources/strongs_words/glosses/:
  * resources/strongs_gloss.tsv          (method=lexicon)  en/es/fr/pt/zh/zh-Hant
      en  -> source=stepbible (CC BY)
      others -> source=ubs-dict (UBS dictionaries, CC BY-SA)
  * resources/llm_strongs_glosses/<c>.tsv (method=llm, source=inhouse-llm)
      ar/as/bn/es/ha/hi/ru  (the English `en_ref` hint column is dropped)

Output: glosses/<code>.tsv  ->  strong  lemma  gloss  methods  sources
  collapsed to one row per (strong, gloss); `methods`/`sources` are ;-sets so a
  word confirmed by both a dictionary and the LLM shows `lexicon;llm`.

There is NO attestation tier for glosses — they are type-level (no occurrences).

Usage: python3 scripts/build_strongs_words_glosses.py
"""
from __future__ import annotations

import datetime as _dt
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from ingest.clear_aligned import _norm_strong               # noqa: E402
from scripts.build_strongs_words import load_canonical_lemmas  # noqa: E402

RES = HERE.parent / "resources"
OUT = RES / "strongs" / "glosses"
LEXICON_TSV = RES / "strongs_gloss.tsv"
LLM_DIR = RES / "llm_strongs_glosses"

# language -> source for the lexicon file's rows (lang values are canonical now)
LEXICON_SOURCE = {"eng": "stepbible"}         # others fall back to ubs-dict
DEFAULT_LEXICON_SOURCE = "ubs-dict"


def _read_header_then_rows(path: Path):
    """Yield split rows after the first non-comment (header) line."""
    with path.open(encoding="utf-8") as fh:
        header = None
        for line in fh:
            if line.startswith("#"):
                continue
            cols = line.rstrip("\n").split("\t")
            if header is None:
                header = cols
                continue
            yield header, cols


def collect() -> dict[str, dict]:
    """{code: {(strong, gloss): {methods:set, sources:set}}}"""
    canon = load_canonical_lemmas()
    data: dict[str, dict] = defaultdict(lambda: defaultdict(
        lambda: {"methods": set(), "sources": set()}))

    # 1. lexicon (multi-language, long format: strong, gloss, translit, lang)
    for header, c in _read_header_then_rows(LEXICON_TSV):
        idx = {name: i for i, name in enumerate(header)}
        strong = _norm_strong(c[idx["strong"]])
        gloss = (c[idx["gloss"]] or "").strip()
        lang = (c[idx["lang"]] or "").strip() if idx.get("lang") is not None \
            and len(c) > idx["lang"] else ""
        if not strong or not gloss or not lang:
            continue
        rec = data[lang][(strong, gloss)]
        rec["methods"].add("lexicon")
        rec["sources"].add(LEXICON_SOURCE.get(lang, DEFAULT_LEXICON_SOURCE))

    # 2. llm (per-language: strong, lemma_ref, en_ref, gloss)
    for p in sorted(LLM_DIR.glob("*.tsv")):
        code = p.stem
        for header, c in _read_header_then_rows(p):
            idx = {name: i for i, name in enumerate(header)}
            if len(c) <= idx["gloss"]:
                continue
            strong = _norm_strong(c[idx["strong"]])
            gloss = (c[idx["gloss"]] or "").strip()
            if not strong or not gloss:
                continue
            rec = data[code][(strong, gloss)]
            rec["methods"].add("llm")
            rec["sources"].add("inhouse-llm")

    return canon, data


def main() -> None:
    canon, data = collect()
    OUT.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()
    print(f"canonical lemmas: {len(canon)} codes", file=sys.stderr)
    for code in sorted(data):
        pairs = data[code]
        with (OUT / f"{code}.tsv").open("w", encoding="utf-8") as fh:
            fh.write(
                f"# dataset=strongs/glosses; lang={code}; "
                f"source=strongs_gloss(lexicon)+llm_strongs_glosses(llm); "
                f"license=see resources/strongs/README.md; date={today}\n"
            )
            fh.write("strong\tlemma\tgloss\tmethods\tsources\n")
            rows = 0
            for (strong, gloss) in sorted(pairs):
                rec = pairs[(strong, gloss)]
                lemma = canon.get(strong, "")
                fh.write(f"{strong}\t{lemma}\t{gloss}\t"
                         f"{';'.join(sorted(rec['methods']))}\t"
                         f"{';'.join(sorted(rec['sources']))}\n")
                rows += 1
        print(f"  {code:8} {rows} rows", file=sys.stderr)


if __name__ == "__main__":
    main()
