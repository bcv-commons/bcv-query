"""Position tables for the lexeme-aligner (the id standard of 2026-11-23). Local; handed over on the box, not published.

    cd shoresh && .venv/bin/python -m macula.build_aligner_tables --ids DIR --out DIR

- `grc_bre/positions.tsv`: Brenton, word level (the aligner links Hebrew parts to Brenton WORDS; the step to GLAUx's parts
  stays ours, CC BY-SA). One row per token of the aligner's verse numbering: book, chapter, verse, position (the tokenizer's
  i), token, bre_word_id, and the source verse the id was minted on. The aligner reads the source's EZR 11-23 as NEH 1-13 and
  the second of the source's two EZR 13:6 as NEH 3:7; our ids were minted on the source, where both 13:6 are one verse of 51
  words (ids stay frozen), so NEH 3:7's positions 0-25 are our EZR 13:6 words 26-51.
- `heb_scg/`, `heb_mod/`: bcv-split/0.1 files (lexeme-aligner docs/split-format.md) of the Hebrew NTs at level 2: one row per
  level-2 piece, with our part ids, the piece's kind and features, and its basis (ours and the spec's).

Slots: in a token, the last part that is not a pronoun suffix is the host; parts before it are `prefix`, pronoun parts after it
`suffix`; inside the host, level 2's prefix / stem / ending are `prefix` / `stem` / `suffix`. A token of one piece is `whole`.
Spec basis: `model` where the level-1 part is the tagger's or the piece is Jev-assisted; `derived` where the Tanakh's cut of the
same form was taken; otherwise `external` (MACULA's analysis carried by hebrew-nt-analysis).
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from macula.build_text_ids import NUMBER

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor_bibles"))
import bcv_tokenize  # noqa: E402

from macula import text_faults  # noqa: E402

HERE = Path(__file__).resolve().parent
VERSION = "v0.2"   # v0.2: level-2 cuts with the common-gender, state and Tanakh-majority fixes (v0.1 stays as the aligner pinned it)
TOKENIZERS_SAME = [2, 3]   # checked 2026-11-23: v2 and v3 give the same tokens and book fingerprints on grc_bre, heb_scg, heb_mod
ANALYSIS = HERE / "data" / "bridge-corpus" / "inputs" / "hebrew-nt-analysis@v0.2"
TEXT = {"heb_scg": "scg", "heb_mod": "del"}
SLOT2 = {"prefix": "prefix", "stem": "stem", "ending": "suffix", "fused": "stem", "whole": "stem"}


def read_tsv(p):
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))


def fp8(manifest, text):
    return {b: h[:8] for b, h in manifest["texts"][text]["book_text_fingerprints"].items()}


def brenton(ids, out, manifest):
    rows = read_tsv(ids / "bre" / "words.tsv")
    d = out / "grc_bre"
    d.mkdir(parents=True)
    n = 0
    with open(d / "positions.tsv", "w", encoding="utf-8") as f:
        f.write("book\tchapter\tverse\tposition\ttoken\tbre_word_id\tsource_book\tsource_chapter\tsource_verse\n")
        for r in rows:
            b, c, v, p = r["book"], int(r["chapter"]), int(r["verse"]), int(r["position"])
            ab, ac, av, ap = b, c, v, p
            if b == "EZR" and c >= 11:
                ab, ac = "NEH", c - 10
                if (c, v) == (13, 6) and p >= 25:
                    av, ap = 7, p - 25
            f.write(f"{ab}\t{ac}\t{av}\t{ap}\t{r['token']}\t{r['word_id']}\t{b}\t{c}\t{v}\n")
            n += 1
    (d / "_table.json").write_text(json.dumps({
        "table": "bcv-query position -> bre word id (id standard 2026-11-23)", "edition": "grc_bre",
        "table_version": VERSION, "tokenizer_version": 3, "tokens_identical_for_tokenizer_versions": TOKENIZERS_SAME,
        "text_fp_version": 1, "text_fp": fp8(manifest, "bre"), "text_fp_as_numbered": as_numbered_fp(), "rows": n, "sha256": hashlib.sha256((d / "positions.tsv").read_bytes()).hexdigest(),
        "licence": "public domain (Brenton's text; our ids carry no third-party data)", "date": datetime.date.today().isoformat(),
        "note": "all 52 source books; EZR 11-23 as NEH 1-13, the second EZR 13:6 as NEH 3:7 (source_* gives the verse the id was minted on)",
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return n


def as_numbered_fp():
    """Brenton's EZR and NEH fingerprints as the aligner numbers them (EZR 1-10; EZR 11-23 as NEH 1-13, the source's doubled
    13:6 split before "Καὶ ἐπὶ χεῖρα αὐτῶν ἐκράτησαν Μαλτίας" as NEH 3:6 and 3:7)"""
    from macula import build_text_ids as bt
    import helloao_to_usj
    import verse_text
    chs = sorted((json.loads(f.read_text()) for f in (bt.HELLOAO / "grc_bre").glob("EZR_*.json")), key=lambda d: d["chapter"]["number"])
    vt = verse_text.extract_usj(helloao_to_usj.merge_book_usj("EZR", chs))
    vs = {(int(c), int(x["verse"])): x["text"] for c, xs in vt.items() for x in xs}
    neh = {(c - 10, v): t for (c, v), t in vs.items() if c >= 11}
    t = neh[(3, 6)]
    cut = t.index("Καὶ ἐπὶ χεῖρα αὐτῶν ἐκράτησαν Μαλτίας")
    neh[(3, 6)], neh[(3, 7)] = t[:cut], t[cut:]
    return {"EZR": bcv_tokenize.fingerprints({k: v for k, v in vs.items() if k[0] <= 10})[0][:8],
            "NEH": bcv_tokenize.fingerprints(neh)[0][:8]}


def basis_of(src, b2):
    if src == "model" or b2.startswith("jev"):
        return "model"
    return "derived" if b2 == "tanakh" else "external"


def split_file(ed, ids, out, manifest):
    text = TEXT[ed]
    faults = text_faults.load(ed)
    p2 = collections.defaultdict(list)
    for r in read_tsv(ids / text / "parts2.tsv"):
        p2[r["part_id"]].append(r)
    toks = collections.defaultdict(list)
    for r in pq.read_table(ANALYSIS / ed / "words.parquet").to_pylist():
        toks[(r["book"], r["chapter"], r["verse"], r["i"])].append(r)
    rows = []
    for k in sorted(toks, key=lambda k: (NUMBER[k[0]], k[1], k[2], k[3])):
        ps = sorted(toks[k], key=lambda r: r["part"])
        host = max((j for j, r in enumerate(ps) if r["class"] != "pron"), default=0)
        pieces = []
        for j, r in enumerate(ps):
            pid = f"{text}:{NUMBER[r['book']]:02d}{r['chapter']:03d}{r['verse']:03d}{r['i'] + 1:03d}{r['part'] + 1}"
            for q in sorted(p2[pid], key=lambda q: int(q["n"])):
                slot = "prefix" if j < host else "suffix" if j > host else SLOT2[q["kind"]]
                pieces.append((r, pid, q, slot))
        r0 = ps[0]
        word = r0["word"]
        wid = f"{text}:{NUMBER[r0['book']]:02d}{r0['chapter']:03d}{r0['verse']:03d}{r0['i'] + 1:03d}"
        fault = faults.get(wid)
        if fault and fault["layer"] == "source_text":
            # a fault of the edition's text (text_faults.tsv): the token as written, one whole piece, with the fault's id
            # and fix (drop: not a word of the text; replace: read as `fixed`)
            word = r0["token"]
            pid0 = pieces[0][1] if pieces else ""
            # replace: a real word read as `fixed`, so it gets a piece id (part id + 1); drop: not a word, no piece id
            q = {"text": word, "part2_id": pid0 + "1" if pid0 and fault["fix"] == "replace" else "", "kind": "whole",
                 "features": "", "basis": f"fault:{fault['fault_id']}"}
            pieces = [(r0, pid0, q, "whole")]
        joined = "".join(q["text"] for _, _, q, _ in pieces)
        if fault and fault["layer"].startswith("ours:") and fault["fault"] == "lost_letters" and word.startswith(joined):
            # one of our datasets lost the word's last letters: the rest as a suffix piece, with the fault's id
            r, pid = pieces[-1][0], pieces[-1][1]
            n_pid = sum(1 for x in pieces if x[1] == pid)     # the restored letters: the next piece of that part
            pieces.append((r, pid, {"text": word[len(joined):], "part2_id": f"{pid}{n_pid + 1}", "kind": "ending", "features": "",
                                    "basis": f"fault:{fault['fault_id']}"}, "suffix"))
            joined = word
        if joined != word or bcv_tokenize.tokenize(word) != [r0["token"]]:
            raise SystemExit(f"{wid} {r0['token']!r}: the parts do not rebuild the word and no fault is listed; "
                             f"add it to text_faults/text_faults.tsv")
        one = len(pieces) == 1
        for n, (r, pid, q, slot) in enumerate(pieces):
            rows.append({"book": r["book"], "chapter": int(r["chapter"]), "verse": int(r["verse"]), "i": int(r["i"]),
                         "token": r["token"], "word": word, "part": n, "slot": "whole" if one else slot, "text": q["text"],
                         "class": r["class"], "lemma": r["lemma"], "lexeme": r["lexeme"], "strong": r["strong"],
                         "basis": basis_of(r["source"], q["basis"]), "p_split": r["p_split"] if n == 0 else None,
                         "part_id": pid, "part2_id": q["part2_id"], "level1_part": int(r["part"]), "level1_source": r["source"],
                         "level2_kind": q["kind"], "level2_features": q["features"], "level2_basis": q["basis"],
                         "fault_fix": fault["fix"] if fault else None, "fault_fixed": (fault["fixed"] or None) if fault else None})
    d = out / ed
    d.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows), d / "words.parquet")
    (d / "_split.json").write_text(json.dumps({
        "spec": "bcv-split/0.1", "edition": ed, "table_version": VERSION, "tokenizer_version": 3,
        "tokens_identical_for_tokenizer_versions": TOKENIZERS_SAME,
        "source": f"bcv-query Hebrew NT level 2 (hebrew-nt-analysis v0.2 parts; Tanakh cut from word-parts v1.1; Jev jev-1.14.0 "
                  f"for gender/number/state), {datetime.date.today().isoformat()}",
        "basis": "derived", "sha256": hashlib.sha256((d / "words.parquet").read_bytes()).hexdigest(),
        "text_licence": "public domain", "books": sorted({r["book"] for r in rows}, key=lambda b: NUMBER[b]),
        "text_fp": fp8(manifest, text), "text_fp_version": 1, "date": datetime.date.today().isoformat(),
        "extra_columns": {"part_id": "our level-1 part id", "part2_id": "our level-2 piece id", "level1_part": "the part in hebrew-nt-analysis",
                          "level1_source": "macula / model (hebrew-nt-analysis)", "level2_kind": "prefix / stem / ending / whole",
                          "level2_features": "MACULA-style code of the piece (Vx...: verb stem not known)",
                          "level2_basis": "tanakh / jev / jev_name / jev_no_parse / whole / verse_number / fault:<id> (text_faults.tsv)",
                          "fault_fix": "drop / replace, where the token has a listed fault", "fault_fixed": "the reading for replace"},
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", type=Path, required=True, help="build_text_ids' folder (with parts2.tsv)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    if a.out.exists() and any(a.out.iterdir()):
        raise SystemExit(f"{a.out} is not empty; give a fresh folder")
    a.out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((a.ids / "manifest.json").read_text(encoding="utf-8"))
    print("grc_bre rows", brenton(a.ids, a.out, manifest))
    for ed in TEXT:
        print(ed, "rows", split_file(ed, a.ids, a.out, manifest))
    files = sorted(p for p in a.out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (a.out / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(a.out)}\n"
                                              for p in files), encoding="utf-8")


if __name__ == "__main__":
    main()
