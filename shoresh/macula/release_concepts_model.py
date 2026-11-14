"""Package bcv-commons/hebrew-word-concepts-model: a concept per occurrence of contested Hebrew content words, finer than the UBS sense,
labelled by models (Claude Opus 5.5 defines each word's concepts; Jev (TypeSafe) labels the occurrences, Opus where Jev is unsure).
Made by make-tanakh-research to bcv-query's specification (packet 25 and the Genesis pass); model output, attributed apart from our
rule-built layers (the user's rule, 2026-11-14).

    cd shoresh && .venv/bin/python3 -m macula.release_concepts_model --src DIR --stage PREFIX[:META.json] [--stage ...] --out OUT
                                                                    [--version v0.2]

  --src     research's hand-over folder (internal-docs/handover/bcv-query-2026-11-12 in make-tanakh-research)
  --stage   one labelling stage: its file prefix there (genesis, torah, ...) and its run record (genesis_run.json, ...); repeat
            for every stage, in order. Concept codes a later stage reuses must be identical (strong, UBS sense, definition).

Writes OUT/data/tokens.parquet, OUT/data/concepts.parquet, OUT/definitions.tsv (the English table, apart from the data),
review.tsv (definitions that still quote a phrase: read before publishing), README.md, build.json, SHA256SUMS. Rows of the closed
chapters GEN 22 / 37 / 44 are dropped. Nothing is uploaded.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import hashlib
import json
import re
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from macula import release_guard  # refuses TBTA and private inputs

REPO = "bcv-commons/hebrew-word-concepts-model"
CLOSED = ("01022", "01037", "01044")
QUOTE = re.compile(r"'[^']{3,}'|\"[^\"]{3,}\"|‘[^’]{3,}’|“[^”]{3,}”")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def clean(defn: str) -> str:
    """drop parenthetical examples that quote a phrase (they may echo an English translation's wording); keep verse references"""
    out = re.sub(r"\s*\((?:e\.g\.|eg|for example|as in|cf\.)[^()]*\)", "", defn)
    out = re.sub(r"\s*\([^()]*(?:'[^']{3,}'|\"[^\"]{3,}\")[^()]*\)", "", out)
    return re.sub(r"\s{2,}", " ", out).strip(" ;,")


def tsv(p: Path) -> list[dict]:
    return list(csv.DictReader(open(p, encoding="utf-8"), delimiter="\t"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--stage", action="append", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--version", default="v0.1")
    a = ap.parse_args()
    release_guard.check(a)
    toks, concepts, defs, stages = [], {}, {}, []
    for st in a.stage:
        prefix, _, meta_name = st.partition(":")
        meta_path = a.src / (meta_name or f"{prefix}_run.json")
        m = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"note": "dry run: no run facts given"}
        rows = [dict(r, stage=prefix) for r in tsv(a.src / f"{prefix}_tokens.tsv") if not r["key"].startswith(CLOSED)]
        for r in tsv(a.src / f"{prefix}_concepts.tsv"):
            if r["code"] in concepts and concepts[r["code"]] != r:
                raise SystemExit(f"{prefix}: concept {r['code']} differs from an earlier stage")
            concepts[r["code"]] = r
        for r in tsv(a.src / f"{prefix}_concept_definitions.tsv"):
            if r["code"] in defs and defs[r["code"]] != r["definition"]:
                raise SystemExit(f"{prefix}: definition of {r['code']} differs from an earlier stage")
            defs[r["code"]] = r["definition"]
        seen = {r["key"] for r in toks}
        dup = [r["key"] for r in rows if r["key"] in seen]
        if dup:
            raise SystemExit(f"{prefix}: {len(dup)} tokens already in an earlier stage: {dup[:5]}")
        lab = collections.Counter(r.get("labeller") or "opus" for r in rows)
        stages.append((prefix, m, len(rows), lab))
        toks += rows
    codes = set(concepts)
    bad = [r["key"] for r in toks if r["concept"] and r["concept"] not in codes]
    if bad:
        raise SystemExit(f"{len(bad)} tokens carry a concept not in the concepts files: {bad[:5]}")
    missing = sorted(codes - set(defs))
    if missing:
        raise SystemExit(f"concepts without a definition: {missing[:5]}")
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "data").mkdir()
    tcols = ["stage"] + [c for c in toks[0] if c != "stage"]
    for r in toks:
        for c in tcols:
            r.setdefault(c, "")
    floats = {c for c in tcols if "confidence" in c}
    pq.write_table(pa.table({c: (pa.array([float(r[c]) if r[c] else None for r in toks], type=pa.float32()) if c in floats else
                                 pa.array([r[c] for r in toks], type=pa.string())) for c in tcols}), a.out / "data/tokens.parquet")
    crow = [concepts[c] for c in sorted(codes, key=lambda x: (int(re.sub(r"\D", "", x.split(".")[0]) or 0), x))]
    pq.write_table(pa.table({c: pa.array([r[c] for r in crow], type=pa.string()) for c in crow[0]}), a.out / "data/concepts.parquet")
    review, n_clean = [], 0
    with open(a.out / "definitions.tsv", "w", encoding="utf-8") as f:
        f.write("# The data holds concept codes only; this table is the English: model-written definitions (Claude Opus 5.5).\n")
        f.write("code\tdefinition\n")
        for r in crow:
            c = r["code"]
            d = clean(defs[c])
            n_clean += d != defs[c]
            f.write(f"{c}\t{d}\n")
            if QUOTE.search(d):
                review.append((c, d))
    with open(a.out / "review.tsv", "w", encoding="utf-8") as f:
        f.write("code\tdefinition (still quotes a phrase: check it is a gloss, not a translation's wording)\n")
        f.writelines(f"{c}\t{d}\n" for c, d in review)
    lab = collections.Counter(r.get("labeller") or "opus" for r in toks)
    n_lex = len({r["strong"] for r in crow})
    (a.out / "README.md").write_text(card(a.version, len(toks), n_lex, len(codes), lab, stages), encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file() and p.name != "review.tsv")
    meta = {"schema": 1, "version": a.version, "repo": REPO, "built": datetime.date.today().isoformat(), "licence": "CC BY-SA 4.0",
            "model_output": True, "human_checked": False, "stages": {p: m for p, m, _, _ in stages}, "tokens": len(toks),
            "lexemes": n_lex, "concepts": len(codes), "labellers": dict(lab), "dropped_closed_chapters": list(CLOSED),
            "definitions_cleaned": n_clean, "definitions_to_review": len(review), "not_read": ["BHSA", "TBTA", "English text"],
            "files": {str(p.relative_to(a.out)): sha256(p) for p in files}}
    (a.out / "build.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file() and p.name != "review.tsv")
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(a.out)}\n" for p in files), encoding="utf-8")
    print(f"{a.out}: {len(toks):,} tokens, {n_lex} lexemes, {len(codes):,} concepts; stages "
          f"{[(p, n) for p, _, n, _ in stages]}; labellers {dict(lab)}; definitions cleaned {n_clean}, still quoting {len(review)} "
          f"(review.tsv, not published)")
    return 0


