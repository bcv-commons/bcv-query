#!/usr/bin/env python3
"""Malbim, Beur HaMilot: near-synonym pairs Malbim sets out to distinguish. Hebrew explaining Hebrew.

Malbim (Meir Leibush Wisser, 19th c.) holds that the Bible has no true synonyms, and his word commentary
(Beur HaMilot, on the Prophets and Writings) explains the difference between words that stand side by
side in a verse: `<b>גוי, עם.</b> ההבדל ביניהם...` ("nation, people: the difference between them..."),
`<b>פצע וחבורה.</b>`. A pair he distinguishes is, by his own premise, a pair of near-synonyms. Hebrew
text Public Domain, via Sefaria ("On Your Way" edition).

Extraction:
  - a bold heading of exactly two items ("X, Y" or "X וY"); each item is resolved through its own verse
    in lexeme-spine.db (surface or lemma, consonants only), as in build_metzudat_zion.py;
  - the explicit phrase נרדף עם ("synonymous with") X in a comment body: the heading word and X, with X
    resolved by consonants against Biblical Hebrew lemmas and kept only if unique;
  - proper names and function words are dropped on both sides; the two Strong's numbers must differ.

  cd shoresh && .venv/bin/python3 -m macula.build_malbim            # fetch (resumable) + extract
  cd shoresh && .venv/bin/python3 -m macula.build_malbim --no-fetch
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine.common import to_modern_form  # noqa: E402

from macula.build_metzudat_zion import _bare_index, _get, _resolve_gloss, chapter_counts, excluded  # noqa: E402
from macula.build_sefer_hashorashim import BOOK_MAP  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine.db"
CACHE = HERE / "data" / "malbim_beur_hamilot_chapters.jsonl"
OUT = ROOT / "resources" / "malbim" / "candidate_pairs.tsv"
TORAH = {"Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"}
_SYN = re.compile(r"נרדף\s+(?:עם|ל|את)\s*(?:פעל\s+|שם\s+)?([א-ת][א-ת֑-ׇ]*)")


def fetch() -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if CACHE.exists():
        done = {json.loads(l)["ref"] for l in CACHE.read_text(encoding="utf-8").splitlines() if l}
    with CACHE.open("a", encoding="utf-8") as fh:
        for book, n_ch in chapter_counts().items():
            if book in TORAH:
                continue
            for ch in range(1, n_ch + 1):
                ref = f"Malbim Beur Hamilot on {book} {ch}"
                if ref in done:
                    continue
                d = _get(ref)
                v = (d or {}).get("versions") or []
                if not v or not v[0].get("text"):
                    if ch == 1:
                        print(f"[malbim] no Beur HaMilot for {book}", file=sys.stderr)
                        break
                    continue
                fh.write(json.dumps({"ref": ref, "book": BOOK_MAP[book], "chapter": ch,
                                     "license": v[0].get("license"), "version": v[0].get("versionTitle"),
                                     "verses": v[0]["text"]}, ensure_ascii=False) + "\n")
                fh.flush()
                time.sleep(0.15)
            print(f"[malbim] {book} done", file=sys.stderr)


def _merged(verses: list) -> list[list]:
    """Per verse, its comments with split headings joined: some editions (Jeremiah) give a two-item heading
    as two entries, `<b>גוי</b>, ` (heading and a comma, nothing else) then `<b>ועמי.</b> text`; joined to
    `<b>גוי, ועמי.</b> text`, the two-item heading Malbim wrote."""
    out = []
    for cs in verses:
        res, carry = [], ""
        for c in (cs if isinstance(cs, list) else [cs]):
            m = re.match(r"\s*<b>([^<]+)</b>(['׳]?\s*,\s*)$", c) if isinstance(c, str) else None
            if m:
                carry += m.group(1).strip().rstrip(",") + m.group(2).strip().rstrip(",") + ", "
                continue
            if carry and isinstance(c, str):
                m2 = re.match(r"(\s*)<b>([^<]+)</b>(.*)", c, re.S)
                c = f"{m2.group(1)}<b>{carry}{m2.group(2)}</b>{m2.group(3)}" if m2 else c
                carry = ""
            res.append(c)
        if carry:
            res.append(f"<b>{carry.rstrip(', ')}</b>")
        out.append(res)
    return out


def _items(head: str) -> list[str]:
    """'גוי, עם' / 'פצע וחבורה' -> the two items; anything else -> []."""
    head = re.sub(r"[.:]\s*$", "", head.strip())
    parts = [p.strip() for p in head.split(",") if p.strip()]
    if len(parts) == 1:
        words = parts[0].split()
        if len(words) == 2 and words[1].startswith("ו") and len(words[1]) > 2:
            parts = words
    return parts if len(parts) == 2 else []


def _in_verse(item: str, vwords, drop: set[str]) -> set[str]:
    for w in item.split():
        b = to_modern_form(w, "hbo")
        hits = {s for sb, lb, s in vwords if b and (b == sb or b == lb) and s not in drop}
        if hits:
            return hits
    return set()


def extract() -> collections.Counter:
    from macula.build_sefer_hashorashim import _verse_words

    drop = excluded()
    idx = _bare_index(drop)
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    code2name = {v: k for k, v in BOOK_MAP.items()}
    pairs: collections.Counter = collections.Counter()
    stats = collections.Counter()
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        for vi, comments in enumerate(_merged(row["verses"]), start=1):
            comments = comments if isinstance(comments, list) else [comments]
            if not any(comments):
                continue
            vwords = _verse_words(f"{code2name[row['book']]} {row['chapter']}:{vi}", sp)
            for c in comments:
                m = re.match(r"\s*<b>([^<]+)</b>\s*\.?\s*(.*)", c or "", re.S)
                if not m:
                    continue
                stats["comments"] += 1
                items = _items(m.group(1))
                if items:
                    stats["two_item_heads"] += 1
                    a, b = (_in_verse(x, vwords, drop) for x in items)
                    if len(a) == 1 and len(b) == 1 and a != b:
                        pairs[frozenset(a | b)] += 1
                        stats["head_pairs"] += 1
                body = re.sub(r"<[^>]+>", "", m.group(2))
                for syn in _SYN.findall(body):
                    heads = _in_verse(m.group(1), vwords, drop)
                    hits = _resolve_gloss(syn, idx)
                    if len(heads) == 1 and len(hits) == 1 and heads != hits:
                        pairs[frozenset(heads | hits)] += 1
                        stats["nirdaf_pairs"] += 1
    print(f"[malbim] {dict(stats)} -> {len(pairs)} distinct pairs", file=sys.stderr)
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--torah", action="store_true",
                    help="fetch Malbim on the Torah and write resources/malbim/distinctions_torah.tsv")
    ap.add_argument("--explanations", action="store_true",
                    help="write resources/malbim/explanations.tsv (per-word comments for /verse) and stop")
    ap.add_argument("--distinctions", action="store_true",
                    help="write resources/malbim/distinctions.tsv (for word studies) and stop")
    ap.add_argument("--commentary", action="store_true",
                    help="fetch Malbim's verse commentary and write resources/malbim/commentary.tsv.gz")
    args = ap.parse_args()
    if args.commentary:
        if not args.no_fetch:
            fetch_torah()
            fetch_leviticus()
            fetch_commentary()
        write_commentary(commentary())
        return 0
    if not args.no_fetch:
        fetch()
    if args.distinctions:
        write_distinctions(distinctions())
        return 0
    if args.explanations:
        write_explanations(explanations())
        return 0
    if args.torah:
        fetch_torah()
        rows = torah_distinctions()
        global DISTINCTIONS
        DISTINCTIONS = TORAH_DISTINCTIONS
        write_distinctions(rows)
        return 0
    pairs = extract()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write("# CANDIDATE Hebrew Strong's pairs from Malbim, Beur HaMilot (19th c.; Hebrew text Public Domain, "
                 "via Sefaria):\n# word pairs Malbim distinguishes (two-item headings) or calls synonymous "
                 "(נרדף עם). Derived data CC0.\n# `count` = number of comments giving the pair. See "
                 "shoresh/macula/build_malbim.py.\n")
        fh.write("strong_a\tstrong_b\tcount\n")
        for pair, cnt in sorted(pairs.items(), key=lambda kv: (-kv[1], sorted(kv[0]))):
            a, b = sorted(pair)
            fh.write(f"{a}\t{b}\t{cnt}\n")
    print(f"[malbim] -> {OUT}", file=sys.stderr)
    return 0



# ---------- cross-references ("see there") ----------

_REF_WORDS = {"עי", "עיין", "ועי", "הבדלם", "בפי", "פי", "כנל", "לקמן", "לעיל", "למעלה", "עוד", "פסוק", "עש", "ועש",
              "עמש", "כמש", "שם", "בארתי", "כבר", "בפירוש", "הבדלו", "בביאור", "ביאור", "שבארתי", "מש"}


def is_cross_reference(text: str) -> bool:
    """Only reference words and verse numbers left: a pointer, not an explanation. Short real glosses
    (רוח: רצון; יסכר: כמו יסגר) are explanations and stay."""
    t = re.sub(r"\([^)]*\)", " ", text)
    words = [re.sub(r"[\"'״׳]", "", w) for w in re.findall(r"[א-ת][א-ת\"'״׳]*", t)]
    real = [w for w in words if len(w) >= 2 and w not in _REF_WORDS and not _is_number(w)]
    return not real


def _is_number(w: str) -> bool:
    from macula.build_mahberet_menahem import gematria
    g = gematria(w)
    return g is not None and g <= 176 and len(w) <= 3


def _targets(text: str, book: str, ch: int, vs: int) -> list[tuple]:
    """(book, chapter, verse|None) the pointer names: '(שופטים ה׳:ג׳)', 'ישעיה ב' ב'', '(ב' י"ג)' (same book),
    'פסוק א'' (same chapter), '(ישעיהו ט"ו)' (chapter only)."""
    from macula.build_mahberet_menahem import HEB_BOOKS, gematria
    t = text.replace("״", '"').replace("׳", "'")
    out = []
    for name, code in sorted(HEB_BOOKS.items(), key=lambda kv: -len(kv[0])):
        for m in re.finditer(re.escape(name) + r"\s+([א-ת\"']+)(?:[:\s,]+([א-ת\"']+))?", t):
            c, v = gematria(m.group(1)), gematria(m.group(2)) if m.group(2) else None
            if c:
                out.append((code, c, v))
    for m in re.finditer(r"פסוק\s+([א-ת\"']+)", t):
        v = gematria(m.group(1))
        if v:
            out.append((book, ch, v))
    for m in re.finditer(r"\((?:לעיל|לקמן|כנ\"ל|למעלה|ע\"ל|עי' לעיל|עיין לעיל)?\s*([א-ת\"']{1,4})[\s,]+([א-ת\"']{1,4})\)", t):
        c, v = gematria(m.group(1)), gematria(m.group(2))
        if c and v:
            out.append((book, c, v))
    return out


def comment_index() -> dict:
    """(book, chapter, verse) -> [(heading words without vowel letters, text)] over all non-pointer comments."""
    idx: dict = collections.defaultdict(list)
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        for vi, comments in enumerate(_merged(row["verses"]), start=1):
            for c in (comments if isinstance(comments, list) else [comments]):
                m = re.match(r"\s*<b>([^<]+)</b>\s*\.?\s*(.*)", c or "", re.S)
                if not m:
                    continue
                text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(2))).strip().rstrip(":").strip()
                if is_cross_reference(text):
                    continue
                words = {re.sub(r"[וי]", "", to_modern_form(w, "hbo")) for w in re.split(r"[,\s]+", m.group(1)) if w}
                idx[(row["book"], row["chapter"], vi)].append(({w for w in words if len(w) >= 2}, text))
    return idx


