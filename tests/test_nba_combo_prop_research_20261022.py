import hashlib
import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from sportsedge import nba_combo_prop_research as C
from sportsedge import nba_prop_empirical as v1

ROOT = Path(__file__).resolve().parents[1]
V1_SHA_AT_BRANCH = (ROOT / "research/grok_nba_combo_props_20261022/V1_MODULE_SHA256").read_text().split()[0]


def store(n=15):
    recs = []
    d0 = date(2024, 10, 22)
    for i in range(n):
        for pid, pos, (p, r, a) in (("A", "G", (20 + i % 5, 4, 7)), ("B", "C", (12, 10 + i % 3, 2))):
            recs.append({"player_id": pid, "player_name": pid, "position": pos,
                         "game_date": (d0 + timedelta(days=2 * i)).isoformat(),
                         "game_id": f"g{i}", "minutes": 30, "points": p,
                         "rebounds": r, "assists": a})
    return v1.GameLogStore(recs)


def test_v1_untouched():
    assert v1.STATS == ("points", "rebounds", "assists", "pra")
    assert hashlib.sha256((ROOT / "sportsedge/nba_prop_empirical.py").read_bytes()).hexdigest() == V1_SHA_AT_BRANCH


def test_prices_with_partition_and_governance():
    out = C.price_combo(store(), "A", "pa", 27.5, date(2024, 12, 30))
    assert out["status"] == "PRICED"
    assert out["p_over"] + out["p_push"] + out["p_under"] == pytest.approx(1.0)
    assert out["play_allowed"] is False and out["registration"] == "UNREGISTERED"


def test_combo_equals_same_game_sum_pit():
    s = store()
    t = date(2024, 11, 15)
    pri = C._prior(s, "A", "pr", t)
    exp = [float(g["points"] + g["rebounds"]) for g in s._players["A"]["games"] if g["game_date"] < t]
    assert pri == exp and len(pri) > 0


@pytest.mark.parametrize("args,reason", [
    (("A", "pra2", 10.5, date(2024, 12, 30)), "NBA_COMBO_UNSUPPORTED"),
    (("A", "pr", float("nan"), date(2024, 12, 30)), v1.REFUSAL_LINE_INVALID),
    (("Z", "pr", 10.5, date(2024, 12, 30)), v1.REFUSAL_PLAYER_NOT_IN_STORE),
    (("A", "pr", 10.5, date(2024, 11, 1)), v1.REFUSAL_INSUFFICIENT_PRIORS),
])
def test_refusals(args, reason):
    out = C.price_combo(store(), *args)
    assert out["status"] == "REFUSED" and out["reason"] == reason
    assert "p_over" not in out


@pytest.mark.parametrize("line,detail", [(True, "LINE_BOOL"), (False, "LINE_BOOL"),
                                         (-0.5, "LINE_NEGATIVE"), (-30, "LINE_NEGATIVE"),
                                         ("-1.5", "LINE_NEGATIVE")])
def test_bool_and_negative_lines_refuse(line, detail):
    out = C.price_combo(store(), "A", "pa", line, date(2024, 12, 30))
    assert out["status"] == "REFUSED"
    assert out["reason"] == v1.REFUSAL_LINE_INVALID and out["detail"] == detail
    assert out["play_allowed"] is False


def test_sources_record_date_clustered_cis():
    import json
    s = json.loads((ROOT / "research/grok_nba_combo_props_20261022/SOURCES.json").read_text())
    ci = s["date_clustered_ci95"]
    assert ci["pr"] == [-1.924, -1.716]
    assert ci["pa"] == [-2.029, -1.825]
    assert ci["ra"] == [-0.789, -0.706]
