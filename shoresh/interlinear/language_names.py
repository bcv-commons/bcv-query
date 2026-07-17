"""Display names for gloss language codes, ported from
example/aleph/data-api/src/language-names.js. Only codes we're confident about are listed —
anything else falls back to showing its raw code (see serve.list_languages), rather than
guessing at a language name and risking showing something wrong."""
from __future__ import annotations

LANGUAGE_NAMES: dict[str, str] = {
    "eng": "English",
    "spa": "Español",
    "fra": "Français",
    "por": "Português",
    "are": "العربية",
    "amh": "አማርኛ",
    "ben": "বাংলা",
    "cat": "Català",
    "deu": "Deutsch",
    "fas": "فارسی",
    "hau": "Hausa",
    "hin": "हिन्दी",
    "hun": "Magyar",
    "ind": "Bahasa Indonesia",
    "jpn": "日本語",
    "kan": "ಕನ್ನಡ",
    "kor": "한국어",
    "mal": "മലയാളം",
    "mlg": "Malagasy",
    "nep": "नेपाली",
    "nld": "Nederlands",
    "ori": "ଓଡ଼ିଆ",
    "pol": "Polski",
    "rus": "Русский",
    "swa": "Kiswahili",
    "tam": "தமிழ்",
    "tel": "తెలుగు",
    "tgl": "Tagalog",
    "tpi": "Tok Pisin",
    "urd": "اردو",
    "yid": "ייִדיש",
    "yor": "Yorùbá",
    "zho": "中文",
}