def resolve_cross_reference(heading: str, text: str, book: str, ch: int, vs: int, idx: dict):
    """(text, 'BOOK c:v') of the comment the pointer leads to, on a word of this heading; else None."""
    mine = {re.sub(r"[וי]", "", to_modern_form(w, "hbo")) for w in re.split(r"[,\s]+", heading) if w}
    mine = {w for w in mine if len(w) >= 2}
    targets = _targets(text, book, ch, vs)
    for b, c, v in targets:
        verses = [v] if v else [k[2] for k in idx if k[0] == b and k[1] == c]
        for vv in sorted(set(verses)):
            for words, t in idx.get((b, c, vv), []):
                if words & mine:
                    return t, f"{b} {c}:{vv}"
    if not targets:                    # bare "above" / "below": the nearest comment on the same word in this book
        t2 = text.replace("״", '"')
        back = re.search(r"למעלה|לעיל|ע\"ל|כנ\"ל", t2)
        fwd = re.search(r"לקמן|להלן", t2)
        if back or fwd:
            keys = sorted(k for k in idx if k[0] == book)
            here = (book, ch, vs)
            order = ([k for k in reversed(keys) if k < here] if back else []) + ([k for k in keys if k > here] if fwd else [])
            for k in order:
                for words, t in idx.get(k, []):
                    if words & mine:
                        return t, f"{k[0]} {k[1]}:{k[2]}"
    return None


