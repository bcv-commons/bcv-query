"""resources/lxx_bridge_tiers: lxx_bridge.tsv stays the top 4 of the macula tier, and both tier files keep their shape."""
import csv
import itertools
from pathlib import Path

RES = Path(__file__).resolve().parents[2] / "resources"
HEADER = ["hebrew_strong", "greek_strong", "tier", "count", "score"]


def rows(name):
    with open(RES / name, encoding="utf-8") as f:
        return list(csv.reader(f, delimiter="\t"))


def test_lxx_bridge_is_top4_of_macula():
    old = [tuple(r) for r in rows("lxx_bridge.tsv")[1:]]
    tier = rows("lxx_bridge_tiers/macula.tsv")[1:]
    top = [(h, g, c) for _, grp in itertools.groupby(tier, key=lambda r: r[0]) for h, g, _, c, _ in list(grp)[:4]]
    assert old == top


def test_tier_files():
    for name, tier in (("macula", "macula"), ("glaux", "glaux")):
        data = rows(f"lxx_bridge_tiers/{name}.tsv")
        assert data[0] == HEADER
        for h, g, t, c, s in data[1:]:
            assert h[0] == "H" and g[0] == "G" and t == tier and int(c) >= 3 and 0 < float(s) <= 1
        if tier == "glaux":
            assert min(float(r[4]) for r in data[1:]) >= 0.3
