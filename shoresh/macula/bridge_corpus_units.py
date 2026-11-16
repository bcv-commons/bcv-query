"""Units across texts in the bridge corpus (plan step 4, section 4.7): lexeme, concept and person; and the lexeme-to-lexeme edges that
carry the bridge tiers.

lexeme   all words of one lexeme in every text. Hebrew and Aramaic: keyed by the Strong's number with MACULA's letter (`hbo:0871a`,
         `arc:...`), spanning the Tanakh and both Hebrew NTs. Greek: keyed by the lemma (`grc:πορεύομαι`), spanning the Greek NT and the
         Septuagint (whose words already carry the NT's lemma where their number is an NT number). Features lex_key, lex_lang, lemma
         (the commonest), strong (the commonest, where any), lex_words, and lex_texts (the texts it occurs in, joined with commas: a search value has no spaces).
concept  all words with one model-made concept (m_concept, hebrew-word-concepts-model); feature m_concept.
person   one person of the addressees release (an entity: a person, group, deity, ...): the words of every quotation it speaks or is
         addressed in. The releases have no word-level mentions of persons, so this unit is "the speech it takes part in". Features
         ad_entity, ad_type, ad_gender, ad_spoke, ad_addressed, ad_characters; edges `speaker` and `addressee` from a quotation to its
         person.
Words with no Strong's number in a Hebrew NT (model-analysed names such as Peter and Paul, about 10,000) belong to no lexeme.
Lexeme edges: Hebrew lexeme -> Greek lexeme, one edge set per tier, value the tier's count: tier_macula and tier_glaux
(resources/lxx_bridge_tiers, the Septuagint), tier_heb_scg and tier_heb_mod (hebrew-nt-bridge pairs, the Hebrew NTs). A tier row's Hebrew number
without a letter goes to the commonest lettered lexeme where the words carry only lettered ones (2050a, 2050b); its Greek
number goes to the lexeme whose words carry that number most.
"""
from __future__ import annotations

import collections
import re

from macula.build_bridge_corpus import ROOT_RESOURCES, folder, pins, table

TIERS = (("macula", ROOT_RESOURCES / "lxx_bridge_tiers" / "macula.tsv"), ("glaux", ROOT_RESOURCES / "lxx_bridge_tiers" / "glaux.tsv"))


def strong_key(s) -> str | None:
    """'H0871a' / '0871a' / 871 -> '0871a'; Greek 'G3962' / '3962' -> '3962'"""
    m = re.match(r"[HG]?0*(\d+)([a-z]?)", str(s or ""))
    return f"{int(m.group(1)):04d}{m.group(2)}" if m else None