# ---------- distinctions for word studies ----------

_DIFF = re.compile(r"הבדל|ההבדל|הבדלם|נרדף|הנרדפים|בינו ובין")
_DIFF_FROM = re.compile(r"(?:הבדלו מן|והבדלו מן|נבדל מן|ההבדל בינו ובין|בינו ובין|נרדף עם)\s+(?:פעל\s+|שם\s+)?([א-ת][א-ת\u0591-\u05C7]*)")

DISTINCTIONS = ROOT / "resources" / "malbim" / "distinctions.tsv"


def distinctions() -> list[tuple]:
    """Every two-item heading anchored word by word (whole words, as build_metzudat_zion --explanations):
    the two words Malbim distinguishes and his explanation of the difference."""
    from macula.build_metzudat_zion import _anchor, _content_strong, _verse_word_units
    drop = excluded()
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    xidx = comment_index()
    gidx = _bare_index(drop)
    rows, st = [], collections.Counter()
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        for vi, comments in enumerate(_merged(row["verses"]), start=1):
            comments = comments if isinstance(comments, list) else [comments]
            units = None
            for c in comments:
                m = re.match(r"\s*<b>([^<]+)</b>\s*\.?\s*(.*)", c or "", re.S)
                if not m:
                    continue
                items = _items(m.group(1))
                body = re.sub(r"<[^>]+>", "", m.group(2))
                partner_word = ""
                if not items:
                    words = re.sub(r"[.:]\s*$", "", m.group(1).strip()).split()
                    if len(words) == 2 and _DIFF.search(body):
                        items = words                     # "ישמח יגל" + "הבדל בין שמחה ובין גיל"
                        st["two_word_heading_confirmed_by_text"] += 1
                    elif len(words) == 1:
                        pm = _DIFF_FROM.search(body)       # "יגל: הבדלו מן שמחה"
                        if not pm:
                            continue
                        items, partner_word = words, pm.group(1)
                        st["differs_from_in_text"] += 1
                    else:
                        continue
                else:
                    st["two_item_headings"] += 1
                if any(len(x.split()) > 2 for x in items):
                    st["long_phrase_item"] += 1            # anchors to an unhelpful first word
                    continue
                if units is None:
                    units = _verse_word_units(sp, row["book"], row["chapter"], vi)
                anchored = [_anchor(x.split()[0], units) for x in items]
                if not all(anchored):
                    st["not_anchored"] += 1
                    continue
                if partner_word:                          # partner named only in the text: link it only if unique
                    sa = _content_strong(anchored[0], drop)
                    hits = _resolve_gloss(partner_word, gidx)
                    sb = next(iter(hits)) if len(hits) == 1 else ""
                    items = [items[0], partner_word]
                    st["partner_linked" if sb else "partner_unlinked"] += 1
                else:
                    sa, sb = (_content_strong(u, drop) for u in anchored)
                if not sa or sa == sb or (not sb and not partner_word):
                    st["same_or_missing_word"] += 1
                    continue
                text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(2))).strip().rstrip(":").strip()
                via = ""
                if is_cross_reference(text):
                    got = resolve_cross_reference(m.group(1), text, row["book"], row["chapter"], vi, xidx)
                    if not got:
                        st["unresolved_cross_reference"] += 1
                        continue
                    text, via = got
                    st["cross_reference_resolved"] += 1
                rows.append((row["book"], row["chapter"], vi, sa, items[0], sb, items[1],
                             re.sub(r"[.:]\s*$", "", m.group(1).strip()), text, row.get("license") or "", via))
                st["distinctions"] += 1
    # "the difference between X and Y" stated in a comment's text, about words other than its heading's
    have = {(r[0], r[1], r[2], *sorted((r[3], r[5]))) for r in rows}
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        for vi, comments in enumerate(_merged(row["verses"]), start=1):
            units = None
            for c in (comments if isinstance(comments, list) else [comments]):
                m0 = re.match(r"\s*<b>([^<]+)</b>\s*\.?\s*(.*)", c or "", re.S)
                if not m0:
                    continue
                body = re.sub(r"<[^>]+>", "", m0.group(2))
                for m in _BETWEEN.finditer(body):
                    if units is None:
                        units = _verse_word_units(sp, row["book"], row["chapter"], vi)
                    strongs = []
                    for w in (m.group(1), m.group(2)):
                        u = _anchor(w, units)
                        hits = {_content_strong(u, drop)} if u else _resolve_gloss(w, gidx)
                        strongs.append(next(iter(hits)) if len(hits) == 1 else "")
                    if not all(strongs) or strongs[0] == strongs[1]:
                        st["text_pair_unresolved"] += 1
                        continue
                    key = (row["book"], row["chapter"], vi, *sorted(strongs))
                    if key in have:
                        continue
                    have.add(key)
                    text = re.sub(r"\s+", " ", body).strip().rstrip(":").strip()
                    rows.append((row["book"], row["chapter"], vi, strongs[0], m.group(1), strongs[1], m.group(2),
                                 f"{m.group(1)} / {m.group(2)}", text, row.get("license") or "", ""))
                    st["text_pair_distinctions"] += 1
    print(f"[malbim] distinctions: {dict(st)}", file=sys.stderr)
    return rows


