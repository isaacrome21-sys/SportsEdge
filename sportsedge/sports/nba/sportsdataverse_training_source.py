from __future__ import annotations

"""Materialize NBA training rows from normalized SportsDataverse/ESPN team boxes.

The public SportsDataverse team-box releases are useful factual history, but a
current release file does not by itself prove when each historical final row was
known. Therefore every consumed team-game row MUST carry a caller-supplied
``known_at`` timestamp from a preserved source receipt/commit/capture. Missing
row-level availability fails closed. Market data is forbidden.

This module does not grant Model_P, Truth Gate, promotion, staking, or OFFICIAL
authority. It only creates validated chronological ``NBATrainingRow`` objects.
"""

from collections import defaultdict, deque
from datetime import datetime, timezone
import math
from typing import Any, Mapping, Sequence

from .training import NBATrainingRow

SCHEMA_REFERENCE = (
    "sportsdataverse/hoopR@7cad20c078c189206955f8e1a6e5de56c3804b30:"
    "R/espn_nba_data.R#helper_espn_nba_team_box"
)
_FORBIDDEN = ("odds", "price", "vig", "sportsbook", "market", "closing_line", "spread", "total_line")


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _number(row: Mapping[str, Any], names: Sequence[str], *, field: str) -> float:
    value = None
    for name in names:
        if name in row and row[name] not in (None, ""):
            value = row[name]
            break
    if value is None:
        raise ValueError(f"missing {field}")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if not math.isfinite(out) or out < 0:
        raise ValueError(f"invalid {field}")
    return out


def _text(row: Mapping[str, Any], names: Sequence[str], *, field: str) -> str:
    for name in names:
        value = str(row.get(name) or "").strip()
        if value:
            return value
    raise ValueError(f"missing {field}")


def _assert_market_blind(obj: Any, path: str = "root") -> None:
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            low = str(key).lower()
            if any(token in low for token in _FORBIDDEN):
                raise ValueError(f"market input forbidden at {path}.{key}")
            _assert_market_blind(value, f"{path}.{key}")
    elif isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        for i, value in enumerate(obj):
            _assert_market_blind(value, f"{path}[{i}]")


def _normalized_team_game(row: Mapping[str, Any]) -> dict[str, Any]:
    game_id = _text(row, ("game_id", "id"), field="game_id")
    team_id = _text(row, ("team_id",), field="team_id")
    side = _text(row, ("team_home_away", "home_away", "homeAway"), field="team_home_away").lower()
    if side not in {"home", "away"}:
        raise ValueError("team_home_away must be home or away")
    tipoff_value = row.get("game_date_time", row.get("tipoff"))
    if tipoff_value in (None, ""):
        raise ValueError("missing game_date_time")
    known_value = row.get("known_at")
    if known_value in (None, ""):
        raise ValueError("missing row-level known_at; current historical release alone is not PIT proof")
    tipoff = _utc(tipoff_value, "game_date_time")
    known_at = _utc(known_value, "known_at")
    if known_at <= tipoff:
        raise ValueError("final team-box known_at must be after tipoff")

    points = int(_number(row, ("team_score", "points"), field="team_score"))
    fga = _number(row, ("field_goals_attempted", "field_goal_attempts", "fga"), field="field_goals_attempted")
    orb = _number(row, ("offensive_rebounds", "off_rebounds", "orb"), field="offensive_rebounds")
    tov = _number(row, ("turnovers", "total_turnovers", "tov"), field="turnovers")
    fta = _number(row, ("free_throws_attempted", "free_throw_attempts", "fta"), field="free_throws_attempted")
    possessions = fga - orb + tov + 0.44 * fta
    if possessions <= 0:
        raise ValueError("derived possessions must be positive")
    return {
        "game_id": game_id,
        "team_id": team_id,
        "side": side,
        "tipoff": tipoff,
        "known_at": known_at,
        "points": points,
        "possessions": possessions,
        "off_rating": 100.0 * points / possessions,
    }


def build_training_rows_from_team_boxes(
    rows: Sequence[Mapping[str, Any]],
    *,
    source_version: str,
    minimum_history_games: int = 5,
    rolling_games: int = 12,
) -> tuple[NBATrainingRow, ...]:
    """Create chronological PIT-safe rows from normalized team boxscore history.

    Features for a target game use only prior games whose preserved ``known_at``
    timestamp is strictly before the target tipoff. The target game's final score
    is retained only as the supervised outcome.
    """
    if not source_version.strip():
        raise ValueError("source_version is required")
    if minimum_history_games < 1:
        raise ValueError("minimum_history_games must be positive")
    if rolling_games < minimum_history_games:
        raise ValueError("rolling_games must be >= minimum_history_games")
    _assert_market_blind(rows)

    team_rows = [_normalized_team_game(row) for row in rows]
    games: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in team_rows:
        games[row["game_id"]].append(row)

    paired: list[tuple[datetime, str, dict[str, Any], dict[str, Any]]] = []
    for game_id, sides in games.items():
        if len(sides) != 2:
            raise ValueError(f"game {game_id} must contain exactly two team rows")
        by_side = {r["side"]: r for r in sides}
        if set(by_side) != {"home", "away"}:
            raise ValueError(f"game {game_id} must contain one home and one away row")
        home, away = by_side["home"], by_side["away"]
        if home["tipoff"] != away["tipoff"]:
            raise ValueError(f"game {game_id} has inconsistent tipoff")
        if home["team_id"] == away["team_id"]:
            raise ValueError(f"game {game_id} has duplicate team identity")
        paired.append((home["tipoff"], game_id, home, away))
    paired.sort(key=lambda item: (item[0], item[1]))

    history: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=rolling_games))
    output: list[NBATrainingRow] = []

    def eligible(team_id: str, tipoff: datetime) -> list[dict[str, Any]]:
        return [row for row in history[team_id] if row["known_at"] < tipoff]

    for tipoff, game_id, home, away in paired:
        hh = eligible(home["team_id"], tipoff)
        ah = eligible(away["team_id"], tipoff)
        if len(hh) >= minimum_history_games and len(ah) >= minimum_history_games:
            hp = sum(r["possessions"] for r in hh) / len(hh)
            ap = sum(r["possessions"] for r in ah) / len(ah)
            hor = sum(r["off_rating"] for r in hh) / len(hh)
            aor = sum(r["off_rating"] for r in ah) / len(ah)
            hdr = sum(r["opp_off_rating"] for r in hh) / len(hh)
            adr = sum(r["opp_off_rating"] for r in ah) / len(ah)
            feature_as_of = max(r["known_at"] for r in hh + ah)
            training_row = NBATrainingRow(
                game_id=game_id,
                tipoff=tipoff,
                feature_as_of=feature_as_of,
                home_team_id=home["team_id"],
                away_team_id=away["team_id"],
                expected_possessions=(hp + ap) / 2.0,
                home_offensive_rating=hor,
                home_defensive_rating=hdr,
                away_offensive_rating=aor,
                away_defensive_rating=adr,
                home_points=home["points"],
                away_points=away["points"],
                source_version=source_version,
            )
            training_row.validate()
            output.append(training_row)

        home_hist = dict(home, opp_off_rating=away["off_rating"])
        away_hist = dict(away, opp_off_rating=home["off_rating"])
        history[home["team_id"]].append(home_hist)
        history[away["team_id"]].append(away_hist)

    return tuple(output)


__all__ = ["SCHEMA_REFERENCE", "build_training_rows_from_team_boxes"]
