"""The speaker of a Hebrew Bible quotation, named from the Hebrew text: the subject of the verb that introduces it.

The speaker layer's quotation spans come from Clear's speaker data and the clause layout; Clear's label for who speaks is in English
and is not shipped. The name comes from MACULA Hebrew (WLC lowfat, CC BY 4.0):
- The inquit: the verb of the nearest clause above the quotation's first word in the tree, outside the quotation; else the nearest
  verb of saying (אָמַר, דִּבֶּר) in the 20 words before it (the usual case: וַיֹּאמֶר … stands as a clause of its own).
- Its subject: MACULA's subject links (`subjref`, all of them: וַתַּעַן רָחֵל וְלֵאָה names both), else the subject (role s) of the
  inquit's clause. Where there is none, a נְאֻם in the quotation's first words names its speaker (חַי־אָנִי נְאֻם־הַמֶּלֶךְ, Jer 46:18).
  A subject that is a pronoun or only in the verb is not named: MACULA's participant references and a verb's link to an earlier
  verb were tried and agreed with the speaker data's speaker in about half the cases and a third, against three in four for a
  written subject, so an empty name is left rather than a doubtful one.
- The name is the lemma of that noun (or adjective or numeral used as one) with the nouns it stands in a construct chain with: מַלְאַךְ יְהוָה, מֶלֶךְ אַשּׁוּר,
  בְּנֵי יִשְׂרָאֵל; where the subject is someone's word or oracle (וַיְהִי דְבַר־יְהוָה אֵלַי לֵאמֹר, נְאֻם יְהוָה), the one whose
  word it is: יְהוָה. Several subjects are separated by commas.

    from macula import hebrew_speakers
    find = hebrew_speakers.Finder(con, spine_con)
    find(first_key, last_key)       # -> {"names": [...], "refs": [...], "inquit": key, "how": "tree" | "near" | "oracle" | None}
"""
from __future__ import annotations

import bisect
import collections
import glob
import hashlib
import re
import sqlite3
from pathlib import Path

from macula import discourse_rules as D

HERE = Path(__file__).resolve().parent
LOWFAT = HERE / ".lowfat-src" / "WLC" / "lowfat"
SAYING = D.SAY | {"1696"}                         # אָמַר and דִּבֶּר (וַיְדַבֵּר מֹשֶׁה … אֶת־דִּבְרֵי הַשִּׁירָה, Deut 31:30)
ORACLE = "5002"                                   # נְאֻם
SPOKEN_BY = D.WORD_NOUN | {ORACLE}               # דְּבַר X, נְאֻם X: the speaker is X, whose word or oracle it is
NAMING = ("noun", "adj", "num")                  # word classes a speaker is named by (הַזָּקֵן, הַשֵּׁנִי as well as nouns)


def lowfat_state() -> tuple[dict[str, str], str]:
    """Word key -> its state ("construct", "absolute", …) from the lowfat files; and the SHA-256 of the files read."""
    out, h = {}, hashlib.sha256()
    files = sorted(glob.glob(str(LOWFAT / "*.xml")))
    if not files:
        raise SystemExit(f"no MACULA Hebrew lowfat files in {LOWFAT}: run python -m macula.build_trees once (it downloads them)")
    for f in files:
        data = Path(f).read_bytes()
        h.update(data)
        for m in re.finditer(r"<w\b([^>]*)>", data.decode("utf-8")):
            at = m.group(1)
            k, s = re.search(r'xml:id="o(\d+)"', at), re.search(r'\bstate="([^"]*)"', at)
            if k and s:
                out[k.group(1)] = s.group(1)
    return out, h.hexdigest()


