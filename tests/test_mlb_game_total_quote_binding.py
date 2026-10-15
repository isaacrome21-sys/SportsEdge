"""Total Runs 3-Way quote-binding tests. Offline fixtures only.

Proves the canonical-path game-total binding layer
(sportsedge.mlb_game_total_quote_binding), the gate-for-gate sibling
of the period binding for the DraftKings full-game "Total Runs
(3-Way)" market (GAME_TOTAL_3_WAY: OVER / EXACTLY / UNDER at an
integer line):

* a complete three-selection group binds (rung-identity grouping
  included), reaches feature assembly and the shared game-total
  pricer (provenance hashes), and blocks only at the deployment
  gate -- GAME_TOTAL_3_WAY is absent from config/deployments.json,
  whose lookup fails closed, so the stage is UNKNOWN / not eligible;
* each admissibility failure produces its specific
  GAME_TOTAL_3WAY_* code;
* the settlement basis is VERIFIED THREE_WAY and its partition
  matches the canonical full-game totals settlement code (the
  two-way PUSH cell at equality is the 3-way EXACTLY cell);
* through run_full, 3-way rows resolve to named blockers, never the
  legacy generic reason and never a price.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from sportsedge.mlb_game_total_quote_binding import (
    GAME_TOTAL_3WAY_DEPLOYMENT_NOT_ELIGIBLE,
    GAME_TOTAL_3WAY_EVENT_ID_MISSING,
    GAME_TOTAL_3WAY_FEATURES_UNAVAILABLE,
    GAME_TOTAL_3WAY_FIXTURE_BINDING_MISMATCH,
    GAME_TOTAL_3WAY_FIXTURE_BINDING_MISSING,
    GAME_TOTAL_3WAY_LINE_UNVERIFIED,
    GAME_TOTAL_3WAY_PAIR_SKEW_EXCEEDED,
    GAME_TOTAL_3WAY_PERIOD_UNVERIFIED,
    GAME_TOTAL_3WAY_PRICE_UNVERIFIED,
    GAME_TOTAL_3WAY_QUOTE_NOT_PREGAME,
    GAME_TOTAL_3WAY_QUOTE_STALE,
    GAME_TOTAL_3WAY_QUOTE_TIMESTAMP_INVALID,
    GAME_TOTAL_3WAY_QUOTE_TIMESTAMP_MISSING,
    GAME_TOTAL_3WAY_QUOTE_UNPAIRED,
    GAME_TOTAL_3WAY_SELECTION_UNVERIFIED,
    GAME_TOTAL_3WAY_SOURCE_MISSING,
    SETTLEMENT_BASIS, bind_game_total_quotes, normalize_game_total_market,
    phone_game_total_binding_rows, settlement_basis,
)
from sportsedge.mlb_game_total_quote_binding import (
    _validate_game_total_canonical_quote as validate_game_total_quote)

NOW = datetime(2026, 9, 14, 23, 0, tzinfo=timezone.utc)
GAME_PK = 777002
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
        "sport": "MLB", "market": "GAME_TOTAL_3_WAY", "book": "draftkings",
        "event_id": "DK-EVT-9", "game_pk": GAME_PK,
        "away": "Away Club", "home": "Home Club", "kickoff": KICKOFF,
        "side": "OVER", "line": 8, "odds": 150,
        "quote_captured_at": "2026-09-14T22:59:00Z",
    }
    base.update(over)
    return base


def _trio(**over):
    rows = [
        _row(side="OVER", odds=150),
        _row(side="EXACTLY", odds=800,
             quote_captured_at="2026-09-14T22:59:20Z"),
        _row(side="UNDER", odds=-160,
             quote_captured_at="2026-09-14T22:59:40Z"),
    ]
    for row in rows:
        row.update(over)
    return rows


def _codes(bound):
    return [r.get("reason_code") for r in bound["row_results"]]


# ------------------------------------------------------------ happy paths

def test_valid_trio_binds_as_one_group():
    bound = bind_game_total_quotes(_trio(), now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND"] * 3
    assert len(bound["groups"]) == 1
    group = bound["groups"][0]
    assert group["status"] == "BOUND"
    assert group["rung_line"] == 8.0
    assert group["settlement_basis"]["status"] == "VERIFIED"
    assert group["settlement_basis"]["settlement_type"] == "THREE_WAY"
    assert group["fixture"]["game_pk"] == GAME_PK
    # Quotes are carried in canonical selection order.
    assert [q["side"] for q in group["quotes"]] == ["OVER", "EXACTLY", "UNDER"]
    for quote in group["quotes"]:
        again = validate_game_total_quote(dict(quote))
        assert again["period"] == "FULL_GAME"
        assert again["market"] == "GAME_TOTAL_3_WAY"
        assert quote["period_period_basis"] == "MARKET_IDENTITY"


def test_explicit_full_game_period_binds_with_explicit_basis():
    bound = bind_game_total_quotes(
        _trio(period="FULL_GAME"), now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND"] * 3
    assert bound["groups"][0]["quotes"][0]["period_period_basis"] == "EXPLICIT"


def test_exact_spelling_canonicalizes_to_exactly():
    rows = _trio()
    rows[1]["side"] = "EXACT"
    bound = bind_game_total_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND"] * 3
    assert bound["groups"][0]["quotes"][1]["side"] == "EXACTLY"


def test_two_rungs_bind_as_two_groups():
    # Two integer rungs of the ladder in one capture: 8 and 9. Each
    # rung must bind as its own group; a rung-blind grouping would
    # collapse all six quotes into one group and refuse.
    rows = _trio() + _trio(line=9)
    bound = bind_game_total_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND"] * 6
    assert len(bound["groups"]) == 2
    assert sorted(g["rung_line"] for g in bound["groups"]) == [8.0, 9.0]


def test_rungs_never_cross_bind():
    rows = _trio()
    rows[2]["line"] = 9  # UNDER quoted at a different rung
    bound = bind_game_total_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_QUOTE_UNPAIRED] * 3
    assert bound["groups"] == []


# ------------------------------------------------------- settlement basis

def test_settlement_basis_table_is_verified_three_way():
    assert set(SETTLEMENT_BASIS) == {"GAME_TOTAL_3_WAY"}
    basis = settlement_basis("GAME_TOTAL_3_WAY")
    assert basis["status"] == "VERIFIED"
    assert basis["settlement_type"] == "THREE_WAY"


def test_settlement_partition_matches_canonical_totals_code():
    # The canonical full-game totals settlement partitions the final
    # total into above / exactly-on / below the line; its PUSH cell
    # at equality is exactly the 3-way market's EXACTLY cell.
    from sportsedge.mlb_catalog_prediction_settlement import _game_outcome
    facts = {"game": {"away_runs": 5, "home_runs": 3,
                      "away_team_id": "101", "home_team_id": "202"}}
    pred = {"market": "TOTALS", "entity_id": str(GAME_PK), "line": 8}
    assert _game_outcome(dict(pred, side="OVER"), facts) == "PUSH"
    assert _game_outcome(dict(pred, side="UNDER"), facts) == "PUSH"
    assert _game_outcome(dict(pred, side="OVER", line=7.5), facts) == "WIN"
    assert _game_outcome(dict(pred, side="UNDER", line=8.5), facts) == "WIN"


# ------------------------------------------------------------ refusals

def test_missing_source_refused():
    bound = bind_game_total_quotes(_trio(book=""), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_SOURCE_MISSING] * 3


def test_missing_event_id_refused():
    bound = bind_game_total_quotes(_trio(event_id=""), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_EVENT_ID_MISSING] * 3


def test_segment_period_never_binds_as_full_game():
    bound = bind_game_total_quotes(_trio(period="F5"), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_PERIOD_UNVERIFIED] * 3
    bound = bind_game_total_quotes(_trio(period="FIRST_3"), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_PERIOD_UNVERIFIED] * 3


def test_bad_selection_refused():
    bound = bind_game_total_quotes(_trio(side="HOME"), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_SELECTION_UNVERIFIED] * 3


def test_half_line_refused_by_name():
    # A "3-way" row at a half line is a different contract: no final
    # total can land exactly on 8.5, so the EXACTLY cell cannot exist.
    bound = bind_game_total_quotes(_trio(line=8.5), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_LINE_UNVERIFIED] * 3


def test_negative_line_refused():
    bound = bind_game_total_quotes(_trio(line=-8), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_LINE_UNVERIFIED] * 3


def test_bad_price_refused():
    bound = bind_game_total_quotes(_trio(odds=-50), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_PRICE_UNVERIFIED] * 3


def test_missing_timestamp_refused():
    bound = bind_game_total_quotes(
        _trio(quote_captured_at=""), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_QUOTE_TIMESTAMP_MISSING] * 3


def test_naive_timestamp_refused():
    bound = bind_game_total_quotes(
        _trio(quote_captured_at="2026-09-14T22:59:00"), now=NOW,
        fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_QUOTE_TIMESTAMP_INVALID] * 3


def test_stale_quote_refused():
    bound = bind_game_total_quotes(
        _trio(quote_captured_at="2026-09-14T22:50:00Z"), now=NOW,
        fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_QUOTE_STALE] * 3


def test_missing_game_pk_refused():
    rows = _trio()
    for row in rows:
        row.pop("game_pk")
    bound = bind_game_total_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_FIXTURE_BINDING_MISSING] * 3


def test_no_resolver_fails_closed():
    bound = bind_game_total_quotes(_trio(), now=NOW, fixture_resolver=None)
    assert _codes(bound) == [GAME_TOTAL_3WAY_FIXTURE_BINDING_MISSING] * 3


def test_fixture_team_mismatch_refused():
    bound = bind_game_total_quotes(
        _trio(away="Other Club"), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_FIXTURE_BINDING_MISMATCH] * 3


def test_post_first_pitch_capture_refused():
    rows = [
        _row(side="OVER", quote_captured_at="2026-09-14T23:10:30Z"),
        _row(side="EXACTLY", quote_captured_at="2026-09-14T23:10:35Z"),
        _row(side="UNDER", quote_captured_at="2026-09-14T23:10:40Z"),
    ]
    bound = bind_game_total_quotes(
        rows, now=datetime(2026, 9, 14, 23, 11, 0, tzinfo=timezone.utc),
        fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_QUOTE_NOT_PREGAME] * 3


def test_incomplete_group_refused_unpaired():
    bound = bind_game_total_quotes(_trio()[:2], now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_QUOTE_UNPAIRED] * 2
    assert bound["groups"] == []


def test_duplicate_selection_refused_unpaired():
    rows = _trio()
    rows[2]["side"] = "OVER"  # two OVERs, no UNDER
    bound = bind_game_total_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_QUOTE_UNPAIRED] * 3


def test_group_skew_refused():
    rows = _trio()
    rows[0]["quote_captured_at"] = "2026-09-14T22:58:10Z"
    rows[1]["quote_captured_at"] = "2026-09-14T22:58:30Z"
    rows[2]["quote_captured_at"] = "2026-09-14T23:00:40Z"  # group span 150s
    bound = bind_game_total_quotes(
        rows, now=datetime(2026, 9, 14, 23, 1, 0, tzinfo=timezone.utc),
        fixture_resolver=_resolver)
    assert _codes(bound) == [GAME_TOTAL_3WAY_PAIR_SKEW_EXCEEDED] * 3


def test_non_3way_rows_are_not_game_total():
    bound = bind_game_total_quotes(
        [_row(market="TOTALS")], now=NOW, fixture_resolver=_resolver)
    assert bound["row_results"][0]["status"] == "NOT_GAME_TOTAL_3WAY"
    assert bound["groups"] == []


def test_aliases_normalize():
    assert normalize_game_total_market("total_runs_3_way") == "GAME_TOTAL_3_WAY"
    assert normalize_game_total_market("GAME_TOTAL_THREE_WAY") == "GAME_TOTAL_3_WAY"
    assert normalize_game_total_market("TOTAL_RUNS_3WAY") == "GAME_TOTAL_3_WAY"
    assert normalize_game_total_market("TOTALS") is None
    assert normalize_game_total_market("F3_TOTALS") is None
    assert normalize_game_total_market("GAME_TOTAL") is None


# ------------------------------------------------------------- the stage

class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _history_payload(games=120):
    """Synthetic strictly-prior StatsAPI schedule: both fixture teams
    in every game, verified final scores, all before 2026-09-14."""
    out = []
    for i in range(games):
        day = 1 + (i % 13)
        out.append({
            "gamePk": 9000 + i,
            "gameDate": f"2026-09-{day:02d}T23:10:00Z",
            "officialDate": f"2026-09-{day:02d}",
            "status": {"abstractGameState": "Final"},
            "teams": {
                "away": {"team": {"id": 101}, "score": 3 + (i % 5)},
                "home": {"team": {"id": 202}, "score": 2 + (i % 4)},
            },
            "linescore": {"innings": [
                {"num": n, "away": {"runs": 0}, "home": {"runs": 0}}
                for n in range(1, 10)]},
        })
    return {"dates": [{"date": "2026-09-13", "games": out}]}


def _history_opener(request, timeout=0):
    return _Response(_history_payload())


def _empty_opener(request, timeout=0):
    return _Response({"dates": []})


def test_stage_reaches_pricer_and_blocks_at_deployment_gate():
    results, receipts = phone_game_total_binding_rows(
        _trio(), now=NOW, fixture_resolver=_resolver,
        opener=_history_opener)
    assert len(results) == 3
    for result in results:
        assert result["status"] == "NO_MODEL_OR_MARKET"
        assert result["game_total_reason"] == GAME_TOTAL_3WAY_DEPLOYMENT_NOT_ELIGIBLE
        assert result["blocker"] == "NO_VALIDATION"
        # GAME_TOTAL_3_WAY is absent from the deployment registry;
        # the lookup fails closed rather than inventing a stage.
        assert result["game_total_deployment"]["stage"] == "UNKNOWN"
        assert result["game_total_deployment"]["eligible"] is False
        assert result["game_total_deployment"]["reason"] == "market absent from registry"
        lineage = result["game_total_feature_lineage"]
        assert lineage["feature_source_hash"]
        assert lineage["away_history_games"] >= 10
        assert lineage["home_history_games"] >= 10
        reach = result["game_total_pricer_reachability"]
        assert reach["engine"] == "SHARED_GAME_TOTAL_ENGINE"
        assert len(reach["readouts"]) == 3
        assert [r["side"] for r in reach["readouts"]] == ["OVER", "EXACTLY", "UNDER"]
        for readout in reach["readouts"]:
            assert len(readout["distribution_sha256"]) == 64
            assert len(readout["readout_sha256"]) == 64
        assert "model_p" not in result
        assert "model_probability" not in result
    assert receipts[0]["bound_groups"] == 1


def test_stage_blocks_at_feature_assembly_without_history():
    results, _ = phone_game_total_binding_rows(
        _trio(), now=NOW, fixture_resolver=_resolver, opener=_empty_opener)
    for result in results:
        assert result["game_total_reason"] == GAME_TOTAL_3WAY_FEATURES_UNAVAILABLE
        assert result["blocker"] == "NO_DATA"
        assert result["game_total_binding"]["group_id"]


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


@pytest.mark.registry_lane_internals
def test_trio_through_run_full_names_feature_blocker():
    from artifacts.run_it_full import run_full

    def getter(url):
        if "probablePitcher" in url:
            return _fixture_schedule_payload()
        return {"dates": []}

    card = run_full({"lines": _trio(), "sport": "MLB"},
                    now=NOW, getter=getter)
    evaluated = card["evaluated_rows"]
    assert len(evaluated) == 3
    for result in evaluated:
        assert result["status"] == "NO_MODEL_OR_MARKET"
        assert result["game_total_reason"] == GAME_TOTAL_3WAY_FEATURES_UNAVAILABLE
        assert result["blocker"] == "NO_DATA"
        assert result["game_total_binding"]["fixture"]["game_pk"] == GAME_PK
        assert "NO_VERIFIED_MODEL_FOR_THIS_MARKET" not in result["reason"]
    assert card["prop_model_status"]["mlb_game_total_engine"].startswith(
        "SHARED_GAME_TOTAL_ENGINE_VIA_MLB_GAME_TOTAL_QUOTE_BINDING_V1")


@pytest.mark.registry_lane_internals
def test_alias_intake_routes_to_binding_stage():
    from artifacts.run_it_full import run_full
    rows = [{"sport": "MLB", "market": "TOTAL_RUNS_3_WAY",
             "away": "Away Club", "home": "Home Club", "side": "OVER",
             "line": 8, "odds": 150, "kickoff": KICKOFF,
             "quote_captured_at": "2026-09-14T22:59:00Z"}]
    card = run_full({"lines": rows}, now=NOW, auto_context=False)
    result = card["evaluated_rows"][0]
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["game_total_reason"] == GAME_TOTAL_3WAY_SOURCE_MISSING
    assert result["blocker"] == "NO_QUOTE"
