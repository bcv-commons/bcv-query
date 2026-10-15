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


def test_dialogue_reply_takes_its_own_speaker():
    # 1 SAM 3:6: one FCBH block is God's call and Samuel's answer; each quotation gets its own speaker.
    hits = {h["word_start"]: h for h in _hits("1SA", 3, 6)}
    assert hits["o090030060051"]["speaker"] == "God" and hits["o090030060051"]["speaker_basis"] == "referent"
    assert hits["o090030060121"]["speaker"] == "Samuel (boy)" and not hits["o090030060121"]["divine"]


def test_addressee_is_not_taken_as_speaker():
    # JER 15:20: Clear's referent is Jeremiah, the one addressed; Glyssen lists him only as a possible speaker.
    assert {h["speaker"] for h in _hits("JER", 15, 20)} == {"God"}


def test_casting_voice_gives_way_to_the_character():
    # GEN 16:9: FCBH voices "Yahweh's angel" with Jesus; the speaker is the angel, the block speaker stays recorded.
    (h,) = _hits("GEN", 16, 9)
    assert (h["speaker"], h["block_speaker"], h["speaker_basis"]) == ("Yahweh's angel", "Jesus", "character")


def test_group_speaker_with_slash_is_reachable():
    # /speakers lists group speakers such as "priests/Levites"; /speaker/{name:path} takes the rest of the path as the name.
    from fastapi.testclient import TestClient
    import app as shoresh_app
    names = [s["speaker"] for s in data.speakers_list()["speakers"] if "/" in s["speaker"]]
    assert names
    client = TestClient(shoresh_app.app)
    for name in names:
        r = client.get(f"/speaker/{name}")
        assert r.status_code == 200 and r.json()["count"] > 0, name
    assert client.get("/speaker/priests%2FLevites").status_code == 200


def test_hand_correction_gen_16_8():
    # The angel's question to Hagar (2nd person feminine) was under the source's Hagar block; corrections.tsv fixes it.
    hits = {h["word_start"]: h for h in _hits("GEN", 16, 8)}
    assert (hits["o010160080021"]["speaker"], hits["o010160080021"]["speaker_basis"]) == ("Yahweh's angel", "correction")
    assert hits["o010160080111"]["speaker"] == "Hagar, Sarai's maid"
