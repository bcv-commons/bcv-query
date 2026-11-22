"""Stage 42 of the Hebrew levels: words/ and near/ for the whole lexicon of i1, with sources.json, categories.toml,
COLUMNS.md, build.json and the reader's sample (SPEC-levels 4, 5, 10)."""
import json
from collections import Counter
from pathlib import Path

import pyarrow as pa

import levels_explain
import levels_near
import levels_words
from levels_common import (DATA, I1, MAC, ROOT, SOURCE_FILES, jdump, lexicon, sha256, write_parquet, write_text,
                           write_tsv)

S, I, B, F = pa.string(), pa.int64(), pa.bool_(), pa.float64()

INPUTS_I1 = ["lexicon/lexemes.tsv", "lexicon/groups.parquet", "lexicon/pairs.parquet", "lexicon/sources.json",
             "hbo/words.parquet", "hbo/pieces.parquet", "hbo/lexemes.tsv", "hbo/terms.tsv",
             "arc/words.parquet", "arc/pieces.parquet", "arc/lexemes.tsv"]
INPUTS_DATA = [SOURCE_FILES[s] for s in ("mz", "rd", "mn", "mb")] + [
    "compact_renderings_80.pkl", "vector-store/lexemes.npy", "vector-store/lexemes.json", "vector-store/build.json"]
CODE = ["build_levels.py", "levels_common.py", "levels_explain.py", "levels_words.py", "levels_near.py",
        "levels_stage42.py"]

SCHEMAS = {
    "words/explanations.parquet": pa.schema([
        ("expl", S), ("source", S), ("line", I), ("offset", I), ("witness", S), ("kind", S), ("cue", S),
        ("x_text", S), ("x_key", S), ("x_lexeme", S), ("x_state", S), ("y_text", S), ("y_words", S),
        ("y_content", S), ("one_word", B)]),
    "near/pairs.parquet": pa.schema([
        ("a", S), ("b", S), ("route", S), ("basis", S), ("count", I), ("evidence", S), ("meaning", B),
        ("engine", B), ("places", S)]),
    "near/rend_langs.parquet": pa.schema([
        ("a", S), ("b", S), ("lang", S), ("edition", S), ("rendering_share_a", F), ("rendering_share_b", F)]),
    "near/distance.parquet": pa.schema([
        ("a", S), ("b", S), ("grade", S), ("k", I), ("routes", S), ("grade_strict", S), ("k_strict", I),
        ("routes_strict", S), ("group", B)]),
}
TSV = {
    "words/vocabulary.tsv": ["lexeme", "lemma", "uses", "sources", "explains", "in_dv"],
    "words/levels.tsv": ["lexeme", "lemma", "lang", "class", "state", "count", "band", "kind", "level", "uses",
                         "explanations", "one_word", "senses", "count_model", "level_model"],
    "words/sense_levels.tsv": ["lexeme", "sense", "count", "share", "level"],
}

