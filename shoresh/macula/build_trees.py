#!/usr/bin/env python3
"""Syntax trees from MACULA's lowfat XML, Hebrew (WLC) and Greek (Nestle 1904) -> trees-macula.db (NC exit, step 3).

Source: Clear-Bible/macula-hebrew (WLC/lowfat) and Clear-Bible/macula-greek (Nestle1904/lowfat), both CC BY 4.0, no BHSA or ETCBC input.
Only the tree's STRUCTURAL attributes are kept (class, role, rule, type, junction, clauseType, articular, head) plus the surface, trailer, lemma, class and
Strong's number of each word, and the verb form (`type`: qatal, wayyiqtol, ...) and language (H/A) attributes. Everything else about a token (gloss, morphology, lexeme id) is joined from lexeme-spine-macula.db / macula-spine.db by its key at read
time. The UBS MARBLE fields (domain, ln, sdbh, lexdomain, coredomain, sensenumber) and the translations (mandarin, english) are never read.

Tables
  nodes(id, corpus, kind 'sentence'|'wg', parent, ord, cls, role, rule, type, junction, clausetype, articular, head, book, chapter, verse, lo, hi)
      one row per sentence and per word group; lo..hi is the range of `seq` of the words below it.
  words(seq, corpus, key, book, chapter, verse, word, part, surface, after, class, role, lemma, strong, wtype, wlang, inserted, parent, cl, ph, sent)
      one row per <w>, in text order; `cl` is the nearest enclosing clause node (class="cl"; a word outside every clause takes the next clause of its sentence), `ph` the outermost role-bearing node below that clause
      (a word group, or the word itself) and `sent` the sentence; `sfx` is 1 on the Hebrew token a pronominal suffix token directly follows. `seq` is tree (document) order, which is not always text order (Greek
      lowfat puts a conjunction before the adverb it follows): text order is (chapter, verse, word, part). A word with no role-bearing node has ph NULL.
  meta(key, value)

  cd shoresh && .venv/bin/python3 -m macula.build_trees [--hbo DIR] [--grc DIR] [--out PATH]
The Hebrew files are read from macula/.lowfat-src/WLC/lowfat (cloned by macula.parse_lowfat_hbo) or $MACULA_HBO_LOWFAT_DIR; the Greek files from
macula/.lowfat-src-grc (downloaded on first run) or $MACULA_GRC_LOWFAT_DIR.
"""
from __future__ import annotations

import argparse
import os
import re
import gzip
import sqlite3
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "trees-macula.db"
HBO_DIR = HERE / ".lowfat-src" / "WLC" / "lowfat"
GRC_RAW = "https://raw.githubusercontent.com/Clear-Bible/macula-greek/main/Nestle1904/lowfat/"
GRC_DIR = HERE / ".lowfat-src-grc"                   # gitignored scratch download
GRC_FILES = ("01-matthew 02-mark 03-luke 04-john 05-acts 06-romans 07-1corinthians 08-2corinthians 09-galatians 10-ephesians 11-philippians "
             "12-colossians 13-1thessalonians 14-2thessalonians 15-1timothy 16-2timothy 17-titus 18-philemon 19-hebrews 20-james 21-1peter "
             "22-2peter 23-1john 24-2john 25-3john 26-jude 27-revelation").split()
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_REF = re.compile(r"^(\w+)\s+(\d+):(\d+)!(\d+)")

