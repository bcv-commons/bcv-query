"""Package bcv-commons/aramaic-hebrew-equivalents: the Aramaic of the Tanakh linked to Hebrew, so tables keyed by Hebrew lexemes
(lexicons, renderings learned from translations, the Septuagint bridge) reach Daniel 2:4b-7:28, Ezra 4:8-6:18 and 7:12-26,
Jeremiah 10:11 and Genesis 31:47.

    cd shoresh && .venv/bin/python3 -m macula.release_aramaic --out DIR [--allow-dirty]

Rebuilds both tables (macula/build_aramaic_cognates.py, macula/build_aramaic_equivalents.py) and writes
DIR/data/{lexemes,words}.parquet, checks.md, README.md, build.json, SHA256SUMS. Nothing is uploaded. The single pick per word failed
research's rule-engine test (exact words under +1 point); the ranked lists are released for drafters that weigh several words
(the user, 2026-11-14), with their own check on the card.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import datetime
import hashlib
import io
import json
import re
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from macula import build_aramaic_cognates as C
from macula import build_aramaic_equivalents as E
from macula import release_guard  # refuses TBTA and private inputs

ROOT = Path(__file__).resolve().parents[2]
VERSION = "v0.1"
REPO = "bcv-commons/aramaic-hebrew-equivalents"
# measured by make-tanakh-research (track D, Daniel in its own fold; chrF3 on Daniel's 196 Aramaic verses; base -> with the table)
MEASURED_COGNATES = "Indonesian 27.96 -> 31.74, Swahili 25.78 -> 28.89, Tagalog 25.69 -> 28.78; Daniel's Hebrew verses unchanged"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


CARD = """---
license: cc-by-sa-4.0
language: [arc, hbo]
pretty_name: Aramaic to Hebrew equivalents in the Tanakh
tags: [bible, aramaic, hebrew, lexicon, cognates, daniel, ezra, translation]
configs:
- config_name: lexemes
  data_files: data/lexemes.parquet
- config_name: words
  data_files: data/words.parquet
---

# Aramaic to Hebrew equivalents ({v})

The Aramaic parts of the Tanakh (Daniel 2:4b-7:28, Ezra 4:8-6:18 and 7:12-26, Jeremiah 10:11, two words in Genesis 31:47) use
their own lexemes, with their own Strong's numbers. Whatever is known of a Hebrew word (its renderings in translations, the
Septuagint's Greek for it, a lexicon entry) does not reach its Aramaic counterpart. Above all, a Hebrew-Greek lexeme bridge (which
Greek lexemes render a Hebrew one, as used to align words across translations) has no entry for an Aramaic word, so an aligner gets
no Greek candidates for it. Two tables make that link, by rule, from the original-language sources only: through them an Aramaic
word takes the bridge entries, and anything else keyed by Hebrew lexemes, of its Hebrew counterparts.

## `lexemes`: the Hebrew cognate of each Aramaic lexeme ({nl:,} content lexemes, proper names left out)

| column | description |
|---|---|
| `aramaic_strong`, `aramaic_lemma`, `tokens` | the Aramaic lexeme (MACULA Hebrew, `wlang` A) and its content-word occurrences |
| `hebrew_strong`, `hebrew_lemma` | its Hebrew cognate |
| `basis` | `strongs`: Strong's dictionary says "(Aramaic) corresponding to" that Hebrew number; `strongs_shifted`: the same, "in the sense of" or "through the idea of" another meaning (same root, meaning moved: Aramaic שְׁכַח "find", Hebrew שָׁכַח "forget"; not for word choice); `strongs_root`: Strong's derives it "from" that root; `consonants`: no Strong's link, the same consonants after the regular shifts ד/ז, ת/שׁ, ט/צ, ע/צ, chosen by Septuagint overlap; empty: none |
| `greek_check`, `domain_check` | 1 / 0: whether the two share Septuagint Greek, and a UBS (SDBH) domain code; empty where either lacks one |

{lex_counts}

Only Strong's cross-reference numbers are read, never its English.

## `words`: Hebrew words of the same meaning, per Aramaic word ({nw:,} words)

