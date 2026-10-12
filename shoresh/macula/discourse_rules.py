"""Text-level hierarchy of Hebrew clauses (discourse_parent, relation, discourse_attach, tree_depth, text_depth), derived by rule from
MACULA Hebrew features only.

MACULA has no clause-to-clause relations above the verse (a MACULA sentence is one verse; main clauses in a verse are siblings), so the
hierarchy is derived, not passed through. Inputs per clause, all MACULA (CC BY 4.0) plus person from the lexeme spine (same source):
verb form (`wtype`: wayyiqtol, weqatal, qatal, yiqtol, imperative, infinitive, participle ...), the clause's first words (conjunction,
relative, preposition), the verb's lemma (verbs of speaking, oaths), the clause's rule and role, and the MACULA tree (`parent`, phrase
nesting). No BHSA input. The segmentation gives a clause-opening subordinator or relative to the clause it opens.

ONE TREE. Every clause has a discourse_parent (an earlier clause, or for a protasis the later apodosis) and a relation on that link,
except the first clause of a line: a book, a chapter, a new Psalm, and in poetry and prophecy a paragraph mark (ס/פ).

  LINES. The narrative is one line; a speech opens a line of its own under its speaking clause. Main clauses chain along their line:
    continuation   a wayyiqtol or weqatal; in speech also a yiqtol, qatal, imperative, jussive or cohortative with וְ   (CHAIN_FORMS)
    coordination   any other clause with וְ
    asyndetic      no conjunction (poetry, lists, a new address)
    speech         the first clause of a speech, on its speaking or לֵאמֹר clause
  SPEECHES open at a clause whose verb is a verb of speaking (Hebrew אָמַר, דִּבֶּר, צִוָּה, עָנָה, שָׁאַל: finite; Aramaic אֲמַר, עֲנָה,
    מְלַל: finite or participle) or at a לֵאמֹר clause.
    - עָנָה opens one only when an אָמַר clause follows in the verse (Ps 3:5 "he answered me" opens none).
    - Indirect speech opens none: a speaking clause whose only follow-up in the verse is a לְ + infinitive (Dan 2:12 "and he commanded to
      destroy") gets the infinitive as a complement.
    - The narrative resumes, closing all speeches, at a 3rd-person wayyiqtol; in Aramaic at a 3rd-person speaking clause ("the king
      answered and said", which opens the next speech), or at אֱדַיִן / כָּל־קֳבֵל דְּנָה with a named actor (not inside a retold dream).
    - Inside a speech only a narrated speaking clause (3rd person wayyiqtol/qatal, or a participle) or a לֵאמֹר opens a nested speech;
      a nested speech ends after the verse following the one it opened in.
    - In poetry a participle of saying (Ps 3:3 "many say") opens a quotation that ends with its verse or at סֶלָה.
    inquit         a 3rd-person speaking clause without וְ that is not the first clause of its verse (Isa 40:1 "יֹאמַר אֱלֹהֵיכֶם"), and a formula
                   such as נְאֻם יְהוָה: it hangs on the clause before it on its line, opens no speech, and the line goes on past it.
  SUBORDINATE clauses (opened by a subordinator; an infinitive clause; a participle clause without the article and without a subject,
    i.e. MACULA's rule has no S) hang on the first main clause of the run directly before them in the verse (a clause without וְ that is
    not a chain link starts a new run; formulas are skipped). With none before them they hang on the next main clause, except a
    verse-initial Aramaic דִּי or a verse-initial participle, which look back to the previous verse's line. Relation by the opener:
    causal (כִּי after its main clause, יַעַן, עֵקֶב, Aramaic כָּל־קֳבֵל דִּי, verse-initial דִּי), purpose (לְמַעַן, פֶּן, לְ + infinitive),
    temporal (כַּאֲשֶׁר, עַד, טֶרֶם, בְּ/כְּ + infinitive), conditional (אִם, לוּ, לוּלֵא, אִלּוּ, Aramaic הֵן, and a כִּי before its main
    clause: casuistic law), relative (אֲשֶׁר, דִּי, שֶׁ), circumstantial (participle), complement (infinitive without a preposition).
  OATHS (נִשְׁבַּעְתִּי, כֹּה יַעֲשֶׂה … וְכֹה יֹסִיף, חַי ...): while the speech goes on, a following כִּי/אִם clause that opens its verse or
    follows the oath directly is its complement (the content of the oath), and a reason clause (יַעַן, עֵקֶב) is causal on the oath.
  vocative       an address (MACULA rule Np2CL with a noun or participle, in a verse with an imperative or a 2nd-person verb): on the
                 nearest main clause before it in the verse, else on the next.
  circumstantial a verbless clause opened by וְ + a non-verb in narrative: on the preceding main clause.
  EMBEDDED clauses keep their MACULA parent; relation relative (in a noun phrase, discourse_attach = the antecedent's first word),
    complement (MACULA role o/s/p, or לֵאמֹר), purpose/temporal (לְ / בְּ כְּ + infinitive), or embedded.

CONDITIONALS: the protasis hangs under its apodosis (the first clause of the run that follows), relation conditional. A client that
wants the other direction inverts exactly those links: the protasis takes the apodosis's parent and relation, and the apodosis hangs
under the protasis with relation conditional.

DEPTHS: tree_depth counts every link up to the root of the line. text_depth counts only the links whose relation is not in FLAT
(continuation, coordination, asyndetic, inquit): the flat view, where a chain stays on one level.
"""
from __future__ import annotations

