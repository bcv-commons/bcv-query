#!/usr/bin/env python3
"""Language-detection eval — accuracy of query.lang_detect.detect_lang over
sample queries per supported language, plus the ambiguous/fallback cases.

  python -m eval.lang_detect
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from query.lang_detect import detect_lang  # noqa: E402

# (query, expected) — expected None means "should fall back to default (eng)".
CASES = [
    ("¿De qué diferentes tipos de amor habla la Biblia?", "spa"),
    ("¿Qué dice la Biblia sobre el perdón?", "spa"),
    ("what are the different kinds of love in the Bible", "eng"),
    ("how should I translate abstract nouns", "eng"),
    ("Quels sont les types d'amour dans la Bible", "fra"),
    ("Que dit la Bible sur la grâce", "fra"),
    # NB: "Que tipos de amor a Bíblia menciona" is intentionally NOT here — it
    # reads identically as Portuguese OR Spanish (undecidable; see module docstr).
    ("O que a Bíblia diz sobre a fé", "por"),
    ("Como devo perdoar o meu irmão segundo a Bíblia", "por"),
    ("Какие виды любви в Библии", "rus"),
    ("ما الذي يقوله الكتاب المقدس عن الحب", "arb"),
    ("बाइबल प्रेम के बारे में क्या कहती है", "hin"),
    # ambiguous / fallback (no function words → default eng)
    ("Boaz", "eng"),
    ("agape", "eng"),
    ("", "eng"),
]


def main() -> int:
    ok = 0
    print(f"{'query':<46} {'detected':<10} expected")
    for q, exp in CASES:
        got = detect_lang(q)
        mark = "✓" if got == exp else "✗ FAIL"
        ok += got == exp
        print(f"  {q[:44]:<44} {got:<10} {exp:<6} {mark}")
    print(f"\naccuracy: {ok}/{len(CASES)}")
    return 0 if ok == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
