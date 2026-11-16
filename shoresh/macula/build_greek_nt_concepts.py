"""A first concept layer for the Greek NT, by projection: no model is run.

    python -m macula.build_greek_nt_concepts [--concepts DIR] [--out DIR]

bcv-commons/hebrew-word-concepts-model gives contested Hebrew words a set of concepts and each occurrence in the Tanakh its concept
(model-made, no human check). This carries those concept ids to the words of the Greek NT (MACULA Greek, Nestle 1904) over the two
bridges, so that a Greek word and a Hebrew word can meet on one concept id. A Greek word gets its concept on one of four bases, the
strongest that applies:

  quoted      the word stands where a Hebrew NT follows a Tanakh verse (bcv-commons/hebrew-nt-bridge, the links' `tanakh`), and the
              Tanakh word it renders there has a concept: that concept. The context is the Tanakh's own.
  both        a Hebrew NT renders the word by a Hebrew lexeme that has concepts, and the Septuagint renders at least one of them by
              this Greek lexeme (`concept_greek`): those concepts, ranked by how often the Septuagint does so.
  hebrew      a Hebrew NT renders the word by a Hebrew lexeme that has concepts, but the Septuagint never renders any of them by
              this Greek lexeme: the lexeme's concepts, ranked by their occurrences in the Tanakh.
  septuagint  no Hebrew NT links the word to a lexeme with concepts, but the Septuagint renders concepts by this Greek lexeme: those
              concepts, ranked by count. The same list for every occurrence of the lexeme.

The Hebrew lexeme comes from the word's links in Salkinson-Ginsburg (`heb_scg`) and Delitzsch (`heb_mod`); links of class edited-wide
are not read. Only Greek nouns, verbs, adjectives, adverbs and numerals get a concept. `editions` says which of the two link the word to the lexeme of its first concept.

Two checks, both without a hand-made answer (written to report.json):
  - on the Tanakh: each labelled occurrence's concept is guessed from its lexeme and its Septuagint word with that occurrence left
    out of the counts, against guessing the lexeme's commonest concept. It says how much the Greek word tells about the concept.
  - on the NT: for the `quoted` words the concept is also made by the other three rules, as if the word were not in a quotation (and
    with the quoted Tanakh word left out of the counts), and compared with the quoted concept.

Writes (git-ignored; packaged by macula/release_greek_nt_concepts.py):
  <out>/words.parquet        one row per Greek NT word that gets a concept: greek_id, greek_strong, greek_lemma, greek_class, concept,
                             basis, share (the first concept's weight over all candidates' weights), candidates, hebrew_strong,
                             editions, tanakh (the Tanakh word's key, basis quoted)
  <out>/candidates.parquet   one row per word and candidate concept, the first 10: greek_id, rank, concept, weight
  <out>/report.json
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

from macula import build_hebrew_nt_bridge as b

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REVISION = "5a7af3035cb38fa6ca906ae5dda0b24398be737a"            # bcv-commons/hebrew-word-concepts-model v0.5
CONCEPTS = HERE / "data" / f"hebrew-word-concepts-model-{REVISION[:8]}"
OUT = HERE / "data" / "greek-nt-concepts"
EDITIONS = ("heb_scg", "heb_mod")
BASES = ("quoted", "both", "hebrew", "septuagint")
BANDS = (0.95, 0.8, 0.6, 0.0)                                    # the first concept's share of the candidates' weight, for the checks
TOP = 10                                                         # candidates kept per word
num = lambda x: (m.group(1) if (m := re.match(r"\D*0*(\d+)", x or "")) else "")


def ranked(c: dict) -> list[tuple[str, int]]:
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))


class Concepts:
    """the concept dataset: each lexeme's concepts with their occurrences, each Greek lexeme's concepts, each word's concept"""

    def __init__(self, folder: Path):
        import pyarrow.parquet as pq
        self.lexeme = {r["code"]: b.hcode(r["strong"]) for r in pq.read_table(folder / "data" / "concepts.parquet").to_pylist()}
        self.label = {r["key"]: r["concept"] for r in pq.read_table(folder / "data" / "tokens.parquet").to_pylist() if r["concept"]}
        self.prior: dict = collections.defaultdict(collections.Counter)         # hebrew lexeme -> concept -> occurrences
        for c in self.label.values():
            self.prior[self.lexeme[c]][c] += 1
        self.greek: dict = collections.defaultdict(collections.Counter)         # greek lexeme -> concept -> occurrences rendered by it
        for r in pq.read_table(folder / "data" / "concept_greek.parquet").to_pylist():
            self.greek[b.gcode(r["greek_strong"])][r["concept"]] += r["count"]

    def project(self, g: str, hebrew: set, less: tuple | None = None) -> tuple[str, list[tuple[str, int]]]:
        """(basis, candidates) for a Greek lexeme rendered by these Hebrew lexemes. `less` = (concept, greek lexeme) of one occurrence to
        leave out of the Septuagint counts (the checks)."""
        seen = dict(self.greek.get(g, {}))
        if less and less[1] == g and seen.get(less[0]):
            seen[less[0]] -= 1
        own = [h for h in hebrew if h in self.prior]
        both = {c: seen[c] for h in own for c in self.prior[h] if seen.get(c)}
        if both:
            return "both", ranked(both)
        if own:
            return "hebrew", ranked({c: n for h in own for c, n in self.prior[h].items()})
        seen = {c: n for c, n in seen.items() if n}
        return ("septuagint", ranked(seen)) if seen else ("", [])


