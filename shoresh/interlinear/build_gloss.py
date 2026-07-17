"""Builds a per-language gloss <lang>.db from globalbibletools/data's <lang>/ JSON source — one
CONTEXTUAL, human-edited gloss per word OCCURRENCE (not a dictionary lemma gloss). Ported from
example/aleph/data-builder/build_gloss_db.py.

  python -m interlinear.build_gloss spa                    # one language
  python -m interlinear.build_gloss                        # every real gloss language found
  python -m interlinear.build_gloss spa fra por             # a subset
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from interlinear.fetch import DATA_DIR, fetch

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "data" / "gloss"

# "test" = tiny fixture (~255/448k words filled); "bib" = blank template (0 non-null glosses);
# "hbo+grc" = the interlinear source itself, handled by build_hebrew_greek.py, not a gloss language.
NON_LANGUAGE_DIRS = {"test", "bib", "hbo+grc"}


def extract_glosses(json_path: Path) -> list[tuple[int, str | None]]:
	"""One (word_id, gloss) pair per interlinear word id.

	A small fraction of entries (~0.3% in eng/spa/fra, 0 in por/are and most others) use a
	"<word_id>-01"/"-02" suffixed id instead of a plain integer — virtual extra word slots for
	genealogy-list chains ("X begat Y, Y begat Z") where the interlinear source tokenizes a repeated
	name once but the gloss needs to say it twice. "<word_id>-01" means "the word right after
	word_id": real id = int(word_id) + int(suffix). Plain entries are collected first and always
	take priority; a computed offset id only fills a gap if nothing already occupies it (verified
	against the shipped eng.db: every such collision has a blank gloss on the offset entry)."""
	import json
	with open(json_path, encoding="utf-8") as f:
		data = json.load(f)

	entries = [
		word
		for chapter in data["chapters"]
		for verse in chapter["verses"]
		for word in verse["words"]
	]

	glosses: dict[int, str | None] = {}
	order: list[int] = []

	def add(word_id: int, gloss: str | None):
		if gloss is not None:
			gloss = gloss.strip()
		if word_id not in glosses:
			glosses[word_id] = gloss
			order.append(word_id)

	for word in entries:
		if "-" not in word["id"]:
			add(int(word["id"]), word.get("gloss"))
	for word in entries:
		if "-" in word["id"]:
			base, suffix = word["id"].split("-")
			add(int(base) + int(suffix), word.get("gloss"))

	return [(word_id, glosses[word_id]) for word_id in order]


def discover_language_codes(source_data_dir: Path) -> list[str]:
	return sorted(
		d.name
		for d in source_data_dir.iterdir()
		if d.is_dir() and not d.name.startswith(".") and d.name not in NON_LANGUAGE_DIRS
	)


def build(lang_code: str, source_data_dir: Path | None = None, output_db_path: Path | None = None) -> dict:
	source_data_dir = source_data_dir or DATA_DIR
	output_db_path = output_db_path or (OUT_DIR / f"{lang_code}.db")
	lang_dir = source_data_dir / lang_code
	book_files = sorted(p.name for p in lang_dir.iterdir())

	unique_glosses: set[str] = set()
	words_by_file: dict[str, list[tuple[int, str | None]]] = {}
	total_words = 0
	non_null = 0

	for filename in book_files:
		words = extract_glosses(lang_dir / filename)
		words_by_file[filename] = words
		total_words += len(words)
		for _id, gloss in words:
			if gloss is not None:
				unique_glosses.add(gloss)
				non_null += 1

	print(f"[interlinear] {lang_code}: {total_words} words, {non_null} with a gloss "
	      f"({100*non_null//max(total_words,1)}%)", file=sys.stderr)

	output_db_path.parent.mkdir(parents=True, exist_ok=True)
	output_db_path.unlink(missing_ok=True)

	db = sqlite3.connect(output_db_path)
	db.executescript("""
		CREATE TABLE verses (_id INTEGER PRIMARY KEY, text INTEGER);
		CREATE TABLE text (_id INTEGER PRIMARY KEY, text TEXT NOT NULL);
	""")

	sorted_glosses = sorted(unique_glosses)
	text_id_by_gloss: dict[str, int] = {}
	rows = []
	for i, gloss in enumerate(sorted_glosses):
		gloss_id = i + 1
		text_id_by_gloss[gloss] = gloss_id
		rows.append((gloss_id, gloss))
	db.executemany("INSERT INTO text (_id, text) VALUES (?, ?)", rows)

	rows = []
	for filename in book_files:
		for word_id, gloss in words_by_file[filename]:
			text_id = text_id_by_gloss[gloss] if gloss is not None else None
			rows.append((word_id, text_id))
	db.executemany("INSERT INTO verses (_id, text) VALUES (?, ?)", rows)

	db.commit()
	db.close()
	return {"lang": lang_code, "total": total_words, "glossed": non_null,
	        "coverage": non_null / max(total_words, 1)}


def build_all(langs: list[str] | None = None, source_data_dir: Path | None = None) -> list[dict]:
	source_data_dir = source_data_dir or DATA_DIR
	lang_codes = langs or discover_language_codes(source_data_dir)
	print(f"[interlinear] building {len(lang_codes)} gloss db(s): {', '.join(lang_codes)}", file=sys.stderr)
	return [build(code, source_data_dir) for code in lang_codes]


if __name__ == "__main__":
	fetch()
	build_all(sys.argv[1:] or None)
