"""Glossed chapters of the source examples (stage 10): one table per verse, one row per piece.

    shoresh/.venv/bin/python -I shoresh/macula/examples_glossed.py BUILD_DIR OUT_DIR

Adapted from internal-docs/source-examples-work/tools/gloss.py. Per piece: the word (on its first piece), the piece,
its kind, lexeme, class, marks (the codes of `pieces.marks`), its head piece (`t.n` and its letters, or `root`), the
label of that edge (`pieces.rel`), the word's innermost clause (its number in the verse, then the clause's rule; the
keys are listed under the table), and the participant(s) of the piece (`ent` keys with the name of `participants.tsv`).
No English gloss: nothing from MACULA's `gloss` or `english` is read. Every value is copied from the tables.
"""
import collections as C
import json
import os
import sys

import pyarrow.parquet as pq

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import examples_common as X  # noqa: E402

CHAPTERS = [("hbo", "GEN", 22, "narrative"), ("hbo", "PSA", 23, "psalm"), ("hbo", "LEV", 19, "law"),
            ("hbo", "ISA", 40, "prophecy"), ("arc", "DAN", 3, "Aramaic narrative"), ("grc", "MRK", 4, "gospel narrative"),
            ("grc", "ROM", 8, "letter, argument"), ("grc", "HEB", 1, "letter, exposition")]
FILE = {("hbo", "GEN", 22): "genesis-22", ("hbo", "PSA", 23): "psalm-23", ("hbo", "LEV", 19): "leviticus-19",
        ("hbo", "ISA", 40): "isaiah-40", ("arc", "DAN", 3): "daniel-3-aramaic", ("grc", "MRK", 4): "mark-4",
        ("grc", "ROM", 8): "romans-8", ("grc", "HEB", 1): "hebrews-1"}


def _cell(s):
    return str(s).replace("|", "\\|")


def chapter(build, lang, book, ch, kind):
    d = os.path.join(build, lang)
    W = [w for w in pq.read_table(os.path.join(d, "words.parquet")).to_pylist() if w["book"] == book and w["chapter"] == ch]
    ts = {w["t"] for w in W}
    P = C.defaultdict(list)
    text_of = {}
    for p in pq.read_table(os.path.join(d, "pieces.parquet"),
                           columns=["t", "n", "text", "kind", "lexeme", "class", "marks", "head_t", "head_n", "head_basis",
                                    "rel", "who"]).to_pylist():
        if p["t"] in ts:
            P[p["t"]].append(p)
    # head pieces may lie outside the chapter (never outside the verse); in GEN 31:47 and DAN 2:4 in the other table
    need = {(p["head_t"], p["head_n"]) for ps in P.values() for p in ps}
    for other in sorted({lang, "hbo", "arc"} if lang in ("hbo", "arc") else {lang}):
        for p in pq.read_table(os.path.join(build, other, "pieces.parquet"), columns=["t", "n", "text"]).to_pylist():
            if (p["t"], p["n"]) in need:
                text_of[(p["t"], p["n"])] = p["text"]
    rule = {c["clause"]: (c["rule"], c["parent"]) for c in pq.read_table(os.path.join(d, "clauses.parquet"),
                                                                       columns=["clause", "rule", "parent", "book", "chapter"]).to_pylist()
            if c["book"] == book and c["chapter"] == ch}
    with open(os.path.join(d, "participants.tsv"), encoding="utf-8") as fh:
        rows = [ln.split("\t") for ln in fh.read().split("\n")[1:] if ln]
    name = {r[0]: r[2] for r in rows}
    out = [f"# {book} {ch} ({lang}, {kind}): the tables, piece by piece", "",
           "Written by `build_examples.py --stage 10` (`examples_glossed.py`) from the source examples. One table per verse,",
           "one row per piece (`pieces.parquet`). `marks`: the piece's codes; `head`: the piece it depends on as `t.n` and its",
           "letters (`root` for the root of the sentence), with `head_basis` where it is not `index`; `label`: `pieces.rel`;",
           "`clause`: the word's innermost clause, numbered in the verse, with its rule (the keys follow the table);",
           "`participant`: `pieces.who` with the name `participants.tsv` gives. No gloss: nothing English is read.", ""]
    nverse = npiece = 0
    for v in sorted({w["verse"] for w in W}):
        ws = sorted((w for w in W if w["verse"] == v), key=lambda w: w["t"])
        nverse += 1
        order = []
        for w in ws:
            if w["clause"] and w["clause"] not in order:
                order.append(w["clause"])
        num = {c: i + 1 for i, c in enumerate(order)}
        out += [f"## {book} {ch}:{v}", "", "| t.n | word | piece | kind | lexeme | class | marks | head | label | clause | participant |",
                "|---|---|---|---|---|---|---|---|---|---|---|"]
        for w in ws:
            for i, p in enumerate(sorted(P[w["t"]], key=lambda p: p["n"])):
                npiece += 1
                m = json.loads(p["marks"])
                marks = " ".join(f"{k}={m[k]}" for k in sorted(m))
                if p["head_basis"] == "root":
                    head = "root"
                else:
                    head = f"{p['head_t']}.{p['head_n']} {text_of.get((p['head_t'], p['head_n']), '?')}"
                    if p["head_basis"] != "index":
                        head += f" ({p['head_basis']})"
                cl = f"{num[w['clause']]} {rule.get(w['clause'], ('?', ''))[0]}" if (w["clause"] and i == 0) else ""
                who = " ".join(f"`{e}`" + (f" {name[e]}" if name.get(e) else "") for e in p["who"].split())
                out.append("| " + " | ".join(_cell(x) for x in [
                    f"{p['t']}.{p['n']}", w["text"] if i == 0 else "", p["text"], p["kind"], p["lexeme"], p["class"], marks,
                    head, p["rel"], cl, who]) + " |")
        out += [""] + [f"- clause {num[c]}: `{c}`" + (f", in `{rule[c][1]}`" if c in rule and rule[c][1] else "")
                       for c in order] + [""]
    return "\n".join(out), nverse, npiece


def build_all(build, outdir, counts):
    for lang, book, ch, kind in CHAPTERS:
        text, nv, npc = chapter(build, lang, book, ch, kind)
        X.write_text(os.path.join(outdir, FILE[(lang, book, ch)] + ".md"), text)
        counts[f"glossed {lang} {book} {ch}"] = f"{nv} verses, {npc} pieces"


if __name__ == "__main__":
    cnt = {}
    build_all(sys.argv[1], sys.argv[2], cnt)
    for k, v in cnt.items():
        print(k, v)