def tanakh_keys() -> dict[tuple, list[str]]:
    """(book, chapter, verse) -> the keys of the verse's content words, in step with build_hebrew_nt_bridge.Tanakh.verses"""
    out = collections.defaultdict(list)
    con = sqlite3.connect(HERE / "macula-spine.db")
    for key, bk, c, v, strong, cls in con.execute("select key, book, chapter, verse, strong, class from macula_words where lang = 'hbo' order by key"):
        if cls in b.H_CONTENT and b.hcode(strong):
            out[(bk, c, v)].append(key)
    return out


def quoted_words(ana: dict, rows: list[dict], tanakh: b.Tanakh, keys: dict) -> dict[tuple, str]:
    """(book, chapter, verse, i, part) of a Hebrew NT part in a marked stretch -> the key of the Tanakh word it stands for"""
    out: dict = {}
    for bk, c, v, ref in {(r["book"], r["chapter"], r["verse"], r["tanakh"]) for r in rows if r["tanakh"]}:
        tokens = ana[(bk, c, v)]
        parts = [r for i in sorted(tokens) for r in tokens[i] if r["class"] in b.H_CONTENT and b.hcode(r["strong"])]
        tb, cv = ref.split()
        tk = (tb, *map(int, cv.split(":")))
        assert len(keys[tk]) == len(tanakh.verses[tk]), tk
        for m in SequenceMatcher(None, [b.hcode(r["strong"]) for r in parts], tanakh.verses[tk], autojunk=False).get_matching_blocks():
            if m.size >= 2:
                for j in range(m.size):
                    out.setdefault((bk, c, v, parts[m.a + j]["i"], parts[m.a + j]["part"], ref), keys[tk][m.b + j])
    return out


def septuagint_words() -> dict[str, str]:
    """Tanakh word key -> the Greek lexeme of its Septuagint word (MACULA Hebrew's link, on the NT's number), as concept_greek counts it"""
    to_nt = {}
    for line in (ROOT / "resources" / "lxx_bridge_tiers" / "greek_numbers.tsv").read_text().splitlines()[1:]:
        f = line.split("\t")
        if f[1]:
            to_nt[num(f[0])] = num(f[1])
    hb = sqlite3.connect(f"file:{HERE / 'lowfat-hbo.db'}?mode=ro", uri=True)
    out = {}
    for k, g in hb.execute("select key, greekstrong from lowfat_words where is_inserted = 0 and greekstrong != ''"):
        n = num(g)
        out[k] = b.gcode(to_nt.get(n, n))
    return out