import unicodedata


def _n(s: str | None) -> str:
    return unicodedata.normalize("NFC", s or "")


RULES_VERSION = "0.4"

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
FLAT = {"continuation", "coordination", "asyndetic", "inquit"}
RELATIONS = ["continuation", "coordination", "asyndetic", "speech", "inquit", "causal", "purpose", "temporal", "conditional", "relative",
             "circumstantial", "complement", "vocative", "embedded"]

_SUB_KIND = {"כִּי": "causal", "יַעַן": "causal", "עֵקֶב": "causal", "אִם": "conditional", "לוּ": "conditional", "לוּלֵא": "conditional",
             "אִלּוּ": "conditional", "לְמַעַן": "purpose", "פֶּן": "purpose", "עַד": "temporal", "טֶרֶם": "temporal",
             "בְּטֶרֶם": "temporal", "תַּחַת": "causal"}
SUB_KIND = {_n(k): v for k, v in _SUB_KIND.items()}
SUB_CJ = set(SUB_KIND)
SUB_ARC = {_n("הֵן")}                                     # Aramaic "if" (Hebrew הֵן is "behold")
REL = {_n(x) for x in ("אֲשֶׁר", "שֶׁ", "דִּי", "זוּ")}
DI = _n("דִּי")
WAW, BE, KE, LE = _n("וְ"), _n("בְּ"), _n("כְּ"), _n("לְ")
KI, IM = _n("כִּי"), _n("אִם")
ADAYIN, QABEL, KOL, DENA = _n("אֱדַיִן"), _n("קֳבֵל"), _n("כֹּל"), _n("דְּנָה")
KO, HAY, MELEK = _n("כֹּה"), _n("חַי"), _n("מֶלֶךְ")
FORMULA = {_n("נְאֻם")}
SELAH = _n("סֶלָה")


def is_subordinator(t) -> bool:
    lem = _n(t["lemma"])
    return lem in SUB_CJ or lem in REL or (lem in SUB_ARC and t["wlang"] == "A")


def _strong(t) -> str:
    s = (t["strong"] or "").lstrip("0")
    return "".join(ch for ch in s if ch.isdigit())


