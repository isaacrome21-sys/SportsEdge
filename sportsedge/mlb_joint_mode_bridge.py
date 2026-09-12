"""One price-independent feature bridge for manual, hybrid, and automatic MLB modes."""
from __future__ import annotations

from datetime import date
import hashlib
import json
from typing import Any, Mapping, Sequence

from .first_hr_order_engine import build_first_hr_features
from .generic_market_engine import GAME_MARKETS
from .hitter_joint_engine import HITTER_MARKETS
from .live_slate import LiveGame
from .mlb_f5_features import MLBF5HistorySource
from .mlb_generic_features import MLBGenericHistorySource
from .mlb_joint_features import FEATURE_VERSION, build_hitter_joint_features, build_pitcher_joint_features
from .pitcher_joint_engine import PITCHER_MARKETS
from .pitcher_record_win_engine import build_pitcher_record_win_features
from .quote_bridge import validate_canonical_quote


class MLBJointModeBridgeError(ValueError):
    pass


def _content_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _live_game_state(game: LiveGame) -> dict[str, Any]:
    """Return the immutable pregame baseball state bound to game-market Model_P.

    This is provenance, not a sportsbook or predictive feature. Production game
    markets require confirmed batting orders and both probable starters so a Model_P
    cannot survive a lineup/starter change under the same historical team means.
    """
    if game.away_probable_pitcher_id is None or game.home_probable_pitcher_id is None:
        raise MLBJointModeBridgeError("both probable pitchers required for game market")
    if not game.away_lineup.confirmed or not game.home_lineup.confirmed:
        raise MLBJointModeBridgeError("confirmed MLB batting orders required for game market")
    return {
        "game_pk": int(game.game_pk),
        "away_team_id": int(game.away_team_id),
        "home_team_id": int(game.home_team_id),
        "away_probable_pitcher_id": int(game.away_probable_pitcher_id),
        "home_probable_pitcher_id": int(game.home_probable_pitcher_id),
        "away_lineup": [
            [int(pid), int(slot)]
            for pid, slot in zip(game.away_lineup.player_ids, game.away_lineup.batting_slots)
        ],
        "home_lineup": [
            [int(pid), int(slot)]
            for pid, slot in zip(game.home_lineup.player_ids, game.home_lineup.batting_slots)
        ],
        "away_lineup_confirmed": True,
        "home_lineup_confirmed": True,
        "venue_id": None if game.venue_id is None else int(game.venue_id),
        "official_date": game.official_date,
        "game_number": game.game_number,
        "double_header": game.double_header,
    }


def _batter_team(game: LiveGame, entity_id: str) -> int:
    try:
        pid = int(entity_id)
    except (TypeError, ValueError) as exc:
        raise MLBJointModeBridgeError("batter entity_id must be MLB player id") from exc
    away = pid in game.away_lineup.player_ids
    home = pid in game.home_lineup.player_ids
    if away and home:
        raise MLBJointModeBridgeError("batter appears in both lineups")
    if away:
        return int(game.away_team_id)
    if home:
        return int(game.home_team_id)
    raise MLBJointModeBridgeError("batter not present in live lineup")


def _team_side(game: LiveGame, entity_id: str) -> str:
    try:
        team_id = int(entity_id)
    except (TypeError, ValueError) as exc:
        raise MLBJointModeBridgeError("team-total entity_id must be MLB team id") from exc
    if team_id == int(game.away_team_id):
        return "AWAY"
    if team_id == int(game.home_team_id):
        return "HOME"
    raise MLBJointModeBridgeError("TEAM_TOTAL_ENTITY_NOT_IN_GAME")


def _batter_context(game: LiveGame, entity_id: str) -> tuple[int, int, int]:
    team_id = _batter_team(game, entity_id)
    if game.venue_id is None:
        raise MLBJointModeBridgeError("VENUE_UNMAPPED")
    if team_id == int(game.away_team_id):
        if game.home_probable_pitcher_id is None:
            raise MLBJointModeBridgeError("home probable pitcher required")
        return team_id, int(game.home_probable_pitcher_id), int(game.venue_id)
    if game.away_probable_pitcher_id is None:
        raise MLBJointModeBridgeError("away probable pitcher required")
    return team_id, int(game.away_probable_pitcher_id), int(game.venue_id)


