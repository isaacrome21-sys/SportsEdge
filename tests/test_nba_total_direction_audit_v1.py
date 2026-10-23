"""Deterministic research diagnostics, never market admission or card authority."""
from __future__ import annotations

import copy
import json
from datetime import date, timedelta

import pytest

from scripts.audit_nba_total_directions import main
from sportsedge.research.nba_total_direction_audit_v1 import (
    _date, audit_total_directions,
)
from sportsedge.research.nba_totals_chronological_screen_v1 import (
    SCREEN, chronological_total_screen,
)


def row(i, *, market=232.5, model=220.0, actual=230.0, day=0):
    day_text = (date(2026, 10, 21) + timedelta(days=day)).isoformat()
    result = {"event_id": f"nba-{i}", "event_start": f"{day_text}T23:00:00Z",
              "actual": actual, "candidate_total": model,
              "climatology_total": 225.0,
              "candidate_error": model - actual,
              "baseline_error": 225.0 - actual,
              "market_close": market,
              "independent_market_admission": "NOT_VERIFIED"}
    if market is not None:
        result["market_reference_error"] = market - actual
    return result


def screen(rows):
    return {"screen_id": SCREEN, "status": "HISTORICAL_SCREEN_ONLY",
            "research_only": True, "play_authority": False,
            "market_admission": "NOT_VERIFIED",
            "counts": {"model_priced": len(rows),
                       "paired_with_timestamped_market_reference": sum(
                           r["market_close"] is not None for r in rows)},
            "rows": rows}


def test_separates_scoring_underprediction_from_market_direction():
    rows = [row(1, actual=230, day=0),  # forecast under book, under hit
            row(2, actual=240, day=0),  # forecast under book, under loss
            row(3, market=210, model=220, actual=225, day=1),  # over hit
            row(4, market=210, model=220, actual=205, day=1),  # over loss
            row(5, market=220, model=220, actual=220, day=2),  # tie projection
            row(6, market=None, model=219, actual=230, day=2)]
    audit = audit_total_directions(screen(rows))
    assert audit["all_model_rows"] == 6 and audit["paired_rows"] == 5
    assert audit["direction"]["UNDER"] == {"rows": 2, "hit": 1, "loss": 1, "push": 0}
    assert audit["direction"]["OVER"] == {"rows": 2, "hit": 1, "loss": 1, "push": 0}
    assert audit["direction"]["TIE"]["rows"] == 1
    assert audit["under_share_of_directional_rows"] == 0.5
    assert audit["mean_model_minus_actual"] < 0
    assert audit["model_vs_actual_day_bootstrap_95pct"] is not None
    assert audit == audit_total_directions(screen(rows))
    assert audit["play_authority"] is False


def test_many_unders_warns_without_changing_rows_or_reclassifying_anything():
    rows = [row(i, actual=229.0, day=i % 6) for i in range(25)]
    before = copy.deepcopy(rows)
    audit = audit_total_directions(screen(rows))
    assert audit["direction"]["UNDER"]["rows"] == 25
    assert audit["under_share_of_directional_rows"] == 1.0
    assert audit["one_direction_warning"] is True
    assert audit["mean_model_minus_actual"] == -9.0
    assert audit["mean_model_minus_market"] == -12.5
    assert rows == before
    assert audit["model_p_authority"] is False


def test_no_paired_market_is_not_zero_and_cannot_establish_edge():
    audit = audit_total_directions(screen([row(1, market=None)]))
    assert audit["paired_rows"] == 0
    assert audit["under_share_of_directional_rows"] is None
    assert audit["mean_model_minus_market"] is None
    assert audit["model_vs_market_day_bootstrap_95pct"] is None
    assert audit["one_direction_warning"] is False


def test_late_nba_tipoffs_cluster_by_chicago_slate_date_not_utc_day():
    assert _date("2026-10-23T02:00:00Z") == "2026-10-22"
    assert _date("2026-10-23T23:00:00Z") == "2026-10-23"


@pytest.mark.parametrize("mutate, code", [
    (lambda x: x["rows"][0].update(event_id=""), "NBA_TOTAL_BIAS_DUPLICATE_OR_MISSING_EVENT"),
    (lambda x: x["rows"][0].update(event_start="2026-10-21T23:00:00"),
     "NBA_TOTAL_BIAS_EVENT_START_NAIVE"),
    (lambda x: x["rows"][0].update(candidate_error=99), "NBA_TOTAL_BIAS_PARENT_ERROR_MISMATCH"),
    (lambda x: x["rows"][0].update(market_reference_error=99), "NBA_TOTAL_BIAS_MARKET_PAIR_INVALID"),
    (lambda x: x["rows"][0].update(candidate_total=float("nan")), "NBA_TOTAL_BIAS_MODEL_INVALID"),
    (lambda x: x.update(market_admission="VERIFIED"),
     "NBA_TOTAL_BIAS_PARENT_SCREEN_NOT_RESEARCH_ONLY"),
    (lambda x: x["counts"].update(model_priced=999), "NBA_TOTAL_BIAS_PARENT_CONSERVATION_FAILED"),
])
def test_refuses_tampered_or_authority_claiming_parent_rows(mutate, code):
    source = screen([row(1)])
    mutate(source)
    with pytest.raises(ValueError, match=code):
        audit_total_directions(source)


def test_cli_emits_only_research_diagnostic(tmp_path, capsys):
    source = tmp_path / "v2_screen.json"
    source.write_text(json.dumps(screen([row(1)])))
    assert main(["--screen", str(source)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "RESEARCH_DIAGNOSTIC_ONLY"
    assert result["market_admission"] == "NOT_VERIFIED"
    assert result["historical_entry_authority"] is False
    assert result["forward_entry_authority"] is False


def test_real_chronological_screen_handoff_preserves_research_only_receipts():
    # Exercise the actual parent producer, not a synthetic hand-built screen.
    from datetime import datetime, timedelta, timezone

    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    games = []
    for i in range(55):
        tip = base + timedelta(days=i)
        games.append({
            "event_id": f"receipt-{i}", "source_ref": f"score-{i}",
            "tipoff": tip.isoformat(),
            "observed_at": (tip + timedelta(hours=5)).isoformat(),
            "home": "A" if i % 2 else "B",
            "away": "B" if i % 2 else "A",
            "home_pts": 120, "away_pts": 112,
            "closing_total": 235.5,
            "close_captured_at": (tip - timedelta(minutes=30)).isoformat(),
            "close_source_ref": f"quote-{i}",
        })
    parent = chronological_total_screen(games)
    child = audit_total_directions(parent)
    assert child["paired_rows"] == parent["paired_games"]
    assert child["paired_rows"] > 0
    assert child["model_vs_market_day_bootstrap_95pct"] is not None
    assert child["source_receipts_reverified"] is False
    assert child["market_admission"] == "NOT_VERIFIED"
    assert child["play_authority"] is False
