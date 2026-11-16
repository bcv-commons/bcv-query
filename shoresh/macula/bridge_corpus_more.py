"""Three more layers in the bridge corpus: word-parts, hebrew-phrase-types-model and passage-facts.

word-parts (CC BY 4.0)   on Greek NT words: wp_cut (the word cut into its parts, `ἐ|γέννησ|εν`), wp_group (the inflection group),
                         wp_flags, wp_kinds (the parts' kinds in order, `augment|stem|ending`) and wp_part_features (each part's
                         features in order, `|`-joined); on Hebrew word parts: wp_kind and wp_features.
hebrew-phrase-types-model (CC BY 4.0, model-made)
                         the type of a Hebrew prepositional phrase, on the argument-roles phrase with the same first and last word:
                         m_pt_label, m_pt_group, m_pt_basis (jev / opus / jev+opus), m_pt_confidence (Jev's, 0 to 100). A phrase of
                         the layer with no such phrase gets a phrase unit of its own (counted), with no ar_ features.
passage-facts (CC BY-SA 4.0)
                         a `fact` unit per fact, over its words from `first` to `last`: pf_id, pf_kind, pf_value, pf_basis, pf_precision,
                         pf_src (the sources, `+`-joined), pf_lic, and the plain values of a fact (level, quote, found, speaker,
                         speaker_by, speaker_id, speaker_name, divine, tn_id) under pf_; edges pf_of, pf_verb and pf_parent between facts.
                         Word lists (at, lines, the references) are left to the release.
"""
from __future__ import annotations

import collections
import json

from macula.build_bridge_corpus import folder, pins, table, value

FACT_VALUES = ("level", "quote", "found", "speaker", "speaker_by", "speaker_id", "speaker_name", "divine", "tn_id")


def add_word_parts(c) -> None:
    st = collections.Counter()
    parts = collections.defaultdict(list)
    for r in table("word-parts", "data/src_part_grc.parquet"):
        parts[r["key"]].append((r["n"], r["kind"], r["features"] or ""))
    for r in table("word-parts", "data/words_grc.parquet"):
        s = c.slot.get(r["key"])
        st["Greek words"] += 1
        if s is None:
            continue
        st["Greek words placed"] += 1
        for col in ("cut", "group", "flags"):
            c.set(f"wp_{col}", s, r[col], "word-parts")
        ps = sorted(parts.get(r["key"], ()))
        if ps:
            c.set("wp_kinds", s, "|".join(k for _, k, _ in ps), "word-parts")
            if any(f for *_, f in ps):
                c.set("wp_part_features", s, "|".join(f for *_, f in ps), "word-parts")
    for r in table("word-parts", "data/src_part_hbo.parquet"):
        s = c.slot.get(r["token"])
        st["Hebrew parts"] += 1
        if s is None:
            continue
        st["Hebrew parts placed"] += 1
        c.set("wp_kind", s, r["kind"], "word-parts")
        c.set("wp_features", s, r["features"], "word-parts")
    c.report["layers"]["word-parts"] = dict(st)


def add_phrase_types(c) -> None:
    st = collections.Counter()
    key_of = {s: k for k, s in c.slot.items() if len(k) == 12 and k[:2] < "40"}
    span = {}
    for i, sl in enumerate(c.nodes["phrase"]):
        if min(sl) in key_of:
            span.setdefault((key_of[min(sl)], key_of[max(sl)]), ("phrase", i))
    for r in table("hebrew-phrase-types-model", "data/hebrew_phrase_types.parquet"):
        st["rows"] += 1
        first, last = r["phrase_key"].split(":")[0].split("-")
        h = span.get((first, last))
        if h is None and first in c.slot and last in c.slot:
            h = c.node("phrase", range(c.slot[first], c.slot[last] + 1))
            st["phrases of their own"] += 1
        if h is None:
            st["not placed"] += 1
            continue
        st["on an argument-roles phrase"] += (first, last) in span
        for col, name in (("label", "m_pt_label"), ("group", "m_pt_group"), ("basis", "m_pt_basis")):
            c.set(name, h, r[col], "hebrew-phrase-types-model")
        if r["jev_confidence"] is not None:
            c.set("m_pt_confidence", h, value(r["jev_confidence"]), "hebrew-phrase-types-model")
    c.report["layers"]["hebrew-phrase-types-model"] = dict(st)


def add_passage_facts(c) -> None:
    st = collections.Counter()
    root = folder("passage-facts", pins()["layers"]["passage-facts"])
    rows = [json.loads(line) for f in sorted((root / "data").glob("*.jsonl")) for line in f.read_text(encoding="utf-8").splitlines()]
    for r in rows:
        st["facts"] += 1
        a, b = c.slot.get(r["first"]), c.slot.get(r["last"])
        if a is None or b is None or b < a:
            st["not placed"] += 1
            continue
        h = c.node("fact", range(a, b + 1), r["id"])
        for col in ("id", "kind", "value", "basis", "precision", "lic") + FACT_VALUES:
            if col in r:
                c.set(f"pf_{col}", h, value(r[col]), "passage-facts")
        c.set("pf_src", h, "+".join(r["src"]), "passage-facts")
        st[f"kind {r['kind']}"] += 1
    for r in rows:
        for col in ("of", "verb", "parent"):
            if r.get(col):
                st[f"pf_{col} edges"] += c.edge(f"pf_{col}", c.at["fact"].get(r["id"]), c.at["fact"].get(r[col]), None, "passage-facts")
    c.report["layers"]["passage-facts"] = dict(st)


def add_more(c) -> None:
    add_word_parts(c)
    add_phrase_types(c)
    add_passage_facts(c)
