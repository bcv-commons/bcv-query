"""Rule W1 (SPEC-levels 4.2): explanation statements of the four Hebrew lexicographers, read by stage 40's fixed rule,
one row per place the rule reads, with the witness (the Hebrew text from the headword to the end of Y, tags off, NFC).

The record's text (for `offset`): a record is one line of the pinned file. Its text is, tags taken off:
  mz, mb: every gloss of the chapter in verse order, each followed by one newline;
  mn: every entry of the letter (its strings joined by one space), each followed by one newline;
  rd: the entry's `text`.
"""
import json
import re
import unicodedata

from levels_common import DATA, SOURCE_FILES, consonants, is_content_lexeme, resolve_x, resolve_y

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
NUMV = dict(zip("אבגדהוזחטיכלמנסעפצקרשת", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100,
                                          200, 300, 400]))
NUMV.update({"ך": 20, "ם": 40, "ן": 50, "ף": 80, "ץ": 90})

MEANING = {"ענין", "ענינו", "עניינו", "הוא", "היא", "הם", "ר״ל", 'ר"ל', "כעין", "פירוש", "פירושו", "ופירוש",
           "ופירושו", "כלומר", "פתרון", "פתרונו", "ופתרון"}
CUES = {
    "mz": {**{c: "meaning" for c in MEANING}, "כמו": "likeness", "מלשון": "derivation", "מל׳": "derivation",
           "מל'": "derivation", "תרגומו": "targum", "תרגם": "targum", "ת״י": "targum", "תרגום": "targum",
           "שם": "class", "מין": "class", "מקום": "class", "כלי": "class"},
    "mb": {**{c: "meaning" for c in MEANING}, "כמו": "likeness", "מענין": "derivation", "מלשון": "derivation",
           "שם": "class", "מקום": "class"},
    "rd": {c: "meaning" for c in ("פירוש", "פירושו", "ופירוש", "ופירושו", "פירושם", "כלומר", "ענין", "ענינו")},
    "mn": {**{c: "meaning" for c in ("ענין", "פתרון", "פתרונו", "ופתרון", "לשון")},
           "כמשמעו": "literal", "מגזרת": "derivation"},
}
STOPS = {"וכן", "כמו", "והוא", "ר״ל", 'ר"ל', "או", "כי", "אבל", "וזה", "רוצה", "וכמוהו", "ובדברי", "וכלם",
         "והם", "שהוא", "על", "אשר"}
FORMULA = {"אחד", "כפי", "לפי", "פתרו", "ויסודתם"}
TOK = re.compile(r"<(b|strong)>(.*?)</\1>|<a [^>]*data-ref=\"([^\"]+)\"[^>]*>.*?</a>|<small>\((.*?)\)</small>|"
                 r"<[^>]+>|(\s'[^'<]{1,60}')|([^<\s]+)", re.S)
TAG = re.compile(r"<[^>]+>")
WORDPART = re.compile(r"[֐-׿\"״׳']+|[^֐-׿\"״׳']+")
EXPLAINING = ("meaning", "likeness", "derivation")


def strip_map(html):
    """(text without tags, pos) where pos[i] is the index in the text of html position i."""
    inside = bytearray(len(html))
    for m in TAG.finditer(html):
        inside[m.start():m.end()] = b"\x01" * (m.end() - m.start())
    pos, n, out = [0] * (len(html) + 1), 0, []
    for i, ch in enumerate(html):
        pos[i] = n
        if not inside[i]:
            out.append(ch)
            n += 1
    pos[len(html)] = n
    return "".join(out), pos


def events(html, pos):
    """(kind, value, start, end) in order; start/end are offsets in the tag-free text."""
    out = []
    for m in TOK.finditer(html):
        b, ref, small, quote, word = m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
        if b is not None:
            txt = TAG.sub("", b).strip()
            if txt:
                out.append(("bold", txt, pos[m.start()], pos[m.end()]))
        elif ref is not None:
            out.append(("ref_en", ref, pos[m.start()], pos[m.end()]))
        elif small is not None:
            out.append(("ref_he", small, pos[m.start()], pos[m.end()]))
        elif quote is not None:
            out.append(("quote", quote.strip(), pos[m.start(5)], pos[m.end(5)]))
        elif word is not None:
            base = m.start(6)
            for p in WORDPART.finditer(word):
                s = p.group(0)
                if re.match(r"[֐-׿]", s):
                    v = s.strip("'")
                    lead = len(s) - len(s.lstrip("'"))
                    a = base + p.start() + lead
                    out.append(("word", v, pos[a], pos[a + len(v)]))
                else:
                    out.append(("punct", s, pos[base + p.start()], pos[base + p.end()]))
    return out


def hnum(s):
    s = re.sub(r"[\"'״׳‎\s]", "", s)
    if not s or any(c not in NUMV for c in s):
        return None
    return sum(NUMV[c] for c in s)


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
    """Y after the cue at ev[i]: a quote right after the cue and לומר skipped; at most six words; stops."""
    y, j = [], i + 1
    if j < len(ev) and ev[j][0] == "quote":
        j += 1
    if j < len(ev) and ev[j][0] == "word" and ev[j][1] == "לומר":
        j += 1
    while j < len(ev) and len(y) < 6:
        k, v = ev[j][0], ev[j][1]
        if k != "word" or v in STOPS:
            if k == "punct" and v.strip() in ("", "-", "\"", "״"):
                j += 1
                continue
            break
        y.append(ev[j])
        j += 1
    return y


def head_text(s):
    return unicodedata.normalize("NFC", s.strip().rstrip(".:").strip())


