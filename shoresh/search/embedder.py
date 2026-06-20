"""Original-language sentence embedders for clause search.

Two modes, selected by SEARCH_EMBEDDER env var:

- **cloudflare** (default): BGE-M3 via Cloudflare Workers AI. No torch,
  ~200MB RAM, 2-3s cold start, $0. Multilingual.
- **berel** (opt-in): BEREL 3.0 for Hebrew (5.5× advantage), SPhilBERTa
  for Greek (3.7× advantage). Needs torch, ~3GB RAM, 30-60s cold start.

At build time, use --embedder to select which model embeds the clauses.
The query embedder must match the build embedder.
"""
from __future__ import annotations

import os
from functools import lru_cache

SEARCH_EMBEDDER = os.environ.get("SEARCH_EMBEDDER", "cloudflare")

NATIVE_MODELS = {
    "hbo": ("dicta-il/BEREL_3.0", "hbo"),
    "grc": ("bowphs/SPhilBerta", "grc"),
}


class PooledEncoder:
    """HF masked-LM encoder + mean pooling → normalized sentence vectors."""

    def __init__(self, model_id: str, norm_lang: str):
        import torch
        from transformers import AutoModel, AutoTokenizer
        from spine.common import to_modern_form
        self.torch = torch
        self.norm_lang = norm_lang
        self.to_modern_form = to_modern_form
        self.tok = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModel.from_pretrained(model_id)
        self.model.eval()

    def encode(self, texts: list[str]) -> list[list[float]]:
        torch = self.torch
        texts = [self.to_modern_form(t, self.norm_lang) for t in texts]
        out: list[list[float]] = []
        with torch.no_grad():
            for i in range(0, len(texts), 32):
                enc = self.tok(texts[i:i + 32], padding=True, truncation=True,
                               max_length=128, return_tensors="pt")
                hidden = self.model(**enc).last_hidden_state
                mask = enc["attention_mask"].unsqueeze(-1).float()
                pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                pooled = torch.nn.functional.normalize(pooled, dim=1)
                out.extend(pooled.tolist())
        return out


class CloudflareEncoder:
    """BGE-M3 via Cloudflare Workers AI — no torch needed."""

    def __init__(self):
        self.account_id = (os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
        self.api_token = (os.environ.get("CLOUDFLARE_API_TOKEN") or "").strip()
        if not self.account_id or not self.api_token:
            raise RuntimeError(
                "CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN required "
                "for cloudflare embedder"
            )

    def encode(self, texts: list[str]) -> list[list[float]]:
        import httpx
        resp = httpx.post(
            f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}"
            f"/ai/run/@cf/baai/bge-m3",
            headers={"Authorization": f"Bearer {self.api_token}"},
            json={"text": texts},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(f"Cloudflare API error: {data.get('errors')}")
        return data["result"]["data"]


class LocalBGEM3Encoder:
    """BGE-M3 via local sentence-transformers — for build-time batch."""

    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer("BAAI/bge-m3")

    def encode(self, texts: list[str]) -> list[list[float]]:
        vecs = self.model.encode(texts, normalize_embeddings=True)
        return vecs.tolist()


_encoder_cache: dict[str, object] = {}


def get_encoder(lang: str):
    embedder = os.environ.get("SEARCH_EMBEDDER", SEARCH_EMBEDDER)
    cache_key = f"{embedder}:{lang}"
    if cache_key in _encoder_cache:
        return _encoder_cache[cache_key]
    if embedder == "cloudflare":
        enc = CloudflareEncoder()
    elif embedder == "bge-m3-local":
        enc = LocalBGEM3Encoder()
    elif lang not in NATIVE_MODELS:
        raise ValueError(f"no native embedder for lang '{lang}' (have: {list(NATIVE_MODELS)})")
    else:
        model_id, norm_lang = NATIVE_MODELS[lang]
        enc = PooledEncoder(model_id, norm_lang)
    _encoder_cache[cache_key] = enc
    return enc
