#!/usr/bin/env python3
"""Embedding pipeline.

  python3 -m indexer.embed                # embed every chunk that hasn't been embedded yet
  python3 -m indexer.embed --reset-vec    # drop chunks_vec then re-embed everything

Used at *both* index-build time (this CLI) and query time
(`embed_texts([question])` in `query/ask.py` and `/api/search`,`/api/ask`).

Providers
---------
Provider is auto-detected from `BTMCP_EMBEDDING_MODEL` (override via
`BTMCP_EMBEDDING_PROVIDER`):

  * `bge-m3`            → Cloudflare Workers AI (query) / local HuggingFace (ingest)
  * `text-embedding-*`  → OpenAI
  * `voyage-*`          → Voyage AI

BGE-M3 is the recommended default: $0 query-time via Cloudflare free tier,
multilingual (handles Hebrew/Greek/French/Spanish). Local batch for ingest.

Configuration env vars (all optional, sane defaults):

  BTMCP_EMBEDDING_MODEL       default: bge-m3
  BTMCP_EMBEDDING_DIM         default: per-model (see _DEFAULT_DIMS below)
  BTMCP_EMBEDDING_BATCH_SIZE  default: 100
  BTMCP_EMBEDDING_PROVIDER    optional: explicit override
  CLOUDFLARE_ACCOUNT_ID       required for bge-m3 query-time embedding
  CLOUDFLARE_API_TOKEN         required for bge-m3 query-time embedding

Switching models / providers requires re-embedding (`--reset-vec`); the
schema check enforces this so the index never carries vectors from
mixed providers.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, Literal

# Per-model default dimension. Override via BTMCP_EMBEDDING_DIM.
_DEFAULT_DIMS: dict[str, int] = {
    # BGE-M3 (Cloudflare + local)
    "bge-m3": 1024,
    # OpenAI
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    # Voyage AI
    "voyage-3-large": 1024,
    "voyage-3-lite": 512,
    "voyage-3":      1024,
    "voyage-2":      1024,
}

EMBEDDING_MODEL = os.environ.get("BTMCP_EMBEDDING_MODEL", "bge-m3")
EMBEDDING_DIM = int(
    os.environ.get("BTMCP_EMBEDDING_DIM")
    or _DEFAULT_DIMS.get(EMBEDDING_MODEL, 1536)
)
EMBEDDING_BATCH = int(os.environ.get("BTMCP_EMBEDDING_BATCH_SIZE", "100"))

DEFAULT_DB = Path(__file__).resolve().parent / "index.db"

InputType = Literal["document", "query"]


# ---------- provider detection ----------

def _detect_provider(model: str) -> str:
    explicit = (os.environ.get("BTMCP_EMBEDDING_PROVIDER") or "").strip().lower()
    if explicit:
        return explicit
    if model == "bge-m3":
        return "cloudflare"
    if model.startswith("voyage"):
        return "voyage"
    if model.startswith("text-embedding") or model.startswith("ada-"):
        return "openai"
    raise RuntimeError(
        f"cannot detect provider for embedding model {model!r}; "
        f"set BTMCP_EMBEDDING_PROVIDER to 'cloudflare', 'openai', or 'voyage'"
    )


PROVIDER = _detect_provider(EMBEDDING_MODEL)


# ---------- OpenAI provider ----------

def _openai_client():
    from openai import OpenAI

    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY required for OpenAI embeddings")
    try:
        key.encode("ascii")
    except UnicodeEncodeError as e:
        raise RuntimeError(
            f"OPENAI_API_KEY contains non-ASCII char {key[e.start:e.end]!r} at position {e.start}; "
            f"re-copy from a plain-text source"
        ) from None
    return OpenAI(api_key=key)


def _embed_openai(texts: list[str]) -> list[list[float]]:
    resp = _openai_client().embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [e.embedding for e in resp.data]


# ---------- Voyage AI provider ----------

def _voyage_client():
    try:
        import voyageai  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "voyageai not installed; pip install voyageai or remove BTMCP_EMBEDDING_PROVIDER=voyage"
        ) from e
    key = (os.environ.get("VOYAGE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("VOYAGE_API_KEY required for Voyage embeddings")
    try:
        key.encode("ascii")
    except UnicodeEncodeError as e:
        raise RuntimeError(
            f"VOYAGE_API_KEY contains non-ASCII char {key[e.start:e.end]!r} at position {e.start}; "
            f"re-copy from a plain-text source"
        ) from None
    return voyageai.Client(api_key=key)


def _embed_voyage(texts: list[str], input_type: InputType) -> list[list[float]]:
    """Voyage's `input_type` distinguishes document vs query embeddings — small
    but real recall lift on retrieval. We pass it through whenever the caller
    knows which side they're on; default 'document' for ingest paths."""
    client = _voyage_client()
    # output_dimension is optional for voyage-3-large (Matryoshka). We only
    # set it if the user picked a non-default dim.
    kwargs: dict = {"model": EMBEDDING_MODEL, "input_type": input_type}
    default_dim = _DEFAULT_DIMS.get(EMBEDDING_MODEL)
    if default_dim is not None and EMBEDDING_DIM != default_dim:
        kwargs["output_dimension"] = EMBEDDING_DIM
    result = client.embed(texts, **kwargs)
    return result.embeddings  # type: ignore[no-any-return]


