-- Structured index schema (Tier 2 — SQLite + FTS5).
--
-- Three retrieval paths share one database:
--   1. passage_refs (range overlap on encoded BBCCCVVV references)
--   2. tags         (exact-string lookup; replaces Aquifer's ACAI entity index)
--   3. chunks_fts   (FTS5 substring/keyword search with porter stemming)
--
-- Bodies live in `chunks` (separately addressable so an embedding pipeline
-- can later JOIN chunks ↔ vector_store on chunks.id without re-chunking).
--
-- Doc-level filter columns (resource_code, language, etc.) live in
-- documents.metadata (JSON) and become indexable scalar filters via
-- generated columns once the metadata schema stabilizes.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS documents (
  id           TEXT PRIMARY KEY,
  source_path  TEXT NOT NULL,
  source_sha   TEXT,
  title        TEXT NOT NULL,
  metadata     TEXT NOT NULL DEFAULT '{}',  -- JSON blob
  indexed_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_source_path ON documents(source_path);

-- FTS5 over document titles. Used by `title_search` retriever for entity
-- lookups ("Who was Boaz?", "What is godliness?") where title-match is far
-- more reliable than body-match (titles are short and term-focused; bodies
-- saturate with noisy literal mentions of the entity name).
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
  title,
  content='documents',
  content_rowid='rowid',
  tokenize='porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
  INSERT INTO documents_fts(rowid, title) VALUES (new.rowid, new.title);
END;
CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
  INSERT INTO documents_fts(documents_fts, rowid, title) VALUES('delete', old.rowid, old.title);
END;
CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
  INSERT INTO documents_fts(documents_fts, rowid, title) VALUES('delete', old.rowid, old.title);
  INSERT INTO documents_fts(rowid, title) VALUES (new.rowid, new.title);
END;

CREATE TABLE IF NOT EXISTS chunks (
  id           TEXT PRIMARY KEY,
  doc_id       TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index  INTEGER NOT NULL,
  body         TEXT NOT NULL,
  UNIQUE(doc_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);

-- FTS5 virtual table over chunk bodies. Porter stemming fixes the
-- "justification ≠ justified" failure mode that Aquifer's substring search has.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  body,
  content='chunks',
  content_rowid='rowid',
  tokenize='porter unicode61 remove_diacritics 2'
);

-- Triggers keep FTS5 in sync with chunks. NOTE: this populates chunks_fts
-- for EVERY chunk regardless of kind. v3 expansion content (lexicons,
-- morphology, …) is routed *out* of chunks_fts and *into* per-kind FTS
-- tables (below) at the end of `indexer.build`. The reason: BM25 corpus
-- stats are computed per FTS table, so isolating v3 content prevents the
-- larger expansion corpus from re-ranking v2 retrieval results.
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, body) VALUES (new.rowid, new.body);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, body) VALUES('delete', old.rowid, old.body);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, body) VALUES('delete', old.rowid, old.body);
  INSERT INTO chunks_fts(rowid, body) VALUES (new.rowid, new.body);
END;

-- Per-kind FTS5 tables for v3 expansion content. Each carries only chunks
-- of one kind so its BM25 stats reflect that corpus alone, and so each
-- can pick a tokenizer that fits its content (e.g. polytonic Greek for
-- lexicons in the future). All use `content='chunks'` so chunk bodies
-- aren't duplicated. Population happens explicitly in indexer/build.py
-- (see V3_KIND_TO_FTS) after tags are written, since routing depends on
-- tag membership which a trigger can't see at chunks-INSERT time.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts_lexicon USING fts5(
  body,
  content='chunks',
  content_rowid='rowid',
  tokenize='porter unicode61 remove_diacritics 2'
);

