"""Deterministic CFB football-prop artifact fitting from frozen ESPN CFB PBP.

Only market-blind play fields are consumed. Sportsbook columns may exist in the
published source bytes but are never read into predictive profiles.
"""
from __future__ import annotations

from collections import defaultdict
import csv
from dataclasses import dataclass
import gzip
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping

ARTIFACT_SCHEMA = "FOOTBALL_PROP_MODEL_ARTIFACT_V1"
TRAINING_VERSION = "CFB_ESPN_PBP_FIT_V1"
MIN_SCRIMMAGE_PLAYS = 200
MIN_TEAM_COUNT = 100


def _f(value: Any) -> float | None:
    if value in (None, "", "NA", "NaN", "nan", "None"):
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
    with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CFB_PROP_FIT_CSV_HEADER_REQUIRED")
        yield from reader


def _team(row: Mapping[str, Any]) -> str:
    team_id = str(row.get("start.pos_team.id") or row.get("pos_team") or "").strip()
    home_id = str(row.get("homeTeamId") or "").strip()
    away_id = str(row.get("awayTeamId") or "").strip()
    if team_id and team_id == home_id:
        return str(row.get("homeTeamName") or "").strip()
    if team_id and team_id == away_id:
        return str(row.get("awayTeamName") or "").strip()
    return str(row.get("start.pos_team.name") or "").strip()


def _regular_season(row: Mapping[str, Any]) -> bool:
    raw = row.get("seasonType")
    return True if raw in (None, "") else _f(raw) == 2.0


def _try_kind(row: Mapping[str, Any]) -> tuple[bool, bool, bool]:
    """Return XP-attempt, two-point-attempt, made from ESPN PAT metadata.

    ESPN documents ``pointAfterAttempt.text`` as the PAT attempt description and
    ``pointAfterAttempt.value`` as points *added* by that attempt. Therefore the
    value is an outcome, not an attempt-type code. Inferring type from value was
    a data-semantic bug because misses commonly have value zero.
    """
    text = str(row.get("pointAfterAttempt.text") or "").strip().lower()
    abbr = str(row.get("pointAfterAttempt.abbreviation") or "").strip().lower()
    if not text and not abbr:
        return False, False, False
    two = any(token in text for token in ("two-point", "two point", "2-point", "2 point")) or abbr in {"2pt", "2-pt", "2pc"}
    xp = ("extra point" in text or abbr in {"xp", "pat"}) and not two
    if not xp and not two:
        return False, False, False
    value = _f(row.get("pointAfterAttempt.value"))
    if value is None:
        raise ValueError("CFB_PROP_FIT_PAT_VALUE_REQUIRED")
    made = (xp and value == 1.0) or (two and value == 2.0)
    if value not in {0.0, 1.0, 2.0}:
        raise ValueError(f"CFB_PROP_FIT_PAT_VALUE_INVALID:{value}")
    return xp, two, made


@dataclass
class _TeamFit:
    scrimmage: int = 0
    pass_like: int = 0
    rush: int = 0
    pass_attempts: int = 0
    completions: int = 0
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

    @staticmethod
    def rate(num: int, den: int, name: str) -> float:
        if den <= 0:
            raise ValueError(f"CFB_PROP_FIT_DENOMINATOR_ZERO:{name}")
        return num / den

    def drive_profile(self, team: str, league_fg: float) -> dict[str, float]:
        if self.scrimmage < MIN_SCRIMMAGE_PLAYS:
            raise ValueError(f"CFB_PROP_FIT_TEAM_SCRIMMAGE_DEPTH_INSUFFICIENT:{team}:{self.scrimmage}")
        pace = self.pace_sum / self.pace_n if self.pace_n else None
        if pace is None or not 5.0 <= pace <= 60.0:
            raise ValueError(f"CFB_PROP_FIT_PACE_INVALID:{team}:{pace}")
        return {
            "pass_rate": self.rate(self.pass_like, self.pass_like + self.rush, f"{team}:pass_rate"),
            "completion_rate": self.rate(self.completions, self.pass_attempts, f"{team}:completion_rate"),
            "success_rate": self.rate(self.success, self.scrimmage, f"{team}:success_rate"),
            "explosive_rate": self.rate(self.explosive, self.scrimmage, f"{team}:explosive_rate"),
            "turnover_rate": self.rate(self.turnovers, self.scrimmage, f"{team}:turnover_rate"),
            "sack_rate": self.rate(self.sacks, self.pass_like, f"{team}:sack_rate"),
            "field_goal_attempt_rate": self.rate(self.fourth_short_field_fg, self.fourth_short_field, f"{team}:fg_decision_rate"),
            "field_goal_skill": self.fg_made / self.fg_attempts if self.fg_attempts >= 8 else league_fg,
            "pace_seconds_mean": pace,
        }

    def special_profile(self, league_fg: float, league_xp: float, league_two: float) -> dict[str, float]:
        tries = self.xp_attempts + self.two_attempts
        return {
            "fg_base_skill": self.fg_made / self.fg_attempts if self.fg_attempts >= 8 else league_fg,
            "xp_make_rate": self.xp_made / self.xp_attempts if self.xp_attempts >= 8 else league_xp,
            "two_point_attempt_rate": self.two_attempts / tries if tries >= 8 else 0.0,
            "two_point_success_rate": self.two_made / self.two_attempts if self.two_attempts >= 4 else league_two,
        }


