"""Sense split by translation: occurrences of a Hebrew word that translators render alike share a sense.

For רוּחַ, translators in ten languages write "spirit / espíritu / esprit / дух..." in some verses and
"wind / viento / vent / ветер..." in others. The renderings of one sense co-occur on the same Hebrew
token across languages; renderings of different senses do not. So per lexeme:
1. features = (language, normalised rendering) on each aligned occurrence (resources/strongs/attestations,
   10 languages, Clear-Bible alignments; function words dropped via resources/stopwords);
2. a feature graph, edges weighted by cross-language co-occurrence on the same token (cosine-normalised);
3. Louvain communities = candidate senses; each occurrence goes to the community its features vote for;
   communities with too few occurrences are dissolved into the next-best;
4. label = the community's most frequent English rendering.
Hebrew-internal context plays no part; the BEREL context split (build_bhsa_free_senses.py) could not
separate spirit/wind.

Evaluated (`--eval`) against the UBS Dictionary of Biblical Hebrew per-token sense index (CC BY-SA,
index/WLC of ubsicap/ubs-open-license) as an independent check, beside two baselines: one sense per word,
and MACULA's per-token English gloss.

  python -m macula.build_rendering_senses --eval
  python -m macula.build_rendering_senses --out macula/data/rendering_senses
"""
from __future__ import annotations

import argparse
import collections
import itertools
import json
import math
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine.db"
LOWFAT = HERE / "lowfat-hbo.db"
ATTEST = ROOT / "resources" / "strongs" / "attestations"
STOP = ROOT / "resources" / "stopwords"
UBS_INDEX = HERE / "data" / "ubs_open" / "index_wlc"
LANGS = ("eng", "spa", "fra", "por", "rus", "arb", "hin", "ben", "asm", "hau")
MIN_OCC = 20            # lexemes with fewer aligned occurrences keep one sense
MIN_SENSE_SHARE = 0.05  # a sense needs at least this share of the word's occurrences ...
MIN_SENSE_OCC = 4       # ... and at least this many
RESOLUTION = 1.0
COMPACT_FEATURES = None  # --compact FILE: renderings from the aligner's positional alignments
USE_GBT = False          # --gbt: add Global Bible Tools per-word glosses (14 more languages)
MIN_OCC_EVAL = 20       # words need this many reference-labelled tokens to be scored (Menahem: set to 4)

_ARABIC_MARKS = re.compile(r"[ً-ٰٟـ]")


def norm(lang: str, s: str) -> str:
    s = unicodedata.normalize("NFC", s.lower()).strip(".,;:!?\"'«»()[]“”‘’-—")
    if lang == "arb":
        s = _ARABIC_MARKS.sub("", s)
        for pre in ("و", "ف"):
            if s.startswith(pre) and len(s) > 3:
                s = s[1:]
        if s.startswith("ال") and len(s) > 4:
            s = s[2:]
        return s[:5]
    if lang in ("eng", "spa", "fra", "por", "hau", "rus"):
        s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
        # grammatical number is not a sense: plural tokens get plural renderings in every language
        if lang in ("eng", "fra") and len(s) > 3 and s.endswith(("s", "x")):
            s = s[:-1]
        elif lang in ("spa", "por") and len(s) > 4 and s.endswith(("es", "os", "as")):
            s = s[:-1]
        elif lang in ("spa", "por") and len(s) > 3 and s.endswith("s"):
            s = s[:-1]
        if lang == "rus":
            return s[:4]
        return s[:5] if len(s) > 5 else s
    return s


# Pronouns and possessives: Hebrew suffixes ("his hand", "your soul") are translated with them in every
# language, so without this suffixed forms clustered as a "sense" of their own (יָד: "his"; נֶפֶשׁ: "you").
PRONOUNS = {
    "eng": "he him his she her hers it its they them their theirs you your yours thou thee thy thine ye i me my "
           "mine we us our ours himself herself itself themselves yourself yourselves myself ourselves",
    "fra": "il le lui son sa ses elle la leur leurs ils eux elles les vous votre vos tu te toi ton ta tes je me moi "
           "mon ma mes nous notre nos se soi",
    "spa": "él lo le su sus ella la ellos ellas los las les vosotros vuestro vuestra vuestros vuestras tú te ti tu "
           "tus yo me mí mi mis nosotros nuestro nuestra nuestros nuestras se sí usted ustedes",
    "por": "ele o lhe seu sua seus suas ela a eles elas os as lhes vós vosso vossa vossos vossas tu te ti teu tua "
           "teus tuas eu me mim meu minha meus minhas nós nosso nossa nossos nossas se si",
    "rus": "он его ему него нему им ним она её ее ей ней они их им ими них нам вы вас вам ваш ваша ваше ваши ты тебя "
           "тебе твой твоя твое твоё твои я меня мне мой моя мое моё мои мы нас нам наш наша наше наши свой своя "
           "свое своё свои себя себе",
}


