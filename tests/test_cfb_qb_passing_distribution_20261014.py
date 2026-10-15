"""CFB QB passing-yard research distribution (sprint lane 3, Oct 14 2026).

Covers: Form 2 identity-gate precedence, registry refusal intactness,
PIT discipline (a later game never moves an earlier as-of distribution),
Illinois exclusion, and construction sanity. Synthetic fixtures only --
no network, no card surfaces.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.research.cfb_qb_passing_distribution import (  # noqa: E402
    QBDistributionError,
    build_qb_passing_distribution,
)
from sportsedge.prepricing.qb_identity_evidence import (  # noqa: E402
    AVAILABILITY_UNVERIFIED,
    STATUS_SATISFIED,
)
from sportsedge.registry_gate import PRICING_KEYS, family_gate_row  # noqa: E402

KICKOFF = "2026-10-14T23:30:00+00:00"
AS_OF = "2026-10-14T20:00:00+00:00"


def _identity(**overrides):
    record = {
        "status": STATUS_SATISFIED,
        "team_id": "338",
        "event_id": "401871054",
        "resolved_athlete_id": "4870645",
        "resolved_athlete_name": "Rickie Collins",
        "availability_status": AVAILABILITY_UNVERIFIED,
        "kickoff_utc": KICKOFF,
        "home_team_name": "Missouri State Bears",
        "away_team_name": "Kennesaw State Owls",
    }
    record.update(overrides)
    return record


def _game(date, *, att=30, comp=18, yds=200, team_pa=32, team_ra=30,
          event_id=None):
    return {
        "event_id": event_id or f"E-{date}",
        "game_date_utc": date,
        "qb_team": "Kennesaw State Owls",
        "qb_attempts": att, "qb_completions": comp, "qb_passing_yards": yds,
        "team_pass_attempts": team_pa, "team_rush_attempts": team_ra,
    }


def _games(n=6):
    dates = ["2026-09-03T23:00:00+00:00", "2026-09-12T23:00:00+00:00",
             "2026-09-19T23:45:00+00:00", "2026-09-26T23:00:00+00:00",
             "2026-10-03T23:00:00+00:00", "2026-10-07T23:00:00+00:00"]
    return [_game(d, att=28 + i, comp=17 + i, yds=180 + 15 * i,
                  team_pa=30 + i, team_ra=28 + i, event_id=f"E{i}")
            for i, d in enumerate(dates[:n])]


def _build(**kw):
    args = {"identity_record": _identity(), "prior_games": _games(),
            "as_of_utc": AS_OF, "thresholds": (150, 250)}
    args.update(kw)
    return build_qb_passing_distribution(**args)


# ---------------------------------------------------------------------
# Identity gate precedence
# ---------------------------------------------------------------------

def test_identity_not_satisfied_refuses():
    with pytest.raises(QBDistributionError, match="IDENTITY_NOT_SATISFIED"):
        _build(identity_record=_identity(status="QB_DEPTH_EVIDENCE_MISSING"))


def test_identity_missing_athlete_refuses():
    with pytest.raises(QBDistributionError, match="FIELD_MISSING:resolved_athlete_id"):
        _build(identity_record=_identity(resolved_athlete_id=""))


def test_identity_missing_availability_label_refuses():
    with pytest.raises(QBDistributionError, match="FIELD_MISSING:availability_status"):
        _build(identity_record=_identity(availability_status=None))


def test_identity_gate_precedes_pit_and_history():
    # Even with a PIT-violating game AND too little history, the identity
    # refusal is the one raised: identity is checked first, always.
    bad_games = [_game("2026-10-15T23:30:00+00:00")]
    with pytest.raises(QBDistributionError, match="IDENTITY_NOT_SATISFIED"):
        _build(identity_record=_identity(status="QB_DEPTH_QB1_NOT_ON_ROSTER"),
               prior_games=bad_games)


def test_illinois_fixture_refused():
    with pytest.raises(QBDistributionError, match="ILLINOIS_COLLEGE_EXCLUDED"):
        _build(identity_record=_identity(home_team_name="Illinois Fighting Illini"))


# ---------------------------------------------------------------------
# PIT discipline
# ---------------------------------------------------------------------

def test_future_game_does_not_move_earlier_distribution():
    base = _build()
    later = _game("2026-10-14T21:30:00+00:00", att=45, comp=30, yds=410,
                  team_pa=46, team_ra=20, event_id="LATE")
    moved = _build(prior_games=_games() + [later])
    assert moved["inputs"]["excluded_post_asof_games"][0]["event_id"] == "LATE"
    assert moved["distribution"] == base["distribution"]
    assert moved["chain_means"] == base["chain_means"]
    assert moved["inputs"]["prior_game_count"] == base["inputs"]["prior_game_count"]


def test_game_at_or_after_kickoff_refuses():
    bad = _game("2026-10-14T23:30:00+00:00", event_id="AT_KICKOFF")
    with pytest.raises(QBDistributionError, match="PIT_VIOLATION_GAME_AT_OR_AFTER_KICKOFF"):
        _build(prior_games=_games() + [bad])


def test_insufficient_history_refuses():
    with pytest.raises(QBDistributionError, match="INSUFFICIENT_PIT_HISTORY:4"):
        _build(prior_games=_games(4))


def test_qb_attempts_above_team_excluded_and_counted():
    bad = _game("2026-08-29T23:00:00+00:00", att=40, team_pa=35,
                event_id="IMPOSSIBLE")
    obj = _build(prior_games=_games() + [bad])
    assert obj["inputs"]["prior_game_count"] == 6
    reasons = [g["reason"] for g in obj["inputs"]["excluded_unusable_games"]]
    assert reasons == ["QB_ATTEMPTS_EXCEED_TEAM_PASS_ATTEMPTS"]


# ---------------------------------------------------------------------
# Construction + labeling
# ---------------------------------------------------------------------

def test_degenerate_chain_concentrates():
    games = [_game(f"2026-09-{d:02d}T23:00:00+00:00", att=30, comp=30,
                   yds=300, team_pa=30, team_ra=0, event_id=f"D{i}")
             for i, d in enumerate((3, 10, 17, 24, 26, 30))]
    obj = _build(prior_games=games, thresholds=(300, 301))
    assert obj["distribution"]["mean_yards"] == 300.0
    shares = {e["threshold_yards"]: e["share_of_paths_at_or_above"]
              for e in obj["distribution"]["exceedance"]}
    assert shares[300] == 1.0 and shares[301] == 0.0


def test_deterministic_under_seed():
    assert _build()["distribution"] == _build()["distribution"]


def test_object_labels_availability_and_certainty():
    obj = _build()
    assert obj["identity"]["availability_status"] == AVAILABILITY_UNVERIFIED
    assert obj["identity"]["injury_points"] == 0.0
    cert = obj["starter_certainty"]
    assert cert["state"] == "PROJECTED" and cert["subclass"] == "FORM2_IDENTITY"
    assert cert["p_starts"] == 0.90 and cert["p_starts_provenance"] == "DECLARED"
    assert cert["mixture_status"] == "NOT_CONSTRUCTED_REPLACEMENT_POOL_UNKNOWN"
    assert obj["research_only"] is True
    assert obj["validation_status"] == "UNVALIDATED_RESEARCH_DISTRIBUTION"


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


def test_object_carries_no_pricing_keys():
    obj = _build()
    leaked = set(_walk_keys(obj)) & set(PRICING_KEYS)
    assert leaked == set(), f"pricing-shaped keys on research object: {leaked}"


# ---------------------------------------------------------------------
# Registry refusal intact (the boundary this research lives beneath)
# ---------------------------------------------------------------------

def test_family_gate_refuses_cfb_passing_yards():
    row = {"market": "PLAYER_PASSING_YARDS", "side": "OVER",
           "player_name": "Rickie Collins",
           "away": "Kennesaw State", "home": "Missouri State"}
    gated = family_gate_row("CFB", "PLAYER_PASSING_YARDS", row)
    assert gated is not None
    assert gated["status"] == "NO_MODEL_OR_MARKET"
    assert gated["registry_enforced"] is True
    assert gated["family_decision"]["state"] == "BLOCKED"
    assert not any(gated.get(k) is not None for k in PRICING_KEYS)


def test_runner_does_not_import_research_module():
    runner = (Path(__file__).resolve().parents[1]
              / "artifacts" / "run_it_full.py").read_text(encoding="utf-8")
    assert "cfb_qb_passing_distribution" not in runner
