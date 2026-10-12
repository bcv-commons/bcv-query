"""Text-level hierarchy of Hebrew clauses (discourse_parent, discourse_attach, text_depth), derived by rule from MACULA Hebrew features only.

MACULA has no clause-to-clause relations above the verse (a MACULA sentence is one verse; main clauses in a verse are siblings), so the
hierarchy is derived, not passed through. Inputs per clause, all MACULA (CC BY 4.0) plus person from the lexeme spine (same source):
verb form (`wtype`: wayyiqtol, weqatal, qatal, yiqtol, imperative, infinitive, participle ...), the clause's first words (conjunction,
relative, preposition), the verb's lemma (verbs of speaking), the MACULA tree (`parent`, phrase nesting). No BHSA input.

Rules, applied to the clauses of a book in text order (a clause is named by its clause_key; all its segments share its values).
The segmentation gives a clause-opening subordinator or relative (כִּי, אִם, אֲשֶׁר, עַד, דִּי ...) to the clause it opens.

  embedded   the clause sits inside another clause in the MACULA tree (an infinitive in a prepositional phrase, a relative clause in a noun
             phrase): discourse_parent = that clause; discourse_attach = first word of the head the clause hangs on, when it hangs on a phrase.
  speech     a clause whose verb is a verb of speaking (Hebrew אָמַר, דִּבֶּר, צִוָּה, עָנָה, שָׁאַל: finite; Aramaic אֲמַר, עֲנָה, מְלַל: finite
             or participle), or a לֵאמֹר clause, opens a speech: the following clauses belong to it, one level deeper. עָנָה opens one
             only when an אָמַר clause follows in the verse ("and he answered and said"; Ps 3:5 "he answered me" opens none). The
             narrative resumes, closing the speech, at a 3rd-person wayyiqtol; in Aramaic at a 3rd-person speaking clause ("the king
             answered and said", which opens the next speech) or at אֱדַיִן with a named actor (not inside a retold dream). Inside a
             speech only a narrated speaking clause (3rd person wayyiqtol/qatal, or a participle) or a לֵאמֹר opens a nested speech, and
             a nested speech ends after the verse following the one it opened in. In poetry a participle of saying (Ps 3:3 "many say")
             opens a quotation that ends with its verse or at סֶלָה. A new Psalm, and a paragraph mark (ס/פ) in
             poetry and prophecy, end any speech. Top-level clauses of a speech: discourse_parent = the speaking (or לֵאמֹר) clause.
  sub_back   a clause opened by a subordinator, or an infinitive clause, or a participle clause without the article and without a subject
             of its own (MACULA's clause rule has no S), after a main clause of the same verse: discourse_parent = the first main clause
             of the verse at its level (the head of the coordinated run; a formula such as נְאֻם יְהוָה is skipped).
  sub_fwd    the same, with no main clause before it in the verse (a conditional or temporal clause ahead of its main clause, casuistic
             law כִּי/אִם): discourse_parent = the next main clause.
  circ       a verbless clause opened by וְ + a non-verb, inside narrative (after a wayyiqtol): discourse_parent = the preceding main clause.
  main       everything else, including a participle with the article or with its own subject (a nominal clause): on the main line of
             its level, discourse_parent = the speaking clause of the current speech, or null in narrative.
text_depth is the length of the discourse_parent chain.
"""
from __future__ import annotations

import unicodedata


def _n(s: str | None) -> str:
    return unicodedata.normalize("NFC", s or "")

RULES_VERSION = "0.3"

SPEAK = {"559", "1696", "6680", "6030", "7592",          # אָמַר, דָּבַר, צָוָה, עָנָה, שָׁאַל (Strong's, MACULA strong column)
         "560", "6032", "4449"}                           # Aramaic אֲמַר, עֲנָה, מְלַל
