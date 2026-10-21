"""Build the Hebrew clause layout (proposed dataset bcv-commons/hebrew-clause-layout, phase 1): the Hebrew Bible one clause segment per
line, chapter by chapter, from MACULA Hebrew (CC BY 4.0) in trees-macula.db. No BHSA input.

A clause segment is a maximal run of whole words, inside one verse, that belongs to one MACULA clause:
- a word goes as a whole (prefixes included) to the clause of its last token, because MACULA sometimes puts a prefix (the ל of an
  infinitive) in the higher clause;
- a clause interrupted by an embedded clause gives two segments; a clause that crosses a verse boundary gives one per verse.
`depth` is the number of clause ancestors in the MACULA tree. It only reaches up to the verse (a MACULA sentence is one verse); the
text-level hierarchy (`discourse_parent`, `text_depth`) is phase 2 and is written as null here.

Text: MACULA's WLC surface forms and trailers. A word-final token with an empty trailer gets a space (MACULA leaves it empty at some
ketiv/qere words, which glues two words together); paseq is written ` ׀ `; the setuma/petucha marks after sof pasuq are dropped.
`verse_ref_en` comes from the bibles verse map org-to-eng (TVTMS, CC BY 4.0) through vrsmap; a Psalm title is `PSA 3:title`.
`ketiv_qere` lists the ketiv (from UHB, unpointed) and qere of the segment's words; the text shows the qere, as MACULA does.

  python -m macula.build_clause_layout [--books RUT,DAN] [--out macula/data/clause-layout]
  python -m macula.build_clause_layout --profile reader     # a profile (macula/profiles/reader.toml), into its own folder
  python -m macula.build_clause_layout --config my.toml     # any settings file, a full one or a profile

Writes clauses/<BOOK>/<BOOK>_<CCC>.jsonl, layout/<BOOK>/<BOOK>_<CCC>.txt and build.json.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import difflib
import hashlib
import io
import json
import re
import sqlite3
import sys
from pathlib import Path

SHORESH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHORESH))

import trees_macula  # noqa: E402
from macula import discourse_rules  # noqa: E402
import vrsmap  # noqa: E402
from spine.common import FILENUM  # noqa: E402

# The external sources (MACULA Hebrew, the lexeme spine, UHB for ketiv/qere, the versification map) are pinned in
# macula/clause_layout.toml [sources.*] and checked by macula.sources before anything is written.
_uhb_read: set[str] = set()                # UHB files this build read (checked against their pins)


def uhb_source() -> dict:
    return discourse_rules.CFG["sources"]["uhb"]

FORMAT_VERSION = 1
LANG = {"H": "hbo", "A": "arc"}
# Book groups, the rules, their scopes, the paragraph marks and the split verses are in macula/clause_layout.toml (discourse_rules).


# ---------------------------------------------------------------- ketiv/qere from UHB (CC BY-SA 4.0)
# UHB writes the ketiv unpointed in the text and the qere as a footnote `\f + \ft Q \+w ...\f*` (Daniel has no footnotes). MACULA gives
# the pointed qere and skips the ketiv's word number. The two word streams of a book are aligned by consonants: a ketiv is a mismatch
# opposite MACULA's qere word(s). Verse numbers are not used (UHB numbers 1,977 verses differently, most of them Psalm titles).
_KQ_FOOT = re.compile(r"\\f \+ \\ft Q (.*?)\\f\*|\\w ([^|]*)\|")
_VOWELS = re.compile(r"[\u05B0-\u05BC\u05C1\u05C2\u05C7]")


def _cons(s: str) -> str:
    return re.sub(r"[^\u05D0-\u05EA]", "", s)


def _uhb_words(text: str) -> list[dict]:
    words: list[dict] = []
    for m in _KQ_FOOT.finditer(text):
        if m.group(1) is not None:
            if words:
                words[-1]["qere"] = " ".join(x.replace("\u2060", "") for x in re.findall(r"\\\+w ([^|]*)\|", m.group(1)))
        else:
            f = m.group(2).replace("\u2060", "")
            words.append({"form": f, "qere": None, "ketiv": bool(re.search("[\u05D0-\u05EA]", f)) and not _VOWELS.search(f)})
    return words


def _uhb_book(code: str, cache: Path) -> str:
    u = uhb_source()
    f = cache / u["tag"] / f"{FILENUM[code]:02d}-{code}.usfm"
    _uhb_read.add(f.name)
    if not f.exists():
        import httpx
        r = httpx.get(u["url"].format(tag=u["tag"], nn=FILENUM[code], code=code), timeout=120, follow_redirects=True)
        r.raise_for_status()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(r.text, encoding="utf-8")
    return f.read_text(encoding="utf-8")


def ketiv_qere(con: sqlite3.Connection, book: str, cache: Path, stats: collections.Counter) -> dict[str, dict]:
    """MACULA word key (its first token) -> {key, ketiv, qere}. A ketiv over several qere words gives one entry per qere word, each with
    the whole ketiv (several ketiv words over one qere word: one entry); ketiv without qere has qere null and sits on the next word;
    qere without ketiv has ketiv null."""
    u = _uhb_words(_uhb_book(book, cache))
    m = con.execute("SELECT MIN(key), GROUP_CONCAT(surface, '') FROM (SELECT * FROM words WHERE corpus='hbo' AND book=? AND inserted=0 "
                    "ORDER BY chapter, verse, word, part) GROUP BY chapter, verse, word ORDER BY chapter, verse, word", (book,)).fetchall()
    out: dict[str, dict] = {}

    def put(key, ketiv, qere, kind):
        out[key] = {"key": key, "ketiv": ketiv, "qere": qere}
        stats[kind] += 1

    sm = difflib.SequenceMatcher(None, [_cons(x["form"]) for x in u], [_cons(s) for _, s in m], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        kt = [i for i in range(i1, i2) if u[i]["ketiv"]]
        if op == "equal":
            for i in kt:                                    # same consonants, the qere is in the vowels only
                put(m[j1 + i - i1][0], u[i]["form"], u[i]["qere"] or m[j1 + i - i1][1], "vowels_only")
        elif op == "replace" and kt:
            if i2 - i1 == j2 - j1:
                for i in kt:
                    put(m[j1 + i - i1][0], u[i]["form"], u[i]["qere"] or m[j1 + i - i1][1], "paired")
            else:                                           # one entry per MACULA word, each with the whole ketiv
                for j in range(j1, j2):
                    put(m[j][0], " ".join(u[i]["form"] for i in range(i1, i2)), m[j][1], "split_or_joined")
        elif op == "delete" and kt and j1 < len(m):
            put(m[j1][0], " ".join(u[i]["form"] for i in kt), None, "ketiv_only")
        elif op == "insert" and j2 - j1 <= 2:
            for j in range(j1, j2):
                put(m[j][0], None, m[j][1], "qere_only")
        elif kt:
            stats["unresolved"] += len(kt)
    return out


def _clause_parents(con: sqlite3.Connection) -> dict[int, int | None]:
    """Clause id -> nearest clause ancestor that has words of its own (None at the top of the verse). Clauses without words of their own
    are MACULA's coordination groups (rule ClCl, ClCl2, ...): their members are siblings, so they add no level (as in the /scaffold API)."""
    nodes = {r[0]: (r[1], r[2]) for r in con.execute("SELECT id, parent, cls FROM nodes WHERE corpus='hbo'")}
    worded = {r[0] for r in con.execute("SELECT DISTINCT cl FROM words WHERE corpus='hbo' AND inserted=0 AND cl IS NOT NULL")}
    out = {}
    for nid, (_, cls) in nodes.items():
        if cls != "cl":
            continue
        p = nodes[nid][0]
        while p is not None and not (nodes.get(p, (None, None))[1] == "cl" and p in worded):
            p = nodes.get(p, (None, None))[0]
        out[nid] = p
    return out