def write_distinctions(rows: list[tuple]) -> None:
    DISTINCTIONS.parent.mkdir(parents=True, exist_ok=True)
    with DISTINCTIONS.open("w", encoding="utf-8") as fh:
        fh.write("# Malbim, Beur HaMilot (19th c.): pairs of words he distinguishes in a verse, with his explanation of "
                 "the difference.\n# Hebrew text via Sefaria; `license` is Sefaria's label for the edition (Public "
                 "Domain; 'unknown' for the\n# newer Psalms import from the same source, mobile.tora.ws). Anchoring "
                 "CC0. Built by shoresh/macula/build_malbim.py --distinctions.\n")
        fh.write("book\tchapter\tverse\tstrong_a\tword_a\tstrong_b\tword_b\theading\ttext\tlicense\tvia\n")
        for r in rows:
            fh.write("\t".join(str(x).replace("\t", " ") for x in r) + "\n")
    print(f"[malbim] -> {DISTINCTIONS} ({len(rows)} rows)", file=sys.stderr)



# ---------- per-word explanations (served in /verse beside Metzudat Zion) ----------

EXPLANATIONS = ROOT / "resources" / "malbim" / "explanations.tsv"


def explanations() -> list[tuple]:
    """Every Beur HaMilot comment anchored to the word(s) its heading quotes: one-word and phrase headings
    to their first word, two- and three-item headings to each item's word. Cross-reference-only comments
    are left out."""
    from macula.build_metzudat_zion import _anchor, _content_strong, _verse_word_units
    drop = excluded()
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    xidx = comment_index()
    rows, st = [], collections.Counter()
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        for vi, comments in enumerate(_merged(row["verses"]), start=1):
            comments = comments if isinstance(comments, list) else [comments]
            units = None
            for c in comments:
                m = re.match(r"\s*<b>([^<]+)</b>\s*\.?\s*(.*)", c or "", re.S)
                if not m:
                    continue
                st["comments"] += 1
                heading = re.sub(r"[.:]\s*$", "", m.group(1).strip())
                text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(2))).strip().rstrip(":").strip()
                via = ""
                if is_cross_reference(text):
                    got = resolve_cross_reference(heading, text, row["book"], row["chapter"], vi, xidx)
                    if not got:
                        st["unresolved_cross_reference"] += 1
                        continue
                    text, via = got
                    st["cross_reference_resolved"] += 1
                items = [x.strip() for x in heading.split(",") if x.strip()]
                if len(items) == 1:
                    items = _items(heading) or [heading]
                if units is None:
                    units = _verse_word_units(sp, row["book"], row["chapter"], vi)
                short = re.split(r"(?<=[.:])\s|\s\(", text, maxsplit=1)[0]
                if len(short.split()) < 3:                 # e.g. a lone pointer word: use the text's opening
                    short = re.sub(r"\([^)]*\)", "", text).strip()
                short = short if len(short) <= 200 else short[:200].rsplit(" ", 1)[0] + "…"
                done = set()
                for item in items:
                    u = _anchor(item.split()[0], units) if item.split() else None
                    if not u and item.split():
                        from macula.anchor_llm import fallback
                        u = fallback("malbim", row["book"], row["chapter"], vi, item.split()[0], units, text)
                        st["anchored_llm"] += bool(u)
                    if not u or u["key"] in done:
                        continue
                    done.add(u["key"])
                    rows.append((row["book"], row["chapter"], vi, u["key"], u["surface"], _content_strong(u, drop),
                                 heading, short, text, row.get("license") or "", via))
                st["anchored" if done else "not_anchored"] += 1
    print(f"[malbim] explanations: {dict(st)}", file=sys.stderr)
    return rows


