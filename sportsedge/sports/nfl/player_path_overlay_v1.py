"""Research-only same-seed NFL player outcome overlay for V2K game paths.

The goal is not to price a prop from a marginal bucket.  It is to create player
outcomes inside each already-simulated game world so an SGP can be evaluated on
the same path.  Team play volume is conditioned on simulated offensive-drive
count; offensive touchdowns are allocated within the team path.  Inputs are
football projections only and market-derived fields are rejected.

V1 supports the player markets needed by the SGP engine: receptions, receiving
and rushing yards, rush attempts, rush+rec yards, and anytime touchdowns.  It is
research-only and grants no OFFICIAL/Truth-Gate/staking authority.
"""

from __future__ import annotations

from math import isfinite, sqrt
from random import Random
from typing import Any, Mapping, Sequence


MODEL_ID = "NFL_PLAYER_PATH_OVERLAY_V1"
STATUS = "RESEARCH_ONLY_SAME_PATH"
_BANNED_KEYS = {
    "odds",
    "price",
    "line",
    "spread",
    "total",
    "sportsbook",
    "book",
    "american_odds",
    "decimal_odds",
    "implied_probability",
    "fair_odds",
    "edge",
    "ev",
}


class NFLPlayerPathOverlayError(ValueError):
    pass


def _reject_market_inputs(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in _BANNED_KEYS or any(
                token in normalized
                for token in ("sportsbook", "market_price", "closing_odds", "opening_odds")
            ):
                raise NFLPlayerPathOverlayError(f"MARKET_INPUT_FORBIDDEN:{key}")
            _reject_market_inputs(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_market_inputs(child)


def _finite(value: Any, error: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NFLPlayerPathOverlayError(error) from exc
    if not isfinite(out):
        raise NFLPlayerPathOverlayError(error)
    return out


def _probability(value: Any, error: str) -> float:
    out = _finite(value, error)
    if not 0.0 <= out <= 1.0:
        raise NFLPlayerPathOverlayError(error)
    return out


def _draw_binomial(n: int, p: float, rng: Random) -> int:
    if n <= 0 or p <= 0.0:
        return 0
    if p >= 1.0:
        return n
    return sum(rng.random() < p for _ in range(n))


def _weighted_choice(weights: Sequence[tuple[str, float]], rng: Random) -> str | None:
    positive = [(key, float(weight)) for key, weight in weights if float(weight) > 0.0]
    total = sum(weight for _, weight in positive)
    if total <= 0.0:
        return None
    u = rng.random() * total
    running = 0.0
    for key, weight in positive:
        running += weight
        if u <= running:
            return key
    return positive[-1][0]


def _allocate_count(count: int, shares: Mapping[str, float], rng: Random) -> dict[str, int]:
    allocation = {key: 0 for key in shares}
    if count <= 0:
        return allocation
    share_sum = sum(max(0.0, float(value)) for value in shares.values())
    if share_sum > 1.0 + 1e-9:
        raise NFLPlayerPathOverlayError("PLAYER_ROLE_SHARES_EXCEED_ONE")
    weights = [(key, max(0.0, float(value))) for key, value in shares.items()]
    other = max(0.0, 1.0 - share_sum)
    if other > 0.0:
        weights.append(("__OTHER__", other))
    for _ in range(count):
        selected = _weighted_choice(weights, rng)
        if selected is not None and selected != "__OTHER__":
            allocation[selected] += 1
    return allocation


def _offensive_drive_counts(path: Mapping[str, Any]) -> dict[str, int]:
    teams = [str(path.get("home_team") or ""), str(path.get("away_team") or "")]
    if not all(teams) or teams[0] == teams[1]:
        raise NFLPlayerPathOverlayError("PLAYER_PATH_TEAM_IDENTITY_INVALID")
    counts = {team: 0 for team in teams}
    drives = path.get("drive_path")
    if not isinstance(drives, Sequence) or isinstance(drives, (str, bytes)):
        raise NFLPlayerPathOverlayError("PLAYER_PATH_DRIVES_REQUIRED")
    for drive in drives:
        if not isinstance(drive, Mapping):
            raise NFLPlayerPathOverlayError("PLAYER_PATH_DRIVE_INVALID")
        offense = str(drive.get("offense") or "")
        if offense in counts:
            counts[offense] += 1
    return counts


def _offensive_td_counts(path: Mapping[str, Any]) -> dict[str, int]:
    teams = [str(path.get("home_team") or ""), str(path.get("away_team") or "")]
    counts = {team: 0 for team in teams}
    drives = path.get("drive_path")
    if not isinstance(drives, Sequence) or isinstance(drives, (str, bytes)):
        raise NFLPlayerPathOverlayError("PLAYER_PATH_DRIVES_REQUIRED")
    for drive in drives:
        if not isinstance(drive, Mapping):
            continue
        offense = str(drive.get("offense") or "")
        if offense in counts and str(drive.get("outcome") or "").upper() == "TD":
            counts[offense] += 1
    return counts


def _validate_profile(team: str, profile: Mapping[str, Any]) -> dict[str, Any]:
    plays_mean = _finite(profile.get("plays_mean"), f"PLAYS_MEAN_INVALID:{team}")
    plays_sd = _finite(profile.get("plays_sd", sqrt(max(plays_mean, 1.0))), f"PLAYS_SD_INVALID:{team}")
    pass_rate = _probability(profile.get("pass_rate"), f"PASS_RATE_INVALID:{team}")
    targetable = _probability(
        profile.get("targetable_pass_rate", 0.90), f"TARGETABLE_PASS_RATE_INVALID:{team}"
    )
    expected_drives = _finite(profile.get("expected_offensive_drives", 10.5), f"EXPECTED_DRIVES_INVALID:{team}")
    if plays_mean <= 0.0 or plays_sd <= 0.0 or expected_drives <= 0.0:
        raise NFLPlayerPathOverlayError(f"TEAM_VOLUME_INVALID:{team}")
    players = profile.get("players")
    if not isinstance(players, Mapping) or not players:
        raise NFLPlayerPathOverlayError(f"PLAYERS_REQUIRED:{team}")

    normalized_players: dict[str, dict[str, float]] = {}
    for player, raw in players.items():
        if not isinstance(raw, Mapping):
            raise NFLPlayerPathOverlayError(f"PLAYER_PROFILE_INVALID:{player}")
        normalized_players[str(player)] = {
            "target_share": _probability(raw.get("target_share", 0.0), f"TARGET_SHARE_INVALID:{player}"),
            "catch_rate": _probability(raw.get("catch_rate", 0.0), f"CATCH_RATE_INVALID:{player}"),
            "yards_per_reception": max(0.0, _finite(raw.get("yards_per_reception", 0.0), f"YPR_INVALID:{player}")),
            "yards_per_reception_sd": max(
                0.01,
                _finite(
                    raw.get("yards_per_reception_sd", max(2.5, float(raw.get("yards_per_reception", 0.0)) * 0.35)),
                    f"YPR_SD_INVALID:{player}",
                ),
            ),
            "rush_share": _probability(raw.get("rush_share", 0.0), f"RUSH_SHARE_INVALID:{player}"),
            "yards_per_carry": max(0.0, _finite(raw.get("yards_per_carry", 0.0), f"YPC_INVALID:{player}")),
            "yards_per_carry_sd": max(
                0.01,
                _finite(
                    raw.get("yards_per_carry_sd", max(1.5, float(raw.get("yards_per_carry", 0.0)) * 0.50)),
                    f"YPC_SD_INVALID:{player}",
                ),
            ),
            "td_share": _probability(raw.get("td_share", 0.0), f"TD_SHARE_INVALID:{player}"),
        }

    for key in ("target_share", "rush_share", "td_share"):
        if sum(row[key] for row in normalized_players.values()) > 1.0 + 1e-9:
            raise NFLPlayerPathOverlayError(f"PLAYER_ROLE_SHARES_EXCEED_ONE:{team}:{key}")

    return {
        "plays_mean": plays_mean,
        "plays_sd": plays_sd,
        "pass_rate": pass_rate,
        "targetable_pass_rate": targetable,
        "expected_offensive_drives": expected_drives,
        "players": normalized_players,
    }


def simulate_player_stats_for_path(
    path: Mapping[str, Any],
    team_profiles: Mapping[str, Mapping[str, Any]],
    *,
    seed_salt: int = 9102026,
) -> dict[str, dict[str, Any]]:
    """Generate player outcomes conditional on one game simulation path."""
    _reject_market_inputs(team_profiles)
    if "simulation_seed" not in path:
        raise NFLPlayerPathOverlayError("PLAYER_PATH_SIMULATION_SEED_REQUIRED")
    seed = int(path["simulation_seed"])
    rng = Random(seed ^ int(seed_salt))
    drive_counts = _offensive_drive_counts(path)
    td_counts = _offensive_td_counts(path)
    output: dict[str, dict[str, Any]] = {}

    for team in (str(path.get("home_team") or ""), str(path.get("away_team") or "")):
        raw_profile = team_profiles.get(team)
        if not isinstance(raw_profile, Mapping):
            raise NFLPlayerPathOverlayError(f"TEAM_PROFILE_REQUIRED:{team}")
        profile = _validate_profile(team, raw_profile)
        drive_factor = max(0.25, drive_counts[team] / profile["expected_offensive_drives"])
        plays_mean = profile["plays_mean"] * drive_factor
        plays_sd = profile["plays_sd"] * sqrt(drive_factor)
        plays = max(1, int(round(rng.gauss(plays_mean, plays_sd))))
        pass_attempts = _draw_binomial(plays, profile["pass_rate"], rng)
        rush_attempts = max(0, plays - pass_attempts)
        targetable_attempts = _draw_binomial(pass_attempts, profile["targetable_pass_rate"], rng)

        players: Mapping[str, Mapping[str, float]] = profile["players"]
        targets = _allocate_count(
            targetable_attempts, {player: row["target_share"] for player, row in players.items()}, rng
        )
        carries = _allocate_count(
            rush_attempts, {player: row["rush_share"] for player, row in players.items()}, rng
        )
        touchdowns = _allocate_count(
            td_counts[team], {player: row["td_share"] for player, row in players.items()}, rng
        )

        for player, row in players.items():
            player_targets = targets[player]
            receptions = _draw_binomial(player_targets, row["catch_rate"], rng)
            receiving_yards = sum(
                max(0.0, rng.gauss(row["yards_per_reception"], row["yards_per_reception_sd"]))
                for _ in range(receptions)
            )
            player_carries = carries[player]
            rushing_yards = sum(
                max(0.0, rng.gauss(row["yards_per_carry"], row["yards_per_carry_sd"]))
                for _ in range(player_carries)
            )
            output[player] = {
                "player_name": player,
                "team": team,
                "targets": player_targets,
                "receptions": receptions,
                "receiving_yards": receiving_yards,
                "rush_attempts": player_carries,
                "rushing_yards": rushing_yards,
                "touchdowns": touchdowns[player],
                "rush_rec_yards": rushing_yards + receiving_yards,
                "model_id": MODEL_ID,
                "status": STATUS,
                "simulation_seed": seed,
            }
    return output


def simulate_player_overlays_by_seed(
    paths: Sequence[Mapping[str, Any]],
    team_profiles: Mapping[str, Mapping[str, Any]],
    *,
    seed_salt: int = 9102026,
) -> dict[int, dict[str, dict[str, Any]]]:
    """Build seed-keyed overlays consumable by ``attach_player_stats_by_seed``."""
    overlays: dict[int, dict[str, dict[str, Any]]] = {}
    for path in paths:
        if "simulation_seed" not in path:
            raise NFLPlayerPathOverlayError("PLAYER_PATH_SIMULATION_SEED_REQUIRED")
        seed = int(path["simulation_seed"])
        if seed in overlays:
            raise NFLPlayerPathOverlayError("PLAYER_PATH_DUPLICATE_SIMULATION_SEED")
        overlays[seed] = simulate_player_stats_for_path(
            path, team_profiles, seed_salt=seed_salt
        )
    return overlays
