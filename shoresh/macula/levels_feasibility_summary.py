"""Stage 40: the tables of FEASIBILITY.md sections 3, 4, 7, 8, printed from switches-counts.json (no new counting).

  shoresh/.venv/bin/python -I shoresh/macula/levels_feasibility_summary.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from levels_feasibility_common import OUT, PARTS  # noqa: E402

KIND = {"כָּלוּל בַּפֹּעַל": "in_verb", "נֶאֱמַר בְּמָקוֹם אַחֵר": "elsewhere", "לֹא נֶאֱמַר": "unsaid",
        "בַּעַל שֶׁלֹּא נִזְכַּר": "possessor"}


def merged(d, scopes=None):
    c = Counter()
    for sc, v in d.items():
        if scopes is None or sc in scopes:
            c.update(v)
    return c


def en(k):
    for h, e in KIND.items():
        k = k.replace(h, e)
    return k


def main():
    d = json.load(open(OUT / "switches-counts.json", encoding="utf-8"))
    print("## R (whole part; pilot = GEN+RUT+JON for hbo)")
    print("| part | heads pron/suffix/zero | 1st/2nd person | 3rd with referent | ambiguous | ambiguous with name |"
          " unambiguous | no referent |")
    print("|---|---|---|---|---|---|---|---|")
    for p in PARTS:
        for scopes, lab in ((None, p), ({"pilot"}, p + " pilot")):
            c = merged(d[p]["R"], scopes)
            if not c:
                continue
            heads = c["heads:pronoun"] + c["heads:suffix"] + c["heads:verb_zero"]
            nr = sum(v for k, v in c.items() if k.startswith("no_referent"))
            print(f"| {lab} | {heads} | {c['person_1_2']} | {c['referent']} | {c['ambiguous']} | "
                  f"{c['ambiguous_named']} | {c['unambiguous']} | {nr} |")
        c = merged(d[p]["R"])
        print("   no referent by state:", {k.split(":", 1)[1]: v for k, v in c.items() if k.startswith("no_referent")})
    print("\n## A and the precision rule")
    for p in PARTS:
        for scopes, lab in ((None, p), ({"pilot"}, p + " pilot")):
            c = merged(d[p]["A"], scopes)
            if not c:
                continue
            rows = {en(k[5:]): v for k, v in c.items() if k.startswith("rows:")}
            ver = {k[8:]: v for k, v in c.items() if k.startswith("verdict:") and k.count(":") == 1}
            who = {en(k): v for k, v in c.items() if ":who" in k or ":no_who" in k}
            print(f"- {lab}: rows {sum(rows.values())} {rows}\n    verdict {ver}\n    who {who}")
            per_kind = {en(k[8:]): v for k, v in c.items() if k.startswith("verdict:") and k.count(":") == 2}
            print("    by kind", per_kind)
    print("\n## E")
    for p in PARTS:
        for scopes, lab in ((None, p), ({"pilot"}, p + " pilot")):
            c = merged(d[p]["E"], scopes)
            if c:
                print(f"- {lab}: {dict(sorted(c.items()))}")
    print("\n## V")
    for cut, v in d["hbo"]["V"].items():
        for p in PARTS:
            for scopes, lab in ((None, p), ({"pilot"}, p + " pilot")):
                c = merged(d[p]["V"][cut], scopes)
                if c:
                    ni = sum(x for k, x in c.items() if k.startswith("no_input"))
                    print(f"| {cut} | {lab} | {c['content_tokens']} | {c['below_cut']} | {c['input:group_head']} | "
                          f"{c['input:explanation_all_above_cut']} | {c['input:either']} | {ni} | "
                          f"{c.get('no_input:state:nt_only', 0)} |")
    print("\n## pilot lines", json.dumps(d["pilot_lines"]), json.dumps(d["pilot_chars_outside"]))


if __name__ == "__main__":
    main()
