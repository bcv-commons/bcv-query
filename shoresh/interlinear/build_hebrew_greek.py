"""Builds hebrew_greek.db from globalbibletools/data's hbo+grc/ JSON source — the per-occurrence
Hebrew/Greek interlinear (word text, grammar code, Strong's-tagged lemma). Ported from
example/aleph/data-builder/build_hebrew_greek_db.py (itself ported from globalbibletools/study-app's
Dart `database_builder`), which verified a byte-for-byte rebuild against the shipped db.

  python -m interlinear.build_hebrew_greek       # -> interlinear/data/hebrew_greek.db
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from interlinear.fetch import DATA_DIR, STRONGS_DATA_DIR, fetch, fetch_strongs_data
from interlinear.normalization import normalize_hebrew_greek, remove_punctuation

HERE = Path(__file__).resolve().parent
OUT_PATH = HERE / "data" / "hebrew_greek.db"


class HebrewGreekWord:
	__slots__ = ("id", "text", "grammar", "lemma")

	def __init__(self, id_: int, text: str, grammar: str, lemma: str):
		self.id = id_
		self.text = text
		self.grammar = grammar
		self.lemma = lemma


def extract_words(json_path: Path) -> list[HebrewGreekWord]:
	with open(json_path, encoding="utf-8") as f:
		data = json.load(f)

	words = []
	for chapter in data["chapters"]:
		for verse in chapter["verses"]:
			for word in verse["words"]:
				words.append(
					HebrewGreekWord(
						id_=int(word["id"]),
						text=(word.get("text") or "").strip(),
						grammar=(word.get("grammar") or "").strip(),
						lemma=(word.get("lemma") or "").strip(),
					)
				)
	return words


def load_strongs_root_map() -> dict[str, str]:
	"""{Strong's code (prefix + 4-digit zero-padded number, e.g. "H7225"): root word}, from the
	bundled strongs-hebrew.txt / strongs-greek.txt lookup tables (line format: "<number>|<word>")."""
	strongs_map: dict[str, str] = {}
	for filename, prefix in (("strongs-greek.txt", "G"), ("strongs-hebrew.txt", "H")):
		path = STRONGS_DATA_DIR / filename
		with open(path, encoding="utf-8") as f:
			for line in f:
				line = line.rstrip("\n")
				if not line:
					continue
				number_str, word = line.split("|", 1)
				key = prefix + number_str.strip().zfill(4)
				strongs_map[key] = word.strip()
	return strongs_map


def build(source_data_dir: Path | None = None, output_db_path: Path | None = None) -> None:
	source_data_dir = source_data_dir or DATA_DIR
	output_db_path = output_db_path or OUT_PATH
	hbo_grc_dir = source_data_dir / "hbo+grc"
	book_files = sorted(p.name for p in hbo_grc_dir.iterdir())
	print(f"[interlinear] {len(book_files)} book files in {hbo_grc_dir}", file=sys.stderr)

	text_frequencies: Counter[str] = Counter()
	unique_grammar: set[str] = set()
	unique_lemmas: set[str] = set()
	words_by_file: dict[str, list[HebrewGreekWord]] = {}

	for filename in book_files:
		words = extract_words(hbo_grc_dir / filename)
		words_by_file[filename] = words
		for word in words:
			text_frequencies[word.text] += 1
			unique_grammar.add(word.grammar)
			unique_lemmas.add(word.lemma)

	total_words = sum(len(w) for w in words_by_file.values())
	print(f"[interlinear] {total_words} words, {len(text_frequencies)} unique text forms", file=sys.stderr)

	output_db_path.parent.mkdir(parents=True, exist_ok=True)
	output_db_path.unlink(missing_ok=True)

	db = sqlite3.connect(output_db_path)
	db.executescript("""
		CREATE TABLE verses (
			_id INTEGER PRIMARY KEY,
			text INTEGER NOT NULL,
			grammar INTEGER NOT NULL,
			strongs INTEGER NOT NULL
		);
		CREATE TABLE text (
			_id INTEGER PRIMARY KEY,
			text TEXT NOT NULL,
			no_punctuation TEXT NOT NULL,
			normalized TEXT NOT NULL
		);
		CREATE TABLE grammar (
			_id INTEGER PRIMARY KEY,
			grammar TEXT NOT NULL
		);
		CREATE TABLE strongs (
			_id INTEGER PRIMARY KEY,
			code TEXT NOT NULL,
			root TEXT
		);
	""")

	sorted_text = [w for w, _ in text_frequencies.most_common()]
	text_id_by_word: dict[str, int] = {}
	rows = []
	for i, word in enumerate(sorted_text):
		word_id = i + 1
		text_id_by_word[word] = word_id
		rows.append((word_id, word, remove_punctuation(word), normalize_hebrew_greek(word)))
	db.executemany("INSERT INTO text (_id, text, no_punctuation, normalized) VALUES (?, ?, ?, ?)", rows)

	sorted_grammar = sorted(unique_grammar)
	grammar_id_by_code: dict[str, int] = {}
	rows = []
	for i, grammar in enumerate(sorted_grammar):
		grammar_id = i + 1
		grammar_id_by_code[grammar] = grammar_id
		rows.append((grammar_id, grammar))
	db.executemany("INSERT INTO grammar (_id, grammar) VALUES (?, ?)", rows)

	strongs_root_map = load_strongs_root_map()
	sorted_lemmas = sorted(unique_lemmas)
	strongs_id_by_code: dict[str, int] = {}
	rows = []
	missing_roots = 0
	for i, lemma in enumerate(sorted_lemmas):
		strongs_id = i + 1
		strongs_id_by_code[lemma] = strongs_id
		root = strongs_root_map.get(lemma[:5])
		if root is None or root == "NONE":
			missing_roots += 1
			root = None
		rows.append((strongs_id, lemma, root))
	db.executemany("INSERT INTO strongs (_id, code, root) VALUES (?, ?, ?)", rows)
	print(f"[interlinear] {len(rows)} strongs codes ({missing_roots} with no root found)", file=sys.stderr)

	rows = []
	for filename in book_files:
		for word in words_by_file[filename]:
			rows.append((
				word.id,
				text_id_by_word[word.text],
				grammar_id_by_code[word.grammar],
				strongs_id_by_code[word.lemma],
			))
	db.executemany("INSERT INTO verses (_id, text, grammar, strongs) VALUES (?, ?, ?, ?)", rows)

	# idx_normalized / idx_no_punctuation: upstream schema (search support). idx_verses_strongs /
	# idx_strongs_code: /similar mode=root (strongs->verses join direction). idx_verses_text:
	# /similar mode=exact (text->verses join direction) — one index per join direction, per
	# API_CONTRACT.md's guidance; without either, its respective mode is a full table scan of the
	# ~448k-row verses table regardless of how common the Strong's code / text is.
	db.executescript("""
		CREATE INDEX idx_normalized ON text (normalized);
		CREATE INDEX idx_no_punctuation ON text (no_punctuation);
		CREATE INDEX idx_verses_strongs ON verses (strongs);
		CREATE INDEX idx_strongs_code ON strongs (code);
		CREATE INDEX idx_verses_text ON verses (text);
	""")
	db.commit()
	db.close()
	print(f"[interlinear] {output_db_path} ({output_db_path.stat().st_size // 1024} KB)", file=sys.stderr)


if __name__ == "__main__":
	fetch()
	fetch_strongs_data()
	build()
