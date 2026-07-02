"""FastAPI app. Mounts REST routes under /api and MCP at /mcp."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from indexer.env import load_env
from server.cors import allowed_origins
from server.ratelimit import limiter
from server.routes import ask as ask_route
from server.routes import branched as branched_route
from server.routes import chunks as chunks_route
from server.routes import concordance as concordance_route
from server.routes import cross_references as xref_route
from server.routes import entities as entities_route
from server.routes import health as health_route
from server.routes import search as search_route
from server.routes import topics as topics_route
from server.routes import trees as trees_route
from server.routes import study as study_route
from server.mcp import server as mcp_server


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_env()
    # Eagerly open the shared DB connection and warm the lexicon strongs cache
    # so the first user request doesn't pay the 1-2s startup cost.
    from server.deps import get_shared_db
    from query.retrieve import _lexicon_strongs_map
    db = get_shared_db()
    _lexicon_strongs_map(db)
    # Run the MCP Streamable HTTP session manager for the app's lifetime.
    async with mcp_server.session_lifespan():
        yield


app = FastAPI(title="bcv-query API", version="2.0.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    allow_credentials=False,
)

# Access gate (key on gated paths) + rate limiting — pure ASGI so it doesn't buffer the
# streaming /mcp mount. Outermost (added last) → runs before routing.
from server.gate import Gate  # noqa: E402
app.add_middleware(Gate)

# REST surface
app.include_router(health_route.router, prefix="/api")
app.include_router(chunks_route.router, prefix="/api")
app.include_router(search_route.router, prefix="/api")
app.include_router(ask_route.router, prefix="/api")
app.include_router(branched_route.router, prefix="/api")
app.include_router(trees_route.router, prefix="/api")
app.include_router(topics_route.router, prefix="/api")
app.include_router(entities_route.router, prefix="/api")
app.include_router(xref_route.router, prefix="/api")
app.include_router(concordance_route.router, prefix="/api")
app.include_router(study_route.router, prefix="/api")

# MCP surface — official SDK Streamable HTTP transport, mounted at /mcp (gated by the
# app-level key middleware above). stdio transport: `python -m server.mcp.stdio`.
app.mount("/mcp", mcp_server.handle_streamable_http)


@app.get("/")
def root() -> dict:
    return {
        "name": "bcv-query",
        "version": "2.0.0",
        "endpoints": {
            "rest": [
                "/api/health",
                "/api/search",
                "/api/ask",
                "/api/study",
                "/api/chunk/{id}",
                "/api/trees", "/api/tree/{name}",
                "/api/topics", "/api/topic/{id}",
                "/api/entities", "/api/entity/{id}",
                "/api/cross-references/{bbcccvvv}",
                "/api/concordance/{word}",
            ],
            "mcp": "/mcp",
        },
        "docs": {"openapi": "/docs", "redoc": "/redoc"},
    }
