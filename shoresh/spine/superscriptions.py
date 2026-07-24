"""Psalm superscription detection — marks which spine.db tokens belong to a Psalm's title
(e.g. "A Psalm of David") rather than its actual body content.

Two trustworthy sources combine to cover all 116 titled psalms, with NO frequency-based or
otherwise-guessed heuristic anywhere in this module — every flag traces back to an actual marked
structural boundary, not an inference:

1. UHB's own USFM `\\d` marker (parsed by parse.py into spine.db's verse=0) isolates the title for
   the ~64 psalms where Masoretic tradition gives it a separate verse (e.g. Psalm 3: "A Psalm of
   David, when he fled..." is verse 0; "LORD, how many are my foes" is verse 1). Ground truth,
   directly from the source text's own markup.
2. For the ~52 psalms Masoretic tradition merges into verse 1 (e.g. Psalm 23), BHSA's own CLAUSE
   segmentation reliably isolates the title as its own first clause — verified directly against
   the local BHSA text-fabric checkout for all 52 (e.g. Psalm 23:1 splits into clause "מזמור לדוד"
   + clause "יהוה רעי" + clause "לא אחסר"; Psalm 72:1's single-word title "לשלמה" is its own
   clause too). This is genuine ETCBC syntactic annotation, not a "superscription" *feature* (none
   exists — confirmed by direct search) and not an inference from surrounding text. The exact
   Strong's sequence for each of the 52 clauses was extracted once via BHSA + resources/
   occurrences/hbo.db (BHSA's own word-node ids, confirmed to match hbo.db's `node` column
   exactly) and committed as psalm_superscription_clauses.tsv — a static resource, not something
   re-derived at build time (the local BHSA text-fabric checkout is a heavy, occasional dependency
   unsuited to routine builds, same reasoning as bhsa-macula-bridge.db).

BSB-publishing/bsb-data-output's `headings.jsonl` `level:"d"` entries still do one job here: they
say WHICH psalms have a title at all (confirming both sources above cover all 116, and catching
the rare edge case neither source would reveal alone).

  python -m spine.superscriptions      # standalone check: prints coverage counts, no db writes
"""
from __future__ import annotations

import csv
import json
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Pinned independently of shoresh/interlinear/fetch.py's own BSB_DATA_OUTPUT_COMMIT (same upstream
# repo, different purpose — translation text/headings display vs. this structural flag). A few
# commits of drift between the two pins is harmless; re-pin this one deliberately on its own
# schedule, same discipline as every other fetch in this codebase.
HEADINGS_COMMIT = "90bab7c30aff44693f059be5cfd5813d66bba8a7"
HEADINGS_URL = "https://raw.githubusercontent.com/BSB-publishing/bsb-data-output/{commit}/base/headings.jsonl"
HEADINGS_PATH = HERE / "data" / "bsb-headings.jsonl"

# Committed resource (NOT gitignored/fetched) — see this module's docstring for how it was built.
CLAUSE_VOCAB_PATH = HERE / "psalm_superscription_clauses.tsv"

_STRONG_DIGITS = re.compile(r"\d+")


def fetch_headings(commit: str | None = None) -> Path:
    """Download base/headings.jsonl at a pinned commit. Idempotent — a commit-stamped marker file
    skips re-download if already present at that exact pin."""
    commit = commit or HEADINGS_COMMIT
    marker = HEADINGS_PATH.with_suffix(".commit")
    if HEADINGS_PATH.exists() and marker.exists() and marker.read_text().strip() == commit:
        return HEADINGS_PATH
    HEADINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(HEADINGS_URL.format(commit=commit), HEADINGS_PATH)
    marker.write_text(commit)
    return HEADINGS_PATH


def psalms_with_superscription(headings_path: Path | None = None) -> set[int]:
    """Psalm chapters with a genuine title heading — BSB's `level:"d"`, `before_v==2`.
    `before_v==1` entries are book-division labels ("Psalms 1-41", "Psalms 107-150"), not titles —
    confirmed only 2 of 121 `level:"d"` PSA headings have before_v==1, both book-division text."""
    path = headings_path or HEADINGS_PATH
    chapters: set[int] = set()
    if not path.exists():
        return chapters
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            h = json.loads(line)
            if h.get("b") == "PSA" and h.get("level") == "d" and h.get("before_v") == 2:
                chapters.add(h["c"])
    return chapters


def load_clause_vocab(path: Path | None = None) -> dict[int, set[int]]:
    """{chapter: {strong, ...}} from the committed BHSA-clause-derived resource — the exact,
    non-blank Strong's numbers of each of the 52 merged-title psalms' superscription clause.
    Bound-morpheme prefix nodes (BHSA splits ל/ה/ב/ו into their own word nodes, same as MACULA)
    are blank in the source TSV and skipped here — see classify_leading_run's own bound-morpheme
    handling for how a *different* tokenization (MACULA's) passes through them instead."""
    path = path or CLAUSE_VOCAB_PATH
    out: dict[int, set[int]] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            strongs = set()
            for s in row["strong_sequence"].split(","):
                s = s.strip()
                if s:
                    m = _STRONG_DIGITS.search(s)
                    if m:
                        strongs.add(int(m.group()))
            if strongs:
                out[int(row["chapter"])] = strongs
    return out


