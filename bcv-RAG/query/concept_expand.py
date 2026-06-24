"""Strategy 1: Concept expansion via Strong's reverse-gloss lookup.

Expands query words to `strongs:` tags so the tag_search, lexicon_search,
and morphology_search retrievers find content tagged with the original-
language Strong's number — even when the query uses a different synonym.

Multilingual: the reverse index is built per language from three layers,
highest confidence last so it wins on quality ties —
  1. authoritative UBS glosses   (strongs_gloss.tsv)
  2. LLM gap-fill glosses         (glosses_llm/<lang>.tsv,  source=llm)
  3. aligned-translation lexicon  (aligned_lex/<lang>.tsv,  source=aligned)
A Spanish query "amor" maps to G0026/H0160 just like English "love".
Words not found in the index for ANY language carry no biblical retrieval
signal and are effectively stop words.

Runs at $0, <1ms after the one-time per-language load.
"""
from __future__ import annotations

import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

from resource_paths import resource_path
from lang import canon

_GLOSS_PATHS = [
    resource_path("strongs_gloss.tsv"),
]

# Per-language LLM gap-fill glosses (source=llm), one file per language. Unioned
# into the reverse index alongside the authoritative UBS glosses (never override).
_GLOSSES_LLM_DIR = resource_path("llm_strongs_glosses")

# Per-language aligned lexicons (source=aligned), one file per language: real
# surface→Strong's mappings read from a manually word-aligned Bible
# (Clear-Bible/Alignments). The high-confidence layer — grounded in how a human
# translation actually renders each original word — unioned into the reverse
# index above the LLM glosses. See scripts/build_aligned_all.py.
_ALIGNED_DIR = resource_path("aligned_lex")
# Drop a (surface, code) pair below this fraction of the surface's alignments —
# the long tail of 1-off alignment artifacts (also kills high-frequency function
# surfaces like "de", whose every spurious code has tiny share).
_ALIGNED_MIN_SHARE = 0.05
# At/above this share the code is a *primary* rendering of the surface → quality
# 2 (enters concept expansion); between MIN and PRIMARY it's a secondary sense →
# quality 1. Bi-testamental words clear PRIMARY on both originals (es "espíritu"
# → G4151 pneuma 0.58 AND H7307 ruach 0.40), so both expand.
_ALIGNED_PRIMARY_SHARE = 0.10

# R1 — Strong's → surface family (resources/concept_surfaces/<lang>.tsv), the
# inverse of aligned_lex. Used to expand a query word to every in-language
# rendering of its concept before FTS (recall on prose / other-language Bibles).
_CONCEPT_SURFACES_DIR = resource_path("concept_surfaces")
# Keep only surfaces that genuinely render the concept (surface→Strong's share);
# higher than the reverse-index floor since these go straight into the FTS query.
_SURFACE_MIN_SHARE = 0.15
# A clean single word token (starts with a letter; allows internal '/-). Drops
# alignment-noise surfaces like "1,000" / "-ring" that would break FTS syntax.
_SURFACE_TOKEN = re.compile(r"[^\W\d_][\w'\-]*$")

_FREQ_PATHS = [
    resource_path("strongs_freq.tsv"),
]

_KEYNESS_PATHS = [
    resource_path("strongs_keyness.tsv"),
]

# Concept-expansion floor: don't expand a query word to a Strong's tag whose
# biblical-salience keyness is clearly negative (non-distinctive). Codes absent
# from the table count as neutral (0.0) — function words are already handled by
# the is_function gate.
_KEYNESS_EXPAND_FLOOR = -1.0

# Filter floor: drop a matched query word only when EVERY one of its Strong's
# matches is KNOWN (present in the table) and non-distinctive (keyness ≤ floor).
# Missing/unknown codes never trigger a drop — keyness gaps must not lose words.
_KEYNESS_FILTER_FLOOR = 0.0

_SUFFIXES = ("d", "s", "es", "ed", "ing", "er", "est", "ly", "ness")


@lru_cache(maxsize=1)
def _load_gloss_file() -> Path | None:
    for p in _GLOSS_PATHS:
        if p.exists():
            return p
    return None


