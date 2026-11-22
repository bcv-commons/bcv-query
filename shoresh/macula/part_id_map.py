"""Map the part ids of one word-parts release onto the next, by letter overlap, and report the churn.

    cd shoresh && .venv/bin/python -m macula.part_id_map --old OLD/parts.tsv --new NEW/parts.tsv --out DIR

Each file is a parts table with a word id and the part's text in reading order: columns (part_id, word_id, n, [start, end,]
text, kind, ...) as in word-parts v1.0, or (key, n, text, kind, features) as in word-parts v0.1 (whose punctuation parts,
kind `mark`, are dropped; their part ids are the key followed by n). Where `start` / `end` are missing they are counted from
the texts: letters (a base letter with its marks) within the word, from 0, end not included.

An old part goes to the new parts that share at least one letter with it. The kind of change:
  same       one new part, same letters, same id
  renumbered one new part, same letters, another id (a boundary moved earlier in the word)
  split      several new parts, together exactly its letters
  merged     one new part that covers it and other whole old parts (several old parts went into one)
  moved      the letters overlap but the boundaries differ
  gone       no new part shares a letter (the word's letters differ between the releases: a text change)
A word's letters are compared first; a word whose letters differ is listed as `text_differs` and its parts as `gone`.

Writes DIR/id_map.tsv (old_id, new_ids space-separated, change), DIR/changed_words.tsv (word_id, old cut, new cut) and
DIR/churn.md. Nothing else is read or written.
"""
from __future__ import annotations

import argparse
import collections
import csv
import sys
import unicodedata as ud
from pathlib import Path

csv.field_size_limit(sys.maxsize)


def letters(s):
    """graphemes: a base character with the combining marks after it"""
    out = []
    for ch in ud.normalize("NFD", s):
        if out and ud.combining(ch):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def read(path):
    """{word_id: [(part_id, start, end, text)]} in reading order"""
    words = collections.defaultdict(list)
    with open(path, encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
        for row in rd:
            if row.get("kind") == "mark":
                continue
            wid = row.get("macula_id") or row.get("word_id") or row["key"]   # Hebrew level 2: spans within MACULA's part
            pid = row.get("part_id") or f"{row['key']}{row['n']}"
            words[wid].append([pid, int(row["n"]), row.get("start"), row.get("end"), row["text"]])
    out = {}
    for wid, ps in words.items():
        ps.sort(key=lambda p: p[1])
        at, rows = 0, []
        for pid, _, st, en, text in ps:
            ln = len(letters(text))
            s0, e0 = (int(st), int(en)) if st not in (None, "") else (at, at + ln)
            rows.append((pid, s0, e0, text))
            at = e0
        out[wid] = rows
    return out


def word_letters(rows):
    return [ud.normalize("NFC", g) for _, _, _, t in rows for g in letters(t)]


def compare(old, new):
    id_map, changed, cnt = [], [], collections.Counter()
    for wid in sorted(set(old) | set(new)):
        o, n = old.get(wid, []), new.get(wid, [])
        cut_o, cut_n = "|".join(p[3] for p in o), "|".join(p[3] for p in n)
        if not o:
            cnt["words only in new"] += 1
            continue
        if not n or word_letters(o) != word_letters(n):
            cnt["words: text_differs" if n else "words only in old"] += 1
            for p in o:
                id_map.append((p[0], "", "gone")); cnt["parts: gone"] += 1
            changed.append((wid, cut_o, cut_n, "text_differs"))
            continue
        kinds = []
        bounds = {p[1] for p in o} | {p[2] for p in o}
        for pid, s, e, _ in o:
            hit = [q for q in n if q[1] < e and s < q[2]]
            if len(hit) == 1 and (hit[0][1], hit[0][2]) == (s, e):
                k = "same" if hit[0][0] == pid else "renumbered"
            elif len(hit) > 1 and hit[0][1] == s and hit[-1][2] == e:
                k = "split"
            elif len(hit) == 1 and hit[0][1] <= s and e <= hit[0][2] and {hit[0][1], hit[0][2]} <= bounds:
                k = "merged"
            else:
                k = "moved"
            id_map.append((pid, " ".join(q[0] for q in hit), k)); kinds.append(k); cnt[f"parts: {k}"] += 1
        if any(k != "same" for k in kinds) or len(o) != len(n):
            changed.append((wid, cut_o, cut_n, ",".join(sorted(set(kinds) - {"same"})) or "added_parts"))
            cnt["words: changed"] += 1
        else:
            cnt["words: same"] += 1
    return id_map, changed, cnt


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old", type=Path, required=True)
    ap.add_argument("--new", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    old, new = read(a.old), read(a.new)
    id_map, changed, cnt = compare(old, new)
    with open(a.out / "id_map.tsv", "w", encoding="utf-8") as f:
        f.write("old_id\tnew_ids\tchange\n")
        f.writelines("\t".join(r) + "\n" for r in id_map)
    with open(a.out / "changed_words.tsv", "w", encoding="utf-8") as f:
        f.write("word_id\told_cut\tnew_cut\tchange\n")
        f.writelines("\t".join(r) + "\n" for r in changed)
    nw = sum(v for k, v in cnt.items() if k.startswith("words: ") and k != "words: text_differs") + cnt["words: text_differs"]
    npart = sum(v for k, v in cnt.items() if k.startswith("parts: "))
    L = [f"# Part id churn: {a.old} -> {a.new}", "",
         f"Words compared: {nw:,}. Words whose cut changed: {cnt['words: changed']:,} ({cnt['words: changed'] / max(nw, 1):.1%}). "
         f"Old part ids whose meaning changed (anything but `same`): {npart - cnt['parts: same']:,} of {npart:,} "
         f"({(npart - cnt['parts: same']) / max(npart, 1):.1%}).", "", "| count | what |", "|---|---|"]
    L += [f"| {v:,} | {k} |" for k, v in sorted(cnt.items())]
    (a.out / "churn.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
