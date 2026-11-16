"""The Hebrew NT bridge: Greek NT lexeme -> Hebrew lexeme, from the Hebrew translations of the NT.

    python -m macula.build_hebrew_nt_bridge [--editions heb_scg,heb_mod] [--by-id DIR] [--compact DIR]

The Septuagint bridge (resources/lxx_bridge_tiers) goes from a Hebrew source to its Greek translation. This one goes the other
way: the Greek NT is the source, and a Hebrew translation of it (Salkinson-Ginsburg `heb_scg`, Delitzsch `heb_mod`) says which
Hebrew word a translator chose for each Greek word. Per edition it joins three published things:

  - the Greek word: MACULA Greek (Nestle 1904), its id, lemma and Strong's number (macula-spine.db; CC BY 4.0);
  - the link: lexeme-aligner's word alignment of the edition (CC0). Two forms exist:
      `by-id`    bcv-commons/alignments-by-id: Greek word id -> a token or a word part of the verse, with a class (kept, inside, part,
                 edited, edited-wide) whose hand-checked precision is on that dataset's card. Published for heb_scg.
      `compact`  bcv-commons/compact-alignments: the n-th content word (noun, verb, adjective) of the verse -> whole tokens.
                 Published for both editions. It has no classes, no function words and no word parts.
    An edition takes `by-id` when it is published for it, else `compact`;
  - the Hebrew word part with its lexeme: our analysis of the edition (bcv-commons/hebrew-nt-analysis; `macula.clause_tagger export`).

The mark `tanakh` (2026-11-16). The translators knew the Hebrew Bible. Where the NT quotes it they could write the Hebrew verse instead
of translating the Greek, and elsewhere they borrowed its phrases. There the Hebrew word is the Tanakh's choice, not the translator's
answer to the Greek word. It is found on the Hebrew side alone, with no list of quotations: a verse's nouns, verbs, adjectives, adverbs
and numerals with a Strong's number are compared, as a sequence of lexemes, with those of every Tanakh verse (MACULA Hebrew); what they
have in common in the same order is found by difflib, and of that the stretches of two lexemes or more count. A stretch weighs the sum
of ln(Tanakh verses / Tanakh verses with the lexeme) over its lexemes. A pair of verses is listed from weight 16 (QUOTE_LIST) and its
stretches are marked from weight 20 (QUOTE_MARK): read by sample, from 25 nearly all are quotations, 20-25 quotations and borrowed
phrases, 16-20 about half are phrases any Hebrew text shares (numbers, "eat and drink").

A link to a whole token is resolved to parts by rule: a token of one part is that part; for a Greek noun, verb, adjective, adverb or
numeral, the token's parts of those classes; for a Greek function word, the token's parts of the same family (conjunction, preposition,
article, pronoun, particle). A link whose parts carry no Strong's number (names, words the Hebrew Bible lacks) gives no pair.

Writes, per edition:
  resources/hebrew_nt_bridge/<edition>.tsv   hebrew_strong, greek_strong, tier, count, kept, score, quoted; pairs with count >= 3, sorted
                                             by Greek lexeme, then count. `count`: links of all classes but edited-wide; `kept`: of them,
                                             links of class kept (empty for a compact edition); `score`: count / the Greek lexeme's
                                             links that reach a Hebrew lexeme = P(hebrew | greek), the direction of translation;
                                             `quoted`: of `count`, links to a part inside a marked stretch.
  resources/hebrew_nt_bridge/quotes/<edition>.tsv   nt_ref, tanakh_ref, weight, lexemes, longest: the listed pairs of verses. The Tanakh
                                             verse has MACULA Hebrew's (the Hebrew) numbering.
  macula/data/hebrew-nt-bridge/<edition>/links.parquet   one row per Greek word and linked Hebrew part (all classes; for a release);
                                             `tanakh`: the Tanakh verse of the marked stretch the part lies in
and resources/hebrew_nt_bridge/report.json: the figures of each edition, the two editions against each other, each against the
Septuagint tiers, and (heb_scg) the compact form against the by-id form, which says what the compact form costs.

Codes are zero-padded as in the Septuagint tiers (`H2617`, `G1656`); the Hebrew key drops the homonym letter, as they do.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "resources" / "hebrew_nt_bridge"
DATA = HERE / "data" / "hebrew-nt-bridge"
ANALYSIS = HERE / "data" / "clause-tagger" / "export"
TIERS = ROOT / "resources" / "lxx_bridge_tiers"
MIN = 3
HEADER = "hebrew_strong\tgreek_strong\ttier\tcount\tkept\tscore\tquoted\n"
QUOTE_HEADER = "nt_ref\ttanakh_ref\tweight\tlexemes\tlongest\n"
QUOTE_LIST, QUOTE_MARK = 16.0, 20.0             # weight from which a pair of verses is listed, and from which its stretches are marked
G_CONTENT = {"noun", "verb", "adj", "adv", "num"}
H_CONTENT = {"noun", "verb", "adj", "adv", "num"}
FAMILY = {"conj": {"cj"}, "prep": {"prep"}, "det": {"art"}, "pron": {"pron", "rel"}, "ptcl": {"ptcl", "om", "ij"}, "intj": {"ij"}}
INDEXED = {"noun", "verb", "adj"}                # the classes compact-alignments counts as content (its _index/<BOOK>_lexemes.json)
SAFE = ("kept", "inside", "part", "edited")       # edited-wide is left out of the pair counts (17 of 36 right in the aligner's hand check)


def hcode(strong: str | None) -> str | None:
    d = "".join(c for c in (strong or "") if c.isdigit())
    return f"H{int(d):04d}" if d else None


def gcode(strong) -> str | None:
    s = str(strong or "")
    return f"G{int(s):04d}" if s.isdigit() else None


def greek() -> tuple[dict, dict]:
    """id -> word, and "BOOK C:V" -> the verse's ids in order"""
    con = sqlite3.connect(HERE / "macula-spine.db")
    words, verses = {}, collections.defaultdict(list)
    for xid, b, c, v, lemma, strong, cls in con.execute(
            "select xml_id, book, chapter, verse, lemma, strong, class from macula_words where lang = 'grc' order by key"):
        words[xid] = {"book": b, "chapter": c, "verse": v, "lemma": lemma, "strong": gcode(strong), "class": cls, "n": str(strong or "").lstrip("0")}
        verses[f"{b} {c}:{v}"].append(xid)
    return words, verses


