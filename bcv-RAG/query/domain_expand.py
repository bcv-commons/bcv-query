"""Strategy 4: semantic-domain expansion (S2 wiring).

Given the query's Strong's tags, add a FEW highly-related co-domain lexemes from
the shared **SDBG (Louw-Nida)** axis of `resources/semantic_domains/{grc,hbo}.tsv`.
That axis spans Greek (native) AND Hebrew (bridged via the LXX), so a query
concept broadens cross-language (e.g. "love" → G0026 → also G0025, and Hebrew
H0157/H2617 that the LXX renders into the Love/Affection domain).

Tightly gated to avoid tag noise (same restraint as concept_expand):
  • only expand from a query Strong's whose PRIMARY sdbg domain share ≥ 0.5
    (a confident concept word, not an incidental membership);
  • skip broad/grammatical domains (Relations/Discourse/Names) and any domain
    with > MAX_DOMAIN_MEMBERS lexemes (avoids generic-domain explosions);
  • co-members must have share ≥ 0.5 in that domain; ranked by keyness;
  • hard cap MAX_PER per query word, MAX_TOTAL overall.

Disable with DOMAIN_EXPAND=0.
"""
from __future__ import annotations

import math
import os
from collections import defaultdict

from resource_paths import resource_path
from query.concept_expand import _normalize_code, strong_keyness

# DEFAULT-OFF: measured to have only marginal retrieval impact (it surfaces TW
# concept articles already findable via title/tag, and a single RRF retriever can't
# lift them past vec/commentary). Kept opt-in (DOMAIN_EXPAND=1) for experiments and
# in case a future use surfaces — see internal-docs/macula-semantic-layer-plan.md §9.
DOMAIN_EXPAND = os.environ.get("DOMAIN_EXPAND", "0") != "0"
PRIMARY_SHARE = 0.5
# A light backstop against grammatical mega-domains only — the real noise control
# is the per-query/total caps below + the keyness ranking, so a concept domain like
# "Love, Affection, Compassion" (32 members) must NOT be excluded.
MAX_DOMAIN_MEMBERS = 80
MAX_PER = 2
MAX_TOTAL = 4
# broad / grammatical SDBG top-level domains — never expand on these
_BROAD_SDBG = {"089", "090", "091", "092", "093"}  # Relations, Case, Discourse, Referentials, Names

_DOMAINS_DIR = resource_path("semantic_domains")
_primary: dict[str, tuple[str, float]] | None = None   # strong -> (domain, share)
_members: dict[str, list[tuple[str, float, int]]] | None = None  # domain -> [(strong, share, count)]


def _rank(m: tuple[str, float, int]) -> float:
    """Co-member ranking: central AND distinctive. log(freq) lifts common,
    concept-central lexemes (agapaō) over rare keyness-only compounds (philotheos);
    keyness keeps it on-concept."""
    return math.log1p(m[2]) + strong_keyness(m[0])


def _load() -> None:
    global _primary, _members
    if _primary is not None:
        return
    _primary, _members = {}, defaultdict(list)
    for lang in ("grc", "hbo"):
        p = _DOMAINS_DIR / f"{lang}.tsv"
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as f:
            next(f, None)
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 6 or parts[1] != "sdbg":
                    continue
                strong, domain, share, count = parts[0], parts[2], float(parts[5]), int(parts[4])
                _members[domain].append((strong, share, count))
                if strong not in _primary or share > _primary[strong][1]:
                    _primary[strong] = (domain, share)


def expand_domains(tags: list[str]) -> list[str]:
    """Additional `strongs:` tags from co-domain lexemes. Empty if disabled."""
    if not DOMAIN_EXPAND:
        return []
    _load()
    if not _primary:
        return []
    existing = {t for t in tags if t.startswith("strongs:")}
    added: list[str] = []
    for t in tags:
        if not t.startswith("strongs:"):
            continue
        code = _normalize_code(t.split(":", 1)[1])
        pd = _primary.get(code)
        if not pd or pd[1] < PRIMARY_SHARE or pd[0][:3] in _BROAD_SDBG:
            continue
        members = _members.get(pd[0], [])
        if len(members) > MAX_DOMAIN_MEMBERS:
            continue
        co = sorted((m for m in members if m[0] != code and m[1] >= PRIMARY_SHARE),
                    key=lambda m: -_rank(m))
        n_this = 0
        for s, _, _ in co:
            tag = f"strongs:{s}"
            if tag in existing or tag in added:
                continue
            added.append(tag)
            n_this += 1
            if n_this >= MAX_PER or len(added) >= MAX_TOTAL:
                break
        if len(added) >= MAX_TOTAL:
            break
    return added[:MAX_TOTAL]


def query_domains(tags: list[str]) -> dict[str, list[str]]:
    """For the query's confident concept Strong's, return {sdbg_domain: [member
    Strong's]} — the data a first-class domain retriever needs (rank docs by how
    many of a domain's members they carry). Same gating as expand_domains."""
    if not DOMAIN_EXPAND:
        return {}
    _load()
    out: dict[str, list[str]] = {}
    for t in tags:
        if not t.startswith("strongs:"):
            continue
        code = _normalize_code(t.split(":", 1)[1])
        pd = _primary.get(code)
        if not pd or pd[1] < PRIMARY_SHARE or pd[0][:3] in _BROAD_SDBG or pd[0] in out:
            continue
        members = _members.get(pd[0], [])
        if len(members) > MAX_DOMAIN_MEMBERS:
            continue
        mem = [m[0] for m in members if m[1] >= PRIMARY_SHARE]
        if len(mem) >= 2:
            out[pd[0]] = mem
    return out
