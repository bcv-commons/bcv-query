"""Entity ids and family relations from ACAI, on MACULA word ids, joined to our character tables (development plan, step 0.4).

Source: BibleAquifer/ACAI (ACAI Biblical Entity Data, (c) Mission Mutual / BiblioNexus, CC BY-SA 4.0), release tag v2026-11-07,
commit 5375d0d334bb6d635ef1813e4d3df58eb30efcca: one JSON record per entity in people/ places/ groups/ deities/ realia/ flora/
fauna/ keyterms/, with word links to WLC (= MACULA Hebrew ids, `o` + BBCCCVVVWWWP) and to SBLGNT (MACULA Greek's SBLGNT ids,
`n` + BBCCCVVVWWW). Our Greek is MACULA Nestle 1904, so the SBLGNT ids are carried over to Nestle 1904 ids by aligning the two
MACULA Greek editions chapter by chapter on their (normalised) lemmas: Clear-Bible/macula-greek SBLGNT/tsv (CC BY 4.0), pinned.

Fetch (once; the downloads are data, read as JSON / TSV only, nothing in them is run):

    cd shoresh/macula/data/entities
    GIT_LFS_SKIP_SMUDGE=1 git -c core.hooksPath=/dev/null clone --depth 1 --branch v2026-11-07 \\
        https://github.com/BibleAquifer/ACAI.git acai-src
    mkdir macula-greek-sblgnt-src && curl -sSL -o macula-greek-sblgnt-src/sblgnt.tsv \\
        https://raw.githubusercontent.com/Clear-Bible/macula-greek/8423afe47b9e8f24b7772e808af45c7159a6fe7e/SBLGNT/tsv/macula-greek-SBLGNT.tsv

Build (from shoresh/):  .venv/bin/python3 -m macula.build_entities

Output (shoresh/macula/data/entities/, git-ignored):
- entity_words.tsv: word (MACULA key, our layers' form: Hebrew 12 digits, Greek Nestle 1904 11 digits), entity (ACAI primary id),
  form (the ACAI record of the name form, when it is not the primary one: person:Abram under person:Abraham), kind (`explicit`,
  `pronominal`, `subject`, `speech`), instance (the first word of ACAI's instance: a phrase or a speech), quote_type (speech only,
  ACAI's / FCBH's code), source_word (ACAI's own word id: WLC or SBLGNT), map (Greek: `lemma` aligned on the lemma, `position`
  paired inside a block of the same length; Hebrew: `same`).
- entities.tsv: entity (ACAI id, opaque), primary, type, subtype (ACAI's type field per kind as a lower-case code), gender,
  lemmas (Hebrew / Aramaic / Greek, from ACAI), apocrypha_only, non_biblical, characters (our character ids joined to it), counts.
- kinship.tsv: entity, relation (father, mother, partner, offspring, sibling, tribe, group_origin, birth_place, death_place,
  possibly_same_as), other.
- characters.tsv: our character id -> ACAI entity, the rule(s) that joined it, the votes, conflicts.
- checks.md, build.json.

No English content: ACAI's labels, descriptions, roles and alternate sources are not carried; its ids (English-based strings such
as `person:Aaron`, `person:Eleazar.2`) are carried as opaque external keys.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import csv
import datetime
import difflib
import glob
import hashlib
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "data" / "entities"
ACAI = OUT / "acai-src"
SBL = OUT / "macula-greek-sblgnt-src" / "sblgnt.tsv"
SBL_COMMIT = "8423afe47b9e8f24b7772e808af45c7159a6fe7e"
ACAI_TAG = "v2026-11-07"
SPINE = HERE / "macula-spine.db"
HEB_CHARS = REPO / "resources" / "speaker_layer" / "characters.tsv"
HEB_QUOT = HERE / "data" / "speaker-layer" / "quotations.tsv"
NT_CHARS = REPO / "resources" / "speaker_quotations" / "nt_characters.tsv"
NT_CLAUSES = HERE / "data" / "nt-clause-layout" / "clauses"

TYPES = ["people", "places", "groups", "deities", "realia", "flora", "fauna", "keyterms"]
SUBTYPE = {"group": "group_type", "deity": "deity_type", "realia": "realia_type", "flora": "flora_type",
           "fauna": "fauna_type", "keyterm": "keyterm_type"}
KINDS = {"explicit_instances": "explicit", "pronominal_referents": "pronominal", "subject_referents": "subject",
         "speeches": "speech"}
RELATIONS = [("father", "father"), ("mother", "mother"), ("partners", "partner"), ("offspring", "offspring"),
             ("siblings", "sibling"), ("tribe", "tribe"), ("group_origin", "group_origin"),
             ("possibly_same_as", "possibly_same_as")]
CONFLICT_SHARE = 0.5     # another entity tops a rule with at least this share of the rule's votes: a conflict


def code(s: str) -> str:
    """ACAI's English type value as a lower-case code ('Wild Trees and Shrubs' -> wild_trees_and_shrubs)."""
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def acai_commit() -> str:
    """The checked-out commit, read from the clone's HEAD file (git itself is not run inside the download)."""
    head = (ACAI / ".git" / "HEAD").read_text().strip()
    if head.startswith("ref:"):
        head = (ACAI / ".git" / head.split()[1]).read_text().strip()
    return head


