"""Referent identity for pronouns, pronoun suffixes and finite verbs of the Hebrew New Testaments (request 40, row 1).

Per target part (a pronoun, a pronoun suffix, a verb with a person) the referent, an id shared along the chain, and the
part that last names it (the antecedent). Three bases, strongest first:
  - `linked`: the entity k1 (source examples, format 1.9) carries to the part from the Greek through lexeme-aligner's links
    (`who`). A verb takes it only from a Greek verb whose referent is its subject (k1 grc `who_basis` subject, chain,
    pronominal, reference): a Hebrew verb linked to a Greek noun (תָּקַע to σάλπιγξ) or a Greek verb that names a thing
    (`explicit`: σταυρόω, the cross) would give the verb what it evokes, not who does it (2026-11-26, research's Swahili
    check of inanimate referents);
  - `speech`: a first-person part inside a quotation is its speaker, a second-person part its addressee
    (hebrew-nt-analysis `speech.parquet`), where the number fits (a plural only a group, a singular never one). On the
    Tanakh (k1/hbo) the rule holds for 0.918 of first and 0.967 of second persons (without the number check 0.907, 0.951);
  - `model`: a mention ranker trained on the MACULA Hebrew Tanakh's referents (k1/hbo `who`: MACULA's subject and
    participant references and the entity layer) picks the antecedent among the previous nouns, pronouns and verbs, or
    `new`. Its inputs are forms, not words: class, person, number, gender, relation, distance, clause, quotation, the
    candidate's lexeme count; with `train --animacy` also two animacy shares counted on the Tanakh (how often the
    candidate's lexeme refers to a person, group or deity, and how often the target verb's lexeme has such a subject: on
    2026-11-26 it cut inanimate verb referents from 0.109 to 0.075 but agreed a little less with the carried entities, so
    it is off by default). The referent is the antecedent's (its carried entity, or its own resolved referent, or an
    id minted at the first part of a chain: `x:<edition>:<book>.<chapter>.<verse>.<i>.<part>`).
No generative language model is called (with `train --context` the frozen DictaBERT encoder gives word vectors, as below); nothing of the Greek goes into a `model` value. As input only (not published as a feature),
a noun or name without number or gender whose carried entity is one person or deity is taken as singular, and as the
entity's recorded sex (k1 participants), for the agreement the ranker reads: names the Tanakh lacks have none otherwise.

The two editions translate the same Greek, so they check each other: a target of one edition and a target of the other that
k1's strict word links tie to the same Greek word should have the same referent. `other_edition_referent` is the other
edition's entity there (where both have an entity id), `editions_agree` whether they are the same.

  cd shoresh && .venv/bin/python -I macula/hebrew_nt_referents.py train --context   (the v0.7 ranker: 15 epochs, seed 1)
  cd shoresh && .venv/bin/python -I macula/hebrew_nt_referents.py calibrate
  cd shoresh && .venv/bin/python -I macula/hebrew_nt_referents.py export --release DIR --out OUT

With `train --context` the ranker also reads the words: each word's vector from dicta-il/dictabert (frozen, the mean of its
word pieces, one verse at a time), projected for the target and each candidate (their product and the candidate's own).

`calibrate` measures, on the Tanakh's dev and test chapters, how often the ranker is right per bin of its probability
(CALIB_BINS), and writes calibration.json; `export` then gives each model row `referent_p_calibrated`, the right-share of
its bin.

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
ENCODER = "dicta-il/dictabert"
SUBJECT_BASES = {"subject", "chain", "pronominal", "reference"}
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
    gsubj = collections.defaultdict(set)                 # Greek word -> referents it carries as a verb's subject
    for g in pq.read_table(K1 / "grc" / "pieces.parquet", columns=["t", "class", "who", "who_basis"]).to_pylist():
        if g["class"] == "verb" and g["who"] and g["who_basis"] in SUBJECT_BASES:
            gsubj[g["t"]].update(g["who"].split())
    carried, dropped = {}, collections.Counter()
    for p in pq.read_table(K1 / ed / "pieces.parquet", columns=["t", "n", "class", "who", "who_from"]).to_pylist():
        w = kwords.get(p["t"])
        if w is None or not p["who"]:
            continue
        if p["class"] == "verb" and not (set(p["who"].split()) & gsubj.get(p["who_from"], set())):
            dropped[p["who"].split(":")[0]] += 1
            continue
        wk = (w["book"], w["chapter"], w["verse"], w["w"] - 1)
        parts = sorted(an.get(wk, []))
        if 0 < p["n"] <= len(parts):
            carried[wk + (parts[p["n"] - 1],)] = p["who"]
    print(f"[hebrew_nt_referents] {ed}: carried verb referents dropped (not a Greek verb's subject): {dict(dropped)}")
    import csv
    with open(K1 / ed / "participants.tsv", encoding="utf-8") as fh:
        sex = {r["ent"]: r["sex"] for r in csv.DictReader(fh, delimiter="\t")}
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
    filled = collections.Counter()
    for ps in books.values():
        ps.sort(key=lambda x: (x["chapter"], x["verse"], x["key"][3], x["key"][4]))
        for p in ps:
            ids = p["who"].split()
            if p["cls"] in ("noun", "name") and len(ids) == 1 and ids[0].split(":")[0] in ("person", "deity"):
                if not p["num"]:
                    p["num"] = "s"; filled["number"] += 1
                if not p["gen"] and sex.get(ids[0]) in ("m", "f"):
                    p["gen"] = sex[ids[0]]; filled["gender"] += 1
    print(f"[hebrew_nt_referents] {ed}: candidate nouns filled from their entity: {dict(filled)}")
    return books


def encode(verses, device):
    """verses: [[word, ...], ...] (unpointed) -> one vector per word, fp16, in order; dicta-il/dictabert frozen"""
    from transformers import AutoModel, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(ENCODER)
    enc = AutoModel.from_pretrained(ENCODER).to(device).eval()
    out = []
    with torch.no_grad():
        for k in range(0, len(verses), 32):
            batch = [v if v else ["-"] for v in verses[k:k + 32]]
            b = tok(batch, is_split_into_words=True, truncation=True, max_length=512, padding=True, return_tensors="pt")
            h = enc(**{x: y.to(device) for x, y in b.items()}).last_hidden_state
            for r in range(len(batch)):
                ids = b.word_ids(r)
                n = len(verses[k + r])
                acc = torch.zeros(max(1, n), h.shape[-1], device=device); cnt = torch.zeros(max(1, n), 1, device=device)
                for pos, wi in enumerate(ids):
                    if wi is not None and wi < n:
                        acc[wi] += h[r, pos]; cnt[wi] += 1
                out.append((acc / cnt.clamp(min=1))[:n].half().cpu())
    return torch.cat(out) if out else torch.zeros(0, 768, dtype=torch.float16)


def word_vectors(name, verses_keys, device):
    """verses_keys: [(verse words, word keys)] -> ({word key: row}, tensor with a zero row last), cached in WORK"""
    f = WORK / f"vec-{name}.pt"
    keys = [k for _, ks in verses_keys for k in ks]
    if f.exists():
        d = torch.load(f)
        if d["keys"] == keys:
            return {k: i for i, k in enumerate(keys)}, d["V"]
    V = encode([ws for ws, _ in verses_keys], device)
    V = torch.cat([V, torch.zeros(1, V.shape[1], dtype=V.dtype)])
    WORK.mkdir(parents=True, exist_ok=True)
    torch.save({"keys": keys, "V": V}, f)
    return {k: i for i, k in enumerate(keys)}, V


def attach_vectors(books, name, verses_keys, device, key_of):
    idx, V = word_vectors(name, verses_keys, device)
    for ps in books.values():
        for p in ps:
            p["vec"] = idx.get(key_of(p), -1)
    VEC[0] = V.to(device)
    return V.shape[1]


def tanakh_verses():
    from macula.clause_tagger import unpointed
    vs = collections.OrderedDict()
    for w in pq.read_table(K1 / "hbo" / "words.parquet", columns=["t", "book", "chapter", "verse", "text"]).to_pylist():
        vs.setdefault((w["book"], w["chapter"], w["verse"]), ([], []))
        vs[(w["book"], w["chapter"], w["verse"])][0].append(unpointed(w["text"] or "") or "-")
        vs[(w["book"], w["chapter"], w["verse"])][1].append(w["t"])
    return list(vs.values())


def nt_verses(release, ed):
    vs = collections.OrderedDict()
    seen = set()
    for r in pq.read_table(release / ed / "words.parquet", columns=["book", "chapter", "verse", "i", "token", "source"]).to_pylist():
        k = (r["book"], r["chapter"], r["verse"], r["i"])
        if r["source"] is None or k in seen:
            continue
        seen.add(k)
        vs.setdefault(k[:3], ([], []))
        vs[k[:3]][0].append(r["token"] or "-"); vs[k[:3]][1].append(k)
    return list(vs.values())


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


ANIMATE = ("person", "group", "deity")
ANIM = {"noun": {}, "verb": {}}                        # Tanakh lexeme (Strong's) -> share of occurrences with an animate referent
USE_ANIM = [False]


def animacy_tables(books):
    """per noun / name lexeme and per verb lexeme: (animate + 1) / (occurrences + 2) over the Tanakh"""
    cnt = {"noun": collections.defaultdict(lambda: [0, 0]), "verb": collections.defaultdict(lambda: [0, 0])}
    for parts in books.values():
        for p in parts:
            kind = "verb" if p["cls"] == "verb" else "noun" if p["cls"] in ("noun", "name") else None
            if kind and p["lex"]:
                c = cnt[kind][p["lex"]]
                c[1] += 1
                c[0] += any(x.split(":")[0] in ANIMATE for x in p["who"].split())
    return {k: {lex: round((a + 1) / (n + 2), 3) for lex, (a, n) in v.items() if n >= 3} for k, v in cnt.items()}


def anim_of(p, kind):
    return ANIM[kind].get(p["lex"], 0.5) if p["lex"] else 0.5


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
    if not USE_ANIM[0]:
        return f
    ta = anim_of(t, "verb") if t["cls"] == "verb" else 0.5
    ca = anim_of(c, "noun") if c["cls"] in ("noun", "name") else 0.5
    return f + [ta, ca, ta * ca, (1 - ta) * (1 - ca)]


def instances(parts, with_gold=True):
    """per target: (target index, candidate indices, feature rows, target features, gold mask, (target vector, candidate
    vectors)); a part's vector index is p["vec"] (-1: none)"""
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
            out.append((i, cs, rows, target_feats(t), gold, (t.get("vec", -1), [parts[j].get("vec", -1) for j in cs])))
        if is_candidate(t):
            cand_idx.append(i)
    return out


