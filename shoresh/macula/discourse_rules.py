"""Text-level hierarchy of Hebrew clauses (discourse_parent, relation, discourse_attach, tree_depth, text_depth), derived by rule from
MACULA Hebrew features only.

MACULA has no clause-to-clause relations above the verse (a MACULA sentence is one verse; main clauses in a verse are siblings), so the
hierarchy is derived, not passed through. Inputs per clause, all MACULA (CC BY 4.0) plus person from the lexeme spine (same source):
verb form (`wtype`: wayyiqtol, weqatal, qatal, yiqtol, imperative, infinitive, participle ...), the clause's first words (conjunction,
relative, preposition), the verb's lemma (verbs of speaking, oaths), the clause's rule and role, and the MACULA tree (`parent`, phrase
nesting). No BHSA input. The segmentation gives a clause-opening subordinator or relative to the clause it opens.

ONE TREE. Every clause has a discourse_parent (an earlier clause, or for a protasis the later apodosis) and a relation on that link,
except the first clause of a line: a book, a chapter, a new Psalm, and in poetry and prophecy a chapter that starts after a paragraph
mark (ס/פ). Inside a chapter a paragraph mark closes only the speeches opened by כֹּה אָמַר or a command to say; a speech opened by a
narrative speaking clause (Amos 1:2 "וַיֹּאמַר", "וַיְהִי דְבַר־יְהוָה אֵלַי לֵאמֹר") stays open over ס/פ until the narrative resumes.

  LINES. The narrative is one line; a speech opens a line of its own under its speaking clause. Main clauses chain along their line:
    continuation   a wayyiqtol or weqatal; in speech also a yiqtol, qatal, imperative, jussive or cohortative with וְ   (CHAIN_FORMS).
                   A chain clause that names its subject (MACULA rule with S) starts a new step: it hangs on the nearest earlier
                   chain clause that also names one (over continuation, coordination and parallel links), and the subjectless
                   clauses after it fill that step in (Gen 22:5 וַיֹּאמֶר אַבְרָהָם → 22:4 וַיִּשָּׂא אַבְרָהָם).
    coordination   any other clause with וְ
    asyndetic      no conjunction (poetry, lists, a new address)
    speech         the first clause of a speech, on its speaking or לֵאמֹר clause
  SPEECHES open at a clause whose verb is a verb of speaking (Hebrew אָמַר, דִּבֶּר, צִוָּה, עָנָה, שָׁאַל: finite; Aramaic אֲמַר, עֲנָה,
    מְלַל: finite or participle) or at a לֵאמֹר clause.
    - עָנָה opens one only when an אָמַר clause follows in the verse (Ps 3:5 "he answered me" opens none).
    - Indirect speech opens none: a speaking clause whose only follow-up in the verse is a לְ + infinitive (Dan 2:12 "and he commanded to
      destroy") gets the infinitive as a complement.
    - The narrative resumes, closing all speeches, at a 3rd-person wayyiqtol; in Aramaic at a 3rd-person speaking clause in qatal or
      participle ("the king answered and said", which opens the next speech; a yiqtol "let the king tell" is speech content), or at אֱדַיִן / כָּל־קֳבֵל דְּנָה with a named actor (not inside a retold dream).
    - Inside a speech only a narrated speaking clause (3rd person wayyiqtol/qatal, or a participle) or a לֵאמֹר opens a nested speech;
      a nested speech ends after the verse following the one it opened in.
    - In poetry a participle of saying (Ps 3:3 "many say") opens a quotation that ends with its verse or at סֶלָה.
    - שָׁאַל with an object or with לְשָׁלוֹם quotes nothing and opens no speech.
    - The messenger formula כֹּה אָמַר (יְהוָה), and inside a speech a command to say something without an object of its own (אֱמֹר,
      וְאָמַרְתָּ אֲלֵהֶם, כֹּה תֹאמַר; not Dan 2:4 "אֱמַר חֶלְמָא"),
      open a speech that lasts to the next paragraph mark (ס/פ), nested if inside a speech; in poetry only to the end of the verse or סֶלָה.
      A command to say that comes at the start of a speech (in its first two verses: Lev 1:2 "דַּבֵּר אֶל־בְּנֵי יִשְׂרָאֵל וְאָמַרְתָּ
      אֲלֵהֶם") carries the rest of that speech: it lasts as long as the speech, over paragraph marks.
    - A 1st-person wayyiqtol (וָאֹמַר) resumes the narrative when an open speech was addressed to "me" (Jer 1:4 "וַיְהִי דְבַר־יְהוָה
      אֵלַי לֵאמֹר"): the narrator speaks in the first person. In a speech addressed to someone else it is a retelling (Gen 24:42).
    inquit         a 3rd-person speaking clause without וְ that is not the first clause of its verse (Isa 40:1 "יֹאמַר אֱלֹהֵיכֶם"), and a formula
                   such as נְאֻם יְהוָה: it hangs on the clause before it on its line, opens no speech, and the line goes on past it.
    asyndetic links hang on the head of the run before: from the previous main clause, up over continuation, coordination and parallel
    links within that clause's verse (not over an earlier asyndetic link).
    parallel       a turn that repeats the opening of the turn before (the same speaking verb and form, without וְ: Dan 2:5, 2:8 עָנֵה מַלְכָּא), and
                   the second and later clauses of a series of subordinate clauses with the same opener (Isa 40:2 כִּי, כִּי, כִּי; Lev 1:3,
                   1:10, 1:14 אִם; within a chapter for conditionals, else adjacent): each on the one before. Flat for both depths.
  SUBORDINATE clauses (opened by a subordinator; an infinitive clause; a participle clause without the article and without a subject,
    i.e. MACULA's rule has no S) hang on the nearest main clause before them in the verse (formulas are skipped). A subordinate clause
    that opens a speech is the speech's first clause (Ruth 1:10). With none before them they hang on the next main clause, except a
    verse-initial Aramaic דִּי or a verse-initial participle, which look back to the previous verse's line. Relation by the opener:
    causal (כִּי after its main clause, יַעַן, עֵקֶב, Aramaic כָּל־קֳבֵל דִּי, verse-initial דִּי), purpose (לְמַעַן, פֶּן, לְ + infinitive),
    temporal (כַּאֲשֶׁר, עַד, טֶרֶם, בְּ/כְּ + infinitive), conditional (אִם, לוּ, לוּלֵא, אִלּוּ, Aramaic הֵן, and a כִּי before its main
    clause: casuistic law), relative (אֲשֶׁר, דִּי, שֶׁ), circumstantial (participle), complement (infinitive without a preposition).
  PROPHETIC SPEECH (opened by כֹּה אָמַר with God as the speaker, a command to say, or the word-event formula with its לֵאמֹר): a wayyiqtol
    inside it is retold history (Jer 2:5 "וַיֵּלְכוּ אַחֲרֵי הַהֶבֶל וַיֶּהְבָּלוּ"; Ezek 16, 20, 23; Deut 26:5), not the narrative resuming.
    A human messenger formula (Isa 37:3 "כֹּה אָמַר חִזְקִיָּהוּ", Exod 5:10 "כֹּה אָמַר פַּרְעֹה") opens an ordinary speech. The narrative
    resumes only with a narrative frame: a new word-event formula (which always resumes it), a wayyiqtol of saying with a named or
    definite speaker ("וַיֹּאמֶר יְהוָה אֵלַי", Hag 2:12 "וַיַּעֲנוּ הַכֹּהֲנִים"), a 3rd-person wayyiqtol whose subject is headed by a
    proper noun or names God, without a 1st/2nd-person pronoun (Jonah 1:3 "וַיָּקָם יוֹנָה", Isa 37:8 "וַיָּשָׁב רַב־שָׁקֵה"; not Ezek 23:11
    "וַתֵּרֶא אֲחוֹתָהּ אָהֳלִיבָה"), a dated וַיְהִי or a וַיְהִי with a temporal clause (Ezek 11:13 "וַיְהִי כְּהִנָּבְאִי"), the
    compliance formula "וַיַּעֲשׂוּ כֵן", a new chapter, or the narrator's own "וָאֹמַר" (1st person, without a 3rd-person addressee and
    not "I said to pour out": Ezek 20:8).
    In the books whose narrator speaks in the first person (SCOPE narrator_frames), "וַיֹּאמֶר אֵלַי" and God's spirit or glory acting
    on "me" ("וַתִּפֹּל עָלַי רוּחַ יְהוָה") are narrative frames when the outermost speech is addressed to "me".
    QUOTATIONS end with their verse: those introduced by a 2nd-person or future verb of saying without an object (Mal 1:5 "וְאַתֶּם
    תֹּאמְרוּ", Mal 1:6 "וַאֲמַרְתֶּם"), by בְּ + the infinitive of אָמַר (בֶּאֱמָרְכֶם), and by a כִּי/אִם/פֶּן clause with a verb of saying
    (Mal 1:4 "כִּי־תֹאמַר אֱדוֹם"). A messenger formula ends an open quotation. "וְאָמַרְתָּ" is a command to say only with an addressee
    (אֶל, לְ) or after a command; otherwise it is such a quotation.
    COMMANDED SPEECH: a לֵאמֹר under a command (Jer 2:2 "וְקָרָאתָ בְאָזְנֵי יְרוּשָׁלִַם לֵאמֹר", Lev 4:2 "דַּבֵּר ... לֵאמֹר") opens a
    commanded speech like וְאָמַרְתָּ אֲלֵהֶם. A new command to the prophet to speak (Jer 7:27 "וְדִבַּרְתָּ אֲלֵיהֶם", "הִנָּבֵא") returns
    to the line that gave the earlier command. A nested speech also ends at a 3rd-person וְ-qatal/wayyiqtol opening the next verse
    (Jer 7:24 "וְלֹא שָׁמְעוּ" after the command quoted in 7:23).
    adversative    "כִּי אִם" right after a negated clause: "not … but" (Jer 7:22-23), on that clause; flat.
    consequence    לָכֵן / עַל־כֵּן "therefore", on the main clause before it, one level deeper (BHSA's convention).
    A "for" (כִּי) in poetry and prophecy that opens its verse, or has no main clause before it in its verse, looks back to the clause
    before; a series of כִּי clauses continues over a וְ-clause that continues the one before (Mal 1:11). A clause meant to hang forward
    that finds nothing to hang on (or only a clause inside itself) hangs on the clause before it.
    An inquit may follow a subordinate clause in its verse (Mal 1:11 "אָמַר יְהוָה צְבָאוֹת" after two כִּי clauses); it opens no speech.
  OATHS (נִשְׁבַּעְתִּי, כֹּה יַעֲשֶׂה … וְכֹה יֹסִיף, חַי ...): while the speech goes on, a following כִּי/אִם clause that opens its verse or
    follows the oath directly is its complement (the content of the oath), and a reason clause (יַעַן, עֵקֶב) is causal on the oath.
  POETRY AND PROPHECY: a וְ-clause right after a subordinate clause in the same verse (no main clause between), or after such a
    continuation (Jer 2:5 "וַיֶּהְבָּלוּ"), continues it, with continuation (wayyiqtol, weqatal) or coordination on it (Prov 8:7 "וְתוֹעֲבַת שְׂפָתַי רֶשַׁע" on "כִּי־אֱמֶת יֶהְגֶּה חִכִּי"). In poetry (Job, Psalms, Proverbs, Song,
    Lamentations) a verse-initial asyndetic clause whose first word (the lemmas of all its parts) repeats the first word of an earlier verse-initial clause on
    its line hangs on that one as parallel: a stanza head (Job 3:20 לָמָּה → 3:11 לָמָּה; Prov 8:10 קְחוּ → 8:6 שִׁמְעוּ). Imperatives
    of hearing (שִׁמְעוּ, הַאֲזִינוּ, הָבִינוּ, קְחוּ) count as one opening.
  vocative       an address (MACULA rule Np2CL with a noun or participle, in a verse with an imperative or a 2nd-person verb): on the
                 nearest main clause before it in the verse, else on the next.
  circumstantial a verbless clause opened by וְ + a non-verb right after a wayyiqtol main clause of its verse, in narrative (not in the
                 poetic books, where such a clause is the second half of a couplet: coordination).
  EMBEDDED clauses keep their MACULA parent; relation relative (in a noun phrase, discourse_attach = the antecedent's first word),
    complement (MACULA role o/s/p, or לֵאמֹר), purpose/temporal (לְ / בְּ כְּ + infinitive), or embedded.

CONDITIONALS: the protasis hangs under its apodosis, relation conditional. A client that wants the other direction inverts the
conditional links whose protasis comes before the clause it hangs on (a protasis after its main clause is left as it is): the protasis takes the apodosis's parent and relation, and the apodosis hangs
under the protasis with relation conditional.

A wayyiqtol with a 1st- or 2nd-person pronoun ("וַתִּפָּעֶם רוּחִי", Dan 2:3) stays in its speech.
CONDITIONALS in a series: the inversion applies to the first clause of the series only; the others stay parallel on it.

RULE SCOPES: the rules added in 0.11 are named in SCOPE, each with the books it applies to ("all", "poetic", "poetry", "prose", "none",
or a list of books). Only narrator_frames is limited (to the books with a first-person narrator).

DEPTHS: tree_depth counts every link up to the root of the line, except parallel.
text_depth (the flat view) does not count continuation, coordination, asyndetic, inquit, parallel, vocative and circumstantial links,
nor links with discourse_rule embedded_flat: an embedded clause with no opener (conjunction, relative, preposition), no infinitive, and a
participle or no verb (Deut 28:25 "נִגָּף לִפְנֵי אֹיְבֶיךָ"), which stands next to its parent clause. An address and a circumstantial
clause stay on the line of the clause they belong to; the relation still says what they are. text_depth counts only the links whose relation is not in FLAT
(continuation, coordination, asyndetic, inquit): the flat view, where a chain stays on one level.
"""
from __future__ import annotations

