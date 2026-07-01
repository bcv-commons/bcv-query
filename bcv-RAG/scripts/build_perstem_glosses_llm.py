#!/usr/bin/env python3
"""Generate per-STEM Hebrew verb glosses for a target language (Hebrew-anchored, LLM).

Brings a Strong's-bridged language (single gloss per lexeme) up to the per-stem
granularity of the BibleOL languages — anchored on the Hebrew binyan, NOT on English.
For each Hebrew verb that occurs in ≥2 stems with distinct senses, each (lemma, stem) is
glossed into the target with the LLM given: the Hebrew lemma + transliteration, the
stem's grammatical function, AND existing glosses in chosen reference languages (--refs,
most-related first) — the references are aids, the Hebrew is the anchor.

  python scripts/build_perstem_glosses_llm.py <Language>                       # DRY RUN (no API)
  python scripts/build_perstem_glosses_llm.py <Language> --run                 # call the LLM ($)
  python scripts/build_perstem_glosses_llm.py Norwegian --refs Danish,Swedish  # closely-related refs, no English

`--refs` is an ordered, comma-separated list of ALREADY-GENERATED gloss languages to show
the model as references (most-related first). When the target has close cousins, prefer
them over English: e.g. a Scandinavian target with `--refs Danish,Swedish` reasons from
vetted Danish/Swedish glosses, not English. Default: English,German,Danish,Swahili.
Any language in the list whose glosses don't exist yet is skipped with a warning.

DRY RUN is the default and makes NO API calls. --run requires ANTHROPIC_API_KEY and
incurs token cost. Output (run): merges per-stem cells into resources/word_glosses/hbo/
<Language>.csv (existing `default` preserved). Seed: example/BibleOL/lexicons/heb_en.csv.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
# per-stem ENGLISH template (BibleOL, MIT). Prefer the committed resources/ copy so this
# needs no gitignored example/; fall back to a local example/ checkout, then (in _seed_rows)
# to the committed word_glosses/hbo/English.csv (same per-stem data, minus transliteration).
_SEED_RES = ROOT / "resources/lexicons/heb_en.csv"
_SEED_EX = ROOT / "example/BibleOL/lexicons/heb_en.csv"
SEED = _SEED_RES if _SEED_RES.exists() else _SEED_EX
WG = ROOT / "resources/word_glosses/hbo"
DEFAULT_REFS = ["English", "German", "Danish", "Swahili"]    # ordered; most-related first
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
BATCH = 40
_PLACEHOLDER = re.compile(r"^[A-ZÆØÅ]{2,}$")

# heb_en column index → (BHSA stem code, grammatical function for the prompt)
STEMS = {5: ("qal", "basic active"), 6: ("nif", "passive/reflexive"),
         7: ("piel", "intensive/factitive"), 8: ("pual", "passive of piel"),
         9: ("hit", "reflexive/iterative"), 10: ("hif", "causative"),
         11: ("hof", "passive of causative"), 12: ("hsht", "Shaphel/causative"),
         13: ("pasq", "passive qal"), 14: ("etpa", "Etpaal"), 15: ("nit", "Nitpael"),
         16: ("hotp", "Hotpaal"), 17: ("tif", "Tifal"), 18: ("htpa", "Hitpoel"),
         19: ("poal", "Poal"), 20: ("poel", "Poel")}


def _load_dotenv() -> None:
    """Load bcv-RAG/.env into os.environ (keys not already set) — where ANTHROPIC_API_KEY
    lives. No dependency."""
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = re.split(r"\s+#", v, 1)[0]        # drop inline comments ("val   # note")
            k = k.strip()
            if not os.environ.get(k):             # set if missing OR empty (a pre-set "" key)
                os.environ[k] = v.strip().strip('"').strip("'")


def _real(v):
    v = (v or "").strip()
    return "" if (not v or v == "-" or _PLACEHOLDER.match(v)) else v


def _seed_rows():
    """Yield (lex, translit, {stem: english_gloss}) — the per-stem STRUCTURE + English
    reference. Prefers the BibleOL `heb_en.csv` seed (has transliteration); falls back to
    the committed `word_glosses/hbo/English.csv` (same per-stem data, no translit column)
    so per-stem generation needs no gitignored example/ file."""
    if SEED.exists():
        with SEED.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.reader(fh):
                if len(row) < 6 or row[1] == "lex" or not row[1].strip():
                    continue
                translit = row[3].strip() if len(row) > 3 else ""
                cells = {STEMS[i][0]: _real(row[i]) for i in STEMS if i < len(row) and _real(row[i])}
                yield row[1].strip(), translit, cells
        return
    p = WG / "English.csv"
    if not p.exists():
        return
    with p.open(encoding="utf-8-sig", newline="") as fh:
        r = csv.reader(fh)
        idx = {c.strip(): i for i, c in enumerate(next(r))}
        stemcols = [(idx[c], c) for _, (c, _f) in STEMS.items() if c in idx]
        li = idx.get("lex", 0)
        for row in r:
            if li >= len(row) or not row[li].strip():
                continue
            cells = {c: _real(row[i]) for i, c in stemcols if i < len(row) and _real(row[i])}
            yield row[li].strip(), "", cells


def _english_table():
    """English per-stem senses, keyed by lex."""
    return {lex: cells for lex, _t, cells in _seed_rows()}


def _lang_table(language):
    """{lex: {stem: gloss}} for any reference language (English from the seed; others
    from their per-stem CSV). Empty if the language has no glosses yet."""
    if language == "English":
        return _english_table()
    p = WG / f"{language}.csv"
    out = {}
    if not p.exists():
        return out
    with p.open(encoding="utf-8-sig", newline="") as fh:
        r = csv.reader(fh)
        cols = [c.strip() for c in next(r)]
        li = cols.index("lex")
        for row in r:
            if li < len(row) and row[li].strip():
                out[row[li].strip()] = {cols[i]: row[i].strip()
                                        for i in range(len(cols)) if i < len(row) and cols[i]}
    return out


def _worklist(ref_langs):
    """Entries for the multi-stem verbs only (single-stem/non-verbs already have default).
    Structure (which lexeme×stem cells) comes from the seed; `refs` are the chosen
    reference languages' glosses, in priority order (most-related first)."""
    tables = {L: _lang_table(L) for L in ref_langs}
    entries = []
    for lex, translit, cells in _seed_rows():
        if len({v for v in cells.values()}) < 2:        # not genuinely multi-stem → skip
            continue
        for stem in cells:
            fn = next(f for c, f in STEMS.values() if c == stem)
            # ordered refs (dict preserves ref_langs order = priority)
            refs = {L: tables[L].get(lex, {}).get(stem) for L in ref_langs}
            refs = {k: v for k, v in refs.items() if v}
            entries.append({"key": f"{lex}|{stem}", "lemma": lex, "translit": translit,
                            "stem": stem, "function": fn, "refs": refs})
    return entries


