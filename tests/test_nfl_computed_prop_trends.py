from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from sportsedge.sports.nfl.computed_prop_trends import (
    ComputedPropTrendError,
    ComputedPropTrendSnapshot,
    SourceProof,
    build_computed_prop_trends,
    fetch_nflverse_weekly_player_stats,
    match_computed_prop_trend,
    research_sidecar,
)
from sportsedge.sports.nfl.prop_context_contract import validate_context_payload


NOW = datetime(2026, 1, 10, 18, 0, tzinfo=timezone.utc)
PLAYER_ID = "00-0030506"
SOURCE_URI = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2025.csv"
SCHEDULE_URI = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
PLAYER_SHA = "a" * 64
SCHEDULE_SHA = "b" * 64


def _schedule(game_id: str, kickoff: datetime, opponent: str, *, team: str = "SF"):
    return {
        "game_id": game_id,
        "start_time": kickoff.isoformat(),
        "home_team": team,
        "away_team": opponent,
        "season": "2025",
        "week": game_id.split("-")[-1],
    }


def _row(game_id: str, opponent: str, receptions: float, *, team: str = "SF", **updates):
    row = {
        "player_id": PLAYER_ID,
        "player_name": "George Kittle",
        "season": "2025",
        "week": game_id.split("-")[-1],
        "season_type": "REG",
        "game_id": game_id,
        "team": team,
        "opponent_team": opponent,
        "receptions": str(receptions),
        "receiving_yards": str(receptions * 12),
        "targets": str(receptions + 2),
        "carries": "0",
        "rushing_yards": "0",
        "passing_yards": "0",
        "attempts": "0",
        "completions": "0",
        "passing_tds": "0",
        "passing_interceptions": "0",
    }
    row.update(updates)
    return row


def _history():
    opponents = ["LAR", "SEA", "ARI", "DAL", "GB", "MIN", "CHI", "DET", "TB", "ATL", "CAR"]
    # 10/11 over 3.5 overall, 9/10 over in the latest ten, 4/5 in latest five.
    receptions = [4, 4, 4, 4, 4, 4, 3, 4, 4, 4, 4]
    rows = []
    schedule = []
    start = datetime(2025, 9, 1, 17, 0, tzinfo=timezone.utc)
    for index, (opponent, value) in enumerate(zip(opponents, receptions), start=1):
        game_id = f"2025-{index}"
        kickoff = start + timedelta(days=7 * (index - 1))
        rows.append(_row(game_id, opponent, value))
        schedule.append(_schedule(game_id, kickoff, opponent))
    return rows, schedule


def _snapshot(*, rows=None, schedule=None, line=3.5, side="OVER", opponent="LAR", as_of=NOW):
    if rows is None or schedule is None:
        default_rows, default_schedule = _history()
        rows = default_rows if rows is None else rows
        schedule = default_schedule if schedule is None else schedule
    return build_computed_prop_trends(
        player_rows=rows,
        player_sources=[SourceProof(2025, SOURCE_URI, PLAYER_SHA)],
        schedule_rows=schedule,
        schedule_source_uri=SCHEDULE_URI,
        schedule_source_sha256=SCHEDULE_SHA,
        as_of=as_of,
        player_id=PLAYER_ID,
        current_season=2025,
        opponent_team_id=opponent,
        market_id="RECEPTIONS",
        side=side,
        line=line,
    )


def _windows(snapshot):
    return {window.label: window for window in snapshot.windows}


def test_computes_kittle_style_trends_from_raw_games_not_percentages():
    snapshot = _snapshot()
    windows = _windows(snapshot)
    assert (windows["L10"].wins, windows["L10"].attempts) == (9, 10)
    assert windows["L10"].hit_rate_pct == pytest.approx(90.0)
    assert (windows["L20"].wins, windows["L20"].attempts) == (10, 11)
    assert windows["L20"].hit_rate_pct == pytest.approx(1000 / 11)
    assert (windows["L5"].wins, windows["L5"].attempts) == (4, 5)
    assert (windows["H2H"].wins, windows["H2H"].attempts) == (1, 1)


def test_precomputed_hit_rate_fields_are_rejected():
    rows, schedule = _history()
    rows[0]["reported_pct"] = 100
    with pytest.raises(ComputedPropTrendError, match="PRECOMPUTED_TREND_FIELDS_FORBIDDEN"):
        _snapshot(rows=rows, schedule=schedule)


