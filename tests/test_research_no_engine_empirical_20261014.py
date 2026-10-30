"""Fail-closed proofs for experimental NO_ENGINE prototypes."""
import pytest

from sportsedge.research_no_engine_empirical import (
    EvidenceUnavailable, JOINT_SUM, SINGLE, research_probability,
)

TARGET = "2026-10-14T18:00:00Z"


def samples(n=20):
    return [
        {"fixture_id": f"game-{i}", "game_end_at": "2026-10-01T01:00:00Z",
         "observed_at": "2026-10-01T02:00:00Z",
         "hits": 1, "runs": 1, "stolen_bases": 0, "doubles": 1,
         "triples": 0, "home_runs": 0, "rbis": 1, "walks": 1,
         "touchdowns": 2, "longest_reception": 20}
        for i in range(n)
    ]


def test_joint_empirical_preserves_complete_game_rows():
    x = research_probability(sport="MLB", market="HITS_RUNS_STOLEN_BASES",
                             observations=samples(), target_time=TARGET, line=1.5)
    assert x["research_frequency_smoothed"] == pytest.approx(21 / 22)
    assert x["eligibility"] is False and x["play"] is False
    assert x["status"] == "RESEARCH_ONLY_UNVALIDATED"


def test_two_plus_td_uses_at_least_two_not_anytime_td():
    x = research_probability(sport="NFL", market="two_plus_td",
                             observations=samples(), target_time=TARGET)
    assert x["successes"] == 20
    with pytest.raises(EvidenceUnavailable, match="TWO_PLUS_TD_LINE"):
        research_probability(sport="NFL", market="two_plus_td",
                             observations=samples(), target_time=TARGET, line=0.5)


@pytest.mark.parametrize("modify,reason", [
    (lambda x: x[0].update(hits=None), "STAT_MISSING"),
    (lambda x: x[0].update(hits=True), "STAT_MISSING"),
    (lambda x: x[0].update(hits=-1), "STAT_MISSING"),
    (lambda x: x[0].update(observed_at=TARGET), "NOT_STRICTLY_PRIOR"),
    (lambda x: x[0].update(game_end_at=TARGET), "NOT_STRICTLY_PRIOR"),
    (lambda x: x[0].update(fixture_id=x[1]["fixture_id"]), "FIXTURE_ID"),
])
def test_refusals(modify, reason):
    rows = samples()
    modify(rows)
    with pytest.raises(EvidenceUnavailable, match=reason):
        research_probability(sport="MLB", market="HITS_RUNS_STOLEN_BASES",
                             observations=rows, target_time=TARGET, line=1.5)


def test_insufficient_history_and_unknown_market_fail():
    with pytest.raises(EvidenceUnavailable, match="INSUFFICIENT"):
        research_probability(sport="MLB", market="RUNS_RBIS",
                             observations=samples(19), target_time=TARGET, line=1.5)
    with pytest.raises(EvidenceUnavailable, match="MARKET_NOT_IMPLEMENTED"):
        research_probability(sport="NFL", market="race_to_n_points",
                             observations=samples(), target_time=TARGET, line=1.5)


def test_no_market_can_grant_authority():
    for sport, market_map in SINGLE.items():
        for market, field in market_map.items():
            rows = samples()
            for row in rows:
                row[field] = 2
            x = research_probability(sport=sport, market=market,
                                     observations=rows, target_time=TARGET,
                                     line=None if market == "two_plus_td" else 1.5)
            assert not x["pricing_authority"] and not x["eligibility"]
    for sport, market_map in JOINT_SUM.items():
        for market, fields in market_map.items():
            rows = samples()
            for row in rows:
                for field in fields:
                    row[field] = 1
            x = research_probability(sport=sport, market=market,
                                     observations=rows, target_time=TARGET, line=1.5)
            assert not x["pricing_authority"] and not x["eligibility"]
