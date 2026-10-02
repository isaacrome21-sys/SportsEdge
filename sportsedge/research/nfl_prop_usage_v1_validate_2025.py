"""Frozen one-look 2025 validation for NFL prop usage V1.

The validator consumes the immutable 2021-2024 fit artifact plus the strict
pre-kick source audit. It never tunes parameters. Missing/ambiguous PIT
evidence produces zero model rows.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from math import erf, isfinite, sqrt
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

LOCK_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "research"
    / "nfl_prop_usage_v1_2025_validation_lock.json"
)

SCHEMA = "SPORTSEDGE_NFL_PROP_USAGE_V1_2025_VALIDATION"
FIT_SCHEMA = "SPORTSEDGE_NFL_PROP_USAGE_V1_FIT_ARTIFACT"
FIT_SHA = "ef38c7101da0977f27b71a7cbbe40321149ee2e0fda3bb8371f04d8423c9c555"
FIT_RAW_SHA = "a1fa75f449183120b3017924873e800502c0098b69fdcb6a98e943b704cab9ac"
SOURCE_AUDIT_SHA = "ee2de204bfb7e3ef1a5e5d054a448bc761e91acffa8717f252b635d585691560"
INACTIVE_AUDIT_SHA = "67c2b5e598dfa3dfe4ff0f0d1f9e312cf4a5facc34fb0306f242466deda93623"
TARGET_SEASON = 2025
SCRIPT_REF = 22.5

MARKET_SPECS = {
    "passing_yards": {
        "source_market": "player_pass_yds",
        "positions": ("QB",),
        "usage": "attempts",
        "yards": "passing_yards",
    },
    "rushing_yards": {
        "source_market": "player_rush_yds",
        "positions": ("QB", "RB", "FB", "WR"),
        "usage": "carries",
        "yards": "rushing_yards",
    },
    "receiving_yards": {
        "source_market": "player_reception_yds",
        "positions": ("RB", "FB", "WR", "TE"),
        "usage": "targets",
        "yards": "receiving_yards",
    },
}
SOURCE_TO_INTERNAL = {
    spec["source_market"]: market for market, spec in MARKET_SPECS.items()
}
TEAM_ALIASES = {
    "LAR": "LA", "STL": "LA", "WSH": "WAS", "OAK": "LV", "SD": "LAC",
}
DISPLAY_TEAM_ALIASES = {
    "LA": "LA", "LAR": "LA", "WSH": "WAS", "WAS": "WAS",
}


class NflPropUsageV1ValidationError(ValueError):
    pass


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def raw_sha256(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def load_lock(path: Path | None = None) -> dict[str, Any]:
    cfg = json.loads((path or LOCK_PATH).read_text())
    if cfg.get("schema") != "SPORTSEDGE_NFL_PROP_USAGE_V1_2025_VALIDATION_LOCK":
        raise NflPropUsageV1ValidationError("VALIDATION_LOCK_SCHEMA_INVALID")
    if cfg.get("status") != "FROZEN_BEFORE_2025_OUTCOME_ACCESS":
        raise NflPropUsageV1ValidationError("VALIDATION_LOCK_STATUS_INVALID")
    if cfg["fit_identity"]["fit_artifact_sha256"] != FIT_SHA:
        raise NflPropUsageV1ValidationError("FIT_IDENTITY_DRIFT")
    if cfg["fit_identity"]["fit_json_raw_sha256"] != FIT_RAW_SHA:
        raise NflPropUsageV1ValidationError("FIT_RAW_IDENTITY_DRIFT")
    if cfg["source_identity"]["source_audit_sha256"] != SOURCE_AUDIT_SHA:
        raise NflPropUsageV1ValidationError("SOURCE_AUDIT_IDENTITY_DRIFT")
    if cfg["source_identity"]["pre_kick_inactive_audit_sha256"] != INACTIVE_AUDIT_SHA:
        raise NflPropUsageV1ValidationError("INACTIVE_AUDIT_IDENTITY_DRIFT")
    if cfg["validation_window"]["status"] != "UNSPENT":
        raise NflPropUsageV1ValidationError("VALIDATION_WINDOW_NOT_UNSPENT")
    return cfg


def validate_bound_artifacts(
    *,
    fit_artifact: Mapping[str, Any],
    fit_raw: bytes,
    source_audit_raw: bytes,
    inactive_audit_raw: bytes,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if raw_sha256(fit_raw) != FIT_RAW_SHA:
        raise NflPropUsageV1ValidationError("FIT_JSON_RAW_SHA_MISMATCH")
    if raw_sha256(source_audit_raw) != SOURCE_AUDIT_SHA:
        raise NflPropUsageV1ValidationError("SOURCE_AUDIT_RAW_SHA_MISMATCH")
    if raw_sha256(inactive_audit_raw) != INACTIVE_AUDIT_SHA:
        raise NflPropUsageV1ValidationError("INACTIVE_AUDIT_RAW_SHA_MISMATCH")
    if fit_artifact.get("schema") != FIT_SCHEMA:
        raise NflPropUsageV1ValidationError("FIT_ARTIFACT_SCHEMA_INVALID")
    if fit_artifact.get("artifact_sha256") != FIT_SHA:
        raise NflPropUsageV1ValidationError("FIT_ARTIFACT_SHA_INVALID")
    body = dict(fit_artifact)
    body.pop("artifact_sha256", None)
    if canonical_sha256(body) != FIT_SHA:
        raise NflPropUsageV1ValidationError("FIT_ARTIFACT_CANONICAL_SHA_MISMATCH")
    if fit_artifact.get("validation_season_accessed") is not False:
        raise NflPropUsageV1ValidationError("FIT_ARTIFACT_ALREADY_ACCESSED_2025")

    source_audit = json.loads(source_audit_raw)
    inactive_audit = json.loads(inactive_audit_raw)
    if source_audit.get("status") != "SOURCE_AUDIT_ONLY_NO_2025_MODEL_SCORING":
        raise NflPropUsageV1ValidationError("SOURCE_AUDIT_STATUS_INVALID")
    if inactive_audit.get("status") != "SOURCE_AUDIT_ONLY_NO_2025_MODEL_SCORING":
        raise NflPropUsageV1ValidationError("INACTIVE_AUDIT_STATUS_INVALID")
    if int(inactive_audit.get("n_admissible_games") or 0) != 52:
        raise NflPropUsageV1ValidationError("INACTIVE_ADMITTED_GAME_COUNT_DRIFT")
    return source_audit, inactive_audit


def _team(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return TEAM_ALIASES.get(raw, raw)


def _name(value: Any) -> str:
    raw = str(value or "").lower()
    raw = raw.replace("’", "'").replace(".", "").replace("'", "")
    parts = [
        p for p in raw.replace("-", " ").split()
        if p not in {"jr", "sr", "ii", "iii", "iv"}
    ]
    return " ".join(parts)


def _num(value: Any, field: str, *, default: float | None = None) -> float:
    if value in (None, ""):
        if default is not None:
            return float(default)
        raise NflPropUsageV1ValidationError(f"{field}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NflPropUsageV1ValidationError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise NflPropUsageV1ValidationError(f"{field}:NONFINITE")
    return out


def _int(value: Any, field: str) -> int:
    out = _num(value, field)
    if out != int(out):
        raise NflPropUsageV1ValidationError(f"{field}:INTEGER_REQUIRED")
    return int(out)


def _weighted(values: Sequence[float], decay: float) -> float:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        raise NflPropUsageV1ValidationError("WEIGHTED_VALUES_EMPTY")
    weights = float(decay) ** np.arange(len(arr) - 1, -1, -1)
    return float(np.average(arr, weights=weights))


def normal_over_probability(mean: float, sd: float, line: float) -> float:
    if not isfinite(mean) or not isfinite(sd) or sd <= 0 or not isfinite(line):
        raise NflPropUsageV1ValidationError("NORMAL_PROBABILITY_INPUT_INVALID")
    z = (line - mean) / (sd * sqrt(2.0))
    p = 0.5 * (1.0 - erf(z))
    return min(1.0, max(0.0, float(p)))


def normalize_player_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in rows:
        try:
            season = _int(raw.get("season"), "player.season")
            week = _int(raw.get("week"), "player.week")
        except NflPropUsageV1ValidationError:
            continue
        if season != TARGET_SEASON or str(raw.get("season_type") or "").upper() != "REG":
            continue
        pid = str(raw.get("player_id") or raw.get("gsis_id") or "").strip()
        team = _team(raw.get("team") or raw.get("recent_team"))
        pos = str(raw.get("position") or "").strip().upper()
        if not pid or not team or not pos:
            continue
        out.append({
            "season": season,
            "week": week,
            "player_id": pid,
            "player": str(
                raw.get("player_display_name")
                or raw.get("player_name")
                or raw.get("player")
                or pid
            ).strip(),
            "team": team,
            "position": pos,
            "attempts": max(0.0, _num(raw.get("attempts"), "attempts", default=0.0)),
            "passing_yards": _num(raw.get("passing_yards"), "passing_yards", default=0.0),
            "carries": max(0.0, _num(raw.get("carries"), "carries", default=0.0)),
            "rushing_yards": _num(raw.get("rushing_yards"), "rushing_yards", default=0.0),
            "targets": max(0.0, _num(raw.get("targets"), "targets", default=0.0)),
            "receiving_yards": _num(raw.get("receiving_yards"), "receiving_yards", default=0.0),
        })
    return sorted(out, key=lambda r: (r["week"], r["player_id"], r["team"]))


def _runtime_target(runtime: Mapping[str, Any], target: str, features: Sequence[float]) -> float:
    spec = runtime["runtime"]["targets"][target]
    x = np.asarray(features, dtype=float)
    mean = np.asarray(spec["feature_mean"], dtype=float)
    std = np.asarray(spec["feature_std"], dtype=float)
    coef = np.asarray(spec["coefficients"], dtype=float)
    if not (x.shape == mean.shape == std.shape == coef.shape):
        raise NflPropUsageV1ValidationError("ATTEMPT9_RUNTIME_DIMENSION_INVALID")
    return float(((x - mean) / std) @ coef + float(spec["intercept"]))


def build_attempt9_team_environment_2025(
    games: Sequence[Mapping[str, Any]],
    runtime: Mapping[str, Any],
) -> dict[tuple[int, int, str], float]:
    normalized: list[dict[str, Any]] = []
    for raw in games:
        try:
            season = _int(raw.get("season"), "game.season")
            week = _int(raw.get("week"), "game.week")
        except NflPropUsageV1ValidationError:
            continue
        if str(raw.get("game_type") or "").upper() != "REG":
            continue
        home = _team(raw.get("home_team"))
        away = _team(raw.get("away_team"))
        if not home or not away:
            continue
        hs = raw.get("home_score")
        aw = raw.get("away_score")
        normalized.append({
            "season": season,
            "week": week,
            "date": str(raw.get("gameday") or ""),
            "id": str(raw.get("game_id") or f"{season}_{week}_{away}_{home}"),
            "home": home,
            "away": away,
            "hs": None if hs in (None, "") else _num(hs, "home_score"),
            "as": None if aw in (None, "") else _num(aw, "away_score"),
        })
    normalized.sort(key=lambda g: (g["date"], g["id"]))

    history: dict[str, list[tuple[float, float]]] = defaultdict(list)
    out: dict[tuple[int, int, str], float] = {}
    batch: list[dict[str, Any]] = []
    current_date: str | None = None

    def flush(rows: list[dict[str, Any]]) -> None:
        for game in rows:
            if (
                game["season"] == TARGET_SEASON
                and len(history[game["home"]]) >= 5
                and len(history[game["away"]]) >= 5
            ):
                hp = history[game["home"]][-10:]
                ap = history[game["away"]][-10:]
                hp_for = _weighted([x[0] for x in hp], 0.85)
                hp_against = _weighted([x[1] for x in hp], 0.85)
                ap_for = _weighted([x[0] for x in ap], 0.85)
                ap_against = _weighted([x[1] for x in ap], 0.85)
                features = [
                    hp_for, hp_against, ap_for, ap_against,
                    hp_for - hp_against, ap_for - ap_against,
                ]
                margin = _runtime_target(runtime, "margin", features)
                total = _runtime_target(runtime, "total", features)
                out[(TARGET_SEASON, int(game["week"]), game["home"])] = (total + margin) / 2.0
                out[(TARGET_SEASON, int(game["week"]), game["away"])] = (total - margin) / 2.0
        for game in rows:
            if game["hs"] is None or game["as"] is None:
                continue
            history[game["home"]].append((game["hs"], game["as"]))
            history[game["away"]].append((game["as"], game["hs"]))

    for game in normalized:
        if current_date is None:
            current_date = game["date"]
        if game["date"] != current_date:
            flush(batch)
            batch = []
            current_date = game["date"]
        batch.append(game)
    if batch:
        flush(batch)
    return out


def admitted_inactive_index(
    inactive_audit: Mapping[str, Any],
) -> dict[tuple[int, tuple[str, str]], dict[str, Any]]:
    out: dict[tuple[int, tuple[str, str]], dict[str, Any]] = {}
    for game in inactive_audit.get("admitted_games", []):
        if not game.get("admissible"):
            continue
        week = int(game["week"])
        teams = tuple(sorted(_team(row["team"]) for row in game.get("teams", [])))
        if len(teams) != 2:
            continue
        key = (week, teams)
        if key in out:
            raise NflPropUsageV1ValidationError(
                f"INACTIVE_GAME_IDENTITY_DUPLICATE:{week}:{teams}"
            )
        inactive = {
            _team(team): {_name(name) for name in names}
            for team, names in (game.get("inactive_by_team") or {}).items()
        }
        out[key] = {
            "kickoff_at": str(game["kickoff_at"]),
            "inactive": inactive,
            "source_url": game.get("source_url"),
        }
    if len(out) != 52:
        raise NflPropUsageV1ValidationError(
            f"INACTIVE_ADMITTED_INDEX_DRIFT:{len(out)}"
        )
    return out


def build_depth_snapshots(
    depth_rows: Sequence[Mapping[str, Any]],
    *,
    target_keys: Sequence[tuple[int, str, str]],
) -> dict[tuple[int, str, str], dict[str, Any]]:
    """Build latest pre-kick snapshot keyed by (week, team, kickoff_iso).

    target_keys contains only admitted prop game team identities.
    """
    parsed: list[dict[str, Any]] = []
    for raw in depth_rows:
        dt = raw.get("dt")
        team = _team(raw.get("team") or raw.get("club_code"))
        if dt in (None, "") or not team:
            continue
        parsed.append({
            "dt": str(dt),
            "team": team,
            "player_id": str(raw.get("gsis_id") or "").strip(),
            "position": str(raw.get("pos_abb") or raw.get("position") or "").strip().upper(),
            "pos_rank": raw.get("pos_rank"),
        })

    import pandas as pd
    if not parsed:
        raise NflPropUsageV1ValidationError("DEPTH_ROWS_EMPTY")
    df = pd.DataFrame(parsed)
    df["dt_parsed"] = pd.to_datetime(df["dt"], utc=True, errors="coerce")
    out: dict[tuple[int, str, str], dict[str, Any]] = {}
    for week, team, kickoff_iso in target_keys:
        kickoff = pd.to_datetime(kickoff_iso, utc=True, errors="raise")
        eligible = df[(df["team"] == team) & df["dt_parsed"].notna() & (df["dt_parsed"] <= kickoff)]
        if eligible.empty:
            continue
        latest = eligible["dt_parsed"].max()
        snap = eligible[eligible["dt_parsed"].eq(latest)].copy()
        player_ids = {str(x) for x in snap["player_id"] if str(x)}
        qb = snap[
            snap["position"].eq("QB")
            & pd.to_numeric(snap["pos_rank"], errors="coerce").eq(1)
        ]
        qb_ids = {str(x) for x in qb["player_id"] if str(x)}
        out[(week, team, kickoff_iso)] = {
            "snapshot_at": latest.isoformat(),
            "player_ids": player_ids,
            "rank1_qb_ids": qb_ids,
        }
    return out


def _projection(
    *,
    target: Mapping[str, Any],
    histories: Mapping[str, Sequence[Mapping[str, Any]]],
    market: str,
    fit_artifact: Mapping[str, Any],
    team_environment: Mapping[tuple[int, int, str], float],
) -> tuple[float, float, float]:
    spec = MARKET_SPECS[market]
    pos = str(target["position"])
    if pos not in spec["positions"]:
        raise NflPropUsageV1ValidationError("POSITION_NOT_SUPPORTED")
    fit = fit_artifact["markets"][market]
    params = fit["selected"]
    prior = fit["efficiency_prior_by_position"].get(pos)
    if prior is None:
        raise NflPropUsageV1ValidationError("EFFICIENCY_PRIOR_MISSING")
    hist = list(histories.get(str(target["player_id"]), []))
    hist = [row for row in hist if int(row["week"]) < int(target["week"])]
    if len(hist) < 3:
        raise NflPropUsageV1ValidationError("PRIOR_PLAYER_GAMES_INSUFFICIENT")
    sample = hist[-int(params["history_games"]):]
    decay = float(params["decay"])
    usage = _weighted([float(x[spec["usage"]]) for x in sample], decay)
    weights = decay ** np.arange(len(sample) - 1, -1, -1)
    opp = np.asarray([float(x[spec["usage"]]) for x in sample], dtype=float)
    yards = np.asarray([float(x[spec["yards"]]) for x in sample], dtype=float)
    weighted_opp = float(np.sum(weights * opp))
    weighted_yards = float(np.sum(weights * yards))
    prior_n = float(params["efficiency_prior_opportunities"])
    efficiency = (weighted_yards + prior_n * float(prior)) / (weighted_opp + prior_n)
    env_key = (TARGET_SEASON, int(target["week"]), str(target["team"]))
    if env_key not in team_environment:
        raise NflPropUsageV1ValidationError("ATTEMPT9_TEAM_ENVIRONMENT_MISSING")
    team_points = float(team_environment[env_key])
    if team_points <= 0:
        raise NflPropUsageV1ValidationError("ATTEMPT9_TEAM_POINTS_NONPOSITIVE")
    script = (team_points / SCRIPT_REF) ** float(params["script_gamma"])
    prediction = usage * efficiency * script
    sigma = float(
        fit["oof_residual_sigma_by_position"].get(
            pos, fit["oof_residual_sigma_pooled"]
        )
    )
    baseline = fit["baseline_actual_distribution_by_position"].get(pos)
    if not baseline:
        raise NflPropUsageV1ValidationError("BASELINE_DISTRIBUTION_MISSING")
    return float(prediction), sigma, float(baseline["mean"])


def evaluate_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "n": 0,
            "mean_predicted_over": None,
            "observed_over_rate": None,
            "calibration_gap": None,
            "candidate_brier": None,
            "baseline_brier": None,
        }
    p = np.asarray([float(r["candidate_p_over"]) for r in rows], dtype=float)
    b = np.asarray([float(r["baseline_p_over"]) for r in rows], dtype=float)
    y = np.asarray([float(r["observed_over"]) for r in rows], dtype=float)
    return {
        "n": len(rows),
        "mean_predicted_over": float(np.mean(p)),
        "observed_over_rate": float(np.mean(y)),
        "calibration_gap": float(abs(np.mean(p) - np.mean(y))),
        "candidate_brier": float(np.mean((p - y) ** 2)),
        "baseline_brier": float(np.mean((b - y) ** 2)),
    }


def validate_2025(
    *,
    fit_artifact: Mapping[str, Any],
    inactive_audit: Mapping[str, Any],
    prop_rows: Sequence[Mapping[str, Any]],
    depth_rows: Sequence[Mapping[str, Any]],
    player_rows: Sequence[Mapping[str, Any]],
    team_environment: Mapping[tuple[int, int, str], float],
    source_receipts: Mapping[str, Any],
) -> dict[str, Any]:
    import pandas as pd

    players = normalize_player_rows(player_rows)
    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    target_rows: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in players:
        by_player[row["player_id"]].append(row)
        target_rows[(row["week"], row["player_id"], row["team"])].append(row)

    inactive_index = admitted_inactive_index(inactive_audit)

    df = pd.DataFrame([dict(r) for r in prop_rows])
    if df.empty:
        raise NflPropUsageV1ValidationError("PROP_ROWS_EMPTY")
    required = {
        "season", "week", "event_id", "player_id", "player_name", "market",
        "line", "over_odds", "under_odds", "commence_time", "snapshot_time",
        "home_team", "away_team", "team", "position",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise NflPropUsageV1ValidationError(
            "PROP_COLUMNS_MISSING:" + ",".join(missing)
        )
    df = df[pd.to_numeric(df["season"], errors="coerce").eq(TARGET_SEASON)].copy()
    df["market"] = df["market"].astype("string").fillna("").str.lower().str.strip()
    df = df[df["market"].isin(SOURCE_TO_INTERNAL)].copy()
    book_col = "bookmaker" if "bookmaker" in df.columns else "book"
    df["book"] = df[book_col].astype("string").fillna("").str.lower().str.strip()
    df = df[df["book"].isin({"draftkings", "dk", "68"})].copy()
    df["snapshot_time"] = pd.to_datetime(df["snapshot_time"], utc=True, errors="coerce")
    df["commence_time"] = pd.to_datetime(df["commence_time"], utc=True, errors="coerce")
    df["lead_minutes"] = (
        df["commence_time"] - df["snapshot_time"]
    ).dt.total_seconds() / 60.0
    df = df[
        df["lead_minutes"].gt(0)
        & df["over_odds"].notna()
        & df["under_odds"].notna()
        & df["line"].notna()
    ].copy()
    identity = ["event_id", "player_id", "market", "book"]
    df = df.sort_values(identity + ["snapshot_time"]).drop_duplicates(identity, keep="last")
    df = df[df["lead_minutes"].le(15.0)].copy()
    if df.empty:
        raise NflPropUsageV1ValidationError("NO_PROP_ROWS_WITHIN_FROZEN_CLOSE_WINDOW")

    eligible_games: dict[tuple[int, tuple[str, str]], dict[str, Any]] = inactive_index
    target_depth_keys: set[tuple[int, str, str]] = set()
    game_for_index: dict[int, dict[str, Any]] = {}
    excluded: dict[str, int] = defaultdict(int)

    for idx, row in df.iterrows():
        week = int(row["week"])
        teams = tuple(sorted((_team(row["home_team"]), _team(row["away_team"]))))
        game = eligible_games.get((week, teams))
        if game is None:
            excluded["NO_STRICT_PREKICK_INACTIVE_GAME"] += 1
            continue
        kickoff_iso = pd.to_datetime(row["commence_time"], utc=True).isoformat()
        team = _team(row["team"])
        game_for_index[int(idx)] = {**game, "team": team, "kickoff_iso": kickoff_iso}
        target_depth_keys.add((week, team, kickoff_iso))

    depth_index = build_depth_snapshots(
        depth_rows, target_keys=sorted(target_depth_keys)
    )

    evaluation: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        meta = game_for_index.get(int(idx))
        if meta is None:
            continue
        week = int(row["week"])
        team = meta["team"]
        pid = str(row["player_id"] or "").strip()
        pname = str(row["player_name"] or "").strip()
        market = SOURCE_TO_INTERNAL[str(row["market"])]
        line = float(row["line"])
        if abs(line - round(line)) <= 1e-12:
            excluded["INTEGER_LINE_FAIL_CLOSED"] += 1
            continue
        if _name(pname) in meta["inactive"].get(team, set()):
            excluded["PLAYER_OFFICIALLY_INACTIVE"] += 1
            continue
        depth = depth_index.get((week, team, meta["kickoff_iso"]))
        if depth is None:
            excluded["PIT_DEPTH_SNAPSHOT_MISSING"] += 1
            continue
        pos = str(row["position"] or "").upper().strip()
        if pos == "QB":
            if len(depth["rank1_qb_ids"]) != 1 or pid not in depth["rank1_qb_ids"]:
                excluded["QB_NOT_UNIQUE_PIT_RANK1"] += 1
                continue
        elif pid not in depth["player_ids"]:
            excluded["SKILL_PLAYER_NOT_IN_PIT_DEPTH"] += 1
            continue

        actual_matches = target_rows.get((week, pid, team), [])
        if len(actual_matches) != 1:
            excluded["TARGET_PLAYER_STATS_NOT_UNIQUE"] += 1
            continue
        target = actual_matches[0]
        if target["position"] not in MARKET_SPECS[market]["positions"]:
            excluded["POSITION_NOT_SUPPORTED"] += 1
            continue
        try:
            prediction, sigma, baseline_mean = _projection(
                target=target,
                histories=by_player,
                market=market,
                fit_artifact=fit_artifact,
                team_environment=team_environment,
            )
        except NflPropUsageV1ValidationError as exc:
            excluded[str(exc)] += 1
            continue
        baseline_dist = fit_artifact["markets"][market][
            "baseline_actual_distribution_by_position"
        ][target["position"]]
        candidate_p = normal_over_probability(prediction, sigma, line)
        baseline_p = normal_over_probability(
            baseline_mean, float(baseline_dist["sd"]), line
        )
        actual = float(target[MARKET_SPECS[market]["yards"]])
        evaluation.append({
            "week": week,
            "event_id": str(row["event_id"]),
            "player_id": pid,
            "player": pname,
            "team": team,
            "position": target["position"],
            "market": market,
            "line": line,
            "prediction": prediction,
            "sigma": sigma,
            "candidate_p_over": candidate_p,
            "baseline_p_over": baseline_p,
            "actual": actual,
            "observed_over": 1 if actual > line else 0,
            "prop_snapshot_time": row["snapshot_time"].isoformat(),
            "kickoff_time": row["commence_time"].isoformat(),
            "inactive_source_url": meta.get("source_url"),
            "depth_snapshot_at": depth["snapshot_at"],
        })

    scopes: dict[str, Any] = {}
    for market in MARKET_SPECS:
        scopes[market] = evaluate_rows([r for r in evaluation if r["market"] == market])
    scopes["pooled"] = evaluate_rows(evaluation)

    calibration_gates = {
        scope: bool(scopes[scope]["n"] > 0 and scopes[scope]["calibration_gap"] <= 0.06)
        for scope in ("passing_yards", "rushing_yards", "receiving_yards", "pooled")
    }
    pooled = scopes["pooled"]
    brier_gate = bool(
        pooled["n"] > 0
        and pooled["candidate_brier"] <= pooled["baseline_brier"]
    )
    inactive_gate = excluded.get("MISSING_INACTIVE_EVIDENCE_EMITTED", 0) == 0
    passed = all(calibration_gates.values()) and brier_gate and inactive_gate

    artifact: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "VALIDATION_PASS" if passed else "VALIDATION_FAIL",
        "validation_window_spent": True,
        "validation_season": TARGET_SEASON,
        "fit_artifact_sha256": FIT_SHA,
        "source_audit_sha256": SOURCE_AUDIT_SHA,
        "inactive_audit_sha256": INACTIVE_AUDIT_SHA,
        "source_receipts": dict(source_receipts),
        "n_rows": len(evaluation),
        "n_by_market": {
            market: sum(r["market"] == market for r in evaluation)
            for market in MARKET_SPECS
        },
        "excluded_reason_counts": dict(sorted(excluded.items())),
        "metrics": scopes,
        "gates": {
            "calibration": calibration_gates,
            "pooled_brier_not_worse_than_baseline": brier_gate,
            "zero_rows_without_inactive_evidence": inactive_gate,
            "all_pass": passed,
        },
        "evaluation_rows": evaluation,
        "post_result_policy": {
            "v1_retune_allowed": False,
            "second_2025_look_allowed": False,
            "promotion_pr_allowed": passed,
        },
        "authority": {
            "research_only": True,
            "creates_model_p": False,
            "truth_gate": False,
            "official": False,
            "promotion": False,
            "staking": False,
            "backfill": False,
        },
    }
    artifact["artifact_sha256"] = canonical_sha256(artifact)
    return artifact


__all__ = [
    "FIT_RAW_SHA", "FIT_SHA", "INACTIVE_AUDIT_SHA", "MARKET_SPECS",
    "NflPropUsageV1ValidationError", "SOURCE_AUDIT_SHA",
    "admitted_inactive_index", "build_attempt9_team_environment_2025",
    "canonical_sha256", "evaluate_rows", "load_lock", "normal_over_probability",
    "normalize_player_rows", "raw_sha256", "validate_2025", "validate_bound_artifacts",
]
