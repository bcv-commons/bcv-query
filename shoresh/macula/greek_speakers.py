"""The speaker of a New Testament quotation, named from the Greek text: the subject of the verb that introduces it.

The speaker data (resources/speaker_quotations) gives where a quotation runs, and an English label for who speaks. The label is
not used: the name comes from MACULA Greek (Nestle 1904 lowfat, CC BY 4.0).
- The inquit: the verb of the nearest clause above the quotation's first word in the tree, outside the quotation (εἶπεν, λέγων,
  ἔφη, ἐπηρώτησεν …). When the speech starts a sentence of its own (Matt 5:3 after 5:2 "λέγων"), the nearest verb of saying before it.
- Its subject: MACULA's `subjref` where the subject is not written (the word it points to), else the subject phrase (role s) of the
  inquit's clause. A pronoun (or the article used as one: ὁ δὲ ἔφη) is followed to the word it refers to (`referent`), up to three steps.
- The name is the lemma of that noun or adjective: Ἰησοῦς, Πέτρος, μαθητής, ἡγεμών, γραφή. Several subjects are listed. Where the
  subject is not a noun or adjective (a participle, an unnamed "they"), there is no name; then the same speaker's usual name from
  their other speeches (carry_over), else the speaker data's English label in alt_eng.

    from macula import greek_speakers
    speakers = greek_speakers.find(quotations, con)     # quotation id -> {"names", "refs", "how": "tree"|"near", "basis", "alt_eng"}
"""
from __future__ import annotations

import bisect
import collections
import glob
import hashlib
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOWFAT = HERE / ".lowfat-src-grc"
DIVINE = {"θεός"}                                  # God's name, carried over like a proper name
SAYING = {"λέγω", "εἶπον", "φημί", "ἀποκρίνομαι", "λαλέω", "κράζω", "γράφω", "ἐρωτάω", "ἐπερωτάω", "βοάω", "φωνέω"}


def lowfat_words() -> tuple[dict[str, dict], str]:
    """Word key -> its lowfat attributes (lemma, class, role, subjref, referent); and the SHA-256 of the files read."""
    out, h = {}, hashlib.sha256()
    files = sorted(glob.glob(str(LOWFAT / "*.xml")))
    if not files:
        raise SystemExit(f"no MACULA Greek lowfat files in {LOWFAT}: run python -m macula.build_trees once (it downloads them)")
    for f in files:
        data = Path(f).read_bytes()
        h.update(data)
        for m in re.finditer(r"<w\b([^>]*)>([^<]*)</w>", data.decode("utf-8")):
            at = dict(re.findall(r'([\w:]+)="([^"]*)"', m.group(1)))
            out[at["xml:id"][1:]] = {k: at.get(k) for k in ("lemma", "class", "role", "subjref", "referent", "type")}
    return out, h.hexdigest()


