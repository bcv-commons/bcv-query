"""The verse card of the Hebrew ladder (SPEC-ladder 9).

    cd shoresh && .venv/bin/python -m macula.ladder_card <BOOK> <ch>:<v> --step N [--part hbo|heb_mod|heb_scg] [--build pilot-1]

N is 1-4 (SPEC-ladder 0.2): 1 easiest, 2 easy, 3 more advanced, 4 the real text (step 1 only in JON, PSA 1-41,
ISA 40-55). The steps are read from the build's profiles.toml.

Prints one json object on stdout. Reads only local files; writes nothing; opens nothing over the network. A step the
verse does not have is an error: exit code 2 and a json `error` with the lowest step the verse has.
"""
import argparse, collections, hashlib, json, re, sys, tomllib
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
K1 = DATA / "source-examples" / "k1"
L2 = DATA / "hebrew-levels" / "pilot-2"
REPO = HERE.parent.parent
SIM = DATA / "clauses-similar"
CKEYS = DATA / "clause-keys" / "2026-11-19" / "clause_keys.parquet"
RARE = 20


def portion(book, ch):
    if book in ("JON", "RUT", "MRK"): return book
    if book == "PSA" and 1 <= ch <= 41: return "PSA1-41"
    if book == "ISA" and 40 <= ch <= 55: return "ISA40-55"
    if book == "GEN" and 22 <= ch <= 25: return "GEN22-25"
    return ""


def fail(msg, **kw):
    print(json.dumps({"error": msg, **kw}, ensure_ascii=False)); sys.exit(2)


def tsv(p):
    L = p.read_text(encoding="utf-8").split("\n")
    h = L[0].split("\t")
    return [dict(zip(h, l.split("\t"))) for l in L[1:] if l]


def rel(p):
    return str(Path(p).resolve().relative_to(REPO))


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def codes(s):
    return [x for x in re.split(r"[\s,;|]+", s or "") if x]


