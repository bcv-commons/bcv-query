"""Read the saved Overview pages of Psalms: Layer by Layer (Scriptura, CC BY 4.0; snapshot by fetch_scriptura.py).

    from macula import scriptura
    scriptura.read(n)        # -> {"psalm", "purpose", "sections": [(start, next)], "moods": [(start, next, [label, ...])],
                             #     "superscription": [verse], "url", "snapshot"} or None
    A verse is (number, part): (1, "b") is the second part of verse 1. `next` is where the next one starts (it ends just
    before), None for the psalm's end.

Only what passage facts store is returned in a usable form: the Purpose sentence (read by fixed rules into a type code, never
stored), the At-a-Glance section ranges (stored without their titles) and the mood labels of the At-a-Glance rows (stored as
codes). Verse numbers are the site's, which follow the Hebrew numbering (Ps 88:2-19), as MACULA does.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from pathlib import Path

CACHE = Path(__file__).resolve().parent / ".cache" / "scriptura"

# the stated purpose: the verbs of "To <verb> ..." (and of each "and to <verb>"), grouped; the group is the code (fm.pu.*)
PURPOSE = {
    "lament": ("lament",),
    "petition": ("ask", "petition", "plead", "pray", "invoke", "request", "cry", "intercede"),
    "praise": ("praise", "celebrate", "delight", "exalt", "extol", "worship", "glorify", "honor", "honour", "bless"),
    "thanks": ("thank", "give"),
    "confidence": ("express", "promise", "assure", "reassure"),
    "instruct": ("persuade", "instruct", "teach", "exhort", "rebuke", "warn", "call", "urge", "encourage", "remind", "challenge"),
}
EXPRESS = {"confidence": "confidence", "trust": "confidence", "praise": "praise", "thanks": "thanks", "gratitude": "thanks",
           "lament": "lament", "sorrow": "lament", "grief": "lament"}
MOOD = re.compile(r"^[a-z][a-z-]*(?: [a-z][a-z-]*)?$")      # a mood label: one or two plain words


def purpose_codes(text: str) -> list[str]:
    """The fm.pu.* groups of a Purpose sentence ("To petition ...", "To pray for help ... and to inspire hope"); [] if none fits."""
    out = []
    for m in re.finditer(r"(?:^|\band )to ([a-z]+)(?: (?:in|for|of|about|that|the|his|god|yhwh)\b)?\s*([a-z']+)?", text.lower()):
        verb, nxt = m.group(1), m.group(2) or ""
        if verb == "give" and not nxt.startswith("thank"):
            continue
        if verb == "express":
            code = next((c for w, c in EXPRESS.items() if w in text.lower()[m.start():m.start() + 60]), None)
        else:
            code = next((c for c, vs in PURPOSE.items() if verb in vs), None)
        if code and code not in out:
            out.append(code)
    return out


# the same mood written as an adjective: folded into the noun, so one code per mood
FOLD = {"confident": "confidence", "hopeful": "hope", "joyful": "joy", "distressed": "distress", "fearful": "fear",
        "anxious": "anxiety", "angry": "anger", "desperate": "desperation", "humiliated": "humiliation", "terrified": "terror",
        "ashamed": "shame", "reverent": "reverence", "passionate": "passion", "pensive": "pensiveness", "determined": "determination",
        "secure": "security", "calm": "calm", "grateful": "gratitude", "thankful": "gratitude", "sad": "sadness",
        "lonely": "loneliness", "amazed": "amazement", "astonishment": "amazement", "joyous": "joy", "solemn": "solemnity", "astonished": "amazement", "afraid": "fear", "peaceful": "peace", "trusting": "trust",
        "annoyed": "annoyance", "dependent": "dependence", "disappointed": "disappointment", "frustrated": "frustration",
        "helpless": "helplessness", "triumphant": "triumph"}


def mood_labels(labels: list[str]) -> list[str]:
    out = []
    for x in labels:
        x = re.sub(r"^(?:yet|still|but|and)\s+", "", x)
        x = FOLD.get(x, x)
        if MOOD.match(x) and x not in out:
            out.append(x)
    return out
RANGE = re.compile(r"\((?:vv?\.)\s*(\d+)\s*(?:[–-]\s*(\d+))?\)\s*$")


def snapshot() -> Path | None:
    """The newest snapshot folder."""
    dirs = sorted(p for p in CACHE.glob("20*") if p.is_dir()) if CACHE.exists() else []
    return dirs[-1] if dirs else None


class _Page(HTMLParser):
    """Headings (h2-h4) with the text that follows them, and the At-a-Glance table rows with their cells."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.heads: list[list[str]] = []          # [heading text, following text]
        self.rows: list[list[tuple[str, bool]]] = []   # cells: (text, holds an image: the section's icon)
        self._in_h = self._in_td = False
        self._cell: list[str] = []
        self._style = ""
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("h2", "h3", "h4"):
            self._in_h = True
            self.heads.append(["", ""])
        elif tag == "tr":
            self.rows.append([])
        elif tag == "td":
            self._in_td, self._cell, self._style = True, [], ""
            self._img = False
        elif tag == "img" and self._in_td:
            self._img = True
        elif tag == "br" and self._in_td:
            self._cell.append("|")
        elif tag == "span" and self._in_td and "background-color" in (a.get("style") or ""):
            self._cell.append("|")                      # each label of a mood cell is its own coloured span
        elif tag == "span" and "smwttcontent" in (a.get("class") or ""):
            self._skip += 1                       # tooltip copy of the verse text

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip -= 1
        elif tag in ("h2", "h3", "h4"):
            self._in_h = False
        elif tag == "td" and self._in_td:
            if self.rows:
                self.rows[-1].append((" ".join("".join(self._cell).split()), self._img))
            self._in_td = False
        elif tag == "span" and self._skip and not self._in_h:
            pass

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_h and self.heads:
            self.heads[-1][0] += data
        elif self._in_td:
            self._cell.append(data)
        elif self.heads:
            self.heads[-1][1] += data


