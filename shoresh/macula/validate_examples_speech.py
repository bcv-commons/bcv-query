"""The validator's own build of the review-free speech layers (SPEC 1.1, section 10 "speech"; D10).

    shoresh/.venv/bin/python -I shoresh/macula/validate_examples_speech.py hbo|grc|hbo-review <out folder>

Written for validate_examples.py, apart from the builders (it imports none of the examples_* modules). It runs our
published speech tools themselves:
- hbo: build_speaker_layer.py --no-review, with its output folder and its character registry copy in <out folder>
  (Glyssen's CharacterVerse.txt copied from data/speaker-layer/_cache; no network). Writes quotations.tsv and
  segments/<BOOK>.tsv there.
- grc: the speech fields of build_nt_clause_layout.py (load_quotations, greek_speakers.find) with no review row
  (greek_speakers.REVIEW points at a file that does not exist; the registry is copied). Writes quotations.tsv:
  id, start, end, speaker_id.
Nothing outside <out folder> is written.
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHORESH = HERE.parent
REPO = SHORESH.parent


def hbo(out, review=False):
    sys.path.insert(0, str(SHORESH))
    from macula import build_speaker_layer as B
    (out / "_cache").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HERE / "data" / "speaker-layer" / "_cache" / "CharacterVerse.txt", out / "_cache" / "CharacterVerse.txt")
    shutil.copyfile(REPO / "resources" / "speaker_layer" / "characters.tsv", out / "registry.tsv")
    B.OUT = out
    B.CHARACTERS = out / "registry.tsv"
    sys.argv = ["build_speaker_layer.py"] + ([] if review else ["--no-review"])
    B.main()


def hbo_review(out):
    """Stage 17 (D10m): the reviewed layer, review rows applied."""
    hbo(out, review=True)


def grc(out):
    sys.path.insert(0, str(SHORESH))
    import trees_macula
    from macula import build_nt_clause_layout as L
    from macula import greek_speakers as G
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO / "resources" / "speaker_quotations" / "nt_characters.tsv", out / "registry.tsv")
    G.CHARACTERS = out / "registry.tsv"
    G.REVIEW = out / "absent-review.tsv"
    if G.REVIEW.exists():
        raise SystemExit(f"{G.REVIEW} must not exist")
    con = trees_macula._con()
    quotes = L.load_quotations()
    mood = dict(con.execute("SELECT w.key, s.mood FROM words w JOIN sp.spine_words s ON s.key=w.key "
                            "WHERE w.corpus='grc' AND w.class='verb'").fetchall())
    lemma = dict(con.execute("SELECT key, lemma FROM words WHERE corpus='grc'").fetchall())
    L.close_gaps(quotes, sorted(lemma), lemma, mood)        # the layout's own step before the speakers
    speakers, _ = G.find(quotes, con)
    with open(out / "quotations.tsv", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("id\tstart\tend\tspeaker_id\n")
        for book in sorted(quotes):
            for q in sorted(quotes[book], key=lambda x: x["id"]):
                fh.write(f"{q['id']}\t{q['start']}\t{q['end']}\t{speakers[q['id']]['speaker_id'] or ''}\n")


if __name__ == "__main__":
    lang, folder = sys.argv[1], Path(sys.argv[2]).resolve()
    if "source-examples" not in folder.parts:
        raise SystemExit("the output folder must lie under shoresh/macula/data/source-examples/")
    {"hbo": hbo, "grc": grc, "hbo-review": hbo_review}[lang](folder)
