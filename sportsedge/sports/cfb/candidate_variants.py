"""Prospectively frozen CFB candidate transforms. No fitting or scoring occurs here."""
from copy import deepcopy
from typing import Mapping, Any

RELIABILITY_SWITCH_MIN_GAMES = 3
PRIOR_BLEND_EQUIVALENT_GAMES = 4.0
GAMES_IN_SAMPLE_CAP = 12


def _snapshots(row: Mapping[str, Any], side: str, metric_keys) -> tuple[Mapping[str, Any], Mapping[str, Any], int]:
    season, week = int(row["season"]), int(row["week"])
    prior, current = row.get(f"{side}_prior_metrics"), row.get(f"{side}_current_metrics")
    if not isinstance(prior, Mapping) or not isinstance(current, Mapping):
        raise ValueError(f"CFB_CANDIDATE_DUAL_SNAPSHOT_REQUIRED:{side}")
    if any(k not in prior or k not in current for k in metric_keys):
        raise ValueError(f"CFB_CANDIDATE_DUAL_SNAPSHOT_METRICS_MISSING:{side}")
    if int(prior.get("season", -1)) != season - 1:
        raise ValueError(f"CFB_CANDIDATE_PRIOR_SNAPSHOT_INVALID:{side}")
    games = current.get("games_in_sample")
    if not isinstance(games, int) or games < 0:
        raise ValueError(f"CFB_CANDIDATE_GAMES_IN_SAMPLE_INVALID:{side}")

    # Week 1 has no current-season prior-week sample by construction.  The
    # deterministic history layer therefore aliases the current snapshot to the
    # immediately prior-season fallback with games_in_sample=0.  All three
    # non-baseline frozen formulas reduce to the prior snapshot at games=0.
    if week == 1:
        if games != 0:
            raise ValueError(f"CFB_CANDIDATE_WEEK1_GAMES_IN_SAMPLE_NONZERO:{side}")
        if (
            int(current.get("season", -1)) != season - 1
            or str(current.get("sample_source") or "").upper() != "PRIOR_SEASON_FALLBACK"
        ):
            raise ValueError(f"CFB_CANDIDATE_WEEK1_CURRENT_FALLBACK_INVALID:{side}")
    else:
        if (
            int(current.get("season", -1)) != season
            or int(current.get("through_week", -1)) != week - 1
            or str(current.get("sample_source") or "").upper() != "CURRENT_SEASON_PRIOR_WEEKS"
        ):
            raise ValueError(f"CFB_CANDIDATE_CURRENT_SNAPSHOT_INVALID:{side}")
    return prior, current, games


def reliability_hard_switch(row, metric_keys):
    out = deepcopy(dict(row))
    for side in ("home", "away"):
        prior, current, games = _snapshots(row, side, metric_keys)
        out[f"{side}_metrics"] = deepcopy(dict(current if games >= RELIABILITY_SWITCH_MIN_GAMES else prior))
    return out


def prior_current_blend(row, metric_keys):
    out = deepcopy(dict(row))
    for side in ("home", "away"):
        prior, current, games = _snapshots(row, side, metric_keys)
        w = games / (games + PRIOR_BLEND_EQUIVALENT_GAMES)
        m = {k: w * float(current[k]) + (1.0 - w) * float(prior[k]) for k in metric_keys}
        m.update(season=int(row["season"]), through_week=max(0, int(row["week"])-1), sample_source="PRIOR_CURRENT_BLEND", games_in_sample=games)
        out[f"{side}_metrics"] = m
        out[f"{side}_current_weight"] = w
    return out


def games_in_sample_feature(row, metric_keys):
    out = deepcopy(dict(row))
    for side in ("home", "away"):
        prior, current, games = _snapshots(row, side, metric_keys)
        out[f"{side}_metrics"] = deepcopy(dict(current if games > 0 else prior))
        out[f"{side}_games_in_sample_feature"] = min(games, GAMES_IN_SAMPLE_CAP) / GAMES_IN_SAMPLE_CAP
    return out
