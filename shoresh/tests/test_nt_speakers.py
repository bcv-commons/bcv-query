"""NT clause layout speakers (v0.6): the hand review and groups, pinned to places (skipped where the layout is not built)."""
import json
from pathlib import Path

import pytest

OUT = Path(__file__).resolve().parents[1] / "macula" / "data" / "nt-clause-layout" / "clauses"
pytestmark = pytest.mark.skipif(not OUT.exists(), reason="NT clause layout not built (python -m macula.build_nt_clause_layout)")


def speech(book: str, quotation: str) -> dict:
    ch = int(quotation[2:5])
    for line in (OUT / book / f"{book}_{ch:03d}.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["quotation"] == quotation:
            return r
    raise AssertionError(f"no segment of speech {quotation}")


def test_label_fixed_by_review():
    pilate = speech("MAT", "40027022005")["speaker_id"]           # λέγει αὐτοῖς ὁ Πειλᾶτος (the speaker data: the crowd)
    assert speech("MRK", "41015002006")["speaker_id"] == pilate    # ἐπηρώτησεν αὐτὸν ὁ Πειλᾶτος (the speaker data: Jesus)
    assert speech("MRK", "41006024012")["speaker_name"] == "Ἡρῳδιάς"   # the speaker data swaps mother and daughter


def test_wrong_inquit_fixed_by_review():
    r = speech("LUK", "42003004009")                               # ὡς γέγραπται ἐν βίβλῳ λόγων Ἠσαΐου
    assert r["speaker"] == "Ἠσαΐας" and r["speaker_basis"] == "review"


def test_group_with_members():
    r = speech("MRK", "41010035012")                               # Ἰάκωβος καὶ Ἰωάνης ... λέγοντες
    john = speech("MRK", "41009038005")["speaker_id"]              # ἔφη αὐτῷ ὁ Ἰωάνης (the apostle, not the Baptist)
    assert r["speaker_name"] is None and r["speaker_members"] == [john]      # James never speaks alone in Mark
    assert speech("MRK", "41010037005")["speaker_id"] == r["speaker_id"]   # οἱ δὲ εἶπαν: the same two, by review
