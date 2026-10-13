"""Live in-game state model for SportsEdge research repricing.

Free sources only:
  - MLB: MLB StatsAPI live feed
      https://statsapi.mlb.com/api/v1.1/game/{gamePk}/feed/live
  - NFL/CFB: ESPN public scoreboard API
      https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard

The state model carries every field Isaac's Phase 6 spec requires
(score, inning/outs/bases/count, current pitcher/batter for MLB;
quarter, clock, down, distance, yard line, score, timeouts, possession
for NFL/CFB). Fields that are parsed for display but NOT yet used in
pricing are listed explicitly by the repricing module with NOT_WIRED
reasons -- parsing a field never implies pricing from it.

Hard staleness rule: a state older than
LIVE_STATE_STALENESS_THRESHOLD_SECONDS (60s, inside Isaac's 60-90s band)
is STALE_LIVE_DATA and must never be priced. See docs/live_inplay.md for
the rationale. This is separate from the frozen LIVE_POLICY_V1 TTLs
(30s state / 20s quote), which govern the bet-decision path
(sportsedge.live_engine) that this research path does not invoke.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


# ---------------------------------------------------------------------------
# Freshness policy
# ---------------------------------------------------------------------------

# Isaac's band: 60-90s. Chosen value: 60s -- one full poll cycle is 30s, so
# 60s tolerates exactly one missed provider refresh before failing closed,
# while keeping in-game research cards actionable. Documented in
# docs/live_inplay.md.
LIVE_STATE_STALENESS_THRESHOLD_SECONDS = 60


class LiveStateError(ValueError):
    """Fail-closed live state error. The message is the reason code."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _aware(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise LiveStateError(f"{name}_NOT_DATETIME")
    if value.tzinfo is None or value.utcoffset() is None:
        raise LiveStateError(f"{name}_TIMEZONE_REQUIRED")
    return value


