"""Stage 40, items 1 and 2: statements "word X (at place P) is explained by words Y" read by a fixed rule from the four
Hebrew lexicographers on disk; coverage per part and band; the derived defining vocabulary.

  shoresh/.venv/bin/python -I shoresh/macula/levels_feasibility_explain.py
    -> stdout (counts), /tmp/claude-1000/source-examples/levels40/explain-statements.jsonl (every statement),
       explain-sample.md (20 per source), explain-counts.json
"""
import json
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from levels_feasibility_common import (BAND_NAMES, DATA, OUT, PARTS, SCRATCH, band, consonants, content_tokens, dump,  # noqa
                                       lexicon, resolve_at, resolve_word)

EN = {"Genesis": "GEN", "Exodus": "EXO", "Leviticus": "LEV", "Numbers": "NUM", "Deuteronomy": "DEU",
      "Joshua": "JOS", "Judges": "JDG", "Ruth": "RUT", "I Samuel": "1SA", "II Samuel": "2SA", "I Kings": "1KI",
      "II Kings": "2KI", "I Chronicles": "1CH", "II Chronicles": "2CH", "Ezra": "EZR", "Nehemiah": "NEH",
      "Esther": "EST", "Job": "JOB", "Psalms": "PSA", "Proverbs": "PRO", "Ecclesiastes": "ECC",
      "Song of Songs": "SNG", "Isaiah": "ISA", "Jeremiah": "JER", "Lamentations": "LAM", "Ezekiel": "EZK",
      "Daniel": "DAN", "Hosea": "HOS", "Joel": "JOL", "Amos": "AMO", "Obadiah": "OBA", "Jonah": "JON",
      "Micah": "MIC", "Nahum": "NAM", "Habakkuk": "HAB", "Zephaniah": "ZEP", "Haggai": "HAG",
      "Zechariah": "ZEC", "Malachi": "MAL"}
HE = {"בראשית": "GEN", "שמות": "EXO", "ויקרא": "LEV", "במדבר": "NUM", "דברים": "DEU", "יהושע": "JOS",
      "שופטים": "JDG", "רות": "RUT", 'ש"א': "1SA", 'ש"ב': "2SA", 'מ"א': "1KI", 'מ"ב': "2KI", "דה״א": "1CH",
      "דה״ב": "2CH", "עזרא": "EZR", "נחמיה": "NEH", "אסתר": "EST", "איוב": "JOB", "תהלים": "PSA",
      "משלי": "PRO", "קהלת": "ECC", "שיר": "SNG", "ישעיהו": "ISA", "ירמיהו": "JER", "ירמיה": "JER",
      "איכה": "LAM", "יחזקאל": "EZK", "דניאל": "DAN", "הושע": "HOS", "יואל": "JOL", "עמוס": "AMO",
      "עובדיה": "OBA", "יונה": "JON", "מיכה": "MIC", "נחום": "NAM", "חבקוק": "HAB", "צפניה": "ZEP",
      "חגי": "HAG", "זכריה": "ZEC", "מלאכי": "MAL"}
NUMV = {c: v for c, v in zip("אבגדהוזחטיכלמנסעפצקרשת", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 30, 40, 50, 60, 70,
                                                         80, 90, 100, 200, 300, 400])}
NUMV.update({"ך": 20, "ם": 40, "ן": 50, "ף": 80, "ץ": 90})


def hnum(s):
    s = re.sub(r"[\"'״׳‎\s]", "", s)
    if not s or any(c not in NUMV for c in s):
        return None
    return sum(NUMV[c] for c in s)


# cue word -> kind, per source (fixed lists; FEASIBILITY.md section 1 states them)
MEANING = {"ענין", "ענינו", "עניינו", "הוא", "היא", "הם", "ר״ל", 'ר"ל', "כעין", "פירוש", "פירושו", "ופירוש",
           "ופירושו", "כלומר", "פתרון", "פתרונו", "ופתרון"}
