"""Package the entity layer (O1): who each word of the Tanakh and the Greek NT refers to, the entities, and their kinship.
Nothing is uploaded.

    cd shoresh && .venv/bin/python -m macula.release_entity_mentions --tag v0.1 --out DIR [--allow-dirty]   (after macula.build_entities)

Mentions, per word (MACULA key), from two routes kept side by side:
  acai    ACAI's word links: explicit (a name or noun), pronominal (a pronoun or suffix), subject (a verb's implied subject).
          ACAI's speech links are left out (the speaker layers cover speech).
  chain   MACULA's reference from the word (subjref / participantref / referent), followed up to 4 steps to a word that has an
          ACAI entity (as reference-status does): that entity.
A word both routes reach gets one row with `agree` same, or, where they name different entities, a row per route with `agree`
differs (disagreements kept, neither preferred). A word only one route reaches gets `agree` acai_only / chain_only.
Entities: ACAI's primary records of type person, place, group, deity, realia, flora, fauna (key terms are not entities here);
an alias record's links count for its primary. Kinship: ACAI's relations between those entities.

Ids are neutral: `e` + sha1(ACAI id)[:10], the same codes as reference-status and addressees. ACAI's ids (English names),
labels, descriptions, subtypes and roles are not carried; lemmas are Hebrew, Aramaic and Greek.
OUT gets data/mentions.parquet, data/entities.parquet, data/kinship.parquet, build.json, README.md (entity_mentions_card.md),
SHA256SUMS.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import re
import sqlite3
import subprocess
from pathlib import Path

from macula import release_guard  # refuses TBTA and private inputs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENT = HERE / "data" / "entities"
SPINE = HERE / "macula-spine.db"
CARD = HERE / "entity_mentions_card.md"
CODE = [HERE / "build_entities.py", Path(__file__).resolve(), CARD]
TYPES = {"person", "place", "group", "deity", "realia", "flora", "fauna"}
KINDS = ("explicit", "pronominal", "subject")
STEPS = 4


def code(acai_id: str) -> str:
    return "e" + hashlib.sha1(acai_id.encode("utf-8")).hexdigest()[:10]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    out = Path(a.out)
    if out.exists():
        raise SystemExit(f"{out} exists; give a folder that does not exist yet")
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *map(str, CODE)], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty and not a.allow_dirty:
        raise SystemExit("uncommitted changes; commit first (or --allow-dirty):\n" + dirty)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    commit += " (dirty)" if dirty else ""
    import pyarrow as pa
    import pyarrow.parquet as pq

    erows = list(csv.DictReader(open(ENT / "entities.tsv", encoding="utf-8"), delimiter="\t"))
    primary = {r["entity"]: r["primary"] for r in erows}
    etype = {r["entity"]: r["type"] for r in erows}
    keep = {r["entity"] for r in erows if r["entity"] == r["primary"] and r["type"] in TYPES}
    acai = {}
    st = collections.Counter()
    for r in csv.DictReader(open(ENT / "entity_words.tsv", encoding="utf-8"), delimiter="\t"):
        if r["kind"] not in KINDS:
            continue
        e = primary.get(r["entity"], r["entity"])
        if e not in keep:
            st["acai links outside the entity types"] += 1
            continue
        acai.setdefault(r["word"], (e, r["kind"]))
    m = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    cls = dict(m.execute("select key, class from macula_words"))
    ref = collections.defaultdict(list)
    for s, t, _ in m.execute("select src_key, tgt_key, kind from refs order by rowid"):
        ref[s].append(t)

    def chain(k):
        seen, cur = {k}, k
        for _ in range(STEPS):
            nxt = next((t for t in ref.get(cur, []) if t not in seen), None)
            if not nxt:
                return None
            if nxt in acai:
                return acai[nxt][0]
            seen.add(nxt)
            cur = nxt
        return None

    rows = []
    lang = lambda k: "hbo" if len(k) == 12 else "grc"
    words = sorted(set(acai) | set(ref))
    for k in words:
        A = acai.get(k)
        C = chain(k) if k in ref else None
        ckind = {"pron": "pronominal", "verb": "subject"}.get(cls.get(k, ""), "other")
        base = {"key": k, "lang": lang(k)}
        if A and C:
            if A[0] == C:
                rows.append({**base, "entity": code(A[0]), "kind": A[1], "route": "acai+chain", "agree": "same"})
            else:
                rows.append({**base, "entity": code(A[0]), "kind": A[1], "route": "acai", "agree": "differs"})
                rows.append({**base, "entity": code(C), "kind": ckind, "route": "chain", "agree": "differs"})
        elif A:
            rows.append({**base, "entity": code(A[0]), "kind": A[1], "route": "acai", "agree": "acai_only"})
        elif C:
            rows.append({**base, "entity": code(C), "kind": ckind, "route": "chain", "agree": "chain_only"})
    for r in rows:
        st[r["lang"], r["agree"]] += 1
    words_by = collections.Counter((r["lang"], r["agree"]) for r in {(r["key"], r["agree"]): r for r in rows}.values())

    counts = collections.Counter(r["entity"] for r in rows)
    ents = []
    for r in erows:
        if r["entity"] not in keep:
            continue
        lem = [x.strip() for x in r["lemmas"].split("|") if x.strip()]
        if any(re.search(r"[A-Za-z]", x.split(":", 1)[1]) for x in lem if ":" in x):
            raise SystemExit(f"Latin letters in a lemma of {code(r['entity'])}")
        ents.append({"entity": code(r["entity"]), "type": r["type"], "gender": {"male": "m", "female": "f"}.get(r["gender"], ""),
                     "lemmas": lem, "characters": r["characters"].split(), "apocrypha_only": r["apocrypha_only"] == "Y",
                     "non_biblical": r["non_biblical"] == "Y", "mentions": counts[code(r["entity"])]})
    codes = [e["entity"] for e in ents]
    if len(set(codes)) != len(codes):
        raise SystemExit("two ACAI ids give the same code")
    kin = []
    for r in csv.DictReader(open(ENT / "kinship.tsv", encoding="utf-8"), delimiter="\t"):
        s, o = primary.get(r["entity"], r["entity"]), primary.get(r["other"], r["other"])
        if s in keep and o in keep and s != o:
            kin.append({"entity": code(s), "relation": r["relation"], "other": code(o)})
        else:
            st["kinship rows not between kept entities"] += 1
    kin = [dict(t) for t in sorted({tuple(x.items()) for x in kin})]
    known = set(codes)
    dangling = sum(1 for r in rows if r["entity"] not in known) + sum(1 for r in kin if r["entity"] not in known or r["other"] not in known)
    if dangling:
        raise SystemExit(f"{dangling} rows point at no entity")

    (out / "data").mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows), out / "data" / "mentions.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(ents), out / "data" / "entities.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(kin), out / "data" / "kinship.parquet", compression="zstd")
    acai_build = json.loads((ENT / "build.json").read_text())
    agree = {}
    for lg in ("hbo", "grc"):
        both = words_by[lg, "same"] + words_by[lg, "differs"]
        agree[lg] = {"words": sum(v for k, v in words_by.items() if k[0] == lg), "both routes": both,
                     "same": words_by[lg, "same"], "differs": words_by[lg, "differs"],
                     "share same where both": round(words_by[lg, "same"] / both, 3) if both else None,
                     "acai_only": words_by[lg, "acai_only"], "chain_only": words_by[lg, "chain_only"]}
    build = {"tag": a.tag, "code": commit, "acai": {"tag": acai_build.get("acai_tag") or "v2026-11-07",
             "commit": acai_build.get("acai_commit") or "5375d0d334bb6d635ef1813e4d3df58eb30efcca"},
             "chain_steps": STEPS, "agreement": agree, "entities": len(ents),
             "entities_by_type": dict(collections.Counter(e["type"] for e in ents)), "kinship": dict(collections.Counter(r["relation"] for r in kin)),
             "mention_rows": len(rows), "notes": {k if isinstance(k, str) else " ".join(k): v for k, v in st.items() if isinstance(k, str)}}
    (out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1), encoding="utf-8")
    f = lambda n: f"{n:,}"
    vals = {"@TAG@": a.tag, "@CODE@": commit, "@ACAI_TAG@": build["acai"]["tag"], "@ACAI_COMMIT@": build["acai"]["commit"][:12],
            "@ENTS@": f(len(ents)), "@ROWS@": f(len(rows)), "@KIN@": f(len(kin)),
            "@TYPES@": ", ".join(f"{k} {f(v)}" for k, v in sorted(build["entities_by_type"].items(), key=lambda x: -x[1]))}
    for lg, L in (("hbo", "H"), ("grc", "G")):
        g = agree[lg]
        vals.update({f"@{L}_WORDS@": f(g["words"]), f"@{L}_BOTH@": f(g["both routes"]), f"@{L}_SAME@": f(g["same"]),
                     f"@{L}_DIFF@": f(g["differs"]), f"@{L}_SHARE@": f"{g['share same where both']:.3f}",
                     f"@{L}_AONLY@": f(g["acai_only"]), f"@{L}_CONLY@": f(g["chain_only"])})
    card = CARD.read_text(encoding="utf-8")
    for k, v in vals.items():
        card = card.replace(k, str(v))
    if re.findall(r"@[A-Z_]+@", card):
        raise SystemExit(f"unfilled card fields: {re.findall(r'@[A-Z_]+@', card)}")
    (out / "README.md").write_text(card, encoding="utf-8")
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out).as_posix()}\n" for p in files))
    print(json.dumps(build, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
