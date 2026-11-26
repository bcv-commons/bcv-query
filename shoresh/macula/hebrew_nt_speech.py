"""Speaker and addressee per clause segment of the Hebrew New Testaments (request 40, row 3).

The values are carried, not made: the source-examples build k1 (format 1.9) gives each Hebrew NT word the Greek clause's
quotation, speaker and addressee through lexeme-aligner's word links (basis `linked`), and separately the values of the
reviewed speaker layers that a language model made (`*_model`, basis `model`). This step puts them on the clause segments of
hebrew-nt-analysis: a segment takes the value most of its linked words have (`speech_share` = their share among the
segment's words with a k1 clause). Speakers and addressees are entity ids (`person:…`, `deity:…`, `group:…`, as k1's
`who`); `entities.parquet` gives each id its kind, its Hebrew type word and name where k1 has one.

The addressee, from v0.6, comes from the addressees layer itself (data/addressees/quotations.tsv, its Greek quotation, by the
quotation id), not from k1's copy of it: the layer was mended on 2026-11-26 (a plural hearer is no longer one of its members;
the second-person rule counts the words of the speech's own number). `addressee` is its entity (empty where the layer names
the hearer only by a word, or by a key term or place), `addressee_basis` how it was found (`inquit`, `second_person`, `turn`, empty), `addressee_member`
the person an entity lookup gave a plural hearer (kept apart). The layer's ACAI ids are coded as k1 codes them
(`examples_people.ent_key`: kind + a SHA-1 prefix of the ACAI id), so no English name reaches the data; an entity that k1's
edition tables lack gets a row in `entities.parquet` with its kind's Hebrew type word and no name (`ent_basis` `layer`).

The addressee's number:
  - `addressee_number_form`: the Hebrew segment's own second-person verbs and pronouns (hebrew-nt-analysis
    `features.parquet`), `singular` or `plural` where they all agree, `mixed` where not, empty where there are none;
  - `addressee_number_layer` (+ `_basis`): the layer's number for the whole quotation: `second_person` (most of the Greek
    quotation's second-person words), `inquit_word` (the word that names the hearer), `entity` (the entity's kind);
  - `addressee_number`: the form where it is singular or plural (basis `form`), else the layer's (its basis);
    `addressee_number_agree`: layer against form, where both are given.

  cd shoresh && .venv/bin/python -I macula/hebrew_nt_speech.py --analysis DIR --features DIR --k1 DIR --addressees TSV
      --entities TSV --out OUT

Writes OUT/<edition>/speech.parquet (one row per clause segment that has a quotation, strict or model; keys book,
chapter, verse, seg), OUT/<edition>/entities.parquet and OUT/build.json.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

FIELDS = ("quote", "speaker", "addressee")
HEARERS = ("person", "deity", "group", "fauna", "flora", "realia")         # the kinds k1's addressees have


def majority(vals):
    """(value, share) of the commonest non-empty value among vals (None = no clause); empty values count against"""
    known = [v for v in vals if v is not None]
    if not known:
        return None, None
    c = collections.Counter(known)
    v, n = c.most_common(1)[0]
    return (v or None), round(n / len(known), 3)


def ent_key(acai: str, kind: str) -> str:
    """as examples_people.ent_key (k1's coding of an ACAI id)"""
    return f"{kind}:e{hashlib.sha1(acai.encode('utf-8')).hexdigest()[:10]}"


def run(analysis: Path, features: Path, k1: Path, addressees: Path, acai_entities: Path, out: Path) -> None:
    build = {"k1": str(k1.name), "addressees": str(addressees.name), "editions": {}}
    with open(addressees, encoding="utf-8") as fh:
        layer = {"q:" + r["quote"]: r for r in csv.DictReader(fh, delimiter="\t") if r["corpus"] == "grc"}
    with open(acai_entities, encoding="utf-8") as fh:
        kind_of = {r["entity"]: r["type"] for r in csv.DictReader((l for l in fh if not l.startswith("#")), delimiter="\t")}
    code = lambda a: ent_key(a, kind_of[a]) if a in kind_of else None   # noqa: E731
    for ed in ("heb_scg", "heb_mod"):
        words = pq.read_table(k1 / ed / "words.parquet", columns=["book", "chapter", "verse", "w", "clause"]).to_pylist()
        clauses = {c["clause"]: c for c in pq.read_table(k1 / ed / "clauses.parquet",
                   columns=["clause", *FIELDS, "speech_basis", *(f + "_model" for f in FIELDS)]).to_pylist()}
        per_word = {}
        for w in words:
            c = clauses.get(w["clause"]) if w["clause"] else None
            if c is not None:
                per_word[(w["book"], w["chapter"], w["verse"], w["w"] - 1)] = c
        second = collections.defaultdict(list)                 # word -> numbers of its second-person parts
        for r in pq.read_table(features / ed / "features.parquet", columns=["book", "chapter", "verse", "i", "person", "number"]).to_pylist():
            if r["person"] == "second" and r["number"] in ("singular", "plural"):
                second[(r["book"], r["chapter"], r["verse"], r["i"])].append(r["number"])
        rows, n = [], collections.Counter()
        for s in pq.read_table(analysis / ed / "clauses.parquet", columns=["book", "chapter", "verse", "seg", "first_i", "last_i"]).to_pylist():
            ws = [(s["book"], s["chapter"], s["verse"], i) for i in range(s["first_i"], s["last_i"] + 1)]
            cs = [per_word.get(w) for w in ws]
            row = {k: s[k] for k in ("book", "chapter", "verse", "seg")}
            for f in FIELDS:
                row[f], sh = majority([None if c is None else (c[f] or "") for c in cs])
                if f == "quote":
                    row["speech_share"] = sh
                row[f + "_model"], _ = majority([None if c is None or c[f + "_model"] is None else c[f + "_model"] for c in cs])
            if not row["quote"] and not row["quote_model"]:
                continue
            row["speech_basis"] = "linked" if row["quote"] else ""
            L = layer.get(row["quote"] or "", {})
            old = row["addressee"]
            a = L.get("addressee", "")
            if a.split(":")[0] not in HEARERS:                       # a key term or a place is not a hearer (k1 kept none)
                a = ""
            row["addressee"] = code(a) if a else None
            row["addressee_basis"] = L.get("basis", "") if a else ""
            row["addressee_member"] = code(L["member_of_plural"]) if L.get("member_of_plural") else ""
            if row["quote"] and old != row["addressee"]:
                n["addressee_changed_by_layer"] += 1
            row["addressee_number_layer"], row["addressee_number_layer_basis"] = L.get("number", ""), L.get("number_basis", "")
            nums = {x for w in ws for x in second.get(w, [])}
            row["addressee_number_form"] = "" if not nums else (nums.pop() if len(nums) == 1 else "mixed")
            if row["addressee_number_form"] in ("singular", "plural"):
                row["addressee_number"], row["addressee_number_basis"] = row["addressee_number_form"], "form"
            else:
                row["addressee_number"], row["addressee_number_basis"] = row["addressee_number_layer"], row["addressee_number_layer_basis"]
            both = row["addressee_number_layer"] and row["addressee_number_form"] in ("singular", "plural")
            row["addressee_number_agree"] = (row["addressee_number_layer"] == row["addressee_number_form"]) if both else None
            if both:
                n["number_both"] += 1
                n["number_agree"] += row["addressee_number_agree"]
            for f in FIELDS:
                n[f] += bool(row[f]); n[f + "_model"] += bool(row[f + "_model"])
            n["addressee_number"] += bool(row["addressee_number"]); n["addressee_number_form"] += row["addressee_number_form"] in ("singular", "plural")
            rows.append(row)
        n["segments"] = len(rows)
        cols = [("book", pa.string()), ("chapter", pa.int16()), ("verse", pa.int16()), ("seg", pa.int16()),
                ("quote", pa.string()), ("speaker", pa.string()), ("addressee", pa.string()), ("speech_basis", pa.string()),
                ("speech_share", pa.float32()), ("addressee_number", pa.string()), ("addressee_number_basis", pa.string()),
                ("addressee_number_form", pa.string()), ("addressee_number_layer", pa.string()), ("addressee_number_layer_basis", pa.string()),
                ("addressee_number_agree", pa.bool_()), ("addressee_basis", pa.string()), ("addressee_member", pa.string()),
                ("quote_model", pa.string()), ("speaker_model", pa.string()),
                ("addressee_model", pa.string())]
        (out / ed).mkdir(parents=True, exist_ok=True)
        fp = out / ed / "speech.parquet"
        pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema(cols)), fp, compression="zstd")
        used = {r[f] for r in rows for f in ("speaker", "addressee", "addressee_member", "speaker_model", "addressee_model") if r[f]}
        ents = []
        with open(k1 / ed / "participants.tsv", encoding="utf-8") as fh:
            for e in csv.DictReader(fh, delimiter="\t"):
                ents.append({"ent": e["ent"], "kind": e["ent"].split(":")[0], "type": e["type"], "name": e["name"] or "",
                             "name_basis": e["name_basis"] or "", "ent_basis": e["ent_basis"] or ""})
        word = {}
        for e in ents:
            word.setdefault(e["kind"], e["type"])
        for x in sorted(used - {e["ent"] for e in ents}):
            ents.append({"ent": x, "kind": x.split(":")[0], "type": word.get(x.split(":")[0], ""), "name": "", "name_basis": "",
                         "ent_basis": "layer"})
        missing = used - {e["ent"] for e in ents}
        ef = out / ed / "entities.parquet"
        pq.write_table(pa.Table.from_pylist(ents, schema=pa.schema([(c, pa.string()) for c in
                       ("ent", "kind", "type", "name", "name_basis", "ent_basis")])), ef, compression="zstd")
        build["editions"][ed] = {"counts": dict(sorted(n.items())), "entities": len(ents), "ids_not_in_entities": sorted(missing)[:20],
                                 "number_agree_share": round(n["number_agree"] / max(1, n["number_both"]), 4),
                                 "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (fp, ef)}}
        print(f"[hebrew_nt_speech] {ed}: {dict(sorted(n.items()))}; entities {len(ents)}, ids missing {len(missing)}")
    (out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--analysis", type=Path, required=True)
    ap.add_argument("--features", type=Path, required=True)
    ap.add_argument("--k1", type=Path, required=True)
    ap.add_argument("--addressees", type=Path, required=True)
    ap.add_argument("--entities", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    run(a.analysis, a.features, a.k1, a.addressees, a.entities, a.out)


if __name__ == "__main__":
    main()
