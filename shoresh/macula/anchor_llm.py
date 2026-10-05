"""LLM fallback for anchoring commentary headings to the verse word they explain.

The builders (build_metzudat_zion --explanations, build_malbim --explanations, build_mahberet_menahem --senses)
anchor deterministically first (_anchor: consonants, prefixes, lemmas, full spelling). For the few percent
that still fail (abbreviated or paraphrased quotes, spelling variants), a builder calls fallback(): it returns
the cached LLM answer if there is one and records the miss otherwise, so builds stay deterministic and offline.
judge() asks an LLM, for each recorded miss, which word of the cited verse the heading quotes (or none),
and keeps an answer only if the chosen word shares enough consonants with the heading (plausible()).

  python -m macula.build_metzudat_zion --explanations      # (etc.) records misses
  python -m macula.anchor_llm --judge                      # asks, checks, caches -> resources/anchoring/
  python -m macula.build_metzudat_zion --explanations      # rerun: cached anchors are used
"""
from __future__ import annotations

import argparse
import atexit
import collections
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine.common import to_modern_form  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine.db"
CACHE = ROOT / "resources" / "anchoring" / "llm_anchors.tsv"
MISSES = HERE / "data" / "anchor_misses"
PREFIXES = "והבכלמש"
PROMPT = (
    "You are an expert in Biblical Hebrew and in the classical Hebrew commentaries. Each item below gives a "
    "verse of the Hebrew Bible as numbered words and the words a commentary quotes from that verse (its "
    "heading, sometimes abbreviated, spelled with extra vowel letters, or with a prefix added or dropped), with "
    "the start of the comment for context. For every item, give the number of the verse word the quote refers "
    "to (the word being explained; for a multi-word quote, its first word). If the quoted word is not in this "
    "verse, answer null.\n"
    "Reply with JSON only, no prose: a list of objects {\"id\": <item id>, \"word\": <number or null>}.\n\n"
    "Items:\n")

_cache: dict | None = None
_misses: dict[str, dict] = {}


def _key(source: str, book: str, ch: int, vs: int, head: str) -> str:
    return f"{source}|{book} {ch}:{vs}|{to_modern_form(head, 'hbo')}"


def _load() -> dict:
    global _cache
    if _cache is None:
        _cache = {}
        if CACHE.exists():
            for line in CACHE.read_text(encoding="utf-8").splitlines():
                if line.startswith("#") or line.startswith("source\t"):
                    continue
                source, ref, head, word_key, *_ = line.split("\t")
                _cache[f"{source}|{ref}|{head}"] = word_key
    return _cache


def fallback(source: str, book: str, ch: int, vs: int, head: str, units: list[dict], context: str = "") -> dict | None:
    """The cached LLM anchor for this heading in this verse, if any; otherwise records the miss."""
    if not head or not units:
        return None
    k = _key(source, book, ch, vs, head)
    hit = _load().get(k)
    if hit is not None:
        return next((u for u in units if u["key"] == hit), None)
    _misses[k] = {"id": k, "source": source, "book": book, "chapter": ch, "verse": vs, "head": head,
                  "context": re.sub(r"\s+", " ", context)[:160]}
    return None


@atexit.register
def _save_misses() -> None:
    if not _misses:
        return
    MISSES.mkdir(parents=True, exist_ok=True)
    by_source = collections.defaultdict(list)
    for m in _misses.values():
        by_source[m["source"]].append(m)
    for source, ms in by_source.items():
        (MISSES / f"{source}.jsonl").write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in ms),
                                                encoding="utf-8")
    print(f"[anchor-llm] {len(_misses)} uncached misses recorded -> {MISSES}", file=sys.stderr)


def _letters(w: str) -> str:
    return re.sub(r"[וי]", "", to_modern_form(w, "hbo"))


def _lcs(a: str, b: str) -> int:
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0]
        for j, cb in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if ca == cb else max(prev[j], cur[-1]))
        prev = cur
    return prev[-1]