def analysis(edition: str) -> dict:
    """(book, chapter, verse) -> {token i: [its part rows]}"""
    import pyarrow.parquet as pq
    out: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in pq.read_table(ANALYSIS / edition / "words.parquet").to_pylist():
        if r["class"] != "verse-number":
            out[(r["book"], r["chapter"], r["verse"])][r["i"]].append(r)
    return out


def book_files(folder: Path) -> dict[str, Path]:
    return {f.name.split("_")[0]: f for f in sorted(folder.glob("*_*.json")) if not f.name.endswith(".meta.json")}


def links_by_id(folder: Path):
    """(book, chapter, verse of the edition, [positions], [Greek ids], class)"""
    for book, f in book_files(folder).items():
        for cv, d in json.loads(f.read_text()).items():
            c, v = map(int, cv.split(":"))
            for pos, ids, cls in d["links"]:
                yield book, c, v, pos, ids, cls


def content_units(ids: list[str], gw: dict, lex: list[str]) -> list[list[str]] | None:
    """the verse's content words as compact-alignments counts them: one unit per entry of its lexeme list, None when they cannot be matched"""
    cont = [i for i in ids if gw[i]["class"] in INDEXED]
    want = [str(x).lstrip("0") for x in lex]
    if [gw[i]["n"] for i in cont] == want:
        return [[i] for i in cont]
    units, at = [], 0
    for w in want:                                   # adjacent words of one lexeme are one unit; a compound lexeme ("1417+3461") spans its words
        parts = w.split("+")
        got = []
        for p in parts:
            p = p.lstrip("0")
            while at < len(cont) and gw[cont[at]]["n"] != p:
                at += 1
            if at == len(cont):
                return None
            got.append(cont[at]); at += 1
            while at < len(cont) and len(parts) == 1 and gw[cont[at]]["n"] == p and (len(units) + 1 == len(want) or want[len(units) + 1] != w):
                got.append(cont[at]); at += 1
        units.append(got)
    return units


