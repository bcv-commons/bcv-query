"""Hebrew parts, level 2: the inflection inside MACULA Hebrew's parts (word-parts v1.0, plan
internal-docs/hebrew-greek-part-alignment-plan-2026-11-22.md sections 13-14).

    cd shoresh && .venv/bin/python -m macula.build_hebrew_parts [--out DIR]

Level 1 is MACULA's own cut and id (12 digits: the word's 11 digits + MACULA's part digit): prefixed particles, the stem,
pronominal suffixes. Level 2 cuts a MACULA part once more where the grammar books do, and numbers the pieces from the left
after MACULA's id (13 digits). A MACULA part that is not cut further is sub-part 1, so MACULA's id stays the join key.

What is cut (Hebrew only; the Aramaic parts are not cut in this release, flag `aramaic`):
  prefix   the person prefix of the yiqtol forms (yiqtol, wayyiqtol, cohortative, jussive): א ת י נ
  ending   the person / number ending of the verb (qatal -תָּ -תְּ -תִּי -ה -וּ -תֶּם -תֶּן -נוּ; yiqtol and imperative -י -וּ -נָה,
           cohortative and lengthened imperative -ָה, with a following paragogic ן) and the noun's gender / number / state
           ending (-ִים -וֹת -ֵי -ָה -ַת, on nouns, adjectives and participles)
  fused    the ending's letter is also the root's last letter, written once (כָּרַתָּ, נָתַנּוּ): one piece, the parse on it
  stem     the rest
Not cut: the stem formatives (hiphil ה-, niphal נ-, hitpael הִתְ-, the participle's מְ-), which stay in the stem;
infinitives; proper nouns; pronouns and particles. A cut never falls inside a letter: a vowel sign belongs to the
letter it is written on, so -ִים is cut as ים after the letter that carries the hireq.

Inputs: MACULA Hebrew lowfat XML (CC BY 4.0; its `morph` code per part), BDB's root groups (public domain, via
OpenScriptures/HebrewLexicon CC BY 4.0: resources/bdb_roots/root_groups.tsv; whether a feminine noun's ת is the root's) and
trees-macula.db (route a's level-1 kinds,
via macula.build_word_parts.build_hbo). BHSA is not read here (it is the yardstick in macula.check_hebrew_parts_bhsa).
Writes DIR/parts.tsv (part_id, macula_id, word_id, n, start, end, text, kind, features), DIR/checks.md, DIR/build.json,
DIR/SHA256SUMS. start / end: letters within the MACULA part, from 0, end not included.
"""
from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import json
import re
import subprocess
import unicodedata as ud
import xml.etree.ElementTree as ET
from pathlib import Path

from macula import build_word_parts as wp

HERE = Path(__file__).resolve().parent
LOWFAT = HERE / ".lowfat-src" / "WLC" / "lowfat"
OUT = HERE.parent.parent / "internal-docs" / "word-parts-v1" / "hebrew"
XID = "{http://www.w3.org/XML/1998/namespace}id"
FINAL = str.maketrans("ךםןףץ", "כמנפצ")


def letters(s):
    out = []
    for ch in s:
        if out and ud.combining(ch):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def cons(g):
    """the consonant of a letter (final forms as the plain letter), or '' for anything else"""
    return g[0].translate(FINAL) if "א" <= g[0] <= "ת" else ""


def skel(s):
    return "".join(cons(g) for g in letters(s))


def ends(cs, tails):
    """the longest tail (consonants) the consonant string ends with, or ''"""
    return max((t for t in tails if cs.endswith(t) and len(cs) > len(t)), key=len, default="")


# qatal endings by person + gender + number (consonants; the longest that fits is taken)
QATAL = {"3fs": ["ה", "ת"], "2ms": ["ת", "תה"], "2fs": ["ת", "תי"], "1cs": ["תי"], "3cp": ["ו"], "2mp": ["תמ"],
         "2fp": ["תנ"], "1cp": ["נו"]}
YIQTOL = {"2fs": ["י", "ינ"], "3mp": ["ו", "ונ"], "2mp": ["ו", "ונ"], "3fp": ["נה"], "2fp": ["נה"]}
IMPV = {"2fs": ["י"], "2mp": ["ו"], "2fp": ["נה"]}
PREFIX = {"3m": "י", "3f": "ת", "2m": "ת", "2f": "ת", "1c": "אנ", "3c": "י", "2c": "ת"}