def is_phrase(raw):
    return " " in consonants(raw) or "," in raw


def glosses(src, path):
    """mz, mb: one gloss per verse entry; X the bold headword (first event); P the verse."""
    rows = []
    for line_no, line in enumerate(open(path, encoding="utf-8")):
        if not line.strip():
            continue
        d = json.loads(line)
        base_off = 0
        for vi, vs in enumerate(d["verses"]):
            for g in vs:
                text, pos = strip_map(g)
                ev = events(g, pos)
                place = (d["book"], int(d["chapter"]), vi + 1)
                r = {"source": src, "line": line_no, "place": place, "text": text, "base": base_off}
                base_off += len(text) + 1
                if not ev or ev[0][0] != "bold":
                    rows.append({**r, "offset": 0, "x": None, "cue": None, "kind": "", "y": [], "end": 0})
                    continue
                x = ev[0]
                rest = [e for e in ev[1:] if e[0] != "punct" or e[1].strip() not in ("", ".")]
                first = next((k for k, e in enumerate(ev[1:], 1) if e[0] == "word"), None)
                cue_ev = ev[first] if first else None
                kind = CUES[src].get(cue_ev[1]) if cue_ev else None
                if not rest or kind is None:
                    rows.append({**r, "offset": x[2], "x": x, "cue": None, "kind": "", "y": [], "end": x[3]})
                    continue
                if kind in ("class", "literal"):
                    y = [ev[first + 1]] if (kind == "class" and first + 1 < len(ev) and ev[first + 1][0] == "word") else []
                else:
                    y = take_y(ev, first)
                k2 = "phrase" if is_phrase(x[1]) else kind
                rows.append({**r, "offset": cue_ev[2], "x": x, "cue": cue_ev, "kind": k2, "y": y,
                             "end": y[-1][3] if y else cue_ev[3]})
    return rows


def entries(src, path):
    """rd, mn: every cue word is a statement; X the last bold before it that has a place (its next citation)."""
    rows = []
    for line_no, line in enumerate(open(path, encoding="utf-8")):
        if not line.strip():
            continue
        d = json.loads(line)
        htmls = [d["text"]] if src == "rd" else [" ".join(e) for e in d["entries"]]
        base_off = 0
        for html in htmls:
            text, pos = strip_map(html)
            ev = events(html, pos)
            base = {"source": src, "line": line_no, "text": text, "base": base_off}
            base_off += len(text) + 1
            last_bold, last_place, last_book = None, None, None
            for i, e in enumerate(ev):
                k, v = e[0], e[1]
                if k == "bold":
                    last_bold, last_place = e, None
                elif k in ("ref_en", "ref_he"):
                    pl = place_en(v) if k == "ref_en" else place_he(v, last_book)
                    if pl:
                        last_book = pl[0]
                    if last_bold is not None and last_place is None:
                        last_place = pl
                elif k == "word" and v in CUES[src]:
                    kind = CUES[src][v]
                    y = take_y(ev, i) if kind != "literal" else []
                    if y and y[0][1] in FORMULA:
                        kind = "formula"
                    elif last_bold is not None and " " in consonants(last_bold[1]):
                        kind = "phrase"
                    rows.append({**base, "offset": e[2], "x": last_bold, "cue": e, "kind": kind, "y": y,
                                 "place": last_place if last_bold is not None else None,
                                 "end": y[-1][3] if y else e[3]})
    return rows


def build():
    """-> list of explanation rows (dicts with the columns of explanations.parquet), sorted, keyed."""
    raw = []
    for src in ("mz", "mb"):
        raw += glosses(src, DATA / SOURCE_FILES[src])
    for src in ("rd", "mn"):
        raw += entries(src, DATA / SOURCE_FILES[src])
    raw.sort(key=lambda r: (r["source"], r["line"], r["base"] + r["offset"]))
    out = []
    for n, r in enumerate(raw, 1):
        text, base = r["text"], r["base"]
        x = r["x"]
        start = x[2] if x else r["offset"]
        witness = unicodedata.normalize("NFC", text[start:r["end"]].strip()) if x else ""
        x_text = head_text(x[1]) if x else ""
        place = r["place"]
        if place is None:
            x_key, x_lex, x_state = "", "", "no_place"
        else:
            x_key = f"{place[0]} {place[1]}:{place[2]}"
            x_lex, x_state = resolve_x(x_text, *place)
        ys = []
        for e in r["y"]:
            lx, rule = resolve_y(e[1])
            ys.append({"lexeme": lx, "rule": rule, "text": unicodedata.normalize("NFC", e[1])})
        yc = []
        for w in ys:
            if w["lexeme"] and is_content_lexeme(w["lexeme"]) and w["lexeme"] not in yc:
                yc.append(w["lexeme"])
        one = len(yc) == 1 and not any(w["rule"] in ("ambiguous", "none") for w in ys)
        out.append({
            "expl": f"expl:{n}", "source": r["source"], "line": r["line"], "offset": base + r["offset"],
            "witness": witness, "kind": r["kind"],
            "cue": unicodedata.normalize("NFC", r["cue"][1]) if r["cue"] else "",
            "x_text": x_text, "x_key": x_key, "x_lexeme": x_lex, "x_state": x_state,
            "y_text": " ".join(w["text"] for w in ys), "y_words": ys, "y_content": yc, "one_word": one,
        })
    return out


def explaining(rows):
    """The explaining statements: kind meaning/likeness/derivation, X resolved."""
    return [r for r in rows if r["kind"] in EXPLAINING and r["x_state"] == "resolved"]
