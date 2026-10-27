"""Package a built Hebrew speaker layer as a release of the dataset bcv-commons/hebrew-speaker-layer. Nothing is uploaded: the files
are written to a folder for review, and published by hand.

    python -m macula.release_speaker_layer --tag v0.7 --out DIR [--src macula/data/speaker-layer] [--allow-dirty]

DIR gets:
  README.md                          the dataset card (macula/speaker_layer_card.md with the version fields filled in)
  quotations.tsv, segments/, report.md, corrections.tsv, review.tsv, prophets.tsv, parallels.tsv
  hebrew-speaker-layer-<tag>.tar.gz  the pinned download: the files above (reproducible: sorted entries, fixed times and owners)
  SHA256SUMS                         SHA-256 of the archive and the files

The build must come from committed code, corrections and review rows (`git status` clean for macula/ and resources/speaker_layer/),
unless --allow-dirty. The build must be the default one (with the review rows) and parallels.tsv from `python -m macula.speaker_parallels`.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import gzip
import hashlib
import io
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CARD = HERE / "speaker_layer_card.md"
CORRECTIONS = ROOT / "resources" / "speaker_layer" / "corrections.tsv"
REVIEW = ROOT / "resources" / "speaker_layer" / "review.tsv"
PROPHETS = ROOT / "resources" / "speaker_layer" / "prophets.tsv"


def _rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader((line for line in fh if not line.startswith("#")), delimiter="\t"))


def _archive(out: Path, tag: str, files: list[Path]) -> Path:
    path = out / f"hebrew-speaker-layer-{tag}.tar.gz"
    root = f"hebrew-speaker-layer-{tag}"
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for f in sorted(files, key=lambda p: p.relative_to(out).as_posix()):
            data = f.read_bytes()
            info = tarfile.TarInfo(f"{root}/{f.relative_to(out).as_posix()}")
            info.size, info.mode, info.mtime, info.uid, info.gid, info.uname, info.gname = len(data), 0o644, 0, 0, 0, "", ""
            tar.addfile(info, io.BytesIO(data))
    with open(path, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", mtime=0, filename="") as gz:
        gz.write(raw.getvalue())
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--src", default=str(HERE / "data" / "speaker-layer"))
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    src, out = Path(a.src), Path(a.out)
    if not a.allow_dirty:
        dirty = subprocess.run(["git", "status", "--porcelain", "--", str(HERE), str(CORRECTIONS.parent)], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
        if dirty:
            raise SystemExit("uncommitted changes in macula/ or resources/speaker_layer/; commit first (or --allow-dirty):\n" + dirty)
    if "review.tsv, left out" in (src / "report.md").read_text(encoding="utf-8"):
        raise SystemExit("this build left the review rows out (--no-review); rebuild with them")
    if out.exists():
        shutil.rmtree(out)
    (out / "segments").mkdir(parents=True)
    files = []
    for name in ("quotations.tsv", "report.md"):
        shutil.copy(src / name, out / name)
        files.append(out / name)
    for f in (CORRECTIONS, REVIEW, PROPHETS):
        shutil.copy(f, out / f.name)
        files.append(out / f.name)
    shutil.copy(src / "parallels.tsv", out / "parallels.tsv")
    files.append(out / "parallels.tsv")
    for f in sorted((src / "segments").glob("*.tsv")):
        shutil.copy(f, out / "segments" / f.name)
        files.append(out / "segments" / f.name)

    quotes = _rows(out / "quotations.tsv")
    segs = [r for f in sorted((out / "segments").glob("*.tsv")) for r in _rows(f)]
    fields = {"@TAG@": a.tag, "@BUILT@": datetime.date.today().isoformat(),
              "@QUOTATIONS@": f'{sum(q["level"] == "1" for q in quotes):,}',
              "@NESTED@": f'{sum(q["level"] not in ("", "1") for q in quotes):,}',
              "@IN_QUOTE@": f'{sum(r["quotation"] != "" for r in segs):,}', "@SEGMENTS@": f"{len(segs):,}",
              "@REVIEW_ROWS@": f'{len(_rows(out / "review.tsv")):,}',
              "@NAMED@": f'{sum(bool(q["speaker"]) for q in quotes):,} of {len(quotes):,}',
              "@UNNAMED@": f'{sum(not q["speaker"] for q in quotes):,}',
              "@ALT_ENG@": f'{sum(bool(q["alt_eng"]) for q in quotes):,}',
              "@CHARACTERS@": f'{len({q["speaker_id"] for q in quotes if q["speaker_id"]}):,}',
              "@WITH_ID@": f'{sum(bool(q["speaker_id"]) for q in quotes):,}',
              "@CHAR_NAMED@": f'{len({q["speaker_id"] for q in quotes if q["speaker_name"]}):,}',
              "@NAME_QUOTES@": f'{sum(bool(q["speaker_name"]) for q in quotes):,}',
              "@LOWFAT_SHA@": re.search(r"MACULA Hebrew lowfat sha256 ([0-9a-f]+)", (out / "report.md").read_text(encoding="utf-8")).group(1)[:12]}
    card = CARD.read_text(encoding="utf-8")
    for k, v in fields.items():
        card = card.replace(k, v)
    if any(w.startswith("@") and w.endswith("@") and len(w) > 2 for w in card.split()):
        raise SystemExit("the card has a field that was not filled in")
    (out / "README.md").write_text(card, encoding="utf-8")
    files.append(out / "README.md")

    arc = _archive(out, a.tag, files)
    sums = [(hashlib.sha256(arc.read_bytes()).hexdigest(), arc.name)]
    sums += [(hashlib.sha256(f.read_bytes()).hexdigest(), f.relative_to(out).as_posix()) for f in sorted(files)]
    (out / "SHA256SUMS").write_text("".join(f"{h}  {n}\n" for h, n in sums), encoding="utf-8")
    print(f"{out}: {len(files)} files; {arc.name} {sums[0][0]}")


if __name__ == "__main__":
    main()