# Articles, prepositions, conjunctions, demonstratives: aligned along with the noun ("THE land", "AND his
# hand"), they made spurious senses (אֶרֶץ "the", יָד "and"). Verbs such as be/have stay (היה needs them).
FUNCTION_WORDS = {
    "eng": "the a an and of to in for with from by on at as but or nor not that this these those which who whom "
           "what when where there then than so if unto upon into out up down over under before after all every",
    "fra": "le la les l un une des de du d et à au aux en dans pour par sur avec sans que qui ne pas ou mais ce cet "
           "cette ces tout tous toute toutes",
    "spa": "el la los las un una unos unas de del y e a al en por para con sin que no o u pero este esta estos estas "
           "ese esa todo toda todos todas",
    "por": "o a os as um uma de do da dos das e em no na nos nas por para com sem que não ou mas este esta estes "
           "estas esse essa todo toda todos todas",
    "rus": "и в во на с со к ко по из у о об за от до не что а но или же все всё весь вся",
}


def stopwords(lang: str) -> set[str]:
    p = STOP / f"{lang}.tsv"
    out = set(PRONOUNS.get(lang, "").split()) | set(FUNCTION_WORDS.get(lang, "").split())
    if not p.exists():
        return out
    return out | {l.split("\t")[0].lower() for l in p.read_text(encoding="utf-8").splitlines()
                  if l and not l.startswith("#") and not l.startswith("surface\t")}


GBT_DIR = Path(__import__("os").environ.get(
    "GBT_OCCURRENCE_DIR", str(Path.home() / "dev/bcv-commons/lexeme-aligner/pipeline/work/occurrence_align")))
GBT_MIN_ROWS = 100_000          # skip partial gloss projects (French has 1,300 rows)


def _content_part_keys() -> dict[str, str]:
    """MACULA word key (token key without its part digit) -> the key of its content part (longest lemma)."""
    db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    best: dict = {}
    for key, lemma in db.execute("SELECT key, lemma FROM spine_words WHERE lexeme LIKE 'hbo:%'"):
        w, n = key[:-1], len(lemma or "")
        if w not in best or n > best[w][0]:
            best[w] = (n, key)
    return {w: k for w, (_n, k) in best.items()}


def gbt_features() -> dict[str, set]:
    """Per-word glosses from Global Bible Tools (CC0; via the lexeme-aligner's occurrence_align export), one
    feature set per language tagged gbt-<iso>: content words of the gloss phrase, normalised like the
    translations. GBT ids are BCCCVVVWW over whole words; the gloss goes to the word's content part."""
    import json
    part = _content_part_keys()
    feats: dict[str, set] = collections.defaultdict(set)
    if not GBT_DIR.exists():
        return feats
    for path in sorted(GBT_DIR.glob("gbt_*.jsonl")):
        lang = path.stem.split("_", 1)[1]
        if lang == "eng" or sum(1 for _ in path.open(encoding="utf-8")) < GBT_MIN_ROWS:
            continue                    # English already comes from BSB/YLT; skip partial projects
        stop = stopwords(lang)
        for line in path.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("kind") != "1:1" or not r.get("target_gloss"):
                continue
            sid = str(r["source_ids"][0])
            if len(sid) < 9 or int(sid[:-8]) > 39:
                continue
            key = part.get(f"{int(sid[:-8]):02d}{sid[-8:-5]}{sid[-5:-2]}{int(sid[-2:]):03d}")
            if not key:
                continue
            for w in re.findall(r"[^\W\d_]+", r["target_gloss"][0].lower()):
                if len(w) < 3 or w in stop:
                    continue
                f = norm(lang, w) if lang in LANGS else w[:5]
                if len(f) >= 3:
                    feats[key].add((f"gbt-{lang}", f))
    return feats