def features(toks: list, person: dict[str, str], rule: str | None = None, role: str | None = None) -> dict:
    """toks: MACULA word rows of the clause's words (whole words, as segmented), text order. rule, role: the MACULA clause node's."""
    verbs = [t for t in toks if t["class"] == "verb"]
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
    speak = bool(v) and _strong(v) in SPEAK and (bool(finite) or (aramaic and v["wtype"] in PARTICIPLE))
    # a participle is a clause of its own (nominal clause, main) when it has the article or a subject of its own
    ptc_free = bool(v) and v["wtype"] in PARTICIPLE and not finite and not speak and not (
        any(t["class"] == "art" and (t["verse"], t["word"]) == (v["verse"], v["word"]) for t in toks) or any(t["role"] == "s" for t in toks)
        or "S" in (rule or "").split("-"))
    inf = bool(verbs) and not finite and not speak and verbs[0]["wtype"] in INFINITIVE
    if sub_kind is None and inf:
        before = [t for t in toks if (t["verse"], t["word"]) == (verbs[0]["verse"], verbs[0]["word"]) and t["class"] == "prep"]
        p = _n(before[0]["lemma"]) if before else ""
        sub_kind = "purpose" if p == LE else "temporal" if p in (BE, KE) else "complement"
    elif sub_kind is None and ptc_free:
        sub_kind = "circumstantial"
    actor = any(t["wtype"] == "proper" or _n(t["lemma"]) == MELEK for t in toks)
    noun_head = bool(lead) and not finite and (lead[0]["class"] == "noun" or lead[0]["wtype"] in PARTICIPLE)
    return {"verb": _strong(v) if v else None, "form": v["wtype"] if v else None, "person": person.get(v["key"]) if v else None,
            "aramaic": aramaic, "waw": waw, "speak": speak, "sub_kind": sub_kind, "lead": l0, "di_first": l0 == DI,
            "participle": ptc_free,
            "lemor": any(t["class"] == "verb" and _strong(t) == LEMOR and t["wtype"] == "infinitive construct" for t in toks),
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
            "role": role, "circ": waw and len(toks) > 1 and toks[1]["class"] != "verb" and not finite and not speak}


class _Line:
    """A line of main clauses: the narrative, or one speech."""
    def __init__(self, spk: str | None, opened: int = 0, scoped: bool = False):
        self.spk, self.opened, self.scoped = spk, opened, scoped
        self.last: str | None = None              # last main clause on the line
        self.run_first: str | None = None         # first main clause of the current run in the current verse
        self.run_verse = None
        self.verse_mains: dict = {}               # verse -> main clauses of the line in that verse
        self.oath: str | None = None
        self.oath_last: str | None = None         # the oath clause or a clause continuing it directly