def links_compact(folder: Path, index: Path, gw: dict, gv: dict, hashes: dict[str, str], stats: collections.Counter):
    """(book, chapter, verse, [token positions], [Greek ids], "compact"); the verse is the Greek one, which the edition shares outside
    the few verses numbered otherwise (counted in stats, not linked)"""
    for book, want in hashes.items():
        f = folder / f"{book}_{want}.json"
        if not f.exists():
            raise SystemExit(f"{f}: the compact file of this text is not in the download (text changed?)")
        lex = json.loads((index / f"{book}_lexemes.json").read_text())
        arr = json.loads(f.read_text())
        if len(arr) != len(lex):
            raise SystemExit(f"{book}: {len(arr)} compact verses against {len(lex)} in the index")
        for (ref, lx), line in zip(lex.items(), arr):
            if not line:
                continue
            units = content_units(gv.get(ref, []), gw, lx)
            if units is None:
                stats["compact verses whose content words could not be matched"] += 1
                continue
            c, v = map(int, ref.split()[1].split(":"))
            for item in line.split():
                o, span = item.split(":")
                pos: list[int] = []
                for piece in span.split(","):
                    a, _, z = piece.partition("-")
                    pos.extend(range(int(a), int(z or a) + 1))
                yield book, c, v, pos, units[int(o)], "compact"


def resolve(pos, tokens: dict, gcls: str) -> list[dict] | None:
    """the Hebrew parts a link's positions name; None when a position is not in the verse"""
    out = []
    for p in pos:
        if isinstance(p, str):
            i, k = map(int, p.split("."))
            row = next((r for r in tokens.get(i, ()) if r["part"] == k), None)
            if row is None:
                return None
            out.append(row)
            continue
        parts = tokens.get(p)
        if not parts:
            return None
        if len(parts) == 1:
            out.extend(parts)
        elif gcls in G_CONTENT:
            out.extend(r for r in parts if r["class"] in H_CONTENT)
        else:
            out.extend(r for r in parts if r["class"] in FAMILY.get(gcls, ()))
    return out


class Tanakh:
    """the Tanakh's verses as sequences of content lexemes, for finding the verse a Hebrew NT verse follows"""

    def __init__(self, verses: dict[tuple, list[str]] | None = None):
        if verses is None:
            verses = collections.defaultdict(list)
            con = sqlite3.connect(HERE / "macula-spine.db")
            for b, c, v, strong, cls in con.execute("select book, chapter, verse, strong, class from macula_words where lang = 'hbo' order by key"):
                if cls in H_CONTENT and hcode(strong):
                    verses[(b, c, v)].append(hcode(strong))
        self.verses = dict(verses)
        df = collections.Counter(h for s in self.verses.values() for h in set(s))
        self.idf = {h: math.log(len(self.verses) / n) for h, n in df.items()}
        self.pairs: dict = collections.defaultdict(set)                     # two lexemes in a row -> the verses that have them so
        for k, s in self.verses.items():
            for x in zip(s, s[1:]):
                self.pairs[x].add(k)

    def follows(self, seq: list[str]) -> list[tuple]:
        """(weight, lexemes, longest, Tanakh verse, positions in seq) for every Tanakh verse seq shares stretches of weight >= QUOTE_LIST
        with, heaviest first. A verse can only reach the weight if the two-lexeme sequences it shares with seq weigh that much."""
        bound: collections.Counter = collections.Counter()
        for x in zip(seq, seq[1:]):
            for k in self.pairs.get(x, ()):
                bound[k] += self.idf[x[0]] + self.idf[x[1]]
        out = []
        for k, top in bound.items():
            if top < QUOTE_LIST:
                continue
            runs = [m for m in SequenceMatcher(None, seq, self.verses[k], autojunk=False).get_matching_blocks() if m.size >= 2]
            at = [m.a + j for m in runs for j in range(m.size)]
            weight = sum(self.idf[seq[i]] for i in at)
            if weight >= QUOTE_LIST:
                out.append((round(weight, 1), len(at), max(m.size for m in runs), k, at))
        return sorted(out, key=lambda x: (-x[0], x[3]))


