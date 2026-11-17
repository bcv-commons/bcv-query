#!/usr/bin/env python3
"""Parts analysis of an UNPOINTED Hebrew NT (Delitzsch, heb_mod: eBible `heb`, public domain, no vowel points), by bcv-query's
clause tagger (shoresh/macula/clause_tagger.py, the model behind bcv-commons/hebrew-nt-analysis) retrained on the same MACULA data
with the points removed. Nothing in bcv-query is changed: the tagger's module is imported with its data folder pointed here.
  prep     $BCV_COMMONS/bcv-query/shoresh/macula/data/clause-tagger/verses.jsonl -> OUT/verses.jsonl, every word unpointed and each
           part's length counted in letters (the lemma stays pointed: it is a label)
  train    the tagger's own train() on OUT (dicta-il/dictabert, 4 epochs, seed 13, as the published model) -> OUT/model-dictabert.pt
  score    the tagger's own score() on the held-out Tanakh chapters, with the lookup of known forms (now unpointed forms)
  compare  heb_scg with its points removed, tagged here, against the published pointed analysis (hebrew-nt-analysis v0.1): same
           split, class and Strong's per part
  export   --helloao DIR --edition heb_mod -> OUT/export/heb_mod/{words,clauses}.parquet, manifest.json (the tagger's export())
OUT = $MAKE_TANAKH_PRIVATE/rules/bridge/hebmod/tagger.
2026-11-16: superseded for new work by bcv-commons/hebrew-nt-analysis v0.2 (heb_mod, bcv-query's `train --unpointed`; pinned as
$WORD_PARTS/hebrew-nt-analysis). Our model, its training copy and test predictions are deleted; OUT/export stays, because the
Delitzsch review layer (scg_export, scg_check, witness_agree, hebmod_byid) is positioned on these parts: 141 of 109,641 words are
split differently in the release.
    . ./env.sh; $BCV_COMMONS/bcv-query/shoresh/.venv/bin/python lab/bridge/hebmod_parts.py prep|train|score|compare|export"""
import argparse, collections, json, os, sys, unicodedata
from pathlib import Path

Q = Path(os.environ["BCV_COMMONS"]) / "bcv-query" / "shoresh"
sys.path.insert(0, str(Q))
from macula import clause_tagger as ct                                     # noqa: E402

OUT = Path(os.environ["MAKE_TANAKH_PRIVATE"]) / "rules" / "bridge" / "hebmod" / "tagger"
ct.OUT = OUT
WORDS = Path(os.environ["MAKE_TANAKH_WORK"]) / "download" / "hebrew-nt-analysis" / "heb_scg" / "words.parquet"
un = lambda s: ct.POINTS.sub("", unicodedata.normalize("NFD", s))


def prep(a):
    OUT.mkdir(parents=True, exist_ok=True); n = collections.Counter()
    with (OUT / "verses.jsonl").open("w") as fo:
        for l in (Q / "macula" / "data" / "clause-tagger" / "verses.jsonl").open():
            v = json.loads(l)
            for w in v["words"]:
                t = unicodedata.normalize("NFD", w["text"]); at = 0
                for x in w["parts"]:
                    piece = t[at:at + x["len"]]; at += x["len"]; x["len"] = len(un(piece))
                assert at == len(t), (v["ref"], w["text"])
                w["text"] = unicodedata.normalize("NFC", un(t)); n["words"] += 1
                n["empty parts"] += sum(1 for x in w["parts"] if x["len"] == 0)
            fo.write(json.dumps(v, ensure_ascii=False) + "\n")
    print(dict(n), "->", OUT / "verses.jsonl")


def train(a):
    ct.train("dicta-il/dictabert", 4, 16, 13)


def score(a):
    ct.score(OUT / "model-dictabert.pt", "test", lookup=True)