def _prompt(batch, lang_name, ref_langs):
    refs_note = (", ".join(ref_langs) + " (most-related first)") if ref_langs else "none"
    return (
        f"You are a biblical-Hebrew lexicographer. For each entry, give the single most "
        f"natural {lang_name} gloss for the Hebrew verb IN THE GIVEN STEM (binyan). "
        f"**Anchor on the Hebrew** (lemma + transliteration) and the stem's function. Each "
        f"entry's `refs` are existing glosses in related languages [{refs_note}] — use them "
        f"as aids to pin the sense, NOT as the source; the Hebrew is the source. Capture the "
        f"sense the STEM produces (e.g. qal 'be holy' vs hif 'declare holy'). "
        f"Return ONE LINE PER ENTRY, exactly: the key, a TAB, then the {lang_name} gloss "
        f"(a short phrase if needed). No JSON, no numbering, no commentary.\n"
        f"Entries:\n{json.dumps(batch, ensure_ascii=False)}"
    )


RL = ROOT / "resources/related_langs"          # code-keyed relatedness registry
RG = ROOT / "resources/regional_langs"          # script/regional variants (same-code siblings)


def _perstem_langs():
    """Gloss languages that actually carry per-stem cells (useful as references).
    English (the seed) always qualifies."""
    out = {"English"}
    for p in WG.glob("*.csv"):
        if _existing_cells(p.stem):
            out.add(p.stem)
    return out


