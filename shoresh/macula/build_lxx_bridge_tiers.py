"""The Hebrew <-> Greek lexeme bridge with every pair and its tier, for both directions (resources/lxx_bridge_tiers/).

resources/lxx_bridge.tsv keeps the top 4 Greek per Hebrew lexeme (count >= 3), which is right for Hebrew -> Greek expansion but cuts the
tail of Greek -> Hebrew. These files keep every pair with count >= 3, one file per licence:

  macula.tsv  MACULA Hebrew's per-occurrence `greekstrong` column (WLC TSV), CC BY 4.0. count = occurrences, score = P(greek | hebrew)
              over the Hebrew lexeme's occurrences that have a greekstrong. Counted as bcv-RAG/scripts/build_lxx_bridge.py counts them
              (`strongnumberx` without its homonym letter, the first Greek number), so lxx_bridge.tsv is exactly this tier's top 4.
  glaux.tsv   verse co-occurrence of the Hebrew text (spine, Hebrew numbering) and the Septuagint (lxx-glaux.db, GLAUx, CC BY-SA 4.0;
              Septuagint numbering), both converted to the English scheme with vrsmap (bibles' TVTMS maps); content words of the canonical
              books only. count = verses with both, score = Dice over the two verse sets, kept at Dice >= 0.3. CC BY-SA 4.0.

Greek numbers (2026-11-16). MACULA Hebrew's `greekstrong` gives some Greek words the number of an inflected form (Strong's own
per-form entries: σου 4675, εἶπεν 2036, ἔσται 2071, τοῦτο 5124 ...), while MACULA's Greek NT has one number per lemma. Such a pair
never meets the NT. greek_numbers.tsv maps every `greekstrong` number the Greek NT never uses to the NT number of its forms, from
MACULA alone: each occurrence's Greek form is looked up among the NT's forms (as written; then with grave read as acute; then
without acute and grave, keeping circumflex and breathings; forms written without any accent, as the names are, also without
accents), and the number is mapped when at least 3 occurrences are
found and 0.9 of them agree. Numbers with no such evidence stay as they are, with an empty `nt_strong`. The macula tier counts by the mapped number, so forms of one word merge. Numbers the NT does use are
never changed, also where the alignment's form belongs to another NT lemma (not counted: some `greek` forms upstream are garbled,
e.g. ξ for χ in ἀρξῆς). Make-tanakh-research's list (50 pairs, from GLAUx lemmas and Strong's form lists) agrees on all 48 it shares.

The Hebrew key is MACULA's `strongnumberx` in both, not the spine's `strong`: the spine merges some numbers (H0582 into H0376, H2009 into
H2005, H3069 into H3068), and the bridge is looked up by the number a reader has. Columns of both: hebrew_strong, greek_strong, tier, count, score (codes zero-padded as in lxx_bridge.tsv). Make-tanakh-grammar's
lab/bridge/strong_bridge.py was the reference (2026-10-30); the thresholds are theirs.

  python -m macula.build_lxx_bridge_tiers [--min-count 3] [--min-dice 0.3]    # MACULA_HBO_TSV=<cached macula-hebrew.tsv>, else downloaded
"""
from __future__ import annotations

import argparse
import collections
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import vrsmap  # noqa: E402
from macula.parse import HBO_URL, _rows, _src  # noqa: E402

ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine-macula.db"
GLAUX = HERE.parent / "lxx" / "data" / "lxx-glaux.db"
OUT = ROOT / "resources" / "lxx_bridge_tiers"
HEADER = "hebrew_strong\tgreek_strong\ttier\tcount\tscore\n"
MACULA_DB = HERE / "macula-spine.db"
MAP = OUT / "greek_numbers.tsv"
MAP_HEADER = "source_strong\tnt_strong\tnt_lemma\tlinks\tfound\tshare\texample\n"
MAP_MIN, MAP_SHARE = 3, 0.9


