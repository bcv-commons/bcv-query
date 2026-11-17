"""Package bcv-commons/hebrew-greek-cf: the bridge corpus (build_bridge_corpus) as a release.

    cd shoresh && .venv/bin/python3 -m macula.build_bridge_corpus --build --release v0.1 --out BUILD
    cd shoresh && .venv/bin/python3 -m macula.release_hebrew_greek_cf --version v0.1 --build BUILD --out DIR [--allow-dirty]

Nothing is uploaded. The build must carry this release's version and the current pins, and every fixed query must give its count.
DIR gets tf/ (the dataset's .tf files), bridges/*.parquet (the links between texts as flat tables), pins.json, report.json,
queries.json, build.json, README.md (hebrew_greek_cf_card.md filled in) and SHA256SUMS.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from macula import build_bridge_corpus as B
from macula import release_guard  # refuses TBTA and private inputs

ROOT = Path(__file__).resolve().parents[2]
CARD = Path(__file__).with_name("hebrew_greek_cf_card.md")
SCHEMA = 1
TEXTS = {                                                               # text name -> (shown as, what it is)
    "tanakh": ("Tanakh", "MACULA Hebrew (Westminster Leningrad Codex), with the Aramaic; word parts as MACULA cuts them"),
    "greek_nt": ("Greek New Testament", "MACULA Greek (Nestle 1904)"),
    "septuagint": ("Septuagint", "GLAUx's Septuagint (canonical books); Daniel both as the Old Greek and as Theodotion"),
    "salkinson": ("Hebrew New Testament, Salkinson-Ginsburg", "with bcv-commons/hebrew-nt-analysis"),
    "delitzsch": ("Hebrew New Testament, Delitzsch", "with bcv-commons/hebrew-nt-analysis"),
}
BRIDGES = {                                                             # edge -> what it links
    "lxx": "Tanakh word part -> the Septuagint word that renders it; value: how it was placed (`sure`, `order`, `neighbours`, `number`)",
    "carried": "Septuagint clause line -> the Tanakh clause line it carries over (a Hebrew line's Greek words, where they form a clean stretch)",
    "heb_scg": "Greek NT word -> Salkinson-Ginsburg word part (hebrew-nt-bridge); value: the link's class",
    "heb_mod": "Greek NT word -> Delitzsch word part (hebrew-nt-bridge); value: the link's class",
    "quotes": "Hebrew NT verse -> the Tanakh verse it quotes; value: the weight",
    "parallel": "verse -> the verse of the same number in the other text (Hebrew NT / Greek NT, Septuagint / Tanakh)",
}
LAYER_PREFIX = {"hebrew-clause-layout": "lay", "greek-nt-clause-layout": "lay", "clause-columns": "cc", "clause-connectives": "cn",
                "clause-extras": "cx", "time-aspect": "ta", "argument-roles": "ar", "reference-status": "rs", "noun-relations": "nr",
                "word-senses": "ws", "inclusive-we": "we", "addressees": "ad", "hebrew-word-concepts-model": "m", "hebrew-nt-analysis": "hna",
                "hebrew-nt-bridge": "heb_scg, heb_mod, quotes, hnb", "word-parts": "wp", "hebrew-phrase-types-model": "m_pt", "passage-facts": "pf"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def tf_version(build: Path) -> str:
    for line in (build / "otype.tf").read_text(encoding="utf-8").splitlines():
        if line.startswith("@version="):
            return line.split("=", 1)[1]
        if not line.startswith("@"):
            break
    raise SystemExit(f"{build}: no @version in otype.tf")


def bridges(api, out: Path) -> dict:
    """the links between texts as flat tables, keyed by the words' own ids"""
    import pyarrow as pa
    import pyarrow.parquet as pq
    F, E, T = api.F, api.E, api.T
    words = list(F.otype.s("word"))
    rows = [{"hebrew_mid": F.mid.v(w), "lxx_key": F.lkey.v(m), "how": v} for w in words for m, v in E.lxx.f(w)]
    tables = {"lxx": rows}
    rows = []
    for ed in ("heb_scg", "heb_mod"):
        e = getattr(E, ed)
        rows += [{"edition": ed, "greek_mid": F.mid.v(w), "hebrew_key": F.hkey.v(m), "class": v, "tanakh": F.hnb_tanakh.v(m)}
                 for w in words for m, v in e.f(w)]
    tables["hebrew_nt"] = rows
    ref = lambda n: "{} {}:{}".format(*T.sectionFromNode(n))
    tables["quotes"] = [{"hebrew_nt_verse": ref(v), "tanakh_verse": ref(m), "weight": float(x)} for v in F.otype.s("verse") for m, x in E.quotes.f(v)]
    (out / "bridges").mkdir()
    for name, rs in tables.items():
        pq.write_table(pa.Table.from_pylist(rs), out / "bridges" / f"{name}.parquet")
    return {name: len(rs) for name, rs in tables.items()}