def check_tanakh(con: Concepts, lxx: dict[str, str]) -> dict:
    """each labelled occurrence's concept guessed with the occurrence left out: from lexeme and Greek word (rule `both`, else the
    lexeme's commonest), from the lexeme alone, from the Greek word alone"""
    n, band, size = collections.Counter(), collections.defaultdict(collections.Counter), collections.Counter()
    for key, c in con.label.items():
        g, h = lxx.get(key), con.lexeme[c]
        if not g or not g.startswith("G"):
            continue
        prior = dict(con.prior[h]); prior[c] -= 1
        prior = {x: k for x, k in prior.items() if k}
        guess_h = ranked(prior)[0][0] if prior else None
        basis, cand = con.project(g, set(), (c, g))                       # the Greek word alone
        basis, both = con.project(g, {h}, (c, g))                         # lexeme and Greek word; the lexeme's own count is not reduced:
        if basis != "both":                                               # with no Septuagint evidence left, the lexeme's commonest
            both = ranked(prior)
        n["occurrences with a Septuagint word"] += 1
        n["lexeme and Greek word: right"] += bool(both) and both[0][0] == c
        n["lexeme alone (its commonest concept): right"] += guess_h == c
        n["Greek word alone: right"] += bool(cand) and cand[0][0] == c
        if basis == "both":
            share = both[0][1] / sum(k for _, k in both)
            x = next(f">= {t}" if t else "below 0.6" for t in BANDS if share >= t)
            band[x]["occurrences"] += 1
            band[x]["right"] += both[0][0] == c
            band[x]["lexeme alone right"] += guess_h == c
            n["rule both applies"] += 1
            n["rule both: the concept is among the candidates"] += c in dict(both)
            size["candidates"] += len(both); size["the lexeme's concepts"] += len(prior)
    t = n["occurrences with a Septuagint word"]
    out = {**n, **{f"share: {k[:-7]}": round(v / t, 4) for k, v in n.items() if k.endswith(": right")},
           "rule both: mean candidates": round(size["candidates"] / max(n["rule both applies"], 1), 2),
           "rule both: mean concepts of the lexeme": round(size["the lexeme's concepts"] / max(n["rule both applies"], 1), 2),
           "rule both, by the first concept's share": {}}
    for x in [f">= {t}" if t else "below 0.6" for t in BANDS]:
        d = band[x]
        out["rule both, by the first concept's share"][x] = {**d, "share right": round(d["right"] / max(d["occurrences"], 1), 4),
                                                             "share right, lexeme alone": round(d["lexeme alone right"] / max(d["occurrences"], 1), 4)}
    return out


