"""Synthesis reference cards — the card family.

Per-kind strategies (see internal-docs/roadmap.md): each kind is a self-contained
`CardStrategy` — its OWN confidence, build, and two projections (the gated `to_synthesis` and
the never-exclusive `to_ux`). The shared layer (`assemble` + `render_synthesis`/`render_ux`) only
routes, builds, ranks, and projects. Adding a kind = adding a strategy to STRATEGIES — never
touching the others; "completely varying strategies" is the expected shape.

Two projections, opposite economics:
  • to_synthesis → paid prose: GATED (a wrong/redundant card misdirects the model). May return
    None even when the card is built (e.g. concept on a bare word-lookup — the prose self-defines).
  • to_ux → $0 structured: never-exclusive (always shown if built), ranked by confidence, by kind.
"""
from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass


@functools.lru_cache(maxsize=1)
def _gloss_lang_map() -> dict:
    """lang code (639-1 / 639-3) → gloss CSV name, from related_langs/languages.tsv `gloss_names`."""
    import csv

    from resource_paths import resource_path
    out: dict = {}
    try:
        with open(resource_path("related_langs/languages.tsv"), encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                name = (row.get("gloss_names") or "").split(";")[0].strip()
                if name:
                    for code in (row.get("iso639_3"), row.get("iso639_1")):
                        if code:
                            out[code] = name
    except Exception:
        pass
    return out


def _gloss_lang(lang: str) -> str:
    """The gloss-language NAME for a query lang code (default English) — for shoresh `gloss_lang`."""
    from lang import canon
    mp = _gloss_lang_map()
    return mp.get((lang or "").lower()) or mp.get(canon(lang or "en")) or "English"


def _concept_line(card: dict | None) -> str | None:
    """Render shoresh's /wordstudy data into a compact CONCEPT line."""
    if not card:
        return None
    parts: list[str] = []
    head = " ".join(x for x in (card.get("strong"), card.get("translit")) if x)
    gloss = card.get("gloss")
    parts.append(f"{head} = {gloss}" if gloss else head)

    # the binyan-correct sense — the Hebrew-context sense layer (dominant sense per stem)
    senses: list[str] = []
    for entry in (card.get("lex_senses") or [])[:1]:        # primary lexeme
        for stem, ss in (entry.get("stems") or {}).items():
            if ss:
                senses.append(f"{stem or 'noun'}: {ss[0]['gloss']}")
    if senses:
        parts.append("sense — " + "; ".join(senses[:4]))

    cross = card.get("cross_language") or []
    if cross:
        parts.append("equiv: " + ", ".join(
            " ".join(x for x in (c.get("strong"), c.get("gloss")) if x) for c in cross[:2]))

    keyness = card.get("keyness") or {}
    if keyness.get("score"):
        parts.append(f"keyness {keyness['score']} (distinctively biblical)")

    domains = card.get("domains") or []
    if domains and domains[0].get("label"):
        parts.append("domain: " + domains[0]["label"])

    return "CONCEPT — " + " | ".join(p for p in parts if p)


@dataclass
class BuiltCard:
    kind: str
    confidence: float
    data: dict
    strategy: "CardStrategy"


class CardStrategy:
    """One card kind. Subclasses own confidence / build / the two projections."""
    kind = "?"

    def confidence(self, analysis, db) -> float:
        """Does this kind fire, and how prominently (0 = doesn't fire). Deterministic, $0."""
        return 0.0

    def build(self, analysis, db, query: str, lang: str) -> dict | None:
        """Assemble the card data (or None)."""
        return None

    def to_synthesis(self, data: dict, analysis) -> str | None:
        """GATED prose projection — may be None even when built."""
        return None

    def to_ux(self, data: dict, analysis) -> dict | None:
        """Never-exclusive UX projection — a by-kind headline + drill-in endpoint."""
        return None


# ── Concept / Sense ────────────────────────────────────────────────────────────────────────
# Suppressed on intents that want a DIFFERENT card (A/B-validated: the losses clustered here).
_CONCEPT_SUPPRESS_INTENTS = {"genealogy", "entity_lookup", "speaker", "methodology"}


class ConceptStrategy(CardStrategy):
    """Concept / Sense — gloss · binyan-correct sense · cross-lang equiv · keyness · domain.

    Confidence: fires on concept-bearing intents (not entity/speaker/genealogy/methodology).
    Synthesis gate: require co-domain siblings AND suppress BARE word-lookups — the prose
    self-defines the looked-up word, so the card is redundant there (A/B: anchor lookups added only
    losses). UX: always show when built — including the very bare lookup synthesis suppresses."""
    kind = "concept"
    _PROMINENCE = {"word_study": 1.0, "thematic": 0.7, "topic": 0.6}

    def confidence(self, analysis, db) -> float:
        intent = getattr(analysis, "intent", "") or ""
        if intent in _CONCEPT_SUPPRESS_INTENTS:
            return 0.0
        return self._PROMINENCE.get(intent, 0.5)

    def build(self, analysis, db, query, lang) -> dict | None:
        from server.word_study import word_study_anchor, word_study_card
        tags = getattr(analysis, "concept_tags", None) or getattr(analysis, "tags", [])
        return word_study_card(tags, query, anchor_strongs=word_study_anchor(db, analysis),
                               gloss_lang=_gloss_lang(lang))     # localize gloss + senses to query lang

    def to_synthesis(self, data, analysis) -> str | None:
        if not (data or {}).get("siblings"):              # weak fallback match = noise
            return None
        bare = bool(getattr(analysis, "word_study_terms", None)
                    or getattr(analysis, "word_study_strongs", None))
        if bare:                                          # bare lookup → prose self-defines it
            return None
        return _concept_line(data)

    def to_ux(self, data, analysis) -> dict | None:
        line = _concept_line(data)
        if not line:
            return None
        strong = (data or {}).get("strong")
        return {"kind": self.kind, "headline": line, "anchor": strong,
                "drill": f"/wordstudy/{strong}" if strong else None}


# ── Speaker ────────────────────────────────────────────────────────────────────────────────
class SpeakerStrategy(CardStrategy):
    """Speaker — who is quoted, the red-letter/divine-speech flag, how many passages, scoped to
    the topic. Its OWN strategy: unlike concept, speaker FACTS ground the prose even on a bare
    "what did X say" (who said it, whether it's divine speech) → NO bare-lookup suppression."""
    kind = "speaker"

    def confidence(self, analysis, db) -> float:
        return 1.0 if getattr(analysis, "speaker", None) else 0.0

    def build(self, analysis, db, query, lang) -> dict | None:
        from query.speakers import is_divine, speaker_passages
        name = getattr(analysis, "speaker", None)
        if not name:
            return None
        return {"name": name, "divine": is_divine(name),
                "passages": len(speaker_passages(name))}

    @staticmethod
    def _line(data: dict) -> str:
        bits = [data["name"]]
        if data.get("divine"):
            bits.append("red-letter / divine speech")
        if data.get("passages"):
            bits.append(f"{data['passages']} quoted passages — answer from their actual words")
        return "SPEAKER — " + " | ".join(bits)

    def to_synthesis(self, data, analysis) -> str | None:
        # UX-ONLY (per-kind A/B: speaker in the prose was net −14%). The card is metadata (name the
        # LLM already knows + a count + a directive), not grounding — its value is navigation, the UX
        # surface. Redesign-and-re-eval candidate: inject the speaker's ACTUAL quotations on the topic.
        return None

    def to_ux(self, data, analysis) -> dict | None:
        if not data:
            return None
        return {"kind": self.kind, "headline": self._line(data), "anchor": data["name"],
                "drill": f"/speaker/{data['name']}"}


# ── Entity ─────────────────────────────────────────────────────────────────────────────────
_REL_NOUN = {"father-of": "father", "mother-of": "mother",
             "sibling-of": "sibling", "partner-of": "partner"}
_LOOKUP_STOP = {"who", "what", "where", "when", "why", "how", "the", "is", "was", "were", "are",
                "a", "an", "did", "does"}


def _entity_facts(db, entity_query: dict, lang: str = "en") -> dict | None:
    """Resolve an entity to structured facts: who/what summary + a one-hop relation ANSWER."""
    name = (entity_query or {}).get("name", "").strip()
    if not name:
        return None
    # Prefer the RICHEST entity for a name — disambiguates homonyms (the person "Boaz" carries a
    # full article; the temple pillar "Boaz" is a thin stub).
    row = (db.execute("SELECT id,type,name,metadata FROM entities WHERE LOWER(name)=LOWER(?) "
                      "ORDER BY LENGTH(metadata) DESC, id LIMIT 1", (name,)).fetchone()
           or db.execute("SELECT id,type,name,metadata FROM entities WHERE LOWER(name) LIKE LOWER(?) "
                         "ORDER BY LENGTH(metadata) DESC, id LIMIT 1", (name + "%",)).fetchone())
    if not row:
        return None
    eid, etype, ename, meta = row
    summary = ""
    try:
        m = json.loads(meta or "{}")
        desc = (m.get("description") or m.get("tipnr_description") or "").strip()
        desc = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", desc)          # strip markdown links
        summary = re.split(r"(?<=[.!?])\s", desc)[0][:160] if desc else ""
    except Exception:
        pass
    data = {"name": ename, "type": etype, "summary": summary}
    relation = (entity_query or {}).get("relation")
    if relation:
        reverse = relation.endswith("-rev")                          # "-rev" = inbound to the match
        rel = relation[:-4] if reverse else relation
        dirs = [("source_id", "target_id")] if reverse else [("target_id", "source_id")]
        if rel in ("partner-of", "sibling-of"):                      # symmetric → try both directions
            dirs = [("target_id", "source_id"), ("source_id", "target_id")]
        names: list[str] = []
        for join_id, where_id in dirs:
            names += [r[0] for r in db.execute(
                f"SELECT e.name FROM entity_relations er JOIN entities e ON e.id=er.{join_id} "
                f"WHERE er.{where_id}=? AND er.relation=? LIMIT 8", (eid, rel)).fetchall()]
        data["relation"] = relation
        data["related"] = list(dict.fromkeys(names))[:8]
    return data


def _entity_line(data: dict) -> str:
    if data.get("relation"):
        rel = data["relation"]; reverse = rel.endswith("-rev")
        noun = _REL_NOUN.get(rel[:-4] if reverse else rel, rel)
        rels = ", ".join(data.get("related") or []) or "—"
        if reverse:                                                  # "father of David → Jesse"
            phrase = f"{noun} of {data['name']} → {rels}"
        elif noun in ("father", "mother"):                          # forward father/mother = children
            phrase = f"children of {data['name']} → {rels}"
        else:
            phrase = f"{noun}s of {data['name']} → {rels}"
        return "ENTITY — " + phrase
    line = f"{data['name']} ({data['type']})"
    if data.get("summary"):
        line += f": {data['summary']}"
    return "ENTITY — " + line


class EntityStrategy(CardStrategy):
    """Entity — who/what summary + a one-hop relation ANSWER (genealogy). Its own strategy: entity
    facts ground the prose even on a bare lookup (the relation answer IS the answer) → NO
    bare-lookup suppression. Genealogy gets name+relation from the analyzer; a plain "who is X"
    extracts the proper noun and matches it against the entities graph."""
    kind = "entity"

    def confidence(self, analysis, db) -> float:
        return 1.0 if getattr(analysis, "intent", "") in ("entity_lookup", "genealogy") else 0.0

    def build(self, analysis, db, query, lang) -> dict | None:
        eq = getattr(analysis, "entity_query", None)
        if not (eq and eq.get("name")):
            name = self._lookup_name(db, query)
            if not name:
                return None
            eq = {"name": name}
        return _entity_facts(db, eq, lang)

    @staticmethod
    def _lookup_name(db, query: str) -> str | None:
        for c in re.findall(r"\b([A-Z][a-z]+)\b", query or ""):
            if c.lower() in _LOOKUP_STOP:
                continue
            if db.execute("SELECT 1 FROM entities WHERE LOWER(name)=LOWER(?) LIMIT 1", (c,)).fetchone():
                return c
        return None

    def to_synthesis(self, data, analysis) -> str | None:
        # Synthesize ONLY the discrete relation ANSWER (genealogy: "father of David → Jesse") — a
        # grounding fact + a safety net if retrieval misses it. The who/what SUMMARY ties in the A/B
        # (the prose self-summarizes from the sources) → UX-only. (per-kind A/B: entity ≈ neutral.)
        return _entity_line(data) if (data and data.get("related")) else None

    def to_ux(self, data, analysis) -> dict | None:
        if not data:
            return None
        return {"kind": self.kind, "headline": _entity_line(data), "anchor": data["name"],
                "drill": None}


# ── Passage ────────────────────────────────────────────────────────────────────────────────
def _single_verse(analysis) -> int | None:
    """The bbcccvvv of the cited verse when the query targets exactly ONE verse, else None."""
    for s, e in (getattr(analysis, "passages", None) or []):
        if s == e:
            return s
    return None


def _passage_ref(analysis):
    """(start bbcccvvv, is_range) for a passage query — a single verse, else the range's OPENING
    verse (a representative anchor for "Romans 8"). None when there's no passage."""
    ps = getattr(analysis, "passages", None) or []
    for s, e in ps:
        if s == e:
            return s, False
    for s, e in ps:
        return s, True
    return None


_CONTENT_SP = {"subs", "nmpr", "verb", "adjv", "advb"}   # BHSA content parts of speech


def _clause_frame(syntax: dict | None) -> str | None:
    """Who-did-what from the verse's main (verbal) clause: Subj/Pred/Objc content glosses, compact."""
    clauses = (syntax or {}).get("clauses") or []
    main = next((c for c in clauses if any(p.get("function") == "Pred" for p in c.get("phrases", []))),
                None)
    if not main:
        return None
    parts = []
    for p in main["phrases"]:
        fn = p.get("function")
        if fn not in ("Subj", "Pred", "Objc"):
            continue
        g = " ".join(w["gloss"] for w in p.get("words", [])
                     if w.get("gloss") and w.get("sp") in _CONTENT_SP)
        if g:
            parts.append(f"{fn} {g}")
    return "frame: " + " · ".join(parts) if parts else None


def _norm_gloss(g: str) -> str:
    """Normalize a gloss for cross-source matching: lowercase, first sense, alpha-only, de-plural."""
    first = re.split(r"[;,]", g or "")[0]
    return re.sub(r"[^a-z]", "", first.lower()).rstrip("s")


def _role_map(syntax: dict | None) -> dict:
    """{normalized content-gloss: role} from the verse's main clause Subj/Pred/Objc phrases — lets the
    word list carry its clause role inline (one view, not a redundant separate frame)."""
    clauses = (syntax or {}).get("clauses") or []
    main = next((c for c in clauses if any(p.get("function") == "Pred" for p in c.get("phrases", []))),
                None)
    out: dict = {}
    for p in (main or {}).get("phrases", []):
        fn = p.get("function")
        if fn not in ("Subj", "Pred", "Objc"):
            continue
        for w in p.get("words", []):
            if w.get("sp") in _CONTENT_SP and w.get("gloss"):
                out.setdefault(_norm_gloss(w["gloss"]), fn)
    return out


class PassageStrategy(CardStrategy):
    """Passage — the cited verse's interlinear original words (translit = gloss). Its own strategy:
    confidence is near-DETERMINISTIC (an explicit verse ref), and the OPPOSITE gate from concept —
    synthesis almost always wants the original words behind a cited verse. Single verse only
    (a chapter/range has no one interlinear)."""
    kind = "passage"

    def confidence(self, analysis, db) -> float:
        if getattr(analysis, "intent", "") not in ("passage_specific", "passage_book"):
            return 0.0
        return 1.0 if _passage_ref(analysis) is not None else 0.0

    def build(self, analysis, db, query, lang) -> dict | None:
        from indexer.references import decode, human
        from server.original_words import verse_interlinear, verse_speaker, verse_syntax
        from query.concept_expand import strong_keyness
        ref = _passage_ref(analysis)
        if ref is None:
            return None
        bb, is_range = ref
        try:
            code, ch, v = decode(bb)
        except Exception:
            return None
        il = verse_interlinear(code, ch, v)
        if not il:
            return None
        syntax = verse_syntax(code, ch, v) if il["lang"] == "hbo" else None
        roles = _role_map(syntax)
        # ONE view: keyness-ranked content words (keyness>0 drops et/articles/particles at the source —
        # form-independent, so the sense-form "<OM>" can't leak), sense trimmed, role annotated inline.
        words = []
        for w in il["words"]:
            key = strong_keyness(w.get("strong", "")) if w.get("strong") else 0.0
            if key <= 0:
                continue
            sense = w.get("sense")
            gloss = re.split(r"[;,]", sense)[0].strip() if sense else w.get("gloss", "")
            if not gloss:
                continue
            words.append({"translit": w.get("translit") or w.get("surface"), "gloss": gloss,
                          "key": key, "sensed": bool(sense), "role": roles.get(_norm_gloss(gloss))})
        if not words:
            return None
        words.sort(key=lambda x: -x["key"])
        # UX-only extras (kept OFF the synthesis line — they restate the words): LXX parallel + frame.
        lxx = [{"translit": w.get("translit") or w.get("surface"), "gloss": w["gloss"]}
               for w in (il.get("lxx") or [])
               if w.get("gloss") and (strong_keyness(w["strong"]) if w.get("strong") else 0) > 0][:5]
        return {"ref": human(bb, bb), "lang": il["lang"], "words": words, "lxx": lxx,
                "speaker": verse_speaker(code, ch, v), "is_range": is_range,
                "frame": _clause_frame(syntax), "sensed": any(w["sensed"] for w in words)}

    @staticmethod
    def _line(data: dict) -> str:                            # one lean view: words (role-annotated) + speaker
        head = f"PASSAGE {data['ref']}" + (" (opening)" if data.get("is_range") else "")
        head += f" ({data['lang']})"
        sp = data.get("speaker")
        if sp and sp.get("name"):
            head += f" [{sp['name']}" + (", red-letter" if sp.get("divine") else "") + "]"
        parts = [f"{w['translit']}={w['gloss']}" + (f"[{w['role']}]" if w.get("role") else "")
                 for w in data["words"][:6]]
        return f"{head} — " + " · ".join(parts)

    def to_synthesis(self, data, analysis) -> str | None:
        return self._line(data) if data else None

    def to_ux(self, data, analysis) -> dict | None:
        if not data:
            return None
        code = data["ref"].replace(" ", "").replace(":", "/")
        return {"kind": self.kind, "headline": self._line(data), "anchor": data["ref"],
                "drill": f"/verse/{code}", "syntax": f"/structure/{code}/syntax",
                "lxx": data.get("lxx"), "frame": data.get("frame")}   # never-exclusive extras


# ── Cross-reference ──────────────────────────────────────────────────────────────────────────
class CrossRefStrategy(CardStrategy):
    """Cross-reference — the ranked TSK cross-refs for the cited verse (`cross_references` table).
    Fires on xref intent with a single verse. Likely navigation-leaning; the eval slice decides
    whether the ref list grounds the prose or is UX-only."""
    kind = "xref"

    def confidence(self, analysis, db) -> float:
        # xref intent only — cross-refs point AWAY from the verse, so they're a separate branch, not
        # part of the passage card's grounding (research: the passage rubric can't reward them, and the
        # redesigned sense-rich passage card stands on its own). See internal-docs/roadmap.md.
        return 1.0 if (getattr(analysis, "intent", "") == "xref"
                       and _single_verse(analysis) is not None) else 0.0

    def build(self, analysis, db, query, lang) -> dict | None:
        from indexer.references import human
        bb = _single_verse(analysis)
        if bb is None:
            return None
        rows = db.execute(
            "SELECT target_start_bbcccvvv, target_end_bbcccvvv FROM cross_references "
            "WHERE source_bbcccvvv=? ORDER BY (rank IS NULL), rank ASC, target_start_bbcccvvv ASC "
            "LIMIT 8", (bb,)).fetchall()
        refs = []
        for s, e in rows:
            try:
                refs.append(human(s, e))
            except Exception:
                pass
        if not refs:
            return None
        return {"ref": human(bb, bb), "xrefs": refs}

    @staticmethod
    def _line(data: dict) -> str:
        return f"CROSS-REFS {data['ref']} → " + ", ".join(data["xrefs"])

    def to_synthesis(self, data, analysis) -> str | None:
        return self._line(data) if data else None

    def to_ux(self, data, analysis) -> dict | None:
        if not data:
            return None
        return {"kind": self.kind, "headline": self._line(data), "anchor": data["ref"], "drill": None}


STRATEGIES: list[CardStrategy] = [ConceptStrategy(), SpeakerStrategy(), EntityStrategy(),
                                  PassageStrategy(), CrossRefStrategy()]


def assemble(analysis, db, query: str = "", lang: str = "en") -> list[BuiltCard]:
    """Route + build every kind that fires, highest-confidence first. The shared layer — strategies
    do the kind-specific work; this only routes, builds, and ranks."""
    built: list[BuiltCard] = []
    for strat in STRATEGIES:
        conf = strat.confidence(analysis, db)
        if conf <= 0:
            continue
        data = strat.build(analysis, db, query, lang)
        if data:
            built.append(BuiltCard(kind=strat.kind, confidence=conf, data=data, strategy=strat))
    built.sort(key=lambda b: -b.confidence)
    return built


def render_synthesis(built: list[BuiltCard], analysis) -> str | None:
    """The GATED synthesis projection — each kind's to_synthesis (may be None even when built)."""
    lines = [b.strategy.to_synthesis(b.data, analysis) for b in built]
    lines = [ln for ln in lines if ln]
    if not lines:
        return None
    return ("REFERENCE (original-language facts — ground the answer in these; do NOT cite them "
            "by chunk id):\n" + "\n".join(f"• {ln}" for ln in lines))


def render_ux(built: list[BuiltCard], analysis) -> list[dict]:
    """The never-exclusive UX projection — every built card as a by-kind headline, ranked by
    confidence (the prominent one leads). Part B folds these into branched retrieval."""
    return [ux for ux in (b.strategy.to_ux(b.data, analysis) for b in built) if ux]


def concept_data(built: list[BuiltCard]) -> dict | None:
    """The concept card's raw /wordstudy data (for the JSON `word_study` field)."""
    for b in built:
        if b.kind == "concept":
            return b.data
    return None