RAW_TOK: dict = collections.defaultdict(dict)    # token key -> {English form: the surface the translator wrote}, filled by load_features (labels use the surfaces of the tokens in a sense, never a corpus-wide most-common surface)


def load_features() -> tuple[dict[str, set], dict[str, collections.Counter]]:
    """token key (lexeme-spine key) -> {(lang, form)}, and form -> Counter(raw English surfaces) for labels."""
    feats: dict[str, set] = collections.defaultdict(set)
    eng_raw: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for lang in LANGS:
        p = ATTEST / f"{lang}.parquet"
        if not p.exists():
            continue
        t = pq.read_table(p, columns=["strong", "surface", "source_id"])
        t = t.filter(pc.starts_with(t["source_id"], "o"))
        stop = stopwords(lang)
        for sid, surf in zip(t["source_id"].to_pylist(), t["surface"].to_pylist()):
            if not surf:
                continue
            low = surf.lower().strip(".,;:!?\"'")
            if low in stop or len(low) < 3:
                continue
            f = norm(lang, surf)
            if len(f) < 3:
                continue
            feats[sid[1:]].add((lang, f))
            if lang == "eng":
                eng_raw[f][low] += 1
                RAW_TOK[sid[1:]].setdefault(f, low)
    if USE_GBT:
        for k, fs in gbt_features().items():
            feats[k] |= fs
    if COMPACT_FEATURES:                 # per-occurrence renderings from the aligner (build_compact_renderings)
        import pickle
        with open(COMPACT_FEATURES, "rb") as fh:
            for k, fs in pickle.load(fh)["features"].items():
                feats[k] |= fs
    return feats, eng_raw


def lexeme_tokens() -> dict[str, list[str]]:
    db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    out = collections.defaultdict(list)
    for key, lexeme in db.execute("SELECT key, lexeme FROM spine_words WHERE lexeme LIKE 'hbo:%'"):
        out[lexeme].append(key)
    return out


def split_lexeme(keys: list[str], feats: dict[str, set], seed: int = 13) -> dict[str, int]:
    """token key -> sense number (1 = largest). Tokens without features are left out."""
    import networkx as nx
    occ = [(k, feats[k]) for k in keys if feats.get(k)]
    if len(occ) < MIN_OCC:
        return {k: 1 for k, _ in occ}
    fcount = collections.Counter(f for _, fs in occ for f in fs)
    keep = {f for f, n in fcount.items() if n >= 2}
    pair = collections.Counter()
    for _, fs in occ:
        fs = sorted(f for f in fs if f in keep)
        for a, b in itertools.combinations(fs, 2):
            if a[0] != b[0]:
                pair[(a, b)] += 1
    G = nx.Graph()
    G.add_nodes_from(keep)
    for (a, b), n in pair.items():
        if n >= 2:
            G.add_edge(a, b, weight=n / math.sqrt(fcount[a] * fcount[b]))
    comms = nx.community.louvain_communities(G, weight="weight", resolution=RESOLUTION, seed=seed)
    comm_of = {f: i for i, c in enumerate(comms) for f in c}

    def votes(fs, allowed):
        v = collections.Counter()
        for f in fs:
            if f in comm_of and comm_of[f] in allowed:
                v[comm_of[f]] += 1
        return v

    allowed = set(range(len(comms)))
    while True:
        assign = {}
        for k, fs in occ:
            v = votes(fs, allowed)
            if v:
                assign[k] = v.most_common(1)[0][0]
        size = collections.Counter(assign.values())
        small = [c for c in allowed if size[c] < max(MIN_SENSE_OCC, MIN_SENSE_SHARE * len(occ))]
        if not small or len(allowed) == 1:
            break
        allowed.discard(min(small, key=lambda c: size[c]))
    if not assign:
        return {k: 1 for k, _ in occ}
    order = {c: i + 1 for i, (c, _) in enumerate(collections.Counter(assign.values()).most_common())}
    return {k: order[c] for k, c in assign.items()}