def main() -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--concepts", type=Path, default=CONCEPTS, help="a download of bcv-commons/hebrew-word-concepts-model at its revision")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    con = Concepts(a.concepts)
    gw, _ = b.greek()
    tanakh, keys, lxx = b.Tanakh(), tanakh_keys(), septuagint_words()
    hebrew: dict = collections.defaultdict(lambda: collections.defaultdict(set))    # greek id -> edition -> hebrew lexemes
    quote: dict = collections.defaultdict(dict)                                     # greek id -> edition -> Tanakh word key
    for ed in EDITIONS:
        rows = pq.read_table(b.DATA / ed / "links.parquet").to_pylist()
        qk = quoted_words(b.analysis(ed), rows, tanakh, keys)
        for r in rows:
            if r["link"] == "edited-wide" or not r["hebrew_strong"] or r["hebrew_class"] not in b.H_CONTENT:
                continue
            hebrew[r["greek_id"]][ed].add(r["hebrew_strong"])
            k = qk.get((r["book"], r["chapter"], r["verse"], r["i"], r["part"], r["tanakh"])) if r["tanakh"] else None
            if k and k in con.label and con.lexeme[con.label[k]] == r["hebrew_strong"]:
                quote[r["greek_id"]].setdefault(ed, k)
    words, cands, st, chk = [], [], collections.Counter(), collections.Counter()
    for gid, w in gw.items():
        g = w["strong"]
        if not g or w["class"] not in b.G_CONTENT:                        # nouns, verbs, adjectives, adverbs and numerals
            continue
        hs = {h for ed in EDITIONS for h in hebrew[gid][ed]} if gid in hebrew else set()
        basis, cand = con.project(g, hs)
        tk = ""
        if gid in quote:
            tk = quote[gid].get("heb_scg") or quote[gid]["heb_mod"]
            gold = con.label[tk]
            pb, pc = con.project(g, hs, (gold, lxx.get(tk)))              # the other rules, the quoted Tanakh word left out
            chk[f"{pb or 'none'}: words"] += 1
            chk[f"{pb or 'none'}: same concept"] += bool(pc) and pc[0][0] == gold
            if pb == "both":
                x = next(f">= {t}" if t else "below 0.6" for t in BANDS if pc[0][1] / sum(n for _, n in pc) >= t)
                chk[f"both, share {x}: words"] += 1
                chk[f"both, share {x}: same concept"] += pc[0][0] == gold
            prior = ranked(con.prior[con.lexeme[gold]])
            chk["lexeme's commonest concept: same"] += prior[0][0] == gold
            basis, cand = "quoted", [(gold, 1)]
        if not cand:
            continue
        top = cand[0][0]
        eds = " ".join(ed for ed in EDITIONS if gid in hebrew and con.lexeme[top] in hebrew[gid][ed])
        words.append({"greek_id": gid, "greek_strong": g, "greek_lemma": w["lemma"], "greek_class": w["class"], "concept": top, "basis": basis,
                      "share": round(cand[0][1] / sum(n for _, n in cand), 4), "candidates": len(cand),
                      "hebrew_strong": con.lexeme[top], "editions": eds, "tanakh": tk})
        cands += [{"greek_id": gid, "rank": i + 1, "concept": c, "weight": n} for i, (c, n) in enumerate(cand[:TOP])]
        if basis == "both":
            st[f"both, share {next(f'>= {t}' if t else 'below 0.6' for t in BANDS if words[-1]['share'] >= t)}"] += 1
        st[basis] += 1
        st[f"{basis}: one candidate"] += len(cand) == 1
        st[f"{basis}: both editions"] += eds == " ".join(EDITIONS)
        st[f"{basis}: nouns, verbs, adjectives"] += w["class"] in b.INDEXED
    content = sum(1 for w in gw.values() if w["class"] in b.INDEXED)
    a.out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(words, schema=pa.schema(
        [("greek_id", pa.string()), ("greek_strong", pa.string()), ("greek_lemma", pa.string()), ("greek_class", pa.string()), ("concept", pa.string()),
         ("basis", pa.string()), ("share", pa.float32()), ("candidates", pa.int16()), ("hebrew_strong", pa.string()), ("editions", pa.string()),
         ("tanakh", pa.string())])), a.out / "words.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(cands, schema=pa.schema(
        [("greek_id", pa.string()), ("rank", pa.int16()), ("concept", pa.string()), ("weight", pa.int32())])), a.out / "candidates.parquet", compression="zstd")
    quoted_n = sum(v for k, v in chk.items() if k.endswith(": words") and not k.startswith("both, share"))
    report = {"inputs": {"concepts": f"bcv-commons/hebrew-word-concepts-model@{REVISION}", "links": "bcv-commons/hebrew-nt-bridge (macula/data/hebrew-nt-bridge)",
                         "greek": "MACULA Greek, Nestle 1904 (macula-spine.db)"},
              "greek words": len(gw), "greek nouns, verbs and adjectives": content, "words with a concept": len(words),
              "nouns, verbs and adjectives with a concept": sum(st[f"{x}: nouns, verbs, adjectives"] for x in BASES),
              "concepts used": len({w["concept"] for w in words}), "greek lexemes with a concept": len({w["greek_strong"] for w in words}),
              "candidate rows": len(cands), "by basis": {x: {"words": st[x], "one candidate": st[f"{x}: one candidate"],
                                                             "both editions give the lexeme": st[f"{x}: both editions"]} for x in BASES},
              "basis both, by the first concept's share": {k[12:]: v for k, v in sorted(st.items()) if k.startswith("both, share ")},
              "check on the Tanakh": check_tanakh(con, lxx),
              "check on the quoted words": {"words": quoted_n, **{k: v for k, v in sorted(chk.items())},
                                            "share same, the other rules": round(sum(v for k, v in chk.items() if k.endswith(": same concept") and not k.startswith("both, share")) / max(quoted_n, 1), 4),
                                            "share same, lexeme's commonest concept": round(chk["lexeme's commonest concept: same"] / max(quoted_n, 1), 4)}}
    (a.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(f"[greek_nt_concepts] {len(words):,} of {len(gw):,} Greek words get a concept ({dict((x, st[x]) for x in BASES)}) -> {a.out}")


if __name__ == "__main__":
    main()
