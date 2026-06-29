#!/usr/bin/env python3
"""Build strongs_keyness.tsv: a per-Strong's biblical-salience weight.

    keyness = zipf_bible - zipf_general

i.e. how much MORE a concept appears in scripture than in general language
(a log-ratio). High = distinctively biblical (covenant, grace); ~0 = common
everywhere (about, says); a word absent from scripture is undefined → drop.
The weight lives on the Strong's NUMBER, so it carries to every language via
the gloss map (es "gracia" / fr "grâce" / zh "恩典" all inherit weight[G5485]).

Anchors (see internal-docs/multilingual-endpoint-strategy.md, Strategy 2):
  H#### (OT/Hebrew) — anchor 'he':
      zipf in the spine OT  −  modern Hebrew general freq (wordfreq 'he',
      biblical lemma point-stripped via NFD).
  G#### (NT/Greek) — anchor 'grc':
      zipf in the Nestle1904 NT  −  general (pagan) Koine freq, from the LAGT
      corpus (Lemmatized Ancient Greek Texts, ~25M pagan tokens; the Christian +
      Jewish subsets are excluded so the denominator is genuinely non-biblical).
      Both polytonic → NFC-casefold match, no monotonic conversion. This replaces
      the old English-gloss carry-over proxy (e.g. ἀγάπη 0.17→3.01).

BUILD-TIME ONLY. Requires `wordfreq`, `pandas`+`pyarrow`, the local spine.db, and
the LAGT parquet (auto-downloaded, or point $LAGT_PARQUET at it). The server reads
the committed TSV — NO runtime dependency, no image bloat.
Run:  /path/to/venv-with-build-deps/bin/python3 scripts/build_strongs_keyness.py

Output columns: strong, keyness, anchor, modern_he, koine_general
  modern_he  = raw modern-Hebrew freq (zipf) of the lemma; 0 = absent from modern
    Hebrew → "archaic / extinct in modern". Hebrew rows only ('' for Greek).
  koine_general = raw pagan-Koine freq (zipf) of the lemma; 0 = absent from secular
    Koine → "scripture_only / distinctively scriptural". Greek rows only ('' for He).
  Both are robust even for rare words where the keyness score itself is noisy; storing
  the raw value keeps it graded (client picks the threshold) and lossless.
"""
from __future__ import annotations

import math
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
import urllib.request
from pathlib import Path

from wordfreq import zipf_frequency

ROOT = Path(__file__).resolve().parent.parent.parent
SPINE_DB = ROOT / "shoresh" / "spine" / "spine.db"
GRC_FREQ = ROOT / "resources" / "word_freq" / "grc.tsv"          # NT1904 lemma freq
GRC_STRONG = ROOT / "resources" / "word_freq" / "grc_strong.tsv"  # NT1904 lemma → Strong's
OUTPUT = ROOT / "resources" / "strongs_keyness.tsv"

# LAGT v4.1 (Lemmatized Ancient Greek Texts) — the non-biblical Koine denominator.
LAGT_URL = "https://zenodo.org/records/13889714/files/LAGT_v4-1.parquet?download=1"

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


def _lagt_path() -> Path:
    """Locate the LAGT parquet ($LAGT_PARQUET, else a temp cache, else download)."""
    env = os.environ.get("LAGT_PARQUET")
    if env:
        return Path(env)
    cache = Path(tempfile.gettempdir()) / "lagt_v4-1.parquet"
    if not cache.exists():
        print(f"  downloading LAGT parquet (~270 MB, one-time) → {cache}", file=sys.stderr)
        urllib.request.urlretrieve(LAGT_URL, cache)
    return cache


def _grc_norm(s: str) -> str:
    """Match key for polytonic Greek lemmas (NT1904 ↔ LAGT). Accent-fold: casefold and
    drop accents/breathing/iota-subscript → bare letters. The two lemmatizers disagree
    on accentuation constantly (e.g. δοῦλος), so exact matching produces false zeros;
    folding recovers them. Homograph collisions just sum frequencies — harmless for a
    denominator, and biblical words stay low (ἀγάπη) or absent (σκανδαλίζω)."""
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)   # strip NT1904 homograph marker, e.g. "δοῦλος (II)"
    d = unicodedata.normalize("NFD", s).casefold()
    return unicodedata.normalize("NFC", "".join(c for c in d if not unicodedata.combining(c)))


def _pagan_koine() -> tuple[dict[str, int], int]:
    """({normalized lemma: count}, total_running_words) over LAGT's PAGAN texts only —
    the Christian + Jewish subsets are excluded so the denominator is non-biblical."""
    import pandas as pd  # build-time dep
    df = pd.read_parquet(_lagt_path())
    pagan = df[df.provenience == "pagan"]
    total = int(pagan.wordcount.sum())               # all running words (zipf denominator)
    counts: dict[str, int] = {}
    for sents in pagan["lemmatized_sentences"]:       # content-word lemmas per sentence
        for arr in sents:
            for lem in arr:
                k = _grc_norm(lem)
                counts[k] = counts.get(k, 0) + 1
    return counts, total


