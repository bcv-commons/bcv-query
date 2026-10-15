"""Speaker data (resources/speaker_quotations, built by bcv-RAG/scripts/build_speaker_quotations.py): word spans, the partial-verse
flag, English verse numbering and the source/licence block on every speaker endpoint.
  bcv-RAG/.venv/bin/python -m pytest shoresh/tests/test_speakers.py -q
Skips when the TSV is absent or still the verse-only build."""
import sys
from pathlib import Path

import pytest

SHORESH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHORESH))
import data  # noqa: E402

HAVE = data.SPEAKER_TSV.exists() and "word_start" in data.SPEAKER_TSV.read_text(encoding="utf-8")[:2000]
pytestmark = pytest.mark.skipif(not HAVE, reason="speaker_quotations.tsv with word spans not built")


def _hits(book, ch, v):
    return data.speakers_at(book, ch, v)["speakers"]


def test_speech_after_its_frame_is_partial():
    # GEN 1:3: "וַיֹּאמֶר אֱלֹהִים" frames the speech, "וַיְהִי־אוֹר" follows it; the verse is only partly God's words.
    (h,) = _hits("GEN", 1, 3)
    assert h["speaker"] == "God" and h["divine"]
    assert (h["word_start"], h["word_end"]) == ("o010010030031", "o010010030041")
    assert h["partial"] is True


def test_verse_inside_a_long_speech_is_whole():
    (h,) = [h for h in _hits("JHN", 3, 16) if h["speaker"] == "Jesus"]
    assert h["partial"] is False and h["start"] < ("JHN", 3, 16) < h["end"]


def test_verse_range_in_english_numbering():
    # MACULA EXO 7:26 (Hebrew numbering) is English EXO 8:1.
    (h,) = _hits("EXO", 8, 1)
    assert h["word_start"].startswith("o02007026") and h["start_bbcccvvv"] == 2008001


def test_source_and_licence_on_every_endpoint():
    for out in (data.speakers_list(), data.speaker_ranges("God", limit=1), data.speakers_at("GEN", 1, 3),
                data.speakers_at("GEN", 1, 1)):
        assert out["source"]["license"] == "CC-BY-4.0"
        assert "Clear Bible" in out["source"]["attribution"]
