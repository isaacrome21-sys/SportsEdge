"""Strictly-prior single-inning MLB research distribution (M22, N=2..8).

A standalone, intentionally unconnected research construction. Input rows
are individual *historical* completed fixtures with actual runs for both
halves of ONE inning. The engine enforces timestamps, identity, complete
halves and source hash shapes at this boundary. It cannot independently
authenticate externally supplied records: a separate signed source manifest
and date-by-date replay audit are still required before historic screening.

The ninth inning is NOT approximated: absent bottom-ninth/walkoffs imply
a score-conditioned missing-half problem and require a different prereg.
Cumulative RESULT_AFTER_INNING is a separate family, not this model.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
import re
from typing import Any, Mapping, Sequence

from .mlb_empirical_bayes import JEFFREYS_ALPHA, posterior_settlement_mass
from .source_lineage import canonical_json_sha256

VERSION = "mlb_m22_inning_joint_v1_empirical_opp_50_50"
READOUT_VERSION = "mlb_m22_inning_settlement_v1_jeffreys"
MIN_TEAM_HISTORY = 10
MIN_LEAGUE_HALVES = 200
PRIOR_STRENGTH = 30
SUPPORTED_INNINGS = frozenset(range(2, 9))
MARKET_RE = re.compile(r"^INNING_([2-9])_(RUNS|RUN_LINE|3_WAY)$")
HEX_SHA = re.compile(r"^[0-9a-fA-F]{64}$")


class InningJointError(ValueError):
    """Evidence refused / unsupported construction; never silently impute."""


@dataclass(frozen=True)
class InningJoint:
    innings: int
    as_of_utc: str
    target_game_pk: int
    away_team_id: int
    home_team_id: int
    joint_score_pmf: dict[str, float]
    away_history_games: int
    home_history_games: int
    league_history_halves: int
    evidence_sha256: str
    distribution_sha256: str
    version: str
    research_only: bool = True
    eligible: bool = False
    market_test: str = "NO_MARKET_TEST"


@dataclass(frozen=True)
class InningReadout:
    market: str
    innings: int
    selection: str
    line: float | None
    probability: float
    push_probability: float
    distribution_sha256: str
    readout_sha256: str
    readout_version: str = READOUT_VERSION
    status: str = "RESEARCH_ESTIMATE_UNVALIDATED"
    eligible: bool = False
    research_only: bool = True
    market_test: str = "NO_MARKET_TEST"
    play_authority: bool = False
    staking_authority: bool = False


def _utc(raw: Any, field: str) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise InningJointError(f"{field}: TIMESTAMP_REQUIRED")
    try:
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InningJointError(f"{field}: TIMESTAMP_INVALID") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise InningJointError(f"{field}: UTC_OFFSET_REQUIRED")
    return d.astimezone(timezone.utc)


def _positive(raw: Any, field: str) -> int:
    if isinstance(raw, bool):
        raise InningJointError(f"{field}: POSITIVE_INTEGER_REQUIRED")
    try:
        number = int(raw)
    except (TypeError, ValueError) as exc:
        raise InningJointError(f"{field}: POSITIVE_INTEGER_REQUIRED") from exc
    if not isinstance(raw, int) or number <= 0:
        raise InningJointError(f"{field}: POSITIVE_INTEGER_REQUIRED")
    return number


def _runs(raw: Any, field: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise InningJointError(f"{field}: NONNEGATIVE_INTEGER_REQUIRED")
    return raw


def _hash(raw: Any, field: str) -> str:
    if not isinstance(raw, str) or not HEX_SHA.fullmatch(raw):
        raise InningJointError(f"{field}: SHA256_REQUIRED")
    return raw.lower()


def _pmf(values: Sequence[int]) -> dict[int, float]:
    counts: dict[int, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    n = float(len(values))
    return {k: v / n for k, v in sorted(counts.items())}


def _blend(a: Mapping[int, float], b: Mapping[int, float]) -> dict[int, float]:
    return {k: 0.5 * (a.get(k, 0.0) + b.get(k, 0.0))
            for k in sorted(set(a) | set(b))}


def _smooth(values: Sequence[int], league: Mapping[int, float], strength: int
            ) -> dict[int, float]:
    empirical = _pmf(values)
    if strength == 0:
        return empirical
    n = len(values)
    return {k: (n * empirical.get(k, 0) + strength * league.get(k, 0)) /
            (n + strength) for k in sorted(set(league) | set(empirical))}


def build_inning_joint(target: Mapping[str, Any],
                       history: Sequence[Mapping[str, Any]],
                       *, innings: int, as_of_utc: str,
                       league_prior_strength: int = 0) -> InningJoint:
    """Build Nth-inning joint on a single pinned prior-evidence snapshot.

    Target: game_pk, away_team_id, home_team_id, scheduled_start_utc.
    Each history row: game_pk, away_team_id, home_team_id, inning,
    away_runs, home_runs, game_start_utc, completed_at_utc,
    observed_at_utc, official_innings, played_halves='BOTH',
    source_payload_sha256. All historical rows are for the one N,
    to prevent silent pooling or row selection after observing results.

    The caller must supply and independently attest source completeness.
    Hash-shaped fields alone are not an authenticity guarantee.
    """
    if type(innings) is not int or innings not in SUPPORTED_INNINGS:
        raise InningJointError("NINTH_OR_UNSUPPORTED_INNING_CONSTRUCTION_HELD")
    if league_prior_strength not in (0, PRIOR_STRENGTH):
        raise InningJointError("UNREGISTERED_PRIOR_STRENGTH")
    if not isinstance(target, Mapping):
        raise InningJointError("TARGET_IDENTITY_REQUIRED")
    target_pk = _positive(target.get("game_pk"), "target.game_pk")
    away_id = _positive(target.get("away_team_id"), "target.away_team_id")
    home_id = _positive(target.get("home_team_id"), "target.home_team_id")
    if away_id == home_id:
        raise InningJointError("TARGET_TEAM_IDENTITY_COLLISION")
    start = _utc(target.get("scheduled_start_utc"), "target.scheduled_start_utc")
    asof = _utc(as_of_utc, "as_of_utc")
    if asof >= start:
        raise InningJointError("AS_OF_NOT_STRICTLY_BEFORE_TARGET")
    if not isinstance(history, Sequence) or isinstance(history, (str, bytes)):
        raise InningJointError("HISTORY_ROWS_REQUIRED")
    all_rows = []
    seen = set()
    a_for, a_against, h_for, h_against, league_halves = [], [], [], [], []
    for i, raw in enumerate(history):
        if not isinstance(raw, Mapping):
            raise InningJointError(f"HISTORY_ROW_{i}_NOT_MAPPING")
        pk = _positive(raw.get("game_pk"), f"history[{i}].game_pk")
        if pk == target_pk or pk in seen:
            raise InningJointError("TARGET_LEAKAGE_OR_DUPLICATE_GAMEPK")
        seen.add(pk)
        away = _positive(raw.get("away_team_id"), f"history[{i}].away_team_id")
        home = _positive(raw.get("home_team_id"), f"history[{i}].home_team_id")
        if away == home:
            raise InningJointError("HISTORICAL_TEAM_COLLISION")
        if type(raw.get("inning")) is not int or raw["inning"] != innings:
            raise InningJointError("HISTORY_WRONG_INNING")
        away_runs = _runs(raw.get("away_runs"), f"history[{i}].away_runs")
        home_runs = _runs(raw.get("home_runs"), f"history[{i}].home_runs")
        official_innings = _positive(raw.get("official_innings"),
                                    f"history[{i}].official_innings")
        if official_innings < 9 or raw.get("played_halves") != "BOTH":
            raise InningJointError("INCOMPLETE_OFFICIAL_GAME_OR_INNING")
        game_start = _utc(raw.get("game_start_utc"), "history.game_start_utc")
        completed = _utc(raw.get("completed_at_utc"), "history.completed_at_utc")
        observed = _utc(raw.get("observed_at_utc"), "history.observed_at_utc")
        if not game_start < completed <= observed <= asof or observed >= start:
            raise InningJointError("PIT_OBSERVATION_TIME_VIOLATION")
        digest = _hash(raw.get("source_payload_sha256"),
                       f"history[{i}].source_payload_sha256")
        frozen = {
            "game_pk": pk, "away_team_id": away, "home_team_id": home,
            "inning": innings, "away_runs": away_runs, "home_runs": home_runs,
            "game_start_utc": game_start.isoformat(),
            "completed_at_utc": completed.isoformat(),
            "observed_at_utc": observed.isoformat(),
            "source_payload_sha256": digest,
        }
        all_rows.append(frozen)
        league_halves.extend([away_runs, home_runs])
        if away == away_id:
            a_for.append(away_runs)
            a_against.append(home_runs)
        elif home == away_id:
            a_for.append(home_runs)
            a_against.append(away_runs)
        if home == home_id:
            h_for.append(home_runs)
            h_against.append(away_runs)
        elif away == home_id:
            h_for.append(away_runs)
            h_against.append(home_runs)
    if min(len(a_for), len(h_for)) < MIN_TEAM_HISTORY:
        raise InningJointError("INSUFFICIENT_STRICTLY_PRIOR_TEAM_HISTORY")
    if league_prior_strength and len(league_halves) < MIN_LEAGUE_HALVES:
        raise InningJointError("INSUFFICIENT_STRICTLY_PRIOR_LEAGUE_HISTORY")
    league = _pmf(league_halves) if league_prior_strength else {}
    away_scored = _blend(
        _smooth(a_for, league, league_prior_strength),
        _smooth(h_against, league, league_prior_strength))
    home_scored = _blend(
        _smooth(h_for, league, league_prior_strength),
        _smooth(a_against, league, league_prior_strength))
    joint = {f"{a},{h}": ap * hp for a, ap in sorted(away_scored.items())
             for h, hp in sorted(home_scored.items())}
    if abs(sum(joint.values()) - 1.0) > 1e-12:
        raise InningJointError("INNING_JOINT_MASS_NOT_CONSERVED")
    history_hash = canonical_json_sha256(sorted(all_rows, key=lambda x: x["game_pk"]))
    evidence = {
        "version": VERSION,
        "as_of_utc": asof.isoformat(), "target_game_pk": target_pk,
        "target_start_utc": start.isoformat(),
        "away_team_id": away_id, "home_team_id": home_id,
        "inning": innings, "league_prior_strength": league_prior_strength,
        "history_sha256": history_hash,
        "away_history_games": len(a_for), "home_history_games": len(h_for),
        "league_history_halves": len(league_halves),
    }
    evidence_hash = canonical_json_sha256(evidence)
    return InningJoint(
        innings=innings, as_of_utc=asof.isoformat(), target_game_pk=target_pk,
        away_team_id=away_id, home_team_id=home_id, joint_score_pmf=joint,
        away_history_games=len(a_for), home_history_games=len(h_for),
        league_history_halves=len(league_halves),
        evidence_sha256=evidence_hash,
        distribution_sha256=canonical_json_sha256({
            "evidence_sha256": evidence_hash, "joint_score_pmf": joint,
            "version": VERSION}), version=VERSION)


def _states(distribution: InningJoint) -> list[tuple[int, int, float]]:
    if not isinstance(distribution, InningJoint):
        raise InningJointError("M22_INNING_JOINT_REQUIRED")
    total = 0.0
    states = []
    for key, raw in distribution.joint_score_pmf.items():
        try:
            a, h = key.split(",")
            a_n, h_n, p = int(a), int(h), float(raw)
        except (ValueError, TypeError, AttributeError) as exc:
            raise InningJointError("INVALID_INNING_JOINT_STATE") from exc
        if key != f"{a_n},{h_n}" or min(a_n, h_n) < 0 or (
                not isfinite(p)) or p < 0:
            raise InningJointError("INVALID_INNING_JOINT_STATE")
        total += p
        states.append((a_n, h_n, p))
    if not states or abs(total - 1.0) > 1e-12:
        raise InningJointError("INNING_JOINT_MASS_NOT_CONSERVED")
    return states


def _numeric_line(line: Any) -> float:
    if isinstance(line, bool):
        raise InningJointError("INVALID_INNING_NUMERIC_LINE")
    try:
        value = float(line)
    except (TypeError, ValueError) as exc:
        raise InningJointError("INVALID_INNING_NUMERIC_LINE") from exc
    if not isfinite(value):
        raise InningJointError("INVALID_INNING_NUMERIC_LINE")
    return value


def read_inning_probability(distribution: InningJoint, *, market: str,
                            selection: str, line: Any = None
                            ) -> InningReadout:
    """Standalone research settlement readout, never a pricing authority."""
    m = MARKET_RE.fullmatch(str(market or "").upper().strip())
    if m is None:
        raise InningJointError("UNRECOGNIZED_M22_INNING_MARKET")
    n, kind = int(m.group(1)), m.group(2)
    if n not in SUPPORTED_INNINGS:
        raise InningJointError("NINTH_INNING_CONSTRUCTION_HELD")
    if not isinstance(distribution, InningJoint) or distribution.innings != n:
        raise InningJointError("M22_INNING_DISTRIBUTION_IDENTITY_MISMATCH")
    states = _states(distribution)
    side = str(selection or "").upper().strip()
    effective_n = float(min(distribution.away_history_games,
                            distribution.home_history_games))
    if effective_n < MIN_TEAM_HISTORY:
        raise InningJointError("INSUFFICIENT_INNING_READOUT_HISTORY")
    if kind == "3_WAY":
        if side not in {"HOME", "AWAY", "TIE"} or line is not None:
            raise InningJointError("THREE_WAY_HOME_TIE_AWAY_NO_LINE")
        raw = {
            "HOME": sum(p for a, h, p in states if h > a),
            "AWAY": sum(p for a, h, p in states if a > h),
            "TIE": sum(p for a, h, p in states if a == h),
        }
        if abs(sum(raw.values()) - 1.0) > 1e-12:
            raise InningJointError("THREE_WAY_MASS_NOT_CONSERVED")
        alpha = {s: JEFFREYS_ALPHA + effective_n * v
                 for s, v in raw.items()}
        den = sum(alpha.values())
        probability = alpha[side] / den
        push = 0.0
        normalized_line = None
    elif kind == "RUNS":
        if side not in {"OVER", "UNDER"}:
            raise InningJointError("INNING_RUNS_OVER_UNDER_REQUIRED")
        normalized_line = _numeric_line(line)
        if normalized_line not in (0.5, 1.5):
            raise InningJointError("INNING_RUNS_CATALOG_LINE_ONLY")
        outcomes = [(a + h, p) for a, h, p in states]
        wins = sum(p for value, p in outcomes if value > normalized_line)
        losses = sum(p for value, p in outcomes if value < normalized_line)
        posterior = posterior_settlement_mass(
            over_mass=wins, under_mass=losses, push_mass=0.0,
            effective_n=effective_n, has_push=False)
        probability = posterior["p_over" if side == "OVER" else "p_under"]
        push = 0.0
    else:
        if side not in {"HOME", "AWAY"}:
            raise InningJointError("RUN_LINE_HOME_AWAY_SIDE_REQUIRED")
        normalized_line = _numeric_line(line)
        if not -20.0 <= normalized_line <= 20.0:
            raise InningJointError("RUN_LINE_IMPLAUSIBLE_LINE")
        margins = [((h - a) if side == "HOME" else (a - h)) +
                   normalized_line for a, h, _ in states]
        wins = sum(p for (_, _, p), x in zip(states, margins) if x > 0)
        pushes = sum(p for (_, _, p), x in zip(states, margins) if x == 0)
        losses = sum(p for (_, _, p), x in zip(states, margins) if x < 0)
        post = posterior_settlement_mass(
            over_mass=wins, under_mass=losses, push_mass=pushes,
            effective_n=effective_n, has_push=normalized_line.is_integer())
        probability, push = post["p_over"], post["p_push"]
    evidence = {
        "readout_version": READOUT_VERSION,
        "distribution_sha256": distribution.distribution_sha256,
        "market": m.group(0), "selection": side,
        "line": normalized_line, "probability": float(probability),
        "push_probability": float(push),
    }
    return InningReadout(
        market=m.group(0), innings=n, selection=side,
        line=normalized_line, probability=float(probability),
        push_probability=float(push),
        distribution_sha256=distribution.distribution_sha256,
        readout_sha256=canonical_json_sha256(evidence))
