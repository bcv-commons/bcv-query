"""Package the four part-link datasets of 2026-11-23, each as its own HF dataset folder (nothing is uploaded):

    cd shoresh && .venv/bin/python3 -m macula.release_part_links pieces   --out DIR [--allow-dirty]
    cd shoresh && .venv/bin/python3 -m macula.release_part_links tree     --out DIR [--allow-dirty]
    cd shoresh && .venv/bin/python3 -m macula.release_part_links tree-sa  --out DIR [--allow-dirty]
    cd shoresh && .venv/bin/python3 -m macula.release_part_links lxx      --out DIR [--allow-dirty]

pieces   bcv-commons/hebrew-nt-pieces-model: the aligner tables v0.3 of both Hebrew NTs (level-1 parts, level-2 pieces), the piece
         rule v0.2 and the fixed pairs v0.1; the files the lexeme-aligner's part-alignments pin, byte for byte (CC BY 4.0)
tree     bcv-commons/nt-tree-join: MACULA Greek NT trees joined to both Hebrew NTs through the aligner's part links (CC BY 4.0)
tree-sa  bcv-commons/nt-tree-join-sa: the same for the GLAUx NT dependency trees (CC BY-SA 4.0)
lxx      bcv-commons/tanakh-lxx-part-links: Hebrew part -> Septuagint (GLAUx) part through Brenton, with the GLAUx parts, the
         Brenton -> GLAUx join and the Brenton word ids (CC BY-SA 4.0)

Copies the local builds from internal-docs/ (paths below), checks the pinned shas, writes README.md (the card), build.json and
SHA256SUMS. The inputs are the aligner's pre-release of bcv-commons/part-alignments at revision ALIGNER_REV.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from macula import release_guard  # refuses TBTA and private inputs

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "internal-docs"
VERSION = "v0.1"
ALIGNER_REV = "9a3adbb96468469ce1f5c5955dd2924316732ca3"     # bcv-commons/part-alignments, heb v0.3 layers (2026-11-23)
PINNED = {"piece_rule.parquet": "0e50c44b", "fixed_pairs.tsv": "58e373f1"}   # as the aligner's manifest names them

FILES = {
    "pieces": {
        "tables/heb_scg/words.parquet": "aligner-tables/v0.3/heb_scg/words.parquet",
        "tables/heb_scg/_split.json": "aligner-tables/v0.3/heb_scg/_split.json",
        "tables/heb_mod/words.parquet": "aligner-tables/v0.3/heb_mod/words.parquet",
        "tables/heb_mod/_split.json": "aligner-tables/v0.3/heb_mod/_split.json",
        "piece_rule.parquet": "aligner-piece-rule/v0.2/piece_rule.parquet",
        "piece_rule_report.json": "aligner-piece-rule/v0.2/report.json",
        "fixed_pairs.tsv": "aligner-fixed-pairs/v0.1/pairs.tsv",
    },
    "tree": {f"data/{n}.parquet": f"nt-tree-join/v0.2/by/{n}.parquet" for n in ("parts", "part_links", "nodes", "node_links")}
            | {"report.json": "nt-tree-join/v0.2/report.json"},
    "tree-sa": {f"data/{n}.parquet": f"nt-tree-join/v0.2/by-sa/{n}.parquet"
                for n in ("crosswalk", "glaux_words", "glaux_node_links")},
    "lxx": {
        "data/part_links.parquet": "brenton-part-links/jev-v4/part_links.parquet",
        "data/lxx_parts.tsv": "lxx-parts/v0.2c/parts.tsv",
        "data/lxx_words.tsv": "lxx-parts/v0.2c/words.tsv",
        "data/brenton_glaux_join.tsv": "brenton-glaux-join/v0.2/join.tsv",
        "data/brenton_words.tsv": "aligner-tables/v0.3/grc_bre/positions.tsv",
        "report.json": "brenton-part-links/jev-v4/report.json",
    },
}
REPO = {"pieces": "hebrew-nt-pieces-model", "tree": "nt-tree-join", "tree-sa": "nt-tree-join-sa", "lxx": "tanakh-lxx-part-links"}
LICENCE = {"pieces": "cc-by-4.0", "tree": "cc-by-4.0", "tree-sa": "cc-by-sa-4.0", "lxx": "cc-by-sa-4.0"}

PRE = f"""**Pre-release ({VERSION}, 2026-11-23).** Built on the lexeme-aligner's pre-release of
[bcv-commons/part-alignments](https://huggingface.co/datasets/bcv-commons/part-alignments) at revision `{ALIGNER_REV[:8]}`.
When the aligner's full release comes, this dataset is rebuilt on it; column names may still change before v1.0."""

QUALITY = """## Link quality (read this before use)

The links are the lexeme-aligner's, graded by sample in the hub session by the model (Claude Opus); no person checked them.
- **Delitzsch (`heb_mod`) is below our bar of 90% right.** Five samples of 25 random links on 2026-11-23, one per layer
  update: 16, 19, 22, 23 and 20 right (100 of 125, 80%). The misses are mostly a pronoun suffix taken for the stem, a
  Greek word that two Hebrew words render linked to only one of them, and a few wrong words.
- **Salkinson (`heb_scg`)** was graded once on an earlier layer: 23 of 25. It is not graded on this layer.
- The piece choice inside a word pair (the piece rule) is by rule: 30 of 30 and 14 of 15 right in two samples."""


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def card(kind: str, n: dict) -> str:
    head = f"---\nlicense: {LICENCE[kind]}\n"
    if kind == "pieces":
        return head + f"""language: [he, grc]
pretty_name: Hebrew NT parts and pieces for word alignment (model)
tags: [bible, hebrew, greek, new-testament, morphology, alignment]
configs:
- config_name: heb_scg
  data_files: tables/heb_scg/words.parquet
- config_name: heb_mod
  data_files: tables/heb_mod/words.parquet
- config_name: piece_rule
  data_files: piece_rule.parquet
---

# Hebrew NT parts and pieces ({VERSION})

{PRE}

The units the lexeme-aligner links in its Hebrew layers: every word of two Hebrew translations of the New Testament,
Salkinson-Ginsburg (`heb_scg`, pointed) and Delitzsch (`heb_mod`, unpointed), cut into level-1 parts (prefixes, the word,
suffixes) and level-2 pieces (stem, person/number/state endings, prefixed person letters). These are the files the aligner's
manifest pins, byte for byte: tables v0.3, `piece_rule.parquet` (sha `{PINNED['piece_rule.parquet']}`) and `fixed_pairs.tsv`
(sha `{PINNED['fixed_pairs.tsv']}`).

**Model data.** Part of the cut was made with model help, and those rows say so:
- `level1_source` = `model`: {n['l1_model_scg']:,} Salkinson / {n['l1_model_mod']:,} Delitzsch rows, from the clause
  tagger of [hebrew-nt-analysis](https://huggingface.co/datasets/bcv-commons/hebrew-nt-analysis), a model trained on MACULA Hebrew.
- `level2_basis` starting with `jev`: {n['l2_jev_scg']:,} / {n['l2_jev_mod']:,} rows, where the Jev model gave the analysis
  that the cut follows.
- The fixed pairs and the sample grades are the hub model's (Claude Opus) work.
No person checked the model rows. Rows with `level2_basis` `tanakh` follow MACULA's own cut of the same word in the Tanakh.

## Files

| file | content |
|---|---|
| `tables/<ed>/words.parquet` | one row per level-2 piece: `book chapter verse i token word part slot text class lemma lexeme strong basis p_split`, `part_id` (level 1: `scg:`/`del:` + word id + part digit), `part2_id` (+ piece digit), `level1_part level1_source level2_kind level2_features level2_basis`, `fault_fix fault_fixed` (our text faults) |
| `tables/<ed>/_split.json` | format header (bcv-split/0.1, tokenizer 3) |
| `piece_rule.parquet` | `edition greek_part_id` ([word-parts](https://huggingface.co/datasets/bcv-commons/word-parts) v1.1) `hebrew_part_id hebrew_piece_id basis table_version`: which piece(s) of a Hebrew part a single Greek part takes ({n['rule_rows']:,} rows) |
| `piece_rule_report.json` | counts per basis |
| `fixed_pairs.tsv` | 15 Greek words rendered by two Hebrew words (`greek_lemma greek_strong hebrew_pair hebrew_strongs tanakh_pairs lxx_with_greek_lemma support`) |

Piece rule bases: `rule:piece_stem` (a Greek stem takes the Hebrew stem), `rule:piece_person` (a Greek person ending takes the
Hebrew piece(s) of the same person), `rule:piece_number` (a plural/dual case ending takes a plural/dual Hebrew ending, else the
stem), `rule:piece_none` (an augment or reduplication takes no piece). `level2_features`: V + stem + form + person + gender +
number (`Vqi3ms`); nouns N/A + type + gender + number + state (`Ncmpa`).

{QUALITY}

Known faults: Delitzsch's level-1 cut splits אתם as את+ם in 202 of 485 places (some are the pronoun "you"); fixed at the next
hebrew-nt-analysis export.

## Licence

CC BY 4.0. Texts: Salkinson-Ginsburg (1886) and Delitzsch, public domain, from the bcv-commons/bibles catalog. Analysis:
MACULA Hebrew and Greek (CC BY 4.0, Clear Bible / Biblica), hebrew-nt-analysis (CC BY 4.0), word-parts v1.1 (CC BY 4.0).
Credit: MACULA, the lexeme-aligner (links behind the piece rule), the Jev model and Claude Opus (model work as marked).
"""
    if kind == "tree":
        return head + f"""language: [he, grc]
pretty_name: Greek NT trees joined to two Hebrew New Testaments
tags: [bible, hebrew, greek, new-testament, syntax, treebank, alignment]
configs:
- config_name: parts
  data_files: data/parts.parquet
- config_name: part_links
  data_files: data/part_links.parquet
- config_name: nodes
  data_files: data/nodes.parquet
- config_name: node_links
  data_files: data/node_links.parquet
---

# Greek NT trees joined to two Hebrew NTs ({VERSION})

{PRE}

Every node of the MACULA Greek NT syntax trees (Nestle 1904) with the Hebrew words it maps to in Salkinson-Ginsburg (`heb_scg`)
and Delitzsch (`heb_mod`), through the lexeme-aligner's part links; and every Hebrew clause segment with the Greek it maps to.
Deterministic, no model of its own. The GLAUx trees are in [nt-tree-join-sa](https://huggingface.co/datasets/bcv-commons/nt-tree-join-sa).

| file | rows | content |
|---|---|---|
| `parts` | {n['parts']:,} | the units: `unit` (grc / heb_scg / heb_mod), `id` (Greek: word-parts v1.1 part id; Hebrew: level-2 piece id of [hebrew-nt-pieces-model](https://huggingface.co/datasets/bcv-commons/hebrew-nt-pieces-model)), `word_id book chapter verse position text kind` |
| `part_links` | {n['part_links']:,} | `edition greek_part_id hebrew_piece_id hebrew_ref prior method score`, as in the aligner's layers |
| `nodes` | {n['nodes']:,} | MACULA Greek nodes: `tree node_id parent kind cls role rule first_word last_word book chapter verse` |
| `node_links` | {n['node_links']:,} | `direction` grc_to_heb: per Greek node, `words parts linked_words hebrew_tokens hebrew_span inside_share` (share of the Hebrew span linked from inside the node) `other_node` (the Hebrew clause segment it equals, if one) `hebrew_segments`; heb_to_grc: per Hebrew clause segment, `coverage` |

`hebrew_ref` is the Hebrew verse a link falls in; it differs from the Greek verse where an edition joins verses (Delitzsch
2CO 13:12-13). Figures: a Greek node maps to one contiguous Hebrew stretch for 63% (Salkinson) / 70% (Delitzsch) of nodes;
a Greek clause equals one Hebrew clause segment for 36% / 37%.

{QUALITY}

Known limits: 21 Greek parts are not in the aligner's spine; 1 link falls on a dropped text-fault word (ROM 7:25); the Hebrew
clause segments' parents are offsets and stay empty where not exact.

## Licence

CC BY 4.0. MACULA Greek (CC BY 4.0, Clear Bible / Biblica); the lexeme-aligner's part-alignments (CC BY 4.0);
hebrew-nt-analysis clause segments (CC BY 4.0); texts public domain.
"""
    if kind == "tree-sa":
        return head + f"""language: [he, grc]
pretty_name: GLAUx Greek NT trees joined to two Hebrew New Testaments
tags: [bible, hebrew, greek, new-testament, dependency, treebank, alignment]
configs:
- config_name: crosswalk
  data_files: data/crosswalk.parquet
- config_name: glaux_words
  data_files: data/glaux_words.parquet
- config_name: glaux_node_links
  data_files: data/glaux_node_links.parquet
---

# GLAUx NT trees joined to two Hebrew NTs ({VERSION})

{PRE}

The [GLAUx](https://github.com/alekkeersmaekers/glaux) dependency trees of the Greek NT (commit `b077d8f6`), word by word
against MACULA, and every GLAUx subtree with the Hebrew words it maps to in Salkinson-Ginsburg and Delitzsch, through the
lexeme-aligner's part links (see [nt-tree-join](https://huggingface.co/datasets/bcv-commons/nt-tree-join)).

| file | rows | content |
|---|---|---|
| `crosswalk` | {n['crosswalk']:,} | `glaux_id macula_id kind` |
| `glaux_words` | {n['glaux_words']:,} | `glaux_id document sentence form lemma postag head relation artificial macula_id` (GLAUx's `sense` is left out) |
| `glaux_node_links` | {n['glaux_node_links']:,} | per edition and GLAUx word as subtree head: `relation subtree_words hebrew_tokens hebrew_span inside_share hebrew_segment hebrew_segments macula_node` |

Known limits: 91 GLAUx words are in or above head cycles in the source (each counted once). Artificial nodes have no MACULA word.

{QUALITY}

## Licence

CC BY-SA 4.0 (GLAUx, KU Leuven). Also MACULA Greek (CC BY 4.0) and the lexeme-aligner's part-alignments (CC BY 4.0).
"""
    return head + f"""language: [hbo, grc]
pretty_name: Hebrew Bible parts linked to Septuagint parts
tags: [bible, hebrew, greek, septuagint, alignment, morphology]
configs:
- config_name: part_links
  data_files: data/part_links.parquet
- config_name: lxx_parts
  data_files: data/lxx_parts.tsv
---

# Tanakh parts linked to Septuagint parts ({VERSION})

{PRE}

Every Hebrew part of the Tanakh (MACULA Hebrew, [word-parts](https://huggingface.co/datasets/bcv-commons/word-parts) v1.1) with the
Septuagint parts it is rendered by, in the GLAUx Septuagint cut into parts (stem, ending, preverb, augment, ...). The link goes
through Brenton's Septuagint, which the lexeme-aligner aligned to the Hebrew (its `grc_bre` Jev layer), and our word join of
Brenton to GLAUx. 37 books: no Esther or Daniel (Brenton's Daniel is Theodotion).

| file | rows | content |
|---|---|---|
| `part_links` | {n['links']:,} | `hebrew_part_id` (`wlc:` + word-parts Hebrew part id) `bre_word_id lxx_word_id lxx_part_id lxx_part_kind basis join_link methods` |
| `lxx_parts` | {n['lxx_parts']:,} | GLAUx Septuagint parts: `part_id word_id n start end text kind features` (ids without the `lxx:` prefix) |
| `lxx_words` | {n['lxx_words']:,} | GLAUx words: `word_id text book chapter verse idx lead surface trail lemma morph basis cut flags` (Daniel by Theodotion included) |
| `brenton_glaux_join` | {n['join']:,} | `bre_word_id lxx_word_id link lxx_verse verse_basis` |
| `brenton_words` | {n['bre']:,} | Brenton word ids: `book chapter verse position token bre_word_id source_book source_chapter source_verse` |

`basis`: `rule:one_hebrew_part` (the Brenton word is linked from one Hebrew part: its GLAUx parts all take it),
`rule:one_greek_part` (the GLAUx word has one part), `open` (several of both, no rule decides: {n['open']:,} Brenton words, 0.6%),
`no_glaux` (the Brenton word has no GLAUx word). `join_link`: `same`, `variant`, `differs`, `none`.

Checked against MACULA's own Septuagint word for each Hebrew part: the linked Brenton words include it for 93.8% of the parts
(317,410 of 338,504), at 1.03 Brenton words per part. The GLAUx cut: a sample of 100 rule-cut words read by the hub model
(Claude Opus) gave 97 right and 3 partly right; no person checked it. The Brenton -> GLAUx join is `same` for 98.2% of words.

## Licence

CC BY-SA 4.0 (GLAUx, KU Leuven). Also MACULA Hebrew (CC BY 4.0), word-parts v1.1 (CC BY 4.0), the lexeme-aligner's
part-alignments (CC BY 4.0), Brenton's Septuagint (public domain) via the bcv-commons/bibles catalog.
"""


def counts(kind: str, out: Path) -> dict:
    import pyarrow.parquet as pq
    n = {}
    if kind == "pieces":
        for ed, k in (("heb_scg", "scg"), ("heb_mod", "mod")):
            t = pq.read_table(out / f"tables/{ed}/words.parquet", columns=["level1_source", "level2_basis"])
            n[f"l1_model_{k}"] = sum(1 for v in t.column("level1_source").to_pylist() if v == "model")
            n[f"l2_jev_{k}"] = sum(1 for v in t.column("level2_basis").to_pylist() if (v or "").startswith("jev"))
        n["rule_rows"] = pq.read_metadata(out / "piece_rule.parquet").num_rows
    elif kind in ("tree", "tree-sa"):
        for f in (out / "data").glob("*.parquet"):
            n[f.stem] = pq.read_metadata(f).num_rows
    else:
        t = pq.read_table(out / "data/part_links.parquet", columns=["bre_word_id", "basis"]).to_pylist()
        n["links"] = len(t)
        n["open"] = len({r["bre_word_id"] for r in t if r["basis"] == "open"})
        for k, f in (("lxx_parts", "lxx_parts"), ("lxx_words", "lxx_words"), ("join", "brenton_glaux_join"), ("bre", "brenton_words")):
            with open(out / f"data/{f}.tsv", encoding="utf-8") as fh:
                n[k] = sum(1 for _ in fh) - 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=sorted(FILES))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "shoresh/macula"], cwd=ROOT, text=True).strip()
    if dirty and not a.allow_dirty:
        raise SystemExit(f"shoresh/macula has uncommitted changes; commit first (or --allow-dirty for a dry run):\n{dirty}")
    code = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=ROOT, text=True).strip() + ("+uncommitted" if dirty else "")
    if a.out.exists() and any(a.out.iterdir()):
        raise SystemExit(f"{a.out} is not empty; give a fresh folder")
    inputs = {}
    for dst, src in FILES[a.kind].items():
        s, t = D / src, a.out / dst
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(s, t)
        inputs[dst] = {"from": f"internal-docs/{src}", "sha256": sha256(t)}
        if dst in PINNED and not inputs[dst]["sha256"].startswith(PINNED[dst]):
            raise SystemExit(f"{dst}: sha {inputs[dst]['sha256'][:8]} is not the {PINNED[dst]} the aligner pins")
    n = counts(a.kind, a.out)
    (a.out / "README.md").write_text(card(a.kind, n), encoding="utf-8")
    build = {"dataset": f"bcv-commons/{REPO[a.kind]}", "version": VERSION, "schema": 1, "code": code,
             "licence": LICENCE[a.kind], "aligner": {"repo": "bcv-commons/part-alignments", "revision": ALIGNER_REV},
             "inputs": inputs, "counts": n}
    (a.out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(a.out)}\n" for p in files), encoding="utf-8")
    print(json.dumps({"dataset": build["dataset"], "code": code, "files": len(files), "counts": n}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