CUES = {
    "mz": {**{c: "meaning" for c in MEANING}, "כמו": "likeness", "מלשון": "derivation", "מל׳": "derivation",
           "מל'": "derivation", "תרגומו": "targum", "תרגם": "targum", "ת״י": "targum", "תרגום": "targum",
           "שם": "class", "מין": "class", "מקום": "class", "כלי": "class"},
    "malbim": {**{c: "meaning" for c in MEANING}, "כמו": "likeness", "מענין": "derivation", "מלשון": "derivation",
               "שם": "class", "מקום": "class"},
    "radak": {c: "meaning" for c in ("פירוש", "פירושו", "ופירוש", "ופירושו", "פירושם", "כלומר", "ענין", "ענינו")},
    "menahem": {**{c: "meaning" for c in ("ענין", "פתרון", "פתרונו", "ופתרון", "לשון")},
                "כמשמעו": "literal", "מגזרת": "derivation"},
}
STOPS = {"וכן", "כמו", "והוא", "ר״ל", 'ר"ל', "או", "כי", "אבל", "וזה", "רוצה", "וכמוהו", "ובדברי", "וכלם",
         "והם", "שהוא", "על", "אשר"}
FORMULA = {"אחד", "כפי", "לפי", "פתרו", "ויסודתם"}   # "one meaning", "as its sense": no explaining words
TOK = re.compile(r"<(b|strong)>(.*?)</\1>|<a [^>]*data-ref=\"([^\"]+)\"[^>]*>.*?</a>|<small>\((.*?)\)</small>|"
                 r"<[^>]+>|(\s'[^'<]{1,60}')|([^<\s]+)", re.S)


def events(html):
    """bold / ref / quote / word / punct events, in order."""
    out = []
    for m in TOK.finditer(html):
        b, ref, small, quote, word = m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
        if b is not None:
            txt = re.sub(r"<[^>]+>", "", b).strip()
            if txt:
                out.append(("bold", txt))
        elif ref is not None:
            out.append(("ref_en", ref))
        elif small is not None:
            out.append(("ref_he", small))
        elif quote is not None:
            out.append(("quote", quote.strip()))
        elif word is not None:
            parts = re.findall(r"[֐-׿\"״׳']+|[^֐-׿\"״׳']+", word)
            for p in parts:
                if re.match(r"[֐-׿]", p):
                    out.append(("word", p.strip("'")))
                else:
                    out.append(("punct", p))
    return out


def place_en(ref):
    m = re.match(r"(.+?) (\d+):(\d+)", ref)
    if m and m.group(1) in EN:
        return EN[m.group(1)], int(m.group(2)), int(m.group(3))
    return None


def place_he(ref, last_book):
    m = re.match(r"\s*(\S+)\s+(\S+),\s*(\S+)\s*$", ref.replace("‎", ""))
    if not m:
        return None
    bk = m.group(1)
    code = last_book if bk == "שם" else HE.get(bk)
    c, v = hnum(m.group(2)), hnum(m.group(3))
    if code and c and v:
        return code, c, v
    return None


def take_y(ev, i):
    """words after the cue at ev[i], up to a terminator; a quote right after the cue is skipped."""
    y, j = [], i + 1
    if j < len(ev) and ev[j][0] == "quote":
        j += 1
    if j < len(ev) and ev[j][0] == "word" and ev[j][1] == "לומר":
        j += 1
    while j < len(ev) and len(y) < 6:
        k, v = ev[j]
        if k != "word" or v in STOPS:
            if k == "punct" and v.strip() in ("", "-", "\"", "״"):
                j += 1
                continue
            break
        y.append(v)
        j += 1
    return y


def statements_glosses(src, fname):
    """Metzudat Zion, Malbim: one gloss per verse entry; X = the bold headword; place = the verse."""
    out = []
    for line in open(DATA / fname, encoding="utf-8"):
        d = json.loads(line)
        for vi, vs in enumerate(d["verses"]):
            for gi, g in enumerate(vs):
                ev = events(g)
                base = {"source": src, "book": d["book"], "chapter": d["chapter"], "verse": vi + 1, "entry": gi + 1}
                if not ev or ev[0][0] != "bold":
                    out.append({**base, "state": "no_headword"})
                    continue
                head = consonants(ev[0][1].rstrip(".:"))
                rest = [e for e in ev[1:] if e[0] != "punct" or e[1].strip() not in ("", ".")]
                first = next((k for k, e in enumerate(ev[1:], 1) if e[0] == "word"), None)
                cue = ev[first][1] if first else ""
                kind = CUES[src].get(cue)
                row = {**base, "x_text": head, "cue": cue}
                if not rest or kind is None:
                    out.append({**row, "state": "no_cue"})
                    continue
                y = take_y(ev, first) if kind not in ("class", "literal") else []
                if kind == "class" and first + 1 < len(ev) and ev[first + 1][0] == "word":
                    y = [ev[first + 1][1]]
                row.update(kind=kind, y_text=y)
                row["state"] = "phrase" if " " in head or "," in ev[0][1] else "statement"
                out.append(row)
    return out


