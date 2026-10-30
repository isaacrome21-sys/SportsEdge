"""Reconstructed-historical materialization for frozen CFB candidate selection.

This module is intentionally separate from ``historical_features``.  The latter is
promotion/PIT machinery and requires evidence that each snapshot existed before an
old kickoff.  Reconstructed selection is allowed by the frozen selection policy to
use current-provider historical reconstructions, but those rows MUST NOT be called
PIT evidence.

No network access, model fitting, candidate evaluation, Model_P, Truth Gate,
promotion, eligibility, staking, OFFICIAL, evidence-clock, or backfill authority is
created here.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence

from .candidate_history import enrich_candidate_history
from .classification_policy import assert_fbs_only_games
from .source import CFBGame, CFBTeamMetrics

CFB_RECONSTRUCTED_SELECTION_MATERIALIZER_VERSION = "CFB_RECONSTRUCTED_SELECTION_V1"
RECONSTRUCTED_PROVENANCE = "RECONSTRUCTED_HISTORICAL_NOT_PIT"
WEATHER_MISSING_SOURCE = "WEATHER_MISSING"

_BANNED_GAME_KEYS = {
    "spread", "spread_line", "total", "total_line", "line", "price",
    "american_odds", "decimal_odds", "implied_probability", "implied_prob",
    "market_probability", "novig_prob", "no_vig_prob", "book", "sportsbook",
    "closing_line", "closing_price", "home_moneyline", "away_moneyline", "odds",
}


class CFBReconstructedSelectionError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _dt(value: object, error: str) -> str:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise CFBReconstructedSelectionError(error)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBReconstructedSelectionError(error) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CFBReconstructedSelectionError(error)
    return parsed.isoformat()


def _score(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise CFBReconstructedSelectionError(f"CFB_RECONSTRUCTED_SCORE_INVALID:{name}")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBReconstructedSelectionError(
            f"CFB_RECONSTRUCTED_SCORE_INVALID:{name}"
        ) from exc
    if not isfinite(out) or out < 0:
        raise CFBReconstructedSelectionError(f"CFB_RECONSTRUCTED_SCORE_INVALID:{name}")
    return out


def _assert_market_blind(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key).strip().lower()
            if (
                name in _BANNED_GAME_KEYS
                or "implied_prob" in name
                or "no_vig" in name
                or "novig" in name
            ):
                raise CFBReconstructedSelectionError(
                    f"CFB_RECONSTRUCTED_MARKET_DATA_PROHIBITED:{path}.{key}"
                )
            _assert_market_blind(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_market_blind(child, f"{path}[{index}]")


def _game(raw: Mapping[str, Any]) -> CFBGame:
    _assert_market_blind(raw, "game")
    try:
        season = int(raw["season"])
        week = int(raw["week"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBReconstructedSelectionError(
            "CFB_RECONSTRUCTED_GAME_SEASON_WEEK_INVALID"
        ) from exc
    if not 2015 <= season <= 2025 or week < 1:
        raise CFBReconstructedSelectionError(
            "CFB_RECONSTRUCTED_GAME_OUTSIDE_FROZEN_WINDOW"
        )
    gid = str(raw.get("game_id") or "").strip()
    home = str(raw.get("home_team") or "").strip()
    away = str(raw.get("away_team") or "").strip()
    if not gid or not home or not away:
        raise CFBReconstructedSelectionError("CFB_RECONSTRUCTED_GAME_IDENTITY_MISSING")
    neutral = raw.get("neutral_site", False)
    if type(neutral) is not bool:
        raise CFBReconstructedSelectionError("CFB_RECONSTRUCTED_NEUTRAL_SITE_INVALID")
    return CFBGame(
        game_id=gid,
        season=season,
        week=week,
        start_ts=_dt(raw.get("start_ts"), f"CFB_RECONSTRUCTED_START_INVALID:{gid}"),
        home_team=home,
        away_team=away,
        neutral_site=neutral,
        venue=str(raw.get("venue") or "").strip() or None,
    )


def _metric_index(
    metrics: Iterable[CFBTeamMetrics],
) -> dict[tuple[str, int, int, str], CFBTeamMetrics]:
    out: dict[tuple[str, int, int, str], CFBTeamMetrics] = {}
    for metric in metrics:
        if not isinstance(metric, CFBTeamMetrics):
            raise CFBReconstructedSelectionError("CFB_RECONSTRUCTED_METRIC_OBJECT_INVALID")
        key = (
            str(metric.team),
            int(metric.season),
            int(metric.through_week),
            str(metric.sample_source).upper(),
        )
        if key in out:
            raise CFBReconstructedSelectionError(
                f"CFB_RECONSTRUCTED_METRIC_DUPLICATE:{key}"
            )
        out[key] = metric
    if not out:
        raise CFBReconstructedSelectionError("CFB_RECONSTRUCTED_METRICS_EMPTY")
    return out


def _prior_metric(
    index: Mapping[tuple[str, int, int, str], CFBTeamMetrics],
    *,
    team: str,
    season: int,
) -> CFBTeamMetrics:
    rows = [
        metric
        for (name, metric_season, _week, source), metric in index.items()
        if name == team
        and metric_season == season - 1
        and source == "PRIOR_SEASON_FALLBACK"
    ]
    if len(rows) != 1:
        raise CFBReconstructedSelectionError(
            f"CFB_RECONSTRUCTED_PRIOR_COUNT:{team}:{season}:{len(rows)}"
        )
    return rows[0]


def _current_metric(
    index: Mapping[tuple[str, int, int, str], CFBTeamMetrics],
    *,
    team: str,
    season: int,
    week: int,
) -> CFBTeamMetrics:
    metric = index.get((team, season, week - 1, "CURRENT_SEASON_PRIOR_WEEKS"))
    if metric is None:
        raise CFBReconstructedSelectionError(
            f"CFB_RECONSTRUCTED_CURRENT_MISSING:{team}:{season}:{week-1}"
        )
    return metric


def _weather(game: CFBGame, raw: Mapping[str, Any]) -> dict[str, Any]:
    _assert_market_blind(raw, f"weather:{game.game_id}")
    source = str(raw.get("source") or "").strip()
    if not source:
        raise CFBReconstructedSelectionError(
            f"CFB_RECONSTRUCTED_WEATHER_SOURCE_MISSING:{game.game_id}"
        )
    retrieved = _dt(
        raw.get("retrieved_at_utc"),
        f"CFB_RECONSTRUCTED_WEATHER_RETRIEVAL_INVALID:{game.game_id}",
    )
    out = deepcopy(dict(raw))
    out["source"] = source
    out["retrieved_at_utc"] = retrieved
    out["provenance_class"] = RECONSTRUCTED_PROVENANCE

    # Explicit null-weather path: never coerce None → 0 / 70 / False.
    if source == WEATHER_MISSING_SOURCE or raw.get("weather_missing") is True:
        out["weather_missing"] = True
        out["weather_status"] = WEATHER_MISSING_SOURCE
        out["gameIndoors"] = None
        out["windSpeed"] = None
        out["temperature"] = None
        return out

    indoors = raw.get("game_indoor", raw.get("gameIndoors"))
    if type(indoors) is not bool:
        raise CFBReconstructedSelectionError(
            f"CFB_RECONSTRUCTED_WEATHER_INDOOR_INVALID:{game.game_id}"
        )
    out["weather_missing"] = False
    # Deliberately DO NOT compare retrieval time to an old kickoff.  Doing so would
    # either reject all current-provider reconstructions or tempt a false PIT claim.
    return out


def materialize_reconstructed_selection_rows(
    *,
    games: Sequence[Mapping[str, Any]],
    metrics: Iterable[CFBTeamMetrics],
    weather_by_game: Mapping[str, Mapping[str, Any]],
    fbs_membership_by_season: Mapping[int, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Build frozen-selection rows without asserting historical PIT availability."""
    if not games:
        raise CFBReconstructedSelectionError("CFB_RECONSTRUCTED_GAMES_EMPTY")
    metric_rows = list(metrics)
    index = _metric_index(metric_rows)
    parsed = [(_game(raw), raw) for raw in games]
    output: list[dict[str, Any]] = []

    for game, raw in sorted(parsed, key=lambda item: (item[0].season, item[0].week, item[0].game_id)):
        membership = fbs_membership_by_season.get(game.season)
        if membership is None:
            raise CFBReconstructedSelectionError(
                f"CFB_RECONSTRUCTED_FBS_MEMBERSHIP_MISSING:{game.season}"
            )
        assert_fbs_only_games([game], fbs_team_rows=membership)
        weather_raw = weather_by_game.get(game.game_id)
        if not isinstance(weather_raw, Mapping):
            raise CFBReconstructedSelectionError(
                f"CFB_RECONSTRUCTED_WEATHER_MISSING:{game.game_id}"
            )

        if game.week == 1:
            home_metric = _prior_metric(index, team=game.home_team, season=game.season)
            away_metric = _prior_metric(index, team=game.away_team, season=game.season)
        else:
            home_metric = _current_metric(
                index, team=game.home_team, season=game.season, week=game.week
            )
            away_metric = _current_metric(
                index, team=game.away_team, season=game.season, week=game.week
            )

        weather = _weather(game, weather_raw)
        output.append(
            {
                "game_id": game.game_id,
                "season": game.season,
                "week": game.week,
                "neutral_site": game.neutral_site,
                "home_metrics": home_metric.to_dict(),
                "away_metrics": away_metric.to_dict(),
                "weather": weather,
                "home_score": _score(raw.get("home_score"), "home_score"),
                "away_score": _score(raw.get("away_score"), "away_score"),
                **({
                    "regulation_home_score": _score(raw.get("regulation_home_score"), "regulation_home_score"),
                    "regulation_away_score": _score(raw.get("regulation_away_score"), "regulation_away_score"),
                } if raw.get("regulation_home_score") is not None and raw.get("regulation_away_score") is not None else {}),
                "provenance_class": RECONSTRUCTED_PROVENANCE,
                "historical_pit_created": False,
                "weather_missing": bool(weather.get("weather_missing")),
            }
        )

    # Attach the frozen dual prior/current snapshots and games-in-sample counts.
    enriched = enrich_candidate_history(output, metrics=metric_rows)
    for row in enriched:
        row["provenance_class"] = RECONSTRUCTED_PROVENANCE
        row["historical_pit_created"] = False
    return enriched


