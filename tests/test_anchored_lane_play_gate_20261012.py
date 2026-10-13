"""Anchored-lane PLAY gate (Isaac's architecture-conflict ruling, Oct 12 2026).

Under the end-state contract a research PLAY requires an INDEPENDENT model
probability that does not borrow the sportsbook price. Market-anchored
estimates (free_models Lane B: 15% shrink toward the posted line for
totals/spreads, 15% blend toward the no-vig price for moneylines) remain
available as separately labeled research, but:

- an anchored row with a large nominal EV can never reach a PLAY surface
  (engine ``edges``, ``independent_candidates``, or a positive-EV status);
- the same fixture priced by the genuinely independent lane can;
- every priced row on the canonical card carries an explicit
  ``pricing_provenance`` (INDEPENDENT vs MARKET_ANCHORED, mechanism named);
- a priced row whose provenance cannot be determined fails closed with
  PROVENANCE_UNDETERMINED -- it never defaults to independent.

All fixtures are offline; no network, no betting authority.
"""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "free_models_anchored_gate", ROOT / "artifacts" / "free_models.py")
model = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model)

from sportsedge.pricing_provenance import (
    ANCHORED_WATCH_STATUS,
    LANE_INDEPENDENT,
    LANE_MARKET_ANCHORED,
    UNDETERMINED_STATUS,
    apply_play_gate,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
KICKOFF = "2026-10-21T00:05:00Z"
FRESH_QUOTE = "2026-10-20T11:59:00Z"  # 60s before NOW


def _mlb_total_rows():
    """MLB total pair where BOTH lanes see a large nominal EV on UNDER.

    Raw model total is ~8.8 runs against a posted 14.5 line, so the
    independent Lane A probability is strongly +EV at +150 -- and the
    anchored Lane B probability (means shrunk 15% toward the line) is
    still +EV. Pre-ruling, a lane="B" run presented the anchored numbers
    as a positive-EV play. The gate must refuse exactly that.
    """
    base = {"sport": "MLB", "away": "Los Angeles Dodgers",
            "home": "Milwaukee Brewers", "market": "TOTAL",
            "line": 14.5, "kickoff": KICKOFF,
            "quote_captured_at": FRESH_QUOTE}
    return [dict(base, side="UNDER", odds=150),
            dict(base, side="OVER", odds=-170)]


def _engine_card(rows, **kw):
    return model.run({"lines": rows}, now=NOW, auto_context=False, **kw)


# ------------------------------------------------------- engine-level gate

def test_anchored_fixture_would_have_been_a_play_without_the_gate():
    # Fixture sanity: the Lane B (anchored) view itself clears the EV
    # floor by a wide margin -- this is a genuine would-be play, not a
    # row that was never going anywhere.
    card = _engine_card(_mlb_total_rows(), lane="A")
    under = next(r for r in card["evaluated_rows"]
                 if r["selection"].startswith("UNDER"))
    lane_b = under["pricing_lanes"]["lane_b_anchored"]
    assert lane_b["ev_per_dollar"] >= 0.30


def test_anchored_row_with_large_nominal_ev_cannot_reach_play():
    card = _engine_card(_mlb_total_rows(), lane="B")
    under = next(r for r in card["evaluated_rows"]
                 if r["selection"].startswith("UNDER"))
    # The anchored probability is still computed and labeled -- the math
    # is untouched -- but it is capped at WATCH with the mechanism named.
    assert under["pricing_lane"] == "LANE_B_ANCHORED"
    assert under["pricing_provenance"]["lane"] == LANE_MARKET_ANCHORED
    assert under["pricing_provenance"]["mechanism"] == "MARKET_SHRINK_15PCT"
    assert under["pricing_provenance"]["play_eligible"] is False
    assert under["status"] == ANCHORED_WATCH_STATUS
    assert under["reason"].startswith(
        "MARKET_ANCHORED_CANNOT_QUALIFY_AS_INDEPENDENT_PLAY")
    assert under["ev_per_dollar"] == \
        under["pricing_lanes"]["lane_b_anchored"]["ev_per_dollar"]
    # No play surface contains the anchored row (or any row).
    assert card["edges"] == []
    assert card["independent_candidates"] == []
    assert all(r["pricing_provenance"]["lane"] != LANE_MARKET_ANCHORED
               or r not in card["independent_candidates"]
               for r in card["evaluated_rows"])
    # Anchored EV is suppressed from the edges presentation: the legacy
    # lane_b_edges list is empty, and the qualifier surfaces as WATCH.
    assert card["lane_b_edges"] == []
    assert under in card["lane_b_watchlist"]
    assert under in card["independent_watchlist"]
    assert card["play_gate"]["anchored_max_surface"] == "WATCH"


def test_same_fixture_independent_lane_can_reach_play():
    card = _engine_card(_mlb_total_rows(), lane="A")
    under = next(r for r in card["evaluated_rows"]
                 if r["selection"].startswith("UNDER"))
    assert under["pricing_lane"] == "LANE_A_INDEPENDENT"
    assert under["pricing_provenance"]["lane"] == LANE_INDEPENDENT
    assert under["pricing_provenance"]["mechanism"] is None
    assert under["pricing_provenance"]["play_eligible"] is True
    assert under["status"] == "RESEARCH_POSITIVE_EV_UNVALIDATED"
    assert under in card["edges"]
    assert under in card["independent_candidates"]
    # Even in an independent run, the anchored side-view never becomes an
    # edge: lane_b_edges stays suppressed.
    assert card["lane_b_edges"] == []


def test_lane_b_moneyline_provenance_names_no_vig_blend():
    row = {"sport": "NFL", "away": "DET", "home": "ARI", "market": "ML",
           "side": "HOME", "odds": -110, "opposite_odds": -110,
           "kickoff": "2026-10-25T17:00:00Z",
           "quote_captured_at": FRESH_QUOTE}
    result = model.calculate(row, model.PublicContext(NOW), NOW,
                             auto_context=False, lane="B")
    assert result["pricing_lane"] == "LANE_B_ANCHORED"
    assert result["pricing_provenance"]["lane"] == LANE_MARKET_ANCHORED
    assert result["pricing_provenance"]["mechanism"] == "NO_VIG_BLEND_15PCT"
    assert result["pricing_provenance"]["play_eligible"] is False


def test_every_priced_engine_row_carries_provenance():
    card = _engine_card(_mlb_total_rows(), lane="A")
    for r in card["evaluated_rows"]:
        assert r["pricing_provenance"]["lane"] == LANE_INDEPENDENT
        assert r["pricing_provenance"]["source"]


# ------------------------------------------- canonical run_full propagation

def _run_full(rows, **kw):
    from artifacts.run_it_full import run_full
    return run_full({"lines": rows}, now=NOW, auto_context=False, **kw)


def test_run_full_anchored_game_row_cannot_reach_play():
    card = _run_full(_mlb_total_rows(), lane="B")
    under = next(r for r in card["evaluated_rows"]
                 if str(r.get("selection") or "").startswith("UNDER"))
    assert under["pricing_provenance"]["lane"] == LANE_MARKET_ANCHORED
    assert under["pricing_provenance"]["mechanism"] == "MARKET_SHRINK_15PCT"
    assert under["status"] == ANCHORED_WATCH_STATUS
    assert card["edges"] == []
    assert card["independent_candidates"] == []
    assert card["prop_candidates"] == []
    # The factor audit carries the provenance too: identifiable from the
    # card output alone, without re-deriving it.
    audit = card["factor_coverage"]["by_input_index"][0]
    assert audit["pricing_provenance"]["lane"] == LANE_MARKET_ANCHORED


def test_run_full_independent_game_row_still_reaches_play():
    card = _run_full(_mlb_total_rows(), lane="A")
    under = next(r for r in card["evaluated_rows"]
                 if str(r.get("selection") or "").startswith("UNDER"))
    assert under["pricing_provenance"]["lane"] == LANE_INDEPENDENT
    assert under["status"] == "RESEARCH_POSITIVE_EV_UNVALIDATED"
    assert under in card["edges"]
    audit = card["factor_coverage"]["by_input_index"][0]
    assert audit["pricing_provenance"]["lane"] == LANE_INDEPENDENT


def test_run_full_anytime_td_rows_carry_independent_provenance(tmp_path):
    from tests.test_canonical_run_it_20261012 import _td_cache, _td_row
    cache = _td_cache(tmp_path / "td")
    rows = [_td_row(side="YES", odds=-150), _td_row(side="NO", odds=130)]
    card = _run_full(rows, td_cache_dir=cache)
    td_rows = [r for r in card["evaluated_rows"]
               if r.get("market") == "ANYTIME_TD"]
    assert len(td_rows) == 2
    for r in td_rows:
        prov = r["pricing_provenance"]
        assert prov["lane"] == LANE_INDEPENDENT
        assert prov["source"].startswith("RESEARCH_BRIDGE_MARKET_BLIND:")
        assert prov["play_eligible"] is True


def test_run_full_nrfi_rows_carry_independent_provenance():
    from tests.test_mlb_first_inning import (
        _fixture_game, _history_games, _schedule_getter)
    getter = _schedule_getter(_history_games(), _fixture_game())
    now = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)
    base = {"sport": "MLB", "away": "Los Angeles Dodgers",
            "home": "Milwaukee Brewers",
            "kickoff": "2026-10-11T19:00:00-05:00", "book": "draftkings",
            "quote_captured_at": "2026-10-11T20:00:00Z"}
    rows = [dict(base, market="NRFI", odds=-140),
            dict(base, market="YRFI", odds=105)]
    from artifacts.run_it_full import run_full
    card = run_full({"lines": rows}, now=now, getter=getter)
    for r in card["evaluated_rows"]:
        prov = r["pricing_provenance"]
        assert prov["lane"] == LANE_INDEPENDENT
        assert prov["source"].startswith("RESEARCH_BRIDGE_MARKET_BLIND:")