def _close_skip(p: _Page, raw: str) -> str:
    # the tooltip spans nest one inner span each; strip them before parsing so the skip counter cannot drift
    return re.sub(r'<span class="smwttcontent">.*?</span>', "", raw, flags=re.S)


def glance_rows(folder: Path) -> dict[int, list[tuple[str, tuple[int, str], str]]]:
    """glance.tsv of a snapshot (macula/scriptura_glance.py: the At-a-Glance pictures read by OCR): psalm -> [(kind, verse,
    labels)]."""
    f = folder / "glance.tsv"
    out: dict[int, list] = {}
    if not f.exists():
        return out
    for line in f.read_text(encoding="utf-8").splitlines()[1:]:
        n, kind, v, labels, _ = line.split("\t")
        m = re.match(r"(\d+)([a-z]*)$", v)
        out.setdefault(int(n), []).append((kind, (int(m.group(1)), m.group(2)), labels))
    return out


def read(n: int, folder: Path | None = None, pictures: bool = True) -> dict | None:
    """With `pictures`, a page whose At-a-Glance is a picture (no sections or moods in its HTML) takes them from glance.tsv;
    the result then says "read_from": "picture"."""
    folder = folder or snapshot()
    f = folder / f"psalm_{n:03d}.html" if folder else None
    if not f or not f.exists():
        return None
    raw = f.read_text(encoding="utf-8")
    p = _Page()
    p.feed(_close_skip(p, raw))
    heads = [(" ".join(html.unescape(h).split()), " ".join(t.split())) for h, t in p.heads]
    purpose = next((t for h, t in heads if h.startswith("Purpose")), "")
    headed = []
    for h, _ in heads:
        m = RANGE.search(h)
        if m and "At-a-Glance" not in h:
            a = int(m.group(1))
            headed.append((a, int(m.group(2) or a)))
    starts, last, sec, superscription = [], (0, ""), [], []
    for row in p.rows:
        if not row:
            continue
        m = re.match(r"v\.\s*(\d+)([a-z]?)", row[0][0])
        if not m:
            continue
        v = (int(m.group(1)), m.group(2))
        last = max(last, v)
        cells = [c for c, _ in row]
        if len(cells) > 1 and cells[1] == "Superscription":
            superscription.append(v)
            continue
        icon = next((k for k, (_, img) in enumerate(row) if img), None)
        if icon is not None:
            # verse | [title] | summary | icon | mood: a title before the summary starts a section; the mood follows the icon
            first = cells[1].strip("| ") if len(cells) > 1 else ""
            titled = first and len(first.split()) <= 5 and not re.search(r"[.!?;]$", first)
            if (icon - 2 >= 1 and cells[icon - 2].strip("| ")) or (icon > 1 and titled):
                sec.append(v)
            mood = cells[icon + 1] if icon + 1 < len(cells) else ""
            labels = [x.strip().lower() for x in re.split(r"\s*[&|,/()]\s*|\s+(?:and|amidst|amid)\s+|\s*\.\.\.\s*", mood) if x.strip()]
            if labels:
                starts.append((v, labels))
        else:
            first = cells[1].strip("| ") if len(cells) > 1 else ""
            if len(cells) >= 3 and first and len(first.split()) <= 5 and not re.search(r"[.!?;]$", first):
                sec.append(v)                           # a page without icons: a short title cell starts a section
    def ends(xs):
        return [(v, xs[k + 1] if k + 1 < len(xs) else None) for k, v in enumerate(xs)]   # (start, next start or None = to the end)
    read_from = "page"
    rows = glance_rows(folder).get(n) if pictures and not sec and not starts else None
    if rows:
        read_from = "picture"
        superscription = [v for kind, v, _ in rows if kind == "superscription"]
        sec = [v for kind, v, _ in rows if kind == "section"]
        starts = [(v, [x.strip().lower() for x in re.split(r"\s*[&|,/()]\s*|\s+(?:and|amidst|amid)\s+|\s*\.\.\.\s*", lab) if x.strip()])
                  for kind, v, lab in rows if kind == "mood"]
    moods = [(a, b, starts[k][1]) for k, (a, b) in enumerate(ends([v for v, _ in starts]))]
    sections = ends(sec)
    return {"psalm": n, "purpose": purpose, "sections": sections, "moods": moods, "superscription": superscription,
            "headed_sections": headed, "read_from": read_from,
            "url": f"https://psalms.scriptura.org/w/Psalm_{n}/Overview", "snapshot": folder.name}


