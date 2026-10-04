#!/usr/bin/env python3
"""Frozen domain-provider tables for the usability scorecard (plan: internal-docs/usability-scorecard.md).

A "provider" is one way of giving a Hebrew word a group and a label. The scorecard measures every
provider the same way, so the current SDBH `core` axis ("now") can be compared with each candidate
replacement ("later") on usability for clients, not on agreement with SDBH.

Each provider is frozen as two TSVs plus a sha256 in a manifest, so numbers stay comparable after the
CC0 clusters are rebuilt and after `resources/semantic_domains/hbo.tsv` is gone:

  <name>.members.tsv  strong, axis, group_id, share, served   (one row per word-group membership)
  <name>.groups.tsv   group_id, label, label_strong, label_lemma, n_served

`served=1` marks the one group `/verse` would show for that word: the dominant group, gated at the
same 0.6 share `_dominant_domain` applies today. A group's members, for coherence tests, are the words
it is served for.

Providers:
  P0       SDBH `core` exactly as `/verse` serves it today, plus `ctx` membership rows (served=0) so the
           `/wordstudy` view is frozen too. One-time read of hbo.tsv through shoresh's own loaders.
  P0none   `core`/`ctx` removed, nothing added: the floor.
  P1       CC0 domain clusters, `anchor=high` units only, exemplar-labelled.
  P2       CC0 domain clusters, all units, exemplar-labelled.
  P1nb/P2nb  as P1/P2, but built with no BHSA input (macula.build_bhsa_free_contexts + build_semantic_neighbors
           --macula-contexts --no-structural --parallelism-tomim-only); units are plain lexemes, counts and
           reading-aid glosses come from MACULA (data/bhsa_free/occurrence.db).
  PR-<base>  random control: each served word's group swapped with another served word of the same
           frequency band (group sizes preserved exactly). Built per seed by random_control().

Cluster units are `lexeme#sense` keys (sense from hbo.db's per-occurrence `sense` column, the same keys
build_semantic_neighbors.lexeme_vectors(sense_split=True) clusters on), so a word's share in a cluster
is weighted by how many of its occurrences fall in units of that cluster.

Exemplar label: the group's most frequent served member, as its pointed lemma plus English gloss. The
lemma is the label; the gloss is only a reading aid and is rendered in the reader's language at serve
time (render_label).

  cd shoresh && .venv/bin/python3 -m macula.domain_providers            # build all + manifest
  cd shoresh && .venv/bin/python3 -m macula.domain_providers --check    # rebuild in memory, compare hashes
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SHORESH = HERE.parent
OUT = HERE / "data" / "usability" / "providers"

SPINE_DB = SHORESH / "spine" / "spine.db"
LEXEME_SPINE = HERE / "lexeme-spine.db"
BRIDGE = HERE / "bhsa-macula-bridge.db"
HBO = ROOT / "resources" / "occurrences" / "hbo.db"
CLUSTERS = ROOT / "resources" / "semantic_neighbors" / "domain_clusters.tsv"
HBO_DOMAINS = ROOT / "resources" / "semantic_domains" / "hbo.tsv"

MIN_SHARE = 0.6                     # same gate as shoresh data._dominant_domain
RANDOM_BASES = ("P0", "P2", "P2nb")
BHSA_FREE = HERE / "data" / "bhsa_free"
CLUSTERS_NB = BHSA_FREE / "domain_clusters.tsv"
OCC_NB = BHSA_FREE / "occurrence.db"
# Ablations isolating which BHSA input matters (built from the production BHSA-clause embeddings):
#   A1 = sense split kept, BHSA structural pairs and BHSA parallelism detection dropped
#   A2 = all signals kept, no sense split
# (name -> clusters file, unit kind: "sense" = lexeme#sense units, "lexeme" = plain lexemes)
ABLATIONS = {"A1": (BHSA_FREE / "ablations" / "a1" / "domain_clusters.tsv", "sense"),
             "A2": (BHSA_FREE / "ablations" / "a2" / "domain_clusters.tsv", "lexeme"),
             # admission test: the BHSA-free pack plus the Metzudat Zion signal (compare with P2nb)
             "P2nbmz": (BHSA_FREE / "with_mz" / "domain_clusters.tsv", "lexeme"),
             # BHSA-free + homograph routing of Strong's-level evidence (--route-homographs)
             "P2nbr": (BHSA_FREE / "routed" / "domain_clusters.tsv", "lexeme"),
             # admission tests on top of P2nbr: + Malbim Beur HaMilot; + Malbim and Metzudat Zion
             "P2nbrm": (BHSA_FREE / "routed_malbim" / "domain_clusters.tsv", "lexeme"),
             "P2nbrmz": (BHSA_FREE / "routed_mz_malbim" / "domain_clusters.tsv", "lexeme"),
             # seed-controlled builds (fixed PYTHONHASHSEED; build_semantic_neighbors.deterministic_hash_seed):
             # baseline at hash seeds 0 and 1 (clustering noise), + Malbim and Metzudat Zion, + sense units
             # split by translation (build_rendering_senses.py)
             "B0": (BHSA_FREE / "seeded" / "base_h0" / "domain_clusters.tsv", "lexeme"),
             "B1": (BHSA_FREE / "seeded" / "base_h1" / "domain_clusters.tsv", "lexeme"),
             "MZM0": (BHSA_FREE / "seeded" / "mzm_h0" / "domain_clusters.tsv", "lexeme"),
             "RS0": (BHSA_FREE / "seeded" / "rs_h0" / "domain_clusters.tsv", "rsense"),
             # sense units for nouns and adjectives only (verb "senses" were mostly tense/inflection)
             "RSN0": (BHSA_FREE / "seeded" / "rsn_h0" / "domain_clusters.tsv", "rsense_nouns"),
             # + Malbim, Metzudat Zion and Mahberet Menahem
             "MZMM0": (BHSA_FREE / "seeded" / "mzmm_h0" / "domain_clusters.tsv", "lexeme"),
             # baseline without the corroborated family (Wiktionary-backed, CC BY-SA) for a clean CC0 lineage
             "BNC0": (BHSA_FREE / "seeded" / "base_nc_h0" / "domain_clusters.tsv", "lexeme")}
RENDERING_SENSES = HERE / "data" / "rendering_senses" / "occurrences.tsv"
CONTROL_SEED = 13

Row = tuple[str, str, str, float, int]               # strong, axis, group_id, share, served


def _ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        sys.exit(f"missing input: {path}")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------- shared word facts ----------

def token_counts() -> collections.Counter:
    """H#### -> number of Old Testament tokens (Hebrew + Aramaic) in spine.db, the table /verse serves."""
    db = _ro(SPINE_DB)
    out: collections.Counter = collections.Counter()
    for strong, n in db.execute(
            "SELECT strong, COUNT(*) FROM spine_words WHERE strong IS NOT NULL "
            "AND (morph LIKE 'He,%' OR morph LIKE 'Ar,%') GROUP BY strong"):
        out[f"H{int(strong):04d}"] = n
    return out


