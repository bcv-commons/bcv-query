"""A clause tagger for pointed biblical-style Hebrew, trained on MACULA Hebrew and our clause layout (for a Hebrew NT such as
Salkinson-Ginsburg, which has no MACULA analysis). No BHSA input.

For each word of a verse it predicts what the clause layout reads from MACULA:
  - `start`: the word opens a new clause segment (as the layout segments the verse);
  - `depth`: the layout's `depth` of the word's segment (clause ancestors in the MACULA tree, within the verse; 0-4);
  - `form`: the verb form of a verb in the word (MACULA lowfat `type`: qatal, wayyiqtol, ... participle, infinitive), or none;
  - `person`: the person of that verb (1, 2, 3), or none;
and for the word that opens a segment, what the layout's rules read of the segment's clause:
  - `parent`: where its parent clause stands in the verse, in segments from this one (-1 the one before, +1 the one after; "none"
    for a clause on the verse's own group);
  - `kind`: VC or NC (MACULA clause class: with or without a verb);
  - `rule`: the MACULA clause rule (constituent order, such as V-S-PP; the 60 most common, others "other");
  - `att`: the MACULA attachment kind where the segment meets an earlier segment of the verse in the tree, the kind rule
    tree_level_inside_verse checks against [tree] trusted ("cjpCLx|1|cl|-", ...; the 300 most common, 95% of the trusted kinds; others "other"; "-" none).
and the word's MACULA parts (prefixes and suffixes are parts of their own, as in MACULA; the article after a preposition is a
part without letters, as in בַּ):
  - `tmpl`: how the pointed word splits into parts, as the parts' lengths in pointed letters ("1,0,5": ב, the article, מָּשִׁיחַ);
  - per part (up to 4): `class` (MACULA word class), `role` (MACULA role of the part, where it heads one) and `lemma` (the 4000
    most common MACULA lemmas; another lemma comes out as the part's own letters), with the Strong's number MACULA gives the lemma.
A word is a space- or maqaf-separated unit, prefixes and suffixes included, as the bibles verse-text tokenizer gives it.

Model: a Hebrew BERT encoder (dicta-il/dictabert or dicta-il/BEREL_3.0; their tokenizers drop the vowel points) reads the
unpointed verse; a small character BiGRU reads each word with its points (which tell wayyiqtol from weyiqtol and much else);
the two are joined per word and four heads classify.

Data: trees-macula.db (words, MACULA Hebrew, CC BY 4.0), lowfat-hbo.db (verb type), lexeme-spine-macula.db (person), and the
clause layout's segments (macula/data/clause-layout/clauses, built by macula.build_clause_layout). Held out for testing: the
chapters of the Parsan comparison (Gen 37-45, Ruth, Jonah, 1 Sam 1-10, Deut 5-11); for development: Judges 1-5.

  python -m macula.clause_tagger prep                       # -> data/clause-tagger/verses.jsonl
  python -m macula.clause_tagger train [--encoder dicta-il/dictabert] [--epochs 4]
  python -m macula.clause_tagger score [--split test] [--lookup]   # the metrics of the Parsan comparison
  python -m macula.clause_tagger tag FILE.txt               # one verse per line -> JSON lines
  python -m macula.clause_tagger export --helloao DIR --edition heb_scg   # a Hebrew NT, word by word as lexeme-aligner counts words

export reads helloAO chapter JSON (DIR/<BOOK>_<chapter>.json), takes each verse's text and its words by bcv-commons/bibles' rule and
tokenizer (macula/vendor_bibles, as lexeme-aligner does), so word i of a verse is the aligner's token i, and writes to
data/clause-tagger/export/<edition>/:
  - words.parquet: one row per word part (book, chapter, verse, i = the aligner's token, part, token, word, text, class, lemma,
    lexeme, strong, role, source, p_split, form, person, seg); the Hebrew verse number some texts carry is a row of class
    "verse-number";
  - clauses.parquet: one row per clause segment (book, chapter, verse, seg, first_i, last_i, depth, parent, kind, rule, att);
  - <BOOK>.jsonl: the same, one line per verse (the format lexeme-aligner read first);
  - manifest.json: the text fingerprint of each book, the model's sha256, the tokenizer and verse-text versions.
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "clause-tagger"
LAYOUT = HERE / "data" / "clause-layout" / "clauses"

TEST = {"GEN": range(37, 46), "RUT": range(1, 5), "JON": range(1, 5), "1SA": range(1, 11), "DEU": range(5, 12)}
DEV = {"JDG": range(1, 6)}
FORMS = ["-", "qatal", "wayyiqtol", "yiqtol", "weqatal", "imperative", "jussive", "cohortative", "participle active",
         "participle passive", "infinitive construct", "infinitive absolute"]
FINITE = {"qatal", "wayyiqtol", "yiqtol", "weqatal", "imperative", "jussive", "cohortative"}
PERSONS = ["-", "first", "second", "third"]
MAX_DEPTH = 4
PARENTS = ["none", "-1", "-2", "-3", "-4+", "+1", "+2+"]
N_RULES, N_ATTS = 60, 300
SEG_HEADS = ("parent", "kind", "rule", "att")
SLOTS = 4
N_LEMMAS = 4000
PART_HEADS = ("tmpl",) + tuple(f"{h}{i}" for i in range(SLOTS) for h in ("class", "role", "lemma"))
MAX_CHARS = 24
CANTILLATION = re.compile(r"[֑-ֽ֯׀׃׆]")   # accents, meteg, paseq, sof pasuq, nun hafukha
POINTS = re.compile(r"[ְ-ׇ]")


def pointed(s: str) -> str:
    """the word with its vowel points, without accents or punctuation"""
    s = CANTILLATION.sub("", unicodedata.normalize("NFD", s))
    return unicodedata.normalize("NFC", "".join(c for c in s if "ְ" <= c <= "ת" or "יִ" <= c <= "ﭏ"))


def unpointed(s: str) -> str:
    return POINTS.sub("", unicodedata.normalize("NFD", pointed(s)))


def split_of(book: str, chapter: int) -> str:
    if chapter in TEST.get(book, ()):
        return "test"
    return "dev" if chapter in DEV.get(book, ()) else "train"


# ---------------------------------------------------------------- data
def prep() -> None:
    """one JSON line per verse: words (pointed) with their gold labels"""
    from macula.build_clause_layout import _Tree
    con = sqlite3.connect(HERE / "trees-macula.db")
    word_parent = dict(con.execute("select key, parent from words where corpus = 'hbo'"))
    tree = _Tree(con)
    seg = {}
    seg_info = {}
    for f in sorted(LAYOUT.glob("*/*.jsonl")):
        by_verse = collections.defaultdict(list)
        for line in f.open():
            r = json.loads(line)
            by_verse[(r["book"], r["chapter"], r["verse"])].append(r)
            for k in r["words"]:
                seg[k[:11]] = ((r["book"], r["chapter"], r["verse"], r["seg"]), r["depth"])   # word key: BBCCCVVVWWW (part digit dropped)
        for vk, segs in by_verse.items():
            paths = [tree.path([{"parent": word_parent.get(k)} for k in r["words"]]) for r in segs]
            for j, r in enumerate(segs):
                seg_info[vk + (r["seg"],)] = {"parent": _parent_offset(segs, j), "kind": r["kind"] or "-", "rule": r["rule"] or "-",
                                              "att": _meet_kind(paths, j)}
    form = dict(sqlite3.connect(HERE / "lowfat-hbo.db").execute("select key, type from lowfat_words where class = 'verb'"))
    person = dict(sqlite3.connect(HERE / "lexeme-spine-macula.db").execute("select key, person from spine_words where person != ''"))
    verses: dict = collections.OrderedDict()
    for b, ch, v, w, s, key, wlang, cls, role, lemma, strong, lexeme in sqlite3.connect(HERE / "trees-macula.db").execute(
            "select book, chapter, verse, word, surface, key, wlang, class, role, lemma, strong, lexeme from words where corpus = 'hbo' "
            "order by book, chapter, verse, word, part"):
        vs = verses.setdefault((b, ch, v), collections.OrderedDict())
        wd = vs.setdefault(w, {"text": "", "key": key[:11], "form": "-", "person": "-", "aramaic": False, "parts": []})
        wd["text"] += s
        wd["parts"].append({"len": len(pointed(s)), "class": cls or "-", "role": role or "-", "lemma": unicodedata.normalize("NFC", lemma or "-"),
                            "strong": strong or "", "lexeme": lexeme or ""})
        wd["aramaic"] |= wlang == "A"
        if key in form and form[key] in FORMS:
            wd["form"] = form[key]
            wd["person"] = person.get(key, "-") if person.get(key) in PERSONS else "-"
    OUT.mkdir(parents=True, exist_ok=True)
    n = collections.Counter()
    with (OUT / "verses.jsonl").open("w") as out:
        for (b, ch, v), ws in verses.items():
            ws = [w for w in ws.values() if pointed(w["text"])]
            if not ws or any(w["aramaic"] for w in ws):
                continue
            prev = None
            words = []
            for i, w in enumerate(ws):
                sg, depth = seg.get(w["key"], prev or (None, 0))      # a word the layout leaves out (35 in the test set) goes with the one before
                start = int(i == 0 or sg != (prev or (None,))[0])
                words.append({"text": pointed(w["text"]), "start": start, "depth": min(depth, MAX_DEPTH), "form": w["form"],
                              "person": w["person"], "parts": w["parts"], **({"seg": seg_info[sg]} if start and sg in seg_info else {})})
                prev = (sg, depth)
            split = split_of(b, ch)
            n[split] += 1
            out.write(json.dumps({"ref": f"{b} {ch}:{v}", "split": split, "words": words}, ensure_ascii=False) + "\n")
    print(f"[clause_tagger] {dict(n)} verses -> {OUT / 'verses.jsonl'}")


def _parent_offset(segs: list[dict], j: int) -> str:
    """where segment j's parent clause stands in the verse, in segments from j (the nearest segment of it before, else after)"""
    pk = segs[j]["parent_key"]
    idx = [i for i, r in enumerate(segs) if pk is not None and r["clause_key"] == pk]
    back, fwd = [i for i in idx if i < j], [i for i in idx if i > j]
    if not idx:
        return "none"
    if back:
        o = j - back[-1]
        return f"-{o}" if o < 4 else "-4+"
    return "+1" if fwd[0] - j == 1 else "+2+"