def derive(clauses: list[dict]) -> dict[str, dict]:
    """clauses: in text order, each {key, verse (book, ch, v), parent_key, attach, f (features), reset, chapter_start, poetry}.
    Returns key -> {parent, relation, attach, rule, tree_depth, depth (text_depth)}."""
    out: dict[str, dict] = {}
    lines: list[_Line] = [_Line(None)]
    pending: list[str] = []                       # clauses waiting for the next main clause (protasis, fronted temporal clause ...)
    narrative = False
    vi, prev_v = 0, None
    prev_top: str | None = None                   # previous non-embedded clause
    clauses_verse: dict = {}                      # clause key -> verse

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
        pending.clear()

    for i, c in enumerate(clauses):
        k, f, vref = c["key"], c["f"], c["verse"]
        if c.get("reset"):
            lines = [_Line(None, vi)]
            pending.clear()
        elif c.get("chapter_start"):
            for ln in lines:                      # a chapter starts each line afresh (the speech goes on, its chain restarts)
                ln.last = ln.run_first = None
        if vref != prev_v:
            vi, prev_v = vi + 1, vref
            while len(lines) > 1 and lines[-1].scoped:                  # a poetry quotation ends with its verse
                lines.pop()
            while len(lines) > 2 and lines[-1].opened < vi - 1:         # a nested speech ends after the next verse
                lines.pop()
        if f["selah"]:
            while len(lines) > 1 and lines[-1].scoped:
                lines.pop()
        line = lines[-1]

        # ---- embedded: keep the MACULA parent
        if c["parent_key"]:
            rel = ("relative" if f["sub_kind"] == "relative" or c["attach"] else
                   "complement" if f["lemor"] or f["role"] in ("o", "o2", "s", "p") else
                   f["sub_kind"] if f["sub_kind"] in ("purpose", "temporal", "causal", "conditional", "complement") else "embedded")
            link(k, c["parent_key"], rel, "embedded", c["attach"])
            if f["lemor"]:                        # the speech hangs on the לֵאמֹר clause
                if len(lines) > 1 and lines[-1].spk == c["parent_key"]:
                    lines[-1].spk = k
                else:
                    lines.append(_Line(k, vi))
            continue

        # ---- the narrative resumes
        resumes = (f["form"] == "wayyiqtol" and f["person"] == "third") or (
            f["aramaic"] and (f["step"] or (f["speak"] and f["person"] in ("third", None) and (f["verb"] not in ANSWER or amar_after[i]))))
        if len(lines) > 1 and resumes:
            lines = lines[:1]
            line = lines[0]
        first_in_verse = prev_top is None or clauses_verse.get(prev_top) != vref
        clauses_verse[k] = vref
        prev_top_key, prev_top = prev_top, k

        # ---- inquit: a speaking formula inside or after the words it quotes
        if line.last is not None and (f["formula"] or (f["speak"] and f["person"] == "third" and not f["waw"] and not first_in_verse and f["form"] != "wayyiqtol"
                                                       and clauses_verse.get(line.last) == vref)):
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
            continue

        # ---- oath content and reasons
        if line.oath and f["sub_kind"] in ("causal", "conditional") and (
                f["lead"] in (_n("יַעַן"), _n("עֵקֶב")) or (f["lead"] in (KI, IM) and (first_in_verse or prev_top_key == line.oath_last))):
            link(k, line.oath, "complement" if f["lead"] in (KI, IM) else "causal", "oath")
            continue

        # ---- subordinate clauses
        if f["sub_kind"]:
            run = line.run_first if line.run_verse == vref else None
            if run is not None:
                link(k, run, f["sub_kind"], "sub_back")
            elif first_in_verse and (f["di_first"] and f["aramaic"] or f["participle"]) and line.last is not None:
                link(k, line.last, "causal" if f["di_first"] else f["sub_kind"], "look_back")
            else:
                rel = "conditional" if f["sub_kind"] == "causal" and f["lead"] == KI else f["sub_kind"]
                link(k, None, None, "sub_fwd")
                out[k]["relation"] = rel
                pending.append(k)
            continue

        # ---- circumstantial
        if f["circ"] and narrative and len(lines) == 1 and line.verse_mains.get(vref):
            link(k, line.verse_mains[vref][-1], "circumstantial", "circ")
            continue

        # ---- main clause on its line
        in_speech = len(lines) > 1
        if line.last is None:
            parent, rel = (line.spk, "speech") if line.spk else (None, None)
        else:
            parent = line.last
            chain_form = f["form"] in CHAIN_FORMS or (in_speech and f["waw"] and f["form"] in CHAIN_FORMS_SPEECH)
            rel = "continuation" if chain_form else "coordination" if f["waw"] else "asyndetic"
        link(k, parent, rel, "main")
        out[k]["imperative"] = f["imperative"]
        resolve_pending(k)
        if line.run_verse != vref or (not f["waw"] and rel == "asyndetic"):
            if not (line.run_verse == vref and line.run_first and f["formula"]):
                line.run_first, line.run_verse = k, vref
        line.last = k
        line.verse_mains.setdefault(vref, []).append(k)
        if f["oath"]:
            if line.oath is None or clauses_verse.get(line.oath) != vref:
                line.oath = k
            line.oath_last = k
        elif line.oath_last == prev_top_key and f["waw"] and clauses_verse.get(line.oath) == vref:
            line.oath_last = k                    # וְכֹה יֹסִיף continues the oath
        if not in_speech and f["form"] == "wayyiqtol":
            narrative = True
        speaks = f["speak"] and (f["verb"] not in ANSWER or amar_after[i]) and not only_inf_after[i] and f["form"] != "imperative"
        narrated = (f["person"] == "third" and f["form"] in ("wayyiqtol", "qatal")) or f["form"] in PARTICIPLE
        if f["lemor"] or (speaks and (not in_speech or narrated)):
            lines.append(_Line(k, vi))
        elif c.get("poetry") and f["ptc_saying"]:
            lines.append(_Line(k, vi, scoped=True))

    for k in out:
        ch = chain(k)
        out[k]["tree_depth"] = len(ch) - 1
        out[k]["depth"] = sum(1 for x in ch[:-1] if out[x]["relation"] not in FLAT)
        out[k].pop("imperative", None)
    return out

