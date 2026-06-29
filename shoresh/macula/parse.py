"""Build macula-spine.db from MACULA's CC-BY per-token layers (frames / coreference).

  python -m macula.parse            # fetch both TSVs (LFS) + build
  MACULA_GRC_TSV=… MACULA_HBO_TSV=… python -m macula.parse   # use local files

Ingests ONLY the CC BY 4.0 columns (frame, subjref, participantref, referent,
role/class, lemma/strong/gloss). The UBS MARBLE domain/sense columns
(lexdomain/coredomain/contextualdomain/sensenumber/domain/ln) are deliberately
skipped — they are "used with permission," outside CC-BY (plan §12).

Pointer ids: Greek token-ids carry an `n` prefix, Hebrew an `o`, and the in-cell
frame/ref pointers drop the prefix (Hebrew) or keep it (Greek). We normalize every
id to its digits (`_key`) as the join key, so resolution is prefix-agnostic and the
two corpora share one namespace without collision (Greek 11 digits / book ≥40,
Hebrew 12 digits / book ≤39).

Tables:
  macula_words(key PK, xml_id, lang, book, chapter, verse, word, lemma, strong,
               gloss, text, role, class)
  frames(verb_key, role, arg_key)              -- one row per (verb, role, argument)
  refs(src_key, tgt_key, kind)                 -- referent / subjref / participantref
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from references import BOOK_NUMBERS  # noqa: E402  (USFM code → number)

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "macula-spine.db"

# Greek TSV is a regular file (raw); the Hebrew TSV is Git-LFS (media endpoint).
GRC_URL = "https://raw.githubusercontent.com/Clear-Bible/macula-greek/main/Nestle1904/tsv/macula-greek-Nestle1904.tsv"
HBO_URL = "https://media.githubusercontent.com/media/Clear-Bible/macula-hebrew/main/WLC/tsv/macula-hebrew.tsv"

_REF = re.compile(r"^(\w+)\s+(\d+):(\d+)!(\d+)")   # "GEN 1:1!2" → GEN, 1, 1, 2


def _key(token_id: str) -> str:
    """Normalize a token-id / pointer to its digits (drop the n/o prefix)."""
    return re.sub(r"\D", "", token_id or "")


def _src(url: str, env: str) -> Path:
    p = os.environ.get(env)
    if p:
        return Path(p)
    cache = Path(tempfile.gettempdir()) / Path(url).name
    if not cache.exists():
        print(f"  downloading {url} → {cache}", file=sys.stderr)
        urllib.request.urlretrieve(url, cache)
    return cache


def _rows(path: Path):
    import csv
    with path.open(encoding="utf-8") as fh:
        yield from csv.DictReader(fh, delimiter="\t")


def _parse_ref(ref: str):
    m = _REF.match(ref or "")
    if not m:
        return None
    book, ch, vs, word = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
    if book not in BOOK_NUMBERS:
        return None
    return book, ch, vs, word


# Per-language column aliases (the two TSVs name a few fields differently).
COLS = {
    "grc": {"lemma": "lemma", "strong": "strong", "gloss": "gloss", "text": "text",
            "role": "role", "class": "class",
            "refcols": ["referent", "subjref"]},
    "hbo": {"lemma": "lemma", "strong": "strongnumberx", "gloss": "gloss", "text": "text",
            "role": "role", "class": "class",
            "refcols": ["participantref", "subjref"]},
}


def _ingest(con: sqlite3.Connection, path: Path, lang: str) -> tuple[int, int, int]:
    c = COLS[lang]
    nw = nf = nr = 0
    words, frames, refs = [], [], []
    for r in _rows(path):
        parsed = _parse_ref(r.get("ref", ""))
        if not parsed:
            continue
        book, ch, vs, word = parsed
        k = _key(r.get("xml:id", ""))
        if not k:
            continue
        words.append((k, r.get("xml:id", ""), lang, book, ch, vs, word,
                      r.get(c["lemma"], ""), r.get(c["strong"], ""), r.get(c["gloss"], ""),
                      r.get(c["text"], ""), r.get(c.get("role", ""), "") or "",
                      r.get(c.get("class", ""), "") or ""))
        nw += 1
        # frame: "A0:<id>;<id> A1:<id>" → one row per (role, arg)
        for token in (r.get("frame", "") or "").split():
            if ":" not in token:
                continue
            role, _, args = token.partition(":")
            for a in args.split(";"):
                ak = _key(a)
                if ak:
                    frames.append((k, role, ak)); nf += 1
        # coreference / subject pointers
        for kind in c["refcols"]:
            for a in (r.get(kind, "") or "").split():
                ak = _key(a)
                if ak:
                    refs.append((k, ak, kind)); nr += 1
    con.executemany("INSERT OR IGNORE INTO macula_words VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", words)
    con.executemany("INSERT INTO frames VALUES (?,?,?)", frames)
    con.executemany("INSERT INTO refs VALUES (?,?,?)", refs)
    return nw, nf, nr


def build() -> None:
    grc = _src(GRC_URL, "MACULA_GRC_TSV")
    hbo = _src(HBO_URL, "MACULA_HBO_TSV")
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
        CREATE TABLE macula_words(key TEXT PRIMARY KEY, xml_id TEXT, lang TEXT,
            book TEXT, chapter INT, verse INT, word INT,
            lemma TEXT, strong TEXT, gloss TEXT, text TEXT, role TEXT, class TEXT);
        CREATE TABLE frames(verb_key TEXT, role TEXT, arg_key TEXT);
        CREATE TABLE refs(src_key TEXT, tgt_key TEXT, kind TEXT);
    """)
    for path, lang in [(grc, "grc"), (hbo, "hbo")]:
        nw, nf, nr = _ingest(con, path, lang)
        print(f"  {lang}: {nw} tokens, {nf} frame-args, {nr} ref-pointers", file=sys.stderr)
    con.executescript("""
        CREATE INDEX ix_words_ref ON macula_words(book, chapter, verse, word);
        CREATE INDEX ix_words_strong ON macula_words(strong);
        CREATE INDEX ix_frames_verb ON frames(verb_key);
        CREATE INDEX ix_frames_arg ON frames(arg_key);
        CREATE INDEX ix_refs_src ON refs(src_key);
    """)
    con.commit()
    con.close()
    print(f"\nWrote {DB_PATH} ({DB_PATH.stat().st_size // 1024} KB)", file=sys.stderr)


if __name__ == "__main__":
    print("building macula-spine.db ...", file=sys.stderr)
    build()
    print("done.", file=sys.stderr)
