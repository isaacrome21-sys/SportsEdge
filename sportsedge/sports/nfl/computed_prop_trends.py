"""Compute NFL prop trend context from governed game-level statistics.

This module deliberately does not ingest rendered competitor analytics or
precomputed hit-rate summaries.  It derives L5/L10/L20/season/H2H results from
per-game player rows joined to the authoritative SportsEdge NFL schedule path.
The output is a research/context sidecar only: it cannot create or alter
Model_P, satisfy Truth Gate, change EV/Kelly, or promote a wager.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
import json
import math
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.request import Request, urlopen

from .auto_context_source import _fetch_schedule, _kickoff, _team


COMPUTE_CONTRACT = "NFL_COMPUTED_PROP_TRENDS_V1"
NFLVERSE_PLAYER_STATS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "stats_player/stats_player_week_{season}.csv"
)

MODEL_P_ELIGIBLE = False
TRUTH_GATE_ELIGIBLE = False
DECISION_EFFECT = "NONE"

SUPPORTED_SIDES = frozenset({"OVER", "UNDER"})
MARKET_STAT_FIELDS: dict[str, str] = {
    "RECEPTIONS": "receptions",
    "RECEIVING_YARDS": "receiving_yards",
    "TARGETS": "targets",
    "RUSHING_YARDS": "rushing_yards",
    "RUSH_ATTEMPTS": "carries",
    "PASSING_YARDS": "passing_yards",
    "PASS_ATTEMPTS": "attempts",
    "COMPLETIONS": "completions",
    "PASSING_TDS": "passing_tds",
    "INTERCEPTIONS": "passing_interceptions",
}

REQUIRED_PLAYER_COLUMNS = frozenset(
    {
        "player_id",
        "season",
        "week",
        "season_type",
        "game_id",
        "team",
        "opponent_team",
    }
)

# A source row that already contains a prop hit-rate summary is not a raw
# game-log row for this contract.  Reject it rather than accidentally treating
# someone else's rendered trend as our own computation.
FORBIDDEN_PRECOMPUTED_FIELDS = frozenset(
    {
        "hit_rate",
        "hit_rate_pct",
        "historical_hit_rate",
        "reported_pct",
        "trend_hit_rate",
        "l5_hit_rate",
        "l10_hit_rate",
        "l20_hit_rate",
        "season_hit_rate",
        "h2h_hit_rate",
    }
)


class ComputedPropTrendError(ValueError):
    pass


@dataclass(frozen=True)
class SourceProof:
    season: int
    source_uri: str
    source_sha256: str


@dataclass(frozen=True)
class PlayerStatsAcquisition:
    rows: tuple[Mapping[str, Any], ...]
    sources: tuple[SourceProof, ...]


@dataclass(frozen=True)
class GameSettlement:
    game_id: str
    kickoff_ts: str
    season: int
    week: int
    team_id: str
    opponent_team_id: str
    value: float
    outcome: str


@dataclass(frozen=True)
class TrendWindow:
    label: str
    wins: int
    losses: int
    pushes: int
    attempts: int
    decisions: int
    hit_rate_pct: float | None


@dataclass(frozen=True)
class ComputedPropTrendSnapshot:
    contract: str
    as_of: datetime
    player_id: str
    opponent_team_id: str
    market_id: str
    side: str
    line: float
    stat_field: str
    windows: tuple[TrendWindow, ...]
    games: tuple[GameSettlement, ...]
    player_sources: tuple[SourceProof, ...]
    schedule_source_uri: str
    schedule_source_sha256: str
    content_hash: str
    model_p_eligible: bool = field(default=False, init=False)
    truth_gate_eligible: bool = field(default=False, init=False)
    decision_effect: str = field(default="NONE", init=False)
    historical_hit_rate_is_probability: bool = field(default=False, init=False)


@dataclass(frozen=True)
class PropTrendMatch:
    state: str
    reasons: tuple[str, ...]
    snapshot: ComputedPropTrendSnapshot | None
    line_delta: float | None


def _utc(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        try:
            out = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ComputedPropTrendError(f"INVALID_TIMESTAMP:{field_name}") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise ComputedPropTrendError(f"TIMEZONE_REQUIRED:{field_name}")
    return out.astimezone(timezone.utc)


def _required_text(value: Any, field_name: str) -> str:
    out = str(value or "").strip()
    if not out:
        raise ComputedPropTrendError(f"MISSING_IDENTITY:{field_name}")
    return out


def _integer(value: Any, field_name: str) -> int:
    try:
        parsed = float(value)
        out = int(parsed)
    except (TypeError, ValueError) as exc:
        raise ComputedPropTrendError(f"INVALID_INTEGER:{field_name}") from exc
    if not math.isfinite(parsed) or parsed != out:
        raise ComputedPropTrendError(f"INVALID_INTEGER:{field_name}")
    return out


def _finite(value: Any, field_name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ComputedPropTrendError(f"INVALID_NUMBER:{field_name}") from exc
    if not math.isfinite(out):
        raise ComputedPropTrendError(f"INVALID_NUMBER:{field_name}")
    return out


def _sha(value: Any, field_name: str) -> str:
    out = str(value or "").strip().lower()
    if len(out) != 64:
        raise ComputedPropTrendError(f"INVALID_SHA256:{field_name}")
    try:
        int(out, 16)
    except ValueError as exc:
        raise ComputedPropTrendError(f"INVALID_SHA256:{field_name}") from exc
    return out


def _https(value: Any, field_name: str) -> str:
    out = _required_text(value, field_name)
    if not out.startswith("https://"):
        raise ComputedPropTrendError(f"HTTPS_SOURCE_REQUIRED:{field_name}")
    return out


def _settle(value: float, *, line: float, side: str) -> str:
    if value == line:
        return "PUSH"
    if side == "OVER":
        return "WIN" if value > line else "LOSS"
    return "WIN" if value < line else "LOSS"


def _window(label: str, games: Sequence[GameSettlement]) -> TrendWindow:
    wins = sum(game.outcome == "WIN" for game in games)
    losses = sum(game.outcome == "LOSS" for game in games)
    pushes = sum(game.outcome == "PUSH" for game in games)
    attempts = len(games)
    decisions = wins + losses
    rate = None if decisions == 0 else 100.0 * wins / decisions
    return TrendWindow(
        label=label,
        wins=wins,
        losses=losses,
        pushes=pushes,
        attempts=attempts,
        decisions=decisions,
        hit_rate_pct=rate,
    )


def _source_map(proofs: Iterable[SourceProof]) -> dict[int, SourceProof]:
    out: dict[int, SourceProof] = {}
    for proof in proofs:
        season = int(proof.season)
        normalized = SourceProof(
            season=season,
            source_uri=_https(proof.source_uri, f"player_source_uri:{season}"),
            source_sha256=_sha(proof.source_sha256, f"player_source_sha256:{season}"),
        )
        if season in out and out[season] != normalized:
            raise ComputedPropTrendError(f"CONTRADICTORY_SOURCE_PROOF:{season}")
        out[season] = normalized
    return out


def fetch_nflverse_weekly_player_stats(
    *,
    seasons: Iterable[int],
    opener: Callable = urlopen,
) -> PlayerStatsAcquisition:
    """Fetch nflverse weekly player-stat CSVs with exact-byte provenance.

    A missing season is an explicit acquisition failure.  The caller may choose
    which seasons are required; this function never substitutes another year or
    manufactures a current-season row.
    """

    wanted = sorted({int(season) for season in seasons})
    if not wanted:
        raise ComputedPropTrendError("PLAYER_STATS_SEASONS_REQUIRED")
    rows: list[Mapping[str, Any]] = []
    proofs: list[SourceProof] = []
    for season in wanted:
        uri = NFLVERSE_PLAYER_STATS_URL.format(season=season)
        request = Request(uri, headers={"User-Agent": "SportsEdge/1.0", "Accept": "text/csv"})
        try:
            with opener(request, timeout=25) as response:
                raw = response.read()
        except Exception as exc:
            raise ComputedPropTrendError(f"NFLVERSE_PLAYER_STATS_FETCH_FAILED:{season}") from exc
        try:
            parsed = [dict(row) for row in csv.DictReader(StringIO(raw.decode("utf-8-sig")))]
        except Exception as exc:
            raise ComputedPropTrendError(f"NFLVERSE_PLAYER_STATS_CSV_INVALID:{season}") from exc
        if not parsed:
            raise ComputedPropTrendError(f"NFLVERSE_PLAYER_STATS_EMPTY:{season}")
        missing = REQUIRED_PLAYER_COLUMNS - set(parsed[0])
        if missing:
            raise ComputedPropTrendError(
                f"NFLVERSE_PLAYER_STATS_SCHEMA_UNSUPPORTED:{season}:{','.join(sorted(missing))}"
            )
        rows.extend(parsed)
        proofs.append(SourceProof(season, uri, sha256(raw).hexdigest()))
    return PlayerStatsAcquisition(rows=tuple(rows), sources=tuple(proofs))


def fetch_nfl_prop_trend_inputs(
    *,
    seasons: Iterable[int],
    opener: Callable = urlopen,
) -> tuple[PlayerStatsAcquisition, list[dict[str, Any]], str]:
    """Acquire player logs and the independent NFL schedule used for PIT binding."""

    player = fetch_nflverse_weekly_player_stats(seasons=seasons, opener=opener)
    schedule_rows, schedule_sha = _fetch_schedule(opener=opener)
    return player, schedule_rows, schedule_sha


def build_computed_prop_trends(
    *,
    player_rows: Iterable[Mapping[str, Any]],
    player_sources: Iterable[SourceProof],
    schedule_rows: Iterable[Mapping[str, Any]],
    schedule_source_uri: str,
    schedule_source_sha256: str,
    as_of: Any,
    player_id: str,
    current_season: int,
    opponent_team_id: str,
    market_id: str,
    side: str,
    line: float,
    season_types: Iterable[str] = ("REG",),
) -> ComputedPropTrendSnapshot:
    """Compute exact-line prop trend context from timestamp-valid raw game rows."""

    pit = _utc(as_of, "as_of")
    target_player = _required_text(player_id, "player_id")
    target_opponent = _team(_required_text(opponent_team_id, "opponent_team_id"))
    target_market = _required_text(market_id, "market_id").upper()
    target_side = _required_text(side, "side").upper()
    if target_side not in SUPPORTED_SIDES:
        raise ComputedPropTrendError(f"INVALID_PROP_SIDE:{target_side}")
    if target_market not in MARKET_STAT_FIELDS:
        raise ComputedPropTrendError(f"UNSUPPORTED_PROP_MARKET:{target_market}")
    target_line = _finite(line, "line")
    target_season = int(current_season)
    allowed_types = {_required_text(value, "season_type").upper() for value in season_types}
    if not allowed_types:
        raise ComputedPropTrendError("SEASON_TYPES_REQUIRED")

    source_by_season = _source_map(player_sources)
    schedule_uri = _https(schedule_source_uri, "schedule_source_uri")
    schedule_sha = _sha(schedule_source_sha256, "schedule_source_sha256")

    schedule_index: dict[str, Mapping[str, Any]] = {}
    for schedule in schedule_rows:
        game_id = str(schedule.get("game_id") or "").strip()
        if not game_id:
            continue
        if game_id in schedule_index:
            raise ComputedPropTrendError(f"DUPLICATE_SCHEDULE_GAME_ID:{game_id}")
        schedule_index[game_id] = schedule

    stat_field = MARKET_STAT_FIELDS[target_market]
    seen_games: set[str] = set()
    settlements: list[GameSettlement] = []
    for raw in player_rows:
        if str(raw.get("player_id") or "").strip() != target_player:
            continue
        contaminated = FORBIDDEN_PRECOMPUTED_FIELDS.intersection(raw)
        if contaminated:
            raise ComputedPropTrendError(
                "PRECOMPUTED_TREND_FIELDS_FORBIDDEN:" + ",".join(sorted(contaminated))
            )
        missing = REQUIRED_PLAYER_COLUMNS - set(raw)
        if missing:
            raise ComputedPropTrendError(
                "RAW_GAME_IDENTITY_MISSING:" + ",".join(sorted(missing))
            )
        game_id = _required_text(raw.get("game_id"), "game_id")
        if game_id in seen_games:
            raise ComputedPropTrendError(f"DUPLICATE_PLAYER_GAME:{target_player}:{game_id}")
        seen_games.add(game_id)
        if game_id not in schedule_index:
            raise ComputedPropTrendError(f"SCHEDULE_BINDING_MISSING:{game_id}")
        schedule = schedule_index[game_id]
        kickoff = _kickoff(schedule)
        if kickoff >= pit:
            # A source file can already contain a row for a game that is not PIT
            # eligible.  Exclude it; never use week number as a substitute for time.
            continue

        row_season = _integer(raw.get("season"), "season")
        row_week = _integer(raw.get("week"), "week")
        season_type = _required_text(raw.get("season_type"), "season_type").upper()
        if season_type not in allowed_types:
            continue
        proof = source_by_season.get(row_season)
        if proof is None:
            raise ComputedPropTrendError(f"PLAYER_SOURCE_PROOF_MISSING:{row_season}")

        team = _team(_required_text(raw.get("team"), "team"))
        opponent = _team(_required_text(raw.get("opponent_team"), "opponent_team"))
        home = _team(_required_text(schedule.get("home_team"), "schedule_home_team"))
        away = _team(_required_text(schedule.get("away_team"), "schedule_away_team"))
        if team == opponent or {team, opponent} != {home, away}:
            raise ComputedPropTrendError(f"PLAYER_SCHEDULE_TEAM_MISMATCH:{game_id}")

        if stat_field not in raw or raw.get(stat_field) in (None, ""):
            raise ComputedPropTrendError(f"RAW_STAT_MISSING:{target_market}:{game_id}:{stat_field}")
        value = _finite(raw.get(stat_field), stat_field)
        settlements.append(
            GameSettlement(
                game_id=game_id,
                kickoff_ts=kickoff.isoformat(),
                season=row_season,
                week=row_week,
                team_id=team,
                opponent_team_id=opponent,
                value=value,
                outcome=_settle(value, line=target_line, side=target_side),
            )
        )

    settlements.sort(key=lambda game: (game.kickoff_ts, game.game_id))
    season_games = [game for game in settlements if game.season == target_season]
    h2h_games = [game for game in settlements if game.opponent_team_id == target_opponent]
    windows = (
        _window("L5", settlements[-5:]),
        _window("L10", settlements[-10:]),
        _window("L20", settlements[-20:]),
        _window("SEASON", season_games),
        _window("H2H", h2h_games),
    )

    used_seasons = sorted({game.season for game in settlements})
    used_sources = tuple(source_by_season[season] for season in used_seasons)
    canonical = {
        "contract": COMPUTE_CONTRACT,
        "as_of": pit.isoformat(),
        "player_id": target_player,
        "opponent_team_id": target_opponent,
        "market_id": target_market,
        "side": target_side,
        "line": target_line,
        "stat_field": stat_field,
        "windows": [asdict(window) for window in windows],
        "games": [asdict(game) for game in settlements],
        "player_sources": [asdict(source) for source in used_sources],
        "schedule_source_uri": schedule_uri,
        "schedule_source_sha256": schedule_sha,
    }
    content_hash = sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ComputedPropTrendSnapshot(
        contract=COMPUTE_CONTRACT,
        as_of=pit,
        player_id=target_player,
        opponent_team_id=target_opponent,
        market_id=target_market,
        side=target_side,
        line=target_line,
        stat_field=stat_field,
        windows=windows,
        games=tuple(settlements),
        player_sources=used_sources,
        schedule_source_uri=schedule_uri,
        schedule_source_sha256=schedule_sha,
        content_hash=content_hash,
    )


def match_computed_prop_trend(
    snapshot: ComputedPropTrendSnapshot,
    *,
    player_id: str,
    opponent_team_id: str,
    market_id: str,
    side: str,
    line: float,
) -> PropTrendMatch:
    """Require exact snapshot identity; never reuse a hit rate at another line."""

    if snapshot.player_id != _required_text(player_id, "player_id"):
        return PropTrendMatch("IDENTITY_MISMATCH", ("PLAYER_ID_MISMATCH",), None, None)
    opponent = _team(_required_text(opponent_team_id, "opponent_team_id"))
    if snapshot.opponent_team_id != opponent:
        return PropTrendMatch("IDENTITY_MISMATCH", ("OPPONENT_TEAM_ID_MISMATCH",), None, None)
    market = _required_text(market_id, "market_id").upper()
    if snapshot.market_id != market:
        return PropTrendMatch("IDENTITY_MISMATCH", ("MARKET_ID_MISMATCH",), None, None)
    normalized_side = _required_text(side, "side").upper()
    if snapshot.side != normalized_side:
        return PropTrendMatch("IDENTITY_MISMATCH", ("SIDE_MISMATCH",), None, None)
    requested_line = _finite(line, "line")
    delta = snapshot.line - requested_line
    if delta != 0.0:
        return PropTrendMatch("LINE_MISMATCH", ("PROP_LINE_MISMATCH",), snapshot, delta)
    return PropTrendMatch("EXACT", (), snapshot, 0.0)


def research_sidecar(snapshot: ComputedPropTrendSnapshot) -> dict[str, Any]:
    """Serialize the trend context with non-actionable governance flags."""

    return {
        "contract": snapshot.contract,
        "as_of": snapshot.as_of.isoformat(),
        "player_id": snapshot.player_id,
        "opponent_team_id": snapshot.opponent_team_id,
        "market_id": snapshot.market_id,
        "side": snapshot.side,
        "line": snapshot.line,
        "stat_field": snapshot.stat_field,
        "windows": [asdict(window) for window in snapshot.windows],
        "games": [asdict(game) for game in snapshot.games],
        "player_sources": [asdict(source) for source in snapshot.player_sources],
        "schedule_source_uri": snapshot.schedule_source_uri,
        "schedule_source_sha256": snapshot.schedule_source_sha256,
        "content_hash": snapshot.content_hash,
        "model_p_eligible": False,
        "truth_gate_eligible": False,
        "decision_effect": "NONE",
        "historical_hit_rate_is_probability": False,
    }
