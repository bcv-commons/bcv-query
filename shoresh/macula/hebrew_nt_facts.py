"""Source facts on the Hebrew New Testaments (Salkinson-Ginsburg, Delitzsch), for their use as a source text.

Three tables, each built from pinned inputs:

  clauses   facts read from the Hebrew words of each clause segment alone: the verb (lexeme, form, person, stem, number,
            gender), the negator, the leading conjunction, a question word, the speech introduction. Nothing Greek goes in.
  agree     per Greek word that both Hebrew texts link to: whether the two translators chose the same lexeme and the same
            form. The Greek word only pairs the two places; none of its features is read.
  carried   facts about the content of the text, which are the same in any translation, moved from the Greek onto the
            Hebrew through the word links: the entity a word refers to; per clause segment the speech level, the speaker and
            the quotation. Each row keeps the link class, so the user can weight by it.

  python -m macula.hebrew_nt_facts --analysis DIR --morph DIR --bridge DIR --ontology DIR --layout FILE --out OUT

  --analysis  hebrew-nt-analysis release folder (heb_scg/, heb_mod/ with words.parquet, clauses.parquet)
  --morph     output of macula.hebrew_nt_morph
  --bridge    hebrew-nt-bridge data folder (heb_scg/links.parquet, heb_mod/links.parquet)
  --ontology  a source-ontology release (data/entity_relations.parquet, data/propositions.parquet)
  --layout    greek-nt-clause-layout clauses.parquet (which Greek word belongs to which clause; quotation ids)

Codes are Strong's numbers and MACULA's own labels; there is no English content in the tables.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import sqlite3
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
FINITE = {"qatal", "wayyiqtol", "yiqtol", "weqatal", "imperative", "jussive", "cohortative"}
NEG = {"3808", "0408", "0369", "0370", "1077", "1097", "1115"}          # לֹא אַל אַיִן בַּל בְּלִי בִּלְתִּי
INTERROG = {"1886b", "4310", "4100", "4101", "0349", "0335", "0346", "0375", "0575", "4069", "4970"}
LE, AMAR = {"3807a", "3807b", "3807z"}, "0559"
CONTENT = {"noun", "verb", "adj", "adv", "num"}
EDITIONS = ("heb_scg", "heb_mod")


def speech_verbs(min_n: int = 5) -> dict[str, int]:
    """Strong's numbers of the verbs that introduce a quotation in the Tanakh at least `min_n` times (quote-frames)"""
    keys = collections.Counter()
    with (HERE / "data" / "quote-frames" / "clauses.tsv").open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r["corpus"] == "hbo" and r["speech_verb"]:
                keys[r["speech_verb"]] += 1
    strong = dict(sqlite3.connect(HERE / "trees-macula.db").execute("select key, strong from words where corpus = 'hbo' and class = 'verb'"))
    c = collections.Counter()
    for k, n in keys.items():
        if strong.get(k):
            c[strong[k]] += n
    return {s: n for s, n in c.items() if n >= min_n}


def load_edition(analysis: Path, morph: Path, ed: str) -> tuple[dict, list[dict]]:
    """words: (book, chapter, verse, i) -> parts in order, each with its morphology; and the clause rows"""
    m = {(r["book"], r["chapter"], r["verse"], r["i"], r["part"]): r for r in pq.read_table(morph / ed / "morph.parquet").to_pylist()}
    words: dict = collections.defaultdict(list)
    for r in pq.read_table(analysis / ed / "words.parquet").to_pylist():
        if r["source"] is None:
            continue
        mm = m.get((r["book"], r["chapter"], r["verse"], r["i"], r["part"]), {})
        r.update({k: mm.get(k) or "" for k in ("stem", "number", "gender", "state", "basis")})
        if not r["person"]:
            r["person"] = mm.get("person") or ""
        words[(r["book"], r["chapter"], r["verse"], r["i"])].append(r)
    for parts in words.values():
        parts.sort(key=lambda r: r["part"])
    return words, pq.read_table(analysis / ed / "clauses.parquet").to_pylist()


def word_marks(parts: list[dict]) -> dict:
    """what the written word shows about definiteness: an article, a suffixed pronoun, the construct state"""
    cls = [p["class"] for p in parts]
    head = next((p for p in parts if p["class"] in CONTENT), None)
    return {"art": "art" in cls,
            "suffix": bool(head) and any(p["class"] == "pron" and p["part"] > head["part"] for p in parts),
            "construct": bool(head) and head["state"] == "construct"}


