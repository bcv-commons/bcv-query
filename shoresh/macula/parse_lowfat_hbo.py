"""Extract MACULA Hebrew's "lowfat" XML tree (Clear-Bible/macula-hebrew, WLC/lowfat/) -- a richer
sibling distribution to the flat TSV `macula.parse` already ingests, same repo, same CC-BY 4.0
license. Fulfills, from source data we already have rights to (no upstream ask needed), the still-
open items in the aligner wishlist (internal-docs -- see the 2026-09-23 wishlist thread):

  #10 (assimilated article as its own token): the lowfat XML DOES carry it, confirmed directly at
      Joshua 1:14 word 5 ("in the land") -- a zero-width <w class="art" unicode=""> sibling of the
      preposition, absent from the flat TSV entirely (checked directly: macula-spine.db's own
      macula_words has no row for it either -- this is a distribution gap, not something our own
      build_spine_words.py dropped).
  #3  (syntactic role + head): the TSV's per-token `role` column is Greek-only (0% Hebrew, verified
      directly against macula_words -- the wishlist's 7.7% figure was the Hebrew+Greek blend). The
      lowfat XML's <wg> tree gives head_key (verb-of-the-clause, per word) and a role label (v/s/o/
      o2/p/pp/adv) for Hebrew, which the flat TSV has no equivalent of at all.
  #3b (construct chain): also derivable today from EXISTING lexeme-spine.db columns (state='construct'
      + phrase_id + rela='rec', both already published) -- no new extraction strictly needed. This
      module additionally derives it from the lowfat tree's own `rule="NPofNP"` grouping as a second,
      independent source (see enrich_spine_lowfat.py, which keeps both for comparison).

WHAT THIS DOES NOT DO: this is Hebrew only (the wishlist's construct-chain/assimilated-article asks
are Hebrew-specific; macula-greek has no lowfat distribution to check). It does not modify
lexeme-spine.db's existing rows, PRIMARY KEY, or idx scheme -- that is a PUBLISHED, PINNED contract
(data-contracts.md) and splicing a new row for a zero-width token would shift idx for every
downstream row in an affected verse. Enrichment happens as purely additive columns and a separate
side table -- see enrich_spine_lowfat.py.

HEAD DEFINITION (a deliberate simplification, stated plainly rather than left implicit): head_key is
the key of the nearest enclosing clause's (`wg class="cl"`) verb (`role="v"`), not a full multi-level
dependency parse. This directly serves the wishlist's own stated use case ("a gap that's a verb's
object prefers targets in the object region") without claiming a linguistically complete parse. A
word IN the clause verb itself gets head_key=NULL (it's that clause's root).

LICENSE DISCIPLINE (same posture as macula.parse.py): the lowfat <w> elements bundle UBS MARBLE
fields (`sdbh`, `lexdomain`, `coredomain`, `sensenumber`) inline with the CC-BY grammatical ones --
verified directly, they're present on ordinary word elements. Only CC-BY fields are extracted here;
`sdbh`/`lexdomain`/`coredomain`/`sensenumber`/`contextualdomain`/`domain`/`ln`/`mandarin` are never
read.

  python -m macula.parse_lowfat_hbo                    # git-fetch (sparse, blobless) + build
  MACULA_HBO_LOWFAT_DIR=/path/to/WLC/lowfat python -m macula.parse_lowfat_hbo   # use a local checkout
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from references import BOOK_NUMBERS  # noqa: E402

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "lowfat-hbo.db"
REPO_URL = "https://github.com/Clear-Bible/macula-hebrew.git"
CLONE_DIR = HERE / ".lowfat-src"  # gitignored scratch checkout, not the published artifact
ENV_DIR = "MACULA_HBO_LOWFAT_DIR"

_REF = re.compile(r"^(\w+)\s+(\d+):(\d+)!(\d+)")
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"  # ElementTree expands xml:id to this

# CC-BY grammatical fields only -- mirrors macula.parse.MORPH_FIELDS + COLS, extended with the
# lowfat tree's own structural attributes (role, head, rule, class govern tree-walking below, not
# extracted as flat fields). Deliberately excludes sdbh/lexdomain/coredomain/sensenumber/
# contextualdomain/domain/ln (UBS MARBLE, NC) and mandarin (a different licensed translation).
_W_FIELDS = ("class", "morph", "pos", "type", "lemma", "gloss", "state",
             "gender", "number", "person", "role")
_STRONG_ATTR = "strongnumberx"


def _fetch_source(env: str) -> Path:
    local = __import__("os").environ.get(env)
    if local:
        return Path(local)
    if not (CLONE_DIR / "WLC" / "lowfat").is_dir():
        print(f"  git sparse-checkout {REPO_URL} -> {CLONE_DIR} (one-time, ~400MB)", file=sys.stderr)
        CLONE_DIR.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
                         REPO_URL, str(CLONE_DIR)], check=True)
        subprocess.run(["git", "-C", str(CLONE_DIR), "sparse-checkout", "set", "WLC/lowfat"], check=True)
    return CLONE_DIR / "WLC" / "lowfat"


def _key(xml_id: str) -> str:
    """Digits-only join key (drop the leading o/n prefix), matching macula.parse._key. An
    assimilated-article id (e.g. 'o060010140051ה') keeps its trailing non-digit marker stripped by
    \\D removal too -- fine, since these synthetic ids never need to match a macula_words row."""
    return re.sub(r"\D", "", xml_id or "")


def _find_verb_key(clause_el: ET.Element) -> str | None:
    """First role='v' <w> directly inside clause_el, not descending into a NESTED clause. Recurses
    through any wrapper tag (wg, or the rarer `<c>` compound/coordination wrapper -- see walk()'s
    same defensive default) except a nested clause, which owns its own verb."""
    for child in clause_el:
        if child.tag == "w" and child.get("role") == "v":
            return _key(child.get(_XML_ID, ""))
        if child.tag == "wg" and child.get("class") == "cl":
            continue  # nested clause owns its own verb
        if child.tag != "w":
            found = _find_verb_key(child)
            if found:
                return found
    return None


def parse_chapter(path: Path) -> list[dict]:
    tree = ET.parse(path)
    root = tree.getroot()  # <chapter>

    rows: list[dict] = []
    seq_counter: dict[tuple, int] = {}

    def walk(el: ET.Element, clause_verb: str | None, construct_group: str | None,
             phrase_role: str | None, group_counter: list[int]):
        for child in el:
            if child.tag == "p":
                continue  # raw verse text, not the word tree
            elif child.tag == "wg":
                is_clause = child.get("class") == "cl"
                cv = _find_verb_key(child) if is_clause else clause_verb
                cg = construct_group
                if child.get("rule") == "NPofNP" and construct_group is None:
                    group_counter[0] += 1
                    cg = f"{path.stem}-cg{group_counter[0]}"
                pr = child.get("role") or phrase_role
                walk(child, cv, cg, pr, group_counter)
            elif child.tag == "w":
                xml_id = child.get(_XML_ID, "")
                parsed = _REF.match(child.get("ref", ""))
                if not parsed:
                    continue
                book, ch, vs, word = parsed.group(1), int(parsed.group(2)), int(parsed.group(3)), int(parsed.group(4))
                if book not in BOOK_NUMBERS:
                    continue
                k = _key(xml_id)
                own_role = child.get("role")
                vkey = k if own_role == "v" else clause_verb
                skey = seq_counter.setdefault((book, ch, vs), 0)
                seq_counter[(book, ch, vs)] = skey + 1
                surface = child.get("unicode")
                is_inserted = 1 if (child.get("class") == "art" and not surface) else 0
                if not surface and not is_inserted:
                    print(f"  ! unexpected zero-width, non-article token {xml_id!r} in {path.name} "
                          f"-- kept, flagged, not assumed to be an assimilated article", file=sys.stderr)
                row = {
                    "key": k, "xml_id": xml_id, "book": book, "chapter": ch, "verse": vs, "word": word,
                    "seq": skey, "is_inserted": is_inserted, "surface": surface or "",
                    "strong": child.get(_STRONG_ATTR, "") or "",
                    "head_key": (None if vkey == k else vkey),
                    "phrase_role": own_role or phrase_role,
                    "construct_group": construct_group,
                }
                for f in _W_FIELDS:
                    row[f] = child.get(f, "") or ""
                rows.append(row)
            else:
                # Any other wrapper tag (sentence, chapter, or the rarer <c> compound/coordination
                # wrapper seen on ~832 multi-word proper names like "Tubal-Cain") -- recurse through
                # it transparently rather than silently dropping its content. Discovered directly:
                # an earlier version only handled "sentence"/"chapter" by name and silently dropped
                # every <w> inside a <c>, undercounting real words by ~1,700 across the OT (concentrated
                # in genealogy-heavy books) before this default branch was added.
                pr = child.get("role") or phrase_role
                walk(child, clause_verb, construct_group, pr, group_counter)

    walk(root, None, None, None, [0])
    return rows


def build(src: Path, out_path: Path) -> dict:
    out_path.unlink(missing_ok=True)
    db = sqlite3.connect(out_path)
    db.executescript("""
        CREATE TABLE lowfat_words(
            key TEXT, xml_id TEXT, book TEXT, chapter INT, verse INT, word INT, seq INT,
            is_inserted INT NOT NULL,      -- 1 = zero-width token absent from the flat TSV (e.g. an
                                            -- assimilated definite article) -- see docstring
            surface TEXT,                  -- '' for is_inserted rows (phonologically silent)
            strong TEXT, class TEXT, morph TEXT, pos TEXT, type TEXT, lemma TEXT, gloss TEXT,
            state TEXT, gender TEXT, number TEXT, person TEXT,
            head_key TEXT,                 -- key of this word's clause verb; NULL if this word IS
                                            -- that verb (clause root) -- see docstring HEAD DEFINITION
            phrase_role TEXT,               -- v/s/o/o2/p/pp/adv -- own role, else nearest ancestor's
            construct_group TEXT,          -- shared id for all words in one NPofNP chain, else NULL
            PRIMARY KEY (book, chapter, verse, seq)
        );
        CREATE INDEX ix_lowfat_key ON lowfat_words(key);
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
    """)

    files = sorted(src.glob("*-lowfat.xml"))
    n_words = n_inserted = 0
    for i, path in enumerate(files):
        rows = parse_chapter(path)
        db.executemany(
            "INSERT INTO lowfat_words VALUES "
            "(:key,:xml_id,:book,:chapter,:verse,:word,:seq,:is_inserted,:surface,:strong,"
            " :class,:morph,:pos,:type,:lemma,:gloss,:state,:gender,:number,:person,"
            " :head_key,:phrase_role,:construct_group)",
            rows,
        )
        n_words += len(rows)
        n_inserted += sum(r["is_inserted"] for r in rows)
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(files)} chapters, {n_words} words so far", file=sys.stderr)
    db.commit()

    n_head = db.execute("SELECT COUNT(*) FROM lowfat_words WHERE head_key IS NOT NULL").fetchone()[0]
    n_cg = db.execute("SELECT COUNT(DISTINCT construct_group) FROM lowfat_words "
                       "WHERE construct_group IS NOT NULL").fetchone()[0]
    db.executemany("INSERT INTO meta VALUES (?,?)", [
        ("source", "Clear-Bible/macula-hebrew, WLC/lowfat/ (CC-BY 4.0)"),
        ("chapters", str(len(files))),
        ("words", str(n_words)),
        ("inserted_tokens", str(n_inserted)),
        ("words_with_head_key", str(n_head)),
        ("construct_groups", str(n_cg)),
    ])
    db.commit()
    db.close()
    return {"chapters": len(files), "words": n_words, "inserted_tokens": n_inserted,
            "words_with_head_key": n_head, "construct_groups": n_cg}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DB_PATH)
    args = ap.parse_args()

    src = _fetch_source(ENV_DIR)
    if not src.is_dir():
        sys.exit(f"missing lowfat source dir: {src}")
    stats = build(src, args.out)
    print(f"{stats['words']} words ({stats['inserted_tokens']} inserted/assimilated-article) "
          f"from {stats['chapters']} chapters -> {args.out}")
    print(f"  head_key populated: {stats['words_with_head_key']}")
    print(f"  construct groups (NPofNP): {stats['construct_groups']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
