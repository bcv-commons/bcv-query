"""Psalm superscription detection — marks which spine.db tokens belong to a Psalm's title
(e.g. "A Psalm of David") rather than its actual body content.

Two already-available sources combine to make this both accurate and cheap — neither alone is
enough:

1. UHB's own USFM `\\d` marker (parsed by parse.py into spine.db's verse=0) already isolates the
   title for the ~64 psalms where Masoretic tradition gives it a separate verse (e.g. Psalm 3:
   "A Psalm of David, when he fled..." is verse 0; "LORD, how many are my foes" is verse 1). But
   it only covers about half of titled psalms.
2. BSB-publishing/bsb-data-output's `headings.jsonl` `level:"d"` entries are a purpose-built,
   versification-independent superscription tag (confirmed: covers both the UHB-split case AND
   the merged case, e.g. Psalm 23, where UHB's own verse 1 contains BOTH the title and "The LORD
   is my shepherd" with no verse 0 at all — see internal-docs/gbt-alignment-handover.md). This
   tells us WHICH psalms have a title, but not where it ends within a merged verse 1.

Combined: for a titled psalm with no verse=0, the title's own vocabulary — built empirically from
the already-known verse=0 tokens of OTHER psalms, not hand-transcribed Hebrew — lets us find the
leading run of verse=1 tokens that belong to the title without guessing at spelling.

  python -m spine.superscriptions      # standalone check: prints coverage counts, no db writes
"""
from __future__ import annotations

import json
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


# Minimum number of DISTINCT psalms a Strong's number must appear in (at verse==0) to count as
# genuine superscription vocabulary, not an incidental word from a longer narrative-style title
# (e.g. Psalm 18's "...Of David the servant of the LORD, who sang to the LORD..."). Verified: with
# this threshold, "the LORD" (H3068, appears in only 4 titles) is correctly excluded — it would
# otherwise false-positive-match the start of Psalm 23's real content ("The LORD is my shepherd").
# Every formulaic term (מזמור/לדוד/למנצח/משכיל/נגינות/לאסף/לבני קרח/...) clears this easily (5-50
# psalms); one-off narrative words from the handful of longer historical titles don't.
MIN_TITLE_CHAPTERS = 5


def mark_superscriptions(records: list) -> None:
    """Mutate `records` (spine.parse.SpineWord instances) in place, setting `is_superscription`
    for Psalm title tokens. No-ops (no network fetch) if `records` has no PSA words. Two cases per
    titled chapter:
    - verse==0 already present (UHB's own `\\d` split, e.g. Psalm 3): mark all of it.
    - no verse==0 (title merged into verse 1, e.g. Psalm 23): mark the leading run of verse==1
      tokens whose Strong's number is in the vocabulary observed across MIN_TITLE_CHAPTERS+ other
      psalms' verse==0 — stop at the first token outside that vocabulary (the start of real
      content)."""
    psa = [w for w in records if w.book == "PSA"]
    if not psa:
        return

    fetch_headings()
    titled = psalms_with_superscription()
    if not titled:
        return

    chapters_by_strong: dict[int, set[int]] = {}
    for w in psa:
        if w.verse == 0 and w.strong is not None:
            chapters_by_strong.setdefault(w.strong, set()).add(w.chapter)
    vocab = {s for s, chapters in chapters_by_strong.items() if len(chapters) >= MIN_TITLE_CHAPTERS}
    has_verse0 = {w.chapter for w in psa if w.verse == 0}

    for w in psa:
        if w.chapter in titled and w.verse == 0:
            w.is_superscription = True

    verse1_by_chapter: dict[int, list] = {}
    for w in psa:
        if w.verse == 1 and w.chapter in titled and w.chapter not in has_verse0:
            verse1_by_chapter.setdefault(w.chapter, []).append(w)

    for chapter, words in verse1_by_chapter.items():
        ordered = sorted(words, key=lambda w: w.index)
        start = 0
        # Tolerate exactly one unrecognized leading token if immediately followed by a
        # recognized one — a rare genre-designation word before a common author attribution
        # (e.g. Psalm 17/86 "A Prayer of David": תפלה/"prayer" appears in only 3 titles, below
        # MIN_TITLE_CHAPTERS, but the לדוד/"of David" right after it clears it easily).
        if ordered and ordered[0].strong not in vocab and len(ordered) > 1 and ordered[1].strong in vocab:
            ordered[0].is_superscription = True
            start = 1
        for w in ordered[start:]:
            if w.strong in vocab:
                w.is_superscription = True
            else:
                break


if __name__ == "__main__":
    fetch_headings()
    titled = psalms_with_superscription()
    print(f"[spine] {len(titled)} psalms with a genuine title heading", file=sys.stderr)