# book abbreviations as the site writes them -> USFM code
BOOKS = {
    "gen": "GEN", "genesis": "GEN", "exod": "EXO", "ex": "EXO", "exodus": "EXO", "lev": "LEV", "num": "NUM", "deut": "DEU", "dt": "DEU",
    "josh": "JOS", "judg": "JDG", "ruth": "RUT", "1sam": "1SA", "2sam": "2SA", "1kgs": "1KI", "2kgs": "2KI", "1kings": "1KI",
    "2kings": "2KI", "1chr": "1CH", "2chr": "2CH", "ezra": "EZR", "neh": "NEH", "esth": "EST", "job": "JOB", "ps": "PSA",
    "pss": "PSA", "psalm": "PSA", "psalms": "PSA", "prov": "PRO", "pro": "PRO", "eccl": "ECC", "qoh": "ECC", "song": "SNG", "isa": "ISA",
    "jer": "JER", "lam": "LAM", "ezek": "EZK", "dan": "DAN", "hos": "HOS", "joel": "JOL", "am": "AMO", "amos": "AMO", "obad": "OBA",
    "jonah": "JON", "jon": "JON", "mic": "MIC", "nah": "NAM", "hab": "HAB", "zeph": "ZEP", "hag": "HAG", "zech": "ZEC", "mal": "MAL",
    "matt": "MAT", "mt": "MAT", "mark": "MRK", "luke": "LUK", "john": "JHN", "acts": "ACT", "rom": "ROM", "1cor": "1CO", "2cor": "2CO",
    "gal": "GAL", "eph": "EPH", "phil": "PHP", "col": "COL", "1thess": "1TH", "2thess": "2TH", "1tim": "1TI", "2tim": "2TI",
    "heb": "HEB", "jas": "JAS", "1pet": "1PE", "2pet": "2PE", "1john": "1JN", "rev": "REV",
}
_BOOK = r"(?<![A-Za-z])((?:[123]\s?)?[A-Z][a-z]{1,7})\.?\s+(?=\d)"


