"""Hebrew/Greek text normalization, ported from globalbibletools/study-app's
database_builder/lib/src/hebrew_greek/normalization.dart (via example/aleph/data-builder's Python
port, which verified this range-by-range against the Dart source).

Only normalize_hebrew_greek and remove_punctuation are ported — they're the
two used by the database build scripts (populating text.normalized and
text.no_punctuation). fix_final_forms exists in the Dart source too but is
only used by the live search feature, not by the build pipeline.

Character ranges are built from explicit integer codepoints (not typed
glyphs) so each one is byte-for-byte auditable against the Dart source's
\\uXXXX literals, with no risk of a lookalike character being typed instead
(e.g. an ASCII ';' where the source means U+037E, the Greek question mark).
"""

import re
import unicodedata


def _range(start: int, end: int) -> str:
	return chr(start) + "-" + chr(end)


def _chars(*codepoints: int) -> str:
	return "".join(chr(c) for c in codepoints)


# Hebrew Alef (U+05D0) - Tav (U+05EA); Greek Alpha (U+0391) - omega (U+03C9).
_HEBREW_LETTERS = _range(0x05D0, 0x05EA)
_GREEK_LETTERS = _range(0x0391, 0x03C9)
_NON_ESSENTIAL_CHARS = re.compile("[^ " + _HEBREW_LETTERS + _GREEK_LETTERS + "]+")
_WHITESPACE = re.compile("\\s+")

# Final Kaf (05DA), Mem (05DD), Nun (05DF), Pe (05E3), Tsadi (05E5), Sigma (03C2).
_FINAL_KAF, _FINAL_MEM, _FINAL_NUN, _FINAL_PE, _FINAL_TSADI, _FINAL_SIGMA = (
	chr(0x05DA), chr(0x05DD), chr(0x05DF), chr(0x05E3), chr(0x05E5), chr(0x03C2)
)
_KAF, _MEM, _NUN, _PE, _TSADI, _SIGMA = (
	chr(0x05DB), chr(0x05DE), chr(0x05E0), chr(0x05E4), chr(0x05E6), chr(0x03C3)
)
_FINAL_FORMS = re.compile(
	"[" + _chars(0x05DA, 0x05DD, 0x05DF, 0x05E3, 0x05E5, 0x03C2) + "]"
)
_FINAL_TO_REGULAR = {
	_FINAL_KAF: _KAF,
	_FINAL_MEM: _MEM,
	_FINAL_NUN: _NUN,
	_FINAL_PE: _PE,
	_FINAL_TSADI: _TSADI,
	_FINAL_SIGMA: _SIGMA,
}


def normalize_hebrew_greek(text: str) -> str:
	"""Decompose diacritics, strip anything but Hebrew/Greek letters and
	spaces, collapse whitespace, lowercase, and fold final-form letters to
	their regular form. Output is ready to `.split(' ')` into search terms."""
	decomposed = unicodedata.normalize("NFD", text)
	filtered = _NON_ESSENTIAL_CHARS.sub("", decomposed)
	cleaned = _WHITESPACE.sub(" ", filtered).strip()
	lowercase = cleaned.lower()
	return _FINAL_FORMS.sub(lambda m: _FINAL_TO_REGULAR[m.group(0)], lowercase)


# Hebrew block (0590-05FF), Hebrew Presentation Forms (FB1D-FB4F),
# Greek and Coptic (0370-03FF), Greek Extended (1F00-1FFF),
# Combining Diacritical Marks (0300-036F), plus space.
_PUNCTUATION_KEEP = re.compile(
	"[^ "
	+ _range(0x0590, 0x05FF)
	+ _range(0xFB1D, 0xFB4F)
	+ _range(0x0370, 0x03FF)
	+ _range(0x1F00, 0x1FFF)
	+ _range(0x0300, 0x036F)
	+ "]+"
)
# Hebrew: Maqaf (05BE), Paseq (05C0), Sof Pasuk (05C3), Geresh (05F3),
# Gershayim (05F4). Greek: Greek Question Mark (037E, looks like ';' but
# isn't), Ano Teleia (00B7).
_PUNCTUATION_MARKS = re.compile(
	"[" + _chars(0x05BE, 0x05C0, 0x05C3, 0x05F3, 0x05F4, 0x037E, 0x00B7) + "]+"
)


def remove_punctuation(text: str) -> str:
	"""Keep only Hebrew/Greek letters, their combining diacritics, and
	spaces; drop Hebrew/Greek punctuation marks; trim and lowercase."""
	filtered = _PUNCTUATION_KEEP.sub("", text)
	cleaned = _PUNCTUATION_MARKS.sub("", filtered)
	return cleaned.strip().lower()
