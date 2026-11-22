"""Stage 14 (SPEC 1.1, section 4.10): terms.tsv, the Hebrew and Greek terms for the meaning values.

    shoresh/.venv/bin/python -I shoresh/macula/examples_terms.py --write-master   # writes the master
    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build c1 --stage 14   # copies it into c1/<lang>/

The table is naming, done by a model (`named_by`), unchecked (`checked` empty). Two kinds of term:

- `text`, by rule (no choice): for `relation`, the connective lexeme of `connectives.conn`; for `sem_role`, the
  preposition lexeme of `arg-roles.prep_lemma`. Rule T: count the dataset's rows per (value, item) in the language
  (Hebrew rows of verses that hold Aramaic clauses in `b1` are left out; each item once per row; empty values left
  out). An item's home is the value with most of its rows (a tie: no home, listed). A value's term is, among the items
  whose home it is and that stand in at least 5% of its rows, the one with most rows (tie: code-point order). The item
  becomes the `b1` lexeme key whose lemma it is (more than one: the key most used as a connective in `b1`'s marks,
  then the larger `count`; for prepositions class `prep` first).
- named (`NAMED` below): for `ent_type`, a noun of the text (`text`, with its `b1` lexeme key); otherwise a term of
  the grammatical or rhetorical tradition (`tradition`, with the work) or a `coined` term (with how in `note`).
  `time`, `aspect` and `line_kind` are read off forms and positions, not marked by a word, so they take no `text` term.

A named entry is used only where rule T gives no term for that language.
"""
import argparse
import collections as C
import csv
import json
import os
import shutil
import unicodedata as U

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "data")
B1 = os.path.join(D, "source-examples", "b1")
# the 1.1 master (c builds); from SPEC 1.2 on, terms.tsv is the 1.2 master that examples_terms12.py writes
MASTER = os.path.join(HERE, "..", "..", "internal-docs", "source-examples-spec", "terms-v1.1.tsv")
NAMED_BY = "claude-opus-5-5"
COLS = ["category", "code", "hbo", "grc", "from_hbo", "from_grc", "source_hbo", "source_grc", "note", "named_by",
        "checked"]
CATS = ["relation", "time", "aspect", "line_kind", "sem_role", "ent_type"]
ENT_TYPES = ["person", "place", "group", "deity", "realia", "flora", "fauna"]
SHARE = 0.05


def c0(v):
    out, run = [], False
    for ch in v.lower():
        if "a" <= ch <= "z" or "0" <= ch <= "9":
            out.append(ch)
            run = False
        elif not run:
            out.append("_")
            run = True
    return "".join(out).strip("_")


def nfc(s):
    return U.normalize("NFC", s)


def tsv(path):
    csv.field_size_limit(1 << 30)
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


# ---- the values that occur -----------------------------------------------------------------------------------
def arc_verses():
    t = pq.read_table(os.path.join(B1, "arc", "words.parquet"), columns=["book", "chapter", "verse"]).to_pylist()
    return {(r["book"], r["chapter"], r["verse"]) for r in t}


def heb_verse_of_key():
    t = pq.read_table(os.path.join(D, "clause-columns", "hebrew.parquet"), columns=["clause_key", "ref"]).to_pylist()
    out = {}
    for r in t:
        book, cv = r["ref"].split(" ", 1)
        c, v = cv.split(".")[0].split(":")
        out[r["clause_key"]] = (book, int(c), int(v))
    return out