QAMETS, SEGOL, PATAH, HIREQ = "\u05b8", "\u05b6", "\u05b7", "\u05b4"


VOWEL_SIGNS = set(chr(c) for c in range(0x05B0, 0x05BC)) | {"\u05c7"}


def mater(g):
    """a ו or י written as a vowel letter: no vowel sign of its own (holam male וֹ and shureq וּ are vowel letters;
    וֺ with holam haser, יִ, יֵ are consonants)"""
    if cons(g) not in "וי":
        return False
    own = set(g[1:]) & VOWEL_SIGNS
    return not own or cons(g) == "ו" and own == {"\u05b9"}


def fem_lemma(lemma, root_t):
    """the lemma ends in the feminine ת (-ֶת -ַת -ָת -וֹת -וּת -ִית -את), as far as BDB's root does not say it is the root's"""
    lg = letters(lemma)
    if root_t is True or len(lg) < 2 or cons(lg[-1]) != "ת":
        return False
    b = lg[-2]
    return root_t is False or cons(b) in "ויא" or any(v in b for v in (SEGOL, PATAH, QAMETS))


def nominal_tail(g, n, s, cs, lemma_cs, lemma_masc, numeral=False, gs=(), root_t=None, lemma=""):
    """the gender / number / state ending (consonants) of a noun, adjective or participle. lemma_masc: the lemma is the
    masculine singular (adjectives, participles), so a feminine ending is never in it"""
    fem_t = (root_t is False or root_t is None and not lemma_cs.endswith("ת")) and not (g == "m" and lemma_cs.endswith("ת"))
    # a ת before the ending is the feminine's, not the root's (BDB root; a masculine noun's ת, בַּיִת, is the stem's)
    before = gs[-2] if len(gs) > 1 else ""               # the letter before the last one, with its vowel signs
    qamets_he = cs.endswith("ה") and QAMETS in before     # -ָה; -ֶה -ֵה (שָׂדֶה, מִקְנֶה, שְׁמֹנֶה) is the root's ה
    if n in ("p", "d"):
        if s == "c":
            tails = ["ות", "י", "ותי"] + (["ת", "תי"] if fem_t else [])
        else:
            tails = (["ימ", "ות"] + (["ת"] if fem_t else []) + (["מ"] if not lemma_cs.endswith("מ") else [])
                     + (["ינ"] if not lemma_cs.endswith("נ") else [])) if n == "p" else ["ימ"]
            if n == "p" and (lemma_cs.endswith("י") or lemma_cs.endswith("ימ")) and cs.endswith("ימ") and HIREQ in before:
                tails = [t for t in tails if t != "ימ"] + ["מ"]  # גּוֹיִם, שָׁמַיִם, מַיִם: the yod carries its own vowel, so it is the
                                                         # stem's; the ending is -ִם (פְּלִשְׁתִּים: the yod is the ending's)
            if n == "d" and fem_t:
                tails.append("תימ")                     # שְׂפָתַיִם, שְׁתַּיִם: the feminine ת with the dual
            if n == "p" and cs.endswith("ותי"):
                tails.append("ותי")
        if n == "d" and s == "c" and fem_t:
            tails.append("תי")
        return ends(cs, tails)
    if numeral:
        if qamets_he:
            return "ה"                                  # אַרְבָּעָה, מֵאָה, עֲשָׂרָה
        if cs.endswith("ת") and fem_t:
            return "ת"                                  # אַחַת, שִׁבְעַת
        return ""
    if g not in ("f", "b"):
        return ""
    if lemma_masc:                                      # גְּדוֹלָה, קֹטְלָה, קֹטֶלֶת, שֵׁנִית
        if qamets_he:
            return "ה"
        return "ת" if cs.endswith("ת") and fem_t else ""
    if qamets_he and s != "c":
        return "ה"                                      # שָׁנָה
    if cs.endswith("ת") and root_t is not True and (lemma_cs.endswith("ה") or fem_lemma(lemma, root_t)):
        return "ת"      # the construct -ַת of a -ָה noun; the feminine -ֶת -ַת -וּת -ִית when BDB's root does not end in ת
                        # (בַּת, דֶּלֶת, מַלְכוּת; not שַׁבָּת, root שָׁבַת)
    return ""


