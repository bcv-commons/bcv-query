"""Stage 43 of the Hebrew levels: sources.json, categories.toml and COLUMNS.md extended, the pack for research with its
README and SHA256SUMS (SPEC-levels 9), and build.json over every file of the build."""
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import levels_drafts as L
from levels_common import I1, ROOT, sha256, write_text

MARK = "\n# ---- stage 43 ----\n"
READS43 = {
    "hbo": ["words", "pieces", "clauses", "constituents", "added", "who_account", "passages"],
    "arc": ["words", "pieces", "clauses", "constituents", "added", "who_account", "passages"],
    "heb_mod": ["words", "pieces", "clauses", "constituents", "added", "who_account", "passages", "links"],
    "heb_scg": ["words", "pieces", "clauses", "constituents", "added", "who_account", "passages", "links"],
    "grc": ["words", "pieces"],
}
CODE = ["shoresh/macula/build_levels.py", "shoresh/macula/levels_common.py", "shoresh/macula/levels_explain.py",
        "shoresh/macula/levels_near.py", "shoresh/macula/levels_stage42.py", "shoresh/macula/levels_words.py",
        "shoresh/macula/levels_drafts.py", "shoresh/macula/levels_stage43.py", "shoresh/macula/levels_pack43.py"]

COLUMNS43 = {
    "texts/<level>/<text>/words.parquet": [("t", "derived"), ("book", "given"), ("chapter", "given"), ("verse", "given"),
                                           ("w", "derived"), ("text", "given or derived (op)"), ("after", "given or derived (op)"),
                                           ("sentence", "given"), ("clause", "linked"), ("op", "derived")],
    "texts/<level>/<text>/pieces.parquet": [("t", "derived"), ("n", "derived"), ("text", "given or derived (op)"),
                                            ("kind", "given"), ("lexeme", "given or derived (op)"),
                                            ("class", "given or derived (op)"), ("marks", "given or derived (op)"),
                                            ("who", "as the source; derived on a name R or A wrote"),
                                            ("who_basis", "as the source; inserted on a name R or A wrote"),
                                            ("op", "derived")],
    "texts/<level>/<text>/links.parquet": [("t", "derived"), ("n", "derived"), ("s", "derived"), ("agree", "derived"),
                                           ("agree_model", "model (null)"), ("other", "derived"), ("how", "derived"),
                                           ("basis", "derived"), ("s_n", "derived")],
    "texts/<level>/<text>/lexemes.tsv": [("lexeme", "given"), ("lemma", "given"), ("class", "given"), ("count", "derived")],
    "ops.parquet": [("op", "derived"), ("level", "—"), ("text", "—"), ("switch", "—"), ("setting", "—"),
                    ("key", "given"), ("scoring_closed", "given"), ("src_t", "given"), ("src_n", "given"),
                    ("added_clause", "given"), ("added_role", "given"), ("state", "derived"), ("reason", "derived"),
                    ("detail", "derived"), ("rule", "derived"), ("before", "given"), ("after", "derived"),
                    ("lexeme_before", "given"), ("lexeme_after", "derived"), ("ent", "given"), ("tier", "derived"),
                    ("chosen_by", "derived"), ("routes_all", "derived"), ("grade", "derived"),
                    ("form_rule", "derived"), ("draft_t", "derived")],
    "lines/<level>/<text>.<form>.tsv": [("key", "given"), ("text", "—"), ("level", "—"), ("form", "—"),
                                        ("scoring_closed", "given"), ("changed", "derived"), ("line", "derived")],
    "changed_verses.tsv": [("level", "—"), ("text", "—"), ("key", "given"), ("scoring_closed", "given"),
                           ("switches", "derived"), ("ops", "derived")],
    "measures/kept.parquet": [("level", "—"), ("text", "—"), ("clause", "given"), ("key", "given"),
                              ("scoring_closed", "given"), ("covered", "derived"), ("who_kept", "derived"),
                              ("roles_kept", "derived"), ("event_kept", "derived"), ("links_kept", "derived"),
                              ("anchor_kept", "derived"), ("ok", "derived")],
    "measures/pair.parquet": [("level", "—"), ("g", "linked"), ("edited", "derived"), ("state_l0", "derived"),
                              ("state_mod", "derived"), ("state_scg", "derived"), ("state_both", "derived")],
    "measures/reach.tsv": [("level", "—"), ("text", "—"), ("switch", "—"), ("setting", "—"), ("scope", "—"),
                           ("state", "derived"), ("reason", "derived"), ("places", "derived")],
    "measures/referents.parquet": [("level", "—"), ("text", "—"), ("key", "given"), ("scoring_closed", "given"),
                                   ("src_t", "given"), ("src_n", "given"), ("ent", "given"), ("person", "given"),
                                   ("form_src", "derived"), ("form_draft", "derived"), ("right", "derived")],
    "measures/referents_by_ent.tsv": [("level", "—"), ("text", "—"), ("ent", "given"), ("places", "derived"),
                                      ("name", "derived"), ("noun", "derived"), ("pronoun", "derived"),
                                      ("suffix", "derived"), ("ending", "derived"), ("lost", "derived"),
                                      ("wrong", "derived")],
    "anatomy.parquet": [("text", "given"), ("key", "given"), ("t", "given"), ("n", "given"), ("scoring_closed", "given"),
                        ("piece_text", "given"), ("kind", "given"), ("class", "given"), ("lexeme", "given"),
                        ("level", "derived"), ("level_kind", "derived"), ("band", "derived"), ("sense", "given"),
                        ("sense_level", "derived"), ("domain", "given"),
                        ("ref_status", "given (hbo), linked (editions)"), ("ref_form", "given (hbo), linked (editions)"),
                        ("who", "as the source"), ("who_basis", "as the source"), ("layout", "given"),
                        ("line_kind", "as the source"), ("in_quote", "derived"), ("changed_in", "derived"),
                        ("ops", "derived")],
}

