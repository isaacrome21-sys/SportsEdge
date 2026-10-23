from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from sportsedge import nfl_longest_fg_empirical as eng
from sportsedge.canonical_coverage import resolve_market

T0 = datetime(2025, 9, 7, 17, 0, tzinfo=timezone.utc)


def games(n=8, kid="K1", atts=((33, True), (47, True), (52, False))):
    return [{"game_id": f"G{i}", "kicker_id": kid,
             "kickoff": T0 + timedelta(days=7 * i),
             "fg_attempts": list(atts), "pat_attempts": 3, "pat_makes": 3}
            for i in range(n)]


KO = T0 + timedelta(days=7 * 20)


def test_prices_and_mass_partition():
    out = eng.price_longest_fg(games(), kicker_id="K1", kickoff=KO, line=44.5)
    total = (out["p_made_longer_than_line"]
             + out["p_made_fg_not_longer_than_line"] + out["p_no_made_fg"])
    assert total == pytest.approx(1.0, abs=1e-9)
    assert 0 < out["p_made_longer_than_line"] < 1
    assert out["governance"] == "RESEARCH_UNSCREENED"
    assert out["eligible"] is False and out["validation_status"] == "NOT_VALIDATED"
    assert "fair" not in json.dumps(out) and "ev" not in out


def test_monotone_in_line():
    ps = [eng.price_longest_fg(games(), kicker_id="K1", kickoff=KO,
                               line=L)["p_made_longer_than_line"]
          for L in (30.5, 40.5, 45.5, 50.5, 55.5)]
    assert all(a >= b for a, b in zip(ps, ps[1:]))


def test_longer_kicker_prices_higher():
    short = eng.price_longest_fg(games(atts=((25, True), (31, True))),
                                 kicker_id="K1", kickoff=KO, line=45.5)
    long_ = eng.price_longest_fg(games(atts=((49, True), (54, True))),
                                 kicker_id="K1", kickoff=KO, line=45.5)
    assert long_["p_made_longer_than_line"] > short["p_made_longer_than_line"]


def test_strict_point_in_time():
    g = games(8)
    late = {"game_id": "LATE", "kicker_id": "K1", "kickoff": KO,
            "fg_attempts": [(60, True)] * 5, "pat_attempts": 0, "pat_makes": 0}
    a = eng.price_longest_fg(g, kicker_id="K1", kickoff=KO, line=50.5)
    b = eng.price_longest_fg(g + [late], kicker_id="K1", kickoff=KO, line=50.5)
    assert a == b


@pytest.mark.parametrize("line", [44.0, float("nan"), 10.5, 80.5, "x"])
def test_bad_lines_refuse(line):
    with pytest.raises(eng.NflLongestFgError):
        eng.price_longest_fg(games(), kicker_id="K1", kickoff=KO, line=line)


def test_insufficient_history_refuses():
    with pytest.raises(eng.NflLongestFgError, match="UPSTREAM"):
        eng.price_longest_fg(games(3), kicker_id="K1", kickoff=KO, line=44.5)


def test_wrong_kicker_refuses():
    with pytest.raises(eng.NflLongestFgError):
        eng.price_longest_fg(games(kid="K2"), kicker_id="K1", kickoff=KO,
                             line=44.5)


def test_no_fg_attempts_refuses():
    with pytest.raises(eng.NflLongestFgError):
        eng.price_longest_fg(games(atts=()), kicker_id="K1", kickoff=KO,
                             line=44.5)


def test_canonical_path_still_blocked_and_registry_state():
    assert resolve_market("NFL", "longest_fg_made")["state"] == "BLOCKED"
    reg = json.loads((Path(__file__).resolve().parents[1] / "config"
                      / "grok_research_unscreened_families_v1.json").read_text())
    for fam in reg["families"]:
        assert fam["state"] == "RESEARCH_UNSCREENED"
        assert fam["eligible"] is False and fam["play_allowed"] is False
        assert fam["validation_status"] == "NOT_VALIDATED"
