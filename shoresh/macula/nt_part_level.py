"""The part level inside the aligner's word links: Greek parts (word-parts v1.0) to Hebrew parts (hebrew-nt-analysis v0.2) of a
Hebrew New Testament, within each Greek word's reviewed link (hebrew-nt-bridge, from bcv-commons/alignments-by-id).

    cd shoresh && .venv/bin/python -m macula.nt_part_level build  --edition heb_scg [--books MRK,ROM,REV]
    cd shoresh && .venv/bin/python -m macula.nt_part_level ask    --edition heb_scg [--books ...] [--max-usd N]   (Jev; key in env)
    cd shoresh && .venv/bin/python -m macula.nt_part_level finish --edition heb_scg [--books ...]

A Greek word's link gives the Hebrew parts H that render it; word-parts gives its parts P. Inside that link:
  rule:one_greek_part    |P| = 1: the part goes to every part of H
  rule:one_hebrew_part   |H| = 1: every part of P goes to it
  eflomal                otherwise, where eflomal's part links (2026-11-22-wp1, five runs) made in 4 or 5 runs settle the word:
                         every Hebrew part of H has a Greek part and every Greek part has a Hebrew part
  jev                    otherwise: Jev (TypeSafe System One) is asked, per Hebrew part of H, which part of the Greek word it renders
                         (or the Greek word as a whole). A Greek part no Hebrew part chose goes to the parts that chose the whole
                         word, else to the link's content parts (basis jev+implied).
  rule:verb_government, rule:om_case   two grammar rules over Jev's choice for a Hebrew preposition or אֵת (see grammar()).
Held out: one in five eflomal-settled words (greek id's last digit 0 or 5) is also asked, to measure Jev against eflomal
(--hold-all: every one of them is asked, and Jev's answer is used in place of eflomal's; the held-out figure then measures
how far the two agree. Chosen 2026-11-22: on the three test books Jev was right in about 18 of the 22 places where they
disagreed.)
Words with no link stay at word level (the aligner's `none` or unlinked); they get no part row.

Writes data/nt-part-level/<edition>/{jev_items.jsonl, jev_answers.jsonl, part_links.parquet, report.json}. Nothing is sent
but the Greek New Testament (MACULA, CC BY 4.0) and the Hebrew edition (public domain): no English, no other text.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORD_PARTS = ("bcv-commons/word-parts", "v1.0", "9733875e")   # the Greek parts: repo, tag, commit (pinned)
BRIDGE = HERE / "data" / "hebrew-nt-bridge"
ANALYSIS = HERE / "data" / "bridge-corpus" / "inputs" / "hebrew-nt-analysis@v0.2"
EFLOMAL = HERE / "data" / "hebrew-nt-part-links" / "2026-11-22-wp1"
OUT = HERE / "data" / "nt-part-level"
CONTENT = {"noun", "verb", "adj", "adv", "num", "pron", "-", "x"}
FIRM = 4
csv.field_size_limit(sys.maxsize)
BOOKS = {n: b for n, b in zip(range(40, 67), "MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP COL 1TH 2TH 1TI 2TI TIT PHM HEB JAS 1PE 2PE 1JN 2JN 3JN JUD REV".split())}


def word_parts() -> Path:
    """the folder of word-parts v1.0's Greek files, downloaded from Hugging Face at the pinned tag (cached by huggingface_hub);
    the tag must still be the pinned commit"""
    from huggingface_hub import HfApi, hf_hub_download
    repo, tag, commit = WORD_PARTS
    sha = HfApi().dataset_info(repo, revision=tag).sha
    if not sha.startswith(commit):
        raise SystemExit(f"{repo} tag {tag} is {sha[:8]}, the pin says {commit}")
    for n in ("greek/parts.tsv", "greek/words.tsv"):
        got = Path(hf_hub_download(repo, n, repo_type="dataset", revision=sha))
    return got.parent


def tsv(p):
    with open(p, encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)


def load(ed, books):
    WP = word_parts()
    gparts = collections.defaultdict(list)
    for r in tsv(WP / "parts.tsv"):
        if BOOKS[int(r["word_id"][:2])] in books:
            gparts[r["word_id"]].append((int(r["n"]), r["part_id"], r["text"], r["kind"]))
    gwords = {r["word_id"]: r["lead"] + r["surface"] + r["trail"] for r in tsv(WP / "words.tsv") if r["word_id"] in gparts}
    H = collections.defaultdict(dict)
    for l in pq.read_table(BRIDGE / ed / "links.parquet").to_pylist():
        if l["book"] in books and l["greek_id"][1:] in gparts:
            H[l["greek_id"][1:]][(l["book"], l["chapter"], l["verse"], l["i"], l["part"])] = (l["hebrew_class"], l["link"])
    htext, hword = {}, {}
    for r in pq.read_table(ANALYSIS / ed / "words.parquet", columns=["book", "chapter", "verse", "i", "part", "word", "text", "class"]).to_pylist():
        if r["book"] in books:
            htext[(r["book"], r["chapter"], r["verse"], r["i"], r["part"])] = (r["text"], r["class"])
            hword[(r["book"], r["chapter"], r["verse"], r["i"])] = r["word"]
    ef = collections.Counter()
    for r in pq.read_table(EFLOMAL / ed / "part_links.parquet").to_pylist():
        if r["book"] in books and r["runs"] >= FIRM:
            ef[(r["greek_id"][1:], r["greek_n"], (r["book"], r["chapter"], r["verse"], r["i"], r["part"]))] = r["runs"]
    return gparts, gwords, H, htext, hword, ef


def ef_has(ef, g, n, h):
    return ef.get((g, n, h)) or ef.get((g, n, h[:4] + (-1,)))


def plan(ed, books, hold_all=False):
    gparts, gwords, H, htext, hword, ef = load(ed, books)
    rows, items, cnt = [], [], collections.Counter()
    for g in sorted(gparts):
        P = sorted(gparts[g]); hs = sorted(H.get(g, {}))
        if not hs:
            cnt["words: no link (word level only)"] += 1
            continue
        cls = {h: H[g][h] for h in hs}
        if len(P) == 1 or len(hs) == 1:
            basis = "rule:one_greek_part" if len(P) == 1 else "rule:one_hebrew_part"
            cnt[f"words: {basis}"] += 1
            rows += [(g, p[1], p[3], h, cls[h][0], cls[h][1], basis, None) for p in P for h in hs]
            continue
        pairs = [(p, h) for p in P for h in hs if ef_has(ef, g, p[0], h)]
        settled = {p[0] for p, _ in pairs} == {p[0] for p in P} and {h for _, h in pairs} == set(hs)
        held = settled and (hold_all or g[-1] in "05")
        if settled:
            cnt["words: eflomal"] += 1
            rows += [(g, p[1], p[3], h, cls[h][0], cls[h][1], "eflomal", None) for p, h in pairs]
        else:
            cnt["words: open (jev)"] += 1
        if not settled or held:
            cnt["words: held out (also asked)"] += held
            b, c, v = hs[0][:3]
            gverse = " ".join(gwords[k] for k in sorted(gwords) if k[:8] == g[:8])
            hverse = " ".join(hword[k] for k in sorted(hword) if k[:3] == (b, c, v))
            items.append({"id": f"{ed}:{g}", "greek_id": g, "held": held, "greek_verse": gverse, "greek_word": gwords[g],
                          "greek_parts": {f"g{p[0]}": {"text": p[2], "kind": p[3]} for p in P},
                          "hebrew_verse": hverse,
                          "hebrew_parts": {f"h{k}": {"word": hword[h[:4]], "part": htext.get(h, ("", ""))[0], "class": cls[h][0]}
                                           for k, h in enumerate(hs)},
                          "hebrew_keys": {f"h{k}": list(h) for k, h in enumerate(hs)},
                          "eflomal": [[f"g{p[0]}", f"h{hs.index(h)}"] for p, h in pairs]})
    return rows, items, cnt


def ask_one(item, model):
    state = {"greek_verse": item["greek_verse"], "greek_word": item["greek_word"], "greek_word_parts": item["greek_parts"],
             "hebrew_verse": item["hebrew_verse"], "hebrew_parts_rendering_the_word": item["hebrew_parts"]}
    crit = {k: f"the Greek part {v['text']} ({v['kind']})" for k, v in item["greek_parts"].items()}
    crit["whole"] = "the Greek word as a whole, no one part of it"
    qs = {h: {"type": "choice", "criteria": crit,
              "instructions": f"The Hebrew part {v['part']} (of the Hebrew word {v['word']}, class {v['class']}) is one of the Hebrew "
                              "parts that render the Greek word `greek_word` in this verse. Which part of the Greek word does this "
                              "Hebrew part render? A Hebrew prefixed preposition usually renders a Greek case ending; a Hebrew stem "
                              "the Greek stem; a pronoun suffix a person ending or a pronoun. Choose 'whole' if it renders the word "
                              "as a whole."} for h, v in item["hebrew_parts"].items()}
    body = json.dumps({"model": model, "state": state, "questions": qs}).encode("utf-8")
    req = urllib.request.Request("https://api.typesafe.ai/v1/systemone", data=body, method="POST",
                                 headers={"Authorization": "Bearer " + os.environ["TYPESAFE_API_KEY"], "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                raise
            print("retry", attempt, e, file=sys.stderr)
            time.sleep(2 * (attempt + 1))


def cmd_ask(ed, out, max_usd, model, price_in, price_out):
    items = [json.loads(l) for l in (out / "jev_items.jsonl").read_text(encoding="utf-8").splitlines()]
    ans_p = out / "jev_answers.jsonl"
    done = {json.loads(l)["id"] for l in ans_p.read_text(encoding="utf-8").splitlines()} if ans_p.exists() else set()
    spent, n, usage = 0.0, 0, collections.Counter()
    with open(ans_p, "a", encoding="utf-8") as f:
        for it in items:
            if it["id"] in done:
                continue
            if spent >= max_usd:
                print(f"stopped at the cap: USD {spent:.2f}"); break
            r = ask_one(it, model)
            u = r.get("usage", {}); usage.update({k: v for k, v in u.items() if isinstance(v, (int, float))})
            spent += u.get("input_tokens", 0) / 1e6 * price_in + u.get("output_tokens", 0) / 1e6 * price_out
            f.write(json.dumps({"id": it["id"], "model": r.get("model"), "answers": {h: {"choice": a.get("choice"), "probabilities": a.get("probabilities")}
                                                                                   for h, a in r["answers"].items()}}, ensure_ascii=False) + "\n")
            n += 1
            if n % 100 == 0:
                f.flush(); print(n, f"USD {spent:.2f}", dict(usage), file=sys.stderr)
    print(f"asked {n}, USD {spent:.2f} at the stated price, usage {dict(usage)}")


def finite(m):
    """a finite verb or an infinitive (Robinson's code: V-PAI-3S, V-AAN), not a participle (V-PAP-NSM)"""
    return m.startswith("V-") and len(m.split("-")) > 1 and m.split("-")[1][-1:] != "P"


def grammar(m, gparts, hclass, choice):
    """two rules of Hebrew grammar over Jev's choice, for a preposition or the object marker inside a word's link (added
    2026-11-22 after the three-book reader's sample; measured on other books):
      verb_government  in the link of a finite verb or an infinitive, a preposition or אֵת renders the verb's government,
                       not its person ending: the word as a whole (a preverb Jev chose is kept: אֶל for προσ-)
      om_case          אֵת in the link of a noun, adjective, pronoun or participle marks the accusative: the case ending"""
    if hclass not in ("prep", "om"):
        return choice, None
    kind = gparts.get(choice, {}).get("kind")
    if finite(m):
        return (choice, None) if kind == "preverb" or choice == "whole" else ("whole", "rule:verb_government")
    if hclass == "om":
        ends = [k for k, v in gparts.items() if v["kind"] == "ending"]
        if ends and choice != ends[-1]:
            return ends[-1], "rule:om_case"
    return choice, None


def cmd_finish(ed, out, rows, items, jev_first=False):
    WP = word_parts()
    by = {it["id"]: it for it in items}
    ans = {}
    for l in (out / "jev_answers.jsonl").read_text(encoding="utf-8").splitlines():
        a = json.loads(l); ans[a["id"]] = a
    gk = {}
    for r in tsv(WP / "parts.tsv"):
        gk[(r["word_id"], int(r["n"]))] = (r["part_id"], r["kind"])
    morph = {r["word_id"]: r["morph"] for r in tsv(WP / "words.tsv")}
    held_ok = held_n = 0
    cnt = collections.Counter()
    for iid, it in by.items():
        a = ans.get(iid)
        if a is None:
            cnt["open words not answered"] += 1
            continue
        g = it["greek_id"]; keys = {h: tuple(v) for h, v in it["hebrew_keys"].items()}
        choice = {h: x["choice"] for h, x in a["answers"].items()}
        if it["held"]:
            efl = collections.defaultdict(set)
            for gp, h in it["eflomal"]:
                efl[h].add(gp)
            for h, c in choice.items():
                held_n += 1; held_ok += c == "whole" or c in efl[h]
            if not jev_first:
                continue
            rows[:] = [r for r in rows if not (r[0] == g and r[6] == "eflomal")]
            cnt["eflomal words decided by jev instead"] += 1
        chosen = collections.defaultdict(list)
        basis_of = {}
        for h, c in list(choice.items()):
            c2, b2 = grammar(morph.get(g, ""), it["greek_parts"], it["hebrew_parts"][h]["class"], c)
            if c2 != c:
                cnt[f"jev choice changed: {b2}"] += 1
                choice[h], basis_of[h] = c2, b2
        for h, c in choice.items():
            if h in basis_of:
                for gp in (it["greek_parts"] if c == "whole" else [c]):
                    chosen[gp].append((h, basis_of[h]))
            elif c == "whole":
                for gp in it["greek_parts"]:
                    chosen[gp].append((h, "jev"))
            elif c in it["greek_parts"]:
                chosen[c].append((h, "jev"))
        for gp in it["greek_parts"]:
            if not chosen[gp]:
                whole = [h for h, c in choice.items() if c == "whole"]
                cont = [h for h in keys if it["hebrew_parts"][h]["class"] in CONTENT] or list(keys)
                chosen[gp] = [(h, "jev+implied") for h in (whole or cont)]
        for gp, hl in chosen.items():
            pid, kind = gk[(g, int(gp[1:]))]
            for h, basis in hl:
                rows.append((g, pid, kind, keys[h], it["hebrew_parts"][h]["class"], None, basis,
                             (a["answers"][h]["probabilities"] or {}).get(choice[h])))
        cnt["open words answered"] += 1
    return rows, cnt, (held_ok, held_n)


def write(out, ed, rows, cnt, held, books):
    schema = pa.schema([("greek_id", pa.string()), ("greek_part_id", pa.string()), ("greek_kind", pa.string()), ("book", pa.string()),
                        ("chapter", pa.int16()), ("verse", pa.int16()), ("i", pa.int16()), ("part", pa.int8()),
                        ("hebrew_class", pa.string()), ("word_link", pa.string()), ("basis", pa.string()), ("p", pa.float32())])
    recs = [{"greek_id": g, "greek_part_id": pid, "greek_kind": k, "book": h[0], "chapter": h[1], "verse": h[2], "i": h[3], "part": h[4],
             "hebrew_class": hc, "word_link": wl, "basis": b, "p": p} for g, pid, k, h, hc, wl, b, p in rows]
    f = out / "part_links.parquet"
    pq.write_table(pa.Table.from_pylist(recs, schema=schema), f, compression="zstd")
    rep = {"edition": ed, "books": sorted(books), "counts": dict(sorted(cnt.items())),
           "part_links_by_basis": dict(collections.Counter(r["basis"] for r in recs).most_common()),
           "held_out": {"hebrew_parts_asked": held[1], "jev_agrees_with_eflomal": held[0],
                        "share": round(held[0] / held[1], 3) if held[1] else None, "bar": 0.90},
           "inputs": {"word_parts": "bcv-commons/word-parts v1.0 (9733875e)", "bridge": "bcv-commons/hebrew-nt-bridge v0.3 (a1a3d5ed), links sha256 " + hashlib.sha256((BRIDGE / ed / "links.parquet").read_bytes()).hexdigest(),
                      "analysis": "bcv-commons/hebrew-nt-analysis v0.2 (0c9132c3)",
                      "eflomal": hashlib.sha256((EFLOMAL / ed / "part_links.parquet").read_bytes()).hexdigest()},
           "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("build", "ask", "finish"))
    ap.add_argument("--edition", default="heb_scg")
    ap.add_argument("--books", default="", help="comma-separated book codes (default: the whole New Testament)")
    ap.add_argument("--max-usd", type=float, default=10.0)
    ap.add_argument("--model", default="jev-latest")
    ap.add_argument("--hold-all", action="store_true", help="ask Jev on every eflomal-settled word too (the test books)")
    ap.add_argument("--price-in", type=float, default=0.04, help="USD per million input tokens (Jev)")
    ap.add_argument("--price-out", type=float, default=0.15, help="USD per million output tokens (Jev)")
    a = ap.parse_args()
    books = set(a.books.split(",")) if a.books else set(BOOKS.values())
    out = OUT / (a.edition + ("-" + "-".join(sorted(books)) if a.books else ""))
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "ask":
        return cmd_ask(a.edition, out, a.max_usd, a.model, a.price_in, a.price_out)
    rows, items, cnt = plan(a.edition, books, a.hold_all)
    if a.cmd == "build":
        (out / "jev_items.jsonl").write_text("".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items), encoding="utf-8")
        print(dict(cnt), f"{len(items)} items for Jev -> {out}")
        return
    rows, c2, held = cmd_finish(a.edition, out, rows, items, a.hold_all)
    cnt.update(c2)
    write(out, a.edition, rows, cnt, held, books)


if __name__ == "__main__":
    main()
