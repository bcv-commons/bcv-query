"""Quotation depth per Hebrew word in nine English translations, the votes the speaker layer uses for nesting.

- Clear's "alignment-quotations" files (Clear-Bible/speaker-quotations, CC BY 4.0, pinned commit): for eight translations, the
  quotation depth of each MACULA word, projected from the translation's quotation marks through the word alignment (only the
  numbers, no English text). Clear's own consensus file is left out: it is made from the others.
- The BSB Translation Tables (bereanbible.com, public domain): the BSB's quotation marks on each Hebrew word, counted in English
  reading order; a paragraph that opens with the mark of the level already open restates it (English typesetting), so it opens no
  new level. Rows are matched to MACULA's tokens by Strong's number in Hebrew order, resyncing on five rows in a row.

Depth is 0 for the narrator, 1 for speech, 2 for speech inside speech, and so on. A word a translation leaves unaligned has no
vote from it. The absolute depth is a translation's convention (whether it quotes Moses' or a prophet's whole speech), so the
speaker layer compares depths within a quotation, not across.

    depths() -> {voter: {token key: depth}}, {voter: source sha256}
"""
from __future__ import annotations

import csv
import hashlib
import io
import pickle
import re
import sqlite3
import urllib.request
from pathlib import Path

SHORESH = Path(__file__).resolve().parents[1]
CACHE = SHORESH / "macula" / "data" / "speaker-layer" / "_cache"
CLEAR_COMMIT = "b09e308a3a1aafdb7d6c75baf0fe2a31d61601da"
CLEAR_URL = "https://raw.githubusercontent.com/Clear-Bible/speaker-quotations/{commit}/tsv/alignment-quotations-{t}.tsv"
CLEAR_VOTERS = ["csbe", "esv", "hcsb", "leb", "nasb77", "nasb95", "niv84", "nrsv"]
BSB_URL = "https://bereanbible.com/bsb_tables.tsv"
BSB_SHA256 = "09bbee6f9fe4fa22b5df28e8a9ffa99bf9c33435f4eb8c47c2dc221d855d35cb"
BSB_LOCAL = [SHORESH.parent.parent / "lexeme-aligner" / "pipeline" / "vendor" / "bsb" / "tables" / "bsb_tables.tsv",
             SHORESH.parent / "example" / "bsb_tables.tsv"]
OPEN, CLOSE = "“‘", "”’"


def _fetch(url: str, dest: Path) -> bytes:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=600) as r:
            dest.write_bytes(r.read())
    return dest.read_bytes()


def _clear(t: str, commit: str) -> tuple[dict, str]:
    raw = _fetch(CLEAR_URL.format(commit=commit, t=t), CACHE / f"alignment-quotations-{t}-{commit[:12]}.tsv")
    out = {}
    for r in csv.DictReader(io.StringIO(raw.decode("utf-8")), delimiter="\t"):
        k, d = r.get("id") or "", r.get("depth") or ""
        if len(k) == 12 and d.isdigit() and int(d) > 0 and int(k[:2]) <= 39:
            out[k] = int(d) - 1
    return out, hashlib.sha256(raw).hexdigest()


def _bsb(tokens: list[tuple[str, str]]) -> tuple[dict, str]:
    path = next((p for p in BSB_LOCAL if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == BSB_SHA256), None)
    raw = path.read_bytes() if path else _fetch(BSB_URL, CACHE / "bsb_tables.tsv")
    sha = hashlib.sha256(raw).hexdigest()
    if sha != BSB_SHA256:
        raise SystemExit(f"bsb_tables.tsv: sha256 {sha}, expected {BSB_SHA256}")
    rows, depth, book = [], 0, None
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig", errors="replace")), delimiter="\t")
    next(reader)
    for row in reader:
        if len(row) < 21:
            continue
        if row[4] not in ("Hebrew", "Aramaic") and row[1] != "0":
            break                                               # the NT
        if row[12] and row[12].rsplit(" ", 1)[0] != book:
            book, depth = row[12].rsplit(" ", 1)[0], 0
        for m in (c for c in row[17] if c in OPEN):
            if row[15] and depth > 0 and m == ("“" if depth % 2 == 1 else "‘"):
                continue                                        # a paragraph restating the open level
            depth += 1
        if row[0].isdigit() and 0 < int(row[0]) < 999999 and row[4] in ("Hebrew", "Aramaic"):
            rows.append((int(row[0]), re.sub(r"\D", "", row[10]).lstrip("0"), depth))
        closing = row[20] + row[19] + (row[22] if len(row) > 22 else "")
        depth = max(0, depth - sum(closing.count(c) for c in CLOSE))
    rows.sort()
    rs = [(st, d) for _, st, d in rows if st]
    pst = [st for _, st in tokens]
    word_depth, j = {}, 0
    for n, (st, d) in enumerate(rs):
        hit = next((k for k in range(j, min(j + 12, len(tokens))) if pst[k] == st), None)
        if hit is None:                                         # resync: the next five rows' Strong's in order among the next tokens
            nxt = [x for x, _ in rs[n:n + 5]]
            for k in range(j, min(j + 4000, len(tokens))):
                if pst[k] != nxt[0]:
                    continue
                kk, ok = k + 1, True
                for x in nxt[1:]:
                    f = next((y for y in range(kk, min(kk + 4, len(tokens))) if pst[y] == x), None)
                    if f is None:
                        ok = False
                        break
                    kk = f + 1
                if ok:
                    hit = k
                    break
        if hit is not None:
            word_depth.setdefault(tokens[hit][0][:11], d)
            j = hit + 1
    return {k: word_depth[k[:11]] for k, _ in tokens if k[:11] in word_depth}, sha


def depths(con: sqlite3.Connection) -> tuple[dict, dict]:
    """the votes, cached per source (con: the MACULA trees database, for the tokens' Strong's numbers)"""
    cache = CACHE / f"votes-{CLEAR_COMMIT[:12]}-{BSB_SHA256[:12]}.pkl"
    if cache.exists():
        return pickle.loads(cache.read_bytes())
    votes, shas = {}, {}
    for t in CLEAR_VOTERS:
        votes[t], shas[t] = _clear(t, CLEAR_COMMIT)
    tokens = [(r[0], re.sub(r"\D", "", r[1] or "").lstrip("0"))
              for r in con.execute("SELECT key, strong FROM words WHERE corpus='hbo' AND inserted=0 ORDER BY key")]
    votes["bsb"], shas["bsb"] = _bsb(tokens)
    cache.write_bytes(pickle.dumps((votes, shas)))
    return votes, shas