def build_canonical_feature_row(
    *,
    game: LiveGame,
    quote: Mapping[str, Any],
    source: MLBGenericHistorySource,
    target_date: date,
    f5_source: MLBF5HistorySource | None = None,
) -> dict[str, Any]:
    q = validate_canonical_quote(quote)
    if str(q["game_id"]) != str(game.game_pk):
        raise MLBJointModeBridgeError("quote/game identity mismatch")
    market = str(q["market"])
    entity_id = str(q["entity_id"])
    base = {
        "game_pk": int(game.game_pk),
        "market": market,
        "entity_id": entity_id,
        "retrieved_at": source.retrieved_at.isoformat(),
        "asof": source.retrieved_at.isoformat(),
        "source": "MLB_STATSAPI_STRICTLY_PRIOR_JOINT_FEATURES",
    }

    if market == "HOME_RUNS":
        team_id = _batter_team(game, entity_id)
        return source.feature_row(
            game_pk=int(game.game_pk),
            market=market,
            entity_id=entity_id,
            target_date=target_date,
            away_team_id=int(game.away_team_id),
            home_team_id=int(game.home_team_id),
            player_id=int(entity_id),
            team_id=team_id,
        )

    if market == "FIRST_HOME_RUN":
        team_id = _batter_team(game, entity_id)
        built = build_first_hr_features(source, game=game, target_date=target_date)
        return {
            **base,
            "team_id": team_id,
            "source": "MLB_STATSAPI_STRICTLY_PRIOR_FIRST_HR_LINEUP_ORDER",
            "first_hr_feature_version": built["feature_version"],
            "feature_source_hash": built["feature_source_hash"],
            "features": dict(built["features"]),
        }

    if market == "PITCHER_RECORD_WIN":
        try:
            pid = int(entity_id)
        except (TypeError, ValueError) as exc:
            raise MLBJointModeBridgeError("pitcher entity_id must be MLB player id") from exc
        f5 = f5_source or MLBF5HistorySource(
            opener=source.opener, retrieved_at=source.retrieved_at
        )
        built = build_pitcher_record_win_features(
            source,
            game=game,
            pitcher_id=pid,
            target_date=target_date,
            f5_source=f5,
        )
        team_side = str(built["team_side"])
        return {
            **base,
            "team_id": int(built["team_id"]),
            "team_side": team_side,
            "source": "MLB_STATSAPI_STRICTLY_PRIOR_STARTER_OUTS_PLUS_F5_WIN_CREDIT_PATHS",
            "pitcher_record_win_feature_version": built["feature_version"],
            "feature_source_hash": built["feature_source_hash"],
            "features": {
                "qualification_rate": built["qualification_rate"],
                "starter_outs_history": list(built["starter_outs_history"]),
                "f5_features": dict(built["f5_features"]),
                "post_f5_credit_paths": {
                    state: list(values)
                    for state, values in built["post_f5_credit_paths"].items()
                },
                "credit_path_state_counts": dict(built["credit_path_state_counts"]),
                "game_source_hash": built["game_source_hash"],
                "pitcher_source_hash": built["pitcher_source_hash"],
                "f5_feature_source_hash": built["f5_feature_source_hash"],
                "credit_path_source_hash": built["credit_path_source_hash"],
                "history": list(built["history"]),
            },
        }

    if market in HITTER_MARKETS:
        team_id, opposing_pitcher_id, venue_id = _batter_context(game, entity_id)
        built = build_hitter_joint_features(
            source,
            batter_id=int(entity_id),
            opposing_pitcher_id=opposing_pitcher_id,
            venue_id=venue_id,
            target_date=target_date,
        )
        return {
            **base,
            "team_id": team_id,
            "opposing_pitcher_id": opposing_pitcher_id,
            "venue_id": venue_id,
            "joint_feature_version": built["feature_version"],
            "feature_source_hash": built["feature_source_hash"],
            "features": {
                "history_pool": built["history_pool"],
                "history_weights": built["history_weights"],
                "matchup": built["matchup"],
            },
        }

    if market in PITCHER_MARKETS:
        if market.startswith("EITHER_PITCHER_"):
            if game.away_probable_pitcher_id is None or game.home_probable_pitcher_id is None:
                raise MLBJointModeBridgeError("both probable pitchers required for either-pitcher market")
            a = build_pitcher_joint_features(source, pitcher_id=int(game.away_probable_pitcher_id), target_date=target_date)
            b = build_pitcher_joint_features(source, pitcher_id=int(game.home_probable_pitcher_id), target_date=target_date)
            payload = {"pitcher_a_history": a["history_pool"], "pitcher_b_history": b["history_pool"]}
            return {
                **base,
                "joint_feature_version": FEATURE_VERSION,
                "feature_source_hash": _content_sha({"version": FEATURE_VERSION, "payload": payload, "game_pk": game.game_pk}),
                "features": payload,
            }
        try:
            pid = int(entity_id)
        except (TypeError, ValueError) as exc:
            raise MLBJointModeBridgeError("pitcher entity_id must be MLB player id") from exc
        if pid not in {game.away_probable_pitcher_id, game.home_probable_pitcher_id}:
            raise MLBJointModeBridgeError("NON_PROBABLE_PITCHER")
        built = build_pitcher_joint_features(source, pitcher_id=pid, target_date=target_date)
        return {
            **base,
            "joint_feature_version": built["feature_version"],
            "feature_source_hash": built["feature_source_hash"],
            "features": {"history_pool": built["history_pool"]},
        }

    if market in GAME_MARKETS:
        live_state = _live_game_state(game)
        live_state_hash = _content_sha(live_state)
        if market.startswith("F5_"):
            f5 = f5_source or MLBF5HistorySource(opener=source.opener, retrieved_at=source.retrieved_at)
            built = f5.matchup_features(
                away_team_id=int(game.away_team_id),
                home_team_id=int(game.home_team_id),
                target_date=target_date,
            )
            row = {
                **base,
                "source": "MLB_STATSAPI_STRICTLY_PRIOR_ACTUAL_F5_INNINGS",
                "f5_feature_version": built["feature_version"],
                "live_game_state_hash": live_state_hash,
                "feature_source_hash": _content_sha({
                    "f5_feature_source_hash": built["feature_source_hash"],
                    "live_game_state_hash": live_state_hash,
                }),
                "features": dict(built["features"]),
            }
            if market == "F5_TEAM_TOTALS":
                row["team_side"] = _team_side(game, entity_id)
            return row

        away, home, _ = source.team_means(
            away_team_id=int(game.away_team_id),
            home_team_id=int(game.home_team_id),
            target_date=target_date,
        )
        identity = {
            "version": "mlb_generic_feature_v2_live_state_bound",
            "game_pk": int(game.game_pk),
            "target_date": target_date.isoformat(),
            "away_mean_runs": away,
            "home_mean_runs": home,
            "retrieved_at": source.retrieved_at.isoformat(),
            "live_game_state_hash": live_state_hash,
        }
        row = {
            **base,
            "generic_feature_version": "mlb_generic_feature_v2_live_state_bound",
            "away_mean_runs": away,
            "home_mean_runs": home,
            "live_game_state_hash": live_state_hash,
            "source_subset_hash": _content_sha(identity),
        }
        if market == "TEAM_TOTALS":
            row["team_side"] = _team_side(game, entity_id)
        return row

    raise MLBJointModeBridgeError(f"unsupported market {market}")


def build_feature_rows_for_quotes(
    *,
    games: Sequence[LiveGame],
    quotes: Sequence[Mapping[str, Any]],
    source: MLBGenericHistorySource,
    target_date: date,
) -> list[dict[str, Any]]:
    games_by_id = {str(g.game_pk): g for g in games}
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    f5_source = MLBF5HistorySource(opener=source.opener, retrieved_at=source.retrieved_at)
    for raw in quotes:
        q = validate_canonical_quote(raw)
        identity = (str(q["game_id"]), str(q["entity_id"]), str(q["market"]))
        if identity in seen:
            continue
        game = games_by_id.get(identity[0])
        if game is None:
            raise MLBJointModeBridgeError(f"game not found for {identity[0]}")
        out.append(
            build_canonical_feature_row(
                game=game,
                quote=q,
                source=source,
                target_date=target_date,
                f5_source=f5_source,
            )
        )
        seen.add(identity)
    return out