def _special_team_league_rates(stats: Mapping[str, _TeamFit]) -> tuple[float, float, float, dict[str, Any]]:
    teams = list(stats)
    fg_a = sum(stats[t].fg_attempts for t in teams)
    xp_a = sum(stats[t].xp_attempts for t in teams)
    two_a = sum(stats[t].two_attempts for t in teams)
    if min(fg_a, xp_a, two_a) <= 0:
        raise ValueError("CFB_PROP_FIT_LEAGUE_SPECIAL_TEAMS_DEPTH_ZERO")
    fg = sum(stats[t].fg_made for t in teams) / fg_a
    xp = sum(stats[t].xp_made for t in teams) / xp_a
    two = sum(stats[t].two_made for t in teams) / two_a
    # Semantic guardrails, not promotion/calibration thresholds. A source-schema
    # mapping that says ~0% XP or ~100% 2PT is broken and must fail closed.
    if not 0.45 <= fg <= 0.95:
        raise ValueError(f"CFB_PROP_FIT_LEAGUE_FG_RATE_IMPLAUSIBLE:{fg}")
    if not 0.75 <= xp <= 1.0:
        raise ValueError(f"CFB_PROP_FIT_LEAGUE_XP_RATE_IMPLAUSIBLE:{xp}")
    if not 0.20 <= two <= 0.80:
        raise ValueError(f"CFB_PROP_FIT_LEAGUE_TWO_POINT_RATE_IMPLAUSIBLE:{two}")
    return fg, xp, two, {
        "fg_attempts": fg_a, "fg_make_rate": fg,
        "xp_attempts": xp_a, "xp_make_rate": xp,
        "two_point_attempts": two_a, "two_point_success_rate": two,
    }


