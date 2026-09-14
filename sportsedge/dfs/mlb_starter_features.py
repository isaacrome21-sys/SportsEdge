from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

from ..mlb_f5_features import MLBF5HistorySource
from ..mlb_generic_features import MLBGenericHistorySource, _number, _outs_from_ip
from ..source_lineage import canonical_json_sha256

DFS_MLB_STARTER_FEATURE_VERSION = "dfs_mlb_starter_path_features_v2"
MIN_STARTS = 5
DEFAULT_START_WINDOW = 20
DEFAULT_CREDIT_WINDOW = 60


class MlbStarterFeatureError(ValueError):
    pass


def _integer_stat(
    stat: Mapping[str, Any],
    keys: Sequence[str],
    field: str,
    *,
    allow_missing: bool = False,
) -> int | None:
    for key in keys:
        if key not in stat or stat.get(key) is None:
            continue
        value = _number(stat.get(key), field)
        if value < 0 or value != int(value):
            raise MlbStarterFeatureError(f"{field} must be nonnegative integer")
        return int(value)
    if allow_missing:
        return None
    raise MlbStarterFeatureError(f"DFS_MLB_STARTER_STAT_MISSING:{field}")


def _date_text(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise MlbStarterFeatureError("DFS_MLB_STARTER_HISTORY_DATE_INVALID") from exc


def build_starter_path_features(
    source: MLBGenericHistorySource,
    *,
    f5_source: MLBF5HistorySource,
    pitcher_id: int,
    team_id: int,
    target_date: date,
    start_window: int = DEFAULT_START_WINDOW,
    credit_window: int = DEFAULT_CREDIT_WINDOW,
) -> dict[str, Any]:
    """Build strictly-prior workload/leash and team win-credit rows for DFS paths.

    Incomplete starts are skipped rather than imputed. A usable start must expose
    actual BF, pitch count, HBP, total runs and the starter's scored events.
    Win-credit rows are official inning-by-inning team score paths and never use
    historical pitcher wins.
    """

    if start_window < MIN_STARTS:
        raise MlbStarterFeatureError("DFS_MLB_STARTER_WINDOW_TOO_SMALL")
    if credit_window < 10:
        raise MlbStarterFeatureError("DFS_MLB_CREDIT_WINDOW_TOO_SMALL")

    pitching = source.player_rows(
        player_id=int(pitcher_id), group="pitching", target_date=target_date
    )
    starts = [
        row
        for row in pitching
        if _number(row["stat"].get("gamesStarted", 0), "gamesStarted") >= 1
    ][-start_window:]

    history: list[dict[str, Any]] = []
    incomplete = 0
    for row in starts:
        stat = row["stat"]
        try:
            outs = int(_outs_from_ip(stat.get("inningsPitched")))
            bf = _integer_stat(stat, ("battersFaced",), "battersFaced")
            pitches = _integer_stat(
                stat, ("numberOfPitches", "pitchesThrown"), "numberOfPitches"
            )
            hbp = _integer_stat(
                stat, ("hitByPitch", "hitBatsmen"), "hitByPitch"
            )
            strikeouts = _integer_stat(stat, ("strikeOuts",), "strikeOuts")
            earned_runs = _integer_stat(stat, ("earnedRuns",), "earnedRuns")
            runs = _integer_stat(stat, ("runs",), "runs")
            hits = _integer_stat(stat, ("hits",), "hits")
            walks = _integer_stat(stat, ("baseOnBalls",), "baseOnBalls")
            complete_games = _integer_stat(
                stat, ("completeGames",), "completeGames", allow_missing=True
            )
            shutouts = _integer_stat(
                stat, ("shutouts",), "shutouts", allow_missing=True
            )
        except (MlbStarterFeatureError, ValueError, TypeError):
            incomplete += 1
            continue

        assert bf is not None and pitches is not None and hbp is not None
        assert strikeouts is not None and earned_runs is not None and runs is not None
        assert hits is not None and walks is not None
        if not 0 <= outs <= 27 or bf <= 0 or pitches < bf:
            incomplete += 1
            continue
        if earned_runs > runs or strikeouts + hits + walks + hbp > bf:
            incomplete += 1
            continue

        complete_game = bool(complete_games) if complete_games is not None else outs >= 27
        cg_shutout = (
            bool(shutouts)
            if shutouts is not None
            else bool(complete_game and runs == 0)
        )
        no_hitter = bool(outs >= 27 and hits == 0)
        history.append(
            {
                "date": _date_text(row["date"]),
                "outs": outs,
                "strikeouts": strikeouts,
                "earned_runs": earned_runs,
                "runs_allowed": runs,
                "hits_allowed": hits,
                "walks_allowed": walks,
                "hbp_allowed": hbp,
                "starter_exit_batters_faced": bf,
                "starter_exit_pitch_count": pitches,
                "complete_game_probability": float(complete_game),
                "cg_shutout_probability": float(cg_shutout),
                "no_hitter_probability": float(no_hitter),
            }
        )

    if len(history) < MIN_STARTS:
        raise MlbStarterFeatureError(
            f"DFS_MLB_STARTER_HISTORY_INSUFFICIENT:{len(history)}<{MIN_STARTS}"
        )

    credit_rows = list(
        f5_source.win_credit_rows(team_id=int(team_id), target_date=target_date)
    )[-credit_window:]
    if len(credit_rows) < 10:
        raise MlbStarterFeatureError(
            f"DFS_MLB_CREDIT_HISTORY_INSUFFICIENT:{len(credit_rows)}<10"
        )

    normalized_credit: list[dict[str, Any]] = []
    for row in credit_rows:
        required = row.get("win_credit_required_outs")
        normalized_credit.append(
            {
                "game_pk": int(row["game_pk"]),
                "date": str(row["date"]),
                "f5_state": str(row["f5_state"]),
                "team_won": bool(row["team_won"]),
                "win_credit_required_outs": None if required is None else int(required),
            }
        )

    identity = {
        "feature_version": DFS_MLB_STARTER_FEATURE_VERSION,
        "pitcher_id": int(pitcher_id),
        "team_id": int(team_id),
        "target_date": target_date.isoformat(),
        "starter_history": history,
        "credit_history": normalized_credit,
        "source_retrieved_at": source.retrieved_at.isoformat(),
        "f5_retrieved_at": f5_source.retrieved_at.isoformat(),
    }
    return {
        "feature_version": DFS_MLB_STARTER_FEATURE_VERSION,
        "feature_source_hash": canonical_json_sha256(identity),
        "pitcher_id": int(pitcher_id),
        "team_id": int(team_id),
        "target_date": target_date.isoformat(),
        "starter_history": history,
        "credit_history": normalized_credit,
        "usable_starts": len(history),
        "incomplete_starts_skipped": incomplete,
    }
