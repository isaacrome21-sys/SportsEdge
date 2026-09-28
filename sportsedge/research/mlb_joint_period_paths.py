"""Research-only MLB period outcomes from the canonical joint-path state machine.

This module deliberately does not register period markets with production. It
replays the exact joint-path inning loop with the canonical path-set identity and
per-path seeds, records inning deltas, and then verifies every final score against
``simulate_mlb_joint_paths``. Any state-machine drift fails closed rather than
silently creating a second MLB probability engine.
"""
from __future__ import annotations

from hashlib import sha256
from math import isfinite
import random
from typing import Any

from sportsedge.dfs.mlb_joint_paths import (
    MlbGamePathInput,
    MlbJointPathError,
    _GameState,
    _HitterStats,
    _StarterState,
    _refresh_preserved_leads,
    _simulate_half_inning,
    simulate_mlb_joint_paths,
)
from sportsedge.source_lineage import canonical_json_sha256

PERIOD_RESEARCH_VERSION = "MLB_JOINT_PERIOD_RESEARCH_V1"
SUPPORTED_PERIOD_MARKETS = frozenset(
    {
        "NRFI",
        "YRFI",
        "F5_MONEYLINE",
        "F5_RUN_LINE",
        "F5_TOTALS",
        "FIRST_INNING_MONEYLINE",
        "FIRST_INNING_RUN_LINE",
        "FIRST_INNING_TOTALS",
        "INNING_MONEYLINE",
        "INNING_RUN_LINE",
        "INNING_TOTALS",
    }
)


class MlbPeriodResearchError(ValueError):
    pass


def _path_seed(path_set_id: str, path_index: int) -> int:
    return int.from_bytes(
        sha256(f"{path_set_id}:{path_index}".encode("utf-8")).digest()[:8],
        "big",
    )


