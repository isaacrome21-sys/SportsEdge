"""Deterministic NFL football-prop artifact fitting from frozen nflverse PBP.

The fitter consumes local immutable CSV/CSV.GZ inputs only. It does not fetch
network data, inspect sportsbook fields, or derive player usage from realized
future games. The output supplies the market-blind team drive and special-teams
rates consumed by the shared-path football prop runner.
"""
from __future__ import annotations

from collections import defaultdict
import csv
from dataclasses import dataclass, field
import gzip
from hashlib import sha256
import json
from math import isfinite, sqrt
from pathlib import Path
from typing import Any, Iterable, Mapping

ARTIFACT_SCHEMA = "FOOTBALL_PROP_MODEL_ARTIFACT_V1"
TRAINING_VERSION = "NFL_PROP_PBP_FIT_V1"


def _f(value: Any) -> float | None:
    if value in (None, "", "NA", "NaN", "nan"):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _flag(value: Any) -> bool:
    out = _f(value)
    if out is not None:
        return out == 1.0
    return str(value or "").strip().lower() in {"true", "t", "yes", "y"}


def _sha_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows(path: Path) -> Iterable[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def _game_id(row: Mapping[str, Any]) -> str:
    return str(row.get("game_id") or row.get("nflverse_game_id") or "").strip()


def _team(row: Mapping[str, Any]) -> str:
    return str(row.get("posteam") or row.get("possession_team") or "").strip()


def _defteam(row: Mapping[str, Any]) -> str:
    return str(row.get("defteam") or "").strip()


def _play_type(row: Mapping[str, Any]) -> str:
    return str(row.get("play_type") or "").strip().lower()


@dataclass
class _TeamFit:
    scrimmage: int = 0
    pass_like: int = 0
    rush: int = 0
    completed_pass: int = 0
    pass_eligible: int = 0
    success: int = 0
    explosive: int = 0
    turnovers: int = 0
    sacks: int = 0
    fourth_short_field: int = 0
    fourth_short_field_fg: int = 0
    pace_sum: float = 0.0
    pace_n: int = 0
    fg_attempts: int = 0
    fg_made: int = 0
    xp_attempts: int = 0
    xp_made: int = 0
    two_attempts: int = 0
    two_made: int = 0

    def rate(self, numerator: int, denominator: int, *, name: str) -> float:
        if denominator <= 0:
            raise ValueError(f"NFL_PROP_FIT_DENOMINATOR_ZERO:{name}")
        return numerator / denominator

    def drive_profile(self, team: str) -> dict[str, float]:
        if self.scrimmage < 300:
            raise ValueError(f"NFL_PROP_FIT_TEAM_SCRIMMAGE_DEPTH_INSUFFICIENT:{team}:{self.scrimmage}")
        pace = self.pace_sum / self.pace_n if self.pace_n else None
        if pace is None or not 5.0 <= pace <= 60.0:
            raise ValueError(f"NFL_PROP_FIT_PACE_INVALID:{team}:{pace}")
        fg_skill = self.rate(self.fg_made, self.fg_attempts, name=f"{team}:fg_skill")
        return {
            "pass_rate": self.rate(self.pass_like, self.pass_like + self.rush, name=f"{team}:pass_rate"),
            "completion_rate": self.rate(self.completed_pass, self.pass_eligible, name=f"{team}:completion_rate"),
            "success_rate": self.rate(self.success, self.scrimmage, name=f"{team}:success_rate"),
            "explosive_rate": self.rate(self.explosive, self.scrimmage, name=f"{team}:explosive_rate"),
            "turnover_rate": self.rate(self.turnovers, self.scrimmage, name=f"{team}:turnover_rate"),
            "sack_rate": self.rate(self.sacks, self.pass_like, name=f"{team}:sack_rate"),
            "field_goal_attempt_rate": self.rate(
                self.fourth_short_field_fg,
                self.fourth_short_field,
                name=f"{team}:fg_decision_rate",
            ),
            "field_goal_skill": fg_skill,
            "pace_seconds_mean": pace,
        }

    def special_teams_profile(self, team: str) -> dict[str, float]:
        if self.fg_attempts < 20:
            raise ValueError(f"NFL_PROP_FIT_FG_DEPTH_INSUFFICIENT:{team}:{self.fg_attempts}")
        if self.xp_attempts < 20:
            raise ValueError(f"NFL_PROP_FIT_XP_DEPTH_INSUFFICIENT:{team}:{self.xp_attempts}")
        tries = self.xp_attempts + self.two_attempts
        if tries <= 0:
            raise ValueError(f"NFL_PROP_FIT_TRY_DEPTH_INSUFFICIENT:{team}")
        two_success = self.two_made / self.two_attempts if self.two_attempts else 0.48
        # The 0.48 fallback is not empirical evidence. It is used only when the
        # team had zero observed 2-point attempts in the fit window, and the
        # artifact records that fallback count so promotion evidence can veto it.
        return {
            "fg_base_skill": self.fg_made / self.fg_attempts,
            "xp_make_rate": self.xp_made / self.xp_attempts,
            "two_point_attempt_rate": self.two_attempts / tries,
            "two_point_success_rate": two_success,
        }


@dataclass
class FitDiagnostics:
    source_files: list[dict[str, Any]] = field(default_factory=list)
    team_rows: dict[str, dict[str, int]] = field(default_factory=dict)
    two_point_zero_attempt_teams: list[str] = field(default_factory=list)


def fit_nfl_prop_artifact(
    paths: Iterable[str | Path],
    *,
    code_git_sha: str,
    artifact_version: str,
    seasons: Iterable[int] = (2022, 2023, 2024, 2025),
) -> tuple[dict[str, Any], dict[str, Any]]:
    git_sha = str(code_git_sha or "").strip().lower()
    if len(git_sha) != 40 or any(ch not in "0123456789abcdef" for ch in git_sha):
        raise ValueError("NFL_PROP_FIT_CODE_GIT_SHA_INVALID")
    version = str(artifact_version or "").strip()
    if not version:
        raise ValueError("NFL_PROP_FIT_ARTIFACT_VERSION_REQUIRED")
    allowed_seasons = {int(x) for x in seasons}
    files = sorted(Path(path) for path in paths)
    if not files or any(not path.is_file() for path in files):
        raise ValueError("NFL_PROP_FIT_SOURCE_FILE_REQUIRED")

    source_files = [
        {"path": path.name, "sha256": _sha_file(path), "bytes": path.stat().st_size}
        for path in files
    ]
    manifest_payload = {
        "schema_version": "NFL_PROP_SOURCE_MANIFEST_V1",
        "training_version": TRAINING_VERSION,
        "files": source_files,
        "seasons": sorted(allowed_seasons),
    }
    manifest_sha = sha256(
        json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    stats: dict[str, _TeamFit] = defaultdict(_TeamFit)
    last_clock: dict[tuple[str, str], float] = {}
    row_counts: dict[str, int] = defaultdict(int)
    for path in files:
        for row in _rows(path):
            season = _f(row.get("season"))
            if season is not None and int(season) not in allowed_seasons:
                continue
            season_type = str(row.get("season_type") or row.get("game_type") or "REG").strip().upper()
            if season_type not in {"REG", ""}:
                continue
            team = _team(row)
            if not team:
                continue
            fit = stats[team]
            row_counts[team] += 1
            play_type = _play_type(row)
            is_pass = play_type == "pass" or _flag(row.get("sack"))
            is_rush = play_type == "run"
            if is_pass or is_rush:
                fit.scrimmage += 1
                if is_pass:
                    fit.pass_like += 1
                    if not _flag(row.get("sack")):
                        fit.pass_eligible += 1
                        fit.completed_pass += int(_flag(row.get("complete_pass")))
                    fit.sacks += int(_flag(row.get("sack")))
                if is_rush:
                    fit.rush += 1
                success = _f(row.get("success"))
                if success is not None:
                    fit.success += int(success > 0)
                else:
                    epa = _f(row.get("epa"))
                    fit.success += int(epa is not None and epa > 0)
                yards = _f(row.get("yards_gained"))
                fit.explosive += int(yards is not None and yards >= 20.0)
                fit.turnovers += int(_flag(row.get("interception")) or _flag(row.get("fumble_lost")))

                game = _game_id(row)
                clock = _f(row.get("game_seconds_remaining"))
                if game and clock is not None:
                    key = (game, team)
                    prior = last_clock.get(key)
                    if prior is not None:
                        elapsed = prior - clock
                        if 5.0 <= elapsed <= 60.0:
                            fit.pace_sum += elapsed
                            fit.pace_n += 1
                    last_clock[key] = clock

            down = _f(row.get("down"))
            yardline = _f(row.get("yardline_100"))
            if down == 4 and yardline is not None and yardline <= 35:
                fit.fourth_short_field += 1
                fit.fourth_short_field_fg += int(_flag(row.get("field_goal_attempt")))

            if _flag(row.get("field_goal_attempt")):
                fit.fg_attempts += 1
                result = str(row.get("field_goal_result") or "").strip().lower()
                fit.fg_made += int(result == "made" or _flag(row.get("field_goal_result_made")))
            if _flag(row.get("extra_point_attempt")):
                fit.xp_attempts += 1
                result = str(row.get("extra_point_result") or "").strip().lower()
                fit.xp_made += int(result == "good" or result == "made")
            if _flag(row.get("two_point_attempt")):
                fit.two_attempts += 1
                result = str(row.get("two_point_conv_result") or "").strip().lower()
                fit.two_made += int(result in {"success", "successful", "good", "made"})

    teams = sorted(stats)
    if len(teams) != 32:
        raise ValueError(f"NFL_PROP_FIT_TEAM_COUNT_INVALID:{len(teams)}:{','.join(teams)}")

    drive_profiles: dict[str, dict[str, float]] = {}
    special_profiles: dict[str, dict[str, float]] = {}
    zero_two: list[str] = []
    diagnostics_rows: dict[str, dict[str, int]] = {}
    for team in teams:
        fit = stats[team]
        drive_profiles[team] = fit.drive_profile(team)
        special_profiles[team] = fit.special_teams_profile(team)
        if fit.two_attempts == 0:
            zero_two.append(team)
        diagnostics_rows[team] = {
            "source_rows": row_counts[team],
            "scrimmage": fit.scrimmage,
            "pass_like": fit.pass_like,
            "rush": fit.rush,
            "fg_attempts": fit.fg_attempts,
            "xp_attempts": fit.xp_attempts,
            "two_point_attempts": fit.two_attempts,
            "pace_observations": fit.pace_n,
        }

    artifact = {
        "schema_version": ARTIFACT_SCHEMA,
        "sport": "NFL",
        "artifact_version": version,
        "training_version": TRAINING_VERSION,
        "code_git_sha": git_sha,
        "source_manifest_sha256": manifest_sha,
        "team_drive_profiles": drive_profiles,
        "team_special_teams_rates": special_profiles,
        "fit_scope": {
            "seasons": sorted(allowed_seasons),
            "season_type": "REG",
            "team_count": len(teams),
        },
    }
    diagnostics = {
        "schema_version": "NFL_PROP_FIT_DIAGNOSTICS_V1",
        "status": "PASS",
        "code_git_sha": git_sha,
        "source_manifest": manifest_payload,
        "source_manifest_sha256": manifest_sha,
        "team_count": len(teams),
        "team_rows": diagnostics_rows,
        "two_point_zero_attempt_teams": zero_two,
        "note": "A zero two-point-attempt team uses the structural 0.48 fallback and remains evidence-gated; this diagnostic does not certify promotion.",
    }
    return artifact, diagnostics
