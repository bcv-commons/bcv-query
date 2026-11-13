#!/usr/bin/env python3
"""Inclusive / exclusive "we": votes from openly licensed translations in languages that mark it (wave 1d, development-phase plan
2026-11-13; plan explained to the user the same day).

For every verse with a first-person plural in the Hebrew or Greek, count in each edition the inclusive and the exclusive forms of a
closed per-language list, after mapping the edition's (English) verse numbering to the source's (macula's org numbering, vrsmap). A
verse with only inclusive forms is an inclusive vote, only exclusive an exclusive vote, both a mixed verse (settled later by word
links or a judge), neither no vote. No alignment is used.

    cd shoresh && .venv/bin/python3 -m macula.build_we_votes

Inputs: MACULA Hebrew (lowfat-hbo.db: morph ...1cp on verbs, pronouns and suffixes), the Greek spine (first person plural verbs,
plural ἐγώ, ἡμέτερος); the editions' USJ as cached by lexeme-aligner's ingest (CC BY-SA / public domain, eBible; licences checked
2026-11-13). Output (git-ignored, never published as text): macula/data/we-votes/
  verses.tsv   book, chapter, verse (source numbering), src_we (count), src_keys, then per edition i / e / m / - (inclusive, exclusive,
               mixed, no form = abstention), and n_i, n_e, n_m, value (i | e | split | unknown: fewer than 3 decisive votes), agree (share of the majority among decisive votes)
  forms.tsv    per edition and form: occurrences, share in verses with a source "we" (the form list's precision check)
  checks.md, build.json
Translation text is not stored; only counts and codes.
"""
from __future__ import annotations

import collections
import datetime
import json
import sqlite3
import subprocess
import sys
import unicodedata as ud
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import vrsmap  # noqa: E402

OUT = HERE / "data" / "we-votes"
USJ = Path.home() / "dev/bcv-commons/lexeme-aligner/pipeline/work/ingest-cache"
LOWFAT = HERE / "lowfat-hbo.db"
LSPINE = HERE / "lexeme-spine-macula.db"
NT = {"MAT", "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL", "EPH", "PHP", "COL", "1TH", "2TH", "1TI", "2TI", "TIT", "PHM",
      "HEB", "JAS", "1PE", "2PE", "1JN", "2JN", "3JN", "JUD", "REV"}

