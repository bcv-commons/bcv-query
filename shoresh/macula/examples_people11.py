"""Stage 16 (SPEC 1.1, build c1): clause values and speech, the strict bases only.

Builds `clauses.marks`, `line` (examples_values11: D9, D11), `constituents.sem_role`, `sem_role_basis` (D12),
`pieces.who`, `who_basis` (D7, strict steps), `clauses.quote`, `speaker`, `addressee`, `speech_basis` (D10),
`participants.tsv` (strict rows; `name` by D7n), the kin rows of `facts.parquet`, `source_errors.tsv` (SE1, SE2), and the
clause part of categories.toml. M columns (`concept`, `quote_model`, ...) stay null: stage 17.

What 1.1 changes against the 1.0 module examples_people.py (left as it was, for b1):
- D7 step 1: a `suffix` piece takes an explicit row only where ACAI's instance begins at that piece (entity_words
  `instance` equals the row's word); else steps 2 to 4 (D1).
- a Greek `det` piece may take `who` with basis `pronominal` or `chain` (D8); conjunctions, prepositions and other
  articles only `explicit`.
- D7n names; `name_basis`; `ent_basis`; `type` as its term (ent_type).
- D10 addressee only from rows whose quotation has the same id, first and last word in the review-free layer and
  whose basis is not `turn` (D13); `speech_basis` `derived` on the clauses of a quotation whose first word is the key
  of a corrections.tsv row.
"""
import collections as C
import csv
import json
import os
import unicodedata

import pyarrow as pa
import pyarrow.parquet as pq

import examples_clauses as EC
import examples_common as X
import examples_people as EP
import examples_src as S
import examples_values11 as V11
import examples_v13 as EX13
import examples_v13m as EX13M

REPO = os.path.dirname(os.path.dirname(S.HERE))
CORRECTIONS = os.path.join(REPO, "resources", "speaker_layer", "corrections.tsv")
NT_REVIEW = os.path.join(REPO, "resources", "speaker_quotations", "nt_review.tsv")
NO_WHO = {"hbo": {"cj", "prep", "art"}, "arc": {"cj", "prep", "art"}, "grc": {"conj", "prep", "det"}}
DET_OK = {"pronominal", "chain"}            # D7 / CHANGES D8: Greek det
NAME_CLASSES = {"noun", "adj"}
FALLBACK = {"hbo": ("he:",), "arc": ("arc:", "he:"), "grc": ("el:",)}
PART_HEADER = ["ent", "type", "name", "name_basis", "sex", "words", "words_model", "ent_basis"]
SE_HEADER = ["rule", "source", "place", "value", "count"]
GOD_LEMMAS = ("אֱלֹהִים", "אֱלָהּ")
OTHER_LEMMAS = ("אַחֵר", "נֵכָר")
ARTICLE_LEMMA = "הַ"
SE4_FIRST, SE4_SECOND, SE4_THIRD = "ὅς", ("μέν", "δέ"), ("ἄν", "ἐάν")
SE2_TYPES = {"fauna", "flora", "realia"}
MARKER = "# ---- the people and speech part (build_examples.py --stage 16) ----"


def nfc(s):
    return unicodedata.normalize("NFC", s)


