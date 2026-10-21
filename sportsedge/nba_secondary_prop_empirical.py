"""New NBA secondary-prop empirical RESEARCH challenger, never PLAY.

This is NOT a revision of the frozen PTS/REB/AST/PRA forward test or a
scored NBA model. It uses the same predeclared empirical mixture recipe
(k=5) but independently screens new stat families. Actual same-game
player box outcomes are the source of stocks, double-doubles and
triple-doubles; no independent-stat product or synthetic correlation.

No minute or participation model exists. Predictions condition on the
player having played. No market quote, identity/binder or eligibility
path is provided.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
import re
from typing import Any, Mapping, Sequence

from .source_lineage import canonical_json_sha256

VERSION = "NBA_SECONDARY_PROPS_EMPIRICAL_MIXTURE_V1_K5"
PLAYER_K = 5
MIN_PLAYER_PRIOR_GAMES = 10
MIN_POSITION_POOL_GAMES = 30
STATS = ("points", "rebounds", "assists", "steals", "blocks",
         "turnovers", "three_pointers")
FAMILIES = frozenset({
    "THREE_POINTERS", "STEALS", "BLOCKS", "TURNOVERS",
    "STEALS_PLUS_BLOCKS", "DOUBLE_DOUBLE", "TRIPLE_DOUBLE",
})
ID = re.compile(r"^[A-Za-z0-9:_-]{1,100}$")
HASH = re.compile(r"^[a-fA-F0-9]{64}$")


class NBASecondaryError(ValueError):
    """Named evidence/model refusal."""


@dataclass(frozen=True)
class NBASecondaryReadout:
    family: str
    player_id: str
    game_id: str
    selection: str
    line: float | None
    probability: float
    push_probability: float
    history_sha256: str
    readout_sha256: str
    pool_player_n: int
    pool_position_n: int
    pool_scope: str
    version: str = VERSION
    status: str = "RESEARCH_UNSCREENED_NEW_FAMILY"
    eligible: bool = False
    research_only: bool = True
    market_test: str = "NO_MARKET_TEST"
    conditional_on_participation: bool = True
    participation_model_verified: bool = False
    play_authority: bool = False
    staking_authority: bool = False


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise NBASecondaryError(f"{field}_IDENTITY_REQUIRED")
    return value


def _time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise NBASecondaryError(f"{field}_UTC_REQUIRED")
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NBASecondaryError(f"{field}_UTC_INVALID") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise NBASecondaryError(f"{field}_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)


def _row(row: Mapping[str, Any]) -> dict:
    if not isinstance(row, Mapping):
        raise NBASecondaryError("PLAYER_GAME_ROW_REQUIRED")
    season = row.get("season_start_year")
    if type(season) is not int or not 2000 <= season <= 2100:
        raise NBASecondaryError("SEASON_YEAR_INVALID")
    position = row.get("position_group")
    if position not in ("G", "F", "C"):
        raise NBASecondaryError("POSITION_GROUP_UNVERIFIED")
    stats = {}
    for stat in STATS:
        value = row.get(stat)
        if type(value) is not int or value < 0:
            raise NBASecondaryError(f"{stat.upper()}_OBSERVATION_INVALID")
        stats[stat] = value
    if stats["three_pointers"] * 3 > stats["points"]:
        raise NBASecondaryError("THREE_POINTERS_IMPOSSIBLE_POINTS")
    minutes = row.get("minutes")
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)):
        raise NBASecondaryError("MINUTES_NOT_OBSERVED")
    m = float(minutes)
    if not isfinite(m) or not 0 <= m <= 75:
        raise NBASecondaryError("MINUTES_INVALID")
    if m == 0 and any(stats.values()):
        raise NBASecondaryError("DNP_HAS_NONZERO_BOX_STATS")
    digest = row.get("snapshot_sha256")
    if not isinstance(digest, str) or not HASH.fullmatch(digest):
        raise NBASecondaryError("BOX_SOURCE_HASH_REQUIRED")
    start = _time(row.get("game_start_utc"), "GAME_START")
    observed = _time(row.get("result_observed_utc"), "RESULT_OBSERVED")
    if observed <= start:
        raise NBASecondaryError("RESULT_OBSERVED_BEFORE_GAME")
    return {
        "game_id": _id(row.get("game_id"), "GAME"),
        "player_id": _id(row.get("player_id"), "PLAYER"),
        "team_id": _id(row.get("team_id"), "TEAM"),
        "season_start_year": season, "position_group": position,
        "game_start": start, "observed": observed,
        "snapshot_sha256": digest.lower(), "minutes": m,
        **stats,
    }


def _value(r: Mapping[str, Any], family: str) -> int:
    if family == "THREE_POINTERS":
        return r["three_pointers"]
    if family == "STEALS":
        return r["steals"]
    if family == "BLOCKS":
        return r["blocks"]
    if family == "TURNOVERS":
        return r["turnovers"]
    if family == "STEALS_PLUS_BLOCKS":
        return r["steals"] + r["blocks"]
    buckets = (r["points"], r["rebounds"], r["assists"],
               r["steals"], r["blocks"])
    return int(sum(x >= 10 for x in buckets) >= (
        2 if family == "DOUBLE_DOUBLE" else 3))


def research_nba_secondary_readout(
    *, rows: Sequence[Mapping[str, Any]],
    game_id: str, player_id: str, position_group: str,
    season_start_year: int, target_start_utc: str, as_of_utc: str,
    family: str, selection: str, line: Any = None,
) -> NBASecondaryReadout:
    """Point-in-time outcome distribution over games with actual minutes>0.

    Certified source archive, player identity, target active participation
    and independent DK market lines are outside this function's authority.
    """
    fid = _id(game_id, "TARGET_GAME")
    pid = _id(player_id, "TARGET_PLAYER")
    if position_group not in ("G", "F", "C"):
        raise NBASecondaryError("TARGET_POSITION_UNVERIFIED")
    if type(season_start_year) is not int:
        raise NBASecondaryError("TARGET_SEASON_INVALID")
    target = _time(target_start_utc, "TARGET_START")
    asof = _time(as_of_utc, "AS_OF")
    if asof >= target:
        raise NBASecondaryError("AS_OF_AT_OR_AFTER_GAME_START")
    family = str(family or "").upper().strip()
    if family not in FAMILIES:
        raise NBASecondaryError("SECONDARY_FAMILY_UNREGISTERED")
    selection = str(selection or "").upper().strip()
    if family in ("DOUBLE_DOUBLE", "TRIPLE_DOUBLE"):
        if selection not in ("YES", "NO") or line is not None:
            raise NBASecondaryError("MILESTONE_REQUIRES_YES_NO_NO_LINE")
        resolved_line = None
    else:
        if selection not in ("OVER", "UNDER") or (
                isinstance(line, bool) or line is None):
            raise NBASecondaryError("COUNT_PROP_OVER_UNDER_LINE_REQUIRED")
        try:
            resolved_line = float(line)
        except (ValueError, TypeError) as exc:
            raise NBASecondaryError("COUNT_PROP_LINE_INVALID") from exc
        if (not isfinite(resolved_line) or not 0 <= resolved_line <= 100
                or resolved_line % 1 not in (0.0, 0.5)):
            raise NBASecondaryError("COUNT_PROP_LINE_UNSUPPORTED")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise NBASecondaryError("OBSERVATION_ROWS_REQUIRED")
    checked = []
    seen = set()
    for raw in rows:
        r = _row(raw)
        identity = (r["game_id"], r["player_id"])
        if identity in seen:
            raise NBASecondaryError("DUPLICATE_PLAYER_GAME_RECORD")
        seen.add(identity)
        if r["game_id"] == fid:
            raise NBASecondaryError("TARGET_GAME_RESULT_LEAKAGE")
        if r["game_start"] >= target or (
                r["game_start"].date() >= target.date()):
            raise NBASecondaryError("FUTURE_OR_SAME_DATE_GAME_RESULT")
        if r["observed"] > asof:
            raise NBASecondaryError("RESULT_UNAVAILABLE_AT_ASOF")
        if r["season_start_year"] != season_start_year or r["minutes"] == 0:
            continue
        checked.append(r)
    own = [r for r in checked if r["player_id"] == pid]
    if len(own) < MIN_PLAYER_PRIOR_GAMES:
        raise NBASecondaryError("INSUFFICIENT_SAME_SEASON_PLAYER_HISTORY")
    if any(r["position_group"] != position_group for r in own):
        raise NBASecondaryError("PLAYER_POSITION_CONTRADICTION")
    league_pos = [r for r in checked if r["position_group"] == position_group]
    pool = league_pos if len(league_pos) >= MIN_POSITION_POOL_GAMES else checked
    scope = ("POSITION" if pool is league_pos else "LEAGUE_OVERALL_FALLBACK")
    if len(pool) < MIN_POSITION_POOL_GAMES:
        raise NBASecondaryError("INSUFFICIENT_PRIOR_COMPARISON_POOL")
    weight_own = len(own) / (len(own) + PLAYER_K)
    def mass(data):
        vals = [_value(r, family) for r in data]
        if resolved_line is None:
            return sum(x == 1 for x in vals) / len(vals)
        return sum(x > resolved_line for x in vals) / len(vals)
    yes_mass = weight_own * mass(own) + (1 - weight_own) * mass(pool)
    if resolved_line is None:
        pwin = yes_mass if selection == "YES" else 1 - yes_mass
        ppush = 0.0
    else:
        def push_mass(data):
            return sum(_value(r, family) == resolved_line for r in data) / len(data)
        ppush = (weight_own * push_mass(own) +
                 (1 - weight_own) * push_mass(pool))
        if selection == "OVER":
            pwin = yes_mass
        else:
            pwin = 1 - yes_mass - ppush
    if min(pwin, ppush) < -1e-12 or pwin + ppush > 1 + 1e-12:
        raise NBASecondaryError("INVALID_MIXTURE_PROBABILITY_MASS")
    material_rows = sorted([
        {"game_id": r["game_id"], "player_id": r["player_id"],
         "team_id": r["team_id"],
         "season_start_year": r["season_start_year"],
         "position_group": r["position_group"],
         "minutes": r["minutes"],
         "game_start_utc": r["game_start"].isoformat(),
         "source_sha256": r["snapshot_sha256"],
         "observed_at_utc": r["observed"].isoformat(),
         "stats": {stat: r[stat] for stat in STATS}}
        for r in checked], key=lambda r: (r["game_id"], r["player_id"]))
    source_hash = canonical_json_sha256({
        "version": VERSION, "as_of_utc": asof.isoformat(),
        "game_id": fid, "season": season_start_year, "rows": material_rows})
    outcome_hash = canonical_json_sha256({
        "source_sha256": source_hash, "player_id": pid,
        "family": family, "side": selection,
        "line": resolved_line, "probability": float(pwin),
        "push_probability": float(ppush), "position_group": position_group,
        "pool_scope": scope})
    return NBASecondaryReadout(
        family=family, player_id=pid, game_id=fid,
        selection=selection, line=resolved_line,
        probability=float(pwin), push_probability=float(ppush),
        history_sha256=source_hash, readout_sha256=outcome_hash,
        pool_player_n=len(own), pool_position_n=len(pool),
        pool_scope=scope)