def lemma_of() -> dict[str, str]:
    """H#### -> most frequent pointed lemma in spine.db."""
    db = _ro(SPINE_DB)
    ct: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for strong, lemma, n in db.execute(
            "SELECT strong, lemma, COUNT(*) FROM spine_words WHERE strong IS NOT NULL AND lemma IS NOT NULL "
            "AND (morph LIKE 'He,%' OR morph LIKE 'Ar,%') GROUP BY strong, lemma"):
        ct[f"H{int(strong):04d}"][lemma] += n
    return {s: c.most_common(1)[0][0] for s, c in ct.items()}


FROZEN_GLOSSES = HERE / "data" / "usability" / "spine_glosses_frozen.tsv"


def _frozen_glosses() -> dict[str, str]:
    out = {}
    for line in FROZEN_GLOSSES.read_text(encoding="utf-8").splitlines()[1:]:
        p = line.split("\t")
        if len(p) >= 2:
            out[p[0]] = p[1]
    return out


def english_gloss(strong: str) -> str:
    """Word-level fallback for label reading aids. Reads a frozen copy of spine/spine_glosses.tsv (taken
    before its 2026-10-03 homograph fix) so provider tables, and the locked item files built from them,
    stay byte-identical across rebuilds; the served gloss table may change, the measurement set may not."""
    if FROZEN_GLOSSES.exists():
        m = re.match(r"^H0*(\d+)", strong)
        return _frozen_glosses_cache().get(f"H{m.group(1)}" if m else strong, "")
    sys.path.insert(0, str(SHORESH))
    import data
    g = data.gloss_of(strong)
    return (g or {}).get("gloss") or ""


