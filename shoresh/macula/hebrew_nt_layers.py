"""Phrase relations, argument roles, referent kind, and clause marks for the Hebrew New Testaments (request 39, rows 3-7).

A tagger trained on the MACULA Hebrew Tanakh in the source-examples format (k1/hbo: the MACULA tree as head and relation per
piece, the constituents' semantic role and reference status, the referent kind of `who`, and the clause marks), applied to
the words and clause segments of hebrew-nt-analysis v0.2. Every value it writes is a model value (basis `model`), with
its probability. Beside each value stands the value k1 v1.9 carries from the Greek through the word links, where there is
one, and whether the two agree. No language model is called; nothing is read from the Greek to make a value.

Per piece (a word part with letters; the article hidden after a preposition has none and is no piece, as in k1):
  - `head`: the piece it depends on in the verse, or none (the verse's root), chosen by a biaffine scorer;
  - `rel`: the k1 relation (MACULA's rule and slot such as `NPofNP:1`, `PrepNp:0`, or the clause role `s`, `o`, `pp`, ...;
    the 80 commonest, else `other`);
  - on the piece that heads a constituent (the piece of its head word whose head lies outside the word): `sem_role`
    and `ref_status` (k1 constituents), else `-`;
  - `who_kind`: the kind of the referent (`person`, `deity`, `group`, `place`, `realia`, `fauna`, `flora`), else `-`.
Per clause segment (a clause of k1/hbo is its words whose innermost clause it is; an NT segment is first_i..last_i):
  force, polarity, mood, time, time_abs, aspect, relation, voice, negator, connective (k1 clause marks; `-` = none).

Model: dicta-il/dictabert reads the unpointed words; a character BiGRU reads each word and each piece with its points
(without them for the unpointed model); a BiLSTM over the words, then one over the pieces (piece class, place in the
word and the word's number of pieces added); biaffine head scores; label heads; clause pooling of the segment's words
(mean, first word, first verb word).

  cd shoresh && .venv/bin/python -I macula/hebrew_nt_layers.py prep
  cd shoresh && .venv/bin/python -I macula/hebrew_nt_layers.py train [--unpointed] [--epochs 3]
  cd shoresh && .venv/bin/python -I macula/hebrew_nt_layers.py score [--unpointed] [--split test]
  cd shoresh && .venv/bin/python -I macula/hebrew_nt_layers.py export --edition heb_scg --out DIR

Splits as clause_tagger (test: Gen 37-45, Ruth, Jonah, 1 Sam 1-10, Deut 5-11; dev: Judges 1-5).
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyarrow as pa
import pyarrow.parquet as pq

from macula.clause_tagger import pointed, unpointed, split_of

HERE = Path(__file__).resolve().parent
K1 = HERE / "data" / "source-examples" / "k1"
OUT = HERE / "data" / "hebrew-nt-layers"
ANALYSIS = HERE / "data" / "clause-tagger" / "export"
ENCODER = "dicta-il/dictabert"
MARKS = ("force", "polarity", "mood", "time", "time_abs", "aspect", "relation", "voice", "negator", "connective")
PIECE_HEADS = ("rel", "sem_role", "ref_status", "who_kind")
N_REL, N_CONN = 80, 30
MAX_CHARS = 24
MAX_PIECE_CHARS = 16
MAX_PIECES = 6


def mark_value(m, k):
    v = m.get(k)
    if v is None:
        return "-"
    if isinstance(v, list):
        return "+".join(v) if v else "-"
    return str(v)


# ---------------------------------------------------------------- data
def head_piece(pieces, t):
    """the piece of word t that heads it: whose head lies outside the word (a stem first), else the stem"""
    out = [p for p in pieces if p["head_t"] != t]
    pool = out or pieces
    stems = [p for p in pool if p["kind"] == "stem"]
    return (stems or pool)[0]["n"]


def prep():
    words = pq.read_table(K1 / "hbo" / "words.parquet").to_pylist()
    pieces = collections.defaultdict(list)
    for p in pq.read_table(K1 / "hbo" / "pieces.parquet").to_pylist():
        pieces[p["t"]].append(p)
    cons = collections.defaultdict(dict)                            # word t -> (sem_role, ref_status) of a constituent it heads
    for c in pq.read_table(K1 / "hbo" / "constituents.parquet").to_pylist():
        if c["head"]:
            cons[c["head"]] = (c["sem_role"] or "-", c["ref_status"] or "-")
    clauses = {c["clause"]: c for c in pq.read_table(K1 / "hbo" / "clauses.parquet").to_pylist()}
    verses = collections.OrderedDict()
    for w in words:
        verses.setdefault((w["book"], w["chapter"], w["verse"]), []).append(w)
    OUT.mkdir(parents=True, exist_ok=True)
    n = collections.Counter()
    with (OUT / "verses.jsonl").open("w") as f:
        for (b, ch, v), ws in verses.items():
            ws.sort(key=lambda w: w["w"])
            idx = {}                                                # (t, n) -> verse piece index from 1
            for w in ws:
                for p in sorted(pieces[w["t"]], key=lambda p: p["n"]):
                    idx[(w["t"], p["n"])] = len(idx) + 1
            out_words, cl_words = [], collections.defaultdict(list)
            for wi, w in enumerate(ws):
                ps = sorted(pieces[w["t"]], key=lambda p: p["n"])
                hn = head_piece(ps, w["t"]) if ps else None
                sem, ref = cons.get(w["t"], ("-", "-"))
                pl = []
                for p in ps:
                    is_head = p["n"] == hn
                    pl.append({"text": pointed(p["text"]) or p["text"], "class": p["class"] or "-",
                               "head": idx.get((p["head_t"], p["head_n"]), 0) if p["head_t"] else 0,
                               "rel": p["rel"] or "-", "sem_role": sem if is_head else "-",
                               "ref_status": ref if is_head else "-",
                               "who_kind": (p["who"] or "").split(":")[0] or "-"})
                out_words.append({"text": pointed(w["text"]) or w["text"], "pieces": pl})
                if w["clause"]:
                    cl_words[w["clause"]].append(wi)
            cls = []
            for cid, wis in cl_words.items():
                c = clauses.get(cid)
                if not c:
                    continue
                m = json.loads(c["marks"] or "{}")
                cls.append({"words": wis, "marks": {k: mark_value(m, k) for k in MARKS}})
            split = split_of(b, ch)
            n[split] += 1
            f.write(json.dumps({"ref": f"{b} {ch}:{v}", "split": split, "words": out_words, "clauses": cls},
                               ensure_ascii=False) + "\n")
    print(f"[hebrew_nt_layers] {dict(n)} verses -> {OUT / 'verses.jsonl'}")


def load(split=None, plain=False):
    rows = [json.loads(l) for l in (OUT / "verses.jsonl").open()]
    rows = [r for r in rows if split is None or r["split"] == split]
    if plain:
        for r in rows:
            for w in r["words"]:
                w["text"] = unpointed(w["text"])
                for p in w["pieces"]:
                    p["text"] = unpointed(p["text"])
    return [r for r in rows if r["words"] and sum(len(w["pieces"]) for w in r["words"])]


def make_vocab(tr):
    c = {h: collections.Counter() for h in PIECE_HEADS + MARKS + ("class",)}
    for v in tr:
        for w in v["words"]:
            for p in w["pieces"]:
                for h in PIECE_HEADS + ("class",):
                    c[h][p[h]] += 1
        for cl in v["clauses"]:
            for k in MARKS:
                c[k][cl["marks"][k]] += 1
    voc = {"class": ["?"] + sorted(c["class"]), "rel": [x for x, _ in c["rel"].most_common(N_REL)] + ["other"],
           "connective": [x for x, _ in c["connective"].most_common(N_CONN)] + ["other"]}
    for h in ("sem_role", "ref_status", "who_kind") + tuple(k for k in MARKS if k != "connective"):
        voc[h] = sorted(c[h]) + ["other"]
    return voc


# ---------------------------------------------------------------- model
def build_model(encoder, chars, voc):
    import torch
    from torch import nn
    from transformers import AutoModel

    class Layers(nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = AutoModel.from_pretrained(encoder)
            self.char_emb = nn.Embedding(len(chars) + 2, 48, padding_idx=0)
            self.char_rnn = nn.GRU(48, 64, batch_first=True, bidirectional=True)
            self.pchar_rnn = nn.GRU(48, 64, batch_first=True, bidirectional=True)
            self.mix = nn.LSTM(self.encoder.config.hidden_size + 128, 256, batch_first=True, bidirectional=True)
            self.cls_emb = nn.Embedding(len(voc["class"]), 32)
            self.pos_emb = nn.Embedding(MAX_PIECES + 1, 8)
            self.cnt_emb = nn.Embedding(MAX_PIECES + 1, 8)
            self.pmix = nn.LSTM(512 + 128 + 48, 256, batch_first=True, bidirectional=True)
            self.drop = nn.Dropout(0.2)
            self.arc_dep = nn.Linear(512, 256)
            self.arc_head = nn.Linear(512, 256)
            self.root = nn.Parameter(torch.zeros(512))
            self.biaf = nn.Parameter(torch.zeros(256, 256))
            self.arc_bias = nn.Linear(256, 1)
            self.rel = nn.Sequential(nn.Linear(1024, 256), nn.ReLU(), nn.Linear(256, len(voc["rel"])))
            self.piece_heads = nn.ModuleDict({h: nn.Linear(512, len(voc[h])) for h in ("sem_role", "ref_status", "who_kind")})
            self.clause = nn.Sequential(nn.Linear(1536, 512), nn.ReLU(), nn.Dropout(0.2))
            self.mark_heads = nn.ModuleDict({k: nn.Linear(512, len(voc[k])) for k in MARKS})

        def forward(self, x):
            enc = self.encoder(input_ids=x["input_ids"], attention_mask=x["attention_mask"]).last_hidden_state
            idx = x["first"].clamp(min=0).unsqueeze(-1).expand(-1, -1, enc.size(-1))
            words = enc.gather(1, idx)
            B, W, C = x["char_ids"].shape
            _, hc = self.char_rnn(self.char_emb(x["char_ids"].view(B * W, C)))
            wv, _ = self.mix(self.drop(torch.cat([words, torch.cat([hc[0], hc[1]], -1).view(B, W, 128)], -1)))
            wv = self.drop(wv)                                                     # B x W x 512
            P = x["p_word"].size(1)
            pw = wv.gather(1, x["p_word"].clamp(min=0).unsqueeze(-1).expand(-1, -1, 512))
            _, hp = self.pchar_rnn(self.char_emb(x["p_chars"].view(B * P, -1)))
            pv = torch.cat([pw, torch.cat([hp[0], hp[1]], -1).view(B, P, 128), self.cls_emb(x["p_class"]),
                            self.pos_emb(x["p_pos"]), self.cnt_emb(x["p_cnt"])], -1)
            pv, _ = self.pmix(self.drop(pv))
            pv = self.drop(pv)                                                     # B x P x 512
            cand = torch.cat([self.root.view(1, 1, -1).expand(B, 1, -1), pv], 1)  # B x (P+1) x 512, 0 = root
            d = torch.relu(self.arc_dep(pv)); h = torch.relu(self.arc_head(cand))
            arc = torch.einsum("bpi,ij,bqj->bpq", d, self.biaf, h) + self.arc_bias(h).transpose(1, 2)
            mask = torch.cat([torch.ones(B, 1, dtype=torch.bool, device=pv.device), x["p_mask"]], 1)
            arc = arc.masked_fill(~mask.unsqueeze(1), -1e4)
            out = {"arc": arc, "pv": pv, "cand": cand}
            for k, hd in self.piece_heads.items():
                out[k] = hd(pv)
            if x["c_words"].numel():
                cw = x["c_words"]                                                  # N x 3 (batch, word mask idx...) -> pooled
                pooled = torch.cat([(wv[cw[:, 0]] * x["c_mask"].unsqueeze(-1)).sum(1) / x["c_mask"].sum(1, keepdim=True).clamp(min=1),
                                    wv[cw[:, 0], cw[:, 1]], wv[cw[:, 0], cw[:, 2]]], -1)
                z = self.clause(pooled)
                for k, hd in self.mark_heads.items():
                    out["m_" + k] = hd(z)
            return out

        def rel_logits(self, out, heads):
            hv = out["cand"].gather(1, heads.clamp(min=0).unsqueeze(-1).expand(-1, -1, 512))
            return self.rel(torch.cat([out["pv"], hv], -1))

    return Layers()


class Batcher:
    def __init__(self, tok, chars, voc):
        self.tok, self.voc = tok, voc
        self.cid = {c: i + 2 for i, c in enumerate(chars)}
        self.ix = {h: {x: i for i, x in enumerate(v)} for h, v in voc.items()}

    def lab(self, h, x):
        d = self.ix[h]
        return d.get(x, d.get("other", 0))

    def __call__(self, verses, device, gold=True):
        import torch
        texts = [[unpointed(w["text"]) or "-" for w in v["words"]] for v in verses]
        enc = self.tok(texts, is_split_into_words=True, truncation=True, max_length=512, padding=True, return_tensors="pt")
        B, W = len(verses), max(len(t) for t in texts)
        P = max(sum(len(w["pieces"]) for w in v["words"]) for v in verses)
        first = torch.full((B, W), -1, dtype=torch.long)
        for b in range(B):
            seen = set()
            for t, wid in enumerate(enc.word_ids(b)):
                if wid is not None and wid not in seen:
                    seen.add(wid); first[b, wid] = t
        chars = torch.zeros((B, W, MAX_CHARS), dtype=torch.long)
        p_word = torch.full((B, P), -1, dtype=torch.long)
        p_chars = torch.zeros((B, P, MAX_PIECE_CHARS), dtype=torch.long)
        p_class = torch.zeros((B, P), dtype=torch.long); p_pos = torch.zeros((B, P), dtype=torch.long)
        p_cnt = torch.zeros((B, P), dtype=torch.long); p_mask = torch.zeros((B, P), dtype=torch.bool)
        g = {k: torch.full((B, P), -100, dtype=torch.long) for k in ("arc",) + PIECE_HEADS}
        c_rows, c_masks, c_gold = [], [], {k: [] for k in MARKS}
        for b, v in enumerate(verses):
            k = 0
            for i, w in enumerate(v["words"]):
                for j, c in enumerate(w["text"][:MAX_CHARS]):
                    chars[b, i, j] = self.cid.get(c, 1)
                for j, p in enumerate(w["pieces"]):
                    p_word[b, k] = i if first[b, i] >= 0 else -1
                    for q, c in enumerate(p["text"][:MAX_PIECE_CHARS]):
                        p_chars[b, k, q] = self.cid.get(c, 1)
                    p_class[b, k] = self.ix["class"].get(p["class"], 0)
                    p_pos[b, k] = min(j, MAX_PIECES); p_cnt[b, k] = min(len(w["pieces"]), MAX_PIECES)
                    p_mask[b, k] = first[b, i] >= 0
                    if gold and "rel" in p and p_mask[b, k]:
                        g["arc"][b, k] = p["head"] if p["head"] <= P else 0
                        for h in PIECE_HEADS:
                            g[h][b, k] = self.lab(h, p[h])
                    k += 1
            for cl in v.get("clauses", []):
                ws = [i for i in cl["words"] if i < W and first[b, i] >= 0]
                if not ws:
                    continue
                verb = next((i for i in ws if any(p["class"] == "verb" for p in v["words"][i]["pieces"])), ws[0])
                m = torch.zeros(W); m[ws] = 1
                c_rows.append([b, ws[0], verb]); c_masks.append(m)
                if gold and "marks" in cl:
                    for kk in MARKS:
                        c_gold[kk].append(self.lab(kk, cl["marks"][kk]))
        x = {"input_ids": enc["input_ids"], "attention_mask": enc["attention_mask"], "first": first, "char_ids": chars,
             "p_word": p_word, "p_chars": p_chars, "p_class": p_class, "p_pos": p_pos, "p_cnt": p_cnt, "p_mask": p_mask,
             "c_words": torch.tensor(c_rows, dtype=torch.long).view(-1, 3),
             "c_mask": torch.stack(c_masks) if c_masks else torch.zeros(0, W)}
        x = {k: t.to(device) for k, t in x.items()}
        gd = {k: t.to(device) for k, t in g.items()}
        for kk in MARKS:
            gd["m_" + kk] = torch.tensor(c_gold[kk], dtype=torch.long, device=device)
        return x, gd


def model_path(plain):
    return OUT / f"model-{'unpointed' if plain else 'pointed'}.pt"


def train(epochs, batch, seed, plain):
    import torch
    from transformers import AutoTokenizer, get_linear_schedule_with_warmup
    random.seed(seed); torch.manual_seed(seed)
    tr, dev = load("train", plain), load("dev", plain)
    chars = sorted({c for v in tr for w in v["words"] for c in w["text"]})
    voc = make_vocab(tr)
    tok = AutoTokenizer.from_pretrained(ENCODER)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model(ENCODER, chars, voc).to(device)
    bat = Batcher(tok, chars, voc)
    enc_p = list(model.encoder.parameters()); rest = [p for n, p in model.named_parameters() if not n.startswith("encoder.")]
    opt = torch.optim.AdamW([{"params": enc_p, "lr": 3e-5}, {"params": rest, "lr": 1e-3}], weight_decay=0.01)
    steps = epochs * ((len(tr) + batch - 1) // batch)
    sched = get_linear_schedule_with_warmup(opt, int(0.06 * steps), steps)
    ce = torch.nn.CrossEntropyLoss(ignore_index=-100)
    scaler = torch.amp.GradScaler()
    best = -1.0
    for ep in range(epochs):
        model.train()
        random.shuffle(tr)
        tr.sort(key=lambda v: len(v["words"]) // 8 + random.random())
        order = list(range(0, len(tr), batch)); random.shuffle(order)
        total = 0.0
        for k, i in enumerate(order):
            x, g = bat(tr[i:i + batch], device)
            with torch.autocast("cuda", dtype=torch.float16, enabled=device.type == "cuda"):
                out = model(x)
                rl = model.rel_logits(out, g["arc"])
                loss = ce(out["arc"].float().flatten(0, 1), g["arc"].flatten()) + ce(rl.float().flatten(0, 1), g["rel"].flatten())
                for h in ("sem_role", "ref_status", "who_kind"):
                    loss = loss + ce(out[h].float().flatten(0, 1), g[h].flatten())
                for kk in MARKS:
                    if "m_" + kk in out and g["m_" + kk].numel():
                        loss = loss + 0.5 * ce(out["m_" + kk].float(), g["m_" + kk])
            opt.zero_grad()
            scaler.scale(loss).backward()
            scaler.unscale_(opt); torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt); scaler.update(); sched.step()
            total += loss.item()
            if k % 200 == 0:
                print(f"[hebrew_nt_layers] epoch {ep + 1} batch {k}/{len(order)} loss {total / (k + 1):.3f}", flush=True)
        m = metrics(dev, predict(model, bat, dev, device), voc)
        print(f"[hebrew_nt_layers] epoch {ep + 1} dev: " + ", ".join(f"{k} {v:.3f}" for k, v in m.items()), flush=True)
        if m["uas"] + m["las"] > best:
            best = m["uas"] + m["las"]
            torch.save({"state": model.state_dict(), "chars": chars, "vocab": voc, "epoch": ep + 1, "dev": m, "seed": seed,
                        "unpointed": plain, "encoder": ENCODER}, model_path(plain))
    print(f"[hebrew_nt_layers] best dev -> {model_path(plain)}")


def predict(model, bat, verses, device, batch=32):
    """per verse: pieces [(head, rel, rel_p, sem, sem_p, ref, ref_p, who, who_p)] in order; clauses [{mark: (v, p)}]"""
    import torch
    model.eval()
    res = []
    with torch.no_grad():
        for i in range(0, len(verses), batch):
            chunk = verses[i:i + batch]
            x, _ = bat(chunk, device, gold=False)
            with torch.autocast("cuda", dtype=torch.float16, enabled=device.type == "cuda"):
                out = model(x)
                heads = out["arc"].float().argmax(-1)
                rl = model.rel_logits(out, heads).float()
            prob = {"rel": torch.softmax(rl, -1)}
            for h in ("sem_role", "ref_status", "who_kind"):
                prob[h] = torch.softmax(out[h].float(), -1)
            arc_p = torch.softmax(out["arc"].float(), -1).max(-1).values
            mp = {k: torch.softmax(out["m_" + k].float(), -1).cpu() for k in MARKS if "m_" + k in out}
            ci = 0
            for b, v in enumerate(chunk):
                n = sum(len(w["pieces"]) for w in v["words"])
                ps = []
                for k in range(n):
                    row = {"head": int(heads[b, k]), "head_p": round(float(arc_p[b, k]), 3)}
                    for h in PIECE_HEADS:
                        pv, ix = prob[h][b, k].max(-1)
                        row[h], row[h + "_p"] = bat.voc[h][int(ix)], round(float(pv), 3)
                    ps.append(row)
                cls = []
                for cl in v.get("clauses", []):
                    ws = [j for j in cl["words"] if j < len(v["words"])]
                    if not ws or not x["c_words"].numel():
                        cls.append(None); continue
                    row = {}
                    for kk in MARKS:
                        pv, ix = mp[kk][ci].max(-1)
                        row[kk] = (bat.voc[kk][int(ix)], round(float(pv), 3))
                    cls.append(row); ci += 1
                res.append({"pieces": ps, "clauses": cls})
    return res


def metrics(gold, pred, voc):
    c = collections.Counter()
    for v, p in zip(gold, pred):
        gp = [q for w in v["words"] for q in w["pieces"]]
        for g, r in zip(gp, p["pieces"]):
            c["n"] += 1
            ok = r["head"] == g["head"]
            c["uas"] += ok
            gr = g["rel"] if g["rel"] in voc["rel"] else "other"
            c["las"] += ok and r["rel"] == gr
            c["rel"] += r["rel"] == gr
            for h in ("sem_role", "ref_status", "who_kind"):
                gv = g[h] if g[h] in voc[h] else "other"
                if gv != "-" or r[h] != "-":
                    c[h + "_n"] += 1; c[h] += r[h] == gv
        for cl, r in zip(v["clauses"], p["clauses"]):
            if r is None:
                continue
            c["cl_n"] += 1
            for kk in MARKS:
                gv = cl["marks"][kk] if cl["marks"][kk] in voc[kk] else "other"
                c["m_" + kk] += r[kk][0] == gv
    m = {"uas": c["uas"] / max(1, c["n"]), "las": c["las"] / max(1, c["n"]), "rel": c["rel"] / max(1, c["n"])}
    for h in ("sem_role", "ref_status", "who_kind"):
        m[h] = c[h] / max(1, c[h + "_n"])                           # over pieces where gold or prediction is not "-"
    for kk in MARKS:
        m[kk] = c["m_" + kk] / max(1, c["cl_n"])
    return m


def load_model(plain):
    import torch
    from transformers import AutoTokenizer
    ck = torch.load(model_path(plain), map_location="cpu", weights_only=False)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model(ck["encoder"], ck["chars"], ck["vocab"])
    model.load_state_dict(ck["state"])
    return model.to(device), Batcher(AutoTokenizer.from_pretrained(ck["encoder"]), ck["chars"], ck["vocab"]), device, ck


def score(split, plain):
    model, bat, device, ck = load_model(plain)
    rows = load(split, plain)
    m = metrics(rows, predict(model, bat, rows, device), ck["vocab"])
    print(json.dumps({"split": split, "unpointed": plain, "epoch": ck["epoch"], **{k: round(v, 4) for k, v in m.items()}}))
    return m


# ---------------------------------------------------------------- the Hebrew NTs
def nt_verses(ed, plain):
    words = collections.OrderedDict()
    for r in pq.read_table(ANALYSIS / ed / "words.parquet").to_pylist():
        if r["source"] is None:
            continue
        words.setdefault((r["book"], r["chapter"], r["verse"]), collections.OrderedDict()).setdefault(r["i"], []).append(r)
    segs = collections.defaultdict(list)
    for s in pq.read_table(ANALYSIS / ed / "clauses.parquet").to_pylist():
        segs[(s["book"], s["chapter"], s["verse"])].append(s)
    norm = unpointed if plain else pointed
    out = []
    for vk, ws in words.items():
        wl, keys, ipos = [], [], {}
        for i, parts in ws.items():
            parts.sort(key=lambda r: r["part"])
            pl = [{"text": norm(p["text"]) or p["text"], "class": p["class"] or "-"} for p in parts if p["text"]]
            ipos[i] = len(wl)
            wl.append({"text": norm(parts[0]["word"]) or parts[0]["word"], "pieces": pl})
            keys.append([(i, p["part"]) for p in parts if p["text"]])
        cls = []
        for s in segs.get(vk, []):
            wis = [ipos[i] for i in range(s["first_i"], s["last_i"] + 1) if i in ipos]
            cls.append({"words": wis, "seg": s["seg"]})
        out.append({"key": vk, "words": wl, "clauses": cls, "piece_keys": [k for ks in keys for k in ks],
                    "word_i": list(ws.keys())})
    return out


def carried(ed):
    """k1 v1.9 values on the analysis keys: pieces (i, part) -> dict; clauses: word (book, ch, v, i) -> clause marks"""
    an = collections.defaultdict(list)
    for r in pq.read_table(ANALYSIS / ed / "words.parquet").to_pylist():
        if r["source"] is not None and r["text"]:
            an[(r["book"], r["chapter"], r["verse"], r["i"])].append(r["part"])
    words = {w["t"]: w for w in pq.read_table(K1 / ed / "words.parquet").to_pylist()}
    pieces = collections.defaultdict(list)
    for p in pq.read_table(K1 / ed / "pieces.parquet").to_pylist():
        pieces[p["t"]].append(p)

    def key(t, n):
        w = words[t]; wk = (w["book"], w["chapter"], w["verse"], w["w"] - 1)
        parts = sorted(an.get(wk, []))
        return wk + (parts[n - 1],) if 0 < n <= len(parts) else None
    cons = {}
    for c in pq.read_table(K1 / ed / "constituents.parquet").to_pylist():
        if c["head"] and c["head"] in pieces:
            cons[c["head"]] = (c["sem_role"] or "-", c["ref_status"] or "-")
    pv = {}
    for t, ps in pieces.items():
        hn = head_piece(sorted(ps, key=lambda p: p["n"]), t) if ps else None
        for p in ps:
            k = key(t, p["n"])
            if k is None:
                continue
            d = {"who_kind": (p["who"] or "").split(":")[0] or None}
            if p["rel"]:
                d["rel"] = p["rel"]
                d["head"] = key(p["head_t"], p["head_n"]) if p["head_t"] else "root"
            if p["n"] == hn and t in cons:
                d["sem_role"], d["ref_status"] = cons[t]
            pv[k] = d
    cm = {}
    clauses = {c["clause"]: c for c in pq.read_table(K1 / ed / "clauses.parquet").to_pylist()}
    for t, w in words.items():
        c = clauses.get(w["clause"]) if w["clause"] else None
        if c and c["marks"] and c["marks"] != "{}":
            cm[(w["book"], w["chapter"], w["verse"], w["w"] - 1)] = (w["clause"], json.loads(c["marks"]))
    return pv, cm


def export(ed, out, plain):
    model, bat, device, ck = load_model(plain)
    verses = nt_verses(ed, plain)
    pred = predict(model, bat, verses, device)
    pv, cm = carried(ed)
    prow, crow = [], []
    agree = collections.Counter()
    for v, p in zip(verses, pred):
        b, ch, vs = v["key"]
        pk = v["piece_keys"]
        for k, r in enumerate(p["pieces"]):
            i, part = pk[k]
            hi, hp = (pk[r["head"] - 1] if r["head"] > 0 else (None, None))
            row = {"book": b, "chapter": ch, "verse": vs, "i": i, "part": part, "head_i": hi, "head_part": hp,
                   "head_p": r["head_p"]}
            for h in PIECE_HEADS:
                row[h], row[h + "_p"] = r[h], r[h + "_p"]
            g = pv.get((b, ch, vs, i, part), {})
            gh = g.get("head")
            row["head_carried"] = None if gh is None else ("root" if gh == "root" else f"{gh[3]}.{gh[4]}")
            row["head_agree"] = None if gh is None else ((gh == "root" and hi is None) or (gh != "root" and gh[3:] == (hi, hp)))
            for h in PIECE_HEADS:
                gv = g.get(h)
                row[h + "_carried"] = gv
                row[h + "_agree"] = None if gv is None else gv == r[h]
            voc = ck["vocab"]
            for h in ("head",) + PIECE_HEADS:
                a = row[h + "_agree"]
                if a is not None:
                    agree[f"{h}_n"] += 1; agree[h] += a
                    cv = g.get("rel") if h == "head" else g.get(h)      # comparable: the carried value is in the Tanakh scheme
                    if cv in voc["rel" if h == "head" else h] and cv != "other":
                        agree[f"c_{h}_n"] += 1; agree["c_" + h] += a
            prow.append(row)
        for cl, r in zip(v["clauses"], p["clauses"]):
            row = {"book": b, "chapter": ch, "verse": vs, "seg": cl["seg"]}
            src, mk = collections.Counter(), {}
            for j in cl["words"]:                                   # the carried clause most of the segment's words are in
                c = cm.get((b, ch, vs, v["word_i"][j]))
                if c:
                    src[c[0]] += 1; mk[c[0]] = c[1]
            marks = mk[src.most_common(1)[0][0]] if src else None
            for kk in MARKS:
                val, pr = r[kk] if r else (None, None)
                row[kk], row[kk + "_p"] = val, pr
                gv = mark_value(marks, kk) if marks is not None else None
                row[kk + "_carried"] = gv
                row[kk + "_agree"] = None if gv is None or val is None else gv == val
                if row[kk + "_agree"] is not None:
                    agree[f"m_{kk}_n"] += 1; agree["m_" + kk] += row[kk + "_agree"]
                    if gv in ck["vocab"][kk] and gv != "other" and not (kk == "voice" and gv == "-"):
                        agree[f"c_m_{kk}_n"] += 1; agree["c_m_" + kk] += row[kk + "_agree"]
            crow.append(row)
    (out / ed).mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(prow), out / ed / "pieces.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(crow), out / ed / "clauses.parquet", compression="zstd")
    ag = {k: {"n": agree[k + "_n"], "agree": round(agree[k] / agree[k + "_n"], 4)} for k in
          ["head", *PIECE_HEADS] + ["m_" + kk for kk in MARKS] if agree[k + "_n"]}
    agc = {k: {"n": agree["c_" + k + "_n"], "agree": round(agree["c_" + k] / agree["c_" + k + "_n"], 4)} for k in
           ["head", *PIECE_HEADS] + ["m_" + kk for kk in MARKS] if agree["c_" + k + "_n"]}
    cov = {"pieces": len(prow), "clauses": len(crow),
           "pieces_with_carried_head": agree["head_n"], "clauses_with_carried_marks": agree["m_force_n"]}
    print(f"[hebrew_nt_layers] {ed}: {cov}; agreement {ag}; comparable {agc}")
    return {"model": model_path(plain).name, "model_epoch": ck["epoch"], "coverage": cov, "agreement_with_carried": ag,
            "agreement_with_carried_comparable": agc}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["prep", "train", "score", "export"])
    ap.add_argument("--unpointed", action="store_true")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--split", default="test")
    ap.add_argument("--edition")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    if a.cmd == "prep":
        prep()
    elif a.cmd == "train":
        train(a.epochs, a.batch, a.seed, a.unpointed)
    elif a.cmd == "score":
        score(a.split, a.unpointed)
    else:
        r = export(a.edition, a.out, a.edition == "heb_mod" or a.unpointed)
        (a.out / a.edition / "export.json").write_text(json.dumps(r, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
