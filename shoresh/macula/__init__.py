"""MACULA per-token semantic layer (frames / coreference / roles).

Additive store alongside spine.db — built into `macula-spine.db` by `macula.parse`
from the CC-BY layers of Clear.Bible's MACULA (frames, subjref, participantref,
referent, role/class). The UBS MARBLE domain/sense columns are NOT ingested here:
they are "used with permission," outside MACULA's CC-BY grant (see
internal-docs/roadmap.md), so this DB — and the endpoints
on it — stay cleanly CC BY 4.0.
"""
