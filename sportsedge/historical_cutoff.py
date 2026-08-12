"""Deterministic prior-day historical chronology for model rebuilds.

Safety invariants:
- canonical slate date is MLB ``officialDate`` (the game's scheduled local date)
- all games on a slate date read one frozen prior-day snapshot
- no result from date D mutates state until every eligible game on D is featurized
- suspended/resumed games are excluded fail-closed from both feature generation and
  state application unless a future explicitly validated reconciliation path handles them
- output ordering is deterministic by (officialDate, gamePk)
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from typing import Any, Callable, Iterable, Mapping, MutableMapping, TypeVar


class HistoricalCutoffError(ValueError):
    pass


TState = TypeVar("TState")
TFeature = TypeVar("TFeature")


@dataclass(frozen=True)
class ExcludedHistoricalGame:
    game_pk: int
    reason_code: str
    official_date: str | None


def canonical_slate_date(game: Mapping[str, Any]) -> date:
    """Return the venue-scheduled MLB date.

    ``officialDate`` is intentionally authoritative. UTC ``gameDate`` is ignored so a
    West Coast game that begins on one local date and crosses midnight elsewhere does
    not move between historical batches depending on timezone conversion.
    """
    raw = game.get("officialDate")
    if not isinstance(raw, str) or not raw:
        raise HistoricalCutoffError("OFFICIAL_DATE_REQUIRED")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise HistoricalCutoffError("OFFICIAL_DATE_INVALID") from exc


def game_pk(game: Mapping[str, Any]) -> int:
    try:
        return int(game["gamePk"])
    except Exception as exc:
        raise HistoricalCutoffError("GAME_PK_REQUIRED") from exc


def suspended_or_resumed_reason(game: Mapping[str, Any]) -> str | None:
    """Return a fail-closed exclusion reason for suspended/resumed-game metadata."""
    status = game.get("status") if isinstance(game.get("status"), Mapping) else {}
    text_parts = [
        status.get("abstractGameState"),
        status.get("detailedState"),
        status.get("reason"),
        status.get("statusCode"),
    ]
    text = " ".join(str(x) for x in text_parts if x).lower()
    if "suspend" in text:
        return "SUSPENDED_GAME_EXCLUDED"
    if "resum" in text:
        return "RESUMED_GAME_EXCLUDED"

    # StatsAPI has used different top-level resume markers over time. Treat any
    # recognized resume linkage as unsafe unless an explicit reconciliation path exists.
    for key in ("resumeDate", "resumedFrom", "resumeGameDate", "resumeGamePk"):
        if game.get(key) not in (None, "", 0):
            return "RESUMED_GAME_EXCLUDED"
    return None


def eligible_historical_games(
    games: Iterable[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[ExcludedHistoricalGame]]:
    eligible: list[Mapping[str, Any]] = []
    excluded: list[ExcludedHistoricalGame] = []
    for game in games:
        pk = game_pk(game)
        reason = suspended_or_resumed_reason(game)
        try:
            d = canonical_slate_date(game)
            d_text: str | None = d.isoformat()
        except HistoricalCutoffError:
            d_text = None
            if reason is None:
                reason = "OFFICIAL_DATE_INVALID_OR_MISSING"
        if reason:
            excluded.append(ExcludedHistoricalGame(pk, reason, d_text))
        else:
            eligible.append(game)
    eligible.sort(key=lambda g: (canonical_slate_date(g), game_pk(g)))
    excluded.sort(key=lambda x: (x.official_date or "", x.game_pk, x.reason_code))
    return eligible, excluded


def process_prior_day_batches(
    *,
    games: Iterable[Mapping[str, Any]],
    initial_state: TState,
    make_feature: Callable[[TState, Mapping[str, Any]], TFeature],
    apply_result: Callable[[TState, Mapping[str, Any]], None],
) -> tuple[list[tuple[Mapping[str, Any], TFeature]], TState, list[ExcludedHistoricalGame]]:
    """Feature all same-day games from one frozen snapshot, then apply that day's results.

    ``make_feature`` receives a deep copy of the frozen prior-day state for every game,
    so accidental mutation inside feature code cannot leak into another same-day game.
    ``apply_result`` runs only after the entire date has been featurized.
    """
    eligible, excluded = eligible_historical_games(games)
    state = deepcopy(initial_state)
    output: list[tuple[Mapping[str, Any], TFeature]] = []

    i = 0
    while i < len(eligible):
        d = canonical_slate_date(eligible[i])
        day: list[Mapping[str, Any]] = []
        while i < len(eligible) and canonical_slate_date(eligible[i]) == d:
            day.append(eligible[i])
            i += 1

        frozen = deepcopy(state)
        day_features: list[tuple[Mapping[str, Any], TFeature]] = []
        for game in day:
            feature = make_feature(deepcopy(frozen), game)
            day_features.append((game, feature))
        output.extend(day_features)

        for game in day:
            apply_result(state, game)

    return output, state, excluded


def stable_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(stable_json_bytes(value)).hexdigest()