def test_snapshot_is_exact_line_bound_and_cannot_be_reused_at_another_line():
    snapshot = _snapshot()
    exact = match_computed_prop_trend(
        snapshot,
        player_id=PLAYER_ID,
        opponent_team_id="LAR",
        market_id="RECEPTIONS",
        side="OVER",
        line=3.5,
    )
    assert exact.state == "EXACT"
    mismatch = match_computed_prop_trend(
        snapshot,
        player_id=PLAYER_ID,
        opponent_team_id="LAR",
        market_id="RECEPTIONS",
        side="OVER",
        line=4.5,
    )
    assert mismatch.state == "LINE_MISMATCH"
    assert mismatch.reasons == ("PROP_LINE_MISMATCH",)
    assert mismatch.line_delta == pytest.approx(-1.0)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("player_id", "00-other", "PLAYER_ID_MISMATCH"),
        ("opponent_team_id", "SEA", "OPPONENT_TEAM_ID_MISMATCH"),
        ("market_id", "RECEIVING_YARDS", "MARKET_ID_MISMATCH"),
        ("side", "UNDER", "SIDE_MISMATCH"),
    ],
)
def test_snapshot_identity_mismatches_are_explicit(field, value, reason):
    snapshot = _snapshot()
    kwargs = {
        "player_id": PLAYER_ID,
        "opponent_team_id": "LAR",
        "market_id": "RECEPTIONS",
        "side": "OVER",
        "line": 3.5,
    }
    kwargs[field] = value
    result = match_computed_prop_trend(snapshot, **kwargs)
    assert result.state == "IDENTITY_MISMATCH"
    assert result.reasons == (reason,)


def test_future_row_is_excluded_but_completed_same_week_row_is_included():
    past_id = "2025-1"
    future_id = "2025-2"
    rows = [
        _row(past_id, "SEA", 5),
        _row(future_id, "ARI", 5),
    ]
    schedule = [
        _schedule(past_id, NOW - timedelta(minutes=1), "SEA"),
        _schedule(future_id, NOW + timedelta(minutes=1), "ARI"),
    ]
    snapshot = _snapshot(rows=rows, schedule=schedule)
    assert [game.game_id for game in snapshot.games] == [past_id]
    assert _windows(snapshot)["L5"].attempts == 1


def test_duplicate_player_game_is_rejected():
    rows, schedule = _history()
    rows.append(dict(rows[0]))
    with pytest.raises(ComputedPropTrendError, match="DUPLICATE_PLAYER_GAME"):
        _snapshot(rows=rows, schedule=schedule)


def test_player_team_and_opponent_must_bind_to_schedule():
    rows, schedule = _history()
    rows[0]["opponent_team"] = "SEA"
    with pytest.raises(ComputedPropTrendError, match="PLAYER_SCHEDULE_TEAM_MISMATCH"):
        _snapshot(rows=rows, schedule=schedule)


def test_missing_game_id_is_not_inferred_from_week_or_team():
    rows, schedule = _history()
    rows[0]["game_id"] = ""
    with pytest.raises(ComputedPropTrendError, match="MISSING_IDENTITY:game_id"):
        _snapshot(rows=rows, schedule=schedule)


def test_missing_stat_is_explicit_not_zero_filled():
    rows, schedule = _history()
    rows[0]["receptions"] = ""
    with pytest.raises(ComputedPropTrendError, match="RAW_STAT_MISSING:RECEPTIONS"):
        _snapshot(rows=rows, schedule=schedule)


def test_source_proof_is_required_for_every_used_season():
    rows, schedule = _history()
    with pytest.raises(ComputedPropTrendError, match="PLAYER_SOURCE_PROOF_MISSING:2025"):
        build_computed_prop_trends(
            player_rows=rows,
            player_sources=[],
            schedule_rows=schedule,
            schedule_source_uri=SCHEDULE_URI,
            schedule_source_sha256=SCHEDULE_SHA,
            as_of=NOW,
            player_id=PLAYER_ID,
            current_season=2025,
            opponent_team_id="LAR",
            market_id="RECEPTIONS",
            side="OVER",
            line=3.5,
        )


def test_integer_line_pushes_are_not_counted_as_losses():
    rows = [
        _row("2025-1", "SEA", 4),
        _row("2025-2", "ARI", 5),
        _row("2025-3", "DAL", 3),
    ]
    schedule = [
        _schedule("2025-1", NOW - timedelta(days=21), "SEA"),
        _schedule("2025-2", NOW - timedelta(days=14), "ARI"),
        _schedule("2025-3", NOW - timedelta(days=7), "DAL"),
    ]
    snapshot = _snapshot(rows=rows, schedule=schedule, line=4.0)
    l5 = _windows(snapshot)["L5"]
    assert (l5.wins, l5.losses, l5.pushes, l5.attempts, l5.decisions) == (1, 1, 1, 3, 2)
    assert l5.hit_rate_pct == pytest.approx(50.0)