class Ranker(nn.Module):
    def __init__(self, nf, nt, ctx=0):
        super().__init__()
        self.ctx = ctx
        h = 64 if ctx else 0
        if ctx:
            self.pt = nn.Sequential(nn.Dropout(0.2), nn.Linear(ctx, h))
            self.pc = nn.Sequential(nn.Dropout(0.2), nn.Linear(ctx, h))
        self.pair = nn.Sequential(nn.Linear(nf + nt + 2 * h, 128), nn.ReLU(), nn.Linear(128, 64), nn.ReLU(), nn.Linear(64, 1))
        self.new = nn.Sequential(nn.Linear(nt + h, 64), nn.ReLU(), nn.Linear(64, 1))

    def forward(self, pf, tf, mask, vt=None, vc=None):
        """pf [B, W, nf], tf [B, nt], mask [B, W], vt [B, ctx], vc [B, W, ctx] -> logits [B, W+1] (last = new)"""
        parts = [pf, tf.unsqueeze(1).expand(-1, pf.shape[1], -1)]
        nt = tf
        if self.ctx:
            ht, hc = self.pt(vt), self.pc(vc)
            parts += [ht.unsqueeze(1) * hc, hc]
            nt = torch.cat([tf, ht], -1)
        s = self.pair(torch.cat(parts, -1)).squeeze(-1).masked_fill(~mask, -1e9)
        return torch.cat([s, self.new(nt)], -1)


