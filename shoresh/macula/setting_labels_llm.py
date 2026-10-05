"""Better two-word labels for the settings: an LLM picks, from each setting's own characteristic Hebrew words,
the two that best tell a reader what the setting is, and the setting-fit judge compares them with the current
labels (top two by P(word|setting)).

Labels stay Hebrew words drawn from the setting itself; only the choice of words changes. The comparison
reuses the published build's setting-fit items (setting_scorecard.py) and changes only the label text, so
both arms are scored on the same tokens with the same distractor settings. Claude proposes, so the OpenAI
judge is the one that decides (a Claude judge would be partly marking its own choice).

  python -m macula.setting_labels_llm --propose            # -> data/settings/k40a05/labels_llm.json
  python -m macula.setting_labels_llm --items               # -> eval/settingfit-S40a05L.jsonl (+ shuffled control)
  python -m macula.setting_scorecard --run --judge openai   # judges the new item files
  python -m macula.setting_labels_llm --publish             # writes the labels into resources/settings/
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUILD = "k40a05"
SETTINGS = HERE / "data" / "settings"
EVAL = SETTINGS / "eval"
OUT = SETTINGS / BUILD / "labels_llm.json"
PUBLISHED = ROOT / "resources" / "settings" / "hbo_settings.tsv"
N_WORDS = 25
PROMPT = (
    "You are an expert in Biblical Hebrew. Below are topics found in the Hebrew Bible by a statistical model "
    "over its paragraphs. Each topic is a setting in which words are used (a ritual, legal, military, "
    "domestic, royal, prophetic or wisdom setting and so on). For each topic you get its most characteristic "
    "Hebrew words with an English gloss, the word's weight in the topic, and the share of the word's "
    "occurrences that fall in this topic (high = the word is typical of this topic and rare elsewhere).\n"
    "For each topic, choose exactly TWO of its listed words that together best tell a reader which setting "
    "this is, so that a reader seeing a word in a verse could recognise the setting from these two words. "
    "Prefer concrete, recognisable words that are typical of the topic over very general words, and avoid "
    "two words that say the same thing. Use only words from the topic's own list.\n"
    "Reply with JSON only: a list of objects {\"topic\": <id>, \"words\": [<strong>, <strong>] (the two "
    "words' \"strong\" numbers), "
    "\"setting\": <a short English description of the setting, for our notes>}.\n\nTopics:\n")


def _gloss(strong: str) -> str:
    sys.path.insert(0, str(HERE.parent))
    import data
    return (data.gloss_of(strong) or {}).get("gloss") or ""


def topic_words() -> list[dict]:
    """Per setting: its top N_WORDS words with weight and the share of the word's occurrences in this setting."""
    by_lex, tot = collections.Counter(), collections.Counter()
    with (SETTINGS / BUILD / "occurrences.tsv").open(encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) > 7 and p[7] != "word":
                continue
            by_lex[(p[4], p[5])] += 1
            tot[p[4]] += 1
    out = []
    for t in json.loads((SETTINGS / BUILD / "topics.json").read_text(encoding="utf-8")):
        ws = []
        for w in t["words"][:N_WORDS]:
            lx = w.get("lexeme") or f"hbo:{int(w['strong'][1:]):04d}"
            share = by_lex[(lx, t["topic"])] / tot[lx] if tot[lx] else 0.0
            ws.append({"lemma": w["lemma"], "strong": w["strong"], "gloss": _gloss(w["strong"]),
                       "weight": round(w.get("p", 0.0), 4), "share": round(share, 2)})
        out.append({"topic": t["topic"], "words": ws})
    return out


def propose(model: str) -> None:
    import os
    os.environ["JUDGE_CLAUDE_CLI_MODEL"] = model
    from macula import usability_judge as uj
    uj.MODELS["claude-cli"] = model
    topics = topic_words()
    prompt = PROMPT + json.dumps(topics, ensure_ascii=False, indent=1)
    text, n_in, n_out = uj.call_judge("claude-cli", prompt)
    got = json.loads(re.search(r"\[.*\]", text, re.S).group(0))
    lemmas = {t["topic"]: {w["strong"]: w for w in t["words"]} for t in topics}
    res, bad = {}, []
    for r in got:
        tid, ws = r.get("topic"), r.get("words") or []
        picked = [lemmas.get(tid, {}).get(w) for w in ws[:2]]
        if len(picked) != 2 or None in picked:
            bad.append(tid)
            continue
        res[tid] = {"words": [{"lemma": w["lemma"], "strong": w["strong"], "gloss": w["gloss"]} for w in picked],
                    "setting": r.get("setting", "")}
    for t in topics:                       # anything unusable keeps its current label
        if t["topic"] not in res:
            res[t["topic"]] = {"words": [{k: w[k] for k in ("lemma", "strong", "gloss")} for w in t["words"][:2]],
                               "setting": "", "kept": True}
    (OUT.parent / "labels_llm_raw.txt").write_text(text, encoding="utf-8")
    OUT.write_text(json.dumps({"model": model, "tokens_in": n_in, "tokens_out": n_out, "labels": res},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    changed = sum(1 for t in topics if [w["lemma"] for w in res[t["topic"]]["words"]]
                  != [w["lemma"] for w in t["words"][:2]])
    print(f"[setting-labels] {len(res)} settings, {changed} relabelled, unusable answers {bad}; "
          f"tokens {n_in} in / {n_out} out -> {OUT}", file=sys.stderr)


def render(words: list[dict]) -> str:
    return ", ".join(f"{w['lemma']} · {w['gloss']}" if w["gloss"] else w["lemma"] for w in words)


def make_items() -> None:
    """Copies of the published build's setting-fit items with every option relabelled (same tokens, same
    distractor settings, same answer position); the shuffled control is relabelled the same way."""
    from macula.setting_scorecard import setting_labels
    old = setting_labels(BUILD[1:])                       # setting -> current label text
    by_text = {v: k for k, v in old.items()}
    new = {k: render(v["words"]) for k, v in json.loads(OUT.read_text(encoding="utf-8"))["labels"].items()}
    for src, name in ((f"S{BUILD[1:]}", f"S{BUILD[1:]}L"), (f"PR-S{BUILD[1:]}", f"PR-S{BUILD[1:]}L")):
        items = []
        for line in (EVAL / f"settingfit-{src}.jsonl").read_text(encoding="utf-8").splitlines():
            it = json.loads(line)
            it["options"] = [new[by_text[o]] for o in it["options"]]
            it["id"] = it["id"].replace(f"-{src}-", f"-{name}-", 1)
            it["provider"] = name
            items.append(it)
        (EVAL / f"settingfit-{name}.jsonl").write_text(
            "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items), encoding="utf-8")
        print(f"[setting-labels] {len(items)} items -> settingfit-{name}.jsonl", file=sys.stderr)


def publish() -> None:
    labels = json.loads(OUT.read_text(encoding="utf-8"))["labels"]
    lines = PUBLISHED.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        p = line.split("\t")
        if line.startswith("#") or p[0] == "setting" or p[0] not in labels:
            out.append(line)
            continue
        ws = labels[p[0]]["words"]
        p[1], p[2] = ",".join(w["strong"] for w in ws), ",".join(w["lemma"] for w in ws)
        out.append("\t".join(p))
    PUBLISHED.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"[setting-labels] labels written -> {PUBLISHED}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--propose", action="store_true")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--items", action="store_true")
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args()
    if a.propose:
        propose(a.model)
    if a.items:
        make_items()
    if a.publish:
        publish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