def fit_cfb_prop_artifact(
    paths: Iterable[str | Path], *, code_git_sha: str, artifact_version: str,
    seasons: Iterable[int] = (2025,),
) -> tuple[dict[str, Any], dict[str, Any]]:
    git_sha = str(code_git_sha or "").strip().lower()
    if len(git_sha) != 40 or any(ch not in "0123456789abcdef" for ch in git_sha):
        raise ValueError("CFB_PROP_FIT_CODE_GIT_SHA_INVALID")
    version = str(artifact_version or "").strip()
    if not version:
        raise ValueError("CFB_PROP_FIT_ARTIFACT_VERSION_REQUIRED")
    allowed_seasons = {int(x) for x in seasons}
    files = sorted(Path(path) for path in paths)
    if not files or any(not p.is_file() for p in files):
        raise ValueError("CFB_PROP_FIT_SOURCE_FILE_REQUIRED")

    source_files = [{"path": p.name, "sha256": _sha_file(p), "bytes": p.stat().st_size} for p in files]
    manifest_payload = {
        "schema_version": "CFB_PROP_SOURCE_MANIFEST_V1",
        "training_version": TRAINING_VERSION,
        "files": source_files,
        "seasons": sorted(allowed_seasons),
        "market_fields_consumed": False,
    }
    manifest_sha = sha256(json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    stats: dict[str, _TeamFit] = defaultdict(_TeamFit)
    row_counts: dict[str, int] = defaultdict(int)
    last_clock: dict[tuple[str, str], float] = {}
    for path in files:
        for row in _rows(path):
            season = _f(row.get("season"))
            if season is not None and int(season) not in allowed_seasons:
                continue
            if not _regular_season(row) or not _flag(row.get("status_type_completed", True)):
                continue
            team = _team(row)
            if not team:
                continue
            fit = stats[team]
            row_counts[team] += 1
            if _flag(row.get("penalty_no_play")):
                continue

            is_pass = _flag(row.get("pass")) or _flag(row.get("sack"))
            is_rush = _flag(row.get("rush"))
            if is_pass or is_rush:
                fit.scrimmage += 1
                if is_pass:
                    fit.pass_like += 1
                    fit.sacks += int(_flag(row.get("sack")))
                    if _flag(row.get("pass_attempt")):
                        fit.pass_attempts += 1
                        fit.completions += int(_flag(row.get("completion")))
                if is_rush:
                    fit.rush += 1
                fit.success += int(_flag(row.get("EPA_success")))
                yards = _f(row.get("statYardage"))
                fit.explosive += int(yards is not None and yards >= 20.0)
                fit.turnovers += int(_flag(row.get("int")) or _flag(row.get("fumble_lost")))
                game = str(row.get("game_id") or "").strip()
                clock = _f(row.get("start.adj_TimeSecsRem"))
                if game and clock is not None:
                    key = (game, team)
                    prior = last_clock.get(key)
                    if prior is not None:
                        elapsed = prior - clock
                        if 5.0 <= elapsed <= 60.0:
                            fit.pace_sum += elapsed
                            fit.pace_n += 1
                    last_clock[key] = clock

            down = _f(row.get("down") or row.get("start.down"))
            yte = _f(row.get("start.yardsToEndzone"))
            if down == 4 and yte is not None and yte <= 35:
                fit.fourth_short_field += 1
                fit.fourth_short_field_fg += int(_flag(row.get("fg_attempt")))
            if _flag(row.get("fg_attempt")):
                fit.fg_attempts += 1
                fit.fg_made += int(_flag(row.get("fg_made")))
            xp, two, made = _try_kind(row)
            if xp:
                fit.xp_attempts += 1
                fit.xp_made += int(made)
            if two:
                fit.two_attempts += 1
                fit.two_made += int(made)

    league_fg, league_xp, league_two, league_special = _special_team_league_rates(stats)
    drive_profiles: dict[str, dict[str, float]] = {}
    special_profiles: dict[str, dict[str, float]] = {}
    diagnostics_rows: dict[str, dict[str, int]] = {}
    excluded: dict[str, str] = {}
    for team in sorted(stats):
        fit = stats[team]
        if fit.scrimmage < MIN_SCRIMMAGE_PLAYS or fit.pass_attempts <= 0 or fit.pass_like <= 0 or fit.fourth_short_field <= 0 or fit.pace_n <= 0:
            excluded[team] = "INSUFFICIENT_DEPTH"
            continue
        drive_profiles[team] = fit.drive_profile(team, league_fg)
        special_profiles[team] = fit.special_profile(league_fg, league_xp, league_two)
        diagnostics_rows[team] = {
            "source_rows": row_counts[team], "scrimmage": fit.scrimmage,
            "pass_like": fit.pass_like, "rush": fit.rush,
            "pass_attempts": fit.pass_attempts, "fg_attempts": fit.fg_attempts,
            "xp_attempts": fit.xp_attempts, "two_point_attempts": fit.two_attempts,
            "pace_observations": fit.pace_n,
        }
    if len(drive_profiles) < MIN_TEAM_COUNT:
        raise ValueError(f"CFB_PROP_FIT_TEAM_COUNT_INSUFFICIENT:{len(drive_profiles)}")

    artifact = {
        "schema_version": ARTIFACT_SCHEMA, "sport": "CFB",
        "artifact_version": version, "training_version": TRAINING_VERSION,
        "code_git_sha": git_sha, "source_manifest_sha256": manifest_sha,
        "team_drive_profiles": drive_profiles,
        "team_special_teams_rates": special_profiles,
        "fit_scope": {"seasons": sorted(allowed_seasons), "season_type": "REGULAR",
                      "minimum_scrimmage_plays": MIN_SCRIMMAGE_PLAYS,
                      "team_count": len(drive_profiles)},
    }
    diagnostics = {
        "schema_version": "CFB_PROP_FIT_DIAGNOSTICS_V1", "status": "PASS",
        "code_git_sha": git_sha, "source_manifest": manifest_payload,
        "source_manifest_sha256": manifest_sha, "team_count": len(drive_profiles),
        "team_rows": diagnostics_rows, "excluded_teams": excluded,
        "league_special_teams": league_special,
        "governance": {"sportsbook_fields_consumed": False,
                       "market_prices_can_create_model_p": False,
                       "promotion_authority": False},
    }
    return artifact, diagnostics