def classify_leading_run(tokens: list[tuple[int, int | None, bool]], vocab: set[int]) -> set[int]:
    """Core algorithm, shared across producers with different tokenizations (spine.db, MACULA's
    finer sub-word tokens — the two don't share an `idx` scheme, so this operates on whichever
    (idx, strong, is_bound_morpheme) triples a caller hands it for ONE verse, not on a specific
    schema).

    `tokens`: [(idx, strong, is_bound_morpheme), ...] for a single verse (any order). `vocab` is
    the EXACT, trustworthy Strong's set for that specific chapter's title (from verse=0 or
    load_clause_vocab — never a cross-chapter frequency-filtered guess).
    `is_bound_morpheme`: True for a token that's a grammatical prefix/suffix split into its own
    row rather than fused onto its content word (MACULA's and BHSA's tokenization does this — a
    preposition like ל/"of" gets its own row with no lexical Strong's of its own; spine.db fuses
    these, so its caller always passes False). Such a token doesn't need to be in `vocab` itself —
    it's transparently included as long as the very next token is.

    Returns the set of idx values in the title's leading run: walk from the lowest idx while
    strong is in `vocab` (or the token is a bound morpheme immediately followed by one that is) —
    stop at the first token that's neither."""
    ordered = sorted(tokens, key=lambda t: t[0])
    flagged: set[int] = set()
    for i, (idx, strong, bound) in enumerate(ordered):
        if strong in vocab:
            flagged.add(idx)
        elif bound and i + 1 < len(ordered) and ordered[i + 1][1] in vocab:
            flagged.add(idx)
        else:
            break
    return flagged


def all_chapter_vocab(spine_db_path: Path) -> dict[int, set[int]]:
    """{chapter: {strong, ...}} covering all ~116 titled psalms — spine.db's own verse=0 ground
    truth (vocab_from_spine_db) for the ~64 UHB splits, merged with load_clause_vocab's BHSA-clause
    ground truth for the ~52 merged-into-verse-1 psalms neither source alone covers."""
    merged = dict(load_clause_vocab())
    merged.update(vocab_from_spine_db(spine_db_path))  # verse=0 takes priority where both exist
    return merged


def mark_superscriptions(records: list) -> None:
    """Mutate `records` (spine.parse.SpineWord instances) in place, setting `is_superscription`
    for Psalm title tokens. No-ops (no network fetch) if `records` has no PSA words. Two cases per
    titled chapter:
    - verse==0 already present (UHB's own `\\d` split, e.g. Psalm 3): mark all of it directly.
    - no verse==0 (title merged into verse 1, e.g. Psalm 23): mark the leading run of verse==1
      tokens whose Strong's number is in that SPECIFIC chapter's BHSA-clause-derived exact
      vocabulary (load_clause_vocab) — never a cross-chapter guess."""
    psa = [w for w in records if w.book == "PSA"]
    if not psa:
        return

    fetch_headings()
    titled = psalms_with_superscription()
    if not titled:
        return

    clause_vocab = load_clause_vocab()
    has_verse0 = {w.chapter for w in psa if w.verse == 0}

    for w in psa:
        if w.chapter in titled and w.verse == 0:
            w.is_superscription = True

    verse1_by_chapter: dict[int, list] = {}
    for w in psa:
        if w.verse == 1 and w.chapter in titled and w.chapter not in has_verse0:
            verse1_by_chapter.setdefault(w.chapter, []).append(w)

    for chapter, words in verse1_by_chapter.items():
        vocab = clause_vocab.get(chapter)
        if not vocab:
            continue  # no ground truth for this chapter — leave unflagged, don't guess
        by_idx = {w.index: w for w in words}
        flagged = classify_leading_run([(w.index, w.strong, False) for w in words], vocab)
        for idx in flagged:
            by_idx[idx].is_superscription = True


def vocab_from_spine_db(spine_db_path: Path) -> dict[int, set[int]]:
    """{chapter: {strong, ...}} — the EXACT Strong's set for every psalm where spine.db's
    superscription flag came from UHB's own verse=0 marker (built by spine.parse, which runs
    before this), i.e. ground truth, not inferred."""
    import sqlite3
    if not spine_db_path.exists():
        return {}
    con = sqlite3.connect(f"file:{spine_db_path}?mode=ro", uri=True)
    reliable_by_chapter: dict[int, set[int]] = {}
    for chapter, strong in con.execute(
        "SELECT chapter, strong FROM spine_words WHERE book='PSA' AND verse=0 AND strong IS NOT NULL"
    ):
        reliable_by_chapter.setdefault(chapter, set()).add(strong)
    con.close()
    return reliable_by_chapter


if __name__ == "__main__":
    fetch_headings()
    titled = psalms_with_superscription()
    clause_vocab = load_clause_vocab()
    print(f"[spine] {len(titled)} psalms with a genuine title heading", file=sys.stderr)
    print(f"[spine] {len(clause_vocab)} covered by the BHSA-clause resource (merged-verse case)",
          file=sys.stderr)