def dataset_values():
    """(category, lang) -> Counter of codes, over the datasets SPEC 8, 4.4, 4.5 name; lang hbo includes arc rows."""
    occ = C.defaultdict(C.Counter)
    for r in tsv(os.path.join(D, "connectives", "clauses.tsv")):
        if r["relation"]:
            occ[("relation", r["corpus"])][c0(r["relation"])] += 1
    for r in tsv(os.path.join(D, "time-aspect", "clauses.tsv")):
        for cat, col in (("time", "time"), ("aspect", "aspect"), ("line_kind", "band")):
            if r[col]:
                occ[(cat, r["corpus"])][c0(r[col])] += 1
    for r in tsv(os.path.join(D, "arg-roles", "roles.tsv")):
        if r["role"] not in ("", "-"):
            occ[("sem_role", r["corpus"])][c0(r["role"])] += 1
    for lang in ("hbo", "arc", "grc"):
        for r in tsv(os.path.join(B1, lang, "participants.tsv")):
            occ[("ent_type", "grc" if lang == "grc" else "hbo")][r["ent"].split(":")[0]] += 1
    return occ


# ---- rule T --------------------------------------------------------------------------------------------------
def marker_counts(cnt):
    """lang -> category -> (Counter (code, item), Counter code)."""
    arcv, vkey = arc_verses(), heb_verse_of_key()
    out = {lg: {} for lg in ("hbo", "grc")}
    for cat, path, vcol, icol in (("relation", "connectives/clauses.tsv", "relation", "conn"),
                                  ("sem_role", "arg-roles/roles.tsv", "role", "prep_lemma")):
        pair = {lg: C.Counter() for lg in out}
        tot = {lg: C.Counter() for lg in out}
        for r in tsv(os.path.join(D, path)):
            lg, val = r["corpus"], r[vcol]
            if val in ("", "-"):
                continue
            if lg == "hbo":
                vk = vkey.get(r["clause_key"])
                if vk is None:
                    cnt[f"hbo {cat} rows whose clause_key has no clause-columns ref"] = \
                        cnt.get(f"hbo {cat} rows whose clause_key has no clause-columns ref", 0) + 1
                    continue
                if vk in arcv:
                    k = f"hbo {cat} rows left out: verse holds Aramaic clauses in b1"
                    cnt[k] = cnt.get(k, 0) + 1
                    continue
            code = c0(val)
            tot[lg][code] += 1
            for it in sorted(set(nfc(x) for x in r[icol].split())):
                pair[lg][(code, it)] += 1
        for lg in out:
            out[lg][cat] = (pair[lg], tot[lg])
    return out


def rule_t(pair, tot):
    """-> {code: (item, rows, share)}, [items whose home is tied]."""
    home_c = C.defaultdict(C.Counter)
    for (code, it), n in pair.items():
        home_c[it][code] = n
    home, tied = {}, []
    for it, cc in sorted(home_c.items()):
        top = cc.most_common()
        if len(top) > 1 and top[0][1] == top[1][1]:
            tied.append(f"{it}: {top[0][0]} {top[0][1]} = {top[1][0]} {top[1][1]}")
            continue
        home[it] = top[0][0]
    best = {}
    for it, code in sorted(home.items()):
        n = pair[(code, it)]
        if n < SHARE * tot[code]:
            continue
        if code not in best or n > best[code][1]:
            best[code] = (it, n, n / tot[code])
    return best, tied


def lexeme_keys(lang):
    lex = tsv(os.path.join(B1, lang, "lexemes.tsv"))
    used = C.Counter()
    for m in pq.read_table(os.path.join(B1, lang, "clauses.parquet"), columns=["marks"]).column("marks").to_pylist():
        for k in json.loads(m).get("connective", []):
            used[k] += 1
    by = C.defaultdict(list)
    for r in lex:
        by[nfc(r["lemma"])].append(r)
    return by, used


def key_for(by, used, item, cat):
    rows = by.get(item, [])
    if not rows:
        return None, 0, None
    if cat == "relation":
        rows = sorted(rows, key=lambda r: (-used[r["lexeme"]], -int(r["count"]), r["lexeme"]))
    else:
        rows = sorted(rows, key=lambda r: (r["class"] != "prep", -int(r["count"]), r["lexeme"]))
    return rows[0]["lexeme"], len(rows), rows[0]["lemma"]


