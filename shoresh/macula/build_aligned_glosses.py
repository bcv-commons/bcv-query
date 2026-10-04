"""Per-language glosses for Hebrew words from the lexeme-aligner's published renderings, for labels.

Shoresh localizes group and relation labels through BibleOL gloss tables keyed on BHSA lexemes, bridged to
Strong's by a crosswalk; where that route has no gloss whose English matches, the label stays English. This
fills those gaps from the aligner's per-language renderings (bcv-commons/lexeme-alignments, as mirrored in
resources/aligned_lex_hf/, CC0): per Hebrew Strong's and language, the most frequent rendering with at least
MIN_COUNT occurrences and confidence >= MIN_CONF, not a transliteration (ʼ) and not a function word in that
language (bcv-commons/target-stopwords, CC0). Only the languages shoresh offers (related_langs/languages.tsv).

  python -m macula.build_aligned_glosses      # -> resources/aligned_glosses/hbo.tsv
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ALIGNED = ROOT / "resources" / "aligned_lex_hf"
LANGS = ROOT / "resources" / "related_langs" / "languages.tsv"
STOPWORDS = Path(os.environ.get("TARGET_STOPWORDS_DIR",
                                str(Path.home() / "dev/bcv-commons/lexeme-aligner/publish/target-stopwords")))
OUT = ROOT / "resources" / "aligned_glosses" / "hbo.tsv"
MIN_COUNT, MIN_CONF = 5, 0.5


def main() -> int:
    isos = []
    with LANGS.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if (row.get("iso639_3") or "").strip():
                isos.append(row["iso639_3"].strip())
    rows, n_lang = [], 0
    for iso in sorted(set(isos)):
        src = ALIGNED / f"{iso}.tsv"
        if not src.exists():
            continue
        stop = set()
        sw = STOPWORDS / f"{iso}.txt"
        if sw.exists():
            stop = {w.strip().lower() for w in sw.read_text(encoding="utf-8").splitlines() if w.strip()}
        best: dict = {}
        for line in src.read_text(encoding="utf-8").splitlines():
            if line.startswith(("#", "surface\t")):
                continue
            p = line.split("\t")
            if len(p) < 5 or not p[1].startswith("H"):
                continue
            surf, strong, n, conf = p[0], p[1], int(p[2]), float(p[4])
            words = surf.lower().split()
            if n < MIN_COUNT or conf < MIN_CONF or "ʼ" in surf or "'" in surf or not words:
                continue
            if all(w in stop for w in words) or len(surf) < 2:
                continue
            if strong not in best or n > best[strong][1]:
                best[strong] = (surf, n, conf)
        n_lang += 1
        rows += [(s, iso, g, n, c) for s, (g, n, c) in best.items()]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write("# Per-language glosses for Hebrew Strong's numbers: the lexeme-aligner's most frequent rendering "
                 f"(count >= {MIN_COUNT}, confidence >= {MIN_CONF}, no transliterations or function words).\n"
                 "# Source: bcv-commons/lexeme-alignments and bcv-commons/target-stopwords (CC0). Built by "
                 "shoresh/macula/build_aligned_glosses.py.\n")
        fh.write("strong\tiso\tgloss\tcount\thi_conf\n")
        for r in sorted(rows):
            fh.write("\t".join(map(str, r)) + "\n")
    print(f"[aligned-glosses] {n_lang} languages, {len(rows)} (strong, language) glosses -> {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
