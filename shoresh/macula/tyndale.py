"""Psalm types from the Tyndale Open Study Notes (Tyndale House Publishers, 2022, CC BY-SA 4.0), read by fixed keyword rules.

    from macula import tyndale
    tyndale.psalm_types()   # -> [{"psalm", "code", "ranges": [(a, b)] English verses or [], "note", "eng_last"}]

Input: the unmodified ZIP from tyndaleopenresources.com, saved in macula/.cache/tyndale/<date>/ (sha256 recorded in SOURCE).
Each psalm's introduction is the StudyNotes.xml item that covers the whole psalm and no other (`Ps.N.1-M`); group notes
(`Ps.1.1-8.9`) are not read. A type is taken only where the note names it in its first three sentences, in the wording below;
nothing is inferred from a description of content. Where a type phrase is followed (within two words) by a verse range of this
psalm, and its sentence lays out the psalm in two or more ranged parts, "the lament ( 22:1-21 ) and praise for redemption
( 22:22-31 )", the type gets that range; a single cited verse ("this morning prayer ( 5:3 )") does not make a range. Only the code and the note's name leave this module, never the note's English.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

CACHE = Path(__file__).resolve().parent / ".cache" / "tyndale"
SOURCE = {"file": "tyndale_open-studynotes.zip", "url": "https://tyndaleopenresources.com/wp-content/themes/tyndale-openresources/files/tyndale_open-studynotes.zip",
          "sha256": "7b4d5ae088449d5a6925170c4b89b978acee2f78f73dc6b8a278fa948a7e8498"}

# code -> patterns (lower case, on the note's plain text). Order matters only for display. The codes are Hebrew terms (from
# passage-facts v0.3.3; were lament, praise …); the English patterns only select them and are never stored.
HEAD = {'qinah': 'קִינָה', 'qinat_tsibbur': 'קִינַת צִבּוּר', 'tehillah': 'תְּהִלָּה', 'todah': 'תּוֹדָה', 'mivtach': 'מִבְטָח', 'chokhmah': 'חָכְמָה', 'melekh': 'מֶלֶךְ', 'viduy': 'וִדּוּי', 'tsiyyon': 'צִיּוֹן', 'malkhut': 'מַלְכוּת', 'tefillah': 'תְּפִלָּה', 'qelalah': 'קְלָלָה', 'aliyah': 'עֲלִיָּה לָרֶגֶל'}
RULES = {
    "qinat_tsibbur": [r"\b(?:community|communal|national) lament\b", r"\bcommunal and individual expressions of lament\b"],
    "qinah": [r"\b(?:this|a|an|individual|untitled) (?:individual )?lament\b", r"\bthe lament(?= \()", r"\bpsalm of lament\b", r"\bin lament\b",
               r"\bthe psalmist laments\b", r"\bexpressions of lament\b", r"\bin this (?:individual )?lament\b",
               r"\belements of [^.]*\blament\b", r"\bpsalm is a lament\b"],
    "tehillah": [r"\bhymn of praise\b", r"\bpsalm of praise\b", r"\b(?:this|the|a|nature|creation|concluding) hymn\b(?! of thanksgiving)",
               r"\bhymn of creation\b", r"\bhymns? (?:\( [^)]*\) )?that praise\b", r"\belements of [^.]*\bpraise\b", r"\) and praise for\b"],
    "todah": [r"\bthanksgiving (?:psalm|song|hymn)\b", r"\bhymn of thanksgiving\b", r"\bpsalm of [^.]*\bthanksgiving\b",
                     r"\belements of [^.]*\bthanksgiving\b"],
    "mivtach": [r"\bpsalm of (?:trust|confidence)\b", r"\bpsalm of trust and confidence\b"],
    "chokhmah": [r"\bwisdom psalm\b", r"\belements of wisdom\b", r"\bthemes of wisdom\b"],
    "melekh": [r"\broyal (?:psalm|prayers?|drama|wedding)\b"],
    "viduy": [r"\bpsalms? of penitence\b", r"\bpsalm of confession\b", r"\belements of [^.]*\bconfession\b"],
    "tsiyyon": [r"\b(?:psalm|song) of zion\b"],
    "malkhut": [r"\bcelebrates (?:god’s|the lord’s) kingship\b", r"\bestablishes the lord’s universal kingship\b"],
    "tefillah": [r"\b(?:this|morning|anonymous) prayer\b", r"\bprayer for (?:rescue|god’s|healing)\b"],
    "qelalah": [r"\bimprecation\b"],
    "aliyah": [r"\bpilgrims’ songs\b", r"\bon a pilgrimage\b"],
}
RANGE = r"\s*(?:[a-z’]+\s+){0,2}?\(\s*{n}:(\d+)(?:-(\d+))?((?:\s*,\s*\d+(?:-\d+)?)*)\s*\)"


def _zip() -> Path:
    for d in sorted(CACHE.glob("20*"), reverse=True):
        z = d / SOURCE["file"]
        if z.exists():
            return z
    raise FileNotFoundError(f"Tyndale Open Study Notes ZIP not found under {CACHE} (download: {SOURCE['url']})")


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def intros() -> dict[int, tuple[str, int, str]]:
    """psalm -> (note name, last English verse, plain text) for the note that covers the whole psalm and no other."""
    with zipfile.ZipFile(_zip()) as z:
        xml = z.read("Tyndale Open Study Notes/StudyNotes.xml").decode("utf-8")
    best: dict[int, tuple[str, int, str]] = {}
    for name, n, last, body in re.findall(r'<item name="(Ps\.(\d+)\.1-(\d+))"[^>]*>(.*?)</item>', xml, re.S):
        n, last = int(n), int(last)
        if n not in best or last > best[n][1]:
            best[n] = (name, last, _plain(body))
    return best


def _sentences(text: str, n: int, k: int = 3) -> str:
    text = re.sub(r"^(?:Ps\.\S+\s+)*(?:Ps|Pss) %d(?:[–-]\d+)?\s+" % n, "", text)
    return " ".join(re.split(r"(?<=[.!?])\s+", text)[:k])


def psalm_types() -> list[dict]:
    out = []
    for n, (name, last, text) in sorted(intros().items()):
        if n == 43 and last < 5:
            continue                                     # 43:1-4 is a verse note, not an introduction (Pss 42-43 share one)
        head = _sentences(text, n).lower()
        for code, pats in RULES.items():
            hits = sorted((m.start(), m.end()) for pat in pats for m in re.finditer(pat, head))
            if not hits:
                continue
            s, e = hits[0]
            ranges = []
            r = re.match(RANGE.replace("{n}", str(n)), head[e:])
            sentence = next(x for x in re.split(r"(?<=[.!?])\s+(?=[a-z])", head) if head.find(x) <= s < head.find(x) + len(x) + 1) \
                if re.search(r"(?<=[.!?])\s+", head) else head
            if r and len(re.findall(r"\(\s*%d:" % n, sentence)) >= 2:   # a range counts where the sentence lays out a structure
                ranges = [(int(r.group(1)), int(r.group(2) or r.group(1)))]
                for piece in re.findall(r"(\d+)(?:-(\d+))?", r.group(3) or ""):
                    ranges.append((int(piece[0]), int(piece[1] or piece[0])))
            out.append({"psalm": n, "code": code, "ranges": ranges, "note": name, "eng_last": last})
    return out
