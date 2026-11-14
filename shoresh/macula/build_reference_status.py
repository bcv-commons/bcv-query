#!/usr/bin/env python3
"""Reference status per noun phrase: who a phrase refers to, whether that referent is new, given or brought back, and how the source
marks it (wave 1b, development-phase plan 2026-11-13; first, rule-based version). What a translation needs to choose articles,
demonstratives and pronouns, where a rule-based drafter does worst.

    cd shoresh && .venv/bin/python3 -m macula.build_reference_status      (after macula.build_arg_roles)

Unit: the head of each constituent in macula/data/arg-roles/roles.tsv (its first noun / pronoun / adjective / number word).

  referent      who or what the head refers to, in order of evidence:
                  ACAI's entity for the word (explicit, pronominal or subject link; never the `speech` links)   basis acai
                  MACULA's reference from the word (subjref / participantref / referent), followed up to 4 steps to a word with an
                  ACAI entity, else to the last word reached; that word's entity or lemma                        basis ref
                  the head's own lemma ("lemma:<strong or lemma>")                                                  basis lemma
  status        new        the referent's first mention in the episode
                given      mentioned within the last 20 clauses of the episode
                restaged   mentioned earlier in the episode, more than 20 clauses back
                known      God (ACAI deity:Lord / deity:God) on first mention in an episode
                unresolved a pronoun head with no referent from ACAI or MACULA (basis unresolved)
                The episode is the chapter (paragraph marks would be finer; later). Mentions counted: every head, and every word
                ACAI links to the referent as an explicit, pronominal or implied-subject mention (verbs carry their subjects).
  distance      clauses since the referent's last mention in the episode ('' for new / known)
  definite      article | proper | suffix | construct | demonstrative | pronoun | '' : how the source marks the phrase as definite
                (Hebrew: the article in the head's word, also inside a preposition (morph Rd) or Aramaic determined state, a proper noun, a pronominal suffix on it, a construct head; Greek: an
                article in the constituent, a proper name; both: a demonstrative or a pronoun head)
  animacy       person | deity | animal | place | thing | '' : the referent's ACAI type (person and group → person), else the
                head's UBS domain (SDBH 001001001-3, Louw-Nida 9-12, 4); a noun with other domains is thing; a first / second person pronoun is person; other pronouns without a
                referent and words without domains ''
  proximity     near | remote | '' : a demonstrative in the constituent (Hebrew זֶה, זֹאת, אֵלֶּה, Aramaic דְּנָה ... near; an
                article-marked הוּא, הִיא, הֵם, הֵמָּה remote; Greek οὗτος near, ἐκεῖνος remote)

Output (git-ignored): macula/data/reference-status/{np.tsv, checks.md, build.json}. Codes and word ids only. Not read: BHSA, TBTA,
English text (ACAI's entity ids are names in English and stay internal: the referent column is for joining and testing here; a
release would carry our own codes).
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
OUT = DATA / "reference-status"
MSPINE = HERE / "macula-spine.db"
LOWFAT = HERE / "lowfat-hbo.db"
WINDOW = 20
GOD = {"deity:Lord", "deity:God"}
NEAR_HBO = {"זֶה", "זֹאת", "אֵלֶּה", "דְּנָה", "דָּא", "אֵל", "אִלֵּין", "דֵּךְ", "דִּכֵּן", "אִלֵּךְ"}
REMOTE_HBO = {"הוּא", "הִיא", "הֵם", "הֵמָּה", "הֵנָּה"}
NEAR_HBO = {unicodedata.normalize("NFC", x) for x in NEAR_HBO}           # MACULA orders dagesh / vowel otherwise
REMOTE_HBO = {unicodedata.normalize("NFC", x) for x in REMOTE_HBO}
COLS = ["corpus", "clause_key", "head", "referent", "basis", "status", "distance", "definite", "proximity", "animacy"]
ANIM_ENT = {"person": "person", "group": "person", "deity": "deity", "fauna": "animal", "flora": "thing", "realia": "thing",
            "place": "place", "keyterm": ""}
ANIM_HBO = {"001001001": "deity", "001001002": "animal", "001001003": "person"}        # SDBH domain prefix
ANIM_GRC = {"009": "person", "010": "person", "011": "person", "012": "deity", "004": "animal"}   # Louw-Nida domain


def main() -> int:
    m = sqlite3.connect(f"file:{MSPINE}?mode=ro", uri=True)
    lemma, strong, cls = {}, {}, {}
    for k, lem, st, cl in m.execute("select key, lemma, strong, class from macula_words"):
        lemma[k], strong[k], cls[k] = lem or "", st or "", cl or ""
    ref = collections.defaultdict(list)
    for s, t, kind in m.execute("select src_key, tgt_key, kind from refs order by rowid"):
        ref[s].append(t)
    ent = {}
    ent_words = collections.defaultdict(list)                  # (corpus, book, chapter) -> [(word, entity)]
    for r in csv.DictReader(open(DATA / "entities/entity_words.tsv", encoding="utf-8"), delimiter="\t"):
        if r["kind"] in ("explicit", "pronominal", "subject"):
            ent.setdefault(r["word"], r["entity"])           # the full ACAI id: Saul.2 (the king) is not Saul (an alias of Paul)
    hb = {}                                                     # Hebrew word -> (type, state, word number)
    art_words, sfx_words = set(), set()
    for k, c, typ, st, lem, morph in sqlite3.connect(f"file:{LOWFAT}?mode=ro", uri=True).execute(
            "select key, class, type, state, lemma, morph from lowfat_words"):
        hb[k] = (typ or "", st or "", unicodedata.normalize("NFC", lem or ""))
        if c == "art" or (morph or "") == "Rd" or st == "determined":       # Rd: a preposition with the article in it (בַּ, לַ)
            art_words.add(k[:11])
        if c == "pron" and typ == "pronominal":
            sfx_words.add(k[:11])

    def resolve(k):
        """referent id and basis for a head word"""
        if k in ent:
            return ent[k], "acai"
        seen, cur = {k}, k
        for _ in range(4):
            nxt = next((t for t in ref.get(cur, []) if t not in seen), None)
            if not nxt:
                break
            if nxt in ent:
                return ent[nxt], "ref"
            seen.add(nxt)
            cur = nxt
        if cur != k and cls.get(cur) != "pron":
            return "lemma:" + (strong.get(cur) or lemma.get(cur, "")), "ref"
        if cls.get(cur) == "pron":                             # a pronoun with no referent: no chain on the pronoun's own lemma
            return "unresolved:" + k, "unresolved"
        return "lemma:" + (strong.get(k) or lemma.get(k, "")), "lemma"

    # animacy of a word from its UBS domains (SDBH / Louw-Nida): the first domain that says person / deity / animal
    dom_anim = {}
    for r in csv.DictReader(open(DATA / "word-senses-ubs/words.tsv", encoding="utf-8"), delimiter="\t"):
        if r["key"] in dom_anim:
            continue
        for d in r["domains"].split(";"):
            a = ANIM_HBO.get(d[:9]) if r["lang"] == "hbo" else ANIM_GRC.get(d[:3])
            if a:
                dom_anim[r["key"]] = a
                break

    pers = dict(m.execute("select key, person from macula_words"))
    lemma_keys_with_dom = set()
    for r in csv.DictReader(open(DATA / "word-senses-ubs/words.tsv", encoding="utf-8"), delimiter="\t"):
        if r["domains"]:
            lemma_keys_with_dom.add(r["key"])

    def animacy(w, rid):
        """person | deity | animal | place | thing | '' (unknown): the referent's type, else the head's domain"""
        kind = rid.split(":")[0]
        if kind in ANIM_ENT and ANIM_ENT[kind]:
            return ANIM_ENT[kind]
        if w in dom_anim:
            return dom_anim[w]
        p_ = cls.get(w)
        if p_ == "pron":                                       # I / you are people (or God); a third person stays unknown
            return "person" if pers.get(w) in ("first", "second") else ""
        return "thing" if p_ == "noun" and w in lemma_keys_with_dom else ""

    rows = [r for r in csv.DictReader(open(DATA / "arg-roles/roles.tsv", encoding="utf-8"), delimiter="\t")]
    # clause order per corpus and the clauses of every word (for ACAI mentions outside the heads)
    order, wclause = {}, {}
    for corpus, sub, field in (("hbo", "clause-layout", "clause_key"), ("grc", "nt-clause-layout", "first")):
        i = 0
        for f in sorted((DATA / sub / "clauses").glob("*/*.jsonl")):
            for line in open(f, encoding="utf-8"):
                r = json.loads(line)
                ck = r[field]
                if (corpus, ck) not in order:
                    order[(corpus, ck)] = i
                    i += 1
                for w in r["words"]:
                    wclause.setdefault(w, ck)
    # mention stream: heads, plus ACAI-linked words (verbs with an implied subject, pronouns not heading a constituent)
    events = collections.defaultdict(list)     # (corpus, book, chapter) -> [(clause index, word, referent, is_head, row)]
    head_rows = {}
    for r in rows:
        h = r["head"]
        if not h:
            continue
        corpus = r["corpus"]
        rid, basis = resolve(h)
        chap = (corpus, h[:2] if corpus == "hbo" else h[:2], int(h[2:5]))
        idx = order.get((corpus, r["clause_key"]), 0)
        events[chap].append((idx, h, rid, True, r))
        head_rows[h] = (rid, basis)
    for w, e in ent.items():
        if w in head_rows or w not in wclause:
            continue
        corpus = "hbo" if len(w) == 12 else "grc"
        events[(corpus, w[:2], int(w[2:5]))].append((order.get((corpus, wclause[w]), 0), w, e, False, None))
    out, st = [], collections.Counter()
    for chap, evs in events.items():
        evs.sort(key=lambda e: (e[0], e[1]))
        last = {}
        for idx, w, rid, is_head, r in evs:
            if is_head:
                prev = last.get(rid)
                if rid.startswith("unresolved:"):
                    status, dist = "unresolved", ""
                elif prev is None:
                    status, dist = ("known" if rid in GOD else "new"), ""
                else:
                    dist = idx - prev
                    status = "given" if dist <= WINDOW else "restaged"
                corpus = r["corpus"]
                ws = r["words"].split()
                definite, prox = "", ""
                if corpus == "hbo":
                    typ, state, lem = hb.get(w, ("", "", ""))
                    for x in ws:
                        xl = hb.get(x, ("", "", ""))[2]
                        if xl in NEAR_HBO and hb.get(x, ("", "", ""))[0] == "demonstrative":
                            prox = "near"
                        elif xl in REMOTE_HBO and x[:11] in art_words:
                            prox = "remote"
                    definite = ("demonstrative" if prox else "pronoun" if cls.get(w) == "pron" else
                                "article" if w[:11] in art_words else "proper" if typ == "proper" else
                                "suffix" if w[:11] in sfx_words else "construct" if state == "construct" else "")
                else:
                    lems = {lemma.get(x) for x in ws}
                    prox = "near" if "οὗτος" in lems else "remote" if "ἐκεῖνος" in lems else ""
                    definite = ("demonstrative" if prox else "pronoun" if cls.get(w) == "pron" else
                                "article" if "ὁ" in lems else "proper" if rid.split(":")[0] in ("person", "place", "deity") and
                                head_rows[w][1] == "acai" else "")
                an = animacy(w, rid)
                out.append([corpus, r["clause_key"], w, rid, head_rows[w][1], status, str(dist), definite, prox, an])
                st[(corpus, "animacy:" + (an or "-"))] += 1
                st[(corpus, "status:" + status)] += 1
                st[(corpus, "basis:" + head_rows[w][1])] += 1
                st[(corpus, "definite:" + (definite or "-"))] += 1
                st[(corpus, f"{status}|{definite or '-'}")] += 1
                if prox:
                    st[(corpus, "proximity:" + prox)] += 1
            last[rid] = idx
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "np.tsv", "w", encoding="utf-8") as f:
        f.write("\t".join(COLS) + "\n")
        f.writelines("\t".join(r) + "\n" for r in out)
    lines = ["# Reference status: checks", "", f"Noun phrases: {len(out):,}. Episode = chapter, window {WINDOW} clauses.", "",
             "| corpus | count | value |", "|---|---|---|"]
    lines += [f"| {c} | {n:,} | {k} |" for (c, k), n in sorted(st.items(), key=lambda x: (x[0][0], x[0][1]))]
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = subprocess.run(["git", "log", "-1", "--format=%h"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    (OUT / "build.json").write_text(json.dumps({"schema": 1, "built": datetime.date.today().isoformat(), "code": code,
                                                "window": WINDOW, "episode": "chapter",
                                                "not_read": ["BHSA", "TBTA", "English text"]}, indent=1) + "\n")
    for c in ("hbo", "grc"):
        print(c, {k: n for (cc, k), n in sorted(st.items()) if cc == c and "|" not in k})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