import unicodedata


def _n(s: str | None) -> str:
    return unicodedata.normalize("NFC", s or "")


RULES_VERSION = "0.11"

SPEAK = {"559", "1696", "6680", "6030", "7592",          # אָמַר, דָּבַר, צָוָה, עָנָה, שָׁאַל (Strong's, MACULA strong column)
         "560", "6032", "4449"}                           # Aramaic אֲמַר, עֲנָה, מְלַל
LEMOR = "559"                                             # לֵאמֹר = infinitive construct of אָמַר with לְ
AMAR = {"559", "560"}
ANSWER = {"6030", "6032"}
OATH_VERBS = {"7650"}                                     # שָׁבַע (1st person)
KO_VERBS = {"6213", "3254"}                               # כֹּה יַעֲשֶׂה … וְכֹה יֹסִיף
FINITE = {"wayyiqtol", "weqatal", "qatal", "yiqtol", "imperative", "jussive", "cohortative"}
CHAIN_FORMS = {"wayyiqtol", "weqatal"}
CHAIN_FORMS_SPEECH = {"yiqtol", "qatal", "imperative", "jussive", "cohortative"}
INFINITIVE = {"infinitive construct", "infinitive absolute"}
PARTICIPLE = {"participle active", "participle passive"}
FLAT = {"continuation", "coordination", "asyndetic", "inquit", "parallel",    # add no level to text_depth
        "vocative", "circumstantial", "adversative"}