# ---- the named terms -----------------------------------------------------------------------------------------
# (category, code) -> {lang: (term, from, source, note)}. `text` entries here are nouns of the text (ent_type).
DT = "Dionysius Thrax, Techne grammatike"
MHG = "medieval Hebrew grammar (Abraham ibn Ezra; David Kimhi, Mikhlol): the verb tenses"


def _c(term, note):
    return (term, "coined", "", note)


NAMED = {
    # relation
    ("relation", "adversative"): {"hbo": _c("נִגּוּד", "noun from נֶגֶד 'over against'"),
                                  "grc": _c("ἐναντίωσις", "noun of ἐναντιόομαι 'oppose'")},
    ("relation", "asyndetic"): {"hbo": _c("בְּלִי חִבּוּר", "בְּלִי 'without' + חִבּוּר 'joining' (root חבר)"),
                                "grc": ("ἀσύνδετον", "tradition", "Aristotle, Rhetoric 3.12 (1413b): τὰ ἀσύνδετα", "")},
    ("relation", "causal"): {"hbo": _c("סִבָּה", "post-biblical noun 'cause' (root סבב)"),
                             "grc": _c("αἰτία", "noun 'cause'")},
    ("relation", "circumstantial"): {"hbo": _c("נְסִבָּה", "post-biblical noun 'circumstance' (root סבב)"),
                                     "grc": _c("περίστασις", "noun 'what stands around'; later rhetoric uses it for "
                                               "the circumstances of a deed; tradition not claimed")},
    ("relation", "comparison"): {"hbo": _c("דִּמּוּי", "noun of דָּמָה 'be like'"),
                                 "grc": _c("σύγκρισις", "noun 'comparing'")},
    ("relation", "complement"): {"hbo": _c("הַשְׁלָמָה", "noun of hiphil הִשְׁלִים 'complete' (root שלם)"),
                                 "grc": _c("συμπλήρωσις", "noun 'filling up'")},
    ("relation", "concession"): {"hbo": _c("הוֹדָאָה", "Rabbinic noun 'admission' (root ידה)"),
                                 "grc": _c("συγχώρησις", "noun 'granting' (συγχωρέω); later rhetoric names a figure "
                                           "so; tradition not claimed")},
    ("relation", "conditional"): {"hbo": _c("תְּנַאי", "Rabbinic noun 'condition'"),
                                  "grc": _c("ὑπόθεσις", "noun 'supposition'")},
    ("relation", "consequence"): {"hbo": _c("תּוֹלָדָה", "Rabbinic noun 'what follows' (root ילד)"),
                                  "grc": _c("ἀκολούθημα", "noun 'what follows' (ἀκολουθέω)")},
    ("relation", "continuation"): {"hbo": _c("הֶמְשֵׁךְ", "noun 'continuing' (root משך)"),
                                   "grc": _c("ἀκολουθία", "noun 'following in order'; Apollonius Dyscolus uses it "
                                             "for grammatical sequence, a different sense; tradition not claimed")},
    ("relation", "coordination"): {"hbo": _c("חִבּוּר", "noun 'joining' (root חבר)"),
                                   "grc": ("συμπλεκτικός", "tradition", DT + " 20: σύνδεσμοι συμπλεκτικοί", "")},
    ("relation", "embedded"): {"hbo": _c("מְשֻׁבָּץ", "pual participle of שבץ 'set in' (Exod 28:20)"),
                               "grc": _c("ἐγκείμενον", "participle of ἔγκειμαι 'lie within'")},
    ("relation", "inquit"): {"hbo": _c("מְבוֹא אֲמִירָה", "מָבוֹא 'entrance' + אֲמִירָה 'saying' (root אמר)"),
                             "grc": _c("εἰσαγωγὴ λόγου", "'introduction of speech'")},
    ("relation", "parallel"): {"hbo": _c("כֶּפֶל", "noun 'doubling' (root כפל); Abraham ibn Ezra speaks of doubling "
                                         "the sense; tradition not claimed"),
                               "grc": ("παρίσωσις", "tradition", "Aristotle, Rhetoric 3.9 (1410a)", "")},
    ("relation", "place"): {"hbo": _c("צִיּוּן מָקוֹם", "צִיּוּן 'marker' + מָקוֹם 'place'"),
                            "grc": _c("τοπικόν", "adjective of τόπος 'place'")},
    ("relation", "purpose"): {"hbo": _c("תַּכְלִית", "noun 'end'; post-biblical 'purpose'"),
                              "grc": _c("τέλος", "noun 'end, aim'")},
    ("relation", "relative"): {"hbo": _c("כִּנּוּי זִקָּה", "כִּנּוּי 'substitute name' + זִקָּה 'link'"),
                               "grc": ("ἄρθρον ὑποτακτικόν", "tradition", DT + " 16: the postpositive article ὅς",
                                       "")},
    ("relation", "speech"): {"hbo": _c("מַאֲמָר", "noun 'word, saying' (Esth 1:15)"),
                             "grc": _c("λεγόμενον", "passive participle of λέγω: 'what is said'")},
    ("relation", "subject"): {"hbo": _c("נוֹשֵׂא", "participle of נשא 'carry'; modern Hebrew grammar's word for the "
                                        "subject; tradition not claimed"),
                              "grc": _c("ὑποκείμενον", "participle 'what lies under'; Aristotle's word for the "
                                        "subject of predication (Categories 2), logic, not grammar; tradition not "
                                        "claimed")},
    ("relation", "temporal"): {"hbo": _c("צִיּוּן זְמַן", "צִיּוּן 'marker' + זְמַן 'time'"),
                               "grc": _c("χρονικόν", "adjective of χρόνος 'time'")},
    ("relation", "vocative"): {"hbo": _c("קְרִיאָה", "noun 'calling' (root קרא)"),
                               "grc": ("κλητική", "tradition", DT + " 12: the case κλητική", "")},
    # time
    ("time", "past"): {"hbo": ("עָבָר", "tradition", MHG, ""),
                       "grc": ("παρεληλυθώς", "tradition", DT + " 13: χρόνοι", "")},
    ("time", "present"): {"hbo": _c("הֹוֶה", "participle of הוה 'be'; the medieval grammarians name the participle "
                                    "בֵּינוֹנִי, so tradition not claimed"),
                          "grc": ("ἐνεστώς", "tradition", DT + " 13: χρόνοι", "")},
    ("time", "future"): {"hbo": ("עָתִיד", "tradition", MHG, ""),
                         "grc": ("μέλλων", "tradition", DT + " 13: χρόνοι", "")},
    ("time", "timeless"): {"hbo": _c("בְּלִי זְמַן", "בְּלִי 'without' + זְמַן 'time'"),
                           "grc": _c("ἄχρονον", "ἀ- + χρόνος: 'without time'")},
    ("time", "anterior"): {"hbo": _c("מֻקְדָּם", "hophal participle of קדם 'be before'"),
                           "grc": _c("πρότερον", "adverb 'before'; Aristotle's triad πρότερον, ἅμα, ὕστερον "
                                     "(Categories 12-13), logic, not grammar")},
    ("time", "simultaneous"): {"hbo": _c("בְּעֵת אַחַת", "'at one time'"),
                               "grc": _c("ἅμα", "adverb 'at the same time'; see πρότερον")},
    ("time", "posterior"): {"hbo": _c("מְאֻחָר", "pual participle of אחר 'be after'"),
                            "grc": _c("ὕστερον", "adverb 'after'; see πρότερον")},
    ("time", "irrealis"): {"hbo": _c("אִי מְצִיאוּת", "אִי 'not' + מְצִיאוּת 'being found, reality' (root מצא)"),
                           "grc": _c("ἀνύπαρκτον", "ἀ- + ὑπάρχω: 'not existing'")},
    # aspect
    ("aspect", "perfective"): {"hbo": _c("שָׁלֵם", "adjective 'whole'"),
                               "grc": ("ἀόριστος", "tradition", DT + " 13: a past tense", "")},
    ("aspect", "imperfective"): {"hbo": _c("בִּלְתִּי שָׁלֵם", "בִּלְתִּי 'not' + שָׁלֵם 'whole'"),
                                 "grc": ("παρατατικός", "tradition", DT + " 13: a past tense, 'extending'", "")},
    ("aspect", "progressive"): {"hbo": _c("נִמְשָׁךְ", "niphal participle of משך 'be drawn out'"),
                                "grc": _c("γινόμενον", "participle of γίνομαι: 'coming about'")},
    ("aspect", "resultative"): {"hbo": _c("תּוֹצָאָה", "noun 'outcome' (root יצא; biblical 'outgoings')"),
                                "grc": ("παρακείμενος", "tradition", DT + " 13: a past tense, 'lying at hand'", "")},
    ("aspect", "stative"): {"hbo": _c("עֲמִידָה", "noun 'standing' (root עמד)"),
                            "grc": _c("ἕξις", "noun 'having, condition' (ἔχω)")},
    # line_kind
    ("line_kind", "main"): {"hbo": _c("שַׁלְשֶׁלֶת הַסִּפּוּר", "'the chain of the story'"),
                            "grc": ("διήγησις", "tradition", "Plato, Republic 3.392d: ἁπλῆ διήγησις", "")},
    ("line_kind", "background"): {"hbo": _c("לְוַאי", "Rabbinic 'accompaniment' (root לוה)"),
                                  "grc": _c("πάρεργον", "'by-work, a thing beside the main'")},
    ("line_kind", "setting"): {"hbo": _c("פְּתִיחָה", "noun 'opening' (root פתח)"),
                               "grc": _c("ἔκθεσις", "noun 'setting out'")},
    ("line_kind", "speech"): {"hbo": _c("דִּבּוּר", "post-biblical noun 'speaking' (root דבר)"),
                              "grc": ("μίμησις", "tradition", "Plato, Republic 3.392d-394c: narration through "
                                      "the speakers' own words", "")},
    ("line_kind", "non_narrative"): {"hbo": _c("שֶׁאֵינוֹ סִפּוּר", "'what is not story'"),
                                     "grc": _c("οὐ διήγησις", "'not narration'")},
    # sem_role (named where rule T gives no preposition)
    ("sem_role", "a2"): {"hbo": _c("שְׁלִישִׁי לַפֹּעַל", "'third of the verb': the frame's third label A2, kept unnamed "
                                   "by the dataset"),
                         "grc": _c("τρίτον τοῦ ῥήματος", "'third of the verb': the frame label A2")},
    ("sem_role", "accompaniment"): {"hbo": _c("לְוָיָה", "noun 'accompanying' (root לוה)"),
                                    "grc": _c("συνοδία", "noun 'going together' (Luke 2:44)")},
    ("sem_role", "actor"): {"hbo": _c("פּוֹעֵל", "participle of פעל 'do'"),
                            "grc": _c("ὁ ἐνεργῶν", "'the one acting'; from ἐνέργεια, the active διάθεσις of " + DT +
                                      " 13")},
    ("sem_role", "addressee"): {"hbo": _c("הַנֶּאֱמָר אֵלָיו", "'the one spoken to'"),
                                "grc": _c("πρὸς ὃν ὁ λόγος", "'to whom the speech is'")},
    ("sem_role", "agent"): {"hbo": _c("עַל יְדֵי", "'by the hands of'"),
                            "grc": _c("ποιητικὸν αἴτιον", "'the making cause'")},
    ("sem_role", "basis"): {"hbo": _c("יְסוֹד", "noun 'foundation'"),
                            "grc": _c("θεμέλιον", "noun 'foundation'")},
    ("sem_role", "beneficiary"): {"hbo": _c("מְקַבֵּל טוֹבָה", "'receiver of good'"),
                                  "grc": _c("ὠφελούμενος", "passive participle of ὠφελέω: 'the one helped'")},
    ("sem_role", "circumstance"): {"hbo": _c("נְסִבָּה", "post-biblical noun 'circumstance' (root סבב)"),
                                   "grc": _c("περίστασις", "noun 'what stands around'; tradition not claimed")},
    ("sem_role", "content"): {"hbo": _c("תֹּכֶן", "noun 'measure', later 'content'"),
                              "grc": _c("περὶ οὗ", "'that about which'")},
    ("sem_role", "distribution"): {"hbo": _c("חֲלֻקָּה", "noun 'division' (root חלק)"),
                                   "grc": _c("διανομή", "noun 'distribution'")},
    ("sem_role", "experiencer"): {"hbo": _c("מַרְגִּישׁ", "participle of hiphil הִרְגִּישׁ 'feel'"),
                                  "grc": _c("ὁ αἰσθανόμενος", "'the one perceiving'")},
    ("sem_role", "goal"): {"hbo": _c("מַטָּרָה", "noun 'target'"), "grc": _c("τέρμα", "noun 'end-point'")},
    ("sem_role", "guarantor"): {"hbo": _c("עָרֵב", "noun 'surety' (Prov 6:1)"),
                                "grc": _c("ἔγγυος", "noun 'surety' (Heb 7:22)")},
    ("sem_role", "instrument"): {"hbo": _c("כְּלִי", "noun 'tool'"), "grc": _c("ὄργανον", "noun 'tool'")},
    ("sem_role", "location"): {"hbo": _c("מָקוֹם", "noun 'place'"), "grc": _c("τόπος", "noun 'place'")},
    ("sem_role", "manner"): {"hbo": _c("אֹפֶן", "noun 'manner'"), "grc": _c("τρόπος", "noun 'manner'")},
    ("sem_role", "means"): {"hbo": _c("אֶמְצָעִי", "medieval noun 'means' (root מצע)"),
                            "grc": _c("πόρος", "noun 'way, means'")},
    ("sem_role", "opposition"): {"hbo": _c("נֶגֶד", "noun 'what is over against'"),
                                 "grc": _c("ἀντίστασις", "noun 'standing against'")},
    ("sem_role", "origin"): {"hbo": _c("מוֹצָא", "noun 'going out, origin'"), "grc": _c("γένεσις", "noun 'origin'")},
    ("sem_role", "partitive"): {"hbo": _c("חֵלֶק", "noun 'part'"), "grc": _c("μέρος", "noun 'part'")},
    ("sem_role", "path"): {"hbo": _c("דֶּרֶךְ", "noun 'way'"), "grc": _c("ὁδός", "noun 'way'")},
    ("sem_role", "purpose"): {"hbo": _c("תַּכְלִית", "noun 'end'; post-biblical 'purpose'"),
                              "grc": _c("τέλος", "noun 'end, aim'")},
    ("sem_role", "reason"): {"hbo": _c("סִבָּה", "post-biblical noun 'cause' (root סבב)"),
                             "grc": _c("αἰτία", "noun 'cause'")},
    ("sem_role", "reason_participant"): {"hbo": _c("בִּגְלַל מִי", "'because of whom'"),
                                         "grc": _c("δι᾽ ὅν", "'on account of whom'")},
    ("sem_role", "recipient"): {"hbo": _c("מְקַבֵּל", "participle of piel קִבֵּל 'receive'"),
                                "grc": _c("ὁ λαμβάνων", "'the one receiving'")},
    ("sem_role", "responsibility"): {"hbo": _c("אַחֲרָיוּת", "Rabbinic noun 'responsibility' (root אחר)"),
                                     "grc": _c("εὔθυνα", "noun 'account, liability'")},
    ("sem_role", "result"): {"hbo": _c("הַנַּעֲשֶׂה", "'what is made' (niphal participle of עשה)"),
                             "grc": _c("ἀποτέλεσμα", "noun 'outcome'")},
    ("sem_role", "separation"): {"hbo": _c("הַבְדָּלָה", "noun 'separating' (root בדל)"),
                                 "grc": _c("χωρισμός", "noun 'separation'")},
    ("sem_role", "source"): {"hbo": _c("מָקוֹר", "noun 'spring, source'"), "grc": _c("πηγή", "noun 'spring'")},
    ("sem_role", "source_event"): {"hbo": _c("מְקוֹר מַעֲשֶׂה", "'source of a deed'"),
                                   "grc": _c("ἀφορμή", "noun 'starting point'")},
    ("sem_role", "specification"): {"hbo": _c("פֵּרוּט", "Rabbinic noun 'specifying' (root פרט)"),
                                    "grc": _c("διορισμός", "noun 'defining'")},
    ("sem_role", "standard"): {"hbo": _c("מִדָּה", "noun 'measure'"), "grc": _c("κανών", "noun 'rule, measure'")},
    ("sem_role", "state"): {"hbo": _c("מַצָּב", "noun 'standing place', later 'state' (root נצב)"),
                            "grc": _c("κατάστασις", "noun 'condition'")},
    ("sem_role", "time"): {"hbo": _c("זְמַן", "noun 'time'"), "grc": _c("χρόνος", "noun 'time'")},
    ("sem_role", "undergoer"): {"hbo": _c("נִפְעָל", "niphal participle of פעל: 'the one acted on'"),
                                "grc": _c("ὁ πάσχων", "'the one undergoing'; from πάθος, the passive διάθεσις of " +
                                          DT + " 13")},
    ("sem_role", "viewpoint"): {"hbo": _c("בְּעֵינֵי", "'in the eyes of'"), "grc": _c("ὄψις", "noun 'sight'")},
    # ent_type: nouns of the text (key looked up in b1)
    ("ent_type", "person"): {"hbo": ("אָדָם", "text", "", ""), "grc": ("ἄνθρωπος", "text", "", "")},
    ("ent_type", "place"): {"hbo": ("מָקוֹם", "text", "", ""), "grc": ("τόπος", "text", "", "")},
    ("ent_type", "group"): {"hbo": ("עַם", "text", "", ""), "grc": ("πλῆθος", "text", "", "")},
    ("ent_type", "deity"): {"hbo": ("אֱלֹוהַּ", "text", "", ""), "grc": ("θεός", "text", "", "")},
    ("ent_type", "realia"): {"hbo": ("כְּלִי", "text", "", ""), "grc": ("πρᾶγμα", "text", "", "")},
    ("ent_type", "flora"): {"hbo": ("צֶמַח", "text", "", ""), "grc": ("φυτεία", "text", "", "")},
    ("ent_type", "fauna"): {"hbo": ("חַיָּה", "text", "", ""), "grc": ("ζῷον", "text", "", "")},
}


