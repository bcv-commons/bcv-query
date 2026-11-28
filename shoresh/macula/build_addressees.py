#!/usr/bin/env python3
"""Addressee per quotation, and a person table (wave 3, development-phase plan: "addressee per quotation and a person table,
then listener, speaker's role and age relation"). By rule, from the source text only.

    cd shoresh && .venv/bin/python3 -m macula.build_addressees

Output macula/data/addressees/ (git-ignored):
  quotations.tsv  one row per quotation (Hebrew speaker layer ids, Greek layout quotation ids):
    corpus, quote, first (its first clause key), speaker_id, speaker (ACAI entity of the speaker's character), addressee (entity, or lemma:<lemma> where none
    resolves), addressee_id (character id where the addressee speaks elsewhere), basis, addressee_words (the words that name the
    addressee), second_person (entity most second-person words inside the quotation point to), agree (1 / 0 where inquit and
    second_person both give an entity), plural (1 when the addressee is a group or plural), relation (see below),
    number (singular / plural / ''), number_basis, strongest first (second_person: most of the quotation's second-person words,
    at least 2 of them and 2/3; inquit_word: the number of the word that names the hearer; entity: the entity's type), member_of_plural (the person
    an entity lookup gave a plural hearer, kept here, not as the addressee)
  basis:
    inquit         the inquit's addressee: Hebrew אֶל / לְ / עַל phrase, or object of צִוָּה; Greek dative, πρός + accusative, or the
                   accusative of a verb of asking or urging; resolved through reference-status referents, then ACAI word links
    second_person  no addressee in the inquit; the person, deity or group most of the quotation's second-person words of the
                   quotation's own number are linked to by ACAI (a plural majority takes a group only); the entity must have at least a
                   third of the quotation's second-person words
    review         a row of resources/speaker_quotations/nt_review.tsv (field addressee: the Greek word ids that name the
                   hearer in the text, "-" for none), where the rules below go wrong; the number is that word's own
    turn           neither; the quotation answers the one before it (same or previous verse, another speaker, said to this
                   speaker): that one's speaker is the addressee
    ''             unknown
  relation (speaker to addressee): parent_to_child, child_to_parent, spouse, sibling, divine_to_human, human_to_divine,
    to_group, '' otherwise. From ACAI's kinship and entity types; no social rank is guessed.
  persons.tsv     one row per entity that speaks or is addressed: entity, type, gender, character ids, quotations spoken,
                  quotations addressed, father, mother, partners, children (counts from ACAI kinship)
  checks.md, build.json
Not read: BHSA, TBTA, English text (ACAI ids are English names: the release codes them).
"""
from __future__ import annotations

import collections
import csv
import datetime
import json
import sqlite3
import subprocess
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "addressees"
NFC = lambda s: unicodedata.normalize("NFC", s)   # noqa: E731
PREP_HBO = {NFC(p) for p in ("אֶל", "לְ", "עַל")}
OBJ_HBO = {"6680"}                                    # צִוָּה: the one commanded is the object
PREP_GRC = {"πρός"}
OBJ_GRC = {"ἐρωτάω", "ἐπερωτάω", "παρακαλέω", "παραγγέλλω", "ἐπιτιμάω"}
KIN = {"father", "mother", "offspring", "partner", "sibling"}
SPK_TO = {"father": "child_to_parent", "mother": "child_to_parent", "offspring": "parent_to_child", "partner": "spouse", "sibling": "sibling"}
SPK_FROM = {"father": "parent_to_child", "mother": "parent_to_child", "offspring": "child_to_parent", "partner": "spouse", "sibling": "sibling"}
COLS = ["corpus", "quote", "first", "speaker_id", "speaker", "addressee", "addressee_id", "basis", "addressee_words", "second_person",
        "agree", "plural", "relation", "number", "number_basis", "member_of_plural"]
SINGLE = ("person", "deity")                          # entity kinds that cannot be a plural hearer


REVIEW = HERE.parents[1] / "resources" / "speaker_quotations" / "nt_review.tsv"


def tsv(p: Path):
    return csv.DictReader((l for l in open(p, encoding="utf-8") if not l.startswith("#")), delimiter="\t")