def hebrew_words(path: Path, forms: collections.Counter | None = None) -> dict[str, tuple[int, tuple[int, ...]]]:
    """{spine key: (Hebrew strong, Greek strongs)} from the MACULA Hebrew TSV. A compound value counts each of its numbers
    ("1722|1698", the form "ἐν|ἐμοί": 8 words; research 2026-11-16); before, only the first was read. With forms, also counts
    (Greek strong, Greek form) over the same rows, the parts of a compound form paired with its numbers."""
    out = {}
    for row in _rows(path):
        h = re.match(r"(\d+)", (row.get("strongnumberx") or "").strip())
        if h:
            gs = tuple(int(x) for x in re.findall(r"\d+", (row.get("greekstrong") or "").split()[0] if (row.get("greekstrong") or "").strip() else ""))
            out[row["xml:id"][1:]] = (int(h.group(1)), gs)
            if gs and forms is not None:
                fs = (row.get("greek") or "").split("|")
                for i, g in enumerate(gs):
                    forms[(g, fs[i] if len(fs) == len(gs) else row.get("greek") or "")] += 1
    return out


def _form(s: str) -> str:
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFC", s or "").lower())


def _acute(s: str) -> str:
    return unicodedata.normalize("NFC", unicodedata.normalize("NFD", _form(s)).replace("\u0300", "\u0301"))


def _tone(s: str) -> str:
    """without acute and grave (their place shifts with enclitics: ἰδέ, ἴδε); circumflex and breathings stay (ἦ is not ἤ or ἡ)"""
    return unicodedata.normalize("NFC", "".join(c for c in unicodedata.normalize("NFD", _form(s)) if c not in "\u0300\u0301"))


