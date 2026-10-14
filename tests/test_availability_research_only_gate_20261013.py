"""Availability research-only gate (owner review of PR #2157, finding 4;
issue #2158).

A row priced on QB_IDENTITY_EVIDENCE Form 2 carries
``availability_status == AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT``:
the QB's IDENTITY was verified, his AVAILABILITY is explicitly unknown.
The owner's governing sentence: a verified QB name must never be
mistaken for verified availability. The classification layer therefore
forces any such row to research-only BY STRUCTURE:

- the guard is driven by the availability FIELD, never by the row's
  status string -- a forged candidate status cannot switch it off;
- it fires regardless of EV size or provenance lane;
- the field itself is system-stamped only (trusted pre-pricing stage
  -> VERIFIED prepricing object -> priced row); intake rows can never
  forge it in either direction;
- a Form 1 row (availability verified through the injury payload --
  no such field stamped) is completely unaffected.

The gate is field-driven and sport-agnostic at the classification
layer, so the engine surface fixtures below reuse the MLB totals
harness from the anchored-lane gate tests: what matters is the field
on the row, not which sport's QB produced it.

All fixtures are offline; no network, no betting authority.
"""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "free_models_availability_gate", ROOT / "artifacts" / "free_models.py")
model = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model)

from sportsedge.pricing_provenance import (
    AVAILABILITY_PLAY_BLOCK,
    AVAILABILITY_RESEARCH_ONLY_STATUS,
    AVAILABILITY_UNVERIFIED,
    apply_play_gate,
    availability_forces_research_only,
    is_play_eligible,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
KICKOFF = "2026-10-21T00:05:00Z"
FRESH_QUOTE = "2026-10-20T11:59:00Z"  # 60s before NOW


def _verified_pp(**overrides):
    pp = {"source": "SPORTSEDGE_PREPRICING_V1",
          "verification_status": "VERIFIED",
          "adjustments": {}, "factors": [],
          "availability_status": AVAILABILITY_UNVERIFIED}
    pp.update(overrides)
    return pp


def _mlb_total_rows():
    base = {"sport": "MLB", "away": "Los Angeles Dodgers",
            "home": "Milwaukee Brewers", "market": "TOTAL",
            "line": 14.5, "kickoff": KICKOFF,
            "quote_captured_at": FRESH_QUOTE}
    return [dict(base, side="UNDER", odds=150),
            dict(base, side="OVER", odds=-170)]


# ------------------------------------------------------------ gate units

def test_extreme_ev_form2_row_is_forced_research_only():
    rows = [{"status": "RESEARCH_POSITIVE_EV_UNVALIDATED",
             "pricing_lane": "LANE_A_INDEPENDENT",
             "estimate_p": 0.99, "ev_per_dollar": 5.0,
             "availability_status": AVAILABILITY_UNVERIFIED}]
    changed = apply_play_gate(rows)
    assert changed == 1
    row = rows[0]
    assert row["status"] == AVAILABILITY_RESEARCH_ONLY_STATUS
    assert row["research_only"] is True
    assert row["availability_research_only"] is True
    assert row["play_blocked_reason"] == AVAILABILITY_PLAY_BLOCK
    assert row["reason"].startswith(AVAILABILITY_PLAY_BLOCK)
    # The label stays on the row: research output CARRIES it.
    assert row["availability_status"] == AVAILABILITY_UNVERIFIED
    assert availability_forces_research_only(row)
    assert not is_play_eligible(row)


def test_guard_fires_on_forged_candidate_statuses():
    # The availability FIELD drives the guard: relabeling the row as a
    # research candidate (prop surface) or a Phase 7 research edge
    # cannot launder it into an actionable surface.
    for forged in ("RESEARCH_CANDIDATE_NOT_VALIDATED", "RESEARCH_EDGE",
                   "PRICED_RESEARCH"):
        rows = [{"status": forged, "estimate_p": 0.95,
                 "ev_per_dollar": 2.5,
                 "availability_status": AVAILABILITY_UNVERIFIED}]
        apply_play_gate(rows)
        assert rows[0]["status"] == AVAILABILITY_RESEARCH_ONLY_STATUS, forged
        assert rows[0]["research_only"] is True
        assert not is_play_eligible(rows[0])


def test_form1_row_without_the_field_is_unaffected():
    # Form 1: availability verified via the injury payload -- the
    # pipeline stamps no availability field, and the same EV that was
    # demoted above stays a play-eligible independent row.
    rows = [{"status": "RESEARCH_POSITIVE_EV_UNVALIDATED",
             "pricing_lane": "LANE_A_INDEPENDENT",
             "estimate_p": 0.99, "ev_per_dollar": 5.0}]
    changed = apply_play_gate(rows)
    assert changed == 0
    assert rows[0]["status"] == "RESEARCH_POSITIVE_EV_UNVALIDATED"
    assert "research_only" not in rows[0]
    assert is_play_eligible(rows[0])


def test_blocked_row_carrying_the_field_is_not_reclassified():
    # The guard governs PRICED rows; a blocked row has no surface to
    # protect and keeps its blocker status.
    rows = [{"status": "NO_MODEL_OR_MARKET", "reason": "NO_ENGINE",
             "availability_status": AVAILABILITY_UNVERIFIED}]
    apply_play_gate(rows)
    assert rows[0]["status"] == "NO_MODEL_OR_MARKET"


# ------------------------------------------------------- engine surfaces

def test_engine_surfaces_exclude_availability_unverified_rows():
    rows = _mlb_total_rows()
    card = model.run({"lines": rows}, now=NOW, auto_context=False,
                     prepricing_adjustments=[_verified_pp(),
                                             _verified_pp()])
    under = next(r for r in card["evaluated_rows"]
                 if r["selection"].startswith("UNDER"))
    # The trusted prepricing object stamped the field, the gate
    # demoted the row, and no actionable surface contains it -- even
    # though this exact fixture reaches edges/candidates unstamped
    # (see the anchored-lane gate tests).
    assert under["availability_status"] == AVAILABILITY_UNVERIFIED
    assert under["status"] == AVAILABILITY_RESEARCH_ONLY_STATUS
    assert under["research_only"] is True
    assert card["edges"] == []
    assert card["independent_candidates"] == []
    # Research output only: the row surfaces on the watchlist,
    # carrying its availability label.
    assert under in card["independent_watchlist"]


def test_engine_control_same_fixture_without_the_stamp_plays():
    rows = _mlb_total_rows()
    pp = _verified_pp(availability_status=None)
    card = model.run({"lines": rows}, now=NOW, auto_context=False,
                     prepricing_adjustments=[pp, dict(pp)])
    under = next(r for r in card["evaluated_rows"]
                 if r["selection"].startswith("UNDER"))
    assert "availability_status" not in under
    assert under["status"] == "RESEARCH_POSITIVE_EV_UNVALIDATED"
    assert under in card["edges"]
    assert under in card["independent_candidates"]


def test_intake_cannot_forge_the_availability_field():
    # A forged field on the INTAKE row is stripped: the guard's input
    # is exclusively the trusted prepricing object. Forging the
    # unverified value must not block a clean row, and forging a
    # benign value must not matter either.
    rows = _mlb_total_rows()
    rows[0]["availability_status"] = AVAILABILITY_UNVERIFIED
    rows[1]["availability_status"] = "AVAILABILITY_VERIFIED_FORM1"
    card = model.run({"lines": rows}, now=NOW, auto_context=False)
    under = next(r for r in card["evaluated_rows"]
                 if r["selection"].startswith("UNDER"))
    assert "availability_status" not in under
    assert under["status"] == "RESEARCH_POSITIVE_EV_UNVALIDATED"
    assert under in card["independent_candidates"]


def test_unverified_prepricing_object_cannot_stamp_the_field():
    # The stamp follows the same trust rule as prepricing context:
    # an UNVERIFIED prepricing object is skipped wholesale.
    rows = _mlb_total_rows()
    pp = _verified_pp(verification_status="UNVERIFIED")
    card = model.run({"lines": rows}, now=NOW, auto_context=False,
                     prepricing_adjustments=[pp, dict(pp)])
    under = next(r for r in card["evaluated_rows"]
                 if r["selection"].startswith("UNDER"))
    assert "availability_status" not in under
    assert under in card["independent_candidates"]


# ------------------------------------------- canonical run_full chain

def test_run_full_stage_availability_forces_research_only():
    # End to end on the canonical path: the pre-pricing stage reports
    # availability unverified (as it does when a Form 2 consult
    # satisfies a fixture), and the priced game rows come out
    # research-only with every actionable surface empty.
    import artifacts.run_it_full as rif

    real_stage_games = rif.stage_games

    def stage_with_availability(game_rows, **kw):
        stages = real_stage_games(game_rows, **kw)
        for st in stages:
            st["availability_status"] = AVAILABILITY_UNVERIFIED
        return stages

    with mock.patch.object(rif, "stage_games", stage_with_availability):
        card = rif.run_full({"lines": _mlb_total_rows()}, now=NOW,
                            auto_context=False, lane="A")
    under = next(r for r in card["evaluated_rows"]
                 if str(r.get("selection") or "").startswith("UNDER"))
    assert under["availability_status"] == AVAILABILITY_UNVERIFIED
    assert under["status"] == AVAILABILITY_RESEARCH_ONLY_STATUS
    assert under["research_only"] is True
    assert card["edges"] == []
    assert card["independent_candidates"] == []
    assert card["prop_candidates"] == []
    assert (card["play_gate"]["availability_unverified_max_surface"]
            == "RESEARCH_ONLY")
    # The prepricing audit carries the state too: identifiable from
    # the card output alone.
    entry = card["prepricing_factor_audit"]["by_input_index"][0]
    assert entry["verification_status"] == "VERIFIED"