# edition -> (licence, family, inclusive forms, exclusive forms). Whole-token matches after lower-casing and stripping punctuation;
# a form with a space is a two-token sequence. Ambiguous forms are left out (Tagalog kita "I-you"; Hawaiian kaua "war").
EDITIONS = {
    "tgl_ulb": ("CC BY-SA", "Philippine",
                ["tayo", "tayong", "natin", "nating", "atin", "ating"],
                ["kami", "kaming", "namin", "naming", "amin", "aming"]),
    "ceb_ulb": ("CC BY-SA", "Philippine",
                ["kita", "kitang", "nato", "natong", "ato", "atong"],
                ["kami", "kaming", "namo", "namong", "amo", "among"]),
    "hil_bib": ("CC BY-SA", "Philippine",
                ["kita", "kitang", "naton", "natong", "aton"],          # atong: precision 0.10
                ["kami", "kaming", "namon", "namong", "amon", "among"]),
    "mal_irv": ("CC BY-SA", "Dravidian",
                ["നാം", "നാമും", "നാമോ", "നാമെല്ലാവരും", "നമ്മൾ", "നമ്മുടെ", "നമുക്ക്", "നമ്മെ", "നമ്മോട്", "നമ്മിൽ", "നമ്മാൽ", "നമ്മളെ",
                 "നമ്മുടെമേൽ", "നമ്മോടുകൂടെ", "നമുക്കും", "നമ്മളും"],
                ["ഞങ്ങൾ", "ഞങ്ങളുടെ", "ഞങ്ങൾക്ക്", "ഞങ്ങളെ", "ഞങ്ങളോട്", "ഞങ്ങളിൽ", "ഞങ്ങളാൽ", "ഞങ്ങളും", "ഞങ്ങൾക്കും", "ഞങ്ങളോടുകൂടെ"]),
    "tam_irv": ("CC BY-SA", "Dravidian",
                ["நாம்", "நாமே", "நாமும்", "நம்", "நம்முடைய", "நமது", "நமக்கு", "நம்மை", "நம்மால்", "நம்மிடம்", "நம்மோடு", "நம்மில்",
                 "நம்மேல்", "நம்முடன்", "நமக்கும்", "நம்மையும்"],
                ["நாங்கள்", "நாங்களே", "நாங்களும்", "எங்கள்", "எங்களுக்கு", "எங்களை", "எங்களுடைய", "எங்களால்", "எங்களிடம்",
                 "எங்களோடு", "எங்களில்", "எங்கள்மேல்", "எங்களுக்கும்", "எங்களையும்"]),
    "tel_irv": ("CC BY-SA", "Dravidian",
                ["మనం", "మనము", "మనమే", "మనమంతా", "మన", "మనకు", "మనకి", "మనల్ని", "మనలను", "మనతో", "మనలో", "మనందరం", "మనందరి"],
                ["మేము", "మేమే", "మేమంతా", "మా", "మాకు", "మాకై", "మమ్మల్ని", "మమ్ము", "మాతో", "మాలో", "మాది", "మాయొక్క"]),
    "mar_irv": ("CC BY-SA", "Indo-Aryan",
                ["आपण", "आपल्याला", "आपणांला"],        # आपला / आपली / आपले / आपल्या / आपणास / आपणाला: mostly reflexive "own" (precision 0.07-0.28)
                ["आम्ही", "आमचे", "आमचा", "आमची", "आमच्या", "आम्हाला", "आम्हांला", "आम्हास", "आम्हां", "आम्हा"]),
    "haw_868": ("public domain", "Polynesian",
                ["kakou", "kākou", "ka kakou", "ko kakou", "na kakou", "no kakou"],
                ["makou", "mākou", "maua", "māua", "ka makou", "ko makou", "na makou", "no makou"]),
    "ton_png": ("public domain", "Polynesian",
                ["kitautolu", "kitaua", "hotau", "hota", "ʻetau", "'etau"],
                ["kimautolu", "kimaua", "homau", "homa", "ʻemau", "'emau"]),
    "vie_vcb": ("CC BY-SA", "Vietic",
                ["chúng ta"],
                ["chúng tôi", "chúng con"]),
}


# editions counted and shown but not voting: mar_irv agrees with the others 0.74-0.82 against 0.89-0.95 for every other pair
# (2026-11-13); its exclusive आम्ही seems to cover inclusive uses too
NON_VOTING = {"mar_irv"}


def tokens(text: str) -> list[str]:
    out = []
    for w in ud.normalize("NFC", text).lower().split():
        w = "".join(c for c in w if not ud.category(c)[0] in "PS" or c in "ʻ'")
        w = w.strip("'")
        if w:
            out.append(w)
    return out


def usj_verses(path: Path):
    """(chapter, verse, text) from a USJ book; footnotes and cross references skipped; a verse range goes to its first verse"""
    d = json.loads(path.read_text(encoding="utf-8"))
    state = {"c": 0, "v": 0}
    buf = collections.defaultdict(list)

    def walk(node):
        if isinstance(node, str):
            if state["v"]:
                buf[(state["c"], state["v"])].append(node)
            return
        t, m = node.get("type"), node.get("marker")
        if t == "chapter":
            state["c"], state["v"] = int(node["number"]), 0
            return
        if t == "verse":
            state["v"] = int(str(node["number"]).split("-")[0].rstrip("abc") or 0)
            return
        if t == "note" or m in ("f", "x", "fe", "rq") or (t == "para" and m in ("s", "s1", "s2", "ms", "mr", "r", "d", "cl", "sp")):
            return
        for c in node.get("content") or []:
            walk(c)
    walk(d)
    for (c, v), parts in buf.items():
        yield c, v, " ".join(parts)