# ---------- Cloudflare Workers AI provider (BGE-M3, query-time) ----------

def _embed_cloudflare(texts: list[str]) -> list[list[float]]:
    import httpx
    account_id = (os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    api_token = (os.environ.get("CLOUDFLARE_API_TOKEN") or "").strip()
    if not account_id or not api_token:
        raise RuntimeError(
            "CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN required for "
            "Cloudflare BGE-M3 embeddings"
        )
    resp = httpx.post(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/baai/bge-m3",
        headers={"Authorization": f"Bearer {api_token}"},
        json={"text": texts},
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"Cloudflare API error: {data.get('errors', data)}")
    return data["result"]["data"]


# ---------- BGE-M3 local provider (ingest-time batch) ----------

_local_model = None


def _select_device() -> str:
    """Compute device for local embedding. Override with BTMCP_EMBEDDING_DEVICE
    ('mps'/'cuda'/'cpu'); else auto-detect Apple-GPU (MPS) → CUDA → CPU."""
    explicit = (os.environ.get("BTMCP_EMBEDDING_DEVICE") or "").strip()
    if explicit:
        return explicit
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


# Memory with batching is bounded by batch_size × max_seq_length² (attention is
# quadratic). BGE-M3's default max_seq_length is 8192 — batching long texts at
# that length OOMs (which is why batch was pinned to 1). Capping the sequence
# length is the real fix: ~98% of chunks are <500 tokens, so 512 truncates only
# a long tail (FTS still covers their full text) and makes batching memory-safe.
# On Apple Silicon GPU memory is UNIFIED (shared with RAM) — the cap matters as
# much as on CPU. All three are env-overridable.
_MAX_SEQ = int(os.environ.get("BTMCP_EMBEDDING_MAX_SEQ", "512"))
_ENCODE_BATCH = int(os.environ.get("BTMCP_EMBEDDING_ENCODE_BATCH", "32"))


def _embed_bge_m3_local(texts: list[str]) -> list[list[float]]:
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer
        device = _select_device()
        _local_model = SentenceTransformer("BAAI/bge-m3", device=device)
        _local_model.max_seq_length = _MAX_SEQ
        # fp16 on GPU ~halves memory + speeds up; stored vectors are float32
        # regardless (negligible retrieval impact). Off on CPU (fp16 is slow
        # there) and via BTMCP_EMBEDDING_FP16=0.
        fp16 = device in ("mps", "cuda") and os.environ.get("BTMCP_EMBEDDING_FP16", "1") != "0"
        if fp16:
            _local_model = _local_model.half()
        print(f"  loaded BAAI/bge-m3 locally on {device} "
              f"(max_seq {_MAX_SEQ}, batch {_ENCODE_BATCH}, fp16={fp16})", file=sys.stderr)
    vecs = _local_model.encode(texts, normalize_embeddings=True,
                               batch_size=_ENCODE_BATCH, show_progress_bar=False)
    return vecs.tolist()


# ---------- public API ----------

def embed_texts(texts: list[str], *, input_type: InputType = "document") -> list[list[float]]:
    """Batch-embed a list of strings. Order-preserving.

    `input_type` is honored by Voyage (asymmetric retrieval); OpenAI ignores
    it. Pass `input_type='query'` from search/ask call sites for better
    Voyage recall once you switch providers.
    """
    if not texts:
        return []
    if PROVIDER == "cloudflare":
        return _embed_cloudflare(texts)
    if PROVIDER == "bge-m3-local":
        return _embed_bge_m3_local(texts)
    if PROVIDER == "voyage":
        return _embed_voyage(texts, input_type)
    if PROVIDER == "openai":
        return _embed_openai(texts)
    raise RuntimeError(f"unknown embedding provider: {PROVIDER!r}")


def serialize_vector(vec: list[float]) -> bytes:
    """Pack a Python float list into the bytes layout sqlite-vec expects."""
    import sqlite_vec  # type: ignore

    return sqlite_vec.serialize_float32(vec)


def ensure_vec_table(db: sqlite3.Connection) -> None:
    db.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
            chunk_id TEXT PRIMARY KEY,
            embedding FLOAT[{EMBEDDING_DIM}] distance_metric=cosine
        )
        """
    )


def _stored_model(db: sqlite3.Connection) -> str | None:
    row = db.execute("SELECT value FROM meta WHERE key = ?", ("embedding_model",)).fetchone()
    return row[0] if row else None


def embed_all_chunks(db: sqlite3.Connection, *, batch_size: int = EMBEDDING_BATCH) -> dict:
    """Embed every chunk that doesn't yet have a row in chunks_vec.

    If a different embedding model was used previously (recorded in meta),
    raise — callers should --reset-vec to switch models so the index doesn't
    end up with mixed-provenance vectors.
    """
    ensure_vec_table(db)

    prev = _stored_model(db)
    if prev is not None and prev != EMBEDDING_MODEL:
        raise RuntimeError(
            f"existing index was embedded with {prev!r}; current model is {EMBEDDING_MODEL!r}. "
            f"Run `python -m indexer.embed --reset-vec` to re-embed under the new model."
        )

    rows = db.execute(
        """
        SELECT chunks.id, chunks.body
        FROM chunks
        LEFT JOIN chunks_vec ON chunks_vec.chunk_id = chunks.id
        WHERE chunks_vec.chunk_id IS NULL
        ORDER BY chunks.id
        """
    ).fetchall()

    embedded = 0
    skipped = 0
    total = len(rows)
    for i in range(0, total, batch_size):
        batch = rows[i : i + batch_size]
        # Drop rows with empty bodies — providers reject empty inputs; their
        # absence from chunks_vec just means vector retrieval can't surface them.
        items = [(cid, body) for cid, body in batch if body and body.strip()]
        skipped += len(batch) - len(items)
        if not items:
            continue
        ids = [it[0] for it in items]
        bodies = [it[1] for it in items]
        vectors = embed_texts(bodies, input_type="document")
        params = [(cid, serialize_vector(v)) for cid, v in zip(ids, vectors)]
        db.executemany("INSERT INTO chunks_vec(chunk_id, embedding) VALUES (?, ?)", params)
        db.commit()
        embedded += len(params)
        print(f"  embedded {min(i + batch_size, total)}/{total}", file=sys.stderr)

    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", ("embedding_model", EMBEDDING_MODEL))
    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", ("embedding_dim", str(EMBEDDING_DIM)))
    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", ("embedding_provider", PROVIDER))
    db.commit()
    return {"embedded": embedded, "skipped_empty": skipped, "candidate_total": total}


def reset_vec(db: sqlite3.Connection) -> None:
    db.execute("DROP TABLE IF EXISTS chunks_vec")
    db.execute(
        "DELETE FROM meta WHERE key IN ('embedding_model', 'embedding_dim', 'embedding_provider')"
    )
    db.commit()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB, type=Path)
    ap.add_argument("--reset-vec", action="store_true", help="drop chunks_vec, then re-embed all chunks")
    ap.add_argument("--local", action="store_true",
                    help="force the local HuggingFace model (no API). Already the default "
                         "for bge-m3 ingest unless BTMCP_EMBEDDING_PROVIDER is set.")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"db not found: {args.db}\nrun ingest + indexer.build first", file=sys.stderr)
        return 2

    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from indexer.db import has_vec, open_db
    from indexer.env import load_env

    load_env()
    # Ingest defaults to the LOCAL HuggingFace model for bge-m3 (Cloudflare is
    # query-time only). An explicit BTMCP_EMBEDDING_PROVIDER wins; otherwise
    # --local or a bge-m3 model selects the local provider — so the CLI never
    # silently falls back to Cloudflare and fails on missing creds.
    global PROVIDER
    if args.local or (EMBEDDING_MODEL == "bge-m3" and not os.environ.get("BTMCP_EMBEDDING_PROVIDER")):
        PROVIDER = "bge-m3-local"

    db = open_db(args.db)
    if not has_vec(db):
        print("sqlite-vec is not loaded; cannot embed. Install with: pip install sqlite-vec", file=sys.stderr)
        return 3

    if args.reset_vec:
        reset_vec(db)

    result = embed_all_chunks(db)
    result["db"] = str(args.db)
    result["model"] = EMBEDDING_MODEL
    result["dim"] = EMBEDDING_DIM
    result["provider"] = PROVIDER
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