FLAT_RULES = {"embedded_flat"}                                                 # links set by these rules add no level to text_depth
TREE_FLAT = {"parallel"}                                                       # add no level to tree_depth
RELATIONS = ["continuation", "coordination", "asyndetic", "speech", "inquit", "causal", "purpose", "temporal", "conditional", "relative",
             "circumstantial", "complement", "vocative", "embedded", "parallel", "adversative", "consequence"]

_SUB_KIND = {"כִּי": "causal", "יַעַן": "causal", "עֵקֶב": "causal", "אִם": "conditional", "לוּ": "conditional", "לוּלֵא": "conditional",
             "אִלּוּ": "conditional", "לְמַעַן": "purpose", "פֶּן": "purpose", "עַד": "temporal", "טֶרֶם": "temporal",
             "בְּטֶרֶם": "temporal", "תַּחַת": "causal"}
SUB_KIND = {_n(k): v for k, v in _SUB_KIND.items()}
SUB_CJ = set(SUB_KIND)
SUB_ARC = {_n("הֵן")}                                     # Aramaic "if" (Hebrew הֵן is "behold")
REL = {_n(x) for x in ("אֲשֶׁר", "שֶׁ", "דִּי", "זוּ")}
DI = _n("דִּי")
WAW, BE, KE, LE = _n("וְ"), _n("בְּ"), _n("כְּ"), _n("לְ")
KI, IM, PEN = _n("כִּי"), _n("אִם"), _n("פֶּן")
ADAYIN, QABEL, KOL, DENA = _n("אֱדַיִן"), _n("קֳבֵל"), _n("כֹּל"), _n("דְּנָה")
KO, HAY, MELEK = _n("כֹּה"), _n("חַי"), _n("מֶלֶךְ")
FORMULA = {_n("נְאֻם")}
SELAH = _n("סֶלָה")
SHALOM = _n("שָׁלוֹם")
LAKHEN, AL, KEN = _n("לָכֵן"), _n("עַל"), _n("כֵּן")
TIME_WORDS = {_n(x) for x in ("יוֹם", "שָׁנָה", "חֹדֶשׁ", "עֵת", "אַחַר", "בֹּקֶר", "עֶרֶב", "לַיְלָה")}
HEAR = {"8085", "238", "995", "3947"}                     # שִׁמְעוּ, הַאֲזִינוּ, הָבִינוּ, קְחוּ: imperatives of hearing count as one opening
ADDRESS = {"413", "3807"}                                 # אֶל, לְ: the addressee of a verb of saying
DIVINE = {"3068", "3069", "136", "430", "410", "433", "6918"}   # יְהוָה, יֱהֹוִה, אֲדֹנָי, אֱלֹהִים, אֵל, אֱלוֹהַּ, קָדוֹשׁ (יִשְׂרָאֵל)
PROCLAIM = {"559", "1696", "5012"}                        # אָמַר, דִּבֶּר, נִבָּא: a command to the prophet to speak (not קָרָא: Lev 25:10
                                                          # "וּקְרָאתֶם דְּרוֹר" is law, not a command to speak)


# Named rules and where they apply: "all", "none", "poetic" (poetry and the prophets), "poetry", "prose" (all other books), or a list
# of USFM book codes. Setting one to "none" turns it off, to see what it changes.
SCOPE: dict[str, object] = {
    "nested_speech_ends_at_3rd_person": "all",   # Jer 7:24
    "quotation_lines": "all",                    # Mal 1:4-13, 1:5 "וְאַתֶּם תֹּאמְרוּ", בֶּאֱמָרְכֶם, "כִּי־תֹאמַר אֱדוֹם"
    "command_needs_addressee": "all",            # Mal "וַאֲמַרְתֶּם" is a quotation, "וְאָמַרְתָּ אֲלֵיהֶם" a command
    "prophetic_needs_god": "all",                # Isa 37:3 "כֹּה אָמַר חִזְקִיָּהוּ"
    "proclaim_returns": "all",                   # Jer 7:27 "וְדִבַּרְתָּ אֲלֵיהֶם"
    "commanded_lemor": "all",                    # Jer 2:2 "וְקָרָאתָ ... לֵאמֹר"
    # books whose narrator speaks in the first person (Ezek 11:5 "וַתִּפֹּל עָלַי רוּחַ יְהוָה וַיֹּאמֶר אֵלַי"); elsewhere "אֵלַי" in a
    # speech is a character retelling (Deut 2:9 "וַיֹּאמֶר יְהוָה אֵלַי" in Moses' speech)
    "narrator_frames": ["ISA", "JER", "EZK", "HOS", "AMO", "MIC", "HAB", "ZEC", "DAN", "EZR", "NEH"],
    "narrative_frames": "all",                   # in a speech: Ezek 11:13 "וַיְהִי כְּהִנָּבְאִי", Hag 2:12 "וַיַּעֲנוּ הַכֹּהֲנִים", Exod 8:13 "וַיַּעֲשׂוּ־כֵן"
    "word_event_resumes": "all",                 # Ezek 21:6
    "inquit_after_subordinate": "all",           # Mal 1:11
    "ki_series_and_look_back": "all",            # Mal 1:11; Jer 2:5
}


def active(name: str, c: dict) -> bool:
    sc = SCOPE.get(name, "all")
    if sc in ("all", "none"):
        return sc == "all"
    if sc == "poetic":
        return bool(c.get("poetic"))
    if sc == "poetry":
        return bool(c.get("poetry"))
    if sc == "prose":
        return not c.get("poetic")
    return c["verse"][0] in sc


def is_subordinator(t) -> bool:
    lem = _n(t["lemma"])
    return lem in SUB_CJ or lem in REL or (lem in SUB_ARC and t["wlang"] == "A")


