"""Hash-bound empirical NFL environment profile.

The profile supplies fitted *environmental distribution* inputs used by the NFL
adapter: regulation/full-game margin dispersion, total dispersion, and a global
non-neutral home-field prior. It does not contain sportsbook lines and it does
not inject historical key-number mass into the simulator.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import isfinite
from statistics import stdev
from typing import Any


ENVIRONMENT_PROFILE_CONTRACT = "NFL_REAL_HISTORY_ENVIRONMENT_V1"


def _valid_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _score(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _neutral_flag(value: Any, *, field: str) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    text = str(value).strip().lower()
    if field == "location":
        if text == "neutral":
            return True
        if text == "home":
            return False
        raise ValueError(f"NFL_LOCATION_VALUE_INVALID:{value}")
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"NEUTRAL_SITE_VALUE_INVALID:{value}")


def _row_is_neutral(row: Mapping[str, Any]) -> bool:
    flags: list[bool] = []
    for field in ("neutral_site", "neutral", "location"):
        if field not in row:
            continue
        parsed = _neutral_flag(row.get(field), field=field)
        if parsed is not None:
            flags.append(parsed)
    if len(set(flags)) > 1:
        raise ValueError("NEUTRAL_SITE_CONTEXT_CONFLICT")
    return flags[0] if flags else False


def validate_nfl_environment_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize a persisted NFL environment profile."""

    if profile.get("contract") != ENVIRONMENT_PROFILE_CONTRACT:
        raise ValueError("NFL_ENVIRONMENT_PROFILE_CONTRACT_INVALID")
    if profile.get("provenance") != "REAL_PUBLIC_HISTORY":
        raise ValueError("REAL_HISTORY_REQUIRED")
    source_url = str(profile.get("source_url", ""))
    if not source_url.startswith("https://"):
        raise ValueError("REAL_HISTORY_SOURCE_URL_REQUIRED")
    source_sha256 = profile.get("source_sha256")
    if not _valid_sha256(source_sha256):
        raise ValueError("SOURCE_SHA256_INVALID")

    seasons = sorted({int(value) for value in profile.get("seasons", [])})
    if len(seasons) < 2:
        raise ValueError("MULTI_SEASON_HISTORY_REQUIRED")

    game_count = int(profile.get("game_count", 0))
    non_neutral_game_count = int(profile.get("non_neutral_game_count", 0))
    if game_count < 2:
        raise ValueError("NFL_ENVIRONMENT_GAME_COUNT_INVALID")
    if non_neutral_game_count < 1 or non_neutral_game_count > game_count:
        raise ValueError("NFL_ENVIRONMENT_NON_NEUTRAL_COUNT_INVALID")

    values: dict[str, float] = {}
    for key in ("margin_sigma", "total_sigma", "hfa_points"):
        value = float(profile.get(key))
        if not isfinite(value):
            raise ValueError(f"NFL_ENVIRONMENT_VALUE_NONFINITE:{key}")
        values[key] = value
    if values["margin_sigma"] <= 0:
        raise ValueError("NFL_MARGIN_SIGMA_MUST_BE_POSITIVE")
    if values["total_sigma"] <= 0:
        raise ValueError("NFL_TOTAL_SIGMA_MUST_BE_POSITIVE")

    return {
        **dict(profile),
        "contract": ENVIRONMENT_PROFILE_CONTRACT,
        "provenance": "REAL_PUBLIC_HISTORY",
        "source_url": source_url,
        "source_sha256": str(source_sha256).lower(),
        "seasons": seasons,
        "game_count": game_count,
        "non_neutral_game_count": non_neutral_game_count,
        **values,
    }


def fit_nfl_environment_profile(
    rows: Iterable[Mapping[str, Any]],
    *,
    source_url: str,
    source_sha256: str,
    min_games: int = 200,
) -> dict[str, Any]:
    """Fit global NFL score-distribution environment values from real history.

    Only scored regular-season rows are used. nflverse schedule rows commonly
    identify neutral sites through ``location == 'Neutral'``; the legacy
    ``neutral_site`` and ``neutral`` aliases are also accepted. Conflicting
    neutral-site fields fail closed.

    ``hfa_points`` is the empirical mean home scoring margin across non-neutral
    regular-season games. It is a deliberately simple league-level prior;
    venue/context refinements can be layered later without changing provenance.
    """

    if not str(source_url).startswith("https://"):
        raise ValueError("REAL_HISTORY_SOURCE_URL_REQUIRED")
    if not _valid_sha256(source_sha256):
        raise ValueError("SOURCE_SHA256_INVALID")
    if isinstance(min_games, bool) or not isinstance(min_games, int) or min_games < 2:
        raise ValueError("NFL_ENVIRONMENT_MIN_GAMES_INVALID")

    input_rows = [dict(row) for row in rows]
    scored: list[tuple[int, float, float, bool]] = []
    for row in input_rows:
        if str(row.get("game_type", "REG")).upper() != "REG":
            continue
        if row.get("season") in (None, ""):
            continue
        home = _score(row.get("home_score"))
        away = _score(row.get("away_score"))
        if home is None or away is None:
            continue
        scored.append((int(row["season"]), home, away, _row_is_neutral(row)))

    seasons = sorted({season for season, _, _, _ in scored})
    if len(seasons) < 2:
        raise ValueError("MULTI_SEASON_HISTORY_REQUIRED")
    if len(scored) < min_games:
        raise ValueError(
            f"NFL_ENVIRONMENT_MIN_GAMES_NOT_MET:{len(scored)}<{min_games}"
        )

    margins = [home - away for _, home, away, _ in scored]
    totals = [home + away for _, home, away, _ in scored]
    non_neutral_margins = [
        home - away for _, home, away, neutral in scored if not neutral
    ]
    if not non_neutral_margins:
        raise ValueError("NFL_ENVIRONMENT_NON_NEUTRAL_HISTORY_REQUIRED")

    profile = {
        "contract": ENVIRONMENT_PROFILE_CONTRACT,
        "provenance": "REAL_PUBLIC_HISTORY",
        "source_url": str(source_url),
        "source_sha256": str(source_sha256).lower(),
        "seasons": seasons,
        "input_row_count": len(input_rows),
        "game_count": len(scored),
        "excluded_row_count": len(input_rows) - len(scored),
        "non_neutral_game_count": len(non_neutral_margins),
        "margin_sigma": float(stdev(margins)),
        "total_sigma": float(stdev(totals)),
        "hfa_points": float(sum(non_neutral_margins) / len(non_neutral_margins)),
        "method": {
            "margin_sigma": "sample_stdev(home_score-away_score)",
            "total_sigma": "sample_stdev(home_score+away_score)",
            "hfa_points": "mean(home_score-away_score) on non-neutral REG games",
            "neutral_site": "location=Neutral with neutral_site/neutral aliases",
        },
    }
    return validate_nfl_environment_profile(profile)