def _meet_kind(paths: list[list], j: int) -> str:
    """the attachment kind rule tree_level_inside_verse reads for segment j: where it meets the best earlier segment of the verse"""
    ca = [n for n, _ in paths[j]]
    pos = {n: i for i, n in enumerate(ca)}
    best = None
    for m in range(j):
        ce = [n for n, _ in paths[m]]
        meet = next((n for n in ce if n in pos), None)
        if meet is None:
            continue
        be, ba = ce.index(meet), pos[meet]
        score = (len(ca) - ba, -be, m)
        if best is None or score > best[0]:
            best = (score, ba)
    return paths[j][best[1] - 1][1] if best and best[1] > 0 else "-"


def load(split: str | None = None) -> list[dict]:
    rows = [json.loads(l) for l in (OUT / "verses.jsonl").open()]
    return [r for r in rows if split is None or r["split"] == split]


# ---------------------------------------------------------------- model
def tmpl_of(w: dict) -> str:
    return ",".join(str(x["len"]) for x in w["parts"])


def part_label(w: dict, h: str) -> str:
    """the gold label of a word for part head h ("class2": the class of its third part; "-" no such part)"""
    if h == "tmpl":
        return tmpl_of(w)
    i = int(h[-1])
    return w["parts"][i][h[:-1]] if i < len(w["parts"]) else "-"


