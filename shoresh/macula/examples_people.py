"""Stage 06 (participants and speech) of the source-examples build, SPEC 1.0 sections 3 (`ent`, `quote`), 4.2 (`who`,
`who_basis`), 4.3 (`quote`, `speaker`, `addressee`), 4.5 (`participants.tsv`), 4.8 (`facts.parquet`, the kin
relations), D7, D10.

Reads the stage-02..05 tables, MACULA's references on the pieces (lowfat, through examples_src's cached parse), the
morphId -> pid map of stage 02 (cache/morphid.parquet), our entities (data/entities: entity_words.tsv, entities.tsv,
characters.tsv, kinship.tsv), our addressees (data/addressees/quotations.tsv), the clause layouts, and the speech data
rebuilt without review rows by examples_speech_src.py into <build>/cache/speech-hbo/ and speech-grc/ (run here as a
subprocess, anew every time). Writes pieces.parquet, clauses.parquet (only `who`, `who_basis`, `quote`, `speaker`,
`addressee` change), participants.tsv and facts.parquet anew.

Rules as implemented (the report gives the counts):
- D7 steps 1-3 take entity_words rows of kind explicit, pronominal, subject keyed to the piece; rows of kind speech
  are never read; keyterm entities are not taken. Step 4 (chain): the piece's own reference attribute (Hebrew
  participantref, else subjref; Greek referent, else subjref; no piece has both) names target pieces; Hebrew targets
  are morphIds read through the morphId map; `who` is the union of the targets' `who` from steps 1-3.
- A piece whose class is a conjunction, preposition or article (hbo/arc cj, prep, art; grc conj, prep, det) takes
  `who` only from step 1 (SPEC 10, participants); what steps 2-4 would give it is left empty and listed.
- D10: a clause's `quote` is the quotation of its layout line (D11 `line`): Hebrew the segment row of the rebuilt
  speaker layer, Greek the layout's `quotation`. `speaker`: the quotation's character id (no-review) through
  characters.tsv to an ACAI id, as an `ent`. `addressee`: addressees/quotations.tsv, the quotation's ACAI id as an
  `ent`; `lemma:<strong>` and keyterm ids are not participants and stay empty (counted).
- participants.tsv: one row per `ent` in who, speaker or addressee of the language.
- facts.parquet: the kin relations of kinship.tsv whose two sides are both participants of the language.
"""
import collections as C
import csv
import glob
import hashlib
import json
import os
import pickle
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq

import examples_common as X
import examples_src as S

D = os.path.join(S.HERE, "data")
ENT = os.path.join(D, "entities")
ADDR = os.path.join(D, "addressees", "quotations.tsv")
SPEAKER_PUBLISHED = os.path.join(D, "speaker-layer")
HEB_LAYOUT = os.path.join(D, "clause-layout", "clauses")
GRC_LAYOUT = os.path.join(D, "nt-clause-layout", "clauses")
TYPES = ("person", "place", "group", "deity", "realia", "flora", "fauna")
KIN = ("father", "mother", "offspring", "sibling", "partner", "tribe", "group_origin")
KIN_NOT_TAKEN = ("possibly_same_as", "birth_place", "death_place")
NAME_PREFIX = {"hbo": "he:", "arc": "arc:", "grc": "el:"}
SEX = {"male": "m", "female": "f"}
NO_WHO_CLASSES = {"hbo": {"cj", "prep", "art"}, "arc": {"cj", "prep", "art"}, "grc": {"conj", "prep", "det"}}
FACT_SCHEMA = pa.schema([("subject", pa.string()), ("relation", pa.string()), ("object", pa.string()),
                         ("kind", pa.string()), ("method", pa.string()), ("source", pa.string()),
                         ("confidence", pa.float64()), ("count", pa.int64()), ("share", pa.float64()),
                         ("tier", pa.string())])
PART_HEADER = ["ent", "type", "name", "sex", "words"]
csv.field_size_limit(1 << 30)


def ent_key(acai, etype):
    return f"{etype}:e{hashlib.sha1(acai.encode('utf-8')).hexdigest()[:10]}"


def read_tsv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader((ln for ln in fh if not ln.startswith("#")), delimiter="\t",
                                   quoting=csv.QUOTE_NONE))


