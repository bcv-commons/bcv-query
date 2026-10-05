"""Topic words in any language → a Nave's topic, through Strong's numbers (no LLM, no translation).

Nave's topics are English ("FAITH", "FORGIVENESS"), so "¿Qué dice la Biblia sobre la fe?" found no topic, and
the prefix fallback could match the wrong one ("amor" → AMORITES). Here the topic phrase alone (not the whole
question, so frame words such as "dice" stay out) goes through the multilingual concept expansion to Strong's
codes (fe → G4102), and then to a topic:

1. a topic named by a code's English gloss: G4102 "faith" → FAITH, G0859 "forgiveness" → FORGIVENESS, G5485
   "grace" → GRACE-OF-GOD (a topic whose id starts with the gloss); when codes name different topics
   (תִּקְוָה is "hope" and "cord"), the verse statistics below choose among them;
2. else the topic most specific to the codes in resources/topic_strongs.tsv (Strong's attested in each
   topic's verses): Σ share of the code's topic uses × √(concentration in the topic), kept only when it is
   clearly ahead of the runner-up. The statistics never overrule a gloss-named topic: tried, they turned
   perdón into SIN and humildad into LONGSUFFERING.

Checked on 20 concepts × Spanish, French, German, Portuguese against the English question's topic: 15-18 of
20 agree; most of the rest are near topics (pride → ARROGANCE, money → SILVER).
"""
from __future__ import annotations

import collections
import csv
import re
from functools import lru_cache

from resource_paths import resource_path

MIN_COUNT = 2          # topic_strongs rows attested in fewer verses are incidental
MARGIN = 1.5           # the statistical pick must beat the runner-up by this factor


@lru_cache(maxsize=1)
def _topic_strongs() -> tuple[dict, collections.Counter, collections.Counter]:
    """(strong -> {topic: verses}, verses per topic, verses per strong)."""
    by_strong: dict = collections.defaultdict(dict)
    size, total = collections.Counter(), collections.Counter()
    path = resource_path("topic_strongs.tsv")
    if not path.exists():
        return by_strong, size, total
    with path.open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            t, s, n = line.rstrip("\n").split("\t")
            n = int(n)
            if n < MIN_COUNT:
                continue
            by_strong[s][t] = n
            size[t] += n
            total[s] += n
    return by_strong, size, total


@lru_cache(maxsize=1)
def _english_glosses() -> dict[str, str]:
    out: dict[str, str] = {}
    path = resource_path("strongs_gloss.tsv")
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if row.get("lang") == "eng" and row.get("gloss"):
                out[row["strong"]] = row["gloss"]
    return out


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def topic_codes(topic_query: str, lang: str) -> list[str]:
    """Strong's codes for the topic phrase alone (multilingual concept expansion)."""
    from query.concept_expand import _normalize_code, expand_concepts
    # more codes per word than query expansion uses (2): esperanza's first two are Hebrew miqveh / tiqvah
    # ("Kue", "cord"); Greek elpis "hope" comes third
    return [_normalize_code(t.split(":", 1)[1])
            for t in expand_concepts(topic_query, [], max_per_word=4, max_total=6, lang=lang)
            if t.startswith("strongs:")]


def _stat_scores(codes: list[str]) -> collections.Counter:
    by_strong, size, total = _topic_strongs()
    sc: collections.Counter = collections.Counter()
    for c in codes:
        for t, n in by_strong.get(c, {}).items():
            sc[t] += (n / total[c]) * (n / size[t]) ** 0.5
    return sc


def map_topic(topic_query: str, lang: str, topic_ids: set[str]) -> str | None:
    """The Nave's topic id for a topic phrase in any language, or None."""
    codes = topic_codes(topic_query, lang)
    if not codes:
        return None
    gloss = _english_glosses()
    sc = _stat_scores(codes)
    # 1. topics named by a code's English gloss (exact name, else an id starting with it); several codes can
    #    name different topics (תִּקְוָה is "hope" and "cord"), so the statistics choose among them
    named: list[str] = []
    for c in codes:
        g = _slug(gloss.get(c, ""))
        if g in topic_ids:
            named.append(g)
    if not named:
        for c in codes:
            g = _slug(gloss.get(c, ""))
            named += sorted(t for t in topic_ids if g and t.startswith(g + "-"))[:1]
    stat = [(t, v) for t, v in sc.most_common() if t in topic_ids]
    if named:                  # the gloss decides; verse statistics are too noisy to overrule it
        return max(named, key=lambda t: sc.get(t, 0.0))
    # 2. the topic most specific to the codes, if clearly ahead
    if not stat:
        return None
    if len(stat) == 1 or stat[0][1] >= MARGIN * stat[1][1]:
        return stat[0][0]
    return None
