"""Reader for Clear-Bible/Alignments data — generic over language + version.

Each language has a word-aligned target Bible (e.g. spa/RV09) split into three
parts that join by token id:
  data/sources/<SRC>.tsv                 original tokens: id, text, strongs, lemma, …
  data/<lang>/targets/<VER>/{nt,ot}_<VER>.tsv   target tokens: id, source_verse, text, skip_space_after, …
  data/<lang>/alignments/<VER>/<SRC>-<VER>-manual.json   records: {source:[ids], target:[ids]}

Yields one record per verse:
  {ref: int BBCCCVVV, text: str (reconstructed),
   strongs: sorted list (padded H####/G####, from aligned source tokens),
   tokens: [{surface, strong|None}]}

This is the reusable B1+A2 core: `text` → content (FTS/display); per-token
`strong` → surface→Strong's (Tier-2 tagged translation). No index.db / network
dependency — point it at a local clone of the Alignments repo.

Usage:
  from ingest.clear_aligned import read_aligned
  for v in read_aligned("/path/to/Alignments/data", "spa", "RV09"):
      ...
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path


def _bare(token_id: str) -> str:
    """Source token id without its scheme prefix (n40…/o01… → 40…/01…).

    Manual alignments reference sources with the prefix; transfer alignments
    drop it. Keying both sides on the bare digits makes the join prefix-blind.
    NT (books 40-66) and OT (01-39) bare ids never collide.
    """
    return re.sub(r"^[A-Za-z]+", "", token_id or "")


def _norm_strong(s: str) -> str:
    """Canonicalize to padded prefixed, matching our core's granularity.

    Greek source codes are prefixed (G0976); Hebrew source codes are BARE
    numbers, often with an a/b/c sense suffix (0871a). A bare code is Hebrew,
    so it gets an 'H'; the suffix is dropped because our concepts/gloss tables
    carry no suffixed codes — keeping it would prevent the join.
    """
    m = re.match(r"^([HG])?0*(\d+)[a-z]?$", (s or "").strip())
    if not m:
        return ""
    return f"{m.group(1) or 'H'}{int(m.group(2)):04d}"


def _load_sources(data_dir: Path, src_ids: set[str]) -> dict[str, str]:
    """{source_token_id: padded_strong} from the named source TSVs."""
    out: dict[str, str] = {}
    for src in src_ids:
        p = data_dir / "sources" / f"{src}.tsv"
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                code = _norm_strong((row.get("strongs") or "").split("/")[0])
                if code:
                    out[_bare(row["id"])] = code
    return out


def _load_sources_rich(data_dir: Path, src_ids: set[str]) -> dict[str, dict]:
    """{bare_source_token_id: {strong, lemma, prefixed_id}} from source TSVs.

    Richer than `_load_sources` — also carries the original-language `lemma` and
    the full prefixed token id (the Clear/BCVW anchor, e.g. n40010030011) for
    provenance/attestation. Keyed on the bare id so the prefix-blind join holds.
    """
    out: dict[str, dict] = {}
    for src in src_ids:
        p = data_dir / "sources" / f"{src}.tsv"
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                code = _norm_strong((row.get("strongs") or "").split("/")[0])
                if not code:
                    continue
                out[_bare(row["id"])] = {
                    "strong": code,
                    "lemma": (row.get("lemma") or "").strip(),
                    "id": row["id"],
                    "pos": (row.get("pos") or "").strip(),
                }
    return out


# Hebrew source tokens are MORPHEMES (prefix, stem, suffix); the id's last digit numbers them within the word.
# A word-level alignment (BSB, IRVHin) lists all of them; the prefix (conjunction, preposition, article) must not
# take the link. Content parts, in preference order; anything else (suffix, bare prefix) never wins over them.
_CONTENT_POS = ("noun", "verb", "adjective", "adverb", "pronoun")


def _word_of(bare_id: str) -> str:
    return bare_id[:-1]


def _pick_source(src_tokens: list[str], sources: dict[str, dict], hebrew: bool) -> dict | None:
    """The source token an alignment record is attributed to.

    Greek / single token: the first token with a Strong's (as before). Hebrew record with several morphemes:
    the first content morpheme (noun/verb/adjective/adverb/pronoun); if none, the last non-suffix morpheme
    (the stem follows its prefixes); the first token only as a last resort."""
    infos = [i for i in (sources.get(_bare(s)) for s in src_tokens) if i]
    if not infos:
        return None
    if not hebrew or len(infos) == 1:
        return infos[0]
    for i in infos:
        if i.get("pos") in _CONTENT_POS:
            return i
    body = [i for i in infos if i.get("pos") != "suffix"]
    return (body or infos)[-1] if body else infos[0]


def read_aligned_occurrences(data_dir: str | Path, lang: str, version: str):
    """Yield one record per aligned target *occurrence* with full provenance.

    Unlike `read_aligned`, this does NOT collapse manual/transfer — each
    alignment file is processed and labelled, so the same target token can be
    attested by both methods (that agreement is the provenance signal). Carries
    the original `lemma`, the source token's Clear/BCVW id, the alignment
    `method`, the original-language `source` corpus, and the target `version`.

    Yields: {ref:int BBCCCVVV, target_id:str, source_id:str, surface:str,
             strong:str, lemma:str, method:str, source_corpus:str, version:str}
    """
    data_dir = Path(data_dir)
    align_dir = data_dir / lang / "alignments" / version
    target_dir = data_dir / lang / "targets" / version

    align_files = sorted(align_dir.glob(f"*-{version}-*.json")) if align_dir.exists() else []
    target_files = sorted(target_dir.glob(f"*_{version}.tsv")) if target_dir.exists() else []
    if not align_files or not target_files:
        raise FileNotFoundError(f"no Clear-Bible data for {lang}/{version} under {data_dir}")

    targets = _load_targets(target_files)
    # every <SRC> referenced by an alignment file (SBLGNT, WLCM, BGNT, …)
    src_ids = {f.name.split("-")[0] for f in align_files}
    sources = _load_sources_rich(data_dir, src_ids)
    morphemes: dict[str, int] = {}                      # word id -> how many source morphemes it has
    for bare in sources:
        morphemes[_word_of(bare)] = morphemes.get(_word_of(bare), 0) + 1

    for af in align_files:
        parts = af.stem.split("-")           # <SRC>-<VERSION>-<method>
        src_corpus = parts[0]
        method = "manual" if af.stem.endswith("-manual") else "transfer"
        rec = json.loads(af.read_text(encoding="utf-8"))
        for r in rec.get("records", []):
            src_tokens = r.get("source", [])
            picked = _pick_source(src_tokens, sources, src_corpus.startswith("WLC"))
            if not picked:
                continue
            words = {_word_of(_bare(s)) for s in src_tokens}
            if len(words) > 1:
                unit = "span"                            # several words
            elif len(src_tokens) >= morphemes.get(next(iter(words)), 1):
                unit = "word"                            # every morpheme of one word (word-level link)
            else:
                unit = "morpheme"                        # a part of a multi-morpheme word
            for t in r.get("target", []):
                tok = targets.get(t)
                if not tok or tok["verse"] is None:
                    continue
                yield {
                    "ref": tok["verse"],
                    "target_id": t,
                    "source_id": picked["id"],
                    "surface": tok["text"],
                    "strong": picked["strong"],
                    "lemma": picked["lemma"],
                    "method": method,
                    "source_corpus": src_corpus,
                    "source_unit": unit,
                    "version": version,
                }


def _load_targets(target_files: list[Path]) -> dict[str, dict]:
    """{target_token_id: {text, verse, skip}} from the target TSVs.

    The verse is taken from the token id (BBCCCVVV·WWW) rather than a
    `source_verse` column, since the column name/presence varies between
    targets (e.g. spa RV09 has it, fra LSG doesn't) but the id scheme is
    constant across the corpus.
    """
    out: dict[str, dict] = {}
    for p in target_files:
        with p.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                tid = row["id"]
                verse = tid[:8]
                out[tid] = {
                    "text": row.get("text") or "",
                    "verse": int(verse) if verse.isdigit() else None,
                    "skip": (row.get("skip_space_after") or "").lower() == "true",
                }
    return out


def read_aligned(data_dir: str | Path, lang: str, version: str):
    """Yield per-verse records for one language/version. See module docstring."""
    data_dir = Path(data_dir)
    align_dir = data_dir / lang / "alignments" / version
    target_dir = data_dir / lang / "targets" / version

    # Alignment files are <SRC>-<VERSION>-<type>.json where type is `manual`
    # (human) or `transfer` (projected). Prefer manual when both exist for a
    # source; otherwise take whatever is published (e.g. por only has transfer).
    found = sorted(align_dir.glob(f"*-{version}-*.json")) if align_dir.exists() else []
    chosen: dict[str, Path] = {}
    for f in found:
        src = f.name.split("-")[0]
        if src not in chosen or f.stem.endswith("-manual"):
            chosen[src] = f
    align_files = list(chosen.values())
    target_files = sorted(target_dir.glob(f"*_{version}.tsv")) if target_dir.exists() else []
    if not align_files or not target_files:
        raise FileNotFoundError(f"no Clear-Bible data for {lang}/{version} under {data_dir}")

    targets = _load_targets(target_files)
    src_ids = set(chosen)                                       # e.g. SBLGNT, WLCM
    sources = _load_sources_rich(data_dir, src_ids)

    # target_id -> aligned source strong (content morpheme of a Hebrew word-level link, see _pick_source)
    tgt_strong: dict[str, str] = {}
    for af in align_files:
        rec = json.loads(af.read_text(encoding="utf-8"))
        for r in rec.get("records", []):
            picked = _pick_source(r.get("source", []), sources, af.name.startswith("WLC"))
            if not picked:
                continue
            for t in r.get("target", []):
                tgt_strong.setdefault(t, picked["strong"])

    # group target tokens by verse, in token-id order (reconstruct text)
    verses: dict[int, list[str]] = {}
    for tid, tok in targets.items():
        if tok["verse"] is not None:
            verses.setdefault(tok["verse"], []).append(tid)

    for ref in sorted(verses):
        ids = sorted(verses[ref])
        parts, toks, strongs = [], [], set()
        for tid in ids:
            tok = targets[tid]
            parts.append(tok["text"] + ("" if tok["skip"] else " "))
            code = tgt_strong.get(tid)
            toks.append({"surface": tok["text"], "strong": code})
            if code:
                strongs.add(code)
        yield {"ref": ref, "text": "".join(parts).strip(),
               "strongs": sorted(strongs), "tokens": toks}
