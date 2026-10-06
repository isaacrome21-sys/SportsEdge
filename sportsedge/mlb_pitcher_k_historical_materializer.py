"""Efficient PIT-safe materializer for frozen MLB pitcher-K evaluation rows.

The materializer uses immutable historical MLB game logs and date-bounded
Baseball Savant pitch data. Historical target lineups are deliberately not
reconstructed from final boxscores; the frozen validated lineup fallback is used
unless a separate genuine pregame lineup archive is supplied in a later version.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from math import isfinite
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import urlopen

from .mlb_generic_features import MLBGenericHistorySource, _read_json
from .mlb_pitcher_k_composite_candidate import build_composite_candidate
from .mlb_pitcher_k_historical_row import (
    EVALUATION_USE,
    PROVENANCE_SCHEMA,
    bind_historical_statcast_skill,
    build_historical_evaluation_row,
)
from .mlb_pitcher_k_workload_candidate import build_workload_bundle
from .statcast_daily_source import (
    OUT_OF_ZONE_CODES,
    SOURCE as STATCAST_SOURCE,
    SWING_DESCRIPTIONS,
    WHIFF_DESCRIPTIONS,
    _request_csv,
    build_statcast_url,
)

FROZEN_SEASONS = (2023, 2024, 2025)
STATCAST_WINDOW_DAYS = 30
DEFAULT_CHUNK_DAYS = 45
SCHEDULE_BASE = "https://statsapi.mlb.com/api/v1/schedule"


class PitcherKHistoricalMaterializerError(ValueError):
    pass


@dataclass(frozen=True)
class PitcherKTarget:
    season: int
    target_date: date
    game_id: int
    pitcher_id: int
    team_id: int
    opponent_id: int
    away_team_id: int
    home_team_id: int


@dataclass(frozen=True)
class _Pitch:
    game_date: date
    description: str
    zone: int | None
    hand: str


def _int(value: Any) -> int | None:
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out


def targets_from_schedule(payload: Mapping[str, Any], *, season: int) -> list[PitcherKTarget]:
    """Discover regular-season historical probable starters from a final schedule.

    A target survives only if the schedule still identifies that side's probable
    pitcher. The later outcome lookup independently requires that pitcher to have
    actually started that game, so stale probable-pitcher identities fail closed.
    """
    if int(season) not in FROZEN_SEASONS:
        raise PitcherKHistoricalMaterializerError("season outside frozen split")
    out: list[PitcherKTarget] = []
    seen: dict[tuple[int, int, int], PitcherKTarget] = {}
    for block in payload.get("dates") or []:
        if not isinstance(block, Mapping):
            continue
        for game in block.get("games") or []:
            if not isinstance(game, Mapping):
                continue
            if str((game.get("status") or {}).get("abstractGameState") or "").lower() != "final":
                continue
            if str(game.get("gameType") or "R").upper() != "R":
                continue
            raw_date = str(game.get("officialDate") or block.get("date") or "")[:10]
            try:
                target_date = date.fromisoformat(raw_date)
            except ValueError:
                continue
            if target_date.year != int(season):
                continue
            game_id = _int(game.get("gamePk"))
            teams = game.get("teams") or {}
            away = teams.get("away") or {}
            home = teams.get("home") or {}
            away_id = _int((away.get("team") or {}).get("id"))
            home_id = _int((home.get("team") or {}).get("id"))
            if None in {game_id, away_id, home_id}:
                continue
            for side, team_id, opponent_id in (
                (away, away_id, home_id),
                (home, home_id, away_id),
            ):
                pitcher_id = _int((side.get("probablePitcher") or {}).get("id"))
                if pitcher_id is None:
                    continue
                target = PitcherKTarget(
                    season=int(season),
                    target_date=target_date,
                    game_id=int(game_id),
                    pitcher_id=int(pitcher_id),
                    team_id=int(team_id),
                    opponent_id=int(opponent_id),
                    away_team_id=int(away_id),
                    home_team_id=int(home_id),
                )
                identity = (target.season, target.game_id, target.pitcher_id)
                prior = seen.get(identity)
                if prior is None:
                    seen[identity] = target
                    out.append(target)
                elif prior != target:
                    raise PitcherKHistoricalMaterializerError(
                        "conflicting duplicate season/game/pitcher target"
                    )
                # StatsAPI can repeat an identical completed game record in a
                # season schedule payload (for example around rescheduled or
                # suspended-game bookkeeping). Identical target identity is
                # transport duplication, not a second pitcher start.
    out.sort(key=lambda x: (x.target_date, x.game_id, x.pitcher_id))
    return out


def fetch_season_schedule(
    season: int,
    *,
    opener: Callable = urlopen,
) -> Mapping[str, Any]:
    if int(season) not in FROZEN_SEASONS:
        raise PitcherKHistoricalMaterializerError("season outside frozen split")
    query = urlencode(
        {
            "sportId": 1,
            "gameType": "R",
            "startDate": f"{int(season)}-03-01",
            "endDate": f"{int(season)}-11-15",
            "hydrate": "probablePitcher",
        }
    )
    return _read_json(f"{SCHEDULE_BASE}?{query}", opener=opener)


def _pitch_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    core = tuple(
        str(row.get(key) or "")
        for key in ("game_pk", "at_bat_number", "pitch_number", "pitcher", "batter", "game_date")
    )
    if any(core[:3]):
        return core
    return (json.dumps(dict(row), sort_keys=True, separators=(",", ":")),)


class HistoricalStatcastArchive:
    """Reduced pitch archive supporting local rolling 30-day pitcher skill."""

    def __init__(self, pitches: Mapping[int, Sequence[_Pitch]], *, retrieved_at: datetime):
        self.retrieved_at = retrieved_at.astimezone(timezone.utc)
        self._rows: dict[int, tuple[_Pitch, ...]] = {}
        self._dates: dict[int, tuple[date, ...]] = {}
        for pitcher_id, rows in pitches.items():
            ordered = tuple(sorted(rows, key=lambda r: r.game_date))
            self._rows[int(pitcher_id)] = ordered
            self._dates[int(pitcher_id)] = tuple(row.game_date for row in ordered)

    @classmethod
    def fetch_season(
        cls,
        season: int,
        *,
        opener: Callable = urlopen,
        chunk_days: int = DEFAULT_CHUNK_DAYS,
        retrieved_at: datetime | None = None,
    ) -> "HistoricalStatcastArchive":
        if int(season) not in FROZEN_SEASONS:
            raise PitcherKHistoricalMaterializerError("season outside frozen split")
        if not 7 <= int(chunk_days) <= 90:
            raise PitcherKHistoricalMaterializerError("chunk_days outside [7,90]")
        start = date(int(season), 2, 1)
        end = date(int(season), 11, 16)
        cursor = start
        seen: set[tuple[str, ...]] = set()
        pitches: dict[int, list[_Pitch]] = defaultdict(list)
        while cursor < end:
            stop = min(end, cursor + timedelta(days=int(chunk_days)))
            rows = _request_csv(build_statcast_url(cursor, stop), opener=opener)
            for row in rows:
                key = _pitch_key(row)
                if key in seen:
                    continue
                seen.add(key)
                pitcher_id = _int(row.get("pitcher"))
                raw_date = str(row.get("game_date") or "")[:10]
                if pitcher_id is None:
                    continue
                try:
                    game_date = date.fromisoformat(raw_date)
                except ValueError:
                    continue
                if game_date < start or game_date >= end:
                    continue
                description = str(row.get("description") or "").strip()
                zone = _int(row.get("zone"))
                hand = str(row.get("p_throws") or "").upper()
                if hand not in {"L", "R"}:
                    continue
                pitches[pitcher_id].append(
                    _Pitch(game_date=game_date, description=description, zone=zone, hand=hand)
                )
            # One-day overlap prevents boundary ambiguity at the Savant query layer;
            # _pitch_key de-duplicates the repeated boundary pitches.
            if stop >= end:
                break
            cursor = stop - timedelta(days=1)
        return cls(pitches, retrieved_at=retrieved_at or datetime.now(timezone.utc))

    def pitcher_context(self, *, pitcher_id: int, target_date: date) -> tuple[dict[str, Any], dict[str, Any]]:
        rows = self._rows.get(int(pitcher_id), ())
        dates = self._dates.get(int(pitcher_id), ())
        # Mirror the existing live source metadata boundary: end is target date
        # exclusive and start is end-(30-1).
        window_start = target_date - timedelta(days=STATCAST_WINDOW_DAYS - 1)
        left = bisect_left(dates, window_start)
        right = bisect_left(dates, target_date)
        window = rows[left:right]
        if not window:
            raise PitcherKHistoricalMaterializerError("historical Statcast pitcher window empty")
        swings = sum(row.description in SWING_DESCRIPTIONS for row in window)
        whiffs = sum(row.description in WHIFF_DESCRIPTIONS for row in window)
        out_zone = sum(row.zone in OUT_OF_ZONE_CODES for row in window)
        chases = sum(
            row.zone in OUT_OF_ZONE_CODES and row.description in SWING_DESCRIPTIONS
            for row in window
        )
        hands = sorted({row.hand for row in window})
        if swings <= 0 or whiffs <= 0 or out_zone <= 0 or chases <= 0:
            raise PitcherKHistoricalMaterializerError("historical Statcast skill counts incomplete")
        if len(hands) != 1:
            raise PitcherKHistoricalMaterializerError("historical pitcher hand ambiguous")
        context = {
            "entity_id": str(int(pitcher_id)),
            "swings": int(swings),
            "whiffs": int(whiffs),
            "whiff_rate": round(whiffs / swings, 6),
            "out_of_zone_pitches": int(out_zone),
            "chases": int(chases),
            "chase_rate": round(chases / out_zone, 6),
            "pitcher_hand": hands[0],
            "window_start": window_start.isoformat(),
            "window_end": target_date.isoformat(),
        }
        provenance = {
            "schema": PROVENANCE_SCHEMA,
            "source": STATCAST_SOURCE,
            "mode": "HISTORICAL_RECONSTRUCTION",
            "target_date": target_date.isoformat(),
            "window_start": window_start.isoformat(),
            "query_end_exclusive": target_date.isoformat(),
            "retrieved_at": self.retrieved_at.isoformat(),
            "raw_pitch_rows": len(window),
            "raw_pitch_rows_scope": "TARGET_PITCHER_WINDOW",
            "same_day_rows_included": False,
            "future_rows_included": False,
            "historical_reconstruction": True,
            "backfill": True,
            "forward_evidence_eligible": False,
            "promotion_authority": False,
            "evaluation_use": EVALUATION_USE,
        }
        return context, provenance


def _is_start(row: Mapping[str, Any]) -> bool:
    stat = row.get("stat")
    if not isinstance(stat, Mapping):
        return False
    try:
        return float(stat.get("gamesStarted", 0) or 0) >= 1
    except (TypeError, ValueError):
        return False


def _target_outcome(source: MLBGenericHistorySource, target: PitcherKTarget) -> tuple[int, int]:
    payload = source._player_season(target.pitcher_id, "pitching", target.season)
    for block in payload.get("stats") or []:
        if not isinstance(block, Mapping):
            continue
        for split in block.get("splits") or []:
            if not isinstance(split, Mapping):
                continue
            game_id = _int((split.get("game") or {}).get("gamePk"))
            raw_date = str(split.get("date") or "")[:10]
            stat = split.get("stat") or {}
            if game_id != target.game_id or raw_date != target.target_date.isoformat():
                continue
            try:
                if float(stat.get("gamesStarted", 0) or 0) < 1:
                    break
                k = int(stat.get("strikeOuts"))
                bf = int(stat.get("battersFaced"))
            except (TypeError, ValueError) as exc:
                raise PitcherKHistoricalMaterializerError("target outcome K/BF missing") from exc
            if bf <= 0 or k < 0 or k > bf:
                raise PitcherKHistoricalMaterializerError("target outcome K/BF impossible")
            return k, bf
    raise PitcherKHistoricalMaterializerError("scheduled probable pitcher did not start target game")


def materialize_target(
    source: MLBGenericHistorySource,
    archive: HistoricalStatcastArchive,
    target: PitcherKTarget,
) -> dict[str, Any]:
    prior = [
        row
        for row in source.player_rows(
            player_id=target.pitcher_id, group="pitching", target_date=target.target_date
        )
        if _is_start(row)
    ][-10:]
    if len(prior) < 5:
        raise PitcherKHistoricalMaterializerError("fewer than 5 strictly-prior starts")
    workload = build_workload_bundle(prior)
    opp_k, reason = source._opp_k_payload(
        player_id=target.pitcher_id,
        target_date=target.target_date,
        team_id=target.team_id,
        away_team_id=target.away_team_id,
        home_team_id=target.home_team_id,
    )
    if opp_k is None:
        raise PitcherKHistoricalMaterializerError(f"opponent-K unavailable:{reason}")
    # No historical final-boxscore lineup reconstruction: that would not prove
    # pregame availability. The validated fallback is exactly lineup=None.
    composite = build_composite_candidate(
        workload=workload,
        opp_k_adjustment=opp_k,
        lineup_k_adjustment=None,
    )
    context, provenance = archive.pitcher_context(
        pitcher_id=target.pitcher_id,
        target_date=target.target_date,
    )
    candidate = bind_historical_statcast_skill(
        composite,
        pitcher_context=context,
        provenance=provenance,
        target_date=target.target_date,
    )
    history_pool = source.pitcher_joint_history(
        player_id=target.pitcher_id,
        target_date=target.target_date,
    )
    if len(history_pool) != len(prior):
        raise PitcherKHistoricalMaterializerError("workload/incumbent history alignment mismatch")
    realized_k, realized_bf = _target_outcome(source, target)
    row = build_historical_evaluation_row(
        season=target.season,
        target_date=target.target_date,
        game_id=target.game_id,
        pitcher_id=target.pitcher_id,
        candidate=candidate,
        history_pool=history_pool,
        realized_strikeouts=realized_k,
        realized_batters_faced=realized_bf,
    )
    row["lineup_reconstruction_policy"] = "VALIDATED_FALLBACK_TO_OPP_K_NO_PREGAME_LINEUP_ARCHIVE"
    return row


def materialize_season(
    *,
    season: int,
    source: MLBGenericHistorySource,
    archive: HistoricalStatcastArchive,
    schedule_payload: Mapping[str, Any],
) -> dict[str, Any]:
    targets = targets_from_schedule(schedule_payload, season=season)
    rows: list[dict[str, Any]] = []
    exclusions: dict[str, int] = defaultdict(int)
    for target in targets:
        try:
            rows.append(materialize_target(source, archive, target))
        except Exception as exc:  # fail closed per target; reason is counted, no fallback.
            key = f"{type(exc).__name__}:{exc}"
            exclusions[key] += 1
    rows.sort(key=lambda row: (row["target_date"], int(row["game_id"]), str(row["pitcher_id"])))
    return {
        "schema": "MLB_PITCHER_K_HISTORICAL_MATERIALIZATION_SEASON_V1",
        "season": int(season),
        "target_count": len(targets),
        "eligible_row_count": len(rows),
        "excluded_row_count": len(targets) - len(rows),
        "exclusions": dict(sorted(exclusions.items())),
        "rows": rows,
        "historical_reconstruction": True,
        "forward_evidence_eligible": False,
        "promotion_authority": False,
    }


def combine_seasons(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_season = {int(item.get("season")): item for item in results}
    if set(by_season) != set(FROZEN_SEASONS):
        raise PitcherKHistoricalMaterializerError("all frozen seasons required")
    rows: list[dict[str, Any]] = []
    receipts = []
    for season in FROZEN_SEASONS:
        item = by_season[season]
        rows.extend(item.get("rows") or [])
        receipts.append(
            {
                "season": season,
                "target_count": int(item.get("target_count") or 0),
                "eligible_row_count": int(item.get("eligible_row_count") or 0),
                "excluded_row_count": int(item.get("excluded_row_count") or 0),
                "exclusions": dict(item.get("exclusions") or {}),
            }
        )
    return {
        "schema": "MLB_PITCHER_K_HISTORICAL_EVALUATION_ROWS_V1",
        "seasons": list(FROZEN_SEASONS),
        "row_count": len(rows),
        "season_receipts": receipts,
        "rows": rows,
        "historical_reconstruction": True,
        "backfill": True,
        "forward_evidence_eligible": False,
        "promotion_authority": False,
        "authority": {
            "model_p": False,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "official": False,
            "bettor_facing_release": False,
        },
    }