@lru_cache(maxsize=1)
def _function_strongs() -> frozenset[str]:
    """Set of Strong's codes (H####/G####) classed as function particles.

    Sourced from strongs_freq.tsv, where is_function=1 means the majority of
    a Strong's number's occurrences in the original text are is_content=0
    (articles, conjunctions, relative particles, prepositions). A query word
    that maps ONLY to function codes carries no retrieval signal and is
    dropped — e.g. H0834 אֲשֶׁר ("que"/"asher"). Frequency-independent, so
    frequent CONTENT words (G2962 κύριος "Lord") are correctly kept.
    """
    for p in _FREQ_PATHS:
        if not p.exists():
            continue
        funcs: set[str] = set()
        with p.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 3 and parts[2] == "1":
                    funcs.add(_normalize_code(parts[0]))  # canonical padded code
        return frozenset(funcs)
    return frozenset()


@lru_cache(maxsize=1)
def _valid_strongs() -> frozenset[str]:
    """Codes that actually occur in the original text (the spine), from
    strongs_freq.tsv.

    A strongs: tag for a code OUTSIDE this set points only at a dictionary /
    extended-numbering entry (e.g. G6113 ἀγάπησις, absent from the Greek text),
    never at scripture — so expanding a query word to it wastes a limited tag
    slot and crowds out the real code (G0026). Concept expansion is restricted
    to this set. Empty → no filtering (graceful degrade if the table is absent).
    """
    for p in _FREQ_PATHS:
        if not p.exists():
            continue
        out: set[str] = set()
        with p.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if parts and parts[0]:
                    out.add(_normalize_code(parts[0]))
        return frozenset(out)
    return frozenset()


@lru_cache(maxsize=1)
def _keyness() -> dict[str, float]:
    """{strong_code: keyness} — per-Strong's biblical-salience weight.

    keyness = zipf_bible − zipf_general (Strategy 2). High = distinctively
    biblical; the weight lives on the language-independent Strong's number, so
    it carries to every query language via the gloss map. Built offline by
    scripts/build_strongs_keyness.py; the server only reads the TSV.
    """
    for p in _KEYNESS_PATHS:
        if not p.exists():
            continue
        out: dict[str, float] = {}
        with p.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2:
                    try:
                        # canonical padded code so padded lookups match files
                        # that store low Greek codes unpadded (e.g. G26→G0026)
                        out[_normalize_code(parts[0])] = float(parts[1])
                    except ValueError:
                        continue
        return out
    return {}


def strong_keyness(code: str, default: float = 0.0) -> float:
    """Biblical-salience weight for a Strong's code (0.0 if not in the table)."""
    return _keyness().get(_normalize_code(code), default)


def _gloss_matches(word: str, lang: str, idx: dict) -> list[tuple[str, int]]:
    """Gloss-index matches for a word, with English suffix stemming."""
    if word in idx:
        return idx[word]
    if lang == "eng":
        for suffix in _SUFFIXES:
            if word.endswith(suffix) and len(word) > len(suffix) + 2:
                stem = word[:-len(suffix)]
                if stem in idx:
                    return idx[stem]
    return []


