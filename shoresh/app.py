"""shoresh — original-language anchoring service.

Anchors biblical study on the structure of the original Hebrew/Greek, not on
BCV. Current capabilities are deterministic, $0 reads over the original-
language word stores (lxx.db + spine.db):

  GET /health                       liveness
  GET /                             service descriptor + data status
  GET /verse/{book}/{chapter}/{verse}   Greek (LXX) + Hebrew/Greek (spine) interlinear
  GET /word/{strong}                concordance for a Strong's number (e.g. G2316, H7225)
  GET /structure/{book}/{ch}/{v}    BHSA/Nestle1904 structure from bcv-corpus
  GET /search?q=&lang=hbo           clause-level original-language semantic search
  GET /words?language=&pos=&...     filtered corpus word sampler (vocab-trainer feed)

The service is reachable from the open internet (Caddy → uvicorn): CORS is open
for the read-only word data, and every route carries a per-IP rate limit
(ratelimit.py). The /search store + model are loaded at startup (not per-request)
so a scale-to-zero cold start doesn't load the model mid-request and 502.
"""
from __future__ import annotations

import logging
import math
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

import corpus
import data
from macula import data as macula
from ratelimit import limiter

logger = logging.getLogger("shoresh")

# bcv-corpus (BHSA/Nestle1904 structural graph) over Railway private networking.
CORPUS_URL = os.environ.get("CORPUS_URL", "")

# Loaded clause vector stores, keyed by language (populated at startup).
SEARCH: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    from search import store as vstore
    for lang in ("hbo", "grc"):
        if vstore.exists(lang):
            try:
                SEARCH[lang] = vstore.ClauseStore(lang)
                from search.embedder import get_encoder
                get_encoder(lang)               # warm the model at startup
                logger.info("search[%s]: %d clauses loaded + model warm",
                            lang, SEARCH[lang].count)
            except Exception as e:              # serve the rest even if search fails
                logger.warning("search[%s] failed to load: %s", lang, e)
    yield


app = FastAPI(
    title="shoresh",
    description="Original-language anchoring service (Hebrew/Greek structure).",
    version="0.2.0",
    lifespan=lifespan,
)