class Card:
    def __init__(self, build):
        self.d = DATA / "hebrew-ladder" / build
        P = tomllib.loads((self.d / "profiles.toml").read_text(encoding="utf-8"))
        self.steps = {s["step"]: s for s in P["step"]}
        self.sj = json.loads((self.d / "sources.json").read_text(encoding="utf-8"))
        self.bj = json.loads((self.d / "build.json").read_text(encoding="utf-8"))

    def has(self, por, part):
        return [n for n, s in sorted(self.steps.items()) if por in s["portions"] and part in s.get("level", {"hbo": s.get("base_level")})]

    def src(self, key, dataset, path, basis):
        p = Path(path)
        if p.is_absolute() and self.d in p.parents:
            r = str(p.relative_to(self.d)); h = self.bj["files"].get(r)
            path = f"{rel(self.d)}/{r}"
        else:
            path = rel(p); h = self.sj.get(path, {}).get("sha256")
        if h is None: h = sha_file(p)
        return {"dataset": dataset, "path": path, "sha256": h, "basis": basis}

    def run(self, book, cv, step, part):
        ch, v = (int(x) for x in cv.split(":"))
        key = f"{book} {ch}:{v}"; por = portion(book, ch)
        part = part or ("heb_mod" if book == "MRK" else "hbo")
        have = self.has(por, part) if por else []
        if not have: fail("verse_not_in_scope", key=key, part=part)
        if step not in have: fail("no_such_step", key=key, part=part, step=step, lowest_step=have[0])
        st = self.steps[step]; td = self.d / "texts" / f"step{step}" / part
        W = [r for r in pq.read_table(td / "words.parquet", filters=[("book", "=", book), ("chapter", "=", ch), ("verse", "=", v)]).to_pylist()]
        ts = [w["t"] for w in W]
        Pc = pq.read_table(td / "pieces.parquet", filters=[("t", ">=", ts[0]), ("t", "<=", ts[-1])]).to_pylist()
        K = pq.read_table(td / "links.parquet", filters=[("t", ">=", ts[0]), ("t", "<=", ts[-1])]).to_pylist()
        kl = collections.defaultdict(list); pl = collections.defaultdict(list)
        for k in K: kl[k["t"]].append(k)
        for p in Pc: pl[p["t"]].append(p)
        # the V words' gloss ids (Metzudat Zion), from the pilot-2 log
        opids = sorted({w["op"] for w in W if w["op"].startswith("op:")})
        gl = {}
        if opids:
            for o in pq.read_table(L2 / "ops.parquet", columns=["op", "switch", "detail"], filters=[("op", "in", opids)]).to_pylist():
                if o["switch"] == "v": gl[o["op"]] = json.loads(o["detail"]).get("gloss", "")
        words = []
        for w in W:
            hows = sorted({k["how"] for k in kl[w["t"]]})
            wit = (kl[w["t"]][0].get("comment") or "") if "comment" in hows else gl.get(w["op"], "")
            words.append({"t": w["t"], "text": w["text"], "src": sorted({(k["s"], k["s_n"]) for k in kl[w["t"]]}),
                          "how": "+".join(hows), "witness": wit})
        for x in words: x["src"] = [list(s) for s in x["src"]]
        line = next(r["line"] for r in tsv(self.d / "lines" / f"step{step}" / f"{part}.point.tsv") if r["key"] == key)
        nxt = [{"change": r["change"], "kind": r["kind"], "text_here": r["text_here"], "text_next": r["text_next"],
                "words_here": json.loads(r["words_here"]), "words_next": json.loads(r["words_next"])}
               for r in pq.read_table(self.d / "changes.parquet", filters=[("step", "=", step), ("part", "=", part), ("key", "=", key)]).to_pylist()]
        # the source words of the verse
        SW = pq.read_table(K1 / part / "words.parquet", columns=["t", "book", "chapter", "verse", "text"],
                           filters=[("book", "=", book), ("chapter", "=", ch), ("verse", "=", v)]).to_pylist()
        st_ = [w["t"] for w in SW]
        SP = pq.read_table(K1 / part / "pieces.parquet", columns=["t", "n", "kind", "lexeme", "who", "who_basis", "sense", "domain"],
                           filters=[("t", ">=", st_[0]), ("t", "<=", st_[-1])]).to_pylist()
        # who
        parts_tsv = {r["ent"]: r for r in tsv(K1 / part / "participants.tsv")}
        ent_src = collections.defaultdict(set)
        for p in SP:
            if p["who"] and p["who_basis"] != "model":
                for e in p["who"].split(): ent_src[e].add((p["t"], p["n"]))
        who = []
        for e in sorted(ent_src):
            here = sorted({w["t"] for w in W if any((k["s"], k["s_n"]) in ent_src[e] for k in kl[w["t"]])
                           or any(e in p["who"].split() for p in pl[w["t"]])})
            r = parts_tsv.get(e, {})
            who.append({"ent": e, "name": r.get("name", ""), "type": r.get("type", ""), "words_here": here})
        # hard words
        lex = {r["lexeme"]: r for r in tsv(K1 / "lexicon" / "lexemes.tsv")}
        gloss = collections.defaultdict(list)
        if part == "hbo":
            for g in pq.read_table(self.d / "banks" / "gloss.parquet", columns=["gloss", "key", "n", "anchor_state", "anchor_part", "anchor_t", "core", "body"],
                                   filters=[("key", "=", key)]).to_pylist():
                if g["anchor_state"] == "anchored" and g["anchor_part"] == "hbo":
                    for t in json.loads(g["anchor_t"]): gloss[t].append(g)
        sp = collections.defaultdict(list)
        for p in SP: sp[p["t"]].append(p)
        hard = []
        for w in SW:
            stem = next((p for p in sp[w["t"]] if p["kind"] == "stem"), None)
            lx = stem["lexeme"] if stem else ""
            cnt = int(lex[lx]["tanakh"]) if lx in lex and lex[lx]["tanakh"] != "" else None
            g = sorted(gloss.get(w["t"], []), key=lambda g: g["n"])
            if not (g or (cnt is not None and cnt < RARE)): continue
            hard.append({"t": w["t"], "text": w["text"], "lexeme": lx, "tanakh_count": cnt,
                         "gloss": {"gloss": g[0]["gloss"], "core": g[0]["core"], "body": g[0]["body"]} if g else None,
                         "sense": sorted({c for p in sp[w["t"]] for c in codes(p["sense"])}) if part == "hbo" else [],
                         "domain": sorted({c for p in sp[w["t"]] for c in codes(p["domain"])}) if part == "hbo" else []})
        # passages
        pas = [{"passage": r["passage"], "source": r["source"], "kind": r["kind"], "fact": r["fact"]}
               for r in pq.read_table(K1 / part / "passages.parquet", columns=["passage", "source", "kind", "first", "last", "fact"],
                                      filters=[("first", "<=", st_[-1]), ("last", ">=", st_[0])]).to_pylist()]
        # similar (9.2)
        cls = list(dict.fromkeys(w["clause"] for w in W if w["clause"]))
        sim = self.similar(part, cls)
        lay = [{"clause": r["clause"], "depth": int(r["depth"]) if r["depth"] != "" else None, "line": r["line"]}
               for r in tsv(self.d / "layout" / f"step{step}" / f"{part}.tsv") if r["key"] == key]
        comments = sorted({x["witness"] for x in words if x["witness"].startswith("md:")})
        glosses = sorted({x["witness"] for x in words if x["witness"].startswith("mz:")})
        d = self.d
        textsrc = [self.src("text", f"hebrew-ladder/{d.name} step {step}", td / "words.parquet", "derived"),
                   self.src("text", f"hebrew-ladder/{d.name} step {step}", td / "links.parquet", "derived"),
                   self.src("text", f"hebrew-ladder/{d.name} lines", d / "lines" / f"step{step}" / f"{part}.point.tsv", "derived")]
        if step == 1: textsrc.append(self.src("text", f"hebrew-ladder/{d.name} chooser", d / "chooser" / "choices_model.parquet", "model"))
        sources = {
            "key": [self.src("key", f"hebrew-ladder/{d.name} profiles", d / "profiles.toml", "derived")],
            "text": textsrc,
            "next": [self.src("next", f"hebrew-ladder/{d.name} changes", d / "changes.parquet", "derived")],
            "who": [self.src("who", "k1 pieces", K1 / part / "pieces.parquet", "given"),
                    self.src("who", "k1 participants", K1 / part / "participants.tsv", "derived")],
            "hard_words": [self.src("hard_words", "k1 pieces", K1 / part / "pieces.parquet", "given"),
                           self.src("hard_words", "k1 lexicon", K1 / "lexicon" / "lexemes.tsv", "given"),
                           self.src("hard_words", f"hebrew-ladder/{d.name} gloss bank", d / "banks" / "gloss.parquet", "derived")],
            "passage": [self.src("passage", "k1 passages", K1 / part / "passages.parquet", "given")],
            "similar": [self.src("similar", "clauses-similar (a vector neighbour table)", SIM / "hebrew.parquet", "derived"),
                        self.src("similar", "clauses-similar (a vector neighbour table)", SIM / "tanakh-nt.parquet", "derived"),
                        self.src("similar", "clause-keys", CKEYS, "derived")],
            "layout": [self.src("layout", f"hebrew-ladder/{d.name} layout", d / "layout" / f"step{step}" / f"{part}.tsv", "derived")],
        }
        if part != "hbo": sources["similar"].append(self.src("similar", "k1 clauses", K1 / part / "clauses.parquet", "derived"))
        return {"key": key, "part": part, "step": step, "name": st["name"],
                "text": {"line": line, "words": words}, "next": nxt, "who": who, "hard_words": hard, "passage": pas,
                "similar": sim, "layout": lay, "sources": sources,
                "witness": {"code": "jewish_reading_aid" if comments or glosses else "", "comments": comments, "glosses": glosses}}

    def similar(self, part, cls):
        ck = pq.read_table(CKEYS, columns=["clause", "lang"]).to_pylist()
        have = {(r["lang"], r["clause"]) for r in ck}
        out = []
        if part == "hbo":
            ids = {c: m.group(1) for c in cls if (m := re.match(r"cl:o(\d{12}):", c)) and ("hbo", m.group(1)) in have}
            q = sorted(set(ids.values()))
            H = pq.read_table(SIM / "hebrew.parquet", filters=[("clause_key", "in", q)]).to_pylist() if q else []
            N = pq.read_table(SIM / "tanakh-nt.parquet", filters=[("clause_key", "in", q)]).to_pylist() if q else []
            for c in cls:
                if c not in ids: out.append({"clause": c, "tanakh": [], "nt": [], "reason": "no_join"}); continue
                i = ids[c]
                out.append({"clause": c, "tanakh": [r["other"] for r in sorted((r for r in H if r["clause_key"] == i), key=lambda r: r["rank"])][:5],
                            "nt": [r["nt_clause"] for r in sorted((r for r in N if r["clause_key"] == i), key=lambda r: r["rank"])][:5]})
            return out
        fc = {r["clause"]: r["from_clause"] for r in pq.read_table(K1 / part / "clauses.parquet", columns=["clause", "from_clause"],
                                                                     filters=[("clause", "in", cls)]).to_pylist()} if cls else {}
        ids = {c: m.group(1) for c in cls if (m := re.match(r"cl:n(\d{11}):", fc.get(c) or "")) and ("grc", m.group(1)) in have}
        q = sorted(set(ids.values()))
        N = pq.read_table(SIM / "tanakh-nt.parquet", filters=[("nt_clause", "in", q)]).to_pylist() if q else []
        for c in cls:
            rows = sorted((r for r in N if r["nt_clause"] == ids.get(c)), key=lambda r: (r["rank"], -r["score"], r["clause_key"]))
            if c not in ids or not rows: out.append({"clause": c, "tanakh": [], "nt": [], "reason": "no_join"}); continue
            out.append({"clause": c, "tanakh": [r["clause_key"] for r in rows][:5], "nt": []})
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book"); ap.add_argument("cv"); ap.add_argument("--step", type=int, required=True)
    ap.add_argument("--part"); ap.add_argument("--build", default="pilot-1")
    a = ap.parse_args()
    print(json.dumps(Card(a.build).run(a.book, a.cv, a.step, a.part), ensure_ascii=False))


if __name__ == "__main__":
    main()