LEMOR = "559"
AMAR = {"559", "560"}                                     # אָמַר / Aramaic אֲמַר: "and he answered and said"
ANSWER = {"6030", "6032"}                                 # עָנָה / Aramaic עֲנָה: opens a speech only when an אָמַר clause follows in the verse
FORMULA = {"נְאֻם"}                                        # "declares the LORD": never the clause a subordinate clause hangs on
SELAH = "סֶלָה"                                             # לֵאמֹר = infinitive construct of אָמַר with לְ
SUB_CJ = {"כִּי", "אִם", "לְמַעַן", "פֶּן", "לוּלֵא", "אִלּוּ", "יַעַן", "עֵקֶב", "לוּ", "טֶרֶם", "בְּטֶרֶם", "עַד", "תַּחַת"}
SUB_ARC = {"הֵן"}                                         # Aramaic "if" (Hebrew הֵן is "behold")
ADAYIN = "אֱדַיִן"                                        # Aramaic "then": a new narrative step
REL = {"אֲשֶׁר", "שֶׁ", "דִּי", "זוּ"}
FINITE = {"wayyiqtol", "weqatal", "qatal", "yiqtol", "imperative", "jussive", "cohortative"}
SUB_CJ, SUB_ARC, REL, ADAYIN = {_n(x) for x in SUB_CJ}, {_n(x) for x in SUB_ARC}, {_n(x) for x in REL}, _n(ADAYIN)
FORMULA, SELAH = {_n(x) for x in FORMULA}, _n(SELAH)
INFINITIVE = {"infinitive construct", "infinitive absolute"}
PARTICIPLE = {"participle active", "participle passive"}


def is_subordinator(t) -> bool:
    lem = _n(t["lemma"])
    return lem in SUB_CJ or lem in REL or (lem in SUB_ARC and t["wlang"] == "A")


def _strong(t) -> str:
    s = (t["strong"] or "").lstrip("0")
    return "".join(ch for ch in s if ch.isdigit())


def features(toks: list, person: dict[str, str], rule: str | None = None) -> dict:
    """toks: MACULA word rows of the clause's words (whole words, as segmented), text order."""
    verbs = [t for t in toks if t["class"] == "verb"]
    finite = [t for t in verbs if t["wtype"] in FINITE]
    v = finite[0] if finite else (verbs[0] if verbs else None)
    aramaic = sum(t["wlang"] == "A" for t in toks) * 2 > len(toks)
    lead = [t for t in toks if not (t["class"] in ("cj", "prep") and _n(t["lemma"]) in (_n("וְ"), _n("בְּ")))][:2]
    sub = any(is_subordinator(t) for t in toks[:3])
    # a participle is a clause of its own (nominal clause, main) when it has the article or a subject of its own
    ptc_free = bool(v) and v["wtype"] in PARTICIPLE and not finite and not (
        any(t["class"] == "art" and (t["verse"], t["word"]) == (v["verse"], v["word"]) for t in toks) or any(t["role"] == "s" for t in toks)
        or "S" in (rule or "").split("-"))          # MACULA's clause rule names a subject (V-S, S-V-PP): a nominal clause
    speak = bool(v) and _strong(v) in SPEAK and (bool(finite) or (aramaic and v["wtype"] in PARTICIPLE))
    ptc_saying = bool(v) and not finite and v["wtype"] in PARTICIPLE and _strong(v) in AMAR       # Ps 3:3 רַבִּים אֹמְרִים
    return {"verb": _strong(v) if v else None, "ptc_saying": ptc_saying,
            "formula": bool(lead) and _n(lead[0]["lemma"]) in FORMULA, "selah": any(_n(t["lemma"]) == SELAH for t in toks),
            "form": v["wtype"] if v else None, "person": person.get(v["key"]) if v else None, "finite": bool(finite) or speak,
            "aramaic": aramaic,
            # אֱדַיִן starts a narrative step when it names an actor (Daniel, Arioch, the king); inside a retold dream it does not (Dan 2:35)
            "adayin": any(_n(t["lemma"]) == ADAYIN for t in lead) and any(t["wtype"] == "proper" or _n(t["lemma"]) == _n("מֶלֶךְ") for t in toks), "speak": speak,
            "lemor": any(t["class"] == "verb" and _strong(t) == LEMOR and t["wtype"] == "infinitive construct" for t in toks),
            "sub": sub, "nonfinite_only": bool(verbs) and not finite and not speak and (verbs[0]["wtype"] in INFINITIVE or ptc_free),
            "waw_nonverb": bool(toks) and _n(toks[0]["lemma"]) == _n("וְ") and len(toks) > 1 and toks[1]["class"] != "verb" and not finite}