VEC = [None]                                           # the corpus's word vectors on the device, row -1 = zeros


def gather(insts, W, device):
    V = VEC[0]
    if V is None:
        return None, None
    ti = torch.tensor([x[5][0] for x in insts], device=device)
    ci = torch.full((len(insts), W), -1, dtype=torch.long)
    for b, x in enumerate(insts):
        if x[5][1]:
            ci[b, :len(x[5][1])] = torch.tensor(x[5][1])
    return V[ti].float(), V[ci.to(device)].float()


def batchify(insts, device):
    W = max(1, max(len(x[1]) for x in insts))
    nf = next((len(x[2][0]) for x in insts if x[2]), n_feats())
    pf = torch.zeros(len(insts), W, nf); tf = torch.tensor([x[3] for x in insts]); mask = torch.zeros(len(insts), W, dtype=torch.bool)
    gold = torch.zeros(len(insts), W + 1, dtype=torch.bool)
    for b, (_, cs, rows, _, g, _v) in enumerate(insts):
        if rows:
            pf[b, :len(rows)] = torch.tensor(rows); mask[b, :len(rows)] = True
            gold[b, :len(rows)] = torch.tensor(g)
        if not any(g):
            gold[b, W] = True
    vt, vc = gather(insts, W, device)
    return pf.to(device), tf.to(device), mask.to(device), gold.to(device), vt, vc