def seg_vocab(train_rows: list[dict]) -> dict[str, list[str]]:
    c = {h: collections.Counter() for h in ("rule", "att", "tmpl", "class", "role", "lemma")}
    strong = collections.defaultdict(collections.Counter)
    for v in train_rows:
        for w in v["words"]:
            if "seg" in w:
                for h in ("rule", "att"):
                    c[h][w["seg"][h]] += 1
            c["tmpl"][tmpl_of(w)] += 1
            for x in w["parts"]:
                for h in ("class", "role", "lemma"):
                    c[h][x[h]] += 1
                strong[x["lemma"]][x["strong"]] += 1
    vocab = {"parent": PARENTS, "kind": ["VC", "NC", "-"], "rule": [x for x, _ in c["rule"].most_common(N_RULES)] + ["other"],
             "att": ["-"] + [x for x, _ in c["att"].most_common(N_ATTS + 1) if x != "-"][:N_ATTS] + ["other"],
             "tmpl": [x for x, _ in c["tmpl"].most_common()] + ["other"]}
    for i in range(SLOTS):
        vocab[f"class{i}"] = ["-"] + sorted(x for x in c["class"] if x != "-")
        vocab[f"role{i}"] = ["-"] + sorted(x for x in c["role"] if x != "-")
        vocab[f"lemma{i}"] = ["-"] + [x for x, _ in c["lemma"].most_common(N_LEMMAS) if x != "-"] + ["other"]
    vocab["strong_of"] = {lem: cs.most_common(1)[0][0] for lem, cs in strong.items()}
    return vocab


