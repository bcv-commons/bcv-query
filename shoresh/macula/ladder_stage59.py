"""Stage 59 of the Hebrew ladder: writes hebrew-levels/pilot-2/ (SPEC-ladder 6) with its build.json, sources.json,
categories.toml, COLUMNS.md and README.md. The tables come from ladder_switches.run()."""
import json
from pathlib import Path

from macula import ladder_switches as LS

SPEC = "Ladder specification, version 0.3"
CODE = ["shoresh/macula/build_ladder.py", "shoresh/macula/ladder_stage59.py", "shoresh/macula/ladder_switches.py",
        "shoresh/macula/levels_drafts.py", "shoresh/macula/levels_stage43.py", "shoresh/macula/levels_common.py"]

COLUMNS = """# Columns of hebrew-levels/pilot-2 (SPEC-ladder 6; the levels format of SPEC-levels 7)

Bases as SPEC-ladder 2.3: `given`, `derived`, `linked`, `model`.

## ops.parquet (one row per candidate place of every switch of every level; SPEC-levels 7.1)

| column | basis | meaning |
|---|---|---|
| op | derived | `op:<level>:<text>:<n>` |
| level, text, switch, setting | derived | level `l0`, `r`, `zr_r`, `z_r_a`; text `hbo`, `heb_mod`, `heb_scg`; switch `v`, `r`, `a`; setting `amb` (R), `all` / `rare` (V), `""` (A) |
| key, scoring_closed | given | the verse; SPEC-levels 7.4 |
| src_t, src_n | given | the source piece of k1 (A: the verb's stem piece) |
| added_clause, added_role | given | A only |
| state, reason | derived | `applied` / `not_applied`; the first reason that holds (SPEC-ladder 6.2, 6.4, 6.5) |
| detail | derived | R: `window` (candidate ents), `greek` (linked Greek word keys t, editions), `nf_at` (the source word t of the mention NF2 took); V: `gloss` (the Metzudat Zion gloss id); A: `nf_at` |
| rule | derived | `v_gloss`; `r_subject`, `r_pronoun`, `r_prep_free`, `r_prep_bound`, `r_construct`, `r_object`; `a_subject`, `a_object` |
| before, after | given, derived | the source word; the words written |
| lexeme_before, lexeme_after | given, derived | V only |
| ent | given | R, A |
| tier, chosen_by | derived | V: `gloss`, `["mz"]` |
| routes_all, grade | derived | not used in pilot-2 (`[]`, `""`) |
| form_rule | derived | R, A: `nf_chapter` / `nf_book` / `nf_chain` (NF2, NF2-CHAIN) or AF's `whole`, `joined`, `whole_tanakh`, `joined_tanakh` for a host form; V: `whole` |
| draft_t | derived | the draft words the op wrote |

## texts/<level>/<text>/ (SPEC-levels 7.2)

- `words.parquet`: t, book, chapter, verse, w, text, after, sentence, clause (linked), op.
- `pieces.parquet`: t, n, text, kind, lexeme, class, marks, who, who_basis, **basis**, op. `basis` (SPEC-ladder 6.1):
  the source piece's basis on a copied piece (`given` for k1/hbo, which has no basis column; `derived` or `model`
  for the editions), `derived` on every piece of a word an op wrote.
- `links.parquet`: t, n, s, agree, agree_model, other, how (`copy`, `replace`, `insert`), basis (`derived`), s_n.
- `lexemes.tsv`: lexeme, lemma, class, count.

## lines/<level>/<text>.<form>.tsv, changed_verses.tsv

Rule IN (SPEC-levels 7.3); header key, text, level, form, scoring_closed, changed, line. `changed_verses.tsv`: level,
text, key, scoring_closed, switches, ops (7.5).

## sealed/switch_sample.tsv (stage 59 brief)

switch, level, op: 30 applied op ids per switch (R at level `r` over the three texts; A and V at `z_r_a`), drawn with
`random.Random("ladder-2026-11-24").sample(ids, 30)` on one generator in the order R, A, V, from the ids sorted; all of
them where fewer than 30 exist. No reading in it: stage 63 reads the ops against their verses.
"""

