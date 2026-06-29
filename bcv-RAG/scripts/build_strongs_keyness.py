#!/usr/bin/env python3
"""Build strongs_keyness.tsv: a per-Strong's biblical-salience weight.

    keyness = zipf_bible - zipf_general

i.e. how much MORE a concept appears in scripture than in general language
(a log-ratio). High = distinctively biblical (covenant, grace); ~0 = common
everywhere (about, says); a word absent from scripture is undefined → drop.
The weight lives on the Strong's NUMBER, so it carries to every language via
the gloss map (es "gracia" / fr "grâce" / zh "恩典" all inherit weight[G5485]).

Anchors (see internal-docs/multilingual-endpoint-strategy.md, Strategy 2):
  H#### (OT/Hebrew) — original-language anchor:
      zipf in the spine OT  −  modern Hebrew general freq (wordfreq 'he',
      biblical lemma point-stripped via NFD). Ready now.
  G#### (NT/Greek) — English carry-over anchor (interim):
      zipf of the English gloss in BSB (index.db english_concordance)
      −  general English (wordfreq 'en'). Polytonic Koine ≠ monotonic modern
      Greek, so modern 'el' isn't reliable yet; the principled path later is a
      non-biblical Koine corpus denominator + polytonic→monotonic normalization.

BUILD-TIME ONLY. Requires `wordfreq` and the local spine.db / index.db. The
server reads the committed TSV — NO runtime dependency, no image bloat.
Run:  /path/to/venv-with-wordfreq/bin/python3 scripts/build_strongs_keyness.py

Output columns: strong, keyness, anchor, modern_he
  modern_he = raw modern-Hebrew frequency (zipf scale) of the lemma; 0 = absent from
  modern Hebrew ("archaic / extinct in modern" — robust even for rare words where the
  keyness score is noisy). Hebrew rows only; '' for Greek (no modern-Greek denominator).
"""
from __future__ import annotations

import math
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

from wordfreq import zipf_frequency

ROOT = Path(__file__).resolve().parent.parent.parent
SPINE_DB = ROOT / "shoresh" / "spine" / "spine.db"
INDEX_DB = Path(__file__).resolve().parent.parent / "indexer" / "index.db"
GLOSS_TSV = ROOT / "resources" / "strongs_gloss.tsv"
OUTPUT = ROOT / "resources" / "strongs_keyness.tsv"

sys.path.insert(0, str(ROOT / "shoresh"))
from spine.common import NT_BOOKS  # noqa: E402  (single source of the OT/NT split)


def _strip_marks(s: str) -> str:
    """Strip Hebrew points/cantillation (and any combining marks) → base letters."""
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if not unicodedata.combining(c))


def _norm(prefix: str, strong: int) -> str:
    return f"{prefix}{int(strong):04d}"


def _pad_code(code: str) -> str:
    """Canonicalize an already-prefixed code to padded form: G26→G0026, H0821a kept."""
    m = re.match(r"^([HG])(\d+)([a-z]?)$", code.strip())
    return f"{m.group(1)}{int(m.group(2)):04d}{m.group(3)}" if m else code


def _zipf(count: int, total: int) -> float:
    """Frequency on wordfreq's zipf scale: log10(occurrences per billion)."""
    return math.log10(count / total * 1e9)