def quotes(ana: dict, tanakh: Tanakh, order: list[str]) -> tuple[list[tuple], dict]:
    """the listed pairs of verses (nt_ref, tanakh_ref, weight, lexemes, longest) in the order of the text, and
    (book, chapter, verse, i, part) -> the Tanakh verse of the marked stretch the part lies in (the heaviest, when several)"""
    listed, marked = [], {}
    for (b, c, v), tokens in sorted(ana.items(), key=lambda x: (order.index(x[0][0]), x[0][1], x[0][2])):
        parts = [r for i in sorted(tokens) for r in tokens[i] if r["class"] in H_CONTENT and hcode(r["strong"])]
        for weight, n, longest, (tb, tc, tv), at in tanakh.follows([hcode(r["strong"]) for r in parts]):
            ref = f"{tb} {tc}:{tv}"
            listed.append((f"{b} {c}:{v}", ref, weight, n, longest))
            if weight >= QUOTE_MARK:
                for i in at:
                    marked.setdefault((b, c, v, parts[i]["i"], parts[i]["part"]), ref)
    return listed, marked


def build(edition: str, form: str, links, gw: dict, ana: dict, marked: dict | None = None) -> tuple[list[dict], dict]:
    rows, st = [], collections.Counter()
    for book, c, v, pos, ids, cls in links:
        tokens = ana.get((book, c, v))
        if tokens is None:
            st["links in a verse the analysis lacks"] += 1
            continue
        for gid in ids:
            g = gw[gid]
            parts = resolve(pos, tokens, g["class"])
            st[f"greek words linked ({cls})"] += 1
            if parts is None:
                st["links to a position the analysis lacks"] += 1
                continue
            if not parts:
                st["links with no part of a fitting class"] += 1
            for r in parts:
                rows.append({"edition": edition, "greek_id": gid, "greek_strong": g["strong"], "greek_lemma": g["lemma"], "greek_class": g["class"],
                             "book": book, "chapter": c, "verse": v, "i": r["i"], "part": r["part"], "hebrew_strong": hcode(r["strong"]),
                             "hebrew_lemma": r["lemma"], "hebrew_class": r["class"], "source": r["source"], "link": cls, "form": form,
                             "tanakh": (marked or {}).get((book, c, v, r["i"], r["part"]))})
    return rows, dict(st)


def tier(rows: list[dict], edition: str) -> list[tuple]:
    count, kept, total, quoted = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    for r in rows:
        if r["link"] == "edited-wide" or not r["greek_strong"] or not r["hebrew_strong"]:
            continue
        k = (r["hebrew_strong"], r["greek_strong"])
        count[k] += 1
        kept[k] += r["link"] == "kept"
        quoted[k] += bool(r.get("tanakh"))
        total[r["greek_strong"]] += 1
    out = [(h, g, edition, n, kept[(h, g)] if any(kept.values()) else "", round(n / total[g], 5), quoted[(h, g)])
           for (h, g), n in count.items() if n >= MIN]
    return sorted(out, key=lambda x: (x[1], -x[3], x[0]))


def per_word(rows: list[dict]) -> dict[str, frozenset]:
    """Greek content word id -> the Hebrew lexemes it is linked to (pair-counting links only)"""
    d = collections.defaultdict(set)
    for r in rows:
        if r["greek_class"] in INDEXED and r["link"] != "edited-wide" and r["hebrew_strong"] and r["hebrew_class"] in H_CONTENT:
            d[r["greek_id"]].add(r["hebrew_strong"])
    return {k: frozenset(v) for k, v in d.items()}


def agreement(a: dict, b: dict) -> dict:
    both = [k for k in a if k in b]
    return {"greek content words with a Hebrew lexeme in both": len(both), "same lexemes": sum(a[k] == b[k] for k in both),
            "share same": round(sum(a[k] == b[k] for k in both) / max(len(both), 1), 4),
            "share with a lexeme in common": round(sum(bool(a[k] & b[k]) for k in both) / max(len(both), 1), 4)}


def septuagint() -> dict[str, set]:
    out = {}
    for name in ("macula", "glaux"):
        out[name] = {tuple(l.split("\t")[:2]) for l in (TIERS / f"{name}.tsv").read_text().splitlines()[1:]}
    return out