def _ci(d: dict, scale: float = 1.0, nd: int = 3) -> str:
    lo, hi = d["95%"]
    return f"{d['diff'] * scale:+.{nd}f} [{lo * scale:+.{nd}f}, {hi * scale:+.{nd}f}]"


def _pick(d: dict, *words: str):
    """the value under the first key containing every word (research's record keys are descriptive and vary a little)"""
    for k, v in d.items():
        if all(w in k for w in words):
            return k, v
    return None, None


def stage_text(prefix: str, m: dict, n: int, lab: dict) -> str:
    out = [f"### {m.get('stage', prefix).capitalize() if isinstance(m.get('stage'), str) else prefix.capitalize()}: "
           f"{', '.join(m.get('books', [])) or prefix} ({n:,} occurrences)", ""]
    if m.get("scope"):
        out.append(f"- Scope: {m['scope']}.")
    if m.get("labelling"):
        jv = f" Jev version: {m['jev_model'].split(' (')[0]}." if m.get("jev_model") else ""
        out.append(f"- Labelling: {m['labelling'].rstrip('.')}.{jv} Labellers: " + ", ".join(f"{k} {v:,}" for k, v in sorted(lab.items())) + ".")
    s = m.get("consistency")
    if isinstance(s, dict):
        parts = [f"{k}: {v:.3f}" for k, v in s.items() if "=" in k and isinstance(v, float)]
        _, cpl = _pick(s, "concepts per")
        _, upl = _pick(s, "UBS senses per")
        out.append("- Two labellings of the same occurrences (model with itself, not human agreement): " + "; ".join(parts) +
                   (f". {cpl:.1f} concepts per word against {upl:.1f} UBS senses." if cpl and upl else "."))
    h = m.get("held_result")
    if isinstance(h, dict):
        pairs = re.search(r"(\d+) pairs", h.get("what", ""))
        out.append(f"- Independent check on {len(m.get('editions_held', []))} translations never shown: the concept predicts how a "
                   f"translation groups a word's occurrences better than the UBS sense. NMI {h['NMI']['concept']:.3f} against "
                   f"{h['NMI']['ubs']:.3f}, {_ci(h['NMI'])}; AMI {_ci(h['AMI'])}; purity {_ci(h['purity'])}"
                   + (f" (95% intervals, {int(pairs.group(1)):,} word-translation pairs)." if pairs else "."))
    d = m.get("drafting")
    if isinstance(d, dict):
        _, g = _pick(d, "governed")
        _, v = _pick(d, "verses")
        txt = "- Use in drafting (Indonesian word list keyed by (word, concept) against (word, UBS sense), learned and scored on separate halves)"
        if g:
            txt += f": on the {g['tokens']:,} occurrences where the two differ, {g['sense']:.3f} -> {g['concept']:.3f}, {_ci(g, 100, 1)} points"
        if v:
            txt += (f"; over {v['verses']:,} verses word F1 {v['word F1']['sense']:.2f} -> {v['word F1']['concept']:.2f}, chrF1 "
                    f"{v['chrF1']['sense']:.2f} -> {v['chrF1']['concept']:.2f} (point figures)")
        out.append(txt + ".")
    c = m.get("cost_usd")
    if isinstance(c, dict):
        out.append("- Cost (list price): USD " + f"{c['total']:.2f} (" + "; ".join(f"{k} {v:.2f}" for k, v in c.items() if k != "total") + ").")
    return "\n".join(out)