def build(out: Path | None = None, only: set[str] | None = None,
          merge_same_label: bool = False) -> dict[str, dict[str, int]]:
    feats, eng_raw = load_features()
    toks = lexeme_tokens()
    result, labels = {}, {}
    for lexeme, keys in toks.items():
        if only and lexeme not in only:
            continue
        a = split_lexeme(keys, feats)
        eng = collections.defaultdict(collections.Counter)
        for k, s in a.items():
            for lang, f in feats.get(k, ()):
                if lang == "eng":
                    eng[s][f] += 1
        by_sense = collections.defaultdict(list)
        for k, s_ in a.items():
            by_sense[s_].append(k)
        lab = {s: _label(eng[s], eng_raw, by_sense[s]) for s in set(a.values())}
        # optional: senses with the same English label as one (two "soul" communities). Off by default:
        # it lowered agreement with the UBS sense index (ARI 0.202 -> 0.183 at resolution 1.0).
        first = {}
        merged = {s: (first.setdefault(lab[s] or f"#{s}", s) if merge_same_label else s) for s in sorted(lab)}
        a = {k: merged[s] for k, s in a.items()}
        order = {s: i + 1 for i, (s, _) in enumerate(collections.Counter(a.values()).most_common())}
        result[lexeme] = {k: order[s] for k, s in a.items()}
        labels[lexeme] = {order[s]: lab[s] for s in order}
    if out:
        out.mkdir(parents=True, exist_ok=True)
        with (out / "occurrences.tsv").open("w", encoding="utf-8") as fh:
            fh.write("key\tlexeme\tsense\n")
            for lexeme, a in result.items():
                for k, s in a.items():
                    fh.write(f"{k}\t{lexeme}\t{s}\n")
        with (out / "senses.tsv").open("w", encoding="utf-8") as fh:
            fh.write("lexeme\tsense\tlabel\tcount\tshare\n")
            for lexeme, a in result.items():
                cnt = collections.Counter(a.values())
                tot = sum(cnt.values())
                for s, n in sorted(cnt.items()):
                    fh.write(f"{lexeme}\t{s}\t{labels[lexeme].get(s, '')}\t{n}\t{n / tot:.3f}\n")
    return result


def _label(c: collections.Counter, eng_raw: dict, tokens=None) -> str:
    """Most frequent English form of a sense, written as the surface its own tokens carry. The English normaliser keeps five letters, so "sanctify",
    "sanctified" and "sanctuary" are one form; the surface must come from the tokens (tokens=...), not from the corpus-wide most common surface of the form
    (which labelled a verb "sanctuary")."""
    if not c:
        return ""
    f = c.most_common(1)[0][0]
    if tokens is not None:
        return token_surface(f, tokens) or f
    return eng_raw[f].most_common(1)[0][0] if eng_raw.get(f) else f


def token_surface(form: str, tokens) -> str:
    cnt = collections.Counter(RAW_TOK[k][form] for k in tokens if form in RAW_TOK.get(k, ()))
    return cnt.most_common(1)[0][0] if cnt else ""


# ---------- evaluation ----------

def ubs_gold() -> dict[str, str]:
    """token key -> UBS sense id ("lemma:000002"), first lexical link."""
    gold = {}
    for p in sorted(UBS_INDEX.glob("*.json")):
        for rec in json.loads(p.read_text(encoding="utf-8")):
            links = [l for l in rec.get("LexicalLinks", []) if l.startswith("SDBH:")]
            if links:
                parts = links[0].split(":")
                gold[rec["ID"][1:]] = f"{parts[1]}:{parts[2]}"
    return gold


def menahem_gold() -> dict[str, str]:
    """token key -> Mahberet Menahem division ("entry#division") for the occurrences Menahem cites
    (resources/mahberet_menahem/senses.tsv); the word's content part stands for the word."""
    path = ROOT / "resources" / "mahberet_menahem" / "senses.tsv"
    if not path.exists():
        return {}
    db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    parts = collections.defaultdict(list)
    for key, lemma in db.execute("SELECT key, lemma FROM spine_words WHERE lexeme LIKE 'hbo:%'"):
        parts[key[:-1]].append((len(lemma or ""), key))
    gold = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(("#", "book\t")):
            continue
        r = line.split("\t")
        if parts.get(r[3]):
            gold[max(parts[r[3]])[1]] = f"{r[7]}#{r[8]}"
    return gold


def gloss_partition() -> dict[str, str]:
    lf = sqlite3.connect(f"file:{LOWFAT}?mode=ro", uri=True)
    return {k: (g or "").lower() for k, g in lf.execute("SELECT key, gloss FROM lowfat_words WHERE is_inserted=0")}