def _bare(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", _form(s)) if not unicodedata.combining(c)).replace("ς", "σ")


def greek_number_map(forms: collections.Counter, db: Path = MACULA_DB) -> list[tuple]:
    """[(source number, NT number or None, NT lemma, links, found, share, commonest form)] for every `greekstrong` number the
    Greek NT never uses (module docstring)."""
    nt = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    by: tuple[dict, ...] = tuple(collections.defaultdict(collections.Counter) for _ in range(4))
    lemma: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    for text, lem, strong in nt.execute("SELECT text, lemma, strong FROM macula_words WHERE lang = 'grc'"):
        m = re.match(r"\D*(\d+)", strong or "")
        if m:
            k = int(m.group(1))
            lemma[k][lem] += 1
            for d, f in zip(by, (_form, _acute, _tone, _bare)):
                d[f(text)][k] += 1
    src: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    for (g, form), n in forms.items():
        if g not in lemma:
            src[g][form] += n
    out = []
    for g, c in sorted(src.items()):
        tgt: collections.Counter = collections.Counter()
        for form, n in c.items():
            plain = _bare(form) == _form(form).replace("ς", "σ")             # written without any accent or breathing
            d = (by[0].get(_form(form)) or by[1].get(_acute(form)) or by[2].get(_tone(form))
                 or (by[3].get(_bare(form)) if plain else None))
            if d:
                tgt[d.most_common(1)[0][0]] += n
        found = sum(tgt.values())
        top, n = tgt.most_common(1)[0] if tgt else (None, 0)
        ok = found >= MAP_MIN and n / found >= MAP_SHARE
        out.append((g, top if ok else None, lemma[top].most_common(1)[0][0] if ok else "", sum(c.values()), found,
                    round(n / found, 3) if found else 0.0, c.most_common(1)[0][0]))
    return out


def macula_tier(words: dict, min_count: int) -> dict[tuple[int, int], tuple[int, float]]:
    pairs = collections.Counter((h, g) for h, gs in words.values() for g in dict.fromkeys(gs))
    tot = collections.Counter(h for h, gs in words.values() if gs)        # occurrences with a Greek link (a compound counts once)
    return {k: (c, round(c / tot[k[0]], 5)) for k, c in pairs.items() if c >= min_count}


def verse_sets(rows, scheme: str, multi: bool = False) -> dict[tuple, set]:
    """{English verse: set of the rows' values}; with multi, a list with every occurrence (build_grammar_bridge)."""
    out: dict[tuple, set | list] = collections.defaultdict(list if multi else set)
    eng: dict[tuple, list] = {}
    for b, c, v, s in rows:
        r = (b, c, v)
        if r not in eng:
            eng[r] = vrsmap.to_eng(r, scheme)
        for e in eng[r]:
            out[e].append(s) if multi else out[e].add(s)
    return out


def glaux_tier(words: dict, spine: sqlite3.Connection, glaux: sqlite3.Connection, min_count: int, min_dice: float) -> tuple[dict, dict]:
    content = spine.execute("SELECT key, book, chapter, verse FROM spine_words WHERE lexeme LIKE 'hbo:%' AND is_content = 1")
    hv = verse_sets(((b, c, v, words[k][0]) for k, b, c, v in content if k in words), "org")
    from macula.lxx_verses import verse_rows                     # Daniel from Theodotion, in Hebrew numbering
    gv = {}
    for scheme, rows in verse_rows("SELECT book, chapter, verse, strong FROM lxx_words WHERE canonical = 1 AND is_content = 1 "
                                   "AND strong IS NOT NULL"):
        gv.update(verse_sets(rows, scheme))
    both = set(hv) & set(gv)
    ch, cg, chg = collections.Counter(), collections.Counter(), collections.Counter()
    for r in both:
        ch.update(hv[r]); cg.update(gv[r])
        chg.update((h, g) for h in hv[r] for g in gv[r])
    out = {}
    for (h, g), c in sorted(chg.items()):
        if c >= min_count and (d := 2 * c / (ch[h] + cg[g])) >= min_dice:
            out[(h, g)] = (c, round(d, 3))
    return out, {"hebrew_verses": len(hv), "septuagint_verses": len(gv), "matched_verses": len(both)}


def write(path: Path, tier: str, pairs: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(HEADER)
        # ties keep the order of the pairs dict (macula: first occurrence in the text, as build_lxx_bridge.py; glaux: Greek number)
        for (h, g), (c, s) in sorted(pairs.items(), key=lambda kv: (kv[0][0], -kv[1][0])):
            f.write(f"H{h:04d}\tG{g:04d}\t{tier}\t{c}\t{s}\n")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-count", type=int, default=3)
    ap.add_argument("--min-dice", type=float, default=0.3)
    a = ap.parse_args(argv)
    forms: collections.Counter = collections.Counter()
    words = hebrew_words(_src(HBO_URL, "MACULA_HBO_TSV"), forms)
    gmap = greek_number_map(forms)
    to_nt = {g: t for g, t, *_ in gmap if t}
    words = {k: (h, tuple(to_nt.get(g, g) for g in gs)) for k, (h, gs) in words.items()}
    mac = macula_tier(words, a.min_count)
    lxx, stats = glaux_tier(words, sqlite3.connect(SPINE), sqlite3.connect(GLAUX), a.min_count, a.min_dice)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(MAP, "w", encoding="utf-8") as f:
        f.write(MAP_HEADER)
        f.writelines(f"G{g:04d}\t{f'G{t:04d}' if t else ''}\t{lem}\t{n}\t{found}\t{share}\t{ex}\n" for g, t, lem, n, found, share, ex in gmap)
    n_links = sum(forms.values())
    print(f"greek numbers: {len(gmap)} numbers the Greek NT never uses, {sum(r[3] for r in gmap):,} of {n_links:,} links; mapped "
          f"{sum(1 for r in gmap if r[1])} ({sum(r[3] for r in gmap if r[1]):,} links), left {sum(1 for r in gmap if not r[1])} "
          f"({sum(r[3] for r in gmap if not r[1]):,} links)")
    write(OUT / "macula.tsv", "macula", mac)
    write(OUT / "glaux.tsv", "glaux", lxx)
    for name, p in (("macula", mac), ("glaux", lxx)):
        print(f"{name}: {len(p):,} pairs, Hebrew {len({h for h, _ in p}):,}, Greek {len({g for _, g in p}):,}")
    print(f"glaux: {stats}; in both tiers {len(set(mac) & set(lxx)):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
