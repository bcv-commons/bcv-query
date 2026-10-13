"""Text-level hierarchy of Hebrew clauses (discourse_parent, relation, discourse_attach, tree_depth, text_depth), derived by rule from
MACULA Hebrew features only.

MACULA has no clause-to-clause relations above the verse (a MACULA sentence is one verse; main clauses in a verse are siblings), so the
hierarchy is derived, not passed through. Inputs per clause, all MACULA (CC BY 4.0) plus person from the lexeme spine (same source):
verb form (`wtype`), the clause's first words, the verb's Strong's number, the clause's rule, role and subject phrases, and the MACULA
tree (`parent`). No BHSA input.

Every rule, word list, book group and depth convention is in clause_layout.toml, documented there: what each rule does, examples, and
where it applies (its scope). This module keeps only the mechanics:
- features() computes the clause features described in [features.*];
- derive() walks the clauses in text order with a stack of lines (the narrative, and a line per open speech), tries the rules in the
  order of [rules.*] and links each clause; on("name") asks whether a rule applies in the clause's book.
It contains no Hebrew words, Strong's numbers or book names (a test checks this).

PROFILES. A profile is a settings file that names itself and extends another ([profile] extends = "default" or another profile's
name) and overrides only what it changes. configure(profile=NAME) loads macula/profiles/NAME.toml merged over what it extends;
configure(path) loads any settings file, a full one or a profile (build_clause_layout --config / --profile). A profile may not change
the external sources, the versification data or the rules version, and may only set keys the base has (new book groups excepted).
"""
from __future__ import annotations

import copy
import hashlib
import json
import tomllib
import unicodedata
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("clause_layout.toml")
PROFILES_DIR = Path(__file__).with_name("profiles")
BASE_PROFILE = "default"                          # the profile of clause_layout.toml
PROFILE_FIXED = ("sources", "versification", "version")    # what a profile may not change


def _n(s: str | None) -> str:
    return unicodedata.normalize("NFC", s or "")


def _profile_path(name: str) -> Path:
    return CONFIG_PATH if name == BASE_PROFILE else PROFILES_DIR / f"{name}.toml"


def _merge(base: dict, over: dict, where: str, changed: list[str]) -> None:
    for key, value in over.items():
        here = f"{where}.{key}" if where else key
        if not where and key in PROFILE_FIXED:
            raise ValueError(f"a profile may not change [{key}]")
        if key not in base:
            if where == "books":              # a profile may add a book group for its scopes
                base[key] = copy.deepcopy(value)
                changed.append(here)
                continue
            raise ValueError(f"the profile sets {here}, which the settings it extends don't have")
        if isinstance(value, dict) and isinstance(base[key], dict):
            _merge(base[key], value, here, changed)
        else:
            base[key] = copy.deepcopy(value)
            changed.append(here)


def load_settings(path: str | Path | None = None, profile: str | None = None, _seen: tuple = ()) -> tuple[dict, list, list]:
    """(settings, files, changed): the settings of a file or a profile, merged over what it extends; files = [(name, sha256)] in load
    order; changed = the dotted keys the profiles set."""
    p = Path(path) if path else _profile_path(profile or BASE_PROFILE)
    raw = p.read_bytes()
    cfg = tomllib.loads(raw.decode("utf-8"))
    files = [(p.name, hashlib.sha256(raw).hexdigest())]
    prof = cfg.get("profile", {})
    name, parent = prof.get("name"), prof.get("extends")
    if not name:
        raise ValueError(f"{p.name}: no [profile] name")
    if profile and name != profile:
        raise ValueError(f"{p.name}: [profile] name is {name!r}, expected {profile!r}")
    if parent is None:
        return cfg, files, []
    if parent in _seen + (name,):
        raise ValueError(f"profile {name!r}: a cycle of extends")
    base, base_files, changed = load_settings(None, parent, _seen + (name,))
    over = {k: v for k, v in cfg.items() if k != "profile"}
    _merge(base, over, "", changed)
    base["profile"] = prof
    return base, base_files + files, changed