def main() -> int:
    m = sqlite3.connect(f"file:{HERE / 'macula-spine.db'}?mode=ro", uri=True)
    w = {k: (lang, cls or "", (st or "").zfill(4)[:4] if lang == "hbo" else "", NFC(lem or ""), pers or "", num or "")
         for k, lang, cls, st, lem, pers, num in m.execute("select key, lang, class, strong, lemma, person, number from macula_words")}
    participle = {k[:12]: (t or "").startswith("participle") for k, t in
                  sqlite3.connect(f"file:{HERE / 'lowfat-hbo.db'}?mode=ro", uri=True).execute(
                      "select key, type from lowfat_words where class = 'verb'")}
    # word -> entity: reference-status referents first (they follow chains), then ACAI's own links
    ref = {}
    for r in tsv(DATA / "reference-status/np.tsv"):
        if r["referent"] and not r["referent"].startswith("unresolved"):
            ref[r["head"]] = r["referent"]
    acai = {}
    for r in tsv(DATA / "entities/entity_words.tsv"):
        if r["kind"] in ("explicit", "pronominal", "subject"):
            acai.setdefault(r["word"], r["entity"])                  # full ACAI ids: Saul.2 is not Saul
    ents = {r["entity"]: r for r in tsv(DATA / "entities/entities.tsv")}
    char_ent = {r["character"]: r["entity"] for r in tsv(DATA / "entities/characters.tsv")}
    ent_chars = collections.defaultdict(set)
    for c, e in char_ent.items():
        ent_chars[e].add(c)
    kin = collections.defaultdict(dict)
    kcount = collections.defaultdict(collections.Counter)
    for r in tsv(DATA / "entities/kinship.tsv"):
        a, b = r["entity"], r["other"]
        if r["relation"] in KIN:
            kin[a][b] = r["relation"]
            kcount[a][r["relation"]] += 1

    def entity(word: str) -> str:
        return ref.get(word) or acai.get(word) or ""

    # clause order, quotation per clause, words per clause
    words, order = {}, []
    for corpus, sub, field in (("hbo", "clause-layout", "clause_key"), ("grc", "nt-clause-layout", "first")):
        for f in sorted((DATA / sub / "clauses").glob("*/*.jsonl")):
            for line in open(f, encoding="utf-8"):
                r = json.loads(line)
                k = r[field]
                if k not in words:
                    words[k] = []
                    order.append((corpus, k))
                words[k].extend(r["words"])
    frame = {r["clause_key"]: r for r in tsv(DATA / "quote-frames/clauses.tsv")}
    roles = collections.defaultdict(list)
    for r in tsv(DATA / "arg-roles/roles.tsv"):
        roles[r["clause_key"]].append(r)
    # quotations: speaker id, words, opening clause, inquit clause
    q_speaker, q_words, q_first, q_inquit, q_order = {}, collections.defaultdict(list), {}, {}, []
    for r in tsv(DATA / "speaker-layer/quotations.tsv"):
        q_speaker[r["id"]] = r["speaker_id"]
    for f in sorted((DATA / "nt-clause-layout/clauses").glob("*/*.jsonl")):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r["quotation"]:
                q_speaker.setdefault(r["quotation"], r["speaker_id"] or "")
    pending = {}
    for corpus, k in order:
        fr = frame.get(k)
        if fr is None:
            continue
        if fr["inquit"] == "1":
            pending[corpus] = k
        q = fr["quote"]
        if q:
            q_words[(corpus, q)].extend(words[k])
            if fr["opens"] == "1" and (corpus, q) not in q_first:
                q_first[(corpus, q)] = k
                q_order.append((corpus, q))
                if pending.get(corpus) and pending[corpus][:5] == k[:5]:
                    q_inquit[(corpus, q)] = pending.pop(corpus)

    def from_inquit(corpus: str, ck: str):
        for r in roles.get(ck, []):
            head = r["head"]
            hw = w.get(head, ("", "", "", "", "", ""))
            if not head and corpus == "hbo":                          # אֵלָיו "to him": the hearer is the preposition's suffix,
                for x in [y for y in r["words"].split() if y != r["prep"]] + ([r["prep"]] if r["prep"] else []):
                    e = entity(x)                                     # ACAI links the suffix (its own word id) or the preposition
                    if e:
                        return e, x, ""
                continue
            if not head:
                continue
            if hw[1] == "verb" and not (corpus == "hbo" and participle.get(head, False)):
                continue                                              # לֵאמֹר and other infinitives; a participle (נֹשֵׂא "bearer") can be the hearer
            verb = w.get(r["verb"], ("", "", "", "", "", "")) if r["verb"] else None
            ok = False
            if corpus == "hbo":
                ok = (r["relation"] == "pp" and NFC(r["prep_lemma"]) in PREP_HBO and r["role"] not in ("location", "time", "standard")) \
                    or (r["relation"] == "o" and verb is not None and verb[2] in OBJ_HBO)
            else:
                ok = (r["relation"] == "io" and r["case"] == "dative") or (NFC(r["prep_lemma"]) in PREP_GRC and r["case"] != "dative") \
                    or (r["relation"] == "o" and verb is not None and verb[3] in OBJ_GRC)
            if ok:
                e = entity(head)
                if e or hw[3]:
                    return (e or f"lemma:{hw[3]}"), head, hw[5]
        return "", "", ""

    def second_number(qws: list) -> str:
        """the number most of the quotation's second-person words have: at least 2 such words and 2/3 of them"""
        c = collections.Counter(w.get(x, ("",) * 6)[5] for x in qws if w.get(x, ("",) * 6)[4] == "second")
        tot = c["singular"] + c["plural"]
        for n in ("singular", "plural"):
            if tot >= 2 and c[n] / tot >= 2 / 3:
                return n
        return ""

    def from_second(qws: list, number: str) -> str:
        """the entity most second-person words of that number point to; plural: a group only (2026-11-26: a few singular
        words linked to the deity outvoted many plural ones linked to nothing, as in Acts 2 and Matthew 5)"""
        c = collections.Counter()
        total = sum(1 for x in qws if w.get(x, ("",) * 6)[4] == "second")
        for x in qws:
            e = acai.get(x, "")
            if w.get(x, ("",) * 6)[4] != "second" or e.split(":")[0] not in ("person", "deity", "group"):
                continue
            if number and w[x][5] != number:
                continue
            if number == "plural" and e.split(":")[0] in SINGLE:
                continue
            c[e] += 1
        if not c:
            return ""
        e, k = c.most_common(1)[0]
        return e if k >= total / 3 else ""                         # at least a third of all its second-person words

    reviewed = {}                                                  # Greek quotation -> the word ids that name its hearer
    if REVIEW.exists():
        for r in tsv(REVIEW):
            if r["field"] == "addressee":
                reviewed[r["word_start"]] = [] if r["value"] == "-" else r["value"].split(",")
    rows, st = [], collections.Counter()
    last_by_corpus = {}
    spoke, heard = collections.Counter(), collections.Counter()
    for corpus, q in q_order:
        sid = q_speaker.get(q, "")
        spk = char_ent.get(sid, "")
        ik = q_inquit.get((corpus, q))
        add, aw, num = from_inquit(corpus, ik) if ik else ("", "", "")
        if add and add == spk:
            add, aw, num = "", "", ""                                 # "the angel who spoke with me" names the speaker, not the hearer
        snum = second_number(q_words[(corpus, q)])
        sec = from_second(q_words[(corpus, q)], snum)
        if sec == spk:
            sec = ""
        member = ""
        if add and num == "plural" and add.split(":")[0] in SINGLE:
            # "said to them" resolved to one of them (Andrew, James): not the hearer (2026-11-26, research's Swahili check)
            member = add
            group = sec if sec.split(":")[0] == "group" else ""
            hw = w.get(aw, ("",) * 6)
            add = group or (f"lemma:{hw[3]}" if hw[3] else "")
            st[(corpus, "plural_member_dropped")] += 1
        basis = "inquit" if add else ""
        if corpus == "grc" and q in reviewed:
            named = [(entity(x), x) for x in reviewed[q]]
            if any(x not in w for _, x in named):
                raise SystemExit(f"nt_review.tsv: quotation {q}: an addressee word is not a Greek word: {reviewed[q]}")
            add, aw = next(((e, x) for e, x in named if e), ("", ",".join(reviewed[q])))
            if not add and reviewed[q]:
                add = f"lemma:{w[reviewed[q][0]][3]}"
            num = w[aw.split(",")[0]][5] if aw else ""
            basis, member, sec = ("review" if reviewed[q] else ""), "", ""
        if not add and sec:
            add, basis = sec, "second_person"
        prev = last_by_corpus.get(corpus)
        # a reply: the one before (same or previous verse, another speaker) was said to this speaker. Where the inquit names the
        # addressee, this holds 0.85 (Hebrew) and 0.75 (Greek); without "said to this speaker" only 0.5 to 0.65, so not used
        if not add and basis != "review" and q not in reviewed and prev and prev[1] and prev[1] != spk and prev[2] == spk and int(q_first[(corpus, q)][:8]) - int(prev[0][:8]) <= 1:
            add, basis = prev[1], "turn"
        last_by_corpus[corpus] = (q_first[(corpus, q)], spk, add)
        agree = ""
        if basis == "inquit" and not add.startswith("lemma:") and sec:
            agree = "1" if sec == add else "0"
        et = ents.get(add, {}).get("type", "")
        if basis == "review" and num in ("singular", "plural"):
            number, nbasis = num, "review"
        elif snum:                                   # the speech's own "you" first: John 14:23 is said to Judas, its "you" plural
            number, nbasis = snum, "second_person"
        elif basis == "inquit" and et == "group" and num != "plural":   # "to the crowd" (ὄχλῳ): a collective, heard as many
            number, nbasis = "plural", "entity"
        elif basis == "inquit" and num in ("singular", "plural"):
            number, nbasis = num, "inquit_word"
        elif et:
            number, nbasis = ("plural" if et == "group" else "singular"), "entity"
        else:
            number, nbasis = "", ""
        plural = "1" if et == "group" or num == "plural" or number == "plural" else "0"
        stype = ents.get(spk, {}).get("type", "")
        rel = ""
        if spk and add and not add.startswith("lemma:"):
            if add in kin.get(spk, {}):                                 # ACAI: (A, father, B) = B is A's father
                rel = SPK_TO.get(kin[spk][add], "")
            elif spk in kin.get(add, {}):
                rel = SPK_FROM.get(kin[add][spk], "")
            elif stype == "deity" and et == "person":
                rel = "divine_to_human"
            elif stype == "person" and et == "deity":
                rel = "human_to_divine"
            elif et == "group":
                rel = "to_group"
        aid = ",".join(sorted(ent_chars.get(add, set())))
        rows.append([corpus, q, q_first[(corpus, q)], sid, spk, add, aid, basis, aw, sec, agree, plural, rel, number, nbasis, member])
        st[(corpus, "number:" + (number or "none") + ":" + (nbasis or "-"))] += 1
        st[(corpus, "quotations")] += 1
        st[(corpus, "basis:" + (basis or "unknown"))] += 1
        if agree:
            st[(corpus, "agree:" + agree)] += 1
        if rel:
            st[(corpus, "relation:" + rel)] += 1
        if spk:
            spoke[spk] += 1
        if add and not add.startswith("lemma:"):
            heard[add] += 1
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "quotations.tsv", "w", encoding="utf-8") as f:
        f.write("\t".join(COLS) + "\n")
        f.writelines("\t".join(r) + "\n" for r in rows)
    with open(OUT / "persons.tsv", "w", encoding="utf-8") as f:
        f.write("entity\ttype\tgender\tcharacters\tspoke\taddressed\tfather\tmother\tpartners\tchildren\n")
        for e in sorted(set(spoke) | set(heard)):
            r, k = ents.get(e, {}), kcount.get(e, collections.Counter())
            f.write(f"{e}\t{r.get('type', '')}\t{r.get('gender', '')}\t{','.join(sorted(ent_chars.get(e, set())))}\t{spoke[e]}\t"
                    f"{heard[e]}\t{k['father']}\t{k['mother']}\t{k['partner']}\t{k['offspring']}\n")
    lines = ["# Addressees: checks", "", "| corpus | value | count |", "|---|---|---|"]
    lines += [f"| {c} | {v} | {n:,} |" for (c, v), n in sorted(st.items())]
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = subprocess.run(["git", "log", "-1", "--format=%h"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    (OUT / "build.json").write_text(json.dumps({"schema": 1, "built": datetime.date.today().isoformat(), "code": code,
                                                "not_read": ["BHSA", "TBTA", "English text"]}, indent=1) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
