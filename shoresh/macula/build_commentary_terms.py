"""hebrew-commentary-terms: what the rabbinic commentators say about words and passages of the Tanakh, in their own Hebrew
terms, as statements on MACULA word keys (plan: internal-docs/rabbinic-layer-plan-2026-11-18.md).

    cd shoresh && .venv/bin/python -m macula.build_commentary_terms --out DIR

Tables (DIR/statements.jsonl, terms.tsv, witnesses.tsv, lists.tsv; DIR/model/statements.jsonl for model-anchored rows):

statements: one row = one witness saying one thing about one stretch of the text.
  subject_first, subject_last   MACULA word keys of the word or passage spoken about
  says                          closed list (SAYS below)
  term                          the witness's own Hebrew term (consonants, as written, prefix ו dropped), or null
  object_first, object_last     another passage (occasion statements), or null
  witness, locus                the work (witnesses.tsv) and the Sefaria reference of the comment
  formula                       the Hebrew formula matched (ענין, לשון, …)
  register                      peshat or derash
  anchor                        how the subject was found: rule (consonants, prefixes, lemma, full spelling) or model
terms: every term with its count, the biblical lemma it spells where that is unambiguous (Strong's), and the lists it is on.
lists: the sages' own lists of terms (resources/commentary_terms/lists.tsv, keyed by hand with locus).

P1 (this file): Metzudat Zion's word explanations (Public Domain, Sefaria "On Your Way"). The commentary's head word is
anchored in its verse by build_metzudat_zion._anchor (rules); where only the cached model fallback (anchor_llm) finds it,
the row goes to the model table. Formulas:
  ענין X [וY]      says sense      (the matter the word belongs to)
  לשון X           says expression (the word is an expression of X); מלשון X is etymology and gives says from_word
  a first word     says gloss      (the comment opens with one Hebrew word that explains the head word, as build_metzudat_zion
                                    reads it; openers that cite or explain at length are skipped)
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine.common import to_modern_form  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RES = ROOT / "resources" / "commentary_terms"
COLUMNS = ("subject_first", "subject_last", "says", "term", "object_first", "object_last", "witness", "locus", "formula",
           "register", "anchor", "citation", "quote", "licence")
SAYS = ("sense", "expression", "from_word", "gloss", "occasion", "voice", "kind", "member_of")
STOP = {"של", "את", "על", "אל", "מן", "עם", "כי", "אשר", "הוא", "היא", "זה", "זו", "כן", "גם", "או", "דבר", "וכן", "כמו", "ר״ל"}
MACULA = HERE / "macula-spine.db"
# first words that open a description, not a gloss: "שם מקום" (the name of a place), "מין" (a kind of), "נקרא" (is called)
GLOSS_OPENERS = {"שם", "מין", "נקרא", "יקרא", "נקראו", "הנה", "אין", "לא", "אמר", "כאשר", "כלומר", "ענינו", "שמו", "פי׳", "פירוש"}


def clean(w: str) -> str:
    """A term as written: consonants only (to_modern_form), no geresh/gershayim, a leading ו dropped when 4+ letters remain."""
    w = re.sub(r"[׳״'\".,:;()\[\]]", "", to_modern_form(w, "hbo"))
    return w[1:] if w.startswith("ו") and len(w) >= 4 else w


def word_span() -> dict[str, tuple[str, str]]:
    """MACULA word (key without its part digit) -> first and last part key."""
    sp = sqlite3.connect(f"file:{MACULA}?mode=ro", uri=True)
    out: dict[str, list[str]] = {}
    for (k,) in sp.execute("SELECT key FROM macula_words WHERE lang='hbo' OR lang IS NULL"):
        out.setdefault(k[:-1], []).append(k)
    return {w: (min(ks), max(ks)) for w, ks in out.items()}


def terms_after(text: str, formula: str) -> list[str]:
    """The term(s) after a formula: up to three words joined by ו ("ענין חלוקה והפרדה" -> חלוקה, הפרדה), stopping at a
    citation or punctuation."""
    m = re.search(rf"(?:^|\s){formula}\s+([^.:;,(]+)", text)
    if not m:
        return []
    words = m.group(1).split()[:3]
    out = []
    for i, w in enumerate(words):
        if i and not w.startswith("ו"):
            break
        c = clean(w)
        if len(c) >= 2 and c not in STOP:
            out.append(c)
    return out


def metzudat_zion() -> tuple[list[dict], collections.Counter]:
    from macula import build_metzudat_zion as mz
    from macula.anchor_llm import fallback
    spans = word_span()
    sp = sqlite3.connect(f"file:{mz.SPINE}?mode=ro", uri=True)
    code2name = {v: k for k, v in mz.BOOK_MAP.items()}
    rows, st = [], collections.Counter()
    for line in mz.CACHE.read_text(encoding="utf-8").splitlines():
        ch = json.loads(line)
        if ch.get("license") not in ("Public Domain", "CC0"):
            st["licence_skipped"] += 1
            continue
        for vi, comments in enumerate(ch["verses"], start=1):
            comments = comments if isinstance(comments, list) else [comments]
            units = None
            for ci, c in enumerate(comments, start=1):
                m = re.match(r"\s*<b>([^<]+)</b>\s*\.?\s*(.*)", c or "", re.S)
                if not m:
                    continue
                st["comments"] += 1
                if units is None:
                    units = mz._verse_word_units(sp, ch["book"], ch["chapter"], vi)
                heading = re.sub(r"[.:]\s*$", "", m.group(1).strip())
                head = heading.split()[0] if heading.split() else ""
                u, anchor = mz._anchor(head, units), "rule"
                if not u:
                    u, anchor = fallback("metzudat_zion", ch["book"], ch["chapter"], vi, head, units, m.group(2)), "model"
                if not u or u["key"] not in spans:
                    st["not_anchored"] += 1
                    continue
                first, last = spans[u["key"]]
                text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(2))).strip()
                text = re.sub(r"[֑-ׇ]", "", text)
                locus = f"Metzudat Zion on {code2name[ch['book']]} {ch['chapter']}:{vi}:{ci}"
                base = {"subject_first": first, "subject_last": last, "witness": "metzudat_zion", "locus": locus,
                        "register": "peshat", "anchor": anchor, "object_first": None, "object_last": None,
                        "licence": ch.get("license")}
                found = False
                for formula, says in (("ענין", "sense"), ("מלשון", "from_word"), ("לשון", "expression")):
                    pat = formula if formula != "לשון" else r"(?<!מ)לשון"
                    for t in terms_after(text, pat):
                        rows.append({**base, "says": says, "term": t, "formula": formula})
                        st[says, anchor] += 1
                        found = True
                if not found:
                    words = [w for w in re.findall(r"[א-ת״׳'\"]+", mz._CITE_START.split(" " + text, maxsplit=1)[0])
                             if w not in mz._OPENER_WORDS]
                    if len(words) == 1 or (words and len(words) <= 3 and not words[0].startswith(mz.SKIP_OPENERS)):
                        t = clean(words[0])
                        if len(t) >= 2 and t not in STOP and t not in GLOSS_OPENERS and t != clean(head):
                            rows.append({**base, "says": "gloss", "term": t, "formula": ""})
                            st["gloss", anchor] += 1
    return rows, st


# ---------- P2: what a psalm is, as the commentators say at its opening ----------
SEFARIA = HERE / ".cache" / "sefaria" / "2026-11-18"
PSALM_WORKS = ("radak", "meiri", "ibn_ezra", "rashi", "metzudat_david", "malbim")
OPEN_LICENCES = ("Public Domain", "CC0")
OPENING = re.compile(r"(?:ה?מזמור ה?זה|זה המזמור|מזמור זה|המזמור)[^.:]{0,40}?(?:אמר|אמרו|נאמר|חבר|חברו|יאמר|נאמרה|עשה|תקן)")
KIND = ("תפלה", "שבח", "הודאה", "תחנה", "תחנונים", "קינה", "בקשה", "תוכחה", "נבואה", "שירה", "הלל", "תהלה", "מוסר", "תשובה",
        "ודוי", "בטחון", "שמחה", "צעקה", "זעקה", "קללה", "ברכה")
VOICE = ("דוד", "גלות", "כל אדם", "כל ישראל", "ישראל", "משה", "שלמה", "אסף", "בני קרח", "חזקיה", "יחיד", "צבור", "חסיד", "עני",
         "משורר", "נביא", "לעתיד", "ימות המשיח", "משיח")     # matched with a prefix letter (ה, ו, ב, ל) allowed
DERASH = re.compile(r"דרש|רז״ל|רז\"ל|רבותינו|מדרש|אגדה|חז״ל|חז\"ל")


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\u0591-\u05C7]", "", re.sub(r"<[^>]+>", " ", s))).strip()


def psalm_opening(work: str, n: int, verses: int = 2) -> tuple[list[tuple[str, str]], str] | None:
    """The comments on the psalm's first `verses` verses (Hebrew numbering, as Sefaria), from the first version with an open
    licence: ([(locus, plain text)], licence)."""
    p = SEFARIA / work / f"{n}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    v = next((x for x in d.get("versions") or [] if x.get("license") in OPEN_LICENCES and x.get("text")), None)
    if v is None:
        return None
    title = d.get("title") or d.get("indexTitle") or work
    out = []
    for vi, comments in enumerate(v["text"][:verses], start=1):
        comments = comments if isinstance(comments, list) else [comments]
        for ci, c in enumerate(comments, start=1):
            if isinstance(c, str) and c.strip():
                out.append((f"{title} {n}:{vi}:{ci}", _plain(c)))
    return out, v["license"]


def psalm_span(n: int) -> tuple[str, str] | None:
    sp = sqlite3.connect(f"file:{MACULA}?mode=ro", uri=True)
    r = sp.execute("SELECT MIN(key), MAX(key) FROM macula_words WHERE book='PSA' AND chapter=?", (n,)).fetchone()
    return (r[0], r[1]) if r and r[0] else None


def verse_span(book: str, c: int, v: int) -> tuple[str, str] | None:
    sp = sqlite3.connect(f"file:{MACULA}?mode=ro", uri=True)
    r = sp.execute("SELECT MIN(key), MAX(key) FROM macula_words WHERE book=? AND chapter=? AND verse=?", (book, c, v)).fetchone()
    return (r[0], r[1]) if r and r[0] else None


HONORIFIC = re.compile(r"(?:זכרונם|זכרם|זכרו|זכרונו|זכרו)\s+לברכה|ז[״\"]ל|זצ[״\"]ל")
KIND_WINDOW = 6
NEGATORS = {"לא", "אינו", "אין", "איננו", "אינם", "ולא", "בלא", "בלי"}


def kind_terms(sent: str) -> list[str]:
    """Kind terms said of this psalm: within KIND_WINDOW words after המזמור or מזמור זה/הזה (not the heading's own מזמור, not
    המזמורים = psalms in general), the sages' honorific (זכרונם לברכה …) removed first; a negation word ends the window."""
    words = HONORIFIC.sub(" ", sent).split()
    found = []
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if re.fullmatch(r"[ו]?[בל]?המזמור", w) or (w == "מזמור" and nxt in ("זה", "הזה")):
            for x in words[i + 1:i + 1 + KIND_WINDOW]:
                x = x.strip(".,:;()")
                if x in NEGATORS or re.fullmatch(r"[ו]?(?:ה)?מזמור", x):
                    break                                    # "המזמור אינו ענין תפלה"; the next מזמור starts its own window
                for t in KIND:
                    if re.fullmatch(rf"[וה]?[בל]?[ה]?{t}", x) and t not in found:
                        found.append(t)
    return found