def n_feats():
    return len(pair_feats({"cls": "pron", "lex": "", "num": "", "gen": "", "per": "", "rel": "", "clause": "", "key": 0, "head": None, "quote": ""},
                    {"cls": "noun", "num": "", "gen": "", "per": "", "rel": "", "clause": "", "key": 1, "head": None, "quote": "", "lex": ""},
                    0, 1, 0, 0))


NF = None


def loss_fn(logits, gold):
    lp = torch.log_softmax(logits, -1)
    return -(torch.logsumexp(lp.masked_fill(~gold, -1e9), -1)).mean()


def train(epochs=15, seed=1, animacy=False, context=False):
    random.seed(seed); torch.manual_seed(seed)
    USE_ANIM[0] = animacy
    NF = n_feats()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    books = tanakh_parts()
    ctx = attach_vectors(books, "tanakh", tanakh_verses(), device, lambda p: p["w"]) if context else 0
    if animacy:
        ANIM.update(animacy_tables({b: [p for p in ps if split_of(b, p["chapter"]) == "train"] for b, ps in books.items()}))
    data = {"train": [], "dev": [], "test": []}
    for b, parts in books.items():
        by = collections.defaultdict(list)
        for x in instances(parts):
            t = parts[x[0]]
            data[split_of(b, t["chapter"])].append((x, t))
    print({k: len(v) for k, v in data.items()}, "features", NF)
    nt = len(data["train"][0][0][3])
    model = Ranker(NF, nt, ctx).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    tr = [x for x, _ in data["train"]]
    for ep in range(1, epochs + 1):
        model.train(); random.shuffle(tr); tot = 0.0
        for k in range(0, len(tr), 256):
            pf, tf, mask, gold, vt, vc = batchify(tr[k:k + 256], device)
            loss = loss_fn(model(pf, tf, mask, vt, vc), gold)
            opt.zero_grad(); loss.backward(); opt.step(); tot += loss.item()
        print(f"epoch {ep} loss {tot / (len(tr) / 256):.4f} dev {score(model, data['dev'], device)['all']}")
    WORK.mkdir(parents=True, exist_ok=True)
    torch.save({"state": model.state_dict(), "nf": NF, "nt": nt, "epochs": epochs, "seed": seed, "anim": ANIM if animacy else None,
                "ctx": ctx}, WORK / "ranker.pt")
    res = score(model, data["test"], device)
    (WORK / "score-test.json").write_text(json.dumps(res, indent=1) + "\n")
    print("test", json.dumps(res))