def _nonneg_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise LiveStateError(f"{name}_NOT_INT")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise LiveStateError(f"{name}_NOT_INT") from exc
    if out < 0:
        raise LiveStateError(f"{name}_NEGATIVE")
    return out


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        parsed = None
    if parsed is None:
        # MLB StatsAPI metaData.timeStamp format: 20261011_024449 (UTC).
        try:
            parsed = datetime.strptime(text, "%Y%m%d_%H%M%S").replace(
                tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _clock_to_seconds(display: Any) -> int | None:
    """ESPN displayClock like '12:34' -> seconds remaining in the period."""
    if display is None:
        return None
    text = str(display).strip()
    if ":" not in text:
        return None
    try:
        minutes, seconds = text.split(":", 1)
        total = int(minutes) * 60 + int(float(seconds))
    except (ValueError, TypeError):
        return None
    return total if total >= 0 else None


# ---------------------------------------------------------------------------
# MLB state
# ---------------------------------------------------------------------------

MLB_LIVE_STATUSES = {"Live", "In Progress"}
MLB_FINAL_STATUSES = {"Final", "Completed Early", "Completed Early: Rain",
                      "Completed Early: Mercy"}


@dataclass(frozen=True)
class MLBGameState:
    game_pk: int
    observed_at: datetime      # when WE retrieved the snapshot
    source_as_of: datetime     # provider's own timestamp (falls back to observed_at)
    status: str                # LIVE / FINAL / PREGAME / SUSPENDED / UNKNOWN
    inning: int | None
    half: str | None           # "top" | "bottom"
    outs: int | None
    balls: int | None
    strikes: int | None
    # (first, second, third) occupied; None when not derivable from the feed.
    # Display-only: bases/outs/count do NOT enter pricing (NOT_WIRED, see
    # sportsedge.live_reprice).
    bases: tuple[bool, bool, bool] | None
    bases_provenance: str | None
    batter_id: int | None
    batter_name: str | None
    pitcher_id: int | None
    pitcher_name: str | None
    home_score: int
    away_score: int
    home_team: str
    away_team: str
    kickoff: datetime | None = None
    # Probable starters from gameData.probablePitchers, {"id","fullName"}.
    # Compared against the live current pitcher for the participation
    # diagnostic (sportsedge.live_participation); a change is routine in
    # baseball and does NOT block pricing (reliever impact NOT_WIRED).
    probable_pitcher_away: Mapping[str, Any] | None = None
    probable_pitcher_home: Mapping[str, Any] | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _aware(self.observed_at, "observed_at")
        _aware(self.source_as_of, "source_as_of")
        if isinstance(self.game_pk, bool) or int(self.game_pk) <= 0:
            raise LiveStateError("GAME_PK_INVALID")
        if self.half not in (None, "top", "bottom"):
            raise LiveStateError("HALF_INVALID")
        for name in ("inning", "outs", "balls", "strikes"):
            value = getattr(self, name)
            if value is not None:
                _nonneg_int(value, name.upper())
        if self.outs is not None and self.outs > 3:
            raise LiveStateError("OUTS_IMPLAUSIBLE")
        if self.balls is not None and self.balls > 4:
            raise LiveStateError("BALLS_IMPLAUSIBLE")
        if self.strikes is not None and self.strikes > 3:
            raise LiveStateError("STRIKES_IMPLAUSIBLE")
        _nonneg_int(self.home_score, "HOME_SCORE")
        _nonneg_int(self.away_score, "AWAY_SCORE")
        if not self.home_team or not self.away_team:
            raise LiveStateError("TEAM_IDENTITY_INCOMPLETE")

    def age_seconds(self, now: datetime) -> float:
        now = _aware(now, "now")
        return (now - self.observed_at).total_seconds()

    def is_fresh(self, now: datetime,
                 threshold: int = LIVE_STATE_STALENESS_THRESHOLD_SECONDS) -> bool:
        return self.staleness_reason(now, threshold) is None

    def staleness_reason(self, now: datetime,
                         threshold: int = LIVE_STATE_STALENESS_THRESHOLD_SECONDS
                         ) -> str | None:
        """Hard staleness fail-closed check.

        Both our retrieval time AND the provider's own timestamp must be
        within the threshold: a provider serving a cached/old snapshot is
        stale even if we just fetched it. observed_at is the card request
        time (the poller is clocked to it); source_as_of is the
        independent provider signal.
        """
        now = _aware(now, "now")
        obs_age = (now - self.observed_at).total_seconds()
        src_age = (now - self.source_as_of).total_seconds()
        if obs_age < 0 or src_age < 0:
            return "FUTURE_TIMESTAMP"
        if obs_age > threshold:
            return (f"STALE_LIVE_DATA:retrieved_{obs_age:.0f}s_ago_exceeds_"
                    f"{threshold}s")
        if src_age > threshold:
            return (f"STALE_LIVE_DATA:provider_timestamp_{src_age:.0f}s_old_"
                    f"exceeds_{threshold}s")
        return None

    def is_live(self) -> bool:
        return self.status == "LIVE"


def _mlb_status(abstract: str) -> str:
    text = str(abstract or "")
    if text in MLB_LIVE_STATUSES:
        return "LIVE"
    if text in MLB_FINAL_STATUSES:
        return "FINAL"
    if text in {"Preview", "Scheduled"}:
        return "PREGAME"
    if "Suspended" in text or "Postponed" in text or "Delayed" in text:
        return "SUSPENDED"
    return "UNKNOWN"


def _bases_from_play(play: Mapping[str, Any]) -> tuple[bool, bool, bool] | None:
    """Best-effort base occupancy from one play's runner movements.

    Informational only (provenance recorded); never enters pricing.
    """
    try:
        runners = play.get("runners") or []
        occupied = [False, False, False]
        seen = False
        for runner in runners:
            movement = (runner or {}).get("movement") or {}
            end = str(movement.get("end") or "")
            if movement.get("isOut"):
                continue
            if end in ("1B", "2B", "3B"):
                occupied[{"1B": 0, "2B": 1, "3B": 2}[end]] = True
                seen = True
        if not seen:
            return None
        return (occupied[0], occupied[1], occupied[2])
    except (AttributeError, TypeError, ValueError):
        return None


def parse_mlb_live_feed(feed: Mapping[str, Any], *, retrieved_at: datetime,
                        game_pk: int | None = None) -> MLBGameState:
    """Parse an MLB StatsAPI live feed into an MLBGameState. Fail closed."""
    retrieved_at = _aware(retrieved_at, "retrieved_at")
    if not isinstance(feed, Mapping):
        raise LiveStateError("FEED_NOT_MAPPING")
    game_data = feed.get("gameData") or {}
    live_data = feed.get("liveData") or {}
    if not game_data and not live_data:
        raise LiveStateError("FEED_EMPTY")

    pk = game_pk if game_pk is not None else (game_data.get("game") or {}).get("pk")
    try:
        pk = int(pk)
    except (TypeError, ValueError) as exc:
        raise LiveStateError("GAME_PK_INVALID") from exc
    if pk <= 0:
        raise LiveStateError("GAME_PK_INVALID")

    status = _mlb_status((game_data.get("status") or {}).get("abstractGameState"))
    teams = game_data.get("teams") or {}
    home_team = str(((teams.get("home") or {}).get("name")) or "")
    away_team = str(((teams.get("away") or {}).get("name")) or "")
    kickoff = _parse_dt((game_data.get("datetime") or {}).get("dateTime"))
    probable = game_data.get("probablePitchers") or {}

    def _probable(side: str) -> Mapping[str, Any] | None:
        entry = probable.get(side)
        if not isinstance(entry, Mapping):
            return None
        pid = entry.get("id")
        name = str(entry.get("fullName") or "")
        if not isinstance(pid, int) or not name:
            return None
        return {"id": pid, "fullName": name}

    linescore = live_data.get("linescore") or {}
    inning = linescore.get("currentInning")
    half_raw = str(linescore.get("inningHalf") or "").lower()
    half = half_raw if half_raw in ("top", "bottom") else None
    team_runs = linescore.get("teams") or {}
    try:
        home_score = int((team_runs.get("home") or {}).get("runs") or 0)
        away_score = int((team_runs.get("away") or {}).get("runs") or 0)
    except (TypeError, ValueError) as exc:
        raise LiveStateError("SCORE_NOT_INT") from exc

    plays = live_data.get("plays") or {}
    current = plays.get("currentPlay") or {}
    count = current.get("count") or {}
    about = current.get("about") or {}
    matchup = current.get("matchup") or {}
    if inning is None:
        inning = about.get("inning")
    if half is None:
        half_about = str(about.get("halfInning") or "").lower()
        half = half_about if half_about in ("top", "bottom") else None

    def _opt_int(*names: str) -> int | None:
        for name in names:
            value = count.get(name)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
        return None

    outs = _opt_int("outs")
    balls = _opt_int("balls")
    strikes = _opt_int("strikes")

    batter = matchup.get("batter") or {}
    pitcher = matchup.get("pitcher") or {}

    bases, bases_provenance = None, None
    all_plays = plays.get("allPlays") or []
    if all_plays:
        last = all_plays[-1]
        if isinstance(last, Mapping):
            bases = _bases_from_play(last)
            if bases is not None:
                bases_provenance = "LAST_PLAY_RUNNER_MOVEMENTS_DISPLAY_ONLY"

    # Provider's own timestamp when present; otherwise our retrieval time.
    source_as_of = retrieved_at
    meta = feed.get("metaData") or {}
    for key in ("timeStamp", "timestamp"):
        parsed = _parse_dt(meta.get(key))
        if parsed is not None:
            source_as_of = parsed
            break

    state = MLBGameState(
        game_pk=pk,
        observed_at=retrieved_at,
        source_as_of=source_as_of,
        status=status,
        inning=int(inning) if inning is not None else None,
        half=half,
        outs=outs,
        balls=balls,
        strikes=strikes,
        bases=bases,
        bases_provenance=bases_provenance,
        batter_id=batter.get("id") if isinstance(batter.get("id"), int) else None,
        batter_name=str(batter.get("fullName") or "") or None,
        pitcher_id=pitcher.get("id") if isinstance(pitcher.get("id"), int) else None,
        pitcher_name=str(pitcher.get("fullName") or "") or None,
        home_score=home_score,
        away_score=away_score,
        home_team=home_team,
        away_team=away_team,
        kickoff=kickoff,
        probable_pitcher_away=_probable("away"),
        probable_pitcher_home=_probable("home"),
    )
    state.validate()
    return state


# ---------------------------------------------------------------------------
# NFL / CFB state
# ---------------------------------------------------------------------------

FOOTBALL_REGULATION_SECONDS = 3600
FOOTBALL_QUARTER_SECONDS = 900


@dataclass(frozen=True)
class FootballGameState:
    sport: str  # NFL | CFB
    event_id: str
    observed_at: datetime
    source_as_of: datetime
    status: str  # LIVE / FINAL / PREGAME / SUSPENDED / UNKNOWN
    quarter: int | None
    # Seconds remaining in the current quarter; None when not parseable.
    clock_seconds: int | None
    clock_display: str | None
    down: int | None
    distance: int | None
    yard_line_raw: Any | None
    # Yards from the possessing team's own goal line (0-100); None unless
    # confidently parseable. Display-only: NOT_WIRED for pricing.
    yard_line_100: int | None
    # "HOME" | "AWAY" | None.
    possession: str | None
    timeouts_home: int | None
    timeouts_away: int | None
    home_score: int
    away_score: int
    home_team: str
    away_team: str
    kickoff: datetime | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _aware(self.observed_at, "observed_at")
        _aware(self.source_as_of, "source_as_of")
        if self.sport not in ("NFL", "CFB"):
            raise LiveStateError("SPORT_INVALID")
        if not self.event_id:
            raise LiveStateError("EVENT_ID_REQUIRED")
        if self.quarter is not None:
            _nonneg_int(self.quarter, "QUARTER")
        if self.clock_seconds is not None and self.clock_seconds < 0:
            raise LiveStateError("CLOCK_NEGATIVE")
        if self.possession not in (None, "HOME", "AWAY"):
            raise LiveStateError("POSSESSION_INVALID")
        for name in ("down", "distance", "timeouts_home", "timeouts_away"):
            value = getattr(self, name)
            if value is not None:
                _nonneg_int(value, name.upper())
        _nonneg_int(self.home_score, "HOME_SCORE")
        _nonneg_int(self.away_score, "AWAY_SCORE")
        if not self.home_team or not self.away_team:
            raise LiveStateError("TEAM_IDENTITY_INCOMPLETE")

    def age_seconds(self, now: datetime) -> float:
        now = _aware(now, "now")
        return (now - self.observed_at).total_seconds()

    def is_fresh(self, now: datetime,
                 threshold: int = LIVE_STATE_STALENESS_THRESHOLD_SECONDS) -> bool:
        return self.staleness_reason(now, threshold) is None

    def staleness_reason(self, now: datetime,
                         threshold: int = LIVE_STATE_STALENESS_THRESHOLD_SECONDS
                         ) -> str | None:
        """Hard staleness fail-closed check (see MLBGameState)."""
        now = _aware(now, "now")
        obs_age = (now - self.observed_at).total_seconds()
        src_age = (now - self.source_as_of).total_seconds()
        if obs_age < 0 or src_age < 0:
            return "FUTURE_TIMESTAMP"
        if obs_age > threshold:
            return (f"STALE_LIVE_DATA:retrieved_{obs_age:.0f}s_ago_exceeds_"
                    f"{threshold}s")
        if src_age > threshold:
            return (f"STALE_LIVE_DATA:provider_timestamp_{src_age:.0f}s_old_"
                    f"exceeds_{threshold}s")
        return None

    def is_live(self) -> bool:
        return self.status == "LIVE"

    def is_overtime(self) -> bool:
        return self.quarter is not None and self.quarter > 4


def _football_status(status_type: Mapping[str, Any]) -> str:
    name = str(status_type.get("name") or "").upper()
    state = str(status_type.get("state") or "").lower()
    if any(token in name for token in ("CANCELED", "CANCELLED", "POSTPONED", "SUSPENDED", "DELAYED")):
        return "SUSPENDED"
    if bool(status_type.get("completed")) or state == "post":
        return "FINAL"
    if state == "in":
        return "LIVE"
    return "PREGAME"


def _normalize_yard_line(raw: Any, possession_text: str | None) -> int | None:
    """Best effort 0-100 normalization; None unless confident. Display-only."""
    if raw is None:
        return None
    text = str(raw).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        value = int(digits)
    except ValueError:
        return None
    if not 0 <= value <= 100:
        return None
    # Without a side marker we cannot tell whose goal line the number is
    # measured from, so refuse to normalize rather than guess.
    if possession_text:
        upper = possession_text.upper()
        if "OWN" in upper:
            return 100 - value if value <= 50 else value
    return None


def parse_espn_football_event(event: Mapping[str, Any], *, sport: str,
                              retrieved_at: datetime) -> FootballGameState:
    """Parse one ESPN scoreboard event into a FootballGameState. Fail closed."""
    retrieved_at = _aware(retrieved_at, "retrieved_at")
    if sport not in ("NFL", "CFB"):
        raise LiveStateError("SPORT_INVALID")
    if not isinstance(event, Mapping):
        raise LiveStateError("EVENT_NOT_MAPPING")
    competitions = event.get("competitions") or []
    competition = competitions[0] if competitions else {}
    status = competition.get("status") or event.get("status") or {}
    status_type = status.get("type") or {}
    game_status = _football_status(status_type)

    competitors = competition.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if home is None or away is None:
        raise LiveStateError("COMPETITORS_INCOMPLETE")

    def _team_name(comp: Mapping[str, Any]) -> str:
        team = comp.get("team") or {}
        return str(team.get("displayName") or team.get("shortDisplayName")
                   or team.get("abbreviation") or "")

    def _score(comp: Mapping[str, Any]) -> int:
        try:
            return int(float(comp.get("score") or 0))
        except (TypeError, ValueError) as exc:
            raise LiveStateError("SCORE_NOT_INT") from exc

    situation = competition.get("situation") or {}

    def _situation(*names: str) -> Any | None:
        for name in names:
            if situation.get(name) is not None:
                return situation[name]
        return None

    def _opt_int(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            out = int(value)
        except (TypeError, ValueError):
            return None
        return out if out >= 0 else None

    possession_raw = _situation("possession")
    possession = None
    if possession_raw is not None:
        home_id = str((home.get("team") or {}).get("id") or "")
        away_id = str((away.get("team") or {}).get("id") or "")
        if str(possession_raw) == home_id:
            possession = "HOME"
        elif str(possession_raw) == away_id:
            possession = "AWAY"

    clock_display = status.get("displayClock")
    clock_seconds = _clock_to_seconds(clock_display)
    possession_text = _situation("possessionText", "shortPossessionText")

    source_as_of = _parse_dt(status_type.get("lastUpdated")) or retrieved_at
    kickoff = _parse_dt(event.get("date"))

    state = FootballGameState(
        sport=sport,
        event_id=str(event.get("id") or ""),
        observed_at=retrieved_at,
        source_as_of=source_as_of,
        status=game_status,
        quarter=_opt_int(status.get("period")),
        clock_seconds=clock_seconds,
        clock_display=str(clock_display) if clock_display else None,
        down=_opt_int(_situation("down")),
        distance=_opt_int(_situation("distance")),
        yard_line_raw=_situation("yardLine", "yardline", "yardLine100"),
        yard_line_100=_normalize_yard_line(
            _situation("yardLine", "yardline", "yardLine100"),
            str(possession_text) if possession_text else None),
        possession=possession,
        timeouts_home=_opt_int(_situation("homeTimeouts", "timeoutsHome")),
        timeouts_away=_opt_int(_situation("awayTimeouts", "timeoutsAway")),
        home_score=_score(home),
        away_score=_score(away),
        home_team=_team_name(home),
        away_team=_team_name(away),
        kickoff=kickoff,
    )
    state.validate()
    return state