SCHEMA = """
CREATE TABLE nodes(id INTEGER PRIMARY KEY, corpus TEXT NOT NULL, kind TEXT NOT NULL, parent INTEGER, ord INTEGER,
  cls TEXT, role TEXT, rule TEXT, type TEXT, junction TEXT, clausetype TEXT, articular TEXT, head TEXT,
  book TEXT, chapter INTEGER, verse INTEGER, lo INTEGER, hi INTEGER);
CREATE TABLE words(seq INTEGER PRIMARY KEY, corpus TEXT NOT NULL, key TEXT NOT NULL, book TEXT, chapter INTEGER, verse INTEGER, word INTEGER, part INTEGER,
  surface TEXT, after TEXT, class TEXT, role TEXT, lemma TEXT, strong TEXT, wtype TEXT, wlang TEXT, inserted INTEGER NOT NULL DEFAULT 0,
  parent INTEGER, cl INTEGER, ph INTEGER, sent INTEGER, sfx INTEGER, lexeme TEXT, strong_n INTEGER, stem TEXT, tense TEXT, voice TEXT);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
"""
INDEXES = """
CREATE INDEX words_verse ON words(corpus, book, chapter, verse, seq);
CREATE UNIQUE INDEX words_key ON words(corpus, key, seq);
CREATE INDEX words_cl ON words(cl);
CREATE INDEX words_strong ON words(corpus, strong_n);
CREATE INDEX words_lexeme ON words(corpus, lexeme);
CREATE INDEX nodes_parent ON nodes(parent);
CREATE INDEX nodes_verse ON nodes(corpus, book, chapter, verse, kind);
"""


class Builder:
    def __init__(self, con: sqlite3.Connection, corpus: str):
        self.con, self.corpus = con, corpus
        self.next_node = con.execute("SELECT COALESCE(MAX(id), 0) FROM nodes").fetchone()[0] + 1
        self.seq = con.execute("SELECT COALESCE(MAX(seq), 0) FROM words").fetchone()[0]
        self.words: list[tuple] = []
        self.nodes: list[list] = []
        self.first_node = self.next_node                  # nodes of the current chapter are appended in id order

    def node(self, el: ET.Element, kind: str, parent: int | None, ord_: int) -> int:
        nid = self.next_node
        self.next_node += 1
        self.nodes.append([nid, self.corpus, kind, parent, ord_, el.get("class"), el.get("role"), el.get("rule"), el.get("type"), el.get("junction"),
                           el.get("clauseType") or el.get("clausetype"), el.get("articular"), el.get("head"), None, None, None, None, None])
        return nid

    def walk(self, el: ET.Element, parent: int, sent: int, cl: int | None, ph: int | None, seen_ph: bool) -> tuple[int | None, int | None]:
        """Returns (lo, hi) seq of the words below `el`."""
        lo = hi = None
        ordinal = 0
        for ch in el:
            if ch.tag in ("p", "milestone"):
                continue
            ordinal += 1
            if ch.tag == "w":
                ref = _REF.match(ch.get("ref", ""))
                xml_id = ch.get(_XML_ID, "")
                digits = re.sub(r"\D", "", xml_id)
                if not ref or not digits:
                    continue
                self.seq += 1
                role = ch.get("role")
                # a role-bearing word with no phrase node above it (directly under the clause) is its own phrase: ph stays NULL and role is set
                inserted = 1 if (xml_id[-1:].isdigit() is False or not (ch.text or "").strip()) else 0
                part = int(digits[-1]) if self.corpus == "hbo" else 0
                strong = ch.get("strongnumberx") if self.corpus == "hbo" else ch.get("strong")
                self.words.append((self.seq, self.corpus, digits, ref.group(1), int(ref.group(2)), int(ref.group(3)), int(ref.group(4)), part,
                                   (ch.text or "").strip(), ch.get("after") or "", ch.get("class"), role, ch.get("lemma"), strong, ch.get("type"), ch.get("lang"), inserted,
                                   parent, cl, ph, sent))
                lo = self.seq if lo is None else lo
                hi = self.seq
            else:                                             # wg, or the rare <c> coordination wrapper: a group
                nid = self.node(ch, "wg", parent, ordinal)
                is_cl = ch.get("class") == "cl"
                c2 = nid if is_cl else cl
                p2 = None if is_cl else ph
                if not is_cl and ph is None and cl is not None and ch.get("role"):
                    p2 = nid
                a, b = self.walk(ch, nid, sent, c2, p2, False)
                self._set_range(nid, a, b)
                if a is not None:
                    lo = a if lo is None else min(lo, a)
                    hi = b if hi is None else max(hi, b)
        return lo, hi

    def _set_range(self, nid: int, lo, hi) -> None:
        n = self.nodes[nid - self.first_node]
        n[16], n[17] = lo, hi

    def chapter(self, path: Path) -> None:
        root = ET.parse(path).getroot()
        for sent_el in root.iter("sentence"):
            sid = self.node(sent_el, "sentence", None, 0)
            lo, hi = self.walk(sent_el, sid, sid, None, None, False)
            self._set_range(sid, lo, hi)
        self.flush()

    def flush(self) -> None:
        self.con.executemany("INSERT INTO words(seq, corpus, key, book, chapter, verse, word, part, surface, after, class, role, lemma, strong, wtype, wlang, inserted, parent, cl, ph, sent) VALUES (" + ",".join("?" * 21) + ")", self.words)
        self.con.executemany("INSERT INTO nodes VALUES (" + ",".join("?" * 18) + ")", self.nodes)
        self.words, self.nodes = [], []
        self.first_node = self.next_node


