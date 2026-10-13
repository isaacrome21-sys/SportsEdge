"""F5 quote-binding tests (2026-10-12). Offline fixtures only.

Proves the canonical-path F5 binding layer
(sportsedge.mlb_f5_quote_binding):
* a valid paired F5 quote set binds, reaches feature assembly and the
  shared F5 pricer (provenance hashes), and blocks only at the F5
  deployment gate;
* each admissibility failure produces its specific F5_* reason code;
* all four markets carry a verified settlement basis -- F5_MONEYLINE
  as VERIFIED_TWO_WAY (declared settlement type, ties push) since the
  2026-10-12 owner settlement ruling;
* through run_full, F5 rows resolve to named blockers, never the
  legacy generic reason.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from sportsedge.mlb_f5_quote_binding import (
    F5_DEPLOYMENT_NOT_ELIGIBLE, F5_EVENT_ID_MISSING,
    F5_FEATURES_UNAVAILABLE, F5_FIXTURE_BINDING_MISMATCH,
    F5_FIXTURE_BINDING_MISSING, F5_LINE_UNVERIFIED, F5_PAIR_SKEW_EXCEEDED,
    F5_PERIOD_UNVERIFIED, F5_PRICE_UNVERIFIED, F5_QUOTE_NOT_PREGAME,
    F5_QUOTE_STALE, F5_QUOTE_TIMESTAMP_INVALID, F5_QUOTE_TIMESTAMP_MISSING,
    F5_QUOTE_UNPAIRED, F5_SELECTION_UNVERIFIED,
    F5_SETTLEMENT_BASIS_UNVERIFIED, F5_SOURCE_MISSING,
    SETTLEMENT_BASIS, bind_f5_quotes, phone_f5_binding_rows,
    settlement_basis,
)
from sportsedge.quote_bridge import validate_canonical_quote

NOW = datetime(2026, 9, 14, 23, 0, tzinfo=timezone.utc)
GAME_PK = 777001
KICKOFF = "2026-09-14T23:10:00Z"

FIXTURE = {
    "game_pk": GAME_PK,
    "away_team_id": 101,
    "home_team_id": 202,
    "away_name": "Away Club",
    "home_name": "Home Club",
    "first_pitch_at": datetime(2026, 9, 14, 23, 10, tzinfo=timezone.utc),
    "official_date": "2026-09-14",
}


def _resolver(**_kwargs):
    return dict(FIXTURE)


def _row(**over):
    base = {
        "sport": "MLB", "market": "F5_TOTALS", "book": "draftkings",
        "event_id": "DK-EVT-1", "game_pk": GAME_PK,
        "away": "Away Club", "home": "Home Club", "kickoff": KICKOFF,
        "side": "OVER", "line": 4.5, "odds": -110,
        "quote_captured_at": "2026-09-14T22:59:00Z",
    }
    base.update(over)
    return base


def _totals_pair(**over):
    return [
        _row(**over),
        _row(side="UNDER", odds=-105,
             quote_captured_at="2026-09-14T22:59:30Z", **over),
    ]


def _codes(bound):
    return [r.get("reason_code") for r in bound["row_results"]]


# ------------------------------------------------------------ happy paths

def test_valid_totals_pair_binds():
    bound = bind_f5_quotes(_totals_pair(), now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND", "BOUND"]
    assert len(bound["pairs"]) == 1
    pair = bound["pairs"][0]
    assert pair["status"] == "BOUND"
    assert pair["settlement_basis"]["status"] == "VERIFIED"
    assert pair["fixture"]["game_pk"] == GAME_PK
    for quote in pair["quotes"]:
        # The emitted quotes are admissible canonical quotes, period F5.
        again = validate_canonical_quote(dict(quote))
        assert again["period"] == "F5"
        assert again["market"] == "F5_TOTALS"
        assert quote["f5_period_basis"] == "MARKET_IDENTITY"


def test_explicit_first5_period_binds_with_explicit_basis():
    bound = bind_f5_quotes(_totals_pair(period="F5"), now=NOW,
                           fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND", "BOUND"]
    assert bound["pairs"][0]["quotes"][0]["f5_period_basis"] == "EXPLICIT"


def test_run_line_pair_binds_with_negated_lines():
    rows = [
        _row(market="F5_RUN_LINE", side="HOME", line=-1.5, odds=-130),
        _row(market="F5_RUN_LINE", side="AWAY", line=1.5, odds=110,
             quote_captured_at="2026-09-14T22:59:30Z"),
    ]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND", "BOUND"]
    assert bound["pairs"][0]["settlement_basis"]["status"] == "VERIFIED"


def test_team_totals_pair_binds_to_fixture_team_entity():
    rows = [
        _row(market="F5_TEAM_TOTALS", team_side="HOME", line=2.5),
        _row(market="F5_TEAM_TOTALS", team_side="HOME", side="UNDER",
             line=2.5, quote_captured_at="2026-09-14T22:59:30Z"),
    ]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND", "BOUND"]
    pair = bound["pairs"][0]
    assert pair["entity_id"] == "202"
    assert {q["entity_id"] for q in pair["quotes"]} == {"202"}


# ------------------------------------------------------- settlement basis

def test_settlement_basis_table_matches_settlement_code():
    basis = settlement_basis("F5_MONEYLINE")
    assert basis["status"] == "VERIFIED"
    assert basis["settlement_type"] == "TWO_WAY"
    assert "VERIFIED_TWO_WAY" in basis["basis"]
    assert "PUSH" in basis["basis"]
    assert "draftkings.com" in " ".join(basis["rules_sources"])
    for market in ("F5_RUN_LINE", "F5_TOTALS", "F5_TEAM_TOTALS"):
        assert settlement_basis(market)["status"] == "VERIFIED"
        assert "PUSH" in settlement_basis(market)["basis"]


def test_moneyline_pair_binds_with_verified_two_way_basis():
    rows = [
        _row(market="F5_MONEYLINE", side="HOME", line=None, odds=-120),
        _row(market="F5_MONEYLINE", side="AWAY", line=None, odds=100,
             quote_captured_at="2026-09-14T22:59:30Z"),
    ]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND", "BOUND"]
    pair = bound["pairs"][0]
    assert pair["status"] == "BOUND"
    assert pair["settlement_basis"]["status"] == "VERIFIED"
    assert pair["settlement_basis"]["settlement_type"] == "TWO_WAY"


# --------------------------------------------------------- identity gates

def test_missing_source_event_and_gamepk():
    rows = _totals_pair()
    del rows[0]["book"]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert bound["row_results"][0]["reason_code"] == F5_SOURCE_MISSING

    rows = _totals_pair()
    del rows[0]["event_id"]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert bound["row_results"][0]["reason_code"] == F5_EVENT_ID_MISSING

    rows = _totals_pair()
    del rows[0]["game_pk"]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert bound["row_results"][0]["reason_code"] == \
        F5_FIXTURE_BINDING_MISSING


def test_fixture_binding_missing_without_resolver_or_match():
    bound = bind_f5_quotes(_totals_pair(), now=NOW, fixture_resolver=None)
    assert _codes(bound) == [F5_FIXTURE_BINDING_MISSING] * 2
    bound = bind_f5_quotes(_totals_pair(), now=NOW,
                           fixture_resolver=lambda **kw: None)
    assert _codes(bound) == [F5_FIXTURE_BINDING_MISSING] * 2


def test_fixture_mismatch_on_kickoff_and_team_names():
    bound = bind_f5_quotes(_totals_pair(kickoff="2026-09-14T23:30:00Z"),
                           now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_FIXTURE_BINDING_MISMATCH] * 2
    bound = bind_f5_quotes(_totals_pair(away="Home Club", home="Away Club"),
                           now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_FIXTURE_BINDING_MISMATCH] * 2


def test_quote_captured_after_first_pitch_refuses():
    later = datetime(2026, 9, 14, 23, 12, tzinfo=timezone.utc)
    rows = [
        _row(quote_captured_at="2026-09-14T23:11:00Z"),
        _row(side="UNDER", quote_captured_at="2026-09-14T23:11:30Z"),
    ]
    bound = bind_f5_quotes(rows, now=later, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_QUOTE_NOT_PREGAME] * 2


# ------------------------------------------------------------ period gate

def test_ambiguous_period_refuses():
    bound = bind_f5_quotes(_totals_pair(period="FG"), now=NOW,
                           fixture_resolver=_resolver)
    assert _codes(bound) == [F5_PERIOD_UNVERIFIED] * 2
    bound = bind_f5_quotes(_totals_pair(period="FULL_GAME"), now=NOW,
                           fixture_resolver=_resolver)
    assert _codes(bound) == [F5_PERIOD_UNVERIFIED] * 2


# ------------------------------------------------- selection/line/price

def test_selection_line_price_failures():
    bound = bind_f5_quotes(
        [_row(market="F5_TEAM_TOTALS", line=2.5)], now=NOW,
        fixture_resolver=_resolver)
    assert _codes(bound) == [F5_SELECTION_UNVERIFIED]

    bound = bind_f5_quotes([_row(side="HOME")], now=NOW,
                           fixture_resolver=_resolver)
    assert _codes(bound) == [F5_SELECTION_UNVERIFIED]

    bound = bind_f5_quotes(
        [_row(market="F5_MONEYLINE", side="HOME", line=1.5)], now=NOW,
        fixture_resolver=_resolver)
    assert _codes(bound) == [F5_LINE_UNVERIFIED]

    bound = bind_f5_quotes([_row(line=None)], now=NOW,
                           fixture_resolver=_resolver)
    assert _codes(bound) == [F5_LINE_UNVERIFIED]

    bound = bind_f5_quotes([_row(odds=-50)], now=NOW,
                           fixture_resolver=_resolver)
    assert _codes(bound) == [F5_PRICE_UNVERIFIED]


# ------------------------------------------------------------- timestamps

def test_stale_missing_and_invalid_timestamps():
    bound = bind_f5_quotes(
        [_row(quote_captured_at="2026-09-14T22:55:00Z")], now=NOW,
        fixture_resolver=_resolver)
    assert _codes(bound) == [F5_QUOTE_STALE]

    row = _row()
    del row["quote_captured_at"]
    bound = bind_f5_quotes([row], now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_QUOTE_TIMESTAMP_MISSING]

    bound = bind_f5_quotes([_row(quote_captured_at="not-a-time")], now=NOW,
                           fixture_resolver=_resolver)
    assert _codes(bound) == [F5_QUOTE_TIMESTAMP_INVALID]


# ---------------------------------------------------------------- pairing

def test_unpaired_single_side_and_duplicate_side():
    bound = bind_f5_quotes([_row()], now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_QUOTE_UNPAIRED]

    rows = [_row(), _row(odds=-115,
                         quote_captured_at="2026-09-14T22:59:30Z")]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_QUOTE_UNPAIRED] * 2


def test_pair_skew_over_120s_refuses():
    rows = [
        _row(quote_captured_at="2026-09-14T22:57:00Z"),
        _row(side="UNDER", quote_captured_at="2026-09-14T22:59:30Z"),
    ]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_PAIR_SKEW_EXCEEDED] * 2


def test_run_line_lines_must_negate_to_pair():
    rows = [
        _row(market="F5_RUN_LINE", side="HOME", line=-1.5),
        _row(market="F5_RUN_LINE", side="AWAY", line=-1.5,
             quote_captured_at="2026-09-14T22:59:30Z"),
    ]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_QUOTE_UNPAIRED] * 2


# ------------------------------------------------- stage: features + gate

class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _inning(num, away, home):
    return {"num": num, "away": {"runs": away}, "home": {"runs": home}}


def _history_payload(games=120):
    """Synthetic strictly-prior StatsAPI schedule: both fixture teams in
    every game, complete innings 1-5 linescores, all before 2026-09-14."""
    out = []
    for i in range(games):
        day = 1 + (i % 13)
        away_f5, home_f5 = i % 4, (i + 1) % 3
        innings = [_inning(1, away_f5, home_f5)] + [
            _inning(n, 0, 0) for n in range(2, 8)]
        out.append({
            "gamePk": 9000 + i,
            "gameDate": f"2026-09-{day:02d}T23:10:00Z",
            "officialDate": f"2026-09-{day:02d}",
            "status": {"abstractGameState": "Final"},
            "teams": {
                "away": {"team": {"id": 101}, "score": away_f5 + 3},
                "home": {"team": {"id": 202}, "score": home_f5 + 2},
            },
            "linescore": {"innings": innings},
        })
    return {"dates": [{"date": "2026-09-13", "games": out}]}


def _history_opener(request, timeout=0):
    return _Response(_history_payload())


def _empty_opener(request, timeout=0):
    return _Response({"dates": []})


def test_stage_reaches_pricer_and_blocks_at_deployment_gate():
    results, receipts = phone_f5_binding_rows(
        _totals_pair(), now=NOW, fixture_resolver=_resolver,
        opener=_history_opener)
    assert len(results) == 2
    for result in results:
        assert result["status"] == "NO_MODEL_OR_MARKET"
        assert result["f5_reason"] == F5_DEPLOYMENT_NOT_ELIGIBLE
        assert result["blocker"] == "NO_VALIDATION"
        assert result["f5_deployment"]["stage"] == "F5_STATE_CANDIDATE"
        assert result["f5_deployment"]["eligible"] is False
        lineage = result["f5_feature_lineage"]
        assert lineage["feature_source_hash"]
        assert lineage["away_history_games"] >= 10
        assert lineage["home_history_games"] >= 10
        reach = result["f5_pricer_reachability"]
        assert reach["engine"] == "SHARED_F5_ENGINE"
        assert len(reach["readouts"]) == 2
        for readout in reach["readouts"]:
            assert len(readout["distribution_sha256"]) == 64
            assert len(readout["readout_sha256"]) == 64
        # A blocked row publishes no probability.
        assert "model_p" not in result
        assert "model_probability" not in result
    assert receipts[0]["bound_pairs"] == 1


def test_stage_blocks_at_feature_assembly_without_history():
    results, _ = phone_f5_binding_rows(
        _totals_pair(), now=NOW, fixture_resolver=_resolver,
        opener=_empty_opener)
    for result in results:
        assert result["f5_reason"] == F5_FEATURES_UNAVAILABLE
        assert result["blocker"] == "NO_DATA"
        assert "insufficient" in result["blocker_detail"]
        assert result["f5_binding"]["pair_id"]


def test_stage_moneyline_reaches_deployment_gate_like_other_f5():
    rows = [
        _row(market="F5_MONEYLINE", side="HOME", line=None, odds=-120),
        _row(market="F5_MONEYLINE", side="AWAY", line=None, odds=100,
             quote_captured_at="2026-09-14T22:59:30Z"),
    ]
    results, _ = phone_f5_binding_rows(
        rows, now=NOW, fixture_resolver=_resolver,
        opener=_history_opener)
    for result in results:
        assert result["status"] == "NO_MODEL_OR_MARKET"
        assert result["f5_reason"] == F5_DEPLOYMENT_NOT_ELIGIBLE
        assert result["blocker"] == "NO_VALIDATION"
        assert result["f5_deployment"]["eligible"] is False
        basis = result["f5_binding"]["settlement_basis"]
        assert basis["status"] == "VERIFIED"
        assert basis["settlement_type"] == "TWO_WAY"
        reach = result["f5_pricer_reachability"]
        assert reach["engine"] == "SHARED_F5_ENGINE"
        assert len(reach["readouts"]) == 2
        assert "model_p" not in result


# ------------------------------------------------------------- run_full

def _fixture_schedule_payload():
    return {"dates": [{"date": "2026-09-14", "games": [{
        "gamePk": GAME_PK,
        "gameDate": KICKOFF,
        "officialDate": "2026-09-14",
        "status": {"abstractGameState": "Preview"},
        "teams": {
            "away": {"team": {"id": 101, "name": "Away Club"}},
            "home": {"team": {"id": 202, "name": "Home Club"}},
        },
    }]}]}


def test_f5_pair_through_run_full_binds_and_names_feature_blocker():
    from artifacts.run_it_full import run_full

    def getter(url):
        if "probablePitcher" in url:
            return _fixture_schedule_payload()
        return {"dates": []}

    card = run_full({"lines": _totals_pair(), "sport": "MLB"},
                    now=NOW, getter=getter)
    evaluated = card["evaluated_rows"]
    assert len(evaluated) == 2
    for result in evaluated:
        assert result["status"] == "NO_MODEL_OR_MARKET"
        assert result["f5_reason"] == F5_FEATURES_UNAVAILABLE
        assert result["blocker"] == "NO_DATA"
        assert result["f5_binding"]["fixture"]["game_pk"] == GAME_PK
        assert "NO_VERIFIED_MODEL_FOR_THIS_MARKET" not in result["reason"]
    assert card["prop_model_status"]["mlb_f5_engine"].startswith(
        "SHARED_F5_ENGINE_VIA_MLB_F5_QUOTE_BINDING_V1")


def test_f5_alias_intake_routes_to_binding_stage():
    from artifacts.run_it_full import run_full
    rows = [{"sport": "MLB", "market": "FIRST_FIVE_TOTAL",
             "away": "Away Club", "home": "Home Club", "side": "OVER",
             "line": 4.5, "odds": -110, "kickoff": KICKOFF,
             "quote_captured_at": "2026-09-14T22:59:00Z"}]
    card = run_full({"lines": rows}, now=NOW, auto_context=False)
    result = card["evaluated_rows"][0]
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["f5_reason"] == F5_SOURCE_MISSING
    assert result["blocker"] == "NO_QUOTE"
