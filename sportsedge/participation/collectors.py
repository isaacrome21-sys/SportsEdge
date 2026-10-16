"""Collectors for the PIT-reconstructible participation signals.

Sources are the free nflverse data releases (the foundation doc's named
sources). Each collector run:

1. Stores the raw payload in the archive FIRST (immutable, SHA-addressed).
2. Parses rows into ParticipationRecords with conservative
   ``available_from_utc`` bounds stamped per the foundation's rules.
3. Appends a receipt: source URL, fetch time, raw SHA, row counts, and
   fail-closed rejection counts by reason. Rejected rows are NEVER
   silently repaired; they are counted with their reason.

Signals collected: S3 final designations, S4 practice status, S5 weekly
roster/reserve status, S6 depth-chart QB ordering, S2 snap actuals, and
S1 starter actuals derived from snaps (cross-checked against the
schedule's listed starting QBs). S7/S8 have NO collector: they are
forward-capture only and any historical ingest is refused by schema
validation.
"""

from __future__ import annotations

import io
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone

import pandas as pd

from .archive import ParticipationArchive
from .schema import (
    AVAIL_HISTORICAL,
    AVAIL_RETROSPECTIVE,
    BASIS_COMPLETION_WINDOW,
    BASIS_FINAL_REPORT_RULE,
    BASIS_PRIOR_WEEK_LAG,
    REJ_DUPLICATE_CONFLICTING,
    REJ_GAME_BINDING_UNRESOLVED,
    REJ_MISSING_GSIS_ID,
    REJ_MISSING_TEAM_WEEK,
    REJ_SCHEMA_COLUMN_MISSING,
    REJ_SNAPS_SHARE_RANGE,
    REJ_SNAPS_TEAM_TOTAL,
    REJ_SOURCE_FILE_EMPTY,
    REJ_STARTER_AMBIGUOUS,
    SIGNAL_DEPTH_CHART,
    SIGNAL_INJURY_DESIGNATION,
    SIGNAL_PRACTICE_STATUS,
    SIGNAL_ROSTER_STATUS,
    SIGNAL_SNAP_ACTUAL,
    SIGNAL_STARTER_ACTUAL,
    TIMING_CADENCE,
    USE_PREGAME_FEATURE,
    USE_TRAINING_TARGET,
    USE_VALIDATION_LABEL,
    ParticipationRecord,
    iso_z,
)
from .timing import (
    completion_bound_utc,
    final_report_bound_utc,
    kickoff_utc,
    week_snapshot_bound_utc,
)

RELEASE = "https://github.com/nflverse/nflverse-data/releases/download"
URL_TEMPLATES = {
    "injuries": RELEASE + "/injuries/injuries_{season}.csv",
    "snap_counts": RELEASE + "/snap_counts/snap_counts_{season}.csv",
    "weekly_rosters": RELEASE + "/weekly_rosters/roster_weekly_{season}.csv",
    "depth_charts": RELEASE + "/depth_charts/depth_charts_{season}.csv",
}
GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
SOURCE_NAME = "nflverse-data release (github.com/nflverse/nflverse-data)"

TEAM_ALIASES = {"LA": "LAR", "STL": "LAR", "SD": "LAC", "OAK": "LV"}


def norm_team(code) -> str:
    text = str(code or "").strip()
    return TEAM_ALIASES.get(text, text)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "sportsedge-participation/1.0"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# Schedule context
