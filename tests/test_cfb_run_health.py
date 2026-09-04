from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sportsedge.sports.cfb.joint_model import (
    CFBJointScoreModel,
    CFB_FEATURE_CONTRACT,
    CFB_JOINT_MODEL_ID,
    _feature_names,
)
from sportsedge.sports.cfb.run_machine import run_cfb_machine
from sportsedge.sports.cfb.source import CFBGame, CFBQuote, CFBTeamMetrics


NOW = datetime(2026, 8, 26, 17, 0, tzinfo=timezone.utc)
START = datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc)


def _metric(team: str, bump: float = 0.0) -> CFBTeamMetrics:
    return CFBTeamMetrics(
        team=team,
        season=2025,
        through_week=99,
        sample_source="PRIOR_SEASON_FALLBACK",
        off_ppa_rush=0.11 + bump,
        off_ppa_dropback=0.19 + bump,
        def_ppa_rush_allowed=0.05 - bump,
        def_ppa_dropback_allowed=0.08 - bump,
        off_success_rate=0.46 + bump / 10,
        def_success_rate_allowed=0.42 - bump / 10,
        standard_down_ppa=0.13 + bump,
        passing_down_success_rate=0.39 + bump / 10,
        eckel_rate=0.31 + bump / 10,
        points_per_eckel=4.7 + bump,
        points_per_drive=2.3 + bump,
        net_field_position=1.8 + bump,
        explosive_rate=0.12 + bump / 10,
        feature_asof_ts=NOW.isoformat(),
    )


def _model() -> CFBJointScoreModel:
    names = _feature_names()
    n = len(names)
    return CFBJointScoreModel(
        CFB_JOINT_MODEL_ID,
        CFB_FEATURE_CONTRACT,
        names,
        (0.0,) * n,
        (1.0,) * n,
        (28.0,) + (0.0,) * n,
        (21.0,) + (0.0,) * n,
        ((0.0, 0.0), (1.0, -1.0), (-1.0, 1.0), (2.0, 0.0)),
        ((6, 0), (0, 6)),
        (2024, 2025),
        10.0,
    )


def test_all_blocked_decisions_cannot_report_ready():
    game = CFBGame(
        "1001",
        2026,
        1,
        START.isoformat(),
        "Alpha State",
        "Beta Tech",
        False,
        "Test Stadium",
        {"game_indoor": False, "wind_speed": 7.0, "temperature": 76.0},
    )
    metrics = {
        "Alpha State": _metric("Alpha State"),
        "Beta Tech": _metric("Beta Tech", 0.02),
    }
    ts = (NOW - timedelta(seconds=20)).isoformat()
    base = dict(
        game_id="1001",
        market="MONEYLINE",
        line=0,
        period="FG",
        entity_id="1001",
        book_key="draftkings",
        sportsbook="DraftKings",
        retrieved_at=ts,
        is_alternate=False,
    )
    quotes = [
        CFBQuote(side="HOME", american_odds=-150, offer_id="mlh", **base),
        CFBQuote(side="AWAY", american_odds=130, offer_id="mla", **base),
    ]
    teams = [
        {"school": "Alpha State", "abbreviation": "ASU", "mascot": "Owls", "alternateNames": []},
        {"school": "Beta Tech", "abbreviation": "BT", "mascot": "Bears", "alternateNames": []},
    ]

    report = run_cfb_machine(
        mode="MANUAL",
        season=2026,
        week=1,
        model=_model(),
        now=NOW,
        games=[game],
        metrics=metrics,
        quotes=quotes,
        fbs_team_rows=teams,
        n_paths=20,
        root_seed=44,
    )

    assert report.results
    assert all(row.engine_status == "PRICED" for row in report.results)
    assert all(row.bet_status == "BLOCKED" for row in report.results)
    assert all(row.reason == "CFB_PROMOTION_EVIDENCE_REQUIRED" for row in report.results)
    assert report.run_status == "BLOCKED"
    assert report.summary["blocked"] == len(report.results)