# --- MACULA words ---------------------------------------------------------------------------------------------------------

def spine_words() -> tuple[dict[str, str], list[str], dict[str, str], list[str]]:
    """Hebrew key -> lemma, sorted Hebrew keys; Greek (Nestle 1904) key -> lemma, sorted Greek keys."""
    con = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    heb, grc = {}, {}
    for k, lang, lemma in con.execute("SELECT key, lang, lemma FROM macula_words"):
        (heb if lang == "hbo" else grc)[k] = lemma or ""
    return heb, sorted(heb), grc, sorted(grc)


def norm(s: str) -> str:
    """A spelling-tolerant lemma key for aligning SBLGNT with Nestle 1904 (Δαυίδ / Δαυείδ, Ἰωάννης / Ἰωάνης)."""
    s = "".join(c for c in unicodedata.normalize("NFD", s or "") if not unicodedata.combining(c)).lower().replace("ς", "σ")
    s = s.replace("ει", "ι")
    return re.sub(r"(.)\1", r"\1", s)


def sblgnt_to_nestle(grc: dict[str, str]) -> tuple[dict[str, tuple[str, str]], dict]:
    """SBLGNT key -> (Nestle 1904 key, method), aligning each chapter's lemma sequence; and figures."""
    sbl: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    with open(SBL, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            k = r["xml:id"][1:]
            sbl[k[:5]].append((k, r["lemma"]))
    nes: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    for k in sorted(grc):
        nes[k[:5]].append((k, grc[k]))
    out, fig = {}, collections.Counter()
    for ch, a in sbl.items():
        b = nes.get(ch, [])
        fig["sbl_words"] += len(a)
        sm = difflib.SequenceMatcher(None, [norm(x[1]) for x in a], [norm(x[1]) for x in b], autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                for i, j in zip(range(i1, i2), range(j1, j2)):
                    out[a[i][0]] = (b[j][0], "lemma")
            elif op == "replace" and i2 - i1 == j2 - j1:
                for i, j in zip(range(i1, i2), range(j1, j2)):
                    out[a[i][0]] = (b[j][0], "position")
    fig["mapped_lemma"] = sum(1 for v in out.values() if v[1] == "lemma")
    fig["mapped_position"] = sum(1 for v in out.values() if v[1] == "position")
    fig["same_id"] = sum(1 for k, v in out.items() if k == v[0])
    return out, dict(fig), set(k for ks in sbl.values() for k, _ in ks)


# --- ACAI ----------------------------------------------------------------------------------------------------------------

def read_acai() -> dict[str, dict]:
    recs = {}
    for t in TYPES:
        for f in sorted(glob.glob(str(ACAI / t / "json" / "*.json"))):
            d = json.loads(Path(f).read_text(encoding="utf-8"))
            recs[d["id"]] = d
    return recs


def links(d: dict):
    """(kind, edition, instance words, quote_type) for each word link of a record."""
    for field, kind in KINDS.items():
        for ed, insts in (d.get(field) or {}).items():
            for inst in insts:
                if kind == "speech":
                    yield kind, ed, inst.get("words") or [], inst.get("quote_type") or ""
                else:
                    yield kind, ed, inst, ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.parse_args()
    heb, heb_sorted, grc, grc_sorted = spine_words()
    g_map, g_fig, sbl_ids = sblgnt_to_nestle(grc)
    recs = read_acai()
    primary = {i: (d.get("primary_id") or i) for i, d in recs.items()}

    # --- entity_words ---
    rows, seen = [], set()
    cov = collections.Counter()
    bad = collections.defaultdict(list)
    alias_words: dict[tuple[str, str], str] = {}     # (primary, word) -> alias form id (explicit instances of non-primary records)
    subset = collections.Counter()
    by_prim_links: dict[str, set] = collections.defaultdict(set)
    for i, d in recs.items():
        if primary[i] == i:
            for kind, ed, inst, _ in links(d):
                by_prim_links[i].update((kind, w) for w in inst)
    for i, d in recs.items():
        p = primary[i]
        if p == i:
            continue
        for kind, ed, inst, _ in links(d):
            for w in inst:
                subset["alias_links"] += 1
                subset["alias_links_in_primary"] += (kind, w) in by_prim_links.get(p, ())
                if kind == "explicit":
                    alias_words[(p, w)] = i
    for i, d in recs.items():
        if primary[i] != i:
            continue
        for kind, ed, inst, qt in links(d):
            if not inst:
                continue
            first = None
            for w in inst:
                lang = "heb" if w.startswith("o") else "grc" if w.startswith("n") else "?"
                cov[(lang, kind, "links")] += 1
                k = w[1:]
                if lang == "heb":
                    key, how = k, "same"
                    if k not in heb and re.fullmatch(r"\d{12}\D+", k) and k[:12] in heb:
                        # speech words from speaker-quotations: the article folded into a preposition (בַּ = בְּ + הַ)
                        # has an id of its own there (…1ה); MACULA has the preposition only
                        key, how = k[:12], "article_in_prefix"
                    elif k not in heb and re.fullmatch(r"\d{12}", k):
                        part = [k[:11] + str(p) for p in range(int(k[11]) - 1, 0, -1) if k[:11] + str(p) in heb]
                        if part:                       # a word part MACULA does not have: the nearest part of the same word
                            key, how = part[0], "nearest_part"
                    if key not in heb:
                        cov[(lang, kind, "missing")] += 1
                        bad["heb"].append((i, kind, w))
                        continue
                    if how != "same":
                        cov[(lang, kind, how)] += 1
                elif lang == "grc":
                    if k not in sbl_ids:
                        cov[(lang, kind, "not_in_sblgnt")] += 1
                        bad["grc_sbl"].append((i, kind, w))
                        continue
                    if k not in g_map:
                        cov[(lang, kind, "unmapped")] += 1
                        bad["grc_map"].append((i, kind, w))
                        continue
                    key, how = g_map[k]
                else:
                    cov[(lang, kind, "missing")] += 1
                    bad["other"].append((i, kind, w))
                    continue
                first = first or key
                t = (key, i, kind, first)
                if t in seen:
                    cov[(lang, kind, "duplicate")] += 1
                    continue
                seen.add(t)
                rows.append((key, i, alias_words.get((i, w), ""), kind, first, qt, w, how))
    rows.sort(key=lambda r: (len(r[0]), r[0], r[1], r[3]))

    # lemma check of explicit instances: is the word's MACULA lemma one of the entity's lemmas?
    lem_check = collections.Counter()
    for key, ent, _, kind, *_ in rows:
        if kind != "explicit":
            continue
        lems = {norm(x) for v in (recs[ent].get("lemmas") or {}).values() for x in v for x in x.split()}
        if not lems:
            continue
        lang = "heb" if len(key) == 12 else "grc"
        lem = (heb if lang == "heb" else grc).get(key, "")
        t_ = recs[ent]["type"]
        lem_check[(lang, t_, "checked")] += 1
        lem_check[(lang, t_, "lemma_match")] += norm(lem) in lems

    # word index for the join
    w_ent: dict[tuple[str, str], collections.Counter] = collections.defaultdict(collections.Counter)
    for key, ent, _, kind, *_ in rows:
        w_ent[(key, kind)][ent] += 1

    # --- our characters ---
    def read_tsv(p: Path) -> list[dict]:
        with open(p, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader((l for l in fh if not l.startswith("#")), delimiter="\t", quoting=csv.QUOTE_NONE))

    chars: dict[str, dict] = {}
    table_rows = collections.Counter()
    for side, p in (("heb", HEB_CHARS), ("grc", NT_CHARS)):
        for r in read_tsv(p):              # one id may have several rows (a label per book or per name form): merged
            table_rows[side] += 1
            c = chars.setdefault(r["id"], {"side": side, "name": set(), "inquit": set(), "speech": set()})
            c["name"].update(k for k in r["name_key"].split() if k != "-")
    quots = read_tsv(HEB_QUOT)
    kids = collections.defaultdict(list)
    for q in quots:
        if q["parent"]:
            kids[q["parent"]].append(q)

    def span(q: dict) -> set:
        a, b = bisect.bisect_left(heb_sorted, q["first"]), bisect.bisect_right(heb_sorted, q["last"])
        return set(heb_sorted[a:b])

    for q in quots:
        c = chars.get(q["speaker_id"])
        if not c:
            continue
        if q["speaker_name_ref"]:
            c["name"].update(q["speaker_name_ref"].split())
        c["inquit"].update(q["speaker_ref"].split())
        own = span(q)
        for k in kids[q["id"]]:
            own -= span(k)
        c["speech"].update(own)
    for f in sorted(glob.glob(str(NT_CLAUSES / "*" / "*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            s = json.loads(line)
            c = chars.get(s.get("speaker_id") or "")
            if not c:
                continue
            if s.get("speaker_name_ref"):
                c["name"].update(s["speaker_name_ref"].split())
            c["inquit"].update(s.get("speaker_ref") or [])
            c["speech"].update(s.get("words") or [])

    def votes(words: set, kinds: tuple) -> collections.Counter:
        v = collections.Counter()
        for w in words:
            for kd in kinds:
                for e in w_ent.get((w, kd), ()):
                    v[e] += 1
        return v

    join = {}
    for cid, c in chars.items():
        rv = {"name": votes(c["name"], ("explicit",)),
              "inquit": votes(c["inquit"], ("explicit", "pronominal", "subject")),
              "speech": votes(c["speech"], ("speech",))}
        score = collections.Counter()
        for rule, v in rv.items():
            tot = sum(v.values())
            for e, n in v.items():
                score[e] += n / tot
        if not score:
            join[cid] = {"entity": "", "basis": "", "rv": rv, "conflict": [], "tied": [], "speech_words": len(c["speech"])}
            continue
        best, bs = score.most_common(1)[0]
        basis = [r for r, v in rv.items() if v and v.most_common(1)[0][0] == best]
        conflict = set()
        for r, v in rv.items():
            tot = sum(v.values())
            for e, n in v.items():
                if e != best and n / tot >= CONFLICT_SHARE:
                    conflict.add(e)
        for e, s_ in score.items():
            if e != best and s_ >= 0.5 * bs:
                conflict.add(e)
        sp = rv["speech"]
        top = sp.most_common(1)[0][1] if sp else 0
        tied = sorted(e for e, n in sp.items() if n == top) if sp and sum(1 for n in sp.values() if n == top) > 1 else []
        join[cid] = {"entity": best, "basis": "+".join(basis), "rv": rv, "conflict": sorted(conflict - set(tied)),
                     "tied": tied, "speech_words": len(c["speech"])}

    ent_chars = collections.defaultdict(list)
    for cid, j in join.items():
        if j["entity"]:
            ent_chars[j["entity"]].append(cid)

    # --- write ---
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "entity_words.tsv", "w", encoding="utf-8") as fh:
        fh.write("word\tentity\tform\tkind\tinstance\tquote_type\tsource_word\tmap\n")
        fh.writelines("\t".join(r) + "\n" for r in rows)
    n_by = collections.Counter((r[1], r[3]) for r in rows)
    with open(OUT / "entities.tsv", "w", encoding="utf-8") as fh:
        fh.write("entity\tprimary\ttype\tsubtype\tgender\tlemmas\tapocrypha_only\tnon_biblical\tcharacters\t"
                 "explicit\tpronominal\tsubject\tspeech\n")
        for i in sorted(recs):
            d = recs[i]
            sub = d.get(SUBTYPE.get(d["type"], ""), "") or ""
            if d["type"] == "place":
                sub = " ".join(code(x) for x in (d.get("place_types") or {}).get("acai", []))
            else:
                sub = code(sub)
            lem = " | ".join(f"{lg}:{x}" for lg, v in sorted((d.get("lemmas") or {}).items()) for x in v)
            fh.write("\t".join([i, primary[i], d["type"], sub, d.get("gender") or "", lem,
                                "Y" if d.get("only_mentioned_in_apocrypha") else "", "Y" if d.get("non_biblical") else "",
                                " ".join(sorted(ent_chars.get(i, []))),
                                *(str(n_by[(i, k)]) for k in ("explicit", "pronominal", "subject", "speech"))]) + "\n")
    kin, dangling = [], collections.Counter()
    for i in sorted(recs):
        d = recs[i]
        for field, rel in RELATIONS:
            v = d.get(field)
            for o in ([v] if isinstance(v, str) else v or []):
                if o:
                    kin.append((i, rel, o))
                    dangling[rel] += o not in recs
        for rel, v in (d.get("related_places") or {}).items():
            for o in v:
                kin.append((i, rel, o))
                dangling[rel] += o not in recs
    with open(OUT / "kinship.tsv", "w", encoding="utf-8") as fh:
        fh.write("entity\trelation\tother\n")
        fh.writelines("\t".join(r) + "\n" for r in kin)
    with open(OUT / "characters.tsv", "w", encoding="utf-8") as fh:
        fh.write("character\tentity\tentity_type\tgeneric\tbasis\tname_votes\tinquit_votes\tspeech_votes\tspeech_words\t"
                 "speech_tied\tconflicts\n")
        for cid in sorted(join, key=lambda x: (x[0] != "c", x)):
            j = join[cid]
            e = j["entity"]
            fh.write("\t".join([cid, e, recs[e]["type"] if e else "", "Y" if ":Generic" in e else "", j["basis"],
                                *(str(j["rv"][r].get(e, 0)) + "/" + str(sum(j["rv"][r].values())) for r in ("name", "inquit", "speech")),
                                str(j["speech_words"]), " ".join(j["tied"]), " ".join(j["conflict"])]) + "\n")

    # --- figures and checks ---
    asym = collections.Counter()
    kinset = {(a, r, b) for a, r, b in kin}
    for a, r, b in kin:
        if r in ("father", "mother"):
            asym["parent_without_offspring_back"] += (b, "offspring", a) not in kinset
        elif r == "offspring":
            asym["offspring_without_parent_back"] += not ((a, "father", b) in kinset or (a, "mother", b) in kinset
                                                          or (b, "father", a) in kinset or (b, "mother", a) in kinset)
        elif r in ("partner", "sibling"):
            asym[f"{r}_one_way"] += (b, r, a) not in kinset
    typ = collections.Counter(d["type"] for d in recs.values())
    prim_typ = collections.Counter(d["type"] for i, d in recs.items() if primary[i] == i)
    stats = {}
    for side, n_label in (("heb", "Hebrew"), ("grc", "Greek NT")):
        ids = [c for c in chars if chars[c]["side"] == side]
        joined = [c for c in ids if join[c]["entity"]]
        st = {"table_rows": table_rows[side], "characters": len(ids), "joined": len(joined),
              "by_type": dict(collections.Counter(recs[join[c]["entity"]]["type"] for c in joined)),
              "by_basis": dict(collections.Counter(join[c]["basis"] for c in joined)),
              "rule_has_votes": {r: sum(1 for c in ids if join[c]["rv"][r]) for r in ("name", "inquit", "speech")},
              "to_generic_entity": sum(1 for c in joined if ":Generic" in join[c]["entity"]),
              "person_specific": sum(1 for c in joined if recs[join[c]["entity"]]["type"] == "person"
                                     and ":Generic" not in join[c]["entity"]),
              "person_specific_no_conflict": sum(1 for c in joined if recs[join[c]["entity"]]["type"] == "person"
                                                 and ":Generic" not in join[c]["entity"] and not join[c]["conflict"]
                                                 and not join[c]["tied"]),
              "speech_tied": sum(1 for c in joined if join[c]["tied"]),
              "with_conflicts": sum(1 for c in joined if join[c]["conflict"]),
              "no_evidence": len(ids) - len(joined)}
        e_side = collections.Counter(join[c]["entity"] for c in joined)
        st["entities"] = len(e_side)
        st["entities_with_several_characters"] = sum(1 for n in e_side.values() if n > 1)
        stats[side] = st
    kind_n = collections.Counter(r[3] for r in rows)
    build = {
        "built": datetime.date.today().isoformat(),
        "source": {"name": "ACAI Biblical Entity Data", "repo": "https://github.com/BibleAquifer/ACAI", "tag": ACAI_TAG,
                   "commit": acai_commit(), "licence": "CC BY-SA 4.0", "copyright": "Mission Mutual (README); BiblioNexus (LICENSE.md)"},
        "greek_bridge": {"repo": "https://github.com/Clear-Bible/macula-greek", "file": "SBLGNT/tsv/macula-greek-SBLGNT.tsv",
                         "commit": SBL_COMMIT, "sha256": sha256(SBL), "licence": "CC BY 4.0", **g_fig},
        "spine_sha256": sha256(SPINE),
        "code_sha256": sha256(Path(__file__)),
        "licence": "CC BY-SA 4.0 (ACAI's ShareAlike)",
        "records": dict(typ), "primary_records": dict(prim_typ),
        "entity_words": len(rows), "entity_words_by_kind": dict(kind_n),
        "kinship": len(kin), "kinship_by_relation": dict(collections.Counter(r for _, r, _ in kin)),
        "characters": stats,
    }
    (OUT / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    L = ["# ACAI entities: build checks", "",
         f"ACAI {ACAI_TAG}, commit `{build['source']['commit']}`; built {build['built']}.", "",
         "## What ACAI holds", "", "| type | records | primary |", "|---|---|---|"]
    L += [f"| {t} | {typ[t]} | {prim_typ[t]} |" for t in sorted(typ)]
    L += ["", f"Alias (non-primary) records' word links that are also in their primary record: "
          f"{subset['alias_links_in_primary']} of {subset['alias_links']}.", "",
          "## Coverage of ACAI's word links against MACULA", "",
          "| language | kind | links | missing in MACULA | not in SBLGNT | not mapped to Nestle 1904 | duplicate |", "|---|---|---|---|---|---|---|"]
    for lang in ("heb", "grc", "?"):
        for kd in ("explicit", "pronominal", "subject", "speech"):
            if cov[(lang, kd, "links")]:
                L.append(f"| {lang} | {kd} | {cov[(lang, kd, 'links')]} | {cov[(lang, kd, 'missing')]} | "
                         f"{cov[(lang, kd, 'not_in_sblgnt')]} | {cov[(lang, kd, 'unmapped')]} | {cov[(lang, kd, 'duplicate')]} |")
    L += ["", f"Greek bridge SBLGNT -> Nestle 1904: {g_fig['sbl_words']} SBLGNT words, {g_fig['mapped_lemma']} aligned on the lemma, "
          f"{g_fig['mapped_position']} paired by position, {g_fig['same_id']} keep the same id number.", "",
          "Hebrew ids MACULA does not have, carried to a MACULA word: " + ", ".join(
              f"{kd} {how} {cov[('heb', kd, how)]}" for kd in KINDS.values() for how in ("article_in_prefix", "nearest_part")
              if cov[("heb", kd, how)]) + ".", "",
          "Lemma check: explicit-instance words whose MACULA lemma is one of the entity's ACAI lemmas (a phrase's other words "
          "and name forms ACAI lists only on the alias record count as misses):", "",
          "| type | Hebrew | Greek |", "|---|---|---|"]
    for t_ in sorted({k[1] for k in lem_check}):
        L.append(f"| {t_} | " + " | ".join(
            f"{lem_check[(lg, t_, 'lemma_match')]} / {lem_check[(lg, t_, 'checked')]}" for lg in ("heb", "grc")) + " |")
    L += [""]
    for k, v in bad.items():
        L.append(f"- examples, {k}: " + "; ".join(f"{e} {kd} {w}" for e, kd, w in v[:8]))
    L += ["", "## Kinship", "", "| relation | rows | target not an ACAI record |", "|---|---|---|"]
    kc = collections.Counter(r for _, r, _ in kin)
    L += [f"| {r} | {n} | {dangling[r]} |" for r, n in kc.most_common()]
    L += ["", "Consistency: " + ", ".join(f"{k} {v}" for k, v in sorted(asym.items())), "",
          "## Join to our characters", "",
          "Rules (votes per ACAI entity; the entity with the highest sum of vote shares over the three rules joins):",
          "- `name`: the words that name the character (characters table name_key, speaker_name_ref) among ACAI's explicit instances;",
          "- `inquit`: the inquit subject words (speaker_ref) among ACAI's explicit, pronominal and subject links;",
          "- `speech`: the character's own speech words (Hebrew: the quotation minus its nested quotations; Greek: the segments with "
          "its speaker_id) among ACAI's speech words.",
          f"A conflict: another entity has at least {CONFLICT_SHARE:.0%} of one rule's votes, or half the best entity's score.", ""]
    for side, st in stats.items():
        L += [f"### {'Hebrew (characters.tsv)' if side == 'heb' else 'Greek NT (nt_characters.tsv)'}", "",
              f"- table rows {st['table_rows']}, distinct character ids {st['characters']}, joined {st['joined']}, no evidence {st['no_evidence']}",
              f"- joined to type: {st['by_type']}",
              f"- basis (rules whose top entity is the joined one): {dict(sorted(st['by_basis'].items(), key=lambda x: -x[1]))}",
              f"- characters with votes per rule: {st['rule_has_votes']}",
              f"- joined to an ACAI placeholder (`…:Generic…`, not an identity): {st['to_generic_entity']}",
              f"- joined to a specific ACAI person: {st['person_specific']}; of them without conflict or tie: "
              f"{st['person_specific_no_conflict']}",
              f"- speech votes tied between several entities (ACAI gives a group's speech to each member): {st['speech_tied']}",
              f"- joined with a conflict: {st['with_conflicts']}",
              f"- distinct entities {st['entities']}; entities joined by several characters: {st['entities_with_several_characters']}", ""]
    L += ["## Provenance and licences (read from ACAI's README.md, LICENSE.md and the per-type READMEs)", "",
          "- ACAI: CC BY-SA 4.0 (LICENSE.md: (c) 2024 BiblioNexus; README: (c) 2025 Mission Mutual). ShareAlike binds anything built on it.",
          "- MACULA Hebrew / Greek (Biblica / Clear): CC BY 4.0. Word ids, UBS domains, `participantref` / `subjref` / `referent`.",
          "- Clear speaker-quotations (CC BY 4.0): ACAI's `speeches`. Projected from quotation marks in aligned English Bibles, speakers "
          "from FCBH: English-derived evidence (the same caveat as our speaker layers).",
          "- UBS Dictionaries (UBSDBH, UBSDGNT) and UBS Thematic Lexicons (flora, fauna, realia): CC BY-SA 4.0. English descriptions "
          "'inspired by' them (not carried here).",
          "- STEPBible TIPNR: CC BY 4.0; STEPBible asks that copies be kept up to date with a link back (its README: mirrors welcome "
          "'so long as it is kept up-to-date'). ACAI took TIPNR as the base for grouping name forms into one person (identity and "
          "family relations). TIPNR is made from the Hebrew / Greek, with English names.",
          "- Theographic (viz.bible, robertrouse/theographic-bible-metadata): CC BY-SA 4.0 (GitHub licence). Folded into people / places / "
          "groups. Its records are keyed to an English (KJV) text and Easton's dictionary: English-derived evidence for some "
          "relations; ACAI does not say which field came from which source.",
          "- OpenBible.info geocoding: CC BY 4.0 (places; not carried here except as nothing).",
          "- Keyterms: built on 'UBS Key Terms data from Paratext ... used by permission' (UBS claims no copyright, per ACAI). "
          "Not an open licence statement: keyterm rows are kept in the build but are a doubt for release.",
          "- `alternate_sources.aquifer` holds ids of Tyndale Bible Dictionary, unfoldingWord Translation Words and Biblica study-note "
          "key terms (cross-reference ids only; not carried).",
          "- Versification: ACAI is in ORG (Hebrew / Greek) numbering, as MACULA.", ""]
    L += ["### Conflicts (first 40)", "", "| character | joined | basis | other candidates |", "|---|---|---|---|"]
    n = 0
    for cid in sorted(join, key=lambda x: (x[0] != "c", x)):
        if join[cid]["conflict"] and n < 40:
            L.append(f"| {cid} | {join[cid]['entity']} | {join[cid]['basis']} | {' '.join(join[cid]['conflict'][:5])} |")
            n += 1
    L += ["", "### Entities joined by several characters (first 40)", "", "| entity | characters |", "|---|---|"]
    n = 0
    for e, cs in sorted(ent_chars.items(), key=lambda x: -len(x[1])):
        if len(cs) > 1 and n < 40:
            L.append(f"| {e} | {' '.join(sorted(cs))} |")
            n += 1
    (OUT / "checks.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in build.items() if k in ("records", "entity_words_by_kind", "kinship", "characters")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
