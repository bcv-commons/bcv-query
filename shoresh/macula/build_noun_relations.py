#!/usr/bin/env python3
"""The relation in "of" constructions: Hebrew construct chains and pronominal suffixes on nouns, Greek genitives under a noun (wave 2,
development-phase plan 2026-11-13: "noun-to-noun relation", TBTA's types over the "of" constructions; packet 12's adnominal labels
are not built yet, so this is the rule-based first version). For Indonesian -nya / X Y order, Swahili -a / -angu, Tagalog ng / ni / ni.

    cd shoresh && .venv/bin/python3 -m macula.build_noun_relations      (after build_reference_status, word-senses-ubs)

One row per pair (head noun, dependent):
  corpus, head, dependent, form      construct (Hebrew noun in construct + the next noun), suffix (Hebrew pronominal suffix on a
                                     noun), genitive (Greek genitive noun / pronoun after or before a noun in the same constituent)
  relation  quantity     the head is a quantifier (כֹּל, רֹב, πλῆθος …)                  (all the kingdoms)
            kin          the head is a kin term                                        (son of Jesse, his brother)
            part         the head is a body part or a part noun, the dependent a person / thing (hand of Moses)
            member       the head is a people / group noun (or a kin term) and the dependent a place or a people, not a
                         person                                                      (men of Judah, sons of Israel)
            ruler        the head is a leader, the dependent a place, people or group                (king of Israel)
            material     the dependent is a substance or metal                          (altar of bronze)
            measure      the head is a measure, container or number noun                (cup of water, a jar of oil)
            origin       the dependent is a place, and the head a person or thing       (Jesse of Bethlehem)
            time         the dependent is a time noun                                    (the days of Saul)
            agent        the head is an event noun, the dependent a person or God       (word of the LORD)
            event_other  the head is an event noun, the dependent not a person          (the day of battle)
            attribute    the dependent is an attribute / quality noun                    (mountain of holiness → holy mountain)
            name         the head is a name-type noun (land, city, river) and the dependent a proper name  (the land of Egypt)
            possessor    the dependent is a person, God or group, none of the above      (house of David)
            other
  animacy   the dependent's animacy (reference-status, else its ACAI type / UBS domain / pronoun person), to choose the target's marker (Tagalog ni / ng)
The types are by rule from the UBS domains (SDBH, Louw-Nida), ACAI types and fixed lists; 'agent' does not separate subjective
from objective genitives ("fear of the LORD" is listed as agent).
Output: macula/data/noun-relations/{pairs.tsv, checks.md, build.json} (git-ignored). Not read: BHSA, TBTA, English text.
"""
from __future__ import annotations

import collections
import csv
import datetime
import json
import sqlite3
import subprocess
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "noun-relations"
MSPINE = HERE / "macula-spine.db"
LOWFAT = HERE / "lowfat-hbo.db"
N = lambda x: unicodedata.normalize("NFC", x or "")  # noqa: E731
BODY = {N(x) for x in ("יָד", "רֹאשׁ", "עַיִן", "פֶּה", "לֵב", "לֵבָב", "רֶגֶל", "פָּנֶה", "פָּנִים", "אֹזֶן", "נֶפֶשׁ", "זְרוֹעַ", "כַּף", "לָשׁוֹן",
                                "שָׂפָה", "בֶּטֶן", "אַף", "צַוָּאר", "כָּתֵף", "בָּשָׂר", "עֶצֶם", "יָמִין", "אֶצְבַּע", "שֵׁן", "קֶרֶב", "תָּוֶךְ",
                                "קָצֶה", "צַד", "פֵּאָה", "חֲצִי", "שְׁאָר", "יֶתֶר",
                                "χείρ", "κεφαλή", "ὀφθαλμός", "στόμα", "καρδία", "πούς", "πρόσωπον", "οὖς", "γλῶσσα", "χεῖλος", "σάρξ",
                                "σῶμα", "μέρος", "μέσος", "ψυχή")}
NAME_HEADS = {N(x) for x in ("אֶרֶץ", "עִיר", "נָהָר", "הַר", "מִדְבָּר", "נַחַל", "יָם", "שַׁעַר", "γῆ", "πόλις", "ποταμός", "ὄρος",
                                "ἔρημος", "θάλασσα", "χώρα")}
QUANT = {N(x) for x in ("כֹּל", "רֹב", "מִסְפָּר", "מְעַט", "יֶתֶר", "שְׁאָר", "חֲצִי", "πλῆθος", "ἀριθμός", "μέρος", "λοιπός")}
KIN_HBO, PEOPLE_HBO, LEADER_HBO, GROUP_HBO = "001001003012", "001001003", "001001003005", "001001003004"
DEITY_HBO = "001001001"


