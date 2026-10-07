"""Derive the Psalm title spans (`psalm_title_spans.tsv`) from Hebrew-only sources. Run occasionally; the table is committed.

Which words are a Psalm's title is a fact about the Hebrew text, so it is derived only from the Hebrew text's own structure
and from versification -- never from an English translation, BHSA, or UHB:

1. TITLE IS ITS OWN HEBREW VERSE(S) (63 psalms, e.g. Ps 3, 51:1-2): TVTMS (STEPBible, CC BY; via cdn.bibel.wiki
   `_vrs/map/org-to-eng.json`) maps the Hebrew verse(s) to an English *title*. The whole verse(s) are the title. Exact.
2. TITLE OPENS VERSE 1 (52 psalms, e.g. Ps 23 `מִזְמוֹר לְדָוִד | יְהוָה רֹעִי ...`): MACULA's lowfat tree (Clear-Bible/macula-hebrew,
   CC BY 4.0) splits verse 1 into top-level clauses. The title is the leading run of clauses made only of title terms:
   every content lemma is in TITLE_TERMS (a closed list of Hebrew title words and the personal names found in titles) or in the
   vocabulary of the 63 true titles of rule 1, divine names are never title terms, and a clause with a finite verb (anything but
   a participle such as `לַמְנַצֵּחַ`) is body. The first clause of a titled psalm always belongs to the title. This finds exactly
   the 52 psalms known to have such a title and no other psalm (checked 2026-10-07 against all 150), and it extends the title
   past a first clause that stops short (Ps 11 `לַמְנַצֵּחַ | לְדָוִד`, Ps 87 `...מִזְמוֹר | שִׁיר`, the Songs of Ascents `שִׁיר הַמַּעֲלוֹת
   לְדָוִד`) -- 16 of the 52 are longer than a first-clause boundary alone.
3. MANUAL: Ps 90 (`תְּפִלָּה לְמֹשֶׁה אִישׁ־הָאֱלֹהִים`): the title ends in a divine name, which rule 2 excludes. Checked by hand.

Output rows are key ranges over MACULA token keys (digits of xml:id, text order), so applying them needs no tokenization
assumptions (see psalm_title_spans.py). A leave-one-out check of rule 2's vocabulary on the 59 single-verse titles showed it is
NOT reliable as an automatic rule for long or unusual titles (it stops early on idiosyncratic words), which is why the 52
results are a reviewed, frozen table and not recomputed at spine build time.

  python -m macula.build_psalm_title_spans [--lowfat DIR] [--map FILE_OR_URL] [--out psalm_title_spans.tsv]

--lowfat DIR holds the 19-Psa-NNN-lowfat.xml chapter files (default: $MACULA_HBO_LOWFAT_DIR or the macula-hebrew clone that
parse_lowfat_hbo makes).
"""
from __future__ import annotations

import argparse
import collections
import itertools
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "psalm_title_spans.tsv"
MAP_URL = "https://cdn.bibel.wiki/_vrs/map/org-to-eng.json"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_LET = re.compile(r"[^א-ת]")
_BOUND = {"prep", "cj", "art", "pron"}           # prefixes/suffixes that carry no lemma of their own

# Closed list of Hebrew title terms (lemmas, vowel- and accent-free): genre/performance words, and the names found in titles.
TITLE_TERMS = {_LET.sub("", x) for x in (
    "מִזְמוֹר שִׁיר מַשְׂכִּיל מִכְתָּם תְּפִלָּה תְּהִלָּה תּוֹדָה נָצַח מַעֲלָה שִׁגָּיוֹן "
    "דָּוִד אָסָף קֹרַח שְׁלֹמֹה מֹשֶׁה אֵיתָן הֵימָן יְדוּתוּן יְדִידוּת").split()}
DIVINE = {_LET.sub("", x) for x in "יהוה אֵל אֱלֹהִים אֱלוֹהַּ אֲדֹנָי".split()}
MANUAL_WORDS = {90: 4}                            # Ps 90: the first 4 words of verse 1 are the title


def lemma(w: ET.Element) -> str:
    return _LET.sub("", w.get("lemma") or "")


def key_of(w: ET.Element) -> str:
    return re.sub(r"\D", "", w.get(_XML_ID, ""))


def content_words(node: ET.Element) -> list[ET.Element]:
    return [w for w in node.iter("w") if w.get("class") not in _BOUND]


def words_of(root: ET.Element, ch: int) -> dict[int, list[tuple[int, str, ET.Element]]]:
    """{verse: [(word_no, key, w), ...]} for the tokens with a real surface form (not inserted articles)."""
    out: dict[int, list] = collections.defaultdict(list)
    for w in root.iter("w"):
        m = re.match(r"PSA (\d+):(\d+)!(\d+)", w.get("ref", ""))
        if m and int(m.group(1)) == ch and w.get("unicode"):
            out[int(m.group(2))].append((int(m.group(3)), key_of(w), w))
    return out


