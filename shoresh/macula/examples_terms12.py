"""Stage 23 (SPEC 1.2, 4.10): terms.tsv in ten columns, and terms-notes.md beside it.

    shoresh/.venv/bin/python -I shoresh/macula/examples_terms12.py --write-master   # writes both masters
    (build_examples.py --build d1 --stage 23 copies them into d1/<lang>/ after checking them)

What changes against 1.1 (examples_terms.py, whose rule T and named terms are reused; CHANGES-1.2.md):
- P6: rule T as 1.1, plus the pair: where no single item gives a value a term, a pair of items that stand together in at
  least 90% of the value's rows and whose home is the value (the value with most of the pair's rows) is taken, the
  items in the writing order the rows give most; its source is a JSON array of the two keys.
- P7: a `sem_role` term is always a named noun (NAMED, with the P7 replacements of CHANGES-1.2.md); rule T's
  preposition goes to `source_<lang>`, `from_<lang>` stays as NAMED gives it (`coined` or `tradition`).
- P8: no `note` column; a `tradition` source is a reference code `ref:<C0 of author, work and place>` that
  terms-notes.md resolves; A5: grc `imperfective` cites `ref:stoic_usage_scholia_dionysius_thrax`.
"""
import argparse
import collections as C
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import examples_terms as T11  # noqa: E402

HERE = T11.HERE
SPEC = os.path.join(HERE, "..", "..", "internal-docs", "source-examples-spec")
MASTER = os.path.join(SPEC, "terms.tsv")
NOTES = os.path.join(SPEC, "terms-notes.md")
COLS = ["category", "code", "hbo", "grc", "from_hbo", "from_grc", "source_hbo", "source_grc", "named_by", "checked"]
PAIR_SHARE = 0.90

# CHANGES-1.2.md P7: the new sem_role terms (named by claude-opus-5-5 in stage 22)
P7 = {"hbo": {"addressee": "נִמְעָן", "accompaniment": "לִוּוּי", "agent": "גּוֹרֵם", "content": "עִנְיָן",
              "goal": "מַטָּרָה", "location": "מָקוֹם", "opposition": "הִתְנַגְּדוּת", "reason_participant": "עִלָּה",
              "recipient": "מְקַבֵּל", "source": "מָקוֹר", "standard": "מִדָּה", "time": "זְמַן", "viewpoint": "רְאוּת"},
      "grc": {"accompaniment": "συνοδία", "addressee": "ὁ προσαγορευόμενος", "agent": "ὁ δρῶν",
              "beneficiary": "ὁ ὠφελούμενος", "content": "ὑπόθεσις", "distribution": "διανομή", "goal": "σκοπός",
              "location": "τόπος", "reason_participant": "αἴτιος", "separation": "χωρισμός", "source": "ἀφετηρία",
              "source_event": "ἀφορμή", "standard": "κανών", "time": "χρόνος", "viewpoint": "ὄψις"}}