_FG: dict | None = None


def _frozen_glosses_cache() -> dict[str, str]:
    global _FG
    if _FG is None:
        _FG = _frozen_glosses()
    return _FG


# ---------- P0: what /verse serves today ----------

def build_p0() -> tuple[list[Row], dict[str, str]]:
    """Calls shoresh's own loaders, so this is the served behaviour, not a re-implementation of it."""
    sys.path.insert(0, str(SHORESH))
    import data
    # Read hbo.tsv directly: shoresh's loader no longer serves core/ctx (retired 2026-10), so going through
    # data._strong_domains() would now yield nothing. The selection logic (_dominant_domain) is still shoresh's.
    by_strong: dict[str, list] = collections.defaultdict(list)
    with HBO_DOMAINS.open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 6 and parts[1] in ("core", "ctx"):
                by_strong[parts[0]].append((parts[1], parts[2], parts[3], float(parts[5])))
    rows: list[Row] = []
    labels: dict[str, str] = {}
    for strong, dd in by_strong.items():
        if not strong.startswith("H"):
            continue
        core = [d for d in dd if d[0] == "core"]
        best = data._dominant_domain(core) if core else None
        served_code = best[0] if best else None
        for axis, code, label, share in dd:
            if axis not in ("core", "ctx"):
                continue
            labels.setdefault(code if axis == "core" else f"ctx:{code}", label)
            gid = code if axis == "core" else f"ctx:{code}"
            rows.append((strong, axis, gid, round(share, 4), int(axis == "core" and code == served_code)))
        if best:
            labels[best[0]] = best[1]
    return rows, labels


# ---------- P1 / P2: CC0 domain clusters ----------

def unit_occurrences() -> tuple[collections.Counter, dict[str, collections.Counter]]:
    """`lexeme#sense` unit -> occurrence count, and unit -> Counter of its occurrences' glosses. Keyed
    exactly as lexeme_vectors(sense_split=True) keys them (hbo.db node -> BHSA/MACULA bridge -> MACULA
    lexeme; empty sense -> '#_nosense'). The per-unit gloss is sense-specific, unlike spine_glosses."""
    sp = _ro(LEXEME_SPINE)
    key2lex = {k: lx for k, lx in sp.execute(
        "SELECT key, lexeme FROM spine_words WHERE is_content=1 AND lexeme IS NOT NULL")}
    br = _ro(BRIDGE)
    node2lex = {node: key2lex[key] for node, key in br.execute("SELECT node, key FROM bridge") if key in key2lex}
    counts: collections.Counter = collections.Counter()
    glosses: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for node, sense, gloss in _ro(HBO).execute("SELECT node, sense, gloss FROM occurrence"):
        lexeme = node2lex.get(node)
        if lexeme is not None:
            unit = f"{lexeme}#{sense}" if sense else f"{lexeme}#_nosense"
            counts[unit] += 1
            if gloss:
                glosses[unit][gloss] += 1
    return counts, glosses


def lexeme_occurrences_nb() -> tuple[collections.Counter, dict[str, collections.Counter]]:
    """Plain-lexeme counts and MACULA glosses from the BHSA-free occurrence table."""
    counts: collections.Counter = collections.Counter()
    glosses: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for lexeme, gloss in _ro(OCC_NB).execute("SELECT lexeme, gloss FROM occurrence"):
        counts[lexeme] += 1
        g = clean_gloss((gloss or "").replace("[", "").replace("]", ""))
        if g and g.lower() not in _GLOSS_PREFIXES:          # MACULA sometimes glosses a verb token "he"
            glosses[lexeme][g] += 1
    return counts, glosses