def derive(clauses: list[dict]) -> dict[str, dict]:
    """clauses: in text order, each {key, verse (book, ch, v), parent_key, attach, f (features)}. Returns key -> {parent, attach, depth, rule}."""
    out: dict[str, dict] = {}
    frames: list[str] = []                 # stack of speaking clauses; frames[-1] is the speech we are in
    pending_fwd: list[str] = []            # sub_fwd clauses waiting for the next main clause
    last_main: dict[tuple, str] = {}       # verse -> last main clause at the current level
    narrative = False                      # has a wayyiqtol been seen at the outer level (for circ)

    def depth(k):
        return len(chain(k)) - 1

    def chain(k):
        seen = []
        while k is not None and k not in seen:
            seen.append(k)
            k = out.get(k, {}).get("parent")
        return seen

    def set_(k, parent, rule, attach=None):
        out[k] = {"parent": parent, "attach": attach, "rule": rule}

    opened: list[int] = []                 # verse index at which each frame opened
    scoped: list[bool] = []                # a frame that ends with its verse (or at סֶלָה)
    first_main: dict[tuple, str] = {}      # (verse, level) -> first main clause, the one a subordinate clause hangs on
    vi, prev_v = 0, None
    # עָנָה opens a speech only when an אָמַר clause follows in the same verse ("וַיַּעַן ... וַיֹּאמֶר")
    amar_after = [False] * len(clauses)
    seen: dict[tuple, bool] = {}
    for i in range(len(clauses) - 1, -1, -1):
        vref = clauses[i]["verse"]
        amar_after[i] = seen.get(vref, False)
        if clauses[i]["f"]["speak"] and clauses[i]["f"]["verb"] in AMAR:
            seen[vref] = True

    def push(k, verse_scoped=False):
        frames.append(k)
        opened.append(vi)
        scoped.append(verse_scoped)

    def pop_scoped():
        while frames and scoped[-1]:
            frames.pop(), opened.pop(), scoped.pop()

    for i, c in enumerate(clauses):
        k, f, vref = c["key"], c["f"], c["verse"]
        if c.get("reset"):                 # a new Psalm, or a paragraph mark (ס/פ) in poetry and prophecy
            frames.clear(), opened.clear(), scoped.clear()
        if vref != prev_v:
            vi, prev_v = vi + 1, vref
            pop_scoped()
            while len(frames) > 1 and opened[-1] < vi - 1:     # a speech inside a speech ends after the next verse
                frames.pop(), opened.pop(), scoped.pop()
        if f["selah"]:
            pop_scoped()
        if c["parent_key"]:
            set_(k, c["parent_key"], "embedded", c["attach"])
            if f["lemor"]:                 # לֵאמֹר under the speaking clause: the speech hangs on it instead
                if frames and frames[-1] == c["parent_key"]:
                    frames[-1] = k
                else:
                    push(k)
            continue
        resumes = (f["form"] == "wayyiqtol" and f["person"] == "third") or (
            f["aramaic"] and (f["adayin"] or (f["speak"] and f["person"] in ("third", None))))
        if frames and resumes and not (c["parent_key"]):
            frames.clear(), opened.clear(), scoped.clear()     # the narrative resumes (Aramaic: אֱדַיִן, or "the king answered and said")
        if f["sub"] or f["nonfinite_only"]:
            m = first_main.get((vref, len(frames)))           # the first clause of the coordinated run, not the nearest
            if m is not None:
                set_(k, m, "sub_back")
            else:
                set_(k, None, "sub_fwd")
                pending_fwd.append(k)
            continue
        if f["waw_nonverb"] and narrative and not frames and last_main.get((vref, 0)) is not None:
            set_(k, last_main[(vref, 0)], "circ")
            continue
        set_(k, frames[-1] if frames else None, "main")
        for p in pending_fwd:
            if p not in chain(k):          # a forward clause that holds the speech's לֵאמֹר would point into its own speech
                out[p]["parent"] = k
        pending_fwd.clear()
        last_main[(vref, len(frames))] = k
        if not f["formula"]:
            first_main.setdefault((vref, len(frames)), k)
        if not frames and f["form"] == "wayyiqtol":
            narrative = True
        speaks = f["speak"] and (f["verb"] not in ANSWER or amar_after[i])
        narrated = f["person"] == "third" and f["form"] in ("wayyiqtol", "qatal") or f["form"] in PARTICIPLE
        if f["lemor"] or (speaks and (not frames or narrated)):
            push(k)                        # inside a speech only a narrated (3rd person past or participle) speaking clause nests
        elif c.get("poetry") and f["ptc_saying"]:
            push(k, verse_scoped=True)     # Ps 3:3 "many say": the quotation ends with the verse or at סֶלָה
    for k in out:
        out[k]["depth"] = depth(k)
    return out