P7_NOTES = {
    ("hbo", "addressee"): "later noun 'the one addressed, recipient of a letter' (root נמע); replaces הַנֶּאֱמָר "
                          "אֵלָיו, whose אֵלָיו is a form of the preposition אֶל",
    ("hbo", "accompaniment"): "verbal noun of piel לִוָּה 'accompany' (root לוה)",
    ("hbo", "agent"): "participle of hiphil גָּרַם 'cause', Rabbinic 'the one who brings about'",
    ("hbo", "content"): "Rabbinic noun 'matter, subject' (root ענה)",
    ("hbo", "opposition"): "hithpael verbal noun of נגד 'stand against'",
    ("hbo", "reason_participant"): "Rabbinic noun 'cause' (Aramaic loan); also 'the one who causes'",
    ("hbo", "viewpoint"): "noun 'seeing, view' (root ראה; Eccl 5:10 ketiv רְאוּת)",
    ("grc", "addressee"): "participle 'the one addressed' (προσαγορεύω); replaces πρὸς ὃν ὁ λόγος, which began with "
                          "the preposition πρός",
    ("grc", "agent"): "'the one doing' (δράω)",
    ("grc", "beneficiary"): "passive participle of ὠφελέω with the article: 'the one helped'",
    ("grc", "content"): "noun 'subject, matter laid down'",
    ("grc", "goal"): "noun 'mark aimed at' (Phil 3:14)",
    ("grc", "reason_participant"): "adjective 'responsible, the cause'",
    ("grc", "source"): "noun 'starting point'",
    ("grc", "source_event"): "noun 'starting point, occasion'",
}
# the tradition sources of 1.1 (examples_terms.NAMED) -> reference codes; the citation goes to terms-notes.md
REF_OF = {
    "Aristotle, Rhetoric 3.12 (1413b): τὰ ἀσύνδετα": "ref:aristotle_rhetoric_3_12_1413b",
    T11.DT + " 20: σύνδεσμοι συμπλεκτικοί": "ref:dionysius_thrax_techne_20",
    "Aristotle, Rhetoric 3.9 (1410a)": "ref:aristotle_rhetoric_3_9_1410a",
    T11.DT + " 16: the postpositive article ὅς": "ref:dionysius_thrax_techne_16",
    T11.DT + " 12: the case κλητική": "ref:dionysius_thrax_techne_12",
    T11.MHG: "ref:ibn_ezra_kimhi_mikhlol_tenses",
    T11.DT + " 13: χρόνοι": "ref:dionysius_thrax_techne_13",
    T11.DT + " 13: a past tense": "ref:dionysius_thrax_techne_13",
    T11.DT + " 13: a past tense, 'lying at hand'": "ref:dionysius_thrax_techne_13",
    "Plato, Republic 3.392d: ἁπλῆ διήγησις": "ref:plato_republic_3_392d",
    "Plato, Republic 3.392d-394c: narration through the speakers' own words": "ref:plato_republic_3_392d_394c",
}
A5 = ("aspect", "imperfective", "grc")
A5_REF = "ref:stoic_usage_scholia_dionysius_thrax"
REFS = {
    "ref:aristotle_rhetoric_3_12_1413b": "Aristotle, Rhetoric 3.12, 1413b: τὰ ἀσύνδετα (speech without connectives).",
    "ref:aristotle_rhetoric_3_9_1410a": "Aristotle, Rhetoric 3.9, 1410a: παρίσωσις (clauses of equal length).",
    "ref:dionysius_thrax_techne_12": "Dionysius Thrax, Techne grammatike 12: the five cases, among them the κλητική.",
    "ref:dionysius_thrax_techne_13": "Dionysius Thrax, Techne grammatike 13: the verb's χρόνοι (ἐνεστώς, "
                                     "παρεληλυθώς, μέλλων) and the kinds of past (παρατατικός, παρακείμενος, "
                                     "ὑπερσυντέλικος, ἀόριστος).",
    "ref:dionysius_thrax_techne_16": "Dionysius Thrax, Techne grammatike 16: the article, prepositive (ὁ) and "
                                     "postpositive (ὅς).",
    "ref:dionysius_thrax_techne_20": "Dionysius Thrax, Techne grammatike 20: the conjunctions, among them the "
                                     "σύνδεσμοι συμπλεκτικοί.",
    "ref:ibn_ezra_kimhi_mikhlol_tenses": "Medieval Hebrew grammar on the verb tenses: Abraham ibn Ezra; David Kimhi, "
                                         "Mikhlol (עָבָר, עָתִיד). The locus was not verified here.",
    "ref:plato_republic_3_392d": "Plato, Republic 3.392d: ἁπλῆ διήγησις (plain narration).",
    "ref:plato_republic_3_392d_394c": "Plato, Republic 3.392d-394c: μίμησις, narration through the speakers' own "
                                      "words.",
    A5_REF: "The Stoic usage of παρατατικός (the 'extending' tense) as the scholia on Dionysius Thrax report it. "
            "Techne 13 uses the word for the imperfect, a past tense; here it names the imperfective aspect, which "
            "falls on present forms in 7,602 of 7,643 rows (OPEN-1.1 A5). The locus was not verified here.",
}
DOUBTS = {("line_kind", "background", "hbo"): "לְוַאי: Rabbinic 'accompaniment, attribute'; whether it reads as "
                                                "'background' to a reader of Hebrew is open (OPEN-1.1 A6).",
          ("ent_type", "flora", "grc"): "φυτεία: 'plant, planting' (Matt 15:13); a rare word for plants in general "
                                        "(OPEN-1.1 A6).",
          ("relation", "parallel", "grc"): "παρίσωσις: Aristotle's term is for clauses of equal length, not for "
                                           "parallelism of sense (OPEN-1.1 A6).",
          ("time", "present", "hbo"): "הֹוֶה: the medieval grammarians name the participle בֵּינוֹנִי; הֹוֶה as "
                                      "'present' is later usage (OPEN-1.1 A6)."}