def compare(a):
    """heb_scg unpointed, tagged here, against the published analysis: the published one is 80.7% MACULA lookup, the rest model."""
    import pyarrow.parquet as pq
    rows = pq.read_table(WORDS, columns=["book", "chapter", "verse", "i", "part", "token", "text", "class", "strong"]).to_pylist()
    model, bat, device, ck = ct.load_model(OUT / "model-dictabert.pt")
    table = ct.lookup_table(("train", "dev", "test"))
    byv = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        if r["class"] != "verse-number":
            byv[(r["book"], r["chapter"], r["verse"])][r["i"]].append(r)
    verses, gold = [], []
    for (b, c, v), ws in byv.items():
        verses.append({"ref": f"{b} {c}:{v}", "words": [{"text": ws[i][0]["token"]} for i in sorted(ws)]})
        gold.append([[(len(un(x["text"])), x["class"], x["strong"]) for x in sorted(ws[i], key=lambda x: x["part"])] for i in sorted(ws)])
    pred = ct.predict(model, bat, verses, device)
    for p_ in pred:
        for x in p_["words"]:
            x["source"] = "model"
    ct.apply_lookup(pred, table)
    st = collections.Counter()
    for p_, gw in zip(pred, gold):
        for x, g in zip(p_["words"], gw):
            ps = [(len(y["text"]), y["class"], y["strong"]) for y in x["parts"]]
            st["words"] += 1; st["lookup"] += x["source"] == "macula"
            if [q[0] for q in ps] == [q[0] for q in g]:
                st["split"] += 1
                st["class"] += all(q[1] == r[1] for q, r in zip(ps, g))
                st["strong"] += all((q[2] or None) == (r[2] or None) for q, r in zip(ps, g))
                cont = [(q, r) for q, r in zip(ps, g) if r[1] in ("noun", "verb", "adj")]
                st["content parts"] += len(cont); st["content strong"] += sum((q[2] or None) == (r[2] or None) for q, r in cont)
    n = st["words"]
    print({k: v for k, v in st.items()}, f"lookup {st['lookup'] / n:.1%}; split {st['split'] / n:.1%}; class|split {st['class'] / st['split']:.1%}; "
          f"strong|split {st['strong'] / st['split']:.1%}; content-part strong {st['content strong'] / st['content parts']:.1%}")


def export(a):
    """the tagger's export, plus a `_split.json` beside words.parquet (bcv-split header, so align-text --split checks the text's
    fingerprints; the rows stay in hebrew-nt-analysis' format, which lexeme-aligner's target_parts reads as is)"""
    import datetime, hashlib
    ct.export(OUT / "model-dictabert.pt", Path(a.helloao), a.edition, [])
    d = OUT / "export" / a.edition; man = json.loads((d / "manifest.json").read_text())
    import pyarrow as pa, pyarrow.parquet as pq                            # lexeme-aligner's Jev by clause reads `chain_id` (a
    t = pq.read_table(d / "words.parquet")                                  # bcv-split column); Hebrew has no chain facts: null
    if "chain_id" not in t.column_names:
        pq.write_table(t.append_column("chain_id", pa.nulls(len(t), pa.string())), d / "words.parquet")
    (d / "_split.json").write_text(json.dumps({
        "spec": "bcv-split/0.1", "edition": a.edition, "tokenizer_version": man["tokenizer_version"],
        "source": "bcv-query clause tagger retrained unpointed (make-tanakh-grammar lab/bridge/hebmod_parts.py), " + str(datetime.date.today()),
        "basis": "model", "sha256": hashlib.sha256((d / "words.parquet").read_bytes()).hexdigest(), "text_licence": "public domain",
        "books": sorted(man["books"]), "text_fp": {b: x["file_hash"] for b, x in man["books"].items()},
        "text_fp_version": man["text_fp_version"], "date": str(datetime.date.today())}, ensure_ascii=False, indent=1) + "\n")
    print("_split.json ->", d)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("--helloao"); ap.add_argument("--edition", default="heb_mod")
    a = ap.parse_args(); globals()[a.cmd](a)
