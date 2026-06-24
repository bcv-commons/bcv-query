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

The /search store + model are loaded at startup (not per-request) so a
scale-to-zero cold start doesn't load the model mid-request and 502.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

import corpus
import data

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
