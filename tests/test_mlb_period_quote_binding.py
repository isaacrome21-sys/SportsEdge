"""Period (F3/F7) quote-binding tests. Offline fixtures only.

Proves the canonical-path period binding layer
(sportsedge.mlb_period_quote_binding), the gate-for-gate sibling of
the F5 binding for the DraftKings 1st-3 / 1st-7 innings market sets:

* valid paired period quotes bind (rung-identity pairing included),
  reach feature assembly and the shared period pricer (provenance
  hashes), and block only at the deployment gate -- the period
  markets are absent from config/deployments.json, whose lookup
  fails closed, so the stage is UNKNOWN / not eligible;
* each admissibility failure produces its specific PERIOD_* code;
* all eight markets carry a verified settlement basis, the period
  moneylines as VERIFIED_TWO_WAY (declared settlement type in
  sportsedge.moneyline_settlement; ties push, undeclared books fail
  closed in the settlement code itself);
* through run_full, period rows resolve to named blockers, never the
  legacy generic reason and never a price.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from sportsedge.mlb_period_quote_binding import (
    PERIOD_DEPLOYMENT_NOT_ELIGIBLE, PERIOD_EVENT_ID_MISSING,
    PERIOD_FEATURES_UNAVAILABLE, PERIOD_FIXTURE_BINDING_MISMATCH,
    PERIOD_FIXTURE_BINDING_MISSING, PERIOD_LINE_UNVERIFIED,
    PERIOD_PAIR_SKEW_EXCEEDED, PERIOD_PERIOD_UNVERIFIED,
    PERIOD_PRICE_UNVERIFIED, PERIOD_QUOTE_NOT_PREGAME, PERIOD_QUOTE_STALE,
    PERIOD_QUOTE_TIMESTAMP_INVALID, PERIOD_QUOTE_TIMESTAMP_MISSING,
    PERIOD_QUOTE_UNPAIRED, PERIOD_SELECTION_UNVERIFIED,
    PERIOD_SOURCE_MISSING,
    SETTLEMENT_BASIS, bind_period_quotes, normalize_period_market,
    phone_period_binding_rows, settlement_basis,
)
from sportsedge.mlb_period_quote_binding import (
    _validate_period_canonical_quote as validate_period_quote)

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
        "sport": "MLB", "market": "F3_TOTALS", "book": "draftkings",
        "event_id": "DK-EVT-9", "game_pk": GAME_PK,
        "away": "Away Club", "home": "Home Club", "kickoff": KICKOFF,
        "side": "OVER", "line": 2.5, "odds": -110,
        "quote_captured_at": "2026-09-14T22:59:00Z",
    }
    base.update(over)
    return base


def _pair(**over):
    second = {"side": "UNDER", "odds": -105,
              "quote_captured_at": "2026-09-14T22:59:30Z"}
    second.update(over)
    return [_row(**over), _row(**second)]


def _codes(bound):
    return [r.get("reason_code") for r in bound["row_results"]]


# ------------------------------------------------------------ happy paths

def test_valid_f3_totals_pair_binds():
    bound = bind_period_quotes(_pair(), now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND", "BOUND"]
    assert len(bound["pairs"]) == 1
    pair = bound["pairs"][0]
    assert pair["status"] == "BOUND"
    assert pair["innings"] == 3
    assert pair["settlement_basis"]["status"] == "VERIFIED"
    assert pair["fixture"]["game_pk"] == GAME_PK
    for quote in pair["quotes"]:
        again = validate_period_quote(dict(quote))
        assert again["period"] == "F3"
        assert again["market"] == "F3_TOTALS"
        assert quote["period_period_basis"] == "MARKET_IDENTITY"


def test_valid_f7_totals_pair_binds():
    bound = bind_period_quotes(
        _pair(market="F7_TOTALS", line=6.5), now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND", "BOUND"]
    pair = bound["pairs"][0]
    assert pair["innings"] == 7
    for quote in pair["quotes"]:
        assert validate_period_quote(dict(quote))["period"] == "F7"


def test_explicit_period_binds_with_explicit_basis():
    bound = bind_period_quotes(_pair(period="FIRST_3"), now=NOW,
                               fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND", "BOUND"]
    assert bound["pairs"][0]["quotes"][0]["period_period_basis"] == "EXPLICIT"


def test_f7_run_line_pair_binds_with_negated_lines():
    rows = [
        _row(market="F7_RUN_LINE", side="HOME", line=-1.5, odds=-130),
        _row(market="F7_RUN_LINE", side="AWAY", line=1.5, odds=110,
             quote_captured_at="2026-09-14T22:59:30Z"),
    ]
    bound = bind_period_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND", "BOUND"]
    assert bound["pairs"][0]["rung_line"] == 1.5  # away side's signed line


def test_f3_team_totals_pair_binds_to_fixture_team_entity():
    rows = [
        _row(market="F3_TEAM_TOTALS", team_side="HOME", line=0.5),
        _row(market="F3_TEAM_TOTALS", team_side="HOME", side="UNDER",
             line=0.5, quote_captured_at="2026-09-14T22:59:30Z"),
    ]
    bound = bind_period_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND", "BOUND"]
    pair = bound["pairs"][0]
    assert pair["entity_id"] == "202"
    assert {q["entity_id"] for q in pair["quotes"]} == {"202"}


def test_f7_team_totals_at_catalog_line_binds():
    # The Oct 13 catalog records 1st-7 team totals at 2.5.
    rows = [
        _row(market="F7_TEAM_TOTALS", team_side="AWAY", line=2.5),
        _row(market="F7_TEAM_TOTALS", team_side="AWAY", side="UNDER",
             line=2.5, quote_captured_at="2026-09-14T22:59:30Z"),
    ]
    bound = bind_period_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND", "BOUND"]
    assert bound["pairs"][0]["entity_id"] == "101"


def test_run_line_rungs_never_cross_pair():
    # Two rungs of the F3 run-line ladder in one capture: -0.5 and -1.5
    # (away-signed). Each rung must bind as its own pair; a rung-blind
    # grouping would collapse all four quotes into one group and refuse.
    rows = [
        _row(market="F3_RUN_LINE", side="AWAY", line=-0.5, odds=-130),
        _row(market="F3_RUN_LINE", side="HOME", line=0.5, odds=110,
             quote_captured_at="2026-09-14T22:59:20Z"),
        _row(market="F3_RUN_LINE", side="AWAY", line=-1.5, odds=130,
             quote_captured_at="2026-09-14T22:59:10Z"),
        _row(market="F3_RUN_LINE", side="HOME", line=1.5, odds=-150,
             quote_captured_at="2026-09-14T22:59:40Z"),
    ]
    bound = bind_period_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND"] * 4
    assert len(bound["pairs"]) == 2
    assert sorted(p["rung_line"] for p in bound["pairs"]) == [-1.5, -0.5]


# ------------------------------------------------------- settlement basis

def test_settlement_basis_table_covers_all_eight_markets():
    assert set(SETTLEMENT_BASIS) == {
        "F3_MONEYLINE", "F3_RUN_LINE", "F3_TOTALS", "F3_TEAM_TOTALS",
        "F7_MONEYLINE", "F7_RUN_LINE", "F7_TOTALS", "F7_TEAM_TOTALS"}
    for market, basis in SETTLEMENT_BASIS.items():
        assert basis["status"] == "VERIFIED", market


def test_period_moneyline_basis_is_declared_two_way_in_code():
    from sportsedge.moneyline_settlement import (
        MoneylineSettlementType, declared_moneyline_settlement_type)
    for market in ("F3_MONEYLINE", "F7_MONEYLINE"):
        assert declared_moneyline_settlement_type(
            market, "DraftKings") is MoneylineSettlementType.TWO_WAY
        assert settlement_basis(market)["settlement_type"] == "TWO_WAY"


def test_period_settlement_code_settles_from_period_facts():
    from sportsedge.mlb_additional_pit_joiner import _derive_outcome
    facts = {"f3": {"away_runs": 2, "home_runs": 2},
             "f7": {"away_runs": 5, "home_runs": 3}}
    # Tied F3 moneyline at DraftKings pushes under the declared type.
    assert _derive_outcome(facts, "F3_MONEYLINE", str(GAME_PK), None,
                           "HOME", sportsbook="DraftKings") == "PUSH"
    # F7 moneyline: away leads 5-3 after seven.
    assert _derive_outcome(facts, "F7_MONEYLINE", str(GAME_PK), None,
                           "AWAY", sportsbook="DraftKings") == "WIN"
    assert _derive_outcome(facts, "F7_RUN_LINE", str(GAME_PK), -1.5,
                           "AWAY", sportsbook="DraftKings") == "WIN"
    assert _derive_outcome(facts, "F3_TOTALS", str(GAME_PK), 4,
                           "OVER", sportsbook="DraftKings") == "PUSH"
    assert _derive_outcome(facts, "F3_TOTALS", str(GAME_PK), 4.5,
                           "UNDER", sportsbook="DraftKings") == "WIN"


def test_period_moneyline_tie_fails_closed_for_undeclared_book():
    from sportsedge.mlb_additional_pit_joiner import (
        MLBPITJoinError, _derive_outcome, _policy_ambiguity)
    facts = {"f3": {"away_runs": 1, "home_runs": 1}}
    with pytest.raises(MLBPITJoinError):
        _derive_outcome(facts, "F3_MONEYLINE", str(GAME_PK), None,
                        "HOME", sportsbook="SomeUndeclaredBook")
    assert _policy_ambiguity(facts, "F3_MONEYLINE",
                             sportsbook="SomeUndeclaredBook") == [
        "F3_MONEYLINE_TIE_POLICY_NOT_NORMALIZED"]
    # A declared book records no ambiguity for the same tied facts.
    assert _policy_ambiguity(facts, "F3_MONEYLINE",
                             sportsbook="DraftKings") == []


def test_period_team_total_settles_in_joiner():
    from sportsedge.mlb_additional_pit_joiner import (
        MLBPITJoinError, _derive_outcome)
    facts = {"f7": {"away_runs": 5, "home_runs": 3,
                    "away_team_id": "101", "home_team_id": "202"}}
    assert _derive_outcome(facts, "F7_TEAM_TOTALS", "202", 2.5,
                           "OVER", sportsbook="DraftKings") == "WIN"
    assert _derive_outcome(facts, "F7_TEAM_TOTALS", "101", 5.5,
                           "UNDER", sportsbook="DraftKings") == "WIN"
    assert _derive_outcome(facts, "F7_TEAM_TOTALS", "101", 5,
                           "OVER", sportsbook="DraftKings") == "PUSH"
    # Missing period facts fail closed in the settlement code itself.
    with pytest.raises(MLBPITJoinError):
        _derive_outcome(facts, "F3_TEAM_TOTALS", "101", 0.5,
                        "OVER", sportsbook="DraftKings")
    # An entity outside the fixture's teams refuses by name.
    with pytest.raises(MLBPITJoinError):
        _derive_outcome(facts, "F7_TEAM_TOTALS", "999", 2.5,
                        "OVER", sportsbook="DraftKings")


# ------------------------------------------------------------ refusals

def test_missing_source_refused():
    bound = bind_period_quotes(_pair(book=""), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_SOURCE_MISSING] * 2


def test_missing_event_id_refused():
    bound = bind_period_quotes(_pair(event_id=""), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_EVENT_ID_MISSING] * 2


def test_full_game_period_refused():
    bound = bind_period_quotes(_pair(period="FG"), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_PERIOD_UNVERIFIED] * 2


def test_f5_period_never_binds_as_f3():
    bound = bind_period_quotes(_pair(period="F5"), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_PERIOD_UNVERIFIED] * 2


def test_f3_period_never_binds_as_f7():
    rows = _pair(market="F7_TOTALS", line=6.5, period="FIRST_3")
    bound = bind_period_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_PERIOD_UNVERIFIED] * 2


def test_draw_selection_refused_for_period_moneyline():
    rows = [
        _row(market="F3_MONEYLINE", side="DRAW", line=None, odds=300),
        _row(market="F3_MONEYLINE", side="HOME", line=None, odds=-120,
             quote_captured_at="2026-09-14T22:59:30Z"),
    ]
    bound = bind_period_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert bound["row_results"][0]["reason_code"] == PERIOD_SELECTION_UNVERIFIED
    assert bound["row_results"][1]["reason_code"] == PERIOD_QUOTE_UNPAIRED


def test_moneyline_with_nonzero_line_refused():
    rows = [
        _row(market="F7_MONEYLINE", side="HOME", line=1.5, odds=-120),
        _row(market="F7_MONEYLINE", side="AWAY", line=1.5, odds=100,
             quote_captured_at="2026-09-14T22:59:30Z"),
    ]
    bound = bind_period_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_LINE_UNVERIFIED] * 2


def test_negative_totals_line_refused():
    bound = bind_period_quotes(_pair(line=-0.5), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_LINE_UNVERIFIED] * 2


def test_bad_price_refused():
    bound = bind_period_quotes(_pair(odds=-50), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_PRICE_UNVERIFIED] * 2


def test_missing_timestamp_refused():
    bound = bind_period_quotes(
        _pair(quote_captured_at=""), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_QUOTE_TIMESTAMP_MISSING] * 2


def test_naive_timestamp_refused():
    bound = bind_period_quotes(
        _pair(quote_captured_at="2026-09-14T22:59:00"), now=NOW,
        fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_QUOTE_TIMESTAMP_INVALID] * 2


def test_stale_quote_refused():
    bound = bind_period_quotes(
        _pair(quote_captured_at="2026-09-14T22:50:00Z"), now=NOW,
        fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_QUOTE_STALE] * 2


def test_missing_game_pk_refused():
    rows = _pair()
    for row in rows:
        row.pop("game_pk")
    bound = bind_period_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_FIXTURE_BINDING_MISSING] * 2


def test_no_resolver_fails_closed():
    bound = bind_period_quotes(_pair(), now=NOW, fixture_resolver=None)
    assert _codes(bound) == [PERIOD_FIXTURE_BINDING_MISSING] * 2


def test_fixture_team_mismatch_refused():
    bound = bind_period_quotes(
        _pair(away="Other Club"), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_FIXTURE_BINDING_MISMATCH] * 2


def test_post_first_pitch_capture_refused():
    rows = [
        _row(quote_captured_at="2026-09-14T23:10:30Z"),
        _row(side="UNDER", quote_captured_at="2026-09-14T23:10:40Z"),
    ]
    bound = bind_period_quotes(
        rows, now=datetime(2026, 9, 14, 23, 11, 0, tzinfo=timezone.utc),
        fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_QUOTE_NOT_PREGAME] * 2


def test_unpaired_single_quote_refused():
    bound = bind_period_quotes([_row()], now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_QUOTE_UNPAIRED]


def test_pair_skew_refused():
    rows = [
        _row(quote_captured_at="2026-09-14T22:57:30Z"),
        _row(side="UNDER", quote_captured_at="2026-09-14T22:59:45Z"),
    ]
    bound = bind_period_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_PAIR_SKEW_EXCEEDED] * 2


def test_team_total_without_team_refused():
    rows = [
        _row(market="F3_TEAM_TOTALS", line=0.5),
        _row(market="F3_TEAM_TOTALS", side="UNDER", line=0.5,
             quote_captured_at="2026-09-14T22:59:30Z"),
    ]
    bound = bind_period_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [PERIOD_SELECTION_UNVERIFIED] * 2


def test_non_period_rows_are_not_period():
    bound = bind_period_quotes(
        [_row(market="F5_TOTALS")], now=NOW, fixture_resolver=_resolver)
    assert bound["row_results"][0]["status"] == "NOT_PERIOD"
    assert bound["pairs"] == []


def test_aliases_normalize():
    assert normalize_period_market("first_three_team_total") == "F3_TEAM_TOTALS"
    assert normalize_period_market("F7_TOTAL") == "F7_TOTALS"
    assert normalize_period_market("F3_ML") == "F3_MONEYLINE"
    assert normalize_period_market("F5_TOTALS") is None
    assert normalize_period_market("TOTALS") is None


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


def _inning(num, away, home):
    return {"num": num, "away": {"runs": away}, "home": {"runs": home}}


def _history_payload(games=120):
    """Synthetic strictly-prior StatsAPI schedule: both fixture teams in
    every game, complete innings 1-9 linescores, all before 2026-09-14."""
    out = []
    for i in range(games):
        day = 1 + (i % 13)
        innings = [_inning(1, i % 3, (i + 1) % 2)] + [
            _inning(n, (i + n) % 2, (i + 1) % 3) for n in range(2, 10)]
        out.append({
            "gamePk": 9000 + i,
            "gameDate": f"2026-09-{day:02d}T23:10:00Z",
            "officialDate": f"2026-09-{day:02d}",
            "status": {"abstractGameState": "Final"},
            "teams": {
                "away": {"team": {"id": 101}, "score": 6},
                "home": {"team": {"id": 202}, "score": 5},
            },
            "linescore": {"innings": innings},
        })
    return {"dates": [{"date": "2026-09-13", "games": out}]}


def _history_opener(request, timeout=0):
    return _Response(_history_payload())


def _empty_opener(request, timeout=0):
    return _Response({"dates": []})


def test_stage_reaches_pricer_and_blocks_at_deployment_gate():
    results, receipts = phone_period_binding_rows(
        _pair(), now=NOW, fixture_resolver=_resolver,
        opener=_history_opener)
    assert len(results) == 2
    for result in results:
        assert result["status"] == "NO_MODEL_OR_MARKET"
        assert result["period_reason"] == PERIOD_DEPLOYMENT_NOT_ELIGIBLE
        assert result["blocker"] == "NO_VALIDATION"
        # The period markets are absent from the deployment registry;
        # the lookup fails closed rather than inventing a stage.
        assert result["period_deployment"]["stage"] == "UNKNOWN"
        assert result["period_deployment"]["eligible"] is False
        assert result["period_deployment"]["reason"] == "market absent from registry"
        lineage = result["period_feature_lineage"]
        assert lineage["feature_source_hash"]
        assert lineage["away_history_games"] >= 10
        assert lineage["home_history_games"] >= 10
        reach = result["period_pricer_reachability"]
        assert reach["engine"] == "SHARED_PERIOD_ENGINE"
        assert len(reach["readouts"]) == 2
        for readout in reach["readouts"]:
            assert len(readout["distribution_sha256"]) == 64
            assert len(readout["readout_sha256"]) == 64
        assert "model_p" not in result
        assert "model_probability" not in result
    assert receipts[0]["bound_pairs"] == 1


def test_stage_f7_moneyline_reaches_deployment_gate():
    rows = [
        _row(market="F7_MONEYLINE", side="HOME", line=None, odds=-120),
        _row(market="F7_MONEYLINE", side="AWAY", line=None, odds=100,
             quote_captured_at="2026-09-14T22:59:30Z"),
    ]
    results, _ = phone_period_binding_rows(
        rows, now=NOW, fixture_resolver=_resolver, opener=_history_opener)
    for result in results:
        assert result["period_reason"] == PERIOD_DEPLOYMENT_NOT_ELIGIBLE
        basis = result["period_binding"]["settlement_basis"]
        assert basis["status"] == "VERIFIED"
        assert basis["settlement_type"] == "TWO_WAY"
        assert "model_p" not in result


def test_stage_blocks_at_feature_assembly_without_history():
    results, _ = phone_period_binding_rows(
        _pair(), now=NOW, fixture_resolver=_resolver, opener=_empty_opener)
    for result in results:
        assert result["period_reason"] == PERIOD_FEATURES_UNAVAILABLE
        assert result["blocker"] == "NO_DATA"
        assert result["period_binding"]["pair_id"]


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
def test_period_pair_through_run_full_names_feature_blocker():
    from artifacts.run_it_full import run_full

    def getter(url):
        if "probablePitcher" in url:
            return _fixture_schedule_payload()
        return {"dates": []}

    card = run_full({"lines": _pair(), "sport": "MLB"},
                    now=NOW, getter=getter)
    evaluated = card["evaluated_rows"]
    assert len(evaluated) == 2
    for result in evaluated:
        assert result["status"] == "NO_MODEL_OR_MARKET"
        assert result["period_reason"] == PERIOD_FEATURES_UNAVAILABLE
        assert result["blocker"] == "NO_DATA"
        assert result["period_binding"]["fixture"]["game_pk"] == GAME_PK
        assert "NO_VERIFIED_MODEL_FOR_THIS_MARKET" not in result["reason"]
    assert card["prop_model_status"]["mlb_period_engine"].startswith(
        "SHARED_PERIOD_ENGINE_VIA_MLB_PERIOD_QUOTE_BINDING_V1")


@pytest.mark.registry_lane_internals
def test_period_alias_intake_routes_to_binding_stage():
    from artifacts.run_it_full import run_full
    rows = [{"sport": "MLB", "market": "FIRST_THREE_TOTAL",
             "away": "Away Club", "home": "Home Club", "side": "OVER",
             "line": 2.5, "odds": -110, "kickoff": KICKOFF,
             "quote_captured_at": "2026-09-14T22:59:00Z"}]
    card = run_full({"lines": rows}, now=NOW, auto_context=False)
    result = card["evaluated_rows"][0]
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["period_reason"] == PERIOD_SOURCE_MISSING
    assert result["blocker"] == "NO_QUOTE"
