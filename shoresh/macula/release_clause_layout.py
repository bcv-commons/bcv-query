"""Package a built Hebrew clause layout as a release of the dataset bcv-commons/hebrew-clause-layout. Nothing is uploaded: the files
are written to a folder for review, and published by hand.

    python -m macula.release_clause_layout --out DIR --steps STEPS.md [--src macula/data/clause-layout] [--reach rule-reach.txt]

DIR gets:
  README.md                         the dataset card (macula/clause_layout_card.md with the version fields filled in)
  RELEASE_NOTES.md                  the release: sources, the rules with their scope and reach, checksums
  _clauses_source.json              the version stamp: segmentation, levels, per-book segment-boundary hashes
  build.json                        the build record (copied)
  clause_layout.toml                the rules and settings the layout was built with (copied)
  schema/clause_segment.schema.json the JSON Schema of a row
  data/clauses-<BOOK>.parquet       the rows, one file per book
  hebrew-clause-layout-<tag>.tar.gz the pinned download: clauses/, layout/ and the files above except data/ (reproducible: sorted
                                    entries, fixed times and owners)
  SHA256SUMS                        SHA-256 of the archive and the data files

The build must come from the settings in use (its rules version and settings hash are checked), and its rows are checked: every
row has the fields of the schema, every book's boundary hash is recomputed from the rows and must match build.json.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

from macula import discourse_rules

HERE = Path(__file__).resolve().parent
CARD = HERE / "clause_layout_card.md"
SCHEMA = HERE / "clause_segment.schema.json"
DATASET = "bcv-commons/hebrew-clause-layout"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _rows(src: Path) -> dict[str, list[tuple[int, list[dict]]]]:
    """book -> [(chapter, rows)] in file order."""
    out: dict[str, list] = collections.defaultdict(list)
    for f in sorted((src / "clauses").glob("*/*.jsonl")):
        rows = [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
        out[rows[0]["book"]].append((rows[0]["chapter"], rows))
    for book in out:
        out[book].sort(key=lambda x: x[0])
    return out


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_clean() -> bool:
    try:
        r = subprocess.run(["git", "status", "--porcelain", "--", str(HERE)], cwd=HERE, capture_output=True, text=True, check=True)
        return not r.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return False


def _reach(path: Path | None) -> dict[str, str]:
    """rule -> "total (top books)" from a rule-reach table, if given."""
    out = {}
    if path is None:
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 7 and parts[1].isdigit():
            top = line.split("  ")[-1].strip() if int(parts[1]) else ""
            out[parts[0]] = parts[1] + (f" ({top})" if top and not top.isdigit() else "")
    return out


def _stamp(build: dict, books: dict, tag: str, commit: str | None) -> dict:
    src = build["sources"]
    stamp = {"dataset": DATASET, "release": tag, "segmentation": build["segmentation"]["version"],
             "levels": f'{build["discourse_rules"]}+{build["rules_config"]["sha256"][:16]}',
             "rules_version": build["discourse_rules"], "settings_sha256": build["rules_config"]["sha256"],
             "profile": build["rules_config"]["profile"],
             "macula_hebrew": {"repository": src["macula_hebrew"]["repository"], "path": src["macula_hebrew"]["path"],
                               "commit": src["macula_hebrew"]["commit"]},
             "uhb": {"repository": src["uhb"]["repository"], "tag": src["uhb"]["tag"]},
             "versification": {"tvtms_rev": src["versification"]["tvtms_rev"], "sha256": src["versification"]["sha256"]},
             "speaker_layer": src.get("speaker_layer"),
             "built": build["built"], "code": {"repository": "https://github.com/bcv-commons/bcv-query", "commit": commit},
             "books": {}}
    for book, chapters in books.items():
        h = hashlib.sha256()
        verses = set()
        n = 0
        for ch, rows in chapters:
            for r in rows:
                h.update(f"{book} {ch}:{r['verse']} {r['first']} {r['last']}\n".encode())
                verses.add((ch, r["verse"]))
                n += 1
        if h.hexdigest() != build["books"][book]["segments_sha256"]:
            raise SystemExit(f"{book}: the rows' boundary hash differs from build.json; rebuild before releasing")
        stamp["books"][book] = {"chapters": len(chapters), "verses": len(verses), "segments": n, "sha256": h.hexdigest()}
    return stamp


def _parquet(books: dict, out: Path) -> list[Path]:
    import pyarrow as pa
    import pyarrow.parquet as pq
    all_rows = [r for chapters in books.values() for _, rows in chapters for r in rows]
    schema = pa.Table.from_pylist(all_rows).schema       # one schema for every book
    files = []
    (out / "data").mkdir(parents=True, exist_ok=True)
    for book, chapters in books.items():
        rows = [r for _, rs in chapters for r in rs]
        path = out / "data" / f"clauses-{book}.parquet"
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="zstd")
        files.append(path)
    return files


def _archive(src: Path, out: Path, tag: str, extra: list[Path], mtime: int) -> Path:
    """A reproducible .tar.gz: sorted entries, fixed time, owner and modes, gzip without a time stamp."""
    root = f"hebrew-clause-layout-{tag}"
    path = out / f"{root}.tar.gz"
    members: list[tuple[str, Path]] = [(p.name if p.parent == out else str(p.relative_to(out)), p) for p in extra]
    for d in ("clauses", "layout"):
        members += [(str(p.relative_to(src)), p) for p in sorted((src / d).glob("*/*")) if p.is_file()]
    members.sort(key=lambda m: m[0])
    with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz, \
            tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
        dirs = sorted({str(Path(name).parent) for name, _ in members if str(Path(name).parent) != "."}
                      | {str(p) for name, _ in members for p in Path(name).parents if str(p) != "."})
        for d in [""] + dirs:
            info = tarfile.TarInfo(f"{root}/{d}".rstrip("/"))
            info.type, info.mode, info.mtime, info.uid, info.gid, info.uname, info.gname = tarfile.DIRTYPE, 0o755, mtime, 0, 0, "", ""
            tar.addfile(info)
        for name, p in members:
            data = p.read_bytes()
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size, info.mode, info.mtime, info.uid, info.gid, info.uname, info.gname = len(data), 0o644, mtime, 0, 0, "", ""
            tar.addfile(info, io.BytesIO(data))
    return path


def _card(stamp: dict, build: dict, tag: str, steps: str) -> str:
    fields = {"@TAG@": tag, "@VERSION@": stamp["rules_version"], "@BUILT@": stamp["built"], "@SEGMENTATION@": stamp["segmentation"],
              "@LEVELS@": stamp["levels"], "@BOOKS@": str(len(stamp["books"])),
              "@CHAPTERS@": str(sum(b["chapters"] for b in stamp["books"].values())),
              "@VERSES@": f'{sum(b["verses"] for b in stamp["books"].values()):,}',
              "@SEGMENTS@": f'{sum(b["segments"] for b in stamp["books"].values()):,}',
              "@MACULA_COMMIT@": stamp["macula_hebrew"]["commit"][:12], "@UHB_TAG@": stamp["uhb"]["tag"],
              "@TVTMS_REV@": stamp["versification"]["tvtms_rev"][:12], "@STEP_TABLE@": steps.strip(),
              "@SPEAKER_TAG@": (stamp["speaker_layer"] or {}).get("tag", "-")}
    text = CARD.read_text(encoding="utf-8")
    for k, v in fields.items():
        text = text.replace(k, v)
    if "@" in "".join(x for x in text.split() if x.startswith("@") and x.endswith("@")):
        raise SystemExit("the card has a field that was not filled in")
    return text


def _notes(stamp: dict, tag: str, reach: dict[str, str], sums: list[tuple[str, str]]) -> str:
    lines = [f"# Hebrew Bible Clause Layout {tag}", "",
             f"Rules {stamp['rules_version']}, built {stamp['built']}, profile `{stamp['profile']}`.", "",
             f"- Segmentation `{stamp['segmentation']}`; levels `{stamp['levels']}`.",
             f"- MACULA Hebrew `{stamp['macula_hebrew']['path']}` at `{stamp['macula_hebrew']['commit']}`; UHB {stamp['uhb']['tag']}; "
             f"TVTMS `{stamp['versification']['tvtms_rev']}`.",
             f"- Code: bcv-commons/bcv-query at `{stamp['code']['commit']}`.", "",
             "## Files", "", "```"] + [f"{h}  {name}" for name, h in sums] + ["```", "",
             "## The rules", "",
             "Each rule of `clause_layout.toml`, in the order the derivation tries them, with its scope and its reach: the clauses whose "
             "`discourse_parent` or `text_depth` changes over the whole Old Testament when that rule alone is turned off (rules that act "
             "only in the law view show 0).", "",
             "| rule | scope | reach | what it does |", "|---|---|---|---|"]
    for name, r in discourse_rules.RULES.items():
        doc = " ".join(r["doc"].split())
        first = doc.split(". ")[0].rstrip(".") + "."
        scope = r["scope"] if isinstance(r["scope"], str) else ", ".join(r["scope"]) if isinstance(r["scope"], list) else str(r["scope"])
        lines.append(f"| `{name}` | {scope} | {reach.get(name, '—' if r.get('switchable', True) else 'part of the model')} | "
                     f"{first.replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", default=str(HERE / "data" / "clause-layout"), help="the built layout (default macula/data/clause-layout)")
    ap.add_argument("--out", required=True, help="folder to write the release into (must not exist)")
    ap.add_argument("--reach", help="a rule-reach table, for the release notes")
    ap.add_argument("--steps", required=True, help="a Markdown table of bsb-add-books' step agreement for this build, for the card")
    ap.add_argument("--allow-dirty", action="store_true", help="package even if macula/ has uncommitted changes")
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    if out.exists():
        raise SystemExit(f"{out} exists; give a new folder")
    build = json.loads((src / "build.json").read_text(encoding="utf-8"))
    if build["discourse_rules"] != discourse_rules.RULES_VERSION or build["rules_config"]["sha256"] != discourse_rules.CONFIG_SHA256:
        raise SystemExit("the build was not made with the settings in use (rules version or settings hash differ); rebuild first")
    if not _git_clean() and not args.allow_dirty:
        raise SystemExit("macula/ has uncommitted changes; commit first (or --allow-dirty for a trial)")
    tag = f"v{build['discourse_rules']}"
    books = _rows(src)
    schema_fields = set(json.loads(SCHEMA.read_text(encoding="utf-8"))["properties"])
    for chapters in books.values():
        for _, rows in chapters:
            for r in rows:
                if set(r) != schema_fields:
                    raise SystemExit(f"{r['book']} {r['chapter']}:{r['verse']}: fields differ from the schema: {sorted(set(r) ^ schema_fields)}")
    stamp = _stamp(build, books, tag, _git_commit())
    out.mkdir(parents=True)
    (out / "schema").mkdir()
    shutil.copy(SCHEMA, out / "schema" / SCHEMA.name)
    shutil.copy(src / "build.json", out / "build.json")
    shutil.copy(discourse_rules.CONFIG_PATH, out / "clause_layout.toml")
    (out / "_clauses_source.json").write_text(json.dumps(stamp, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "README.md").write_text(_card(stamp, build, tag, Path(args.steps).read_text(encoding="utf-8")), encoding="utf-8")
    mtime = int(time.mktime(time.strptime(build["built"], "%Y-%m-%d")))
    extra = [out / n for n in ("README.md", "_clauses_source.json", "build.json", "clause_layout.toml")] + [out / "schema" / SCHEMA.name]
    archive = _archive(src, out, tag, extra, mtime)
    data = _parquet(books, out)
    sums = [(p.name if p.parent == out else str(p.relative_to(out)), _sha256(p)) for p in [archive] + data]
    (out / "SHA256SUMS").write_text("".join(f"{h}  {n}\n" for n, h in sums), encoding="utf-8")
    reach = _reach(Path(args.reach)) if args.reach else {}
    (out / "RELEASE_NOTES.md").write_text(_notes(stamp, tag, reach, sums), encoding="utf-8")
    total = sum(b["segments"] for b in stamp["books"].values())
    print(f"{tag}: {len(books)} books, {total} segments -> {out}\n{sums[0][1]}  {sums[0][0]}")


if __name__ == "__main__":
    main()