def cut(text, morph, lemma, root_t=None):
    """[(kind, text, feature)] for one MACULA part, or None when it is not cut"""
    gs = letters(text)
    cs = "".join(cons(g) for g in gs)
    if len([c for c in cs if c]) != len([g for g in gs if cons(g)]):
        return None
    lemma_cs = skel(lemma)
    head = tail = ""
    m = re.match(r"V(.)(.)(.*)$", morph)
    if m:
        t, rest = m.group(2), m.group(3)
        if t in "pqiwhjv" and len(rest) >= 3:
            pgn = rest[:3]
            if t in "pq":
                tail = ends(cs, QATAL.get(pgn, []))
                if pgn == "3fs" and lemma_cs.endswith("ה") and cs.endswith("תה"):
                    tail = "תה"                         # ל"ה: the old feminine ת with ה (הָיְתָה, גָּלְתָה)
            elif t == "v":
                tail = ends(cs, IMPV.get(pgn, []) + (["ה"] if pgn == "2ms" and not lemma_cs.endswith("ה") else []))
            else:
                tail = ends(cs, YIQTOL.get(pgn, []) + (["ה"] if t == "h" and not lemma_cs.endswith("ה") else []))
                want = PREFIX.get(pgn[:2], "")
                if cs[:1] and cs[0] in want and len(cs) > 1:
                    head = cs[0]
        elif t in "rs" and len(rest) >= 3:
            tail = nominal_tail(rest[0], rest[1], rest[2], cs, lemma_cs, True, False, gs, None, lemma)
        elif t == "c":
            # the infinitive construct's feminine ending: עֲשׂוֹת, הֱיוֹת (ל"ה); תֵּת, לֶכֶת, שֶׁבֶת (the root's first letter gone)
            tail = ends(cs, ["ות", "ת"]) if lemma_cs.endswith("ה") else (ends(cs, ["ת"]) if not lemma_cs.endswith("ת") else "")
            if not tail and cs.endswith("ה") and not lemma_cs.endswith("ה") and len(gs) > 1 and QAMETS in gs[-2]:
                tail = "ה"                              # אַהֲבָה, יִרְאָה
    elif re.match(r"N[cg]|A[aocg]", morph) and len(morph) >= 5:
        tail = nominal_tail(morph[2], morph[3], morph[4], cs, lemma_cs, morph[0] == "A" and morph[1] != "c",
                            morph[:2] == "Ac", gs, root_t, lemma)
    # an ending that begins with ו or י needs it to be a vowel letter (מִצְוֺ|ת, not מִצְ|וֺת; גּוֹיֵ is not cut);
    # the dual's -ַיִם keeps its yod (שְׁנַ|יִם)
    dual = morph[:1] in ("N", "A") and len(morph) > 3 and morph[3] == "d"
    while tail and tail[0] in "וי" and not mater(gs[len(gs) - len(tail)]) and not (dual and tail == "ימ"):
        tail = tail[1:] if not m or m.group(2) in "rsc" else ""
    if not head and not tail:
        return None
    # letters: the prefix is the first letter; the ending the last len(tail) letters
    hn, tn = len(head), len(tail)
    if hn + tn >= len(gs):
        return None
    pieces = []
    if hn:
        pieces.append(("prefix", "".join(gs[:hn]), morph))
    stem = gs[hn:len(gs) - tn]
    fused = tn and lemma_cs[-1:] == tail[0] and (cs[len(cs) - tn - 1:len(cs) - tn] != tail[0]) \
        and not lemma_cs.endswith("ה") and m and m.group(2) in "pq"
    if fused:
        pieces.append(("fused", "".join(stem + gs[len(gs) - tn:]), morph))
    else:
        pieces.append(("stem", "".join(stem), ""))
        if tn:
            pieces.append(("ending", "".join(gs[len(gs) - tn:]), morph))
    return pieces


def read_roots(groups, strong_lemma):
    """{noun Strong's: True / False}: whether the BDB root (the verb in the word's root group) ends in ת; missing when
    the group has no verb. groups: resources/bdb_roots/root_groups.tsv (BDB, public domain, via OpenScriptures)"""
    by, pos = collections.defaultdict(list), {}
    for line in open(groups, encoding="utf-8"):
        f = line.rstrip("\n").split("\t")
        if len(f) < 5 or line.startswith("#") or f[0] == "root_id":
            continue
        by[f[0]].append(f[1]); pos[f[1]] = f[4]
    out = {}
    for rid, ss in by.items():
        verbs = [skel(strong_lemma[v]) for v in ss if pos[v] == "V" and v in strong_lemma]
        if verbs:
            t = any(v.endswith("ת") for v in verbs)
            for x in ss:
                out[x] = t
    return out