@torch.no_grad()
def predict(model, insts, device):
    model.eval(); out = []
    for k in range(0, len(insts), 512):
        chunk = insts[k:k + 512]
        pf, tf, mask, _, vt, vc = batchify(chunk, device)
        pr = torch.softmax(model(pf, tf, mask, vt, vc), -1)
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
    ANALYSIS_OF[0] = release
    calib = json.loads((WORK / "calibration.json").read_text())["bins"]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    ck = torch.load(WORK / "ranker.pt", map_location=device)
    model = Ranker(ck["nf"], ck["nt"], ck.get("ctx", 0)).to(device); model.load_state_dict(ck["state"])
    if ck.get("anim"):
        USE_ANIM[0] = True
        ANIM.update(ck["anim"])
    build = {"model": "ranker.pt", "sha256": hashlib.sha256((WORK / "ranker.pt").read_bytes()).hexdigest(),
             "tanakh_test": json.loads((WORK / "score-test.json").read_text()), "calibration": calib, "editions": {}}
    for ed in ("heb_scg", "heb_mod"):
        books = nt_parts(release, ed)
        if ck.get("ctx"):
            attach_vectors(books, ed, nt_verses(release, ed), device, lambda p: p["key"][:4])
        rows, n = [], collections.Counter()
        for b, parts in books.items():
            insts = instances(parts, with_gold=False)
            pred = predict(model, insts, device)
            ref = {}                                         # part index -> resolved referent
            for (i, cs, _, _, _, _), (j, p) in zip(insts, pred):
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
                       "referent_p_calibrated": None if prob is None else calibrated(prob, calib),
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
                ("referent_p", pa.float32()), ("referent_p_calibrated", pa.float32()), ("antecedent_i", pa.int16()), ("antecedent_part", pa.int8()),
                ("antecedent_verse", pa.string()), ("model_antecedent_p", pa.float32()), ("model_referent", pa.string()),
                ("model_agree", pa.bool_())]
        (out / ed).mkdir(parents=True, exist_ok=True)
        fp = out / ed / "referents.parquet"
        pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema(cols)), fp, compression="zstd")
        build["editions"][ed] = {"rows": len(rows), "counts": dict(sorted(n.items())),
                                 "model_vs_linked": round(n["check_agree"] / max(1, n["check_n"]), 4),
                                 "sha256": hashlib.sha256(fp.read_bytes()).hexdigest()}
        print(f"[hebrew_nt_referents] {ed}: {len(rows)} rows; {dict(sorted(n.items()))}")
    cross_edition(out, build)
    (out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n")


def greek_of(ed):
    """analysis part key -> the Greek words (k1 grc t) the strict links tie it to"""
    words = {w["t"]: w for w in pq.read_table(K1 / ed / "words.parquet", columns=["t", "book", "chapter", "verse", "w"]).to_pylist()}
    npart = collections.defaultdict(list)
    for p in pq.read_table(K1 / ed / "pieces.parquet", columns=["t", "n"]).to_pylist():
        npart[p["t"]].append(p["n"])
    out = collections.defaultdict(set)
    for l in pq.read_table(K1 / ed / "links.parquet", columns=["t", "n", "other", "s", "basis"]).to_pylist():
        if l["other"] != "grc" or l["basis"] != "linked":
            continue
        w = words.get(l["t"])
        if w is not None:
            out[(w["book"], w["chapter"], w["verse"], w["w"] - 1, l["n"])].add(l["s"])
    return out


def cross_edition(out: Path, build: dict):
    eds = ("heb_scg", "heb_mod")
    tabs = {ed: pq.read_table(out / ed / "referents.parquet") for ed in eds}
    by_greek = {}
    for ed in eds:
        g = greek_of(ed)
        rows = tabs[ed].to_pylist()
        # the analysis part number of a k1 piece n: the n-th part with letters (as nt_parts maps them)
        parts = collections.defaultdict(list)
        for r in pq.read_table(ANALYSIS_OF[0] / ed / "words.parquet", columns=["book", "chapter", "verse", "i", "part", "text", "source"]).to_pylist():
            if r["source"] is not None and r["text"]:
                parts[(r["book"], r["chapter"], r["verse"], r["i"])].append(r["part"])
        m = collections.defaultdict(set)
        for (b, ch, v, i, n), gs in g.items():
            ps = sorted(parts.get((b, ch, v, i), []))
            if 0 < n <= len(ps):
                for x in gs:
                    m[(b, ch, v, i, ps[n - 1])].add(x)
        by_greek[ed] = (rows, m)
    for ed in eds:
        other = eds[1] if ed == eds[0] else eds[0]
        rows, m = by_greek[ed]
        orows, om = by_greek[other]
        ref_by_g = collections.defaultdict(set)
        for r in orows:
            if r["referent"] and not r["referent"].startswith("x:"):
                for x in om.get((r["book"], r["chapter"], r["verse"], r["i"], r["part"]), ()):
                    ref_by_g[(r["target"], x)].add(r["referent"])
        oref, agree, n = [], [], collections.Counter()
        for r in rows:
            gs = m.get((r["book"], r["chapter"], r["verse"], r["i"], r["part"]), ())
            cand = set().union(*[ref_by_g.get((r["target"], x), set()) for x in gs]) if gs else set()
            mine = r["referent"] if r["referent"] and not r["referent"].startswith("x:") else None
            if cand and mine:
                o = mine if mine in cand else sorted(cand)[0]
                oref.append(o); agree.append(o == mine)
                n[r["referent_basis"] + "_n"] += 1; n[r["referent_basis"]] += o == mine
            else:
                oref.append(sorted(cand)[0] if cand else None); agree.append(None)
        t = tabs[ed].append_column("other_edition_referent", pa.array(oref, pa.string())).append_column("editions_agree", pa.array(agree, pa.bool_()))
        fp = out / ed / "referents.parquet"
        pq.write_table(t, fp, compression="zstd")
        build["editions"][ed]["editions_agree"] = {k: {"n": n[k + "_n"], "agree": round(n[k] / n[k + "_n"], 4)}
                                                   for k in ("linked", "speech", "model") if n[k + "_n"]}
        build["editions"][ed]["sha256"] = hashlib.sha256(fp.read_bytes()).hexdigest()
        print(f"[hebrew_nt_referents] {ed}: editions agree {build['editions'][ed]['editions_agree']}")


ANALYSIS_OF = [None]
CALIB_BINS = (0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.01)


def calibrate():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    ck = torch.load(WORK / "ranker.pt", map_location=device)
    model = Ranker(ck["nf"], ck["nt"], ck.get("ctx", 0)).to(device); model.load_state_dict(ck["state"])
    if ck.get("anim"):
        USE_ANIM[0] = True; ANIM.update(ck["anim"])
    data = []
    books = tanakh_parts()
    if ck.get("ctx"):
        attach_vectors(books, "tanakh", tanakh_verses(), device, lambda p: p["w"])
    for b, parts in books.items():
        for x in instances(parts):
            if split_of(b, parts[x[0]]["chapter"]) in ("dev", "test"):
                data.append(x)
    pred = predict(model, data, device)
    bins = collections.defaultdict(lambda: [0, 0])
    for x, (j, p) in zip(data, pred):
        g = x[4]
        ok = (not any(g)) if j is None else g[x[1].index(j)]
        k = max(i for i, lo in enumerate(CALIB_BINS[:-1]) if p >= lo)
        bins[k][0] += ok; bins[k][1] += 1
    ks = sorted(bins)
    blocks = [[bins[k][0], bins[k][1], [k]] for k in ks]        # pool adjacent bins until the right-share never falls
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] / blocks[i][1] > blocks[i + 1][0] / blocks[i + 1][1]:
            blocks[i] = [blocks[i][0] + blocks[i + 1][0], blocks[i][1] + blocks[i + 1][1], blocks[i][2] + blocks[i + 1][2]]
            del blocks[i + 1]
            i = max(0, i - 1)
        else:
            i += 1
    share = {k: round(a / n, 4) for a, n, kk in blocks for k in kk}
    table = [{"from": CALIB_BINS[k], "to": min(1.0, CALIB_BINS[k + 1]), "n": bins[k][1], "right_raw": round(bins[k][0] / bins[k][1], 4),
              "right": share[k]} for k in ks]
    (WORK / "calibration.json").write_text(json.dumps({"targets": len(data), "bins": table}, indent=1) + "\n")
    for r in table:
        print(r)


def calibrated(p, table):
    for r in table:
        if r["from"] <= p < r["to"] or (p >= r["from"] and r["to"] >= 1.0):
            return r["right"]
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train"); t.add_argument("--epochs", type=int, default=15); t.add_argument("--seed", type=int, default=1)
    t.add_argument("--animacy", action="store_true"); t.add_argument("--context", action="store_true")
    sub.add_parser("calibrate")
    e = sub.add_parser("export"); e.add_argument("--release", type=Path, required=True); e.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "train":
        train(a.epochs, a.seed, a.animacy, a.context)
    elif a.cmd == "calibrate":
        calibrate()
    else:
        export(a.release, a.out)


if __name__ == "__main__":
    main()
