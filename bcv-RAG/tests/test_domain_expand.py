"""Lock-in test for query.domain_expand (S2 semantic-domain expansion).

Guards the cross-language co-domain expansion behavior — the value of the
domain+bridge work — and its conservative bounds. (The Titus+Ruth eval corpus
can't measure the *retrieval* benefit: it's small/English, so the added Greek/
Hebrew co-domain Strong's tags don't match any chunk. The benefit shows on a
larger / original-language-tagged corpus; here we lock in the expansion logic.)

Run:  PYTHONPATH=. python tests/test_domain_expand.py
"""
from query.domain_expand import expand_domains

# query Strong's → a co-domain lexeme that MUST appear in its expansion.
# Each pair crosses languages (the shared SDBG axis spanning Greek + LXX-bridged Hebrew).
EXPECT = {
    "G0026": "H0157",   # agapē (love)      → ahav (Hebrew "love")
    "G1515": "H7965",   # eirēnē (peace)    → shalom
    "G0040": "H6944",   # hagios (holy)     → qodesh (holiness)
    "H2617": "G1656",   # chesed            → eleos (mercy)
    "H0157": "G0025",   # ahav (love)       → agapaō (Greek "love")
}


def main() -> None:
    fails = []
    for src, want in EXPECT.items():
        got = expand_domains([f"strongs:{src}"])
        ok = f"strongs:{want}" in got
        print(f"  {src} -> {got}  {'OK' if ok else 'MISSING ' + want}")
        if not ok:
            fails.append((src, want, got))

    # conservative bounds: never over-expand, even for a broad title like kyrios.
    for src in ("G2962", "G3056", "G0026"):
        got = expand_domains([f"strongs:{src}"])
        assert len(got) <= 4, f"{src} over-expanded ({len(got)}): {got}"

    # the kill-switch must zero it out.
    import os
    os.environ["DOMAIN_EXPAND"] = "0"
    import importlib
    import query.domain_expand as D
    importlib.reload(D)
    assert D.expand_domains(["strongs:G0026"]) == [], "DOMAIN_EXPAND=0 should disable"
    os.environ.pop("DOMAIN_EXPAND")

    if fails:
        raise SystemExit(f"FAIL: {fails}")
    print("PASS")


if __name__ == "__main__":
    main()
