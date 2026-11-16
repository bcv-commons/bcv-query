"""One Context-Fabric dataset on MACULA's keys: the texts in the original biblical languages with the published layers and, later, the
bridges between Hebrew and Greek (plan: internal-docs/bridge-corpus-plan-2026-11-16.md). Steps 1, 2 and 5: the Tanakh and the Greek New
Testament with every layer as features and edges inside a text; the two Hebrew New Testaments (Salkinson-Ginsburg `heb_scg`, Delitzsch
`heb_mod`) as texts of their own, with our analysis, their clause segments, their links to the Greek NT and their marked quotations.

    python -m macula.build_bridge_corpus --fetch             download the pinned releases (bridge_corpus_pins.json) and check them
    python -m macula.build_bridge_corpus --build             -> macula/data/bridge-corpus/build-<pins>/ (the dataset) and its report.json
    python -m macula.build_bridge_corpus --check [DIR]       load a build, time it, run the fixed queries

Rules of the build (plan 4.1): the releases stay the source and this is a derived view; every input is pinned and the pins are written
into the dataset; every feature states its origin, licence and whether a model made it; no English content values (MACULA's gloss and the
layouts' alt_eng and text columns are left out) and no BHSA values; a new version of a layer means a new build.

Units: word (the base unit: a word part in Hebrew, a word in Greek), token (a written Hebrew word), phrase (a clause constituent of
argument-roles), line (a row of a clause layout), clause (the layers' clause key: in Hebrew a clause can have several lines, in Greek
each line is a clause; in a Hebrew NT a clause is a segment of hebrew-nt-analysis), quotation, verse, chapter, book, text.
Sections: `sec` on books (GEN, MAT; SCG.MAT and DEL.MAT in the Hebrew NTs, since one book name in two texts breaks the lookup), chapter,
verse; `book` stays the plain name on every section.
Features: the source's word features have no prefix (mid = the MACULA key, text, lang, lemma, strong, pos, ...); a layer's column is
`<prefix><column>` (lay_ layout, cc_ clause-columns, cn_ clause-connectives, cx_ clause-extras, ta_ time-aspect, ar_ argument-roles,
rs_ reference-status, nr_ noun-relations, ws_ word-senses, we_ inclusive-we, ad_ addressees, m_ model-made).
Edges: parent and discourse_parent (clause to clause), arg (verb to its argument phrase, value: the relation), ar_head and ar_prep
(phrase to word), nr_relation / nr_form / nr_animacy (head noun to dependent), frame (verb to argument word, MACULA's role), ref (word
to the word it refers to, MACULA's kind); between texts: heb_scg and heb_mod (Greek NT word to Hebrew NT word part, value: the aligner's
class, `compact` for heb_mod), parallel (Hebrew NT verse to the Greek NT verse of the same number), quotes (Hebrew NT verse to the Tanakh
verse it follows, value: the weight).
Lexeme, concept and person units and the tier edges: see bridge_corpus_units. word-parts (wp_), hebrew-phrase-types-model (m_pt_) and
passage-facts (fact units, pf_): see bridge_corpus_more. MACULA's trees (sentence and wordgroup units, tr_, the source's trailers): see
bridge_corpus_trees.
The Septuagint: see bridge_corpus_lxx (texts septuagint; words, lxx and carried edges, parallel verses, LXX.<BOOK> sections).
Hebrew NT words carry the source's word features under the same names (text, lemma, strong, pos, role, person) and the rest of the
analysis under hna_ (source macula / model, lexeme, form, word, p_split as 0 to 100, token); `hkey` = "<edition> BOOK C:V i.part".
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sqlite3
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PINS = HERE / "bridge_corpus_pins.json"
DATA = HERE / "data" / "bridge-corpus"
INPUTS = DATA / "inputs"
ROOT_RESOURCES = HERE.parents[1] / "resources"
TYPES = ("token", "phrase", "line", "clause", "quotation", "verse", "chapter", "book", "text", "lexeme", "concept", "person", "fact", "sentence", "wordgroup")     # after word; nodes are numbered type by type
WORD = (("lemma", "lemma"), ("strong", "strong"), ("class", "pos"), ("role", "role"), ("stem", "stem"), ("person", "person"), ("number", "number"),
        ("gender", "gender"), ("case_", "case"), ("tense", "tense"), ("voice", "voice"), ("mood", "mood"), ("degree", "degree"), ("state", "state"))
LANG = {"H": "hbo", "A": "arc", "": "grc"}
TEXT = {"hbo": "tanakh", "grc": "greek_nt"}
HNT = {"heb_scg": ("salkinson", "SCG"), "heb_mod": ("delitzsch", "DEL")}
CORPUS = {"hebrew": "hbo", "greek-nt": "grc"}
CLAUSE_LAYERS = (("clause-columns", "cc_"), ("clause-connectives", "cn_"), ("clause-extras", "cx_"), ("time-aspect", "ta_"))
LINE_SKIP = {"book", "chapter", "verse", "words", "text", "first", "last", "alt_eng", "clause_key", "parent_key", "discourse_parent"}
REFERENCES = {"lay_verse_ref_en", "cc_ref", "lay_via", "hkey", "lkey"}                  # verse references and lists of codes: Latin script with spaces, no English text
QUERIES = (                                              # fixed queries with their hits in this build (the check fails when they move)
    ("speech clauses in Ruth, imperative or prohibitive, with an undergoer phrase that holds a noun",
     "book book=RUT\n  clause cc_speech>0 cc_force=imperative|prohibitive\n    phrase ar_role=undergoer\n      word pos=noun\n", 6),
    ("clauses of the Tanakh with the verb of Strong's number 1980 whose time is future", "text name=tanakh\n  clause ta_time=future\n    word strong=1980\n", 174),
    ("Greek NT verbs whose subject phrase is an actor and holds a proper name of a person",
     "text name=greek_nt\n  v:word pos=verb\n  p:phrase ar_role=actor\n    word rs_definite=proper rs_animacy=person\nv -arg=s> p\n", 372),
    ("words with a model-made concept inside a quotation spoken by c0001", "quotation lay_speaker_id=c0001\n  word m_concept\n", 26194),
    ("nouns that are the A1 of a form of ἀγαπάω (MACULA's frames)", "v:word lemma=ἀγαπάω\na:word pos=noun\nv -frame=A1> a\n", 50),
    ("Hebrew kinship pairs (noun-relations)", "a:word lang=hbo\nb:word\na -nr_relation=kin> b\n", 6560),
    ("future clauses whose parent clause is imperative", "c:clause cc_force=imperative\nd:clause ta_time=future\nd -parent> c\n", 21),
    ("Greek NT words of λόγος that Salkinson renders by דָּבָר", "g:word lemma=λόγος\nh:word strong=1697\ng -heb_scg> h\n", 249),
    ("the same in Delitzsch", "g:word lemma=λόγος\nh:word strong=1697\ng -heb_mod> h\n", 267),
    ("Salkinson verses that follow a verse of Isaiah", "v:verse\nt:verse book=ISA\nv -quotes> t\n", 190),
    ("Hebrew NT words of the verb Strong 1980 inside a Salkinson clause of John", "text name=salkinson\n  book book=JHN\n    clause\n      word strong=1980\n", 114),
    ("Tanakh words of הלך placed on a Septuagint word of πορεύομαι", "h:word strong=1980\ng:word lemma=πορεύομαι\nh -lxx> g\n", 777),
    ("the same, placed only by the Greek number", "h:word strong=1980\ng:word lemma=πορεύομαι\nh -lxx=number> g\n", 20),
    ("carried Septuagint lines of Ruth whose Hebrew line is imperative speech",
     "book sec=LXX.RUT\n  g:line\nh:line\nc:clause cc_force=imperative\n  h\ng -carried> h\n", 18),
    ("Theodotion's verses of Daniel 7", "book sec=LXX.DAN-TH\n  chapter chapter=7\n    verse\n", 28),
    ("Greek lexemes that MACULA's Septuagint numbers pair with הלך", "h:lexeme lex_key=hbo:1980\ng:lexeme\nh -tier_macula> g\n", 17),
    ("Hebrew lexemes paired with a Greek lexeme by both Salkinson and Delitzsch", "h:lexeme\ng:lexeme\nh -tier_heb_scg> g\nh -tier_heb_mod> g\n", 1490),
    ("lexemes found in the Tanakh and both Hebrew NTs", "lexeme lex_texts=delitzsch,salkinson,tanakh\n", 2173),
    ("quotations whose speaker is a deity", "q:quotation\np:person ad_type=deity\nq -speaker> p\n", 1509),
    ("Septuagint words inside the unit of one Greek lexeme with an NT number", "lexeme lex_key=grc:πορεύομαι\n  word lkey\n", 990),
    ("Greek NT verbs with a syllabic augment (word-parts)", "word pos=verb wp_part_features~augment=syllabic\n", 4408),
    ("Hebrew phrases typed Instrument by the model whose preposition is בְּ", "phrase m_pt_label=Instrument\n  word strong=0871a\n", 2159),
    ("imperative facts inside a quotation fact of the Tanakh", "q:fact pf_kind=quote\n  f:fact pf_kind=force pf_value=fc.imp\n    word lang=hbo\n", 15171),
    ("semantic-domain facts tied to their quotation", "a:fact pf_kind=domain\nb:fact pf_kind=quote\na -pf_of> b\n", 6499),
    ("Hebrew words joined by maqaf to the next", "word lang=hbo trailer=־\n", None),
    ("Greek NT prepositional groups inside a clause group that is the object", "c:wordgroup tr_cls=cl tr_role=o\n  wordgroup tr_cls=pp\n", None),
    ("Hebrew head groups that are noun phrases, under a prepositional phrase", "p:wordgroup tr_cls=pp\nn:wordgroup tr_cls=np tr_head=1\nn -tr_parent> p\n", None),
)


def pins() -> dict:
    return json.loads(PINS.read_text())


def version(p: dict | None = None) -> str:
    return "0.1.0-dev+" + hashlib.sha256(json.dumps(p or pins(), sort_keys=True).encode()).hexdigest()[:8]


def folder(name: str, pin: dict) -> Path:
    return INPUTS / f"{name}@{pin['tag']}"


def fetch() -> None:
    """each layer's files at its tag, into data/bridge-corpus/inputs/<name>@<tag>; the tag must still be the pinned commit and the card's licence the pinned one"""
    from huggingface_hub import HfApi, snapshot_download
    api, p = HfApi(), pins()
    for name, pin in p["layers"].items():
        sha = api.dataset_info(f"bcv-commons/{name}", revision=pin["tag"]).sha
        if not sha.startswith(pin["revision"]):
            raise SystemExit(f"{name}: tag {pin['tag']} is {sha[:8]}, the pin says {pin['revision']}")
        out = folder(name, pin)
        snapshot_download(f"bcv-commons/{name}", repo_type="dataset", revision=sha, allow_patterns=[*pin["files"], "README.md"], local_dir=out)
        card = (out / "README.md").read_text(encoding="utf-8")
        lic = next((l.split(":", 1)[1].strip() for l in card.split("---")[1].splitlines() if l.startswith("license:")), "")
        if lic != pin["licence"]:
            raise SystemExit(f"{name}: the card says licence {lic!r}, the pin {pin['licence']!r}")
        (out / "PIN.json").write_text(json.dumps({"repo": f"bcv-commons/{name}", "tag": pin["tag"], "commit": sha, "licence": lic}) + "\n")
        print(f"[bridge_corpus] {name}@{pin['tag']} = {sha[:8]} ({lic})")


def table(name: str, pattern: str) -> list[dict]:
    import pyarrow.parquet as pq
    files = sorted(folder(name, pins()["layers"][name]).glob(pattern))
    if not files:
        raise SystemExit(f"{name}: no {pattern} in {folder(name, pins()['layers'][name])}; run --fetch")
    return [r for f in files for r in pq.read_table(f).to_pylist()]


def value(v):
    """a feature value, or None for nothing: lists as one string, true and false as 1 and 0, other numbers as they are"""
    if v is None or v == "" or v == []:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, list):
        return " ".join(json.dumps(x, ensure_ascii=False, sort_keys=True) if isinstance(x, (dict, list)) else str(x) for x in v)
    if isinstance(v, float):
        return int(round(100 * v))
    return v


class Corpus:
    """nodes by type with their words, features and edges by handle (a word's number, or (type, index) for any other unit)"""

    def __init__(self):
        self.slot: dict[str, int] = {}                                  # MACULA key -> word number
        self.nodes: dict[str, list] = {t: [] for t in TYPES}
        self.at: dict[str, dict] = {t: {} for t in TYPES}               # type -> key -> handle
        self.F: dict = collections.defaultdict(dict)
        self.E: dict = collections.defaultdict(lambda: collections.defaultdict(dict))
        self.origin: dict[str, str] = {}
        self.given: collections.Counter = collections.Counter()         # values given per feature: more than it holds = one unit got two rows
        self.report: dict = {"layers": {}}

    def node(self, typ: str, slots, key=None):
        slots = set(slots)
        if not slots:
            return None
        self.nodes[typ].append(slots)
        h = (typ, len(self.nodes[typ]) - 1)
        if key is not None:
            self.at[typ][key] = h
        return h

    def put(self, h, row: dict, prefix: str, layer: str, skip=()) -> None:
        for k, v in row.items():
            v = None if k in skip else value(v)
            if v is not None:
                self.F[prefix + k.rstrip("_")][h] = v
                self.given[prefix + k.rstrip("_")] += 1
                self.origin.setdefault(prefix + k.rstrip("_"), layer)

    def set(self, name: str, h, v, layer: str) -> None:
        if v is not None and v != "":
            self.F[name][h] = v
            self.given[name] += 1
            self.origin.setdefault(name, layer)

    def edge(self, name: str, a, b, v, layer: str) -> bool:
        if a is None or b is None:
            return False
        self.E[name][a][b] = v
        self.origin.setdefault(name, layer)
        return True

    def words(self, keys) -> list[int]:
        return [self.slot[k] for k in keys if k in self.slot]


def add_words(c: Corpus, db: Path) -> None:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = [r for lang in ("hbo", "grc") for r in con.execute("select * from macula_words where lang = ? order by key", (lang,))]
    sections: dict = collections.OrderedDict()
    for i, r in enumerate(rows):
        s = c.slot[r["key"]] = i + 1
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        same_token = r["lang"] == "hbo" and nxt is not None and nxt["key"][:11] == r["key"][:11]
        c.F["mid"][s], c.F["text"][s], c.F["lang"][s], c.F["trailer"][s] = r["key"], r["text"], LANG[r["wlang"]], "" if same_token else " "
        for col, name in WORD:
            if r[col]:
                c.F[name][s] = r[col]
        sections.setdefault((r["lang"], r["book"], r["chapter"], r["verse"]), []).append(s)
        if r["lang"] == "hbo":
            c.at["token"].setdefault(r["key"][:11], []).append(s)
    for name in ("mid", "text", "lang", "trailer", *(n for _, n in WORD)):
        c.origin[name] = "words"
    tokens, c.at["token"] = c.at["token"], {}
    for k, sl in tokens.items():
        c.set("mid", c.node("token", sl, k), k, "words")
    chapters, books, texts = collections.OrderedDict(), collections.OrderedDict(), collections.OrderedDict()
    for (lang, b, ch, v), sl in sections.items():
        h = c.node("verse", sl, (TEXT[lang], b, ch, v))
        c.F["book"][h], c.F["chapter"][h], c.F["verse"][h] = b, ch, v
        chapters.setdefault((lang, b, ch), []).extend(sl)
    for (lang, b, ch), sl in chapters.items():
        h = c.node("chapter", sl, (TEXT[lang], b, ch))
        c.F["book"][h], c.F["chapter"][h] = b, ch
        books.setdefault((lang, b), []).extend(sl)
    for (lang, b), sl in books.items():
        h = c.node("book", sl, (TEXT[lang], b))
        c.F["book"][h] = c.F["sec"][h] = b
        texts.setdefault(lang, []).extend(sl)
    for lang, sl in texts.items():
        c.F["name"][c.node("text", sl, TEXT[lang])] = TEXT[lang]
    for name in ("book", "chapter", "verse", "name", "sec"):
        c.origin[name] = "words"
    c.report["words"] = {"hbo": sum(1 for r in rows if r["lang"] == "hbo"), "grc": sum(1 for r in rows if r["lang"] == "grc")}
    for edge, sql in (("frame", "select verb_key, arg_key, role from frames"), ("ref", "select src_key, tgt_key, kind from refs")):
        st = collections.Counter()
        for a, b, v in con.execute(sql):                                # a target can be several words (their keys in one string) or none (zeros)
            n = len(a)
            tos = [b[i:i + n] for i in range(0, len(b), n)] if len(b) % n == 0 else [b]
            st["rows"] += 1
            st["rows with no word as target (zeros)"] += not any(int(t) for t in tos if t.isdigit())
            placed = [c.edge(edge, c.slot.get(a), c.slot.get(t), v, "words") for t in tos if not t.isdigit() or int(t)]
            st["edges"] += sum(placed)
            st["targets not found"] += len(placed) - sum(placed)
        c.report["layers"][f"words: {edge}"] = dict(st)


def add_layout(c: Corpus) -> None:
    """lines and clauses of both layouts, the clause edges, the quotations"""
    quotes: dict = collections.defaultdict(list)
    links = []                                                          # (edge, clause key, target key)
    for name, key, parent in (("hebrew-clause-layout", "clause_key", "parent_key"), ("greek-nt-clause-layout", "first", "parent")):  # the key the layers use
        rows = table(name, pins()["layers"][name]["files"][0])
        spans: dict = collections.OrderedDict()
        st = collections.Counter()
        for r in rows:
            sl = c.words(r["words"])
            st["words not found"] += len(r["words"]) - len(sl)
            h = c.node("line", sl)
            st["rows"] += 1
            st["placed"] += h is not None
            if h is None:
                continue
            c.put(h, r, "lay_", name, LINE_SKIP)
            c.set("lay_clause_key", h, r[key], name)
            spans.setdefault(r[key], []).extend(sl)
            if r["quotation"]:
                quotes[r["quotation"]].append((sl, r))
            for e, col in (("parent", parent), ("discourse_parent", "discourse_parent")):
                if r.get(col):
                    links.append((e, r[key], r[col], name))
        for k, sl in spans.items():
            c.set("mid", c.node("clause", sl, k), k, name)
        st["clauses"] = len(spans)
        c.report["layers"][name] = dict(st)
    for e, a, b, name in dict.fromkeys(links):
        ok = c.edge(e, c.at["clause"].get(a), c.at["clause"].get(b), None, name)
        c.report["layers"][name][f"{e}: {'placed' if ok else 'target is no clause'}"] = c.report["layers"][name].get(f"{e}: {'placed' if ok else 'target is no clause'}", 0) + 1
    for q, parts in quotes.items():
        h = c.node("quotation", [s for sl, _ in parts for s in sl], q)
        r = parts[0][1]
        c.set("mid", h, q, "layout")
        for k in ("quote_level", "speaker", "speaker_id", "speaker_name", "speaker_basis"):
            c.set(f"lay_{k}", h, value(r.get(k)), "hebrew-clause-layout" if "clause_key" in r else "greek-nt-clause-layout")


def add_clause_layers(c: Corpus) -> None:
    for name, prefix in CLAUSE_LAYERS:
        st = collections.Counter()
        for file in CORPUS:
            for r in table(name, f"data/{file}.parquet"):
                h = c.at["clause"].get(r["clause_key"])
                st["rows"] += 1
                st["placed"] += h is not None
                if h is not None:
                    c.put(h, r, prefix, name, {"clause_key"})
        c.report["layers"][name] = dict(st)


def add_phrases(c: Corpus) -> None:
    st = collections.Counter()
    for file in CORPUS:
        for r in table("argument-roles", f"data/{file}.parquet"):
            keys = r["words"].split()
            sl = c.words(keys)
            h = c.node("phrase", sl)
            st["rows"] += 1
            st["placed"] += h is not None and len(sl) == len(keys)
            st["clause not found"] += r["clause_key"] not in c.at["clause"]
            if h is None:
                continue
            c.put(h, r, "ar_", "argument-roles", {"clause_key", "words", "head", "verb", "prep"})
            st["arg edges"] += c.edge("arg", c.slot.get(r["verb"]), h, r["relation"], "argument-roles")
            st["head edges"] += c.edge("ar_head", h, c.slot.get(r["head"]), None, "argument-roles")
            st["prep edges"] += c.edge("ar_prep", h, c.slot.get(r["prep"]), None, "argument-roles")
            for col in ("head", "verb", "prep"):
                st[f"{col} not found"] += bool(r[col]) and r[col] not in c.slot
    c.report["layers"]["argument-roles"] = dict(st)


def add_word_layers(c: Corpus) -> None:
    st = collections.Counter()
    for file in CORPUS:
        for r in table("reference-status", f"data/{file}.parquet"):
            s = c.slot.get(r["head"])
            st["rows"] += 1
            st["placed"] += s is not None
            if s is not None:
                c.put(s, r, "rs_", "reference-status", {"clause_key", "head"})
    c.report["layers"]["reference-status"] = dict(st)
    st = collections.Counter()
    for file in CORPUS:
        for r in table("noun-relations", f"data/{file}.parquet"):
            a, b = c.slot.get(r["head"]), c.slot.get(r["dependent"])
            st["rows"] += 1
            st["placed"] += c.edge("nr_relation", a, b, r["relation"], "noun-relations")
            c.edge("nr_form", a, b, r["form"], "noun-relations")
            if r["animacy"]:
                c.edge("nr_animacy", a, b, r["animacy"], "noun-relations")
    c.report["layers"]["noun-relations"] = dict(st)
    st, by = collections.Counter(), collections.OrderedDict()
    for r in table("word-senses", "data/words.parquet"):
        by.setdefault(r["key"], []).append(r)
        st["rows"] += 1
    for k, rs in by.items():                                            # a word with several senses: the values joined with |, in the release's order
        s = c.slot.get(k)
        st["placed"] += len(rs) if s is not None else 0
        st["words"] += s is not None
        if s is not None:
            c.put(s, {col: "|".join(str(r[col] or "") for r in rs) if len(rs) > 1 else rs[0][col] for col in rs[0]}, "ws_", "word-senses", {"key", "lang"})
    c.report["layers"]["word-senses"] = dict(st)
    st = collections.Counter()
    for r in table("inclusive-we", "data/words.parquet"):
        s = c.slot.get(r["key"])
        st["rows"] += 1
        st["placed"] += s is not None
        if s is not None:
            c.put(s, r, "we_", "inclusive-we", {"key", "lang", "book", "chapter", "verse", "clause_key"})
    c.report["layers"]["inclusive-we"] = dict(st)
    st = collections.Counter()
    for r in table("hebrew-word-concepts-model", "data/tokens.parquet"):
        s = c.slot.get(r["key"])
        st["rows"] += 1
        st["placed"] += s is not None
        if s is not None:
            c.put(s, {"concept": r["concept"], "concept_labeller": r["labeller"], "concept_confidence": r["jev_confidence"]}, "m_", "hebrew-word-concepts-model")
    c.report["layers"]["hebrew-word-concepts-model"] = dict(st)
    st = collections.Counter()
    for r in table("addressees", "data/quotations.parquet"):
        h = c.at["quotation"].get(r["quote"])
        st["rows"] += 1
        st["placed"] += h is not None
        if h is not None:
            c.put(h, r, "ad_", "addressees", {"corpus", "quote", "first"})
    c.report["layers"]["addressees"] = dict(st)


def add_hebrew_nt(c: Corpus) -> None:
    """the two Hebrew NTs: words, tokens, clause segments, sections, text; then the links to the Greek NT, the parallel verses, the quotes"""
    import pyarrow.parquet as pq
    an, br = folder("hebrew-nt-analysis", pins()["layers"]["hebrew-nt-analysis"]), folder("hebrew-nt-bridge", pins()["layers"]["hebrew-nt-bridge"])
    for ed, (name, tag) in HNT.items():
        st = collections.Counter()
        rows = [r for r in pq.read_table(an / ed / "words.parquet").to_pylist() if r["class"] != "verse-number"]
        tokens, segs, verses = collections.OrderedDict(), collections.OrderedDict(), collections.OrderedDict()
        for i, r in enumerate(rows):
            key = f"{ed} {r['book']} {r['chapter']}:{r['verse']} {r['i']}.{r['part']}"
            s = c.slot[key] = len(c.slot) + 1
            nxt = rows[i + 1] if i + 1 < len(rows) else None
            same = nxt is not None and (nxt["book"], nxt["chapter"], nxt["verse"], nxt["i"]) == (r["book"], r["chapter"], r["verse"], r["i"])
            c.F["hkey"][s], c.F["text"][s], c.F["lang"][s], c.F["trailer"][s] = key, r["text"], "hbo", "" if same else " "
            for col, feat in (("lemma", "lemma"), ("strong", "strong"), ("class", "pos"), ("role", "role"), ("person", "person")):
                if r[col]:
                    c.F[feat][s] = r[col]
            for col in ("source", "lexeme", "form", "word", "token"):
                if r[col] and not (col == "word" and same and r["part"]):
                    c.F[f"hna_{col}"][s] = r[col]
            if r["p_split"] is not None:
                c.F["hna_p_split"][s] = value(r["p_split"])
            tokens.setdefault((r["book"], r["chapter"], r["verse"], r["i"]), []).append(s)
            segs.setdefault((r["book"], r["chapter"], r["verse"], r["seg"]), []).append(s)
            verses.setdefault((r["book"], r["chapter"], r["verse"]), []).append(s)
        for k in ("hkey", "hna_source", "hna_lexeme", "hna_form", "hna_word", "hna_token", "hna_p_split"):
            c.origin[k] = "hebrew-nt-analysis"
        for k, sl in tokens.items():
            c.node("token", sl)
        for r in pq.read_table(an / ed / "clauses.parquet").to_pylist():
            k = (r["book"], r["chapter"], r["verse"], r["seg"])
            h = c.node("clause", segs.get(k, []), (ed, *k))
            st["clauses"] += 1
            st["clauses placed"] += h is not None
            if h is not None:
                c.put(h, r, "hna_", "hebrew-nt-analysis", {"book", "chapter", "verse", "first_i", "last_i"})
        for (b, ch, v, sg), h in [(k[1:], h) for k, h in c.at["clause"].items() if isinstance(k, tuple) and k[0] == ed]:
            p = c.F["hna_parent"].get(h)
            if p in ("-1", "+1"):
                st["parent edges"] += c.edge("parent", h, c.at["clause"].get((ed, b, ch, v, sg + int(p))), None, "hebrew-nt-analysis")
        chapters, books = collections.OrderedDict(), collections.OrderedDict()
        for (b, ch, v), sl in verses.items():
            h = c.node("verse", sl, (name, b, ch, v))
            c.F["book"][h], c.F["chapter"][h], c.F["verse"][h] = b, ch, v
            chapters.setdefault((b, ch), []).extend(sl)
            st["parallel edges"] += c.edge("parallel", h, c.at["verse"].get(("greek_nt", b, ch, v)), None, "hebrew-nt-bridge")
            st["verses"] += 1
        for (b, ch), sl in chapters.items():
            h = c.node("chapter", sl, (name, b, ch))
            c.F["book"][h], c.F["chapter"][h] = b, ch
            books.setdefault(b, []).extend(sl)
        for b, sl in books.items():
            h = c.node("book", sl, (name, b))
            c.F["book"][h], c.F["sec"][h] = b, f"{tag}.{b}"
        c.F["name"][c.node("text", [s for sl in books.values() for s in sl], name)] = name
        st["words"] = len(rows)
        for r in pq.read_table(br / "links" / f"{ed}.parquet").to_pylist():
            a = c.slot.get(r["greek_id"][1:])
            t = c.slot.get(f"{ed} {r['book']} {r['chapter']}:{r['verse']} {r['i']}.{r['part']}")
            st["links"] += 1
            st["links placed"] += c.edge(ed, a, t, r["link"], "hebrew-nt-bridge")
        for line in (br / "quotes" / f"{ed}.tsv").read_text(encoding="utf-8").splitlines()[1:]:
            nt, tk, w, *_ = line.split("\t")
            (nb, ncv), (tb, tcv) = nt.split(), tk.split()
            a = c.at["verse"].get((name, nb, *map(int, ncv.split(":"))))
            t = c.at["verse"].get(("tanakh", tb, *map(int, tcv.split(":"))))
            st["quotes"] += 1
            st["quotes placed"] += c.edge("quotes", a, t, w, "hebrew-nt-bridge")
        c.report["layers"][f"hebrew NT {ed}"] = dict(st)


def save(c: Corpus, out: Path) -> dict:
    import cfabric
    p = pins()
    n = len(c.slot)
    nid, otype, oslots = {}, {}, {}
    for s in range(1, n + 1):
        otype[s] = "word"
    nxt = n + 1
    for t in TYPES:                                                     # numbered type by type: mixed numbering loads with wrong counts
        for i, sl in enumerate(c.nodes[t]):
            nid[(t, i)] = nxt
            otype[nxt], oslots[nxt] = t, sl
            nxt += 1
    num = lambda h: h if isinstance(h, int) else nid[h]
    source = {name: {"source": f"bcv-commons/{name}@{pin['tag']} ({pin['revision']})", "licence": pin["licence"],
                     "model_made": "yes" if pin.get("model_made") else "no"} for name, pin in p["layers"].items()}
    source["words"] = {"source": f"{p['words']['origin']}; {p['words']['source']} {p['words']['tag']}", "licence": p["words"]["licence"], "model_made": "no"}
    source["tier-macula"] = {"source": "bcv-query resources/lxx_bridge_tiers/macula.tsv (MACULA Hebrew's Septuagint numbers)", "licence": "cc-by-4.0", "model_made": "no"}
    source["tier-glaux"] = {"source": "bcv-query resources/lxx_bridge_tiers/glaux.tsv (verse co-occurrence with GLAUx's Septuagint)", "licence": "cc-by-sa-4.0", "model_made": "no"}
    for name, pin in p.get("stores", {}).items():
        source[name] = {"source": f"{pin['origin']}; {pin['source']} {pin['tag']}", "licence": pin["licence"], "model_made": "no"}
    source["layout"] = {"source": "the two clause layouts (see lay_ features)", "licence": "cc-by-sa-4.0", "model_made": "no"}
    meta = {"": {"name": "bridge corpus (working name)", "version": version(p), "licence": "cc-by-sa-4.0", "pins": "pins.json in this folder"},
            "otext": {"sectionTypes": "book,chapter,verse", "sectionFeatures": "sec,chapter,verse", "fmt:text-orig-full": "{text}{trailer}"},
            "otype": {"valueType": "str"}, "oslots": {"valueType": "str"}}
    nodef, edgef = {"otype": otype}, {"oslots": oslots}
    for name, vals in c.F.items():
        ints = all(isinstance(v, int) for v in vals.values())
        nodef[name] = {num(h): v if ints else str(v) for h, v in vals.items()}
        meta[name] = {"valueType": "int" if ints else "str", **source[c.origin[name]]}
    for name, vals in c.E.items():
        valued = any(v is not None for tos in vals.values() for v in tos.values())
        edgef[name] = {num(a): ({num(b): str(v) for b, v in tos.items()} if valued else {num(b) for b in tos}) for a, tos in vals.items()}
        meta[name] = {"valueType": "str", **({"edgeValues": True} if valued else {}), **source[c.origin[name]]}
    t = time.time()
    if not cfabric.Fabric(locations=str(out), silent="deep").save(nodeFeatures=nodef, edgeFeatures=edgef, metaData=meta, silent="deep"):
        raise SystemExit("Context Fabric did not save the dataset")
    (out / "pins.json").write_text(json.dumps(p, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    twice = {name: n - len(c.F[name]) for name, n in c.given.items() if n > len(c.F[name])}
    latin = {}                                                          # free text in Latin script would be English: codes have no spaces
    for name, vals in c.F.items():
        d = {v for v in vals.values() if isinstance(v, str)}
        spaced = sum(1 for v in d if " " in v and v.isascii() and any(ch.isalpha() for ch in v))
        if len(d) > 200 and spaced > len(d) / 2 and name not in REFERENCES:
            latin[name] = {"distinct values": len(d), "with spaces, in Latin script": spaced}
    c.report.update({"version": version(p), "features that lost a value (two rows on one unit)": twice, "features to read for free text": latin, "nodes": {"word": n, **{t: len(c.nodes[t]) for t in TYPES}}, "save seconds": round(time.time() - t, 1),
                     "features": {name: {"values": len(v), "origin": c.origin[name]} for name, v in sorted(c.F.items())},
                     "edges": {name: {"pairs": sum(len(t_) for t_ in v.values()), "origin": c.origin[name]} for name, v in sorted(c.E.items())}})
    return c.report


def build(out: Path, db: Path) -> dict:
    p = pins()
    if hashlib.sha256(db.read_bytes()).hexdigest() != p["words"]["sha256"]:
        raise SystemExit(f"{db} is not the pinned word store ({p['words']['tag']} of bcv-commons/spine-releases)")
    if out.exists():
        raise SystemExit(f"{out} exists; give a folder that does not exist yet")
    stores = {}
    for name, pin in p.get("stores", {}).items():
        f = HERE.parent / pin["path"]
        if hashlib.sha256(f.read_bytes()).hexdigest() != pin["sha256"]:
            raise SystemExit(f"{f} is not the pinned store {pin['tag']}")
        stores[name] = f
    c = Corpus()
    add_words(c, db)
    add_layout(c)
    add_clause_layers(c)
    add_phrases(c)
    add_word_layers(c)
    add_hebrew_nt(c)
    from macula import bridge_corpus_lxx
    bridge_corpus_lxx.add_septuagint(c, stores)
    from macula import bridge_corpus_more, bridge_corpus_trees, bridge_corpus_units
    bridge_corpus_trees.add_trees(c, stores["trees"])
    bridge_corpus_more.add_more(c)
    bridge_corpus_units.add_units(c)
    rep = save(c, out)
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return rep


def load(out: Path):
    """the dataset's API. Context Fabric 0.5.7 forgets which edges carry values when it loads from its own cache, and search then refuses
    `-edge=value>`; set here from the loaded edges"""
    import cfabric
    cf = cfabric.Fabric(locations=str(out), silent="deep")
    api = cf.loadAll(silent="deep")
    for name, feat in cf.features.items():
        if getattr(getattr(api.E, name, None), "doValues", False):
            feat.edgeValues = True
    return api


def check(out: Path) -> dict:
    """load the build and run the fixed queries; the first load builds Context Fabric's own index"""
    t = time.time()
    api = load(out)
    rep = {"load seconds": round(time.time() - t, 1), "nodes": {t_: len(list(api.F.otype.s(t_))) for t_ in api.F.otype.all}, "queries": []}
    for name, q, hits in QUERIES:
        t = time.time()
        n = len(list(api.S.search(q)))
        rep["queries"].append({"query": name, "hits": n, "expected": hits, "seconds": round(time.time() - t, 2)})
    rep["queries as expected"] = all(q["hits"] == q["expected"] for q in rep["queries"])
    return rep


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--check", nargs="?", const="", metavar="DIR")
    ap.add_argument("--out", type=Path, help="the build's folder (default: data/bridge-corpus/build-<pins>)")
    ap.add_argument("--words", type=Path, default=HERE / "macula-spine.db")
    a = ap.parse_args()
    out = a.out or DATA / f"build-{version().split('+')[1]}"
    if a.fetch:
        fetch()
    if a.build:
        rep = build(out, a.words)
        print(json.dumps({k: rep[k] for k in ("version", "nodes", "save seconds", "features that lost a value (two rows on one unit)",
                                              "features to read for free text", "layers")}, ensure_ascii=False, indent=1))
    if a.check is not None:
        print(json.dumps(check(Path(a.check) if a.check else out), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