def _load_registry():
    """Read the future-proof resources → (name↔code maps, ordered related codes,
    code→variant gloss-names). Returns None if the registry isn't built yet."""
    reg = RL / "languages.tsv"
    if not reg.exists():
        return None
    name_code, code_name, code_gloss = {}, {}, {}
    with reg.open(encoding="utf-8") as fh:
        cols = next(fh).rstrip("\n").split("\t")
        ci = {c: i for i, c in enumerate(cols)}
        for line in fh:
            r = line.rstrip("\n").split("\t")
            code, name = r[ci["iso639_3"]], r[ci["name"]]
            gnames = [g for g in r[ci["gloss_names"]].split(";") if g]
            code_name[code] = name
            name_code[name] = code
            code_gloss.setdefault(code, [])
            for g in gnames:
                name_code[g] = code
                code_gloss[code].append(g)
    related = {}
    rel = RL / "related.tsv"
    if rel.exists():
        with rel.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                code, rank, rcode, _basis = line.rstrip("\n").split("\t")
                related.setdefault(code, []).append((int(rank), rcode))
    code_variants = {}
    var = RG / "variants.tsv"
    if var.exists():
        with var.open(encoding="utf-8") as fh:
            cols = next(fh).rstrip("\n").split("\t")
            vi = {c: i for i, c in enumerate(cols)}
            for line in fh:
                r = line.rstrip("\n").split("\t")
                g = r[vi["gloss_name"]] if vi.get("gloss_name", -1) < len(r) else ""
                if g:
                    code_variants.setdefault(r[vi["iso639_3"]], []).append(g)
    return name_code, code_name, code_gloss, related, code_variants


def _auto_refs(target, perstem):
    """Ordered reference languages for `target`, resolved from the registries:
    same-code script/regional variants first (closest), then related languages by
    rank, then English. Filtered to languages that actually have per-stem glosses.
    Returns None if the registry isn't available (caller falls back to DEFAULT_REFS)."""
    reg = _load_registry()
    if not reg:
        return None
    name_code, code_name, code_gloss, related, code_variants = reg
    code = name_code.get(target)
    if not code:
        return None
    ordered = []
    # 1. variant siblings under the same code (e.g. Chinese-Simplified for Chinese-Traditional)
    for g in code_variants.get(code, []) + code_gloss.get(code, []):
        if g != target and g not in ordered:
            ordered.append(g)
    # 2. related languages, by rank → their gloss-name(s)
    for _rank, rcode in sorted(related.get(code, [])):
        for g in (code_gloss.get(rcode) or [code_name.get(rcode)]):
            if g and g != target and g not in ordered:
                ordered.append(g)
    refs = [g for g in ordered if g in perstem]      # only per-stem refs are useful
    if "English" not in refs:
        refs.append("English")
    return refs


def _existing_cells(language):
    """{'lex|stem'} cells already glossed in the output CSV (so re-runs skip them)."""
    p = WG / f"{language}.csv"
    done = set()
    if not p.exists():
        return done
    with p.open(encoding="utf-8-sig", newline="") as fh:
        r = csv.reader(fh)
        cols = [c.strip() for c in next(r)]
        li = cols.index("lex")
        scols = [(i, c) for i, c in enumerate(cols) if c not in ("", "lex", "default")]
        for row in r:
            if li < len(row) and row[li].strip():
                lex = row[li].strip()
                for i, c in scols:
                    if i < len(row) and row[i].strip():
                        done.add(f"{lex}|{c}")
    return done


def _parse_args(argv):
    run = "--run" in argv
    force = "--force" in argv
    refs = None                                  # None → auto-resolve from the registries
    rest, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("--run", "--force"):
            i += 1
        elif a == "--refs" and i + 1 < len(argv):
            refs = [x.strip() for x in argv[i + 1].split(",") if x.strip()]; i += 2
        elif a.startswith("--refs="):
            refs = [x.strip() for x in a.split("=", 1)[1].split(",") if x.strip()]; i += 1
        else:
            rest.append(a); i += 1
    return (rest[0] if rest else None), refs, run, force


