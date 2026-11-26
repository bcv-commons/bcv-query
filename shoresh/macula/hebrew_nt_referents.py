"""Referent identity for pronouns, pronoun suffixes and finite verbs of the Hebrew New Testaments (request 40, row 1).

Per target part (a pronoun, a pronoun suffix, a verb with a person) the referent, an id shared along the chain, and the
part that last names it (the antecedent). Three bases, strongest first:
  - `linked`: the entity k1 (source examples, format 1.9) carries to the part from the Greek through lexeme-aligner's links
    (`who`);
  - `speech`: a first-person part inside a quotation is its speaker, a second-person part its addressee
    (hebrew-nt-analysis `speech.parquet`), where the number fits (a plural only a group, a singular never one). On the
    Tanakh (k1/hbo) the rule holds for 0.918 of first and 0.967 of second persons (without the number check 0.907, 0.951);
  - `model`: a mention ranker trained on the MACULA Hebrew Tanakh's referents (k1/hbo `who`: MACULA's subject and
    participant references and the entity layer) picks the antecedent among the previous nouns, pronouns and verbs, or
    `new`. Its inputs are forms, not words: class, person, number, gender, relation, distance, clause, quotation, the
    candidate's lexeme count. The referent is the antecedent's (its carried entity, or its own resolved referent, or an
    id minted at the first part of a chain: `x:<edition>:<book>.<chapter>.<verse>.<i>.<part>`).
No language model is called; nothing of the Greek goes into a `model` value.

  cd shoresh && .venv/bin/python -I macula/hebrew_nt_referents.py train
  cd shoresh && .venv/bin/python -I macula/hebrew_nt_referents.py export --release DIR --out OUT

DIR is a hebrew-nt-analysis release folder of v0.4 or later (words, features, pieces, clauses, speech per edition).
Writes OUT/<edition>/referents.parquet (one row per target part, keys book, chapter, verse, i, part) and OUT/build.json.
Splits as clause_tagger (test: Gen 37-45, Ruth, Jonah, 1 Sam 1-10, Deut 5-11; dev: Judges 1-5).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyarrow as pa
import pyarrow.parquet as pq
import torch
import torch.nn as nn

from macula.clause_tagger import split_of

HERE = Path(__file__).resolve().parent
K1 = HERE / "data" / "source-examples" / "k1"
WORK = HERE / "data" / "hebrew-nt-referents"
WINDOW, BACK_VERSES = 40, 6
NUM = {"sg": "s", "singular": "s", "pl": "p", "plural": "p", "du": "p", "dual": "p"}
GEN = {"m": "m", "masculine": "m", "f": "f", "feminine": "f", "c": "c", "common": "c", "both": "c"}
PER = {"1": "1", "first": "1", "2": "2", "second": "2", "3": "3", "third": "3"}
RELS = ("s", "o", "pp", "adv", "io", "v", "vc", "p", "root", "NPofNP:0", "NPofNP:1", "PrepNp:1", "DetNP:1", "Np-Appos:1",
        "Np-Appos:0", "CLaCL:0", "other")


# ---------------------------------------------------------------- parts, the same shape on both sides

def mention_class(cls, suffix, proper):
    if cls == "noun":
        return "name" if proper else "noun"
    if cls == "pron":
        return "sfx" if suffix else "pron"
    return cls


def tanakh_parts():
    """per book: the k1/hbo parts in order, as dicts"""
    words = {w["t"]: w for w in pq.read_table(K1 / "hbo" / "words.parquet",
             columns=["t", "book", "chapter", "verse", "w", "clause"]).to_pylist()}
    quotes = {c["clause"]: c["quote"] or "" for c in pq.read_table(K1 / "hbo" / "clauses.parquet",
              columns=["clause", "quote"]).to_pylist()}
    books = collections.OrderedDict()
    for p in pq.read_table(K1 / "hbo" / "pieces.parquet", columns=["t", "n", "class", "kind", "marks", "lexeme", "rel",
                                                                    "head_t", "head_n", "who"]).to_pylist():
        w = words.get(p["t"])
        if w is None:
            continue
        m = json.loads(p["marks"] or "{}")
        cls = p["class"] or "-"
        books.setdefault(w["book"], []).append({
            "key": (p["t"], p["n"]), "book": w["book"], "chapter": w["chapter"], "verse": w["verse"], "w": p["t"],
            "cls": mention_class(cls, p["kind"] == "suffix", m.get("type") == "proper"),
            "per": PER.get(str(m.get("person", "")), ""), "num": NUM.get(m.get("number", ""), ""),
            "gen": GEN.get(m.get("gender", ""), ""), "rel": p["rel"] or "", "lex": (p["lexeme"] or "").rsplit(":", 1)[-1],
            "head": (p["head_t"], p["head_n"]) if p["head_t"] else None, "clause": w["clause"] or "",
            "quote": quotes.get(w["clause"], "") if w["clause"] else "", "who": p["who"] or "",
            "finite": cls == "verb" and bool(PER.get(str(m.get("person", "")), ""))})
    for ps in books.values():
        ps.sort(key=lambda x: x["key"])
    return books


def nt_parts(release: Path, ed: str):
    """per book: the edition's parts in order, from the release (words, features, pieces, clauses, speech) and k1's
    carried `who`"""
    tab = lambda name, cols=None: pq.read_table(release / ed / name, columns=cols).to_pylist()
    feats = {(r["book"], r["chapter"], r["verse"], r["i"], r["part"]): r for r in tab("features.parquet")}
    pieces = {(r["book"], r["chapter"], r["verse"], r["i"], r["part"]): r for r in tab("pieces.parquet")}
    speech = {(r["book"], r["chapter"], r["verse"], r["seg"]): r for r in tab("speech.parquet")}
    an = collections.defaultdict(list)
    rows = [r for r in tab("words.parquet") if r["source"] is not None]
    for r in rows:
        if r["text"]:
            an[(r["book"], r["chapter"], r["verse"], r["i"])].append(r["part"])
    kwords = {w["t"]: w for w in pq.read_table(K1 / ed / "words.parquet", columns=["t", "book", "chapter", "verse", "w"]).to_pylist()}
    carried = {}
    for p in pq.read_table(K1 / ed / "pieces.parquet", columns=["t", "n", "who"]).to_pylist():
        w = kwords.get(p["t"])
        if w is None or not p["who"]:
            continue
        wk = (w["book"], w["chapter"], w["verse"], w["w"] - 1)
        parts = sorted(an.get(wk, []))
        if 0 < p["n"] <= len(parts):
            carried[wk + (parts[p["n"] - 1],)] = p["who"]
    books = collections.OrderedDict()
    for r in rows:
        k = (r["book"], r["chapter"], r["verse"], r["i"], r["part"])
        if not r["text"]:
            continue
        f, pc = feats.get(k, {}), pieces.get(k, {})
        sp = speech.get((r["book"], r["chapter"], r["verse"], r["seg"]), {}) if r["seg"] else {}
        cls = r["class"] or "-"
        suffix = cls == "pron" and r["part"] > 0
        head = (r["book"], r["chapter"], r["verse"], pc["head_i"], pc["head_part"]) if pc.get("head_i") is not None else None
        books.setdefault(r["book"], []).append({
            "key": k, "book": r["book"], "chapter": r["chapter"], "verse": r["verse"], "w": (r["chapter"], r["verse"], r["i"]),
            "cls": mention_class(cls, suffix, f.get("definite") == "name"),
            "per": PER.get(f.get("person") or "", ""), "num": NUM.get(f.get("number") or "", ""),
            "gen": GEN.get(f.get("gender") or "", ""), "rel": pc.get("rel") or "", "lex": r["strong"] or "",
            "head": head, "clause": f"{r['chapter']}.{r['verse']}.{r['seg']}", "quote": sp.get("quote") or "",
            "speaker": sp.get("speaker") or "", "addressee": sp.get("addressee") or "",
            "who": carried.get(k, ""), "finite": cls == "verb" and bool(PER.get(f.get("person") or "", ""))})
    for ps in books.values():
        ps.sort(key=lambda x: (x["chapter"], x["verse"], x["key"][3], x["key"][4]))
    return books


def is_target(p):
    return p["cls"] in ("pron", "sfx") or p["finite"]


def is_candidate(p):
    return p["cls"] in ("noun", "name", "pron", "sfx") or p["finite"]


# ---------------------------------------------------------------- features

CATS = {"t_cls": ("pron", "sfx", "verb"), "c_cls": ("noun", "name", "pron", "sfx", "verb"), "rel": RELS,
        "num": ("s", "p", ""), "gen": ("m", "f", "c", ""), "per": ("1", "2", "3", "")}


def onehot(name, v, vocab):
    out = [0.0] * len(vocab)
    out[vocab.index(v) if v in vocab else len(vocab) - 1] = 1.0
    return out


def rel_of(r):
    return r if r in RELS else "other"


def match(a, b, common=False):
    if not a or not b:
        return [0, 0, 1]
    if a == b or (common and "c" in (a, b)):
        return [1, 0, 0]
    return [0, 1, 0]


def target_feats(t):
    return (onehot("t_cls", t["cls"] if t["cls"] != "verb" else "verb", CATS["t_cls"]) + onehot("rel", rel_of(t["rel"]), RELS)
            + onehot("num", t["num"], CATS["num"]) + onehot("gen", t["gen"], CATS["gen"]) + onehot("per", t["per"], CATS["per"])
            + [1.0 if t["quote"] else 0.0])


def pair_feats(t, c, rank, wdist, vdist, lexcount):
    cper = c["per"] or ("3" if c["cls"] in ("noun", "name") else "")
    f = (onehot("c_cls", c["cls"], CATS["c_cls"]) + onehot("rel", rel_of(c["rel"]), RELS)
         + match(t["num"], c["num"]) + match(t["gen"], c["gen"], common=True) + match(t["per"], cper)
         + [min(rank, 39) / 39.0, min(wdist, 200) / 200.0, min(vdist, BACK_VERSES) / BACK_VERSES]
         + [1.0 if vdist == 0 else 0.0, 1.0 if c["clause"] and c["clause"] == t["clause"] else 0.0,
            1.0 if c["head"] == t["key"] else 0.0, 1.0 if t["head"] == c["key"] else 0.0,
            1.0 if c["head"] is not None and c["head"] == t["head"] else 0.0,
            1.0 if t["quote"] and c["quote"] == t["quote"] else 0.0, 1.0 if bool(t["quote"]) != bool(c["quote"]) else 0.0,
            min(lexcount, 10) / 10.0, 1.0 if c["rel"] == "s" else 0.0])
    return f


def instances(parts, with_gold=True):
    """per target: (target index, candidate indices, feature rows, target features, gold mask)"""
    out = []
    cand_idx = []                                         # indices of candidates so far
    for i, t in enumerate(parts):
        if is_target(t) and (not with_gold or t["who"]):
            cs = []
            lex = collections.Counter()
            for j in reversed(cand_idx):
                c = parts[j]
                if (c["chapter"], c["verse"]) != (t["chapter"], t["verse"]):
                    vd = (t["chapter"] - c["chapter"]) * 50 + (t["verse"] - c["verse"])
                    if c["chapter"] != t["chapter"]:
                        vd = BACK_VERSES + 1 if c["chapter"] < t["chapter"] - 1 else min(vd, BACK_VERSES)
                    if vd > BACK_VERSES:
                        break
                cs.append(j)
                if len(cs) >= WINDOW:
                    break
            for j in cs:
                if parts[j]["lex"]:
                    lex[parts[j]["lex"]] += 1
            rows, gold = [], []
            tw = set(t["who"].split())
            for rank, j in enumerate(cs):
                c = parts[j]
                vd = 0 if (c["chapter"], c["verse"]) == (t["chapter"], t["verse"]) else \
                    (min(BACK_VERSES, t["verse"] - c["verse"]) if c["chapter"] == t["chapter"] else BACK_VERSES)
                rows.append(pair_feats(t, c, rank, i - j, vd, lex[c["lex"]] if c["lex"] else 0))
                gold.append(bool(tw & set(c["who"].split())) if with_gold else False)
            out.append((i, cs, rows, target_feats(t), gold))
        if is_candidate(t):
            cand_idx.append(i)
    return out


class Ranker(nn.Module):
    def __init__(self, nf, nt):
        super().__init__()
        self.pair = nn.Sequential(nn.Linear(nf + nt, 128), nn.ReLU(), nn.Linear(128, 64), nn.ReLU(), nn.Linear(64, 1))
        self.new = nn.Sequential(nn.Linear(nt, 64), nn.ReLU(), nn.Linear(64, 1))

    def forward(self, pf, tf, mask):
        """pf [B, W, nf], tf [B, nt], mask [B, W] -> logits [B, W+1] (last = new)"""
        x = torch.cat([pf, tf.unsqueeze(1).expand(-1, pf.shape[1], -1)], -1)
        s = self.pair(x).squeeze(-1).masked_fill(~mask, -1e9)
        return torch.cat([s, self.new(tf)], -1)


def batchify(insts, device):
    W = max(1, max(len(x[1]) for x in insts))
    nf, nt = len(insts[0][2][0]) if insts[0][2] else NF, len(insts[0][3])
    pf = torch.zeros(len(insts), W, NF); tf = torch.tensor([x[3] for x in insts]); mask = torch.zeros(len(insts), W, dtype=torch.bool)
    gold = torch.zeros(len(insts), W + 1, dtype=torch.bool)
    for b, (_, cs, rows, _, g) in enumerate(insts):
        if rows:
            pf[b, :len(rows)] = torch.tensor(rows); mask[b, :len(rows)] = True
            gold[b, :len(rows)] = torch.tensor(g)
        if not any(g):
            gold[b, W] = True
    return pf.to(device), tf.to(device), mask.to(device), gold.to(device)


NF = len(pair_feats({"num": "", "gen": "", "per": "", "rel": "", "clause": "", "key": 0, "head": None, "quote": ""},
                    {"cls": "noun", "num": "", "gen": "", "per": "", "rel": "", "clause": "", "key": 1, "head": None, "quote": "", "lex": ""},
                    0, 1, 0, 0))


def loss_fn(logits, gold):
    lp = torch.log_softmax(logits, -1)
    return -(torch.logsumexp(lp.masked_fill(~gold, -1e9), -1)).mean()


def train(epochs=6, seed=1):
    random.seed(seed); torch.manual_seed(seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    books = tanakh_parts()
    data = {"train": [], "dev": [], "test": []}
    for b, parts in books.items():
        by = collections.defaultdict(list)
        for x in instances(parts):
            t = parts[x[0]]
            data[split_of(b, t["chapter"])].append((x, t))
    print({k: len(v) for k, v in data.items()}, "features", NF)
    nt = len(data["train"][0][0][3])
    model = Ranker(NF, nt).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    tr = [x for x, _ in data["train"]]
    for ep in range(1, epochs + 1):
        model.train(); random.shuffle(tr); tot = 0.0
        for k in range(0, len(tr), 256):
            pf, tf, mask, gold = batchify(tr[k:k + 256], device)
            loss = loss_fn(model(pf, tf, mask), gold)
            opt.zero_grad(); loss.backward(); opt.step(); tot += loss.item()
        print(f"epoch {ep} loss {tot / (len(tr) / 256):.4f} dev {score(model, data['dev'], device)['all']}")
    WORK.mkdir(parents=True, exist_ok=True)
    torch.save({"state": model.state_dict(), "nf": NF, "nt": nt, "epochs": epochs, "seed": seed}, WORK / "ranker.pt")
    res = score(model, data["test"], device)
    (WORK / "score-test.json").write_text(json.dumps(res, indent=1) + "\n")
    print("test", json.dumps(res))


@torch.no_grad()
def predict(model, insts, device):
    model.eval(); out = []
    for k in range(0, len(insts), 512):
        chunk = insts[k:k + 512]
        pf, tf, mask, _ = batchify(chunk, device)
        pr = torch.softmax(model(pf, tf, mask), -1)
        W = pr.shape[1] - 1
        for b, x in enumerate(chunk):
            p = pr[b]; j = int(p.argmax())
            out.append((None if j == W else x[1][j], float(p[j])))
    return out


def score(model, data, device):
    """antecedent right: the chosen candidate shares the target's referent, or `new` where no candidate does"""
    insts = [x for x, _ in data]
    pred = predict(model, insts, device)
    acc = collections.Counter()
    bands = collections.Counter()
    for (x, t), (j, p) in zip(data, pred):
        g = x[4]
        ok = (not any(g)) if j is None else g[x[1].index(j)]
        kind = "verb" if t["cls"] == "verb" else t["cls"]
        for k in ("all", kind, f"{kind}_{t['per'] or '-'}"):
            acc[k + "_n"] += 1; acc[k] += ok
        band = "p>=0.9" if p >= 0.9 else "p>=0.7" if p >= 0.7 else "p<0.7"
        bands[band + "_n"] += 1; bands[band] += ok
    res = {k: round(acc[k] / acc[k + "_n"], 4) for k in acc if not k.endswith("_n")}
    res.update({f"n_{k[:-2]}": v for k, v in acc.items() if k.endswith("_n")})
    res.update({f"band {k}": round(bands[k] / bands[k + '_n'], 4) for k in bands if not k.endswith("_n")})
    res.update({f"band_n {k[:-2]}": v for k, v in bands.items() if k.endswith("_n")})
    return res