def plausible(head: str, surface: str) -> bool:
    """The chosen word must share, in order, at least two consonants and 60% of the quote's consonants
    (vowel letters ו/י ignored, up to two prefix letters of the quote optional)."""
    h, w = _letters(head), _letters(surface)
    if len(h) < 2:
        return False
    best = _lcs(h, w)
    for _ in range(2):
        if len(h) > 2 and h[0] in PREFIXES:
            h = h[1:]
            best = max(best, _lcs(h, w))
    return best >= 2 and best >= 0.6 * len(h)


def _verse_words(sp, book: str, ch: int, vs: int) -> list[tuple[str, str]]:
    """(word key, pointed surface) per whole word, as _verse_word_units builds them."""
    words: "collections.OrderedDict[str, str]" = collections.OrderedDict()
    for key, surface in sp.execute("SELECT key, surface FROM spine_words WHERE book=? AND chapter=? AND verse=? "
                                   "AND lexeme LIKE 'hbo:%' ORDER BY idx", (book, ch, vs)):
        words[key[:-1]] = words.get(key[:-1], "") + (surface or "")
    return list(words.items())


def judge(judge_name: str, batch_size: int = 25) -> None:
    import concurrent.futures
    from macula import usability_judge as uj
    uj._load_env()
    have = _load()
    todo = []
    for f in sorted(MISSES.glob("*.jsonl")):
        todo += [m for m in map(json.loads, f.read_text(encoding="utf-8").splitlines()) if m["id"] not in have]
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    words = {m["id"]: _verse_words(sp, m["book"], m["chapter"], m["verse"]) for m in todo}
    todo = [m for m in todo if words[m["id"]]]
    print(f"[anchor-llm] {len(todo)} misses to judge with {judge_name}", file=sys.stderr)

    def call(batch):
        payload = [{"id": m["id"], "verse": {str(i + 1): w for i, (_k, w) in enumerate(words[m["id"]])},
                    "quote": m["head"], "comment": m["context"]} for m in batch]
        text, _i, _o = uj.call_judge(judge_name, PROMPT + json.dumps(payload, ensure_ascii=False, indent=1))
        mt = re.search(r"\[.*\]", text, re.S)
        try:
            got = json.loads(mt.group(0)) if mt else []
        except json.JSONDecodeError:
            got = []
        return batch, {g.get("id"): g.get("word") for g in got if isinstance(g, dict)}

    st = collections.Counter()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    new = not CACHE.exists()
    batches = [todo[i:i + batch_size] for i in range(0, len(todo), batch_size)]
    with CACHE.open("a", encoding="utf-8") as fh, \
            concurrent.futures.ThreadPoolExecutor(uj.WORKERS_FOR.get(judge_name, uj.WORKERS)) as pool:
        if new:
            fh.write("# LLM fallback anchors for commentary headings the deterministic anchoring missed "
                     "(shoresh/macula/anchor_llm.py).\n# word_key '-' = the model found no such word in the verse, "
                     "or its choice failed the consonant check. CC0.\n")
            fh.write("source\tref\thead\tword_key\tword\tjudge\n")
        for batch, got in pool.map(call, batches):
            for m in batch:
                if m["id"] not in got:
                    st["no_answer"] += 1           # not cached: asked again next time
                    continue
                ans, ws = got[m["id"]], words[m["id"]]
                wk, w = "-", ""
                if isinstance(ans, int) and 1 <= ans <= len(ws):
                    if plausible(m["head"], ws[ans - 1][1]):
                        wk, w = ws[ans - 1]
                        st["anchored"] += 1
                    else:
                        st["implausible"] += 1
                else:
                    st["none"] += 1
                source, ref, head = m["id"].split("|")
                fh.write("\t".join((source, ref, head, wk, w, uj.MODELS[judge_name])) + "\n")
            fh.flush()
    print(f"[anchor-llm] {dict(st)} -> {CACHE}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--with", dest="judge_name", default="claude-cli")
    a = ap.parse_args()
    if a.judge:
        judge(a.judge_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
