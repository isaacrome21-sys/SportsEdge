"""PIT-safe historical materialization for the CFB joint score feature contract.

This module turns already-frozen historical game/metric/weather snapshots into the
same market-blind row shape consumed by ``CFB_JOINT_GAME_FEATURES_V1``. It does not
fetch data and it does not claim that an ex-post source was available historically;
source acquisition/provenance must establish that separately.

Week 2+ requires an exact current-season snapshot through ``game.week - 1``.
Week 1 requires an explicit immediately-prior-season fallback snapshot. Target-week,
post-kickoff metric snapshots, and weather without a pre-kickoff retrieval timestamp
fail closed. FBS membership is checked per season.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence

from .classification_policy import assert_fbs_only_games
from .source import CFBGame, CFBTeamMetrics

CFB_HISTORICAL_MATERIALIZER_VERSION = "CFB_JOINT_HISTORY_PIT_V2"

_BANNED_GAME_KEYS = {
    "spread", "spread_line", "total", "total_line", "line", "price", "american_odds",
    "decimal_odds", "implied_probability", "implied_prob", "market_probability",
    "novig_prob", "no_vig_prob", "book", "sportsbook", "closing_line", "closing_price",
    "home_moneyline", "away_moneyline", "odds",
}


class CFBHistoricalFeatureError(ValueError):
    pass


def _dt(value: Any, error: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise CFBHistoricalFeatureError(error)
        try:
            out = datetime.fromisoformat(text)
        except ValueError as exc:
            raise CFBHistoricalFeatureError(error) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBHistoricalFeatureError(error)
    return out.astimezone(timezone.utc)


def _score(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise CFBHistoricalFeatureError(f"CFB_HISTORICAL_SCORE_INVALID:{name}")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBHistoricalFeatureError(f"CFB_HISTORICAL_SCORE_INVALID:{name}") from exc
    if not isfinite(out) or out < 0:
        raise CFBHistoricalFeatureError(f"CFB_HISTORICAL_SCORE_INVALID:{name}")
    return out


def _assert_market_blind_game(row: Mapping[str, Any]) -> None:
    for key in row:
        name = str(key).strip().lower()
        if name in _BANNED_GAME_KEYS or "implied_prob" in name or "no_vig" in name or "novig" in name:
            raise CFBHistoricalFeatureError(f"CFB_HISTORICAL_MARKET_DATA_PROHIBITED:{key}")


def _game(row: Mapping[str, Any]) -> CFBGame:
    _assert_market_blind_game(row)
    try:
        season = int(row["season"]); week = int(row["week"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBHistoricalFeatureError("CFB_HISTORICAL_GAME_SEASON_WEEK_INVALID") from exc
    if week < 1:
        raise CFBHistoricalFeatureError("CFB_HISTORICAL_GAME_WEEK_INVALID")
    gid = str(row.get("game_id") or "").strip()
    home = str(row.get("home_team") or "").strip()
    away = str(row.get("away_team") or "").strip()
    if not gid or not home or not away:
        raise CFBHistoricalFeatureError("CFB_HISTORICAL_GAME_IDENTITY_MISSING")
    start = _dt(row.get("start_ts"), f"CFB_HISTORICAL_GAME_START_INVALID:{gid}")
    neutral = row.get("neutral_site", False)
    if type(neutral) is not bool:
        raise CFBHistoricalFeatureError("CFB_HISTORICAL_NEUTRAL_SITE_INVALID")
    return CFBGame(
        game_id=gid, season=season, week=week, start_ts=start.isoformat(),
        home_team=home, away_team=away, neutral_site=neutral,
        venue=str(row.get("venue") or "").strip() or None,
    )


def _metric_index(metrics: Iterable[CFBTeamMetrics]) -> dict[tuple[str, int, int, str], CFBTeamMetrics]:
    out: dict[tuple[str, int, int, str], CFBTeamMetrics] = {}
    for metric in metrics:
        if not isinstance(metric, CFBTeamMetrics):
            raise CFBHistoricalFeatureError("CFB_HISTORICAL_METRIC_OBJECT_INVALID")
        key=(metric.team, int(metric.season), int(metric.through_week), str(metric.sample_source).upper())
        if key in out:
            raise CFBHistoricalFeatureError(f"CFB_HISTORICAL_METRIC_DUPLICATE:{key}")
        out[key]=metric
    return out


def _select_metric(index: Mapping[tuple[str, int, int, str], CFBTeamMetrics], *, game: CFBGame, team: str) -> CFBTeamMetrics:
    if game.week == 1:
        candidates=[m for (t,s,_w,src),m in index.items() if t==team and s==game.season-1 and src=="PRIOR_SEASON_FALLBACK"]
        if len(candidates) != 1:
            raise CFBHistoricalFeatureError(f"CFB_HISTORICAL_WEEK1_FALLBACK_COUNT:{team}:{len(candidates)}")
        metric=candidates[0]
    else:
        key=(team, game.season, game.week-1, "CURRENT_SEASON_PRIOR_WEEKS")
        metric=index.get(key)
        if metric is None:
            raise CFBHistoricalFeatureError(f"CFB_HISTORICAL_PRIOR_WEEK_METRIC_MISSING:{team}:{game.season}:{game.week-1}")
    start=_dt(game.start_ts, f"CFB_HISTORICAL_GAME_START_INVALID:{game.game_id}")
    asof=_dt(metric.feature_asof_ts, f"CFB_HISTORICAL_FEATURE_ASOF_INVALID:{team}")
    if asof >= start:
        raise CFBHistoricalFeatureError(f"CFB_HISTORICAL_FEATURE_NOT_PREGAME:{team}")
    return metric


def _validate_weather(game: CFBGame, weather: Mapping[str, Any]) -> dict[str, Any]:
    clean = dict(weather)
    retrieved = _dt(clean.get("retrieved_at"), f"CFB_HISTORICAL_WEATHER_RETRIEVED_AT_INVALID:{game.game_id}")
    start = _dt(game.start_ts, f"CFB_HISTORICAL_GAME_START_INVALID:{game.game_id}")
    if retrieved >= start:
        raise CFBHistoricalFeatureError(f"CFB_HISTORICAL_WEATHER_NOT_PREGAME:{game.game_id}")
    clean["retrieved_at"] = retrieved.isoformat()
    return clean


def materialize_cfb_joint_history(
    *,
    games: Sequence[Mapping[str, Any]],
    metrics: Iterable[CFBTeamMetrics],
    weather_by_game: Mapping[str, Mapping[str, Any]],
    fbs_membership_by_season: Mapping[int, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Build deterministic market-blind training rows from frozen PIT snapshots."""
    index=_metric_index(metrics)
    output: list[dict[str, Any]]=[]
    parsed=[(_game(raw), raw) for raw in games]
    for game, raw in sorted(parsed, key=lambda x:(x[0].season,x[0].week,x[0].game_id)):
        membership=fbs_membership_by_season.get(game.season)
        if membership is None:
            raise CFBHistoricalFeatureError(f"CFB_HISTORICAL_FBS_MEMBERSHIP_MISSING:{game.season}")
        assert_fbs_only_games([game], fbs_team_rows=membership)
        weather=weather_by_game.get(game.game_id)
        if not isinstance(weather, Mapping):
            raise CFBHistoricalFeatureError(f"CFB_HISTORICAL_WEATHER_MISSING:{game.game_id}")
        weather = _validate_weather(game, weather)
        home=_select_metric(index, game=game, team=game.home_team)
        away=_select_metric(index, game=game, team=game.away_team)
        row={
            "game_id":game.game_id, "season":game.season, "week":game.week,
            "neutral_site":game.neutral_site, "home_metrics":home.to_dict(),
            "away_metrics":away.to_dict(), "weather":weather,
            "home_score":_score(raw.get("home_score"), "home_score"),
            "away_score":_score(raw.get("away_score"), "away_score"),
        }
        if "regulation_home_score" in raw or "regulation_away_score" in raw:
            if "regulation_home_score" not in raw or "regulation_away_score" not in raw:
                raise CFBHistoricalFeatureError("CFB_HISTORICAL_REGULATION_SCORE_PAIR_REQUIRED")
            row["regulation_home_score"]=_score(raw.get("regulation_home_score"), "regulation_home_score")
            row["regulation_away_score"]=_score(raw.get("regulation_away_score"), "regulation_away_score")
        output.append(row)
    if not output:
        raise CFBHistoricalFeatureError("CFB_HISTORICAL_MATERIALIZATION_EMPTY")
    return output