def main():
    language, refs, run, force = _parse_args(sys.argv[1:])
    if not language:
        sys.exit("usage: build_perstem_glosses_llm.py <Language> [--refs L1,L2,…] [--run] [--force]")
    # refs: explicit --refs wins; otherwise auto-resolve from related_langs + regional_langs
    if refs is None:
        auto = _auto_refs(language, _perstem_langs())
        refs = auto if auto else list(DEFAULT_REFS)
        src = "auto (related_langs + regional_langs)" if auto else "fallback default"
        print(f"  refs [{src}]: {','.join(refs)}", file=sys.stderr)
    # keep only reference languages that actually have glosses
    ref_langs = [L for L in refs if L == "English" or (WG / f"{L}.csv").exists()]
    for L in refs:
        if L not in ref_langs:
            print(f"  (skipping reference '{L}' — no glosses generated yet)", file=sys.stderr)
    all_entries = _worklist(ref_langs)
    verbs = len({e["lemma"] for e in all_entries})
    # resume/gap-fill: skip cells already glossed in the output CSV (unless --force)
    done = set() if force else _existing_cells(language)
    entries = [e for e in all_entries if e["key"] not in done]
    if done:
        print(f"  resume: {len(done & {e['key'] for e in all_entries})} of {len(all_entries)} "
              f"cells already done → {len(entries)} remaining"
              f"{' (--force: redoing all)' if force else ''}", file=sys.stderr)
    if run and not entries:
        print(f"  nothing to do — all {len(all_entries)} cells already glossed "
              f"(use --force to regenerate). No API calls made.", file=sys.stderr)
        return
    batches = [entries[i:i + BATCH] for i in range(0, len(entries), BATCH)]
    # rough token estimate (chars/4): prompt boilerplate + entries in, ~8 tok/entry out
    in_tok = sum(len(_prompt(b, language, ref_langs)) for b in batches) // 4
    out_tok = len(entries) * 8

    if not run:
        outdir = ROOT / "out" / "perstem"
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / f"{language}_prompts.txt").write_text(
            "\n\n===\n\n".join(_prompt(b, language, ref_langs) for b in batches), encoding="utf-8")
        print(f"DRY RUN — {language}", file=sys.stderr)
        print(f"  multi-stem verbs: {verbs}", file=sys.stderr)
        print(f"  (lemma,stem) cells to gloss: {len(entries)}", file=sys.stderr)
        print(f"  API calls (batch {BATCH}): {len(batches)}", file=sys.stderr)
        print(f"  est. tokens: ~{in_tok:,} in + ~{out_tok:,} out", file=sys.stderr)
        print(f"  est. cost @ Haiku (~$0.80/M in, $4/M out): "
              f"~${in_tok/1e6*0.8 + out_tok/1e6*4:.2f}", file=sys.stderr)
        print(f"  prompts written: {(outdir / f'{language}_prompts.txt').relative_to(ROOT)}", file=sys.stderr)
        print(f"  sample entry: {entries[0] if entries else '(none)'}", file=sys.stderr)
        print("\n  → re-run with --run to call the LLM and write the per-stem CSV.", file=sys.stderr)
        return

    # --- live run (paid) ---
    _load_dotenv()
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001").strip()
    if not key:
        sys.exit("ERROR: set ANTHROPIC_API_KEY (--run incurs token cost)")
    import urllib.request
    glosses = {}
    for i, b in enumerate(batches):
        body = json.dumps({"model": model, "max_tokens": 4000,
                           "messages": [{"role": "user", "content": _prompt(b, language, ref_langs)}]}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                              "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            text = json.loads(resp.read())["content"][0]["text"]
        keys = {e["key"] for e in b}
        for line in text.splitlines():
            if "\t" in line:
                k, g = line.split("\t", 1)
                if k.strip() in keys and g.strip():
                    glosses[k.strip()] = g.strip()
        print(f"  batch {i+1}/{len(batches)}: {len(glosses)} cumulative", file=sys.stderr)

    # merge into the existing <Language>.csv (preserve default), add stem columns
    out_path = WG / f"{language}.csv"
    rows, cols = {}, ["lex", "default"]
    if out_path.exists():
        with out_path.open(encoding="utf-8-sig", newline="") as fh:
            r = csv.reader(fh); cols = [c for c in next(r) if c]; li = cols.index("lex")
            for row in r:
                if li < len(row) and row[li].strip():
                    rows[row[li].strip()] = {cols[i]: row[i] for i in range(len(cols)) if i < len(row)}
    stem_order = [c for _, (c, _f) in sorted(STEMS.items())]
    for c in stem_order:
        if c not in cols:
            cols.append(c)
    for k, g in glosses.items():
        lex, stem = k.split("|", 1)
        rows.setdefault(lex, {"lex": lex})["lex"] = lex
        rows[lex][stem] = g
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh); w.writerow(cols)
        for lex in sorted(rows):
            w.writerow([rows[lex].get(c, "") for c in cols])
    print(f"wrote {len(glosses)} per-stem cells → {out_path.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