def strong_key(x):
    m = re.match(r"(\d+)", x or "")
    return f"H{int(m.group(1)):04d}" if m else ""


def read_strongs(d):
    """{macula id: Strong's as H0000}, {Strong's: lemma}"""
    ids, lem = {}, {}
    for f in sorted(glob.glob(str(d / "*.xml"))):
        for w in ET.parse(f).iter("w"):
            i, k = (w.get(XID) or "")[1:], strong_key(w.get("strongnumberx"))
            if i and k:
                ids[i] = k
                lem.setdefault(k, w.get("lemma") or "")
    return ids, lem


def read_lowfat(d):
    """{macula id: (text, morph, lemma, lang)}"""
    out = {}
    for f in sorted(glob.glob(str(d / "*.xml"))):
        for w in ET.parse(f).iter("w"):
            i = (w.get(XID) or "")[1:]
            if i:
                out[i] = (w.text or "", w.get("morph") or "", w.get("lemma") or "", w.get("lang") or "")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lowfat", type=Path, default=LOWFAT)
    ap.add_argument("--trees", type=Path, default=HERE / "trees-macula.db")
    ap.add_argument("--roots", type=Path, default=HERE.parent.parent / "resources" / "bdb_roots" / "root_groups.tsv")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    mac = read_lowfat(a.lowfat)
    strongs, strong_lemma = read_strongs(a.lowfat)
    roots = read_roots(a.roots, strong_lemma)
    rows = wp.build_hbo(a.trees)
    out, stat, flags = [], collections.Counter(), collections.Counter()
    for word_id, _, mid, surf, kind, feat in rows:
        text, morph, lemma, lang = mac.get(mid, (surf, "", "", ""))
        if ud.normalize("NFC", text) != ud.normalize("NFC", surf):
            flags["text differs between lowfat and trees"] += 1
        pieces = None
        if kind == "stem" and lang == "H":
            pieces = cut(surf, morph, lemma, roots.get(strongs.get(mid, "")))
        elif kind == "stem" and lang == "A":
            flags["aramaic (not cut)"] += 1
        if not pieces:
            pieces = [(kind, surf, "")]
        if "".join(p[1] for p in pieces) != surf:
            flags["rebuild_failed"] += 1
            pieces = [(kind, surf, "")]
        if len(pieces) > 9:
            flags["more_than_9"] += 1
        at = 0
        for n, (k, t, f) in enumerate(pieces, 1):
            ln = len(letters(t))
            out.append((f"{mid}{n}", mid, word_id, n, at, at + ln, t, k, f))
            at += ln
            stat[f"kind={k}"] += 1
        stat["cut" if len(pieces) > 1 or pieces[0][0] == "fused" else "not cut"] += 1
    ids = [r[0] for r in out]
    with open(a.out / "parts.tsv", "w", encoding="utf-8") as f:
        f.write("part_id\tmacula_id\tword_id\tn\tstart\tend\ttext\tkind\tfeatures\n")
        f.writelines("\t".join(map(str, r)) + "\n" for r in out)
    L = ["# Hebrew parts, level 2: acceptance figures", "",
         f"MACULA parts: {len(rows):,}. Level-2 parts: {len(out):,}. Cut: {stat['cut']:,}; not cut: {stat['not cut']:,}. "
         f"Rebuild failures: {flags['rebuild_failed']}. Duplicate ids: {len(ids) - len(set(ids))}. "
         f"Ids not 13 digits: {sum(1 for i in ids if not re.fullmatch(r'\d{13}', i))}. More than 9 pieces: {flags['more_than_9']}.",
         "", "## Pieces by kind", ""] + [f"- {k[5:]}: {v:,}" for k, v in sorted(stat.items()) if k.startswith("kind=")]
    L += ["", "## Flags", ""] + [f"- {k}: {v:,}" for k, v in flags.most_common()]
    (a.out / "checks.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    commit = subprocess.run(["git", "-C", str(a.lowfat), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    (a.out / "build.json").write_text(json.dumps({
        "release": "word-parts v1.0, Hebrew level 2 (local, unpublished)", "licence": "CC BY 4.0",
        "macula_hebrew": {"repository": "https://github.com/Clear-Bible/macula-hebrew", "path": "WLC/lowfat", "commit": commit},
        "macula_parts": len(rows), "parts": len(out)}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    sums = [f"{hashlib.sha256((a.out / n).read_bytes()).hexdigest()}  {n}" for n in ("parts.tsv", "checks.md", "build.json")]
    (a.out / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
