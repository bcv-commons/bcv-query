"""Read the At-a-Glance pictures of Psalms: Layer by Layer (Scriptura, CC BY 4.0) into a small table, for the pages whose
At-a-Glance is a picture, not an HTML table (fetch_scriptura.py --images saves them as psalm_NNN_glance.jpg; the three pages
drawn as inline SVG are rendered to the same kind of picture with rsvg-convert).

    python3 -m macula.scriptura_glance [--folder SNAPSHOT] [--psalms 5,7]   # writes SNAPSHOT/glance.tsv

Needs Pillow, numpy and the tesseract and rsvg-convert programs. It runs once per snapshot; the passage-facts build only reads
glance.tsv (scriptura.read), so the build itself needs none of them.

How a picture is read (the layout is the same on every page):
- the verse badges ("v. 12") are the boxes of the left-hand column, found by pixels; they run down the verses one by one, so
  they are numbered by count against the psalm's verses in MACULA (a picture whose count does not fit is left out);
- the sections are the boxes of the title column, found by scanning down one pixel column; a box as wide as the page at the top
  is the superscription; a section holds the verses whose badge centre lies inside it;
- the moods are the magenta-framed boxes on the right; each starts at the first verse of the summary row its top edge lies in
  (or at the badge nearest its centre when two share a row), and its labels are the box's words.
glance.tsv rows: psalm, kind (superscription | section | mood), verse (number plus an optional part letter), labels (mood words
split by "|"), image sha256. Only verse numbers and mood words are kept, as passage facts store them; the titles are not.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

WHITE = 246            # a pixel is background when all channels are at least this


def _runs(mask: np.ndarray, merge: int = 10, least: int = 12) -> list[tuple[int, int]]:
    """[start, end) runs of True, joining runs closer than `merge` and dropping runs shorter than `least`."""
    out: list[list[int]] = []
    ys = np.flatnonzero(np.diff(np.concatenate([[0], mask.astype(int), [0]])))
    for a, b in zip(ys[::2], ys[1::2]):
        if out and a - out[-1][1] < merge:
            out[-1][1] = b
        else:
            out.append([a, b])
    return [(a, b) for a, b in out if b - a >= least]


def _ocr(img: Image.Image, psm: int, chars: str = "") -> str:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.png"
        img.save(p)
        extra = ["-c", f"tessedit_char_whitelist={chars}"] if chars else []
        r = subprocess.run(["tesseract", str(p), "-", "--psm", str(psm), *extra], capture_output=True, text=True,
                           env={"OMP_THREAD_LIMIT": "1", "PATH": "/usr/bin:/bin"})
    return "\n".join(" ".join(l.split()) for l in r.stdout.splitlines() if l.strip())


def _crop(im: Image.Image, box, scale: int = 2) -> Image.Image:
    c = im.crop(box)
    return c.resize((c.width * scale, c.height * scale), Image.LANCZOS)




def read_picture(path: Path, lasts: list[tuple[int, int]]) -> dict:
    """lasts: [(psalm, its last verse)], one psalm, or two when one picture shows both (Ps 9-10). Verses are (psalm, verse,
    part)."""
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(int)
    H, W, _ = a.shape
    ink = a.min(axis=2) < WHITE

    # 1. badges: the left column; its boxes start at the left edge
    def spans_page(x):
        ys = np.flatnonzero(ink[:, x])
        return ys.size > H * 0.2 and ys[0] < H * 0.15 and ys[-1] > H * 0.8
    xb = next((x for x in range(W // 4) if spans_page(x)), None)          # the badges' left border (not a side title)
    if xb is None:
        return {"error": "no column of verse badges"}
    right = xb + next(d for d in range(5, W // 5) if ink[:, xb + d].sum() < H * 0.02 and ink[:, xb + d + 3].sum() < H * 0.02)
    mid = (xb + right) // 2
    found = _runs(ink[:, xb + 12:right - 12].mean(axis=1) > 0.5, merge=1, least=15)
    badges = []
    for y0, y1 in found:
        crop = _ink_only(im, (xb + 8, y0 + 6, right - 8, y1 - 6))
        t = _ocr(crop, 6, "vV.0123456789abcdsS-:")
        if not re.search(r"\d", t) and "hallel" in _ocr(crop, 6).lower():
            continue                                     # a "hallelujah" badge (Ps 150) is not a verse
        badges.append({"y": (y0 + y1) / 2, "text": t})
    if lasts == [(119, 176)] and len(badges) == 22:      # Ps 119: one badge per stanza of eight verses
        for k, b in enumerate(badges):
            b["v"] = (119, 8 * k + 1, "")
        nums = None
    else:
        nums = _numbers([b["text"] for b in badges], lasts)
    if isinstance(nums, str):
        return {"error": nums, "badges": badges}
    for b, v in zip(badges, nums or []):
        b["v"] = v

    # 2. the title column: the first column of boxes right of the badges; it ends at the least inked column before the summaries
    prof = ink.mean(axis=0)
    xs = right + next(d for d in range(10, W // 2) if prof[right + d] > 0.3)
    xg = xs + 100 + int(np.argmin(prof[xs + 100:xs + int(W * 0.4)]))
    xe = xg + next(d for d in range(1, W // 4) if prof[xg + d] > prof[xg] + 0.2)          # where the summaries begin

    def band(x0, x1):
        return _runs(ink[:, x0:x1].mean(axis=1) > 0.3, merge=3, least=20)

    boxes = band(xs + 15, xg - 15)
    rows = band(xe + 15, xe + 300)

    def wide(b):                                   # a box that also fills the gap between the title and summary columns
        y = (b[0] + b[1]) // 2
        return ink[y - 2:y + 3, xg - 3:xe + 3].mean() > 0.9

    out = {"superscription": [], "sections": [], "moods": [], "badges": badges}
    for k, b in enumerate(boxes):
        vs = [x["v"] for x in badges if b[0] <= x["y"] < b[1] and x["v"]]
        if not vs:
            continue
        if k == 0 and (wide(b) or [v[1:] for v in vs] == [(1, "ss")]):
            out["superscription"] += vs
        else:
            out["sections"].append(vs[0])
    supers = set(out["superscription"])

    # 4. moods: magenta frames right of the summary column
    mg = (a[:, :, 0] > 150) & (a[:, :, 1] < 110) & (a[:, :, 2] > 60) & (a[:, :, 0] - a[:, :, 1] > 90)
    cols = mg[:, xe + 300:].sum(axis=0)
    if cols.max() > 40:
        strong = np.flatnonzero(cols > cols.max() * 0.25) + xe + 300
        xl = strong.min()
        frames = _runs(mg[:, max(0, xl - 12):xl + 12].any(axis=1), merge=3, least=25)
        xr = strong.max()
        taken = {}
        for f0, f1 in frames:
            inside = ink[f0 + 12:f1 - 12, xl + 12:xr - 12]
            if inside.size == 0 or inside.mean() > 0.35:
                continue                                 # a filled box, not a mood frame (the frames are white inside)
            lines = [" ".join(re.sub(r"[^A-Za-z&,/()\s-]", " ", x).split()) for x in
                     _ocr(_crop(im, (xl + 8, f0 + 6, xr - 6, f1 - 6)), 6).splitlines()]
            lines = [x for x in lines if x.strip("() ")]
            # each line of a frame is a label, unless it ends (or the next begins) with "&", ",", "and" or "amidst": then it goes on
            t = ""
            for x in lines:
                joined = not t or re.search(r"(?:&|,|\b(?:and|amidst|amid))\s*$", t) or re.match(r"\s*(?:&|,|and\b)", x)
                t += (" " if joined else " | ") + x
            t = " ".join(t.split())
            row_ = next((r for r in rows if f0 + 8 < r[1]), None)          # the row the frame's top is in, or the next one
            cand = [x for x in badges if x["v"] and x["v"] not in supers]
            if row_ and row_ not in taken:
                inrow = [x for x in cand if row_[0] <= x["y"] < row_[1]]
                start = inrow[0]["v"] if inrow else None
                taken[row_] = True
            else:
                start = None
            if start is None and cand:
                c = (f0 + f1) / 2
                start = min(cand, key=lambda x: abs(x["y"] - c))["v"]
            if start:
                out["moods"].append((start, t))
    return out


def _ink_only(im: Image.Image, box) -> Image.Image:
    """A badge cut out as black text on white: its fill colour, whatever it is, drops out."""
    g = np.asarray(im.crop(box).convert("L")).astype(int)
    bw = np.where(g < min(110, int(g.mean()) - 60), 0, 255).astype(np.uint8)
    out = Image.fromarray(bw)
    return out.resize((out.width * 3, out.height * 3), Image.NEAREST)


BADGE = re.compile(r"(\d{1,3})\s*([a-z]{0,2})(?:\s*-\s*[a-z])?")


def _numbers(texts: list[str], lasts: list[tuple[int, int]]) -> list[tuple[int, int, str]] | str:
    """The verse of each badge, top to bottom, as (psalm, verse, part). A badge reads "v. 12", "v. 1a" / "v. 1b" (parts of one
    verse), "v. 5a-b" (taken as its first part) or "v. 1ss" (the superscription part of verse 1), and in the Ps 9-10 picture
    "9:12". OCR's number is taken where it is the same verse with a new part or the next verse; anything else, or a badge OCR
    cannot read, is counted on from the badge before. The badges must end on each psalm's last verse, or the picture is left
    out."""
    parsed = []
    for k, t in enumerate(texts):
        low = t.replace("O", "0").lower()
        m = BADGE.search(low.replace("v", " ").replace(".", " ").split(":", 1)[-1])
        if k == 0 and not re.search(r"[1-9]", low.replace("55", "")) and re.search(r"ss|55", low):
            parsed.append((1, "ss"))
            continue
        num, part = (int(m.group(1)), m.group(2)) if m else (None, "")
        part = part if part == "ss" else part[:1] if part[:1] in ("a", "b", "c", "d") else ""
        parsed.append((num, part))
    if len(parsed) > 1 and parsed[0] == (None, "") and parsed[1][0] == 1:
        parsed[0] = (1, "ss")                            # an unread first badge before verse 1: its superscription part
    # every badge is either the next verse or one more part of the same verse; the numbering that ends on the last verse and
    # agrees with OCR most often wins (dynamic programming over the verses of all psalms in the picture, in order)
    seq = [(ps, v) for ps, last in lasts for v in range(1, last + 1)]
    m, V = len(parsed), len(seq)
    if m < V - 3 or m > 2 * V:
        return f"{m} badges for {V} verses: {texts}"
    hit = lambda k, j: 1 if parsed[k][0] == seq[j][1] else 0
    NEG = -10 ** 9
    best = [[NEG] * V for _ in range(m)]
    back = [[None] * V for _ in range(m)]
    for j in range(min(3, V)):                           # a picture may start at verse 1, 2 or 3 (no superscription badge)
        best[0][j] = hit(0, j) - j * 0.5
    for k in range(1, m):
        for j in range(V):
            stay = best[k - 1][j] + (0.3 if parsed[k][1] or parsed[k - 1][1] else -0.2)
            step = best[k - 1][j - 1] if j else NEG
            if max(stay, step) == NEG:
                continue
            best[k][j], back[k][j] = (stay, j) if stay > step else (step, j - 1)
            best[k][j] += hit(k, j)
    if best[m - 1][V - 1] == NEG:
        return f"no numbering of {m} badges ends on {seq[-1][0]}:{seq[-1][1]}: {texts}"
    path, j = [], V - 1
    for k in range(m - 1, -1, -1):
        path.append(j)
        j = back[k][j] if k else j
    path.reverse()
    out = []
    for k, j in enumerate(path):
        ps, v = seq[j]
        run = [i for i, jj in enumerate(path) if jj == j]
        if len(run) == 1:
            out.append((ps, v, ""))
        elif k == run[0] and parsed[k][1] == "ss":
            out.append((ps, v, "ss"))
        else:
            letters = [parsed[i][1] for i in run if parsed[i][1] != "ss"]
            pos = [i for i in run if parsed[i][1] != "ss"].index(k)
            ok = len(set(letters)) == len(letters) and all(letters) and letters == sorted(letters)
            out.append((ps, v, letters[pos] if ok else "abcd"[pos] if run[0] == k or parsed[run[0]][1] != "ss" else ""))
    for k in range(1, len(out)):                         # after "v. 1ss" comes verse 1 itself, without a letter
        if out[k - 1][2] == "ss" and out[k][1] == out[k - 1][1]:
            out[k] = (out[k][0], out[k][1], "")
    agree = sum(hit(k, j) for k, j in enumerate(path))
    if agree < m * 0.6:
        return f"OCR agrees with the numbering on only {agree} of {m} badges: {texts}"
    if (out[-1][0], out[-1][1]) != lasts[-1]:
        return f"badges end at {out[-1][0]}:{out[-1][1]}, the picture should end at {lasts[-1][0]}:{lasts[-1][1]}: {texts}"
    return out


def svg_pictures(folder: Path, out: Path) -> dict[int, Path]:
    """The pages whose At-a-Glance is an inline SVG (and so gives the HTML reader no sections or moods): the SVG cut from the
    page and rendered to PNG."""
    from macula import scriptura
    got = {}
    for f in sorted(folder.glob("psalm_*.html")):
        n = int(f.stem.split("_")[1])
        if (folder / f"psalm_{n:03d}_glance.jpg").exists():
            continue
        r = scriptura.read(n, folder, pictures=False)
        if not r or r["sections"] or r["moods"]:
            continue
        raw = f.read_text(encoding="utf-8")
        i = raw.find("At-a-Glance")
        m0 = re.compile(r"<svg[^>]*viewBox").search(raw, i) if i >= 0 else None
        j = m0.start() if m0 else -1
        if j < 0:
            continue
        depth, k = 0, j
        for m in re.finditer(r"<svg\b|</svg>", raw[j:]):          # the whole drawing: its <svg> holds nested ones
            depth += 1 if m.group(0) == "<svg" else -1
            if depth == 0:
                k = j + m.end()
                break
        svg = raw[j:k]
        if 'xmlns="http://www.w3.org/2000/svg"' not in svg[:400]:
            svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
        s = out / f"psalm_{n:03d}.svg"
        s.write_text(svg, encoding="utf-8")
        p = out / f"psalm_{n:03d}_glance.png"
        subprocess.run(["rsvg-convert", "-w", "2400", "-b", "white", "-o", str(p), str(s)], check=True)
        got[n] = p
    return got


def main() -> None:
    from macula import scriptura
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", type=Path, default=None)
    ap.add_argument("--psalms", default="")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    folder = a.folder or scriptura.snapshot()
    spine = Path(__file__).resolve().parent / "macula-spine.db"
    last = dict(sqlite3.connect(spine).execute(
        "SELECT chapter, MAX(verse) FROM macula_words WHERE book='PSA' GROUP BY chapter"))
    want = {int(x) for x in a.psalms.split(",") if x}
    pics = {int(p.stem.split("_")[1]): p for p in sorted(folder.glob("psalm_*_glance.jpg"))}
    with tempfile.TemporaryDirectory() as d:
        pics.update(svg_pictures(folder, Path(d)) if not want or want - set(pics) else {})
        lines = ["psalm\tkind\tverse\tlabels\timage_sha256"]
        shas = {n: hashlib.sha256(p.read_bytes()).hexdigest() if p.suffix == ".jpg" else "svg:" + hashlib.sha256(
                (folder / f"psalm_{n:03d}.html").read_bytes()).hexdigest() for n, p in pics.items()}
        done = set()
        for n, p in sorted(pics.items()):
            if (want and n not in want) or n in done:
                continue
            group = [n] + ([n + 1] if shas.get(n + 1) == shas[n] else [])          # one picture for two psalms (9-10)
            done.update(group)
            r = read_picture(p, [(m, last[m]) for m in group])
            if "error" in r:
                print(group, "NOT READ:", r["error"])
                continue
            v = lambda t: f"{t[1]}{t[2]}"
            for kind, xs in (("superscription", r["superscription"]), ("section", r["sections"])):
                for x in xs:
                    lines.append(f"{x[0]}\t{kind}\t{v(x)}\t\t{shas[n]}")
            for x, t in r["moods"]:
                lines.append(f"{x[0]}\t{kind}\t{v(x)}\t{t}\t{shas[n]}".replace(f"\t{kind}\t", "\tmood\t", 1))
            print(group, "super", [v(x) for x in r["superscription"]], "sections", [f"{x[0]}:{v(x)}" for x in r["sections"]],
                  "moods", [(f"{x[0]}:{v(x)}", t) for x, t in r["moods"]])
    if not want:
        (folder / "glance.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