def source_we() -> dict[tuple, list[str]]:
    out = collections.defaultdict(list)
    for b, c, v, k, m in sqlite3.connect(f"file:{LOWFAT}?mode=ro", uri=True).execute(
            "select book, chapter, verse, key, morph from lowfat_words where is_inserted=0 and morph like '%1cp%'"):
        out[(b, c, v)].append(k)
    for b, c, v, k in sqlite3.connect(f"file:{LSPINE}?mode=ro", uri=True).execute(
            "select book, chapter, verse, key from spine_words where length(key)=11 and number='plural' and "
            "(person='first' or lemma in ('ἐγώ', 'ἡμέτερος'))"):
        out[(b, c, v)].append(k)
    return out


GOD_HBO = {("3068", None), ("0430", "אֱלֹהִים"), ("0136", "אֲדֹנָי"), ("0410", "אֵל"), ("0426", None)}
GOD_GRC = {"θεός", "κύριος"}
MSPINE = HERE / "macula-spine.db"
CCOLS = HERE / "data" / "clause-columns"


def rules(src: dict[tuple, list[str]]) -> dict[tuple, tuple[str, str]]:
    """verse -> (value, basis) by rule; '' when no rule applies or two rules disagree.
    let_us: a source "we" is the main verb of a clause whose force is cohortative (Hebrew) or hortatory (Greek) -> inclusive;
            only when the verse has no second-person word: with one ("let us pass through your land", a request to someone outside
            the group) the votes go either way (0.30 exclusive), so the votes decide.
    to_god: the verse has a second-person word whose MACULA referent (subjref / participantref / referent, up to 3 steps) is God
            (יהוה, אֱלֹהִים, אֲדֹנָי, אֵל, Aramaic אֱלָהּ; θεός, κύριος) -> exclusive: the one addressed is not in the "we"."""
    import pyarrow.parquet as pq
    m = sqlite3.connect(f"file:{MSPINE}?mode=ro", uri=True)
    word = {}
    for k, lang, b, c, v, lem, st, person in m.execute("select key, lang, book, chapter, verse, lemma, strong, person from macula_words"):
        word[k] = (lang, (b, c, v), lem or "", (st or "").zfill(4)[:4] if lang == "hbo" else "", person or "")
    ref = collections.defaultdict(list)
    for s_, t, kind in m.execute("select src_key, tgt_key, kind from refs"):
        ref[s_].append(t)

    def is_god(k):
        lang, _, lem, st, _ = word.get(k, ("", None, "", "", ""))
        if lang == "hbo":
            return any(st == g and (gl is None or lem == gl) for g, gl in GOD_HBO)
        return lem in GOD_GRC

    def reaches_god(k, n=3):
        seen, front = set(), [k]
        for _ in range(n):
            nxt = []
            for x in front:
                for t in ref.get(x, []):
                    if t not in seen:
                        if is_god(t):
                            return True
                        seen.add(t)
                        nxt.append(t)
            front = nxt
        return False
    second = collections.defaultdict(list)
    for k, (lang, vkey, lem, st, person) in word.items():
        if person == "second" or lem in ("σύ", "ὑμεῖς"):
            second[vkey].append(k)
    force = {}
    for name in ("hebrew", "greek-nt"):
        for r in pq.read_table(CCOLS / f"{name}.parquet", columns=["verb", "force"]).to_pylist():
            if r["verb"]:
                force[r["verb"]] = r["force"]
    out = {}
    for vkey, keys in src.items():
        got = set()
        if any(force.get(k) in ("cohortative", "hortatory") for k in keys):
            # measured 2026-11-13: without a "you" 0.94 agreement with the votes; with one only 0.30 for exclusive, so no rule there
            if not second.get(vkey):
                got.add(("i", "let_us"))
        if any(reaches_god(k) for k in second.get(vkey, [])):
            got.add(("e", "to_god"))
        vals = {v for v, _ in got}
        out[vkey] = (next(iter(got)) if len(got) == 1 else ("", "conflict:" + "+".join(sorted(b for _, b in got)))
                     if got else ("", ""))
    return out


