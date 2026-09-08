from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.market_context.myspariedge_props import (
    MySpariEdgeContextError,
    MySpariEdgePropObservation,
    TrendWindow,
    compare_to_model,
    find_prop_context,
    parse_myspariedge_records,
    research_sidecar,
)


NOW = datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc)
SOURCE_SHA = "a" * 64
SOURCE_URL = "https://myspariedge.com/nfl/player-prop-trends"


def _kittle_record(**updates):
    row = {
        "observed_at": NOW - timedelta(minutes=5),
        "player_id": "nfl:player:george-kittle",
        "player_name": "George Kittle",
        "opponent_team_id": "nfl:team:lar",
        "opponent_team_name": "Los Angeles Rams",
        "market_id": "RECEPTIONS",
        "side": "OVER",
        "line": 3.5,
        "trends": [
            {"label": "L5", "hits": 5, "attempts": 5, "reported_pct": 100},
            {"label": "L10", "hits": 9, "attempts": 10, "reported_pct": 90},
            {"label": "L20", "hits": 10, "attempts": 11, "reported_pct": 91},
            {"label": "SEASON", "hits": 10, "attempts": 11, "reported_pct": 91},
            {"label": "H2H", "hits": 1, "attempts": 1, "reported_pct": 100},
        ],
    }
    row.update(updates)
    return row


def _snapshot(record=None, *, captured_at=NOW):
    return parse_myspariedge_records(
        [_kittle_record() if record is None else record],
        captured_at=captured_at,
        source_url=SOURCE_URL,
        source_sha256=SOURCE_SHA,
    )


def _match(snapshot, **updates):
    kwargs = {
        "player_id": "nfl:player:george-kittle",
        "opponent_team_id": "nfl:team:lar",
        "market_id": "RECEPTIONS",
        "side": "OVER",
        "line": 3.5,
        "as_of": NOW,
        "max_age": timedelta(hours=1),
    }
    kwargs.update(updates)
    return find_prop_context(snapshot, **kwargs)


def test_accepts_kittle_style_counts_and_exposes_sample_sizes():
    snapshot = _snapshot()
    assert snapshot.state == "OK"
    obs = snapshot.observations[0]
    by_window = {trend.label: trend for trend in obs.trends}
    assert (by_window["L10"].hits, by_window["L10"].attempts) == (9, 10)
    assert (by_window["L20"].hits, by_window["L20"].attempts) == (10, 11)
    assert by_window["L20"].hit_rate_pct == pytest.approx(90.9090909)
    assert obs.model_p_eligible is False
    assert obs.truth_gate_eligible is False
    assert obs.decision_effect == "NONE"


def test_percent_only_trend_is_rejected():
    row = _kittle_record(trends=[{"label": "L10", "reported_pct": 90}])
    with pytest.raises(MySpariEdgeContextError, match="TREND_SAMPLE_COUNTS_REQUIRED:L10"):
        _snapshot(row)


def test_reported_percent_must_agree_with_counts():
    row = _kittle_record(
        trends=[{"label": "L10", "hits": 9, "attempts": 10, "reported_pct": 80}]
    )
    with pytest.raises(MySpariEdgeContextError, match="PCT_SAMPLE_CONTRADICTION:L10"):
        _snapshot(row)


def test_duplicate_windows_are_rejected():
    row = _kittle_record(
        trends=[
            {"label": "L10", "hits": 9, "attempts": 10},
            {"label": "L10", "hits": 8, "attempts": 10},
        ]
    )
    with pytest.raises(MySpariEdgeContextError, match="DUPLICATE_TREND_WINDOW"):
        _snapshot(row)


def test_exact_identity_and_line_match():
    result = _match(_snapshot())
    assert result.state == "EXACT"
    assert result.reasons == ()
    assert result.line_delta == 0.0


def test_line_mismatch_is_flagged_not_silently_reused():
    result = _match(_snapshot(), line=4.5)
    assert result.state == "LINE_MISMATCH"
    assert result.reasons == ("PROP_LINE_MISMATCH",)
    assert result.line_delta == pytest.approx(-1.0)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("player_id", "nfl:player:someone-else", "PLAYER_ID_MISMATCH"),
        ("opponent_team_id", "nfl:team:sea", "OPPONENT_TEAM_ID_MISMATCH"),
        ("market_id", "RECEIVING_YARDS", "MARKET_ID_MISMATCH"),
        ("side", "UNDER", "SIDE_MISMATCH"),
    ],
)
def test_identity_mismatches_are_explicit(field, value, reason):
    result = _match(_snapshot(), **{field: value})
    assert result.state == "IDENTITY_MISMATCH"
    assert result.reasons == (reason,)


def test_stale_context_is_not_exact():
    row = _kittle_record(observed_at=NOW - timedelta(hours=3))
    result = _match(_snapshot(row), max_age=timedelta(minutes=30))
    assert result.state == "STALE"
    assert result.reasons == ("SOURCE_STALE",)


def test_future_observation_is_not_pit_context():
    future_capture = NOW + timedelta(minutes=30)
    row = _kittle_record(observed_at=NOW + timedelta(minutes=10))
    snapshot = _snapshot(row, captured_at=future_capture)
    result = _match(snapshot, as_of=NOW)
    assert result.state == "NO_MATCH"
    assert result.reasons == ("NO_PIT_CONTEXT",)


def test_context_flags_cannot_be_promoted_at_construction():
    with pytest.raises(TypeError):
        MySpariEdgePropObservation(
            observed_at=NOW,
            captured_at=NOW,
            source_url=SOURCE_URL,
            source_sha256=SOURCE_SHA,
            player_id="p1",
            player_name="Player",
            opponent_team_id="t2",
            market_id="RECEPTIONS",
            side="OVER",
            line=3.5,
            trends=(TrendWindow("L5", 4, 5),),
            model_p_eligible=True,
        )


def test_model_comparison_is_diagnostic_only_and_preserves_model_p():
    obs = _snapshot().observations[0]
    diagnostic = compare_to_model(obs, model_p=0.42)
    assert diagnostic.model_p == pytest.approx(0.42)
    assert diagnostic.directional_disagreement is True
    assert diagnostic.decision_effect == "NONE"
    assert diagnostic.model_p_eligible is False
    assert diagnostic.truth_gate_eligible is False


def test_research_sidecar_cannot_enter_model_or_truth_gate():
    sidecar = research_sidecar(_match(_snapshot()))
    assert sidecar["model_p_eligible"] is False
    assert sidecar["truth_gate_eligible"] is False
    assert sidecar["decision_effect"] == "NONE"
    assert sidecar["historical_hit_rate_is_probability"] is False
    assert sidecar["observation"]["trends"][1] == {
        "label": "L10",
        "hits": 9,
        "attempts": 10,
        "hit_rate_pct": 90.0,
    }


def test_snapshot_content_hash_is_deterministic():
    one = _snapshot()
    two = _snapshot()
    assert one.content_hash == two.content_hash


def test_missing_canonical_identity_is_not_inferred_from_player_name():
    row = _kittle_record(player_id=None)
    with pytest.raises(MySpariEdgeContextError, match="MISSING_IDENTITY:player_id"):
        _snapshot(row)
