#!/usr/bin/env python3
"""Hebrew equivalent per Aramaic word: for every Aramaic content word of the Tanakh (Daniel, Ezra, Jer 10:11, Gen 31:47), the
Hebrew lexeme that says the same thing at that place, so Aramaic reaches what is known of Hebrew words by meaning, not only by
cognate. Aramaic עֲבַד "do, make" goes to עָשָׂה (its cognate עָבַד mostly means "serve"); a word with no cognate (a Persian title)
goes to the Hebrew word for the same office.

    cd shoresh && .venv/bin/python3 -m macula.build_aramaic_equivalents [--lxx PATH]

Evidence, all from the original-language sources:
  - the word's UBS senses and domains (SDBH; Aramaic and Hebrew share the domain codes);
  - the Greek at the place: MACULA Hebrew's own link (greekstrong), else the content words of the Septuagint verse
    (Theodotion for Daniel, --lxx; GLAUx for Ezra);
  - the Septuagint bridge (resources/lxx_bridge_tiers/macula.tsv): how often a Hebrew lexeme is rendered by that Greek;
  - the cognate (data/aramaic-cognates, basis strongs or consonants), as one candidate among others.
The cognate is kept where at least KEEP_COGNATE of its own occurrences carry one of the word's UBS domains (evidence
cognate_meaning); only where the meaning has moved, or there is no cognate, is an equivalent sought.
Score of a Hebrew candidate h (content lexeme of the same word class, 10+ occurrences, or the cognate):
  domain(h) = share of h's occurrences whose UBS domains meet the Aramaic word's   (how typical this meaning is for h)
  greek(h)  = the largest P(greek | h) over the Greek at the place                   (1 where no Greek is known)
  score     = domain(h) * greek(h), the cognate's score times COGNATE_PRIOR; a candidate other than the cognate needs
              domain(h) >= MIN_EQ_SHARE
One row per Aramaic content word: key, aramaic_strong, aramaic_lemma, hebrew_strong, hebrew_lemma, basis (cognate | equivalent),
evidence (greek_word | greek_verse | domain), score, margin (best over second), cognate_strong, candidates (the Hebrew strongs
of the same word class and meaning scoring at least RATIO x the best: one where one stands out, many where several compete; the
pick first), candidate_scores (theirs, same order). The pick serves a rule engine that takes
one word; the list serves a drafter that can weigh several (synonyms and related words).
Check (checks.md): the same procedure on the Hebrew content words of Daniel and Ezra, the true lexeme standing in for the cognate:
how often the best candidate is the word itself. No English is read (UBS codes only; no glosses, no definitions).
Output macula/data/aramaic-equivalents/{words.tsv, lexemes.tsv, checks.md, build.json} (git-ignored).
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import json
import re
import sqlite3
import subprocess
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "aramaic-equivalents"
BRIDGE = HERE.parent.parent / "resources" / "lxx_bridge_tiers" / "macula.tsv"
MIN_FREQ = 10
COGNATE_PRIOR = 1.5
RATIO = 0.2                 # a candidate is listed when it scores at least RATIO x the best
RATIOS = (0.5, 0.3, 0.2, 0.1, 0.05)
LIST_CAP = 15                # a safety cap, not a target
LIST_MIN_FREQ = 2           # list only: Hebrew lexemes with 2+ occurrences (פִּתְרוֹן has 5)
MIN_LIST_SHARE = 0.05       # list only: a candidate carrying the word's domain on at least this share of its occurrences
GREEK_FLOOR = 0.01          # list only: a candidate the Greek at the place does not point to keeps this much
KEEP_COGNATE = 0.3          # the cognate stays where at least this share of its own occurrences carry the word's UBS domain
MIN_EQ_SHARE = 0.2          # an equivalent must carry the word's UBS domain on at least this share of its own occurrences
CONTENT = ("noun", "verb", "adj")


def n(s) -> str:
    m = re.match(r"[A-Za-z]*0*(\d+)", str(s or ""))
    return m.group(1) if m else ""


def dan_greek_verse(ch: int, v: int) -> tuple[int, int]:
    """Hebrew / Aramaic Daniel verse -> GLAUx verse (the Greek carries the 3:24-90 additions; MT 3:31-33 is Greek 4:1-3)"""
    if ch == 3 and 24 <= v <= 30:
        return 3, v + 67
    if ch == 3 and v >= 31:
        return 4, v - 30
    if ch == 4:
        return 4, v + 3
    return ch, v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lxx", type=Path, default=HERE.parent / "lxx" / "data" / "lxx-glaux-dan-theodotion.db")
    a = ap.parse_args()
    m = sqlite3.connect(f"file:{HERE / 'macula-spine.db'}?mode=ro", uri=True)
    lf = sqlite3.connect(f"file:{HERE / 'lowfat-hbo.db'}?mode=ro", uri=True)
    proper = {k[:12] for (k,) in lf.execute("select key from lowfat_words where type = 'proper'")}
    gk = {k[:12]: n(g.split()[0]) for k, g in lf.execute("select key, greekstrong from lowfat_words where greekstrong != ''")}
    words, wclass, hclass = [], {}, collections.defaultdict(collections.Counter)
    for k, wl, b, ch, v, st, lem, cl in m.execute(
            "select key, wlang, book, chapter, verse, strong, lemma, class from macula_words where lang = 'hbo'"):
        if cl in CONTENT and k not in proper and n(st):
            words.append((k, wl, b, int(ch), int(v), n(st), unicodedata.normalize("NFC", lem or "")))
            wclass[k] = cl
    doms = {}
    for r in csv.DictReader(open(DATA / "word-senses-ubs/words.tsv", encoding="utf-8"), delimiter="\t"):
        if r["lang"] == "hbo" and r["domains"]:
            doms[r["key"]] = set(d for d in r["domains"].split(";") if d)
    # Hebrew lexicon: frequency, domain counts, lemma
    hfreq, hdom, hlem = collections.Counter(), collections.defaultdict(collections.Counter), {}
    dom_lex = collections.defaultdict(set)
    for k, wl, b, ch, v, st, lem in words:
        if wl != "H":
            continue
        hfreq[st] += 1
        hlem.setdefault(st, lem)
        hclass[st][wclass[k]] += 1
        for d in doms.get(k, ()):
            hdom[st][d] += 1
    for st, c in hdom.items():
        if hfreq[st] >= MIN_FREQ:
            for d in c:
                dom_lex[d].add(st)
    dom_tok = collections.defaultdict(lambda: collections.defaultdict(int))   # (st) -> {frozenset(domains): n}
    for k, wl, b, ch, v, st, lem in words:
        if wl == "H":
            dom_tok[st][frozenset(doms.get(k, ()))] += 1
    p_g = collections.defaultdict(dict)                                       # h -> {g: P(g | h)}
    for r in csv.DictReader(open(BRIDGE, encoding="utf-8"), delimiter="\t"):
        p_g[n(r["hebrew_strong"])][n(r["greek_strong"])] = float(r["score"])
    cog = {}
    for r in csv.DictReader(open(DATA / "aramaic-cognates/cognates.tsv", encoding="utf-8"), delimiter="\t"):
        if r["basis"] in ("strongs", "consonants"):
            cog[r["aramaic_strong"]] = r["hebrew_strong"]
    # the Greek verse: Theodotion for Daniel, GLAUx for the rest
    def verse_sets(db: Path, book: str) -> dict:
        out = collections.defaultdict(set)
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        for ch, v, st, c in con.execute("select chapter, verse, strong, is_content from lxx_words where book = ?", (book,)):
            if c and n(st):
                out[(int(ch), int(v))].add(n(st))
        return out
    gverse = {"DAN": verse_sets(a.lxx, "DAN"), "EZR": verse_sets(HERE.parent / "lxx" / "data" / "lxx-glaux.db", "EZR"),
              "JER": verse_sets(HERE.parent / "lxx" / "data" / "lxx-glaux.db", "JER"),
              "GEN": verse_sets(HERE.parent / "lxx" / "data" / "lxx-glaux.db", "GEN")}

    def domain_share(h: str, dset: set) -> float:
        tot = hfreq[h]
        if not tot or not dset:
            return 0.0
        return sum(cnt for ds, cnt in dom_tok[h].items() if ds & dset) / tot

    list_lex = collections.defaultdict(set)                                    # domain -> Hebrew lexemes (2+ occurrences)
    for st_, c in hdom.items():
        if hfreq[st_] >= LIST_MIN_FREQ:
            for d in c:
                list_lex[d].add(st_)
    NOMINAL = {"noun", "adj"}

    def same_class(h: str, cl: str) -> bool:
        hc = hclass[h].most_common(1)[0][0]
        return hc == cl or (hc in NOMINAL and cl in NOMINAL)          # Hebrew חָכָם "wise" (adjective) for Aramaic חַכִּים (noun)

    def rank(k, b, ch, v, prior: str, own_greek: bool = True) -> list:
        """every candidate (word class, carrying the word's domain, or the cognate) with its score, best first; the word's most
        specific domain codes weigh most, so a code as broad as "person" cannot fill the list"""
        dset = doms.get(k, set())
        cl = wclass.get(k, "")
        top_len = max((len(d) for d in dset), default=0)
        spec = {d for d in dset if len(d) == top_len}
        cands = {h for h in set().union(*(list_lex.get(d, set()) for d in dset))
                 if same_class(h, cl) and domain_share(h, dset) >= MIN_LIST_SHARE} if dset else set()
        if prior:
            cands.add(prior)
        if own_greek and k in gk:
            greek = {gk[k]}
        else:
            greek = gverse.get(b, {}).get(dan_greek_verse(ch, v) if b == "DAN" else (ch, v), set())
        out = []
        for h in cands:
            ds = (domain_share(h, spec) + 0.3 * domain_share(h, dset)) if dset else (1.0 if h == prior else 0.0)
            gs = max((p_g[h].get(g, 0.0) for g in greek), default=0.0) if greek else 1.0
            sc = ds * max(gs, GREEK_FLOOR) * (COGNATE_PRIOR if h == prior else 1.0)   # in a list, no Greek only lowers the rank
            out.append((sc, hfreq[h], h))
        out.sort(reverse=True)
        return [(h, sc) for sc, _, h in out]

    def cut(rk: list, ratio: float) -> list:
        """the candidates scoring at least ratio x the best: one word where one stands out, many where several compete"""
        if not rk:
            return []
        best = rk[0][1]
        return [h for h, sc in rk if best > 0 and sc >= ratio * best][:LIST_CAP] or [rk[0][0]]

    def choose(k, b, ch, v, prior: str, gate: bool = True):
        dset = doms.get(k, set())
        if gate and prior and (not dset or domain_share(prior, dset) >= KEEP_COGNATE):
            return prior, "cognate_meaning", 1.0, float("inf")          # the cognate's own meanings cover this word: keep it
        cl = wclass.get(k, "")
        cands = {h for h in set().union(*(dom_lex.get(d, set()) for d in dset))
                 if hclass[h].most_common(1)[0][0] == cl and domain_share(h, dset) >= MIN_EQ_SHARE} if dset else set()
        # same word class (a verb goes to a verb), and a meaning the candidate itself often has: the Greek of a verse can only
        # choose among words that mean this, never bring in one that does not ("there is" is never "father")
        if prior:
            cands.add(prior)
        if not cands:
            return None
        if k in gk:
            greek, ev = {gk[k]}, "greek_word"
        else:
            gv = gverse.get(b, {}).get(dan_greek_verse(ch, v) if b == "DAN" else (ch, v), set())
            greek, ev = gv, ("greek_verse" if gv else "domain")
        scored = []
        for h in cands:
            ds = domain_share(h, dset) if dset else (1.0 if h == prior else 0.0)
            gs = max((p_g[h].get(g, 0.0) for g in greek), default=0.0) if greek else 1.0
            s = ds * gs * (COGNATE_PRIOR if h == prior else 1.0)
            scored.append((s, hfreq[h], h))
        scored.sort(reverse=True)
        if scored[0][0] <= 0:
            if prior:
                return prior, "domain", 0.0, 0.0
            return None
        best = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        return best[2], ev, best[0], (best[0] / second if second else float("inf"))

    rows, st = [], collections.Counter()
    for k, wl, b, ch, v, s, lem in words:
        if wl != "A":
            continue
        pr = cog.get(s, "")
        r = choose(k, b, ch, v, pr)
        st["aramaic"] += 1
        if r is None:
            st["none"] += 1
            rk = rank(k, b, ch, v, pr)
            keep = set(cut(rk, RATIO))
            rk = [x for x in rk if x[0] in keep]
            rows.append([k, s, lem, "", "", "", "", "", "", pr, " ".join(x for x, _ in rk), " ".join(f"{y:.4f}" for _, y in rk)])
            continue
        h, ev, sc, mg = r
        rk = rank(k, b, ch, v, pr)
        keep = set(cut(rk, RATIO)) | {h}                                 # the pick is always on the list, first
        rk = [(h, dict(rk).get(h, sc))] + [x for x in rk if x[0] in keep and x[0] != h]
        cand = " ".join(x for x, _ in rk)
        cand_sc = " ".join(f"{y:.4f}" for _, y in rk)
        basis = "cognate" if h == pr else "equivalent"
        st[basis] += 1
        st["evidence:" + ev] += 1
        rows.append([k, s, lem, h, hlem.get(h, ""), basis, ev, f"{sc:.4f}", "inf" if mg == float("inf") else f"{mg:.2f}", pr,
                     cand, cand_sc])
    # check on Hebrew words of the same books, the word itself standing in for the cognate
    chk = collections.Counter()
    lens = collections.defaultdict(list)
    for k, wl, b, ch, v, s, lem in words:
        if wl != "H" or b not in ("DAN", "EZR") or hfreq[s] < MIN_FREQ:
            continue
        r = choose(k, b, ch, v, s, gate=False)
        if r is None:
            continue
        ev = r[1]
        chk[("all", "n")] += 1
        chk[("all", "self")] += r[0] == s
        chk[(ev, "n")] += 1
        chk[(ev, "self")] += r[0] == s
        r0 = choose(k, b, ch, v, "", gate=False)                       # without the prior: can the evidence alone find it
        chk[("no_prior", "n")] += 1
        chk[("no_prior", "self")] += bool(r0) and r0[0] == s
        rk0 = rank(k, b, ch, v, "")                                    # the list, without the prior: is the word on it
        for r_ in RATIOS:
            lst = cut(rk0, r_)
            chk[(f"list_ratio{r_}", "n")] += 1
            chk[(f"list_ratio{r_}", "self")] += s in lst
            lens[r_].append(len(lst))
    # bridge check: Aramaic words whose own Greek link MACULA records (greekstrong); that link hidden, the candidates ranked from the
    # Greek verse; is the hidden Greek among the bridge's Greek for the cognate alone / the pick / the list (bridge pairs, count 3+)
    bridge = collections.defaultdict(set)
    for h_, gs_ in p_g.items():
        bridge[h_] = set(gs_)
    bc = collections.Counter()
    for k, wl, b, ch, v, s, lem in words:
        if wl != "A" or k not in gk:
            continue
        g = gk[k]
        pr = cog.get(s, "")
        rk = rank(k, b, ch, v, pr, own_greek=False)
        lst = cut(rk, RATIO)
        bc["n"] += 1
        bc["none"] += 0
        bc["cognate"] += bool(pr) and g in bridge.get(pr, set())
        bc["pick"] += bool(lst) and g in bridge.get(lst[0], set())
        bc["list"] += any(g in bridge.get(h_, set()) for h_ in lst)
        bc["list_or_cognate"] += any(g in bridge.get(h_, set()) for h_ in set(lst) | ({pr} if pr else set()))
        bc["len"] += len(set(lst) | ({pr} if pr else set()))
    OUT.mkdir(parents=True, exist_ok=True)
    cols = ["key", "aramaic_strong", "aramaic_lemma", "hebrew_strong", "hebrew_lemma", "basis", "evidence", "score", "margin", "cognate_strong",
            "candidates", "candidate_scores"]
    with open(OUT / "words.tsv", "w", encoding="utf-8") as f:
        f.write("\t".join(cols) + "\n")
        f.writelines("\t".join(r) + "\n" for r in rows)
    lex = collections.defaultdict(collections.Counter)
    alem = {}
    for r in rows:
        if r[3]:
            lex[r[1]][r[3]] += 1
        alem[r[1]] = r[2]
    with open(OUT / "lexemes.tsv", "w", encoding="utf-8") as f:
        f.write("aramaic_strong\taramaic_lemma\ttokens\tcognate_strong\thebrew_equivalents (strong:count, most frequent first)\n")
        for s, c in sorted(lex.items(), key=lambda x: -sum(x[1].values())):
            f.write(f"{s}\t{alem[s]}\t{sum(c.values())}\t{cog.get(s, '')}\t" + " ".join(f"{h}:{x}" for h, x in c.most_common()) + "\n")
    lines = ["# Aramaic -> Hebrew equivalents: checks", "", "| what | count |", "|---|---|"]
    lines += [f"| {k} | {v:,} |" for k, v in sorted(st.items())]
    lines += ["", "Check on the Hebrew content words of Daniel and Ezra (best candidate = the word itself):", "",
              "| evidence | words | self | share |", "|---|---|---|---|"]
    for ev in sorted({e for e, _ in chk}):
        nn = chk[(ev, "n")]
        lines.append(f"| {ev} | {nn:,} | {chk[(ev, 'self')]:,} | {chk[(ev, 'self')] / nn:.3f} |")
    lines += ["", "List length on those words, by cutoff (candidates scoring at least ratio x the best; no cognate given):", "",
              "| ratio | on the list | mean length | one word | 2-4 | 5-9 | 10+ |", "|---|---|---|---|---|---|---|"]
    for r_ in RATIOS:
        L_ = lens[r_]
        lines.append(f"| {r_} | {chk[(f'list_ratio{r_}', 'self')] / chk[(f'list_ratio{r_}', 'n')]:.3f} | {sum(L_) / len(L_):.1f} | "
                     f"{sum(x == 1 for x in L_) / len(L_):.2f} | {sum(2 <= x <= 4 for x in L_) / len(L_):.2f} | "
                     f"{sum(5 <= x <= 9 for x in L_) / len(L_):.2f} | {sum(x >= 10 for x in L_) / len(L_):.2f} |")
    al = [len(r[10].split()) for r in rows if r[10]]
    lines += ["", f"Aramaic words: list length mean {sum(al) / len(al):.1f}; one word {sum(x == 1 for x in al) / len(al):.2f}, "
              f"2-4 {sum(2 <= x <= 4 for x in al) / len(al):.2f}, 5-9 {sum(5 <= x <= 9 for x in al) / len(al):.2f}, "
              f"10+ {sum(x >= 10 for x in al) / len(al):.2f} (ratio {RATIO})."]
    lines += ["", f"Bridge check: {bc['n']:,} Aramaic words with their own Greek link (MACULA greekstrong), the link hidden and the "
              "candidates ranked from the Greek verse; share whose Greek is among the bridge's Greek (pairs with count 3+) for:", "",
              "| Hebrew side | share |", "|---|---|"]
    for k_ in ("cognate", "pick", "list", "list_or_cognate"):
        lines.append(f"| {k_} | {bc[k_] / bc['n']:.3f} |")
    lines += ["", f"Mean Hebrew lexemes offered (list plus cognate): {bc['len'] / bc['n']:.1f}."]
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = subprocess.run(["git", "log", "-1", "--format=%h"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    (OUT / "build.json").write_text(json.dumps({"schema": 1, "built": datetime.date.today().isoformat(), "code": code,
                                                "lxx_daniel": a.lxx.name, "min_freq": MIN_FREQ, "cognate_prior": COGNATE_PRIOR,
                                                "not_read": ["BHSA", "TBTA", "English text"]}, indent=1) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