def card(version: str, n_tok: int, n_lex: int, n_con: int, lab: dict, stages: list) -> str:
    first = stages[0][1]
    opus = (first.get("opus_model") or "claude-opus-5-5").split(" ")[0]
    eds = sorted({e.split("-", 2)[-1] for _, m, _, _ in stages for e in m.get("editions_shown", [])})
    held = sorted({e for _, m, _, _ in stages for e in m.get("editions_held", [])})
    labs = ", ".join(f"{k} {v:,}" for k, v in sorted(lab.items()))
    sections = "\n\n".join(stage_text(p, m, n, l) for p, m, n, l in stages)
    return f"""---
license: cc-by-sa-4.0
language: [hbo]
pretty_name: Hebrew word concepts (model-labelled)
tags: [bible, hebrew, lexical-semantics, word-sense, concepts, model-generated, translation]
configs:
- config_name: tokens
  data_files: data/tokens.parquet
- config_name: concepts
  data_files: data/concepts.parquet
---

# Hebrew word concepts, model-labelled ({version})

**This dataset is model output. No person has checked it.** For contested Hebrew content words (where translations split a word's
renderings, or one UBS sense covers renderings that differ), each word gets a set of concepts, finer than or equal to its UBS
senses, and each occurrence its concept: {n_tok:,} occurrences of {n_lex:,} words, {n_con:,} concepts, labelled in {len(stages)}
stage{'s' if len(stages) > 1 else ''} ({', '.join(p for p, _, _, _ in stages)}). Labellers over all: {labs}.

## How it was made

- **Concepts per word:** Claude Opus 5.5 ({opus}) read up to 80 occurrences of the word across the Tanakh: the Hebrew clause (MACULA
  lemma and morphology), the word's UBS senses and their definitions, the Septuagint lemma at each place, and how {len(eds)} openly
  licensed translations group the occurrences (cluster ids and counts only, no translation text). It did not see MACULA's English
  gloss, any translation's wording or BHSA data. It proposed codes `H<strong>.<n>` with a one-line definition each. A word defined in
  an earlier stage keeps its concepts and codes.
- **Concept per occurrence:** Jev (TypeSafe) and Claude Opus 5.5 chose among the word's concepts; each stage's rule and its labeller
  per row are below and in `tokens` (`labeller`, each run's label, Jev's confidence).
- Run by make-tanakh-research to bcv-query's specification.

Translations whose grouping was shown (public domain or CC BY-SA 4.0, verified): {', '.join(eds) or '(see build.json)'}.
{len(held)} other translations were held back for the independent check.

## How good it is, per stage

{sections}

## Files

| file | content |
|---|---|
| `data/tokens.parquet` | `stage`, `key` (MACULA Hebrew word id), `concept`, `labeller`, and each labelling run (labels, Jev's confidence) |
| `data/concepts.parquet` | `code`, `strong`, `ubs_sense` (the UBS sense the concept refines) |
| `definitions.tsv` | the model's one-line English definition per concept, kept apart from the data; examples quoting a phrase were removed |

Occurrences in Genesis 22, 37 and 44, Esther, Daniel and Jonah are left out (held back for evaluation elsewhere).

## Licence

CC BY-SA 4.0. Inputs: MACULA Hebrew (CC BY 4.0), the UBS dictionaries' senses (CC BY-SA 4.0), GLAUx Septuagint (CC BY-SA 4.0), and
groupings derived from the translations listed above (public domain, CC BY-SA 4.0). Credit: Claude Opus 5.5 (Anthropic) and Jev
(TypeSafe) as labellers, make-tanakh-research (the runs and measurements), MACULA (Clear Bible / Biblica), United Bible Societies,
GLAUx (KU Leuven), the translation teams of the editions above, and this dataset.
"""


if __name__ == "__main__":
    raise SystemExit(main())
