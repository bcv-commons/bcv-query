"""Speech sources of stage 06 (SPEC 1.0, D10), rebuilt without review rows into the build's cache.

    shoresh/.venv/bin/python -I shoresh/macula/examples_speech_src.py hbo|grc|hbo-review <out folder>

hbo-review (stage 17, D10m): the hbo run with the review rows applied (no --no-review).

hbo: runs `build_speaker_layer.py --no-review` with its output folder set to <out folder> (it writes quotations.tsv,
segments/<BOOK>.tsv, report.md, _work/ there, never in data/speaker-layer). Two of its paths are redirected so that
nothing outside <out folder> is written: Glyssen's CharacterVerse.txt is copied from data/speaker-layer/_cache (no
network), and the character registry (resources/speaker_layer/characters.tsv) is copied fresh into <out folder>, where
the builder may append ids for labels it has not seen.

grc: computes the speech fields of the Greek layout the way build_nt_clause_layout.py does (load_quotations,
close_gaps, greek_speakers.find), with greek_speakers.REVIEW pointed at a file that does not exist (so no review row is
applied) and the registry resources/speaker_quotations/nt_characters.tsv copied fresh into <out folder>. Writes
<out folder>/quotations.tsv: id, start, end, level (1 = outermost), parent, speaker_id.

Both runs are deterministic: the copies are made anew from the same files every time. A file present in the output
folder from an earlier run is overwritten (the builder writes each file anew).
"""
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHORESH = HERE.parent
REPO = SHORESH.parent


def run_hbo(out, review=False):
    sys.path.insert(0, str(SHORESH))
    from macula import build_speaker_layer as B
    out.mkdir(parents=True, exist_ok=True)
    (out / "_cache").mkdir(exist_ok=True)
    shutil.copyfile(SHORESH / "macula" / "data" / "speaker-layer" / "_cache" / "CharacterVerse.txt",
                    out / "_cache" / "CharacterVerse.txt")
    shutil.copyfile(REPO / "resources" / "speaker_layer" / "characters.tsv", out / "characters-registry.tsv")
    B.OUT = out
    B.CHARACTERS = out / "characters-registry.tsv"
    sys.argv = ["build_speaker_layer.py"] + ([] if review else ["--no-review"])
    B.main()


def run_hbo_review(out):
    """Stage 17 (D10m): the same run with the review rows (resources/speaker_layer/review.tsv) applied."""
    run_hbo(out, review=True)


def run_grc(out):
    sys.path.insert(0, str(SHORESH))
    import trees_macula
    from macula import build_nt_clause_layout as L
    from macula import greek_speakers as G
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO / "resources" / "speaker_quotations" / "nt_characters.tsv", out / "nt-characters-registry.tsv")
    G.CHARACTERS = out / "nt-characters-registry.tsv"
    G.REVIEW = out / "no-review-rows.tsv"          # does not exist: greek_speakers.review() then gives {}
    if G.REVIEW.exists():
        raise SystemExit(f"{G.REVIEW} must not exist")
    con = trees_macula._con()
    mood = dict(con.execute("SELECT w.key, s.mood FROM words w JOIN sp.spine_words s ON s.key=w.key WHERE w.corpus='grc' "
                            "AND w.class='verb'").fetchall())
    quotes = L.load_quotations()
    lemma = dict(con.execute("SELECT key, lemma FROM words WHERE corpus='grc'").fetchall())
    joined = L.close_gaps(quotes, sorted(lemma), lemma, mood)
    speakers, _ = G.find(quotes, con)
    rows = []
    for book in sorted(quotes):
        for q in quotes[book]:
            chain = L.chain_of(q["start"], quotes)
            # the quotations around q: those of its start's chain that also hold its end, outermost first
            around = [c for c in chain if c != q["id"]]
            byid = {x["id"]: x for x in quotes[book]}
            around = [c for c in around if byid[c]["end"] >= q["end"]]
            rows.append((q["id"], q["start"], q["end"], len(around) + 1, around[-1] if around else "",
                         speakers[q["id"]]["speaker_id"] or ""))
    rows.sort()
    with open(out / "quotations.tsv", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("id\tstart\tend\tlevel\tparent\tspeaker_id\n")
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")
    with open(out / "run.txt", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"quotations\t{len(rows)}\njoined_over_a_gap\t{joined}\n")


if __name__ == "__main__":
    lang, folder = sys.argv[1], Path(sys.argv[2]).resolve()
    if not str(folder).startswith(str(SHORESH / "macula" / "data" / "source-examples") + os.sep):
        raise SystemExit("the output folder must lie under shoresh/macula/data/source-examples/")
    {"hbo": run_hbo, "grc": run_grc, "hbo-review": run_hbo_review}[lang](folder)