def against_septuagint(t: list[tuple], lxx: dict[str, set], gw: dict) -> dict:
    pairs = {(h, g) for h, g, *_ in t}
    weight = {(h, g): n for h, g, _, n, *_ in t}
    any_lxx = lxx["macula"] | lxx["glaux"]
    lxx_h, lxx_g = {h for h, _ in any_lxx}, {g for _, g in any_lxx}
    nt_g = {w["strong"] for w in gw.values() if w["strong"]}
    hit = pairs & any_lxx
    new_g = {g for _, g in pairs} - lxx_g
    cls: dict = collections.defaultdict(collections.Counter)
    for w in gw.values():
        cls[w["strong"]][w["class"] in INDEXED] += 1
    content = {g for g, c in cls.items() if c[True] > c[False]}             # lexemes that are mostly nouns, verbs or adjectives
    cp = {p for p in pairs if p[1] in content}
    return {"pairs": len(pairs), "hebrew lexemes": len({h for h, _ in pairs}), "greek lexemes": len({g for _, g in pairs}),
            "pairs of greek nouns, verbs and adjectives": len(cp), "of them also in a Septuagint tier": len(cp & any_lxx),
            "pairs also in a Septuagint tier": len(hit), "share of pairs": round(len(hit) / max(len(pairs), 1), 4),
            "share of links on those pairs": round(sum(weight[p] for p in hit) / max(sum(weight.values()), 1), 4),
            "pairs in macula tier": len(pairs & lxx["macula"]), "pairs in glaux tier": len(pairs & lxx["glaux"]),
            "pairs new to the Septuagint tiers": len(pairs - any_lxx),
            "hebrew lexemes with no Septuagint pair that gain one": len({h for h, _ in pairs} - lxx_h),
            "NT greek lexemes": len(nt_g), "NT greek lexemes with a Septuagint pair": len(nt_g & lxx_g),
            "NT greek lexemes with no Septuagint pair that gain one": len(new_g),
            "NT words of those greek lexemes": sum(1 for w in gw.values() if w["strong"] in new_g)}


def quote_figures(rows: list[dict], listed: list[tuple], marked: dict, t: list[tuple], lxx: dict[str, set]) -> dict:
    """what the mark covers, and the check it allows: inside a marked stretch the Hebrew word is the Tanakh's own, so the Septuagint's
    pairs should fit the links there more often than elsewhere"""
    any_lxx = lxx["macula"] | lxx["glaux"]
    n, hit = collections.Counter(), collections.Counter()
    for r in rows:
        if r["link"] != "edited-wide" and r["greek_strong"] and r["hebrew_strong"] and r["greek_class"] in INDEXED and r["hebrew_class"] in H_CONTENT:
            n[bool(r["tanakh"])] += 1
            hit[bool(r["tanakh"])] += (r["hebrew_strong"], r["greek_strong"]) in any_lxx
    return {"pairs of verses listed": len(listed), "NT verses listed": len({x[0] for x in listed}),
            "NT verses with a marked stretch": len({k[:3] for k in marked}), "Tanakh verses they follow": len(set(marked.values())),
            "hebrew parts in a marked stretch": len(marked),
            "counted links in a marked stretch": sum(1 for r in rows if r["tanakh"] and r["link"] != "edited-wide" and r["greek_strong"] and r["hebrew_strong"]),
            "content links in a marked stretch": n[True], "of them on a Septuagint pair": round(hit[True] / max(n[True], 1), 4),
            "content links outside": n[False], "of them on a Septuagint pair (outside)": round(hit[False] / max(n[False], 1), 4),
            "pairs with fewer than 3 links outside the marked stretches": sum(1 for x in t if x[3] - x[6] < MIN),
            "pairs with a link in a marked stretch": sum(1 for x in t if x[6])}