def pair_counts():
    """lang -> (Counter (code, (a, b)) in writing order, Counter code) over the connectives rows, as rule T counts."""
    arcv, vkey = T11.arc_verses(), T11.heb_verse_of_key()
    pair = {lg: C.Counter() for lg in ("hbo", "grc")}
    for r in T11.tsv(os.path.join(T11.D, "connectives/clauses.tsv")):
        lg, val = r["corpus"], r["relation"]
        if val in ("", "-"):
            continue
        if lg == "hbo":
            vk = vkey.get(r["clause_key"])
            if vk is None or vk in arcv:
                continue
        items = [T11.nfc(x) for x in r["conn"].split()]
        seen = set()
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                k = (items[i], items[j])
                if items[i] != items[j] and frozenset(k) not in seen:
                    seen.add(frozenset(k))
                    pair[lg][(T11.c0(val), k)] += 1
    return pair


def rule_t_pair(pair, tot, best, code):
    """The pair rule for one value without a single item -> ((a, b), rows) or None."""
    by_set = C.defaultdict(C.Counter)        # frozenset -> code -> rows
    order = C.defaultdict(C.Counter)         # (code, frozenset) -> (a, b) -> rows
    for (c, k), n in pair.items():
        by_set[frozenset(k)][c] += n
        order[(c, frozenset(k))][k] += n
    cands = []
    for fs, cc in by_set.items():
        top = cc.most_common()
        if top[0][0] != code or (len(top) > 1 and top[0][1] == top[1][1]):
            continue
        n = cc[code]
        if n >= PAIR_SHARE * tot[code]:
            k = sorted(order[(code, fs)].items(), key=lambda x: (-x[1], x[0]))[0][0]
            cands.append((-n, k))
    if not cands:
        return None
    cands.sort()
    return cands[0][1], -cands[0][0]


def make_rows(cnt, ex):
    occ = T11.dataset_values()
    codes = {cat: set() for cat in T11.CATS}
    for (cat, lg), cc in occ.items():
        codes[cat] |= set(cc)
    codes["ent_type"] |= set(T11.ENT_TYPES)
    mk = T11.marker_counts(cnt)
    pairs = pair_counts()
    rule, notes = {}, C.defaultdict(list)
    for lg in ("hbo", "grc"):
        by, used = T11.lexeme_keys(lg)
        for cat in ("relation", "sem_role"):
            pc, tot = mk[lg][cat]
            best, tied = T11.rule_t(pc, tot)
            ex[f"{lg} {cat} rule T: items whose home value is tied (no home)"] = tied
            common = {}
            for (code, it), n in pc.items():
                if code not in common or (n, ) > (common[code][1], ) or (n == common[code][1] and it < common[code][0]):
                    common[code] = (it, n)
            for code in sorted(tot):
                if code in best:
                    it, n, share = best[code]
                    key, nk, lemma = T11.key_for(by, used, it, cat)
                    if key is None:
                        ex[f"{lg} {cat} rule T: item with no b1 lexeme"].append(f"{code} {it}")
                        continue
                    rule[(cat, code, lg)] = ("single", lemma, key, n, tot[code])
                    cnt[f"{lg} {cat} rule T {code}"] = f"{it} {key} {n}/{tot[code]} ({share:.3f})"
                    if common[code][0] != it:
                        notes[(cat, code, lg)].append(
                            f"Rule T's item is {it} ({n} of {tot[code]} rows, its home is this value); the commonest "
                            f"marker of the value is {common[code][0]} ({common[code][1]} of {tot[code]} rows).")
                        k_ = f"{lg} {cat} rule T cells where the commonest marker differs"
                        cnt[k_] = cnt.get(k_, 0) + 1
                elif cat == "relation":
                    got = rule_t_pair(pairs[lg], tot, best, code)
                    if got is not None:
                        (a, b), n = got
                        ka, _na, la = T11.key_for(by, used, a, cat)
                        kb, _nb, lb = T11.key_for(by, used, b, cat)
                        if ka and kb:
                            rule[(cat, code, lg)] = ("pair", f"{la} {lb}", json.dumps([ka, kb], ensure_ascii=False,
                                                                                    separators=(",", ":")), n,
                                                     tot[code])
                            cnt[f"{lg} relation rule T pair {code}"] = f"{a} {b} {n}/{tot[code]}"
    rows = []
    for cat in T11.CATS:
        order = T11.ENT_TYPES if cat == "ent_type" else sorted(codes[cat])
        for code in order:
            row = {"category": cat, "code": code, "named_by": T11.NAMED_BY, "checked": ""}
            for lg in ("hbo", "grc"):
                rt = rule.get((cat, code, lg))
                if cat != "sem_role" and rt is not None:
                    _k, lemma, key, n, tot = rt
                    term, frm, src = lemma, "text", key
                    notes[(cat, code, lg)].insert(0, f"Rule T ({_k}): {lemma}, {n} of {tot} rows.")
                else:
                    if (cat, code) not in T11.NAMED:
                        raise SystemExit(f"stage 23: no term for {cat} {code} ({lg})")
                    term, frm, src, note = T11.NAMED[(cat, code)][lg]
                    if cat == "sem_role" and code in P7[lg]:
                        term, frm, note = P7[lg][code], "coined", P7_NOTES.get((lg, code), note)
                    if note:
                        notes[(cat, code, lg)].insert(0, note)
                    if frm == "text":
                        by, used = T11.lexeme_keys(lg)
                        key, nk, lemma = T11.key_for(by, used, T11.nfc(term), cat)
                        if key is None:
                            raise SystemExit(f"stage 23: {lg} text term {term} is no b1 lexeme")
                        src, term = key, lemma
                    elif frm == "tradition":
                        if (cat, code, lg) == A5:
                            src = A5_REF
                        elif src in REF_OF:
                            notes[(cat, code, lg)].append(f"Cited in 1.1 as: {src}.")
                            src = REF_OF[src]
                        else:
                            raise SystemExit(f"stage 23: tradition source {src!r} has no reference code")
                    if cat == "sem_role":
                        src = ""
                        if rt is not None:
                            _k, lemma, key, n, tot = rt
                            src = key
                            notes[(cat, code, lg)].append(f"Rule T's preposition: {lemma} ({key}), {n} of {tot} "
                                                          f"rows; it goes to source_{lg}, not into the term (P7).")
                row[lg] = term if frm == "text" else T11.nfc(term)
                row[f"from_{lg}"], row[f"source_{lg}"] = frm, src
                if (cat, code, lg) in DOUBTS:
                    notes[(cat, code, lg)].append("Open for the scholar: " + DOUBTS[(cat, code, lg)])
            rows.append(row)
    for cat in T11.CATS:
        for lg in ("hbo", "grc"):
            seen = C.Counter(T11.nfc(r[lg]) for r in rows if r["category"] == cat)
            dup = [t for t, n in seen.items() if n > 1]
            if dup:
                raise SystemExit(f"stage 23: {cat} {lg} terms shared by two codes: {dup}")
    for r in rows:
        for k in COLS:
            if "\t" in r[k] or "\n" in r[k]:
                raise SystemExit(f"stage 23: tab or newline in {r}")
    return rows, notes