-- Per-verse word-by-word parse (Strong's + lemma + morph code) from
-- STEPBible TAGNT/TAHOT. Tokenizer is unicode61 without porter — Greek
-- and Hebrew don't benefit from English stemming, and queries against
-- this table are typically Strong's / lemma / morph-code lookups
-- (which the tag-search retriever handles), with FTS as a fallback for
-- transliteration-keyword searches.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts_morphology USING fts5(
  body,
  content='chunks',
  content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);

-- BSB English Bible (full-Bible translation alongside Door43 ULT/UST).
-- Isolated FTS so BSB's 31k verses don't shift BM25 stats across the
-- existing Door43 ULT/UST/TN/TQ corpus.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts_bible USING fts5(
  body,
  content='chunks',
  content_rowid='rowid',
  tokenize='porter unicode61 remove_diacritics 2'
);

-- Aquifer study breadth (study notes, dictionaries, key terms) in its own FTS,
-- isolated by RESOURCE (resource:aquifer) rather than kind — Aquifer overlaps
-- Door43 kinds (translator-note/term/question), and at multilingual scale its
-- ~84k docs would otherwise shift BM25 stats across the whole corpus and bury
-- the primary Door43 notes. Retrieved via aquifer_search with a modest weight.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts_aquifer USING fts5(
  body,
  content='chunks',
  content_rowid='rowid',
  tokenize='porter unicode61 remove_diacritics 2'
);

-- BSB section headings ("The Creation", "The First Day", etc). Short
-- pericope titles, retrievable independently by stage-3 navigation tools.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts_section_heading USING fts5(
  body,
  content='chunks',
  content_rowid='rowid',
  tokenize='porter unicode61 remove_diacritics 2'
);

-- BibleProject video-transcript chunks. Each source PDF is chunked three
-- ways (by timestamp / by Bible-reference / by semantic window — see
-- ingest/_tools/bibleproject/step2_chunk.py) and all three populate this
-- single FTS table.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts_video_transcript USING fts5(
  body,
  content='chunks',
  content_rowid='rowid',
  tokenize='porter unicode61 remove_diacritics 2'
);

-- Passage references: encoded BBCCCVVV integers (e.g. Gen 1:1 = 1001001,
-- Romans 3:24 = 45003024). Range overlap = (a.start <= b.end AND a.end >= b.start).
CREATE TABLE IF NOT EXISTS passage_refs (
  doc_id          TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  start_bbcccvvv  INTEGER NOT NULL,
  end_bbcccvvv    INTEGER NOT NULL,
  PRIMARY KEY (doc_id, start_bbcccvvv, end_bbcccvvv)
);
CREATE INDEX IF NOT EXISTS idx_passage_start_end ON passage_refs(start_bbcccvvv, end_bbcccvvv);

CREATE TABLE IF NOT EXISTS tags (
  doc_id  TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  tag     TEXT NOT NULL,
  PRIMARY KEY (doc_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);

-- Free-form key/value: schema_version, source_root, source_repo_sha,
-- embedding_model_at_build (pinned for downstream vector reproducibility).
CREATE TABLE IF NOT EXISTS meta (
  key    TEXT PRIMARY KEY,
  value  TEXT NOT NULL
);

-- ── Entity graph (planned-expansion stage 1; see docs/expansion-plan.md) ──
--
-- Genealogy / events / places are *graph*, not text. A separate set of
-- tables sits beside `chunks` so traversal queries ("ancestors of David",
-- "people in Bethlehem") stay fast and don't fight the chunk-and-tag
-- shape. Entities cite as `entity:<id>` provenance ids; relations as
-- `relation:<source>:<rel>:<target>`. See indexer/citations.py for
-- provenance-id formatting.
--
-- The tables are empty until ingest writes into them (stage 2). Existing
-- chunks-only deployments continue working unchanged.
CREATE TABLE IF NOT EXISTS entities (
  id        TEXT PRIMARY KEY,             -- 'person:boaz', 'place:bethlehem', 'event:exodus'
  type      TEXT NOT NULL,                -- 'person' | 'place' | 'event' | 'deity'
  name      TEXT NOT NULL,
  metadata  TEXT NOT NULL DEFAULT '{}'    -- JSON: alternate names, dates, source provenance
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);

CREATE TABLE IF NOT EXISTS entity_relations (
  source_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  target_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  relation   TEXT NOT NULL,               -- 'parent-of' | 'spouse-of' | 'occurred-at' | …
  metadata   TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (source_id, target_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_entity_relations_target ON entity_relations(target_id, relation);
CREATE INDEX IF NOT EXISTS idx_entity_relations_relation ON entity_relations(relation);

CREATE TABLE IF NOT EXISTS entity_passages (
  entity_id       TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  start_bbcccvvv  INTEGER NOT NULL,
  end_bbcccvvv    INTEGER NOT NULL,
  PRIMARY KEY (entity_id, start_bbcccvvv, end_bbcccvvv)
);
CREATE INDEX IF NOT EXISTS idx_entity_passages_range ON entity_passages(start_bbcccvvv, end_bbcccvvv);

-- ── Topical indexes (planned-expansion stage 2) ──
--
-- Verses grouped by theological topic (Nave's Topical Bible from CCEL,
-- and similar). Mirrors the entities + entity_passages shape — topic
-- ids cite as `topic:<id>` provenance ids; topic_passages is the
-- many-to-many between topic and Bible passage range.
CREATE TABLE IF NOT EXISTS topics (
  id        TEXT PRIMARY KEY,             -- 'creation', 'faith', 'covenant'
  name      TEXT NOT NULL,                -- 'Creation', 'Faith', 'Covenant'
  source    TEXT NOT NULL,                -- 'naves' | 'torrey' | …
  metadata  TEXT NOT NULL DEFAULT '{}'    -- JSON: aliases, parent_topic, sub_topics
);
CREATE INDEX IF NOT EXISTS idx_topics_source ON topics(source);
CREATE INDEX IF NOT EXISTS idx_topics_name ON topics(name);

CREATE TABLE IF NOT EXISTS topic_passages (
  topic_id        TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  start_bbcccvvv  INTEGER NOT NULL,
  end_bbcccvvv    INTEGER NOT NULL,
  PRIMARY KEY (topic_id, start_bbcccvvv, end_bbcccvvv)
);
CREATE INDEX IF NOT EXISTS idx_topic_passages_range ON topic_passages(start_bbcccvvv, end_bbcccvvv);

-- ── English concordance (planned-expansion stage 2) ──
--
-- Precomputed word → verse-list lookup over the BSB English Bible.
-- Why precomputed: FTS5 over chunks_fts_bible already supports keyword
-- queries with BM25 ranking, but for exhaustive enumerations ("every
-- occurrence of `righteousness`") we want a flat unranked list with
-- no stemming surprises. Stopwords are filtered at build time.
CREATE TABLE IF NOT EXISTS english_concordance (
  word_normalized  TEXT NOT NULL,        -- lowercased, punctuation-stripped
  bbcccvvv         INTEGER NOT NULL,
  PRIMARY KEY (word_normalized, bbcccvvv)
);
CREATE INDEX IF NOT EXISTS idx_english_concordance_word ON english_concordance(word_normalized);

-- ── Cross-references (planned-expansion stage 2) ──
--
-- Verse-to-verse links from curated cross-reference databases. Source
-- attribution preserved so different sources (TSK, OpenBible, BSB
-- parallel passages) can coexist and be queried together or
-- independently. Ranges are supported on the target side (TSK's
-- "see also Romans 8:28-30" → start=45008028, end=45008030).
CREATE TABLE IF NOT EXISTS cross_references (
  source_bbcccvvv         INTEGER NOT NULL,
  target_start_bbcccvvv   INTEGER NOT NULL,
  target_end_bbcccvvv     INTEGER NOT NULL,
  source_attribution      TEXT NOT NULL,   -- 'tsk' | 'bsb-parallel' | 'openbible' | …
  rank                    INTEGER,         -- order from upstream (lower = stronger link)
  PRIMARY KEY (source_bbcccvvv, target_start_bbcccvvv, target_end_bbcccvvv, source_attribution)
);
CREATE INDEX IF NOT EXISTS idx_xref_source ON cross_references(source_bbcccvvv);
CREATE INDEX IF NOT EXISTS idx_xref_target_range ON cross_references(target_start_bbcccvvv, target_end_bbcccvvv);