def write_links(rows: list[dict], folder: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    folder.mkdir(parents=True, exist_ok=True)
    sch = pa.schema([("edition", pa.string()), ("greek_id", pa.string()), ("greek_strong", pa.string()), ("greek_lemma", pa.string()),
                     ("greek_class", pa.string()), ("book", pa.string()), ("chapter", pa.int16()), ("verse", pa.int16()), ("i", pa.int16()),
                     ("part", pa.int8()), ("hebrew_strong", pa.string()), ("hebrew_lemma", pa.string()), ("hebrew_class", pa.string()),
                     ("source", pa.string()), ("link", pa.string()), ("form", pa.string()), ("tanakh", pa.string())])
    pq.write_table(pa.Table.from_pylist(rows, schema=sch), folder / "links.parquet", compression="zstd")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--editions", default="heb_scg,heb_mod")
    ap.add_argument("--by-id", default=str(HERE / "data" / "alignments-by-id-v1.0"), help="a download of bcv-commons/alignments-by-id at a tag")
    ap.add_argument("--by-id-revision", default="v1.0")
    ap.add_argument("--compact", default="", help="a download of bcv-commons/compact-alignments (default: the one folder data/compact-alignments-*)")
    a = ap.parse_args()
    compact = Path(a.compact) if a.compact else sorted((HERE / "data").glob("compact-alignments-*"))[-1]
    gw, gv = greek()
    lxx = septuagint()
    tanakh = Tanakh()
    (OUT / "quotes").mkdir(parents=True, exist_ok=True)
    verses_marked: dict[str, set] = {}
    report: dict = {"inputs": {"by_id": f"bcv-commons/alignments-by-id@{a.by_id_revision}", "compact": f"bcv-commons/compact-alignments@{compact.name.rsplit('-', 1)[1]}",
                               "greek": "MACULA Greek, Nestle 1904 (macula-spine.db)", "septuagint_tiers": "resources/lxx_bridge_tiers", "tanakh": "MACULA Hebrew (macula-spine.db)"},
                    "quote_rule": {"listed_from_weight": QUOTE_LIST, "marked_from_weight": QUOTE_MARK}, "editions": {}}
    words: dict[str, dict] = {}
    for ed in a.editions.split(","):
        if not (ANALYSIS / ed / "words.parquet").exists():
            print(f"[hebrew_nt_bridge] {ed}: no analysis export, skipped")
            continue
        ana = analysis(ed)
        manifest = json.loads((ANALYSIS / ed / "manifest.json").read_text())
        hashes = {b: m["file_hash"] for b, m in manifest["books"].items()}
        cst: collections.Counter = collections.Counter()
        listed, marked = quotes(ana, tanakh, list(dict.fromkeys(w["book"] for w in gw.values())))
        (OUT / "quotes" / f"{ed}.tsv").write_text(QUOTE_HEADER + "".join("\t".join(map(str, r)) + "\n" for r in listed))
        verses_marked[ed] = {k[:3] for k in marked}
        crows, cstat = build(ed, "compact", links_compact(compact / "h" / "heb" / ed, compact / "_index", gw, gv, hashes, cst), gw, ana, marked)
        cstat.update(cst)
        by_id = Path(a.by_id) / "n1904" / "h" / "heb" / ed
        e: dict = {"analysis_model": manifest["model"]}
        if by_id.is_dir():
            if {b: f.stem.split("_")[1] for b, f in book_files(by_id).items()} != hashes:
                raise SystemExit(f"{ed}: the by-id files are of another text than the analysis")
            rows, stat = build(ed, "by-id", links_by_id(by_id), gw, ana, marked)
            e["compact_against_by_id"] = agreement(per_word(crows), per_word(rows))
            e["compact_figures"] = cstat
        else:
            rows, stat = crows, cstat
        form = rows[0]["form"]
        t = tier(rows, ed)
        (OUT / f"{ed}.tsv").write_text(HEADER + "".join("\t".join(map(str, r)) + "\n" for r in t))
        write_links(rows, DATA / ed)
        content = [gid for gid, w in gw.items() if w["class"] in INDEXED]
        pw = per_word(rows)
        linked = {r["greek_id"] for r in rows}
        e.update({"form": form, "figures": stat, "link_rows": len(rows),
                  "greek content words": len(content), "greek content words linked to a Hebrew part": sum(1 for g in content if g in linked),
                  "greek content words with a Hebrew lexeme": len(pw),
                  "linked hebrew content parts": sum(1 for r in rows if r["hebrew_class"] in H_CONTENT),
                  "of them with a Strong's number": sum(1 for r in rows if r["hebrew_class"] in H_CONTENT and r["hebrew_strong"]),
                  "tier": against_septuagint(t, lxx, gw), "quotes": quote_figures(rows, listed, marked, t, lxx)})
        report["editions"][ed] = e
        words[ed] = pw
        print(f"[hebrew_nt_bridge] {ed} ({form}): {len(rows)} link rows, {len(t)} pairs with count >= {MIN} -> {OUT / (ed + '.tsv')}")
    if len(words) == 2:
        a_, b_ = list(words)
        report["agreement"] = {"editions": [a_, b_], **agreement(words[a_], words[b_]),
                               "NT verses with a marked stretch in both": len(verses_marked[a_] & verses_marked[b_]),
                               "in either": len(verses_marked[a_] | verses_marked[b_])}
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(f"[hebrew_nt_bridge] -> {OUT / 'report.json'}")


if __name__ == "__main__":
    main()