class Finder:
    def __init__(self, con: sqlite3.Connection, spine: sqlite3.Connection):
        self.state, self.sha = lowfat_state()
        q = "SELECT key, class, lemma, strong, cl, role, parent FROM words WHERE corpus='hbo' AND inserted=0"
        self.tok = {r[0]: dict(zip(("key", "class", "lemma", "strong", "cl", "role", "parent"), r)) for r in con.execute(q)}
        self.keys = sorted(self.tok)
        self.pos = {k: i for i, k in enumerate(self.keys)}
        self.parent = dict(con.execute("SELECT id, parent FROM nodes WHERE corpus='hbo'").fetchall())
        self.nrole = dict(con.execute("SELECT id, role FROM nodes WHERE corpus='hbo'").fetchall())
        self.by_cl = collections.defaultdict(list)
        for k, t in self.tok.items():
            self.by_cl[t["cl"]].append(k)
        self.refs: dict[str, dict[str, list[str]]] = collections.defaultdict(lambda: collections.defaultdict(list))
        for s, t, kind in spine.execute("SELECT src_key, tgt_key, kind FROM refs ORDER BY rowid"):
            if s in self.tok:
                self.refs[kind][s].append(t)

    def _noun(self, k: str) -> str | None:          # the word itself, where it names (a pronoun "הוּא", "אַתֶּם" does not)
        return k if k in self.tok and self.tok[k]["class"] in NAMING else None

    def _chain(self, k: str) -> list[str]:          # the construct chain the noun stands in, in text order
        i = self.pos[k]
        a = b = i
        while a > 0 and self._is_noun(a - 1) and self.state.get(self.keys[a - 1]) == "construct":
            a -= 1
        while self.state.get(self.keys[b]) == "construct":
            j = b + 1
            while j < len(self.keys) and self.tok[self.keys[j]]["class"] in ("art",) :
                j += 1
            if j < len(self.keys) and self._is_noun(j):
                b = j
            else:
                break
        return [self.keys[x] for x in range(a, b + 1) if self._is_noun(x)]

    def _is_noun(self, i: int) -> bool:
        return self.tok[self.keys[i]]["class"] in NAMING

    def _subject(self, v: str) -> list[str]:
        out = []
        for t in self.refs["subjref"].get(v, []):
            n = self._noun(t)
            if n and n not in out:
                out.append(n)
        if out:
            return out
        cl = self.tok[v]["cl"]
        for k in sorted(self.by_cl[cl]):
            if k == v:
                continue
            n, above = self.tok[k]["parent"], []
            while n is not None and n != cl:
                above.append(self.nrole.get(n))
                n = self.parent.get(n)
            if self.tok[k]["role"] == "s" or "s" in above:
                n = self._noun(k)
                if n:
                    return [n]
        return []

    def _inquit(self, first: str, last: str) -> tuple[str | None, str | None]:
        n = self.tok[first]["cl"] if first in self.tok else None
        while n is not None:
            n = self.parent.get(n)
            for k in self.by_cl.get(n, []):
                if not (first <= k <= last) and self.tok[k]["class"] == "verb":
                    return k, "tree"
        i = bisect.bisect_left(self.keys, first)
        for k in reversed(self.keys[max(0, i - 20):i]):
            if self.tok[k]["class"] == "verb" and D._strong(self.tok[k]) in SAYING:
                return k, "near"
        return None, None

    def _oracle(self, first: str, last: str) -> list[str]:     # נְאֻם X in the quotation's first ten words: X
        i = self.pos.get(first)
        if i is None:
            return []
        for k in self.keys[i:i + 10]:
            if k > last:
                break
            if D._strong(self.tok[k]) == ORACLE and self.state.get(k) == "construct":
                j = self.pos[k] + 1
                while j < len(self.keys) and self.tok[self.keys[j]]["class"] == "art":
                    j += 1
                if j < len(self.keys) and self._is_noun(j):
                    return [self.keys[j]]
        return []

    def __call__(self, first: str, last: str) -> dict:
        v, how = self._inquit(first, last)
        subj = self._subject(v) if v else []
        if not subj:
            subj = self._oracle(first, last)
            how = "oracle" if subj else how
        names, refs = [], []
        for n in subj:
            chain = self._chain(n)
            while len(chain) > 1 and D._strong(self.tok[chain[0]]) in SPOKEN_BY:
                chain = chain[1:]
            if any(c in refs for c in chain):
                continue
            refs += chain
            names.append(" ".join(D._n(self.tok[c]["lemma"]) for c in chain))
        return {"names": names, "refs": refs, "inquit": v, "how": how}