def hebrew_keyness() -> dict[str, tuple[float, float]]:
    """H#### → (keyness, modern_he): spine OT zipf − modern Hebrew general zipf, and
    the raw modern-Hebrew frequency itself (zipf scale). `modern_he == 0` means the
    lemma is ABSENT from modern Hebrew — a robust "archaic / extinct in modern" signal
    even for rare/hapax words where the continuous keyness score is noisy. Storing the
    raw value (not a boolean) keeps it graded — clients pick their own threshold — and
    lossless: zipf_bible = keyness + modern_he."""
    nt = sorted(NT_BOOKS)
    ph = ",".join("?" * len(nt))
    con = sqlite3.connect(SPINE_DB)
    total = con.execute(
        f"SELECT COUNT(*) FROM spine_words WHERE book NOT IN ({ph})", nt
    ).fetchone()[0]
    # One representative lemma per Strong's (lemmas are stable within a code).
    rows = con.execute(
        f"SELECT strong, COUNT(*) c, lemma FROM spine_words "
        f"WHERE strong IS NOT NULL AND book NOT IN ({ph}) GROUP BY strong", nt
    ).fetchall()
    con.close()

    out: dict[str, tuple[float, float]] = {}
    for strong, c, lemma in rows:
        zb = _zipf(c, total)
        # Lemma absent from modern Hebrew → zipf 0.0 → archaic/biblical → high keyness.
        zg = zipf_frequency(_strip_marks(lemma), "he") if lemma else 0.0
        out[_norm("H", strong)] = (round(zb - zg, 2), round(zg, 2))
    return out


def greek_keyness() -> dict[str, tuple[float, None]]:
    """G#### keyness via English carry-over: BSB gloss zipf − general English zipf.
    No modern-Greek denominator yet (the proxy is English), so `archaic` is undefined."""
    # English gloss per Greek Strong's, from strongs_gloss.tsv (lang=eng).
    en_gloss: dict[str, str] = {}
    with GLOSS_TSV.open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 4 and p[3] == "eng" and p[0].startswith("G"):
                en_gloss[p[0]] = p[1]

    # BSB word frequencies (verse-level concordance — a consistent proxy).
    con = sqlite3.connect(INDEX_DB)
    bsb: dict[str, int] = {}
    for w, c in con.execute(
        "SELECT word_normalized, COUNT(*) FROM english_concordance GROUP BY word_normalized"
    ):
        bsb[w] = c
    con.close()
    bsb_total = sum(bsb.values())

    out: dict[str, float] = {}
    for code, gloss in en_gloss.items():
        best: float | None = None
        for w in re.findall(r"[a-z]{2,}", gloss.lower()):
            c = bsb.get(w)
            if not c:
                continue  # gloss word not in scripture → no signal from this word
            k = _zipf(c, bsb_total) - zipf_frequency(w, "en")
            best = k if best is None else max(best, k)
        if best is not None:
            out[_pad_code(code)] = (round(best, 2), None)  # canonical padded; archaic undefined for Greek
    return out


def main() -> None:
    if not SPINE_DB.exists() or not INDEX_DB.exists():
        print(f"ERROR: need {SPINE_DB} and {INDEX_DB}", file=sys.stderr)
        sys.exit(1)

    heb = hebrew_keyness()
    grk = greek_keyness()
    print(f"hebrew: {len(heb)} codes (modern-he anchor)", file=sys.stderr)
    print(f"greek:  {len(grk)} codes (english carry-over)", file=sys.stderr)

    # modern_he = raw modern-Hebrew zipf (Hebrew only; '' for the Greek English-proxy).
    rows = ([(c, k, "he", mh) for c, (k, mh) in heb.items()]
            + [(c, k, "en", mh) for c, (k, mh) in grk.items()])
    rows.sort(key=lambda r: (-r[1], r[0]))

    with OUTPUT.open("w", encoding="utf-8") as fh:
        fh.write("strong\tkeyness\tanchor\tmodern_he\n")
        for code, k, anchor, mh in rows:
            fh.write(f"{code}\t{k}\t{anchor}\t{'' if mh is None else mh}\n")

    print(f"\nWrote {len(rows)} entries to {OUTPUT}", file=sys.stderr)
    print("Most distinctive (top 8):", file=sys.stderr)
    for code, k, anchor, mh in rows[:8]:
        print(f"  {code}\t{k:+.2f}\t{anchor}\tmodern_he={mh}", file=sys.stderr)
    print("Least distinctive (bottom 8):", file=sys.stderr)
    for code, k, anchor, mh in rows[-8:]:
        print(f"  {code}\t{k:+.2f}\t{anchor}\tmodern_he={mh}", file=sys.stderr)


if __name__ == "__main__":
    main()
