"""Greek parts of the Septuagint (GLAUx), cut by the same grammar-book rule as word-parts' Greek NT (build_greek_parts.py).
Local, unpublished.

    cd shoresh && .venv/bin/python -m macula.build_lxx_parts [--out DIR] [--alone]

Words: the canonical books of GLAUx's Septuagint (spine-releases `lxx-glaux-2026-10-10`, `canonical` = 1) and Daniel by
Theodotion (`lxx-glaux-dan-theodotion-2026-11-14`), the stores the bridge corpus pins (bridge_corpus_pins.json, sha256
checked). The Greek additions of Daniel 3 are kept here: a part cut does not depend on the Hebrew.

Ids: a part id is GLAUx's word id (its `glaux_id`, 9 digits, unique across both stores) followed by one part digit:
`1079760541`. They cannot clash with MACULA's (Greek 12 digits from book 40, Hebrew 12 / 13 digits). book, chapter, verse,
idx (GLAUx's numbering) are columns of words.tsv.

How a GLAUx word reaches the NT cutter: GLAUx's part of speech gives MACULA's class (RA det, RP RD RR RI RX pron, ...);
its code (CCAT style, `V.AAI3S`, `N.GSM`, perfect X, pluperfect Y, imperative D) is rewritten as Robinson's (`V-AAI-3S`,
`N-GSM`, R, L, M) and spelled out (tense, voice, mood, ...). A verb's lemma is the Greek NT's where GLAUx's Strong number
is a number of the NT (resources/lxx_bridge_tiers/greek_numbers.tsv; γίγνομαι -> γίνομαι), so greek-inflexion's stems
are found (also without Nestle's μ before ψ / φ: λημψ- and ληψ-); the word keeps GLAUx's lemma in words.tsv. Dodson is
looked up by the same number; a noun Dodson has no stem for takes the stem of its own commonest genitive singular
(basis `attested`).

The Greek NT's words are cut in the same run (so that a lexeme's stems come from all its forms in both corpora), and only
the Septuagint's are written (--alone: the Septuagint without the NT, to measure what the pooling changes). Then a
Septuagint word whose form and Robinson code occur in the Greek NT takes word-parts v1.1's NT cut (basis `nt`), so that one
form is cut one way in both corpora.

Kept whole (flags): a proper noun whose spellings all end in the same letter (Ἀδάμ, Ἰσραήλ, Βασά / Βαασα:
`indeclinable`, Robinson's N-PRI; a declined name changes its last letter) or that GLAUx gives no case; a word with GLAUx's elision mark (`elided`); a word broken by a hyphen or with stray letters
(`fragment`). Parts of kind `ending` carry GLAUx's own code as features.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import random
import re
import sqlite3
import unicodedata as ud
from pathlib import Path

from macula import build_greek_parts as gp
from macula import build_word_parts as wp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PINS = HERE / "bridge_corpus_pins.json"
NUMBERS = ROOT / "resources" / "lxx_bridge_tiers" / "greek_numbers.tsv"
OUT = ROOT / "internal-docs" / "lxx-parts" / "v0.2c"
WP_NT = ("bcv-commons/word-parts", "v1.1", "18098988")
CLS = {"N": "noun", "V": "verb", "A": "adj", "D": "adv", "C": "conj", "P": "prep", "RA": "det", "RP": "pron", "RD": "pron",
       "RR": "pron", "RI": "pron", "RX": "pron", "M": "num", "I": "intj", "X": "ptcl"}
TENSE = {"P": "present", "I": "imperfect", "F": "future", "A": "aorist", "X": "perfect", "Y": "pluperfect"}
VOICE = {"A": "active", "M": "middle", "P": "passive", "E": "middle"}
MOOD = {"I": "indicative", "S": "subjunctive", "O": "optative", "D": "imperative", "N": "infinitive", "P": "participle"}
CASE = {"N": "nominative", "G": "genitive", "D": "dative", "A": "accusative", "V": "vocative"}
NUMBER = {"S": "singular", "P": "plural", "D": "dual"}
GENDER = {"M": "masculine", "F": "feminine", "N": "neuter"}
GREEK = re.compile(r"^[Ͱ-Ͽἀ-῿̀-ͯ’]+$")


def stores() -> dict[str, Path]:
    p = json.loads(PINS.read_text(encoding="utf-8"))["stores"]
    out = {}
    for name in ("septuagint", "theodotion"):
        f = HERE.parent / p[name]["path"]
        if hashlib.sha256(f.read_bytes()).hexdigest() != p[name]["sha256"]:
            raise SystemExit(f"{f} is not the pinned store {p[name]['tag']}")
        out[name] = f
    return out


def glaux_rows(st: dict[str, Path]) -> list[dict]:
    rows = []
    for name, sql in (("septuagint", "select * from lxx_words where canonical = 1"),
                      ("theodotion", "select * from lxx_words where book = 'DAN'")):
        con = sqlite3.connect(f"file:{st[name]}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        for r in con.execute(sql + " order by book, chapter, verse, idx"):
            d = dict(r)
            d["text"] = "theodotion" if name == "theodotion" else "og"
            rows.append(d)
    return rows


def robinson(pos: str, code: str):
    """GLAUx's code -> (Robinson's morph, spelled-out fields)"""
    f = dict(tense=None, voice=None, mood=None, person=None, number=None, case=None, gender=None)
    body = code.split(".", 1)[1] if "." in code else ""
    if pos == "V" and len(body) >= 3:
        t, v, m, rest = body[0], body[1], body[2], body[3:]
        f.update(tense=TENSE.get(t), voice=VOICE.get(v), mood=MOOD.get(m))
        rt = {"X": "R", "Y": "L"}.get(t, t)
        rm = {"D": "M"}.get(m, m)
        if m == "P" and len(rest) >= 3:
            f.update(case=CASE.get(rest[0]), number=NUMBER.get(rest[1]), gender=GENDER.get(rest[2]))
            return f"V-{rt}{v}{rm}-{rest[:3]}", f
        if m in "ISOD" and len(rest) >= 2:
            f.update(person={"1": "first", "2": "second", "3": "third"}.get(rest[0]), number=NUMBER.get(rest[1]))
            return f"V-{rt}{v}{rm}-{rest[:2]}", f
        return f"V-{rt}{v}{rm}", f
    lead = {"N": "N", "A": "A", "RA": "T", "RP": "P", "RD": "P", "RR": "R", "RI": "I", "RX": "X"}.get(pos)
    if lead is None:
        return {"C": "CONJ", "P": "PREP", "D": "ADV", "M": "A-NUI", "I": "INJ", "X": "PRT"}.get(pos, pos), f
    b = body.replace("-", "")
    if pos == "RP" and b[:1] in "123":                       # RP.GS: person, case, number
        f.update(person=b[0], case=CASE.get(b[1:2]), number=NUMBER.get(b[2:3]))
        return f"P-{b[0]}{b[1:3]}", f
    if pos == "RP" and len(b) == 2:
        f.update(case=CASE.get(b[0]), number=NUMBER.get(b[1]))
        return f"P-{b}", f
    f.update(case=CASE.get(b[0:1]), number=NUMBER.get(b[1:2]), gender=GENDER.get(b[2:3]))
    return f"{lead}-{b}" if b else lead, f


def nt_lemmas(nt_words) -> tuple[dict[str, str], dict[str, str]]:
    """Strong number -> the Greek NT's lemma; GLAUx number -> NT number (greek_numbers.tsv)"""
    cnt = collections.defaultdict(collections.Counter)
    for w in nt_words:
        n = (w["strong"] or "").lstrip("G0")
        if n:
            cnt[n][w["lemma"]] += 1
    lem = {n: c.most_common(1)[0][0] for n, c in cnt.items()}
    to_nt = {}
    if NUMBERS.exists():
        with open(NUMBERS, encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                a, b = (r.get(k) for k in list(r)[:2])
                if a and b:
                    to_nt[str(a).lstrip("G0")] = str(b).lstrip("G0")
    return lem, to_nt


def lxx_words(rows, nt_words):
    lem, to_nt = nt_lemmas(nt_words)
    spellings = collections.defaultdict(set)
    for r in rows:
        if r["pos"] == "N" and r["lemma"][:1].isupper():
            spellings[r["lemma"]].add(wp.plain(r["surface"]))
    words, meta = [], {}
    for r in rows:
        key = str(r["glaux_id"])
        code = r["morph"] or r["pos"]
        if r["pos"] == "RP" and code.count(".") == 1 and len(code.split(".")[1]) == 2 and r["lemma"] in ("ἐγώ", "σύ"):
            code = f"RP.{'1' if r['lemma'] == 'ἐγώ' else '2'}{code.split('.')[1]}"   # GLAUx gives no person: the lemma's
        morph, f = robinson(r["pos"], code)
        surface, flags = ud.normalize("NFC", r["surface"]), []
        cls = CLS.get(r["pos"], "")
        if r["pos"] == "N" and r["lemma"][:1].isupper() and (len({x[-1:] for x in spellings[r["lemma"]]}) == 1 or not f["case"]):
            morph, flags = "N-PRI", ["indeclinable"]
        if not GREEK.match(surface) or surface.endswith("-"):
            cls, flags = "", ["fragment"]
        n = (str(r["strong"]) if r["strong"] is not None else "").lstrip("0")
        n_nt = to_nt.get(n, n) or ("L" + wp.plain(r["lemma"]) if cls in ("noun", "adj") else "")
        lemma = lem.get(n_nt, r["lemma"]) if cls == "verb" else r["lemma"]
        words.append(dict(key=key, surface=surface.rstrip("’") if surface.endswith("’") else surface, lemma=lemma, cls=cls,
                          morph=morph, strong=n_nt, after="’" if surface.endswith("’") else "",
                          wtype="relative" if r["pos"] == "RR" else None, **f))
        meta[key] = dict(text=r["text"], book=r["book"], chapter=r["chapter"], verse=r["verse"], idx=r["idx"],
                         glaux_lemma=r["lemma"], glaux_morph=r["morph"] or "", flags=flags, surface=surface)
    return words, meta


def septuagint_spellings(lex):
    """greek-inflexion's stems with Nestle 1904's μ before ψ / φ (λημψ-, λημφθ-) also without it, as the Septuagint spells
    them (λήψεται, ληφθήσεται)"""
    def more(xs):
        return list(dict.fromkeys(xs + [x.replace("μψ", "ψ").replace("μφ", "φ") for x in xs if "μψ" in x or "μφ" in x]))
    for e in lex.values():
        e["stems"] = {k: more(v) for k, v in e["stems"].items()}
        e["overrides"] = [(rx, more(v)) for rx, v in e["overrides"]]
    return lex


def attested_stems(words, dod):
    """nouns Dodson has no stem for (Septuagint-only words, or none under their number): the stem from the word's own
    commonest genitive singular, its ending taken off as read_dodson does (δόρατος -> δορατ-)"""
    gen = collections.defaultdict(collections.Counter)
    for w in words:
        if w["cls"] == "noun" and w["case"] == "genitive" and w["number"] == "singular" and w["strong"]:
            gen[w["strong"].lstrip("G0")][wp.plain(w["surface"])] += 1
    added = set()
    for k, c in gen.items():
        if k in dod:
            continue
        g = c.most_common(1)[0][0]
        ge = next((e for e in gp.GEN_END if g.endswith(e) and len(g) > len(e) + 1), None)
        if ge:
            dod[k] = ("noun", [g[:-len(ge)]], ge); added.add(k)
    return added


def nt_cut():
    """word-parts v1.1's Greek NT: (form, Robinson code) -> {cut: count} and cut -> its parts [(text, kind, features)]"""
    from huggingface_hub import HfApi, hf_hub_download
    repo, tag, commit = WP_NT
    sha = HfApi().dataset_info(repo, revision=tag).sha
    if not sha.startswith(commit):
        raise SystemExit(f"{repo} tag {tag} is {sha[:8]}, the pin says {commit}")
    rd = lambda n: csv.DictReader(open(hf_hub_download(repo, n, repo_type="dataset", revision=sha), encoding="utf-8",
                                       newline=""), delimiter="\t", quoting=csv.QUOTE_NONE)
    parts = collections.defaultdict(list)
    for r in rd("greek/parts.tsv"):
        parts[r["word_id"]].append((int(r["n"]), r["text"], r["kind"], r["features"]))
    out, shape = collections.defaultdict(collections.Counter), {}
    for r in rd("greek/words.tsv"):
        k = (ud.normalize("NFC", r["surface"]), r["morph"])
        out[k][r["cut"]] += 1
        shape.setdefault((k, r["cut"]), [p[1:] for p in sorted(parts[r["word_id"]])])
    return out, shape


def take_nt(out_parts, out_words, nt, shape, stat):
    """a Septuagint word whose form and code occur in the Greek NT takes the NT's (commonest) cut, kinds and all"""
    parts = collections.defaultdict(list)
    for p in out_parts:
        parts[p[1]].append(p)
    new_parts, new_words = [], []
    for w in out_words:
        c = nt.get((ud.normalize("NFC", w[2]), w[5]))
        if c and w[6] != "whole":
            cut = c.most_common(1)[0][0]
            if cut != w[7]:
                stat["took the NT's cut (it differed)"] += 1
            sh = shape[((ud.normalize("NFC", w[2]), w[5]), cut)]
            at, rows = 0, []
            for n, (t, kind, feat) in enumerate(sh, 1):
                ln = len(wp.graphemes(t))
                rows.append((f"{w[0]}{n}", w[0], n, at, at + ln, t, kind, feat)); at += ln
            new_parts += rows
            new_words.append(w[:6] + ("nt",) + (cut,) + (w[8],))
        else:
            new_parts += parts[w[0]]
            new_words.append(w)
    return new_parts, new_words


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--src", type=Path, default=gp.SRC)
    ap.add_argument("--alone", action="store_true", help="cut the Septuagint without the Greek NT's forms")
    a = ap.parse_args()
    if a.out.exists() and any(a.out.iterdir()):
        raise SystemExit(f"{a.out} is not empty; give a fresh folder")
    a.out.mkdir(parents=True, exist_ok=True)
    st = stores()
    nt_words = wp.read_grc(wp.GRC_DIR)
    words, meta = lxx_words(glaux_rows(st), nt_words)
    lex = septuagint_spellings(gp.read_inflexion(a.src / "morphgnt_lexicon.yaml"))
    dod = gp.read_dodson(a.src / "dodson.csv")
    att = attested_stems(words, dod)
    n_att = len(att)
    pool = words if a.alone else nt_words + words
    out_parts, out_words, stat = gp.build(pool, lex, dod)
    strong_of = {w["key"]: (w["strong"] or "").lstrip("G0") for w in words}
    out_words = [w[:6] + ("attested",) + w[7:] if w[6] == "dodson" and strong_of.get(w[0]) in att else w for w in out_words]
    keep = set(meta)
    out_parts = [p for p in out_parts if p[1] in keep]
    out_words = [w for w in out_words if w[0] in keep]
    nt, shape = nt_cut()
    took = collections.Counter()
    out_parts, out_words = take_nt(out_parts, out_words, nt, shape, took)
    code_of = {k: m["glaux_morph"] for k, m in meta.items()}
    out_parts = [p[:7] + ((code_of[p[1]] if p[6] in ("ending", "fused") else p[7]),) for p in out_parts]
    by_word = {w[0]: w for w in out_words}
    with open(a.out / "parts.tsv", "w", encoding="utf-8") as f:
        f.write("part_id\tword_id\tn\tstart\tend\ttext\tkind\tfeatures\n")
        f.writelines("\t".join(map(str, p)) + "\n" for p in out_parts)
    with open(a.out / "words.tsv", "w", encoding="utf-8") as f:
        f.write("word_id\ttext\tbook\tchapter\tverse\tidx\tlead\tsurface\ttrail\tlemma\tmorph\tbasis\tcut\tflags\n")
        for k, w in by_word.items():
            m = meta[k]
            fl = ",".join(x for x in [*m["flags"], *w[8].split(",")] if x)
            f.write("\t".join(map(str, [k, m["text"], m["book"], m["chapter"], m["verse"], m["idx"], w[1], w[2], w[3],
                                        m["glaux_lemma"], m["glaux_morph"], w[6], w[7], fl])) + "\n")
    # checks
    texts = collections.defaultdict(list)
    for p in out_parts:
        texts[p[1]].append(p[5])
    broken = [w[0] for w in out_words if wp.nfc(w[1]) + "".join(texts[w[0]]) + wp.nfc(w[3]) != ud.normalize("NFC", w[2])]
    fl = collections.Counter(x for w in out_words for x in w[8].split(",") if x and x != "rebuild_failed")
    fl["rebuild_failed"] = len(broken)
    ids = [p[0] for p in out_parts]
    basis = collections.Counter(w[6] for w in out_words)
    kinds = collections.Counter(p[6] for p in out_parts)
    L = ["# Septuagint Greek parts (GLAUx): acceptance figures", "",
         f"Words: {len(out_words):,} ({sum(1 for m in meta.values() if m['text'] == 'og'):,} canonical books, "
         f"{sum(1 for m in meta.values() if m['text'] == 'theodotion'):,} Daniel by Theodotion). Parts: {len(out_parts):,}. "
         f"Rebuild failures: {fl['rebuild_failed']}. Duplicate part ids: {len(ids) - len(set(ids))}. "
         f"Words with more than 9 parts: {fl['more_than_9_parts']}. Pooled with the Greek NT: {not a.alone}.", "",
         "## Basis", ""] + [f"- {k}: {v:,}" for k, v in basis.most_common()]
    L += ["", "## Parts by kind", ""] + [f"- {k}: {v:,}" for k, v in kinds.most_common()]
    L += ["", "## Flags", ""] + [f"- {k}: {v:,}" for k, v in fl.most_common()]
    L += ["", "## Our flags (kept whole)", ""] + [f"- {k}: {v:,}" for k, v in
                                                 collections.Counter(x for m in meta.values() for x in m["flags"]).most_common()]
    L += ["", f"Noun stems from their own attested genitive (no Dodson stem): {n_att:,} lexemes"]
    L += ["", "## Taken from the Greek NT", ""] + [f"- {k}: {v:,}" for k, v in took.items()]
    same = diff = 0
    ex = collections.Counter()
    for k, w in by_word.items():
        c = nt.get((ud.normalize("NFC", w[2]), w[5]))
        if not c:
            continue
        if w[7] in c:
            same += 1
        else:
            diff += 1
            ex[(w[2], w[5], w[7], c.most_common(1)[0][0])] += 1
    L += ["", "## Against word-parts v1.1's Greek NT cut (same form, same code)", "",
          f"Septuagint words whose form and code occur in the NT: {same + diff:,}; same cut as the NT: {same:,} "
          f"({same / max(1, same + diff):.1%}).", "", "| count | form | code | ours | NT |", "|---|---|---|---|---|"]
    L += [f"| {n} | {f} | {m} | {o} | {t} |" for (f, m, o, t), n in ex.most_common(40)]
    (a.out / "checks.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    rnd = random.Random(20261123)
    sample = sorted(rnd.sample([w for w in out_words if w[6] != "whole" and not meta[w[0]]["flags"]], 200))
    with open(a.out / "sample_200.tsv", "w", encoding="utf-8") as f:
        f.write("word_id\tbook\tchapter\tverse\tsurface\tlemma\tmorph\tbasis\tcut\tflags\tverdict\n")
        for w in sample:
            m = meta[w[0]]
            f.write("\t".join(map(str, [w[0], m["book"], m["chapter"], m["verse"], w[2], m["glaux_lemma"], m["glaux_morph"],
                                        w[6], w[7], w[8], ""])) + "\n")
    (a.out / "build.json").write_text(json.dumps({
        "release": "Septuagint Greek parts (local, unpublished)", "pooled_with_nt": not a.alone,
        "stores": {k: json.loads(PINS.read_text())["stores"][k] for k in ("septuagint", "theodotion")},
        "words": len(out_words), "parts": len(out_parts)}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print((a.out / "checks.md").read_text(encoding="utf-8")[:6000])


if __name__ == "__main__":
    main()