def _speaker_spans() -> dict[str, int]:
    """Hebrew word key -> the number of the speaker span it stands in (resources/speaker_quotations: Clear's quotations projected onto
    MACULA words, CC BY 4.0), for rules span_keeps_speech and span_end_resumes. Spans are flat (never nested)."""
    path = SHORESH.parent / "resources" / "speaker_quotations" / "speaker_quotations.tsv"
    if not path.exists():
        return {}
    spans = []
    with open(path, encoding="utf-8") as fh:
        rows = csv.DictReader((line for line in fh if not line.startswith("#")), delimiter="\t")
        for r in rows:
            if r["word_start"].startswith("o") and r["word_end"].startswith("o"):
                spans.append((r["word_start"][1:], r["word_end"][1:]))
    spans.sort()
    return {"_spans": spans}


def _speaker_layer(cache: Path) -> tuple[Path | None, dict, dict, dict]:
    """The pinned speaker-layer release ([sources.speaker_layer]), for rule speech_levels: (the archive, (book, chapter, verse, seg) ->
    (clause key, quotation id or None), quotation id -> the quotation it stands inside or None, quotation id -> speaker). Downloaded
    once into the cache."""
    import tarfile
    s = discourse_rules.CFG["sources"].get("speaker_layer")
    if not s:
        return None, {}, {}, {}
    f = cache / s["tag"] / f"hebrew-speaker-layer-{s['tag']}.tar.gz"
    if not f.exists():
        import httpx
        r = httpx.get(s["url"].format(tag=s["tag"]), timeout=300, follow_redirects=True)
        r.raise_for_status()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(r.content)
    seg_q: dict = {}
    parent: dict = {}
    speaker: dict = {}

    def rows(fh):
        return csv.DictReader((line for line in io.TextIOWrapper(fh, encoding="utf-8") if not line.startswith("#")), delimiter="\t")
    with tarfile.open(f) as tar:
        for m in tar.getmembers():
            name = m.name.split("/")[-1]
            if m.name.endswith("quotations.tsv"):
                for r in rows(tar.extractfile(m)):
                    parent[r["id"]], speaker[r["id"]] = r["parent"] or None, r["speaker"]
            elif "/segments/" in "/" + m.name and name.endswith(".tsv"):
                book = name[:-4]
                for r in rows(tar.extractfile(m)):
                    seg_q[(book, int(r["chapter"]), int(r["verse"]), int(r["seg"]))] = (r["clause_key"], r["quotation"] or None)
    return f, seg_q, parent, speaker


