from __future__ import annotations

"""Build coherent-prop role payloads from frozen nflverse player rows.

Rows must come from an immutable nflverse archive asset already validated by
``bind_nflverse_archive_asset``. Every consumed row must also prove that its
season/week predates the target game. The output is transparent empirical
research plumbing only: NOT Model_P, NOT Truth Gate, NOT OFFICIAL.
"""

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from .context_autopull import NFLContextError

_FORBIDDEN = ("odds", "price", "vig", "sportsbook", "market", "closing_line")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COUNT_FIELDS = (
    "attempts", "completions", "passing_yards", "passing_tds", "interceptions",
    "carries", "rushing_yards", "targets", "receptions", "receiving_yards",
    "receiving_tds", "rushing_tds",
)


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise NFLContextError(f"invalid {field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise NFLContextError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _target_season_week(game_id: str) -> tuple[int, int]:
    parts = str(game_id).split("_")
    if len(parts) < 2:
        raise NFLContextError("game_id must encode season and week")
    try:
        season, week = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise NFLContextError("game_id must encode numeric season and week") from exc
    if season < 2000 or week < 1:
        raise NFLContextError("game_id season/week out of range")
    return season, week


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


def _assert_source_binding(binding: Mapping[str, Any], *, kickoff: datetime, observed_at: datetime) -> None:
    if not isinstance(binding, Mapping) or binding.get("status") != "BOUND":
        raise NFLContextError("BOUND nflverse source receipt required")
    if binding.get("provider") != "nflverse-data-archives":
        raise NFLContextError("nflverse archive provider required")
    uri = str(binding.get("source_uri") or "")
    if not uri.startswith("https://github.com/nflverse/nflverse-data-archives/releases/download/"):
        raise NFLContextError("immutable nflverse archive source_uri required")
    raw_sha = str(binding.get("raw_sha256") or "").lower()
    if not _SHA256.fullmatch(raw_sha):
        raise NFLContextError("valid raw nflverse SHA-256 required")
    published = _utc(binding.get("published_at"), "source_binding.published_at")
    if published >= kickoff:
        raise NFLContextError("archive asset must be published before kickoff")
    if observed_at < published:
        raise NFLContextError("role extraction cannot predate archive publication")


def _assert_rows_before_target(
    rows: Sequence[Mapping[str, Any]], *, target_season: int, target_week: int
) -> None:
    for i, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise NFLContextError(f"player_rows[{i}] must be a mapping")
        if row.get("season") in (None, "") or row.get("week") in (None, ""):
            raise NFLContextError(f"player_rows[{i}] missing season/week PIT markers")
        try:
            season, week = int(row["season"]), int(row["week"])
        except (TypeError, ValueError) as exc:
            raise NFLContextError(f"player_rows[{i}] has invalid season/week PIT markers") from exc
        if season > target_season or (season == target_season and week >= target_week):
            raise NFLContextError(f"player_rows[{i}] is not pre-target PIT data")


def _number(value: Any, field: str) -> float:
    if value in (None, ""):
        return 0.0
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NFLContextError(f"invalid {field}") from exc
    if out < 0:
        raise NFLContextError(f"negative {field}")
    return out


def _safe_div(num: float, den: float) -> float:
    return num / den if den > 0 else 0.0


def _sample_key(row: Mapping[str, Any], index: int) -> str:
    game = str(row.get("game_id") or "").strip()
    if game:
        return f"game:{game}"
    return f"week:{row['season']}:{row['week']}:{index}"


def build_nflverse_prop_role_payloads(
    *,
    game_id: str,
    kickoff: Any,
    observed_at: Any,
    source_binding: Mapping[str, Any],
    player_rows: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Convert frozen pre-target nflverse rows into coherent-simulator roles."""
    target = str(game_id).strip()
    target_season, target_week = _target_season_week(target)
    kick = _utc(kickoff, "kickoff")
    seen = _utc(observed_at, "observed_at")
    if seen >= kick:
        raise NFLContextError("nflverse role snapshot must be observed before kickoff")
    _assert_source_binding(source_binding, kickoff=kick, observed_at=seen)
    _assert_market_blind(player_rows)
    _assert_rows_before_target(player_rows, target_season=target_season, target_week=target_week)

    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    meta: dict[str, dict[str, str]] = {}
    samples: dict[str, set[str]] = defaultdict(set)
    for index, row in enumerate(player_rows):
        pid = str(row.get("player_id") or row.get("gsis_id") or "").strip()
        if not pid:
            continue
        team = str(row.get("team") or row.get("recent_team") or "").strip().upper()
        position = str(row.get("position") or "").strip().upper()
        name = str(row.get("player_name") or row.get("player_display_name") or row.get("player") or pid).strip()
        if not team or not position:
            continue
        prior = meta.get(pid)
        current = {"team": team, "position": position, "player": name}
        if prior is not None and (prior["team"] != team or prior["position"] != position):
            raise NFLContextError(f"conflicting player identity:{pid}")
        meta[pid] = current
        samples[pid].add(_sample_key(row, index))
        for field in _COUNT_FIELDS:
            totals[pid][field] += _number(row.get(field), field)

    team_recv_tds: dict[str, float] = defaultdict(float)
    team_rush_tds: dict[str, float] = defaultdict(float)
    for pid, values in totals.items():
        team = meta[pid]["team"]
        team_recv_tds[team] += values["receiving_tds"]
        team_rush_tds[team] += values["rushing_tds"]

    payloads: list[dict[str, Any]] = []
    for pid in sorted(totals):
        values = totals[pid]
        info = meta[pid]
        n = len(samples[pid])
        if n <= 0:
            continue
        team = info["team"]
        payloads.append({
            "player": info["player"],
            "player_id": pid,
            "team": team,
            "position": info["position"],
            "role_prior": {
                "pass_attempts": values["attempts"] / n,
                "completion_rate": _safe_div(values["completions"], values["attempts"]),
                "pass_yards_per_completion": _safe_div(values["passing_yards"], values["completions"]),
                "pass_td_rate": _safe_div(values["passing_tds"], values["attempts"]),
                "interception_rate": _safe_div(values["interceptions"], values["attempts"]),
                "rush_attempts": values["carries"] / n,
                "rush_yards_per_attempt": _safe_div(values["rushing_yards"], values["carries"]),
                "targets": values["targets"] / n,
                "catch_rate": _safe_div(values["receptions"], values["targets"]),
                "receiving_yards_per_reception": _safe_div(values["receiving_yards"], values["receptions"]),
            },
            "trailing": {},
            "sample_size": 0,
            "context": {"source": "participation", "shared_workload_sigma": 0.12},
            "receiving_td_share": _safe_div(values["receiving_tds"], team_recv_tds[team]),
            "rushing_td_share": _safe_div(values["rushing_tds"], team_rush_tds[team]),
            "pit_sample_games": n,
        })

    normalized = json.dumps(list(player_rows), sort_keys=True, separators=(",", ":"), default=str).encode()
    return {
        "status": "AVAILABLE" if payloads else "MISSING",
        "game_id": target,
        "observed_at": seen.isoformat(),
        "source_uri": source_binding["source_uri"],
        "source_raw_sha256": source_binding["raw_sha256"],
        "normalized_rows_sha256": sha256(normalized).hexdigest(),
        "players": payloads,
        "market_fields_in_payload": False,
        "authority": "RESEARCH_ONLY / NOT Model_P / NOT Truth Gate / NOT OFFICIAL",
    }


__all__ = ["build_nflverse_prop_role_payloads"]
