"""Canonical fail-closed NFL/CFB offensive player-prop run machine.

Only statistics reconciled on shared Engine A game/play paths plus Engine B
player allocation may create Model_P. Sportsbook lines are consumed only after
those paths exist. TD scorer, kicker and defensive props remain outside this
A+B surface.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Mapping, Sequence

from sportsedge.core.simulate.drive_play import EngineADrivePlaySimulator, TeamDriveProfile
from sportsedge.core.simulate.player_markets import derive_player_stat_market
from sportsedge.core.simulate.usage import EngineBUsageAllocator, PlayerUsageProfile, TeamUsageProfile
from sportsedge.devig import DevigError, devig_with_policy
from sportsedge.edge_floors import load_edge_floor_config, require_frozen_devig_policy
from sportsedge.truth_gate import american_to_decimal

FOOTBALL_PROP_MACHINE_VERSION = "FOOTBALL_OFFENSIVE_PROP_AB_V1"
FOOTBALL_PROP_ARTIFACT_SCHEMA = "FOOTBALL_PROP_MODEL_ARTIFACT_V1"
DEFAULT_QUOTE_TTL_SECONDS = 180
DEFAULT_FEATURE_TTL_SECONDS = 120 * 60
SUPPORTED_SPORTS = frozenset({"NFL", "CFB"})

PROVIDER_MARKET_TO_STAT = {
    "player_pass_attempts": "pass_attempts",
    "player_pass_completions": "completions",
    "player_pass_interceptions": "interceptions",
    "player_pass_longest_completion": "longest_completion",
    "player_pass_rush_yds": "pass_plus_rush_yards",
    "player_pass_tds": "passing_tds",
    "player_pass_yds": "passing_yards",
    "player_receptions": "receptions",
    "player_reception_longest": "longest_reception",
    "player_reception_yds": "receiving_yards",
    "player_rush_attempts": "rush_attempts",
    "player_rush_longest": "longest_rush",
    "player_rush_reception_yds": "rush_plus_receiving_yards",
    "player_rush_yds": "rushing_yards",
}

_DRIVE_FIELDS = (
    "pass_rate", "completion_rate", "success_rate", "explosive_rate",
    "turnover_rate", "sack_rate", "field_goal_attempt_rate",
    "field_goal_skill", "pace_seconds_mean",
)
_USAGE_FIELDS = (
    "snap_share", "route_participation", "target_share", "rush_share",
    "red_zone_share",
)


class FootballPropRunError(ValueError):
    pass


def canonical_hash(value: Any) -> str:
    try:
        raw = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FootballPropRunError("FOOTBALL_PROP_CANONICAL_HASH_INPUT_INVALID") from exc
    return sha256(raw).hexdigest()


def _sha256(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 64 or any(ch not in "0123456789abcdef" for ch in raw):
        raise FootballPropRunError(error)
    return raw


def _git_sha(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 40 or any(ch not in "0123456789abcdef" for ch in raw):
        raise FootballPropRunError(error)
    return raw


def _aware(value: Any, error: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise FootballPropRunError(error)
        try:
            out = datetime.fromisoformat(text)
        except ValueError as exc:
            raise FootballPropRunError(error) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise FootballPropRunError(error)
    return out.astimezone(timezone.utc)


def _finite(value: Any, error: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise FootballPropRunError(error) from exc
    if not isfinite(out):
        raise FootballPropRunError(error)
    return out


def _norm_name(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _seed(root_seed: int, game_id: str, label: str, simulation_id: int = 0) -> int:
    if isinstance(root_seed, bool) or not isinstance(root_seed, int):
        raise FootballPropRunError("FOOTBALL_PROP_ROOT_SEED_INVALID")
    raw = f"{root_seed}|{game_id}|{label}|{simulation_id}".encode("utf-8")
    return int(sha256(raw).hexdigest()[:16], 16) % (2**63 - 1)


def _load_artifact(
    payload: Mapping[str, Any], *, sport: str,
    expected_artifact_sha256: str, runtime_code_git_sha: str,
) -> tuple[dict[str, TeamDriveProfile], str, str]:
    if not isinstance(payload, Mapping):
        raise FootballPropRunError("FOOTBALL_PROP_MODEL_ARTIFACT_REQUIRED")
    expected = _sha256(
        expected_artifact_sha256,
        "FOOTBALL_PROP_EXPECTED_ARTIFACT_SHA256_INVALID",
    )
    actual = canonical_hash(dict(payload))
    if actual != expected:
        raise FootballPropRunError("FOOTBALL_PROP_MODEL_ARTIFACT_SHA256_MISMATCH")
    if payload.get("schema_version") != FOOTBALL_PROP_ARTIFACT_SCHEMA:
        raise FootballPropRunError("FOOTBALL_PROP_MODEL_ARTIFACT_SCHEMA_MISMATCH")
    if str(payload.get("sport") or "").upper() != sport:
        raise FootballPropRunError("FOOTBALL_PROP_MODEL_ARTIFACT_SPORT_MISMATCH")
    artifact_code = _git_sha(
        payload.get("code_git_sha"), "FOOTBALL_PROP_MODEL_CODE_GIT_SHA_INVALID"
    )
    runtime_code = _git_sha(
        runtime_code_git_sha, "FOOTBALL_PROP_RUNTIME_CODE_GIT_SHA_INVALID"
    )
    if artifact_code != runtime_code:
        raise FootballPropRunError("FOOTBALL_PROP_MODEL_CODE_GIT_SHA_MISMATCH")
    training_sha = _sha256(
        payload.get("source_manifest_sha256"),
        "FOOTBALL_PROP_TRAINING_SOURCE_SHA256_INVALID",
    )
    raw_profiles = payload.get("team_drive_profiles")
    if not isinstance(raw_profiles, Mapping) or not raw_profiles:
        raise FootballPropRunError("FOOTBALL_PROP_TEAM_DRIVE_PROFILES_REQUIRED")
    profiles: dict[str, TeamDriveProfile] = {}
    for team, raw in raw_profiles.items():
        team_id = str(team or "").strip()
        if not team_id or not isinstance(raw, Mapping):
            raise FootballPropRunError("FOOTBALL_PROP_TEAM_DRIVE_PROFILE_INVALID")
        missing = [field for field in _DRIVE_FIELDS if field not in raw]
        if missing:
            raise FootballPropRunError(
                f"FOOTBALL_PROP_TEAM_DRIVE_PROFILE_FIELD_MISSING:{team_id}:{','.join(missing)}"
            )
        try:
            profiles[team_id] = TeamDriveProfile(
                **{field: raw[field] for field in _DRIVE_FIELDS}
            )
        except (TypeError, ValueError) as exc:
            raise FootballPropRunError(
                f"FOOTBALL_PROP_TEAM_DRIVE_PROFILE_INVALID:{team_id}:{exc}"
            ) from exc
    return profiles, actual, training_sha


def _player_usage(raw: Mapping[str, Any], *, team: str) -> tuple[PlayerUsageProfile, str]:
    player_id = str(raw.get("player_id") or "").strip()
    player_name = str(raw.get("player_name") or "").strip()
    position = str(raw.get("position") or "").strip().upper()
    if not player_id or not player_name or not position:
        raise FootballPropRunError("FOOTBALL_PROP_PLAYER_IDENTITY_REQUIRED")
    if str(raw.get("team") or "").strip() != team:
        raise FootballPropRunError(f"FOOTBALL_PROP_PLAYER_TEAM_MISMATCH:{player_id}")
    if type(raw.get("active")) is not bool:
        raise FootballPropRunError(f"FOOTBALL_PROP_PARTICIPATION_UNRESOLVED:{player_id}")
    missing = [field for field in _USAGE_FIELDS if field not in raw]
    if missing:
        raise FootballPropRunError(
            f"FOOTBALL_PROP_USAGE_FIELD_MISSING:{player_id}:{','.join(missing)}"
        )
    try:
        profile = PlayerUsageProfile(
            player_id=player_id, team=team, position=position,
            active=raw["active"], snap_share=raw["snap_share"],
            route_participation=raw["route_participation"],
            target_share=raw["target_share"], rush_share=raw["rush_share"],
            red_zone_share=raw["red_zone_share"],
        )
    except (TypeError, ValueError) as exc:
        raise FootballPropRunError(
            f"FOOTBALL_PROP_USAGE_PROFILE_INVALID:{player_id}:{exc}"
        ) from exc
    return profile, player_name


def _team_usage(raw: Any, *, team: str) -> tuple[TeamUsageProfile, dict[str, str]]:
    if not isinstance(raw, Mapping):
        raise FootballPropRunError(f"FOOTBALL_PROP_TEAM_USAGE_REQUIRED:{team}")
    items = raw.get("players")
    if not isinstance(items, list) or not items:
        raise FootballPropRunError(f"FOOTBALL_PROP_TEAM_USAGE_PLAYERS_REQUIRED:{team}")
    players: list[PlayerUsageProfile] = []
    names: dict[str, str] = {}
    for item in items:
        if not isinstance(item, Mapping):
            raise FootballPropRunError("FOOTBALL_PROP_PLAYER_USAGE_INVALID")
        player, player_name = _player_usage(item, team=team)
        key = _norm_name(player_name)
        if key in names and names[key] != player.player_id:
            raise FootballPropRunError(f"FOOTBALL_PROP_PLAYER_NAME_COLLISION:{player_name}")
        names[key] = player.player_id
        players.append(player)
    qb = str(raw.get("quarterback_id") or "").strip()
    try:
        usage = TeamUsageProfile(team=team, players=tuple(players), quarterback_id=qb)
    except (TypeError, ValueError) as exc:
        raise FootballPropRunError(f"FOOTBALL_PROP_TEAM_USAGE_INVALID:{team}:{exc}") from exc
    if usage.player(qb).active is not True:
        raise FootballPropRunError(f"FOOTBALL_PROP_STARTING_QB_UNAVAILABLE:{qb}")
    return usage, names


def _validate_features(
    payload: Mapping[str, Any], *, sport: str, current: datetime,
    feature_ttl_seconds: int,
) -> tuple[str, datetime, list[dict[str, Any]]]:
    if not isinstance(payload, Mapping) or str(payload.get("sport") or "").upper() != sport:
        raise FootballPropRunError("FOOTBALL_PROP_LIVE_FEATURE_PAYLOAD_INVALID")
    source_sha = _sha256(
        payload.get("source_manifest_sha256"),
        "FOOTBALL_PROP_LIVE_FEATURE_SOURCE_SHA256_INVALID",
    )
    asof = _aware(payload.get("asof_ts"), "FOOTBALL_PROP_LIVE_FEATURE_ASOF_INVALID")
    if asof > current:
        raise FootballPropRunError("FOOTBALL_PROP_LIVE_FEATURE_FROM_FUTURE")
    if (current - asof).total_seconds() > int(feature_ttl_seconds):
        raise FootballPropRunError("FOOTBALL_PROP_LIVE_FEATURE_SNAPSHOT_STALE")
    games = payload.get("games")
    if not isinstance(games, list) or not games:
        raise FootballPropRunError("FOOTBALL_PROP_LIVE_FEATURE_GAMES_EMPTY")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in games:
        if not isinstance(raw, Mapping):
            raise FootballPropRunError("FOOTBALL_PROP_LIVE_FEATURE_GAME_INVALID")
        row = dict(raw)
        game_id = str(row.get("game_id") or "").strip()
        if not game_id or game_id in seen:
            raise FootballPropRunError("FOOTBALL_PROP_GAME_ID_MISSING_OR_DUPLICATE")
        seen.add(game_id)
        start = _aware(
            row.get("game_start_ts"), f"FOOTBALL_PROP_GAME_START_INVALID:{game_id}"
        )
        if current >= start:
            raise FootballPropRunError(f"FOOTBALL_PROP_GAME_NOT_PREGAME:{game_id}")
        if asof >= start:
            raise FootballPropRunError(
                f"FOOTBALL_PROP_FEATURE_SNAPSHOT_NOT_PREGAME:{game_id}"
            )
        for field in (
            "home_team", "away_team", "provider_home_team", "provider_away_team"
        ):
            if not str(row.get(field) or "").strip():
                raise FootballPropRunError(
                    f"FOOTBALL_PROP_GAME_IDENTITY_MISSING:{game_id}:{field}"
                )
        out.append(row)
    return source_sha, asof, out


def _event_for_game(
    game: Mapping[str, Any], events: Sequence[Mapping[str, Any]]
) -> Mapping[str, Any]:
    start = _aware(game["game_start_ts"], "FOOTBALL_PROP_GAME_START_INVALID")
    matches = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        if str(event.get("home_team") or "").strip() != str(game["provider_home_team"]).strip():
            continue
        if str(event.get("away_team") or "").strip() != str(game["provider_away_team"]).strip():
            continue
        if _aware(event.get("commence_time"), "FOOTBALL_PROP_EVENT_START_INVALID") == start:
            matches.append(event)
    if len(matches) != 1:
        raise FootballPropRunError(
            f"FOOTBALL_PROP_ODDS_EVENT_COUNT_INVALID:{game['game_id']}:{len(matches)}"
        )
    if not str(matches[0].get("id") or "").strip():
        raise FootballPropRunError("FOOTBALL_PROP_PROVIDER_EVENT_ID_REQUIRED")
    return matches[0]


def _paired_offers(
    *, game: Mapping[str, Any], event: Mapping[str, Any],
    player_names: Mapping[str, str], book_key: str, current: datetime,
    quote_ttl_seconds: int,
) -> list[tuple[dict[str, Any], dict[str, Any], bool]]:
    books = event.get("bookmakers")
    if not isinstance(books, list):
        raise FootballPropRunError("FOOTBALL_PROP_BOOKMAKERS_REQUIRED")
    matched_books = [
        book for book in books
        if isinstance(book, Mapping)
        and str(book.get("key") or "").strip().lower() == book_key.lower()
    ]
    if len(matched_books) != 1:
        raise FootballPropRunError(
            f"FOOTBALL_PROP_BOOKMAKER_COUNT_INVALID:{book_key}:{len(matched_books)}"
        )
    book = matched_books[0]
    markets = book.get("markets")
    if not isinstance(markets, list):
        raise FootballPropRunError("FOOTBALL_PROP_MARKETS_REQUIRED")
    pairs: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
    start = _aware(game["game_start_ts"], "FOOTBALL_PROP_GAME_START_INVALID")
    for market_row in markets:
        if not isinstance(market_row, Mapping):
            continue
        provider_key = str(market_row.get("key") or "").strip()
        stat = PROVIDER_MARKET_TO_STAT.get(provider_key)
        if stat is None:
            continue
        observed = _aware(
            market_row.get("last_update"),
            f"FOOTBALL_PROP_MARKET_LAST_UPDATE_REQUIRED:{provider_key}",
        )
        if observed > current:
            raise FootballPropRunError("FOOTBALL_PROP_QUOTE_FROM_FUTURE")
        if observed >= start:
            raise FootballPropRunError(
                f"FOOTBALL_PROP_QUOTE_NOT_PREGAME:{game['game_id']}"
            )
        stale = (current - observed).total_seconds() > int(quote_ttl_seconds)
        outcomes = market_row.get("outcomes")
        if not isinstance(outcomes, list):
            raise FootballPropRunError(f"FOOTBALL_PROP_OUTCOMES_REQUIRED:{provider_key}")
        grouped: dict[tuple[str, float], dict[str, Mapping[str, Any]]] = {}
        for outcome in outcomes:
            if not isinstance(outcome, Mapping):
                continue
            side = str(outcome.get("name") or "").strip().upper()
            if side not in {"OVER", "UNDER"}:
                continue
            name_key = _norm_name(outcome.get("description"))
            if name_key not in player_names:
                continue
            line = _finite(outcome.get("point"), "FOOTBALL_PROP_LINE_INVALID")
            grouped.setdefault((name_key, line), {})[side] = outcome
        for (name_key, line), sides in grouped.items():
            if set(sides) != {"OVER", "UNDER"}:
                raise FootballPropRunError(
                    f"FOOTBALL_PROP_PAIRED_PRICE_REQUIRED:{provider_key}:{name_key}:{line}"
                )
            player_id = player_names[name_key]
            common = {
                "game_id": str(game["game_id"]), "period": "FG",
                "market": provider_key.upper(), "entity_id": player_id,
                "book_key": book_key, "is_alternate": False, "line": line,
                "provider_market": provider_key, "stat": stat,
                "player_id": player_id,
                "player_name": str(sides["OVER"].get("description") or "").strip(),
                "sportsbook": str(book.get("title") or book_key).strip(),
                "quote_observed_at": observed.isoformat(),
                "provider_event_id": str(event.get("id")),
            }
            over = {
                **common, "side": "OVER",
                "american_odds": _finite(
                    sides["OVER"].get("price"), "FOOTBALL_PROP_AMERICAN_ODDS_INVALID"
                ),
            }
            under = {
                **common, "side": "UNDER",
                "american_odds": _finite(
                    sides["UNDER"].get("price"), "FOOTBALL_PROP_AMERICAN_ODDS_INVALID"
                ),
            }
            american_to_decimal(over["american_odds"])
            american_to_decimal(under["american_odds"])
            pairs.append((over, under, stale))
    return pairs


def _distribution_hash(paths: Sequence[Any]) -> str:
    rows = []
    for path in paths:
        stats = path.player_stats()
        rows.append({player: stats[player] for player in sorted(stats)})
    return canonical_hash(rows)


def run_football_props(
    *, sport: str, now: datetime | str, artifact_payload: Mapping[str, Any],
    expected_artifact_sha256: str, runtime_code_git_sha: str,
    live_features: Mapping[str, Any], odds_snapshot: Mapping[str, Any],
    root_seed: int = 20260909, n_paths: int = 20000,
    book_key: str = "draftkings",
    quote_ttl_seconds: int = DEFAULT_QUOTE_TTL_SECONDS,
    feature_ttl_seconds: int = DEFAULT_FEATURE_TTL_SECONDS,
    floor_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_sport = str(sport or "").strip().upper()
    if resolved_sport not in SUPPORTED_SPORTS:
        raise FootballPropRunError(f"FOOTBALL_PROP_SPORT_UNSUPPORTED:{resolved_sport}")
    current = _aware(now, "FOOTBALL_PROP_NOW_TIMEZONE_REQUIRED")
    if isinstance(n_paths, bool) or int(n_paths) <= 0:
        raise FootballPropRunError("FOOTBALL_PROP_N_PATHS_INVALID")
    if int(quote_ttl_seconds) <= 0 or int(feature_ttl_seconds) <= 0:
        raise FootballPropRunError("FOOTBALL_PROP_TTL_INVALID")
    profiles, artifact_sha, training_sha = _load_artifact(
        artifact_payload, sport=resolved_sport,
        expected_artifact_sha256=expected_artifact_sha256,
        runtime_code_git_sha=runtime_code_git_sha,
    )
    live_sha, live_asof, games = _validate_features(
        live_features, sport=resolved_sport, current=current,
        feature_ttl_seconds=int(feature_ttl_seconds),
    )
    if not isinstance(odds_snapshot, Mapping):
        raise FootballPropRunError("FOOTBALL_PROP_ODDS_SNAPSHOT_REQUIRED")
    snapshot_observed = _aware(
        odds_snapshot.get("observed_at"),
        "FOOTBALL_PROP_ODDS_SNAPSHOT_OBSERVED_AT_REQUIRED",
    )
    if snapshot_observed > current:
        raise FootballPropRunError("FOOTBALL_PROP_ODDS_SNAPSHOT_FROM_FUTURE")
    events = odds_snapshot.get("events")
    if not isinstance(events, list) or not events:
        raise FootballPropRunError("FOOTBALL_PROP_ODDS_EVENTS_EMPTY")
    policy = require_frozen_devig_policy(
        config=floor_config or load_edge_floor_config()
    )

    results: list[dict[str, Any]] = []
    distributions: dict[str, str] = {}
    for game in games:
        game_id = str(game["game_id"])
        home = str(game["home_team"])
        away = str(game["away_team"])
        if home not in profiles or away not in profiles:
            missing = home if home not in profiles else away
            raise FootballPropRunError(f"FOOTBALL_PROP_TEAM_MODEL_PROFILE_MISSING:{missing}")
        home_usage, home_names = _team_usage(game.get("home_usage"), team=home)
        away_usage, away_names = _team_usage(game.get("away_usage"), team=away)
        player_names = dict(home_names)
        for name, player_id in away_names.items():
            if name in player_names and player_names[name] != player_id:
                raise FootballPropRunError(f"FOOTBALL_PROP_PLAYER_NAME_COLLISION:{name}")
            player_names[name] = player_id

        simulator = EngineADrivePlaySimulator(
            game_id=game_id, home_team=home, away_team=away,
            home_profile=profiles[home], away_profile=profiles[away],
            seed=_seed(root_seed, game_id, "ENGINE_A"),
        )
        base_paths = simulator.simulate(int(n_paths))
        attributed = []
        for path in base_paths:
            allocator = EngineBUsageAllocator(
                home_usage, away_usage,
                seed=_seed(root_seed, game_id, "ENGINE_B", path.simulation_id),
            )
            attributed.append(allocator.attribute(path))
        distribution_sha = _distribution_hash(attributed)
        distributions[game_id] = distribution_sha

        event = _event_for_game(game, events)
        for over, under, stale in _paired_offers(
            game=game, event=event, player_names=player_names,
            book_key=book_key, current=current,
            quote_ttl_seconds=int(quote_ttl_seconds),
        ):
            market = derive_player_stat_market(
                attributed, player_id=over["player_id"], stat=over["stat"],
                line=float(over["line"]),
            )
            model_by_side = {
                "OVER": float(market["over"]), "UNDER": float(market["under"])
            }
            push_p = float(market["push"])
            for candidate, opposite in ((over, under), (under, over)):
                model_p = model_by_side[candidate["side"]]
                row = {
                    **candidate, "sport": resolved_sport, "model_p": model_p,
                    "push_p": push_p, "model_artifact_sha256": artifact_sha,
                    "model_code_git_sha": runtime_code_git_sha,
                    "training_source_manifest_sha256": training_sha,
                    "live_feature_source_manifest_sha256": live_sha,
                    "live_feature_asof_ts": live_asof.isoformat(),
                    "distribution_sha256": distribution_sha,
                    "engine_status": "MODEL_PRICED", "bet_status": "BLOCKED",
                    "official_eligible": False,
                }
                if stale:
                    row.update({
                        "fair_market_p": None, "raw_implied_p": None,
                        "edge": None, "ev_per_dollar": None,
                        "devig_method": None,
                        "reason": f"{resolved_sport}_PROP_QUOTE_STALE",
                    })
                else:
                    try:
                        devig = devig_with_policy(candidate, opposite, policy=policy)
                    except DevigError as exc:
                        raise FootballPropRunError(str(exc)) from exc
                    non_push = 1.0 - push_p
                    if non_push <= 0.0:
                        raise FootballPropRunError("FOOTBALL_PROP_SETTLED_SAMPLE_SPACE_EMPTY")
                    settled_model_p = model_p / non_push
                    loss_p = max(0.0, 1.0 - model_p - push_p)
                    decimal_odds = american_to_decimal(candidate["american_odds"])
                    row.update({
                        "fair_market_p": devig.fair_probability_for_decision,
                        "raw_implied_p": devig.selected.candidate_raw_implied,
                        "edge": settled_model_p - devig.fair_probability_for_decision,
                        "ev_per_dollar": model_p * (decimal_odds - 1.0) - loss_p,
                        "devig_method": devig.selected.method,
                        "devig_sensitivity_spread": devig.sensitivity_spread_probability_points,
                        "reason": f"{resolved_sport}_PROP_PROMOTION_EVIDENCE_REQUIRED",
                    })
                results.append(row)

    if not results:
        raise FootballPropRunError("FOOTBALL_PROP_NO_SUPPORTED_PAIRED_MARKETS")
    return {
        "schema_version": FOOTBALL_PROP_MACHINE_VERSION,
        "sport": resolved_sport,
        "generated_at_utc": current.isoformat(),
        "run_status": "BLOCKED_PROMOTION_EVIDENCE_REQUIRED",
        "results": results,
        "summary": {
            "games_seen": sorted(distributions),
            "markets_seen": sorted({row["provider_market"] for row in results}),
            "priced_rows": len(results), "official_bets": 0,
            "blocked_rows": len(results), "n_paths_per_game": int(n_paths),
        },
        "game_distribution_sha256": distributions,
        "governance": {
            "model_market_firewall": True,
            "sportsbook_used_to_create_model_p": False,
            "hit_rates_used_to_create_model_p": False,
            "capper_or_consensus_used_to_create_model_p": False,
            "promotion_changed": False, "truth_gate_changed": False,
            "eligible_changed": False, "football_td_props_in_scope": False,
        },
    }