class _Tree:
    """MACULA's syntax tree of a verse, for rule tree_level_inside_verse: a segment's path from the lowest node holding its words up
    to the verse's word group, each node with its attachment kind "parent rule | child index (2 = third or later) | class | role |
    opening word of a clause". The verse's word group has no parent (the sentence node above it is left out) and is "ROOT" as a
    parent; a node without a class is "wg"."""
    OPENERS = ("cj", "ptcl", "rel", "prep", "ij", "intj", "adv")

    def __init__(self, con: sqlite3.Connection):
        rows = con.execute("SELECT id, parent, kind, cls, rule, role, lo FROM nodes WHERE corpus='hbo'").fetchall()
        sentence = {r[0] for r in rows if r[2] == "sentence"}
        self.node = {r[0]: (None if r[1] in sentence else r[1], r[3], r[4], r[5]) for r in rows if r[0] not in sentence}
        kids = collections.defaultdict(list)
        for r in sorted(rows, key=lambda r: (r[6] if r[6] is not None else -1, r[0])):
            if r[0] in self.node and self.node[r[0]][0] is not None:
                kids[self.node[r[0]][0]].append(r[0])
        self.index = {n: i for ks in kids.values() for i, n in enumerate(ks)}
        lo_of = {r[0]: r[6] for r in rows if r[3] == "cl" and r[0] in self.node}
        word = {r[0]: (r[1], r[2]) for r in con.execute("SELECT seq, lemma, class FROM words WHERE corpus='hbo' AND seq IN (SELECT lo FROM nodes "
                                                         "WHERE corpus='hbo' AND cls='cl')")}
        self.first_word = {n: word[lo][0] for n, lo in lo_of.items() if lo in word and word[lo][1] in self.OPENERS
                           and discourse_rules._n(word[lo][0]) != discourse_rules.WAW}

    def chain(self, n):
        out = []
        while n is not None and n in self.node:
            out.append(n)
            n = self.node[n][0]
        return out

    def att(self, n) -> str:
        par = self.node[n][0]
        prule = (self.node[par][2] or ("ROOT" if self.node[par][0] is None else "-")) if par is not None else "-"
        key = f"{prule}|{min(self.index.get(n, 0), 2)}|{self.node[n][1] or 'wg'}|{self.node[n][3] or '-'}"
        return key + (f"|{self.first_word[n]}" if n in self.first_word else "")

    def path(self, toks: list) -> list[list]:
        ns = [t["parent"] for t in toks if t["parent"] in self.node]
        inner = [n for n in ns if self.node[n][0] is not None]
        ns = inner or ns
        common = None
        for n in ns:
            c = self.chain(n)
            common = c if common is None else [x for x in common if x in set(c)]
        return [[x, self.att(x)] for x in self.chain(common[0])] if common else []