def build_model(encoder: str, chars: list[str], vocab: dict[str, list[str]]):
    import torch
    from torch import nn
    from transformers import AutoModel

    class Tagger(nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = AutoModel.from_pretrained(encoder)
            self.char_emb = nn.Embedding(len(chars) + 2, 48, padding_idx=0)
            self.char_rnn = nn.GRU(48, 64, batch_first=True, bidirectional=True)
            h = self.encoder.config.hidden_size + 128
            self.mix = nn.LSTM(h, 256, batch_first=True, bidirectional=True)
            self.drop = nn.Dropout(0.2)
            self.heads = nn.ModuleDict({"start": nn.Linear(512, 2), "depth": nn.Linear(512, MAX_DEPTH + 1),
                                        "form": nn.Linear(512, len(FORMS)), "person": nn.Linear(512, len(PERSONS)),
                                        **{h: nn.Linear(512, len(vocab[h])) for h in SEG_HEADS + PART_HEADS}})

        def forward(self, input_ids, attention_mask, first, char_ids):
            enc = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state   # B x T x H
            idx = first.clamp(min=0).unsqueeze(-1).expand(-1, -1, enc.size(-1))
            words = enc.gather(1, idx)                                                                # B x W x H (first subword)
            B, W, C = char_ids.shape
            _, hc = self.char_rnn(self.char_emb(char_ids.view(B * W, C)))
            chars_v = torch.cat([hc[0], hc[1]], -1).view(B, W, 128)
            x, _ = self.mix(self.drop(torch.cat([words, chars_v], -1)))
            x = self.drop(x)
            return {k: head(x) for k, head in self.heads.items()}

    return Tagger()


class Batcher:
    def __init__(self, tokenizer, chars: list[str], vocab: dict[str, list[str]]):
        self.tok = tokenizer
        self.vocab = vocab
        self.cid = {c: i + 2 for i, c in enumerate(chars)}               # 0 pad, 1 unknown

    def __call__(self, verses: list[dict], device):
        import torch
        texts = [[unpointed(w["text"]) or "-" for w in v["words"]] for v in verses]
        enc = self.tok(texts, is_split_into_words=True, truncation=True, max_length=512, padding=True, return_tensors="pt")
        W = max(len(t) for t in texts)
        first = torch.full((len(verses), W), -1, dtype=torch.long)
        for b in range(len(verses)):
            seen = set()
            for t, wid in enumerate(enc.word_ids(b)):
                if wid is not None and wid not in seen:
                    seen.add(wid); first[b, wid] = t
        chars = torch.zeros((len(verses), W, MAX_CHARS), dtype=torch.long)
        for b, v in enumerate(verses):
            for i, w in enumerate(v["words"]):
                for j, c in enumerate(w["text"][:MAX_CHARS]):
                    chars[b, i, j] = self.cid.get(c, 1)
        mask = first >= 0
        gold = {}
        if "start" in verses[0]["words"][0]:
            for k, vocab in (("start", None), ("depth", None), ("form", FORMS), ("person", PERSONS)):
                g = torch.full((len(verses), W), -100, dtype=torch.long)
                for b, v in enumerate(verses):
                    for i, w in enumerate(v["words"]):
                        if mask[b, i]:
                            g[b, i] = vocab.index(w[k]) if vocab else w[k]
                gold[k] = g.to(device)
            for h in SEG_HEADS:                                       # segment heads: only at the word that opens a segment
                voc = self.vocab[h]
                g = torch.full((len(verses), W), -100, dtype=torch.long)
                for b, v in enumerate(verses):
                    for i, w in enumerate(v["words"]):
                        if mask[b, i] and "seg" in w:
                            x = w["seg"][h]
                            g[b, i] = voc.index(x) if x in voc else voc.index("other")
                gold[h] = g.to(device)
            for h in PART_HEADS:                                      # word parts: every word
                voc = self.vocab[h]
                idx = {x: i for i, x in enumerate(voc)}
                g = torch.full((len(verses), W), -100, dtype=torch.long)
                for b, v in enumerate(verses):
                    for i, w in enumerate(v["words"]):
                        if mask[b, i] and "parts" in w:
                            g[b, i] = idx.get(part_label(w, h), idx.get("other", 0))
                gold[h] = g.to(device)
        return ({"input_ids": enc["input_ids"].to(device), "attention_mask": enc["attention_mask"].to(device),
                 "first": first.to(device), "char_ids": chars.to(device)}, mask, gold)


def train(encoder: str, epochs: int, batch: int, seed: int) -> None:
    import torch
    from transformers import AutoTokenizer, get_linear_schedule_with_warmup
    random.seed(seed); torch.manual_seed(seed)
    tr, dev = load("train"), load("dev")
    chars = sorted({c for v in tr for w in v["words"] for c in w["text"]})
    tok = AutoTokenizer.from_pretrained(encoder)
    dev_ice = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    vocab = seg_vocab(tr)
    model = build_model(encoder, chars, vocab).to(dev_ice)
    bat = Batcher(tok, chars, vocab)
    enc_params = list(model.encoder.parameters())
    rest = [p for n, p in model.named_parameters() if not n.startswith("encoder.")]
    opt = torch.optim.AdamW([{"params": enc_params, "lr": 3e-5}, {"params": rest, "lr": 1e-3}], weight_decay=0.01)
    steps = epochs * ((len(tr) + batch - 1) // batch)
    sched = get_linear_schedule_with_warmup(opt, int(0.06 * steps), steps)
    loss_fn = torch.nn.CrossEntropyLoss(ignore_index=-100)
    scaler = torch.amp.GradScaler()
    best = -1.0
    tag = encoder.split("/")[-1]
    for ep in range(epochs):
        model.train()
        random.shuffle(tr)
        tr.sort(key=lambda v: len(v["words"]) // 8 + random.random())    # similar lengths together
        order = list(range(0, len(tr), batch)); random.shuffle(order)
        total = 0.0
        for k, i in enumerate(order):
            x, mask, gold = bat(tr[i:i + batch], dev_ice)
            with torch.autocast("cuda", dtype=torch.float16, enabled=dev_ice.type == "cuda"):
                out = model(**x)
                loss = sum(loss_fn(out[h].float().flatten(0, 1), gold[h].flatten()) for h in out)
            opt.zero_grad()
            scaler.scale(loss).backward()
            scaler.unscale_(opt); torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt); scaler.update(); sched.step()
            total += loss.item()
            if k % 200 == 0:
                print(f"[clause_tagger] epoch {ep + 1} batch {k}/{len(order)} loss {total / (k + 1):.3f}", flush=True)
        VOCAB_SEEN.update(vocab)
        m = metrics(dev, predict(model, bat, dev, dev_ice))
        print(f"[clause_tagger] epoch {ep + 1} dev: boundary F1 {m['boundary_f1']:.1%}, exact segments {m['segments_exact']:.1%}, "
              f"depth {m['depth']:.1%}, form {m['form']:.1%}, parent {m['parent']:.1%}, rule {m['rule']:.1%}, att {m['att']:.1%}, "
              f"split {m['split']:.1%}, lemma {m['part_lemma']:.1%}, word all {m['word_all']:.1%}", flush=True)
        if m["boundary_f1"] + m["segments_exact"] > best:
            best = m["boundary_f1"] + m["segments_exact"]
            torch.save({"state": model.state_dict(), "encoder": encoder, "chars": chars, "vocab": vocab, "epoch": ep + 1, "dev": m, "seed": seed},
                       OUT / f"model-{tag}.pt")
    print(f"[clause_tagger] best dev checkpoint -> {OUT / f'model-{tag}.pt'}")


def predict(model, bat, verses: list[dict], device, batch: int = 32) -> list[dict]:
    import torch
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(verses), batch):
            chunk = verses[i:i + batch]
            x, mask, _ = bat(chunk, device)
            with torch.autocast("cuda", dtype=torch.float16, enabled=device.type == "cuda"):
                o = model(**x)
            am = {k: v.argmax(-1).cpu() for k, v in o.items() if k != "tmpl"}
            top = {k: o[k].topk(LEMMA_TOPK, -1).indices.cpu() for k in o if k.startswith("lemma")}
            tl = o["tmpl"].float().cpu()
            prob = torch.softmax(o["start"].float(), -1)[..., 1].cpu()
            for b, v in enumerate(chunk):
                ws = []
                for j, w in enumerate(v["words"]):
                    st = int(am["start"][b, j]) if j else 1
                    ws.append({"text": w["text"], "start": st, "p_start": round(float(prob[b, j]), 3),
                               "depth": int(am["depth"][b, j]), "form": FORMS[am["form"][b, j]], "person": PERSONS[am["person"][b, j]],
                               **({"seg": {h: bat.vocab[h][am[h][b, j]] for h in SEG_HEADS}} if st else {}),
                               "parts": parts_of(w["text"], tl[b, j], {h: int(am[h][b, j]) for h in PART_HEADS if h != "tmpl"}, bat.vocab,
                                                 {h: top[h][b, j].tolist() for h in top})})
                out.append({"ref": v.get("ref"), "words": ws})
    return out


LEMMA_TOPK = 30
WEAK = set("אהוינ")


FINAL = str.maketrans("ךםןףץ", "כמנפצ")


def strong_letters(word: str) -> list[str]:
    return [c for c in unpointed(word).translate(FINAL) if "א" <= c <= "ת" and c not in WEAK]


def fits(lemma: str, piece: str) -> int:
    """how many strong consonants (not א ה ו י נ) of the lemma stand in the part, in order; 0 when not all of them do"""
    want = strong_letters(lemma)
    it = iter(unpointed(piece).translate(FINAL))
    return len(want) if want and all(c in it for c in want) else 0


def parts_of(text: str, tmpl_logits, ids: dict[str, int], vocab: dict, top: dict[str, list[int]] | None = None) -> list[dict]:
    """the word's parts: the best split pattern whose lengths add up to the word, then each part's class, role and lemma"""
    import torch
    prob = torch.softmax(tmpl_logits, -1)
    order = tmpl_logits.argsort(descending=True).tolist()
    fit = [k for k in order if vocab["tmpl"][k] != "other" and sum(int(x) for x in vocab["tmpl"][k].split(",")) == len(text)]
    lens = [int(x) for x in vocab["tmpl"][fit[0]].split(",")] if fit else [len(text)]
    p_split = round(float(prob[fit[0]] / prob[fit].sum()), 3) if fit else 0.0      # among the splits that fit the word
    out, at = [], 0
    for i, n in enumerate(lens[:SLOTS]):
        piece = text[at:at + n]
        at += n
        lem = vocab[f"lemma{i}"][ids[f"lemma{i}"]]
        if top and len(unpointed(piece)) > 1:        # among the model's best lemmas, the one whose strong consonants the part carries most fully
            cand = [(fits(vocab[f"lemma{i}"][k], piece), -r, vocab[f"lemma{i}"][k]) for r, k in enumerate(top[f"lemma{i}"])]
            cand = [c for c in cand if c[0]]
            if cand and fits(lem, piece) < max(cand)[0]:
                lem = max(cand)[2]
            if len(strong_letters(piece)) >= 3 and fits(lem, piece) <= 1:
                lem = "other"                         # a long part a lemma explains by one letter at most: no lemma (wrong in 220 of 225 OT test cases)
        if lem in ("other", "-"):
            lem = unpointed(piece) or piece
        out.append({"text": piece, "class": vocab[f"class{i}"][ids[f"class{i}"]], "role": vocab[f"role{i}"][ids[f"role{i}"]],
                    "lemma": lem, "strong": vocab["strong_of"].get(lem, ""), "lexeme": lexeme_of().get(lem, "")})
    if out:
        out[0]["p_split"] = p_split
    return out


_LEXEME_OF: dict[str, str] = {}


def lexeme_of() -> dict[str, str]:
    """MACULA lemma -> the lexeme id MACULA gives it most often (hbo:0559), over the whole OT"""
    if not _LEXEME_OF:
        c: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        for v in load():
            for w in v["words"]:
                for x in w["parts"]:
                    if x.get("lexeme"):
                        c[x["lemma"]][x["lexeme"]] += 1
        _LEXEME_OF.update({lem: n.most_common(1)[0][0] for lem, n in c.items()})
    return _LEXEME_OF


def lookup_table(splits: tuple[str, ...], share: float = 0.9) -> dict[str, list[dict]]:
    """pointed word -> its MACULA parts (split, class, lemma, Strong's), where at least `share` of its occurrences in these splits
    are analysed alike"""
    seen: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for v in load():
        if v["split"] in splits:
            for w in v["words"]:
                seen[w["text"]][json.dumps([[x["len"], x["class"], x["lemma"], x["strong"], x.get("lexeme", "")] for x in w["parts"]],
                                           ensure_ascii=False)] += 1
    out = {}
    for text, c in seen.items():
        a, n = c.most_common(1)[0]
        if n / sum(c.values()) >= share:
            out[text] = json.loads(a)
    return out


def apply_lookup(pred: list[dict], table: dict[str, list[dict]]) -> int:
    """replace the model's split, classes and lemmas by MACULA's where the word is a known form; the model's role is kept where the
    split is the same"""
    n = 0
    for v in pred:
        for w in v["words"]:
            a = table.get(w["text"])
            if a is None:
                continue
            same = [len(x["text"]) for x in w["parts"]] == [x[0] for x in a]
            parts, at = [], 0
            for i, (ln, cls, lem, strong, lexeme) in enumerate(a[:SLOTS]):
                parts.append({"text": w["text"][at:at + ln], "class": cls, "role": w["parts"][i]["role"] if same else "-", "lemma": lem,
                              "strong": strong, "lexeme": lexeme})
                at += ln
            w["parts"] = parts
            w["source"] = "macula"
            n += 1
    return n


def load_model(path: Path):
    import torch
    from transformers import AutoTokenizer
    ck = torch.load(path, map_location="cpu", weights_only=False)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model(ck["encoder"], ck["chars"], ck["vocab"])
    model.load_state_dict(ck["state"])
    return model.to(device), Batcher(AutoTokenizer.from_pretrained(ck["encoder"]), ck["chars"], ck["vocab"]), device, ck


# ---------------------------------------------------------------- scoring (the measures of the Parsan comparison)
VOCAB_SEEN: dict[str, list[str]] = {}            # the model's vocabularies: a gold value outside them counts as right when "other"


def segments(starts: list[int]) -> list[tuple[int, int]]:
    cut = [i for i, s in enumerate(starts) if s or i == 0] + [len(starts)]
    return list(zip(cut, cut[1:]))


def metrics(gold: list[dict], pred: list[dict]) -> dict:
    B = collections.Counter(); seg_n = seg_hit = 0; dep = collections.Counter(); V = collections.Counter(); F = collections.Counter()
    P = collections.Counter(); S = {h: collections.Counter() for h in SEG_HEADS + ("tree_decision",)}
    from macula import discourse_rules as dr
    def uses_tree(k):
        return any(k.startswith(t) for t in dr.TREE_TRUSTED) and not any(k.startswith(t) for t in dr.TREE_UNTRUSTED)
    Q = collections.Counter()
    for g, p in zip(gold, pred):
        gw, pw = g["words"], p["words"]
        for x, y in zip(gw, pw):
            if "parts" not in x or "parts" not in y:
                continue
            same = [a["len"] for a in x["parts"]][:SLOTS] == [len(b["text"]) for b in y["parts"]]
            Q["words"] += 1; Q["split"] += same
            if same:
                ok = True
                for a, b in zip(x["parts"], y["parts"]):
                    Q["parts"] += 1
                    for h in ("class", "lemma", "role"):
                        Q[h] += a[h] == b[h]
                    ok &= a["class"] == b["class"] and a["lemma"] == b["lemma"]
                Q["word_all"] += ok
        for i in range(1, len(gw)):
            B[(bool(gw[i]["start"]), bool(pw[i]["start"]))] += 1
        gs = segments([w["start"] for w in gw]); ps = set(segments([w["start"] for w in pw]))
        seg_n += len(gs); seg_hit += sum(1 for s in gs if s in ps)
        for a, _ in gs:
            if (a, _) in ps:
                dep[min(gw[a]["depth"] - gw[0]["depth"], 3) == min(pw[a]["depth"] - pw[0]["depth"], 3)] += 1
                if "seg" in gw[a] and "seg" in pw[a]:
                    for h in SEG_HEADS:
                        gx = gw[a]["seg"][h]
                        S[h][pw[a]["seg"][h] in (gx, "other" if h in ("rule", "att") and gx not in VOCAB_SEEN.get(h, (gx,)) else gx)] += 1
                    S["tree_decision"][uses_tree(gw[a]["seg"]["att"]) == uses_tree(pw[a]["seg"]["att"])] += 1
        for x, y in zip(gw, pw):
            V[(x["form"] in FINITE, y["form"] in FINITE)] += 1
            if x["form"] in FINITE and y["form"] in FINITE:
                F[x["form"] == y["form"]] += 1
                P[x["person"] == y["person"]] += 1
    def prf(C):
        tp, fp, fn = C[(True, True)], C[(False, True)], C[(True, False)]
        p = tp / (tp + fp) if tp + fp else 0.0; r = tp / (tp + fn) if tp + fn else 0.0
        return p, r, (2 * p * r / (p + r) if p + r else 0.0)
    bp, br, bf = prf(B); vp, vr, vf = prf(V)
    return {"boundary_p": bp, "boundary_r": br, "boundary_f1": bf, "segments_exact": seg_hit / max(seg_n, 1), "segments": seg_n,
            "depth": dep[True] / max(sum(dep.values()), 1), "verb_p": vp, "verb_r": vr, "form": F[True] / max(sum(F.values()), 1),
            "form_n": sum(F.values()), "person": P[True] / max(sum(P.values()), 1),
            **{h: S[h][True] / max(sum(S[h].values()), 1) for h in S},
            "split": Q["split"] / max(Q["words"], 1), "word_all": Q["word_all"] / max(Q["words"], 1),
            **{f"part_{h}": Q[h] / max(Q["parts"], 1) for h in ("class", "lemma", "role")}}


def unseen_parts(gold: list[dict], pred: list[dict], forms: set[str]) -> dict:
    Q = collections.Counter()
    for g, p in zip(gold, pred):
        for x, y in zip(g["words"], p["words"]):
            if x["text"] not in forms:
                continue
            Q["words"] += 1
            same = [a["len"] for a in x["parts"]][:SLOTS] == [len(b["text"]) for b in y["parts"]]
            Q["split_ok"] += same
            if same:
                ok = True
                for a, b in zip(x["parts"], y["parts"]):
                    Q["parts"] += 1; Q["class"] += a["class"] == b["class"]; Q["lemma"] += a["lemma"] == b["lemma"]
                    ok &= a["class"] == b["class"] and a["lemma"] == b["lemma"]
                Q["all"] += ok
    return {"words": Q["words"], "split": Q["split_ok"] / max(Q["words"], 1), "class": Q["class"] / max(Q["parts"], 1),
            "lemma": Q["lemma"] / max(Q["parts"], 1), "all": Q["all"] / max(Q["words"], 1)}


def score(path: Path, split: str, lookup: bool = False) -> None:
    model, bat, device, ck = load_model(path)
    VOCAB_SEEN.update(ck["vocab"])
    gold = load(split)
    pred = predict(model, bat, gold, device)
    if lookup:
        n = apply_lookup(pred, lookup_table(("train",)))
        print(f"[clause_tagger] known forms (from the training books) replace the model's parts in {n} words")
    m = metrics(gold, pred)
    (OUT / f"pred-{split}-{path.stem}.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pred))
    print(f"[clause_tagger] {path.name} (epoch {ck['epoch']}) on {split}: {len(gold)} verses")
    print(f"  clause boundaries: P {m['boundary_p']:.1%}  R {m['boundary_r']:.1%}  F1 {m['boundary_f1']:.1%}")
    print(f"  layout segments reproduced exactly: {m['segments_exact']:.1%} of {m['segments']}")
    print(f"  depth in the verse (exactly matched segments): {m['depth']:.1%}")
    print(f"  finite verb: P {m['verb_p']:.1%}  R {m['verb_r']:.1%};  verb form {m['form']:.1%} of {m['form_n']};  person {m['person']:.1%}")
    print(f"  word parts: split right {m['split']:.1%}; on rightly split words: class {m['part_class']:.1%}, lemma {m['part_lemma']:.1%}, "
          f"role {m['part_role']:.1%}; words with split, classes and lemmas all right {m['word_all']:.1%}")
    unseen = {w["text"] for v in gold for w in v["words"]} - {w["text"] for v in load("train") for w in v["words"]}
    u = unseen_parts(gold, pred, unseen)
    print(f"  words whose form is not in the training books ({u['words']}, {u['words'] / sum(len(v['words']) for v in gold):.1%}): split right "
          f"{u['split']:.1%}, then class {u['class']:.1%}, lemma {u['lemma']:.1%}; all right {u['all']:.1%}")
    print(f"  on exactly matched segments: parent {m['parent']:.1%}, kind {m['kind']:.1%}, rule {m['rule']:.1%}, attachment kind {m['att']:.1%}, "
          f"tree trusted or not {m['tree_decision']:.1%}")


def tag(path: Path, text_file: Path) -> None:
    model, bat, device, _ = load_model(path)
    verses = [{"ref": None, "words": [{"text": pointed(w)} for w in re.split(r"[\s־]+", line) if pointed(w)]}
              for line in text_file.read_text().splitlines() if line.strip()]
    pred = predict(model, bat, verses, device)
    apply_lookup(pred, lookup_table(("train", "dev", "test")))                # every OT book: Salkinson is not in the OT
    for p in pred:
        print(json.dumps(p, ensure_ascii=False))


HEB_UNITS = "אבגדהוזחט"
HEB_TENS = "יכלמנסעפצ"


def heb_numeral(n: int) -> str:
    """a verse number as Hebrew letters (15 = טו, 16 = טז), as Salkinson's verse texts begin"""
    out = "ק" * (n // 100)
    n %= 100
    if n in (15, 16):
        return out + ("טו" if n == 15 else "טז")
    return out + (HEB_TENS[n // 10 - 1] if n >= 10 else "") + (HEB_UNITS[n % 10 - 1] if n % 10 else "")


def pointed_tokens(text: str) -> list[str]:
    """the verse's words as bibles' tokenizer v2 cuts them (runs of letters and marks), with their points kept"""
    toks, cur = [], []
    for ch in unicodedata.normalize("NFC", text):
        if unicodedata.category(ch)[0] in ("L", "M"):
            cur.append(ch)
        elif cur:
            toks.append("".join(cur)); cur = []
    if cur:
        toks.append("".join(cur))
    return [t for t in toks if any(unicodedata.category(c)[0] == "L" for c in t)]   # a stray point alone is no word (Acts 9:6)


def export(path: Path, helloao: Path, edition: str, books: list[str] | None) -> None:
    import hashlib
    sys.path.insert(0, str(HERE / "vendor_bibles"))
    import bcv_tokenize
    import helloao_to_usj
    import verse_text
    model, bat, device, ck = load_model(path)
    table = lookup_table(("train", "dev", "test"))              # every OT book: the edition is not in the OT
    out_dir = OUT / "export" / edition
    out_dir.mkdir(parents=True, exist_ok=True)
    by_book = collections.defaultdict(list)
    for f in helloao.glob("*_*.json"):
        b = f.stem.rsplit("_", 1)[0]
        if not books or b in books:
            by_book[b].append(json.loads(f.read_text()))
    manifest = {"edition": edition, "tokenizer_version": bcv_tokenize.TOKENIZER_VERSION, "text_fp_version": bcv_tokenize.TEXT_FP_VERSION,
                "bibles_verse_text": (HERE / "vendor_bibles" / "VERSION").read_text().strip(),
                "model": {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "encoder": ck["encoder"], "epoch": ck["epoch"]},
                "books": {}}
    tables: dict[str, list[dict]] = {"words": [], "clauses": []}
    for b, chs in sorted(by_book.items()):
        chs.sort(key=lambda d: d["chapter"]["number"])
        vt = verse_text.extract_usj(helloao_to_usj.merge_book_usj(b, chs))
        verses = {(int(c), int(x["verse"])): x["text"] for c, vs in vt.items() for x in vs}
        book_fp, _ = bcv_tokenize.fingerprints(verses)
        rows, words_in = [], []
        for (c, v), text in sorted(verses.items()):
            toks = bcv_tokenize.tokenize(text)
            pts = pointed_tokens(text)
            if [bcv_tokenize.strip_marks(t) for t in pts] != toks:
                raise SystemExit(f"{b} {c}:{v}: our pointed words differ from bibles' tokens")
            label = bool(toks) and toks[0] == heb_numeral(v) and pts[0] == toks[0]     # the verse number in the text: not a word
            rows.append({"ref": f"{b} {c}:{v}", "tokens": toks, "label": label})
            words_in.append({"ref": f"{b} {c}:{v}", "words": [{"text": pointed(t)} for t in pts[int(label):]]})
        pred = predict(model, bat, words_in, device)
        for p_ in pred:
            for w in p_["words"]:
                w["source"] = "model"
        apply_lookup(pred, table)
        n = collections.Counter()
        with (out_dir / f"{b}.jsonl").open("w") as out:
            for r, p_ in zip(rows, pred):
                ws = [{"i": 0, "token": r["tokens"][0], "verse_number": True}] if r["label"] else []
                for i, w in enumerate(p_["words"], start=int(r["label"])):
                    n[w["source"]] += 1
                    ws.append({"i": i, "token": r["tokens"][i], "text": w["text"], "source": w["source"], "parts": w["parts"],
                               "clause": {k: w[k] for k in ("start", "depth", "form", "person", "seg") if k in w}})
                out.write(json.dumps({"ref": r["ref"], "words": ws}, ensure_ascii=False) + "\n")
        tables["words"].extend(word_rows(b, pred, rows))
        tables["clauses"].extend(clause_rows(b, pred, rows))
        manifest["books"][b] = {"file": f"{b}.jsonl", "text_fingerprint": book_fp, "file_hash": bcv_tokenize.file_hash(book_fp),
                                "verses": len(rows), "words": sum(n.values()), "macula": n["macula"], "model": n["model"]}
        print(f"[clause_tagger] {b}: {len(rows)} verses, {sum(n.values())} words ({n['macula']} looked up in MACULA, {n['model']} from the model)")
    write_parquet(out_dir, tables)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    print(f"[clause_tagger] -> {out_dir}")


def _ref(ref: str) -> tuple[int, int]:
    c, v = ref.split()[1].split(":")
    return int(c), int(v)


def word_rows(book: str, pred: list[dict], rows: list[dict]) -> list[dict]:
    out = []
    for r, p_ in zip(rows, pred):
        c, v = _ref(r["ref"])
        base = {"book": book, "chapter": c, "verse": v}
        if r["label"]:
            out.append({**base, "i": 0, "part": 0, "token": r["tokens"][0], "word": r["tokens"][0], "text": r["tokens"][0],
                        "class": "verse-number", "seg": 0})
        seg = 0
        for i, w in enumerate(p_["words"], start=int(r["label"])):
            seg += w["start"]
            verb = next((k for k, x in enumerate(w["parts"]) if x["class"] == "verb"), None)
            for k, x in enumerate(w["parts"]):
                out.append({**base, "i": i, "part": k, "token": r["tokens"][i], "word": w["text"], "text": x["text"], "class": x["class"],
                            "lemma": x["lemma"], "lexeme": x["lexeme"] or None, "strong": x["strong"] or None,
                            "role": None if x["role"] == "-" else x["role"], "source": w["source"],
                            "p_split": x.get("p_split") if w["source"] == "model" else None,
                            "form": None if k != verb or w["form"] == "-" else w["form"],
                            "person": None if k != verb or w["person"] == "-" else w["person"], "seg": seg})
    return out


def clause_rows(book: str, pred: list[dict], rows: list[dict]) -> list[dict]:
    out = []
    for r, p_ in zip(rows, pred):
        c, v = _ref(r["ref"])
        ws = p_["words"]
        off = int(r["label"])
        for n, (a, z) in enumerate(segments([w["start"] for w in ws]), start=1):
            sg = ws[a].get("seg", {})
            out.append({"book": book, "chapter": c, "verse": v, "seg": n, "first_i": a + off, "last_i": z - 1 + off, "depth": ws[a]["depth"],
                        "parent": sg.get("parent"), "kind": sg.get("kind"), "rule": sg.get("rule"), "att": sg.get("att")})
    return out


WORD_SCHEMA = [("book", "string"), ("chapter", "int16"), ("verse", "int16"), ("i", "int16"), ("part", "int8"), ("token", "string"),
               ("word", "string"), ("text", "string"), ("class", "string"), ("lemma", "string"), ("lexeme", "string"), ("strong", "string"),
               ("role", "string"), ("source", "string"), ("p_split", "float64"), ("form", "string"), ("person", "string"), ("seg", "int16")]
CLAUSE_SCHEMA = [("book", "string"), ("chapter", "int16"), ("verse", "int16"), ("seg", "int16"), ("first_i", "int16"), ("last_i", "int16"),
                 ("depth", "int8"), ("parent", "string"), ("kind", "string"), ("rule", "string"), ("att", "string")]


def write_parquet(out_dir: Path, tables: dict[str, list[dict]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    for name, schema in (("words", WORD_SCHEMA), ("clauses", CLAUSE_SCHEMA)):
        sch = pa.schema([(c, getattr(pa, t)()) for c, t in schema])
        t = pa.Table.from_pylist(tables[name], schema=sch)
        pq.write_table(t, out_dir / f"{name}.parquet", compression="zstd")
        print(f"[clause_tagger] {name}.parquet: {t.num_rows} rows")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prep")
    t = sub.add_parser("train")
    t.add_argument("--encoder", default="dicta-il/dictabert")
    t.add_argument("--epochs", type=int, default=4)
    t.add_argument("--batch", type=int, default=16)
    t.add_argument("--seed", type=int, default=13)
    s = sub.add_parser("score")
    s.add_argument("--model", default=str(OUT / "model-dictabert.pt"))
    s.add_argument("--split", default="test")
    s.add_argument("--lookup", action="store_true", help="known OT forms take MACULA's parts (the table from the training books)")
    g = sub.add_parser("tag")
    g.add_argument("file")
    g.add_argument("--model", default=str(OUT / "model-dictabert.pt"))
    e = sub.add_parser("export")
    e.add_argument("--helloao", required=True, help="folder of helloAO chapter JSON, <BOOK>_<chapter>.json")
    e.add_argument("--edition", required=True)
    e.add_argument("--books", default="")
    e.add_argument("--model", default=str(OUT / "model-dictabert.pt"))
    a = ap.parse_args()
    if a.cmd == "prep":
        prep()
    elif a.cmd == "train":
        train(a.encoder, a.epochs, a.batch, a.seed)
    elif a.cmd == "score":
        score(Path(a.model), a.split, a.lookup)
    elif a.cmd == "export":
        export(Path(a.model), Path(a.helloao), a.edition, [b for b in a.books.split(",") if b])
    else:
        tag(Path(a.model), Path(a.file))


if __name__ == "__main__":
    main()