def clauses(root: ET.Element, ch: int) -> list[ET.Element]:
    """The top-level clauses of verse 1's sentence (children of the first wg that has a clause first)."""
    sent = next((s for s in root.iter("sentence")
                 if any(w.get("ref", "").startswith(f"PSA {ch}:1!") for w in s.iter("w"))), None)
    node = next((c for c in sent if c.tag == "wg"), None) if sent is not None else None
    for _ in range(5):
        if node is None:
            return []
        kids = [c for c in node if c.tag in ("wg", "w")]
        if len(kids) >= 2 and kids[0].tag == "wg" and kids[0].get("class") == "cl":
            return kids
        if len(kids) == 1 and kids[0].tag == "wg":
            node = kids[0]
            continue
        return []
    return []


def is_title_clause(u: ET.Element, vocab: set[str]) -> bool:
    ws = content_words(u)
    if not ws:
        return False
    if any(w.get("class") == "verb" and "participle" not in (w.get("type") or "") for w in ws):
        return False                               # a finite verb or imperative is body text, not a title term
    return all(lemma(w) in vocab for w in ws)


def load_map(src: str) -> dict:
    if re.match(r"https?://", src):
        req = urllib.request.Request(src, headers={"User-Agent": "bcv-query"})
        return json.load(urllib.request.urlopen(req, timeout=60))
    return json.load(open(src, encoding="utf-8"))


def build(lowfat: Path, tvtms: dict) -> tuple[list[tuple], dict]:
    title_verses: dict[int, list[int]] = collections.defaultdict(list)
    for r in tvtms["map"]:
        if r["s"].startswith("PSA ") and "title" in r["t"]:
            ch, v = r["s"][4:].split(":")
            title_verses[int(ch)].append(int(v))
    roots = {ch: ET.parse(lowfat / f"19-Psa-{ch:03d}-lowfat.xml").getroot() for ch in range(1, 151)}
    vocab = set(TITLE_TERMS)
    for ch, vs in title_verses.items():
        for v in vs:
            vocab |= {lemma(w) for _n, _k, w in words_of(roots[ch], ch)[v] if w.get("class") not in _BOUND}
    vocab -= DIVINE
    rows = []
    for ch in range(1, 151):
        ws = words_of(roots[ch], ch)
        if ch in title_verses:
            toks = sorted((t for v in title_verses[ch] for t in ws[v]), key=lambda t: t[1])
            evidence, verses = "tvtms", "+".join(str(v) for v in sorted(title_verses[ch]))
        elif ch in MANUAL_WORDS:
            toks = sorted((t for t in ws[1] if t[0] <= MANUAL_WORDS[ch]), key=lambda t: t[1])
            evidence, verses = "manual", "1"
        else:
            us = clauses(roots[ch], ch)
            if not us or not is_title_clause(us[0], vocab):
                continue                           # no title
            take = [us[0]] + list(itertools.takewhile(lambda u: is_title_clause(u, vocab), us[1:]))
            keys = {key_of(w) for u in take for w in u.iter("w") if w.get("unicode")}
            toks = sorted((t for t in ws[1] if t[1] in keys), key=lambda t: t[1])
            evidence, verses = "macula-clauses", "1"
        hebrew = " ".join((w.get("unicode") or "") for _n, _k, w in toks)
        rows.append((ch, verses, evidence, toks[0][1], toks[-1][1], len({(k[:11]) for _n, k, _w in toks}), hebrew))
    return rows, {"tvtms_rev": tvtms.get("tvtms_rev"), "authority": tvtms.get("authority")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lowfat", type=Path)
    ap.add_argument("--map", default=MAP_URL)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    lowfat = a.lowfat or (Path(os.environ["MACULA_HBO_LOWFAT_DIR"]) if os.environ.get("MACULA_HBO_LOWFAT_DIR") else None)
    if lowfat is None:
        from macula.parse_lowfat_hbo import ENV_DIR, _fetch_source
        lowfat = _fetch_source(ENV_DIR)
    rows, meta = build(lowfat, load_map(a.map))
    cnt = collections.Counter(r[2] for r in rows)
    with a.out.open("w", encoding="utf-8") as fh:
        fh.write("# Psalm superscription spans: the MACULA token-key range of each Psalm's title (inclusive; keys sort in text order).\n")
        fh.write("# Hebrew-only: TVTMS versification (CC BY) for titles that are their own Hebrew verse(s); MACULA lowfat clauses (CC BY 4.0) for titles that open\n")
        fh.write("# verse 1; one manual case (Ps 90). No BHSA, UHB or English input. Produced by macula/build_psalm_title_spans.py (see its docstring); reviewed, frozen.\n")
        fh.write(f"# TVTMS: {meta['authority']} @ {meta['tvtms_rev']}. Psalms without a title (34) have no row. License: CC0 (facts), WLC text public domain.\n")
        fh.write("chapter\thebrew_verses\tevidence\tfirst_key\tlast_key\twords\thebrew\n")
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")
    print(f"{len(rows)} titled psalms -> {a.out}: {dict(cnt)}; title words total {sum(r[5] for r in rows)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