def _strong(t) -> str:
    s = (t["strong"] or "").lstrip("0")
    return "".join(ch for ch in s if ch.isdigit())


def features(toks: list, person: dict[str, str], rule: str | None = None, role: str | None = None,
             subj: list[tuple[int, int]] | None = None) -> dict:
    """toks: MACULA word rows of the clause's words (whole words, as segmented), text order. rule, role: the MACULA clause node's.
    subj: word seq ranges (lo, hi) of the clause's subject phrases (MACULA role s)."""
    verbs = [t for t in toks if t["class"] == "verb"]
    subject = [t for t in toks if t["role"] == "s" or any(lo <= t["seq"] <= hi for lo, hi in subj or ())]
    finite = [t for t in verbs if t["wtype"] in FINITE]
    v = finite[0] if finite else (verbs[0] if verbs else None)
    aramaic = sum(t["wlang"] == "A" for t in toks) * 2 > len(toks)
    waw = bool(toks) and _n(toks[0]["lemma"]) == WAW
    lead = [t for t in toks if not (t["class"] == "cj" and _n(t["lemma"]) == WAW)]
    l0 = _n(lead[0]["lemma"]) if lead else ""
    l1 = _n(lead[1]["lemma"]) if len(lead) > 1 else ""
    l2 = _n(lead[2]["lemma"]) if len(lead) > 2 else ""
    # the subordinator must open the clause (Aramaic דִּי inside a clause is the genitive particle: "שָׁקוֹהִי דִּי פַרְזֶל")
    sub_kind = None
    if l0 in SUB_CJ or (l0 in SUB_ARC and lead[0]["wlang"] == "A"):
        sub_kind = "conditional" if l0 in SUB_ARC else SUB_KIND[l0]
        if l0 == KI and l1 == _n("יַעַן"):
            sub_kind = "causal"
    elif l0 in REL:
        sub_kind = "relative"
    elif lead and lead[0]["class"] == "prep" and l1 in REL:
        sub_kind = "temporal"                                # כַּאֲשֶׁר, מֵאֲשֶׁר
    # Aramaic כָּל־קֳבֵל (MACULA: כְּ + לְ + קֳבֵל) + דִּי "because" / + דְּנָה "therefore" (a narrative step)
    qi = next((i for i, t in enumerate(lead[:4]) if _n(t["lemma"]) == QABEL), None)
    after_qabel = _n(lead[qi + 1]["lemma"]) if qi is not None and qi + 1 < len(lead) else ""
    if sub_kind is None and after_qabel == DI:
        sub_kind = "causal"
    has_object = "O" in (rule or "").split("-")
    speak = bool(v) and _strong(v) in SPEAK and (bool(finite) or (aramaic and v["wtype"] in PARTICIPLE)) and not (
        _strong(v) == "7592" and (has_object or any(_n(t["lemma"]) == SHALOM for t in toks)))    # "מַיִם שָׁאַל", "שָׁאַל לְשָׁלוֹם"
    # a participle is a clause of its own (nominal clause, main) when it has the article or a subject of its own
    ptc_free = bool(v) and v["wtype"] in PARTICIPLE and not finite and not speak and not (
        any(t["class"] == "art" and (t["verse"], t["word"]) == (v["verse"], v["word"]) for t in toks) or any(t["role"] == "s" for t in toks)
        or "S" in (rule or "").split("-"))
    inf = bool(verbs) and not finite and not speak and verbs[0]["wtype"] in INFINITIVE
    if sub_kind is None and inf:
        before = [t for t in toks if (t["verse"], t["word"]) == (verbs[0]["verse"], verbs[0]["word"]) and t["class"] == "prep"]
        p = _n(before[0]["lemma"]) if before else ""
        sub_kind = "purpose" if p == LE else "temporal" if p in (BE, KE) else "complement"
    elif sub_kind is None and ptc_free and waw:            # without וְ a participle clause is a main clause (Dan 2:21-22, a hymn's
        sub_kind = "circumstantial"                         # predicates on God)
    actor = any(t["wtype"] == "proper" or _n(t["lemma"]) == MELEK for t in toks)
    noun_head = bool(lead) and not finite and (lead[0]["class"] == "noun" or lead[0]["wtype"] in PARTICIPLE)
    # לֵאמֹר is לְ + the infinitive of אָמַר; another preposition (בֶּאֱמָרְכֶם "in that you say") introduces a quotation of its own
    say_inf = [t for t in verbs if _strong(t) == LEMOR and t["wtype"] == "infinitive construct"]
    say_prep = [_n(t["lemma"]) for t in toks if say_inf and t["class"] == "prep" and (t["verse"], t["word"]) == (say_inf[0]["verse"], say_inf[0]["word"])]
    lemor = bool(say_inf) and say_prep[:1] == [LE]
    addressee = any(t["class"] == "prep" and _strong(t) in ADDRESS for t in toks)
    return {"verb": _strong(v) if v else None, "form": v["wtype"] if v else None, "person": person.get(v["key"]) if v else None,
            "aramaic": aramaic, "waw": waw, "speak": speak, "sub_kind": sub_kind, "lead": l0, "di_first": l0 == DI,
            "participle": ptc_free,
            "lemor": lemor,
            # a quotation: בֶּאֱמָרְכֶם; a 2nd-person verb of saying without an object (Mal 1:5 "וְאַתֶּם תֹּאמְרוּ"), not כֹּה תֹאמַר
            "quote_say": (bool(say_inf) and not lemor and bool(say_prep)) or (bool(v) and _strong(v) in AMAR and bool(finite) and not has_object
                          and person.get(v["key"]) == "second" and v["wtype"] in ("weqatal", "yiqtol") and l0 != KO),
            "say_any": bool(v) and _strong(v) in AMAR and bool(finite) and not has_object,
            "addressee": addressee,
            "inf_le": inf and sub_kind == "purpose",
            "ptc_saying": bool(v) and not finite and v["wtype"] in PARTICIPLE and _strong(v) in AMAR,
            "formula": l0 in FORMULA, "selah": any(_n(t["lemma"]) == SELAH for t in toks),
            # אֱדַיִן / כָּל־קֳבֵל דְּנָה start a narrative step when they name an actor; inside a retold dream they do not (Dan 2:35)
            "step": actor and (l0 == ADAYIN or (l0 in (BE,) and l1 == ADAYIN) or after_qabel == DENA),
            "oath": (bool(v) and _strong(v) in OATH_VERBS and person.get(v["key"]) == "first") or l0 == HAY
                    or (l0 == KO and bool(v) and _strong(v) in KO_VERBS),
            "vocative": (rule or "") == "Np2CL" and noun_head,
            "imperative": bool(v) and v["wtype"] == "imperative",
            "second": bool(v) and (v["wtype"] == "imperative" or person.get(v["key"]) == "second"),
            # a 1st/2nd-person pronoun in a wayyiqtol clause ("וַתִּפָּעֶם רוּחִי") marks it as part of a speech, not the narrative
            "pron12": any(t["class"] == "pron" and person.get(t["key"]) in ("first", "second") for t in toks),
            "pron2": any(t["class"] == "pron" and person.get(t["key"]) == "second" for t in toks),
            "pron1": any(t["class"] == "pron" and person.get(t["key"]) == "first" for t in toks),
            "pron3": any(t["class"] == "pron" and person.get(t["key"]) == "third" for t in toks),
            "l1": l1, "negated": any(t["wtype"] == "negative" for t in toks),
            "proper": any(t["wtype"] == "proper" for t in toks),
            # an explicit subject headed by a proper noun ("רַב־שָׁקֵה"; not Ezek 23:11 "אֲחוֹתָהּ אָהֳלִיבָה" or 31:9 "כָּל־עֲצֵי־עֵדֶן" in
            # an allegory), or one with God in it ("כְּבוֹד יְהוָה"). A definite noun is not enough: retold history names its actors
            # the same way (Ezek 34:8 "וַיִּרְעוּ הָרֹעִים אוֹתָם")
            "named_subject": bool(subject) and (subject[0]["wtype"] == "proper" or any(_strong(t) in DIVINE for t in subject)),
            "divine": any(_strong(t) in DIVINE for t in subject),
            # the compliance formula "וַיַּעַשׂ כֵּן", "וַיַּעֲשׂוּ כֵּן": the narrative reports that a command was carried out
            "compliance": bool(v) and _strong(v) == "6213" and v["wtype"] == "wayyiqtol" and any(_n(t["lemma"]) == KEN for t in toks),
            "def_subject": bool(subject) and (subject[0]["wtype"] == "proper" or subject[0]["class"] == "art"),
            # the word-event formula (וַיְהִי דְבַר־יְהוָה אֵלַי; הַדָּבָר אֲשֶׁר הָיָה אֶל־יִרְמְיָהוּ מֵאֵת יְהוָה) and a dated וַיְהִי
            "word_event": bool(v) and _strong(v) == "1961" and any(_strong(t) in ("1697", "3068") for t in toks),
            "time_wayehi": bool(v) and _strong(v) == "1961" and v["wtype"] == "wayyiqtol" and any(_n(t["lemma"]) in TIME_WORDS for t in toks),
            # לָכֵן / עַל־כֵּן "therefore": the consequence of what was said before
            "consequence": l0 == LAKHEN or (l0 == AL and l1 == KEN),
            # the messenger formula כֹּה אָמַר (יְהוָה), and a command to say something: אֱמֹר, וְאָמַרְתָּ, כֹּה תֹאמַר
            "messenger": l0 == KO and bool(v) and _strong(v) in AMAR and v["wtype"] == "qatal",
            # a 2nd-person weqatal (וְאָמַרְתָּ) is a command only with an addressee or after a command (decided in derive); without
            # them it is a quotation (Mal 1:6 "וַאֲמַרְתֶּם בַּמֶּה בָזִינוּ")
            "command_say": bool(v) and _strong(v) in AMAR and not has_object and (v["wtype"] == "imperative" or (
                person.get(v["key"]) == "second" and l0 == KO and v["wtype"] == "yiqtol")),
            "say_weqatal": bool(v) and _strong(v) in AMAR and not has_object and person.get(v["key"]) == "second" and v["wtype"] == "weqatal",
            # a command to the prophet to speak (Jer 7:27 "וְדִבַּרְתָּ אֲלֵיהֶם", 7:28 "וְאָמַרְתָּ אֲלֵיהֶם", Ezek "הִנָּבֵא")
            "proclaim": bool(v) and _strong(v) in PROCLAIM and (v["wtype"] == "imperative" or (
                person.get(v["key"]) == "second" and v["wtype"] == "weqatal" and addressee)),
            "command": bool(v) and (v["wtype"] == "imperative" or (v["wtype"] == "weqatal" and person.get(v["key"]) == "second")),
            "lead_verb": (_strong(lead[0]), lead[0]["wtype"]) if lead and lead[0]["class"] == "verb" else None,
            "subj": "S" in (rule or "").split("-"),
            "opener": ("HEAR" if bool(v) and v["wtype"] == "imperative" and _strong(v) in HEAR and lead and lead[0] is v else
                       # the whole first word (all its token lemmas): בְּצֶדֶק and בְּרֹאשׁ differ, לָמָּה and לָמָּה agree
                       "+".join(_n(t["lemma"]) for t in lead if (t["verse"], t["word"]) == (lead[0]["verse"], lead[0]["word"])) if lead else None),          # the clause names its subject (MACULA rule V-S-O, S-V ...)
            # an embedded clause with no opener (conjunction, relative, preposition) and no infinitive, whose verb is a participle or
            # that has no verb, stands next to its parent clause in the flat view (predicative participles, elliptic halves)
            "plain_embedded": bool(toks) and toks[0]["class"] not in ("cj", "rel", "prep") and not any(t["wtype"] in INFINITIVE for t in verbs)
                              and not finite and (not verbs or verbs[0]["wtype"] in PARTICIPLE),
            "role": role, "circ": waw and len(toks) > 1 and toks[1]["class"] != "verb" and not finite and not speak}