def write_explanations(rows: list[tuple]) -> None:
    EXPLANATIONS.parent.mkdir(parents=True, exist_ok=True)
    with EXPLANATIONS.open("w", encoding="utf-8") as fh:
        fh.write("# Malbim, Beur HaMilot (19th c.): his word comments on the Prophets and Writings, anchored to the "
                 "word(s) each heading quotes.\n# Hebrew text via Sefaria; `license` is Sefaria's label for the "
                 "edition. Anchoring CC0. short = the first sentence.\n# Built by shoresh/macula/build_malbim.py "
                 "--explanations.\n")
        fh.write("book\tchapter\tverse\tword_key\tword\tstrong\theading\tshort\ttext\tlicense\tvia\n")
        for r in rows:
            fh.write("\t".join(str(x).replace("\t", " ") for x in r) + "\n")
    print(f"[malbim] -> {EXPLANATIONS} ({len(rows)} rows)", file=sys.stderr)



# ---------- Malbim on the Torah: explicit distinctions in the verse commentary ----------

TORAH_CACHE = HERE / "data" / "malbim_torah_chapters.jsonl"
TORAH_DISTINCTIONS = ROOT / "resources" / "malbim" / "distinctions_torah.tsv"
_BETWEEN = re.compile(r"(?:ה)?הבדל\s+(?:יש\s+)?בין\s+([א-ת][א-ת֑-ׇ\"']*)\s+(?:ובין\s+|ל|ו)([א-ת][א-ת֑-ׇ\"']*)")


