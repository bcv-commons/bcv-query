"""How the world's New Testament translations render each Greek word: the lexeme-aligner's published `rend` channel, read per
MACULA Greek word.

    python -m macula.build_nt_rend --fetch      the NT books of every edition (both repos at their pinned commits, by partial git clone)
    python -m macula.build_nt_rend --read       -> macula/data/nt-rend/rend.pkl

Inputs (published, pinned): bcv-commons/compact-alignments (CC0; one "srcOrd:span" string per verse, `_index/<BOOK>_lexemes.json`
with the aligner's Greek number per srcOrd, `manifest.json`) and bcv-commons/compact-alignments-meta (its `rend` channel: per verse
one integer per part, the n-th distinct rendering of that lexeme in that edition). The ids say which occurrences one edition renders
alike; they hold no text. Comparable only within one edition and one Greek lexeme.

rend.pkl: {"editions": [(iso, edition)], "features": {greek id (n40001001001): [(edition index, rendering id), ...]}}. Every NT edition
is read (2,333 in 1,794 languages); a later step weights languages, not editions.
"""
from __future__ import annotations

import argparse
import collections
import json
import pickle
import sqlite3
import sys
from pathlib import Path

from macula.build_rend_renderings import map_entries

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "nt-rend"
ONLY = {"eng": "eng_BSB"}                                               # the edition read for a language where the user named one
PINS = {"bcv-commons/compact-alignments": "11583082", "bcv-commons/compact-alignments-meta": "96d0a229"}
NT = ("MAT", "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL", "EPH", "PHP", "COL", "1TH", "2TH", "1TI", "2TI", "TIT", "PHM", "HEB",
      "JAS", "1PE", "2PE", "1JN", "2JN", "3JN", "JUD", "REV")


def root(repo: str) -> Path:
    return OUT / ("meta-git" if repo.endswith("-meta") else "compact-git")


def choose(n_languages: int, seed: int = 20261116) -> list[str]:
    """edition folders to read: one edition per language (the one with most NT books; English: the BSB), n languages drawn with a seed
    from those with a full NT, English always in"""
    import random
    m = json.loads((root("bcv-commons/compact-alignments") / "manifest.json").read_text())
    pick = {}
    for iso, lang in m["languages"].items():
        eds = sorted((len(set(NT) & set(e["books"])), name) for name, e in lang["editions"].items())
        if eds and eds[-1][0] == len(NT):
            pick[iso] = ONLY.get(iso, eds[-1][1])
    langs = sorted(pick)
    chosen = sorted(set(random.Random(seed).sample(langs, min(n_languages, len(langs)))) | {"eng"})
    return [f"{iso[0]}/{iso}/{pick[iso]}" for iso in chosen]


def fetch(n_languages: int) -> None:
    """a partial git clone (blobs on demand) of both repos at their pinned commits, then the chosen editions' NT books in batches: the
    Hub's per-file API rate-limits this many files (HTTP 429) and drops a long single git transfer, so each checkout stays small"""
    import subprocess
    for repo, rev in PINS.items():
        d = root(repo)
        if not d.exists():
            subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", "--depth", "1", f"https://huggingface.co/datasets/{repo}", str(d)], check=True)
        head = subprocess.check_output(["git", "-C", str(d), "rev-parse", "HEAD"], text=True).strip()
        if not head.startswith(rev):
            raise SystemExit(f"{repo} is at {head[:8]}, the pin is {rev}: update PINS deliberately")
        ext = ".meta.json" if repo.endswith("-meta") else ".json"
        pats = [f"/*/*/*/{b}_*{ext}" for b in NT] + ([] if repo.endswith("-meta") else ["/manifest.json"] + [f"/_index/{b}_lexemes.json" for b in NT])
        subprocess.run(["git", "-C", str(d), "sparse-checkout", "set", "--no-cone", *pats], check=True)
        if not repo.endswith("-meta"):
            subprocess.run(["git", "-C", str(d), "checkout", "-q", "HEAD", "--", "manifest.json", "_index"], check=True)
    eds = choose(n_languages)
    for repo in PINS:
        d = root(repo)
        todo = [e for e in eds if len(list((d / e).glob("*.json"))) < 2 * len(NT)]
        for k in range(0, len(todo), 10):
            for attempt in range(5):
                if subprocess.run(["git", "-C", str(d), "checkout", "-q", "HEAD", "--", *(f"{e}/*" for e in todo[k:k + 10])]).returncode == 0:
                    break
            print(f"[nt-rend] {repo}: {min(k + 10, len(todo))} of {len(todo)} editions", file=sys.stderr, flush=True)
    print(f"[nt-rend] {len(eds)} editions chosen", file=sys.stderr)