# Per-IP rate limiting (blanket default from ratelimit.py) — shoresh is public.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS: read-only public word data → open to any origin (browser vocab trainers,
# etc.). GET-only, no credentials. Added last so it wraps the rate limiter and a
# preflight OPTIONS still gets CORS headers. Override origins via SHORESH_CORS_ORIGINS
# (comma-separated) to lock down to specific apps.
_cors_origins = os.environ.get("SHORESH_CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins.split(",")] if _cors_origins else ["*"],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "shoresh"}


@app.get("/")
def root() -> dict:
    return {
        "service": "shoresh",
        "purpose": "anchor biblical study on original-language structure (not BCV)",
        "corpus_url_configured": bool(CORPUS_URL),
        "data": data.databases_status(),
        "search": {lang: store.count for lang, store in SEARCH.items()},
        "endpoints": [
            "/verse/{book}/{chapter}/{verse}",
            "/word/{strong}",
            "/gloss/{word}",
            "/concept/{word}",
            "/morph?pattern=&book=&chapter=",
            "/bridge/{strong}",
            "/structure/{book}/{chapter}/{verse}",
            "/structure/{book}/{chapter}/{verse}/word/{idx}",
            "/search?q=&lang=hbo&k=10&enrich=false&translate=gloss|llm",
            "/words?language=Hebrew|Aramaic|Greek&pos=&stem=&tense=&suffix=&min_rank=&max_rank=&limit=&random=",
            "/domain/{code}?axis=sdbg|core|lex|ctx",
            "/wordstudy/{strong}",
            "/speakers",
            "/speaker/{name}",
            "/speakers/at/{book}/{chapter}/{verse}",
            "/coref/{book}/{chapter}/{verse}/word/{idx}",
            "/frame/{book}/{chapter}/{verse}/word/{idx}",
            "/participants/{book}/{chapter}/{verse}",
        ],
        "docs": "../docs/original-language-anchoring.md",
    }


@app.get("/verse/{book}/{chapter}/{verse}")
def get_verse(book: str, chapter: int, verse: int) -> dict:
    """Greek (LXX) + Hebrew/Greek (spine) words of a verse, side by side."""
    result = data.verse(book, chapter, verse)
    if result["lxx"] is None and result["spine"] is None:
        raise HTTPException(404, f"no original-language words for {book} {chapter}:{verse}")
    return result


@app.get("/word/{strong}")
def get_word(strong: str, limit: int = 200) -> dict:
    """Concordance: every occurrence of a Strong's number (G#### Greek / H#### Hebrew)."""
    result = data.concordance(strong, limit=min(limit, 1000))
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.get("/gloss/{word}")
def get_gloss(word: str) -> dict:
    """Reverse gloss: English word → all Hebrew/Greek Strong's numbers behind it."""
    result = data.gloss_lookup(word)
    if not result["matches"]:
        raise HTTPException(404, f"no Strong's entries found for gloss '{word}'")
    return result


@app.get("/tw/{strong}")
def get_tw(strong: str) -> dict:
    """Translation-Words article(s) explaining a Strong's number (G#### / H####),
    ranked by occurrence. e.g. G0026 → bible/kt/love."""
    result = data.tw_articles(strong)
    if not result["articles"]:
        raise HTTPException(404, f"no Translation-Words article for Strong's '{strong}'")
    return result


@app.get("/domain/{code}")
def get_domain(code: str, axis: str = "sdbg") -> dict:
    """Every lexeme in a semantic domain, glossed — "every word in Love/Affection".
    axis=sdbg (Louw-Nida; Greek + LXX-bridged Hebrew) | core | lex | ctx (native SDBH).
    e.g. /domain/025003 → ἀγάπη, ἀγαπάω, … + the Hebrew the LXX renders into it."""
    result = data.domain_lexemes(code, axis=axis)
    if not result["lexemes"]:
        raise HTTPException(404, f"no lexemes in domain '{code}' (axis={axis})")
    return result


@app.get("/wordstudy/{strong}")
def get_wordstudy(strong: str) -> dict:
    """Composite word-study card for a Strong's: gloss, keyness (how distinctively
    biblical — score = zipf_bible − zipf_general, content words only; Hebrew carries
    `modern_he` + `archaic` = extinct in modern Hebrew, Greek carries `koine_general` +
    `scripture_only` = absent from secular/pagan Koine, Aramaic = score only),
    semantic domain(s) + co-domain siblings, senses (polysemy), and cross-language."""
    result = data.word_study(strong)
    if not result.get("domains") and not result.get("senses") and not result.get("gloss"):
        raise HTTPException(404, f"no lexical data for Strong's '{strong}'")
    return result


@app.get("/words")
def get_words(
    language: str,
    pos: str | None = None,
    stem: str | None = None,
    tense: str | None = None,
    suffix: bool | None = None,
    min_rank: int | None = None,
    max_rank: int | None = None,
    limit: int = 50,
    random: bool = False,
    order: str | None = None,
) -> dict:
    """Filtered word sample from the corpus — the vocabulary trainer feed.

    Returns up to `limit` words matching the given criteria, each with full
    morphology, frequency rank, gloss, passage ref, and the surrounding clause
    words with the target word's position marked.

    **language** (required): `Hebrew` | `Aramaic` | `Greek`

    **pos** — comma-separated part-of-speech codes.
    Hebrew/Aramaic: `subs verb prep conj art prde prin advb nmpr intj nega inrg`
    Greek: `verb noun adj adv prep conj det pron ptcl intj num`

    **stem** — comma-separated verbal-stem codes (Hebrew/Aramaic only; ignored for Greek).
    Values: `qal nif piel pual hif hof hit` etc.

    **tense** — comma-separated tense/aspect codes.
    Hebrew: `perf impf wayq impv infc infa ptca ptcp`
    Greek: `aor pres fut perf imperf plup`

    **suffix** — `true` = has pronominal suffix; `false` = no suffix (Hebrew/Aramaic only).

    **min_rank** / **max_rank** — inclusive frequency-rank band. `0` = most frequent lexeme.

    **limit** — number of results (default 50, max 500).

    **random** — if `true`, randomly sample from the filtered pool (so repeated calls vary).

    **order** — how to pick `limit` words from the matching pool:
    `frequency` (most common first — the standard vocab-learning order), `rare`
    (least common first), `random` (= the `random` flag), `pool` (corpus order,
    default). `frequency` selects the actual N most-frequent words of the pool, not
    a random sample — e.g. "the 250 most common Hebrew verbs".

    Response includes `total_pool` (how many words matched before sampling) and
    `count` (words returned). Each word carries: `node lex lexUtf8 language pos
    stem tense rank sfx gloss strong keyness priority ref clauseWords targetIndex`.

    `strong` is the Strong's number (or null where the lex→Strong's bridge has no
    mapping — rare lexemes). `keyness` = how distinctively biblical the word is
    (`{score, anchor}`; score = zipf_bible − zipf_general, higher = more distinctively
    scriptural; content words only). Hebrew (anchor 'he') also carries `modern_he` +
    `archaic` (`== 0`, extinct in modern Hebrew); Greek (anchor 'grc') carries
    `koine_general` + `scripture_only` (`== 0`, absent from secular/pagan Koine — e.g.
    ἀγάπη elevated by scripture); biblical Aramaic (anchor 'arc') carries score only (no
    presence flag — modern Hebrew is the wrong denominator). Function words have no
    keyness. Both presence flags are robust even for rare words where `score` is noisy.

    `priority` (0–100, higher = study sooner) is a ready-made study-priority score
    combining `rank` (frequency, dominant) with `keyness` (distinctiveness, a bonus) —
    a transparent heuristic; clients can re-derive their own from the raw fields.
    """
    if limit < 1 or limit > 500:
        raise HTTPException(400, "limit must be 1..500")
    order = (order or ("random" if random else "pool")).lower()
    if order not in ("pool", "random", "frequency", "rare"):
        raise HTTPException(400, "order must be one of: frequency, rare, random, pool")

    lang_to_corpus = {"Hebrew": "hebrew", "Aramaic": "hebrew", "Greek": "greek"}
    corpus = lang_to_corpus.get(language)
    if corpus is None:
        raise HTTPException(400, f"language must be Hebrew, Aramaic, or Greek (got '{language}')")

    pos_list = [p.strip() for p in pos.split(",")] if pos else None
    stem_list = [s.strip() for s in stem.split(",")] if stem else None
    tense_list = [t.strip() for t in tense.split(",")] if tense else None

    try:
        from corpus_engine import engine
        result = engine.list_words_filtered(
            corpus=corpus,
            language=language if corpus == "hebrew" else None,
            pos=pos_list,
            stem=stem_list,
            tense=tense_list,
            suffix=suffix,
            min_rank=min_rank,
            max_rank=max_rank,
            limit=limit,
            random_sample=random,
            order=order,
        )
    except Exception as exc:
        raise HTTPException(503, f"corpus unavailable: {exc}") from exc

    # Per word, via its Strong's: attach keyness (distinctiveness), repair dash/empty
    # per-occurrence glosses (Nestle1904 marks some tokens "-", incl. ὁ) from the lemma's
    # authoritative Strong's gloss, and compute a study-priority score.
    for w in result.get("words", []):
        strong = w.get("strong")
        w["keyness"] = data.keyness_of(strong) if strong else None
        if strong and (w.get("gloss") or "").strip() in ("", "-"):
            g = data.gloss_of(strong)
            if g and g.get("gloss"):
                w["gloss"] = g["gloss"]
        w["priority"] = _study_priority(w.get("rank"), w["keyness"])

    return {"language": language, **result}


def _study_priority(rank: int | None, keyness: dict | None) -> float:
    """Study-priority 0–100 (higher = learn sooner). Frequency-dominant: a log map of
    `rank` (rank 0 → 100, ~rank 10000 → 0) gives the standard vocab-learning order; a
    distinctiveness bonus of up to +15 from `keyness` nudges distinctively-biblical words
    up among similarly-frequent ones. A heuristic — re-derivable from rank + keyness."""
    r = 9999 if rank is None else rank
    freq = max(0.0, 100.0 * (1.0 - math.log10(r + 1) / 4.0))
    score = (keyness or {}).get("score") or 0.0
    bonus = max(0.0, min(score, 6.0)) / 6.0 * 15.0
    return round(min(100.0, freq + bonus), 1)


@app.get("/coref/{book}/{chapter}/{verse}/word/{idx}")
def get_coref(book: str, chapter: int, verse: int, idx: int) -> dict:
    """Coreference: who/what the word at this reference points to — "who is 'he/his'
    here". Resolves MACULA referent (Greek) / participantref (Hebrew) / subjref token
    pointers to the entity (lemma, gloss, Strong's). CC BY 4.0."""
    if not macula.available():
        raise HTTPException(503, "macula-spine.db not loaded")
    return macula.coref(book, chapter, verse, idx)


@app.get("/frame/{book}/{chapter}/{verse}/word/{idx}")
def get_frame(book: str, chapter: int, verse: int, idx: int) -> dict:
    """Semantic frame of the verb at this reference — PropBank roles (A0 agent, A1
    patient, …) resolved to their argument tokens. E.g. GEN 1:1 בָּרָא → A0 God,
    A1 heavens + earth. CC BY 4.0."""
    if not macula.available():
        raise HTTPException(503, "macula-spine.db not loaded")
    result = macula.frame(book, chapter, verse, idx)
    if not result.get("verb"):
        raise HTTPException(404, f"no verb frame at {book.upper()} {chapter}:{verse} word {idx}")
    return result


@app.get("/participants/{book}/{chapter}/{verse}")
def get_participants(book: str, chapter: int, verse: int) -> dict:
    """Participant chain of a verse — every referring word and the entity it points
    to (MACULA participant/referent links). CC BY 4.0."""
    if not macula.available():
        raise HTTPException(503, "macula-spine.db not loaded")
    return macula.participants(book, chapter, verse)


@app.get("/speakers")
def get_speakers() -> dict:
    """All quotation speakers with range counts + divine (red-letter) flag."""
    return data.speakers_list()


@app.get("/speaker/{name}")
def get_speaker(name: str, limit: int = 1000) -> dict:
    """Every verse range a speaker speaks — "what did Jesus say". `divine` marks
    red-letter speakers (God / Jesus / Holy Spirit)."""
    result = data.speaker_ranges(name, limit=min(limit, 5000))
    if not result["ranges"]:
        raise HTTPException(404, f"no quotations found for speaker '{name}'")
    return result


@app.get("/speakers/at/{book}/{chapter}/{verse}")
def get_speakers_at(book: str, chapter: int, verse: int) -> dict:
    """Who speaks at a verse — the speaker(s) whose quotation covers it."""
    return data.speakers_at(book, chapter, verse)


@app.get("/concept/{word}")
def get_concept(word: str, limit: int = 5) -> dict:
    """English concept → Strong's numbers + top occurrences for each."""
    gloss = data.gloss_lookup(word)
    if not gloss["matches"]:
        raise HTTPException(404, f"no Strong's entries found for '{word}'")
    entries = []
    for m in gloss["matches"][:limit]:
        conc = data.concordance(m["strong"], limit=10)
        entries.append({
            "strong": m["strong"], "gloss": m["gloss"],
            "translit": m["translit"], "lang": m["lang"],
            "total_occurrences": conc["count"],
            "sample": conc["occurrences"][:5],
        })
    return {"concept": word, "entries": entries}


@app.get("/morph")
def morph_search(pattern: str, book: str | None = None,
                 chapter: int | None = None, limit: int = 100) -> dict:
    """Search Hebrew words by morphology pattern (e.g. imperative, participle, verb)."""
    result = data.morph_search(pattern, book=book, chapter=chapter,
                               limit=min(limit, 500))
    if "error" in result:
        raise HTTPException(500, result["error"])
    return result


@app.get("/bridge/{strong}")
def lxx_bridge(strong: str, limit: int = 50) -> dict:
    """Hebrew→Greek bridge via LXX: how does the Septuagint translate a Hebrew word?"""
    result = data.lxx_bridge(strong, limit=min(limit, 200))
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.get("/structure/{book}/{chapter}/{verse}")
def get_structure(book: str, chapter: int, verse: int) -> dict:
    """BHSA/Nestle1904 morphological view of a verse, from bcv-corpus (private)."""
    result = corpus.passage(book, chapter, verse)
    if "error" in result:
        raise HTTPException(503 if "CORPUS_URL" in result["error"] else 404,
                            result["error"])
    return result


@app.get("/structure/{book}/{chapter}/{verse}/word/{idx}")
def get_word_structure(book: str, chapter: int, verse: int, idx: int) -> dict:
    """Clause/phrase/sentence hierarchy for one word, from bcv-corpus (private)."""
    result = corpus.context(book, chapter, verse, word_index=idx)
    if "error" in result:
        raise HTTPException(503 if "CORPUS_URL" in result["error"] else 404,
                            result["error"])
    return result


@app.get("/search")
def search(q: str, lang: str = "hbo", k: int = 10,
           enrich: bool = False,
           translate: str | None = None) -> dict:
    """Clause-level original-language semantic search (e.g. Hebrew via BEREL).

    - translate=gloss: $0 deterministic English→Hebrew via reverse gloss (Mode A)
    - translate=llm: near-$0 LLM translation to Hebrew (Mode B/C, needs API key)
    - enrich=true: include word-level breakdown per result
    """
    store = SEARCH.get(lang)
    if store is None:
        raise HTTPException(503, f"no clause vectors loaded for lang '{lang}' "
                                 f"(loaded: {list(SEARCH) or 'none'} — run search.build)")
    original_query = q
    if translate == "gloss":
        from search.translate import gloss_translate
        q = gloss_translate(q)
    elif translate == "llm":
        from search.translate import llm_translate
        q = llm_translate(q)
    from search.embedder import get_encoder
    qvec = get_encoder(lang).encode([q])[0]
    results = store.search(qvec, k=min(k, 50))
    if enrich and results:
        import re
        ref_re = re.compile(r"^(\S+)\s+(\d+):(\d+)$")
        for r in results:
            m = ref_re.match(r["ref"])
            if not m:
                continue
            v = data.verse(m.group(1), int(m.group(2)), int(m.group(3)))
            spine = v.get("spine")
            if spine and spine.get("words"):
                r["words"] = [
                    {"surface": w["surface"], "strong": w.get("strong", ""),
                     "gloss": w.get("gloss", ""), "lemma": w.get("lemma", "")}
                    for w in spine["words"] if w.get("strong")
                ]
    resp = {"query": q, "lang": lang, "clauses": store.count,
            "results": results}
    if translate and q != original_query:
        resp["original_query"] = original_query
        resp["translate"] = translate
    return resp


UPLOAD_SECRET = os.environ.get("UPLOAD_SECRET", "")


@app.post("/upload/{filename}")
async def upload_file(filename: str, request: Request,
                      secret: str = "", chunk: int = -1):
    if not UPLOAD_SECRET or secret != UPLOAD_SECRET:
        raise HTTPException(403, "forbidden")
    if filename not in ("clauses_hbo.npy", "clauses_hbo.sqlite",
                        "clauses_grc.npy", "clauses_grc.sqlite"):
        raise HTTPException(400, "invalid filename")
    from pathlib import Path
    dest = Path("/data") / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = await request.body()
    if chunk == 0:
        dest.write_bytes(body)
    elif chunk > 0:
        with open(dest, "ab") as f:
            f.write(body)
    else:
        dest.write_bytes(body)
    total = dest.stat().st_size
    return {"wrote": str(dest), "chunk": chunk, "chunk_bytes": len(body), "total_bytes": total}


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
