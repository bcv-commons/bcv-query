"""Source-side ontology, phases 1 and 2a (internal-docs/ontology-design-note-2026-11-17.md; research's order of demand):
one id space for lexemes, senses, domains and concepts, the mentions that evoke them, lexeme `rendered_by` with tiers, and
`aligned_to` between mentions (Septuagint, the two Hebrew NTs). Tables are the source of truth; no RDF export yet.

    python -m macula.build_source_ontology [--out macula/data/source-ontology]

Inputs (local copies of published bcv-commons datasets; their revisions are recorded in build.json):
  hebrew-word-concepts-model v0.6   concepts (code, strong, ubs_sense), tokens (Tanakh word -> concept, labeller, confidence),
                                    concept_greek (Hebrew concept -> Greek lexeme, share)
  greek-nt-concepts-model v0.1      Greek NT word -> concept
  word-senses v0.1                  word -> UBS sense, domains
  hebrew-greek-bridge v0.1          lexeme pairs with tier, count, share (computed)
  hebrew-greek-lexeme-bridge-model v0.3   model-chosen lexeme pairs (Jev)
  hebrew-nt-bridge v0.1             Greek NT word -> Hebrew NT word part, per edition
  the bridge corpus (hebrew-greek-cf build b15)   Tanakh word -> Septuagint word (MACULA's alignment, `lxx` edge, GLAUx ids)

Domains (from 2026-11-18) are namespaced by system, `dom:sdbh:<code>` (Hebrew) and `dom:ln:<code>` (Greek: Louw-Nida domain and
subdomain), an SDBH "a;b" is split into its two domains, and each code has `broader` to its parent (3-digit segments). With
--commentary, the terms of hebrew-commentary-terms join as class `term` (`described_by` mention -> term, `spells` term ->
lexeme, `on_list` term -> `list`). build.json records integrity checks (dangling ids, broader cycles, Latin letters in lemmas
other than the homonym markers).

Ids (stable, become URIs later):  lexeme `lex:H0001` / `lex:G3962` (Aramaic under H, as Strong's) · concept `con:H1.1` · sense
`sense:<UBS sense id>` · domain `dom:<UBS domain code>` · mention: a MACULA word id `w:010010010011` (Tanakh) / `w:n40001001001`
(Greek NT), a GLAUx id `w:glx:104873137` (Septuagint), `w:heb_scg:MAT.1.1.3.0` (Hebrew NT edition, book, chapter, verse, word,
part).

OUT gets:
  classes.parquet     id, class (lexeme | concept | sense | domain), lang, lemma (Hebrew/Greek; empty for codes)
  relations.parquet   subject, relation, object, kind (asserted | derived), method (source | computed | model), source (dataset
                      version), confidence, count, share, tier
                      relations: concept_of, sense_of, from_sense, in_domain, rendered_by (lexeme <-> lexeme; concept -> lexeme)
  mentions.parquet    mention, text, lexeme, concept, concept_labeller, concept_confidence, sense
  aligned.parquet     mention, other, edition (septuagint | heb_scg | heb_mod), basis (the source's own label), method
  build.json          inputs with revisions, counts
No English: lemmas are Hebrew and Greek (MACULA's homonym markers "(I)", "(II)" kept), codes are codes; UBS definitions are never
read. Concepts `con:H0.*` belong to words without a Strong's number and have no `concept_of`.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DOCS = ROOT / "internal-docs"
INPUTS = {
    "hebrew-word-concepts-model": ("v0.6", "dbdb2c9f", DOCS / "hebrew-word-concepts-model-release" / "v0.6-release" / "data"),
    "greek-nt-concepts-model": ("v0.1", "6f73ed21", DOCS / "greek-nt-concepts-model-release" / "v0.1" / "data"),
    "word-senses": ("v0.1", "00690ee3", DOCS / "word-senses-release" / "v0.1" / "data"),
    "hebrew-greek-bridge": ("v0.1", "1bee0403", DOCS / "hebrew-greek-bridge-release" / "v0.1" / "data"),
    "hebrew-greek-lexeme-bridge-model": ("v0.3", "ffcb5e7c", DOCS / "lexeme-bridge-model-release" / "v0.3"),
    "hebrew-nt-bridge": ("v0.1", "525db08f", DOCS / "hebrew-nt-bridge-release" / "v0.1" / "links"),
}
CORPUS = HERE / "data" / "bridge-corpus" / "dev-builds" / "b15"


def domain_chain(code: str) -> list[str]:
    """A UBS domain code and its ancestors, narrowest first: SDBH and Louw-Nida codes are 3-digit segments
    ("001001002" -> 001001002, 001001, 001; Louw-Nida "033005" -> 033005, 033)."""
    return [code[:n] for n in range(len(code), 0, -3) if n % 3 == 0]


def src(name):
    return f"{name}@{INPUTS[name][0]}"


def lex(s: str | int | None, side: str) -> str | None:
    s = str(s or "").strip().upper().lstrip("HG")
    m = re.match(r"0*(\d+)", s)
    return f"lex:{side}{int(m.group(1)):04d}" if m and int(m.group(1)) else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=HERE / "data" / "source-ontology")
    ap.add_argument("--commentary", type=Path, help="a hebrew-commentary-terms build folder (statements.jsonl, terms.tsv, lists.tsv)")
    a = ap.parse_args()
    import pyarrow as pa
    import pyarrow.parquet as pq
    from macula import build_bridge_corpus as B
    api = B.load(CORPUS)
    F, L, E = api.F, api.L, api.E

    classes: dict[str, dict] = {}
    rel: list[dict] = []
    seen_rel = set()

    def cls(i, c, lang="", lemma=""):
        if i and i not in classes:
            classes[i] = {"id": i, "class": c, "lang": lang, "lemma": lemma}
        elif i and lemma and not classes[i]["lemma"]:
            classes[i]["lemma"] = lemma

    def R(s, r, o, kind, method, source, confidence=None, count=None, share=None, tier=""):
        k = (s, r, o, source, tier)
        if s and o and k not in seen_rel:
            seen_rel.add(k)
            rel.append({"subject": s, "relation": r, "object": o, "kind": kind, "method": method, "source": source,
                        "confidence": confidence, "count": count, "share": share, "tier": tier})

    # lexemes from the corpus (Tanakh, Greek NT, Septuagint), with their lemma
    word_lex, word_text = {}, {}
    for t in F.otype.s("text"):
        name = F.name.v(t)
        if name not in ("tanakh", "greek_nt", "septuagint"):
            continue
        side = "H" if name == "tanakh" else "G"
        for w in L.d(t, otype="word"):
            lx = lex(F.strong.v(w), side)
            if lx:
                cls(lx, "lexeme", "hbo" if side == "H" else "grc", F.lemma.v(w) or "")
            mid = F.mid.v(w) if name != "septuagint" else None
            gid = F.glx_id.v(w) if name == "septuagint" else None
            m = f"w:{mid}" if mid else (f"w:glx:{gid}" if gid else None)
            if m:
                word_lex[w] = (m, lx, name)

    # concepts (Hebrew v0.6) and their senses
    ccode = pq.read_table(INPUTS["hebrew-word-concepts-model"][2] / "concepts.parquet").to_pylist()
    for r in ccode:
        c = f"con:{r['code']}"
        cls(c, "concept", "hbo")
        lx = lex(r["strong"], "H")
        if lx:
            R(c, "concept_of", lx, "derived", "model", src("hebrew-word-concepts-model"))
        if r.get("ubs_sense"):
            s = f"sense:{r['ubs_sense']}"
            cls(s, "sense", "hbo")
            R(c, "from_sense", s, "asserted", "source", src("hebrew-word-concepts-model"))
    for r in pq.read_table(INPUTS["hebrew-word-concepts-model"][2] / "concept_greek.parquet").to_pylist():
        lx = lex(r["greek_strong"], "G")
        if lx and r["count"] >= 3:
            R(f"con:{r['concept']}", "rendered_by", lx, "derived", "model", src("hebrew-word-concepts-model"),
              count=r["count"], share=r["share_in_concept"], tier="septuagint")

    # mentions: Tanakh (concept tokens) and Greek NT (Greek NT concepts), with UBS senses
    by_mid = {m: (lx, name) for w, (m, lx, name) in word_lex.items()}
    mentions: dict[str, dict] = {}
    for w, (m, lx, name) in word_lex.items():
        mentions[m] = {"mention": m, "text": name, "lexeme": lx, "concept": None, "concept_labeller": None,
                       "concept_confidence": None, "sense": None}
    for r in pq.read_table(INPUTS["hebrew-word-concepts-model"][2] / "tokens.parquet",
                           columns=["key", "concept", "labeller", "jev_confidence"]).to_pylist():
        m = mentions.get(f"w:{r['key']}")
        if m and r["concept"]:
            m.update(concept=f"con:{r['concept']}", concept_labeller=r["labeller"], concept_confidence=r["jev_confidence"])
    for r in pq.read_table(INPUTS["greek-nt-concepts-model"][2] / "words.parquet",
                           columns=["greek_id", "concept", "labeller", "confidence", "none"]).to_pylist():
        m = mentions.get(f"w:{r['greek_id'].lstrip('n')}") or mentions.get(f"w:{r['greek_id']}")
        if m and r["concept"] and not r["none"]:
            m.update(concept=f"con:{r['concept']}", concept_labeller=r["labeller"], concept_confidence=r["confidence"])
    sense_lex = collections.defaultdict(collections.Counter)
    for r in pq.read_table(INPUTS["word-senses"][2] / "words.parquet", columns=["key", "lang", "sense", "domains", "subdomains"]).to_pylist():
        if not r["sense"]:
            continue
        m = mentions.get(f"w:{r['key']}") or mentions.get(f"w:{r['key'].lstrip('n')}")
        s = f"sense:{r['sense']}"
        cls(s, "sense", r["lang"])
        if m:
            m["sense"] = s
            if m["lexeme"]:
                sense_lex[s][m["lexeme"]] += 1
        system = "sdbh" if r["lang"] == "hbo" else "ln"
        codes = (r["domains"] or "").split() + ((r.get("subdomains") or "").split() if system == "ln" else [])
        for d in {x for c in codes for x in c.split(";") if x}:      # an SDBH "a;b" is two domains
            for i, d2 in enumerate(domain_chain(d)):
                cls(f"dom:{system}:{d2}", "domain", system)
                if i:
                    R(f"dom:{system}:{prev}", "broader", f"dom:{system}:{d2}", "asserted", "source", src("word-senses"))
                prev = d2
            R(s, "in_domain", f"dom:{system}:{d}", "asserted", "source", src("word-senses"))
    for s, c in sense_lex.items():
        R(s, "sense_of", c.most_common(1)[0][0], "asserted", "source", src("word-senses"), count=sum(c.values()))

    # lexeme rendered_by: computed tiers, then the model tier
    for r in pq.read_table(INPUTS["hebrew-greek-bridge"][2] / "lexemes.parquet").to_pylist():
        h, g = lex(r["hebrew_strong"], "H"), lex(r["greek_strong"], "G")
        cls(h, "lexeme", "hbo", r.get("hebrew_lemma") or ""), cls(g, "lexeme", "grc", r.get("greek_lemma") or "")
        R(h, "rendered_by", g, "derived", "computed", src("hebrew-greek-bridge"), count=r["count"], share=r["score"], tier=r["tier"])
    with open(INPUTS["hebrew-greek-lexeme-bridge-model"][2] / "pairs.tsv", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            h, g = lex(r["hebrew_strong"], "H"), lex(r["greek_strong"], "G")
            cls(h, "lexeme", "hbo", r.get("hebrew_lemma") or ""), cls(g, "lexeme", "grc", r.get("greek_lemma") or "")
            p = float(r.get("p") or 0) or None
            R(h, "rendered_by", g, "derived", "model", src("hebrew-greek-lexeme-bridge-model"), confidence=p, tier="model")

    # aligned_to: Tanakh -> Septuagint (MACULA's alignment), Greek NT -> Hebrew NT parts
    aligned = []
    tan = next(t for t in F.otype.s("text") if F.name.v(t) == "tanakh")
    for w in L.d(tan, otype="word"):
        m = word_lex.get(w, (None,))[0]
        for g, label in (E.lxx.f(w) or ()):
            o = word_lex.get(int(g), (None,))[0]
            if m and o:
                aligned.append({"mention": m, "other": o, "edition": "septuagint", "basis": label, "method": "source"})
    for ed in ("heb_scg", "heb_mod"):
        for r in pq.read_table(INPUTS["hebrew-nt-bridge"][2] / f"{ed}.parquet").to_pylist():
            m = f"w:{r['greek_id'].lstrip('n')}"
            if m not in mentions:
                m = f"w:{r['greek_id']}"
            o = f"w:{ed}:{r['book']}.{r['chapter']}.{r['verse']}.{r['i']}.{r['part']}"
            aligned.append({"mention": m, "other": o, "edition": ed, "basis": r.get("link") or "",
                            "method": "model" if r.get("source") == "model" else (r.get("source") or "")})

    # commentary terms (hebrew-commentary-terms): a term class, the words a commentator explains with it, the lexeme it spells,
    # the sages' lists it is on. Relation `described_by` (mention -> term), tier = what the statement says (sense, gloss …),
    # source = the witness; `spells` (term -> lexeme); `on_list` (term -> list); `member_of` for a list's members.
    if a.commentary:
        csrc = "hebrew-commentary-terms@" + a.commentary.name
        for line in (a.commentary / "terms.tsv").read_text(encoding="utf-8").splitlines()[1:]:
            t, n, says, strong, lists = line.split("\t")
            cls(f"term:{t}", "term", "hbo", t)
            if strong:
                R(f"term:{t}", "spells", f"lex:{strong}", "asserted", "computed", csrc)
            for l in filter(None, lists.split("|")):
                cls(f"list:{l}", "list", "hbo")
                R(f"term:{t}", "on_list", f"list:{l}", "asserted", "source", csrc)
        for l in (json.loads(x) for x in (a.commentary / "statements.jsonl").open(encoding="utf-8")):
            if not l["term"] or l["witness"] != "metzudat_zion":
                continue
            for k in (l["subject_first"], l["subject_last"]):
                m = f"w:{k}"
                if m in mentions and mentions[m].get("lexeme"):
                    R(m, "described_by", f"term:{l['term']}", "asserted", "source", f"{csrc}:{l['witness']}", tier=l["says"])
                    break

    # integrity: every relation end is a class or a mention; no cycle in broader; lemmas are Hebrew or Greek only
    ids = set(classes) | set(mentions)
    dangling = collections.Counter(r["relation"] for r in rel for e in (r["subject"], r["object"]) if e not in ids)
    up = collections.defaultdict(set)
    for r in rel:
        if r["relation"] == "broader":
            up[r["subject"]].add(r["object"])

    def cyclic(n, seen=()):
        return n in seen or any(cyclic(m, seen + (n,)) for m in up.get(n, ()))
    cycles = sum(cyclic(n) for n in up)
    latin = sum(1 for c in classes.values() if re.search(r"[A-Za-z]", re.sub(r"\((?:I|II|III|IV)\)", "", c["lemma"] or "")))
    integrity = {"dangling_by_relation": dict(dangling), "broader_cycles": cycles, "lemmas_with_latin_letters": latin}

    a.out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(sorted(classes.values(), key=lambda x: x["id"])), a.out / "classes.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(rel), a.out / "relations.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(list(mentions.values())), a.out / "mentions.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(aligned), a.out / "aligned.parquet", compression="zstd")
    counts = {"classes": dict(collections.Counter(c["class"] for c in classes.values())),
              "relations": dict(collections.Counter((r["relation"], r["method"]) for r in rel).most_common()),
              "mentions": dict(collections.Counter(m["text"] for m in mentions.values())),
              "mentions with concept": dict(collections.Counter(m["text"] for m in mentions.values() if m["concept"])),
              "mentions with sense": dict(collections.Counter(m["text"] for m in mentions.values() if m["sense"])),
              "aligned": dict(collections.Counter(x["edition"] for x in aligned)), "integrity": integrity}
    counts["relations"] = {f"{k[0]} ({k[1]})": v for k, v in counts["relations"].items()}
    (a.out / "build.json").write_text(json.dumps({"inputs": {k: {"version": v[0], "revision": v[1]} for k, v in INPUTS.items()},
                                                   "corpus": str(CORPUS.name), "counts": counts}, ensure_ascii=False, indent=1))
    print(json.dumps(counts, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