def configure(path: str | Path | None = None, profile: str | None = None) -> None:
    """Load the settings into the module's constants: clause_layout.toml (profile "default"), a profile by name, or a settings file."""
    global CFG, CONFIG_FILE, CONFIG_SHA256, CONFIG_FILES, PROFILE, PROFILE_CHANGED, RULES_VERSION, GROUPS, RULES, SCOPE, SPLIT_VERSES
    global SPEAK, SAY, SAY_INF, ANSWER, ASK, SWEAR, OATH_FORMULA_VERBS, BE_VERB, WORD_EVENT, DO, HEAR, ADDRESS, DIVINE, PROCLAIM
    global SUB_KIND, SUB_CJ, SUB_ARC, QABEL_DI, REL, REL_AFTER_PREP, INF_PREP, INF_DEFAULT, FORMULA, TIME_WORDS, CONSEQUENCE
    global OATH_CONTENT, OATH_REASON, QUOTING_SUBS, CASE_OPENERS, APODOSIS_MARKERS, WORD_NOUN, EXTENSION_FORMS, LAW_HEAD_WORDS
    global WAW, BE, KE, LE, KI, IM, DI, ADAYIN, QABEL, DENA, KO, HAY, MELEK, SELAH, SHALOM, KEN
    global FINITE, CHAIN_FORMS, CHAIN_FORMS_SPEECH, INFINITIVE, PARTICIPLE, NARRATED, QUOTE_FORMS
    global VOCATIVE_RULE, COMPLEMENT_ROLES, PARAGRAPH_MARKS, RELATIONS, FLAT, TREE_FLAT, FLAT_RULES, LAW_RELATION, LAW_SIBLINGS, LAW_RETURNS, LAW_STAIRCASE
    CFG, files, PROFILE_CHANGED = load_settings(path, profile)
    CONFIG_FILES = files
    CONFIG_FILE, PROFILE, RULES_VERSION = files[-1][0], CFG["profile"]["name"], CFG["version"]
    # the effective settings, whatever files they came from
    CONFIG_SHA256 = hashlib.sha256(json.dumps(CFG, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    GROUPS = {g: set(v["books"]) for g, v in CFG["books"].items()}
    RULES = CFG["rules"]
    SCOPE = {name: r["scope"] for name, r in RULES.items()}
    W = CFG["words"]
    strong = lambda name: set(W[name]["strong"])                          # noqa: E731
    lemmas = lambda name: {_n(x) for x in W[name]["lemmas"]}               # noqa: E731
    SPEAK, SAY, SAY_INF, ANSWER, ASK = strong("speak"), strong("say"), strong("say_infinitive"), strong("answer"), strong("ask")
    SWEAR, OATH_FORMULA_VERBS, BE_VERB, WORD_EVENT, DO = (strong("swear"), strong("oath_formula_verbs"), strong("be"),
                                                         strong("word_event"), strong("do"))
    HEAR, ADDRESS, DIVINE, PROCLAIM = strong("hear"), strong("address"), strong("divine"), strong("proclaim")
    SUB_KIND = {_n(k): v for k, v in W["subordinators"]["relation"].items()}
    SUB_CJ = set(SUB_KIND)
    SUB_ARC = {_n(k): v for k, v in W["subordinators_aramaic"]["relation"].items()}
    QABEL_DI = W["subordinators_aramaic"]["qabel_di"]
    REL, REL_AFTER_PREP = lemmas("relatives"), W["relatives"]["after_preposition"]
    INF_PREP = {_n(k): v for k, v in W["infinitive_preposition"]["relation"].items()}
    INF_DEFAULT = W["infinitive_preposition"]["default"]
    FORMULA, TIME_WORDS = lemmas("formula"), lemmas("time")
    CONSEQUENCE = [[_n(x) for x in seq] for seq in W["consequence"]["sequences"]]
    OATH_CONTENT, OATH_REASON, QUOTING_SUBS = lemmas("oath_content"), lemmas("oath_reason"), lemmas("quoting_subordinators")
    CASE_OPENERS, APODOSIS_MARKERS, LAW_HEAD_WORDS = lemmas("case_openers"), lemmas("apodosis_markers"), lemmas("law_heads")
    WORD_NOUN = strong("word")
    P = {k: _n(v) for k, v in W["particle"].items() if k != "doc"}
    WAW, BE, KE, LE, KI, IM, DI = P["waw"], P["be"], P["ke"], P["le"], P["ki"], P["im"], P["di"]
    ADAYIN, QABEL, DENA, KO, HAY, MELEK = P["adayin"], P["qabel"], P["dena"], P["ko"], P["hay"], P["melek"]
    SELAH, SHALOM, KEN = P["selah"], P["shalom"], P["ken"]
    F = CFG["forms"]
    FINITE, CHAIN_FORMS, CHAIN_FORMS_SPEECH = set(F["finite"]), set(F["chain"]), set(F["chain_in_speech_with_waw"])
    INFINITIVE, PARTICIPLE, NARRATED, QUOTE_FORMS = set(F["infinitive"]), set(F["participle"]), set(F["narrated"]), set(F["quotation"])
    EXTENSION_FORMS = set(F["extension"])
    VOCATIVE_RULE, COMPLEMENT_ROLES = CFG["macula"]["vocative_rule"], set(CFG["macula"]["complement_roles"])
    PARAGRAPH_MARKS = list(CFG["text"]["paragraph_marks"])
    RELATIONS = list(CFG["relations"])
    FLAT = {r for r, v in CFG["relations"].items() if not v["adds_text_level"]}
    TREE_FLAT = {r for r, v in CFG["relations"].items() if not v["adds_tree_level"]}
    FLAT_RULES = set(CFG["depth"]["flat_rules"])
    LAW_RELATION, LAW_SIBLINGS = CFG["depth"]["law"]["relation"], CFG["depth"]["law"]["laws_in_a_row_stand_level"]
    LAW_RETURNS = CFG["depth"]["law"]["return_after_law"]
    LAW_STAIRCASE = CFG["depth"]["law"]["staircase"]
    SPLIT_VERSES = {}
    for ref, v in CFG.get("versification", {}).get("split_verses", {}).items():
        book, cv = ref.split()
        ch, vs = cv.split(":")
        SPLIT_VERSES[(book, int(ch), int(vs))] = (v["from_key"], v["verse_ref_en"])
    _validate()


def _validate() -> None:
    for name, r in RULES.items():
        if not r.get("doc"):
            raise ValueError(f"rule {name}: no doc")
        sc = r["scope"]
        if not r.get("switchable", True) and sc != "all":
            raise ValueError(f"rule {name} is part of the model (switchable = false): its scope must be \"all\"")
        if isinstance(sc, str) and sc not in ("all", "none") and sc.removeprefix("not ") not in GROUPS:
            raise ValueError(f"rule {name}: unknown scope {sc!r}")
    for rel, v in CFG["relations"].items():
        if not v.get("doc") or not isinstance(v.get("adds_text_level"), bool) or not isinstance(v.get("adds_tree_level"), bool):
            raise ValueError(f"relation {rel}: needs doc, adds_text_level and adds_tree_level")


def active(name: str, book: str) -> bool:
    """Does rule `name` apply in `book`? (Its scope in clause_layout.toml.)"""
    return in_scope(SCOPE[name], book)


def in_scope(sc, book: str) -> bool:
    """Is `book` in scope `sc` ("all", "none", a group, "not <group>", a list of books, or true/false)?"""
    if isinstance(sc, bool):
        return sc
    if isinstance(sc, list):
        return book in sc
    if sc in ("all", "none"):
        return sc == "all"
    if sc.startswith("not "):
        return book not in GROUPS[sc[4:]]
    return book in GROUPS[sc]


def param(name: str, key: str):
    return RULES[name][key]


configure()


def is_subordinator(t) -> bool:
    lem = _n(t["lemma"])
    return lem in SUB_CJ or lem in REL or (lem in SUB_ARC and t["wlang"] == "A")


def _strong(t) -> str:
    s = (t["strong"] or "").lstrip("0")
    return "".join(ch for ch in s if ch.isdigit())


def features(toks: list, person: dict[str, str], rule: str | None = None, role: str | None = None,
             subj: list[tuple[int, int]] | None = None, number: dict[str, str] | None = None) -> dict:
    """toks: MACULA word rows of the clause's words (whole words, as segmented), text order. rule, role: the MACULA clause node's.
    subj: word seq ranges (lo, hi) of the clause's subject phrases (MACULA role s). The features are described in [features.*]."""
    verbs = [t for t in toks if t["class"] == "verb"]
    subject = [t for t in toks if t["role"] == "s" or any(lo <= t["seq"] <= hi for lo, hi in subj or ())]
    finite = [t for t in verbs if t["wtype"] in FINITE]
    v = finite[0] if finite else (verbs[0] if verbs else None)
    aramaic = sum(t["wlang"] == "A" for t in toks) * 2 > len(toks)
    waw = bool(toks) and _n(toks[0]["lemma"]) == WAW
    lead = [t for t in toks if not (t["class"] == "cj" and _n(t["lemma"]) == WAW)]
    lead_l = [_n(t["lemma"]) for t in lead[:3]] + ["", "", ""]
    l0, l1 = lead_l[0], lead_l[1]
    lead_words = []                               # the first two words after "and", as the lemmas of their tokens
    for t in lead:
        if not lead_words or (t["verse"], t["word"]) != lead_words[-1][0]:
            if len(lead_words) == 2:
                break
            lead_words.append(((t["verse"], t["word"]), []))
        lead_words[-1][1].append(_n(t["lemma"]))
    in_first_two = {lem for _, lems in lead_words for lem in lems}
    # the subordinator must open the clause (an Aramaic relative inside a clause is the genitive particle)
    sub_kind = None
    if l0 in SUB_CJ or (l0 in SUB_ARC and lead[0]["wlang"] == "A"):
        sub_kind = SUB_ARC[l0] if l0 in SUB_ARC else SUB_KIND[l0]
    elif l0 in REL:
        sub_kind = "relative"
    elif lead and lead[0]["class"] == "prep" and l1 in REL:
        sub_kind = REL_AFTER_PREP
    qi = next((i for i, t in enumerate(lead[:4]) if _n(t["lemma"]) == QABEL), None)
    after_qabel = _n(lead[qi + 1]["lemma"]) if qi is not None and qi + 1 < len(lead) else ""
    if sub_kind is None and after_qabel == DI:
        sub_kind = QABEL_DI
    has_object = "O" in (rule or "").split("-")
    speak = bool(v) and _strong(v) in SPEAK and (bool(finite) or (aramaic and v["wtype"] in PARTICIPLE)) and not (
        _strong(v) in ASK and (has_object or any(_n(t["lemma"]) == SHALOM for t in toks)))
    ptc_free = bool(v) and v["wtype"] in PARTICIPLE and not finite and not speak and not (
        any(t["class"] == "art" and (t["verse"], t["word"]) == (v["verse"], v["word"]) for t in toks) or any(t["role"] == "s" for t in toks)
        or "S" in (rule or "").split("-"))
    inf = bool(verbs) and not finite and not speak and verbs[0]["wtype"] in INFINITIVE
    if sub_kind is None and inf:
        before = [t for t in toks if (t["verse"], t["word"]) == (verbs[0]["verse"], verbs[0]["word"]) and t["class"] == "prep"]
        sub_kind = INF_PREP.get(_n(before[0]["lemma"]) if before else "", INF_DEFAULT)
    elif sub_kind is None and ptc_free and waw:
        sub_kind = "circumstantial"
    actor = any(t["wtype"] == "proper" or _n(t["lemma"]) == MELEK for t in toks)
    noun_head = bool(lead) and not finite and (lead[0]["class"] == "noun" or lead[0]["wtype"] in PARTICIPLE)
    say_inf = [t for t in verbs if _strong(t) in SAY_INF and t["wtype"] == "infinitive construct"]
    say_prep = [_n(t["lemma"]) for t in toks if say_inf and t["class"] == "prep" and (t["verse"], t["word"]) == (say_inf[0]["verse"], say_inf[0]["word"])]
    lemor = bool(say_inf) and say_prep[:1] == [LE]
    addressee = any(t["class"] == "prep" and _strong(t) in ADDRESS for t in toks)
    second = bool(v) and person.get(v["key"]) == "second"
    return {"verb": _strong(v) if v else None, "form": v["wtype"] if v else None, "person": person.get(v["key"]) if v else None,
            "aramaic": aramaic, "waw": waw, "speak": speak, "sub_kind": sub_kind, "lead": l0, "di_first": l0 == DI,
            "participle": ptc_free,
            "lemor": lemor,
            "quote_say": (bool(say_inf) and not lemor and bool(say_prep)) or (bool(v) and _strong(v) in SAY and bool(finite) and not has_object
                          and second and v["wtype"] in QUOTE_FORMS and l0 != KO),
            "say_any": bool(v) and _strong(v) in SAY and bool(finite) and not has_object,
            "addressee": addressee,
            "inf_le": inf and sub_kind == "purpose",
            "ptc_saying": bool(v) and not finite and v["wtype"] in PARTICIPLE and _strong(v) in SAY,
            "formula": l0 in FORMULA, "selah": any(_n(t["lemma"]) == SELAH for t in toks),
            "step": actor and (l0 == ADAYIN or (l0 == BE and l1 == ADAYIN) or after_qabel == DENA),
            "oath": (bool(v) and _strong(v) in SWEAR and person.get(v["key"]) == "first") or l0 == HAY
                    or (l0 == KO and bool(v) and _strong(v) in OATH_FORMULA_VERBS),
            "vocative": (rule or "") == VOCATIVE_RULE and noun_head,
            "imperative": bool(v) and v["wtype"] == "imperative",
            "second": bool(v) and (v["wtype"] == "imperative" or second),
            "pron12": any(t["class"] == "pron" and person.get(t["key"]) in ("first", "second") for t in toks),
            "pron2": any(t["class"] == "pron" and person.get(t["key"]) == "second" for t in toks),
            "pron1": any(t["class"] == "pron" and person.get(t["key"]) == "first" for t in toks),
            "pron3": any(t["class"] == "pron" and person.get(t["key"]) == "third" for t in toks),
            "l1": l1, "negated": any(t["wtype"] == "negative" for t in toks),
            "proper": any(t["wtype"] == "proper" for t in toks),
            "named_subject": bool(subject) and (subject[0]["wtype"] == "proper" or any(_strong(t) in DIVINE for t in subject)),
            "divine": any(_strong(t) in DIVINE for t in subject),
            "compliance": bool(v) and _strong(v) in DO and v["wtype"] == "wayyiqtol" and any(_n(t["lemma"]) == KEN for t in toks),
            "def_subject": bool(subject) and (subject[0]["wtype"] == "proper" or subject[0]["class"] == "art"),
            "word_event": bool(v) and _strong(v) in BE_VERB and any(_strong(t) in WORD_EVENT for t in toks),
            "time_wayehi": bool(v) and _strong(v) in BE_VERB and v["wtype"] == "wayyiqtol" and any(_n(t["lemma"]) in TIME_WORDS for t in toks),
            "consequence": any(lead_l[:len(s)] == s for s in CONSEQUENCE),
            "messenger": KO in in_first_two and bool(v) and _strong(v) in SAY and v["wtype"] == "qatal",
            "command_say": bool(v) and _strong(v) in SAY and not has_object and (v["wtype"] == "imperative" or (
                second and l0 == KO and v["wtype"] == "yiqtol")),
            "say_weqatal": bool(v) and _strong(v) in SAY and not has_object and second and v["wtype"] == "weqatal",
            "proclaim": bool(v) and _strong(v) in PROCLAIM and (v["wtype"] == "imperative" or (second and v["wtype"] == "weqatal" and addressee)),
            "command": bool(v) and (v["wtype"] == "imperative" or (v["wtype"] == "weqatal" and second)),
            "lead_verb": (_strong(lead[0]), lead[0]["wtype"]) if lead and lead[0]["class"] == "verb" else None,
            "subj": "S" in (rule or "").split("-"),
            "number": (number or {}).get(v["key"]) if v else None,
            "law_head": l0 in LAW_HEAD_WORDS,
            "opener": ("HEAR" if bool(v) and v["wtype"] == "imperative" and _strong(v) in HEAR and lead and lead[0] is v else
                       "+".join(_n(t["lemma"]) for t in lead if (t["verse"], t["word"]) == (lead[0]["verse"], lead[0]["word"])) if lead else None),
            "plain_embedded": bool(toks) and toks[0]["class"] not in ("cj", "rel", "prep") and not any(t["wtype"] in INFINITIVE for t in verbs)
                              and not finite and (not verbs or verbs[0]["wtype"] in PARTICIPLE),
            "frame_be": bool(v) and _strong(v) in BE_VERB and v["wtype"] == "weqatal" and len(lead) == 1,
            "bare_np": not verbs and bool(lead) and lead[0]["class"] == "noun" and not sub_kind,
            "extension": KEN in in_first_two and bool(v) and _strong(v) in DO and second and v["wtype"] in EXTENSION_FORMS
                         and any(t["class"] == "prep" and _n(t["lemma"]) == LE for t in toks),
            "then": l0 in APODOSIS_MARKERS,
            "role": role, "circ": waw and len(toks) > 1 and toks[1]["class"] != "verb" and not finite and not speak}


class _Line:
    """A line of main clauses: the narrative, or one speech."""
    def __init__(self, spk: str | None, opened: int = 0, scoped: bool = False, long: bool = False, to_me: bool = False):
        self.spk, self.opened, self.scoped = spk, opened, scoped
        self.long = long                          # a messenger or commanded speech: lasts to the next paragraph mark
        self.carries = False                      # a command at the start of a speech: lasts as long as that speech
        self.prophetic = False                    # rule retold_history_in_prophetic_speech
        self.divine = False                       # God speaks on this line
        self.commander = False                    # a command to speak was given on this line (rule proclaim_returns)
        self.to_me = to_me                        # the speech is addressed to "me" (rules narrator_says, narrator_frames)
        self.messenger = False                    # opened by a messenger formula (rule messenger_returns)
        self.negated = False                      # opened by a negated verb of saying (rule negated_saying_is_quotation)
        self.commanded = False                    # a speech someone is told to give (rule told_speech_ends_at_narrative)
        self.last: str | None = None              # last main clause on the line
        self.verse_mains: dict = {}               # verse -> main clauses of the line in that verse
        self.oath: str | None = None
        self.oath_last: str | None = None         # the oath clause or a clause continuing it directly
        self.subs: dict = {}                      # opener lemma -> last subordinate clause with it (series)
        self.openers: dict = {}                   # first word of a verse-initial clause -> that clause (stanza heads)
        self.turns: dict = {}                     # (speaking verb, form) -> last turn clause opened by it
        self.law_case: str | None = None          # the last case of the current law (rule law_cases_continue_the_law)


def derive(clauses: list[dict]) -> dict[str, dict]:
    """clauses: in text order, each {key, verse (book, ch, v), parent_key, attach, f (features), reset, chapter_start, para}.
    Returns key -> {parent, relation, attach, rule, tree_depth, depth (text_depth)}. The rules are described in clause_layout.toml."""
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
    frame_be_of: dict = {}                        # main clause key -> it is a bare "and it shall be" (rule frame_be_protasis_hangs_forward)
    book_of = {c["key"]: c["verse"][0] for c in clauses}
    rec_of = {c["key"]: c for c in clauses}
    ext: set = set()                              # main clauses with the extension formula (rule extension_formula_returns)
    # rule then_clause_is_apodosis: the main clauses opened by an apodosis marker, by position
    then_at = [i for i, c in enumerate(clauses) if not c["parent_key"] and c["f"]["then"]]
    then_within = param("then_clause_is_apodosis", "within_verses")
    verses_after = param("nested_speech_ends_after_next_verse", "verses_after")
    carry_within = param("command_at_speech_start_carries", "within_verses")

    # lookahead: rule answer_needs_say; rule indirect_speech_opens_none; rule vocative (an address needs a clause addressing someone
    # in its verse); rule narrative_frames (a wayyiqtol of "be" followed by a temporal clause)
    n = len(clauses)
    amar_after, only_inf_after = [False] * n, [False] * n
    seen_amar: dict = {}
    for i in range(n - 1, -1, -1):
        amar_after[i] = seen_amar.get(clauses[i]["verse"], False)
        if clauses[i]["f"]["speak"] and clauses[i]["f"]["verb"] in SAY:
            seen_amar[clauses[i]["verse"]] = True
    second_in_verse: dict = {}
    for c in clauses:
        if c["f"]["second"]:
            second_in_verse[c["verse"]] = True
    # rule casus_pendens: a bare noun phrase followed in its verse by a clause opened by words.case_openers
    next_case = [i + 1 < n and clauses[i + 1]["verse"] == c["verse"] and not clauses[i + 1]["parent_key"]
                 and clauses[i + 1]["f"]["lead"] in CASE_OPENERS for i, c in enumerate(clauses)]
    cp_of: dict = {}                              # clause key -> it is a casus pendens
    prot: dict | None = None                      # the open protasis (rule protasis_continued): key, verse, last clause
    apod: set = set()                             # main clauses that took a fronted protasis (apodoses)
    subish_of: dict = {}                          # clause key -> it is subordinate or embedded (rule speech_in_subordinate_ends_with_verse)
    back: set = set()                             # main clauses that open their verse other than with "and" + weqatal ([depth.law])
    cond_series: set = set()                      # later protases of a series of conditionals ([depth.law] staircase)
    case_apod: dict = {}                          # later protasis of a series -> its own apodosis ([depth.law] staircase)
    case_waiting: str | None = None               # a later protasis whose apodosis is the next main clause
    law_heads: set = set()                        # clauses that start a new law: a casus pendens, a law-head word ([depth.law])
    cp_cases: dict = {}                           # the case under a casus pendens -> the casus pendens
    wayehi_when = [c["f"]["verb"] in BE_VERB and c["f"]["form"] == "wayyiqtol" and i + 1 < n and clauses[i + 1]["verse"] == c["verse"]
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
                if out[p]["relation"] == LAW_RELATION:
                    apod.add(k)                   # k is an apodosis (rule apodosis_keeps_its_chain)
                if out[p]["relation"] is None:
                    out[p]["relation"] = "embedded"
            elif pending_prev.get(p) and active("fallback_to_clause_before", book_of[p]):
                out[p]["parent"] = pending_prev[p]
        pending.clear()

    def fallback_pending():
        for p in pending:
            if out[p]["parent"] is None and pending_prev.get(p) and active("fallback_to_clause_before", book_of[p]):
                out[p]["parent"] = pending_prev[p]
        pending.clear()

    for i, c in enumerate(clauses):
        k, f, vref = c["key"], c["f"], c["verse"]
        on = lambda name: active(name, vref[0])   # noqa: E731
        indirect = only_inf_after[i] and on("indirect_speech_opens_none")
        if c.get("reset") or c.get("chapter_start"):
            fallback_pending()
            prot = None
        if c.get("reset"):                        # rules each_psalm_starts_afresh, chapter_after_mark_starts_afresh (builder)
            lines = [_Line(None, vi)]
            pending.clear()
        elif c.get("para") and on("paragraph_mark_closes_commanded_speech"):
            j = next((x for x in range(1, len(lines)) if lines[x].long and not lines[x].carries), None)
            if j is not None:
                below, formula = lines[j - 1], lines[j].spk
                if on("closed_oracle_returns_to_frame") and lines[j].messenger and below.spk and below.last == formula \
                        and out.get(formula, {}).get("parent") == below.spk and out[formula]["relation"] == "speech":
                    below.last = below.spk        # the oracle's formula opened the speech below: go on from that speech's frame
                lines = lines[:j]
        if not c.get("reset") and c.get("chapter_start"):
            j = next((x for x in range(1, len(lines)) if lines[x].prophetic), None)
            if j is not None and on("chapter_closes_prophetic_speech"):
                lines = lines[:j]
            if on("chapter_restarts_chains"):
                for ln in lines:
                    ln.last = None
                    ln.openers = {}
        if vref != prev_v:
            vi, prev_v = vi + 1, vref
            while on("quotation_ends_with_verse") and len(lines) > 1 and lines[-1].scoped:
                lines.pop()
            while on("nested_speech_ends_after_next_verse") and len(lines) > 2 and not lines[-1].long and lines[-1].opened < vi - verses_after:
                lines.pop()
            if on("nested_speech_ends_at_3rd_person") and len(lines) > 2 and not lines[-1].long and not c["parent_key"] and f["waw"] \
                    and f["person"] == "third" and not f["sub_kind"] and f["form"] in NARRATED and not f["pron12"] and not f["speak"]:
                lines.pop()
        if (f["selah"] and on("selah_ends_quotation")) or (f["messenger"] and on("quotation_lines")):
            while len(lines) > 1 and lines[-1].scoped:
                lines.pop()
        if on("proclaim_returns") and f["proclaim"] and not c["parent_key"] and not f["sub_kind"]:
            j = next((x for x in range(len(lines) - 1, 0, -1) if lines[x].commander), None)
            if j is not None and j < len(lines) - 1:
                lines = lines[:j + 1]
        if on("messenger_returns") and f["messenger"] and not c["parent_key"]:
            j = next((x for x in range(len(lines) - 1, 0, -1) if lines[x].long), None)
            if j is not None and lines[j].messenger:
                lines = lines[:j]
        if on("negated_saying_is_quotation") and len(lines) > 1 and lines[-1].negated and not c["parent_key"] and f["waw"] and f["subj"] \
                and f["pron1"] and not f["sub_kind"] and clauses_verse.get(lines[-1].spk) == vref:
            lines.pop()
        line = lines[-1]
        pron1_of[k], we_of[k], neg_of[k] = f["pron1"], f["word_event"], f["negated"]
        subish_of[k] = bool(f["sub_kind"]) or bool(c["parent_key"])

        # ---- rule embedded_keeps_macula_parent
        if c["parent_key"]:
            rel = ("relative" if f["sub_kind"] == "relative" or c["attach"] else
                   "complement" if f["lemor"] or f["role"] in COMPLEMENT_ROLES else
                   f["sub_kind"] if f["sub_kind"] in ("purpose", "temporal", "causal", "conditional", "complement") else "embedded")
            link(k, c["parent_key"], rel, "embedded_flat" if f["plain_embedded"] else "embedded", c["attach"])
            pr = rec_of.get(c["parent_key"])
            main = rec_of.get(pr["parent_key"]) if pr and pr["parent_key"] else None
            if f["lemor"] and on("word_quote_hangs_on_main") and main and pr["f"]["sub_kind"] == "relative" \
                    and pr["f"]["verb"] in SPEAK and pr.get("attach_strong") in WORD_NOUN \
                    and main["f"]["imperative"] and main["f"]["verb"] in HEAR:      # the call "hear the word which ... spoke, saying"
                # "the word which he spoke, saying": the quotation is the content of the word the main clause names
                link(k, pr["parent_key"], "complement", "word_quote")
            if f["lemor"] and on("lemor_opens_speech"):
                if len(lines) > 1 and lines[-1].spk == c["parent_key"]:
                    lines[-1].spk = k
                else:
                    ln = _Line(k, vi, to_me=pron1_of.get(c["parent_key"], False) or f["pron1"])
                    ln.prophetic = ln.divine = we_of.get(c["parent_key"], False)
                    ln.scoped = on("speech_in_subordinate_ends_with_verse") and subish_of.get(c["parent_key"], False) \
                        and not we_of.get(c["parent_key"], False)
                    if on("commanded_lemor") and cmd_of.get(c["parent_key"]) and len(lines) > 1:
                        ln.long = ln.commanded = True
                        ln.carries = on("command_at_speech_start_carries") and lines[-1].opened >= vi - carry_within
                        ln.prophetic = True
                        lines[-1].commander = True
                    lines.append(ln)
            elif f["quote_say"] and on("quotation_lines"):
                lines.append(_Line(k, vi, scoped=True))
            continue

        # ---- the narrative resumes
        to_me = len(lines) > 1 and lines[1].to_me
        narrator = on("narrator_frames") and to_me and f["form"] == "wayyiqtol" and f["person"] == "third" and f["pron1"] and not f["pron2"] and (
            f["speak"] or f["divine"])
        narrator_says = on("narrator_says") and f["form"] == "wayyiqtol" and f["person"] == "first" and f["verb"] in SAY and not f["pron3"] \
            and not f["pron2"] \
            and not only_inf_after[i] and to_me
        resumes = (f["form"] == "wayyiqtol" and f["person"] == "third" and not f["pron12"]) or narrator or narrator_says or (
            on("aramaic_narrative_steps") and f["aramaic"] and (f["step"] or (
                f["speak"] and f["person"] in ("third", None) and (f["form"] == "qatal" or f["form"] in PARTICIPLE)
                and (f["verb"] not in ANSWER or amar_after[i] or not on("answer_needs_say")))))
        # in the narrative books a message someone is told to deliver (with any oracle quoted in it) is not God speaking now: the
        # narrative resumes after it as after any speech (rule told_speech_ends_at_narrative)
        told = on("told_speech_ends_at_narrative") and any(ln.commanded for ln in lines[1:])
        if on("retold_history_in_prophetic_speech") and any(ln.prophetic for ln in lines[1:]) and not told:
            dated = (f["time_wayehi"] or (wayehi_when[i] and on("narrative_frames"))) and not (f["pron2"] and on("dated_frame_without_you"))
            resumes = f["word_event"] or dated or (f["compliance"] and on("narrative_frames")) or narrator or (
                f["speak"] and f["form"] == "wayyiqtol" and (f["proper"] or (f["def_subject"] and on("narrative_frames")))) or (
                f["form"] == "wayyiqtol" and f["person"] == "third" and f["named_subject"] and not f["pron12"]) or narrator_says
        if len(lines) > 1 and (resumes or (f["word_event"] and f["form"] == "wayyiqtol" and on("word_event_resumes"))):
            lines = lines[:1]
            line = lines[0]
        first_in_verse = prev_top is None or clauses_verse.get(prev_top) != vref
        clauses_verse[k] = vref
        prev_top_key, prev_top = prev_top, k

        # ---- rules inquit, inquit_after_subordinate
        if on("inquit") and line.last is not None and (f["formula"] or (
                f["speak"] and f["person"] == "third" and not f["waw"] and not first_in_verse and f["form"] != "wayyiqtol" and not f["messenger"]
                and not (f["sub_kind"] and on("inquit_not_subordinate"))
                and (on("inquit_after_subordinate") or clauses_verse.get(line.last) == vref))):
            link(k, line.last, "inquit", "inquit")
            continue

        if f["law_head"] and on("law_cases_continue_the_law"):
            line.law_case = None                  # a law-head word: a new law
            law_heads.add(k)
        cp = on("casus_pendens") and f["bare_np"] and next_case[i]
        cp_of[k] = cp
        if cp and on("law_cases_continue_the_law"):
            law_heads.add(k)

        # ---- rule vocative
        if not cp and on("vocative") and f["vocative"] and second_in_verse.get(vref):
            mains = line.verse_mains.get(vref, [])
            if mains:
                link(k, mains[-1], "vocative", "vocative")
            else:
                link(k, None, None, "vocative_fwd")
                out[k]["relation"] = "vocative"
                pending.append(k)
                pending_prev[k] = prev_top_key
            continue

        # ---- rule oath
        if on("oath") and line.oath and f["sub_kind"] in ("causal", "conditional") and (
                f["lead"] in OATH_REASON or (f["lead"] in OATH_CONTENT and (first_in_verse or prev_top_key == line.oath_last))):
            link(k, line.oath, "complement" if f["lead"] in OATH_CONTENT else "causal", "oath")
            continue

        # ---- rule adversative
        if on("adversative") and f["lead"] == KI and f["l1"] == IM and prev_top_key and neg_of.get(prev_top_key):
            link(k, prev_top_key, "adversative", "adversative")
            continue

        # ---- subordinate clauses (one that opens a speech is the speech's first clause)
        if f["sub_kind"] and on("casus_pendens") and prev_top_key and cp_of.get(prev_top_key) and f["lead"] in CASE_OPENERS:
            link(k, prev_top_key, "conditional", "casus_pendens")    # the case hangs under its topic
            cp_cases[k] = prev_top_key
            line.subs[f["lead"]] = k
            prot = {"verse": vref, "last": k, "until": None, "key": None, "pn": (f["person"], f["number"])}
            if on("law_cases_continue_the_law"):
                line.law_case = k                 # a new law: its first case
            continue
        if f["sub_kind"] and not (line.spk and line.last is None):
            prev = line.subs.get(f["lead"]) if f["lead"] else None
            same_ch = prev is not None and clauses_verse.get(prev, (None, None))[:2] == vref[:2]
            pt = prev_top_key
            while on("ki_series_and_look_back") and pt and out.get(pt, {}).get("rule") == "sub_continued":
                pt = out[pt]["parent"]
            # a series needs the same relation, not only the same opener: a fronted "if" is no series member of a "for" before it (Deut
            # 22:6 after 22:5)
            would_be = "conditional" if (f["sub_kind"] == "causal" and f["lead"] == KI and not line.verse_mains.get(vref)
                                         and on("ki_before_main_is_conditional")) else f["sub_kind"]
            law_cases = on("law_cases_continue_the_law") and would_be == "conditional"
            if law_cases:                         # in law: an "if" continues the current law's cases, a fronted "for/if" law starts a new law
                prev = line.law_case if f["lead"] == IM and line.law_case and clauses_verse.get(line.law_case, (None, None))[:2] == vref[:2] \
                    else None
                same_ch = prev is not None
            head = prev
            while head is not None and out.get(head, {}).get("relation") == "parallel":
                head = out[head]["parent"]
            same_rel = head is not None and (out.get(head, {}).get("relation") == would_be or not on("series_needs_same_relation")
                                             or (law_cases and out.get(head, {}).get("relation") == "conditional"))
            if on("subordinate_series") and prev is not None and same_rel and (pt == prev or (f["sub_kind"] == "conditional" and same_ch)):
                link(k, prev, "parallel", "series")
                if (f["sub_kind"] == "conditional" or law_cases) and in_scope(LAW_STAIRCASE, vref[0]):
                    cond_series.add(k)
                    case_waiting = k              # its own apodosis is the next main clause
                    if law_cases:
                        line.law_case = k
                    until = prot.get("until") if prot else None
                    prot = {"verse": vref, "last": k, "until": until, "key": prot.get("key") if prot else None,
                            "pn": (f["person"], f["number"])}
            else:
                mains = line.verse_mains.get(vref, [])
                if mains and on("frame_be_protasis_hangs_forward") and frame_be_of.get(mains[-1]) and f["sub_kind"] in ("conditional", "temporal"):
                    mains = []                    # the protasis after a bare "and it shall be" hangs forward on its apodosis
                if mains:                         # rule subordinate_hangs_back
                    link(k, mains[-1], f["sub_kind"], "sub_back")
                elif line.last is not None and (
                        (first_in_verse and ((on("subordinate_looks_back") and (f["di_first"] and f["aramaic"] or f["participle"]))
                                             or (f["sub_kind"] == "causal" and on("verse_initial_reason_looks_back"))))
                        or (on("ki_series_and_look_back") and f["lead"] == KI and f["sub_kind"] == "causal")):
                    link(k, line.last, "causal" if f["di_first"] else f["sub_kind"], "look_back")
                else:                             # rules subordinate_hangs_forward, ki_before_main_is_conditional
                    rel = "conditional" if f["sub_kind"] == "causal" and f["lead"] == KI and on("ki_before_main_is_conditional") else f["sub_kind"]
                    link(k, None, None, "sub_fwd")
                    out[k]["relation"] = rel
                    if rel == "conditional":
                        prot = {"verse": vref, "last": k, "until": None, "key": k, "pn": (f["person"], f["number"])}
                        if on("law_cases_continue_the_law"):
                            line.law_case = k     # a new law (or the first case of one)
                        # (then_clause_is_apodosis) only a protasis that opens its verse or follows an address; not "if not" after
                        # a negated clause or in an oath ("but rather", Gen 24:38)
                        waits = (first_in_verse or out.get(prev_top_key, {}).get("relation") == "vocative") and not (
                            f["lead"] == IM and f["negated"] and (neg_of.get(prev_top_key) or line.oath))
                        if on("then_clause_is_apodosis") and waits:
                            j = next((j for j in then_at if j > i), None)
                            if j is not None and clauses[j]["verse"][:2] == vref[:2] and clauses[j]["verse"][2] - vref[2] <= then_within:
                                prot["until"] = clauses[j]["key"]
                    pending.append(k)
                    pending_prev[k] = prev_top_key
            if f["lead"]:
                line.subs[f["lead"]] = k
            if f["messenger"] and on("messenger_formula_opens_speech"):
                poem = on("commanded_speech_in_poetry_ends_with_verse")
                ln = _Line(k, vi, scoped=poem, long=not poem, to_me=f["pron1"])
                ln.prophetic = f["divine"] or not on("prophetic_needs_god")
                ln.divine, ln.messenger = f["divine"], True
                lines.append(ln)
            elif on("quotation_lines") and ((f["say_any"] and f["lead"] in QUOTING_SUBS) or f["quote_say"]) and not indirect:
                lines.append(_Line(k, vi, scoped=True))
            continue

        # ---- rule circumstantial
        if on("circumstantial") and f["circ"] and len(lines) == 1 and line.verse_mains.get(vref) \
                and form_of.get(line.verse_mains[vref][-1]) == "wayyiqtol":
            link(k, line.verse_mains[vref][-1], "circumstantial", "circ")
            continue

        # ---- rule waw_continues_subordinate
        if on("waw_continues_subordinate") and f["waw"] and prev_top_key and clauses_verse.get(prev_top_key) == vref and \
                out.get(prev_top_key, {}).get("rule") in ("sub_back", "sub_fwd", "look_back", "series", "oath") + (
                    ("sub_continued",) if on("ki_series_and_look_back") else ()):
            link(k, prev_top_key, "continuation" if f["form"] in CHAIN_FORMS else "coordination", "sub_continued")
            continue

        # ---- rule then_clause_is_apodosis: until the "then" clause, main clauses go on with the protasis
        if prot is not None and prot.get("until") and k != prot["until"] and on("then_clause_is_apodosis") and (
                f["form"] == "wayyiqtol" or f["speak"] or (vref == prot["verse"] and f["form"] in FINITE and f["person"] is not None
                                                           and (f["person"], f["number"]) != prot.get("pn"))):
            prot["until"] = None                  # a wayyiqtol, a new speaker, or the apodosis in the protasis's own verse: no waiting
        if prot is not None and prot.get("until") and k != prot["until"] and on("then_clause_is_apodosis"):
            for p in [p for p in pending if p != prot["key"]]:
                if p not in chain(k):
                    out[p]["parent"] = k
            pending[:] = [p for p in pending if p == prot["key"]]
            link(k, prot["last"], "continuation" if f["form"] in CHAIN_FORMS else "coordination" if f["waw"] else "asyndetic",
                 "protasis_continued")
            prot["last"] = k
            continue

        # ---- rule protasis_continued: an "and"-clause in the open protasis's verse goes on with the protasis
        if prot is not None and on("protasis_continued") and f["waw"] and vref == prot["verse"] and not f["speak"]:
            link(k, prot["last"], "continuation" if f["form"] in CHAIN_FORMS else "coordination", "protasis_continued")
            prot["last"] = k
            continue
        prot = None

        # ---- rule main_clause_chain
        in_speech = len(lines) > 1
        prev_last = line.last
        if line.last is None:
            parent, rel = (line.spk, "speech") if line.spk else (None, None)
        else:
            parent = line.last
            chain_form = f["form"] in CHAIN_FORMS or (in_speech and f["waw"] and f["form"] in CHAIN_FORMS_SPEECH)
            rel = "continuation" if chain_form else "coordination" if f["waw"] else "asyndetic"
            if rel == "asyndetic" and on("asyndetic_climbs_to_run_head"):
                run_verse = clauses_verse.get(parent)
                while out.get(parent, {}).get("relation") in ("continuation", "coordination", "parallel") and out[parent]["parent"] \
                        and clauses_verse.get(out[parent]["parent"]) == run_verse:
                    parent = out[parent]["parent"]
        if on("consequence") and f["consequence"] and line.last is not None:
            rel = "consequence"
            parent = line.last
        if on("subject_starts_new_step") and rel == "continuation" and f["subj"]:
            x = parent
            while x and not out[x].get("subj") and out[x]["relation"] in ("continuation", "coordination", "parallel") and out[x]["parent"] \
                    and not (x in apod and on("apodosis_keeps_its_chain")):
                x = out[x]["parent"]
            if out.get(x, {}).get("subj"):
                parent = x
        if on("stanza_heads") and rel == "asyndetic" and first_in_verse and f["opener"]:
            head = line.openers.get(f["opener"])
            if head is not None:
                parent, rel = head, "parallel"
        turn = f["lead_verb"] if f["speak"] and f["lead_verb"] and not f["waw"] and f["form"] != "wayyiqtol" else None
        if on("repeated_turn_is_parallel") and turn and turn in line.turns:
            parent, rel = line.turns[turn], "parallel"
        link(k, parent, rel, "main")
        out[k]["subj"] = f["subj"]
        form_of[k] = f["form"]
        if on("stanza_heads") and first_in_verse and f["opener"]:
            line.openers[f["opener"]] = k
        if turn:
            line.turns[turn] = k
        cmd_of[k] = f["command"]
        frame_be_of[k] = f["frame_be"]
        if case_waiting is not None:
            case_apod[case_waiting] = k
            case_waiting = None
        if first_in_verse and not (f["waw"] and f["form"] == "weqatal"):
            back.add(k)
        if f["extension"] and on("extension_formula_returns"):
            ext.add(k)
        resolve_pending(k)
        line.last = k
        line.verse_mains.setdefault(vref, []).append(k)
        if f["oath"]:
            if line.oath is None or clauses_verse.get(line.oath) != vref:
                line.oath = k
            line.oath_last = k
        elif line.oath_last == prev_top_key and f["waw"] and clauses_verse.get(line.oath) == vref:
            line.oath_last = k

        # ---- speeches that open at this main clause
        speaks = f["speak"] and (f["verb"] not in ANSWER or amar_after[i] or not on("answer_needs_say")) and not indirect \
            and f["form"] != "imperative"
        narrated = (f["person"] == "third" and f["form"] in NARRATED) or f["form"] in PARTICIPLE
        command = f["command_say"] or (f["say_weqatal"] and (not on("command_needs_addressee") or f["addressee"] or cmd_of.get(prev_last, False)))
        poem = on("commanded_speech_in_poetry_ends_with_verse")
        if (f["messenger"] and on("messenger_formula_opens_speech")) or (
                command and in_speech and not indirect and on("command_to_say_opens_speech")):
            ln = _Line(k, vi, scoped=poem, long=not poem, to_me=f["pron1"])
            ln.carries = command and in_speech and line.opened >= vi - carry_within and not poem and on("command_at_speech_start_carries")
            ln.prophetic = command or f["divine"] or not on("prophetic_needs_god")
            ln.commanded = command
            ln.divine = f["messenger"] and f["divine"]
            ln.messenger = f["messenger"]
            if command:
                line.commander = True
            lines.append(ln)
        elif on("quotation_lines") and (f["quote_say"] or (f["say_weqatal"] and not command)) and not indirect:
            lines.append(_Line(k, vi, scoped=True))
        elif (f["lemor"] and on("lemor_opens_speech")) or (speaks and (not in_speech or narrated)):
            ln = _Line(k, vi, to_me=f["pron1"])
            ln.scoped = on("future_saying_is_quotation") and not f["lemor"] and not narrated and not (
                f["person"] == "first" and f["form"] in NARRATED)
            ln.divine = f["divine"] and narrated
            if on("negated_saying_is_quotation") and f["negated"] and f["verb"] in SAY and not f["lemor"]:
                ln.scoped = ln.negated = True
            lines.append(ln)
        elif on("participle_of_saying_quotes") and f["ptc_saying"]:
            lines.append(_Line(k, vi, scoped=True))

    fallback_pending()
    for k in out:
        ch = chain(k)
        out[k]["tree_depth"] = sum(1 for x in ch[:-1] if out[x]["relation"] not in TREE_FLAT)
        out[k]["depth"] = sum(1 for x in ch[:-1] if out[x]["relation"] not in FLAT and out[x]["rule"] not in FLAT_RULES)
        out[k].pop("subj", None)
    for k, d in _law_depths(out, back if LAW_RETURNS else set(), cond_series, ext, case_apod, law_heads, cp_cases).items():
        out[k]["depth_law"] = d
    return out


def _law_depths(out: dict[str, dict], back: set[str] = frozenset(), cond_series: set[str] = frozenset(),
                ext: set[str] = frozenset(), case_apod: dict | None = None, law_heads: set[str] = frozenset(),
                cp_cases: dict | None = None) -> dict[str, int]:
    """text_depth_law ([depth.law]): where a protasis comes before its apodosis, the protasis takes the apodosis's parent and counts one
    level; the apodosis hangs on the protasis and counts none. Every other link counts as for text_depth. back: main clauses that open
    their verse other than with "and" + weqatal; after an apodosis they go back to the level the law stands on."""
    par = {k: v["parent"] for k, v in out.items()}
    w = {k: int(v["relation"] not in FLAT and v["rule"] not in FLAT_RULES) for k, v in out.items()}
    protases: set[str] = set()
    apodoses: dict[str, str] = {}                 # apodosis -> its protasis
    for p in sorted(k for k, v in out.items() if v["relation"] == LAW_RELATION and v["parent"] and k < v["parent"]):
        a = out[p]["parent"]
        if par[p] != a or par.get(a) == p:
            continue
        new_parent = par[a]
        if LAW_SIBLINGS:                          # laws in a row: up the flat links from the apodosis to an earlier protasis
            x, seen = par[a], set()
            while x is not None and x not in seen and x not in protases and w.get(x) == 0:
                seen.add(x)
                x = par[x]
            if x in protases:
                new_parent = par[x]               # stand level with it, not under its apodosis
        par[p], w[p] = new_parent, 1
        par[a], w[a] = p, 0
        protases.add(p)
        apodoses[a] = p
    if LAW_SIBLINGS and law_heads:
        # a new law (a casus pendens, a law-head word) stands where the law before it stands, not on that law's last clause: up the flat
        # links to the earlier law's first case, its casus pendens, or an earlier law head
        cp_cases = cp_cases or {}
        done: set[str] = set()
        for h in sorted(law_heads):
            x, seen = par.get(h), set()
            while x is not None and x not in seen and x not in protases and x not in cp_cases and x not in done \
                    and (w.get(x) == 0 or x in cond_series):
                seen.add(x)
                x = par[x]
            if x in protases or x in done:
                par[h] = par[x]
            elif x in cp_cases:
                par[h] = par[cp_cases[x]]
            done.add(h)
    if cond_series:
        # a later case's own apodosis stands beside it, and what goes on from it moves with it
        for p, a in sorted((case_apod or {}).items()):
            if a in apodoses or par.get(a) == p or p not in cond_series:
                continue
            par[a], w[a] = p, 0
            apodoses[a] = p
        # each later case one level under the case before, when that case had its own apodosis (alternatives without one stand level)
        cased = set(apodoses.values())
        for k in cond_series:
            if par.get(k) in cased:
                w[k] = 1
    returned: set[str] = set()                    # after a law, these clauses go back to the level the law stands on: the extension
    for k in sorted(set(back) | set(ext)):        # formula (rule extension_formula_returns), and with return_after_law the clauses in back
        if k in apodoses:
            continue
        x, seen = par.get(k), set()
        while x is not None and x not in seen and x not in apodoses and x not in returned and w.get(x) == 0:
            seen.add(x)
            x = par[x]
        if x in apodoses:
            par[k] = par[apodoses[x]]
            returned.add(k)
    memo: dict[str, int] = {}

    def depth(k: str) -> int:
        seen, x = [], k
        while x is not None and x not in memo and x not in seen and par.get(x) is not None:
            seen.append(x)
            x = par[x]
        base = memo.get(x, 0)
        for y in reversed(seen):
            base += w[y]
            memo[y] = base
        return memo.get(k, 0)
    return {k: depth(k) for k in out}