def clause_table(words: dict, clauses: list[dict], speech: dict[str, int]) -> list[dict]:
    out = []
    for c in clauses:
        ws = [words[(c["book"], c["chapter"], c["verse"], i)] for i in range(c["first_i"], c["last_i"] + 1)
              if (c["book"], c["chapter"], c["verse"], i) in words]
        parts = [p for w in ws for p in w]
        verbs = [p for p in parts if p["class"] == "verb"]
        verb = next((p for p in verbs if p["form"] in FINITE), verbs[0] if verbs else None)
        lead = []
        for p in (ws[0] if ws else []):
            if p["class"] in ("cj", "rel"):
                lead.append(p["strong"] or "")
            else:
                break
        neg = next((p["strong"] for p in parts if p["strong"] in NEG), "")
        lemor = any(len(w) >= 2 and w[-1]["strong"] == AMAR and w[-1]["form"] == "infinitive construct" and w[-2]["strong"] in LE for w in ws)
        out.append({"book": c["book"], "chapter": c["chapter"], "verse": c["verse"], "seg": c["seg"], "n_words": len(ws),
                    "verb": (verb or {}).get("strong") or "", "verb_form": (verb or {}).get("form") or "", "person": (verb or {}).get("person") or "",
                    "stem": (verb or {}).get("stem") or "", "number": (verb or {}).get("number") or "", "gender": (verb or {}).get("gender") or "",
                    "verb_basis": (verb or {}).get("basis") or "", "neg": neg, "conj": "+".join(lead),
                    "interrog": next((p["strong"] for p in parts if p["strong"] in INTERROG), ""), "lemor": lemor,
                    "speech_verb": bool(verb) and (verb["strong"] or "") in speech,
                    "subject": any(p["role"] == "s" for p in parts)})
    return out


def links_of(bridge: Path, ed: str) -> list[dict]:
    return pq.read_table(bridge / ed / "links.parquet", columns=["greek_id", "book", "chapter", "verse", "i", "part", "hebrew_strong",
                                                                 "hebrew_class", "link", "tanakh"]).to_pylist()


def agree_table(eds: dict, bridge: Path) -> list[dict]:
    per: dict = {ed: collections.defaultdict(list) for ed in EDITIONS}
    for ed in EDITIONS:
        words = eds[ed][0]
        for l in links_of(bridge, ed):
            w = words.get((l["book"], l["chapter"], l["verse"], l["i"]))
            p = next((x for x in (w or []) if x["part"] == l["part"]), None)
            if p is not None:
                per[ed][l["greek_id"]].append((p, w, l))
    out = []
    for gid in sorted(set(per["heb_scg"]) | set(per["heb_mod"])):
        row = {"greek_id": gid}
        heads = {}
        for ed in EDITIONS:
            content = [(p, w, l) for p, w, l in per[ed].get(gid, []) if p["class"] in CONTENT]
            row[f"{ed}_strongs"] = sorted({p["strong"] for p, _, _ in content if p["strong"]})
            row[f"{ed}_links"] = len(per[ed].get(gid, []))
            row[f"{ed}_link"] = sorted({l["link"] for _, _, l in per[ed].get(gid, [])})
            row[f"{ed}_tanakh"] = any(l["tanakh"] for _, _, l in per[ed].get(gid, []))
            heads[ed] = content[0] if content else None
        a, b = set(row["heb_scg_strongs"]), set(row["heb_mod_strongs"])
        both = bool(per["heb_scg"].get(gid)) and bool(per["heb_mod"].get(gid))
        row["lexeme"] = ("one_text" if not both else "function" if not a and not b else "same" if a & b
                         else "one_content" if not a or not b else "differ")
        for feat in ("class", "form", "stem", "number", "gender", "person"):
            x, y = ((heads[ed][0][feat] or "") if heads[ed] else "" for ed in EDITIONS)
            row[feat] = "" if not (x and y) else "same" if x == y else "differ"
        mk = {ed: word_marks(heads[ed][1]) if heads[ed] else None for ed in EDITIONS}
        for k in ("art", "suffix", "construct"):
            row[k] = "" if not (mk["heb_scg"] and mk["heb_mod"]) else "same" if mk["heb_scg"][k] == mk["heb_mod"][k] else "differ"
        out.append(row)
    return out


