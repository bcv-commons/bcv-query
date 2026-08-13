#!/usr/bin/env python3
"""LXX-only Greek lexemes — words with no Strong's number, grouped into (lemma, variants).

93% of the LXX (Rahlfs 1935, via lxx.db) carries a Strong's number; the remaining ~7% never occurs
in the NT, so Strong's numbering (which only covers NT-catalogued words) has no code for them —
karnbibeln.se's own example is Genesis 1:2's ἀκατασκεύαστος. Their Strong's-scoped lexicon has
nowhere to link these words to.

VALIDATED 2026-08 (see lxx/parse.py's module docstring): the LXX source format carries a `wordid`
per token that reliably groups inflected forms of the same lemma — including on words with no
Strong's, where it's the only lemma-grouping signal available. This script groups the untagged
content words by `wordid` and derives a citation (dictionary-headword) form per group from the
attested morphology:
  - nouns/adjectives: prefer nominative singular (any gender) — the standard Greek lexicon headword
    case/number.
  - verbs: prefer present active indicative 1st singular (PAI1S) — the standard Greek lexicon
    citation form; falls down a fixed priority list (present/aorist, indicative before infinitive,
    active before middle/passive, 1st singular before 3rd) when PAI1S isn't attested in this corpus,
    since most of the ~9.5k lemma groups here are rare words unlikely to happen to occur in exactly
    that one form. `citation_confidence=standard` means the chosen form is SOMEWHERE on that
    priority list (a recognizable lexicon-headword-shaped form, even if not literally PAI1S);
    `fallback` means nothing on the list was attested at all and the most frequent attested form was
    used regardless of shape (e.g. a bare participle) — those are the groups worth a lexicographer's
    eye before publishing citation forms as-is.

  python -m lxx.build_orphan_lexemes
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DB_PATH = HERE / "lxx.db"
OUT = ROOT / "resources" / "lxx_orphan_lexemes" / "lexemes.tsv"

# Priority order for picking a verb citation form (best first). PAI1S is the classic Greek lexicon
# headword; the rest are fallbacks roughly in "how close to a headword" order.
_VERB_PRIORITY = [
    "PAI1S", "PMI1S", "PPI1S",              # present indicative, 1st singular (active/mid/pass)
    "PAI3S", "PMI3S", "PPI3S",              # present indicative, 3rd singular
    "PAN", "PMN", "PPN",                    # present infinitive
    "AAI1S", "AMI1S", "API1S",              # aorist indicative, 1st singular
    "AAI3S", "AMI3S", "API3S",              # aorist indicative, 3rd singular
    "AAN", "AMN", "APN",                    # aorist infinitive
]
_VERB_PRIORITY_RANK = {suffix: i for i, suffix in enumerate(_VERB_PRIORITY)}


def _citation(pos: str, variants: list[tuple]) -> tuple[str, str, str]:
    """variants: [(surface, plain, morph, count)] -> (citation_surface, citation_morph, confidence)."""
    if pos in ("N", "A"):
        nom_sg = [v for v in variants if len(v[2]) >= 4 and v[2][2:4] == "NS"]
        pool, confidence = (nom_sg, "standard") if nom_sg else (variants, "fallback")
        best = max(pool, key=lambda v: v[3])
        return best[0], best[2], confidence
    if pos == "V":
        ranked = sorted(
            variants,
            key=lambda v: (_VERB_PRIORITY_RANK.get(v[2][2:], len(_VERB_PRIORITY)), -v[3]),
        )
        best = ranked[0]
        confidence = "standard" if best[2][2:] in _VERB_PRIORITY_RANK else "fallback"
        return best[0], best[2], confidence
    best = max(variants, key=lambda v: v[3])
    return best[0], best[2], "fallback"


def build(db_path: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT wordid, surface, plain, morph, pos, book, chapter, verse FROM lxx_words "
        "WHERE strong IS NULL AND is_content=1 AND wordid IS NOT NULL "
        "ORDER BY wordid").fetchall()
    con.close()

    groups: dict[int, dict] = {}
    for r in rows:
        g = groups.setdefault(r["wordid"], {
            "pos": r["pos"], "variants": collections.OrderedDict(),
        })
        key = (r["surface"], r["plain"], r["morph"])
        v = g["variants"].setdefault(key, {"count": 0, "ref": f"{r['book']} {r['chapter']}:{r['verse']}"})
        v["count"] += 1

    out = []
    for wordid, g in groups.items():
        variants = [(surf, plain, morph, v["count"]) for (surf, plain, morph), v in g["variants"].items()]
        citation_surface, citation_morph, confidence = _citation(g["pos"], variants)
        for (surf, plain, morph), v in g["variants"].items():
            out.append({
                "wordid": wordid, "citation_form": citation_surface, "citation_morph": citation_morph,
                "pos": g["pos"], "citation_confidence": confidence,
                "variant_surface": surf, "variant_plain": plain, "variant_morph": morph,
                "count": v["count"], "sample_ref": v["ref"],
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    rows = build(args.db)
    n_groups = len({r["wordid"] for r in rows})
    n_standard = len({r["wordid"] for r in rows if r["citation_confidence"] == "standard"})
    print(f"[orphan-lexemes] {n_groups:,} lemma groups ({n_standard:,} standard citation-form, "
          f"{n_groups - n_standard:,} fallback), {len(rows):,} variant rows", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# LXX-only Greek lexemes (no Strong's number) grouped by wordid (validated per-lemma\n"
                 "# key, see lxx/parse.py) into a citation form + all attested inflected variants, with\n"
                 "# per-variant occurrence count + a sample verse ref. citation_confidence=standard means\n"
                 "# the chosen form is on a fixed priority list of lexicon-headword-shaped forms (nom.\n"
                 "# singular for nouns/adjectives; for verbs, present/aorist indicative or infinitive,\n"
                 "# preferring active + 1st singular, even if not literally the ideal PAI1S); fallback\n"
                 "# means nothing on that list was attested and the most frequent form was used regardless\n"
                 "# of shape — worth a lexicographer's eye before treating as a final headword.\n"
                 "# CATSS-derived (non-commercial) — see shoresh/legal/CATSS-user-declaration.md.\n"
                 "# See shoresh/lxx/build_orphan_lexemes.py.\n")
        fh.write("wordid\tcitation_form\tcitation_morph\tpos\tcitation_confidence\t"
                 "variant_surface\tvariant_plain\tvariant_morph\tcount\tsample_ref\n")
        for r in sorted(rows, key=lambda r: (r["wordid"], -r["count"])):
            fh.write("\t".join(str(r[k]) for k in (
                "wordid", "citation_form", "citation_morph", "pos", "citation_confidence",
                "variant_surface", "variant_plain", "variant_morph", "count", "sample_ref")) + "\n")
    print(f"[orphan-lexemes] -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