def fetch_torah() -> None:
    """Malbim on the Torah (HaTorah VeHaMitzvah; Vilna 1891, Public Domain, via Sefaria), per chapter."""
    TORAH_CACHE.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(l)["ref"] for l in TORAH_CACHE.read_text(encoding="utf-8").splitlines()} if TORAH_CACHE.exists() else set()
    counts = chapter_counts()
    with TORAH_CACHE.open("a", encoding="utf-8") as fh:
        for book in sorted(TORAH):
            for ch in range(1, counts.get(book, 0) + 1):
                ref = f"Malbim on {book} {ch}"
                if ref in done:
                    continue
                d = _get(ref)
                v = (d or {}).get("versions") or []
                if v and v[0].get("text"):
                    fh.write(json.dumps({"ref": ref, "book": BOOK_MAP[book], "chapter": ch,
                                         "license": v[0].get("license"), "version": v[0].get("versionTitle"),
                                         "verses": v[0]["text"]}, ensure_ascii=False) + "\n")
                    fh.flush()
                time.sleep(0.15)
            print(f"[malbim-torah] {book} done", file=sys.stderr)


COMMENTARY_CACHE = HERE / "data" / "malbim_commentary_chapters.jsonl"


def fetch_commentary() -> None:
    """Malbim's verse commentary on the Prophets and Writings (Beur HaInyan; Sefaria "Malbim on <book>"),
    per chapter. The Torah commentary is fetched by fetch_torah()."""
    COMMENTARY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    done = ({json.loads(l)["ref"] for l in COMMENTARY_CACHE.read_text(encoding="utf-8").splitlines()}
            if COMMENTARY_CACHE.exists() else set())
    with COMMENTARY_CACHE.open("a", encoding="utf-8") as fh:
        for book, n_ch in chapter_counts().items():
            if book in TORAH:
                continue
            for ch in range(1, n_ch + 1):
                ref = f"Malbim on {book} {ch}"
                if ref in done:
                    continue
                d = _get(ref)
                v = (d or {}).get("versions") or []
                if v and v[0].get("text"):
                    fh.write(json.dumps({"ref": ref, "book": BOOK_MAP[book], "chapter": ch,
                                         "license": v[0].get("license"), "version": v[0].get("versionTitle"),
                                         "verses": v[0]["text"]}, ensure_ascii=False) + "\n")
                    fh.flush()
                time.sleep(0.15)
            print(f"[malbim-commentary] {book} done", file=sys.stderr)


LEVITICUS_CACHE = HERE / "data" / "malbim_leviticus_chapters.jsonl"


def _quoted_verse(sp, quote: str, cv: tuple) -> tuple:
    """The verse, from cv up to three verses on, whose words include all the quote's first two words."""
    from macula.build_metzudat_zion import _anchor, _verse_word_units
    words = [w for w in re.findall(r"[א-ת]+", quote) if len(w) >= 2][:2]
    if not words:
        return cv
    for d in range(0, 4):
        units = _verse_word_units(sp, "LEV", cv[0], cv[1] + d)
        if units and all(_anchor(w, units) for w in words):
            return (cv[0], cv[1] + d)
    return cv


