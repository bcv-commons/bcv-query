#!/usr/bin/env python3
"""Add Russian book aliases to book_names.json -> extra_aliases['ru'].

The ru `names` use full prepositional forms ("К Римлянам", "От Матфея",
"1-е Коринфянам"), so the bare citation forms users actually type don't parse.
This injects:
  1. bare forms — strip leading "К "/"От ", normalize "N-е " -> "N "
  2. standard Synodal abbreviations (Рим, Мф, Быт, 1Цар=1 Samuel … 4Цар=2 Kings)

Idempotent: rerun-safe (rebuilds the ru entry from scratch each time).
Run: .venv/bin/python scripts/add_ru_book_aliases.py
"""
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "resources" / "book_names.json"

# Standard Russian (Synodal) abbreviations → USFM. Note the Царств convention:
# 1-2 Samuel = 1-2 Царств, 1-2 Kings = 3-4 Царств; Chronicles = Паралипоменон.
SYNODAL_ABBR = {
    "GEN": ["Быт"], "EXO": ["Исх"], "LEV": ["Лев"], "NUM": ["Чис"], "DEU": ["Втор"],
    "JOS": ["Нав"], "JDG": ["Суд"], "RUT": ["Руф"], "1SA": ["1Цар"], "2SA": ["2Цар"],
    "1KI": ["3Цар"], "2KI": ["4Цар"], "1CH": ["1Пар"], "2CH": ["2Пар"], "EZR": ["Езд"],
    "NEH": ["Неем"], "EST": ["Есф"], "JOB": ["Иов"], "PSA": ["Пс"], "PRO": ["Притч"],
    "ECC": ["Еккл"], "SNG": ["Песн"], "ISA": ["Ис"], "JER": ["Иер"], "LAM": ["Плач"],
    "EZK": ["Иез"], "DAN": ["Дан"], "HOS": ["Ос"], "JOL": ["Иоил"], "AMO": ["Ам"],
    "OBA": ["Авд"], "JON": ["Ион"], "MIC": ["Мих"], "NAM": ["Наум"], "HAB": ["Авв"],
    "ZEP": ["Соф"], "HAG": ["Агг"], "ZEC": ["Зах"], "MAL": ["Мал"],
    "MAT": ["Мф"], "MRK": ["Мк"], "LUK": ["Лк"], "JHN": ["Ин"], "ACT": ["Деян"],
    "ROM": ["Рим"], "1CO": ["1Кор"], "2CO": ["2Кор"], "GAL": ["Гал"], "EPH": ["Еф"],
    "PHP": ["Флп"], "COL": ["Кол"], "1TH": ["1Фес"], "2TH": ["2Фес"], "1TI": ["1Тим"],
    "2TI": ["2Тим"], "TIT": ["Тит"], "PHM": ["Флм"], "HEB": ["Евр"], "JAS": ["Иак"],
    "1PE": ["1Пет"], "2PE": ["2Пет"], "1JN": ["1Ин"], "2JN": ["2Ин"], "3JN": ["3Ин"],
    "JUD": ["Иуд"], "REV": ["Откр"],
}


def bare_forms(name: str) -> list[str]:
    """Strip leading prepositions and normalize ordinal '1-е'→'1' to get the
    bare citation form ("К Римлянам"→"Римлянам", "1-е Коринфянам"→"1 Коринфянам")."""
    out = []
    n = re.sub(r"^(?:К|Ко|От|Послание\s+к|Послание)\s+", "", name).strip()
    if n != name:
        out.append(n)
    norm = re.sub(r"^(\d)\s*-?[ея]\s+", r"\1 ", name).strip()
    if norm != name and norm not in out:
        out.append(norm)
    return out


data = json.loads(OUT.read_text(encoding="utf-8"))
ru_names = data["names"]["ru"]
data.setdefault("extra_aliases", {})

aliases: dict[str, list[str]] = {}
for code, name in ru_names.items():
    forms = set(bare_forms(name))
    forms.update(SYNODAL_ABBR.get(code, []))
    forms.discard(name)  # the full name is already an alias via names
    if forms:
        aliases[code] = sorted(forms)

data["extra_aliases"]["ru"] = aliases
OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"wrote extra_aliases['ru'] for {len(aliases)} books")
for c in ["ROM", "MAT", "1CO", "1SA", "1KI", "PSA"]:
    print(f"  {c}: {aliases.get(c)}")