def pair_scores(pred: dict[str, object], gold: dict[str, str], keys: list[str]) -> tuple[float, float, float] | None:
    ks = [k for k in keys if k in pred and k in gold]
    if len(ks) < 2:
        return None
    tp = fp = fn = 0
    pc_ = collections.Counter((pred[k], gold[k]) for k in ks)
    pp = collections.Counter(pred[k] for k in ks)
    gg = collections.Counter(gold[k] for k in ks)
    c2 = lambda n: n * (n - 1) // 2
    tp = sum(c2(n) for n in pc_.values())
    same_pred = sum(c2(n) for n in pp.values())
    same_gold = sum(c2(n) for n in gg.values())
    prec = tp / same_pred if same_pred else 1.0
    rec = tp / same_gold if same_gold else 1.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1


def ari(pred: dict, gold: dict, keys: list[str]) -> float | None:
    ks = [k for k in keys if k in pred and k in gold]
    n = len(ks)
    if n < 2:
        return None
    c2 = lambda x: x * (x - 1) / 2
    idx = sum(c2(v) for v in collections.Counter((pred[k], gold[k]) for k in ks).values())
    a = sum(c2(v) for v in collections.Counter(pred[k] for k in ks).values())
    b = sum(c2(v) for v in collections.Counter(gold[k] for k in ks).values())
    exp = a * b / c2(n)
    mx = (a + b) / 2
    return 0.0 if mx == exp else (idx - exp) / (mx - exp)


def bhsa_partition() -> dict[str, str]:
    """Internal comparison only: the BHSA-based sense column of the full spine (never published)."""
    db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    cols = {r[1] for r in db.execute("PRAGMA table_info(spine_words)")}
    if "sense" not in cols:
        return {}
    return {k: f"{st}:{se}" for k, st, se in db.execute(
        "SELECT key, stem, sense FROM spine_words WHERE lexeme LIKE 'hbo:%' AND sense IS NOT NULL")}


def evaluate(result: dict[str, dict[str, int]], gold: dict[str, str]) -> dict:
    gloss = gloss_partition()
    bhsa = bhsa_partition()
    toks = lexeme_tokens()
    rows = collections.defaultdict(list)
    n_lex = 0
    for lexeme, a in result.items():
        keys = [k for k in toks[lexeme] if k in a and k in gold]
        senses = collections.Counter(gold[k] for k in keys)
        # polysemous by UBS: at least two senses, the second with >= 10% of the tokens
        if len(keys) < MIN_OCC_EVAL or len(senses) < 2 or senses.most_common(2)[1][1] < 0.1 * len(keys):
            continue
        n_lex += 1
        for name, pred in (("rendering", a), ("one-sense", {k: 1 for k in keys}),
                           ("macula-gloss", {k: gloss.get(k, "") for k in keys}),
                           ("bhsa-context (internal)", {k: bhsa.get(k, "") for k in keys})):
            s = pair_scores(pred, gold, keys)
            if s:
                rows[name].append((s + (ari(pred, gold, keys) or 0.0,), len(keys)))
    out = {"polysemous_lexemes": n_lex}
    for name, rs in rows.items():
        macro = [sum(r[0][i] for r in rs) / len(rs) for i in range(4)]
        out[name] = {"pair_precision": round(macro[0], 3), "pair_recall": round(macro[1], 3),
                     "pair_f1": round(macro[2], 3), "ari": round(macro[3], 3)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--resolution", type=float, default=RESOLUTION)
    ap.add_argument("--merge-same-label", action="store_true")
    ap.add_argument("--gbt", action="store_true", help="add Global Bible Tools per-word glosses (14 languages)")
    ap.add_argument("--compact", default=None, help="pickle from build_compact_renderings.py (many languages)")
    a = ap.parse_args()
    globals()["RESOLUTION"] = a.resolution
    globals()["USE_GBT"] = a.gbt
    globals()["COMPACT_FEATURES"] = a.compact
    result = build(a.out, merge_same_label=a.merge_same_label)
    multi = sum(1 for r in result.values() if len(set(r.values())) > 1)
    print(f"lexemes {len(result)}; split into >1 sense: {multi}", file=sys.stderr)
    if a.eval:
        print(json.dumps({"vs UBS index": evaluate(result, ubs_gold()),
                          "vs Mahberet Menahem": evaluate(result, menahem_gold())}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
