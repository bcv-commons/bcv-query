"""unfoldingWord Translation Notes as coded notes on MACULA's words: every note with a SupportReference, its issue code and the Hebrew
or Greek words its Quote names. No English is written: from a note only its ID, Reference, SupportReference, Quote and Occurrence are
read; the Quote finds the words (unfoldingword._Verse, the matcher passage facts use) and is not copied.

    python -m macula.build_translation_notes [--books GEN RUT ...] [--out DIR]

Out (default data/translation-notes/):
  notes.tsv   one row per note with a SupportReference: id, book, ref (the note's own, English numbering), code (tn.<article>),
              given (the SupportReference's article name where it was misspelt), occurrence, fit (exact | partial | unmatched),
              how (verse | range | front | all), first, last, words (MACULA keys; Hebrew: each word's first morpheme), cause, tag
  codes.tsv   each code with its Translation Academy article, counts, and the article's English title (the code table)
  checks.md   match rates overall, per language, per code, per book; unmatched causes with examples (references and codes only)
  build.json  source, counts, licence, code version

fit: "exact" = every quoted word found as a run (parts joined by '&' in order) at the note's Occurrence, after unfoldingword.norm
(letters only, no points, accents or case); "partial" = for a first occurrence, at least 80 % of the quoted words found in order.
how: "verse" = in the note's verse (passage facts reads only these); "range" = a note on a verse range found across the range;
"front" = a psalm title (Reference c:front) found in the Hebrew verses 1-2; "all" = Occurrence -1, every occurrence in the verse.
The text is CC BY-SA 4.0 (unfoldingWord); derivatives must not use the unfoldingWord name or mark.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from macula import unfoldingword as uw
from macula.build_passage_facts import TN_SLUGS, Book

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "translation-notes"
TA_CACHE = HERE / ".cache" / "unfoldingword" / f"en_ta_{uw.TAG}"
API = "https://git.door43.org/api/v1/repos/unfoldingWord/{repo}"
# SupportReference values that misspell an article (seen in en_tn master, 2026-11; none in v91) -> the article.
TYPOS = {"figs-ellpisis": "figs-ellipsis", "figs-metaphhor": "figs-metaphor", "figs-possesion": "figs-possession",
         "figs-abstractnoun": "figs-abstractnouns", "figs-quoteinquotes": "figs-quotesinquotes", "translate-number": "translate-numbers",
         "translate-alternatereadings": "translate-alternativereadings"}
CAUSES = {"no_quote": "the note has no Quote",
          "quote_not_original_language": "the Quote has no Hebrew or Greek letters (an English draft quote; not used)", "reference_not_verse": "the Reference is not a verse (intro)",
          "verse_absent": "no MACULA words in the verse(s) the Reference maps to",
          "occurrence_beyond": "the quoted run is in the verse, but fewer times than Occurrence",
          "token_in_neighbour": "a quoted word is not in the verse but in the next or previous one (versification)",
          "token_absent": "a quoted word form is not in the verse (text or spelling differs from MACULA's)",
          "order_or_gap": "all quoted words are in the verse, but not as runs in the quoted order (fuzzy match below 80 %)"}


def _get(url: str) -> bytes:
    return urllib.request.urlopen(url, timeout=120).read()


def ta_articles() -> dict[str, str]:
    """Translation Academy (same tag): slug -> 'category/slug' for the translate and checking manuals, cached."""
    f = TA_CACHE / "articles.tsv"
    if not f.exists():
        TA_CACHE.mkdir(parents=True, exist_ok=True)
        rows = []
        for cat in ("translate", "checking"):
            for d in json.loads(_get(API.format(repo="en_ta") + f"/contents/{cat}?ref={uw.TAG}")):
                if d["type"] == "dir":
                    rows.append(f"{d['name']}\t{cat}/{d['name']}")
        f.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return dict(l.split("\t") for l in f.read_text(encoding="utf-8").splitlines() if l)


def ta_title(path: str) -> str:
    """An article's title (its title.md), cached."""
    f = TA_CACHE / (path.replace("/", "__") + ".title")
    if not f.exists():
        try:
            f.write_text(_get(f"https://git.door43.org/unfoldingWord/en_ta/raw/tag/{uw.TAG}/{path}/title.md").decode("utf-8").strip(),
                         encoding="utf-8")
        except Exception:
            return ""
    return f.read_text(encoding="utf-8").strip()