VOICE_VERBS = r"(?:אמרו|אמר|אמרה|אמרם|חברו|חבר|חברה|יסדו|יסד|נאמר\s+על\s+לשון|על\s+לשון|בלשון|מלשון)"


def voice_terms(sent: str) -> list[str]:
    """Who says the psalm: a VOICE term right after a saying or composing verb (אמרו דוד, חברו אסף) or after על לשון /
    בלשון (in the mouth of). A term that is only mentioned (על דוד = about David, the exile as topic) does not count."""
    sent = HONORIFIC.sub(" ", sent)
    found = []
    for t in VOICE:
        if re.search(rf"(?:^|\s){VOICE_VERBS}\s+(?:[ה]?{t}|[ל]?[ה]?{t})(?:[\s.,:;]|$)", sent) and t not in found:
            found.append(t)
    return found


def psalm_rules() -> tuple[list[dict], collections.Counter]:
    """Rule statements from a fixed opening formula (המזמור הזה … אמרו / נאמר …): in that sentence, kind terms (kind_terms)
    and voice terms (voice_terms) from fixed lists, each parenthesised verse citation as an occasion (object = that verse), register derash where the sentence
    names a midrash or the sages."""
    from macula import hebrew_refs
    rows, st = [], collections.Counter()
    for work in PSALM_WORKS:
        for n in range(1, 151):
            got = psalm_opening(work, n)
            span = psalm_span(n)
            if not got or not span:
                continue
            st[work, "psalms"] += 1
            comments, lic = got
            hit = False
            for locus, text in comments:
                for sent in re.split(r"(?<=[.:])\s+", text):
                    if not OPENING.search(sent):
                        continue
                    hit = True
                    base = {"subject_first": span[0], "subject_last": span[1], "witness": work, "locus": locus, "anchor": "rule",
                            "register": "derash" if DERASH.search(sent) else "peshat", "object_first": None, "object_last": None,
                            "formula": OPENING.search(sent).group(0), "licence": lic}
                    for t in kind_terms(sent):
                        rows.append({**base, "says": "kind", "term": t})
                    vs_ = voice_terms(sent)
                    for t in vs_:
                        if not any(t != u and t in u for u in vs_):        # ישראל inside כל ישראל, משיח inside ימות המשיח
                            rows.append({**base, "says": "voice", "term": t})
                    for a, z, b, c, v in hebrew_refs.find(sent):
                        vs = verse_span(b, c, v)
                        if vs and not (b == "PSA" and c == n):
                            rows.append({**base, "says": "occasion", "term": None, "object_first": vs[0], "object_last": vs[1],
                                         "citation": sent[a:z]})
            st[work, "with_opening"] += hit
    for r in rows:
        st[r["witness"], r["says"]] += 1
    return rows, st