def test_under_settlement_is_directionally_correct():
    rows = [_row("2025-1", "SEA", 3), _row("2025-2", "ARI", 5)]
    schedule = [
        _schedule("2025-1", NOW - timedelta(days=14), "SEA"),
        _schedule("2025-2", NOW - timedelta(days=7), "ARI"),
    ]
    snapshot = _snapshot(rows=rows, schedule=schedule, side="UNDER", line=3.5)
    l5 = _windows(snapshot)["L5"]
    assert (l5.wins, l5.losses) == (1, 1)


def test_research_sidecar_is_structurally_non_actionable():
    snapshot = _snapshot()
    sidecar = research_sidecar(snapshot)
    assert snapshot.model_p_eligible is False
    assert snapshot.truth_gate_eligible is False
    assert snapshot.decision_effect == "NONE"
    assert snapshot.historical_hit_rate_is_probability is False
    assert sidecar["model_p_eligible"] is False
    assert sidecar["truth_gate_eligible"] is False
    assert sidecar["decision_effect"] == "NONE"
    assert sidecar["historical_hit_rate_is_probability"] is False


def test_governance_flags_cannot_be_promoted_at_construction():
    snapshot = _snapshot()
    payload = {
        name: getattr(snapshot, name)
        for name in (
            "contract", "as_of", "player_id", "opponent_team_id", "market_id", "side", "line",
            "stat_field", "windows", "games", "player_sources", "schedule_source_uri",
            "schedule_source_sha256", "content_hash",
        )
    }
    with pytest.raises(TypeError):
        ComputedPropTrendSnapshot(**payload, model_p_eligible=True)


def test_nfl_hybrid_context_rejects_computed_trends_as_model_input():
    with pytest.raises(ValueError, match="computed_prop_trends"):
        validate_context_payload({"computed_prop_trends": research_sidecar(_snapshot())})


def test_snapshot_content_hash_is_deterministic():
    assert _snapshot().content_hash == _snapshot().content_hash


class _Response:
    def __init__(self, raw: bytes):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.raw


def test_nflverse_fetcher_hashes_exact_bytes_and_uses_weekly_game_rows():
    raw = (
        "player_id,season,week,season_type,game_id,team,opponent_team,receptions\n"
        "00-1,2025,1,REG,2025_01_SF_SEA,SF,SEA,4\n"
    ).encode()
    seen = []

    def opener(request, timeout):
        seen.append((request.full_url, timeout))
        return _Response(raw)

    acquired = fetch_nflverse_weekly_player_stats(seasons=[2025], opener=opener)
    assert len(acquired.rows) == 1
    assert acquired.rows[0]["game_id"] == "2025_01_SF_SEA"
    assert acquired.sources[0].source_sha256 == sha256(raw).hexdigest()
    assert acquired.sources[0].source_uri.endswith("stats_player_week_2025.csv")
    assert seen[0][1] == 25


def test_nflverse_fetcher_fails_closed_on_schema_without_game_identity():
    raw = b"player_id,season,week,season_type,team,opponent_team,receptions\n00-1,2025,1,REG,SF,SEA,4\n"

    def opener(request, timeout):
        return _Response(raw)

    with pytest.raises(ComputedPropTrendError, match="NFLVERSE_PLAYER_STATS_SCHEMA_UNSUPPORTED"):
        fetch_nflverse_weekly_player_stats(seasons=[2025], opener=opener)

@pytest.mark.parametrize('side', ['OVER', 'UNDER'])
def test_all_push_windows_have_no_hit_rate(side):
    rows, schedule = _history()
    for row in rows:
        row['receptions'] = '4'
    snapshot = _snapshot(rows=rows, schedule=schedule, line=4.0, side=side)
    for window in snapshot.windows:
        assert window.attempts == window.pushes
        assert window.decisions == window.wins == window.losses == 0
        assert window.hit_rate_pct is None

@pytest.mark.parametrize('side', ['OVER', 'UNDER'])
def test_integer_and_half_line_have_distinct_denominators(side):
    half = _windows(_snapshot(line=3.5, side=side))['L10']
    whole = _windows(_snapshot(line=4.0, side=side))['L10']
    assert (half.attempts, half.decisions, half.pushes) == (10, 10, 0)
    assert (whole.attempts, whole.decisions, whole.pushes) == (10, 1, 9)
    assert half.hit_rate_pct == (90.0 if side == 'OVER' else 10.0)
    assert whole.hit_rate_pct == (0.0 if side == 'OVER' else 100.0)
    assert whole.wins + whole.losses + whole.pushes == whole.attempts