# ---------------------------------------------------------------------------
class Schedule:
    """Game index built from nflverse games.csv."""

    def __init__(self, games: pd.DataFrame):
        self.games = games
        self.by_id: dict[str, dict] = {}
        self.by_team_week: dict[tuple[int, int, str], dict] = {}
        self.week_last_gameday: dict[tuple[int, int], date] = {}
        for row in games.itertuples(index=False):
            gameday = date.fromisoformat(str(row.gameday)[:10])
            game = {
                "game_id": row.game_id,
                "season": int(row.season),
                "week": int(row.week),
                "game_type": row.game_type,
                "gameday": gameday,
                "kickoff_utc": kickoff_utc(gameday, getattr(row, "gametime", None)),
                "home_team": norm_team(row.home_team),
                "away_team": norm_team(row.away_team),
                "home_qb_id": getattr(row, "home_qb_id", None),
                "away_qb_id": getattr(row, "away_qb_id", None),
                "home_qb_name": getattr(row, "home_qb_name", None),
                "away_qb_name": getattr(row, "away_qb_name", None),
            }
            self.by_id[game["game_id"]] = game
            self.by_team_week[(game["season"], game["week"], game["home_team"])] = game
            self.by_team_week[(game["season"], game["week"], game["away_team"])] = game
            key = (game["season"], game["week"])
            if key not in self.week_last_gameday or gameday > self.week_last_gameday[key]:
                self.week_last_gameday[key] = gameday

    def game_for_team_week(self, season: int, week: int, team: str) -> dict | None:
        return self.by_team_week.get((season, week, team))

    def next_game_for_team(self, season: int, week: int, team: str) -> dict | None:
        """First game for the team in a week >= the given week (bye handling)."""
        for w in range(week, week + 4):
            game = self.by_team_week.get((season, w, team))
            if game is not None:
                return game
        return None

    def reg_team_games(self, season: int) -> list[tuple[str, dict]]:
        """(team, game) pairs for regular-season games of a season."""
        out = []
        for game in self.by_id.values():
            if game["season"] == season and game["game_type"] == "REG":
                out.append((game["away_team"], game))
                out.append((game["home_team"], game))
        return out


def load_schedule(raw: bytes) -> Schedule:
    df = pd.read_csv(io.BytesIO(raw), low_memory=False)
    return Schedule(df)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _read_csv(raw: bytes, required: list[str], rejections: Counter) -> pd.DataFrame | None:
    if raw is None or len(raw.strip()) == 0:
        rejections[REJ_SOURCE_FILE_EMPTY] += 1
        return None
    df = pd.read_csv(io.BytesIO(raw), low_memory=False, dtype={"gsis_id": str})
    if len(df) == 0:
        rejections[REJ_SOURCE_FILE_EMPTY] += 1
        return None
    missing = [c for c in required if c not in df.columns]
    if missing:
        rejections[REJ_SCHEMA_COLUMN_MISSING] += 1
        return None
    return df


