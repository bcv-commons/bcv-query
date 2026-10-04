"""Setting axis: the topical setting a Hebrew word is used in, induced from the Hebrew text itself.

Stand-in for SDBH's contextual domains (`ctx`: "Sacrifices and Offerings", "Warfare", "Agriculture"...),
which UBS has not released openly. No English category system: settings are topics found in the text and
labelled by their own most characteristic Hebrew words.

1. Passages: the Leningrad Codex's own paragraphs (petuchot / setumot, resources/parashot/). Psalms have
   no marks, so each psalm is a passage; any passage over MAX_VERSES is cut at chapter ends.
2. Topics: non-negative matrix factorisation of the passage x lexeme matrix (MACULA lexemes, content words
   only, proper names excluded; log-tf x idf weighting), K topics. Passage weights W, topic-word weights H.
3. Each occurrence gets the topic that best explains that word in its passage: argmax_k W[p,k] P(w|k).
   So מִזְבֵּחַ in a sacrifice law and מִזְבֵּחַ in a story about Baal's altar can get different settings.
   Words outside the model's vocabulary (too rare, or in more than MAX_UNIT_SHARE of passages) get their
   passage's main setting (`via` = passage instead of word).
4. Label: the topic's top lexemes (by P(w|k)), shown as "lemma · gloss" like the semantic groups.

  python -m macula.build_setting_axis --k 60 --out macula/data/settings/k60
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine.db"
PARASHOT = ROOT / "resources" / "parashot" / "parashot.tsv"
PRIOR = ROOT / "resources" / "prior_pack" / "prior_pack.parquet"
MAX_VERSES = 30
MIN_UNITS = 3          # a lexeme must occur in at least this many passages
MAX_UNIT_SHARE = 0.15  # ... and in at most this share of them (drops say/be/go-type words)
SETTING_POS = {"noun", "verb", "adj"}   # adverbs, numerals and particles carry style, not setting
# Biblical Aramaic sections: left out, or they form topics of their own by language rather than setting.
ARAMAIC = {"DAN": ((2, 4), (7, 28)), "EZR": ((4, 8), (6, 18)), "EZR2": ((7, 12), (7, 26)), "JER": ((10, 11), (10, 11))}


def is_aramaic(b: str, c: int, v: int) -> bool:
    for key, (lo, hi) in ARAMAIC.items():
        if key[:3] == b and lo <= (c, v) <= hi:
            return True
    return False


def content_lexemes() -> dict[str, dict]:
    """lexeme -> {strong, lemma} for Hebrew nouns, verbs and adjectives, names excluded (prior pack POS)."""
    out = {}
    for r in pq.read_table(PRIOR, columns=["lexeme", "strong", "lemma", "pos", "word_class"]).to_pylist():
        if r["lexeme"].startswith("hbo:") and r["pos"] in SETTING_POS:
            out[r["lexeme"]] = {"strong": r["strong"], "lemma": r["lemma"]}
    return out


def passages() -> tuple[list[dict], dict[tuple, int]]:
    """[{id, book, start, end, verses}], and (book, chapter, verse) -> passage index."""
    marks = set()
    for line in PARASHOT.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("book\t"):
            continue
        b, c, v, _ = line.split("\t")
        marks.add((b, int(c), int(v)))
    db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    order = [(b, c, v) for b, c, v in db.execute(
        "SELECT book, chapter, verse FROM spine_words WHERE lexeme LIKE 'hbo:%' "
        "GROUP BY book, chapter, verse ORDER BY MIN(rowid)")]
    raw, cur = [], []
    for i, bcv in enumerate(order):
        cur.append(bcv)
        nxt = order[i + 1] if i + 1 < len(order) else None
        end = (nxt is None or nxt[0] != bcv[0] or bcv in marks
               or (bcv[0] == "PSA" and nxt[1] != bcv[1]))
        if end:
            raw.append(cur)
            cur = []
    units = []
    for verses in raw:
        chunks = [verses]
        if len(verses) > MAX_VERSES:          # cut long passages at chapter ends
            chunks, cur = [], []
            for j, bcv in enumerate(verses):
                cur.append(bcv)
                if j + 1 < len(verses) and verses[j + 1][1] != bcv[1] and len(cur) >= 5:
                    chunks.append(cur)
                    cur = []
            if cur:
                chunks.append(cur)
        for ch in chunks:
            units.append({"id": len(units), "book": ch[0][0], "start": f"{ch[0][1]}:{ch[0][2]}",
                          "end": f"{ch[-1][1]}:{ch[-1][2]}", "verses": ch})
    where = {bcv: u["id"] for u in units for bcv in u["verses"]}
    return units, where


def nmf(X: np.ndarray, k: int, seed: int, iters: int = 400) -> tuple[np.ndarray, np.ndarray, float]:
    import torch
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    g = torch.Generator(device="cpu").manual_seed(seed)
    Xt = torch.tensor(X, dtype=torch.float32, device=dev)
    scale = math.sqrt(Xt.mean().item() / k)
    W = (torch.rand(X.shape[0], k, generator=g) * scale).to(dev)
    H = (torch.rand(k, X.shape[1], generator=g) * scale).to(dev)
    eps = 1e-10
    for _ in range(iters):
        H *= (W.T @ Xt) / (W.T @ W @ H + eps)
        W *= (Xt @ H.T) / (W @ (H @ H.T) + eps)
    err = torch.linalg.norm(Xt - W @ H).item() / torch.linalg.norm(Xt).item()
    return W.cpu().numpy(), H.cpu().numpy(), err


def build(k: int, out: Path, seeds=(13, 17, 23), alpha: float = 1.0) -> dict:
    lex = content_lexemes()
    units, where = passages()
    db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    tokens = []                              # (book, chapter, verse, idx, lexeme, unit)
    tf = collections.defaultdict(collections.Counter)
    for b, c, v, idx, lexeme in db.execute(
            "SELECT book, chapter, verse, idx, lexeme FROM spine_words WHERE lexeme LIKE 'hbo:%'"):
        if lexeme in lex and (b, c, v) in where and not is_aramaic(b, c, v):
            u = where[(b, c, v)]
            tokens.append((b, c, v, idx, lexeme, u))
            tf[u][lexeme] += 1
    df = collections.Counter(w for u in tf for w in tf[u])
    n_units = len(units)
    vocab = sorted(w for w, d in df.items() if d >= MIN_UNITS and d / n_units <= MAX_UNIT_SHARE)
    col = {w: i for i, w in enumerate(vocab)}
    X = np.zeros((n_units, len(vocab)), dtype=np.float32)
    for u, cnt in tf.items():
        for w, n in cnt.items():
            if w in col:
                X[u, col[w]] = (1 + math.log(n)) * math.log(n_units / df[w])
    best = None
    for s in seeds:
        W, H, err = nmf(X, k, s)
        print(f"  k={k} seed={s} rel.err={err:.4f}", file=sys.stderr)
        if best is None or err < best[2]:
            best = (W, H, err, s)
    W, H, err, seed = best
    P = H / (H.sum(axis=1, keepdims=True) + 1e-12)            # P(w|k)

    # topic labels: top lexemes by P(w|k)
    topics = []
    for t in range(k):
        top = np.argsort(-P[t])[:12]
        topics.append({"topic": f"s{t + 1:02d}", "words": [
            {"lexeme": vocab[i], "strong": lex[vocab[i]]["strong"], "lemma": lex[vocab[i]]["lemma"],
             "p": round(float(P[t, i]), 5)} for i in top]})

    # occurrence assignment
    assigned = []
    for b, c, v, idx, w, u in tokens:
        sc = W[u] * P[:, col[w]] ** alpha if w in col else None
        if sc is not None and sc.sum() > 0:
            t = int(sc.argmax())
            assigned.append((b, c, v, idx, w, topics[t]["topic"], round(float(sc[t] / sc.sum()), 3), "word"))
        elif W[u].sum() > 0:
            t = int(W[u].argmax())
            assigned.append((b, c, v, idx, w, topics[t]["topic"], round(float(W[u][t] / W[u].sum()), 3), "passage"))

    out.mkdir(parents=True, exist_ok=True)
    (out / "topics.json").write_text(json.dumps(topics, ensure_ascii=False, indent=1), encoding="utf-8")
    with (out / "passages.tsv").open("w", encoding="utf-8") as fh:
        fh.write("passage\tbook\tstart\tend\ttop_settings\n")
        for u in units:
            wt = W[u["id"]]
            top = [f"{topics[t]['topic']}:{wt[t] / (wt.sum() + 1e-12):.2f}" for t in np.argsort(-wt)[:3] if wt[t] > 0]
            fh.write(f"{u['id']}\t{u['book']}\t{u['start']}\t{u['end']}\t{','.join(top)}\n")
    with (out / "occurrences.tsv").open("w", encoding="utf-8") as fh:
        fh.write("book\tchapter\tverse\tidx\tlexeme\tsetting\tconfidence\tvia\n")
        for r in assigned:
            fh.write("\t".join(map(str, r)) + "\n")
    meta = {"k": k, "alpha": alpha, "seed": seed, "rel_err": round(err, 4), "passages": n_units, "vocab": len(vocab),
            "content_tokens": len(tokens), "assigned_tokens": len(assigned),
            "assigned_via_passage": sum(r[7] == "passage" for r in assigned)}
    (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--k", type=int, default=60)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--alpha", type=float, default=1.0,
                    help="weight of the word's own pull: argmax W[p,k] * P(w|k)^alpha (lower = more passage)")
    ap.add_argument("--publish", action="store_true", help="also write resources/settings/ from this build")
    a = ap.parse_args()
    out = a.out or HERE / "data" / "settings" / (f"k{a.k}" + (f"a{a.alpha:g}".replace(".", "") if a.alpha != 1 else ""))
    print(json.dumps(build(a.k, out, alpha=a.alpha)))
    if a.publish:
        publish(out)
    return 0



PUBLISH = ROOT / "resources" / "settings"


def publish(src: Path) -> None:
    """resources/settings/: hbo_settings.tsv (labels and top words), hbo_verse_settings.tsv (per verse, the
    setting of each content word in text order, keyed by Strong's so the STEP spine behind /verse can match
    it), hbo_strong_settings.tsv (each word's settings with shares, for word studies)."""
    topics = json.loads((src / "topics.json").read_text(encoding="utf-8"))
    meta = json.loads((src / "meta.json").read_text(encoding="utf-8"))
    lex = content_lexemes()
    PUBLISH.mkdir(parents=True, exist_ok=True)
    head = (f"# Hebrew settings (topical setting a word is used in; stand-in for SDBH ctx). CC BY 4.0: derived from "
            f"MACULA Hebrew (Clear Bible, CC BY 4.0) and the Open Scriptures Hebrew Bible paragraph marks (CC BY 4.0). "
            f"k={meta['k']}, NMF seed {meta['seed']}. Built by shoresh/macula/build_setting_axis.py.\n")
    with (PUBLISH / "hbo_settings.tsv").open("w", encoding="utf-8") as fh:
        fh.write(head + "setting\tlabel_strongs\tlabel_lemmas\ttop_strongs\n")
        for t in topics:
            w = t["words"]
            fh.write(f"{t['topic']}\t{w[0]['strong']},{w[1]['strong']}\t{w[0]['lemma']},{w[1]['lemma']}\t"
                     + ",".join(x["strong"] for x in w) + "\n")
    per_verse = collections.defaultdict(list)
    per_strong = collections.defaultdict(collections.Counter)
    with (src / "occurrences.tsv").open(encoding="utf-8") as fh:
        next(fh)
        rows = [l.rstrip("\n").split("\t") for l in fh]
    rows.sort(key=lambda r: (r[0], int(r[1]), int(r[2]), int(r[3])))
    for b, c, v, idx, lexeme, setting, conf, via in rows:
        strong = lex.get(lexeme, {}).get("strong")
        if not strong:
            continue
        per_verse[(b, int(c), int(v))].append(f"{strong}:{setting}:{via[0]}")
        per_strong[strong][setting] += 1
    with (PUBLISH / "hbo_verse_settings.tsv").open("w", encoding="utf-8") as fh:
        fh.write(head + "# words: strong:setting:via (w = the word's own topic in its passage, p = the passage's main setting)\n")
        fh.write("book\tchapter\tverse\twords\n")
        for (b, c, v), ws in per_verse.items():
            fh.write(f"{b}\t{c}\t{v}\t{'|'.join(ws)}\n")
    with (PUBLISH / "hbo_strong_settings.tsv").open("w", encoding="utf-8") as fh:
        fh.write(head + "strong\tsetting\tcount\tshare\n")
        for s in sorted(per_strong):
            cnt = per_strong[s]
            tot = sum(cnt.values())
            for setting, n in cnt.most_common(5):
                if n / tot >= 0.05:
                    fh.write(f"{s}\t{setting}\t{n}\t{n / tot:.3f}\n")
    print(f"published {len(topics)} settings, {len(per_verse)} verses, {len(per_strong)} words -> {PUBLISH}")


if __name__ == "__main__":
    sys.exit(main())