# ---------------------------------------------------------------- export

def fits(t, ent):
    """may the speaker or addressee `ent` be the referent of target t? a plural (we, you all) only a group, a singular never a
    group (2026-11-26: "we" is not the speaker alone, "you" plural not the one person the inquit names)"""
    if not ent:
        return False
    group = ent.split(":")[0] == "group"
    return not ((t["num"] == "p" and not group) or (t["num"] == "s" and group))


def export(release: Path, out: Path):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    ck = torch.load(WORK / "ranker.pt", map_location=device)
    model = Ranker(ck["nf"], ck["nt"]).to(device); model.load_state_dict(ck["state"])
    build = {"model": "ranker.pt", "sha256": hashlib.sha256((WORK / "ranker.pt").read_bytes()).hexdigest(),
             "tanakh_test": json.loads((WORK / "score-test.json").read_text()), "editions": {}}
    for ed in ("heb_scg", "heb_mod"):
        books = nt_parts(release, ed)
        rows, n = [], collections.Counter()
        for b, parts in books.items():
            insts = instances(parts, with_gold=False)
            pred = predict(model, insts, device)
            ref = {}                                         # part index -> resolved referent
            for (i, cs, _, _, _), (j, p) in zip(insts, pred):
                t = parts[i]
                mref = None
                if j is not None:
                    c = parts[j]
                    mref = c["who"] or ref.get(j) or "x:{}:{}.{}.{}.{}.{}".format(ed, *c["key"])
                    if not c["who"] and j not in ref and c["cls"] in ("noun", "name"):
                        ref[j] = mref                       # the chain's first part keeps the minted id
                if t["who"]:
                    val, basis, prob = t["who"], "linked", None
                elif t["per"] in ("1", "2") and t["quote"] and fits(t, t["speaker"] if t["per"] == "1" else t["addressee"]):
                    val, basis, prob = (t["speaker"] if t["per"] == "1" else t["addressee"]), "speech", None
                elif j is not None:
                    val, basis, prob = mref, "model", round(p, 4)
                else:
                    val, basis, prob = "x:{}:{}.{}.{}.{}.{}".format(ed, *t["key"]), "model_new", round(p, 4)
                ref[i] = val
                ante = None
                if j is not None and basis in ("model", "model_new"):
                    ante = parts[j]["key"]
                else:                                       # the last part before it with the same referent
                    for k in range(i - 1, max(-1, i - 400), -1):
                        if (parts[k]["who"] or ref.get(k)) == val:
                            ante = parts[k]["key"]; break
                row = {"book": t["key"][0], "chapter": t["key"][1], "verse": t["key"][2], "i": t["key"][3], "part": t["key"][4],
                       "target": "verb" if t["cls"] == "verb" else t["cls"], "person": t["per"], "referent": val,
                       "referent_basis": basis, "referent_p": prob,
                       "antecedent_i": None if ante is None else ante[3], "antecedent_part": None if ante is None else ante[4],
                       "antecedent_verse": None if ante is None else f"{ante[1]}:{ante[2]}",
                       "model_antecedent_p": round(p, 4), "model_referent": mref,
                       "model_agree": None if not t["who"] or j is None else bool(set(t["who"].split()) & set((mref or "").split()))}
                rows.append(row)
                n[f"{row['target']}_{basis}"] += 1
                if row["model_agree"] is not None:
                    n["check_n"] += 1; n["check_agree"] += row["model_agree"]
        cols = [("book", pa.string()), ("chapter", pa.int16()), ("verse", pa.int16()), ("i", pa.int16()), ("part", pa.int8()),
                ("target", pa.string()), ("person", pa.string()), ("referent", pa.string()), ("referent_basis", pa.string()),
                ("referent_p", pa.float32()), ("antecedent_i", pa.int16()), ("antecedent_part", pa.int8()),
                ("antecedent_verse", pa.string()), ("model_antecedent_p", pa.float32()), ("model_referent", pa.string()),
                ("model_agree", pa.bool_())]
        (out / ed).mkdir(parents=True, exist_ok=True)
        fp = out / ed / "referents.parquet"
        pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema(cols)), fp, compression="zstd")
        build["editions"][ed] = {"rows": len(rows), "counts": dict(sorted(n.items())),
                                 "model_vs_linked": round(n["check_agree"] / max(1, n["check_n"]), 4),
                                 "sha256": hashlib.sha256(fp.read_bytes()).hexdigest()}
        print(f"[hebrew_nt_referents] {ed}: {len(rows)} rows; {dict(sorted(n.items()))}")
    (out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train"); t.add_argument("--epochs", type=int, default=6); t.add_argument("--seed", type=int, default=1)
    e = sub.add_parser("export"); e.add_argument("--release", type=Path, required=True); e.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "train":
        train(a.epochs, a.seed)
    else:
        export(a.release, a.out)


if __name__ == "__main__":
    main()