def tag_commit(repo: str) -> str | None:
    f = TA_CACHE / f"{repo}.commit"
    if not f.exists():
        try:
            f.write_text(json.loads(_get(API.format(repo=repo) + f"/git/refs/tags/{uw.TAG}"))[0]["object"]["sha"], encoding="utf-8")
        except Exception:
            return None
    return f.read_text(encoding="utf-8").strip()


def newer(absent: list[str]) -> list[str]:
    """Lines for checks.md: the newest en_tn tag, and which absent books the newest tag and the master branch hold (not used)."""
    try:
        tags = [t["name"] for t in json.loads(_get(API.format(repo="en_tn") + "/tags?limit=5"))]
        out = [f"Newest en_tn tag at build time: {tags[0]}" + (" (the one used)." if tags[0] == uw.TAG else f" (newer than {uw.TAG}; not used).")]
        for ref in dict.fromkeys([tags[0], "master"]):
            have = {d["name"][3:6] for d in json.loads(_get(API.format(repo="en_tn") + f"/contents?ref={ref}")) if d["name"].startswith("tn_")}
            out.append(f"Absent books present at {ref}: {', '.join(b for b in absent if b in have) or 'none'} ({len(have)} books there).")
        return out
    except Exception as e:                                  # offline
        return [f"Newer tags not checked ({type(e).__name__})."]


def parse_ref(ref: str) -> tuple[int, list[int] | str] | None:
    """'3:4' -> (3, [4]); '6:8-9' -> (6, [8, 9]); '1:2,4,6' -> (1, [2, 4, 6]); '60:front' -> (60, 'front'); intros -> None."""
    m = re.fullmatch(r"(\d+):(front|\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)", ref or "")
    if not m:
        return None
    if m[2] == "front":
        return int(m[1]), "front"
    vs = []
    for part in m[2].split(","):
        a, _, b = part.partition("-")
        vs += list(range(int(a), int(b or a) + 1))
    return int(m[1]), vs


def merged(book: str, vw: dict, cvs: list[tuple[int, int]], hebrew: bool) -> list:
    """The words of several (English-numbered) verses in order, each from the first of its mapped verses that has words."""
    out = []
    for c, v in cvs:
        for cv in uw._candidates(book, c, v, hebrew):
            if vw.get(cv):
                out += vw[cv]
                break
    return out


def place(book: str, vw: dict, hebrew: bool, c: int, vs, quote: str, occ: int) -> tuple[list[int], str, str] | None:
    """The note's words, its fit and how they were found; None if not found."""
    if vs == "front":                                       # a psalm title: Hebrew verses 1-2 in MACULA's own numbering
        words = vw.get((c, 1), []) + vw.get((c, 2), [])
        hit = uw._Verse(book, {(c, 0): words}, False).phrase(c, 0, quote, max(occ, 1))
        return (hit[0], hit[1], "front") if hit else None
    find = uw._Verse(book, vw, hebrew)
    if occ == -1:                                           # every occurrence in the verse
        got, k = [], 1
        while (hit := find.phrase(c, vs[0], quote, k)) and hit[1] == "exact":
            got += [i for i in hit[0] if i not in got]
            k += 1
        return (sorted(got), "exact", "all") if got else None
    hit = find.phrase(c, vs[0], quote, occ)
    if hit:
        return hit[0], hit[1], "verse"
    if len(vs) > 1:                                         # a quote spread over the verses of a range
        words = merged(book, vw, [(c, v) for v in vs], hebrew)
        hit = uw._Verse(book, {(c, 0): words}, False).phrase(c, 0, quote, occ)
        if hit:
            return hit[0], hit[1], "range"
    return None


def cause(book: str, vw: dict, hebrew: bool, c: int, vs, quote: str, occ: int) -> str:
    """Why a note's Quote was not found (one of CAUSES)."""
    if vs == "front":
        words = [s for _, s in vw.get((c, 1), []) + vw.get((c, 2), [])]
        near = []
    else:
        words = [s for _, s in merged(book, vw, [(c, v) for v in vs], hebrew)]
        near = [s for _, s in merged(book, vw, [(c, vs[0] - 1), (c, vs[-1] + 1)], hebrew)]
    if not words:
        return "verse_absent"
    parts = [[uw.norm(t) for t in re.split(r"[\s־]+", p) if uw.norm(t)] for p in quote.split("&")]
    toks = [t for p in parts for t in p]
    missing = [t for t in toks if t not in words]
    if missing:
        return "token_in_neighbour" if all(t in near for t in missing) else "token_absent"
    first = parts[0] if parts else []
    runs = sum(1 for j in range(len(words)) if words[j:j + len(first)] == first)
    if first and 0 < runs < max(occ, 1):
        return "occurrence_beyond"
    return "order_or_gap"