A cognate does not always mean the same: Aramaic שְׁכַח is "find", Hebrew שָׁכַח "forget"; Aramaic פְּלַח "serve" matches Hebrew
עָבַד, not its cognate; many words (Persian titles, נוּר "fire", עִדָּן "time") have no Hebrew cognate in use. So each Aramaic content
word gets a ranked list of Hebrew words that can say the same thing at that place, synonyms and related words, of any length: one
word where one stands out, many where several compete. Their bridge entries together give an aligner the Greek (and, through
it, the translations' words) to look for.

- **Candidates**: Hebrew content lexemes of the same word class (noun and adjective counted together), with 2+ occurrences, that
  carry one of the word's UBS (SDBH) domains on at least 5 % of their own occurrences; and the cognate.
- **Score**: how typical that meaning is for the candidate (the share of its occurrences carrying the word's most specific domain
  codes, plus 0.3 x the share for any of its codes), times how often the Septuagint renders the candidate by the Greek at the place
  (MACULA's Greek link for the word, else the Greek verse: Theodotion for Daniel, GLAUx for Ezra), at least 0.01; the cognate's
  score x 1.5.
- **The list**: every candidate scoring at least {ratio} x the best, best first; a safety cap at 15.
- **The pick** (`hebrew_strong`): one word, for a rule engine. The cognate is kept where at least 30 % of its own occurrences carry
  the word's domain; otherwise the best equivalent with 10+ occurrences, carrying the domain on 20 % of its own.

| column | description |
|---|---|
| `key` | the MACULA Hebrew word id |
| `aramaic_strong`, `aramaic_lemma` | the Aramaic lexeme |
| `hebrew_strong`, `hebrew_lemma`, `basis` | the pick: `cognate` or `equivalent` |
| `evidence` | `cognate_meaning`, `greek_word`, `greek_verse` or `domain`: what decided the pick |
| `score`, `margin` | the pick's score, and its ratio to the next |
| `cognate_strong` | the cognate (`lexemes`, basis strongs or consonants) |
| `candidates`, `candidate_scores` | the ranked list (Hebrew Strong's numbers, space-separated, the pick first) and their scores |

Lists on the Aramaic words ({n_list:,} with one): mean length {a_mean}; a single word {a_one}; ten or more {a_ten}. A long list means
the evidence does not settle between the candidates, not that all are equally good.

## How good it is

- Where both lexemes have UBS domains, the plain `strongs` links share one {dom_strongs} of the time, `strongs_root` links only
  {dom_root}: use those as a fallback. The Greek check is weaker evidence, since the Old Greek of Daniel 3-6 is free.
- **In drafting** (a rule-based engine drafting Daniel's 196 Aramaic verses with Daniel held out of its training; chrF3), with the
  `strongs` and `consonants` links: {measured_cognates}. Adding `strongs_root`: a further +0.4 to +1.0. The share of Aramaic
  content words that get any word rises from 0.64 to 0.82. Exact word choice rises much less: the Hebrew cognate's usual rendering
  is often not the word a translation uses for the Aramaic.
- **The `words` lists, checked on Hebrew** (the same procedure on the Hebrew content words of Daniel and Ezra, each word hidden and
  no cognate given, so the lists must find the word itself): the word is on its list {on_list} of the time, lists averaging
  {mean_len} words, a single word {one} of the time; the single pick alone finds it {top1}. A near-synonym counts as a miss, so these are lower
  bounds. With the word standing in for its cognate, the pick finds the word itself {self_all} of the time ({n_self} words).
- **For the bridge** ({b_n:,} Aramaic words whose own Greek link MACULA records; that link hidden, the lists ranked from the Greek
  verse, the information an aligner has): the hidden Greek is among the bridge's Greek for the cognate alone {b_cog} of the time;
  for the list with the cognate {b_list} (a mean {b_len} Hebrew lexemes offered per word); for the single pick {b_pick}.
- **The pick in drafting** (the same engine and test, the pick in place of the cognate): exact content words +0.0 to +0.5 points
  and chrF3 +0.3 to +0.7, small. A rule engine that takes one word gains little from it; the lists serve the bridge and
  alignment.
- Known weak spots: some time words (night, season) rank "month" high; officials' titles map to the nearest Hebrew offices.
  No person has checked the tables.

## Licence

CC BY-SA 4.0. Built from MACULA Hebrew (CC BY 4.0), the UBS dictionary's senses and domains (CC BY-SA 4.0), Strong's Hebrew
dictionary (1890, public domain; OpenScriptures XML, CC BY 4.0), MACULA's Hebrew-Greek links and the Septuagint from GLAUx (CC BY-SA
4.0; Theodotion's Daniel, document 0527-057). Credit: MACULA (Clear Bible / Biblica), United Bible Societies, OpenScriptures, GLAUx
(KU Leuven), make-tanakh-research (the drafting measurements), and this dataset.
"""


def tally(rows: list[dict], col: str, label: str) -> str:
    t = {}
    for r in rows:
        t[r[col] or "(none)"] = t.get(r[col] or "(none)", 0) + 1
    return f"| `{label}` | rows |\n|---|---|\n" + "\n".join(f"| {k} | {v:,} |" for k, v in sorted(t.items(), key=lambda x: -x[1]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "shoresh/macula", "shoresh/lxx"], cwd=ROOT, text=True).strip()
    if dirty and not a.allow_dirty:
        raise SystemExit(f"uncommitted changes:\n{dirty}")
    commit = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=ROOT, text=True).strip() + ("+uncommitted" if dirty else "")
    import sys
    argv = sys.argv
    sys.argv = [argv[0]]
    with contextlib.redirect_stdout(io.StringIO()):
        C.main()
        E.main()
    sys.argv = argv
    lex = list(csv.DictReader(open(C.OUT / "cognates.tsv", encoding="utf-8"), delimiter="\t"))
    words = list(csv.DictReader(open(E.OUT / "words.tsv", encoding="utf-8"), delimiter="\t"))
    ck = (E.OUT / "checks.md").read_text(encoding="utf-8")
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "data").mkdir()
    for name, rows in (("lexemes", lex), ("words", words)):
        pq.write_table(pa.table({c: pa.array([r[c] for r in rows], type=pa.string()) for c in rows[0]}), a.out / f"data/{name}.parquet")
    def dom(b: str) -> str:
        s = [r["domain_check"] for r in lex if r["basis"] == b and r["domain_check"]]
        return f"{sum(x == '1' for x in s) / len(s):.2f}" if s else "?"
    def cell(first: str, col: int) -> str:
        for line in ck.splitlines():
            p = [x.strip() for x in line.strip("|").split("|")]
            if p and p[0] == first and len(p) > col:
                return p[col]
        return "?"
    alen = [len(r["candidates"].split()) for r in words if r["candidates"]]
    bridge_part = ck[ck.index("Bridge check"):]

    def bcell(first: str) -> str:
        for line in bridge_part.splitlines():
            p = [x.strip() for x in line.strip("|").split("|")]
            if len(p) == 2 and p[0] == first:
                return p[1]
        return "?"
    (a.out / "checks.md").write_text((C.OUT / "checks.md").read_text(encoding="utf-8") + "\n" + ck, encoding="utf-8")
    (a.out / "README.md").write_text(CARD.format(
        v=VERSION, nl=len(lex), nw=len(words), lex_counts=tally(lex, "basis", "basis"), dom_strongs=dom("strongs"),
        dom_root=dom("strongs_root"), measured_cognates=MEASURED_COGNATES, ratio=E.RATIO,
        on_list=cell(str(E.RATIO), 1), mean_len=cell(str(E.RATIO), 2), one=cell(str(E.RATIO), 3),
        top1=cell("no_prior", 3), self_all=cell("all", 3), n_self=cell("all", 1),
        a_mean=f"{sum(alen) / len(alen):.1f}", a_one=f"{sum(x == 1 for x in alen) / len(alen):.2f}",
        a_ten=f"{sum(x >= 10 for x in alen) / len(alen):.2f}", n_list=len(alen),
        b_n=int(re.search(r"Bridge check: ([\d,]+)", ck).group(1).replace(",", "")), b_cog=bcell("cognate"), b_pick=bcell("pick"),
        b_list=bcell("list_or_cognate"), b_len=re.search(r"offered \(list plus cognate\): (\d+\.\d+)", ck).group(1)), encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    meta = {"schema": 1, "version": VERSION, "repo": REPO, "built": datetime.date.today().isoformat(), "code": commit,
            "licence": "CC BY-SA 4.0", "rows": {"lexemes": len(lex), "words": len(words)},
            "strongs": f"{C.REPO}@{C.COMMIT}", "lxx_daniel": "GLAUx 0527-057 (Theodotion)", "list_ratio": E.RATIO,
            "not_read": ["BHSA", "TBTA", "English text"], "files": {str(p.relative_to(a.out)): sha256(p) for p in files}}
    (a.out / "build.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(a.out)}\n" for p in files), encoding="utf-8")
    print(f"{REPO} -> {a.out}: lexemes {len(lex):,}, words {len(words):,}; code {commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