def _verb_person(con: sqlite3.Connection, keys: set[str]) -> tuple[dict[str, str], dict[str, str]]:
    """(person, number) of verbs and pronouns, from the lexeme spine."""
    import lexeme_macula
    sp = sqlite3.connect(f"file:{lexeme_macula.spine_path()}?mode=ro", uri=True)
    person, number = {}, {}
    for k, p, n in sp.execute("SELECT key, person, number FROM spine_words WHERE person IN ('first', 'second', 'third')"):
        if k in keys:
            person[k] = p
            if n:
                number[k] = n
    return person, number


def _attachments(con: sqlite3.Connection, parents: dict[int, int | None], clause_key: dict[int, str]) -> dict[int, str]:
    """Clause id -> first word key of the head it hangs on, when the MACULA tree nests it inside a phrase of its parent clause (a relative
    clause in a noun phrase: the antecedent). None when it hangs on the parent clause directly."""
    nodes = {r[0]: r for r in con.execute("SELECT id, parent, cls, head, lo, hi FROM nodes WHERE corpus='hbo'")}
    kids: dict[int, list[int]] = collections.defaultdict(list)
    for nid, r in nodes.items():
        if r[1] is not None:
            kids[r[1]].append(nid)
    seq_key = dict(con.execute("SELECT seq, key FROM words WHERE corpus='hbo' AND inserted=0"))
    out = {}
    for cid, p in parents.items():
        if p is None or cid not in clause_key:
            continue
        prev, a = cid, nodes[cid][1]
        while a is not None and a != p:
            heads = [k for k in kids[a] if k != prev and nodes[k][3] == "true" and nodes[k][4] is not None]
            if heads:
                h = nodes[heads[0]]
                ks = [seq_key[q] for q in range(h[4], h[5] + 1) if q in seq_key]
                if ks:
                    out[cid] = min(ks)
                break
            prev, a = a, nodes[a][1]
    return out


def _depth(cid: int, parents: dict[int, int | None]) -> int:
    n = 0
    while parents.get(cid) is not None:
        cid = parents[cid]
        n += 1
    return n


def _trailer(after: str, word_final: bool) -> str:
    if after == "׀":
        return " ׀ "
    if after.startswith("׃"):
        return "׃"
    if after in ("ס", "פ"):                 # parashah mark inside a verse
        return " "
    if after == "" and word_final:
        return " "
    return after


def _eng(book: str, ch: int, v: int) -> str:
    refs = vrsmap.to_eng((book, ch, v), "org")
    return vrsmap.fmt(refs[0]) if refs else None


