"""Screen v3: naive largest-lead pmf and its out-of-support fallback use earlier seasons only."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "research" / "grok_nfl_situational_screen_20261023"


def _load():
    sys.path.insert(0, str(ROOT / "sportsedge"))
    spec = importlib.util.spec_from_file_location("sit_screen_v3_lib", DIR / "screen_v3_lib.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def _rows():
    rows = []
    for s, leads in ((2018, [3, 7, 7]), (2019, [10, 14]), (2020, [99, 99, 99, 99, 99, 99])):
        for i, v in enumerate(leads):
            rows.append({"season": s, "largest_lead": v})
    return rows


def test_naive_lead_uses_only_earlier_seasons():
    lib = _load()
    pmf, fallback = lib.naive_largest_lead(_rows(), 2019)
    assert max(pmf) == 7 + 10
    assert abs(sum(pmf.values()) - 1) < 1e-12
    # later seasons (2019, 2020) must not change the 2019 pmf or fallback
    pmf2, fb2 = lib.naive_largest_lead([r for r in _rows() if r["season"] < 2019], 2019)
    assert (pmf, fallback) == (pmf2, fb2)


def test_fallback_depends_only_on_earlier_pool_size():
    lib = _load()
    _, fb = lib.naive_largest_lead(_rows(), 2019)
    n, mx = 3, 17
    assert fb == 0.5 / (n + 0.5 * (mx + 1))