def dom_kind(lang, doms):
    """coarse kinds of a word from its UBS domains"""
    ks = set()
    for d in doms:
        if lang == "hbo":
            if d.startswith(KIN_HBO):
                ks.add("kin")
            if d.startswith(LEADER_HBO):
                ks.add("leader")
            if d.startswith(GROUP_HBO):
                ks.add("group")
            if d.startswith(PEOPLE_HBO):
                ks.add("person")
            if d.startswith(DEITY_HBO):
                ks.add("deity")
            if d.startswith("001002005"):
                ks.add("substance")
            if d.startswith(("001002002", "001002003", "001002004", "001002008", "003001008")):
                ks.add("place")
            if d.startswith(("001003001001003", "002004002009")):
                ks.add("measure")
            if d.startswith(("002002002010", "003001013", "004009")):
                ks.add("time")
            if d.startswith("002001001"):
                ks.add("attribute")
            if d.startswith("002") and not d.startswith(("002001001", "002002002010")):
                ks.add("event")
        else:
            top = d[:3]
            if top == "010":
                ks.add("kin")
            if top in ("009", "011"):
                ks.add("person")
            if top == "011":
                ks.add("group")
            if top == "037" and d[:6] in ("037048", "037049", "037050", "037051", "037052", "037053", "037054", "037055",
                                          "037056", "037057", "037058", "037059", "037060", "037061", "037062", "037063",
                                          "037064", "037065", "037066", "037067", "037068", "037069", "037070", "037071",
                                          "037072", "037073", "037074", "037075", "037076", "037077", "037078", "037079"):
                ks.add("leader")
            if top == "012":
                ks.add("deity")
            if top == "002":
                ks.add("substance")
            if top in ("001", "093"):
                ks.add("place" if top == "001" else "name")
            if top in ("081", "086", "060") or d[:6] in ("006118", "006119", "006120", "006121", "006122", "006123", "006124",
                                                       "006125", "006126", "006127", "006128", "006129", "006130", "006131"):
                ks.add("measure")
            if top == "067":
                ks.add("time")
            if top in ("025", "079", "088", "065", "022"):
                ks.add("attribute")
            if 13 <= int(top or 0) <= 92 and top not in ("025", "079", "088", "065", "067", "081", "086", "060", "037"):
                ks.add("event")
    return ks