def chapter_segments(rows: list[sqlite3.Row], nodes: dict[int, sqlite3.Row], parents: dict[int, int | None]) -> list[dict]:
    words: list[list[sqlite3.Row]] = []
    for r in rows:
        if words and (words[-1][-1]["verse"], words[-1][-1]["word"]) == (r["verse"], r["word"]):
            words[-1].append(r)
        else:
            words.append([r])
    cids = [next((t["cl"] for t in reversed(w) if t["cl"] is not None), None) for w in words]
    # MACULA puts a clause-opening subordinator or relative (אִם, כִּי, אֲשֶׁר, עַד, דִּי ...) in the parent clause; it goes with the clause
    # it opens, as a prefix goes with its word (backwards, so that עַד אֲשֶׁר moves as a pair)
    for i in range(len(words) - 2, -1, -1):
        w, nxt = words[i], words[i + 1]
        if (w[-1]["verse"] == nxt[0]["verse"] and cids[i + 1] is not None and cids[i] != cids[i + 1]
                and discourse_rules.is_subordinator(w[-1]) and all(t["class"] in ("cj", "prep") or t is w[-1] for t in w)):
            cids[i] = cids[i + 1]
        elif (i + 2 < len(words) and w[-1]["verse"] == nxt[0]["verse"] and cids[i] != cids[i + 1] and cids[i + 1] is not None
              and discourse_rules._n(w[-1]["lemma"]) == discourse_rules.QABEL and discourse_rules._n(nxt[-1]["lemma"]) == discourse_rules.DI):
            cids[i] = cids[i + 1]                  # Aramaic כָּל־קֳבֵל דִּי "because" goes with its clause as a whole
        elif (w[-1]["verse"] == nxt[0]["verse"] and cids[i] != cids[i + 1] and cids[i + 1] is not None and all(t["class"] == "prep" for t in w)
              and discourse_rules._n(nxt[0]["lemma"]) == discourse_rules.QABEL and i + 2 < len(words)
              and discourse_rules._n(words[i + 2][-1]["lemma"]) == discourse_rules.DI):
            cids[i] = cids[i + 1]                  # its כָּל־ (MACULA: כְּ + לְ) too
    segs: list[dict] = []
    for i, w in enumerate(words):
        last = w[-1]
        cid = cids[i]
        text = "".join(t["surface"] + (t["after"] or "") for t in w[:-1]) + last["surface"] + _trailer(last["after"] or "", True)
        keys = [t["key"] for t in w]
        if segs and segs[-1]["verse"] == last["verse"] and segs[-1]["clause"] == cid:
            s = segs[-1]
            s["words"] += [k for k in keys if k != s["words"][-1]]
            s["text"] += text
            s["_lang"].update(t["wlang"] for t in w)
            s["_toks"] += w
        else:
            segs.append({"verse": last["verse"], "clause": cid, "words": list(dict.fromkeys(keys)), "text": text,
                         "_lang": collections.Counter(t["wlang"] for t in w), "_toks": list(w)})
    out = []
    for n, s in enumerate(segs, 1):
        cid, node = s["clause"], nodes.get(s["clause"])
        lang = s.pop("_lang").most_common(1)[0][0]
        own = [r for r in rows if r["cl"] == cid]
        out.append({"verse": s["verse"], "seg": n, "clause": cid, "parent": parents.get(cid), "sentence": own[0]["sent"] if own else None,
                    "depth": _depth(cid, parents) if cid is not None else 0, "discourse_parent": None, "text_depth": None,
                    "kind": trees_macula._clause_kind(own) if own else None, "rule": (node["rule"] if node else None) or None,
                    "language": LANG.get(lang, "hbo"), "first": s["words"][0], "last": s["words"][-1], "words": s["words"],
                    "text": " ".join(s["text"].split()).replace(" ׀ ", " ׀ "), "ketiv_qere": [], "_toks": s["_toks"]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--books", help="comma-separated USFM codes (default: all Hebrew books)")
    ap.add_argument("--out", help="output folder (default macula/data/clause-layout, or clause-layout-profiles/<profile> for a profile)")
    ap.add_argument("--uhb-cache", default=str(SHORESH / "macula" / "data" / "uhb"), help="downloaded UHB USFM (cached per tag)")
    ap.add_argument("--config", help="rules and settings file (default macula/clause_layout.toml)")
    ap.add_argument("--profile", help="a profile in macula/profiles/<name>.toml, merged over what it extends")
    a = ap.parse_args()
    if a.config and a.profile:
        ap.error("give --config or --profile, not both")
    if a.config or a.profile:
        discourse_rules.configure(a.config, a.profile)
    profile = discourse_rules.PROFILE
    data = SHORESH / "macula" / "data"
    out = Path(a.out) if a.out else data / "clause-layout" if profile == discourse_rules.BASE_PROFILE else data / "clause-layout-profiles" / profile
    print(f"profile {profile} -> {out}")
    tp = trees_macula.trees_path()
    con = sqlite3.connect(f"file:{tp}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    nodes = {r["id"]: r for r in con.execute("SELECT id, rule, role FROM nodes WHERE corpus='hbo' AND cls='cl'")}
    parents = _clause_parents(con)
    subj_ranges: dict[int, list] = collections.defaultdict(list)     # clause id -> word seq ranges of its subject phrases (role s)
    for r in con.execute("SELECT parent, lo, hi FROM nodes WHERE corpus='hbo' AND role='s'"):
        subj_ranges[r["parent"]].append((r["lo"], r["hi"]))
    books = a.books.upper().split(",") if a.books else [r[0] for r in con.execute("SELECT book FROM words WHERE corpus='hbo' GROUP BY book ORDER BY MIN(seq)")]
    chapters_out: list[tuple[str, int, list[dict]]] = []
    resets: set[str] = set()               # first word key after which a speech cannot continue
    paras: set[str] = set()                # first word key after a paragraph mark, any book
    kq_stats: collections.Counter = collections.Counter()
    for book in books:
        kq = ketiv_qere(con, book, Path(a.uhb_cache), kq_stats)
        chapters = [r[0] for r in con.execute("SELECT DISTINCT chapter FROM words WHERE corpus='hbo' AND book=? ORDER BY chapter", (book,))]
        mark_pending = False
        for ch in chapters:
            rows = con.execute("SELECT * FROM words w WHERE corpus='hbo' AND book=? AND chapter=? AND inserted=0 ORDER BY " + trees_macula.TEXT_ORDER,
                               (book, ch)).fetchall()
            segs = chapter_segments(rows, nodes, parents)
            pm = discourse_rules.PARAGRAPH_MARKS
            if rows and discourse_rules.active("each_psalm_starts_afresh", book):
                resets.add(rows[0]["key"])
            if rows:
                marks = {rows[i + 1]["key"] for i in range(len(rows) - 1) if any(m in (rows[i]["after"] or "") for m in pm)}
                if mark_pending:                   # the previous chapter ended with a paragraph mark
                    marks.add(rows[0]["key"])
                paras.update(marks)
                if discourse_rules.active("chapter_after_mark_starts_afresh", book) and mark_pending:
                    resets.add(rows[0]["key"])
                mark_pending = any(m in (rows[-1]["after"] or "") for m in pm)
            for sg in segs:
                sg["ketiv_qere"] = [kq[k] for k in sg["words"] if k in kq]
            eng: dict[int, str] = {}
            split_at = None
            for s in segs:
                v = s["verse"]
                if v not in eng:
                    eng[v] = _eng(book, ch, v)
                sp = discourse_rules.SPLIT_VERSES.get((book, ch, v))
                if sp and s["first"] == sp[0]:
                    split_at = sp[1]
                ref = split_at if (sp and split_at) else eng[v]
                if not sp:
                    split_at = None
                s["_eng"] = ref
            chapters_out.append((book, ch, segs))
        print(f"{book}: {len(chapters)} chapters")
    # stable ids: a clause is named by the first word key of its first segment (row ids of the tree build change on every rebuild)
    clause_key: dict[int, str] = {}
    for _, _, segs in chapters_out:
        for s in segs:
            if s["clause"] is not None:
                clause_key.setdefault(s["clause"], s["first"])
    # text-level hierarchy (phase 2): one record per clause, in order of first appearance
    toks_of: dict[int, list] = collections.defaultdict(list)
    first_seen: dict[int, tuple] = {}
    tree = _Tree(con)
    span_list = _speaker_spans().get("_spans", [])
    span_starts = [a for a, _ in span_list]

    def span_of(key: str) -> int | None:                   # the speaker span a word key stands in
        import bisect
        i = bisect.bisect_right(span_starts, key) - 1
        return i if i >= 0 and span_list[i][0] <= key <= span_list[i][1] else None
    tree_of: dict[int, list] = {}                 # clause id -> the tree path of its first segment (rule tree_level_inside_verse)
    chapter_first: set[int] = set()
    speaker_archive, seg_quote, quote_parent, quote_speaker = _speaker_layer(data / "speaker-layer-release")
    frames = {(fr["book"], fr["speaker"]) for fr in discourse_rules.CFG["speech"]["frames"]}
    speech_of: dict[int, tuple] = {}              # clause id -> the quotations its first segment stands in, outermost first (rule speech_levels)
    mismatched = 0
    for book, ch, segs in chapters_out:
        for s in segs:
            if s["clause"] is not None:
                toks_of[s["clause"]] += s["_toks"]
                first_seen.setdefault(s["clause"], (book, ch, s["verse"]))
                if s["clause"] not in tree_of:
                    tree_of[s["clause"]] = tree.path(s["_toks"])
                if seg_quote and s["clause"] not in speech_of:
                    key, q = seg_quote.get((book, ch, s["verse"], s["seg"]), (None, None))
                    mismatched += key != clause_key.get(s["clause"])
                    chain = []
                    while q:
                        chain.append(q)
                        q = quote_parent.get(q)
                    chain.reverse()
                    if chain and (book, quote_speaker.get(chain[0])) in frames:
                        chain = chain[1:]                  # [speech] frames: a book-long speaker's speech is the frame, not a level
                    speech_of[s["clause"]] = tuple(chain)
        if segs and segs[0]["clause"] is not None:
            chapter_first.add(segs[0]["clause"])
    if mismatched:
        raise SystemExit(f"the speaker layer's segments differ from this build's in {mismatched} clauses: it was built on another "
                         "segmentation; pin a speaker-layer release built on this one ([sources.speaker_layer])")
    person, number = _verb_person(con, set(t["key"] for ts in toks_of.values() for t in ts if t["class"] in ("verb", "pron")))
    attach_of = _attachments(con, parents, clause_key)
    strong_of_key = {t["key"]: discourse_rules._strong(t) for ts in toks_of.values() for t in ts}
    disc: dict[str, dict] = {}
    by_book: dict[str, list] = collections.defaultdict(list)
    for cid, (book, ch, v) in first_seen.items():
        by_book[book].append({"key": clause_key[cid], "verse": (book, ch, v), "parent_key": clause_key.get(parents.get(cid)) if parents.get(cid) else None,
                              "attach": attach_of.get(cid), "attach_strong": strong_of_key.get(attach_of.get(cid)),
                              "f": discourse_rules.features(toks_of[cid], person, nodes[cid]["rule"] if cid in nodes else None,
                                                             nodes[cid]["role"] if cid in nodes else None, subj_ranges.get(cid), number),
                              "reset": clause_key[cid] in resets, "chapter_start": cid in chapter_first, "para": clause_key[cid] in paras,
                              "tree": tree_of.get(cid, []), "span": span_of(clause_key[cid]),
                              "speech": speech_of.get(cid, ())})
    for book, cl in by_book.items():
        disc.update(discourse_rules.derive(cl))
    # every external input this build used, against its pin in clause_layout.toml; nothing is written when one differs
    import lexeme_macula
    from macula import sources
    src_record, problems = sources.check(
        discourse_rules.CFG["sources"], trees_db=Path(tp), spine_db=Path(lexeme_macula.spine_path()), uhb_dir=Path(a.uhb_cache),
        uhb_files=sorted(_uhb_read), vrs_files={name: vrsmap._path(name) for name in discourse_rules.CFG["sources"]["versification"]["sha256"]},
        tvtms_rev=vrsmap.revision("org"), speaker_archive=speaker_archive)
    if problems:
        raise SystemExit("A source differs from its pin in " + discourse_rules.CONFIG_FILE + "; nothing written.\n- " + "\n- ".join(problems))
    seg_hash = hashlib.sha256()
    book_hash: dict[str, "hashlib._Hash"] = {}
    n_seg = 0
    for book, ch, segs in chapters_out:
        full = []
        for s in segs:
            r = {"book": book, "chapter": ch, "verse": s["verse"], "seg": s["seg"], "verse_ref_en": s.pop("_eng"),
                 "clause_key": clause_key.get(s["clause"]), "parent_key": clause_key.get(s["parent"]) if s["parent"] is not None else None,
                 **{k: v for k, v in s.items() if k not in ("verse", "seg", "_toks")}}
            d = disc.get(r["clause_key"])
            if d:
                r.update({"discourse_parent": d["parent"], "relation": d["relation"], "discourse_attach": d["attach"],
                          "tree_depth": d["tree_depth"], "text_depth": d["depth"], "text_depth_law": d["depth_law"],
                          "discourse_rule": d["rule"]})
            else:
                r.update({"relation": None, "discourse_attach": None, "tree_depth": None, "discourse_rule": None})
            full.append(r)
            line = f"{book} {ch}:{r['verse']} {r['first']} {r['last']}\n".encode()
            seg_hash.update(line)
            book_hash.setdefault(book, hashlib.sha256()).update(line)
        for d in ("clauses", "layout"):
            (out / d / book).mkdir(parents=True, exist_ok=True)
        with open(out / "clauses" / book / f"{book}_{ch:03d}.jsonl", "w", encoding="utf-8") as f:
            for r in full:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        lines = [f"{book} {ch}"] + [f"{r['verse']}:{r['text_depth'] if r['text_depth'] is not None else r['depth']} {r['text']}" for r in full]
        (out / "layout" / book / f"{book}_{ch:03d}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        n_seg += len(full)
    n_ch = len(chapters_out)
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    build = {"format_version": FORMAT_VERSION, "built": datetime.date.today().isoformat(), "books": len(books), "chapters": n_ch, "segments": n_seg,
             "trees_macula": {"built": meta.get("built"), "source": meta.get("source_hbo"), "sha256": src_record["macula_hebrew"]["trees_db_sha256"]},
             "versification": {"map": "org-to-eng (bcv-commons/bibles, from STEPBible TVTMS, CC BY 4.0)", "tvtms_rev": vrsmap.revision("org")},
             "segmentation": {"version": seg_hash.hexdigest()[:16], "note": "sha256 over every segment's book, chapter, verse, first and last word key; "
                              "changes only when segment boundaries change (levels, text and ketiv/qere do not affect it)"},
             "uhb": {"tag": uhb_source()["tag"], "licence": uhb_source()["licence"], "ketiv_qere": dict(kq_stats)},
             "sources": src_record,
             "books": {b: {"segments_sha256": h.hexdigest()} for b, h in book_hash.items()},
             "depth": "clause ancestors in the MACULA tree, within the verse", "discourse_rules": discourse_rules.RULES_VERSION,
             "relations": {"all": discourse_rules.RELATIONS, "flat": sorted(discourse_rules.FLAT), "flat_rules": sorted(discourse_rules.FLAT_RULES),
                           "tree_flat": sorted(discourse_rules.TREE_FLAT),
                           "chain_forms": sorted(discourse_rules.CHAIN_FORMS), "chain_forms_in_speech_with_waw": sorted(discourse_rules.CHAIN_FORMS_SPEECH),
                           "text_depth": "number of links up the discourse_parent chain whose relation is not in flat and whose discourse_rule is not in flat_rules; "
                                         "then rule speech_levels: every quotation of the speaker layer is a level, and no line of a speech stands further out than it",
                           "tree_depth": "number of links up the discourse_parent chain whose relation is not in tree_flat",
                           "text_depth_law": " ".join(discourse_rules.CFG["depth"]["law"]["doc"].split()),
                           "conditional_inversion": " ".join(discourse_rules.CFG["conventions"]["conditional_inversion"]["doc"].split())},
             "rules_config": {"profile": profile, "profile_doc": " ".join(discourse_rules.CFG["profile"]["doc"].split()),
                              "files": [{"file": f, "sha256": h} for f, h in discourse_rules.CONFIG_FILES],
                              "sha256": discourse_rules.CONFIG_SHA256, "changed_by_profile": discourse_rules.PROFILE_CHANGED,
                              "limited_rules": {r: sc for r, sc in discourse_rules.SCOPE.items() if sc != "all"}},
             "licence": "CC BY-SA 4.0; MACULA Hebrew (CC BY 4.0), UHB ketiv (CC BY-SA 4.0), versification TVTMS (CC BY 4.0), "
                        "speaker layer (bcv-commons, CC BY 4.0)"}
    (out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{n_ch} chapters, {n_seg} segments -> {out}")


if __name__ == "__main__":
    main()