# column -> (basis, meaning); the basis as SPEC-levels 4 and 5 give it ("—" where the specification gives none)
COLUMNS = {
    "words/explanations.parquet": [
        ("expl", "derived", "key `expl:<n>` in the table's sort order (source, line, offset)"),
        ("source", "given", "mz Metzudat Zion, rd Radak's Sefer HaShorashim, mn Mahberet Menahem, mb Malbim's Beur HaMilot"),
        ("line", "given", "0-based line of the record in the pinned file"),
        ("offset", "derived", "character offset of the cue (of the headword where there is no cue; of the gloss where there is neither) in the record's text after the tags are taken off"),
        ("witness", "given", "the Hebrew text from the headword to the end of Y (to the cue where there is no Y), tags off, NFC"),
        ("kind", "derived", "statement kind; empty where the place has no cue"),
        ("cue", "given", "the cue word as written; empty for none"),
        ("x_text", "given", "the headword as written (surrounding spaces and a closing . or : taken off)"),
        ("x_key", "derived", "`BOOK ch:v` of P; empty where W1 finds no place"),
        ("x_lexeme", "derived", "X's lexeme at P; empty where X does not resolve"),
        ("x_state", "derived", "resolved, not_found, ambiguous, no_place"),
        ("y_text", "given", "Y as written: the words W1 keeps, joined by a space"),
        ("y_words", "derived", "json list of {lexeme, rule, text} in Y's order"),
        ("y_content", "derived", "json list of the resolved content lexemes of Y, in order, without repeats"),
        ("one_word", "derived", "y_content holds exactly one lexeme and no Y word is ambiguous or none"),
    ],
    "words/vocabulary.tsv": [
        ("lexeme", "given", "as lexicon/lexemes.tsv"), ("lemma", "given", "as lexicon/lexemes.tsv"),
        ("uses", "derived", "explaining statements (meaning, likeness, derivation; X resolved) whose y_content holds it"),
        ("sources", "derived", "the source codes among its uses, sorted, space-separated"),
        ("explains", "derived", "the distinct x_lexeme of its uses"),
        ("in_dv", "derived", "uses >= 2 (D-1)"),
    ],
    "words/levels.tsv": [
        ("lexeme", "given", "key of lexicon/lexemes.tsv"), ("lemma", "given", "as lexicon/lexemes.tsv"),
        ("lang", "given", "as lexicon/lexemes.tsv"), ("class", "given", "as lexicon/lexemes.tsv"),
        ("state", "given", "as lexicon/lexemes.tsv"),
        ("count", "derived", "tanakh + heb_mod + heb_scg (strict parts)"),
        ("band", "derived", "the count's band"), ("kind", "derived", "W3"),
        ("level", "derived", "W3; empty where count is 0"), ("uses", "derived", "W2; 0 where none"),
        ("explanations", "derived", "explaining statements whose x_lexeme it is (X resolved, content Y)"),
        ("one_word", "derived", "of them, those with one_word"),
        ("senses", "given", "the distinct single sense codes of its Tanakh pieces (a count)"),
        ("count_model", "model", "count + heb_mod_model + heb_scg_model"),
        ("level_model", "model", "W3's level by count_model where it differs from level; else empty"),
    ],
    "words/sense_levels.tsv": [
        ("lexeme", "given", "a lexeme with Tanakh pieces of this single sense"),
        ("sense", "given", "the UBS sense code (15 digits) as hbo/arc pieces.sense write it"),
        ("count", "derived", "Tanakh pieces with this single sense"),
        ("share", "derived", "count / the lexeme's tanakh count in lexicon/lexemes.tsv"),
        ("level", "derived", "the larger of the lexeme's level and the level by count (W4)"),
    ],
    "near/pairs.parquet": [
        ("a", "given", "lexeme key, a < b by code point"), ("b", "given", "lexeme key"),
        ("route", "—", "lex, ubs, nt2, rend, lxx, vec"),
        ("basis", "—", "the row's basis: lex given, ubs given, nt2 linked or model, rend linked, lxx given, vec model"),
        ("count", "derived", "lex statements; ubs 1; nt2, lxx the pairs.parquet count; rend languages; vec 1"),
        ("evidence", "derived", "json: lex {kinds, one_word, sources}; ubs {domain}; nt2, lxx {via}; rend {languages}; vec {rank_a, rank_b}"),
        ("meaning", "derived", "lex: a statement of kind meaning with one_word true; false elsewhere"),
        ("engine", "—", "true on lxx rows"),
        ("places", "derived", "first three places bearing the row (lex: distinct x_key joined by '; '; nt2, lxx as pairs.parquet; else empty)"),
    ],
    "near/rend_langs.parquet": [
        ("a", "given", "lexeme key"), ("b", "given", "lexeme key"), ("lang", "given", "language code of the pickle"),
        ("edition", "given", "the edition id as the pickle names it"),
        ("rendering_share_a", "linked", "the shared owned rendering's share of a's aligned places in that language"),
        ("rendering_share_b", "linked", "the same for b"),
    ],
    "near/distance.parquet": [
        ("a", "given", "lexeme key"), ("b", "given", "lexeme key"),
        ("grade", "derived", "N7 over all rows"), ("k", "derived", "independent routes holding the pair, all rows"),
        ("routes", "derived", "json: the route codes holding it, sorted"),
        ("grade_strict", "derived", "N7 over rows not of basis model"), ("k_strict", "derived", "the same, strict"),
        ("routes_strict", "derived", "the same, strict"), ("group", "derived", "both in one strict group"),
    ],
}