CODES43 = {
    "ops.level": list(L.LEVEL_ORDER[1:]), "ops.text": list(L.TEXTS), "ops.switch": ["a", "r", "v"],
    "ops.setting": ["", "all", "amb", "k2"], "ops.state": ["applied", "not_applied"],
    "ops.reason": ["", "catch_all", "form_unattested", "fused_article", "host_infinitive", "host_other",
                   "host_participle", "indefinite", "model_input", "named_in_clause", "no_candidate", "no_form",
                   "no_name_form", "no_who", "not_ambiguous", "person_1_2", "role_other", "said_in_clause",
                   "several_referents", "taken_by_r"],
    "ops.rule": ["", "a_object", "a_subject", "r_construct", "r_object", "r_prep_bound", "r_prep_free", "r_pronoun",
                 "r_subject", "v_grp", "v_lex", "v_syn"],
    "ops.tier": ["", "grp", "lex", "syn"], "ops.grade": ["", "d0", "d1", "d2", "d3", "d4", "d5", "d6"],
    "ops.form_rule": ["", "joined", "joined_tanakh", "nf", "whole", "whole_tanakh"],
    "ops.chosen_by": ["grp", "lex", "lxx", "nt2", "rend", "ubs", "vec"],
    "ops.detail.keys": ["grp", "lex", "phrase_only", "syn"],
    "ops.added_role": ["", "A0", "A1", "AA", "poss"],
    "levels": list(L.LEVEL_ORDER), "texts": list(L.TEXTS),
    "links.other": ["arc", "hbo", "heb_mod", "heb_scg"], "links.how": ["copy", "insert", "replace"],
    "links.basis": ["derived"],
    "pieces.who_basis": ["", "chain", "explicit", "inserted", "linked", "model", "pronominal", "reference", "subject"],
    "lines.form": ["cons", "point"],
    "pair.state": ["disjoint", "near", "overlap", "same"],
    "reach.scope": ["all", "genesis", "open"],
    "referents.form_src": ["ending", "noun", "pronoun", "suffix"],
    "referents.form_draft": ["ending", "lost", "name", "noun", "pronoun", "suffix"],
    "anatomy.layout": ["", "ed_block", "ed_lines", "ed_qlines", "lines", "song"],
}