def _clean_gsis(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


# ---------------------------------------------------------------------------
# S3 / S4 -- injuries
# ---------------------------------------------------------------------------
_PRACTICE_MAP = (
    ("Did Not Participate", "DNP"),
    ("Limited Participation", "LP"),
    ("Full Participation", "FP"),
)


def practice_class(raw_status) -> str | None:
    if raw_status is None or (isinstance(raw_status, float) and pd.isna(raw_status)):
        return None
    text = str(raw_status)
    for needle, code in _PRACTICE_MAP:
        if needle in text:
            return code
    return "OTHER"


def collect_injuries(archive: ParticipationArchive, schedule: Schedule, season: int,
                     raw: bytes, source_url: str, fetched_at: datetime) -> dict:
    rejections: Counter = Counter()
    sha, ref = archive.store_raw_payload(raw)
    df = _read_csv(raw, ["season", "game_type", "team", "week", "gsis_id",
                          "report_status", "practice_status", "full_name",
                          "position", "report_primary_injury", "date_modified"],
                   rejections)
    receipt = _base_receipt("injuries", season, source_url, fetched_at, sha, ref, df)
    if df is None:
        receipt["rejections"] = dict(rejections)
        archive.append_receipt(receipt)
        return receipt

    seen: dict[tuple, str | None] = {}
    records: list[ParticipationRecord] = []
    modified_after_kickoff = 0
    for row in df.itertuples(index=False):
        gsis = _clean_gsis(row.gsis_id)
        team = norm_team(row.team)
        week = int(row.week) if pd.notna(row.week) else None
        if gsis is None:
            rejections[REJ_MISSING_GSIS_ID] += 1
            continue
        if not team or week is None:
            rejections[REJ_MISSING_TEAM_WEEK] += 1
            continue
        game = schedule.next_game_for_team(season, week, team)
        if game is None:
            rejections[REJ_GAME_BINDING_UNRESOLVED] += 1
            continue
        key = (row.game_type, week, gsis)
        designation = None if pd.isna(row.report_status) else str(row.report_status)
        if key in seen:
            if seen[key] != designation:
                rejections[REJ_DUPLICATE_CONFLICTING] += 1
            continue
        seen[key] = designation
        bound = final_report_bound_utc(game["gameday"], team)
        modified = None
        if pd.notna(getattr(row, "date_modified", None)):
            modified = str(row.date_modified)
            try:
                mts = datetime.fromisoformat(modified.replace("Z", "+00:00"))
                if mts > game["kickoff_utc"]:
                    modified_after_kickoff += 1
            except ValueError:
                pass
        base = dict(
            season=season, week=week, team=team,
            captured_at_utc=iso_z(fetched_at),
            available_from_utc=iso_z(bound),
            availability_class=AVAIL_HISTORICAL,
            availability_basis=BASIS_FINAL_REPORT_RULE,
            timing_evidence=TIMING_CADENCE,
            source_name=SOURCE_NAME, source_url=source_url,
            source_modified_at_utc=modified,
            raw_payload_sha256=sha,
            game_id=game["game_id"], kickoff_utc=iso_z(game["kickoff_utc"]),
            gsis_id=gsis, player_name=str(row.full_name) if pd.notna(row.full_name) else None,
            position=str(row.position) if pd.notna(row.position) else None,
        )
        records.append(ParticipationRecord(
            signal_type=SIGNAL_INJURY_DESIGNATION, source_signal="S3",
            permitted_uses=[USE_PREGAME_FEATURE],
            payload={"designation": designation, "game_type": row.game_type,
                     "primary_injury": None if pd.isna(row.report_primary_injury)
                     else str(row.report_primary_injury)},
            **base))
        pclass = practice_class(row.practice_status)
        if pclass is not None:
            records.append(ParticipationRecord(
                signal_type=SIGNAL_PRACTICE_STATUS, source_signal="S4",
                permitted_uses=[USE_PREGAME_FEATURE],
                payload={"practice_status_class": pclass,
                         "practice_status_raw": str(row.practice_status),
                         "game_type": row.game_type},
                **base))
    n = archive.append_records(records)
    receipt.update(records_written=n,
                   rejections=dict(rejections),
                   notes={"date_modified_after_kickoff_rows": modified_after_kickoff,
                          "date_modified_note": "bookkeeping timestamp, NOT trusted "
                          "as publication time (foundation S3 risk 2); admissibility "
                          "rests on the final-report cadence rule"})
    archive.append_receipt(receipt)
    return receipt


# ---------------------------------------------------------------------------
# S5 -- weekly rosters
# ---------------------------------------------------------------------------
def collect_rosters(archive: ParticipationArchive, schedule: Schedule, season: int,
                    raw: bytes, source_url: str, fetched_at: datetime) -> dict:
    rejections: Counter = Counter()
    sha, ref = archive.store_raw_payload(raw)
    df = _read_csv(raw, ["season", "team", "week", "game_type", "status", "gsis_id",
                          "full_name", "position", "status_description_abbr",
                          "depth_chart_position", "pfr_id"], rejections)
    receipt = _base_receipt("weekly_rosters", season, source_url, fetched_at, sha, ref, df)
    if df is None:
        receipt["rejections"] = dict(rejections)
        archive.append_receipt(receipt)
        return receipt

    records: list[ParticipationRecord] = []
    seen: dict[tuple, str] = {}
    for row in df.itertuples(index=False):
        gsis = _clean_gsis(row.gsis_id)
        team = norm_team(row.team)
        week = int(row.week) if pd.notna(row.week) else None
        if gsis is None:
            rejections[REJ_MISSING_GSIS_ID] += 1
            continue
        if not team or week is None:
            rejections[REJ_MISSING_TEAM_WEEK] += 1
            continue
        status = str(row.status) if pd.notna(row.status) else None
        key = (row.game_type, week, gsis)
        if key in seen:
            if seen[key] != status:
                rejections[REJ_DUPLICATE_CONFLICTING] += 1
            continue
        seen[key] = status
        last_day = schedule.week_last_gameday.get((season, week))
        if last_day is None:
            rejections[REJ_GAME_BINDING_UNRESOLVED] += 1
            continue
        bound = week_snapshot_bound_utc(last_day)
        records.append(ParticipationRecord(
            signal_type=SIGNAL_ROSTER_STATUS, source_signal="S5",
            season=season, week=week, team=team,
            captured_at_utc=iso_z(fetched_at),
            available_from_utc=iso_z(bound),
            availability_class=AVAIL_HISTORICAL,
            availability_basis=BASIS_PRIOR_WEEK_LAG,
            timing_evidence=TIMING_CADENCE,
            permitted_uses=[USE_PREGAME_FEATURE],
            source_name=SOURCE_NAME, source_url=source_url,
            raw_payload_sha256=sha,
            gsis_id=gsis,
            player_name=str(row.full_name) if pd.notna(row.full_name) else None,
            position=str(row.position) if pd.notna(row.position) else None,
            payload={"status": status,
                     "status_description_abbr": None if pd.isna(row.status_description_abbr)
                     else str(row.status_description_abbr),
                     "depth_chart_position": None if pd.isna(row.depth_chart_position)
                     else str(row.depth_chart_position),
                     "game_type": row.game_type,
                     "pfr_id": _clean_gsis(getattr(row, "pfr_id", None))},
        ))
    n = archive.append_records(records)
    receipt.update(records_written=n, rejections=dict(rejections),
                   notes={"status_granularity": "status codes are a coarse bucket "
                          "(ACT/DEV/RES/INA/CUT/...); reserve SUBTYPE is carried only "
                          "as opaque status_description_abbr codes with no in-file "
                          "codebook -- subtype is therefore UNRESOLVED, bucket is not"})
    archive.append_receipt(receipt)
    return receipt


# ---------------------------------------------------------------------------
# S6 -- depth charts (QB rows only; the doc's permitted use is backup identity)
# ---------------------------------------------------------------------------
def collect_depth_charts(archive: ParticipationArchive, schedule: Schedule, season: int,
                         raw: bytes, source_url: str, fetched_at: datetime) -> dict:
    rejections: Counter = Counter()
    sha, ref = archive.store_raw_payload(raw)
    df = _read_csv(raw, ["season", "club_code", "week", "game_type", "depth_position",
                         "depth_team", "gsis_id", "full_name", "formation"],
                   rejections)
    receipt = _base_receipt("depth_charts", season, source_url, fetched_at, sha, ref, df)
    if df is None:
        receipt["rejections"] = dict(rejections)
        archive.append_receipt(receipt)
        return receipt

    out_of_scope = 0
    records: list[ParticipationRecord] = []
    for row in df.itertuples(index=False):
        if str(row.depth_position) != "QB":
            out_of_scope += 1
            continue
        gsis = _clean_gsis(row.gsis_id)
        team = norm_team(row.club_code)
        week = int(row.week) if pd.notna(row.week) else None
        if gsis is None:
            rejections[REJ_MISSING_GSIS_ID] += 1
            continue
        if not team or week is None:
            rejections[REJ_MISSING_TEAM_WEEK] += 1
            continue
        try:
            rank = int(float(row.depth_team))
        except (TypeError, ValueError):
            rejections[REJ_GAME_BINDING_UNRESOLVED] += 1
            continue
        last_day = schedule.week_last_gameday.get((season, week))
        if last_day is None:
            rejections[REJ_GAME_BINDING_UNRESOLVED] += 1
            continue
        bound = week_snapshot_bound_utc(last_day)
        records.append(ParticipationRecord(
            signal_type=SIGNAL_DEPTH_CHART, source_signal="S6",
            season=season, week=week, team=team,
            captured_at_utc=iso_z(fetched_at),
            available_from_utc=iso_z(bound),
            availability_class=AVAIL_HISTORICAL,
            availability_basis=BASIS_PRIOR_WEEK_LAG,
            timing_evidence=TIMING_CADENCE,
            permitted_uses=[USE_PREGAME_FEATURE],
            source_name=SOURCE_NAME, source_url=source_url,
            raw_payload_sha256=sha,
            gsis_id=gsis,
            player_name=str(row.full_name) if pd.notna(row.full_name) else None,
            position="QB",
            payload={"depth_rank": rank, "game_type": row.game_type,
                     "formation": None if pd.isna(row.formation) else str(row.formation)},
        ))
    n = archive.append_records(records)
    receipt.update(records_written=n, rejections=dict(rejections),
                   notes={"rows_out_of_scope_non_qb": out_of_scope,
                          "scope_note": "foundation S6 permitted use is backup-QB "
                          "identity only; non-QB depth rows are counted, not archived"})
    archive.append_receipt(receipt)
    return receipt


# ---------------------------------------------------------------------------
# S2 -- snap counts (+ S1 starter derivation)
# ---------------------------------------------------------------------------
def collect_snap_counts(archive: ParticipationArchive, schedule: Schedule, season: int,
                        raw: bytes, source_url: str, fetched_at: datetime,
                        pfr_to_gsis: dict[tuple[int, str], str] | None = None) -> dict:
    rejections: Counter = Counter()
    sha, ref = archive.store_raw_payload(raw)
    df = _read_csv(raw, ["game_id", "season", "game_type", "week", "player",
                         "pfr_player_id", "position", "team", "opponent",
                         "offense_snaps", "offense_pct", "defense_snaps",
                         "defense_pct", "st_snaps", "st_pct"], rejections)
    receipt = _base_receipt("snap_counts", season, source_url, fetched_at, sha, ref, df)
    if df is None:
        receipt["rejections"] = dict(rejections)
        archive.append_receipt(receipt)
        return receipt

    records: list[ParticipationRecord] = []
    team_game_max_off: Counter = Counter()
    for row in df.itertuples(index=False):
        game = schedule.by_id.get(str(row.game_id))
        if game is None:
            rejections[REJ_GAME_BINDING_UNRESOLVED] += 1
            continue
        team = norm_team(row.team)
        pcts = [row.offense_pct, row.defense_pct, row.st_pct]
        if any(pd.notna(p) and not (0.0 <= float(p) <= 1.0) for p in pcts):
            rejections[REJ_SNAPS_SHARE_RANGE] += 1
            continue
        team_game_max_off[(str(row.game_id), team)] = max(
            team_game_max_off[(str(row.game_id), team)],
            int(row.offense_snaps) if pd.notna(row.offense_snaps) else 0,
        )
        records.append(ParticipationRecord(
            signal_type=SIGNAL_SNAP_ACTUAL, source_signal="S9",
            season=season, week=int(row.week), team=team,
            captured_at_utc=iso_z(fetched_at),
            available_from_utc=iso_z(completion_bound_utc(game["kickoff_utc"])),
            availability_class=AVAIL_RETROSPECTIVE,
            availability_basis=BASIS_COMPLETION_WINDOW,
            timing_evidence="NONE",
            permitted_uses=[USE_TRAINING_TARGET, USE_VALIDATION_LABEL],
            source_name=SOURCE_NAME, source_url=source_url,
            raw_payload_sha256=sha,
            game_id=str(row.game_id), kickoff_utc=iso_z(game["kickoff_utc"]),
            gsis_id=(pfr_to_gsis or {}).get((season, str(row.pfr_player_id))),
            player_name=str(row.player),
            position=str(row.position) if pd.notna(row.position) else None,
            payload={"pfr_player_id": str(row.pfr_player_id),
                     "opponent": norm_team(row.opponent),
                     "offense_snaps": None if pd.isna(row.offense_snaps) else int(row.offense_snaps),
                     "offense_pct": None if pd.isna(row.offense_pct) else float(row.offense_pct),
                     "defense_snaps": None if pd.isna(row.defense_snaps) else int(row.defense_snaps),
                     "defense_pct": None if pd.isna(row.defense_pct) else float(row.defense_pct),
                     "st_snaps": None if pd.isna(row.st_snaps) else int(row.st_snaps),
                     "st_pct": None if pd.isna(row.st_pct) else float(row.st_pct),
                     "game_type": row.game_type},
        ))
    implausible = {k: v for k, v in team_game_max_off.items() if not (30 <= v <= 120)}
    if implausible:
        rejections[REJ_SNAPS_TEAM_TOTAL] += len(implausible)
    n = archive.append_records(records)

    starter_receipt = derive_starters(archive, schedule, season, df, sha,
                                      source_url, fetched_at, pfr_to_gsis or {})
    receipt.update(records_written=n, rejections=dict(rejections),
                   notes={"starter_derivation": starter_receipt,
                          "implausible_team_game_max_offense_snaps": len(implausible)})
    archive.append_receipt(receipt)
    return receipt


def derive_starters(archive: ParticipationArchive, schedule: Schedule, season: int,
                    snap_df: pd.DataFrame, sha: str, source_url: str,
                    fetched_at: datetime, pfr_to_gsis: dict) -> dict:
    """S1: actual starting QB per team-game = QB with most offensive snaps.

    Ties for the snap lead are fail-closed (STARTER_AMBIGUOUS_TIE, no
    record). The derived starter is cross-checked against the schedule's
    listed QB (games.csv away_qb_id/home_qb_id) when the pfr->gsis bridge
    resolves; the match flag is evidence, not an override.
    """
    rejections: Counter = Counter()
    records: list[ParticipationRecord] = []
    checked = matched = 0
    qbs = snap_df[snap_df["position"] == "QB"]
    for (game_id, team), grp in qbs.groupby(["game_id", "team"]):
        game = schedule.by_id.get(str(game_id))
        if game is None:
            rejections[REJ_GAME_BINDING_UNRESOLVED] += 1
            continue
        grp = grp.sort_values("offense_snaps", ascending=False)
        top = grp.iloc[0]
        if len(grp) > 1 and int(grp.iloc[1]["offense_snaps"]) == int(top["offense_snaps"]):
            rejections[REJ_STARTER_AMBIGUOUS] += 1
            continue
        team_n = norm_team(team)
        gsis = pfr_to_gsis.get((season, str(top["pfr_player_id"])))
        schedule_qb = game["home_qb_id"] if team_n == game["home_team"] else game["away_qb_id"]
        match = None
        if gsis is not None and schedule_qb is not None and not pd.isna(schedule_qb):
            checked += 1
            match = bool(gsis == str(schedule_qb))
            matched += int(match)
        records.append(ParticipationRecord(
            signal_type=SIGNAL_STARTER_ACTUAL, source_signal="S1",
            season=season, week=int(top["week"]), team=team_n,
            captured_at_utc=iso_z(fetched_at),
            available_from_utc=iso_z(completion_bound_utc(game["kickoff_utc"])),
            availability_class=AVAIL_RETROSPECTIVE,
            availability_basis=BASIS_COMPLETION_WINDOW,
            timing_evidence="NONE",
            permitted_uses=[USE_TRAINING_TARGET, USE_VALIDATION_LABEL],
            source_name=SOURCE_NAME, source_url=source_url,
            raw_payload_sha256=sha,
            game_id=str(game_id), kickoff_utc=iso_z(game["kickoff_utc"]),
            gsis_id=gsis,
            player_name=str(top["player"]), position="QB",
            payload={"offense_snaps": int(top["offense_snaps"]),
                     "offense_pct": None if pd.isna(top["offense_pct"]) else float(top["offense_pct"]),
                     "starter_basis": "MAX_OFFENSE_SNAPS_AMONG_QBS",
                     "schedule_qb_match": match,
                     "game_type": str(top["game_type"])},
        ))
    n = archive.append_records(records)
    return {"records_written": n, "rejections": dict(rejections),
            "schedule_qb_crosscheck": {"checked": checked, "matched": matched}}


def build_pfr_gsis_bridge(roster_raw: bytes, season: int) -> dict[tuple[int, str], str]:
    """(season, pfr_id) -> gsis_id from the weekly roster file (it carries
    both identity systems). Used only to enrich snap records; unresolved
    identities stay unresolved (counted in coverage), never guessed."""
    bridge: dict[tuple[int, str], str] = {}
    try:
        df = pd.read_csv(io.BytesIO(roster_raw), low_memory=False,
                         usecols=["pfr_id", "gsis_id"])
    except Exception:
        return bridge
    for row in df.itertuples(index=False):
        gsis = _clean_gsis(row.gsis_id)
        pfr = _clean_gsis(row.pfr_id)
        if gsis and pfr:
            bridge.setdefault((season, pfr), gsis)
    return bridge


# ---------------------------------------------------------------------------
def _base_receipt(collector: str, season: int, source_url: str, fetched_at: datetime,
                  sha: str, ref: str, df: pd.DataFrame | None) -> dict:
    return {
        "collector": collector,
        "season": season,
        "source_url": source_url,
        "fetched_at_utc": iso_z(fetched_at),
        "raw_payload_sha256": sha,
        "raw_payload_ref": ref,
        "rows_in": 0 if df is None else int(len(df)),
        "records_written": 0,
        "rejections": {},
        "notes": {},
    }


COLLECTORS = {
    "injuries": collect_injuries,
    "weekly_rosters": collect_rosters,
    "depth_charts": collect_depth_charts,
    "snap_counts": collect_snap_counts,
}
