"""Reader language -> numbering scheme, and its use in the passage card / verse tool."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import original_words  # noqa: E402
from server import versification  # noqa: E402


INDEX = {"l": {"eng/KJV": "eng", "eng/BSB": "eng", "rus/SYN": "rso", "rus/B": "rso", "fra/A": "org", "fra/B": "eng", "fra/C": "eng", "xxx/Z": "undetermined"}}


@pytest.fixture()
def vers(monkeypatch):
    monkeypatch.setattr(versification, "_index", lambda: INDEX)
    return versification


def test_the_scheme_comes_from_bibles_edition_index_and_says_how_sure_it_is(vers):
    assert vers.scheme_for_lang("en") == {"scheme": "eng", "assumed": False, "editions": 2, "agreement": 1.0}
    assert vers.scheme_for_lang(None)["scheme"] == "eng"                  # no language = the default reader
    ru, rus = vers.scheme_for_lang("ru"), vers.scheme_for_lang("rus")     # 639-1 and 639-3 are the same language
    assert ru == rus and ru["scheme"] == "rso" and not ru["assumed"]
    fr = vers.scheme_for_lang("fr")                                       # editions of one language disagree: majority, with the agreement shown
    assert fr["scheme"] == "eng" and fr["editions"] == 3 and fr["agreement"] == 0.67


def test_a_language_without_a_classified_edition_is_flagged_assumed(vers):
    for lang in ("de", "xxx", "zz"):
        assert vers.scheme_for_lang(lang) == {"scheme": "eng", "assumed": True, "editions": 0, "agreement": None}, lang


def test_verse_interlinear_passes_the_scheme_and_returns_what_shoresh_served(monkeypatch):
    seen = {}

    class FakeResp:
        status_code = 200
        def json(self):
            return {"spine": {"language": "hbo", "words": [{"surface": "x", "strong": "H1"}]}, "lxx": {"words": []},
                    "versification": {"requested": "rso", "hebrew": ["PSA 3:1"], "lxx": ["PSA 3:1"]}}

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, path, params=None):
            seen["path"], seen["params"] = path, params
            return FakeResp()

    monkeypatch.setattr(original_words, "SHORESH_URL", "http://shoresh")
    monkeypatch.setattr(original_words.httpx, "Client", FakeClient)
    out = original_words.verse_interlinear("PSA", 3, 1, "Russian", "rso")
    assert seen["path"] == "/verse/PSA/3/1" and seen["params"]["versification"] == "rso"
    assert out["versification"]["hebrew"] == ["PSA 3:1"]
    original_words.verse_interlinear("PSA", 3, 1, "English")
    assert "versification" not in seen["params"]                  # nothing sent when the caller has no scheme


def test_the_shoresh_reference_format_converts_to_bbcccvvv():
    from server.cards import _ref_bb
    assert _ref_bb("PSA 3:2") == 19003002
    with pytest.raises(ValueError):                              # an English "title" is never what shoresh serves: it comes back as Hebrew 1-2
        _ref_bb("PSA 51:title")