def build_selection_bundle_manifest(
    *,
    rows: Sequence[Mapping[str, Any]],
    source_manifest: Mapping[str, Any],
    policy: Mapping[str, Any],
    predictive_code_manifest_sha256: str,
    acquisition_code_manifest_sha256: str,
    weather_source_contract: str,
) -> dict[str, Any]:
    if not rows:
        raise CFBReconstructedSelectionError("CFB_RECONSTRUCTED_SELECTION_ROWS_EMPTY")
    for value, name in (
        (predictive_code_manifest_sha256, "predictive_code_manifest_sha256"),
        (acquisition_code_manifest_sha256, "acquisition_code_manifest_sha256"),
    ):
        text = str(value or "").strip().lower()
        if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
            raise CFBReconstructedSelectionError(f"CFB_RECONSTRUCTED_HASH_INVALID:{name}")
    if not _nonempty(weather_source_contract):
        raise CFBReconstructedSelectionError("CFB_RECONSTRUCTED_WEATHER_CONTRACT_MISSING")

    seasons = sorted({int(row["season"]) for row in rows})
    if not seasons or seasons[0] != 2015 or seasons[-1] != 2025:
        raise CFBReconstructedSelectionError("CFB_RECONSTRUCTED_SELECTION_WINDOW_INCOMPLETE")
    if any(season == 2026 for season in seasons):
        raise CFBReconstructedSelectionError("CFB_RECONSTRUCTED_2026_OUTCOME_PROHIBITED")

    _assert_market_blind(rows, "selection_rows")
    weather_missing_ids = sorted(
        str(row["game_id"]) for row in rows if row.get("weather_missing") is True
    )
    return {
        "schema": "CFB_RECONSTRUCTED_SELECTION_BUNDLE_V1",
        "status": "READY_FOR_CANDIDATE_EVALUATION",
        "provenance_class": RECONSTRUCTED_PROVENANCE,
        "feature_semantics": policy.get("feature_semantics"),
        "feature_value_source_contract": policy.get("feature_value_source_contract"),
        "provider_metric_model_vintage": policy.get("provider_metric_model_vintage"),
        "provider_metric_materialization_mode": policy.get("provider_metric_materialization_mode"),
        "materializer_contract": CFB_RECONSTRUCTED_SELECTION_MATERIALIZER_VERSION,
        "start_season": 2015,
        "end_season": 2025,
        "no_2026_forward_outcomes": True,
        "market_data_in_predictive_features": False,
        "weather_provenance_class": RECONSTRUCTED_PROVENANCE,
        "weather_source_contract": weather_source_contract,
        "selection_row_count": len(rows),
        "weather_missing_count": len(weather_missing_ids),
        "weather_missing_game_ids": weather_missing_ids,
        "selection_rows_sha256": canonical_sha256(rows),
        "source_manifest_sha256": canonical_sha256(source_manifest),
        "predictive_code_manifest_sha256": predictive_code_manifest_sha256.lower(),
        "acquisition_code_manifest_sha256": acquisition_code_manifest_sha256.lower(),
        "historical_pit_created": False,
        "attempt_consumed": False,
        "evaluation_performed": False,
        "model_p_created": False,
        "truth_gate_authority": False,
        "promotion_authority": False,
        "staking_authority": False,
        "eligibility_changed": False,
        "official_authority": False,
    }


__all__ = [
    "CFB_RECONSTRUCTED_SELECTION_MATERIALIZER_VERSION",
    "RECONSTRUCTED_PROVENANCE",
    "WEATHER_MISSING_SOURCE",
    "CFBReconstructedSelectionError",
    "canonical_sha256",
    "materialize_reconstructed_selection_rows",
    "build_selection_bundle_manifest",
]