def witnesses() -> list[dict]:
    return [dict(r) for r in csv.DictReader((RES / "witnesses.tsv").open(encoding="utf-8"), delimiter="\t")]


def lists() -> list[dict]:
    out = []
    for r in csv.DictReader((l for l in (RES / "lists.tsv").open(encoding="utf-8") if not l.startswith("#")), delimiter="\t"):
        r["members"] = [" ".join(clean(w) for w in x.split()) for x in r["members"].split("|") if x]
        out.append(r)
    return out


def lemma_index() -> dict[str, set[str]]:
    from macula import build_metzudat_zion as mz
    return mz._bare_index(mz.excluded())


def build(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    (out / "model").mkdir(exist_ok=True)
    rows, st = metzudat_zion()
    prow, pst = psalm_rules()
    rows += prow
    st.update(pst)
    ls = lists()
    on_list = collections.defaultdict(list)
    for l in ls:
        for t in l["members"]:
            on_list[t].append(l["list_id"])
    rule = [r for r in rows if r["anchor"] == "rule"]
    model = [r for r in rows if r["anchor"] == "model"]
    for name, rs in (("statements.jsonl", rule), ("model/statements.jsonl", model)):
        with (out / name).open("w", encoding="utf-8") as f:
            for i, r in enumerate(rs, start=1):
                r = {k: r.get(k) for k in COLUMNS}
                f.write(json.dumps({"id": f"{'m' if 'model' in name else 's'}{i:06d}", **r}, ensure_ascii=False) + "\n")
    idx = lemma_index()
    from macula import build_metzudat_zion as mz
    count = collections.Counter(r["term"] for r in rule if r["term"])
    says_of = collections.defaultdict(collections.Counter)
    for r in rule:
        if r["term"]:
            says_of[r["term"]][r["says"]] += 1
    every = set(count) | set(on_list)
    with (out / "terms.tsv").open("w", encoding="utf-8") as f:
        f.write("term\tstatements\tsays\tlemma_strong\tlists\n")
        for t in sorted(every, key=lambda t: (-count[t], t)):
            hits = mz._resolve_sense_word(t, idx)
            f.write(f"{t}\t{count[t]}\t{'|'.join(f'{k}:{v}' for k, v in says_of[t].most_common())}\t"
                    f"{next(iter(hits)) if len(hits) == 1 else ''}\t{'|'.join(on_list[t])}\n")
    with (out / "lists.tsv").open("w", encoding="utf-8") as f:
        lic = {w["witness"]: w["licence"] for w in witnesses()}
        f.write("list_id\twitness\tlocus\tformula\tmembers\tlicence\n")
        for l in ls:
            f.write(f"{l['list_id']}\t{l['witness']}\t{l['locus']}\t{l['formula']}\t{'|'.join(l['members'])}\t{lic[l['witness']]}\n")
    ws = witnesses()
    with (out / "witnesses.tsv").open("w", encoding="utf-8") as f:
        f.write("\t".join(ws[0]) + "\n" + "".join("\t".join(w.values()) + "\n" for w in ws))
    stats = {"statements": len(rule), "model_anchored": len(model), "terms": len(every),
             "by_says": dict(collections.Counter(r["says"] for r in rule)), "extract": {str(k): v for k, v in st.items()}}
    (out / "build.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    print(json.dumps(build(a.out), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