def table(head: list[str], rows: list[list]) -> str:
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(x) for x in r) + " |" for r in rows])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "shoresh/macula"], cwd=ROOT, text=True).strip()
    if dirty and not a.allow_dirty:
        raise SystemExit(f"uncommitted changes in shoresh/macula:\n{dirty}")
    code = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=ROOT, text=True).strip() + ("+uncommitted" if dirty else "")
    p = B.pins()
    want = B.version(p, a.version)
    if tf_version(a.build) != want:
        raise SystemExit(f"{a.build} is version {tf_version(a.build)}, this release needs {want}: build it with --release {a.version}")
    if json.loads((a.build / "pins.json").read_text()) != p:
        raise SystemExit(f"{a.build}/pins.json is not the current bridge_corpus_pins.json")
    chk = B.check(a.build)
    if not chk["queries as expected"]:
        raise SystemExit("fixed queries differ: " + json.dumps([q for q in chk["queries"] if q["hits"] != q["expected"]]))
    api = B.load(a.build)
    rep = json.loads((a.build / "report.json").read_text(encoding="utf-8"))

    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "tf").mkdir()
    for f in sorted(a.build.glob("*.tf")):
        shutil.copyfile(f, a.out / "tf" / f.name)
    for f in ("pins.json", "report.json"):
        shutil.copyfile(a.build / f, a.out / f)
    (a.out / "queries.json").write_text(json.dumps([{"name": n, "query": q, "count": h} for n, q, h in B.QUERIES], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    flat = bridges(api, a.out)

    F = api.F
    per_text = {F.name.v(t): len(api.E.oslots.s(t)) for t in F.otype.s("text")}
    assert set(per_text) == set(TEXTS), per_text
    nodes = chk["nodes"]
    build = {"schema": SCHEMA, "version": a.version, "dataset version": want, "built": datetime.date.today().isoformat(), "code": code,
             "licence": "CC BY-SA 4.0", "words per text": per_text, "nodes": nodes, "flat tables": flat,
             "inputs": "pins.json", "queries": f"{len(B.QUERIES)} of {len(B.QUERIES)} as expected"}
    (a.out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    pairs = {k: v["pairs"] for k, v in rep["edges"].items()}
    layers = [[f"[{n}](https://huggingface.co/datasets/bcv-commons/{n})", pin["tag"], f"`{pin['revision']}`", f"`{LAYER_PREFIX.get(n, '')}`",
               pin["licence"], "yes" if pin.get("model_made") else "no"] for n, pin in p["layers"].items()]
    sources = [["Hebrew and Greek NT words, ids, lemmas, morphology", p["words"]["origin"], p["words"]["licence"]]]
    sources += [[n, f"{s['origin']}; {s['source']} {s['tag']}", s["licence"]] for n, s in p["stores"].items()]
    sources += [["the layers", "bcv-commons datasets above", "CC BY 4.0 / CC BY-SA 4.0 (per layer)"]]
    fill = {
        "@VERSION@": a.version, "@DATAVERSION@": want, "@BUILT@": build["built"], "@CODE@": code,
        "@WORDS@": f"{sum(per_text.values()):,}", "@QUERIES@": str(len(B.QUERIES)),
        "@TEXTS@": table(["Text", "`name`", "Words", "What it is"], [[TEXTS[t][0], f"`{t}`", f"{n:,}", TEXTS[t][1]] for t, n in per_text.items()]),
        "@BRIDGES@": table(["Edge", "Pairs", "Links"], [[f"`{e}`", f"{pairs.get(e, 0):,}", d] for e, d in BRIDGES.items()]),
        "@UNITS@": table(["Unit", "Count"], [[f"`{t}`", f"{nodes[t]:,}"] for t in ("word", *B.TYPES) if t in nodes]),
        "@LAYERS@": table(["Layer", "Tag", "Revision", "Prefix", "Licence", "Model-made"], layers),
        "@MODEL@": ", ".join(n for n, pin in p["layers"].items() if pin.get("model_made")),
        "@SOURCES@": table(["Part", "Source", "Licence"], sources),
    }
    card = CARD.read_text(encoding="utf-8")
    for k, v in fill.items():
        card = card.replace(k, v)
    assert "@" not in card, [l for l in card.splitlines() if "@" in l]
    (a.out / "README.md").write_text(card, encoding="utf-8")
    files = sorted(x for x in a.out.rglob("*") if x.is_file() and x.name != "SHA256SUMS")
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(x)}  {x.relative_to(a.out)}\n" for x in files), encoding="utf-8")
    print(f"bcv-commons/hebrew-greek-cf {a.version} -> {a.out}: {sum(per_text.values()):,} words, flat tables {flat}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
