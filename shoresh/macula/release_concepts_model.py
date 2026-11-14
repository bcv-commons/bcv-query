"""Package bcv-commons/hebrew-word-concepts-model: a concept per occurrence of contested Hebrew content words, finer than the UBS sense,
labelled by models (Claude Opus 5.5 defines each word's concepts; Jev (TypeSafe) labels the occurrences, Opus where Jev is unsure).
Made by make-tanakh-research to bcv-query's specification (packet 25 and the Genesis pass); model output, attributed apart from our
rule-built layers (the user's rule, 2026-11-14).

    cd shoresh && .venv/bin/python3 -m macula.release_concepts_model --src DIR --prefix PREFIX --out OUT [--meta META.json]

  --src     research's hand-over folder (internal-docs/handover/bcv-query-2026-11-12 in make-tanakh-research)
  --prefix  file prefix there: concept_cleared (pilot, cleared editions) or the Genesis pass's prefix
  --meta    a JSON with the run's facts (model ids, dates, costs, editions shown / held, scope); required for a real release

Writes OUT/data/tokens.parquet, OUT/data/concepts.parquet, OUT/definitions.tsv (the English table, apart from the data),
review.tsv (definitions that still quote a phrase: read before publishing), README.md, build.json, SHA256SUMS. Rows of the closed
chapters GEN 22 / 37 / 44 are dropped. Nothing is uploaded.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import re
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from macula import release_guard  # refuses TBTA and private inputs

VERSION = "v0.1"
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
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--meta", type=Path)
    a = ap.parse_args()
    release_guard.check(a)
    toks = [r for r in tsv(a.src / f"{a.prefix}_tokens.tsv") if not r["key"].startswith(CLOSED)]
    concepts = tsv(a.src / f"{a.prefix}_concepts.tsv")
    defs = {r["code"]: r["definition"] for r in tsv(a.src / f"{a.prefix}_concept_definitions.tsv")}
    codes = {r["code"] for r in concepts}
    bad = [r["key"] for r in toks if r["concept"] and r["concept"] not in codes]
    if bad:
        raise SystemExit(f"{len(bad)} tokens carry a concept not in concepts.tsv: {bad[:5]}")
    missing = sorted(codes - set(defs))
    if missing:
        raise SystemExit(f"concepts without a definition: {missing[:5]}")
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "data").mkdir()
    tcols = list(toks[0])
    floats = {c for c in tcols if "confidence" in c}
    pq.write_table(pa.table({c: (pa.array([float(r[c]) if r[c] else None for r in toks], type=pa.float32()) if c in floats else
                                 pa.array([r[c] for r in toks], type=pa.string())) for c in tcols}), a.out / "data/tokens.parquet")
    pq.write_table(pa.table({c: pa.array([r[c] for r in concepts], type=pa.string()) for c in concepts[0]}),
                   a.out / "data/concepts.parquet")
    review, n_clean = [], 0
    with open(a.out / "definitions.tsv", "w", encoding="utf-8") as f:
        f.write("# The data holds concept codes only; this table is the English: model-written definitions (Claude Opus 5.5).\n")
        f.write("code\tdefinition\n")
        for c in sorted(codes, key=lambda x: (int(re.sub(r"\D", "", x.split(".")[0]) or 0), x)):
            d = clean(defs[c])
            n_clean += d != defs[c]
            f.write(f"{c}\t{d}\n")
            if QUOTE.search(d):
                review.append((c, d))
    with open(a.out / "review.tsv", "w", encoding="utf-8") as f:
        f.write("code\tdefinition (still quotes a phrase: check it is a gloss, not a translation's wording)\n")
        f.writelines(f"{c}\t{d}\n" for c, d in review)
    meta_in = json.loads(a.meta.read_text(encoding="utf-8")) if a.meta else {"note": "dry run: no run facts given"}
    lab = {}
    for r in toks:
        k = r.get("labeller") or "opus"
        lab[k] = lab.get(k, 0) + 1
    n_lex = len({r["strong"] for r in concepts})
    (a.out / "README.md").write_text(card(len(toks), n_lex, len(codes), lab, meta_in), encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file() and p.name != "review.tsv")
    meta = {"schema": 1, "version": VERSION, "repo": REPO, "built": datetime.date.today().isoformat(), "licence": "CC BY-SA 4.0",
            "model_output": True, "human_checked": False, "run": meta_in, "tokens": len(toks), "lexemes": n_lex, "concepts": len(codes),
            "labellers": lab, "dropped_closed_chapters": list(CLOSED), "definitions_cleaned": n_clean, "definitions_to_review": len(review),
            "not_read": ["BHSA", "TBTA", "English text"], "files": {str(p.relative_to(a.out)): sha256(p) for p in files}}
    (a.out / "build.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file() and p.name != "review.tsv")
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(a.out)}\n" for p in files), encoding="utf-8")
    print(f"{a.out}: {len(toks):,} tokens, {n_lex} lexemes, {len(codes)} concepts; labellers {lab}; "
          f"definitions cleaned {n_clean}, still quoting {len(review)} (review.tsv, not published)")
    return 0


def _ci(d: dict, scale: float = 1.0, nd: int = 3) -> str:
    lo, hi = d["95%"]
    return f"{d['diff'] * scale:+.{nd}f} [{lo * scale:+.{nd}f}, {hi * scale:+.{nd}f}]"


def facts(m: dict) -> dict:
    """turn research's structured run record into card sentences; plain strings pass through (the pilot's dry runs)"""
    out = dict(m)
    if isinstance(m.get("opus_model"), str):
        out["opus_model"] = m["opus_model"].split(" ")[0]
    c = m.get("cost_usd")
    if isinstance(c, dict):
        out["cost"] = "USD " + f"{c['total']:.2f} (" + "; ".join(f"{k} {v:.2f}" for k, v in c.items() if k != "total") + ")"
    s = m.get("consistency")
    if isinstance(s, dict):
        out["consistency"] = (f"{s['Jev run 1 = run 2 (all tokens)']:.3f} for Jev's two runs over all occurrences and "
                              f"{s['Opus run 1 = run 2 (the 2,791 tokens below the band)']:.3f} for Opus's two runs on the "
                              f"2,791 occurrences below Jev's band; {s['concepts per lexeme']:.1f} concepts per word against "
                              f"{s['UBS senses per lexeme']:.1f} UBS senses")
    h = m.get("held_result")
    if isinstance(h, dict):
        out["held_count"] = str(len(m.get("editions_held", [])) or 39)
        out["held_result"] = (f"NMI {h['NMI']['concept']:.3f} against {h['NMI']['ubs']:.3f}, {_ci(h['NMI'])}; AMI {_ci(h['AMI'])}; "
                              f"purity {_ci(h['purity'])} (95% intervals, over {int(re.search(r'(\d+) pairs', h['what']).group(1)):,} word-edition pairs)")
    d = m.get("drafting")
    if isinstance(d, dict):
        g = d["governed (tokens where the concept cell differs)"]
        v = d["Genesis verses"]
        out["drafting"] = (f"an Indonesian word list keyed by (word, concept) against one keyed by (word, UBS sense), learned and "
                           f"scored on separate halves of Genesis: on the {g['tokens']:,} occurrences where the two differ, "
                           f"{g['sense']:.3f} -> {g['concept']:.3f}, {_ci(g, 100, 1)} points; over Genesis's {v['verses']:,} "
                           f"verses word F1 {v['word F1']['sense']:.2f} -> {v['word F1']['concept']:.2f}, chrF1 "
                           f"{v['chrF1']['sense']:.2f} -> {v['chrF1']['concept']:.2f} (point figures)")
    j = m.get("jev_parity")
    if isinstance(j, dict):
        out["jev_parity"] = (f"{j['Jev = Opus']:.3f} overall on the pilot's 1,421 occurrences, 0.995 or more at confidence 0.8 and "
                             f"above; on Genesis Opus was asked only below that band, where Jev agrees with it "
                             f"{m['consistency']['Jev run 1 = the Opus agreed label on those tokens']:.3f} (the hard cases)")
    if m.get("jev_model"):
        out["labelling"] = m["labelling"].rstrip(".") + f". Jev version: {m['jev_model'].split(' (')[0]}"
    out["editions_shown"] = [e.split("-", 2)[-1] for e in m.get("editions_shown", [])]
    return out


def card(n_tok: int, n_lex: int, n_con: int, lab: dict, m: dict) -> str:
    m = facts(m)
    eds = ", ".join(m.get("editions_shown", [])) or "(see build.json)"
    labs = ", ".join(f"{k} {v:,}" for k, v in sorted(lab.items()))
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

# Hebrew word concepts, model-labelled ({VERSION})

**This dataset is model output. No person has checked it.** For contested Hebrew content words (where translations split a word's
renderings, or one UBS sense covers renderings that differ), each word gets a set of concepts, finer than or equal to its UBS
senses, and each occurrence its concept: {n_tok:,} occurrences of {n_lex} words, {n_con:,} concepts. Scope: {m.get('scope', 'see build.json')}.

## How it was made

- **Concepts per word:** Claude Opus 5.5 ({m.get('opus_model', 'claude-opus-5-5')}, {m.get('date', '')}) read up to 80 occurrences of
  the word across the Tanakh: the Hebrew clause (MACULA lemma and morphology), the word's UBS senses and their definitions, the
  Septuagint lemma at each place, and how {len(m.get('editions_shown', [])) or 'the shown'} openly licensed translations group the
  occurrences (cluster ids and counts only, no translation text). It did not see MACULA's English gloss, any translation's wording or
  BHSA data. It proposed codes `H<strong>.<n>` with a one-line definition each.
- **Concept per occurrence:** {m.get('labelling', 'see build.json')}. Labellers: {labs}.
- Run by make-tanakh-research to bcv-query's specification. Cost (list): {m.get('cost', 'see build.json')}.

Translations whose grouping was shown (public domain or CC BY-SA 4.0, verified): {eds}.

## How good it is

- Two labellings of the same occurrences agree (model with itself, not human agreement): {m.get("consistency", "…")}.
- Independent check: on {m.get('held_count', '39')} translations not shown, the concept predicts how a translation groups a word's
  occurrences better than the UBS sense: {m.get('held_result', 'see build.json')}.
- Use in drafting: {m.get('drafting', 'see build.json')}.
- Jev against Opus on the pilot's occurrences: {m.get('jev_parity', '0.966 overall; 0.995 where Jev is confident (0.84 of occurrences)')}.

## Files

| file | content |
|---|---|
| `data/tokens.parquet` | `key` (MACULA Hebrew word id), `concept`, and each labelling run (labeller, confidence) |
| `data/concepts.parquet` | `code`, `strong`, `ubs_sense` (the UBS sense the concept refines) |
| `definitions.tsv` | the model's one-line English definition per concept, kept apart from the data; examples quoting a phrase were removed |

Occurrences in Genesis 22, 37 and 44 are left out (held back for evaluation elsewhere).

## Licence

CC BY-SA 4.0. Inputs: MACULA Hebrew (CC BY 4.0), the UBS dictionaries' senses (CC BY-SA 4.0), GLAUx Septuagint (CC BY-SA 4.0), and
groupings derived from the translations listed above (public domain, CC BY-SA 4.0). Credit: Claude Opus 5.5 (Anthropic) and Jev
(TypeSafe) as labellers, make-tanakh-research (the runs and measurements), MACULA (Clear Bible / Biblica), United Bible Societies,
GLAUx (KU Leuven), the translation teams of the editions above, and this dataset.
"""


if __name__ == "__main__":
    raise SystemExit(main())