def make_rows(cnt, ex):
    occ = dataset_values()
    codes = {cat: set() for cat in CATS}
    for (cat, lg), cc in occ.items():
        codes[cat] |= set(cc)
    codes["ent_type"] |= set(ENT_TYPES)
    mk = marker_counts(cnt)
    rule = {}
    for lg in ("hbo", "grc"):
        by, used = lexeme_keys(lg)
        for cat in ("relation", "sem_role"):
            best, tied = rule_t(*mk[lg][cat])
            ex[f"{lg} {cat} rule T: items whose home value is tied (no home)"] = tied
            for code, (it, n, share) in sorted(best.items()):
                key, nk, lemma = key_for(by, used, it, cat)
                if key is None:
                    ex[f"{lg} {cat} rule T: item with no b1 lexeme (value named instead)"].append(f"{code} {it}")
                    continue
                if nk > 1:
                    ex[f"{lg} {cat} rule T: item with two or more b1 lexemes (key chosen by usage, count)"].append(
                        f"{it} -> {key} ({nk})")
                rule[(cat, code, lg)] = (lemma, key, n, share)
                cnt[f"{lg} {cat} rule T {code}"] = f"{it} {key} {n}/{mk[lg][cat][1][code]} ({share:.3f})"
    rows = []
    for cat in CATS:
        order = ENT_TYPES if cat == "ent_type" else sorted(codes[cat])
        for code in order:
            row = {"category": cat, "code": code, "named_by": NAMED_BY, "checked": ""}
            notes = []
            for lg in ("hbo", "grc"):
                if (cat, code, lg) in rule:
                    it, key, n, share = rule[(cat, code, lg)]
                    term, frm, src, note = it, "text", key, ""
                else:
                    if (cat, code) not in NAMED:
                        raise SystemExit(f"stage 14: no term for {cat} {code} ({lg})")
                    term, frm, src, note = NAMED[(cat, code)][lg]
                    if frm == "text":
                        by, used = lexeme_keys(lg)
                        key, nk, lemma = key_for(by, used, nfc(term), cat)
                        if key is None:
                            raise SystemExit(f"stage 14: {lg} text term {term} is no b1 lexeme")
                        src, term = key, lemma
                # a text term is the b1 lemma as written (MACULA's lemmas are not all NFC); named terms are NFC
                row[lg], row[f"from_{lg}"], row[f"source_{lg}"] = (term if frm == "text" else nfc(term)), frm, src
                if note:
                    notes.append(f"{lg}: {note}")
            row["note"] = "; ".join(notes)
            rows.append(row)
    for cat in CATS:
        for lg in ("hbo", "grc"):
            seen = C.Counter(nfc(r[lg]) for r in rows if r["category"] == cat)
            dup = [t for t, n in seen.items() if n > 1]
            if dup:
                raise SystemExit(f"stage 14: {cat} {lg} terms shared by two codes: {dup}")
    for r in rows:
        for k in COLS:
            if "\t" in r[k] or "\n" in r[k]:
                raise SystemExit(f"stage 14: tab or newline in {r}")
    return rows