def carried_tables(eds: dict, bridge: Path, ontology: Path, layout: Path, ed: str, we: Path | None = None,
                   refstatus: Path | None = None, addressees: Path | None = None) -> tuple[list[dict], list[dict]]:
    """Content facts only. From the reference-status layer the status and the animacy are carried, never its `definite`
    column, which describes the Greek wording."""
    we_of = {r["key"]: r["value"] for r in pq.read_table(we).to_pylist() if r["lang"] == "grc" and r["value"] in ("i", "e")} if we else {}
    ref_of = {r["head"]: r for r in pq.read_table(refstatus, columns=["head", "status", "animacy"]).to_pylist() if r["status"] != "unresolved"} if refstatus else {}
    addr_of = {r["quote"]: r["addressee"] or "" for r in pq.read_table(addressees).to_pylist() if r["corpus"] == "grc"} if addressees else {}
    ent = {}
    for r in pq.read_table(ontology / "data" / "entity_relations.parquet").to_pylist():
        if r["relation"] == "refers_to" and len(r["subject"]) == 13:           # w: + 11 digits: a Greek NT word
            ent[r["subject"][2:]] = r
    prop = {r["prop"][5:]: r for r in pq.read_table(ontology / "data" / "propositions.parquet").to_pylist() if r["lang"] == "grc"}
    clause_of, quotation = {}, {}
    for r in pq.read_table(layout, columns=["clause", "words", "quotation"]).to_pylist():
        for k in r["words"]:
            clause_of[k] = r["clause"]
        quotation[r["clause"]] = r["quotation"] or ""
    words, clauses = eds[ed]
    seg_of = {}
    for c in clauses:
        for i in range(c["first_i"], c["last_i"] + 1):
            seg_of[(c["book"], c["chapter"], c["verse"], i)] = c["seg"]
    wrows, votes = [], collections.defaultdict(collections.Counter)
    for l in links_of(bridge, ed):
        g = l["greek_id"][1:]
        e = ent.get(g)
        if e is not None or g in we_of or g in ref_of:
            e, rf = e or {}, ref_of.get(g, {})
            wrows.append({"book": l["book"], "chapter": l["chapter"], "verse": l["verse"], "i": l["i"], "part": l["part"],
                          "greek_id": l["greek_id"], "link": l["link"], "entity": e.get("object") or "", "kind": e.get("kind") or "",
                          "route": e.get("route") or "", "agree": e.get("agree"), "we": we_of.get(g, ""),
                          "ref_status": rf.get("status") or "", "animacy": rf.get("animacy") or ""})
        s = seg_of.get((l["book"], l["chapter"], l["verse"], l["i"]))
        if s is not None and g in clause_of:
            votes[(l["book"], l["chapter"], l["verse"], s)][clause_of[g]] += 1
    crows, last = [], (None, None)
    for (b, ch, v, s), c in sorted(votes.items()):
        cl, n = c.most_common(1)[0]
        p = prop.get(cl, {})
        q = quotation.get(cl, "")
        crows.append({"book": b, "chapter": ch, "verse": v, "seg": s, "greek_clause": cl, "links": sum(c.values()),
                      "share": round(n / sum(c.values()), 3), "speech": p.get("speech"), "speaker": p.get("speaker_id") or "",
                      "quotation": q, "addressee": addr_of.get(q, ""), "opens": bool(q) and (b, q) != last})
        last = (b, q)
    return wrows, crows


def write(rows: list[dict], path: Path) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")
    return {"rows": len(rows), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for k in ("analysis", "morph", "bridge", "ontology", "layout", "out"):
        ap.add_argument(f"--{k}", type=Path, required=True)
    ap.add_argument("--we", type=Path, help="inclusive-we words.parquet: carries inclusive or exclusive onto first-person plural parts")
    ap.add_argument("--refstatus", type=Path, help="reference-status greek-nt.parquet: carries given / new and animacy onto the linked parts")
    ap.add_argument("--addressees", type=Path, help="addressees quotations.parquet: carries the addressee of a quotation onto its segments")
    a = ap.parse_args()
    speech = speech_verbs()
    eds = {ed: load_edition(a.analysis, a.morph, ed) for ed in EDITIONS}
    build: dict = {"inputs": {k: str(getattr(a, k)) for k in ("analysis", "morph", "bridge", "ontology", "layout", "we", "refstatus", "addressees")},
                   "speech_verbs": dict(sorted(speech.items(), key=lambda x: -x[1])), "tables": {}}
    for ed in EDITIONS:
        rows = clause_table(eds[ed][0], eds[ed][1], speech)
        build["tables"][f"{ed}/clauses"] = {**write(rows, a.out / ed / "clause_facts.parquet"),
                                            "with_verb": sum(bool(r["verb"]) for r in rows), "neg": sum(bool(r["neg"]) for r in rows),
                                            "interrog": sum(bool(r["interrog"]) for r in rows), "lemor": sum(r["lemor"] for r in rows),
                                            "speech_verb": sum(r["speech_verb"] for r in rows)}
        wrows, crows = carried_tables(eds, a.bridge, a.ontology, a.layout, ed, a.we, a.refstatus, a.addressees)
        build["tables"][f"{ed}/carried_words"] = {**write(wrows, a.out / ed / "carried_words.parquet"), "entity": sum(bool(r["entity"]) for r in wrows),
                                                  "we": dict(collections.Counter(r["we"] for r in wrows if r["we"])),
                                                  "ref_status": dict(collections.Counter(r["ref_status"] for r in wrows if r["ref_status"]))}
        build["tables"][f"{ed}/carried_clauses"] = {**write(crows, a.out / ed / "carried_clauses.parquet"),
                                                    "segments": len(eds[ed][1]), "opens": sum(r["opens"] for r in crows),
                                                    "addressee": sum(bool(r["addressee"]) for r in crows),
                                                    "share_1": sum(r["share"] == 1 for r in crows)}
    rows = agree_table(eds, a.bridge)
    c = collections.Counter(r["lexeme"] for r in rows)
    build["tables"]["agree"] = {**write(rows, a.out / "agree.parquet"), "lexeme": dict(c),
                                **{k: dict(collections.Counter(r[k] for r in rows if r[k])) for k in
                                   ("form", "stem", "number", "gender", "person", "art", "suffix", "construct")}}
    (a.out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(build["tables"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