def greek_words() -> dict[str, list[tuple[str, str]]]:
    """'JHN 1:1' -> [(MACULA Greek id, Strong's number)] in order"""
    con = sqlite3.connect(f"file:{HERE / 'macula-spine.db'}?mode=ro", uri=True)
    out = collections.defaultdict(list)
    for xml, b, c, v, s in con.execute("select xml_id, book, chapter, verse, strong from macula_words where lang = 'grc' order by key"):
        out[f"{b} {c}:{v}"].append((xml, str(s or "")))
    return out


def read() -> dict:
    comp, meta = root("bcv-commons/compact-alignments"), root("bcv-commons/compact-alignments-meta")
    words = greek_words()
    index = {b: json.loads((comp / "_index" / f"{b}_lexemes.json").read_text(encoding="utf-8")) for b in NT}
    mapped = {}
    eds, feats, st = [], collections.defaultdict(list), collections.Counter()
    for iso_dir in sorted(comp.glob("?/*")):
        for ed in sorted(p for p in iso_dir.iterdir() if p.is_dir()):
            if len(list(ed.glob("*_????????.json"))) < len(NT):              # only editions fetched whole (fetch's batches)
                continue
            e = None
            for b in NT:
                fs = sorted(ed.glob(f"{b}_????????.json"))
                if not fs:
                    continue
                mp = meta / fs[0].relative_to(comp).with_suffix(".meta.json")
                if not mp.exists():
                    st["books without a meta file"] += 1
                    continue
                rend = json.loads(mp.read_text(encoding="utf-8")).get("rend")
                if not rend:
                    st["books without rend"] += 1
                    continue
                if e is None:
                    e = len(eds)
                    eds.append((iso_dir.name, ed.name))
                compact = json.loads(fs[0].read_text(encoding="utf-8"))
                for ref, s, r in zip(index[b], compact, rend):
                    ws = words.get(ref)
                    if not s or not r or not ws:
                        continue
                    parts, ids = s.split(), r.split()
                    if len(parts) != len(ids):
                        st["verses with unequal lengths"] += 1
                        continue
                    if ref not in mapped:
                        mapped[ref] = map_entries(index[b][ref], [n for _, n in ws])
                    for part, rid in zip(parts, ids):
                        for pos in mapped[ref].get(int(part.split(":", 1)[0]), []):
                            feats[ws[pos][0]].append((e, int(rid)))
                            st["occurrences"] += 1
                st["books"] += 1
    rep = {"editions": len(eds), "languages": len({i for i, _ in eds}), "greek words with a rendering": len(feats), **st}
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "rend.pkl").open("wb") as fh:
        pickle.dump({"editions": eds, "features": dict(feats), "pins": PINS}, fh)
    (OUT / "report.json").write_text(json.dumps(rep, indent=1) + "\n")
    return rep


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--read", action="store_true")
    ap.add_argument("--languages", type=int, default=300, help="with --fetch: how many languages (one edition each)")
    a = ap.parse_args()
    if a.fetch:
        fetch(a.languages)
    if a.read:
        print(json.dumps(read(), indent=1))


if __name__ == "__main__":
    main()
