"""In-game participation verification for live repricing.

Context: on 2026-10-11 a pregame model priced Ravens 1H ML as if Lamar
Jackson were playing (Huntley started) and MLB cards as if the probable
pitchers were on the mound -- all picks withdrawn as unreliable. The rule
generalized from that incident: missing key matchup input = blocked /
downgraded, never silently priced.

This module applies the same discipline IN-GAME. A mid-game exit by a key
participant (starting QB, and by extension any modeled key participant)
invalidates the pregame score means the repricing path scales. Because no
free feed reliably reports every mid-game injury, the rule is fail-closed:

  - NFL/CFB: ESPN's public summary endpoint carries a per-team `injuries`
    section whose entries carry a last-updated timestamp. An entry with
    position QB, status Out, and a timestamp AFTER kickoff is treated as a
    material in-game participation change -> the price is REFUSED with
    LIVE_PARTICIPATION_CHANGE_UNPRICED. Other post-kickoff "Out" entries
    are surfaced as warnings (stated scoping choice: QB is the modeled key
    participant for football team strength; finer participation-impact
    modeling is queued behind the harness).
  - If the summary source is unavailable or has no injuries section, the
    check cannot verify -> LIVE_PARTICIPATION_UNVERIFIED (refuse; a missing
    verification source is a reason code, not a guess).
  - MLB: the StatsAPI live feed verifies the current pitcher and batter
    every pitch. Pitching changes are routine (starters always exit), so a
    change is a diagnostic, not a block: reliever-impact modeling is
    NOT_WIRED (see sportsedge.live_reprice). An early pull (before the
    4th inning) is flagged as a warning.

Pregame participation (inactives known before kickoff) is handled by the
pregame-means reconstruction, which inherits whatever participation
adjustments free_models.context_for / score_means carry (including the
in-progress injury/QB hotfix wiring injury_points + verified inactives
into the means). Only post-kickoff changes are this module's scope.

User-submitted participation flags are NEVER accepted: per the standing
intake discipline, issue payloads are untrusted odds intake, and a
participation verification flag from the user is not independent evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping


class ParticipationError(ValueError):
    """Fail-closed participation error. The message is the reason code."""


# Statuses that mean "not participating" in ESPN's injury feed.
OUT_STATUSES = {"Out", "INJURY_STATUS_OUT"}
# Positions whose mid-game exit is treated as model-invalidating.
KEY_POSITIONS = {"QB"}


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(frozen=True)
class ParticipationSignal:
    team: str
    side: str  # HOME | AWAY | UNKNOWN
    athlete: str
    position: str | None
    status: str
    reported_at: datetime | None

    @property
    def is_out(self) -> bool:
        return self.status in OUT_STATUSES

    @property
    def is_key_position(self) -> bool:
        return (self.position or "").upper() in KEY_POSITIONS

    @property
    def is_midgame(self) -> bool:
        return self.reported_at is not None and self.reported_at > self._kickoff

    _kickoff: datetime | None = field(default=None, repr=False, compare=False)

    def after(self, kickoff: datetime) -> "ParticipationSignal":
        return ParticipationSignal(
            team=self.team, side=self.side, athlete=self.athlete,
            position=self.position, status=self.status,
            reported_at=self.reported_at, _kickoff=kickoff)


@dataclass(frozen=True)
class ParticipationReport:
    sport: str
    event_id: str
    checked_at: datetime
    source: str
    source_ok: bool
    source_error: str | None
    signals: tuple[ParticipationSignal, ...] = ()
    warnings: tuple[str, ...] = ()


ESPN_SUMMARY_URLS = {
    "NFL": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}",
    "CFB": ("https://site.api.espn.com/apis/site/v2/sports/football/"
            "college-football/summary?event={event_id}"),
}


def parse_espn_summary_injuries(summary: Mapping[str, Any], *,
                                home_team: str, away_team: str,
                                checked_at: datetime) -> ParticipationReport:
    """Parse the ESPN summary `injuries` section into signals. Fail closed."""
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ParticipationError("CHECKED_AT_TIMEZONE_REQUIRED")
    if not isinstance(summary, Mapping):
        raise ParticipationError("SUMMARY_NOT_MAPPING")
    groups = summary.get("injuries")
    if groups is None:
        return ParticipationReport(
            sport="", event_id="", checked_at=checked_at,
            source="ESPN_SUMMARY_INJURIES", source_ok=False,
            source_error="INJURIES_SECTION_MISSING")
    signals: list[ParticipationSignal] = []
    for group in groups or []:
        team = (group or {}).get("team") or {}
        team_name = str(team.get("displayName") or team.get("abbreviation") or "")
        side = _side_of(team_name, home_team, away_team)
        for entry in (group or {}).get("injuries") or []:
            athlete = (entry or {}).get("athlete") or {}
            position_raw = athlete.get("position")
            if isinstance(position_raw, Mapping):
                position = position_raw.get("abbreviation")
            else:
                position = position_raw
            signals.append(ParticipationSignal(
                team=team_name, side=side,
                athlete=str(athlete.get("displayName") or ""),
                position=str(position) if position else None,
                status=str(entry.get("status") or ""),
                reported_at=_parse_dt(entry.get("date"))))
    return ParticipationReport(
        sport="", event_id="", checked_at=checked_at,
        source="ESPN_SUMMARY_INJURIES", source_ok=True, source_error=None,
        signals=tuple(signals))


def _side_of(team_name: str, home_team: str, away_team: str) -> str:
    def norm(v: str) -> str:
        return "".join(c for c in v.lower() if c.isalnum())
    t, h, a = norm(team_name), norm(home_team), norm(away_team)
    if t and t == h:
        return "HOME"
    if t and t == a:
        return "AWAY"
    return "UNKNOWN"


def check_football_participation(report: ParticipationReport,
                                 kickoff: datetime
                                 ) -> tuple[str, dict[str, Any]]:
    """Apply the fail-closed participation rule.

    Returns (outcome, detail) where outcome is one of:
      PARTICIPATION_OK -- verified, no material mid-game change signal.
      LIVE_PARTICIPATION_CHANGE_UNPRICED -- a key participant (QB) went Out
        after kickoff; refuse the price.
      LIVE_PARTICIPATION_UNVERIFIED -- the source could not verify; refuse.
    """
    if kickoff.tzinfo is None or kickoff.utcoffset() is None:
        raise ParticipationError("KICKOFF_TIMEZONE_REQUIRED")
    if not report.source_ok:
        return ("LIVE_PARTICIPATION_UNVERIFIED", {
            "reason": ("LIVE_PARTICIPATION_UNVERIFIED: in-game participation "
                       "could not be verified (source: "
                       + report.source + "; error: "
                       + str(report.source_error) + "). Refusing rather than "
                       "repricing on possibly-stale pregame assumptions."),
            "warnings": list(report.warnings),
        })
    midgame_outs = [s.after(kickoff) for s in report.signals
                    if s.is_out and s.reported_at is not None
                    and s.reported_at > kickoff]
    key_outs = [s for s in midgame_outs if s.is_key_position]
    warnings = list(report.warnings)
    for s in midgame_outs:
        if not s.is_key_position:
            warnings.append(
                f"IN_GAME_OUT_NON_QB:{s.side}:{s.team}:{s.athlete}"
                f"({s.position or '?'}) reported Out at "
                f"{s.reported_at.isoformat()}; surfaced as warning, not a "
                f"block (stated scoping: QB is the modeled key participant)")
    if key_outs:
        s = key_outs[0]
        return ("LIVE_PARTICIPATION_CHANGE_UNPRICED", {
            "reason": ("LIVE_PARTICIPATION_CHANGE_UNPRICED: "
                       f"{s.team} {s.position} {s.athlete} reported Out at "
                       f"{s.reported_at.isoformat()} (after kickoff "
                       f"{kickoff.isoformat()}). Pregame means assumed the "
                       f"pre-kickoff participant; repricing on them now "
                       f"would be stale. Refused."),
            "signals": [f"{x.team}:{x.athlete}:{x.status}@{x.reported_at.isoformat()}"
                        for x in key_outs],
            "warnings": warnings,
        })
    return ("PARTICIPATION_OK", {
        "reason": ("PARTICIPATION_VERIFIED_NO_MIDGAME_QB_CHANGE: ESPN summary "
                   "injury feed checked; no QB Out reported after kickoff."),
        "signals_checked": len(report.signals),
        "warnings": warnings,
    })


def build_football_participation_report(sport: str, event_id: str,
                                        summary_data: Mapping[str, Any] | None,
                                        *, home_team: str, away_team: str,
                                        now: datetime) -> ParticipationReport:
    """Build a ParticipationReport from an already-fetched summary payload."""
    sport = str(sport).upper()
    if not event_id:
        raise ParticipationError("EVENT_ID_REQUIRED")
    if summary_data is None:
        return ParticipationReport(
            sport=sport, event_id=str(event_id), checked_at=now,
            source="ESPN_SUMMARY_INJURIES", source_ok=False,
            source_error="FETCH_FAILED:empty_payload")
    try:
        report = parse_espn_summary_injuries(
            summary_data, home_team=home_team, away_team=away_team,
            checked_at=now)
    except ParticipationError as exc:
        return ParticipationReport(
            sport=sport, event_id=str(event_id), checked_at=now,
            source="ESPN_SUMMARY_INJURIES", source_ok=False,
            source_error=f"PARSE_FAILED:{exc}")
    return ParticipationReport(
        sport=sport, event_id=str(event_id), checked_at=now,
        source=report.source, source_ok=report.source_ok,
        source_error=report.source_error, signals=report.signals,
        warnings=report.warnings)


def fetch_football_participation(sport: str, event_id: str, *,
                                 home_team: str, away_team: str,
                                 get_json: Callable[[str], Any],
                                 now: datetime) -> ParticipationReport:
    """Fetch and parse the ESPN summary injury feed for one event."""
    sport = str(sport).upper()
    if sport not in ESPN_SUMMARY_URLS:
        raise ParticipationError(f"UNSUPPORTED_SPORT:{sport}")
    if not event_id:
        raise ParticipationError("EVENT_ID_REQUIRED")
    url = ESPN_SUMMARY_URLS[sport].format(event_id=event_id)
    try:
        data = get_json(url)
    except Exception as exc:
        return ParticipationReport(
            sport=sport, event_id=str(event_id), checked_at=now,
            source="ESPN_SUMMARY_INJURIES", source_ok=False,
            source_error=f"FETCH_FAILED:{type(exc).__name__}")
    return build_football_participation_report(
        sport, event_id, data if isinstance(data, dict) else None,
        home_team=home_team, away_team=away_team, now=now)


# ---------------------------------------------------------------------------
# MLB: probable vs current pitcher (diagnostic; pitching changes are routine)
# ---------------------------------------------------------------------------

def mlb_pitcher_participation(probable_pitcher: Mapping[str, Any] | None,
                              current_pitcher_id: int | None,
                              current_pitcher_name: str | None,
                              pitching_side: str,
                              inning: int | None) -> dict[str, Any]:
    """Compare the probable starter with the pitcher actually on the mound.

    A change is a DIAGNOSTIC, not a block: starters exit every game and
    reliever-impact modeling is NOT_WIRED. An early pull (before the 4th)
    is flagged as a warning because it most likely signals injury/trouble
    rather than routine bullpen usage.
    """
    probable_id = (probable_pitcher or {}).get("id")
    probable_name = str((probable_pitcher or {}).get("fullName") or "")
    changed = (isinstance(probable_id, int) and isinstance(current_pitcher_id, int)
               and probable_id != current_pitcher_id)
    early_pull = bool(changed and inning is not None and inning < 4)
    return {
        "pitching_side": pitching_side,
        "probable_pitcher": probable_name or None,
        "current_pitcher": current_pitcher_name,
        "pitcher_changed": changed,
        "early_pull_warning": early_pull,
        "pricing_effect": ("NOT_WIRED: reliever-impact modeling not built; "
                           "full-game team-level means retained"),
        "warning": ("EARLY_PITCHER_PULL: probable starter exited before the "
                    "4th inning; likely injury/trouble -- price retained on "
                    "team-level means, treat with caution")
        if early_pull else None,
    }


__all__ = [
    "ParticipationError",
    "ParticipationReport",
    "ParticipationSignal",
    "build_football_participation_report",
    "check_football_participation",
    "fetch_football_participation",
    "mlb_pitcher_participation",
    "parse_espn_summary_injuries",
]