TOML_CODES = {
    "explanations.source": ["mb", "mn", "mz", "rd"],
    "explanations.kind": ["", "class", "derivation", "formula", "likeness", "literal", "meaning", "phrase", "targum"],
    "explanations.x_state": ["ambiguous", "no_place", "not_found", "resolved"],
    "explanations.y_words.rule": ["ambiguous", "form", "form_prefix", "lemma", "lemma_prefix", "none", "short"],
    "levels.kind": ["dv", "explained", "function", "name", "number", "unexplained"],
    "levels.band": ["0", "1", "100_499", "20_99", "2_4", "500", "5_19"],
    "levels.level": ["0", "1", "2", "3", "4"],
    "pairs.route": list(levels_near.ROUTES),
    "pairs.basis": ["given", "linked", "model"],
    "pairs.evidence.kinds": ["derivation", "likeness", "meaning"],
    "distance.grade": ["d2", "d3", "d4", "d5", "d6"],
    "distance.routes": list(levels_near.ROUTES),
}


def toml_text(lexicon_codes, rend_langs, editions):
    out = ["# Coded values of the Hebrew levels build (SPEC-levels 0.1). Every coded value of a table is listed here.",
           "", "[method]",
           'W1 = "explanation statements: FEASIBILITY.md 1.1, unchanged (SPEC-levels 4.2)"',
           'W2 = "defining vocabulary: content lexemes with at least 2 uses (4.3, D-1)"',
           'W3 = "level of a lexeme: kind, then level by count with cuts 100, 20, 5 (4.4, D-2)"',
           'W4 = "level of a sense: the larger of the lexeme level and the level by the sense count (4.5)"',
           'N1_to_N6 = "near-synonym routes lex, ubs, nt2, rend, lxx, vec, cut points of stage 40 (5.1, D-15)"',
           'N7 = "graded distance d2 to d6 (5.2, D-19)"', "", "[codes]"]
    codes = dict(TOML_CODES)
    codes.update(lexicon_codes)
    codes["rend_langs.lang"] = rend_langs
    codes["rend_langs.edition"] = editions
    for k in sorted(codes):
        out.append(f"{json.dumps(k)} = {json.dumps(sorted(set(codes[k])), ensure_ascii=False)}")
    out.append("")
    return "\n".join(out)


def columns_md():
    out = ["# Columns of the Hebrew levels build (stage 42)", "",
           "Every column of every table, with its basis (SPEC-levels 2.3: given, derived, linked, model; \"—\" where "
           "the specification gives a row code no basis). Prose; exempt from the no-English rule by name.", ""]
    for f, cols in COLUMNS.items():
        out += [f"## {f}", "", "| column | basis | meaning |", "|---|---|---|"]
        out += [f"| `{c}` | {b} | {m} |" for c, b, m in cols]
        out.append("")
    return "\n".join(out)


def _fmt(v):
    if isinstance(v, float):
        return repr(round(v, 6))
    return v


