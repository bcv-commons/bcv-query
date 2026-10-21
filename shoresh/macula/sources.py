"""External sources of the clause layout, pinned in clause_layout.toml [sources.*].

check() compares every input a build used with its pin and returns (record, problems): the record goes into build.json, each problem
names the value found and the line to change in the TOML when the new input is intended. build_clause_layout stops on any problem
before it writes output.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _meta(db: Path, table: str) -> dict[str, str]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return dict(con.execute(f"SELECT key, value FROM {table}").fetchall())
    finally:
        con.close()


def check(src: dict, *, trees_db: Path, spine_db: Path, uhb_dir: Path, uhb_files: list[str], vrs_files: dict[str, Path | None],
          tvtms_rev: str | None, speaker_archive: Path | None = None) -> tuple[dict, list[str]]:
    """src: the [sources] table. uhb_files: the UHB files the build read; vrs_files: name -> cached path of the versification files;
    tvtms_rev: the TVTMS revision the versification map states; speaker_archive: the speaker-layer release archive the build read."""
    problems: list[str] = []
    record: dict = {}

    if speaker_archive is not None:
        s = src["speaker_layer"]
        found = sha256_file(speaker_archive)
        record["speaker_layer"] = {"repository": s["repository"], "tag": s["tag"], "licence": s["licence"], "archive_sha256": found}
        if found != s["archive_sha256"]:
            problems.append(f"speaker_layer: {speaker_archive.name} has sha256 {found}, the TOML pins {s['archive_sha256']}. If the new "
                            f"release is intended, set [sources.speaker_layer] tag and archive_sha256 = \"{found}\"")

    m = src["macula_hebrew"]
    found = sha256_file(trees_db)
    commit = _meta(trees_db, "meta").get("source_hbo_commit")
    record["macula_hebrew"] = {"repository": m["repository"], "path": m["path"], "commit": m["commit"], "licence": m["licence"],
                               "trees_db_sha256": found, "commit_recorded_in_trees_db": commit is not None}
    if found != m["trees_db_sha256"]:
        problems.append(f"macula_hebrew: {trees_db.name} has sha256 {found}, the TOML pins {m['trees_db_sha256']}. If the new trees are "
                        f"intended, set [sources.macula_hebrew] trees_db_sha256 = \"{found}\""
                        + (f" and commit = \"{commit}\"" if commit else " and the commit they were built from"))
    if commit is not None and commit != m["commit"]:
        problems.append(f"macula_hebrew: {trees_db.name} was built from commit {commit}, the TOML pins {m['commit']}. If intended, set "
                        f"[sources.macula_hebrew] commit = \"{commit}\"")

    s = src["lexeme_spine"]
    found = _meta(spine_db, "spine_meta").get("spine_content_sha256")
    record["lexeme_spine"] = {"file": s["file"], "spine_content_sha256": found, "licence": s["licence"]}
    if found != s["spine_content_sha256"]:
        problems.append(f"lexeme_spine: {spine_db.name} has spine_content_sha256 {found}, the TOML pins {s['spine_content_sha256']}. If "
                        f"the new spine is intended, set [sources.lexeme_spine] spine_content_sha256 = \"{found}\"")

    u = src["uhb"]
    pins = u.get("sha256", {})
    for name in uhb_files:
        f = uhb_dir / u["tag"] / name
        got = sha256_file(f) if f.exists() else None
        if got != pins.get(name):
            problems.append(f"uhb: {u['tag']}/{name} has sha256 {got}, the TOML pins {pins.get(name)}. If intended, set "
                            f"[sources.uhb.sha256] \"{name}\" = \"{got}\"")
    record["uhb"] = {"repository": u["repository"], "tag": u["tag"], "licence": u["licence"], "files_checked": len(uhb_files)}

    v = src["versification"]
    record["versification"] = {"repository": v["repository"], "tvtms_rev": tvtms_rev, "licence": v["licence"], "sha256": {}}
    if tvtms_rev != v["tvtms_rev"]:
        problems.append(f"versification: the map states TVTMS revision {tvtms_rev}, the TOML pins {v['tvtms_rev']}. If intended, set "
                        f"[sources.versification] tvtms_rev = \"{tvtms_rev}\"")
    for name, pin in v["sha256"].items():
        p = vrs_files.get(name)
        got = sha256_file(p) if p is not None else None
        record["versification"]["sha256"][name] = got
        if got != pin:
            problems.append(f"versification: {name} has sha256 {got}, the TOML pins {pin} (bibles may have published a new map). If "
                            f"intended, set [sources.versification.sha256] \"{name}\" = \"{got}\"")
    return record, problems
