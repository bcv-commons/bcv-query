"""Vector track V1: a contextual vector for every word of the bridge corpus, kept here as a working tool (the user, 2026-11-17).

    python -m macula.build_vector_store [--out macula/data/vector-store] [--corpus DIR] [--heb dicta-il/BEREL_3.0] [--grc bowphs/GreBerta]
    python -m macula.build_vector_store --pool-only [--out ...]

Texts: the Tanakh, the Septuagint, the Greek NT and the two Hebrew NTs of the bridge corpus (hebrew-greek-cf build). Each verse goes
through a native encoder: Hebrew (Tanakh, Salkinson, Delitzsch) BEREL 3.0 on unpointed text, Greek (Greek NT, Septuagint) GreBerta.
A word's vector is the mean of its orthographic token's subwords over the last 4 layers; the parts of one Hebrew token (prefix, stem,
suffix) share the token's vector. No English is read.

OUT gets, per text:
  <text>.npy           float16 [words x 768], one row per word, in corpus order
  <text>.parquet       node (corpus word node), key (lexeme key: h/g + Strong's number, or empty), pos, book, chapter, verse
and, from all texts:
  lexemes.npy / lexemes.json   the mean vector per lexeme key over all its occurrences (Hebrew keys over the three Hebrew texts,
                               Greek keys over the two Greek ones), with counts
  build.json                   models, corpus build, layers, counts
A nearest-neighbour search is a normalised matrix product (macula.vector_store_query); the store is small enough for that.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import re
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MARKS = re.compile(r"[֑-ׇ]")
HEBREW_TEXTS = ("tanakh", "salkinson", "delitzsch")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=HERE / "data" / "vector-store")
    ap.add_argument("--corpus", type=Path, default=HERE / "data" / "bridge-corpus" / "dev-builds" / "b15")
    ap.add_argument("--heb", default="dicta-il/BEREL_3.0")
    ap.add_argument("--grc", default="bowphs/GreBerta")
    ap.add_argument("--layers", type=int, default=4)
    ap.add_argument("--pool-only", action="store_true")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    if not a.pool_only:
        encode_all(a)
    pool(a.out)


def encode_all(a) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    import torch
    from transformers import AutoModel, AutoTokenizer
    from macula import build_bridge_corpus as B

    api = B.load(a.corpus)
    F, L = api.F, api.L

    def key(w):
        s = F.strong.v(w)
        if not s:
            return ""
        return ("h" if F.lang.v(w) in ("hbo", "arc") else "g") + str(s).lstrip("0").rstrip("abcdefgh")

    models = {}

    def model(name):
        if name not in models:
            tok = AutoTokenizer.from_pretrained(name, add_prefix_space=True) if name == a.grc else AutoTokenizer.from_pretrained(name)
            m = AutoModel.from_pretrained(name, output_hidden_states=True).to("cuda").eval().half()
            models.clear()
            models[name] = (tok, m)
        return models[name]

    counts = {}
    for t in F.otype.s("text"):
        name = F.name.v(t)
        heb = name in HEBREW_TEXTS
        tok, m = model(a.heb if heb else a.grc)
        words = list(L.d(t, otype="word"))
        row = {w: i for i, w in enumerate(words)}
        X = np.zeros((len(words), m.config.hidden_size), dtype=np.float16)
        done = np.zeros(len(words), dtype=bool)
        t0 = time.time()
        for n, v in enumerate(L.d(t, otype="verse")):
            toks, members, cur = [], [], None
            for w in L.d(v, otype="word"):
                tk = L.u(w, otype="token")
                tk = tk[0] if tk else w
                if tk != cur:
                    toks.append("")
                    members.append([])
                    cur = tk
                s = F.text.v(w) or ""
                toks[-1] += MARKS.sub("", s) if heb else s
                members[-1].append(w)
            pairs = [(x, y) for x, y in zip(toks, members) if x]
            for s0 in range(0, len(pairs), 120):
                chunk = pairs[s0:s0 + 120]
                enc = tok([x for x, _ in chunk], is_split_into_words=True, return_tensors="pt", truncation=True,
                          max_length=510).to("cuda")
                with torch.no_grad():
                    hs = m(**enc).hidden_states
                h = torch.stack(hs[-a.layers:]).float().mean(0)[0]
                acc = collections.defaultdict(list)
                for i, wi in enumerate(enc.word_ids()):
                    if wi is not None:
                        acc[wi].append(i)
                for wi, idx in acc.items():
                    vec = h[idx].mean(0).cpu().numpy().astype(np.float16)
                    for w in chunk[wi][1]:
                        X[row[w]] = vec
                        done[row[w]] = True
            if n % 5000 == 0:
                print(name, n, f"{time.time() - t0:.0f}s", flush=True)
        np.save(a.out / f"{name}.npy", X)
        meta = {"node": words, "key": [key(w) for w in words], "pos": [F.pos.v(w) or "" for w in words],
                "book": [], "chapter": [], "verse": [], "has_vector": done.tolist()}
        for w in words:
            v = L.u(w, otype="verse")[0]
            meta["book"].append(F.book.v(v))
            meta["chapter"].append(F.chapter.v(v))
            meta["verse"].append(F.verse.v(v))
        pq.write_table(pa.table(meta), a.out / f"{name}.parquet")
        counts[name] = {"words": len(words), "with_vector": int(done.sum())}
        print(name, counts[name], flush=True)
    (a.out / "build.json").write_text(json.dumps({
        "built": datetime.date.today().isoformat(), "corpus": str(a.corpus), "hebrew_model": a.heb, "greek_model": a.grc,
        "layers": a.layers, "texts": counts}, indent=1))


def pool(out: Path) -> None:
    import pyarrow.parquet as pq
    sums, cnt = {}, collections.Counter()
    for f in sorted(out.glob("*.parquet")):
        X = np.load(out / f"{f.stem}.npy", mmap_mode="r")
        t = pq.read_table(f, columns=["key", "has_vector"]).to_pydict()
        by = collections.defaultdict(list)
        for i, (k, ok) in enumerate(zip(t["key"], t["has_vector"])):
            if k and ok:
                by[k].append(i)
        for k, idx in by.items():
            s = X[idx].astype(np.float32).sum(0)
            sums[k] = s if k not in sums else sums[k] + s
            cnt[k] += len(idx)
    keys = sorted(sums)
    np.save(out / "lexemes.npy", np.stack([sums[k] / cnt[k] for k in keys]).astype(np.float32))
    (out / "lexemes.json").write_text(json.dumps({"keys": keys, "counts": [cnt[k] for k in keys]}))
    print(f"lexemes: {len(keys)} (Hebrew {sum(k[0] == 'h' for k in keys)}, Greek {sum(k[0] == 'g' for k in keys)})")


if __name__ == "__main__":
    main()