def references(text: str) -> list[tuple[str, int, int, int]]:
    """Bible references in a text, as (book, chapter, first verse, last verse). A reference without a book takes the last one named
    ("Ps 30:4, 49:16"); a chapter without a verse is left out. Verses are the site's: Tanakh in the Hebrew numbering."""
    out, book = [], None
    pos = 0
    tokens = re.finditer(_BOOK + r"|(\d+)\s*:\s*(\d+)(?:\s*[-–]\s*(\d+))?|[;,]\s*(\d+)(?:\s*[-–]\s*(\d+))?(?![\d:A-Za-z])(?!\s*:)|([.!?)\]])", text)
    chapter = None
    for m in tokens:
        if m.group(1):
            book = BOOKS.get(re.sub(r"\s", "", m.group(1)).lower())
            chapter = None
        elif m.group(2) and book:
            chapter = int(m.group(2))
            a = int(m.group(3))
            out.append((book, chapter, a, int(m.group(4) or a)))
        elif m.group(5) and book and chapter:                   # ", 39" after Matt 27:35: another verse of the same chapter
            a = int(m.group(5))
            out.append((book, chapter, a, int(m.group(6) or a)))
        elif m.group(7):
            if m.group(7) in ".!?":
                chapter = None
    return out


def background(n: int, folder: Path | None = None) -> dict:
    """The Background Orientation of a psalm: the passages it cites and the Hebrew words it explains."""
    folder = folder or snapshot()
    f = folder / f"psalm_{n:03d}.html" if folder else None
    if not f or not f.exists():
        return {"refs": [], "hebrew": []}
    p = _Page()
    p.feed(_close_skip(p, f.read_text(encoding="utf-8")))
    text = " ".join(" ".join(t.split()) for h, t in p.heads if " ".join(html.unescape(h).split()).startswith("Background Orientation"))
    refs = [r for r in references(text) if not (r[0] == "PSA" and r[1] == n)]
    hebrew = list(dict.fromkeys(re.findall(r"[\u05d0-\u05ea][\u0591-\u05c7\u05d0-\u05ea]*", text)))
    return {"refs": list(dict.fromkeys(refs)), "hebrew": hebrew}


CODES = Path(__file__).resolve().parents[2] / "resources" / "passage_facts" / "codes.tsv"


def update_mood_codes(path: Path = CODES) -> list[str]:
    """Rewrite the md.* rows of codes.tsv from the mood families (resources/passage_facts/mood_families.tsv), from v0.3.1. Run
    after changing that table:  python -m macula.scriptura --update-mood-codes"""
    from macula import mood_families
    rows = [l for l in path.read_text(encoding="utf-8").splitlines(keepends=True) if not l.startswith("md.")]
    for fid, r in mood_families.FAMILIES.items():
        rows.append(f"{fid}\tmood\t{r['note']}\tubs, macula, scriptura, glyssen\ta feeling the Hebrew or Greek text marks, named by "
                    f"its head word {r['head_hbo']} / {r['head_grc']}; the family's words are SDBH {', '.join(r['sdbh'].split('|')) or '-'}"
                    f", Louw-Nida {', '.join(r['ln'].split('|'))} and the lemmas in mood_families.tsv; `head` the head word in the "
                    f"fact's language, `marked_by` the words that mark it, `marks` why (domain, Strong's number, lemma or cue)\n")
    path.write_text("".join(rows), encoding="utf-8")
    return list(mood_families.FAMILIES)


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--update-mood-codes"]:
        print(len(update_mood_codes()), "mood codes")
