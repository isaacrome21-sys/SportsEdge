"""Research-layer CFB QB passing-yard distribution (Form 2 identity-gated).

Sprint lane 3 (issue #2218 brief + Oct 14 player-prop plan): construct the
QB passing-yard distribution path UNDERNEATH the family registry block.
This module is a research object factory. It is not imported by the card
runner, it produces no prices, no EV, and no card rows, and the CFB family
registry refusal at the output boundary is unchanged by its existence.

WHAT IT CONSUMES (and nothing else):

  * An identity record in the exact shape of the Form 2 evaluator's
    success result (sportsedge.prepricing.qb_identity_evidence.
    evaluate_form2_bundle): identity is the gate, and it is checked
    FIRST. A distribution is built only for a QB whose identity limb is
    QB_IDENTITY_SATISFIED_FORM2_DEPTH_ROSTER_COMPOSITE, with the
    evaluator's resolved athlete ID and its availability label carried
    verbatim. Availability is NEVER upgraded by this module: the Form 2
    label AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT (or whatever
    explicit label the identity record carries) is copied onto the
    research object, and a record without an explicit availability
    label is refused -- an unlabeled distribution would read as an
    availability claim.

  * Prior-game records assembled from public PIT sources (ESPN gamelog
    stats decoded by sportsedge.football_gamelog_decode + the same
    games' boxscore team totals). Each record carries the game's
    kickoff, the QB's attempts/completions/passing yards, and his
    team's pass attempts and rush attempts in that game. Participation
    and snap data do not exist in a dated PIT form for CFB (see
    STARTER_CERTAINTY CFB_MEASURABILITY: no PIT chart archive exists),
    so the opportunity chain is built from what boxscores do record,
    and the QB's share of team pass attempts is measured from his own
    prior games rather than assumed to be 1.0. No input is silently
    substituted: a game whose team totals cannot be joined is excluded
    AND counted, with the reason recorded.

CONSTRUCTION (team plays -> QB attempts -> completions -> yards):

  Per prior game i, with all quantities measured, never assumed:
    plays_i        = team_pass_attempts_i + team_rush_attempts_i
    pass_share_i   = team_pass_attempts_i / plays_i
    qb_share_i     = qb_attempts_i / team_pass_attempts_i
    comp_rate_i    = qb_completions_i / qb_attempts_i
    yds_per_comp_i = qb_passing_yards_i / qb_completions_i
  A predictive path resamples one prior game uniformly (empirical
  bootstrap -- the within-game correlation of the chain components is
  preserved because the components are drawn jointly from one game),
  thins binomially down the chain, and sums per-completion yardage as
  Normal(comp * yds_per_comp_i, sqrt(comp) * ypc_sd) truncated at zero,
  where ypc_sd is the across-game standard deviation of yds_per_comp.
  There is no shrinkage and no league prior in v1; both absences are
  stated on the object.

STARTER CERTAINTY / AVAILABILITY:

  The headline distribution is CONDITIONAL on the identified QB
  starting with the role his PIT history shows. The Form 2 case maps
  to STARTER_CERTAINTY_V1 cell C10 (FORM2_IDENTITY): state PROJECTED,
  P(starts) = 0.90, provenance DECLARED (a frozen assumption, not a
  measurement -- CFB P(starts) is unmeasurable from the historical
  record on hand). The unconditional mixture over the replacement pool
  is NOT constructed: backup QBs do not carry the >=5-game PIT
  histories a replacement distribution would require, and inventing
  one would be a fabricated input. The object therefore reports
  mixture_status NOT_CONSTRUCTED_REPLACEMENT_POOL_UNKNOWN and carries
  p_starts (labeled DECLARED) as the future mixture layer's input.

PIT DISCIPLINE:

  A prior game dated at/after the fixture kickoff is a data
  impossibility and REFUSES the build. A game dated before kickoff
  but at/after ``as_of`` is not knowable at the as-of instant: it is
  excluded and counted, so a later-arriving game can never move an
  earlier as-of distribution.

The distribution object deliberately contains no pricing-shaped keys
(no probability/EV/fair-price fields under the registry gate's PRICING_KEYS
vocabulary): exceedance is reported as an empirical ``share`` of simulated
paths. If such an object were ever attached to a card payload, the family
gate would still refuse the family's rows on identity grounds alone;
the key hygiene is defense in depth, not the protection itself.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import numpy as np

from artifacts.free_models import IL_COLLEGE_NAMES, PublicContext
from sportsedge.prepricing.qb_identity_evidence import (
    STATUS_SATISFIED as FORM2_STATUS_SATISFIED,
)

SCHEMA = "SPORTSEDGE_CFB_QB_PASSING_DISTRIBUTION_RESEARCH_V1"
MIN_PRIOR_GAMES = 5
DEFAULT_PATHS = 20_000
DEFAULT_SEED = 20261014

# STARTER_CERTAINTY_V1, CFB decision table row C10 (FORM2_IDENTITY):
# state PROJECTED; P(starts) is a DECLARED prior (frozen constant,
# SPEC section 4 / config/research/starter_certainty_v1.json on the
# STARTER_CERTAINTY research branch). CFB P(starts) is UNMEASURABLE
# from the historical record on hand (CFB_MEASURABILITY.md) -- this
# value is an assumption wherever it appears, never a measurement.
STARTER_CERTAINTY_STATE_FORM2 = "PROJECTED"
STARTER_CERTAINTY_SUBCLASS_FORM2 = "FORM2_IDENTITY"
P_STARTS_FORM2_IDENTITY = 0.90
P_STARTS_PROVENANCE = "DECLARED"

_IDENTITY_FIELDS = ("team_id", "event_id", "resolved_athlete_id",
                    "resolved_athlete_name", "availability_status",
                    "kickoff_utc", "home_team_name", "away_team_name")
_GAME_FIELDS = ("game_date_utc", "qb_attempts", "qb_completions",
                "qb_passing_yards", "team_pass_attempts",
                "team_rush_attempts")


class QBDistributionError(ValueError):
    """Named fail-closed refusal for the research distribution build."""


def _clock(value, name):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise QBDistributionError(f"{name}_UNPARSEABLE") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QBDistributionError(f"{name}_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def _illinois_fixture(identity):
    for key in ("home_team_name", "away_team_name"):
        name = identity.get(key)
        if isinstance(name, str) and PublicContext.key(name) in IL_COLLEGE_NAMES:
            return True
    return False


def _check_identity(identity):
    if not isinstance(identity, Mapping):
        raise QBDistributionError("QB_DISTRIBUTION_IDENTITY_RECORD_REQUIRED")
    status = identity.get("status")
    if status != FORM2_STATUS_SATISFIED:
        raise QBDistributionError(
            f"QB_DISTRIBUTION_IDENTITY_NOT_SATISFIED:{status or 'ABSENT'}")
    for field in _IDENTITY_FIELDS:
        value = identity.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise QBDistributionError(
                f"QB_DISTRIBUTION_IDENTITY_FIELD_MISSING:{field}")
    if _illinois_fixture(identity):
        raise QBDistributionError("ILLINOIS_COLLEGE_EXCLUDED")
    return identity


def _validate_game(game, index):
    if not isinstance(game, Mapping):
        raise QBDistributionError(f"QB_DISTRIBUTION_PRIOR_GAME[{index}]_NOT_OBJECT")
    for field in _GAME_FIELDS:
        if game.get(field) is None:
            raise QBDistributionError(
                f"QB_DISTRIBUTION_PRIOR_GAME_FIELD_MISSING:{field}")
    out = {"game_date": _clock(game["game_date_utc"], "PRIOR_GAME_DATE")}
    for field in _GAME_FIELDS[1:]:
        try:
            value = float(game[field])
        except (TypeError, ValueError) as exc:
            raise QBDistributionError(
                f"QB_DISTRIBUTION_PRIOR_GAME_FIELD_INVALID:{field}") from exc
        if not math.isfinite(value) or value < 0:
            raise QBDistributionError(
                f"QB_DISTRIBUTION_PRIOR_GAME_FIELD_INVALID:{field}")
        out[field] = value
    return out


def build_qb_passing_distribution(*, identity_record: Mapping[str, Any],
                                  prior_games: Sequence[Mapping[str, Any]],
                                  as_of_utc: str,
                                  thresholds: Sequence[int] = (),
                                  paths: int = DEFAULT_PATHS,
                                  seed: int = DEFAULT_SEED) -> dict[str, Any]:
    """Build the research passing-yard distribution for one fixture QB.

    ``identity_record`` is the Form 2 evaluator's success result plus
    the fixture's team names and kickoff (see module docstring).
    ``prior_games`` are PIT prior-game records; see _GAME_FIELDS.
    Returns the research object described in the module docstring.
    Raises QBDistributionError (named, fail-closed) on any contract
    violation; nothing is built on partial identity or impossible PIT.
    """
    identity = _check_identity(identity_record)
    kickoff = _clock(identity["kickoff_utc"], "FIXTURE_KICKOFF")
    as_of = _clock(as_of_utc, "AS_OF")

    usable, excluded_post_asof, excluded_unusable = [], [], []
    for index, raw in enumerate(prior_games):
        game = _validate_game(raw, index)
        if game["game_date"] >= kickoff:
            raise QBDistributionError(
                "QB_DISTRIBUTION_PIT_VIOLATION_GAME_AT_OR_AFTER_KICKOFF:"
                f"{raw.get('event_id') or index}")
        if game["game_date"] >= as_of:
            excluded_post_asof.append({
                "event_id": raw.get("event_id"),
                "game_date_utc": raw.get("game_date_utc"),
                "reason": "GAME_NOT_KNOWABLE_AT_AS_OF"})
            continue
        team_pass = game["team_pass_attempts"]
        team_rush = game["team_rush_attempts"]
        plays = team_pass + team_rush
        if plays <= 0 or team_pass <= 0:
            excluded_unusable.append({
                "event_id": raw.get("event_id"),
                "game_date_utc": raw.get("game_date_utc"),
                "reason": "TEAM_OPPORTUNITY_TOTALS_UNUSABLE"})
            continue
        if game["qb_attempts"] > team_pass:
            excluded_unusable.append({
                "event_id": raw.get("event_id"),
                "game_date_utc": raw.get("game_date_utc"),
                "reason": "QB_ATTEMPTS_EXCEED_TEAM_PASS_ATTEMPTS"})
            continue
        usable.append((raw, game))
    if len(usable) < MIN_PRIOR_GAMES:
        raise QBDistributionError(
            f"QB_DISTRIBUTION_INSUFFICIENT_PIT_HISTORY:{len(usable)}")

    plays = np.array([g["team_pass_attempts"] + g["team_rush_attempts"]
                      for _, g in usable], dtype=float)
    pass_share = np.array([g["team_pass_attempts"] / (g["team_pass_attempts"]
                           + g["team_rush_attempts"]) for _, g in usable])
    qb_share = np.array([g["qb_attempts"] / g["team_pass_attempts"]
                         for _, g in usable])
    comp_rate = np.array([
        (g["qb_completions"] / g["qb_attempts"]) if g["qb_attempts"] > 0 else 0.0
        for _, g in usable])
    ypc = np.array([
        (g["qb_passing_yards"] / g["qb_completions"]) if g["qb_completions"] > 0
        else np.nan for _, g in usable])
    ypc_observed = ypc[~np.isnan(ypc)]
    ypc_sd = float(np.std(ypc_observed)) if len(ypc_observed) >= 2 else 0.0

    rng = np.random.default_rng(seed)
    n = len(usable)
    draw = rng.integers(0, n, size=paths)
    team_att = rng.binomial(plays[draw].astype(int), pass_share[draw])
    qb_att = rng.binomial(team_att, qb_share[draw])
    comp = rng.binomial(qb_att, comp_rate[draw])
    ypc_draw = np.where(np.isnan(ypc[draw]), 0.0, ypc[draw])
    mean_yds = comp * ypc_draw
    if ypc_sd > 0:
        yards = rng.normal(mean_yds, np.sqrt(np.maximum(comp, 0)) * ypc_sd)
    else:
        yards = mean_yds.astype(float)
    yards = np.maximum(np.round(yards), 0.0)

    quantiles = {f"p{int(q)}": float(np.percentile(yards, q))
                 for q in (5, 25, 50, 75, 95)}
    exceedance = []
    for threshold in sorted({int(t) for t in thresholds}):
        exceedance.append({
            "threshold_yards": threshold,
            "share_of_paths_at_or_above": float(np.mean(yards >= threshold)),
        })

    return {
        "schema": SCHEMA,
        "research_only": True,
        "official_authority": False,
        "model_p_authority": False,
        "staking_authority": False,
        "validation_status": "UNVALIDATED_RESEARCH_DISTRIBUTION",
        "market_status": "NOT_PRICED_FAMILY_REGISTRY_BLOCKED",
        "identity": {
            "team_id": str(identity["team_id"]),
            "event_id": str(identity["event_id"]),
            "athlete_id": str(identity["resolved_athlete_id"]),
            "athlete_name": identity["resolved_athlete_name"],
            "identity_status": identity["status"],
            "availability_status": identity["availability_status"],
            "injury_points": 0.0,
        },
        "starter_certainty": {
            "state": STARTER_CERTAINTY_STATE_FORM2,
            "subclass": STARTER_CERTAINTY_SUBCLASS_FORM2,
            "p_starts": P_STARTS_FORM2_IDENTITY,
            "p_starts_provenance": P_STARTS_PROVENANCE,
            "conditioning": "QB_STARTS_WITH_ROLE_AS_OBSERVED_IN_PIT_HISTORY",
            "mixture_status": "NOT_CONSTRUCTED_REPLACEMENT_POOL_UNKNOWN",
        },
        "inputs": {
            "as_of_utc": as_of.isoformat(),
            "kickoff_utc": kickoff.isoformat(),
            "prior_game_count": len(usable),
            "prior_games": [{
                "event_id": raw.get("event_id"),
                "game_date_utc": raw.get("game_date_utc"),
                "qb_team": raw.get("qb_team"),
                "qb_attempts": game["qb_attempts"],
                "qb_completions": game["qb_completions"],
                "qb_passing_yards": game["qb_passing_yards"],
                "team_pass_attempts": game["team_pass_attempts"],
                "team_rush_attempts": game["team_rush_attempts"],
            } for raw, game in usable],
            "excluded_post_asof_games": excluded_post_asof,
            "excluded_unusable_games": excluded_unusable,
        },
        "chain_means": {
            "team_plays": float(np.mean(plays)),
            "team_pass_attempts": float(np.mean(
                [g["team_pass_attempts"] for _, g in usable])),
            "pass_share": float(np.mean(pass_share)),
            "qb_attempt_share": float(np.mean(qb_share)),
            "qb_attempts": float(np.mean([g["qb_attempts"] for _, g in usable])),
            "completion_rate": float(np.mean(comp_rate)),
            "yards_per_completion": float(np.nanmean(ypc)),
            "yards_per_completion_sd_across_games": ypc_sd,
        },
        "distribution": {
            "paths": int(paths),
            "seed": int(seed),
            "mean_yards": float(np.mean(yards)),
            "sd_yards": float(np.std(yards)),
            "quantiles_yards": quantiles,
            "exceedance": exceedance,
            "construction": (
                "EMPIRICAL_BOOTSTRAP_OVER_PRIOR_GAMES; per path one prior "
                "game is resampled and the chain team plays -> team pass "
                "attempts -> QB attempts -> completions -> yards is "
                "thinned binomially with that game's measured shares; "
                "per-completion yardage is Normal around the game's "
                "measured yards/completion with the across-game sd. "
                "No shrinkage, no league prior (v1, stated)."),
        },
    }


__all__ = [
    "SCHEMA", "MIN_PRIOR_GAMES", "QBDistributionError",
    "build_qb_passing_distribution",
    "STARTER_CERTAINTY_STATE_FORM2", "STARTER_CERTAINTY_SUBCLASS_FORM2",
    "P_STARTS_FORM2_IDENTITY", "P_STARTS_PROVENANCE",
]