class Entities:
    """ACAI ids -> ent keys (type from entities.tsv), with name and sex; records every key made."""

    def __init__(self, cnt):
        self.rows = {r["entity"]: r for r in read_tsv(os.path.join(ENT, "entities.tsv"))}
        self.cnt = cnt
        self.acai_of = {}

    def ent(self, acai, tag):
        """The ent key of an ACAI id, or None (counted under tag) where it is no participant."""
        r = self.rows.get(acai)
        if r is None:
            self.cnt[f"{tag}: ACAI id not in entities.tsv, not taken"] += 1
            return None
        if r["type"] not in TYPES:
            self.cnt[f"{tag}: type {r['type']}, not taken"] += 1
            return None
        k = ent_key(acai, r["type"])
        prev = self.acai_of.setdefault(k, acai)
        if prev != acai:
            raise SystemExit(f"two ACAI ids give one ent key: {prev} {acai} -> {k}")
        return k


# ---- D7 ----------------------------------------------------------------------------------------------------------

def entity_rows(E, cnt):
    """(pid, kind) -> set of ent keys, kinds explicit, pronominal, subject."""
    out = C.defaultdict(set)
    with open(os.path.join(ENT, "entity_words.tsv"), encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            kind = r["kind"]
            greek = len(r["word"]) == 11
            tag = f"{'grc' if greek else 'tan'} entity_words {kind}"
            cnt[f"{tag} rows"] += 1
            if kind == "speech":
                continue
            k = E.ent(r["entity"], tag)
            if k is None:
                continue
            out[(("n" if greek else "o") + r["word"], kind)].add(k)
    return out


def refs_of(greek):
    """pid -> (attribute, [target pid or morphId]) for every piece with a reference attribute."""
    data = S.grc_lowfat() if greek else S.heb_lowfat()
    attrs = ("referent", "subjref") if greek else ("participantref", "subjref")
    out, both = {}, 0
    for _, _, sents in data:
        for pieces, _ in sents:
            for p in pieces:
                have = [a for a in attrs if p.get(a)]
                if len(have) > 1:
                    both += 1
                if have:
                    out[p["id"]] = (have[0], p[have[0]].split())
    return out, both


def d7(pieces_by_lang, greek, rows, morph, cnt, ex):
    """pieces_by_lang: lang -> dict of columns. Returns lang -> (who list, who_basis list)."""
    tag = "grc" if greek else "tan"
    refs, both = refs_of(greek)
    cnt[f"{tag} D7 pieces with two reference attributes"] = both
    base = {}                                                   # pid -> (ents, basis) from steps 1-3
    cls_of = {}
    for lang, P in pieces_by_lang.items():
        for pid, cl in zip(P["pid"], P["class"]):
            cls_of[pid] = (lang, cl)
            for kind in ("explicit", "pronominal", "subject"):
                es = rows.get((pid, kind))
                if es:
                    base[pid] = (es, kind)
                    break
    keys = set(cls_of)
    for (pid, kind) in sorted(rows):
        if pid[0] == ("n" if greek else "o") and pid not in keys:
            cnt[f"{tag} D7 entity_words rows keyed to no piece ({kind})"] += 1
            ex[f"{tag} D7 entity_words key is no piece"].append(pid)
    out = {}
    for lang, P in pieces_by_lang.items():
        bad = NO_WHO_CLASSES[lang]
        who, basis = [], []
        for pid, cl in zip(P["pid"], P["class"]):
            got = base.get(pid)
            if got is None and pid in refs:
                attr, targets = refs[pid]
                es = set()
                for tg in targets:
                    tp = tg if greek else morph.get(tg)
                    if tp is None:
                        cnt[f"{tag} D7 chain target unresolved ({attr})"] += 1
                        ex[f"{tag} D7 chain target unresolved"].append(f"{pid} {tg}")
                        continue
                    if not greek and morph_as_xmlid(tg, morph) != tp:
                        cnt[f"{tag} D7 chain target that as xml:id would give another piece or none"] += 1
                    b = base.get(tp)
                    if b is None:
                        cnt[f"{tag} D7 chain target with no who from steps 1-3 ({attr})"] += 1
                    else:
                        es |= b[0]
                if es:
                    got = (es, "chain")
                else:
                    cnt[f"{tag} D7 pieces with a reference whose targets give no who ({attr})"] += 1
            if got is not None and cl in bad and got[1] != "explicit":
                cnt[f"{lang} D7 left empty: class {cl}, basis {got[1]}"] += 1
                ex[f"{lang} D7 left empty on a {'/'.join(sorted(bad))} piece (pid basis)"].append(f"{pid} {got[1]}")
                got = None
            if got is None:
                who.append("")
                basis.append("")
            else:
                who.append(" ".join(sorted(got[0])))
                basis.append(got[1])
                cnt[f"{lang} D7 pieces with who: {got[1]}"] += 1
                if len(got[0]) > 1:
                    cnt[f"{lang} D7 pieces with two or more participants: {got[1]}"] += 1
        out[lang] = (who, basis)
    return out


_XID_PIDS = None


def morph_as_xmlid(tg, morph):
    """What a Hebrew reference target would name read as an xml:id: the pid 'o'+target if that piece exists."""
    p = "o" + tg
    return p if p in _XID_PIDS else None


# ---- D10 ---------------------------------------------------------------------------------------------------------

def speech_sources(outdir):
    """Rebuild the speech data without review rows into <outdir>/cache/speech-<hbo|grc>/ (subprocesses)."""
    script = os.path.join(S.HERE, "examples_speech_src.py")
    for lang in ("hbo", "grc"):
        folder = os.path.join(outdir, "cache", f"speech-{lang}")
        log = os.path.join(outdir, "cache", f"speech-{lang}.log")
        with open(log, "w", encoding="utf-8") as fh:
            r = subprocess.run([sys.executable, "-I", script, lang, folder], stdout=fh, stderr=subprocess.STDOUT)
        if r.returncode:
            raise SystemExit(f"examples_speech_src.py {lang} failed (log {log})")


def characters(E, cnt):
    """character id -> (ACAI id or '', ent or None)."""
    out = {}
    for r in read_tsv(os.path.join(ENT, "characters.tsv")):
        acai = r["entity"]
        tag = f"{'grc' if r['character'].startswith('n') else 'tan'} characters.tsv"
        out[r["character"]] = E.ent(acai, tag) if acai else None
        if not acai:
            cnt[f"{tag}: character with no entity"] += 1
    return out


def addressees(E, corpus, cnt):
    out = {}
    tag = f"{'grc' if corpus == 'grc' else 'tan'} addressee"
    for r in read_tsv(ADDR):
        if r["corpus"] != corpus:
            continue
        a = r["addressee"]
        if not a:
            out[r["quote"]] = None
            cnt[f"{tag}: quotations with no addressee in the dataset"] += 1
        elif a.startswith("lemma:"):
            out[r["quote"]] = None
            cnt[f"{tag}: quotations whose addressee is lemma:<strong>, left empty"] += 1
        else:
            out[r["quote"]] = E.ent(a, tag)
    return out


def heb_speech(outdir):
    """line -> quotation id (rebuilt layer); quotation id -> row."""
    folder = os.path.join(outdir, "cache", "speech-hbo")
    seg = {}
    for f in sorted(glob.glob(os.path.join(folder, "segments", "*.tsv"))):
        book = os.path.basename(f)[:-4]
        for r in read_tsv(f):
            seg[f"{book}.{r['chapter']}.{r['verse']}.{r['seg']}"] = r["quotation"]
    quotes = {r["id"]: r for r in read_tsv(os.path.join(folder, "quotations.tsv"))}
    return seg, quotes


def heb_speech_published():
    seg = {}
    for f in sorted(glob.glob(os.path.join(SPEAKER_PUBLISHED, "segments", "*.tsv"))):
        book = os.path.basename(f)[:-4]
        for r in read_tsv(f):
            seg[f"{book}.{r['chapter']}.{r['verse']}.{r['seg']}"] = r["quotation"]
    quotes = {r["id"]: r for r in read_tsv(os.path.join(SPEAKER_PUBLISHED, "quotations.tsv"))}
    return seg, quotes


def grc_speech(outdir):
    """line -> quotation id (the layout); quotation id -> no-review row; quotation id -> the layout's speaker_id."""
    seg, layout_sid = {}, {}
    for f in sorted(glob.glob(os.path.join(GRC_LAYOUT, "*", "*.jsonl"))):
        book, chap = os.path.basename(f)[:-len(".jsonl")].rsplit("_", 1)
        with open(f, encoding="utf-8") as fh:
            for ln in fh:
                r = json.loads(ln)
                q = r["quotation"] or ""
                seg[f"{book}.{int(chap)}.{r['verse']}.{r['seg']}"] = q
                if q:
                    prev = layout_sid.setdefault(q, r["speaker_id"] or "")
                    if prev != (r["speaker_id"] or ""):
                        raise SystemExit(f"Greek layout: quotation {q} has two speaker ids")
    quotes = {r["id"]: r for r in read_tsv(os.path.join(outdir, "cache", "speech-grc", "quotations.tsv"))}
    return seg, quotes, layout_sid


def d10(K_by_lang, greek, outdir, E, chars, cnt, ex, counts):
    tag = "grc" if greek else "tan"
    addr = addressees(E, "grc" if greek else "hbo", cnt)
    if greek:
        seg, quotes, layout_sid = grc_speech(outdir)
        sid = {q: r["speaker_id"] for q, r in quotes.items()}
        level = {q: int(r["level"]) for q, r in quotes.items()}
        diff = [q for q in sorted(layout_sid) if layout_sid[q] != sid.get(q, "")]
        cnt[f"{tag} D10 quotations whose speaker_id differs without review rows"] = len(diff)
        ex[f"{tag} D10 speaker_id differs without review rows (quotation layout no-review)"] = \
            [f"{q} {layout_sid[q]} {sid.get(q, '')}" for q in diff]
        missing = sorted(set(layout_sid) - set(quotes))
        cnt[f"{tag} D10 layout quotations not among the rebuilt quotations"] = len(missing)
        ex[f"{tag} D10 layout quotation not rebuilt"] = missing
    else:
        seg, quotes = heb_speech(outdir)
        sid = {q: r["speaker_id"] for q, r in quotes.items()}
        level = {q: int(r["level"]) for q, r in quotes.items()}
        pseg, pquotes = heb_speech_published()
        cnt[f"{tag} D10 rebuilt layer: quotations"] = len(quotes)
        cnt[f"{tag} D10 published layer (with review rows): quotations"] = len(pquotes)
        cnt[f"{tag} D10 quotations only in the published layer (review rows)"] = len(set(pquotes) - set(quotes))
        cnt[f"{tag} D10 quotations only in the rebuilt layer"] = len(set(quotes) - set(pquotes))
        cnt[f"{tag} D10 quotations in both whose speaker_id differs"] = \
            sum(1 for q in quotes if q in pquotes and pquotes[q]["speaker_id"] != quotes[q]["speaker_id"])
        cnt[f"{tag} D10 quotations in both whose span differs"] = \
            sum(1 for q in quotes if q in pquotes and (pquotes[q]["first"], pquotes[q]["last"]) !=
                (quotes[q]["first"], quotes[q]["last"]))
        cnt[f"{tag} D10 segments: rebuilt layer"] = len(seg)
        cnt[f"{tag} D10 segments: published layer"] = len(pseg)
        cnt[f"{tag} D10 segments of the rebuilt layer whose quotation differs in the published layer"] = \
            sum(1 for k, q in seg.items() if pseg.get(k) != q)
        cnt[f"{tag} D10 segments of the rebuilt layer not in the published layer"] = \
            sum(1 for k in seg if k not in pseg)
    counts[f"{tag} D10 quotations by level"] = dict(sorted(C.Counter(str(v) for v in level.values()).items()))
    used_q = set()
    out = {}
    for lang, K in K_by_lang.items():
        quote, speaker, addressee = [], [], []
        lv = C.Counter()
        for ck, line in zip(K["clause"], K["line"]):
            if line not in seg:
                cnt[f"{lang} D10 clauses whose line is not in the speech segments"] += 1
                ex[f"{lang} D10 clause line not in the speech segments"].append(ck)
                q = ""
            else:
                q = seg[line]
            if not q:
                quote.append("")
                speaker.append("")
                addressee.append("")
                continue
            if q not in sid:
                raise SystemExit(f"{lang}: quotation {q} of line {line} not in the quotation table")
            used_q.add(q)
            lv[str(level[q])] += 1
            quote.append(f"q:{q}")
            c = sid[q]
            e = chars.get(c) if c else None
            if not c:
                cnt[f"{lang} D10 clauses in a quotation with no character id"] += 1
            elif c not in chars:
                cnt[f"{lang} D10 clauses whose character id is not in characters.tsv"] += 1
                ex[f"{lang} D10 character id not in characters.tsv"].append(f"{ck} {c}")
            elif e is None:
                cnt[f"{lang} D10 clauses whose character has no participant"] += 1
            speaker.append(e or "")
            if q not in addr:
                cnt[f"{lang} D10 clauses whose quotation has no row in addressees"] += 1
                a = None
            else:
                a = addr[q]
            addressee.append(a or "")
        cnt[f"{lang} D10 clauses with quote"] = sum(1 for v in quote if v)
        cnt[f"{lang} D10 clauses with speaker"] = sum(1 for v in speaker if v)
        cnt[f"{lang} D10 clauses with addressee"] = sum(1 for v in addressee if v)
        counts[f"{lang} D10 clauses with quote by quotation level"] = dict(sorted(lv.items()))
        out[lang] = (quote, speaker, addressee)
    cnt[f"{tag} D10 quotations that hold the line of at least one clause"] = len(used_q)
    cnt[f"{tag} D10 quotations that hold no clause's line"] = len(set(sid) - used_q)
    return out


# ---- the build ---------------------------------------------------------------------------------------------------

def read_cols(path):
    t = pq.read_table(path)
    return t.to_pydict(), pa.schema([t.schema.field(i) for i in range(len(t.schema))])


def name_of(E, acai, lang):
    for x in E.rows[acai]["lemmas"].split(" | "):
        if x.startswith(NAME_PREFIX[lang]):
            return x[len(NAME_PREFIX[lang]):]
    return ""


def build(outdir, langs, counts):
    global _XID_PIDS
    ex = C.defaultdict(list)
    cnt = C.Counter()
    if {"hbo", "arc"} & set(langs) and not {"hbo", "arc"} <= set(langs):
        raise SystemExit("stage 06: hbo and arc are built together (references cross them)")
    speech_sources(outdir)
    E = Entities(cnt)
    rows = entity_rows(E, cnt)
    chars = characters(E, cnt)
    mt = pq.read_table(os.path.join(outdir, "cache", "morphid.parquet"), columns=["morphid", "pid"]).to_pydict()
    morph = dict(zip(mt["morphid"], mt["pid"]))
    groups = []
    if "hbo" in langs:
        groups.append((("hbo", "arc"), False))
    if "grc" in langs:
        groups.append((("grc",), True))
    tables = {}
    for gl, greek in groups:
        P, Ps, K, Ks = {}, {}, {}, {}
        for lang in gl:
            P[lang], Ps[lang] = read_cols(os.path.join(outdir, lang, "pieces.parquet"))
            K[lang], Ks[lang] = read_cols(os.path.join(outdir, lang, "clauses.parquet"))
        _XID_PIDS = {p for lang in gl for p in P[lang]["pid"]}
        whos = d7(P, greek, rows, morph, cnt, ex)
        speech = d10(K, greek, outdir, E, chars, cnt, ex, counts)
        for lang in gl:
            P[lang]["who"], P[lang]["who_basis"] = whos[lang]
            K[lang]["quote"], K[lang]["speaker"], K[lang]["addressee"] = speech[lang]
            tables[lang] = (P[lang], Ps[lang], K[lang], Ks[lang])
    kin = read_tsv(os.path.join(ENT, "kinship.tsv"))
    for lang in langs:
        Pd, Psch, Kd, Ksch = tables[lang]
        d = os.path.join(outdir, lang)
        X.write_parquet(os.path.join(d, "pieces.parquet"), Pd, Psch)
        X.write_parquet(os.path.join(d, "clauses.parquet"), Kd, Ksch)
        words = C.defaultdict(set)
        for t, w in zip(Pd["t"], Pd["who"]):
            for e in w.split():
                words[e].add(t)
        ents = set(words) | {e for e in Kd["speaker"] if e} | {e for e in Kd["addressee"] if e}
        prows = []
        for e in sorted(ents):
            acai = E.acai_of[e]
            r = E.rows[acai]
            nm = name_of(E, acai, lang)
            prows.append((e, r["type"], nm, SEX.get(r["gender"], ""), len(words.get(e, ()))))
            if not nm:
                cnt[f"{lang} participants with no name in {NAME_PREFIX[lang]}"] += 1
                if lang == "arc" and name_of(E, acai, "hbo"):
                    cnt["arc participants with no arc: lemma but a he: lemma"] += 1
            if r["gender"] and r["gender"] not in SEX:
                cnt[f"{lang} participants with a gender not m/f: {r['gender']}"] += 1
        X.write_tsv(os.path.join(d, "participants.tsv"), PART_HEADER, prows)
        cnt[f"{lang} participants"] = len(prows)
        cnt[f"{lang} participants only as speaker or addressee"] = sum(1 for r in prows if r[4] == 0)
        counts[f"{lang} participants by type"] = dict(sorted(C.Counter(r[1] for r in prows).items()))
        counts[f"{lang} top participants by words"] = [[r[0], r[2], r[4]] for r in
                                                       sorted(prows, key=lambda r: (-r[4], r[0]))[:20]]
        # kin facts between participants of this language
        facts = set()
        for r in kin:
            rel = r["relation"]
            if rel in KIN_NOT_TAKEN:
                cnt[f"{lang} kin rows not taken: {rel}"] += 1
                continue
            if rel not in KIN:
                raise SystemExit(f"kinship.tsv: relation {rel!r} not in the specification")
            a = E.rows.get(r["entity"])
            b = E.rows.get(r["other"])
            if a is None or b is None:
                cnt[f"{lang} kin rows with an ACAI id not in entities.tsv"] += 1
                continue
            sa, so = ent_key(r["entity"], a["type"]), ent_key(r["other"], b["type"])
            if a["type"] not in TYPES or b["type"] not in TYPES:
                cnt[f"{lang} kin rows with a keyterm side"] += 1
                continue
            if sa not in ents or so not in ents:
                cnt[f"{lang} kin rows left out: a side is no participant of the language"] += 1
                continue
            facts.add((sa, rel, so))
        facts = sorted(facts)
        cols = {"subject": [f[0] for f in facts], "relation": [f[1] for f in facts], "object": [f[2] for f in facts],
                "kind": ["given"] * len(facts), "method": ["kinship.tsv:relation"] * len(facts),
                "source": ["acai"] * len(facts), "confidence": [None] * len(facts), "count": [None] * len(facts),
                "share": [None] * len(facts), "tier": [""] * len(facts)}
        X.write_parquet(os.path.join(d, "facts.parquet"), cols, FACT_SCHEMA)
        cnt[f"{lang} facts rows"] = len(facts)
        counts[f"{lang} facts by relation"] = dict(sorted(C.Counter(f[1] for f in facts).items()))
        # words with a participant by basis and by class of the piece
        by = C.Counter()
        tb = C.defaultdict(set)
        for t, cl, b in zip(Pd["t"], Pd["class"], Pd["who_basis"]):
            if b:
                by[f"{b} {cl}"] += 1
                tb[b].add(t)
        counts[f"{lang} pieces with who by basis and class"] = dict(sorted(by.items()))
        counts[f"{lang} words with who by basis (a word counts once per basis)"] = \
            {b: len(v) for b, v in sorted(tb.items())}
        cnt[f"{lang} words with who"] = len({t for t, w in zip(Pd["t"], Pd["who"]) if w})
    counts["pins"] = {os.path.relpath(p, S.HERE): S.sha256(p) for p in (
        os.path.join(ENT, "entity_words.tsv"), os.path.join(ENT, "entities.tsv"), os.path.join(ENT, "characters.tsv"),
        os.path.join(ENT, "kinship.tsv"), ADDR)}
    for k in sorted(cnt):
        counts[k] = cnt[k]
    return ex
