"""Extended fail-closed football prop pricing over one shared Engine A path.

This module adds offensive TD, kicker and defender markets without introducing
independent market simulations. Every read-out consumes the same market-blind
Engine A play paths. Offensive player identity is Engine B usage attribution,
kicker outcomes are Engine C resolutions over those paths, and defensive player
identity is Engine B defensive attribution over the same plays.

First/last TD ordering is intentionally not implemented here; those markets need
the complete sport-specific return-score and overtime ordering layer. A provider
row for an unsupported market is ignored only because the authoritative surface
keeps that market NO_ENGINE. A declared supported family fails closed on missing
PIT identity, rates, settlement provenance, or an offered price.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from sportsedge.core.simulate.defense_markets import derive_defender_stat_market
from sportsedge.core.simulate.defense_usage import (
    DefenderUsageProfile,
    EngineBDefenseAllocator,
    TeamDefenseUsageProfile,
)
from sportsedge.core.simulate.kicker_markets import derive_kicker_stat_market
from sportsedge.core.simulate.player_markets import derive_player_stat_market
from sportsedge.core.simulate.special_teams import EngineCSpecialTeamsResolver, SpecialTeamsProfile
from sportsedge.core.simulate.usage import EngineBUsageAllocator
from sportsedge.core.simulate.drive_play import EngineADrivePlaySimulator
from sportsedge.devig import DevigError, devig_with_policy
from sportsedge.edge_floors import FrozenDevigPolicy, load_edge_floor_config, require_frozen_devig_policy
from sportsedge.truth_gate import american_to_decimal

from sportsedge.football_prop_run_machine import (
    DEFAULT_FEATURE_TTL_SECONDS,
    DEFAULT_QUOTE_TTL_SECONDS,
    FOOTBALL_PROP_MACHINE_VERSION,
    SUPPORTED_SPORTS,
    FootballPropRunError,
    _aware,
    _distribution_hash,
    _event_for_game,
    _finite,
    _load_artifact,
    _norm_name,
    _price_economics,
    _seed,
    _team_usage,
    _validate_features,
    canonical_hash,
)

EXTENDED_MACHINE_VERSION = "FOOTBALL_PROP_SHARED_PATH_ABC_DEF_V2"

OFFENSIVE_OU_MARKETS: dict[str, str] = {
    "player_pass_attempts": "pass_attempts",
    "player_pass_completions": "completions",
    "player_pass_interceptions": "interceptions",
    "player_pass_longest_completion": "longest_completion",
    "player_pass_rush_yds": "pass_plus_rush_yards",
    "player_pass_tds": "passing_tds",
    "player_pass_yds": "passing_yards",
    "player_receptions": "receptions",
    "player_reception_longest": "longest_reception",
    "player_reception_tds": "receiving_tds",
    "player_reception_yds": "receiving_yards",
    "player_rush_attempts": "rush_attempts",
    "player_rush_longest": "longest_rush",
    "player_rush_reception_tds": "touchdowns",
    "player_rush_reception_yds": "rush_plus_receiving_yards",
    "player_rush_tds": "rushing_tds",
    "player_rush_yds": "rushing_yards",
}

KICKER_OU_MARKETS: dict[str, str] = {
    "player_field_goals": "field_goals_made",
    "player_kicking_points": "kicking_points",
    "player_pats": "extra_points_made",
}

DEFENDER_OU_MARKETS: dict[str, str] = {
    "player_sacks": "sacks",
    "player_solo_tackles": "solo_tackles",
    "player_tackles_assists": "tackles_assists",
    "player_defensive_interceptions": "interceptions",
}

SCORER_MARKETS = frozenset({"player_anytime_td", "player_tds_over"})

PROVIDER_MARKETS = frozenset(
    set(OFFENSIVE_OU_MARKETS)
    | set(KICKER_OU_MARKETS)
    | set(DEFENDER_OU_MARKETS)
    | set(SCORER_MARKETS)
)


def _book(event: Mapping[str, Any], book_key: str) -> Mapping[str, Any]:
    books = event.get("bookmakers")
    if not isinstance(books, list):
        raise FootballPropRunError("FOOTBALL_PROP_BOOKMAKERS_REQUIRED")
    matches = [
        book for book in books
        if isinstance(book, Mapping)
        and str(book.get("key") or "").strip().lower() == str(book_key).strip().lower()
    ]
    if len(matches) != 1:
        raise FootballPropRunError(
            f"FOOTBALL_PROP_BOOKMAKER_COUNT_INVALID:{book_key}:{len(matches)}"
        )
    return matches[0]


def _market_rows(event: Mapping[str, Any], book_key: str) -> list[Mapping[str, Any]]:
    markets = _book(event, book_key).get("markets")
    if not isinstance(markets, list):
        raise FootballPropRunError("FOOTBALL_PROP_MARKETS_REQUIRED")
    return [row for row in markets if isinstance(row, Mapping)]


def _observed(
    row: Mapping[str, Any], *, provider_key: str, current: datetime,
    game_start: datetime, quote_ttl_seconds: int,
) -> tuple[datetime, bool]:
    observed = _aware(
        row.get("last_update"),
        f"FOOTBALL_PROP_MARKET_LAST_UPDATE_REQUIRED:{provider_key}",
    )
    if observed > current:
        raise FootballPropRunError("FOOTBALL_PROP_QUOTE_FROM_FUTURE")
    if observed >= game_start:
        raise FootballPropRunError("FOOTBALL_PROP_QUOTE_NOT_PREGAME")
    return observed, (current - observed).total_seconds() > int(quote_ttl_seconds)


def _player_id(name_map: Mapping[str, str], raw: Mapping[str, Any]) -> tuple[str, str]:
    name = str(raw.get("description") or "").strip()
    player_id = name_map.get(_norm_name(name))
    if not name or player_id is None:
        raise FootballPropRunError(f"FOOTBALL_PROP_PLAYER_NAME_UNRESOLVED:{name or 'MISSING'}")
    return player_id, name


def _break_even_probability(american_odds: float) -> float:
    return 1.0 / american_to_decimal(float(american_odds))


def _one_sided_economics(*, model_p: float, push_p: float, american_odds: float) -> tuple[float, float]:
    win = _finite(model_p, "FOOTBALL_PROP_WIN_PROBABILITY_INVALID")
    push = _finite(push_p, "FOOTBALL_PROP_PUSH_PROBABILITY_INVALID")
    if not 0 <= win <= 1 or not 0 <= push <= 1 or win + push > 1 + 1e-12:
        raise FootballPropRunError("FOOTBALL_PROP_PROBABILITY_MASS_INVALID")
    settled = 1.0 - push
    if settled <= 0:
        raise FootballPropRunError("FOOTBALL_PROP_SETTLED_SAMPLE_SPACE_EMPTY")
    odds = _finite(american_odds, "FOOTBALL_PROP_ODDS_INVALID")
    if abs(odds) < 100:
        raise FootballPropRunError("FOOTBALL_PROP_ODDS_INVALID")
    profit = american_to_decimal(odds) - 1.0
    loss = max(0.0, 1.0 - win - push)
    ev = win * profit - loss
    kelly = max(0.0, min(1.0, ev / (profit * settled)))
    return ev, kelly


def _ou_offers(
    *,
    event: Mapping[str, Any],
    book_key: str,
    game_start: datetime,
    current: datetime,
    quote_ttl_seconds: int,
    name_maps: Mapping[str, Mapping[str, str]],
) -> list[dict[str, Any]]:
    offers: list[dict[str, Any]] = []
    for row in _market_rows(event, book_key):
        key = str(row.get("key") or "").strip()
        if key in OFFENSIVE_OU_MARKETS:
            family = "OFFENSE"
        elif key in KICKER_OU_MARKETS:
            family = "KICKER"
        elif key in DEFENDER_OU_MARKETS:
            family = "DEFENSE"
        else:
            continue
        _, stale = _observed(
            row, provider_key=key, current=current,
            game_start=game_start, quote_ttl_seconds=quote_ttl_seconds,
        )
        raw_outcomes = row.get("outcomes")
        if not isinstance(raw_outcomes, list):
            raise FootballPropRunError(f"FOOTBALL_PROP_OUTCOMES_REQUIRED:{key}")
        grouped: dict[tuple[str, float], dict[str, dict[str, Any]]] = {}
        names = name_maps[family]
        for raw in raw_outcomes:
            if not isinstance(raw, Mapping):
                continue
            side = str(raw.get("name") or "").strip().upper()
            if side not in {"OVER", "UNDER"}:
                continue
            player_id, player_name = _player_id(names, raw)
            line = _finite(raw.get("point"), f"FOOTBALL_PROP_LINE_INVALID:{key}")
            price = _finite(raw.get("price"), f"FOOTBALL_PROP_PRICE_INVALID:{key}")
            american_to_decimal(price)
            bucket = grouped.setdefault((player_id, line), {})
            if side in bucket:
                raise FootballPropRunError(f"FOOTBALL_PROP_DUPLICATE_SIDE:{key}:{player_id}:{line}:{side}")
            bucket[side] = {
                "player_id": player_id,
                "player_name": player_name,
                "american_odds": price,
            }
        for (player_id, line), sides in grouped.items():
            if not sides:
                continue
            display = sides.get("OVER") or sides.get("UNDER")
            assert display is not None
            offers.append({
                "family": family,
                "provider_market": key,
                "stat": (
                    OFFENSIVE_OU_MARKETS.get(key)
                    or KICKER_OU_MARKETS.get(key)
                    or DEFENDER_OU_MARKETS.get(key)
                ),
                "player_id": player_id,
                "player_name": display["player_name"],
                "line": line,
                "over_price": sides.get("OVER", {}).get("american_odds"),
                "under_price": sides.get("UNDER", {}).get("american_odds"),
                "paired": set(sides) == {"OVER", "UNDER"},
                "stale": bool(stale),
            })
    return offers


def _scorer_offers(
    *,
    event: Mapping[str, Any],
    book_key: str,
    game_start: datetime,
    current: datetime,
    quote_ttl_seconds: int,
    offensive_names: Mapping[str, str],
) -> list[dict[str, Any]]:
    offers: list[dict[str, Any]] = []
    for row in _market_rows(event, book_key):
        key = str(row.get("key") or "").strip()
        if key not in SCORER_MARKETS:
            continue
        _, stale = _observed(
            row, provider_key=key, current=current,
            game_start=game_start, quote_ttl_seconds=quote_ttl_seconds,
        )
        raw_outcomes = row.get("outcomes")
        if not isinstance(raw_outcomes, list):
            raise FootballPropRunError(f"FOOTBALL_PROP_OUTCOMES_REQUIRED:{key}")
        grouped: dict[tuple[str, float], dict[str, float]] = {}
        display: dict[tuple[str, float], str] = {}
        for raw in raw_outcomes:
            if not isinstance(raw, Mapping):
                continue
            raw_side = str(raw.get("name") or "").strip().upper()
            if key == "player_anytime_td":
                if raw_side not in {"YES", "NO"}:
                    continue
                side = raw_side
                line = 0.5
            else:
                if raw_side not in {"OVER", "UNDER"}:
                    continue
                side = raw_side
                line = _finite(raw.get("point"), f"FOOTBALL_PROP_LINE_INVALID:{key}")
            player_id, player_name = _player_id(offensive_names, raw)
            price = _finite(raw.get("price"), f"FOOTBALL_PROP_PRICE_INVALID:{key}")
            american_to_decimal(price)
            bucket_key = (player_id, line)
            bucket = grouped.setdefault(bucket_key, {})
            if side in bucket:
                raise FootballPropRunError(f"FOOTBALL_PROP_DUPLICATE_SIDE:{key}:{player_id}:{side}")
            bucket[side] = price
            display[bucket_key] = player_name
        for (player_id, line), prices in grouped.items():
            primary = "YES" if key == "player_anytime_td" else "OVER"
            opposite = "NO" if primary == "YES" else "UNDER"
            if primary not in prices:
                continue
            offers.append({
                "family": "SCORER",
                "provider_market": key,
                "stat": "touchdowns",
                "player_id": player_id,
                "player_name": display[(player_id, line)],
                "line": line,
                "primary_side": primary,
                "primary_price": prices[primary],
                "opposite_price": prices.get(opposite),
                "paired": opposite in prices,
                "stale": bool(stale),
            })
    return offers


def _special_team_profiles(
    artifact: Mapping[str, Any], game: Mapping[str, Any]
) -> tuple[SpecialTeamsProfile, SpecialTeamsProfile, dict[str, str]]:
    rates = artifact.get("team_special_teams_rates")
    if not isinstance(rates, Mapping):
        raise FootballPropRunError("FOOTBALL_PROP_SPECIAL_TEAMS_RATES_REQUIRED")
    weather = game.get("weather")
    weather = weather if isinstance(weather, Mapping) else {}
    wind = _finite(weather.get("wind_mph", 0.0), "FOOTBALL_PROP_WIND_INVALID")
    roof_closed = weather.get("roof_closed", False)
    if type(roof_closed) is not bool:
        raise FootballPropRunError("FOOTBALL_PROP_ROOF_STATE_INVALID")

    names: dict[str, str] = {}
    out: list[SpecialTeamsProfile] = []
    for side in ("home", "away"):
        team = str(game[f"{side}_team"])
        live = game.get(f"{side}_kicker")
        if not isinstance(live, Mapping):
            raise FootballPropRunError(f"FOOTBALL_PROP_KICKER_CONTEXT_REQUIRED:{team}")
        player_id = str(live.get("player_id") or "").strip()
        player_name = str(live.get("player_name") or "").strip()
        if not player_id or not player_name or type(live.get("active")) is not bool:
            raise FootballPropRunError(f"FOOTBALL_PROP_KICKER_IDENTITY_UNRESOLVED:{team}")
        team_rates = rates.get(team)
        if not isinstance(team_rates, Mapping):
            raise FootballPropRunError(f"FOOTBALL_PROP_SPECIAL_TEAMS_RATE_MISSING:{team}")
        required = (
            "fg_base_skill", "xp_make_rate", "two_point_attempt_rate",
            "two_point_success_rate",
        )
        if any(field not in team_rates for field in required):
            raise FootballPropRunError(f"FOOTBALL_PROP_SPECIAL_TEAMS_RATE_INCOMPLETE:{team}")
        try:
            profile = SpecialTeamsProfile(
                team=team,
                kicker_id=player_id,
                kicker_active=live["active"],
                fg_base_skill=team_rates["fg_base_skill"],
                xp_make_rate=team_rates["xp_make_rate"],
                two_point_attempt_rate=team_rates["two_point_attempt_rate"],
                two_point_success_rate=team_rates["two_point_success_rate"],
                wind_mph=wind,
                roof_closed=roof_closed,
            )
        except (TypeError, ValueError) as exc:
            raise FootballPropRunError(f"FOOTBALL_PROP_SPECIAL_TEAMS_PROFILE_INVALID:{team}:{exc}") from exc
        key = _norm_name(player_name)
        if key in names and names[key] != player_id:
            raise FootballPropRunError(f"FOOTBALL_PROP_PLAYER_NAME_COLLISION:{player_name}")
        names[key] = player_id
        out.append(profile)
    return out[0], out[1], names


def _defense_usage(
    game: Mapping[str, Any]
) -> tuple[TeamDefenseUsageProfile, TeamDefenseUsageProfile, dict[str, str], str]:
    names: dict[str, str] = {}
    profiles: list[TeamDefenseUsageProfile] = []
    settlement_provider = str(game.get("tackle_settlement_provider") or "").strip()
    for side in ("home", "away"):
        team = str(game[f"{side}_team"])
        raw = game.get(f"{side}_defense")
        if not isinstance(raw, Mapping):
            raise FootballPropRunError(f"FOOTBALL_PROP_DEFENSE_USAGE_REQUIRED:{team}")
        players_raw = raw.get("players")
        if not isinstance(players_raw, list) or not players_raw:
            raise FootballPropRunError(f"FOOTBALL_PROP_DEFENSE_PLAYERS_REQUIRED:{team}")
        players: list[DefenderUsageProfile] = []
        for item in players_raw:
            if not isinstance(item, Mapping):
                raise FootballPropRunError("FOOTBALL_PROP_DEFENDER_USAGE_INVALID")
            player_id = str(item.get("player_id") or "").strip()
            player_name = str(item.get("player_name") or "").strip()
            position = str(item.get("position") or "").strip().upper()
            if not player_id or not player_name or not position or type(item.get("active")) is not bool:
                raise FootballPropRunError(f"FOOTBALL_PROP_DEFENDER_IDENTITY_UNRESOLVED:{team}")
            try:
                player = DefenderUsageProfile(
                    player_id=player_id,
                    team=team,
                    position=position,
                    active=item["active"],
                    snap_share=item["snap_share"],
                    tackle_share=item["tackle_share"],
                    assist_share=item["assist_share"],
                    sack_share=item["sack_share"],
                    interception_share=item["interception_share"],
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise FootballPropRunError(f"FOOTBALL_PROP_DEFENDER_USAGE_INVALID:{player_id}:{exc}") from exc
            key = _norm_name(player_name)
            if key in names and names[key] != player_id:
                raise FootballPropRunError(f"FOOTBALL_PROP_PLAYER_NAME_COLLISION:{player_name}")
            names[key] = player_id
            players.append(player)
        try:
            profile = TeamDefenseUsageProfile(
                team=team,
                players=tuple(players),
                assist_probability=raw.get("assist_probability", 0.45),
            )
        except (TypeError, ValueError) as exc:
            raise FootballPropRunError(f"FOOTBALL_PROP_TEAM_DEFENSE_USAGE_INVALID:{team}:{exc}") from exc
        profiles.append(profile)
    return profiles[0], profiles[1], names, settlement_provider


def _devig_pair(
    over_price: float, under_price: float, *, policy: FrozenDevigPolicy,
    game_id: str, book_key: str, offer: Mapping[str, Any],
) -> tuple[float, float, dict[str, Any]]:
    identity = {
        "game_id": game_id, "book_key": book_key, "period": "FG",
        "market": offer["provider_market"], "entity_id": offer["player_id"],
        "line": offer["line"],
    }
    over = {**identity, "side": "OVER", "american_odds": float(over_price)}
    under = {**identity, "side": "UNDER", "american_odds": float(under_price)}
    try:
        result = devig_with_policy(over, under, policy=policy)
        opposite = devig_with_policy(under, over, policy=policy)
    except DevigError as exc:
        raise FootballPropRunError(f"FOOTBALL_PROP_DEVIG_FAILED:{exc}") from exc
    return result.fair_probability_for_decision, opposite.fair_probability_for_decision, {
        "primary_method": result.selected.method,
        "sensitivity_triggered": result.longshot_triggered,
        "sensitivity_max_spread_pp": result.sensitivity_spread_probability_points,
    }


def _scorer_market(paths, *, player_id: str, line: float) -> dict[str, float]:
    return derive_player_stat_market(
        paths, player_id=player_id, stat="touchdowns", line=float(line)
    )


def run_football_extended_props(
    *,
    sport: str,
    now: datetime,
    artifact_payload: Mapping[str, Any],
    expected_artifact_sha256: str,
    runtime_code_git_sha: str,
    live_features: Mapping[str, Any],
    odds_snapshot: Mapping[str, Any],
    root_seed: int = 20260909,
    n_paths: int = 20000,
    book_key: str = "draftkings",
    quote_ttl_seconds: int = DEFAULT_QUOTE_TTL_SECONDS,
    feature_ttl_seconds: int = DEFAULT_FEATURE_TTL_SECONDS,
    floor_path: str = "config/truth_gate_floors.json",
) -> dict[str, Any]:
    resolved = str(sport or "").strip().upper()
    if resolved not in SUPPORTED_SPORTS:
        raise FootballPropRunError(f"FOOTBALL_PROP_SPORT_UNSUPPORTED:{resolved}")
    current = _aware(now, "FOOTBALL_PROP_EXECUTION_TIME_INVALID")
    if isinstance(n_paths, bool) or not isinstance(n_paths, int) or n_paths <= 0:
        raise FootballPropRunError("FOOTBALL_PROP_PATH_COUNT_INVALID")
    profiles, artifact_sha, training_sha = _load_artifact(
        artifact_payload,
        sport=resolved,
        expected_artifact_sha256=expected_artifact_sha256,
        runtime_code_git_sha=runtime_code_git_sha,
    )
    feature_sha, feature_asof, games = _validate_features(
        live_features, sport=resolved, current=current,
        feature_ttl_seconds=feature_ttl_seconds,
    )
    if not isinstance(odds_snapshot, Mapping):
        raise FootballPropRunError("FOOTBALL_PROP_ODDS_SNAPSHOT_REQUIRED")
    snapshot_observed = _aware(
        odds_snapshot.get("observed_at"), "FOOTBALL_PROP_ODDS_SNAPSHOT_ASOF_REQUIRED"
    )
    if snapshot_observed > current:
        raise FootballPropRunError("FOOTBALL_PROP_ODDS_SNAPSHOT_FROM_FUTURE")
    events = odds_snapshot.get("events")
    if not isinstance(events, list):
        raise FootballPropRunError("FOOTBALL_PROP_ODDS_EVENTS_REQUIRED")
    event_rows = [row for row in events if isinstance(row, Mapping)]
    devig_policy = require_frozen_devig_policy(config=load_edge_floor_config(floor_path))

    results: list[dict[str, Any]] = []
    distribution_hashes: dict[str, str] = {}
    for game in games:
        game_id = str(game["game_id"])
        start = _aware(game["game_start_ts"], f"FOOTBALL_PROP_GAME_START_INVALID:{game_id}")
        event = _event_for_game(game, event_rows)
        event_id = str(event["id"])

        home_team = str(game["home_team"])
        away_team = str(game["away_team"])
        try:
            home_drive = profiles[home_team]
            away_drive = profiles[away_team]
        except KeyError as exc:
            raise FootballPropRunError(f"FOOTBALL_PROP_TEAM_DRIVE_PROFILE_MISSING:{game_id}:{exc.args[0]}") from exc

        home_usage, home_names = _team_usage(game.get("home_usage"), team=home_team)
        away_usage, away_names = _team_usage(game.get("away_usage"), team=away_team)
        offensive_names = dict(home_names)
        for key, value in away_names.items():
            if key in offensive_names and offensive_names[key] != value:
                raise FootballPropRunError(f"FOOTBALL_PROP_PLAYER_NAME_COLLISION:{key}")
            offensive_names[key] = value

        rows = _market_rows(event, book_key)
        present_keys = {str(row.get("key") or "").strip() for row in rows}
        need_kicker = bool(present_keys & set(KICKER_OU_MARKETS))
        need_defense = bool(present_keys & set(DEFENDER_OU_MARKETS))

        kicker_names: dict[str, str] = {}
        home_special = away_special = None
        if need_kicker:
            home_special, away_special, kicker_names = _special_team_profiles(artifact_payload, game)

        defender_names: dict[str, str] = {}
        home_defense = away_defense = None
        tackle_provider = ""
        if need_defense:
            home_defense, away_defense, defender_names, tackle_provider = _defense_usage(game)
            if present_keys & {"player_solo_tackles", "player_tackles_assists"} and not tackle_provider:
                raise FootballPropRunError("FOOTBALL_PROP_TACKLE_SETTLEMENT_PROVIDER_REQUIRED")

        name_maps = {
            "OFFENSE": offensive_names,
            "KICKER": kicker_names,
            "DEFENSE": defender_names,
        }
        ou_offers = _ou_offers(
            event=event,
            book_key=book_key,
            game_start=start,
            current=current,
            quote_ttl_seconds=quote_ttl_seconds,
            name_maps=name_maps,
        )
        scorer_offers = _scorer_offers(
            event=event,
            book_key=book_key,
            game_start=start,
            current=current,
            quote_ttl_seconds=quote_ttl_seconds,
            offensive_names=offensive_names,
        )
        if not ou_offers and not scorer_offers:
            continue

        base_sim = EngineADrivePlaySimulator(
            game_id=game_id,
            home_team=home_team,
            away_team=away_team,
            home_profile=home_drive,
            away_profile=away_drive,
            seed=_seed(root_seed, game_id, "ENGINE_A"),
        )
        base_paths = base_sim.simulate(n_paths)
        usage_allocator = EngineBUsageAllocator(
            home_usage, away_usage, seed=_seed(root_seed, game_id, "ENGINE_B_USAGE")
        )
        offensive_paths = usage_allocator.attribute_many(base_paths)

        resolved_paths = None
        if need_kicker:
            assert home_special is not None and away_special is not None
            c_resolver = EngineCSpecialTeamsResolver(
                home_profile=home_special,
                away_profile=away_special,
                seed=_seed(root_seed, game_id, "ENGINE_C_SPECIAL_TEAMS"),
            )
            resolved_paths = c_resolver.resolve_many(base_paths)

        defensive_paths = None
        if need_defense:
            assert home_defense is not None and away_defense is not None
            d_allocator = EngineBDefenseAllocator(
                home_defense,
                away_defense,
                seed=_seed(root_seed, game_id, "ENGINE_B_DEFENSE"),
            )
            defensive_paths = d_allocator.attribute_many(base_paths)

        dist_hash = _distribution_hash(offensive_paths)
        distribution_hashes[game_id] = dist_hash

        for offer in ou_offers:
            family = offer["family"]
            try:
                if family == "OFFENSE":
                    market = derive_player_stat_market(
                        offensive_paths,
                        player_id=offer["player_id"],
                        stat=offer["stat"],
                        line=offer["line"],
                    )
                elif family == "KICKER":
                    assert resolved_paths is not None
                    market = derive_kicker_stat_market(
                        resolved_paths,
                        kicker_id=offer["player_id"],
                        stat=offer["stat"],
                        line=offer["line"],
                    )
                else:
                    assert defensive_paths is not None
                    market = derive_defender_stat_market(
                        defensive_paths,
                        player_id=offer["player_id"],
                        stat=offer["stat"],
                        line=offer["line"],
                        tackle_settlement_provider=tackle_provider or None,
                    )
            except (TypeError, ValueError) as exc:
                raise FootballPropRunError(
                    f"FOOTBALL_PROP_MARKET_DERIVATION_FAILED:{offer['provider_market']}:{offer['player_id']}:{exc}"
                ) from exc

            pricing: list[tuple[str, float, float, float | None, dict[str, Any] | None]] = []
            if offer["paired"]:
                fair_over, fair_under, sensitivity = _devig_pair(
                    offer["over_price"], offer["under_price"], policy=devig_policy,
                    game_id=game_id, book_key=book_key, offer=offer,
                )
                pricing.extend([
                    ("OVER", float(offer["over_price"]), float(market["over"]), fair_over, sensitivity),
                    ("UNDER", float(offer["under_price"]), float(market["under"]), fair_under, sensitivity),
                ])
            else:
                if offer["over_price"] is not None:
                    pricing.append(("OVER", float(offer["over_price"]), float(market["over"]), None, None))
                if offer["under_price"] is not None:
                    pricing.append(("UNDER", float(offer["under_price"]), float(market["under"]), None, None))

            for side, price, model_p, fair_p, sensitivity in pricing:
                stale = bool(offer["stale"])
                edge = ev = kelly = None
                if not stale:
                    if fair_p is not None:
                        edge, ev, kelly = _price_economics(
                            model_p=model_p,
                            push_p=float(market["push"]),
                            american_odds=price,
                            fair_market_p=float(fair_p),
                        )
                    else:
                        ev, kelly = _one_sided_economics(
                            model_p=model_p,
                            push_p=float(market["push"]),
                            american_odds=price,
                        )
                results.append({
                    "sport": resolved,
                    "game_id": game_id,
                    "provider_event_id": event_id,
                    "bookmaker": book_key,
                    "family": family,
                    "provider_market": offer["provider_market"],
                    "market": offer["stat"],
                    "player_id": offer["player_id"],
                    "player_name": offer["player_name"],
                    "side": side,
                    "line": offer["line"],
                    "american_odds": price,
                    "model_p": model_p,
                    "push_p": float(market["push"]),
                    "fair_market_p": None if stale or fair_p is None else float(fair_p),
                    "market_no_vig_p_status": "AVAILABLE_PAIRED" if fair_p is not None else "UNAVAILABLE_ONE_SIDED",
                    "break_even_probability": None if stale else _break_even_probability(price),
                    "paired_price_available": bool(offer["paired"]),
                    "edge": edge,
                    "ev_per_dollar": ev,
                    "kelly_fraction": kelly,
                    "quote_fresh": not stale,
                    "bet_status": "BLOCKED",
                    "official_eligible": False,
                    "reason": f"{resolved}_PROP_QUOTE_STALE" if stale else f"{resolved}_PROP_PROMOTION_EVIDENCE_REQUIRED",
                    "distribution_sha256": dist_hash,
                    "model_artifact_sha256": artifact_sha,
                    "model_training_source_sha256": training_sha,
                    "live_feature_source_sha256": feature_sha,
                    "live_feature_asof": feature_asof.isoformat(),
                    "devig": sensitivity,
                })

        for offer in scorer_offers:
            market = _scorer_market(
                offensive_paths,
                player_id=offer["player_id"],
                line=offer["line"],
            )
            model_p = float(market["over"])
            push_p = float(market["push"])
            stale = bool(offer["stale"])
            fair_market_p = edge = ev = kelly = None
            sensitivity = None
            reason = f"{resolved}_PROP_PROMOTION_EVIDENCE_REQUIRED"
            if stale:
                reason = f"{resolved}_PROP_QUOTE_STALE"
            elif offer["paired"]:
                fair_primary, _, sensitivity = _devig_pair(
                    offer["primary_price"], offer["opposite_price"], policy=devig_policy,
                    game_id=game_id, book_key=book_key, offer=offer,
                )
                fair_market_p = fair_primary
                edge, ev, kelly = _price_economics(
                    model_p=model_p,
                    push_p=push_p,
                    american_odds=float(offer["primary_price"]),
                    fair_market_p=float(fair_primary),
                )
            else:
                ev, kelly = _one_sided_economics(
                    model_p=model_p,
                    push_p=push_p,
                    american_odds=float(offer["primary_price"]),
                )
            results.append({
                "sport": resolved,
                "game_id": game_id,
                "provider_event_id": event_id,
                "bookmaker": book_key,
                "family": "SCORER",
                "provider_market": offer["provider_market"],
                "market": "touchdowns",
                "player_id": offer["player_id"],
                "player_name": offer["player_name"],
                "side": offer["primary_side"],
                "line": offer["line"],
                "american_odds": offer["primary_price"],
                "model_p": model_p,
                "push_p": push_p,
                "fair_market_p": fair_market_p,
                "market_no_vig_p_status": "AVAILABLE_PAIRED" if offer["paired"] else "UNAVAILABLE_ONE_SIDED",
                "break_even_probability": None if stale else _break_even_probability(float(offer["primary_price"])),
                "edge": edge,
                "ev_per_dollar": ev,
                "kelly_fraction": kelly,
                "quote_fresh": not stale,
                "paired_price_available": bool(offer["paired"]),
                "bet_status": "BLOCKED",
                "official_eligible": False,
                "reason": reason,
                "distribution_sha256": dist_hash,
                "model_artifact_sha256": artifact_sha,
                "model_training_source_sha256": training_sha,
                "live_feature_source_sha256": feature_sha,
                "live_feature_asof": feature_asof.isoformat(),
                "devig": sensitivity,
            })

    return {
        "schema_version": "FOOTBALL_PROP_EXTENDED_RUN_V2",
        "machine_version": EXTENDED_MACHINE_VERSION,
        "base_machine_version": FOOTBALL_PROP_MACHINE_VERSION,
        "sport": resolved,
        "run_status": "BLOCKED_PROMOTION_EVIDENCE_REQUIRED",
        "generated_at_utc": current.isoformat(),
        "model_artifact_sha256": artifact_sha,
        "model_training_source_sha256": training_sha,
        "live_feature_source_sha256": feature_sha,
        "live_feature_asof": feature_asof.isoformat(),
        "odds_snapshot_observed_at": snapshot_observed.isoformat(),
        "root_seed": root_seed,
        "n_paths": n_paths,
        "game_distribution_sha256": distribution_hashes,
        "results": results,
        "summary": {
            "games_modeled": len(distribution_hashes),
            "decisions": len(results),
            "official_bets": 0,
        },
        "governance": {
            "model_market_firewall": True,
            "single_shared_engine_a_path_per_game": True,
            "offense_engine_b_on_shared_path": True,
            "kicker_engine_c_on_shared_path": True,
            "defense_engine_b_on_shared_path": True,
            "sportsbook_used_to_create_model_p": False,
            "one_sided_market_opposite_price_invented": False,
            "one_sided_model_p_plus_offered_price_ev_enabled": True,
            "promotion_changed": False,
            "eligible_changed": False,
            "official_bets_allowed": False,
            "devig_primary_method": devig_policy.stable_candidate_estimator,
        },
    }