class _Line:
    """A line of main clauses: the narrative, or one speech."""
    def __init__(self, spk: str | None, opened: int = 0, scoped: bool = False, long: bool = False, to_me: bool = False):
        self.spk, self.opened, self.scoped = spk, opened, scoped
        self.long = long                          # a messenger or commanded speech: lasts to the next paragraph mark
        self.carries = False                      # a command to say at the start of a speech: lasts as long as that speech
        self.prophetic = False                    # opened by כֹּה אָמַר, a command to say, or the word-event formula: a wayyiqtol inside
                                                  # it is retold history, not the narrative resuming
        self.divine = False                       # God speaks on this line (כֹּה אָמַר יְהוָה, the word-event formula)
        self.commander = False                    # a command to speak was given on this line (Jer 7:2 "וְאָמַרְתָּ"): a later command returns here
        self.to_me = to_me                        # the speech is addressed to "me" (וַיְהִי דְבַר־יְהוָה אֵלַי): a 1st-person narrator
        self.last: str | None = None              # last main clause on the line
        self.verse_mains: dict = {}               # verse -> main clauses of the line in that verse
        self.oath: str | None = None
        self.oath_last: str | None = None         # the oath clause or a clause continuing it directly
        self.subs: dict = {}                      # opener lemma -> last subordinate clause with it (series)
        self.openers: dict = {}                   # poetry: first word of a verse-initial clause -> that clause (stanza heads)
        self.turns: dict = {}                     # (speaking verb, form) -> last turn clause opened by it (Dan 2: עָנֵה מַלְכָּא ... עֲנוֹ)