def original_language(quote: str) -> bool:
    """Whether a Quote is in Hebrew or Greek letters (some draft notes quote the English)."""
    return any("\u0590" <= ch <= "\u05ff" or "\u0370" <= ch <= "\u03ff" or "\u1f00" <= ch <= "\u1fff" for ch in quote)


def code_version() -> str:
    run = lambda *a: subprocess.run(["git", *a], cwd=HERE.parent, text=True, capture_output=True).stdout.strip()
    dirty = run("status", "--porcelain", "--", "macula/build_translation_notes.py", "macula/unfoldingword.py",
                "macula/build_passage_facts.py")
    return run("rev-parse", "--short", "HEAD") + ("+uncommitted" if dirty else "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", nargs="+", default=list(uw.NUM))
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    src_label = uw.TAG if "UW_DIR" not in os.environ else f"files in {uw.CACHE} (not the tag)"
    articles = ta_articles()
    rows, absent = [], []
    left_out = collections.Counter()                        # rows without SupportReference
    for book in a.books:
        path = uw._file("en_tn", f"tn_{book}.tsv")
        if path is None:
            absent.append(book)
            continue
        bk = Book(book)
        lang = "hebrew" if bk.hebrew else "greek"
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
                sr = (r.get("SupportReference") or "").strip()
                if not sr:
                    left_out["intro" if "intro" in (r.get("Reference") or "") or "front:" in (r.get("Reference") or "") else "verse"] += 1
                    continue
                given = sr.rsplit("/", 1)[-1]
                slug = TYPOS.get(given, given)
                occ = int(r.get("Occurrence") or 1)
                quote = r.get("Quote") or ""
                ref = parse_ref(r.get("Reference") or "")
                row = {"id": r["ID"], "book": book, "lang": lang, "ref": r.get("Reference") or "", "code": "tn." + slug,
                       "given": given if given != slug else "", "occurrence": occ, "fit": "unmatched", "how": "", "first": "",
                       "last": "", "words": "", "cause": "", "tag": src_label}
                if not quote:
                    row["cause"] = "no_quote"
                elif not original_language(quote):
                    row["cause"] = "quote_not_original_language"
                elif ref is None:
                    row["cause"] = "reference_not_verse"
                else:
                    c, vs = ref
                    hit = place(book, bk.verse_words, bk.hebrew, c, vs, quote, occ)
                    if hit:
                        ws = sorted(hit[0])
                        row.update(fit=hit[1], how=hit[2], first=bk.keys[ws[0]], last=bk.keys[bk.wend[ws[-1]]],
                                   words=" ".join(bk.keys[i] for i in ws))
                    else:
                        row["cause"] = cause(book, bk.verse_words, bk.hebrew, c, vs, quote, occ)
                row["has_quote"] = original_language(quote)
                rows.append(row)
        print(book, sum(r["book"] == book for r in rows), file=sys.stderr)

    cols = ["id", "book", "ref", "code", "given", "occurrence", "fit", "how", "first", "last", "words", "cause", "tag"]
    with open(a.out / "notes.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow([r[k] for k in cols])

    by_code = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        by_code[r["code"]]["n"] += 1
        by_code[r["code"]]["matched"] += r["fit"] != "unmatched"
        by_code[r["code"]]["typo"] += bool(r["given"])
    with open(a.out / "codes.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["code", "article", "notes", "matched", "misspelt_in_source", "in_passage_facts", "english"])
        for code in sorted(by_code, key=lambda k: -by_code[k]["n"]):
            slug = code[3:]
            art = articles.get(slug, "")
            w.writerow([code, art or "(no article)", by_code[code]["n"], by_code[code]["matched"], by_code[code]["typo"],
                        int(slug in TN_SLUGS), ta_title(art) if art else ""])

    # ---- figures
    def rate(rs):
        m = sum(r["fit"] != "unmatched" for r in rs)
        return m, len(rs), (100 * m / len(rs) if rs else 0.0)

    quoted = [r for r in rows if r["has_quote"]]
    fits = collections.Counter(r["fit"] for r in rows)
    hows = collections.Counter(r["how"] for r in rows if r["how"])
    causes = collections.Counter(r["cause"] for r in rows if r["cause"])
    examples = {k: [f"{r['book']} {r['ref']} {r['code']} (occ {r['occurrence']}, {r['id']})" for r in rows if r["cause"] == k][:3]
                for k in causes}
    pf = [r for r in rows if r["code"][3:] in TN_SLUGS]
    pf_base = [r for r in pf if r["how"] == "verse"]
    typos = collections.Counter(r["given"] for r in rows if r["given"])
    no_article = sorted(c for c in by_code if c[3:] not in articles)
    lang_rate = {l: rate([r for r in quoted if r["lang"] == l]) for l in ("hebrew", "greek")}

    L = [f"# Translation Notes on MACULA words: checks", "",
         f"Source: unfoldingWord en_tn {src_label}; built {datetime.date.today().isoformat()}, code {code_version()}.", "",
         "## Counts", "",
         f"- notes with a SupportReference: {len(rows)}",
         f"- left out, no SupportReference: {sum(left_out.values())} (intro / front-matter rows {left_out['intro']}, "
         f"verse rows {left_out['verse']})",
         f"- with an original-language (Hebrew or Greek) Quote: {len(quoted)}; no Quote {causes['no_quote']}, "
         f"a Quote without Hebrew or Greek letters {causes['quote_not_original_language']}",
         f"- matched to MACULA words: {rate(quoted)[0]} of {len(quoted)} quoted ({rate(quoted)[2]:.2f} %); "
         f"exact {fits['exact']}, partial {fits['partial']}, unmatched {fits['unmatched']}",
         f"- how found: " + ", ".join(f"{k} {v}" for k, v in hows.most_common()),
         *[f"- {l}: {m} of {n} quoted matched ({p:.2f} %)" for l, (m, n, p) in lang_rate.items()],
         f"- misspelt SupportReference values mapped: {sum(typos.values())}" + (f" ({dict(typos)})" if typos else ""),
         f"- codes: {len(by_code)}; codes without a Translation Academy article at {uw.TAG}: {', '.join(no_article) or 'none'}", "",
         "## Books absent from the release", "",
         f"{', '.join(absent) or 'none'}.", "", *newer(absent), "",
         "## Cross-check with passage facts", "",
         f"Notes of the {len(TN_SLUGS)} kinds passage facts carries: {len(pf)}; matched {rate(pf)[0]}; matched in the note's own verse "
         f"(the only way passage facts looks) {len(pf_base)}. Published passage facts v0.1 has 8,762.", "",
         "## Unmatched, by cause", "", "| cause | notes | meaning | examples |", "|---|---|---|---|",
         *[f"| {k} | {n} | {CAUSES[k]} | {'; '.join(examples[k])} |" for k, n in causes.most_common()], "",
         "## Per code", "", "| code | notes | matched | rate |", "|---|---|---|---|",
         *[f"| {c} | {v['n']} | {v['matched']} | {100 * v['matched'] / v['n']:.1f} % |"
           for c, v in sorted(by_code.items(), key=lambda kv: -kv[1]["n"])], "",
         "## Per book", "", "| book | notes | quoted | matched | rate of quoted |", "|---|---|---|---|---|"]
    for book in a.books:
        rs = [r for r in rows if r["book"] == book]
        if rs:
            m, n, p = rate([r for r in rs if r["has_quote"]])
            L.append(f"| {book} | {len(rs)} | {n} | {m} | {p:.1f} % |")
    (a.out / "checks.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    build = {"built": datetime.date.today().isoformat(), "code": code_version(),
             "source": {"repo": "git.door43.org/unfoldingWord/en_tn", "tag": src_label, "commit": tag_commit("en_tn") if "UW_DIR" not in os.environ else None,
                        "articles": f"git.door43.org/unfoldingWord/en_ta tag {uw.TAG}", "articles_commit": tag_commit("en_ta")},
             "licence": "CC BY-SA 4.0",
             "attribution": "Translation Notes and Translation Academy by unfoldingWord, CC BY-SA 4.0. Derivatives must not use the "
                            "unfoldingWord name or mark (trademark rule); this data carries codes and anchors only, no note text.",
             "words": {"macula-spine.db": hashlib.sha256((HERE / "macula-spine.db").read_bytes()).hexdigest()},
             "counts": {"notes": len(rows), "left_out_without_support_reference": dict(left_out), "with_quote": len(quoted),
                        "fit": dict(fits), "how": dict(hows), "unmatched_causes": dict(causes),
                        "by_language": {l: {"matched": m, "quoted": n} for l, (m, n, _) in lang_rate.items()},
                        "misspelt_mapped": dict(typos), "codes": len(by_code),
                        "passage_facts_kinds": {"notes": len(pf), "matched": rate(pf)[0], "matched_in_own_verse": len(pf_base)}},
             "books_absent": absent}
    (a.out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(rows)} notes, matched {rate(quoted)[0]} of {len(quoted)} quoted; out {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