def render(rows):
    return "\t".join(COLS) + "\n" + "".join("\t".join(r[k] for k in COLS) + "\n" for r in rows)


def render_notes(rows, notes):
    L = ["# terms-notes.md: notes on the terms of `terms.tsv`", "",
         "Written by `examples_terms12.py` (SPEC 1.2, 4.10) beside `terms.tsv` and copied with it. For the scholar: how a",
         "coined term was built, each reference code with its citation, rule T's counts (with the commonest marker where",
         "it differs from rule T's item), the preposition of each `sem_role` row, and the doubts no count settles. The",
         f"terms are a model's naming (`named_by` {T11.NAMED_BY}); no term has been checked by a person. This file may",
         "hold English; it is exempt from the no-English check by name.", "", "## Reference codes", ""]
    used = C.Counter(r[f"source_{lg}"] for r in rows for lg in ("hbo", "grc") if r[f"source_{lg}"].startswith("ref:"))
    for code in sorted(used):
        L.append(f"- `{code}` ({used[code]} cells): {REFS[code]}")
    L += ["", "## The cells where rule T's item is not the commonest marker", ""]
    diff = [(k, v) for k, vs in sorted(notes.items()) for v in vs if "the commonest marker" in v]
    for (cat, code, lg), v in diff:
        L.append(f"- {lg} `{cat}` `{code}`: {v}")
    L += ["", "## The rows", ""]
    for r in rows:
        L += [f"### {r['category']} `{r['code']}`", ""]
        for lg in ("hbo", "grc"):
            L.append(f"- {lg}: {r[lg]} ({r['from_' + lg]}" + (f"; source `{r['source_' + lg]}`" if r['source_' + lg]
                                                              else "") + ")")
            for v in notes.get((r["category"], r["code"], lg), []):
                L.append(f"  - {v}")
        L.append("")
    return "\n".join(L).rstrip("\n") + "\n"


