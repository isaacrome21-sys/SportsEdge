"""Derived F5 quote-binding tests. Offline fixtures only.

Proves the canonical-path derived-F5 binding layer
(sportsedge.mlb_f5_derived_quote_binding) for the three derived
families of the verified F5 set -- F5_BOTH_TEAMS_TO_SCORE (M14),
F5_WINNING_MARGIN and F5_CORRECT_SCORE (M15):

* a BTTS YES/NO pair binds per rung (rungs never cross-bind), a
  winning-margin group binds only as a mechanically verified
  complete partition, a correct-score group binds only with its
  ANY_OTHER catch-all; bound groups reach feature assembly and the
  shared derived-F5 pricer (provenance hashes) and block only at
  the deployment gate -- none of the markets is in
  config/deployments.json, whose lookup fails closed;
* incomplete single-sided sets refuse by name
  (F5_DERIVED_SELECTION_SET_INCOMPLETE), never silently price;
* each admissibility failure produces its specific F5_DERIVED_*
  code; all three markets carry a verified settlement basis;
* through run_full, derived rows resolve to named blockers, never
  the legacy generic reason and never a price.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from sportsedge.mlb_f5_derived_quote_binding import (
    F5_DERIVED_DEPLOYMENT_NOT_ELIGIBLE,
    F5_DERIVED_FEATURES_UNAVAILABLE,
    F5_DERIVED_LINE_UNVERIFIED,
    F5_DERIVED_PERIOD_UNVERIFIED,
    F5_DERIVED_QUOTE_UNPAIRED,
    F5_DERIVED_SELECTION_SET_INCOMPLETE,
    F5_DERIVED_SELECTION_UNVERIFIED,
    F5_DERIVED_SOURCE_MISSING,
    SETTLEMENT_BASIS, bind_f5_derived_quotes, normalize_f5_derived_market,
    phone_f5_derived_binding_rows, settlement_basis,
)
from sportsedge.mlb_f5_derived_quote_binding import (
    _validate_f5_derived_canonical_quote as validate_derived_quote)

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

MARGIN_PARTITION = ["AWAY_BY_3_PLUS", "AWAY_BY_2", "AWAY_BY_1", "TIE",
                    "HOME_BY_1", "HOME_BY_2", "HOME_BY_3_PLUS"]


def _resolver(**_kwargs):
    return dict(FIXTURE)


def _row(**over):
    base = {
        "sport": "MLB", "market": "F5_BOTH_TEAMS_TO_SCORE",
        "book": "draftkings", "event_id": "DK-EVT-9", "game_pk": GAME_PK,
        "away": "Away Club", "home": "Home Club", "kickoff": KICKOFF,
        "side": "YES", "line": 2, "odds": 130,
        "quote_captured_at": "2026-09-14T22:59:00Z",
    }
    base.update(over)
    return base


def _btts_pair(**over):
    rows = [_row(**over),
            _row(side="NO", odds=-150,
                 quote_captured_at="2026-09-14T22:59:30Z")]
    for row in rows:
        row.update(over)
    return rows


def _margin_rows(selections=MARGIN_PARTITION, **over):
    rows = []
    for i, selection in enumerate(selections):
        row = _row(market="F5_WINNING_MARGIN", side=selection, line=None,
                   odds=200,
                   quote_captured_at=f"2026-09-14T22:59:{10 + i * 5:02d}Z")
        row.update(over)
        rows.append(row)
    return rows


def _score_rows(selections=("AWAY_0_HOME_0", "AWAY_1_HOME_1", "ANY_OTHER"),
                **over):
    rows = []
    for i, selection in enumerate(selections):
        row = _row(market="F5_CORRECT_SCORE", side=selection, line=None,
                   odds=600,
                   quote_captured_at=f"2026-09-14T22:59:{10 + i * 10:02d}Z")
        row.update(over)
        rows.append(row)
    return rows


def _codes(bound):
    return [r.get("reason_code") for r in bound["row_results"]]


# ------------------------------------------------------------ happy paths

def test_valid_btts_pair_binds():
    bound = bind_f5_derived_quotes(_btts_pair(), now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND", "BOUND"]
    assert len(bound["groups"]) == 1
    group = bound["groups"][0]
    assert group["status"] == "BOUND"
    assert group["rung_line"] == 2.0
    assert group["settlement_basis"]["status"] == "VERIFIED"
    assert group["fixture"]["game_pk"] == GAME_PK
    for quote in group["quotes"]:
        again = validate_derived_quote(dict(quote))
        assert again["period"] == "FIRST_5"
        assert again["market"] == "F5_BOTH_TEAMS_TO_SCORE"
        assert quote["period_period_basis"] == "MARKET_IDENTITY"


def test_btts_rungs_never_cross_bind():
    rows = _btts_pair() + _btts_pair(line=3)
    bound = bind_f5_derived_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND"] * 4
    assert len(bound["groups"]) == 2
    assert sorted(g["rung_line"] for g in bound["groups"]) == [2.0, 3.0]
    mixed = _btts_pair()
    mixed[1]["line"] = 3
    bound = bind_f5_derived_quotes(mixed, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_DERIVED_QUOTE_UNPAIRED] * 2


def test_margin_complete_partition_binds():
    bound = bind_f5_derived_quotes(_margin_rows(), now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND"] * 7
    group = bound["groups"][0]
    assert sorted(group["partition"]) == sorted(MARGIN_PARTITION)
    for quote in group["quotes"]:
        assert validate_derived_quote(dict(quote))["market"] == "F5_WINNING_MARGIN"


def test_margin_coarse_partition_also_binds():
    rows = _margin_rows(["AWAY_BY_1_PLUS", "TIE", "HOME_BY_1_PLUS"])
    bound = bind_f5_derived_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND"] * 3


def test_correct_score_with_catch_all_binds():
    bound = bind_f5_derived_quotes(_score_rows(), now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND"] * 3
    assert "ANY_OTHER" in bound["groups"][0]["partition"]


# ------------------------------------------------------- settlement basis

def test_settlement_basis_table_covers_all_three_markets():
    assert set(SETTLEMENT_BASIS) == {
        "F5_BOTH_TEAMS_TO_SCORE", "F5_WINNING_MARGIN", "F5_CORRECT_SCORE"}
    for market, basis in SETTLEMENT_BASIS.items():
        assert basis["status"] == "VERIFIED", market
        assert settlement_basis(market)["settlement_type"]


# ------------------------------------------------------------ refusals

def test_margin_incomplete_partition_refused_by_name():
    rows = _margin_rows(MARGIN_PARTITION[:-1])  # no +infinity tail band
    bound = bind_f5_derived_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_DERIVED_SELECTION_SET_INCOMPLETE] * 6
    assert bound["groups"] == []


def test_margin_duplicate_selection_refused_unpaired():
    rows = _margin_rows()
    rows[6]["side"] = "HOME_BY_2"
    bound = bind_f5_derived_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_DERIVED_QUOTE_UNPAIRED] * 7


def test_correct_score_without_catch_all_refused_by_name():
    rows = _score_rows(("AWAY_0_HOME_0", "AWAY_1_HOME_1"))
    bound = bind_f5_derived_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_DERIVED_SELECTION_SET_INCOMPLETE] * 2
    assert bound["groups"] == []


def test_full_game_period_never_binds_as_f5():
    bound = bind_f5_derived_quotes(
        _btts_pair(period="FG"), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_DERIVED_PERIOD_UNVERIFIED] * 2
    bound = bind_f5_derived_quotes(
        _btts_pair(period="FIRST_5"), now=NOW, fixture_resolver=_resolver)
    assert [r["status"] for r in bound["row_results"]] == ["BOUND", "BOUND"]
    assert bound["groups"][0]["quotes"][0]["period_period_basis"] == "EXPLICIT"


def test_bad_selections_refused():
    bound = bind_f5_derived_quotes(
        _btts_pair(side="OVER"), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_DERIVED_SELECTION_UNVERIFIED] * 2
    rows = _margin_rows(["HOME_BY_LOTS"] * 1)
    bound = bind_f5_derived_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_DERIVED_SELECTION_UNVERIFIED]


def test_btts_rung_shape_refused():
    for bad_line in (0, 8, 2.5, None):
        bound = bind_f5_derived_quotes(
            _btts_pair(line=bad_line), now=NOW, fixture_resolver=_resolver)
        assert _codes(bound) == [F5_DERIVED_LINE_UNVERIFIED] * 2, bad_line
    rows = _margin_rows()
    rows[0]["line"] = 2  # a band market carries no line
    bound = bind_f5_derived_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert bound["row_results"][0]["reason_code"] == F5_DERIVED_LINE_UNVERIFIED


def test_missing_source_refused():
    bound = bind_f5_derived_quotes(_btts_pair(book=""), now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_DERIVED_SOURCE_MISSING] * 2


def test_non_derived_rows_are_not_f5_derived():
    bound = bind_f5_derived_quotes(
        [_row(market="F5_TOTALS")], now=NOW, fixture_resolver=_resolver)
    assert bound["row_results"][0]["status"] == "NOT_F5_DERIVED"
    assert bound["groups"] == []


def test_aliases_normalize():
    assert normalize_f5_derived_market("f5_btts") == "F5_BOTH_TEAMS_TO_SCORE"
    assert normalize_f5_derived_market("FIRST_FIVE_WINNING_MARGIN") == "F5_WINNING_MARGIN"
    assert normalize_f5_derived_market("F5_CORRECT_SCORE") == "F5_CORRECT_SCORE"
    assert normalize_f5_derived_market("F5_TOTALS") is None
    assert normalize_f5_derived_market("GAME_TOTAL_3_WAY") is None


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
    """Synthetic strictly-prior StatsAPI schedule: both fixture teams
    in every game, complete innings linescores, all before 2026-09-14."""
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
    results, receipts = phone_f5_derived_binding_rows(
        _btts_pair() + _margin_rows(), now=NOW,
        fixture_resolver=_resolver, opener=_history_opener)
    assert len(results) == 9
    for result in results:
        assert result["status"] == "NO_MODEL_OR_MARKET"
        assert result["f5_derived_reason"] == F5_DERIVED_DEPLOYMENT_NOT_ELIGIBLE
        assert result["blocker"] == "NO_VALIDATION"
        assert result["f5_derived_deployment"]["stage"] == "UNKNOWN"
        assert result["f5_derived_deployment"]["eligible"] is False
        assert result["f5_derived_deployment"]["reason"] == "market absent from registry"
        lineage = result["f5_derived_feature_lineage"]
        assert lineage["feature_source_hash"]
        assert lineage["away_history_games"] >= 10
        reach = result["f5_derived_pricer_reachability"]
        assert reach["engine"] == "SHARED_F5_DERIVED_ENGINE"
        for readout in reach["readouts"]:
            assert len(readout["distribution_sha256"]) == 64
            assert len(readout["readout_sha256"]) == 64
        assert "model_p" not in result
        assert "model_probability" not in result
    assert receipts[0]["bound_groups"] == 2


def test_stage_blocks_at_feature_assembly_without_history():
    results, _ = phone_f5_derived_binding_rows(
        _btts_pair(), now=NOW, fixture_resolver=_resolver,
        opener=_empty_opener)
    for result in results:
        assert result["f5_derived_reason"] == F5_DERIVED_FEATURES_UNAVAILABLE
        assert result["blocker"] == "NO_DATA"
        assert result["f5_derived_binding"]["group_id"]


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
def test_btts_pair_through_run_full_names_feature_blocker():
    from artifacts.run_it_full import run_full

    def getter(url):
        if "probablePitcher" in url:
            return _fixture_schedule_payload()
        return {"dates": []}

    card = run_full({"lines": _btts_pair(), "sport": "MLB"},
                    now=NOW, getter=getter)
    evaluated = card["evaluated_rows"]
    assert len(evaluated) == 2
    for result in evaluated:
        assert result["status"] == "NO_MODEL_OR_MARKET"
        assert result["f5_derived_reason"] == F5_DERIVED_FEATURES_UNAVAILABLE
        assert result["blocker"] == "NO_DATA"
        assert result["f5_derived_binding"]["fixture"]["game_pk"] == GAME_PK
        assert "NO_VERIFIED_MODEL_FOR_THIS_MARKET" not in result["reason"]
    assert card["prop_model_status"]["mlb_f5_derived_engine"].startswith(
        "SHARED_F5_DERIVED_ENGINE_VIA_MLB_F5_DERIVED_QUOTE_BINDING_V1")


@pytest.mark.registry_lane_internals
def test_alias_intake_routes_to_binding_stage():
    from artifacts.run_it_full import run_full
    rows = [{"sport": "MLB", "market": "F5_BTTS",
             "away": "Away Club", "home": "Home Club", "side": "YES",
             "line": 2, "odds": 130, "kickoff": KICKOFF,
             "quote_captured_at": "2026-09-14T22:59:00Z"}]
    card = run_full({"lines": rows}, now=NOW, auto_context=False)
    result = card["evaluated_rows"][0]
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["f5_derived_reason"] == F5_DERIVED_SOURCE_MISSING
    assert result["blocker"] == "NO_QUOTE"
