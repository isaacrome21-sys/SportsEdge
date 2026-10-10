"""2027 prep (#1482): frozen 2026 few-starts prior pools emitted in #1977 (Outs/K) and #1978 (BB/H/ER).

Same frozen league_short procedure that passed #1495 / #1943. prior_for uses season Y-1,
so these artifacts only price 2027 games; 2026 postseason games keep using the 2025 pools.
"""
from __future__ import annotations

from datetime import date

from sportsedge import mlb_pitcher_prior as P


def _clear():
    P._load.cache_clear()
    P._load_ext.cache_clear()


def test_committed_2026_artifacts_are_valid_and_only_used_for_2027_games():
    _clear()
    for market in ("PITCHER_OUTS", "PITCHER_K", "PITCHER_BB", "PITCHER_HITS_ALLOWED", "PITCHER_ER"):
        prior = P.prior_for(date(2027, 4, 1), market=market)
        assert prior is not None and prior["season"] == 2026, market
        assert sum(prior["counts"][P.MARKET_STAT[market]].values()) == 502
        assert P.prior_for(date(2026, 10, 10), market=market)["season"] == 2025
    ext = P.prior_for(date(2027, 4, 1), market="PITCHER_BB")
    base = P.prior_for(date(2027, 4, 1), market="PITCHER_K")
    assert {s: ext["counts"][s] for s in ("outs", "strikeouts")} == base["counts"]
    _clear()
