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
    speakers = greek_speakers.find(quotations, con)     # quotation id -> {"names", "refs", "how": "tree"|"near", "basis", "alt_eng",
                                                        #   "speaker_id", "speaker_name", "speaker_name_ref"}
Who the speaker is across speeches (characters): `speaker_id`, a stable id for the speaker data's label, and `speaker_name`, that
person's proper name in the text, with `speaker_name_ref` the word that gives it; the same rules as the Hebrew speaker layer
(macula/build_speaker_layer.characters).

Groups: a speech whose inquit (or review row) names two or more is a group's: its id is that set of names (global where all are
proper names, else per book), it has no `speaker_name`, and `speaker_members` lists the ids of the members who speak on their own in
the same book.

Review (resources/speaker_quotations/nt_review.tsv): where the speaker data's label or the inquit found is wrong, a row sets the
speech's label (field speaker) or the words naming its speaker (field name: word ids, people separated by ","; "-" for none).
"""
from __future__ import annotations

import bisect
import collections
import csv
import glob
import hashlib
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOWFAT = HERE / ".lowfat-src-grc"
CHARACTERS = HERE.parents[1] / "resources" / "speaker_quotations" / "nt_characters.tsv"
REVIEW = HERE.parents[1] / "resources" / "speaker_quotations" / "nt_review.tsv"
NO_CHARACTER = ("", "(the one addressed)", "(he/she)", "(they)")     # labels that name no one person
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


def review() -> dict[tuple[str, str], str]:
    """(speech id, field) -> value of the hand review."""
    if not REVIEW.exists():
        return {}
    with open(REVIEW, encoding="utf-8") as fh:
        return {(r["word_start"], r["field"]): r["value"]
                for r in csv.DictReader((line for line in fh if not line.startswith("#")), delimiter="\t")}


def find(quotes: dict[str, list[dict]], con: sqlite3.Connection) -> tuple[dict[str, dict], str]:
    W, sha = lowfat_words()
    fix = review()
    quotes = {b: [dict(q, speaker=fix.get((q["id"], "speaker"), q["speaker"])) for q in qs] for b, qs in quotes.items()}
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
            v = out[q["id"]] = {"names": names, "refs": [k for _, k in subj], "inquit": verb, "how": how,
                                "basis": "inquit" if names else "", "alt_eng": "", "reviewed": any((q["id"], f) in fix for f in ("speaker", "name"))}
            given = fix.get((q["id"], "name"))
            if given == "-":
                v["names"], v["refs"], v["basis"] = [], [], ""
            elif given:
                parts = [p.split() for p in given.split(",")]
                if any(k not in W for p in parts for k in p):
                    raise SystemExit(f"{REVIEW.name}: {q['id']}: a word id not in MACULA Greek: {given}")
                v["names"] = list(dict.fromkeys(W[p[0]]["lemma"] for p in parts))
                v["refs"], v["basis"] = [k for p in parts for k in p], "review"
    carry_over(quotes, out, W)
    characters(quotes, out, W)
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


def characters(quotes: dict[str, list[dict]], out: dict[str, dict], W: dict[str, dict]) -> collections.Counter:
    """Each speech's character. `speaker_id`: a stable id for the speaker data's label, kept in resources/speaker_quotations/
    nt_characters.tsv (id, label, book, name_key; a label not in it gets the next id, appended). A label with a proper name has one
    id for the whole New Testament, one without ("crowd", "someone") one per book; two labels of one person share an id, set there by
    hand. `speaker_name`: the proper name (or θεός) that more than half of the person's speeches named by a proper name, and at
    least a third of those named at all, are named by in their own inquit, and that no other person is named by more than three
    times as often (narrators get none); else the table's name_key, the word that names the person where no inquit does ("-": none).
    `speaker_name_ref`: the speech's own word where its inquit gives that name, else the nearest speech's that does (in the same book
    first), else the nearest name_key."""
    import sys
    sys.path.insert(0, str(HERE.parent))
    from references import BOOK_NUMBERS
    usfm = {f"{n:02d}": b for b, n in BOOK_NUMBERS.items()}
    label = {q["id"]: q["speaker"] for qs in quotes.values() for q in qs}
    rows, by_key = [], {}
    if CHARACTERS.exists():
        with open(CHARACTERS, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        by_key = {(r["label"], r["book"]): r for r in rows}

    def group(k: str) -> list[str]:                # the names of a speech two or more speak (inquit or review)
        v = out[k]
        return v["names"] if v["basis"] in ("inquit", "review") and len(v["names"]) > 1 else []

    def all_proper(k: str) -> bool:
        heads = {W[r]["lemma"]: W[r] for r in out[k]["refs"] if r in W}
        return all(n in heads and (heads[n]["type"] == "proper" or n in DIVINE) for n in group(k))

    def proper(k: str) -> bool:                    # the speech's own inquit names one person by a proper name or θεός
        v = out[k]
        if v["basis"] not in ("inquit", "review") or len(v["names"]) != 1 or not v["refs"]:
            return False
        head = W.get(v["refs"][0])
        return head is not None and (head["type"] == "proper" or head["lemma"] in DIVINE)

    def usual(ks: list[str]) -> str:
        c = collections.Counter(out[k]["names"][0] for k in ks if proper(k))
        top = c.most_common(1)
        if not top or top[0][1] * 2 <= sum(c.values()):
            return ""
        return top[0][0] if top[0][1] * 3 >= sum(out[k]["basis"] == "inquit" for k in ks) else ""

    by_label = collections.defaultdict(list)
    for k in sorted(out):
        if group(k):
            label[k] = "group: " + ", ".join(sorted(group(k)))
        elif label.get(k, "") not in NO_CHARACTER:
            by_label[label[k]].append(k)
    named = {lb for lb, ks in by_label.items() if usual(ks)}
    nxt = max((int(r["id"][1:]) for r in rows), default=0)
    added, cid_of = [], {}
    for k in sorted(out):
        lb = label.get(k, "")
        if lb in NO_CHARACTER:
            continue
        r = by_key.get((lb, "")) or by_key.get((lb, usfm[k[:2]]))
        if r is None:
            nxt += 1
            whole = all_proper(k) if group(k) else lb in named
            r = {"id": f"n{nxt:04d}", "label": lb, "book": "" if whole else usfm[k[:2]], "name_key": ""}
            by_key[(r["label"], r["book"])] = r
            added.append(r)
        cid_of[k] = r["id"]
    if added:
        with open(CHARACTERS, "a" if rows else "w", encoding="utf-8") as fh:
            if not rows:
                fh.write("id\tlabel\tbook\tname_key\n")
            fh.write("".join(f"{r['id']}\t{r['label']}\t{r['book']}\t{r['name_key']}\n" for r in added))
    by_id = collections.defaultdict(list)
    for k, cid in cid_of.items():
        by_id[cid].append(k)
    hand = collections.defaultdict(list)
    for r in by_key.values():
        hand[r["id"]] += [x for x in r["name_key"].split() if x in W or x == "-"]
    uses: dict = collections.defaultdict(collections.Counter)
    for cid, ks in by_id.items():
        for n, c in collections.Counter(out[k]["names"][0] for k in ks if proper(k)).items():
            uses[n][cid] = c
    stats = collections.Counter(added=len(added))
    for v in out.values():
        v["speaker_id"], v["speaker_name"], v["speaker_name_ref"], v["speaker_members"], v["group"] = "", "", "", [], False
    name_of, books_of = {}, collections.defaultdict(set)
    for cid, ks in by_id.items():
        if group(ks[0]):
            for k in ks:
                out[k]["speaker_id"], out[k]["group"] = cid, True
            stats["groups"] += 1
            continue
        books_of[cid] |= {k[:2] for k in ks}
        name = "" if "-" in hand[cid] else W[hand[cid][0]]["lemma"] if hand[cid] else usual(ks)
        if not hand[cid] and name and (uses[name][cid] * 3 < max(uses[name].values()) or label[ks[0]].startswith("narrator")):
            name = ""
        givers = [k for k in ks if proper(k) and out[k]["names"][0] == name]
        for k in ks:
            v = out[k]
            v["speaker_id"], v["speaker_name"] = cid, name
            if not name:
                continue
            near = sorted(givers, key=lambda c: (c[:2] != k[:2], abs(int(c) - int(k))))
            v["speaker_name_ref"] = out[near[0]]["refs"][0] if near else \
                min(hand[cid], key=lambda x: (x[:2] != k[:2], abs(int(x) - int(k))))
            stats["named by hand" if not near else "named"] += 1
        stats["characters"] += 1
        stats["characters named"] += bool(name)
        if name:
            name_of[cid] = name
    for k, v in out.items():                       # a group's members: the people of its names who speak in the same book; where
        if v["speaker_id"] and group(k):           # two share a name (Ἰωάννης), the one who speaks nearest
            near = {m: min(abs(int(x) - int(k)) for x in by_id[m] if x[:2] == k[:2])
                    for m in name_of if k[:2] in books_of[m]}
            v["speaker_members"] = [min((m for m in near if name_of[m] == p), key=near.get) for p in group(k)
                                    if any(name_of[m] == p for m in near)]
            stats["group speeches"] += 1
            stats["group speeches with members"] += bool(v["speaker_members"])
    stats["speeches with a character"] = sum(len(ks) for ks in by_id.values())
    return stats


def named_by_hand() -> int:
    """How many people the characters table names (a name_key, not "-")."""
    with open(CHARACTERS, encoding="utf-8") as fh:
        return len({r["id"] for r in csv.DictReader(fh, delimiter="\t") if r["name_key"] and r["name_key"] != "-"})
