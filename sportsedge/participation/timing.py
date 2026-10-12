"""Conservative availability-bound helpers.

Every bound here answers one question: "from what instant may this record
be treated as knowable?" Bounds are deliberately conservative -- where the
source gives only a date or a week, the record is treated as known at the
END of that granularity unit (foundation doc section 1, as-of rule), and
where publication timing is inferred from league cadence, the basis is
named CADENCE_INFERRED on the record, never presented as a timestamp.

Note on the completion window: the foundation doc (section 1) specifies a
4-hour post-start completion window for source games. That is the value
used here. (A separate 5-hour constant exists in the ESPN gamelog
extension for a different pipeline; the two are not interchangeable, and
this package follows the foundation doc.)
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

#: Foundation doc section 1 completion window for source games.
COMPLETION_WINDOW = timedelta(hours=4)

TEAM_TIMEZONES = {
    # Eastern
    "ATL": "America/New_York", "BAL": "America/New_York", "BUF": "America/New_York",
    "CAR": "America/New_York", "CIN": "America/New_York", "CLE": "America/New_York",
    "DET": "America/Detroit", "IND": "America/Indiana/Indianapolis",
    "JAX": "America/New_York", "MIA": "America/New_York", "NE": "America/New_York",
    "NYG": "America/New_York", "NYJ": "America/New_York", "PHI": "America/New_York",
    "PIT": "America/New_York", "TB": "America/New_York", "WAS": "America/New_York",
    # Central
    "CHI": "America/Chicago", "DAL": "America/Chicago", "GB": "America/Chicago",
    "HOU": "America/Chicago", "KC": "America/Chicago", "MIN": "America/Chicago",
    "NO": "America/Chicago", "TEN": "America/Chicago", "STL": "America/Chicago",
    # Mountain
    "ARI": "America/Phoenix", "DEN": "America/Denver",
    # Pacific
    "LAC": "America/Los_Angeles", "LAR": "America/Los_Angeles",
    "LA": "America/Los_Angeles", "LV": "America/Los_Angeles",
    "OAK": "America/Los_Angeles", "SD": "America/Los_Angeles",
    "SEA": "America/Los_Angeles", "SF": "America/Los_Angeles",
}
DEFAULT_TZ = "America/New_York"


def team_tz(team: str) -> ZoneInfo:
    return ZoneInfo(TEAM_TIMEZONES.get(team, DEFAULT_TZ))


def end_of_date_local_utc(d: date, team: str) -> datetime:
    """End of calendar date ``d`` in the team's local timezone, in UTC."""
    local = datetime.combine(d, time(23, 59, 59), tzinfo=team_tz(team))
    return local.astimezone(timezone.utc)


def kickoff_utc(gameday: date, gametime: str | None) -> datetime:
    """nflverse games.csv gametime is Eastern Time 'HH:MM' (24h)."""
    hh, mm = 13, 0  # conservative early-afternoon default if unparseable
    if gametime:
        try:
            parts = str(gametime).strip().split(":")
            hh, mm = int(parts[0]), int(parts[1][:2])
        except (ValueError, IndexError):
            pass
    local = datetime.combine(gameday, time(hh, mm), tzinfo=ZoneInfo("America/New_York"))
    return local.astimezone(timezone.utc)


def final_report_bound_utc(gameday: date, team: str) -> datetime:
    """Conservative bound for final injury designations (S3/S4).

    League cadence: final designations are public on the last practice day
    (Fri for Sun games, Wed for Thu games, Sat for Mon games). The uniform
    conservative bound is END OF (gameday - 1) team-local, which is before
    kickoff for every game day and later than the true publication for
    Sunday/Monday games -- the safe direction.
    """
    return end_of_date_local_utc(gameday - timedelta(days=1), team)


def week_snapshot_bound_utc(last_gameday_of_week: date) -> datetime:
    """Bound for weekly snapshots (rosters S5, depth charts S6).

    A week-W snapshot's compilation time inside week W is unknown, so it is
    admissible only once week W has fully concluded: bound = 12:00 UTC on
    the second day after the week's last gameday (after the Monday-night
    game has ended everywhere). Plainly after the week ends; conservative.
    """
    return datetime.combine(
        last_gameday_of_week + timedelta(days=2), time(12, 0), tzinfo=timezone.utc
    )


def completion_bound_utc(kickoff: datetime) -> datetime:
    """A source game's actuals are admissible from kickoff + completion
    window (foundation doc section 1 safeguard -- a safeguard, NOT proof
    of visibility at that historical instant)."""
    return kickoff + COMPLETION_WINDOW