# --------------------------------------------------------- gate unit tests

def test_unlabeled_priced_row_fails_closed():
    rows = [{"status": "RESEARCH_CANDIDATE_NOT_VALIDATED",
             "ev_per_dollar": 0.50, "estimate_p": 0.90}]
    changed = apply_play_gate(rows)
    assert changed == 1
    assert rows[0]["status"] == UNDETERMINED_STATUS
    assert rows[0]["reason"].startswith("PROVENANCE_UNDETERMINED")
    assert rows[0]["pricing_provenance"]["lane"] == "UNDETERMINED"
    assert rows[0]["pricing_provenance"]["play_eligible"] is False


def test_markerless_play_surface_row_fails_closed():
    # Even a row with a play status and NO probability fields at all must
    # not slip through: absence of provenance is itself the failure.
    rows = [{"status": "RESEARCH_POSITIVE_EV_UNVALIDATED"}]
    apply_play_gate(rows)
    assert rows[0]["status"] == UNDETERMINED_STATUS


def test_derivative_row_inherits_distribution_provenance():
    base = {"status": "PRICED_RESEARCH",
            "model_probabilities": {"over": 0.6, "under": 0.4},
            "away_team": "BUF", "home_team": "LAR"}
    anchored = {"lane": LANE_MARKET_ANCHORED,
                "mechanism": "MARKET_SHRINK_15PCT",
                "source": "FREE_MODELS_LANE_B_ANCHORED",
                "engine_lane": "LANE_B_ANCHORED", "play_eligible": False}
    rows = [dict(base)]
    apply_play_gate(rows, distribution_provenance={("BUF", "LAR"): anchored})
    assert rows[0]["status"] == ANCHORED_WATCH_STATUS
    assert rows[0]["pricing_provenance"]["via"] == "JOINT_SCORE_DISTRIBUTION"

    independent = {"lane": LANE_INDEPENDENT, "mechanism": None,
                   "source": "FREE_MODELS_LANE_A_INDEPENDENT",
                   "engine_lane": "LANE_A_INDEPENDENT", "play_eligible": True}
    rows = [dict(base)]
    apply_play_gate(rows,
                    distribution_provenance={("BUF", "LAR"): independent})
    assert rows[0]["status"] == "PRICED_RESEARCH"
    assert rows[0]["pricing_provenance"]["lane"] == LANE_INDEPENDENT

    rows = [dict(base)]
    apply_play_gate(rows)
    assert rows[0]["status"] == UNDETERMINED_STATUS
    assert "DERIVATIVE_DISTRIBUTION_PROVENANCE_MISSING" in rows[0]["reason"]


def test_independent_and_blocked_rows_untouched_by_gate():
    rows = [
        {"status": "RESEARCH_POSITIVE_EV_UNVALIDATED",
         "pricing_lane": "LANE_A_INDEPENDENT", "estimate_p": 0.7},
        {"status": "NO_MODEL_OR_MARKET", "reason": "NO_ENGINE"},
    ]
    changed = apply_play_gate(rows)
    assert changed == 0
    assert rows[0]["status"] == "RESEARCH_POSITIVE_EV_UNVALIDATED"
    assert rows[0]["pricing_provenance"]["lane"] == LANE_INDEPENDENT
    # Blocked rows carry no probability and get no lane stamp.
    assert "pricing_provenance" not in rows[1]
