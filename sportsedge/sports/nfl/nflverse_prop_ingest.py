from __future__ import annotations

"""PIT-safe adapter for public nflverse inputs used by NFL prop research.

This module intentionally derives only fields supported by public pre-kickoff
snap/player/PBP data. Route participation and other unavailable live fields
remain None. Market data is never accepted.
"""

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping, Sequence

from .context_autopull import NFLContextError
from .prop_opportunity_context import build_prop_opportunity_provider

_FORBIDDEN = ("odds", "price", "vig", "sportsbook", "market", "closing_line")


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise NFLContextError(f"invalid {field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise NFLContextError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _assert_market_blind(obj: Any, path: str = "root") -> None:
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            low = str(key).lower()
            if any(token in low for token in _FORBIDDEN):
                raise NFLContextError(f"market input forbidden at {path}.{key}")
            _assert_market_blind(value, f"{path}.{key}")
    elif isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        for i, value in enumerate(obj):
            _assert_market_blind(value, f"{path}[{i}]")


def _source_sha(rows: Sequence[Mapping[str, Any]]) -> str:
    raw = json.dumps(list(rows), sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(raw).hexdigest()


def build_nflverse_prop_opportunity_provider(
    *,
    game_id: str,
    kickoff: Any,
    observed_at: Any,
    source_uri: str,
    snap_rows: Sequence[Mapping[str, Any]],
    player_rows: Sequence[Mapping[str, Any]],
    pbp_rows: Sequence[Mapping[str, Any]] = (),
) -> Mapping[str, Any]:
    """Build a hash-bound opportunity provider from already-fetched nflverse rows.

    Inputs MUST be snapshotted before kickoff. Callers should persist the exact
    raw source bytes separately; this adapter hashes the normalized rows as an
    additional deterministic binding.
    """
    kick = _utc(kickoff, "kickoff")
    seen = _utc(observed_at, "observed_at")
    if seen >= kick:
        raise NFLContextError("nflverse prop snapshot must be observed before kickoff")
    for rows in (snap_rows, player_rows, pbp_rows):
        _assert_market_blind(rows)

    snaps: dict[str, dict[str, Any]] = {}
    for row in snap_rows:
        pid = str(row.get("player_id") or row.get("gsis_id") or "").strip()
        if not pid:
            continue
        snaps[pid] = dict(row)

    stats: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    meta: dict[str, dict[str, str]] = {}
    for row in player_rows:
        pid = str(row.get("player_id") or row.get("gsis_id") or "").strip()
        if not pid:
            continue
        meta[pid] = {
            "team": str(row.get("team") or row.get("recent_team") or "").upper(),
            "position": str(row.get("position") or "").upper(),
        }
        for key in ("carries", "attempts", "targets"):
            value = row.get(key)
            if value not in (None, ""):
                stats[pid][key] += float(value)

    # Aggregate team denominators only from the same PIT rows.
    team_carries: dict[str, float] = defaultdict(float)
    team_attempts: dict[str, float] = defaultdict(float)
    team_targets: dict[str, float] = defaultdict(float)
    for pid, values in stats.items():
        team = meta.get(pid, {}).get("team", "")
        team_carries[team] += values["carries"]
        team_attempts[team] += values["attempts"]
        team_targets[team] += values["targets"]

    out = []
    for pid in sorted(set(snaps) | set(stats)):
        s = snaps.get(pid, {})
        m = meta.get(pid, {})
        team = str(s.get("team") or m.get("team") or "").upper()
        position = str(s.get("position") or m.get("position") or "").upper()
        if not team or not position:
            continue
        vals = stats.get(pid, {})
        off_snaps = s.get("offense_snaps")
        off_pct = s.get("offense_pct")
        snap_share = None
        if off_pct not in (None, ""):
            x = float(off_pct)
            snap_share = x / 100.0 if x > 1.0 else x
        games = int(s.get("games") or s.get("game_count") or 0)
        out.append({
            "player_id": pid,
            "team_id": team,
            "position": position,
            "sample_games": max(games, 0),
            "snap_share": snap_share,
            # Public in-season participation/routes are not assumed available.
            "route_participation": None,
            "targets_per_route_run": None,
            "target_share": vals["targets"] / team_targets[team] if team_targets[team] else None,
            "carry_share": vals["carries"] / team_carries[team] if team_carries[team] else None,
            "pass_attempt_share": vals["attempts"] / team_attempts[team] if team_attempts[team] else None,
            "adot": None, "air_yard_share": None,
            "early_down_snap_share": None, "third_down_snap_share": None,
            "two_minute_snap_share": None, "goal_line_carries": None,
            "red_zone_targets": None, "red_zone_snap_share": None,
            "designed_qb_run_rate": None, "scramble_rate": None,
            "pass_rush_snap_share": None, "pressure_rate_allowed": None,
            "run_block_success_rate": None, "man_coverage_target_rate": None,
            "zone_coverage_target_rate": None, "explosive_target_rate": None,
        })

    normalized = list(snap_rows) + list(player_rows) + list(pbp_rows)
    return build_prop_opportunity_provider(
        game_id=game_id,
        as_of=seen,
        source_uri=source_uri,
        source_sha256=_source_sha(normalized),
        rows=out,
    )