def find(quotes: dict[str, list[dict]], con: sqlite3.Connection) -> tuple[dict[str, dict], str]:
    W, sha = lowfat_words()
    parent = {r[0]: r[1] for r in con.execute("SELECT id, parent FROM nodes WHERE corpus='grc'")}
    info = {r[0]: (r[1], r[2]) for r in con.execute("SELECT id, role, cls FROM nodes WHERE corpus='grc'")}
    kids: dict[int, list[int]] = collections.defaultdict(list)
    for n, p in parent.items():
        if p is not None:
            kids[p].append(n)
    cl_of, under_node = {}, collections.defaultdict(list)
    for key, cl, p in con.execute("SELECT key, cl, parent FROM words WHERE corpus='grc' ORDER BY key"):
        cl_of[key] = cl
        under_node[p].append(key)
    by_cl = collections.defaultdict(list)
    for k, c in cl_of.items():
        by_cl[c].append(k)
    keys = sorted(W)

    def words_under(n: int) -> list[str]:
        out = list(under_node[n])
        for c in kids[n]:
            out += words_under(c)
        return sorted(out)

    def name_of(key: str) -> tuple[str, str] | None:
        w = W.get(key)
        for _ in range(3):
            if w is None:
                return None
            if w["class"] in ("noun", "adj", "num"):
                return w["lemma"], key
            if w["class"] in ("pron", "det") and w["referent"]:      # αὐτός, and the article as a pronoun (ὁ δὲ ἔφη)
                key = w["referent"].split()[0][1:]
                w = W.get(key)
                continue
            return None
        return None

    def subject(verb: str) -> list[tuple[str, str]]:
        if W[verb]["subjref"]:
            return [n for n in (name_of(r[1:]) for r in W[verb]["subjref"].split()) if n]
        stack = list(kids[cl_of[verb]])
        while stack:                                   # the subject phrase of the inquit's clause
            n = stack.pop()
            if info[n][0] == "s":
                return next(([nm] for nm in (name_of(k) for k in words_under(n)) if nm), [])
            if info[n][1] != "cl":
                stack += kids[n]
        for k in by_cl[cl_of[verb]]:
            if W[k]["role"] == "s":
                nm = name_of(k)
                return [nm] if nm else []
        return []

    def inquit(q: dict) -> tuple[str | None, str | None]:
        c = parent.get(cl_of.get(q["start"]))
        while c is not None:
            for k in by_cl.get(c, []):
                if not (q["start"] <= k <= q["end"]) and (W[k]["role"] == "v" or W[k]["class"] == "verb"):
                    return k, "tree"
            c = parent.get(c)
        i = bisect.bisect_left(keys, q["start"])
        for k in reversed(keys[max(0, i - 25):i]):
            if W[k]["lemma"] in SAYING:
                return k, "near"
        return None, None

    out = {}
    for qs in quotes.values():
        for q in qs:
            verb, how = inquit(q)
            subj = subject(verb) if verb else []
            names = list(dict.fromkeys(n for n, _ in subj))
            out[q["id"]] = {"names": names, "refs": [k for _, k in subj], "inquit": verb, "how": how,
                            "basis": "inquit" if names else "", "alt_eng": ""}
    carry_over(quotes, out, W)
    return out, sha


def carry_over(quotes: dict[str, list[dict]], out: dict[str, dict], W: dict[str, dict]) -> None:
    """A speech whose inquit names no one takes its speaker's usual Greek name from the same speaker's other speeches (the speaker
    data's label tells only who it is; the name and its word ids come from the text there): in the same book, else in the whole New
    Testament. The name must be a proper name or θεός (not ἄνθρωπος, ὄχλος), named so in at least two of that speaker's speeches and
    in more than half, and a name that is mostly this speaker's. What is still unnamed keeps the label in alt_eng, so no speaker the
    speaker data names is lost."""
    label = {q["id"]: q["speaker"] for qs in quotes.values() for q in qs}
    named = [(k, v) for k, v in out.items() if v["basis"] == "inquit" and len(v["names"]) == 1]
    owner: dict = collections.defaultdict(collections.Counter)
    for k, v in named:
        owner[v["names"][0]][label[k]] += 1

    def fits(k: str, v: dict) -> bool:
        head = W.get(v["refs"][0]) if v["refs"] else None
        return head is not None and (head["type"] == "proper" or head["lemma"] in DIVINE) \
            and owner[v["names"][0]].most_common(1)[0][0] == label[k]
    for k, v in out.items():
        if v["names"] or not label.get(k):
            continue
        cands = [(c, cv) for c, cv in named if label[c] == label[k] and fits(c, cv)]
        for pool, basis in (([x for x in cands if x[0][:2] == k[:2]], "same speaker in book"), (cands, "same speaker in NT")):
            usual = collections.Counter(cv["names"][0] for _, cv in pool).most_common(2)
            if usual and usual[0][1] >= 2 and usual[0][1] * 2 > len(pool) and (len(usual) == 1 or usual[0][1] > usual[1][1]):
                c, cv = min((x for x in pool if x[1]["names"][0] == usual[0][0]), key=lambda x: abs(int(x[0]) - int(k)))
                v["names"], v["refs"], v["basis"] = list(cv["names"]), list(cv["refs"]), basis
                break
            if pool:
                break
        if not v["names"]:
            v["alt_eng"] = label[k]