def entity_rows(E, cnt):
    """(pid, kind) -> ents; and pid -> ents of the explicit rows whose ACAI instance begins at that piece."""
    out, begins = C.defaultdict(set), C.defaultdict(set)
    with open(os.path.join(EP.ENT, "entity_words.tsv"), encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            kind = r["kind"]
            greek = len(r["word"]) == 11
            tag = f"{'grc' if greek else 'tan'} entity_words {kind}"
            if kind == "speech":
                continue
            k = E.ent(r["entity"], tag)
            if k is None:
                continue
            pid = ("n" if greek else "o") + r["word"]
            out[(pid, kind)].add(k)
            if kind == "explicit" and r["instance"] == r["word"]:
                begins[pid].add(k)
    return out, begins


def d7(P_by, greek, rows, begins, morph, cnt, ex):
    tag = "grc" if greek else "tan"
    refs, _both = EP.refs_of(greek)
    base = {}
    for lang, P in P_by.items():
        for pid, kind in zip(P["pid"], P["kind"]):
            for k in ("explicit", "pronominal", "subject"):
                es = rows.get((pid, k))
                if es and k == "explicit" and kind == "suffix":
                    if not begins.get(pid):
                        cnt[f"{lang} D7 suffix pieces whose explicit row begins elsewhere (step 1 not taken)"] += 1
                        ex[f"{lang} D7 suffix piece: explicit row not taken (instance begins elsewhere)"].append(pid)
                        continue
                    es = begins[pid]
                if es:
                    base[pid] = (es, k)
                    break
    out = {}
    for lang, P in P_by.items():
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
                        continue
                    b = base.get(tp)
                    if b is None:
                        cnt[f"{tag} D7 chain target with no who from steps 1-3 ({attr})"] += 1
                    else:
                        es |= b[0]
                if es:
                    got = (es, "chain")
                else:
                    cnt[f"{tag} D7 pieces with a reference whose targets give no who ({attr})"] += 1
            if got is not None and cl in NO_WHO[lang] and got[1] != "explicit" and not (
                    lang == "grc" and cl == "det" and got[1] in DET_OK):
                cnt[f"{lang} D7 left empty: class {cl}, basis {got[1]}"] += 1
                ex[f"{lang} D7 left empty on a function-word piece (pid basis)"].append(f"{pid} {got[1]}")
                got = None
            if got is None:
                who.append("")
                basis.append("")
            else:
                who.append(" ".join(sorted(got[0])))
                basis.append(got[1])
                cnt[f"{lang} D7 pieces with who: {got[1]}"] += 1
        out[lang] = (who, basis)
    return out


def addressees(E, corpus, quotes, pquotes, greek, cnt):
    """quotation id -> ent or None (D10, D13): only rows whose quotation has the same id, first and last word in the
    review-free layer (`quotes`) as in the reviewed one (`pquotes`; Greek: the review rows touch no span), and whose
    basis is not `turn`."""
    tag = f"{'grc' if greek else 'tan'} D10 addressee"
    out = {}
    for r in EP.read_tsv(EP.ADDR):
        if r["corpus"] != corpus:
            continue
        q = r["quote"]
        rb = quotes.get(q)
        if rb is None:
            cnt[f"{tag}: rows whose quotation is not in the review-free layer"] += 1
            continue
        first = rb["start"] if greek else rb["first"]
        if r["first"] != first:
            if greek and X.V12:   # SPEC 1.2 D10: a Greek row's first word is not compared (the row has no last word)
                cnt[f"{tag}: rows whose first word differs from the review-free quotation's (not compared, 1.2)"] += 1
            else:
                cnt[f"{tag}: rows whose first word differs from the review-free quotation's"] += 1
                continue
        if not greek:
            pr = pquotes.get(q)
            if pr is None or (pr["first"], pr["last"]) != (rb["first"], rb["last"]):
                cnt[f"{tag}: rows whose quotation has another span in the review-free layer"] += 1
                continue
        if r["basis"] == "turn":
            cnt[f"{tag}: rows of basis turn, not taken"] += 1
            continue
        a = r["addressee"]
        if not a:
            cnt[f"{tag}: rows with no addressee"] += 1
            out[q] = None
        elif a.startswith("lemma:"):
            cnt[f"{tag}: rows whose addressee is lemma:<strong>, left empty"] += 1
            out[q] = None
        else:
            out[q] = E.ent(a, tag)
            cnt[f"{tag}: rows taken{'' if out[q] else ' (no participant)'}"] += 1
    return out


def d10(K_by, greek, outdir, E, chars, cnt, ex, counts):
    tag = "grc" if greek else "tan"
    if greek:
        seg, quotes, layout_sid = EP.grc_speech(outdir)
        pquotes = {}
        corr = set()
    else:
        seg, quotes = EP.heb_speech(outdir)
        _pseg, pquotes = EP.heb_speech_published()
        corr = {r["first"] for r in EP.read_tsv(CORRECTIONS)}
        cnt["tan D10 corrections.tsv rows"] = len(EP.read_tsv(CORRECTIONS))
        cnt["tan D10 review-free quotations whose first word is a corrections.tsv key"] = sum(
            1 for q in quotes.values() if q["first"] in corr)
    addr = addressees(E, "grc" if greek else "hbo", quotes, pquotes, greek, cnt)
    out = {}
    for lang, K in K_by.items():
        quote, speaker, addressee, sb = [], [], [], []
        for ck, line in zip(K["clause"], K["line"]):
            q = seg.get(line, "")
            if line not in seg:
                cnt[f"{lang} D10 clauses whose line is not in the speech segments"] += 1
            if not q:
                quote.append("")
                speaker.append("")
                addressee.append("")
                sb.append("")
                continue
            if q not in quotes:
                raise SystemExit(f"{lang}: quotation {q} of line {line} not in the quotation table")
            quote.append(f"q:{q}")
            c = quotes[q]["speaker_id"]
            e = chars.get(c) if c else None
            if not c:
                cnt[f"{lang} D10 clauses in a quotation with no character id"] += 1
            elif c not in chars:
                cnt[f"{lang} D10 clauses whose character id is not in characters.tsv"] += 1
                ex[f"{lang} D10 character id not in characters.tsv"].append(f"{ck} {c}")
            elif e is None:
                cnt[f"{lang} D10 clauses whose character has no participant"] += 1
            speaker.append(e or "")
            a = addr.get(q)
            if q not in addr:
                cnt[f"{lang} D10 clauses whose quotation has no strict addressees row"] += 1
            addressee.append(a or "")
            first = quotes[q]["start"] if greek else quotes[q]["first"]
            sb.append("derived" if first in corr else "linked")
        for col, vals in (("quote", quote), ("speaker", speaker), ("addressee", addressee)):
            cnt[f"{lang} D10 clauses with {col}"] = sum(1 for v in vals if v)
        for b, n in C.Counter(v for v in sb if v).items():
            cnt[f"{lang} D10 clauses with speech_basis {b}"] = n
        out[lang] = (quote, speaker, addressee, sb)
    return out


def name_of_acai(E, acai, lang):
    lem = E.rows[acai]["lemmas"].split(" | ")
    for pre in FALLBACK[lang]:
        for x in lem:
            if x.startswith(pre):
                return x[len(pre):]
    return ""


def se5_rows(Ps, added):
    """SPEC 1.6 section 7, SE5: rows of added whose who_reason is disagree; place the verb's stem piece (t.n), value
    the verb's who and the antecedent piece's who joined by ' | ', count the rule's rows in the language."""
    who, stem = {}, {}
    for P in Ps:     # the Tanakh tables of both languages: a verb or antecedent piece may stand in the other one
        who.update({(t, n): w for t, n, w in zip(P["t"], P["n"], P["who"])})
        stem.update({t: n for t, n, k in zip(P["t"], P["n"], P["kind"]) if k == "stem"})
    rows = []
    for a in added:
        if a.get("who_reason") not in ("disagree",) + (("antecedent_not_verb",) if getattr(X, "V19", False) else ()):
            continue        # SPEC 1.9 SE5 (N4): the rows of antecedent_not_verb too (the two readings still disagree)
        n = stem[a["verb"]]
        at, an = map(int, a["antecedent"].split("."))
        rows.append((a["verb"], n, a["clause"], f"{who[(a['verb'], n)]} | {who[(at, an)]}"))
    rows.sort()
    return [("SE5", "acai", f"{t}.{n}", v, len(rows)) for t, n, _k, v in rows]


def source_errors(lang, W, P, E, lemma, ent_type, K=None, rel_term=None):
    """SE1, SE2 (SPEC 7, 'Source errors') -> rows (rule, source, place, value, count)."""
    rows = {"SE1": [], "SE2": []}
    god = {EP.ent_key(a, "deity") for a, r in E.rows.items() if r["primary"] == "deity:Lord" and r["type"] == "deity"}
    stem_lemma = {}
    for t, k, lx in zip(P["t"], P["kind"], P["lexeme"]):
        if k == "stem":
            stem_lemma[t] = nfc(lemma[lx])
    deps = C.defaultdict(set)
    for t, h in zip(W["t"], W["head"]):
        if h:
            deps[h].add(t)
    nxt = {W["t"][i]: W["t"][i + 1] for i in range(len(W["t"]) - 1)}
    others = {nfc(x) for x in OTHER_LEMMAS}
    for t, n, k, lx, who, wb, cl, mk in zip(P["t"], P["n"], P["kind"], P["lexeme"], P["who"], P["who_basis"],
                                             P["class"], P["marks"]):
        if not who or wb != "explicit":
            continue
        es = who.split()
        if nfc(lemma[lx]) in {nfc(x) for x in GOD_LEMMAS} and god & set(es) and lang != "grc":
            dep = any(stem_lemma.get(d) in others for d in deps.get(t, ()))
            cstr = json.loads(mk).get("state") == "cstr" and stem_lemma.get(nxt.get(t)) == nfc("נֵכָר")
            if dep or cstr:
                rows["SE1"].append((t, n, who))
        if k == "stem" and cl == "verb" and all(ent_type[e] in SE2_TYPES for e in es):
            rows["SE2"].append((t, n, who))
    out = []
    for rule in ("SE1", "SE2"):
        for t, n, who in sorted(rows[rule]):
            out.append((rule, "acai", f"{t}.{n}", who, len(rows[rule])))
    if X.V12:
        # SE3: a piece of lemma הַ whose class is not art; value its class
        # only stem pieces: the 91 prefix pieces of lemma הַ (interrogative, class ptcl, in c1) are not in the
        # specification's count of 49 (stage 23 report, "For the specification")
        se3 = sorted((t, n, cl) for t, n, k, lx, cl in zip(P["t"], P["n"], P["kind"], P["lexeme"], P["class"])
                     if lang != "grc" and k == "stem" and nfc(lemma[lx]) == nfc(ARTICLE_LEMMA) and cl != "art")
        out += [("SE3", "macula", f"{t}.{n}", cl, len(se3)) for t, n, cl in se3]
        # SE4 (grc): relation `relative`, first word ὅς, second μέν or δέ, third neither ἄν nor ἐάν
        se4 = []
        if lang == "grc" and K is not None:
            rel = rel_term
            for ck, f, mk in zip(K["clause"], K["first"], K["marks"]):
                m = json.loads(mk or "{}")
                if m.get("relation") != rel:
                    continue
                if stem_lemma.get(f) == nfc(SE4_FIRST) and stem_lemma.get(f + 1) in {nfc(x) for x in SE4_SECOND} \
                        and stem_lemma.get(f + 2) not in {nfc(x) for x in SE4_THIRD}:
                    se4.append(ck)
        out += [("SE4", "connectives", ck, rel_term, len(se4)) for ck in se4]
    return out


def people_part(lang, P, K, prows, terms, pins):
    out = [MARKER, ""]
    bc = C.Counter(v for v in P["who_basis"] if v)
    out += ["[pieces.who_basis]", 'column = "who_basis"', 'basis = "derived"',
            'source = "rule D7: the step that gave who (strict steps; model: stage 17)"', "values = ["]
    desc = {"explicit": "D7 step 1: entity_words kind explicit", "pronominal": "D7 step 2: entity_words kind pronominal",
"subject": "D7 step 3: entity_words kind subject", "chain": "D7 step 4: MACULA's reference on the piece",
            "reference": "D7r: reference-status (basis ref) or implicit-args (A0, in_verb 1, zero subject) referent"}
    for b in sorted(bc):
        out.append(f"  {{ code = {X.toml_str(b)}, value = {X.toml_str(desc[b])}, rule = \"D7\", count = {bc[b]} }},")
    out += ["]", "", "[pieces.who]", 'column = "who"', 'basis = "derived (who_basis)"',
            f"source = {X.toml_str('data/entities/entity_words.tsv sha256 ' + pins['data/entities/entity_words.tsv'] + '; MACULA participantref, subjref, referent')}",
            'pattern = "<type>:e<10 hex> keys, sorted, separated by a space"',
            f"count = {sum(1 for v in P['who'] if v)}", ""]
    tc = C.Counter(r[1] for r in prows)
    code_of = {term: code for (cat, code), term in terms.items() if cat == "ent_type"}
    out += ["[participants.type]", 'column = "type"', 'basis = "given"',
            'source = "ACAI type of data/entities/entities.tsv, as the key prefix"', 'meaning = "terms.tsv"', "values = ["]
    for t in sorted(tc, key=lambda x: code_of[x]):
        out.append(f"  {{ code = {X.toml_str(code_of[t])}, value = {X.toml_str(code_of[t])}, rule = \"terms\", "
                   f"term = {X.toml_str(t)}, count = {tc[t]} }},")
    out += ["]", ""]
    for col, i, desc_ in (("name_basis", 3, {"derived": "D7n: the commonest MACULA lemma (NFC) of the explicit noun "
                                                      "or adjective stem pieces", "given": "D7n: ACAI's first lemma "
                                                      "in the script (entities.tsv lemmas)"}),
                          ("ent_basis", 7, {"given": "a strict column names the participant",
                                            "model": "only M columns name the participant"})):
        cc = C.Counter(r[i] for r in prows if r[i])
        out += [f"[participants.{col}]", f'column = "{col}"', 'basis = "derived"', 'source = "SPEC 4.5"', "values = ["]
        for c in sorted(cc):
            out.append(f"  {{ code = {X.toml_str(c)}, value = {X.toml_str(desc_[c])}, rule = \"4.5\", count = {cc[c]} }},")
        out += ["]", ""]
    sc = C.Counter(v for v in K["speech_basis"] if v)
    out += ["[clauses.speech_basis]", 'column = "speech_basis"', 'basis = "derived"',
            'source = "rule D10: derived where a corrections.tsv row is keyed on the quotation\'s first word"',
            "values = ["]
    for c in sorted(sc):
        v = ("resources/speaker_layer/corrections.tsv row keyed on the quotation's first word" if c == "derived" else
             "the review-free speech layer")
        out.append(f"  {{ code = {X.toml_str(c)}, value = {X.toml_str(v)}, rule = \"D10\", count = {sc[c]} }},")
    out += ["]", ""]
    ev = ("Rests on English evidence: Clear's quotation spans projected from English translations' quotation marks, "
          "the nesting votes of eight English translations and the BSB, speaker ids of English labels (Glyssen, "
          "Clear), resources/proper_nouns/eng.tsv. No English value enters.")
    for col, pat in (("quote", "q:<quotation id>"), ("speaker", "an ent key"), ("addressee", "an ent key")):
        out += [f"[clauses.{col}]", f'column = "{col}"', 'basis = "linked"',
                f"source = {X.toml_str('rule D10: the speaker layer without review rows (build_speaker_layer.py --no-review; Greek: the layout speech fields recomputed with no review row)' + ('; data/addressees/quotations.tsv sha256 ' + pins['data/addressees/quotations.tsv'] if col == 'addressee' else ''))}",
                f"english_evidence = {X.toml_str(ev)}", f"pattern = {X.toml_str(pat)}",
                f"count = {sum(1 for v in K[col] if v)}", ""]
    return "\n".join(out)


def build(outdir, langs, counts):
    ex = C.defaultdict(list)
    cnt = C.Counter()
    langs = set(langs)
    if {"hbo", "arc"} & langs and not {"hbo", "arc"} <= langs:
        raise SystemExit("stage 16: hbo and arc are built together")
    terms = {lg: V11.read_terms(outdir, lg) for lg in langs}
    pins = {}
    EP.speech_sources(outdir)
    E = EP.Entities(cnt)
    rows, begins = entity_rows(E, cnt)
    chars = EP.characters(E, cnt)
    mt = pq.read_table(os.path.join(outdir, "cache", "morphid.parquet"), columns=["morphid", "pid"]).to_pydict()
    morph = dict(zip(mt["morphid"], mt["pid"]))
    groups = ([(("hbo", "arc"), False)] if "hbo" in langs else []) + ([(("grc",), True)] if "grc" in langs else [])
    kin = EP.read_tsv(os.path.join(EP.ENT, "kinship.tsv"))
    for gl, greek in groups:
        tag = "grc" if greek else "tan"
        V = V11.compute(outdir, gl, greek, cnt, ex, pins, counts, terms,
                        more=EX13.more_data(greek) if getattr(X, "V13", False) else None)
        T = V["T"]
        for lang in gl:
            K, N = T[lang]["K"], T[lang]["N"]
            K["marks"] = [V["marks"][k] for k in K["clause"]]
            K["line"] = [V["line"][k] for k in K["clause"]]
            N["sem_role"] = [V["sem"].get((k, o), "") for k, o in zip(N["clause"], N["ord"])]
            N["sem_role_basis"] = [V["semb"].get((k, o), "") for k, o in zip(N["clause"], N["ord"])]
        whos = d7({lg: T[lg]["P"] for lg in gl}, greek, rows, begins, morph, cnt, ex)
        speech = d10({lg: T[lg]["K"] for lg in gl}, greek, outdir, E, chars, cnt, ex, counts)
        added13 = who13 = None
        if getattr(X, "V13", False):      # SPEC 1.3 (stage 27): D9m, D17, D20, D21, D18
            added13, who13 = EX13.hook16(gl, greek, T, V, E, terms, cnt, ex, counts, pins)
            # SPEC 1.3 (stage 28): D12c, D16, D7r (fills whos in place), D19
            wa13 = EX13M.hook28(gl, greek, T, V, E, terms, whos, rows, cnt, ex, counts)
            if getattr(X, "V15", False):    # SPEC 1.5: D12c (the causer), D18 (drops, kind, form, step W)
                import examples_v15 as EX15
                lemma15 = {}
                for lg in gl:
                    with open(os.path.join(outdir, lg, "lexemes.tsv"), encoding="utf-8", newline="") as fh:
                        for r_ in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
                            lemma15[r_["lexeme"]] = r_["lemma"]
                added13 = EX15.hook35(gl, greek, T, V, terms, whos, added13, lemma15, cnt, ex, counts)
                for lg in gl:     # SPEC 1.5 4.5: added.who names no participant of its own
                    cnt[f"{lg} 1.5 entities of the 1.4 added.who (no participant by added.who now)"] = len(who13[lg])
                    who13[lg] = set()
        for lang in gl:
            W, P, K, N = T[lang]["W"], T[lang]["P"], T[lang]["K"], T[lang]["N"]
            P["who"], P["who_basis"] = whos[lang]
            K["quote"], K["speaker"], K["addressee"], K["speech_basis"] = speech[lang]
            d = os.path.join(outdir, lang)
            lemma = {}
            with open(os.path.join(d, "lexemes.tsv"), encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
                    lemma[r["lexeme"]] = r["lemma"]
            # participants (strict rows), D7n
            wordset = C.defaultdict(set)
            namec = C.defaultdict(C.Counter)
            for t, k, cl, lx, w, b in zip(P["t"], P["kind"], P["class"], P["lexeme"], P["who"], P["who_basis"]):
                for e in w.split():
                    wordset[e].add(t)
                    if b == "explicit" and k == "stem" and cl in NAME_CLASSES:
                        if X.V12 and nfc(lemma[lx]) == nfc(ARTICLE_LEMMA):    # SPEC 1.2 D7n (SE3)
                            cnt[f"{lang} D7n stem pieces of lemma הַ left out of the names"] += 1
                            continue
                        namec[e][nfc(lemma[lx])] += 1
            ents = set(wordset) | {e for e in K["speaker"] if e} | {e for e in K["addressee"] if e}
            if who13 is not None:          # SPEC 1.3 4.5: the participants of added.who
                cnt[f"{lang} 1.3 participants only through added.who"] = len(who13[lang] - ents)
                ents |= who13[lang]
            prows, ent_type = [], {}
            for e in sorted(ents):
                acai = E.acai_of[e]
                r = E.rows[acai]
                ent_type[e] = r["type"]
                given = name_of_acai(E, acai, lang)
                if who13 is not None and EX13M.catch_all(acai):     # SPEC 1.3 D7n: a catch-all gets no name
                    nm, nb = "", ""
                    cnt[f"{lang} D7n catch-all participants, no name (1.3)"] += 1
                elif namec[e]:
                    top = max(namec[e].values())
                    nm, nb = min(x for x, v in namec[e].items() if v == top), "derived"
                    if given and nfc(given) != nm:
                        cnt[f"{lang} D7n participants where the two steps would differ"] += 1
                elif given:
                    nm, nb = given, "given"
                else:
                    nm, nb = "", ""
                    cnt[f"{lang} D7n participants unnamed"] += 1
                if nb:
                    cnt[f"{lang} D7n participants named, {nb}"] += 1
                prows.append((e, V11.term_of(terms, lang, "ent_type", r["type"]), nm, nb,
                              EP.SEX.get(r["gender"], ""), len(wordset.get(e, ())), None, "given"))
            X.write_tsv(os.path.join(d, "participants.tsv"), PART_HEADER, prows)
            cnt[f"{lang} participants"] = len(prows)
            cnt[f"{lang} participants only as speaker or addressee"] = sum(1 for r in prows if r[5] == 0)
            counts[f"{lang} participants by type"] = dict(sorted(C.Counter(ent_type.values()).items()))
            counts[f"{lang} top participants by words"] = [[r[0], r[2], r[3], r[5]] for r in
                                                           sorted(prows, key=lambda r: (-r[5], r[0]))[:25]]
            counts[f"{lang} unnamed participants by words (top 25)"] = [
                [r[0], r[5]] for r in sorted(prows, key=lambda r: (-r[5], r[0])) if not r[2]][:25]
            # kin facts
            facts = set()
            for r in kin:
                rel = r["relation"]
                if rel in EP.KIN_NOT_TAKEN:
                    continue
                if rel not in EP.KIN:
                    raise SystemExit(f"kinship.tsv: relation {rel!r} not in the specification")
                a, b = E.rows.get(r["entity"]), E.rows.get(r["other"])
                if a is None or b is None or a["type"] not in EP.TYPES or b["type"] not in EP.TYPES:
                    cnt[f"{lang} kin rows with a side of no participant type or no entities.tsv row"] += 1
                    continue
                sa, so = EP.ent_key(r["entity"], a["type"]), EP.ent_key(r["other"], b["type"])
                if sa not in ents or so not in ents:
                    cnt[f"{lang} kin rows left out: a side is no participant of the language"] += 1
                    continue
                facts.add((sa, rel, so))
            facts = sorted(facts)
            n = len(facts)
            X.write_parquet(os.path.join(d, "facts.parquet"), {
                "subject": [f[0] for f in facts], "relation": [f[1] for f in facts], "object": [f[2] for f in facts],
                "kind": ["given"] * n, "method": ["kinship.tsv:relation"] * n, "source": ["acai"] * n,
                "confidence": [None] * n, "count": [None] * n, "share": [None] * n, "tier": [""] * n}, EP.FACT_SCHEMA)
            cnt[f"{lang} facts kin rows"] = n
            counts[f"{lang} facts by relation"] = dict(sorted(C.Counter(f[1] for f in facts).items()))
            # source errors
            se = source_errors(lang, W, P, E, lemma, ent_type, K, terms[lang].get(("relation", "relative")))
            if getattr(X, "V16", False):     # SPEC 1.6 section 7, SE5 (R8): the added rows of who_reason disagree
                se = se + se5_rows([dict(T[lg_]['P'], who=whos[lg_][0]) for lg_ in gl], added13[lang])
            X.write_tsv(os.path.join(d, "source_errors.tsv"), SE_HEADER, se)
            for rule in ("SE1", "SE2") + (("SE3", "SE4") if X.V12 else ()) + (("SE5",) if getattr(X, "V16", False) else ()):
                cnt[f"{lang} source_errors {rule}"] = sum(1 for r in se if r[0] == rule)
            # tables
            X.write_parquet(os.path.join(d, "pieces.parquet"), P, pa.schema(V11_PIECE_COLS()))
            X.write_parquet(os.path.join(d, "clauses.parquet"), K, pa.schema(EC.CLAUSE_COLS_11))
            X.write_parquet(os.path.join(d, "constituents.parquet"), N, pa.schema(EC.CONST_COLS_11))
            if added13 is not None:
                EX13.write_added(d, added13[lang])
                EX13M.write_account(d, wa13[lang])
            pins.update({os.path.relpath(p, S.HERE): S.sha256(p) for p in (
                os.path.join(EP.ENT, "entity_words.tsv"), os.path.join(EP.ENT, "entities.tsv"),
                os.path.join(EP.ENT, "characters.tsv"), os.path.join(EP.ENT, "kinship.tsv"), EP.ADDR)})
            pins["resources/speaker_layer/corrections.tsv"] = S.sha256(CORRECTIONS)
            path = os.path.join(d, "categories.toml")
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            base = text.split(V11.MARKER)[0].rstrip("\n") + "\n\n"
            X.write_text(path, base + V11.clause_part(lang, V, pins, tag, terms) + "\n"
                         + (EX13M.cat16(lang, K, wa13[lang], terms[lang]) + "\n" if added13 is not None else "")
                         + people_part(lang, P, K, prows, terms[lang], pins))
            parsed = [json.loads(v) for v in K["marks"]]
            for cat, *_ in V11.CATS:
                cnt[f"{lang} {cat}: clauses with a value"] = sum(1 for v in parsed if cat in v)
                counts[f"{lang} values {cat}"] = dict(sorted(V["use"][(lang, cat)].items()))
            counts[f"{lang} values sem_role"] = dict(sorted(V["sem_use"][lang].items()))
            counts[f"{lang} sem_role_basis by role_basis"] = {f"{b} {s}": v for (b, s), v in
                                                              sorted(V["semb_use"][lang].items())}
            cnt[f"{lang} clauses with marks not empty"] = sum(1 for v in parsed if v)
            cnt[f"{lang} constituents with sem_role"] = sum(1 for v in N["sem_role"] if v)
            tb = C.defaultdict(set)
            for t, b in zip(P["t"], P["who_basis"]):
                if b:
                    tb[b].add(t)
            counts[f"{lang} words with who by basis"] = {b: len(v) for b, v in sorted(tb.items())}
            cnt[f"{lang} words with who"] = len({t for t, w in zip(P["t"], P["who"]) if w})
    with open(NT_REVIEW, encoding="utf-8") as fh:
        hdr = next(ln for ln in fh if not ln.startswith("#") and ln.strip())
        fi = hdr.rstrip("\n").split("\t").index("field")
        fields = C.Counter(ln.rstrip("\n").split("\t")[fi] for ln in fh if ln.strip() and not ln.startswith("#"))
    counts["grc nt_review.tsv rows by field (no span field: the Greek spans are the same with and without review)"] = \
        dict(sorted(fields.items()))
    counts["pins"] = pins
    for k in sorted(cnt):
        counts[k] = cnt[k]
    return ex


def V11_PIECE_COLS():
    import examples_core
    return examples_core.PIECE_COLS_11