def write_tables(out, expl, voc, lev, sen, pairs, rlangs, dist):
    E = {c: [] for c in SCHEMAS["words/explanations.parquet"].names}
    for r in expl:
        for c in E:
            v = r[c]
            E[c].append(jdump(v) if c in ("y_words", "y_content") else v)
    write_parquet(out / "words/explanations.parquet", E, SCHEMAS["words/explanations.parquet"])
    lx = lexicon()
    write_tsv(out / "words/vocabulary.tsv", TSV["words/vocabulary.tsv"],
              [[k, lx[k]["lemma"], v["uses"], v["sources"], v["explains"], v["in_dv"]] for k, v in sorted(voc.items())])
    write_tsv(out / "words/levels.tsv", TSV["words/levels.tsv"], [[r[c] for c in TSV["words/levels.tsv"]] for r in lev])
    write_tsv(out / "words/sense_levels.tsv", TSV["words/sense_levels.tsv"],
              [[_fmt(r[c]) for c in TSV["words/sense_levels.tsv"]] for r in sen])
    P = {c: [] for c in SCHEMAS["near/pairs.parquet"].names}
    for r in pairs:
        for c in P:
            P[c].append(jdump(r[c]) if c == "evidence" else r[c])
    write_parquet(out / "near/pairs.parquet", P, SCHEMAS["near/pairs.parquet"])
    R = {c: [r[c] for r in rlangs] for c in SCHEMAS["near/rend_langs.parquet"].names}
    write_parquet(out / "near/rend_langs.parquet", R, SCHEMAS["near/rend_langs.parquet"])
    D = {c: [] for c in SCHEMAS["near/distance.parquet"].names}
    for r in dist:
        for c in D:
            D[c].append(jdump(r[c]) if c in ("routes", "routes_strict") else r[c])
    write_parquet(out / "near/distance.parquet", D, SCHEMAS["near/distance.parquet"])


def sources_json(rinfo, vinfo):
    vb = json.load(open(DATA / "vector-store" / "build.json", encoding="utf-8"))
    lsj = json.load(open(I1 / "lexicon" / "sources.json", encoding="utf-8"))
    lic = {}
    for s in ("mz", "rd", "mn", "mb"):
        first = json.loads(open(DATA / SOURCE_FILES[s], encoding="utf-8").readline())
        lic[s] = {"file": f"shoresh/macula/data/{SOURCE_FILES[s]}",
                  "licence": first.get("license", "not on record"),
                  "version": first.get("version", "not on record")}
    return {
        "build_read": "i1",
        "inputs": {**{f"shoresh/macula/data/source-examples/i1/{p}": sha256(I1 / p) for p in INPUTS_I1},
                   **{f"shoresh/macula/data/{p}": sha256(DATA / p) for p in INPUTS_DATA}},
        "explanation_sources": lic,
        "rend": {"file": "shoresh/macula/data/compact_renderings_80.pkl",
                 "made_by": "our own build, shoresh/macula/build_compact_renderings.py",
                 "alignment_flaw": "about 3.8% of entries attached to a neighbouring token (build_compact_renderings.py)",
                 "languages": rinfo["languages"], "editions": rinfo["editions"],
                 "licence": "not on record"},
        "vec": {"files": ["shoresh/macula/data/vector-store/lexemes.npy", "shoresh/macula/data/vector-store/lexemes.json"],
                "basis": "model", "hebrew_model": vb.get("hebrew_model"), "built": vb.get("built"),
                "human_check": "no human check", "licence": "not on record",
                "hebrew_vectors_joined": vinfo["hebrew_vectors_joined"]},
        "nt2_model_rows": {"from": "i1/lexicon/pairs.parquet rows nt_editions basis model",
                           "model": lsj.get("model", {}).get("hebrew-nt-analysis", {})},
        "not_read": ["compact_renderings_999.pkl (D-15)", "BHSA", "TBTA", "HEBM95"],
    }