CATEGORIES = """# Coded values of hebrew-levels/pilot-2 (SPEC-ladder 6)

[codes]
"levels" = ["l0", "r", "zr_r", "z_r_a"]
"texts" = ["hbo", "heb_mod", "heb_scg"]
"ops.switch" = ["a", "r", "v"]
"ops.setting" = ["", "all", "amb", "rare"]
"ops.state" = ["applied", "not_applied"]
"ops.reason.r" = %s
"ops.reason.a" = %s
"ops.reason.v" = %s
"ops.rule" = ["a_object", "a_subject", "r_construct", "r_object", "r_prep_bound", "r_prep_free", "r_pronoun", "r_subject", "v_gloss"]
"ops.form_rule" = ["", "joined", "joined_tanakh", "nf_book", "nf_chain", "nf_chapter", "whole", "whole_tanakh"]
"ops.tier" = ["", "gloss"]
"ops.chosen_by" = ["mz"]
"pieces.basis" = ["derived", "given", "model"]
"links.how" = ["copy", "insert", "replace"]
"links.basis" = ["derived"]
"lines.form" = ["cons", "point"]

[method]
NF2 = "the name text of the referent's nearest earlier mention: chapter, then book (Psalms: the psalm); verse-final and atnach words skipped; no fallback"
NF2-CHAIN = "where the chapter has no one-word mention, the nearest construct chain of the chapter (a construct head carrying the referent + a proper name: מַלְאַךְ יְהוָה) before a mention of another chapter; not bound to a preposition (name_chain_bound)"
FIN = "subjects and suffix hosts only on finite verbs"
FIN-ART = "a verb with an article prefix is a participle (no subject written)"
NUM = "a plural verb or pronoun and a person's name that is not plural (proper names carry no number); a singular host and a plural-stem name unless אֱלֹהִים-like (Strong 0430, 0136, 0113, 1167): not applied"
REL = "no subject written for the verb of a relative clause (k1 word rel NpRelp, Relp..., NpCL) whose antecedent, or a word in apposition with it, carries the same ent (relative_head)"
REL-ASYN = "no subject written where the word right before the verb, in another clause, is a noun carrying the same ent (name_just_before)"
NIC-FORM = "R: no write where a noun before the host in the host's clause is written as the name NF2 found (named_in_clause)"
A-OBJ = "a_object only outside relative clauses (in_relative), on active stems (passive_stem), where the name is not the clause's subject (object_is_subject) and not spoken of in the first or second person in the verse (speech_person)"
A-HAYAH = "no A subject on a form of הָיָה whose clause holds a noun with the preposition כְּ (measure_hayah)"
OBJ = "r_object writes the verb without its object suffix (AF), then the object marker and the name"
DEF = "every R and A write needs a definite name; lexeme 0854 (with) form_ambiguous"
DEM = "a pronoun with the article is a demonstrative; named_in_clause counts noun and pronoun stems"
KIND = "a written subject only for person:, group:, deity:, fauna:"
GK = "editions: a strict link to a Greek word carrying the same ent, same person and number"
V = "Metzudat Zion's gloss where FIT says fits; at zr_r only rare words (Tanakh count below 20); at z_r_a only words below 100 Tanakh occurrences (V-COUNT, common) and not in a formula with a divine name (V-FIX, fixed_phrase: a noun, adjective or participle right before יהוה, אֱלֹהִים or אֵל with no prefix)"
"""