def extend_meta(out):
    src = json.load(open(out / "sources.json", encoding="utf-8"))
    for part, names in READS43.items():
        for n in names:
            p = I1 / part / f"{n}.parquet"
            src["inputs"][str(p.relative_to(ROOT))] = sha256(p)
        for f in ("participants.tsv", "sources.json"):
            p = I1 / part / f
            if p.exists():
                src["inputs"][str(p.relative_to(ROOT))] = sha256(p)
    src["inputs"] = dict(sorted(src["inputs"].items()))
    src["stage43"] = {
        "reads": {k: v for k, v in READS43.items()},
        "i1_sources_json": {p: sha256(I1 / p / "sources.json") for p in ("hbo", "arc", "heb_mod", "heb_scg", "grc",
                                                                          "lexicon")},
        "i1_build_json": "not on record (i1 has no build.json; the sha256 of each part's sources.json stands instead)",
        "not_read": ["HEBM95", "TBTA", "BHSA", "compact_renderings_999.pkl"],
    }
    write_text(out / "sources.json", json.dumps(src, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    cat = open(out / "categories.toml", encoding="utf-8").read().split(MARK)[0]
    lines = [MARK.strip(), "[codes43]"]
    for k in sorted(CODES43):
        lines.append(f'"{k}" = {json.dumps(CODES43[k], ensure_ascii=False)}')
    write_text(out / "categories.toml", cat + "\n" + "\n".join(lines) + "\n")
    colmd = open(out / "COLUMNS.md", encoding="utf-8").read().split("\n## Stage 43")[0].rstrip("\n")
    parts = [colmd, "", "## Stage 43 (SPEC-levels 7, 8)", ""]
    for f, cs in COLUMNS43.items():
        parts.append(f"### `{f}`")
        parts.append("")
        parts.append("| column | basis |")
        parts.append("|---|---|")
        for c, b in cs:
            parts.append(f"| `{c}` | {b} |")
        parts.append("")
    write_text(out / "COLUMNS.md", "\n".join(parts))


def lic(d):
    return (d or {}).get("licence") or "not on record"


def pack_files(out):
    """The files of section 9, relative to the build (the pack's own README, SHA256SUMS, terms.tsv aside)."""
    fs = []
    for sub in ("lines", "texts", "measures"):
        fs += sorted(str(p.relative_to(out)) for p in (out / sub).rglob("*") if p.is_file())
    fs += ["ops.parquet", "changed_verses.tsv", "near/pairs.parquet", "near/rend_langs.parquet", "near/distance.parquet",
           "words/levels.tsv", "words/sense_levels.tsv", "words/explanations.parquet", "words/vocabulary.tsv",
           "anatomy.parquet", "sources.json"]
    return sorted(fs)


def finish(out, counts, all_ops, cv, reach, sample_path):
    out = Path(out)
    extend_meta(out)
    pack = out / "pack"
    files = pack_files(out)
    for f in files:
        (pack / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out / f, pack / f)
    shutil.copyfile(I1 / "hbo" / "terms.tsv", pack / "terms.tsv")
    write_text(pack / "README.md", readme(out, files, counts, all_ops, cv, reach))
    names = sorted(str(p.relative_to(pack)) for p in pack.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    write_text(pack / "SHA256SUMS", "".join(f"{sha256(pack / n)}  {n}\n" for n in names))
    # build.json over every file of the build
    allf = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()
                  and p.name not in ("VALIDATION.md", "build.json") and "cache" not in p.relative_to(out).parts)
    bj = json.load(open(out / "build.json", encoding="utf-8"))
    bj["code"] = {c: sha256(ROOT / c) for c in CODE}
    bj["counts43"] = counts
    bj["files"] = {f: sha256(out / f) for f in allf}
    bj["stage"] = 43
    write_text(out / "build.json", json.dumps(bj, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


# ------------------------------------------------------------------ README (English prose; exempt by name)

def readme(out, files, counts, all_ops, cv, reach):
    srcs = json.load(open(out / "sources.json", encoding="utf-8"))
    i1 = {p: json.load(open(I1 / p / "sources.json", encoding="utf-8")) for p in ("hbo", "arc", "heb_mod", "heb_scg",
                                                                                   "grc", "lexicon")}
    lex_src = "; ".join(f"{k}: {lic(v)}" for k, v in sorted(i1["lexicon"]["sources"].items()))

    def short(s):
        return s.split(". ")[0]

    F_TANAKH = f"i1/hbo and i1/arc (licence: {lic(i1['hbo'])})"
    F_ED = f"i1/heb_mod and i1/heb_scg (licence: {lic(i1['heb_mod'])})"
    F_GRC = f"i1/grc, read as the hidden anchor only (licence: {lic(i1['grc'])})"
    L_TANAKH = f"i1/hbo and i1/arc (licence: {short(lic(i1['hbo']))}; in full in section 2)"
    L_ED = f"i1/heb_mod and i1/heb_scg (licence: {short(lic(i1['heb_mod']))})"
    L_GRC = f"i1/grc, the hidden anchor (licence: {short(lic(i1['grc']))}; in full in section 2)"
    L_LEX = f"i1/lexicon (licence of the folder: not on record; its sources: {lex_src})"
    ex = srcs["explanation_sources"]
    L_EXPL = "; ".join(f"{k} {ex[k]['file'].split('/')[-1]}: {ex[k]['licence']}" for k in sorted(ex))
    L_REND = f"compact_renderings_80.pkl, our own build (licence: {lic(srcs['rend'])})"
    L_VEC = f"our vector store, BEREL vectors (licence: {lic(srcs['vec'])})"
    L_NT2M = f"hebrew-nt-analysis (licence: {lic(srcs['nt2_model_rows']['model'])})"
    h = []
    a = h.append
    a("# The Hebrew levels, pilot 1: the pack for research")
    a("")
    a("## 1. What this is")
    a("")
    a("Hebrew drafts at several levels of the Hebrew Bible text (Genesis, Ruth, Jonah) and of the two Hebrew New")
    a("Testaments (Delitzsch `heb_mod`, Salkinson-Ginsburg `heb_scg`), written by rule from our structures, with every")
    a("change logged and linked to the source pieces. Specification: `internal-docs/source-examples-spec/levels/SPEC-levels.md`")
    a("(version 0.1). Built from build `i1` of the source examples. `i1` has no `build.json`; the sha256 of each part's")
    a("`sources.json` stands instead:")
    a("")
    for p, v in srcs["stage43"]["i1_sources_json"].items():
        a(f"- `i1/{p}/sources.json`: `{v}`")
    a("")
    a("Built on 2026-11-22 by stage 43 of the levels run. Nothing in this pack is called checked: no person and no model")
    a("has read the drafts yet (stage 44 reads a sample).")
    a("")
    a("## 2. Every file")
    a("")
    a("Sources and licences are given as our records give them (`sources.json` of `i1` and of this build, the dataset")
    a("cards under `internal-docs/*-release/README.md`). Where a licence is not in our records, the words \"not on record\"")
    a("stand. The texts and lines derive from:")
    a("")
    a(f"- the Tanakh: {F_TANAKH}")
    a(f"- the editions: {F_ED}")
    a(f"- the anchor (measurements 1 and 2 only; no Greek is written): {F_GRC}")
    a(f"- the lexicon: {L_LEX}")
    a("")
    desc = {
        "texts": ("one row per draft word / piece / link to a source piece / lexeme of the draft. Columns: words `t, book, "
                  "chapter, verse, w, text, after, sentence, clause, op`; pieces `t, n, text, kind, lexeme, class, marks, "
                  "who, who_basis, op`; links `t, n, s, agree, agree_model, other, how, basis, s_n`; lexemes `lexeme, lemma, "
                  "class, count`. Copied words rest on the source part; written words on the rules AF and NF over the same "
                  "parts and on the stage-42 tables named in 3", None),
        "lines": ("one row per verse of the scope: `key, text, level, form, scoring_closed, changed, line` (rule IN, 5)", None),
        "ops.parquet": ("one row per candidate place of a switch in a level (applied or not): `op, level, text, switch, setting, "
                        "key, scoring_closed, src_t, src_n, added_clause, added_role, state, reason, detail, rule, before, "
                        "after, lexeme_before, lexeme_after, ent, tier, chosen_by, routes_all, grade, form_rule, draft_t`", None),
        "changed_verses.tsv": ("one row per (level, text, verse) where an applied op stands: `level, text, key, "
                               "scoring_closed, switches, ops`", None),
        "measures/kept.parquet": ("measurement 1 (meaning kept), one row per (level, text, clause with an applied op): "
                                  "`level, text, clause, key, scoring_closed, covered, who_kept, roles_kept, event_kept, "
                                  "links_kept, anchor_kept, ok`; `anchor_kept` rests on the anchor", L_GRC),
        "measures/pair.parquet": ("measurement 2 (the editions as a pair), one row per (level, Greek word number g): `level, "
                                  "g, edited, state_l0, state_mod, state_scg, state_both`; g is a word number of the anchor, "
                                  "no Greek text; `near` uses `grade_strict` of `near/distance.parquet`", L_GRC),
        "measures/reach.tsv": ("measurement 4, places per `level, text, switch, setting, scope, state, reason`", None),
        "measures/referents.parquet": ("measurement 5, one row per (level, text, referring head with a participant): `level, "
                                       "text, key, scoring_closed, src_t, src_n, ent, person, form_src, form_draft, right`", None),
        "measures/referents_by_ent.tsv": ("measurement 5 per participant: `level, text, ent, places, name, noun, pronoun, "
                                          "suffix, ending, lost, wrong`", None),
        "anatomy.parquet": ("the error-anatomy join table, one row per source piece of the scope: `text, key, t, n, "
                            "scoring_closed, piece_text, kind, class, lexeme, level, level_kind, band, sense, sense_level, "
                            "domain, ref_status, ref_form, who, who_basis, layout, line_kind, in_quote, changed_in, ops`; "
                            "senses and domains from UBS through i1 (word-senses-ubs: "
                            f"{lic(i1['lexicon']['sources'].get('word-senses-ubs'))})", None),
        "near/pairs.parquet": ("one row per near-synonym evidence (a, b, route, basis): `a, b, route, basis, count, "
                               "evidence, meaning, engine, places` (routes in 3)", "see 3"),
        "near/rend_langs.parquet": ("one row per (a, b, language) of a `rend` pair: `a, b, lang, edition, "
                                    "rendering_share_a, rendering_share_b`", L_REND),
        "near/distance.parquet": ("one row per pair in a route or a strict group: `a, b, grade, k, routes, grade_strict, "
                                  "k_strict, routes_strict, group` (8)", "as the routes in 3"),
        "words/levels.tsv": ("one row per lexicon key: `lexeme, lemma, lang, class, state, count, band, kind, level, uses, "
                             "explanations, one_word, senses, count_model, level_model`", f"{L_LEX}; the explanations: {L_EXPL}"),
        "words/sense_levels.tsv": ("one row per (lexeme, single UBS sense): `lexeme, sense, count, share, level`",
                                   f"word-senses-ubs through i1: {lic(i1['lexicon']['sources'].get('word-senses-ubs'))}"),
        "words/explanations.parquet": ("one row per explanation statement read by rule W1: `expl, source, line, offset, "
                                       "witness, kind, cue, x_text, x_key, x_lexeme, x_state, y_text, y_words, y_content, "
                                       "one_word`", L_EXPL),
        "words/vocabulary.tsv": ("one row per lexeme used to explain another: `lexeme, lemma, uses, sources, explains, "
                                 "in_dv`", L_EXPL),
        "sources.json": ("the pinned inputs (sha256) and the source records of this build (a record file, not a table)",
                         "the records themselves"),
        "terms.tsv": ("the Hebrew terms of `i1/hbo/terms.tsv` (meaning values of the anatomy: `ref_status`, `line_kind`). "
                      "A copy of the file; it holds a column of Greek terms too (`grc`), which SPEC-levels 9 asks to copy "
                      "and the pack's rule of no Greek forbids; see 9", L_TANAKH),
        "SHA256SUMS": ("the sha256 of every other file of the pack", "not a source"),
        "README.md": ("this file", "not a source"),
    }
    a("### Files, one by one")
    a("")
    allnames = files + ["terms.tsv", "SHA256SUMS", "README.md"]
    for f in allnames:
        if f.startswith("texts/"):
            d, lic_ = desc["texts"]
        elif f.startswith("lines/"):
            d, lic_ = desc["lines"]
        else:
            d, lic_ = desc[f]
        if lic_ is None:
            if f.startswith(("texts/", "lines/")):
                lic_ = L_TANAKH if "/hbo" in f else L_ED
            else:
                lic_ = f"{L_TANAKH}; {L_ED}"
        a(f"- `{f}`: {d}. Sources and licence: {lic_}.")
    a("")
    a("## 3. The routes of the near-synonym table and their sources")
    a("")
    a(f"- `lex`: the medieval lexicographers' explanations (rule W1): {L_EXPL}.")
    a(f"- `ubs`: UBS domains through i1 (word-senses-ubs: {lic(i1['lexicon']['sources'].get('word-senses-ubs'))}).")
    a(f"- `nt2`: Delitzsch and Salkinson choosing two Hebrew words for one Greek word ({L_LEX}). Rows of basis `linked`"
      f" rest on the word alignments; rows of basis `model` rest on a model-made parse: {L_NT2M}, "
      f"revision {srcs['nt2_model_rows']['model'].get('revision', 'not on record')}, model "
      f"\"{'; '.join(srcs['nt2_model_rows']['model'].get('models', []))}\", no human check.")
    a(f"- `rend`: other languages' translations rendering two Hebrew words with one word: {L_REND}; about 3.8% of its"
      " entries sit on a neighbouring token (an alignment flaw named in `sources.json`). No English and no Hebrew edition"
      " is among its 80 languages.")
    a(f"- `lxx`: the Septuagint anchor of the concept groups ({L_LEX}). It is the engines' own route: every row has"
      " `engine` true.")
    a(f"- `vec`: nearness in our vector store, basis `model`: {L_VEC}; model {srcs['vec'].get('hebrew_model', 'not on record')},"
      f" built {srcs['vec'].get('built', 'not on record')}, no human check. Never alone above grade `d5`.")
    a("")
    a("## 4. How to read a level")
    a("")
    a("A level is a set of switches, applied in the order V, R, A:")
    a("")
    a("| level | switches | texts |")
    a("|---|---|---|")
    a("| `l0` | none: the source, byte for byte | hbo, heb_mod, heb_scg |")
    a("| `v2` | V: a word of level 3 or 4 gives way to a word of level 1 or 2 (an explanation, a group head, or a near-synonym on two strict routes) | all three |")
    a("| `r` | R `amb`: a 3rd-person pronoun, suffix or zero subject is written as the participant's name where another participant of the same gender and number stands nearby | all three |")
    a("| `rall` | R `all`: the same at every such place | all three |")
    a("| `a` | A: an implicit subject or object (from `added`) is written in | hbo only |")
    a("| `v2_r` | V, then R `amb` | all three |")
    a("| `v2_r_a` | V, then R `amb`, then A | hbo only |")
    a("")
    a("Every candidate place of a switch has one row in `ops.parquet`, applied or not, with the reason. A draft word")
    a("written by an op carries the op's key in `op`; a copied word has `op` empty. Every draft piece links to the")
    a("source pieces it comes from (`links.parquet`: `how` = copy, replace, insert).")
    a("")
    ex_op = next((o for o in all_ops if o["level"] == "v2_r_a" and o["text"] == "hbo" and o["state"] == "applied"
                  and o["rule"] == "r_subject"), None)
    if ex_op:
        a(f"A worked verse: `{ex_op['key']}`, op `{ex_op['op']}`: switch R (rule `{ex_op['rule']}`) wrote the name of the")
        a(f"participant `{ex_op['ent']}` after the verb `{ex_op['before']}`; it wrote `{ex_op['after']}`. Look the verse up in")
        a(f"`lines/l0/hbo.point.tsv` and `lines/v2_r_a/hbo.point.tsv` to see the line before and after.")
        a("")
    a("## 5. The two input forms (rule IN)")
    a("")
    a("A raw line is the verse's draft words: Tanakh `text` + `after` in order; the editions' `text` joined by one space.")
    a("")
    a("- `cons` (consonants only): NFD; every combining mark (category Mn) dropped; maqaf U+05BE to a space; every")
    a("  character outside U+05D0-U+05EA and the space to a space; runs of spaces to one; ends trimmed. Final letters")
    a("  as written; prefixes stay on their word.")
    a("- `point` (pointed without accents): NFD; the marks U+05B0-U+05BC, U+05C1, U+05C2, U+05C7 kept, every other")
    a("  combining mark dropped (accents U+0591-U+05AF, meteg U+05BD, rafe U+05BF, U+05C4, U+05C5); maqaf to a space;")
    a("  paseq U+05C0, sof pasuq U+05C3, nun hafukha U+05C6 and every other character outside the letters, the kept")
    a("  marks and the space to a space; runs of spaces to one; ends trimmed. The result stays in NFD order.")
    a("")
    a("`heb_mod` carries no points, so its `point` line equals its `cons` line. `heb_scg` in our copy is pointed (115,260")
    a("of 115,262 tokens in `i1`), so its `point` line keeps the points. Research said neither edition is pointed:")
    a("please say where your own Salkinson-Ginsburg lines came from. The Tanakh's `after` carries the paragraph marks")
    a("ס and פ (setumah, petuchah) after some verses; they are letters, so rule IN keeps them in both forms (see the")
    a("count in section 9).")
    a("")
    a("## 6. The column `scoring_closed`")
    a("")
    a("Every line and every op row carries `scoring_closed`. It is true for Ruth and Jonah whole, Genesis 22, Luke 1,")
    a("Luke 2, Luke 15, Philippians 3, Acts 1 and Matthew 21, and false elsewhere. Research may not score on those")
    a("verses (they are kept apart for later checks); the Hebrew stays in the pack for reading.")
    a("")
    a("## 7. Which verses changed under which switch")
    a("")
    a("`changed_verses.tsv` names every (level, text, verse) where an applied op stands, with the switches. Counts:")
    a("")
    a("| level | text | changed verses | verses |")
    a("|---|---|---|---|")
    for k, v in counts["changed_verses"].items():
        lv, tx = k.split("/")
        a(f"| `{lv}` | `{tx}` | {v} | {counts['lines'][f'{lv}/{tx}/cons']} |")
    a("")
    a("### Genesis apart")
    a("")
    a("Genesis is the fair test of Hebrew as the one source (there the Hebrew is the original). Places per level, switch,")
    a("state and reason in Genesis (scope `genesis` of `measures/reach.tsv`):")
    a("")
    a("| level | switch | setting | state | reason | places |")
    a("|---|---|---|---|---|---|")
    for r in reach:
        if r[4] == "genesis":
            a(f"| `{r[0]}` | `{r[2]}` | `{r[3]}` | `{r[5]}` | `{r[6]}` | {r[7]} |")
    a("")
    gcv = Counter((r[0]) for r in cv if r[1] == "hbo" and r[2].startswith("GEN "))
    a("Changed verses in Genesis: " + ", ".join(f"`{k}` {v}" for k, v in sorted(gcv.items())) + ".")
    a("")
    a("## 8. The graded distance and near misses")
    a("")
    a("`near/distance.parquet` grades two lexemes: `d2` the same strict group; `d3` a near-synonym on k independent routes")
    a("(`lex` with a one-word meaning, `nt2`, `rend`, `lxx`); `d4` the same domain only (`ubs`, or `lex` without a one-word")
    a("meaning, with or without `vec`); `d5` vector-near only; `d6` far (any pair not in the table). `grade_strict` and")
    a("`routes_strict` leave out the model rows. To credit a near miss fairly, recompute the grade without the routes the")
    a("switch chose by: the op row's `chosen_by` lists them (`[\"lex\"]`, `[\"grp\",\"lxx\"]`, or the pair's strict routes).")
    a("Drop the rows of those routes from `near/pairs.parquet` (and the group, for `grp`) and grade again by the rule above.")
    a("")
    a("## 9. What is model-made, what is not included, and why")
    a("")
    a("- Model-made: only the near-synonym rows of route `vec` and of route `nt2` with basis `model` (and the grades over")
    a("  all rows that use them). No level text, op row or line rests on a model: the switches read strict inputs only.")
    a("- Not included: switch A in the editions (its precision bar was not shown there); switch E (one event per clause:")
    a("  no rule yet for the infinitive's subject and the finite form); switch F (figures need a judgment at every place);")
    a("  the 999-language renderings; multi-word explanations as replacements; HEBM95 (the hub's measurement only).")
    a("- Nothing is called checked.")
    a("- Greek: no draft, line or measure holds Greek text. Two files hold Greek script because the specification puts it")
    a("  there: `near/pairs.parquet` (`evidence.via` of `nt2` rows names Greek lemma keys, SPEC-levels 5.1) and `terms.tsv`")
    a("  (its `grc` column). Strip them before a hand-over if Greek must not travel.")
    pm = counts.get("paragraph_marks")
    if pm:
        a(f"- Verse lines of the Tanakh that end in a paragraph letter ס or פ from `after`: {pm}.")
    a("")
    return "\n".join(h) + "\n"