def sample_md(lev, expl, pairs, dist):
    by_x = {}
    for r in expl:
        if r["kind"] in levels_explain.EXPLAINING and r["x_state"] == "resolved" and r["y_content"]:
            by_x.setdefault(r["x_lexeme"], []).append(r)
    grade = {(d["a"], d["b"]): d for d in dist}
    lx = lexicon()
    md = ["# Stage 42 sample: fifty lexemes across the levels, forty pairs per route", "",
          "Fixed rule (SPEC-levels 10, stage 42). Lexemes: for each level 0 to 4, the rows of `words/levels.tsv` with "
          "that level in key order; rows 0, k, 2k, ... with k = rows // 10, the first ten. Each lexeme shows its "
          "first three explaining statements (X resolved, content Y) in `expl` order, with the witness. Pairs: for "
          "each route, its rows of `near/pairs.parquet` in key order (a, b, basis); rows 0, k, 2k, ... with "
          "k = rows // 40, the first forty.", ""]
    for level in range(5):
        rs = [r for r in lev if r["level"] == level]
        k = max(1, len(rs) // 10)
        md += [f"## Level {level} ({len(rs)} lexemes, k = {k})", ""]
        for r in rs[::k][:10]:
            md.append(f"### `{r['lexeme']}` {r['lemma']}")
            md.append(f"- kind `{r['kind']}`, count {r['count']}, band `{r['band']}`, uses {r['uses']}, "
                      f"explanations {r['explanations']}, senses {r['senses']}")
            st = by_x.get(r["lexeme"], [])
            if not st:
                md.append("- explaining statements: none")
            for s in st[:3]:
                ys = " ".join(f"{lx[y]['lemma']}" for y in s["y_content"])
                md.append(f"- `{s['expl']}` {s['source']} {s['x_key']} kind `{s['kind']}` cue {s['cue']} "
                          f"one_word {str(s['one_word']).lower()}; Y lexemes: {ys}")
                md.append(f"  - witness: {s['witness']}")
            md.append("")
    for route in levels_near.ROUTES:
        rs = sorted((r for r in pairs if r["route"] == route), key=lambda r: (r["a"], r["b"], r["basis"]))
        k = max(1, len(rs) // 40)
        md += [f"## Route {route} ({len(rs)} rows, k = {k})", "",
               "| a | b | lemma a | lemma b | basis | count | evidence | meaning | grade (strict) | routes |",
               "|---|---|---|---|---|---|---|---|---|---|"]
        for r in rs[::k][:40]:
            d = grade[(r["a"], r["b"])]
            md.append(f"| `{r['a']}` | `{r['b']}` | {lx[r['a']]['lemma']} | {lx[r['b']]['lemma']} | {r['basis']} | "
                      f"{r['count']} | `{jdump(r['evidence'])}` | {str(r['meaning']).lower()} | "
                      f"{d['grade']} ({d['grade_strict']}) | {' '.join(d['routes'])} |")
        md.append("")
    return "\n".join(md)


def run(out, sample_path):
    out = Path(out)
    expl = levels_explain.build()
    voc = levels_words.vocabulary(expl)
    senses = levels_words.single_senses()
    lev = levels_words.levels(expl, voc, senses)
    sen = levels_words.sense_levels(senses, lev)
    pairs, rlangs, dist, info = levels_near.build(expl)
    write_tables(out, expl, voc, lev, sen, pairs, rlangs, dist)
    lexcodes = {"levels.lang": [r["lang"] for r in lev], "levels.class": [r["class"] for r in lev],
                "levels.state": [r["state"] for r in lev]}
    write_text(out / "categories.toml", toml_text(lexcodes, sorted({r["lang"] for r in rlangs}),
                                                  sorted({r["edition"] for r in rlangs})))
    write_text(out / "COLUMNS.md", columns_md())
    src = sources_json(info["rend"], info["vec"])
    write_text(out / "sources.json", json.dumps(src, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    files = sorted(list(SCHEMAS) + list(TSV) + ["categories.toml", "COLUMNS.md", "sources.json"])
    counts = {
        "explanations": len(expl), "vocabulary": len(voc), "in_dv": sum(v["in_dv"] for v in voc.values()),
        "levels": len(lev), "sense_levels": len(sen), "rend_langs": len(rlangs), "distance": len(dist),
        "pairs_by_route_basis": {f"{a}/{b}": n for (a, b), n in sorted(Counter((r["route"], r["basis"]) for r in pairs).items())},
        "left_out": info["dropped"], "group_pairs": info["group_pairs"],
        "rend_pairs_below_10_languages": info["rend"]["pairs_below_10_languages"],
    }
    build = {"build": out.name, "stage": 42, "specification": "internal-docs/source-examples-spec/levels/SPEC-levels.md 0.1",
             "reads": "i1", "entry": f"shoresh/.venv/bin/python -I shoresh/macula/build_levels.py --build {out.name} --stage 42",
             "code": {f"shoresh/macula/{c}": sha256(MAC / c) for c in CODE},
             "files": {f: sha256(out / f) for f in files}, "counts": counts}
    write_text(out / "build.json", json.dumps(build, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    write_text(sample_path, sample_md(lev, expl, pairs, dist))
    return counts


__all__ = ["run", "ROOT"]