def statements_entries(src, texts):
    """Sefer HaShorashim, Mahberet Menahem: X = the last bold word before the cue that has a place."""
    out = []
    for ei, html in texts:
        ev = events(html)
        last_bold, last_book = None, None
        for i, (k, v) in enumerate(ev):
            if k == "bold":
                last_bold = {"x_text": consonants(v), "place": None}
            elif k in ("ref_en", "ref_he"):
                pl = place_en(v) if k == "ref_en" else place_he(v, last_book)
                if pl:
                    last_book = pl[0]
                if last_bold is not None and last_bold["place"] is None:
                    last_bold["place"] = pl
            elif k == "word" and v in CUES[src]:
                kind = CUES[src][v]
                base = {"source": src, "entry": ei, "cue": v, "kind": kind}
                if last_bold is None or last_bold["place"] is None:
                    out.append({**base, "state": "no_placed_headword"})
                    continue
                y = take_y(ev, i) if kind != "literal" else []
                b, c, vv = last_bold["place"]
                st = "phrase" if " " in last_bold["x_text"] else "statement"
                if y and y[0] in FORMULA:
                    st = "formula"
                if kind != "literal" and not y:
                    st = "no_y"
                out.append({**base, "x_text": last_bold["x_text"], "book": b, "chapter": c, "verse": vv,
                            "y_text": y, "state": st})
    return out