def rsense_occurrences_nb(senses: Path | None = None) -> tuple[collections.Counter, dict[str, collections.Counter]]:
    """Counts and glosses per lexeme#sense unit, senses from build_rendering_senses.py (as
    build_semantic_neighbors --rendering-senses forms its units)."""
    sense_of = {}
    with (senses or RENDERING_SENSES).open(encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            k, _lx, sn = line.rstrip("\n").split("\t")
            sense_of[k] = sn
    counts: collections.Counter = collections.Counter()
    glosses: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for key, lexeme, gloss in _ro(OCC_NB).execute("SELECT key, lexeme, gloss FROM occurrence"):
        unit = f"{lexeme}#{sense_of.get(key, '_nosense')}"
        counts[unit] += 1
        g = clean_gloss((gloss or "").replace("[", "").replace("]", ""))
        if g and g.lower() not in _GLOSS_PREFIXES:
            glosses[unit][g] += 1
    return counts, glosses


def read_clusters(path: Path = CLUSTERS) -> list[tuple[str, str, str, str]]:
    """(unit, strong, cluster_id, anchor) from a domain_clusters.tsv."""
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("lexeme\t"):
                continue
            unit, strong, cid, _size, anchor = line.rstrip("\n").split("\t")[:5]
            out.append((unit, strong, cid, anchor))
    return out


def build_clusters(anchor_high_only: bool, occ: collections.Counter, unit_gloss: dict[str, collections.Counter],
                   path: Path = CLUSTERS) -> tuple[list[Row], dict[tuple, str]]:
    """Rows, plus (strong, group_id) -> that word's most common gloss within the group's units."""
    weight: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    gloss_in: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
    for unit, strong, cid, anchor in read_clusters(path):
        if anchor_high_only and anchor != "high":
            continue
        gid = f"c{cid}"
        weight[strong][gid] += max(occ.get(unit, 0), 1)
        gloss_in[(strong, gid)].update(unit_gloss.get(unit, {}))
    rows: list[Row] = []
    for strong, by_group in weight.items():
        total = sum(by_group.values())
        top_gid, top_w = max(by_group.items(), key=lambda kv: (kv[1], kv[0]))
        served = top_gid if top_w / total >= MIN_SHARE else None
        for gid, w in by_group.items():
            rows.append((strong, "cc0", gid, round(w / total, 4), int(gid == served)))
    sense_gloss = {k: c.most_common(1)[0][0] for k, c in gloss_in.items() if c}
    return rows, sense_gloss


# ---------- labels and controls ----------

def exemplar_labels(rows: list[Row], counts: collections.Counter, lemmas: dict[str, str]) -> dict[str, tuple]:
    """group_id -> (label_strong, label_lemma): the most frequent word the group is served for."""
    best: dict[str, tuple[int, str]] = {}
    for strong, _axis, gid, _share, served in rows:
        if served:
            cand = (counts.get(strong, 0), strong)
            if gid not in best or cand > best[gid]:
                best[gid] = cand
    return {gid: (s, lemmas.get(s, "")) for gid, (_n, s) in best.items()}


def clean_gloss(gloss: str | None) -> str:
    """hbo.db glosses use MACULA's dotted multiword form ("the.house", "to.go"); make them readable."""
    if not gloss:
        return ""
    words = gloss.replace(".", " ").split()
    while len(words) > 1 and words[0].lower() in _GLOSS_PREFIXES:
        words = words[1:]
    return " ".join(words)


# Leading function words in contextual (per-occurrence) glosses: articles, pronoun subjects,
# auxiliaries. "he will shut up" -> "shut up", "of goats" -> "goats".
_GLOSS_PREFIXES = frozenset("the a an to of he she it they we you i will shall would should was were is "
                            "are be been has have had let may might".split())


def render_label(label_lemma: str, gloss: str | None) -> str:
    """How a client sees an exemplar label: the Hebrew lemma, with a gloss as a reading aid."""
    gloss = clean_gloss(gloss)
    return f"{label_lemma} · {gloss}" if gloss else label_lemma


def random_control(rows: list[Row], counts: collections.Counter, seed: int) -> list[Row]:
    """Permute served groups among served words in the same frequency band (FrequencyMatcher's
    20 rank buckets). Every group keeps its exact size; only which words it holds becomes random."""
    from macula.intrinsic_yardstick import FrequencyMatcher

    served = sorted((s, gid) for s, _a, gid, _sh, sv in rows if sv)
    fm = FrequencyMatcher({s: counts.get(s, 0) for s, _ in served})
    by_bucket: dict[int, list[tuple[str, str]]] = collections.defaultdict(list)
    for s, gid in served:
        by_bucket[fm._bucket_of[s]].append((s, gid))
    rng = random.Random(seed)
    out: list[Row] = []
    for bucket in sorted(by_bucket):
        words = [s for s, _ in by_bucket[bucket]]
        gids = [g for _, g in by_bucket[bucket]]
        rng.shuffle(gids)
        out += [(s, "random", g, 1.0, 1) for s, g in zip(words, gids)]
    return out


# ---------- writing ----------

def write_provider(name: str, rows: list[Row], groups: dict[str, tuple], out_dir: Path = OUT) -> dict:
    """groups: gid -> (label, label_strong, label_lemma)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows)
    n_served = collections.Counter(gid for _s, _a, gid, _sh, sv in rows if sv)
    mem = out_dir / f"{name}.members.tsv"
    grp = out_dir / f"{name}.groups.tsv"
    with mem.open("w", encoding="utf-8") as fh:
        fh.write("strong\taxis\tgroup_id\tshare\tserved\n")
        for s, a, g, sh, sv in rows:
            fh.write(f"{s}\t{a}\t{g}\t{sh}\t{sv}\n")
    with grp.open("w", encoding="utf-8") as fh:
        fh.write("group_id\tlabel\tlabel_strong\tlabel_lemma\tn_served\n")
        for gid in sorted(set(groups) | set(n_served)):
            label, ls, ll = groups.get(gid, ("", "", ""))
            fh.write(f"{gid}\t{label}\t{ls}\t{ll}\t{n_served.get(gid, 0)}\n")
    return {"members": _sha256(mem), "groups": _sha256(grp), "rows": len(rows),
            "served_words": sum(n_served.values()), "served_groups": len(n_served)}


def load_provider(name: str, out_dir: Path = OUT) -> tuple[list[Row], dict[str, dict]]:
    rows: list[Row] = []
    with (out_dir / f"{name}.members.tsv").open(encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            s, a, g, sh, sv = line.rstrip("\n").split("\t")
            rows.append((s, a, g, float(sh), int(sv)))
    groups: dict[str, dict] = {}
    with (out_dir / f"{name}.groups.tsv").open(encoding="utf-8") as fh:
        header = next(fh).rstrip("\n").split("\t")
        for line in fh:
            rec = dict(zip(header, line.rstrip("\n").split("\t")))
            groups[rec["group_id"]] = rec
    return rows, groups


def build_all(out_dir: Path = OUT) -> dict:
    counts, lemmas = token_counts(), lemma_of()
    manifest: dict = {"inputs": {str(p.relative_to(ROOT)): _sha256(p)
                                 for p in (CLUSTERS, HBO_DOMAINS, SPINE_DB, HBO, CLUSTERS_NB, OCC_NB)},
                      "min_share": MIN_SHARE, "providers": {}}
    built: dict[str, list[Row]] = {}

    p0_rows, p0_labels = build_p0() if HBO_DOMAINS.exists() else ([], {})
    if p0_rows:
        p0_groups = {g: (lab, "", "") for g, lab in p0_labels.items()}
        manifest["providers"]["P0"] = write_provider("P0", p0_rows, p0_groups, out_dir)
        built["P0"] = p0_rows
    elif (FROZEN_P0 := OUT / "P0.members.tsv").exists():
        # hbo.tsv was re-sourced from the UBS open release (2026-10) and no longer has core/ctx:
        # P0 is the frozen snapshot from before, copied as-is.
        for suffix in ("members", "groups"):
            src = OUT / f"P0.{suffix}.tsv"
            if out_dir != OUT:
                (out_dir / f"P0.{suffix}.tsv").write_bytes(src.read_bytes())
        built["P0"], p0_groups_rec = load_provider("P0", OUT)
        manifest["providers"]["P0"] = {"members": _sha256(OUT / "P0.members.tsv"),
                                       "groups": _sha256(OUT / "P0.groups.tsv"), "rows": len(built["P0"]),
                                       "served_words": sum(r[4] for r in built["P0"]),
                                       "served_groups": len({r[2] for r in built["P0"] if r[4]}),
                                       "frozen": True}
        print("[providers] hbo.tsv has no core/ctx; kept the frozen P0 snapshot", file=sys.stderr)

    manifest["providers"]["P0none"] = write_provider("P0none", [], {}, out_dir)

    occ, unit_gloss = unit_occurrences()
    for name, high_only in (("P1", True), ("P2", False)):
        rows, sense_gloss = build_clusters(high_only, occ, unit_gloss)
        ex = exemplar_labels(rows, counts, lemmas)
        groups = {g: (render_label(ll, sense_gloss.get((ls, g)) or english_gloss(ls)), ls, ll)
                  for g, (ls, ll) in ex.items()}
        manifest["providers"][name] = write_provider(name, rows, groups, out_dir)
        built[name] = rows

    if CLUSTERS_NB.exists() and OCC_NB.exists():
        occ_nb, gloss_nb = lexeme_occurrences_nb()
        for name, high_only in (("P1nb", True), ("P2nb", False)):
            rows, sense_gloss = build_clusters(high_only, occ_nb, gloss_nb, CLUSTERS_NB)
            ex = exemplar_labels(rows, counts, lemmas)
            groups = {g: (render_label(ll, sense_gloss.get((ls, g)) or english_gloss(ls)), ls, ll)
                      for g, (ls, ll) in ex.items()}
            manifest["providers"][name] = write_provider(name, rows, groups, out_dir)
            built[name] = rows

    for name, (path, unit_kind) in ABLATIONS.items():
        if not path.exists():
            continue
        occ_u, gloss_u = ((occ, unit_gloss) if unit_kind == "sense" else
                          rsense_occurrences_nb() if unit_kind == "rsense" else
                          rsense_occurrences_nb(RENDERING_SENSES.with_name("occurrences_nouns.tsv"))
                          if unit_kind == "rsense_nouns" else lexeme_occurrences_nb())
        rows, sense_gloss = build_clusters(False, occ_u, gloss_u, path)
        ex = exemplar_labels(rows, counts, lemmas)
        groups = {g: (render_label(ll, sense_gloss.get((ls, g)) or english_gloss(ls)), ls, ll)
                  for g, (ls, ll) in ex.items()}
        manifest["providers"][name] = write_provider(name, rows, groups, out_dir)
        built[name] = rows

    for base in RANDOM_BASES:
        if base not in built:
            continue
        rows = random_control(built[base], counts, CONTROL_SEED)
        _, base_groups = (load_provider(base, out_dir))
        groups = {g: (r["label"], r["label_strong"], r["label_lemma"]) for g, r in base_groups.items()}
        name = f"PR-{base}"
        manifest["providers"][name] = write_provider(name, rows, groups, out_dir)

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="rebuild into a temp dir and confirm every provider hash matches the frozen manifest")
    args = ap.parse_args()

    if args.check:
        import tempfile
        frozen = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            if (OUT / "P0.members.tsv").exists() and not HBO_DOMAINS.exists():
                for suffix in ("members", "groups"):
                    (tmpdir / f"P0.{suffix}.tsv").write_bytes((OUT / f"P0.{suffix}.tsv").read_bytes())
            fresh = build_all(tmpdir)
        bad = [n for n, rec in frozen["providers"].items()
               if fresh["providers"].get(n, {}).get("members") != rec["members"]
               or fresh["providers"].get(n, {}).get("groups") != rec["groups"]]
        for n, rec in fresh["providers"].items():
            print(f"[check] {n:10} {'OK ' if n not in bad else 'DIFF'} rows={rec['rows']} "
                  f"served_words={rec['served_words']} served_groups={rec['served_groups']}")
        return 1 if bad else 0

    manifest = build_all()
    for n, rec in manifest["providers"].items():
        print(f"[providers] {n:10} rows={rec['rows']:6} served_words={rec['served_words']:5} "
              f"served_groups={rec['served_groups']:4}")
    print(f"[providers] -> {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