def _greek_content_lemmas() -> set[str]:
    """NT1904 lemmas whose dominant POS is a content class (noun/verb/adj) — the only
    classes LAGT lemmatizes. Function words (conj/det/pron/prep/adv/ptcl) are excluded:
    LAGT doesn't lemmatize them, so they'd get a false koine_general=0 (e.g. ἵνα, οὖν)."""
    import collections
    from corpus_engine import engine
    api = engine._ensure_loaded("greek")
    cls, lemma = api.Fs("cls"), api.Fs("lemma")
    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for w in api.F.otype.s("w"):
        lm = lemma.v(w)
        if lm:
            votes[lm][cls.v(w)] += 1
    content = {"noun", "verb", "adj"}
    return {lm for lm, c in votes.items() if c.most_common(1)[0][0] in content}


def greek_keyness() -> dict[str, tuple[float, float]]:
    """G#### → (keyness, koine_general): zipf in the NT − zipf in pagan Koine (LAGT).
    `koine_general == 0` means the lemma is ABSENT from secular Koine → "scripture_only"
    (distinctively scriptural), the Greek analog of Hebrew's archaic flag — robust even
    for rare words. Replaces the old English-gloss proxy with a real, contemporaneous,
    polytonic-aligned Koine denominator."""
    # NT1904 lemma → Strong's, and lemma → NT frequency.
    lem_strong: dict[str, str] = {}
    with GRC_STRONG.open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            lem, code = line.rstrip("\n").split("\t")
            lem_strong[lem] = code
    nt_freq: dict[str, int] = {}
    rep_lemma: dict[str, str] = {}     # dominant NT lemma per Strong's (for the pagan lookup)
    best_count: dict[str, int] = {}
    nt_total = 0
    with GRC_FREQ.open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            lem, count, _rank = line.rstrip("\n").split("\t")
            count = int(count)
            nt_total += count
            code = lem_strong.get(lem)
            if not code:
                continue
            nt_freq[code] = nt_freq.get(code, 0) + count
            if count > best_count.get(code, 0):
                best_count[code] = count
                rep_lemma[code] = lem

    pagan, pagan_total = _pagan_koine()
    content = _greek_content_lemmas()   # only POS LAGT lemmatizes (noun/verb/adj)

    out: dict[str, tuple[float, float]] = {}
    for code, ntf in nt_freq.items():
        # Skip function words: LAGT doesn't lemmatize them, so koine_general would be a
        # false 0. They're never word-study targets, so no keyness is the right answer.
        if not ntf or rep_lemma.get(code) not in content:
            continue
        z_nt = _zipf(ntf, nt_total)
        pc = pagan.get(_grc_norm(rep_lemma[code]), 0)
        # 0 → absent from secular Koine → scripture_only (high keyness).
        z_koine = round(_zipf(pc, pagan_total), 2) if pc else 0.0
        out[_pad_code(code)] = (round(z_nt - z_koine, 2), z_koine)
    return out


def main() -> None:
    if not SPINE_DB.exists() or not GRC_FREQ.exists() or not GRC_STRONG.exists():
        print(f"ERROR: need {SPINE_DB}, {GRC_FREQ}, {GRC_STRONG}", file=sys.stderr)
        sys.exit(1)

    heb = hebrew_keyness()        # code → (keyness, modern_he)
    grk = greek_keyness()         # code → (keyness, koine_general)
    print(f"hebrew: {len(heb)} codes (modern-he anchor)", file=sys.stderr)
    print(f"greek:  {len(grk)} codes (pagan-Koine anchor)", file=sys.stderr)

    # Two raw denominator columns: modern_he (He) and koine_general (Gr); each row
    # fills exactly one. anchor disambiguates ('he' archaic vs 'grc' scripture_only).
    rows = ([(c, k, "he", mh, None) for c, (k, mh) in heb.items()]
            + [(c, k, "grc", None, kg) for c, (k, kg) in grk.items()])
    rows.sort(key=lambda r: (-r[1], r[0]))

    def _f(v):
        return "" if v is None else v

    with OUTPUT.open("w", encoding="utf-8") as fh:
        fh.write("strong\tkeyness\tanchor\tmodern_he\tkoine_general\n")
        for code, k, anchor, mh, kg in rows:
            fh.write(f"{code}\t{k}\t{anchor}\t{_f(mh)}\t{_f(kg)}\n")

    print(f"\nWrote {len(rows)} entries to {OUTPUT}", file=sys.stderr)
    print("Most distinctive (top 8):", file=sys.stderr)
    for code, k, anchor, mh, kg in rows[:8]:
        gen = f"modern_he={mh}" if anchor == "he" else f"koine_general={kg}"
        print(f"  {code}\t{k:+.2f}\t{anchor}\t{gen}", file=sys.stderr)


if __name__ == "__main__":
    main()