def derive(clauses: list[dict]) -> dict[str, dict]:
    """clauses: in text order, each {key, verse (book, ch, v), parent_key, attach, f (features), reset, chapter_start, poetry}.
    Returns key -> {parent, relation, attach, rule, tree_depth, depth (text_depth)}."""
    out: dict[str, dict] = {}
    lines: list[_Line] = [_Line(None)]
    pending: list[str] = []                       # clauses waiting for the next main clause (protasis, fronted temporal clause ...)
    vi, prev_v = 0, None
    prev_top: str | None = None                   # previous non-embedded clause
    clauses_verse: dict = {}                      # clause key -> verse
    pron1_of: dict = {}                           # clause key -> it has a 1st-person pronoun
    we_of: dict = {}                              # clause key -> it is a word-event formula
    neg_of: dict = {}                             # clause key -> it is negated
    pending_prev: dict = {}                       # forward clause -> the clause before it (fallback parent)
    form_of: dict = {}                            # main clause key -> verb form
    cmd_of: dict = {}                             # main clause key -> it is a command (imperative or 2nd-person weqatal)

    # lookahead: עָנָה needs a following אָמַר in the verse; indirect speech has only a לְ + infinitive after it in the verse
    n = len(clauses)
    amar_after, only_inf_after = [False] * n, [False] * n
    seen_amar: dict = {}
    for i in range(n - 1, -1, -1):
        amar_after[i] = seen_amar.get(clauses[i]["verse"], False)
        if clauses[i]["f"]["speak"] and clauses[i]["f"]["verb"] in AMAR:
            seen_amar[clauses[i]["verse"]] = True
    second_in_verse: dict = {}            # a vocative needs a clause addressing someone (imperative or 2nd person) in its verse
    for c in clauses:
        if c["f"]["second"]:
            second_in_verse[c["verse"]] = True
    # "וַיְהִי כְּהִנָּבְאִי": a וַיְהִי followed by a temporal clause in its verse is a narrative frame, like a dated וַיְהִי
    wayehi_when = [c["f"]["verb"] == "1961" and c["f"]["form"] == "wayyiqtol" and i + 1 < n and clauses[i + 1]["verse"] == c["verse"]
                   and clauses[i + 1]["f"]["sub_kind"] == "temporal" for i, c in enumerate(clauses)]
    for i in range(n):
        rest = [c for c in clauses[i + 1:i + 8] if c["verse"] == clauses[i]["verse"]]
        only_inf_after[i] = bool(rest) and all(c["parent_key"] == clauses[i]["key"] and c["f"]["inf_le"] for c in rest[:1]) and \
            not any(not c["parent_key"] for c in rest)

    def chain(k):
        seen = []
        while k is not None and k not in seen:
            seen.append(k)
            k = out.get(k, {}).get("parent")
        return seen

    def link(k, parent, relation, rule, attach=None):
        out[k] = {"parent": parent, "relation": relation if parent is not None else None, "attach": attach, "rule": rule}

    def resolve_pending(k):
        for p in pending:
            if p not in chain(k):
                out[p]["parent"] = k
                if out[p]["relation"] is None:
                    out[p]["relation"] = "embedded"
            elif pending_prev.get(p):             # the next main clause lies inside it: the clause before it instead
                out[p]["parent"] = pending_prev[p]
        pending.clear()

    def fallback_pending():
        for p in pending:                        # nothing came to hang on: the clause before it
            if out[p]["parent"] is None and pending_prev.get(p):
                out[p]["parent"] = pending_prev[p]
        pending.clear()

    for i, c in enumerate(clauses):
        k, f, vref = c["key"], c["f"], c["verse"]
        on = lambda name: active(name, c)          # noqa: E731
        if c.get("reset") or c.get("chapter_start"):
            fallback_pending()
        if c.get("reset"):
            lines = [_Line(None, vi)]
            pending.clear()
        elif c.get("para"):                       # a paragraph mark ends a messenger or commanded speech (and what is nested in it)
            j = next((x for x in range(1, len(lines)) if lines[x].long and not lines[x].carries), None)
            if j is not None:
                lines = lines[:j]
        if not c.get("reset") and c.get("chapter_start"):
            j = next((x for x in range(1, len(lines)) if lines[x].prophetic), None)
            if j is not None:                     # a new chapter ends a prophetic speech
                lines = lines[:j]
            for ln in lines:                      # a chapter starts each line afresh (the speech goes on, its chain restarts)
                ln.last = None
                ln.openers = {}
        if vref != prev_v:
            vi, prev_v = vi + 1, vref
            while len(lines) > 1 and lines[-1].scoped:                  # a poetry quotation ends with its verse
                lines.pop()
            while len(lines) > 2 and not lines[-1].long and lines[-1].opened < vi - 1:
                lines.pop()                       # a nested speech ends after the next verse
            if on("nested_speech_ends_at_3rd_person") and len(lines) > 2 and not lines[-1].long and not c["parent_key"] and f["waw"] \
                    and f["person"] == "third" and not f["sub_kind"] \
                    and f["form"] in ("qatal", "wayyiqtol") and not f["pron12"] and not f["speak"]:
                lines.pop()                       # or at a 3rd-person וְ-clause opening the next verse (Jer 7:24 "וְלֹא שָׁמְעוּ" after 7:23)
        if f["selah"] or (f["messenger"] and on("quotation_lines")):          # סֶלָה, and a new messenger formula, end a quotation (Mal 1:4 Edom's words)
            while len(lines) > 1 and lines[-1].scoped:
                lines.pop()
        if on("proclaim_returns") and f["proclaim"] and not c["parent_key"] and not f["sub_kind"]:
            # a new command to speak returns to the line that gave the earlier one (Jer 7:27 "וְדִבַּרְתָּ אֲלֵיהֶם" after 7:2 "וְאָמַרְתָּ")
            j = next((x for x in range(len(lines) - 1, 0, -1) if lines[x].commander), None)
            if j is not None and j < len(lines) - 1:
                lines = lines[:j + 1]
        line = lines[-1]
        pron1_of[k], we_of[k], neg_of[k] = f["pron1"], f["word_event"], f["negated"]

        # ---- embedded: keep the MACULA parent
        if c["parent_key"]:
            rel = ("relative" if f["sub_kind"] == "relative" or c["attach"] else
                   "complement" if f["lemor"] or f["role"] in ("o", "o2", "s", "p") else
                   f["sub_kind"] if f["sub_kind"] in ("purpose", "temporal", "causal", "conditional", "complement") else "embedded")
            link(k, c["parent_key"], rel, "embedded_flat" if f["plain_embedded"] else "embedded", c["attach"])
            if f["lemor"]:                        # the speech hangs on the לֵאמֹר clause
                if len(lines) > 1 and lines[-1].spk == c["parent_key"]:
                    lines[-1].spk = k
                else:
                    ln = _Line(k, vi, to_me=pron1_of.get(c["parent_key"], False) or f["pron1"])
                    ln.prophetic = ln.divine = we_of.get(c["parent_key"], False)
                    if on("commanded_lemor") and cmd_of.get(c["parent_key"]) and len(lines) > 1 and not c.get("poetry"):
                        # a command to proclaim (Jer 2:2 "וְקָרָאתָ בְאָזְנֵי יְרוּשָׁלִַם לֵאמֹר", Lev 6:2 "צַו אֶת־אַהֲרֹן ... לֵאמֹר"): a
                        # commanded speech, like וְאָמַרְתָּ אֲלֵהֶם
                        ln.long, ln.carries = True, lines[-1].opened >= vi - 1
                        ln.prophetic = True
                        lines[-1].commander = True
                    lines.append(ln)
            elif f["quote_say"] and on("quotation_lines"):    # בֶּאֱמָרְכֶם "in that you say": a quotation to the end of the verse
                lines.append(_Line(k, vi, scoped=True))
            continue

        # ---- the narrative resumes
        # the book's own narrator speaks as "me" only when the outermost speech is addressed to "me" (Ezek 11:2 "וַיֹּאמֶר אֵלַי"); in
        # a character's speech "אֵלַי" is that character retelling (Deut 2:2 "וַיֹּאמֶר יְהוָה אֵלַי" in Moses' speech)
        to_me = len(lines) > 1 and lines[1].to_me
        # a 1st-person narrator (a speech addressed to "me"): "וַיֹּאמֶר אֵלַי", and God's spirit or glory acting on "me" ("וַתִּפֹּל
        # עָלַי רוּחַ יְהוָה", Ezek 11:5), are the narrative, not retold history
        narrator = on("narrator_frames") and to_me and f["form"] == "wayyiqtol" and f["person"] == "third" and f["pron1"] and not f["pron2"] and (
            f["speak"] or f["divine"])
        resumes = (f["form"] == "wayyiqtol" and f["person"] == "third" and not f["pron12"]) or narrator or (
            f["form"] == "wayyiqtol" and f["person"] == "first" and f["verb"] in AMAR and not f["pron3"] and not only_inf_after[i]
            and to_me) or (
            f["aramaic"] and (f["step"] or (f["speak"] and f["person"] in ("third", None) and f["form"] in ("qatal",) + tuple(PARTICIPLE)
                                         and (f["verb"] not in ANSWER or amar_after[i]))))
        if any(ln.prophetic for ln in lines[1:]):
            # inside a prophetic speech a wayyiqtol is retold history (Jer 2:5); the narrative resumes only with a narrative frame
            resumes = f["word_event"] or f["time_wayehi"] or ((wayehi_when[i] or f["compliance"]) and on("narrative_frames")) or narrator or (
                # a wayyiqtol of saying with a named or definite speaker (Hag 2:12 "וַיַּעֲנוּ הַכֹּהֲנִים וַיֹּאמְרוּ")
                f["speak"] and f["form"] == "wayyiqtol" and (f["proper"] or (f["def_subject"] and on("narrative_frames")))) or (
                # a narrative step names its actor and refers to no "me"/"you" (Jonah 1:3 "וַיָּקָם יוֹנָה"), unlike retold history
                f["form"] == "wayyiqtol" and f["person"] == "third" and f["named_subject"] and not f["pron12"]) or (
                f["form"] == "wayyiqtol" and f["person"] == "first" and f["verb"] in AMAR and not f["pron3"] and not only_inf_after[i]
                and to_me)
        if len(lines) > 1 and (resumes or (f["word_event"] and f["form"] == "wayyiqtol" and on("word_event_resumes"))):    # the word-event formula always does (Ezek 21:6)
            lines = lines[:1]
            line = lines[0]
        first_in_verse = prev_top is None or clauses_verse.get(prev_top) != vref
        clauses_verse[k] = vref
        prev_top_key, prev_top = prev_top, k

        # ---- inquit: a speaking formula inside or after the words it quotes
        if line.last is not None and (f["formula"] or (f["speak"] and f["person"] == "third" and not f["waw"] and not first_in_verse
                                                       and f["form"] != "wayyiqtol" and not f["messenger"]
                                                       and (on("inquit_after_subordinate") or clauses_verse.get(line.last) == vref))):
            link(k, line.last, "inquit", "inquit")
            continue

        # ---- vocative
        if f["vocative"] and second_in_verse.get(vref):
            mains = line.verse_mains.get(vref, [])
            if mains:
                link(k, mains[-1], "vocative", "vocative")
            else:
                link(k, None, None, "vocative_fwd")
                out[k]["relation"] = "vocative"
                pending.append(k)
                pending_prev[k] = prev_top_key
            continue

        # ---- oath content and reasons
        if line.oath and f["sub_kind"] in ("causal", "conditional") and (
                f["lead"] in (_n("יַעַן"), _n("עֵקֶב")) or (f["lead"] in (KI, IM) and (first_in_verse or prev_top_key == line.oath_last))):
            link(k, line.oath, "complement" if f["lead"] in (KI, IM) else "causal", "oath")
            continue

        # ---- subordinate clauses (a subordinate clause that opens a speech is the speech's first clause: Ruth 1:10)
        if f["lead"] == KI and f["l1"] == IM and prev_top_key and neg_of.get(prev_top_key):
            link(k, prev_top_key, "adversative", "adversative")   # "כִּי לֹא … כִּי אִם": not … but (Jer 7:22-23)
            continue
        if f["sub_kind"] and not (line.spk and line.last is None):
            prev = line.subs.get(f["lead"]) if f["lead"] else None
            same_ch = prev is not None and clauses_verse.get(prev, (None, None))[:2] == vref[:2]
            pt = prev_top_key                    # the clause before, or the subordinate clause it continues
            while on("ki_series_and_look_back") and pt and out.get(pt, {}).get("rule") == "sub_continued":
                pt = out[pt]["parent"]
            if prev is not None and (pt == prev or (f["sub_kind"] == "conditional" and same_ch)):
                link(k, prev, "parallel", "series")             # a series of the same opener chains on the one before
            else:
                mains = line.verse_mains.get(vref, [])
                if mains:
                    link(k, mains[-1], f["sub_kind"], "sub_back")  # the nearest main clause before it
                elif line.last is not None and ((first_in_verse and (f["di_first"] and f["aramaic"] or f["participle"]
                                                                     or (f["sub_kind"] == "causal" and c.get("poetic"))))
                                                or (on("ki_series_and_look_back") and f["lead"] == KI and f["sub_kind"] == "causal" and c.get("poetic"))):
                    # a verse-initial Aramaic דִּי, participle, or (poetry and prophecy) "for", and a "for" with no main clause before
                    # it in its verse: it explains what came before
                    link(k, line.last, "causal" if f["di_first"] else f["sub_kind"], "look_back")
                else:
                    rel = "conditional" if f["sub_kind"] == "causal" and f["lead"] == KI and not c.get("poetic") else f["sub_kind"]
                    link(k, None, None, "sub_fwd")
                    out[k]["relation"] = rel
                    pending.append(k)
                    pending_prev[k] = prev_top_key
            if f["lead"]:
                line.subs[f["lead"]] = k
            if on("quotation_lines") and ((f["say_any"] and f["lead"] in (KI, IM, PEN)) or f["quote_say"]) and not only_inf_after[i]:
                lines.append(_Line(k, vi, scoped=True))   # Mal 1:4 "כִּי־תֹאמַר אֱדוֹם": the words are a quotation under the כִּי clause
            continue

        # ---- circumstantial
        if f["circ"] and not c.get("poetry") and len(lines) == 1 and line.verse_mains.get(vref) \
                and form_of.get(line.verse_mains[vref][-1]) == "wayyiqtol":
            link(k, line.verse_mains[vref][-1], "circumstantial", "circ")
            continue

        # ---- poetry and prophecy: a וְ-clause right after a subordinate clause (same verse, no main clause between) continues it
        if c.get("poetic") and f["waw"] and prev_top_key and clauses_verse.get(prev_top_key) == vref and \
                out.get(prev_top_key, {}).get("rule") in ("sub_back", "sub_fwd", "look_back", "series", "oath") + (("sub_continued",) if on("ki_series_and_look_back") else ()):
            # (also after such a continuation: Jer 2:5 "כִּי רָחֲקוּ מֵעָלָי וַיֵּלְכוּ אַחֲרֵי הַהֶבֶל וַיֶּהְבָּלוּ")
            link(k, prev_top_key, "continuation" if f["form"] in CHAIN_FORMS else "coordination", "sub_continued")
            continue

        # ---- main clause on its line
        in_speech = len(lines) > 1
        prev_last = line.last
        if line.last is None:
            parent, rel = (line.spk, "speech") if line.spk else (None, None)
        else:
            parent = line.last
            chain_form = f["form"] in CHAIN_FORMS or (in_speech and f["waw"] and f["form"] in CHAIN_FORMS_SPEECH)
            rel = "continuation" if chain_form else "coordination" if f["waw"] else "asyndetic"
            if rel == "asyndetic":                # on the head of the run before: climb over continuation/coordination/parallel
                run_verse = clauses_verse.get(parent)  # links, within the verse of the clause before
                while out.get(parent, {}).get("relation") in ("continuation", "coordination", "parallel") and out[parent]["parent"] \
                        and clauses_verse.get(out[parent]["parent"]) == run_verse:
                    parent = out[parent]["parent"]
        if f["consequence"] and line.last is not None:
            rel = "consequence"                   # לָכֵן / עַל־כֵּן on the clause before it (BHSA's convention: one level deeper)
            parent = line.last
        if rel == "continuation" and f["subj"]:   # a chain clause naming its subject goes on the last chain clause that named one
            x = parent
            while x and not out[x].get("subj") and out[x]["relation"] in ("continuation", "coordination", "parallel") and out[x]["parent"]:
                x = out[x]["parent"]
            if out.get(x, {}).get("subj"):
                parent = x
        if c.get("poetry") and rel == "asyndetic" and first_in_verse and f["opener"]:
            head = line.openers.get(f["opener"])      # a verse opening like an earlier verse: on that stanza head
            if head is not None:
                parent, rel = head, "parallel"
        turn = f["lead_verb"] if f["speak"] and f["lead_verb"] and not f["waw"] and f["form"] != "wayyiqtol" else None
        if turn and turn in line.turns:           # a turn that repeats the opening of the turn before (Dan 2:8 עָנֵה מַלְכָּא on 2:5)
            parent, rel = line.turns[turn], "parallel"
        link(k, parent, rel, "main")
        out[k]["subj"] = f["subj"]
        form_of[k] = f["form"]
        if c.get("poetry") and first_in_verse and f["opener"]:
            line.openers[f["opener"]] = k
        if turn:
            line.turns[turn] = k
        out[k]["imperative"] = f["imperative"]
        cmd_of[k] = f["command"]
        resolve_pending(k)
        line.last = k
        line.verse_mains.setdefault(vref, []).append(k)
        if f["oath"]:
            if line.oath is None or clauses_verse.get(line.oath) != vref:
                line.oath = k
            line.oath_last = k
        elif line.oath_last == prev_top_key and f["waw"] and clauses_verse.get(line.oath) == vref:
            line.oath_last = k                    # וְכֹה יֹסִיף continues the oath
        speaks = f["speak"] and (f["verb"] not in ANSWER or amar_after[i]) and not only_inf_after[i] and f["form"] != "imperative"
        narrated = (f["person"] == "third" and f["form"] in ("wayyiqtol", "qatal")) or f["form"] in PARTICIPLE
        # וְאָמַרְתָּ is a command to say with an addressee (וְאָמַרְתָּ אֲלֵהֶם) or after a command (Ezek 6:3 "וְהִנָּבֵא ... וְאָמַרְתָּ")
        command = f["command_say"] or (f["say_weqatal"] and (not on("command_needs_addressee") or f["addressee"] or cmd_of.get(prev_last, False)))
        if f["messenger"] or (command and in_speech and not only_inf_after[i]):
            # כֹּה אָמַר יְהוָה, or a command to say (אֱמֹר, וְאָמַרְתָּ אֲלֵהֶם): the words follow, to the next paragraph mark
            # (in poetry to the end of the verse or סֶלָה)
            ln = _Line(k, vi, scoped=bool(c.get("poetry")), long=not c.get("poetry"), to_me=f["pron1"])
            # Lev 1:2 "דַּבֵּר אֶל־בְּנֵי יִשְׂרָאֵל וְאָמַרְתָּ אֲלֵהֶם": a command to say at the start of a speech carries the rest of it
            ln.carries = command and in_speech and line.opened >= vi - 1 and not c.get("poetry")
            # a messenger formula is prophetic only when God speaks (כֹּה אָמַר יְהוָה; not Isa 37:3 "כֹּה אָמַר חִזְקִיָּהוּ", Exod 5:10
            # "כֹּה אָמַר פַּרְעֹה"); a commanded speech always is: what it quotes is retold history (Deut 26:5 "וַיֵּרֶד מִצְרַיְמָה")
            ln.prophetic = command or f["divine"] or not on("prophetic_needs_god")
            ln.divine = f["messenger"] and f["divine"]
            if command:
                line.commander = True
            lines.append(ln)
        elif on("quotation_lines") and (f["quote_say"] or (f["say_weqatal"] and not command)) and not only_inf_after[i]:
            # "וַאֲמַרְתֶּם", "וְאַתֶּם תֹּאמְרוּ": a quotation, not a narrated speech; it ends with its verse (Mal 1:6-7 disputations)
            lines.append(_Line(k, vi, scoped=True))
        elif f["lemor"] or (speaks and (not in_speech or narrated)):
            ln = _Line(k, vi, to_me=f["pron1"])
            # "יֹאמַר": a quotation, not a narrated speech; it ends with its verse
            ln.scoped = not f["lemor"] and not narrated and not (f["person"] == "first" and f["form"] in ("wayyiqtol", "qatal"))
            ln.divine = f["divine"] and narrated
            lines.append(ln)
        elif c.get("poetry") and f["ptc_saying"]:
            lines.append(_Line(k, vi, scoped=True))

    fallback_pending()
    for k in out:
        ch = chain(k)
        out[k]["tree_depth"] = sum(1 for x in ch[:-1] if out[x]["relation"] not in TREE_FLAT)
        out[k]["depth"] = sum(1 for x in ch[:-1] if out[x]["relation"] not in FLAT and out[x]["rule"] not in FLAT_RULES)
        out[k].pop("imperative", None)
        out[k].pop("subj", None)
    return out