def readme(info):
    mp = info["model_pieces"]
    return f"""# Hebrew levels, pilot 2 (stage 59 of the Hebrew ladder)

Built by `shoresh/macula/build_ladder.py --build pilot-1 --stage 59` from build `k1` of the source examples, the
gloss bank of `hebrew-ladder/pilot-1/banks/gloss.parquet` (Metzudat Zion, Public Domain, Sefaria) and, for the
comparison only, `hebrew-levels/pilot-1/ops.parquet`. Specification: `internal-docs/source-examples-spec/ladder/SPEC-ladder.md`
section 6, over `SPEC-levels.md` 6 and 7.

Scope: Jonah, Psalms 1-41, Isaiah 40-55, Ruth, Genesis 22-25 (`hbo`); Mark in Delitzsch (`heb_mod`) and Salkinson
(`heb_scg`). Levels: `l0` (the source), `r` (R, setting amb), `zr_r` (V rare only, then R; `hbo`), `z_r_a` (V, R, A;
`hbo`). `scoring_closed` is true on Ruth, Jonah and Genesis 22.

No value of these tables was chosen by a model. **But the editions' level texts copy k1 pieces whose `basis` is
`model`** (model parses of the unpointed and pointed editions): in Mark, `heb_mod` {mp.get('l0/heb_mod', 0)} pieces
and `heb_scg` {mp.get('l0/heb_scg', 0)} pieces at level `l0` (column `basis` of `pieces.parquet` marks each). No
switch reads a model piece as input (reason `model_input`).

The words V writes come from Metzudat Zion, one Jewish reading (peshat); the op's `detail` names the gloss id. The
names R and A write are copied from the text's own nearest earlier mention (rule NF2).

`sealed/switch_sample.tsv` holds op ids for the review of stage 63; it holds no reading.
"""


def stage59(out, sha, rel, repo):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    info = LS.run(out)
    srcs = {"build_read": "k1", "inputs": {}}
    for part in ("hbo", "arc", "heb_mod", "heb_scg"):
        for f in ("words", "pieces", "clauses", "constituents", "added", "who_account", "passages"):
            p = LS.K1 / part / f"{f}.parquet"
            if p.exists():
                srcs["inputs"][rel(p)] = sha(p)
        p = LS.K1 / part / "participants.tsv"
        srcs["inputs"][rel(p)] = sha(p)
    for p in (LS.K1 / "heb_mod" / "links.parquet", LS.K1 / "heb_scg" / "links.parquet", LS.K1 / "grc" / "pieces.parquet",
              LS.K1 / "lexicon" / "lexemes.tsv", LS.K1 / "hbo" / "terms.tsv", LS.GLOSS, LS.PILOT1 / "ops.parquet"):
        srcs["inputs"][rel(p)] = sha(p)
    srcs["gloss_bank"] = {"work": "Metzudat Zion (Yechiel Hillel Altschuler)", "license": "Public Domain, Sefaria, On Your Way",
                          "via": rel(LS.GLOSS)}
    (out / "sources.json").write_text(json.dumps(srcs, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "categories.toml").write_text(CATEGORIES % (json.dumps(list(LS.R_REASONS)), json.dumps(list(LS.A_REASONS)),
                                                       json.dumps(list(LS.V_REASONS))), encoding="utf-8")
    (out / "COLUMNS.md").write_text(COLUMNS, encoding="utf-8")
    (out / "README.md").write_text(readme(info), encoding="utf-8")
    files = {}
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name not in ("build.json", "VALIDATION.md") and "cache" not in p.relative_to(out).parts:
            files[str(p.relative_to(out))] = sha(p)
    bj = {"build": "pilot-2", "spec": SPEC, "stage": 59, "read": "k1",
          "entry": "shoresh/.venv/bin/python -I shoresh/macula/build_ladder.py --build pilot-1 --stage 59",
          "code": {c: sha(repo / c) for c in CODE}, "files": files,
          "sealed_switches": files["sealed/switch_sample.tsv"], "counts": info}
    (out / "build.json").write_text(json.dumps(bj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return bj