def _simulate_period_final(game: MlbGamePathInput, *, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    state = _GameState()
    starters = {
        "AWAY": _StarterState(team=game.away.team, player_id=game.away.starter_player_id),
        "HOME": _StarterState(team=game.home.team, player_id=game.home.starter_player_id),
    }
    hitters = {
        hitter.player_id: _HitterStats()
        for hitter in game.away.lineup + game.home.lineup
    }
    inning_rows: list[dict[str, Any]] = []
    inning = 1
    while True:
        before_away, before_home = state.away_score, state.home_score
        _simulate_half_inning(
            game=game,
            game_state=state,
            starters=starters,
            hitters=hitters,
            offense_side="AWAY",
            inning=inning,
            rng=rng,
            walkoff_enabled=False,
        )
        top_away, top_home = state.away_score, state.home_score
        if inning >= 9 and state.home_score > state.away_score:
            inning_rows.append(
                {
                    "inning": inning,
                    "away_runs": top_away - before_away,
                    "home_runs": 0,
                    "bottom_played": False,
                }
            )
            break

        walkoff = _simulate_half_inning(
            game=game,
            game_state=state,
            starters=starters,
            hitters=hitters,
            offense_side="HOME",
            inning=inning,
            rng=rng,
            walkoff_enabled=inning >= 9,
        )
        inning_rows.append(
            {
                "inning": inning,
                "away_runs": top_away - before_away,
                "home_runs": state.home_score - top_home,
                "bottom_played": True,
            }
        )
        if walkoff:
            break
        if inning >= 9 and state.home_score != state.away_score:
            break
        inning += 1
        if inning > 30:
            raise MlbJointPathError("DFS_MLB_JOINT_GAME_NOT_TERMINATED_BY_30_INNINGS")

    _refresh_preserved_leads(state, starters)
    if sum(int(row["away_runs"]) for row in inning_rows) != state.away_score:
        raise MlbPeriodResearchError("MLB_PERIOD_AWAY_RUN_CONSERVATION_FAILED")
    if sum(int(row["home_runs"]) for row in inning_rows) != state.home_score:
        raise MlbPeriodResearchError("MLB_PERIOD_HOME_RUN_CONSERVATION_FAILED")
    return {
        "away_runs": state.away_score,
        "home_runs": state.home_score,
        "innings": inning,
        "inning_runs": inning_rows,
    }


def simulate_mlb_period_paths(
    game: MlbGamePathInput,
    *,
    path_count: int,
    seed: int,
) -> dict[str, Any]:
    """Record inning outcomes while proving parity with the canonical joint paths."""
    canonical = simulate_mlb_joint_paths(game, path_count=path_count, seed=seed)
    canonical_rows = canonical.snapshot.get("game_samples")
    if not isinstance(canonical_rows, list) or len(canonical_rows) != canonical.path_count:
        raise MlbPeriodResearchError("MLB_PERIOD_CANONICAL_GAME_SAMPLES_MISSING")

    samples: list[dict[str, Any]] = []
    for path_index, canonical_final in enumerate(canonical_rows):
        period_final = _simulate_period_final(
            game,
            seed=_path_seed(canonical.path_set_id, path_index),
        )
        expected = {
            "away_runs": int(canonical_final["away_runs"]),
            "home_runs": int(canonical_final["home_runs"]),
            "innings": int(canonical_final["innings"]),
        }
        actual = {key: int(period_final[key]) for key in expected}
        if actual != expected:
            raise MlbPeriodResearchError(
                f"MLB_PERIOD_CANONICAL_FINAL_MISMATCH:{path_index}:{actual}:{expected}"
            )
        samples.append(period_final)

    identity = {
        "version": PERIOD_RESEARCH_VERSION,
        "path_set_id": canonical.path_set_id,
        "path_count": canonical.path_count,
        "rules_mode": game.rules_mode,
        "samples": samples,
    }
    return {
        **identity,
        "period_result_sha256": canonical_json_sha256(identity),
        "validation_status": "UNVALIDATED_RESEARCH",
        "production_ready": False,
        "model_p_authority": False,
        "truth_gate_authority": False,
        "promotion_authority": False,
        "official_authority": False,
    }


def _finite_line(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
        raise MlbPeriodResearchError("MLB_PERIOD_LINE_INVALID")
    return float(value)


def _period_score(sample: dict[str, Any], market: str, inning: int | None) -> tuple[int, int]:
    rows = sample.get("inning_runs")
    if not isinstance(rows, list) or not rows:
        raise MlbPeriodResearchError("MLB_PERIOD_INNING_SAMPLES_MISSING")
    if market.startswith("F5_"):
        selected = [row for row in rows if 1 <= int(row.get("inning", 0)) <= 5]
        if len(selected) != 5:
            raise MlbPeriodResearchError("MLB_PERIOD_F5_INCOMPLETE")
    else:
        target = 1 if market.startswith("FIRST_INNING_") else inning
        if isinstance(target, bool) or not isinstance(target, int) or target < 1:
            raise MlbPeriodResearchError("MLB_PERIOD_INNING_REQUIRED")
        selected = [row for row in rows if int(row.get("inning", 0)) == target]
        if len(selected) != 1:
            raise MlbPeriodResearchError("MLB_PERIOD_INNING_NOT_PLAYED")
    return (
        sum(int(row["away_runs"]) for row in selected),
        sum(int(row["home_runs"]) for row in selected),
    )


def read_mlb_period_probability(
    result: dict[str, Any],
    *,
    market: str,
    side: str | None = None,
    line: float | None = None,
    inning: int | None = None,
) -> dict[str, Any]:
    market = str(market or "").upper()
    side = str(side or "").upper()
    if market not in SUPPORTED_PERIOD_MARKETS:
        raise MlbPeriodResearchError(f"MLB_PERIOD_MARKET_UNSUPPORTED:{market}")
    samples = result.get("samples")
    n = result.get("path_count")
    if isinstance(n, bool) or not isinstance(n, int) or n < 1 or not isinstance(samples, list) or len(samples) != n:
        raise MlbPeriodResearchError("MLB_PERIOD_RESULT_IDENTITY_INVALID")

    wins = pushes = 0
    resolved_line: float | None = None
    resolved_inning = inning
    if market in {"NRFI", "YRFI"}:
        if side:
            raise MlbPeriodResearchError("MLB_PERIOD_NRFI_YRFI_SIDE_NOT_USED")
        for sample in samples:
            away, home = _period_score(sample, "FIRST_INNING_TOTALS", 1)
            scored = away + home > 0
            wins += int(scored if market == "YRFI" else not scored)
        resolved_inning = 1
    else:
        if market.startswith("FIRST_INNING_"):
            resolved_inning = 1
        scores = [_period_score(sample, market, resolved_inning) for sample in samples]
        family = market.split("_", 1)[1] if market.startswith("F5_") else market.rsplit("_", 1)[-1]
        if market.startswith("FIRST_INNING_"):
            family = market.removeprefix("FIRST_INNING_")
        elif market.startswith("INNING_"):
            family = market.removeprefix("INNING_")

        if family == "MONEYLINE":
            if side not in {"HOME", "AWAY"}:
                raise MlbPeriodResearchError("MLB_PERIOD_MONEYLINE_SIDE_INVALID")
            for away, home in scores:
                wins += int(home > away if side == "HOME" else away > home)
                pushes += int(home == away)
        elif family == "RUN_LINE":
            if side not in {"HOME", "AWAY"}:
                raise MlbPeriodResearchError("MLB_PERIOD_RUN_LINE_SIDE_INVALID")
            resolved_line = _finite_line(line)
            for away, home in scores:
                margin = (home - away if side == "HOME" else away - home) + resolved_line
                wins += int(margin > 0)
                pushes += int(abs(margin) < 1e-12)
        elif family == "TOTALS":
            if side not in {"OVER", "UNDER"}:
                raise MlbPeriodResearchError("MLB_PERIOD_TOTAL_SIDE_INVALID")
            resolved_line = _finite_line(line)
            if resolved_line < 0:
                raise MlbPeriodResearchError("MLB_PERIOD_TOTAL_LINE_NEGATIVE")
            for away, home in scores:
                total = away + home
                wins += int(total > resolved_line if side == "OVER" else total < resolved_line)
                pushes += int(abs(total - resolved_line) < 1e-12)
        else:
            raise MlbPeriodResearchError(f"MLB_PERIOD_FAMILY_UNSUPPORTED:{family}")

    readout_identity = {
        "version": PERIOD_RESEARCH_VERSION,
        "period_result_sha256": result.get("period_result_sha256"),
        "market": market,
        "side": side or None,
        "line": resolved_line,
        "inning": resolved_inning,
        "wins": wins,
        "pushes": pushes,
        "path_count": n,
    }
    return {
        "market": market,
        "side": side or None,
        "line": resolved_line,
        "inning": resolved_inning,
        "research_p": wins / n,
        "push_p": pushes / n,
        "path_set_id": result.get("path_set_id"),
        "path_count": n,
        "period_result_sha256": result.get("period_result_sha256"),
        "readout_sha256": canonical_json_sha256(readout_identity),
        "validation_scope": "PERIOD_MARKET_RESEARCH_ONLY_NOT_VALIDATED",
        "validation_status": "UNVALIDATED_RESEARCH",
        "production_ready": False,
        "production_readiness": "NOT_ESTABLISHED",
        "model_p_authority": False,
        "truth_gate_authority": False,
        "promotion_authority": False,
        "official_authority": False,
        "label": "NOT Model_P · NOT Truth Gate · NOT OFFICIAL",
    }
