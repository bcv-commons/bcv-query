#!/usr/bin/env python3
"""Build the code-keyed related-languages reference → resources/related_langs/.

Keyed by ISO 639-3 (the comprehensive 3-letter standard), with ISO 639-1, BCP-47 scripts,
and a `macrolanguage` link so the structure scales toward thousands of languages and stays
queryable by code. Relatedness here is a CURATED bootstrap (basis=curated); the README
documents the planned migration to Glottolog + URIEL/lang2vec-derived edges.

Regional/script variants (e.g. cmn → zh-Hans / zh-Hant, nor → nob / nno) are a DIFFERENT
relation and live in the sibling resources/regional_langs/ — see that README.

  python scripts/build_related_langs.py

Outputs (data only; the two README.md files are hand-authored design docs, not regenerated):
  resources/related_langs/languages.tsv         registry, one row per ISO 639-3 language
  resources/related_langs/related.tsv           edges: code · rank · related_code · basis
  resources/related_langs/related_languages.json full structure, keyed by code
  resources/related_langs/recommended_refs.tsv  derived view: code → ideal/available refs
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
WG = ROOT / "resources/word_glosses/hbo"
OUT = ROOT / "resources/related_langs"

# Curated taxonomy: GROUP -> BRANCH -> members ordered by within-branch proximity
# (closest / most mutually-intelligible first). Chinese is ONE language (cmn); its
# Hans/Hant split is a script variant handled in regional_langs, not here.
FAMILIES = {
    "Germanic": {
        "North (Scandinavian)": ["Danish", "Norwegian", "Swedish", "Icelandic", "Faroese"],
        "West-Continental": ["German", "Dutch", "Afrikaans", "Yiddish"],
        "Anglic": ["English"],
    },
    "Romance": {
        "Ibero": ["Spanish", "Portuguese", "Catalan", "Galician"],
        "Gallo": ["French", "Occitan"],
        "Italo": ["Italian"],
        "Eastern": ["Romanian"],
    },
    "Slavic": {
        "East": ["Russian", "Ukrainian", "Belarusian"],
        "West": ["Polish", "Czech", "Slovak"],
        "South": ["Bulgarian", "Serbian", "Croatian", "Slovene", "Macedonian"],
    },
    "Semitic": {
        "Ethiopic": ["Amharic", "Tigrinya", "Geez"],
        "Arabic": ["Arabic"],
        "Canaanite": ["Hebrew"],
        "Aramaic": ["Aramaic"],
    },
    "Indo-Aryan": {
        "Hindustani": ["Hindi", "Urdu"],
        "Other": ["Bengali", "Punjabi", "Gujarati", "Marathi", "Nepali"],
    },
    "Sinitic": {
        "Mandarin": ["Chinese"],
        "Other": ["Cantonese"],
    },
    "Bantu": {
        "Swahili": ["Swahili"],
        "Other": ["Zulu", "Xhosa", "Shona", "Lingala"],
    },
    "Hellenic": {"Greek": ["Greek"]},
}

# group -> top-level genetic stock (recorded for future-proofing / cross-group queries)
STOCK = {"Germanic": "Indo-European", "Romance": "Indo-European", "Slavic": "Indo-European",
         "Indo-Aryan": "Indo-European", "Hellenic": "Indo-European",
         "Semitic": "Afro-Asiatic", "Sinitic": "Sino-Tibetan", "Bantu": "Atlantic-Congo"}

# name -> (iso639_3, iso639_1, scripts[ISO 15924], macrolanguage iso639_3 or "", gloss file stems)
META = {
    "Danish": ("dan", "da", "Latn", "", ["Danish"]),
    "Norwegian": ("nor", "no", "Latn", "nor", []),
    "Swedish": ("swe", "sv", "Latn", "", []),
    "Icelandic": ("isl", "is", "Latn", "", []),
    "Faroese": ("fao", "fo", "Latn", "", []),
    "German": ("deu", "de", "Latn", "", ["German"]),
    "Dutch": ("nld", "nl", "Latn", "", ["Dutch"]),
    "Afrikaans": ("afr", "af", "Latn", "", []),
    "Yiddish": ("yid", "yi", "Hebr", "yid", []),
    "English": ("eng", "en", "Latn", "", ["English"]),
    "Spanish": ("spa", "es", "Latn", "", ["Spanish"]),
    "Portuguese": ("por", "pt", "Latn", "", ["Portuguese"]),
    "Catalan": ("cat", "ca", "Latn", "", []),
    "Galician": ("glg", "gl", "Latn", "", []),
    "French": ("fra", "fr", "Latn", "", ["French"]),
    "Occitan": ("oci", "oc", "Latn", "", []),
    "Italian": ("ita", "it", "Latn", "", []),
    "Romanian": ("ron", "ro", "Latn", "", []),
    "Russian": ("rus", "ru", "Cyrl", "", []),
    "Ukrainian": ("ukr", "uk", "Cyrl", "", []),
    "Belarusian": ("bel", "be", "Cyrl", "", []),
    "Polish": ("pol", "pl", "Latn", "", []),
    "Czech": ("ces", "cs", "Latn", "", []),
    "Slovak": ("slk", "sk", "Latn", "", []),
    "Bulgarian": ("bul", "bg", "Cyrl", "", []),
    "Serbian": ("srp", "sr", "Cyrl,Latn", "", []),
    "Croatian": ("hrv", "hr", "Latn", "", []),
    "Slovene": ("slv", "sl", "Latn", "", []),
    "Macedonian": ("mkd", "mk", "Cyrl", "", []),
    "Amharic": ("amh", "am", "Ethi", "", ["Amharic"]),
    "Tigrinya": ("tir", "ti", "Ethi", "", []),
    "Geez": ("gez", "", "Ethi", "", []),
    "Arabic": ("ara", "ar", "Arab", "ara", []),
    "Hebrew": ("heb", "he", "Hebr", "", []),
    "Aramaic": ("arc", "", "Hebr,Syrc", "", []),
    "Hindi": ("hin", "hi", "Deva", "", []),
    "Urdu": ("urd", "ur", "Arab", "", []),
    "Bengali": ("ben", "bn", "Beng", "", []),
    "Punjabi": ("pan", "pa", "Guru", "", []),
    "Gujarati": ("guj", "gu", "Gujr", "", []),
    "Marathi": ("mar", "mr", "Deva", "", []),
    "Nepali": ("nep", "ne", "Deva", "nep", []),
    "Chinese": ("cmn", "zh", "Hans,Hant", "zho", ["Chinese-Simplified", "Chinese-Traditional"]),
    "Cantonese": ("yue", "", "Hant,Hans", "zho", []),
    "Swahili": ("swa", "sw", "Latn", "", ["Swahili"]),
    "Zulu": ("zul", "zu", "Latn", "", []),
    "Xhosa": ("xho", "xh", "Latn", "", []),
    "Shona": ("sna", "sn", "Latn", "", []),
    "Lingala": ("lin", "ln", "Latn", "", []),
    "Greek": ("ell", "el", "Grek", "", []),
}

# original-language anchors — never themselves gloss targets
SOURCE_LANGS = {"Hebrew", "Aramaic", "Greek"}


def _index():
    idx = {}
    for group, branches in FAMILIES.items():
        for branch, members in branches.items():
            for m in members:
                idx[m] = (group, branch)
    return idx


def _relatives(lang, idx):
    """Ordered relatives by name: branch siblings, then rest of group, then English."""
    group, branch = idx[lang]
    sibs = [x for x in FAMILIES[group][branch] if x != lang]
    others = [x for b, members in FAMILIES[group].items() if b != branch for x in members]
    rel = [x for x in sibs + others if x not in SOURCE_LANGS]
    if lang != "English":
        rel.append("English")
    return list(dict.fromkeys(rel))


def main():
    idx = _index()
    code = {name: META[name][0] for name in idx}
    avail_files = {p.stem for p in WG.glob("*.csv")}
    OUT.mkdir(parents=True, exist_ok=True)

    def available(name):
        c3, c1, scr, macro, gnames = META[name]
        return name == "English" or name in avail_files or any(g in avail_files for g in gnames)

    targets = sorted((l for l in idx if l not in SOURCE_LANGS), key=lambda n: code[n])
    data = {}
    for name in sorted(idx, key=lambda n: code[n]):
        group, branch = idx[name]
        c3, c1, scr, macro, gnames = META[name]
        rel_names = _relatives(name, idx) if name not in SOURCE_LANGS else []
        data[c3] = {
            "iso639_1": c1, "name": name, "glottocode": "",
            "stock": STOCK[group], "group": group, "branch": branch,
            "scripts": scr, "macrolanguage": macro,
            "is_source": name in SOURCE_LANGS, "available": available(name),
            "gloss_names": gnames, "related": [code[r] for r in rel_names],
        }

    # registry
    cols = ["iso639_3", "iso639_1", "name", "glottocode", "stock", "group", "branch",
            "scripts", "macrolanguage", "is_source", "available", "gloss_names"]
    lines = ["\t".join(cols)]
    for c3 in sorted(data):
        d = data[c3]
        lines.append("\t".join([c3, d["iso639_1"], d["name"], d["glottocode"], d["stock"],
                                d["group"], d["branch"], d["scripts"], d["macrolanguage"],
                                "yes" if d["is_source"] else "no",
                                "yes" if d["available"] else "no", ";".join(d["gloss_names"])]))
    (OUT / "languages.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # relatedness edges (pure linguistic; availability applied by consumers)
    elines = ["iso639_3\trank\trelated_iso639_3\tbasis"]
    for c3 in sorted(data):
        for rank, rc in enumerate(data[c3]["related"], 1):
            elines.append(f"{c3}\t{rank}\t{rc}\tcurated")
    (OUT / "related.tsv").write_text("\n".join(elines) + "\n", encoding="utf-8")

    # full structure
    (OUT / "related_languages.json").write_text(
        json.dumps({"key": "iso639_3", "basis": "curated",
                    "note": "bootstrap; migrate edges to Glottolog+URIEL (see README)",
                    "languages": data}, ensure_ascii=False, indent=2), encoding="utf-8")

    # derived convenience view (availability intersected — NOT canonical)
    vlines = ["iso639_3\tname\tgroup\tavailable\tideal_ref_codes\tavailable_ref_codes"]
    for c3 in sorted(c for c in data if not data[c]["is_source"]):
        d = data[c3]
        avail_refs = [rc for rc in d["related"] if data.get(rc, {}).get("available")]
        vlines.append(f"{c3}\t{d['name']}\t{d['group']}\t{'yes' if d['available'] else 'no'}\t"
                      f"{','.join(d['related'])}\t{','.join(avail_refs)}")
    (OUT / "recommended_refs.tsv").write_text("\n".join(vlines) + "\n", encoding="utf-8")

    print(f"wrote {OUT.relative_to(ROOT)}/ : languages.tsv, related.tsv, "
          f"related_languages.json, recommended_refs.tsv")
    print(f"  {len(data)} languages ({len(targets)} targets); "
          f"available now: {sorted(c for c in data if data[c]['available'])}")


if __name__ == "__main__":
    main()