@lru_cache(maxsize=1)
def _has_lang_column() -> bool:
    tsv = _load_gloss_file()
    if not tsv:
        return False
    with tsv.open(encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
    return "lang" in header


@lru_cache(maxsize=8)
def _reverse_gloss(lang: str = "en") -> dict[str, list[tuple[str, int]]]:
    """Build {gloss_word: [(strong_code, match_quality), ...]} for one language.

    match_quality: 2 = exact (gloss is this single word), 1 = partial
    (gloss contains this word among others). Sorted by quality desc then
    Hebrew-first.
    """
    lang = canon(lang)
    tsv = _load_gloss_file()
    if tsv is None:
        return {}
    has_lang = _has_lang_column()
    index: dict[str, list[tuple[str, int]]] = {}
    with tsv.open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            if has_lang:
                row_lang = parts[3] if len(parts) > 3 else "eng"
                if row_lang != lang:
                    continue
            code = parts[0]
            gloss = parts[1].lower().strip()
            # Split on spaces and semicolons (Chinese glosses use ;)
            gloss_words = re.split(r"[;\s]+", gloss)
            # For CJK, also index individual characters
            cjk_chars = re.findall(r"[一-鿿]", gloss)
            all_tokens = gloss_words + cjk_chars
            for word in all_tokens:
                if not word or (len(word) < 2 and not re.match(r"[一-鿿]", word)):
                    continue
                quality = 2 if len(gloss_words) == 1 else 1
                if word not in index:
                    index[word] = {}
                existing_q = index[word].get(code, 0)
                if quality > existing_q:
                    index[word][code] = quality
    # Union LLM gap-fill glosses for this language (glosses_llm/<lang>.tsv,
    # source=llm) — ADD query words for a concept (e.g. es "gracia" → G5485)
    # alongside the authoritative UBS gloss; never overwrite it.
    llm_path = _GLOSSES_LLM_DIR / f"{lang}.tsv"
    if llm_path.exists():
        si, gi = 0, None  # strong / gloss column indices (header-aware)
        with llm_path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if line.startswith("strong\t"):  # header → locate columns
                    si = parts.index("strong")
                    gi = parts.index("gloss") if "gloss" in parts else len(parts) - 1
                    continue
                if gi is None or len(parts) <= max(si, gi):
                    continue
                code, gloss = parts[si], parts[gi].lower().strip()
                gloss_words = re.split(r"[;\s]+", gloss)
                for word in gloss_words + re.findall(r"[一-鿿]", gloss):
                    if not word or (len(word) < 2 and not re.match(r"[一-鿿]", word)):
                        continue
                    quality = 2 if len(gloss_words) == 1 else 1
                    index.setdefault(word, {})
                    if quality > index[word].get(code, 0):
                        index[word][code] = quality

    # Union the aligned lexicon for this language (aligned_lex/<lang>.tsv,
    # source=aligned) — surface→Strong's grounded in a real human-aligned
    # translation. Higher confidence than the LLM gloss; ADDS the original
    # codes a translation actually uses (incl. cross-testament: es "amor" →
    # G0026 agapē, "alianza" → H1285 bĕrit). Function/low-keyness codes are
    # gated downstream; the share floor here drops the 1-off alignment tail.
    # Skip English: the authoritative UBS glosses are already English-native, so
    # the aligned layer is largely redundant there AND it perturbs the
    # well-tuned English retrieval (a correct new expansion like godliness→G2150
    # can crowd study-resource hits out of the top-k). The layer's value is for
    # languages whose gloss coverage is thin — revisit en once retrieval
    # resource-diversity is addressed.
    aligned_path = _ALIGNED_DIR / f"{lang}.tsv"
    if lang != "eng" and aligned_path.exists():
        with aligned_path.open(encoding="utf-8") as fh:
            si = ci = sh = None  # surface / strong / share column indices
            for line in fh:
                if line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if si is None:  # header row
                    si, ci, sh = (parts.index("surface"), parts.index("strong"),
                                  parts.index("share"))
                    continue
                if len(parts) <= max(si, ci, sh):
                    continue
                try:
                    share = float(parts[sh])
                except ValueError:
                    continue
                if share < _ALIGNED_MIN_SHARE:
                    continue
                word, code = parts[si], parts[ci]
                quality = 2 if share >= _ALIGNED_PRIMARY_SHARE else 1
                index.setdefault(word, {})
                if quality > index[word].get(code, 0):
                    index[word][code] = quality

    result: dict[str, list[tuple[str, int]]] = {}
    for word, code_map in index.items():
        entries = [(code, q) for code, q in code_map.items()]
        entries.sort(key=lambda x: (-x[1], 0 if x[0][0] == "H" else 1, x[0]))
        result[word] = entries
    return result


def _normalize_code(code: str) -> str:
    """H430 → H0430 (4-digit padded); strip a sense suffix (H2403a → H2403).

    The spine-derived tables (freq, keyness) and the index.db strongs: tags are
    unsuffixed, so suffixed UBS gloss codes must collapse to match them.
    """
    m = re.match(r"^([HG])(\d+)[a-z]?$", code)
    if not m:
        return code
    return f"{m.group(1)}{int(m.group(2)):04d}"


def is_biblical_word(word: str, lang: str = "en") -> bool:
    """True if this word appears as a gloss for any Strong's number."""
    lang = canon(lang)
    idx = _reverse_gloss(lang)
    if word.lower() in idx:
        return True
    if lang == "eng":
        for suffix in _SUFFIXES:
            stem = word.lower()
            if stem.endswith(suffix) and len(stem) > len(suffix) + 2:
                if stem[:-len(suffix)] in idx:
                    return True
    return False


_LANG_DIR = resource_path("analyzer_lang")


@lru_cache(maxsize=16)
def _lang_stopwords(lang: str) -> frozenset[str]:
    """Stopwords for THIS language only — NO English fallback.

    Used as a first gate in filter_biblical_words: function words like the
    Spanish article "la" align to many Strong's in the alignment data (the
    article G3588 *and* content words like H6440 "face"), so the gloss-only
    gates can't drop them. An explicit per-language stopword list can.

    Reads analyzer_lang/<lang>.json *directly*, NO cross-language fallback: a
    language with no config (some of fr/pt/ru/…) returns empty so the gloss-only
    gates still apply, and we never bleed English stops into, say, French
    ("or"=gold). English is NOT special-cased — `eng.json` supplies its stops
    just like any language (English now goes through filter_biblical_words too).
    """
    lang = canon(lang)
    if not lang:
        return frozenset()
    p = _LANG_DIR / f"{lang}.json"
    if not p.exists():
        return frozenset()
    try:
        return frozenset(json.loads(p.read_text(encoding="utf-8")).get("stopwords", []))
    except Exception:
        return frozenset()


@lru_cache(maxsize=16)
def _lang_frame_words(lang: str) -> frozenset[str]:
    """Interrogative *frame* words for THIS language (NO English fallback).

    Distinct from stopwords (function particles): frame words are real,
    exact-gloss CONTENT words that nonetheless act as question scaffolding —
    "¿de qué DIFERENTES TIPOS … HABLA la Biblia?". They are not the query's
    subject, but they expand to off-target Strong's (habla→G2980 λαλέω "speak",
    diferentes→H8133 "change"), flooding the lexicon branch with noise that no
    downstream signal can cleanly trim (their codes are ordinary exact glosses).
    Curated per language under the `frame_words` key, sibling to `stopwords`.
    Empty for any language without the key → no behavior change. English is not
    special-cased — `eng.json` supplies its frame_words like any language.
    """
    lang = canon(lang)
    if not lang:
        return frozenset()
    p = _LANG_DIR / f"{lang}.json"
    if not p.exists():
        return frozenset()
    try:
        return frozenset(json.loads(p.read_text(encoding="utf-8")).get("frame_words", []))
    except Exception:
        return frozenset()


def filter_biblical_words(raw_query: str, lang: str = "en", *, strip_frames: bool = True) -> str:
    """Keep only biblical content words; drop function words in any language.

    Three gates:
      0. Stopword — a word in the language's analyzer stopword list is dropped
         outright (handles function words that alignment noise maps to content
         Strong's, e.g. Spanish "la").
      0b. Frame word — an interrogative scaffolding word (`frame_words` list,
         e.g. Spanish "habla"/"diferentes") is dropped: it's a real content word
         but the query's frame, not its subject, and expands to off-target
         Strong's. Skipped when strip_frames=False (used by eval A/B).
      1. Length/exactness — a short word (≤3 chars, non-CJK) survives only if
         it has an exact (quality=2) gloss match. This drops articles caught
         as partial gloss fragments (Spanish "la" inside "la piedra"). Longer
         words pass this gate even without a match — UBS glosses have gaps, so
         "gracia"/"graça" must survive.
      2. Function particle — a word whose gloss matches are ALL classed as
         function (is_content=0 in the corpus) is dropped regardless of
         length: H0834 אֲשֶׁר ("que"), G3588 ὁ ("the"). Content words with the
         same or higher frequency (G2962 κύριος "Lord") are kept.

    Returns an FTS-ready OR query.
    """
    lang = canon(lang)
    idx = _reverse_gloss(lang)
    if not idx:
        return raw_query
    funcs = _function_strongs()
    stops = _lang_stopwords(lang)
    frames = _lang_frame_words(lang) if strip_frames else frozenset()

    words = re.findall(r"[一-鿿]|[\w]{2,}", raw_query.lower())
    kept: list[str] = []
    for w in words:
        # Gate 0: explicit per-language stopword
        if w in stops:
            continue
        # Gate 0b: interrogative frame word (real content word, but query
        # scaffolding — expands to off-target Strong's; see _lang_frame_words)
        if w in frames:
            continue
        is_cjk = bool(re.match(r"[一-鿿]", w))
        is_short = len(w) <= 3 and not is_cjk
        matches = _gloss_matches(w, lang, idx)

        # Gate 1: length / exactness
        if not matches:
            if not is_short:
                kept.append(w)
            continue
        exact = [c for c, q in matches if q == 2]
        if is_short and not exact:
            continue

        # Gate 2: drop if every relevant match is non-distinctive — either a
        # function particle (is_function) or a known-low keyness concept.
        relevant = [_normalize_code(c) for c in (exact if exact else [c for c, _ in matches])]
        keyness = _keyness()
        all_function = bool(funcs) and all(c in funcs for c in relevant)
        all_low_key = all(c in keyness and keyness[c] <= _KEYNESS_FILTER_FLOOR
                          for c in relevant)
        if relevant and (all_function or all_low_key):
            continue

        kept.append(w)

    return " OR ".join(kept) if kept else raw_query


def expand_concepts(fts_query: str, existing_tags: list[str],
                    max_per_word: int = 2, max_total: int = 4,
                    lang: str = "en") -> list[str]:
    """Return additional strongs: tags for concept words in the query.

    Only expands words that aren't already covered by explicit Strong's tags
    in the analysis. Prefers exact gloss matches (quality=2) and Hebrew
    Strong's numbers. Conservative limits to avoid tag noise.

    Works for any language in the gloss index (en, es, fr, pt, zh, zh-Hant).
    """
    lang = canon(lang)
    idx = _reverse_gloss(lang)
    if not idx and lang != "eng":
        idx = _reverse_gloss("eng")
    if not idx:
        return []

    existing_strongs = {t for t in existing_tags if t.startswith("strongs:")}
    # CJK characters are meaningful as single chars; Latin needs 2+
    words = re.findall(r"[一-鿿]|[\w]{2,}", fts_query.lower())

    # Sort words: exact-match (quality=2) words first, so content words
    # like "grace" get expanded before function words like "sobre"
    def _best_quality(w: str) -> int:
        forms = [w]
        if lang == "eng":
            for suffix in _SUFFIXES:
                if w.endswith(suffix) and len(w) > len(suffix) + 2:
                    forms.append(w[:-len(suffix)])
        for form in forms:
            if form in idx:
                return max(q for _, q in idx[form])
        return 0
    words.sort(key=lambda w: (-_best_quality(w), -len(w)))

    # Collect candidate tags with their keyness, then keep the most
    # distinctive — limited tag slots go to the strongest biblical concepts.
    seen: set[str] = set()
    candidates: list[tuple[float, str]] = []
    for w in words:
        forms = [w]
        if lang == "eng":
            for suffix in _SUFFIXES:
                if w.endswith(suffix) and len(w) > len(suffix) + 2:
                    forms.append(w[:-len(suffix)])

        matches: list[tuple[float, str]] = []
        for form in forms:
            if form in idx:
                exact = [(c, q) for c, q in idx[form] if q == 2]
                pool = exact if exact else idx[form][:4]
                valid = _valid_strongs()
                for code, _ in pool:
                    norm = _normalize_code(code)
                    tag = f"strongs:{norm}"
                    if tag in existing_strongs or tag in seen:
                        continue
                    if valid and norm not in valid:
                        continue  # extended/dictionary-only code — no scripture
                    key = strong_keyness(norm)
                    if key < _KEYNESS_EXPAND_FLOOR:
                        continue  # non-distinctive concept — skip
                    seen.add(tag)
                    matches.append((key, tag))
                break

        # Highest-keyness matches for this word first, capped per word
        matches.sort(key=lambda m: -m[0])
        candidates.extend(matches[:max_per_word])

    # Across all words, keep the most distinctive tags overall
    candidates.sort(key=lambda m: -m[0])
    return [tag for _, tag in candidates[:max_total]]


def term_strongs(text: str, lang: str = "eng", cap: int = 12) -> list[str]:
    """Generous Strong's codes for a CONCEPT TERM — every exact (quality-2)
    gloss code, valid in scripture and non-function, padded.

    For *tagging* concept resources (e.g. Door43 TW articles) so multilingual
    concept queries reach an English-only article via the bridge it already has
    (`amor → strongs:G0026 → tag_search`). Unlike expand_concepts (the QUERY
    side — keyness-ranked, capped at 4, which drops a low-keyness anchor like
    G0026 ágape for "love"), this keeps the whole concept family: a TW article
    covers the concept across words, so "love" → H0157/H0160/H2245/G0025/G0026/
    G5368. Returns bare codes (no `strongs:` prefix) — caller adds it.
    """
    idx = _reverse_gloss(canon(lang))
    if not idx:
        return []
    valid = _valid_strongs()
    funcs = _function_strongs()
    out: list[str] = []
    for w in re.split(r"[^\w]+", text.lower()):
        for code, q in idx.get(w, []):
            if q != 2:
                continue
            norm = _normalize_code(code)
            if (not valid or norm in valid) and norm not in funcs and norm not in out:
                out.append(norm)
    return out[:cap]


# ---------- R1: surface-family recall expansion ----------

@lru_cache(maxsize=8192)
def _porter_stem(word: str) -> str:
    """Porter stem via SQLite's OWN fts5 'porter' tokenizer — the exact engine the
    chunks_fts index uses, so "redundant inflection" means precisely "the FTS
    already matches it". No external stemmer dependency.

    Returns the space-joined stem token(s) (single token for a single word).
    """
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE VIRTUAL TABLE s USING fts5(x, "
                   "tokenize='porter unicode61 remove_diacritics 2')")
        db.execute("INSERT INTO s(x) VALUES(?)", (word.lower(),))
        db.execute("CREATE VIRTUAL TABLE v USING fts5vocab('s','row')")
        terms = sorted(r[0] for r in db.execute("SELECT term FROM v"))
    except sqlite3.OperationalError:
        return word.lower()
    finally:
        db.close()
    return " ".join(terms) or word.lower()

@lru_cache(maxsize=8)
def _concept_surfaces(lang: str) -> dict[str, list[tuple[str, float]]]:
    """{strong_code: [(surface, share), ...]} from concept_surfaces/<lang>.tsv.

    `share` is the surface→Strong's alignment confidence (carried from
    aligned_lex). Empty if the file is absent (graceful degrade).
    """
    lang = canon(lang)
    p = _CONCEPT_SURFACES_DIR / f"{lang}.tsv"
    out: dict[str, list[tuple[str, float]]] = {}
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fh:
        si = fi = shi = None
        for line in fh:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if si is None:  # header
                try:
                    si, fi, shi = (parts.index("strong"), parts.index("surface"),
                                   parts.index("share"))
                except ValueError:
                    return {}
                continue
            if len(parts) <= max(si, fi, shi):
                continue
            try:
                share = float(parts[shi])
            except ValueError:
                continue
            out.setdefault(parts[si], []).append((parts[fi], share))
    return out


def surface_family(strong: str, lang: str, *, floor: float = _SURFACE_MIN_SHARE) -> list[str]:
    """In-language surface renderings of a concept (Strong's), share-filtered and
    cleaned to FTS-safe single-word tokens. Ordered by the file (count desc)."""
    fam: list[str] = []
    for surface, share in _concept_surfaces(lang).get(_normalize_code(strong), []):
        if share < floor:
            continue
        s = surface.lower()
        if _SURFACE_TOKEN.match(s):
            fam.append(s)
    return fam


def expand_surfaces(keywords: list[str], lang: str, *,
                    max_per_word: int = 4, max_total: int = 12,
                    floor: float = _SURFACE_MIN_SHARE) -> list[str]:
    """Extra FTS terms: in-language surface renderings of each keyword's concept
    (so "amor" also reaches "caridad"/"amado"). Broadens recall on prose where
    exact match misses synonyms/inflections.

    English is **synonym-only**: the chunks_fts index is porter-stemmed, so
    inflections of the query word (love→loved/loving) already match — adding them
    is redundant *and* perturbs the tuned English retrieval. So for English we
    drop any surface that shares the query word's porter stem and keep only
    cross-lemma synonyms (faith→belief, covenant→treaty) that stemming can't
    merge. Non-English keeps inflections too (its porter stemming doesn't fit
    those languages, so the renderings genuinely add coverage).

    Returns NEW terms only (deduped against the input keywords), capped.
    """
    lang = canon(lang)
    idx = _reverse_gloss(lang)
    if not idx:
        return []
    valid = _valid_strongs()
    funcs = _function_strongs()
    is_eng = lang == "eng"

    seen = {w.lower() for w in keywords}
    out: list[str] = []
    for w in keywords:
        wl = w.lower()
        w_stem = _porter_stem(wl) if is_eng else None
        # query word → its exact (quality-2), scripture-valid, non-function codes
        codes: list[str] = []
        for code, q in _gloss_matches(wl, lang, idx):
            if q != 2:
                continue
            norm = _normalize_code(code)
            if (valid and norm not in valid) or norm in funcs:
                continue
            codes.append(norm)

        added = 0
        for code in codes:
            fam = surface_family(code, lang, floor=floor)
            # Mutual constraint: only expand through a code if the query word is
            # ITSELF a primary rendering of it. Drops spurious word→code links
            # whose family is off-concept (es "amor" picking up "enlosado").
            if wl not in fam:
                continue
            for s in fam:
                if s in seen:
                    continue
                # English: keep only cross-lemma synonyms — skip surfaces the
                # porter FTS already matches as inflections of the query word.
                if is_eng and _porter_stem(s) == w_stem:
                    continue
                seen.add(s)
                out.append(s)
                added += 1
                if added >= max_per_word:
                    break
            if added >= max_per_word:
                break
        if len(out) >= max_total:
            break
    return out[:max_total]