def hbo_files(d: Path) -> list[Path]:
    return sorted(p for p in d.glob("*.xml") if p.name[:2].isdigit())


def grc_files(d: Path) -> list[Path]:
    """The 27 Greek lowfat files; missing ones are downloaded gzip-compressed (the XML shrinks ten-fold on the wire; git and plain downloads crawl)."""
    d.mkdir(parents=True, exist_ok=True)
    for name in GRC_FILES:
        p = d / f"{name}.xml"
        if p.exists() and p.stat().st_size > 1000:
            continue
        print(f"  fetching {name}.xml", file=sys.stderr)
        req = urllib.request.Request(GRC_RAW + f"{name}.xml", headers={"Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        p.write_bytes(raw)
    return [d / f"{name}.xml" for name in GRC_FILES]


def finish(con: sqlite3.Connection, spine: Path | None = None) -> None:
    """Fill book/chapter/verse of every node from its first word; copy lexeme, Strong's number, stem, tense and voice of each token from the lexeme spine
    (so searches and the /words feed are indexed lookups; for Greek `lexeme` is the lemma, as the engine's `lex` always was); flag Hebrew tokens a pronominal suffix follows; build the indexes."""
    con.execute("""UPDATE nodes SET book=(SELECT book FROM words WHERE seq=nodes.lo), chapter=(SELECT chapter FROM words WHERE seq=nodes.lo),
                   verse=(SELECT verse FROM words WHERE seq=nodes.lo) WHERE lo IS NOT NULL""")
    if spine is not None and Path(spine).exists():
        con.execute("ATTACH DATABASE ? AS sp", (f"file:{spine}?mode=ro",))
        con.execute("CREATE TEMP TABLE sk AS SELECT key, lexeme, strong, stem, tense, voice FROM sp.spine_words")
        con.execute("CREATE INDEX sk_key ON sk(key)")
        con.execute("""UPDATE words SET lexeme=(SELECT lexeme FROM sk WHERE sk.key=words.key), strong_n=(SELECT strong FROM sk WHERE sk.key=words.key),
                       stem=(SELECT NULLIF(stem,'') FROM sk WHERE sk.key=words.key), tense=(SELECT NULLIF(tense,'') FROM sk WHERE sk.key=words.key),
                       voice=(SELECT NULLIF(voice,'') FROM sk WHERE sk.key=words.key)""")
        con.execute("UPDATE words SET lexeme=lemma, strong_n=CAST(strong AS INTEGER) WHERE corpus='grc'")
        con.execute("DROP TABLE sk")
        con.commit()
        con.execute("DETACH DATABASE sp")
    else:
        print("  lexeme spine not found: lexeme/strong_n columns left empty (searches and /words need them)", file=sys.stderr)
    con.executescript(INDEXES)
    # a word outside every clause (a leading conjunction that sits above the clause in the tree) belongs to the next clause of its sentence in text order, else the last one
    con.execute("CREATE INDEX tmp_sent ON words(sent, verse, word, part)")
    con.execute("""UPDATE words SET cl = COALESCE(
        (SELECT y.cl FROM words y WHERE y.sent=words.sent AND y.cl IS NOT NULL AND (y.verse*100000+y.word*100+y.part) > (words.verse*100000+words.word*100+words.part)
         ORDER BY y.verse, y.word, y.part LIMIT 1),
        (SELECT y.cl FROM words y WHERE y.sent=words.sent AND y.cl IS NOT NULL ORDER BY y.verse DESC, y.word DESC, y.part DESC LIMIT 1))
        WHERE cl IS NULL AND sent IS NOT NULL""")
    con.execute("DROP INDEX tmp_sent")
    con.execute("CREATE INDEX tmp_word_part ON words(corpus, book, chapter, verse, word, part)")
    con.execute("""UPDATE words SET sfx = EXISTS(SELECT 1 FROM words x WHERE x.corpus=words.corpus AND x.book=words.book AND x.chapter=words.chapter
                   AND x.verse=words.verse AND x.word=words.word AND x.part=words.part+1 AND x.class='pron' AND x.wtype='pronominal') WHERE corpus='hbo'""")
    con.execute("DROP INDEX tmp_word_part")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hbo", type=Path, default=Path(os.environ.get("MACULA_HBO_LOWFAT_DIR", HBO_DIR)))
    ap.add_argument("--grc", type=Path, default=Path(os.environ.get("MACULA_GRC_LOWFAT_DIR", GRC_DIR)))
    ap.add_argument("--out", type=Path, default=DB_PATH)
    ap.add_argument("--spine", type=Path, default=Path(os.environ.get("LEXEME_SPINE_DB", HERE / "lexeme-spine-macula.db")))
    ap.add_argument("--only", choices=("hbo", "grc"), help="build one corpus only (for testing)")
    a = ap.parse_args()
    if not a.hbo.is_dir() and a.only != "grc":
        print(f"Hebrew lowfat not found at {a.hbo}; run `python -m macula.parse_lowfat_hbo` once or set MACULA_HBO_LOWFAT_DIR", file=sys.stderr)
        return 1
    if a.out.exists():
        a.out.unlink()
    con = sqlite3.connect(a.out)
    con.executescript(SCHEMA)
    t0 = time.time()
    for corpus in ("hbo", "grc"):
        if a.only and a.only != corpus:
            continue
        files = hbo_files(a.hbo) if corpus == "hbo" else grc_files(a.grc)
        b = Builder(con, corpus)
        for i, p in enumerate(files, 1):
            b.chapter(p)
            if i % 200 == 0:
                print(f"  {corpus} {i}/{len(files)}", file=sys.stderr)
        con.commit()
        print(f"{corpus}: {len(files)} files, {b.seq} words", file=sys.stderr)
    finish(con, a.spine)
    con.executemany("INSERT INTO meta VALUES (?,?)", [
        ("built", time.strftime("%Y-%m-%d")), ("source_hbo", "Clear-Bible/macula-hebrew WLC/lowfat (CC BY 4.0)"),
        ("source_grc", "Clear-Bible/macula-greek Nestle1904/lowfat (CC BY 4.0)"),
        ("note", "structural attributes only; UBS MARBLE fields and translations are never read")])
    con.commit()
    for t in ("nodes", "words"):
        print(t, con.execute(f"SELECT corpus, COUNT(*) FROM {t} GROUP BY corpus").fetchall(), file=sys.stderr)
    con.execute("VACUUM")
    con.close()
    print(f"wrote {a.out} ({a.out.stat().st_size // 1_000_000} MB) in {time.time() - t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