def add_units(c) -> None:
    st = collections.Counter()
    text_of = {}
    for h, name in c.F["name"].items():                                 # text nodes: word -> text name
        for s in c.nodes["text"][h[1]]:
            text_of[s] = name
    lex = collections.defaultdict(list)
    lemmas, strongs = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
    for s in range(1, len(c.slot) + 1):
        lang = c.F["lang"].get(s)
        if lang in ("hbo", "arc"):
            k = strong_key(c.F["strong"].get(s))
            key = f"{lang}:{k}" if k else None
        elif lang == "grc" and c.F["lemma"].get(s):
            key = f"grc:{c.F['lemma'][s]}"
        else:
            key = None
        if key is None:
            st[f"words without a lexeme key: {text_of.get(s)}"] += 1
            continue
        lex[key].append(s)
        if c.F["lemma"].get(s):
            lemmas[key][c.F["lemma"][s]] += 1
        if c.F["strong"].get(s):
            strongs[key][strong_key(c.F["strong"][s])] += 1
    by_strong = {"hbo": {}, "grc": collections.defaultdict(collections.Counter)}
    for key, sl in lex.items():
        h = c.node("lexeme", sl, key)
        lang = key.split(":")[0]
        c.F["lex_key"][h], c.F["lex_lang"][h], c.F["lex_words"][h] = key, lang, len(sl)
        c.F["lex_texts"][h] = ",".join(sorted({text_of[s] for s in sl}))
        if lemmas[key]:
            c.F["lemma"][h] = lemmas[key].most_common(1)[0][0]
        if strongs[key]:
            c.F["strong"][h] = strongs[key].most_common(1)[0][0]
        if lang == "grc":
            for n, cnt in strongs[key].items():
                by_strong["grc"][n][h] += cnt
        elif lang == "hbo":
            by_strong["hbo"].setdefault(key.split(":")[1], h)
    for key in [k for k in lex if k.startswith("arc:")]:
        by_strong["hbo"].setdefault(key.split(":")[1], c.at["lexeme"][key])  # a Hebrew number found only in Aramaic
    for k in ("lex_key", "lex_lang", "lex_words", "lex_texts"):
        c.origin[k] = "words"
    st["lexemes"] = len(lex)
    st.update({f"lexemes {lang}": n for lang, n in collections.Counter(k.split(":")[0] for k in lex).items()})
    st["lexemes in more than one text"] = sum("," in c.F["lex_texts"][c.at["lexeme"][k]] for k in lex)
    greek = {n: cnt.most_common(1)[0][0] for n, cnt in by_strong["grc"].items()}
    base = collections.defaultdict(collections.Counter)                 # a tier's plain number (H2050) when the words carry 2050a / 2050b
    for k, h in by_strong["hbo"].items():
        base[k[:4]][h] += c.F["lex_words"][h]

    def hebrew(n):
        k = strong_key(n)
        if k in by_strong["hbo"]:
            return by_strong["hbo"][k]
        return base[k[:4]].most_common(1)[0][0] if k and base.get(k[:4]) else None

    tiers = list(TIERS)
    br = folder("hebrew-nt-bridge", pins()["layers"]["hebrew-nt-bridge"])
    tiers += [("heb_scg", br / "pairs" / "heb_scg.tsv"), ("heb_mod", br / "pairs" / "heb_mod.tsv")]
    for tier, path in tiers:
        lines = path.read_text(encoding="utf-8").splitlines()
        head = lines[0].split("\t")
        n = placed = 0
        for line in lines[1:]:
            r = dict(zip(head, line.split("\t")))
            n += 1
            a = hebrew(r["hebrew_strong"])
            b = greek.get(strong_key(r["greek_strong"]))
            placed += c.edge(f"tier_{tier}", a, b, int(r["count"]), "hebrew-nt-bridge" if tier.startswith("heb_") else f"tier-{tier}")
        st[f"tier {tier}: rows"], st[f"tier {tier}: placed"] = n, placed
    # concepts
    con = collections.defaultdict(list)
    for s, v in c.F["m_concept"].items():
        con[v].append(s)
    for v, sl in con.items():
        c.F["m_concept"][c.node("concept", sl, v)] = v
    st["concepts"] = len(con)
    # persons
    speech = collections.defaultdict(set)
    rows = table("addressees", "data/quotations.parquet")
    for r in rows:
        q = c.at["quotation"].get(r["quote"])
        if q is None:
            continue
        for role in ("speaker", "addressee"):
            if r[role]:
                speech[r[role]].add((q, role))
    for r in table("addressees", "data/persons.parquet"):
        qs = speech.get(r["entity"], set())
        h = c.node("person", {s for q, _ in qs for s in c.nodes["quotation"][q[1]]}, r["entity"])
        if h is None:
            st["persons without a placed quotation"] += 1
            continue
        c.put(h, {k: r[k] for k in ("entity", "type", "gender", "spoke", "addressed", "characters")}, "ad_", "addressees")
        for q, role in qs:
            st[f"{role} edges"] += c.edge(role, q, h, None, "addressees")
    st["persons"] = len(c.nodes["person"])
    c.report["layers"]["units"] = dict(st)