def main() -> int:
    m = sqlite3.connect(f"file:{MSPINE}?mode=ro", uri=True)
    W = {}
    for k, lang, lem, cls, case, person in m.execute("select key, lang, lemma, class, case_, person from macula_words"):
        W[k] = (lang, N(lem), cls or "", case or "", person or "")
    doms = collections.defaultdict(list)
    for r in csv.DictReader(open(DATA / "word-senses-ubs/words.tsv", encoding="utf-8"), delimiter="\t"):
        if r["domains"]:
            doms[r["key"]].extend(r["domains"].split(";"))
    anim, rid = {}, {}
    for r in csv.DictReader(open(DATA / "reference-status/np.tsv", encoding="utf-8"), delimiter="\t"):
        anim[r["head"]], rid[r["head"]] = r["animacy"], r["referent"]
    ent = {}
    for r in csv.DictReader(open(DATA / "entities/entity_words.tsv", encoding="utf-8"), delimiter="\t"):
        if r["kind"] in ("explicit", "pronominal"):
            ent.setdefault(r["word"], r["entity"].split(":")[0])
    lf = sqlite3.connect(f"file:{LOWFAT}?mode=ro", uri=True)
    hb = [(k, c or "", t or "", s or "") for k, c, t, s in lf.execute("select key, class, type, state from lowfat_words order by key")]
    proper = {k for k, c, t, _ in hb if c == "noun" and t in ("proper", "gentilic")}
    pairs = []
    # Hebrew: construct noun + the next noun (articles and prefixed prepositions skipped); pronominal suffix on a noun host
    for i, (k, c, t, s) in enumerate(hb):
        if c == "noun" and s == "construct":
            for k2, c2, t2, s2 in hb[i + 1:i + 4]:
                if c2 in ("art",):
                    continue
                if c2 in ("noun", "adj") and k2[:11] != k[:11]:
                    pairs.append(("hbo", k, k2, "construct"))
                break
        if c == "pron" and t == "pronominal":
            host = [x for x in hb[max(0, i - 3):i] if x[0][:11] == k[:11] and x[1] == "noun"]
            if host:
                pairs.append(("hbo", host[-1][0], k, "suffix"))
    # Greek: a genitive noun / pronoun and the nearest noun before it (else after it) in the same roles.tsv constituent
    for r in csv.DictReader(open(DATA / "arg-roles/roles.tsv", encoding="utf-8"), delimiter="\t"):
        if r["corpus"] != "grc":
            continue
        ws = sorted(r["words"].split())
        for j, w in enumerate(ws):
            lang, _, cls, case, _ = W.get(w, ("",) * 5)
            if case != "genitive" or cls not in ("noun", "pron"):
                continue
            before = [x for x in ws[:j] if W.get(x, ("",) * 5)[2] == "noun" and W.get(x, ("",) * 5)[3] != "genitive"]
            after = [x for x in ws[j + 1:] if W.get(x, ("",) * 5)[2] == "noun" and W.get(x, ("",) * 5)[3] != "genitive"]
            h = before[-1] if before else (after[0] if after else "")
            if h:
                pairs.append(("grc", h, w, "genitive"))
    rows, st = [], collections.Counter()
    seen = set()
    for corpus, h, d, form in pairs:
        if (h, d) in seen:
            continue
        seen.add((h, d))
        hl, dl = W.get(h, ("",) * 5), W.get(d, ("",) * 5)
        hk, dk = dom_kind(corpus, doms.get(h, [])), dom_kind(corpus, doms.get(d, []))
        de = ent.get(d, "")
        if de in ("person", "group"):
            dk.add("person")
        if de == "deity":
            dk.add("deity")
        if de == "place":
            dk.add("place")
        if dl[2] == "pron" and dl[4] in ("first", "second"):
            dk.add("person")
        if d in proper and not (dk & {"person", "deity"}):
            dk.add("name")
        if hk & {"person", "group"}:                          # a person noun is not an event (μαθητής, עֶבֶד)
            hk.discard("event")
        a = anim.get(d, "")
        if dl[2] == "pron" and not a:
            a = "person" if dl[4] in ("first", "second") else ""
        if a in ("person", "deity"):
            dk.add(a)
        personal = bool(dk & {"person", "deity", "group"})
        if hl[1] in QUANT:
            rel = "quantity"
        elif "kin" in hk and (dk & {"place", "name", "group"}) and not (dk & {"person", "deity"}):
            rel = "member"                                    # sons of Israel, daughters of Moab: members of a people
        elif "kin" in hk:
            rel = "kin"
        elif hl[1] in BODY:
            rel = "part"
        elif "leader" in hk and (dk & {"place", "group", "person", "name"}):
            rel = "ruler"
        elif hl[1] in NAME_HEADS and (dk & {"place", "name"} or de == "place"):
            rel = "name"
        elif ("person" in hk or "group" in hk) and (dk & {"place", "group", "name"}) and "deity" not in dk:
            rel = "member"
        elif "substance" in dk:
            rel = "material"
        elif "measure" in hk:
            rel = "measure"
        elif "time" in dk:
            rel = "time"
        elif "event" in hk and personal:
            rel = "agent"
        elif "attribute" in dk and not personal:
            rel = "attribute"
        elif "place" in dk and not personal:
            rel = "origin"
        elif personal:
            rel = "possessor"
        elif "event" in hk:
            rel = "event_other"
        else:
            rel = "other"
        if not a:                                             # dependents are rarely phrase heads in reference-status
            a = ("deity" if "deity" in dk else "person" if dk & {"person", "group"} else "place" if dk & {"place", "name"}
                 else "thing" if doms.get(d) else "")
        rows.append([corpus, h, d, form, rel, a])
        st[(corpus, "animacy", a or "-")] += 1
        st[(corpus, form, rel)] += 1
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "pairs.tsv", "w", encoding="utf-8") as f:
        f.write("corpus\thead\tdependent\tform\trelation\tanimacy\n")
        f.writelines("\t".join(r) + "\n" for r in rows)
    lines = ["# Noun relations: checks", "", f"Pairs: {len(rows):,}.", "", "| corpus | form | relation | pairs |", "|---|---|---|---|"]
    lines += [f"| {c} | {f_} | {r_} | {n:,} |" for (c, f_, r_), n in sorted(st.items())]
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = subprocess.run(["git", "log", "-1", "--format=%h"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    (OUT / "build.json").write_text(json.dumps({"schema": 1, "built": datetime.date.today().isoformat(), "code": code,
                                                "not_read": ["BHSA", "TBTA", "English text"]}, indent=1) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