def render(rows):
    return "\t".join(COLS) + "\n" + "".join("\t".join(r[k] for k in COLS) + "\n" for r in rows)


def write_master():
    cnt, ex = {}, C.defaultdict(list)
    rows = make_rows(cnt, ex)
    with open(MASTER, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(rows))
    print(f"{len(rows)} rows -> {os.path.normpath(MASTER)}")


def build(outdir, langs, counts):
    """Stage 14: copy the master into <build>/<lang>/terms.tsv unchanged, after checking its rule-T cells."""
    ex = C.defaultdict(list)
    rows = make_rows(counts, ex)
    with open(MASTER, encoding="utf-8", newline="") as fh:
        master = fh.read()
    def unchecked(text):  # a person's mark in `checked` is not the builder's to judge
        return [ln.rsplit("\t", 1)[0] for ln in text.split("\n")]
    if unchecked(master) != unchecked(render(rows)):
        raise SystemExit("stage 14: the master terms.tsv differs from rule T and NAMED; rerun --write-master")
    for lg in langs:
        os.makedirs(os.path.join(outdir, lg), exist_ok=True)
        shutil.copyfile(MASTER, os.path.join(outdir, lg, "terms.tsv"))
    by = C.Counter()
    for r in rows:
        for lg in ("hbo", "grc"):
            by[f"{lg} {r['from_' + lg]}"] += 1
    counts["terms rows"] = len(rows)
    counts["terms rows by category"] = dict(C.Counter(r["category"] for r in rows))
    counts["terms by from"] = dict(sorted(by.items()))
    return ex


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-master", action="store_true")
    if ap.parse_args().write_master:
        write_master()