def main():
    rows = statements_glosses("mz", "metzudat_zion_chapters.jsonl")
    rows += statements_glosses("malbim", "malbim_beur_hamilot_chapters.jsonl")
    radak = [(json.loads(l)["ref"], json.loads(l)["text"]) for l in open(DATA / "sefer_hashorashim_entries.jsonl",
                                                                          encoding="utf-8")]
    rows += statements_entries("radak", radak)
    men = []
    for l in open(DATA / "mahberet_menahem_letters.jsonl", encoding="utf-8"):
        d = json.loads(l)
        for k, e in enumerate(d["entries"]):
            men.append((f"{d['ref']}#{k + 1}", " ".join(e)))
    rows += statements_entries("menahem", men)

    lx = lexicon()
    for r in rows:
        if r.get("state") not in ("statement", "phrase"):
            continue
        words = r["x_text"].split()
        if not words:
            r["state"] = "no_headword"
            continue
        xs =[resolve_at(w, r["book"], r["chapter"], r["verse"]) for w in words]
        r["x"] = [a for a, _, _ in xs]
        r["x_how"] = [b for _, b, _ in xs]
        r["x_t"] = [c for _, _, c in xs]
        ys = [resolve_word(w) for w in r.get("y_text", [])]
        r["y"] = [a for a, _ in ys]
        r["y_how"] = [b for _, b in ys]
        r["y_content"] = [a for a in r["y"] if a and lx[a]["class"] in ("noun", "verb", "adj", "adv")
                          and lx[a]["state"] not in ("function",)]

    OUT.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    with open(SCRATCH / "explain-statements.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    counts = {}
    print("== statements per source (state)")
    for src in ("mz", "radak", "menahem", "malbim"):
        rs = [r for r in rows if r["source"] == src]
        st = Counter(r["state"] for r in rs)
        kinds = Counter(r["kind"] for r in rs if r["state"] == "statement")
        good = [r for r in rs if r["state"] == "statement"]
        xr = sum(1 for r in good if r["x"][0])
        xhow = Counter(r["x_how"][0] for r in good)
        expl = [r for r in good if r["kind"] not in ("class", "literal", "targum")]
        ytok = [h for r in expl for h in r["y_how"]]
        yres = sum(1 for r in expl if r["y_content"])
        both = sum(1 for r in expl if r["y_content"] and r["x"][0])
        c = {"rows": len(rs), "state": dict(st), "kinds": dict(kinds), "x_resolved": xr, "x_how": dict(xhow),
             "explaining": len(expl), "y_tokens": len(ytok), "y_token_how": dict(Counter(ytok)),
             "explaining_with_content_y": yres, "x_and_y": both,
             "x_lexemes": len({r["x"][0] for r in good if r["x"][0]}),
             "pairs_x_y": len({(r["x"][0], y) for r in expl if r["x"][0] for y in r["y_content"] if y != r["x"][0]})}
        counts[src] = c
        print(src, json.dumps(c, ensure_ascii=False))

    # coverage: a lexeme is explained when it is X of a resolved statement (any kind but class) of any source
    explained = defaultdict(set)
    for r in rows:
        if r.get("state") == "statement" and r["x"][0] and r["kind"] != "class":
            explained[r["x"][0]].add(r["source"])
    ever = {r["x"][0] for r in rows if r.get("state") == "statement" and r["x"][0]}
    print("== explained lexemes (kind not class):", len(explained), "; X of any statement:", len(ever))
    cov = {}
    for part in PARTS:
        toks = content_tokens(part)
        freq = Counter(l for _, _, l in toks)
        per = {}
        for bn in BAND_NAMES:
            lexs = [l for l, n in freq.items() if band(n) == bn]
            tk = sum(freq[l] for l in lexs)
            el = [l for l in lexs if l in explained]
            per[bn] = {"lexemes": len(lexs), "explained": len(el), "tokens": tk,
                       "tokens_explained": sum(freq[l] for l in el)}
        tot_l = len(freq)
        tot_e = sum(1 for l in freq if l in explained)
        tot_t = sum(freq.values())
        tot_te = sum(n for l, n in freq.items() if l in explained)
        per["all"] = {"lexemes": tot_l, "explained": tot_e, "tokens": tot_t, "tokens_explained": tot_te}
        cov[part] = per
        print(part, json.dumps(per, ensure_ascii=False))
    counts["coverage"] = cov

    # item 2: the derived defining vocabulary = content lexemes used in Y of explaining statements
    dv = Counter(y for r in rows if r.get("state") == "statement" and r["kind"] not in ("class", "literal", "targum")
                 for y in r["y_content"])
    dvs = {}
    for cut in (1, 2, 3, 5, 10):
        voc = {l for l, n in dv.items() if n >= cut}
        line = {"lexemes": len(voc)}
        for part in PARTS:
            freq = Counter(l for _, _, l in content_tokens(part))
            line[part] = round(sum(n for l, n in freq.items() if l in voc) / max(1, sum(freq.values())), 4)
            line[part + "_lexemes_in_part"] = sum(1 for l in freq if l in voc)
        dvs[f"used>={cut}"] = line
        print("defining vocabulary", cut, json.dumps(line))
    counts["defining_vocabulary"] = dvs
    counts["defining_vocabulary_top40"] = [(lx[l]["lemma"], l, n) for l, n in dv.most_common(40)]
    dump("explain-counts.json", counts)

    # sample: 20 per source, fixed rule: statements in file order, every k-th, k = len // 20
    md = ["# Explanation statements: 20 per source (fixed rule)", "",
          "Rule: the source's rows of state `statement`, in file order; take rows 0, k, 2k, ... with k = count // 20.",
          "Columns: place; X as written; cue; kind; Y as written; X's lexeme (how); Y's lexemes (how).", ""]
    for src in ("mz", "radak", "menahem", "malbim"):
        good = [r for r in rows if r["source"] == src and r["state"] == "statement"]
        k = max(1, len(good) // 20)
        md += [f"## {src} ({len(good)} statements)", "", "| place | X | cue | kind | Y | X lexeme | Y lexemes |",
               "|---|---|---|---|---|---|---|"]
        for r in good[::k][:20]:
            md.append(f"| {r['book']} {r['chapter']}:{r['verse']} | {r['x_text']} | {r['cue']} | {r['kind']} | "
                      f"{' '.join(r.get('y_text', []))} | {r['x'][0] or '—'} ({r['x_how'][0]}) | "
                      + " ".join(f"{a or '—'}({h})" for a, h in zip(r['y'], r['y_how'])) + " |")
        md.append("")
    (OUT / "explain-sample.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    main()