def write_master():
    cnt, ex = {}, C.defaultdict(list)
    rows, notes = make_rows(cnt, ex)
    with open(MASTER, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(rows))
    with open(NOTES, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_notes(rows, notes))
    print(f"{len(rows)} rows -> {os.path.normpath(MASTER)}; notes -> {os.path.normpath(NOTES)}")


def build(outdir, langs, counts):
    """Copy both masters into <build>/<lang>/ unchanged, after checking that they are what the rules give."""
    import shutil
    ex = C.defaultdict(list)
    rows, notes = make_rows(counts, ex)
    with open(MASTER, encoding="utf-8", newline="") as fh:
        master = fh.read()

    def unchecked(text):
        return [ln.rsplit("\t", 1)[0] for ln in text.split("\n")]
    if unchecked(master) != unchecked(render(rows)):
        raise SystemExit("stage 23: the master terms.tsv differs from the 1.2 rules; rerun examples_terms12.py --write-master")
    with open(NOTES, encoding="utf-8", newline="") as fh:
        if fh.read() != render_notes(rows, notes):
            raise SystemExit("stage 23: the master terms-notes.md differs; rerun examples_terms12.py --write-master")
    for lg in langs:
        os.makedirs(os.path.join(outdir, lg), exist_ok=True)
        shutil.copyfile(MASTER, os.path.join(outdir, lg, "terms.tsv"))
        shutil.copyfile(NOTES, os.path.join(outdir, lg, "terms-notes.md"))
    by = C.Counter(f"{lg} {r['from_' + lg]}" for r in rows for lg in ("hbo", "grc"))
    counts["terms rows"] = len(rows)
    counts["terms rows by category"] = dict(C.Counter(r["category"] for r in rows))
    counts["terms by from"] = dict(sorted(by.items()))
    return ex


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-master", action="store_true")
    if ap.parse_args().write_master:
        write_master()


TERMS_MARKER = "# ---- the terms part (build_examples.py --stage 23) ----"


def toml_str(s):
    return json.dumps(s, ensure_ascii=False)


def append_terms_part(outdir, langs):
    """SPEC 1.2 4.10: categories.toml declares the terms.tsv reference codes, the from codes and named_by (after the
    shared part of stage 20; the citations stand in terms-notes.md)."""
    rows = T11.tsv(MASTER)
    refs = C.Counter(r[f"source_{lg}"] for r in rows for lg in ("hbo", "grc") if r[f"source_{lg}"].startswith("ref:"))
    frm = C.Counter(r[f"from_{lg}"] for r in rows for lg in ("hbo", "grc") if r[f"from_{lg}"])  # 1.3: an empty cell (grc noun_rel ruler) has no from
    nb = C.Counter(r["named_by"] for r in rows)
    L = [TERMS_MARKER, "", "[terms.source]", 'column = "source_hbo, source_grc"', 'basis = "given (named)"',
         'source = "internal-docs/source-examples-spec/terms.tsv (SPEC 4.10); the reference codes resolve in terms-notes.md"',
         'pattern = "a lexeme key, a JSON array of two lexeme keys, a reference code ref:<C0 of author, work and place>, or empty"',
         "values = ["]
    L += [f"  {{ code = {toml_str(c)}, value = {toml_str('terms-notes.md, section Reference codes')}, count = {n} }},"
          for c, n in sorted(refs.items())]
    L += ["]", "", "[terms.from]", 'column = "from_hbo, from_grc"', 'basis = "given (named)"', 'source = "SPEC 4.10"',
          "values = ["]
    desc = {"text": "a word of the text itself (rule T, or a noun of the text for ent_type)",
            "tradition": "a term of the language's own grammatical or rhetorical tradition (reference code)",
            "coined": "built from words of the language"}
    L += [f"  {{ code = {toml_str(c)}, value = {toml_str(desc[c])}, count = {n} }}," for c, n in sorted(frm.items())]
    L += ["]", "", "[terms.named_by]", 'column = "named_by"', 'basis = "model"',
          'source = "the model that chose the terms (stages 14 and 22 of the source-examples run); no term is checked by a person"',
          "values = ["]
    L += [f"  {{ code = {toml_str(c)}, value = {toml_str(c)}, count = {n} }}," for c, n in sorted(nb.items())]
    L += ["]", ""]
    for lg in langs:
        path = os.path.join(outdir, lg, "categories.toml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read().split(TERMS_MARKER)[0].rstrip("\n") + "\n\n"
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n".join(L))