def count(toks: list[str], forms: set[str]) -> collections.Counter:
    got = collections.Counter()
    for i, t in enumerate(toks):
        if t in forms:
            got[t] += 1
        if i + 1 < len(toks) and f"{t} {toks[i + 1]}" in forms:
            got[f"{t} {toks[i + 1]}"] += 1
    return got


def main() -> int:
    src = source_we()
    conv = {}
    votes = collections.defaultdict(dict)           # verse -> edition -> i/e/m/-
    form_n, form_hit = collections.Counter(), collections.Counter()
    st = collections.Counter()
    for ed, (lic, fam, inc, exc) in EDITIONS.items():
        inc_s, exc_s = set(inc), set(exc)
        acc = collections.defaultdict(lambda: [collections.Counter(), collections.Counter()])
        for f in sorted((USJ / f"usj-{ed}").glob("*.json")):
            book = f.stem.split("-", 1)[1]
            for c, v, text in usj_verses(f):
                key = (book, c, v)
                if key not in conv:
                    try:
                        conv[key] = vrsmap.convert(key, "eng", "org") or [key]
                    except Exception:
                        conv[key] = [key]
                toks = tokens(text)
                ci, ce = count(toks, inc_s), count(toks, exc_s)
                tgt = conv[key][0]
                acc[tgt][0].update(ci)
                acc[tgt][1].update(ce)
                for fm, n in list(ci.items()) + list(ce.items()):
                    form_n[(ed, fm)] += n
                    if tgt in src:
                        form_hit[(ed, fm)] += n
        for vkey in src:
            ci, ce = acc.get(vkey, [collections.Counter(), collections.Counter()])
            i, e = sum(ci.values()), sum(ce.values())
            votes[vkey][ed] = "m" if i and e else "i" if i else "e" if e else "-"
            st[(ed, votes[vkey][ed])] += 1
    OUT.mkdir(parents=True, exist_ok=True)
    eds = list(EDITIONS)
    rule = rules(src)
    rows = []
    for vkey in sorted(src, key=lambda k: (k[0] not in NT, k)):
        vv = votes[vkey]
        voters = [e for e in eds if e not in NON_VOTING]
        n_i = sum(1 for e in voters if vv.get(e) == "i")
        n_e = sum(1 for e in voters if vv.get(e) == "e")
        n_m = sum(1 for e in voters if vv.get(e) == "m")
        dec = n_i + n_e
        # 75% of 3+ decisive votes: the stable part of the threshold curve (research, 2026-11-13); fewer votes -> unknown
        value = "unknown" if dec < 3 else ("i" if n_i / dec >= 0.75 else "e" if n_e / dec >= 0.75 else "split")
        rows.append([vkey[0], str(vkey[1]), str(vkey[2]), str(len(src[vkey])), " ".join(src[vkey])] +
                    [vv.get(e, "-") for e in eds] + [str(n_i), str(n_e), str(n_m), value,
                                                     f"{max(n_i, n_e) / dec:.2f}" if dec else ""] + list(rule[vkey]))
    with open(OUT / "verses.tsv", "w", encoding="utf-8") as f:
        f.write("\t".join(["book", "chapter", "verse", "src_we", "src_keys"] + eds + ["n_i", "n_e", "n_m", "value", "agree", "rule", "rule_basis"]) + "\n")
        f.writelines("\t".join(r) + "\n" for r in rows)
    with open(OUT / "forms.tsv", "w", encoding="utf-8") as f:
        f.write("edition\tform\tkind\toccurrences\tin_we_verses\tshare\n")
        for ed, (lic, fam, inc, exc) in EDITIONS.items():
            for kind, fl in (("i", inc), ("e", exc)):
                for fm in fl:
                    n = form_n[(ed, fm)]
                    f.write(f"{ed}\t{fm}\t{kind}\t{n}\t{form_hit[(ed, fm)]}\t{form_hit[(ed, fm)] / n:.3f}\n" if n else
                            f"{ed}\t{fm}\t{kind}\t0\t0\t\n")
    # checks
    vals = collections.Counter((r[0] in NT, r[-4]) for r in rows)
    lines = ["# Inclusive / exclusive \"we\" votes: checks", "",
             f"Source verses with a first-person plural: {len(rows):,} (NT {sum(1 for r in rows if r[0] in NT):,}).", "",
             "| edition | licence | family | i | e | mixed | no form |", "|---|---|---|---|---|---|---|"]
    for ed, (lic, fam, _, _) in EDITIONS.items():
        lines.append(f"| {ed} | {lic} | {fam} | {st[(ed, 'i')]:,} | {st[(ed, 'e')]:,} | {st[(ed, 'm')]:,} | {st[(ed, '-')]:,} |")
    lines += ["", "Verse values (3 or more decisive votes; i / e when 75% or more agree):", "", "| | NT | Tanakh |", "|---|---|---|"]
    for v in ("i", "e", "split", "unknown"):
        lines.append(f"| {v} | {vals[(True, v)]:,} | {vals[(False, v)]:,} |")
    for nt in (True, False):
        ag = [float(r[-3]) for r in rows if (r[0] in NT) == nt and r[-3] and r[-4] in ("i", "e", "split")]
        lines.append(f"\nMean agreement among decisive votes, {'NT' if nt else 'Tanakh'}: {sum(ag) / max(len(ag), 1):.3f} "
                     f"over {len(ag):,} verses.")
    # pairwise agreement between editions on verses where both are decisive
    lines += ["", "Pairwise agreement (verses where both editions are decisive):", "", "| | " + " | ".join(eds) + " |",
              "|---|" + "---|" * len(eds)]
    for a in eds:
        cells = []
        for b in eds:
            both = [(votes[k][a], votes[k][b]) for k in src if votes[k].get(a) in ("i", "e") and votes[k].get(b) in ("i", "e")]
            cells.append(f"{sum(x == y for x, y in both) / len(both):.2f}" if both and a != b else "")
        lines.append(f"| {a} | " + " | ".join(cells) + " |")
    lines += ["", "Rules against the votes (verses with a vote value i / e / split):", "",
              "| rule | rule says | votes i | votes e | votes split | no vote value | agreement with i / e votes |", "|---|---|---|---|---|---|---|"]
    for basis in sorted({r[-1] for r in rows if r[-1]}):
        sel = [r for r in rows if r[-1] == basis]
        c = collections.Counter(r[-4] for r in sel)
        c[""] = c["unknown"]
        say = sel[0][-2] or "-"
        dec = c["i"] + c["e"]
        lines.append(f"| {basis} | {say} | {c['i']:,} | {c['e']:,} | {c['split']:,} | {c['']:,} | "
                     f"{(c[say] / dec if dec and say in 'ie' else 0):.3f} |")
    lines += ["", "Forms with low precision (share of occurrences in verses with a source \"we\" under 0.5, 50+ occurrences):", ""]
    for (ed, fm), n in sorted(form_n.items()):
        if n >= 50 and form_hit[(ed, fm)] / n < 0.5:
            lines.append(f"- {ed} `{fm}`: {form_hit[(ed, fm)] / n:.2f} of {n:,}")
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = subprocess.run(["git", "log", "-1", "--format=%h"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    (OUT / "build.json").write_text(json.dumps({"schema": 1, "built": datetime.date.today().isoformat(), "code": code,
                                                "editions": {e: {"licence": v[0], "family": v[1]} for e, v in EDITIONS.items()},
                                                "not_read": ["BHSA", "TBTA", "English text"], "stores_text": False}, indent=1) + "\n")
    print((OUT / "checks.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