def fetch_leviticus() -> None:
    """Malbim on Leviticus follows the Sifra (portion / siman / paragraph), not verses. Sefaria links each
    verse to its paragraphs; with those links the paragraphs are regrouped per chapter and verse, in the same
    shape as the other caches (a paragraph's opening quote, up to its first colon, becomes the heading)."""
    import urllib.parse
    import urllib.request

    def get(url):
        for attempt in range(5):
            try:
                req = urllib.request.Request(url, headers={"user-agent": "bcv-query/1.0"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.load(resp)
            except Exception:                                  # noqa: BLE001 - retried, then given up
                time.sleep(min(2 ** attempt, 20))
        return None

    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    verses = sp.execute("SELECT DISTINCT chapter, verse FROM spine_words WHERE book='LEV' AND lexeme LIKE 'hbo:%' "
                        "ORDER BY chapter, verse").fetchall()
    link = re.compile(r"^Malbim on Leviticus, ([A-Za-z ]+) (\d+):(\d+)(?:-(\d+))?$")
    links_path = HERE / "data" / "malbim_leviticus_links.json"
    links = json.loads(links_path.read_text(encoding="utf-8")) if links_path.exists() else {}
    for c, v in verses:
        if f"{c}:{v}" not in links:
            got = get(f"https://www.sefaria.org/api/links/{urllib.parse.quote(f'Leviticus {c}:{v}')}?with_text=0")
            if got is None:
                continue
            links[f"{c}:{v}"] = [{"ref": x.get("ref"), "category": x.get("category")} for x in got
                                 if "Malbim on Leviticus" in (x.get("ref") or "")]
            time.sleep(0.1)
    links_path.write_text(json.dumps(links, ensure_ascii=False), encoding="utf-8")
    where: dict = {}                                           # (portion, siman, paragraph) -> (chapter, verse)
    for c, v in verses:
        for x in links.get(f"{c}:{v}", []):
            m = link.match(x["ref"] or "")
            # "Commentary" = the paragraph comments on this verse; "Quoting Commentary" only cites it
            if m and x["category"] == "Commentary":
                lo, hi = int(m.group(3)), int(m.group(4) or m.group(3))
                for para in range(lo, hi + 1):
                    where.setdefault((m.group(1), int(m.group(2)), para), (c, v))
    per: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    lic, ver = "", ""
    for portion in sorted({k[0] for k in where}):
        d = get(f"https://www.sefaria.org/api/v3/texts/{urllib.parse.quote(f'Malbim on Leviticus, {portion}')}"
                "?version=hebrew") or {}
        vs = d.get("versions") or []
        if not vs:
            continue
        lic, ver = vs[0].get("license") or lic, vs[0].get("versionTitle") or ver
        for si, paras in enumerate(vs[0].get("text") or [], start=1):
            cv = None
            for pi, para in enumerate(paras if isinstance(paras, list) else [paras], start=1):
                linked = where.get((portion, si, pi))
                cv = linked or cv                              # unlinked paragraphs follow the siman's last link
                if not cv or not isinstance(para, str) or not para.strip():
                    continue
                m = re.match(r"\s*([^:<]{2,80}):\s*(.*)", para, re.S)
                if m:                  # the quote decides when it is only in a later verse (Sefaria links some
                    cv = _quoted_verse(sp, m.group(1), cv)     # simanim one verse early: Kedoshim 46 to 19:18)
                per[cv[0]][cv[1]].append(f"<b>{m.group(1).strip()}</b> {m.group(2)}" if m else para)
    with LEVITICUS_CACHE.open("w", encoding="utf-8") as fh:
        for c in sorted(per):
            n = max(v for cc, v in verses if cc == c)
            fh.write(json.dumps({"ref": f"Malbim on Leviticus (by verse) {c}", "book": "LEV", "chapter": c,
                                 "license": lic, "version": ver,
                                 "verses": [per[c].get(v, []) for v in range(1, n + 1)]}, ensure_ascii=False) + "\n")
    print(f"[malbim-leviticus] {len(where)} linked paragraphs, {sum(len(x) for x in per.values())} verses",
          file=sys.stderr)


COMMENTARY = ROOT / "resources" / "malbim" / "commentary.tsv.gz"


def _plain(html: str) -> str:
    """Comment HTML to plain text; line breaks kept (the questions section is a list)."""
    t = re.sub(r"<br\s*/?>", "\n", html or "")
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    return "\n".join(x.strip() for x in t.split("\n") if x.strip())


def commentary() -> list[tuple]:
    """Every verse comment of Malbim's commentary: the Torah (fetch_torah) and the Prophets and Writings
    (fetch_commentary), one row per comment: book, chapter, verse, n, heading (the bold quote or section
    title, e.g. השאלות = his questions on the passage), text, license, edition."""
    rows, st = [], collections.Counter()
    for cache in (TORAH_CACHE, LEVITICUS_CACHE, COMMENTARY_CACHE):
        if not cache.exists():
            continue
        for line in cache.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            for vi, comments in enumerate(r["verses"], start=1):
                n = 0
                for c in (comments if isinstance(comments, list) else [comments]):
                    if not isinstance(c, str) or not c.strip():
                        continue
                    m = re.match(r"\s*<b>(.*?)</b>\s*(.*)", c, re.S)
                    heading = _plain(m.group(1)).rstrip(",.:; ") if m else ""
                    text = _plain(m.group(2) if m else c).lstrip(",.:; ")
                    if not text and not heading:
                        continue
                    n += 1
                    rows.append((r["book"], r["chapter"], vi, n, heading, text, r.get("license") or "",
                                 r.get("version") or ""))
                    st["comments"] += 1
                st["verses_with_comments"] += bool(n)
    print(f"[malbim] commentary: {dict(st)}", file=sys.stderr)
    return rows


def write_commentary(rows: list[tuple]) -> None:
    import gzip
    COMMENTARY.parent.mkdir(parents=True, exist_ok=True)
    head = ("# Malbim (Meir Leibush Wisser, 19th c.): his verse commentary on the Hebrew Bible (on the Torah: "
            "HaTorah VeHaMitzvah; on the\n# Prophets and Writings: Beur HaInyan), one row per comment. Hebrew text "
            "via Sefaria; license and edition per row\n# as Sefaria gives them. heading = the words the comment "
            "quotes, or a section title (השאלות: his questions).\n# Built by shoresh/macula/build_malbim.py "
            "--commentary.\n")
    body = head + "book\tchapter\tverse\tn\theading\ttext\tlicense\tedition\n" + "".join(
        "\t".join(str(x).replace("\t", " ").replace("\n", "\\n") for x in r) + "\n" for r in rows)
    with COMMENTARY.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as fh:
        fh.write(body.encode("utf-8"))      # mtime=0: the same rows give the same bytes
    print(f"[malbim] -> {COMMENTARY} ({len(rows)} comments)", file=sys.stderr)


def torah_distinctions() -> list[tuple]:
    from macula.build_metzudat_zion import _anchor, _content_strong, _verse_word_units
    drop = excluded()
    gidx = _bare_index(drop)
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    rows, st, seen = [], collections.Counter(), set()
    for line in TORAH_CACHE.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        for vi, comments in enumerate(_merged(row["verses"]), start=1):
            text = " ".join(re.sub(r"<[^>]+>", "", c or "") for c in (comments if isinstance(comments, list) else [comments]))
            units = None
            for m in _BETWEEN.finditer(text):
                st["difference_phrases"] += 1
                if units is None:
                    units = _verse_word_units(sp, row["book"], row["chapter"], vi)
                strongs = []
                for w in (m.group(1), m.group(2)):
                    u = _anchor(w, units)
                    if u:
                        strongs.append(_content_strong(u, drop))
                    else:
                        hits = _resolve_gloss(w, gidx)
                        strongs.append(next(iter(hits)) if len(hits) == 1 else "")
                if not all(strongs) or strongs[0] == strongs[1]:
                    st["same_root_or_unresolved"] += 1
                    continue
                start = max(text.rfind(".", 0, m.start()), text.rfind(":", 0, m.start())) + 1
                end_dot = min([i for i in (text.find(".", m.end()), text.find(":", m.end())) if i != -1] or [len(text)])
                sentence = text[start:end_dot].strip()
                if len(sentence) > 400:
                    sentence = sentence[:400].rsplit(" ", 1)[0] + "…"
                key = (row["book"], row["chapter"], vi, *sorted(strongs))
                if key in seen:
                    continue
                seen.add(key)
                rows.append((row["book"], row["chapter"], vi, strongs[0], m.group(1), strongs[1], m.group(2),
                             f"{m.group(1)} / {m.group(2)}", sentence, row.get("license") or "", ""))
                st["distinctions"] += 1
    print(f"[malbim-torah] {dict(st)}", file=sys.stderr)
    return rows


if __name__ == "__main__":
    sys.exit(main())
