#!/usr/bin/env python3
"""Pre-pricing factor-ingestion stage for the phone RUN IT runner.

Runs BEFORE any market is priced for a game. Pulls, from FREE PUBLIC
endpoints only (zero API keys, zero paid services, zero infra for Isaac):

  1. verified injuries/inactives + QB/participation state -- ESPN, via the
     CANONICAL free_models.injury_rows / injury_points fetch path (no second
     divergent fetch);
  2. weather for outdoor venues -- ARCHIVED evidence first
     (SPORTSEDGE_WEATHER_EVIDENCE_V1, staleness fail-closed), else the
     EXISTING declared-threshold provider.weather path (free Open-Meteo,
     no key), wired into context["weather_total_adj"]. Keyed weather APIs
     are NEVER called directly.
  3. verified MLB probable pitchers -- MLB StatsAPI schedule hydrate,
     declared bounded starter adjustments to team means;
  4. rest/travel from ESPN schedules -- verified rest days plus a declared
     bounded rest-differential adjustment; travel distance stays NOT_WIRED.

OWNER RULING (Oct 13, 2026): items 3 and 4 and the engine's recent-form
term are DISABLED_PENDING_INCREMENTAL_VALUE -- collected and audited,
but their pricing contribution is zero until each demonstrates
incremental value in the harness. Only the retained baseline
(team-strength ratings + static home advantage) and other verified,
non-disabled adjustments shift a mean. Every factor is audited per game as
USED (with source) or MISSING (with explicit reason) against the factor
taxonomy in model_factors_reference.md (NHL/Soccer omitted -- out of scope;
motivation spots / news speed / officiating tendencies stay NOT_WIRED per
standing rule; market-odds-as-features is a REJECTED method, never an audit
item).

Critical factors -- QB identity for NFL/CFB, probable pitcher for MLB --
that are missing or unverifiable DOWNGRADE the game's markets to blocked
with an explicit reason code. Never silently priced.

QB identity, CFB only (owner ruling, Oct 13 2026, issue #2154): for a
team the ESPN injury feed does not cover (TEAM_NOT_IN_INJURY_FEED), a
QB_IDENTITY_EVIDENCE Form 2 bundle (DEPTH_ROSTER_COMPOSITE -- ESPN
roster membership + receipted OurLads depth order, resolved to exactly
one athlete ID) may satisfy the IDENTITY limb as a research-stage
evidence path. It is NOT proof of availability or a clean injury
report: availability stays explicitly AVAILABILITY_UNVERIFIED_
NO_TEAM_INJURY_REPORT and injury points are exactly 0.0. See
sportsedge/prepricing/qb_identity_evidence.py.

Research only. No betting authority. All numeric adjustments are DECLARED
heuristics, NOT calibrated edges; each must earn production status through
the backtest harness (chronological out-of-sample vs existing model).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlencode

from artifacts.free_models import (
    IL_COLLEGE_ESPN_IDS, PublicContext, bounded, declared_weather_total_adj,
    dt, numeric,
)
from sportsedge.prepricing import qb_identity_evidence as _qb_evidence

# Free factors module (harness-gated): provides park factors, rest/travel,
# weather thresholds, key numbers. Marked PENDING_VALIDATION until the
# backtest harness confirms predictive improvement.
try:
    from sportsedge import free_factors as _free_factors
    _FREE_FACTORS_AVAILABLE = True
except ImportError:
    _free_factors = None
    _FREE_FACTORS_AVAILABLE = False

# A module import establishes only a potentially usable source path, NEVER
# proof of a game-specific, point-in-time sample or predictive validation.
try:
    from sportsedge import mlb_bullpen_workload_source as _bullpen_source
    _BULLPEN_AVAILABLE = True
except ImportError:
    _bullpen_source = None
    _BULLPEN_AVAILABLE = False
try:
    from sportsedge import mlb_savant_features as _savant_source
    _SAVANT_AVAILABLE = True
except ImportError:
    _savant_source = None
    _SAVANT_AVAILABLE = False

STATSAPI = "https://statsapi.mlb.com/api/v1"

# Sourcing rule (Isaac): keyed APIs (odds, weather) run Actions-side ONLY via
# ${{ secrets.* }} and arrive as archived evidence on the data branch. This
# stage NEVER calls a keyed API directly. It reads ARCHIVED evidence (with
# staleness fail-closed: a stale archive fails exactly like missing data,
# never silently used) plus free public endpoints live (ESPN, MLB StatsAPI,
# Open-Meteo -- no keys). The phone runner stays on free endpoints +
# archived data only.
WEATHER_EVIDENCE_CONTRACT = "SPORTSEDGE_WEATHER_EVIDENCE_V1"
WEATHER_ARCHIVE_MAX_AGE_HOURS = 36
WEATHER_KICKOFF_BIND_WINDOW_HOURS = 6


class WeatherEvidenceError(ValueError):
    """Archived weather evidence failed admission; fail closed."""


def admit_weather_evidence(evidence, *, sport, kickoff, now):
    """Validate archived weather evidence; return (total_adj, detail).

    Raises WeatherEvidenceError on ANY defect: wrong contract, kickoff
    mismatch, stale/future/post-kickoff retrieval, non-numeric or
    out-of-range forecast fields. A rejected archive is never silently
    used or silently replaced -- the caller audits it MISSING.
    """
    if not isinstance(evidence, dict):
        raise WeatherEvidenceError("EVIDENCE_NOT_OBJECT")
    if evidence.get("contract") != WEATHER_EVIDENCE_CONTRACT:
        raise WeatherEvidenceError("CONTRACT_MISMATCH")
    ev_kickoff = dt(evidence.get("kickoff_utc"))
    if ev_kickoff is None:
        raise WeatherEvidenceError("KICKOFF_INVALID")
    if abs((ev_kickoff - kickoff).total_seconds()) > WEATHER_KICKOFF_BIND_WINDOW_HOURS * 3600:
        raise WeatherEvidenceError("KICKOFF_BINDING_MISMATCH")
    retrieved = dt(evidence.get("retrieved_at_utc"))
    if retrieved is None:
        raise WeatherEvidenceError("RETRIEVED_AT_INVALID")
    if retrieved > now:
        raise WeatherEvidenceError("RETRIEVED_IN_FUTURE")
    if retrieved > kickoff:
        raise WeatherEvidenceError("RETRIEVED_AFTER_KICKOFF")
    if (kickoff - retrieved).total_seconds() > WEATHER_ARCHIVE_MAX_AGE_HOURS * 3600:
        raise WeatherEvidenceError("ARCHIVE_STALE")
    venue = evidence.get("venue") or {}
    if not isinstance(venue, dict):
        raise WeatherEvidenceError("VENUE_NOT_OBJECT")
    if venue.get("indoor") is True:
        return 0.0, "INDOOR_VERIFIED_ARCHIVE"
    forecast = evidence.get("forecast") or {}
    if not isinstance(forecast, dict):
        raise WeatherEvidenceError("FORECAST_NOT_OBJECT")
    try:
        wind = numeric(forecast.get("wind_mph"), "wind_mph")
        precip = numeric(forecast.get("precip_probability"), "precip_probability")
    except (TypeError, ValueError) as exc:
        raise WeatherEvidenceError("FORECAST_FIELDS_INVALID") from exc
    if not 0 <= wind <= 250 or not 0 <= precip <= 100:
        raise WeatherEvidenceError("FORECAST_FIELDS_OUT_OF_RANGE")
    adj = declared_weather_total_adj(wind, precip, sport)
    return adj, (f"ARCHIVED_EVIDENCE_WIND_{wind}MPH_PRECIP_{precip}PCT;"
                 f"RETRIEVED_{retrieved.isoformat()};TOTAL_ADJ_{adj}_DECLARED")

# ---------------------------------------------------------------------------
# Declared constants. Every one is an unfitted prior, NOT a learned edge.
# ---------------------------------------------------------------------------
DECL_LEAGUE_ERA = 4.30          # reference ERA for starter suppression math
DECL_PITCHER_ADJ_CAP = 1.25     # max |runs| shift per probable-starter edge
DECL_MIN_PITCHER_GS = 5         # minimum starts for a usable pitcher line
DECL_MIN_PITCHER_IP = 25.0      # ... or minimum innings pitched
DECL_MAX_STARTER_IP_PER_GS = 8.0
DECL_MIN_STARTER_IP_PER_GS = 3.0
DECL_REST_PTS_PER_DAY = {"NFL": 0.12, "CFB": 0.12, "MLB": 0.05}
DECL_REST_ADJ_CAP = {"NFL": 0.6, "CFB": 0.6, "MLB": 0.25}

# Block reason codes emitted when a critical factor cannot be verified.
BLOCK_FIXTURE_UNVERIFIED = "BLOCKED_PREPRICING_FIXTURE_UNVERIFIED"
BLOCK_TEAMS_UNRESOLVED = "BLOCKED_PREPRICING_TEAMS_UNRESOLVED"
BLOCK_QB_IDENTITY_UNVERIFIED = "BLOCKED_PREPRICING_QB_IDENTITY_UNVERIFIED"
BLOCK_IL_COLLEGE_EXCLUDED = "BLOCKED_PREPRICING_IL_COLLEGE_EXCLUDED"
BLOCK_PITCHER_UNCONFIRMED = "BLOCKED_PREPRICING_PITCHER_UNCONFIRMED"
BLOCK_NFL_TEAM_HISTORY = "BLOCKED_PREPRICING_NFL_TEAM_HISTORY_UNVERIFIED"

PRE_PITCH_STATES = {"Scheduled", "Pre-Game", "Warmup"}

# Factor taxonomy (model_factors_reference.md; NHL/Soccer omitted).
UNIVERSAL_FACTORS = (
    "team_strength_ratings",
    "recent_form",
    "home_advantage",
    "rest_schedule",
    "travel",
    "pace_tempo",
    "lineups_usage",
    "advanced_metrics",
    "situational",
    "weather_venue",
)
SPORT_FACTORS = {
    "NFL": ("qb_specific", "efficiency_epa", "key_numbers", "turnover_special_teams"),
    "CFB": ("qb_specific", "talent_portal", "key_numbers"),
    "NBA": ("four_factors", "rest_back_to_back", "rotations_matchups"),
    "MLB": ("starting_pitcher", "bullpen", "park_factors", "umpire",
            "opponent_adjusted_offense"),
}

USED, MISSING, NOT_WIRED, NOT_APPLICABLE, PENDING_VALIDATION = (
    "USED", "MISSING", "NOT_WIRED", "NOT_APPLICABLE", "PENDING_VALIDATION")

# Owner ruling (Oct 13, 2026): rest_schedule, the ERA-based
# starting-pitcher adjustment, and recent_form are DISABLED in the
# canonical pricing path until each demonstrates incremental value in
# the harness against the retained baseline (team-strength ratings +
# static home advantage) and the market. Their values are still
# collected and reported here for research; the adjustments handed to
# pricing are exactly zero and the factor status is this label.
DISABLED_PENDING_INCREMENTAL_VALUE = "DISABLED_PENDING_INCREMENTAL_VALUE"


@dataclass
class FactorRecord:
    factor: str
    status: str  # USED | MISSING | NOT_WIRED | NOT_APPLICABLE | PENDING_VALIDATION
    source: str
    reason: str
    adjustments: dict = field(default_factory=dict)

    def as_dict(self):
        return {"factor": self.factor, "status": self.status,
                "source": self.source, "reason": self.reason,
                "adjustments": dict(self.adjustments)}


def _factor(name, status, source, reason, adjustments=None):
    return FactorRecord(name, status, source, reason,
                        dict(adjustments or {})).as_dict()


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------
def _resolve_teams(row):
    away = str(row.get("away") or "").strip()
    home = str(row.get("home") or "").strip()
    if (not away or not home or away == home) and " @ " in str(row.get("game") or ""):
        a, h = (s.strip() for s in str(row.get("game")).split(" @ ", 1))
        if a and h and a != h:
            away, home = a, h
    if not away or not home or away == home:
        return None, None
    return away, home


def _parse_ip(value):
    """StatsAPI inningsPitched like '152.1' (1 == one out) -> float innings."""
    try:
        whole, _, outs = str(value).strip().partition(".")
        return float(whole) + (float(outs) / 3.0 if outs else 0.0)
    except (ValueError, TypeError):
        return None


def _out_doubtful(rows):
    out, doubtful = [], []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        raw = r.get("status") or ""
        if isinstance(raw, dict):
            raw = raw.get("name") or raw.get("description") or ""
        status = str(raw).strip().lower()
        if status not in {"out", "doubtful"}:
            continue
        athlete = r.get("athlete") or {}
        if not isinstance(athlete, dict):
            continue
        name = str(athlete.get("displayName") or athlete.get("fullName") or "")
        pos = athlete.get("position") or {}
        pos = pos.get("abbreviation") if isinstance(pos, dict) else pos
        entry = {"name": name, "position": str(pos or "").upper(),
                 "status": status}
        (out if status == "out" else doubtful).append(entry)
    return out, doubtful


# ---------------------------------------------------------------------------
# MLB probable pitchers (free MLB StatsAPI)
# ---------------------------------------------------------------------------
def fetch_probable_pitchers(fetch, game_date):
    """Return raw StatsAPI schedule games for one date (hydrate probablePitcher)."""
    url = (STATSAPI + "/schedule?" + urlencode(
        {"sportId": 1, "date": game_date.strftime("%Y-%m-%d"),
         "hydrate": "team,probablePitcher"}))
    data = fetch(url) or {}
    games = []
    for day in data.get("dates") or []:
        if not isinstance(day, dict):
            continue
        for game in day.get("games") or []:
            if isinstance(game, dict):
                games.append(game)
    return games


def match_scheduled_game(games, home, away, kickoff=None):
    """Require unique two-team identity and, when known, exact pregame time.

    ESPN and StatsAPI sometimes use different club abbreviations; compare
    independently sourced full names as well. Date alone never selects a
    doubleheader or the adjacent UTC-date schedule.
    """
    key = PublicContext.key
    def same(official, wanted):
        if not isinstance(official, dict):
            return False
        abbreviation = key(official.get("abbreviation") or "")
        name = key(wanted.get("name") or "")
        return ((abbreviation and abbreviation == key(wanted.get("abbr") or "")) or
                (name and key(official.get("name") or "") == name))
    matches = {}
    for game in games:
        if not isinstance(game, dict) or not game.get("gamePk"):
            continue
        teams = game.get("teams") or {}
        gh = ((teams.get("home") or {}).get("team") or {})
        ga = ((teams.get("away") or {}).get("team") or {})
        if not (same(gh, home) and same(ga, away)):
            continue
        if kickoff is not None:
            actual = dt(game.get("gameDate"))
            if actual is None or abs((actual - kickoff).total_seconds()) > 900:
                continue
        matches[str(game["gamePk"])] = game
    return next(iter(matches.values())) if len(matches) == 1 else None


def fetch_pitcher_season_line(fetch, pitcher_id, season):
    """Verified season pitching line -> (era, ip, gs) or None when unusable."""
    url = (f"{STATSAPI}/people/{pitcher_id}/stats?" + urlencode(
        {"stats": "season", "season": season, "group": "pitching"}))
    data = fetch(url) or {}
    stats = data.get("stats") or []
    splits = (stats[0].get("splits") or []) if stats and isinstance(stats[0], dict) else []
    stat = splits[0].get("stat") if splits and isinstance(splits[0], dict) else {}
    if not isinstance(stat, dict):
        return None
    try:
        era = float(str(stat.get("era")).strip())
    except (ValueError, TypeError, AttributeError):
        return None
    ip = _parse_ip(stat.get("inningsPitched"))
    try:
        gs = int(stat.get("gamesStarted") or 0)
    except (ValueError, TypeError):
        gs = 0
    if ip is None or not (0 < era < 15):
        return None
    if gs < DECL_MIN_PITCHER_GS and ip < DECL_MIN_PITCHER_IP:
        return None  # sample too thin: fail closed, never a partial credit
    return era, ip, gs


def starter_suppression_adjustment(era, ip, gs):
    """Declared bounded runs-suppressed-vs-average for a verified starter.

    Positive means the starter suppresses runs; the returned offense
    adjustment for the OPPOSING team is its negation (good starter ->
    opponent scores fewer).
    """
    ip_per_gs = bounded(ip / max(gs, 1), DECL_MIN_STARTER_IP_PER_GS,
                        DECL_MAX_STARTER_IP_PER_GS)
    suppression = (DECL_LEAGUE_ERA - era) * (ip_per_gs / 9.0)
    return round(bounded(-suppression, -DECL_PITCHER_ADJ_CAP,
                         DECL_PITCHER_ADJ_CAP), 3)


def mlb_pitcher_adjustments(fetch, *, game_date, home, away, season,
                            stats_fetch=None, allow_completed=False, kickoff=None):
    """Verified probable-pitcher adjustments for one MLB game.

    Returns (adjustments, factors, blocked, block_detail). ``home``/``away``
    are dicts with at least ``abbr`` (StatsAPI abbreviation) and ``name``.
    ``stats_fetch`` overrides the season-line source (harness adapter).
    ``allow_completed`` is for historical validation only: completed games
    keep their probable-pitcher field and the same declared math applies;
    the live path leaves it False (the engine blocks started games itself).
    """
    stats_fetch = stats_fetch or fetch_pitcher_season_line
    factors = []
    # A 7 PM Central game may begin at 00:00 UTC on the NEXT date.
    # Fetch the neighboring schedule dates and bind by the verified start,
    # not by an inferred UTC calendar day. Deduplicate repeated gamePk.
    from datetime import timedelta
    games_by_pk = {}
    offsets = (-1, 0, 1) if kickoff is not None else (0,)
    for offset in offsets:
        # Missing adjacent-date payloads are unavailable, not fabricated
        # empty games. The canonical provider.fetch records source failures.
        try:
            candidates = fetch_probable_pitchers(fetch, game_date + timedelta(days=offset))
        except (OSError, TimeoutError, ValueError, TypeError):
            continue
        for candidate in candidates:
            if candidate.get("gamePk"):
                games_by_pk[str(candidate["gamePk"])] = candidate
    game = match_scheduled_game(list(games_by_pk.values()), home, away, kickoff)
    if game is None:
        reason = "NO_UNIQUE_STATSAPI_SCHEDULE_MATCH_FOR_TEAMS_ON_DATE"
        factors.append(_factor("starting_pitcher", MISSING,
                               "MLB_STATSAPI_SCHEDULE_HYDRATE_PROBABLEPITCHER", reason))
        return {}, factors, True, reason
    state = str((game.get("status") or {}).get("detailedState") or "")
    historical = False
    if state not in PRE_PITCH_STATES:
        if state == "Final" and allow_completed:
            historical = True
        else:
            reason = f"GAME_NOT_PREGAME:{state or 'UNKNOWN_STATE'}"
            factors.append(_factor("starting_pitcher", MISSING,
                                   "MLB_STATSAPI_SCHEDULE_HYDRATE_PROBABLEPITCHER", reason))
            # Engine blocks started games itself; the stage does not double-block.
            return {}, factors, False, reason
    teams = game.get("teams") or {}
    probables = {}
    missing_sides = []
    for side, label in (("home", home), ("away", away)):
        entry = (teams.get(side) or {}).get("probablePitcher") or {}
        pid, name = entry.get("id"), entry.get("fullName")
        if pid is None or not name:
            missing_sides.append(label.get("name") or side)
        else:
            probables[side] = {"id": pid, "name": str(name)}
    if missing_sides:
        reason = "PROBABLE_PITCHER_UNCONFIRMED:" + ",".join(missing_sides)
        factors.append(_factor("starting_pitcher", MISSING,
                               "MLB_STATSAPI_SCHEDULE_HYDRATE_PROBABLEPITCHER", reason))
        return {}, factors, True, reason
    adjustments, problems = {}, []
    # home_pitcher_adj shifts HOME offense: it encodes the AWAY starter's
    # suppression (and vice versa). Documented semantics; do not flip.
    for offense_side, pitcher_side, ctx_key in (
            ("home", "away", "home_pitcher_adj"),
            ("away", "home", "away_pitcher_adj")):
        info = probables[pitcher_side]
        line = stats_fetch(fetch, info["id"], season)
        if line is None:
            problems.append(f"{pitcher_side.upper()}_SP_{info['name']}_LINE_UNUSABLE")
            continue
        era, ip, gs = line
        adj = starter_suppression_adjustment(era, ip, gs)
        adjustments[ctx_key] = adj
        factors.append(_factor(
            "starting_pitcher", USED,
            f"MLB_STATSAPI_PEOPLE_{info['id']}_SEASON_PITCHING",
            f"VS_{info['name']}_ERA_{era}_IP_{round(ip,1)}_GS_{gs};"
            f"DECLARED_HEURISTIC_NOT_CALIBRATED;BULLPEN_WORKLOAD_NOT_WIRED"
            + (";COMPLETED_GAME_HISTORICAL_VALIDATION" if historical else ""),
            {ctx_key: adj}))
    if problems:
        reason = "PITCHER_LINE_UNUSABLE:" + ",".join(problems)
        # Partial pitcher info must not price a half-adjusted game.
        return {}, factors, True, reason
    return adjustments, factors, False, ""


# ---------------------------------------------------------------------------
# Per-game stage
# ---------------------------------------------------------------------------
def _consult_qb_form2(qb_form2_bundles, provider, sport, team, kickoff, now,
                      receipts, *, event_id=None, home_team_id=None,
                      away_team_id=None):
    """QB_IDENTITY_EVIDENCE Form 2 consult (owner ruling, issue #2154).

    Consulted ONLY for a CFB team whose injury-feed status is
    TEAM_NOT_IN_INJURY_FEED. Returns the evaluation result dict, or
    None when no bundle was supplied for this team (Form 2 not in
    play -- the gate then behaves exactly as it did before Form 2).
    Every consultation appends an evidence receipt, pass or fail.
    Bundles arrive ONLY through the stage_games parameter (a trusted
    loader / capture step), never from an input row.

    The staged fixture's identity (ESPN event ID + both team IDs) is
    passed through for the evaluator's exact-binding check (PR #2157
    owner-review correction 1): a bundle for this team in another
    game, or against another opponent, is not evidence here.
    """
    if not qb_form2_bundles:
        return None
    bundle = qb_form2_bundles.get(str(team.get("id")))
    if bundle is None:
        return None
    completed = provider.schedule(sport, team, kickoff)
    previous_kickoff = completed[0][0] if completed else None
    result = _qb_evidence.evaluate_form2_bundle(
        bundle, team_id=str(team.get("id")), kickoff=kickoff,
        previous_game_kickoff=previous_kickoff, now=now,
        event_id=event_id, home_team_id=home_team_id,
        away_team_id=away_team_id)
    receipt = {"source": "QB_IDENTITY_EVIDENCE_FORM2",
               "status": result["status"], "detail": result["detail"]}
    if result.get("receipt"):
        receipt.update(result["receipt"])
    receipts.append(receipt)
    return result


def _rest_days(provider, sport, team, kickoff):
    sample = provider.schedule(sport, team, kickoff)
    if not sample:
        return None
    days = (kickoff - sample[0][0]).total_seconds() / 86400
    return round(days, 2) if days > 0 else None


def _stage_one_game(rows, *, now, getter, enforce_blocks=True,
                    qb_form2_bundles=None):
    row = rows[0]
    sport = str(row.get("sport") or "").upper()
    away_name, home_name = _resolve_teams(row)
    game_label = f"{away_name} @ {home_name}" if away_name else "UNKNOWN_GAME"
    adjustments, factors, receipts = {}, [], []
    blocked, block_reason, block_detail = False, "", ""
    # Structured Form 2 verdicts by side, retained for downstream
    # RESEARCH consumers (the card's CFB research-projection annex).
    # Purely additive metadata: no pricing, blocking or adjustment
    # behavior reads this mapping; the pre-pricing gate remains the
    # only consumer that can affect the priced record. A side appears
    # here only when a bundle was actually consulted for it.
    qb_form2_identities = {}

    def all_missing(reason):
        for name in UNIVERSAL_FACTORS + SPORT_FACTORS.get(sport, ()):
            factors.append(_factor(name, MISSING, "PREPRICING_STAGE", reason))

    if sport not in {"NFL", "CFB", "NBA", "MLB"} or not away_name:
        blocked = enforce_blocks
        block_reason = BLOCK_TEAMS_UNRESOLVED if enforce_blocks else ""
        block_detail = "SPORT_UNSUPPORTED_OR_TEAMS_UNRESOLVED"
        if not enforce_blocks:
            block_detail += ";MANUAL_MODE_NO_PUBLIC_FETCH"
        all_missing(block_detail)
        return {"game_key": f"{sport}:{game_label}", "game_label": game_label,
                "sport": sport, "kickoff_utc": None, "blocked": blocked,
                "block_reason": block_reason, "block_detail": block_detail,
                "adjustments": adjustments, "factors": factors,
                "receipts": receipts,
                "qb_form2_identities": qb_form2_identities}

    kickoff = dt(row.get("commence_time") or row.get("kickoff"))
    provider = PublicContext(now, getter=getter)
    fixture = provider.fixture(sport, away_name, home_name, kickoff)
    if fixture is None:
        blocked = enforce_blocks
        block_reason = BLOCK_FIXTURE_UNVERIFIED if enforce_blocks else ""
        block_detail = "UNIQUE_FUTURE_ESPN_FIXTURE_MISSING"
        if not enforce_blocks:
            block_detail += ";MANUAL_MODE_NO_PUBLIC_FETCH"
        all_missing(block_detail)
        receipts.extend(provider.receipts)
        return {"game_key": f"{sport}:{game_label}", "game_label": game_label,
                "sport": sport, "kickoff_utc": None, "blocked": blocked,
                "block_reason": block_reason, "block_detail": block_detail,
                "adjustments": adjustments, "factors": factors,
                "receipts": receipts,
                "qb_form2_identities": qb_form2_identities}
    kickoff, competition = fixture
    # The staged fixture's ESPN event ID (the scoreboard event the
    # provider bound both teams + start time to). Form 2 bundles must
    # name exactly this event (PR #2157 owner-review correction 1);
    # absent an ID the evaluator fails the binding closed.
    fixture_event_id = (str(competition.get("id"))
                        if competition.get("id") is not None else None)

    home_team = provider.identify(sport, home_name)
    away_team = provider.identify(sport, away_name)
    if home_team is None or away_team is None:
        blocked = enforce_blocks
        block_reason = BLOCK_TEAMS_UNRESOLVED if enforce_blocks else ""
        block_detail = "ESPN_TEAM_IDENTITY_UNMATCHED:" + ",".join(
            s for s, t in (("HOME", home_team), ("AWAY", away_team)) if t is None)
        if not enforce_blocks:
            block_detail += ";MANUAL_MODE_NO_PUBLIC_FETCH"
        all_missing(block_detail)
        receipts.extend(provider.receipts)
        return {"game_key": f"{sport}:{game_label}", "game_label": game_label,
                "sport": sport, "kickoff_utc": kickoff.isoformat(),
                "blocked": blocked, "block_reason": block_reason,
                "block_detail": block_detail, "adjustments": adjustments,
                "factors": factors, "receipts": receipts,
                "qb_form2_identities": qb_form2_identities}

    # -- Illinois college exclusion (owner rule): ID-keyed on the verified
    # directory binding resolved just above. Either competitor whose ESPN
    # id is in the frozen registry excludes the fixture, whatever name
    # form the intake row carried (the IL_COLLEGE_NAMES list in
    # free_models is form-dependent and missed Chicago State, id 2130, in
    # every attested form). Unresolved identity already failed closed
    # above (BLOCK_TEAMS_UNRESOLVED), so no Illinois team can reach
    # pricing through an unbound name.
    if sport == "CFB":
        il_hit = None
        for side, team in (("HOME", home_team), ("AWAY", away_team)):
            school = IL_COLLEGE_ESPN_IDS.get(str(team.get("id") or ""))
            if school is not None:
                il_hit = (side, school, str(team.get("id")))
                break
        if il_hit is not None:
            blocked = enforce_blocks
            block_reason = BLOCK_IL_COLLEGE_EXCLUDED if enforce_blocks else ""
            block_detail = (f"IL_COLLEGE_ESPN_ID_{il_hit[2]}:{il_hit[1]}"
                            f"({il_hit[0]})")
            if not enforce_blocks:
                block_detail += ";MANUAL_MODE_NO_PUBLIC_FETCH"
            all_missing(block_detail)
            receipts.extend(provider.receipts)
            return {"game_key": f"{sport}:{game_label}",
                    "game_label": game_label,
                    "sport": sport, "kickoff_utc": kickoff.isoformat(),
                    "blocked": blocked, "block_reason": block_reason,
                    "block_detail": block_detail,
                    "adjustments": adjustments, "factors": factors,
                    "receipts": receipts,
                    "qb_form2_identities": qb_form2_identities}

    # Game-level QB availability state for the priced record: stays
    # None unless a Form 2 consult satisfies a team's identity limb,
    # in which case availability is explicitly UNKNOWN (never clean)
    # and the constant below is carried onto the priced rows.
    availability_status = None

    # -- 1. injuries / QB-participation (canonical free_models path) -------
    if sport in {"NFL", "CFB", "NBA"}:
        for side, team, ctx_key in (("HOME", home_team, "home_injury_pts"),
                                    ("AWAY", away_team, "away_injury_pts")):
            rows_, status = provider.injury_rows(sport, team)
            pts, pts_status = provider.injury_points(sport, team)
            if status != "STRUCTURE_VERIFIED":
                # Both failure classes stay fail-closed; only the stated
                # reason differs. TEAM_NOT_IN_INJURY_FEED means the ESPN
                # feed parsed cleanly but carries no report for this team
                # (the common CFB case -- ESPN reports only teams with
                # current injury entries), so calling it a schema failure
                # would misstate the evidence.
                if status == "TEAM_NOT_IN_INJURY_FEED":
                    feed_reason = f"{side}_INJURY_FEED_NO_TEAM_REPORT:{status}"
                    detail = ("ESPN injury feed is well-formed but carries "
                              "no report for this team")
                else:
                    feed_reason = f"{side}_INJURY_FEED_UNUSABLE:{status}"
                    detail = "ESPN injury payload failed team-group binding"
                # QB_IDENTITY_EVIDENCE Form 2 (owner ruling, issue
                # #2154): for a CFB team the injury feed does not cover,
                # a DEPTH_ROSTER_COMPOSITE bundle may satisfy the
                # IDENTITY limb only. Availability stays explicitly
                # unknown (never a clean report) and injury points are
                # exactly 0.0 -- there is no report to extract from.
                # Any Form 2 failure falls through to the unchanged
                # fail-closed block below, with the failure status
                # recorded in the factor reason and block detail.
                form2 = None
                if sport == "CFB" and status == "TEAM_NOT_IN_INJURY_FEED":
                    form2 = _consult_qb_form2(
                        qb_form2_bundles, provider, sport, team, kickoff,
                        now, receipts, event_id=fixture_event_id,
                        home_team_id=str(home_team.get("id")),
                        away_team_id=str(away_team.get("id")))
                if form2 is not None:
                    # Retain the evaluator's verdict verbatim (identity
                    # limb only; availability label exactly as issued)
                    # for the research annex. Recording is not a second
                    # evaluation: this is the same result object the
                    # gate below consumes.
                    form2_receipt = form2.get("receipt") or {}
                    qb_form2_identities[side] = {
                        "team_id": str(team.get("id")),
                        "ok": bool(form2.get("ok")),
                        "status": form2.get("status"),
                        "detail": form2.get("detail"),
                        "resolved_athlete_id": form2.get("resolved_athlete_id"),
                        "resolved_athlete_name": form2.get("resolved_athlete_name"),
                        "availability_status": form2.get("availability_status"),
                        "injury_points": form2.get("injury_points"),
                        "event_id": form2_receipt.get("event_id"),
                        "opponent_espn_id": form2_receipt.get("opponent_espn_id"),
                    }
                if form2 is not None and form2["ok"]:
                    proceeds, disposition_status = _qb_evidence.form2_disposition()
                    if proceeds:
                        # The game prices on a QB whose AVAILABILITY is
                        # explicitly unknown. Recorded structurally on
                        # the stage result so the runner stamps it on
                        # the priced rows and the classification layer
                        # forces them research-only (issue #2158).
                        availability_status = _qb_evidence.AVAILABILITY_UNVERIFIED
                        adjustments[ctx_key] = 0.0
                        factors.append(_factor(
                            "qb_specific", USED,
                            "QB_IDENTITY_EVIDENCE_FORM2_DEPTH_ROSTER_COMPOSITE",
                            f"{side}_QB_IDENTITY:{_qb_evidence.STATUS_SATISFIED};"
                            f"QB1_ATHLETE_ID_{form2['resolved_athlete_id']};"
                            f"INJURY_PTS_0.0_FORM2_NO_REPORT_TO_EXTRACT;"
                            f"{_qb_evidence.AVAILABILITY_UNVERIFIED};"
                            f"POSITIVE_STARTER_CONFIRMATION_UNAVAILABLE_FROM_FREE_ESPN",
                            {ctx_key: 0.0}))
                        continue
                    factors.append(_factor(
                        "qb_specific", MISSING,
                        "QB_IDENTITY_EVIDENCE_FORM2_DEPTH_ROSTER_COMPOSITE",
                        f"{side}_QB_IDENTITY:{_qb_evidence.STATUS_SATISFIED};"
                        f"QB1_ATHLETE_ID_{form2['resolved_athlete_id']};"
                        f"AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT"))
                    if enforce_blocks:
                        blocked = True
                        block_reason = _qb_evidence.BLOCK_QB_AVAILABILITY_UNVERIFIED
                        block_detail = (
                            f"{side}_QB_AVAILABILITY_UNVERIFIABLE:identity "
                            f"satisfied via Form 2 (athlete ID "
                            f"{form2['resolved_athlete_id']}); no team injury "
                            f"report exists to verify availability")
                    continue
                if form2 is not None:
                    feed_reason += f";FORM2_FAILED:{form2['status']}"
                    detail += (f"; Form 2 composite failed closed: "
                               f"{form2['status']} ({form2['detail']})")
                factors.append(_factor(
                    "qb_specific" if sport in {"NFL", "CFB"} else "rotations_matchups",
                    MISSING, "ESPN_INJURIES", feed_reason))
                if sport in {"NFL", "CFB"} and enforce_blocks:
                    blocked, block_reason = True, BLOCK_QB_IDENTITY_UNVERIFIED
                    block_detail = f"{side}_QB_IDENTITY_UNVERIFIABLE:{detail}"
                continue
            out, doubtful = _out_doubtful(rows_)
            qbs_out = [e["name"] for e in out if e["position"] == "QB"]
            qbs_doubt = [e["name"] for e in doubtful if e["position"] == "QB"]
            adjustments[ctx_key] = pts
            factors.append(_factor(
                "qb_specific" if sport in {"NFL", "CFB"} else "rotations_matchups",
                USED, "ESPN_INJURIES_STRUCTURE_VERIFIED",
                f"{side}_OUT_QB:{qbs_out or 'none'};DOUBTFUL_QB:{qbs_doubt or 'none'};"
                f"INJURY_PTS_{pts}({pts_status});"
                f"POSITIVE_STARTER_CONFIRMATION_UNAVAILABLE_FROM_FREE_ESPN",
                {ctx_key: pts}))

    # -- 2. weather: archived evidence first, free live endpoint fallback --
    # Keyed weather APIs are NEVER called directly; they run Actions-side
    # and arrive as archived evidence. A present-but-defective archive fails
    # exactly like missing data (MISSING, never silently used or replaced).
    if sport in {"NFL", "CFB", "MLB"}:
        # SECURITY: Never trust user-supplied weather_evidence.
        # Archived weather must arrive via trusted loader, not input row.
        # User-supplied evidence is ignored for verified purposes.
        if row.get("weather_evidence") is not None:
            factors.append(_factor("weather_venue", MISSING,
                                   "USER_SUPPLIED_WEATHER_EVIDENCE_UNTRUSTED",
                                   "USER_SUPPLIED_WEATHER_EVIDENCE_IGNORED: use trusted loader"))
        evidence = None  # Do not read from row
        weather_done = False
        if False:  # Disabled: user evidence never trusted
            try:
                weather_adj, wdetail = admit_weather_evidence(
                    evidence, sport=sport, kickoff=kickoff, now=now)
            except WeatherEvidenceError as exc:
                factors.append(_factor("weather_venue", MISSING,
                                       "ARCHIVED_WEATHER_EVIDENCE",
                                       f"WEATHER_ARCHIVE_REJECTED:{exc}"))
                weather_done = True
            else:
                adjustments["weather_total_adj"] = weather_adj
                factors.append(_factor(
                    "weather_venue", USED, "ARCHIVED_WEATHER_EVIDENCE",
                    wdetail + ";KEYED_APIS_NEVER_CALLED_DIRECTLY",
                    {"weather_total_adj": weather_adj}))
                weather_done = True
        if not weather_done:
            # No archive supplied: free live Open-Meteo via the existing
            # declared-threshold provider.weather path (no key required).
            weather_adj, weather_status = provider.weather(
                sport, competition, kickoff,
                latitude=row.get("venue_latitude"), longitude=row.get("venue_longitude"))
            if weather_status in {"HEURISTIC_FORECAST_NOT_CALIBRATED", "INDOOR_VERIFIED"}:
                adjustments["weather_total_adj"] = weather_adj
                factors.append(_factor(
                    "weather_venue", USED, "OPEN_METEO_LIVE_FREE_NO_KEY",
                    f"{weather_status};DECLARED_THRESHOLD_HEURISTIC_NOT_CALIBRATED;"
                    f"TOTAL_ADJ_{weather_adj}_SPLIT_HALF_EACH_TEAM",
                    {"weather_total_adj": weather_adj}))
            else:
                factors.append(_factor("weather_venue", MISSING, "OPEN_METEO_LIVE_FREE_NO_KEY",
                                       f"WEATHER_UNVERIFIED:{weather_status}"))
    else:
        factors.append(_factor("weather_venue", NOT_APPLICABLE, "ESPN_VENUE",
                               "NBA indoor league"))

    # -- 3. MLB probable pitchers ------------------------------------------
    if sport == "MLB":
        home_abbr = str(home_team.get("abbreviation") or "")
        away_abbr = str(away_team.get("abbreviation") or "")
        padj, pfactors, pblocked, pdetail = mlb_pitcher_adjustments(
            provider.fetch, game_date=kickoff.date(),
            home={"abbr": home_abbr, "name": home_name},
            away={"abbr": away_abbr, "name": away_name},
            season=kickoff.year, kickoff=kickoff)
        factors.extend(pfactors)
        if pblocked:
            adjustments = {k: v for k, v in adjustments.items()
                           if k not in {"home_pitcher_adj", "away_pitcher_adj"}}
            if enforce_blocks:
                blocked, block_reason = True, BLOCK_PITCHER_UNCONFIRMED
                block_detail = pdetail
        else:
            # DISABLED_PENDING_INCREMENTAL_VALUE (owner ruling, Oct 13
            # 2026): the declared ERA-based starter adjustments stay
            # visible in the factor audit for research (ERA/IP/GS and the
            # declared heuristic label are in each factor's reason), but
            # the priced contribution is exactly zero.
            for f in pfactors:
                if f["factor"] == "starting_pitcher" and f["status"] == USED:
                    declared = dict(f["adjustments"])
                    f["status"] = DISABLED_PENDING_INCREMENTAL_VALUE
                    f["reason"] += (";PRICING_CONTRIBUTION_ZERO_"
                                    "DISABLED_PENDING_INCREMENTAL_VALUE")
                    f["adjustments"] = {k: 0.0 for k in declared}
            adjustments.update({k: 0.0 for k in padj})

    # -- 4. rest/travel ------------------------------------------------------
    if sport in {"NFL", "CFB", "MLB"}:
        home_rest = _rest_days(provider, sport, home_team, kickoff)
        away_rest = _rest_days(provider, sport, away_team, kickoff)
        if home_rest is None or away_rest is None:
            factors.append(_factor("rest_schedule", MISSING, "ESPN_SCHEDULE",
                                   "REST_DAYS_UNVERIFIED_FOR_ONE_OR_BOTH_TEAMS"))
        else:
            diff = home_rest - away_rest
            cap = DECL_REST_ADJ_CAP[sport]
            adj = round(bounded(DECL_REST_PTS_PER_DAY[sport] * diff, -cap, cap), 3)
            # DISABLED_PENDING_INCREMENTAL_VALUE (owner ruling, Oct 13
            # 2026): rest days and the declared differential stay visible
            # for research; the priced contribution is exactly zero.
            adjustments["rest_diff_adj"] = 0.0
            factors.append(_factor(
                "rest_schedule", DISABLED_PENDING_INCREMENTAL_VALUE,
                "ESPN_SCHEDULE_VERIFIED",
                f"HOME_REST_DAYS_{home_rest};AWAY_REST_DAYS_{away_rest};"
                f"DECLARED_DIFF_ADJ_{adj}_NOT_CALIBRATED;"
                f"PRICING_CONTRIBUTION_ZERO_"
                f"DISABLED_PENDING_INCREMENTAL_VALUE",
                {"rest_diff_adj": 0.0}))
        factors.append(_factor(
            "travel",
            PENDING_VALIDATION if _FREE_FACTORS_AVAILABLE else NOT_WIRED,
            "FREE_FACTORS_INGEST_TRAVEL" if _FREE_FACTORS_AVAILABLE else "NONE",
            "TRAVEL_MILES_TZ_HARNESS_GATED: free_factors.ingest_travel "
            "available; awaiting backtest validation before pricing use"
            if _FREE_FACTORS_AVAILABLE else
            "TRAVEL_DISTANCE_NOT_WIRED: venue-history travel "
            "pipeline not built; rest days capture congestion only"))
    else:  # NBA
        home_rest = _rest_days(provider, sport, home_team, kickoff)
        away_rest = _rest_days(provider, sport, away_team, kickoff)
        b2b = ("HOME" if home_rest is not None and home_rest < 1.5 else "",
               "AWAY" if away_rest is not None and away_rest < 1.5 else "")
        b2b_flag = "+".join(s for s in b2b if s) or "none"
        if home_rest is None or away_rest is None:
            factors.append(_factor("rest_back_to_back", MISSING, "ESPN_SCHEDULE",
                                   "REST_DAYS_UNVERIFIED_FOR_ONE_OR_BOTH_TEAMS"))
        else:
            factors.append(_factor(
                "rest_back_to_back", USED, "ESPN_SCHEDULE_VERIFIED",
                f"HOME_REST_DAYS_{home_rest};AWAY_REST_DAYS_{away_rest};"
                f"BACK_TO_BACK_{b2b_flag};REST_ADJ_MANUAL_ONLY_NO_PRICE_EFFECT"))
        factors.append(_factor(
            "travel",
            PENDING_VALIDATION if _FREE_FACTORS_AVAILABLE else NOT_WIRED,
            "FREE_FACTORS_INGEST_TRAVEL" if _FREE_FACTORS_AVAILABLE else "NONE",
            "TRAVEL_MILES_TZ_HARNESS_GATED: free_factors.ingest_travel "
            "available; awaiting backtest validation before pricing use"
            if _FREE_FACTORS_AVAILABLE else
            "TRAVEL_DISTANCE_NOT_WIRED"))

    # A uniquely identified fixture and a structurally readable injuries feed
    # do not establish team scoring strength. The phone runner must require
    # a prior completed game for BOTH NFL teams before asking its generic
    # score engine for a team-specific probability. Never promote a two-prior
    # score estimate into an apparent 50%+ EV wager.
    nfl_history_missing = sport == "NFL" and (home_rest is None or away_rest is None)
    if nfl_history_missing and enforce_blocks:
        blocked = True
        block_reason = BLOCK_NFL_TEAM_HISTORY
        missing_sides = [side for side, rest in (
            ("HOME", home_rest), ("AWAY", away_rest)) if rest is None]
        block_detail = "NFL_PRIOR_COMPLETED_GAME_HISTORY_REQUIRED:" + ",".join(missing_sides)

    # -- engine-owned / backlog factors: stated honestly --------------------
    factors.append(_factor(
        "team_strength_ratings", MISSING if nfl_history_missing else USED,
        "FREE_MODELS_ENGINE",
        "NFL_TWO_TEAM_HISTORY_UNVERIFIED_NO_RATING_AUTHORITY"
        if nfl_history_missing else
        "HEURISTIC_NOT_VALIDATED: bounded prior-five-game "
        "scoring-margin proxy + static HFA"))
    factors.append(_factor("recent_form", DISABLED_PENDING_INCREMENTAL_VALUE,
                           "FREE_MODELS_ENGINE",
                           "HEURISTIC_NOT_VALIDATED: short prior-game scoring trend; "
                           "MLB form subsumed into rating;"
                           "PRICING_CONTRIBUTION_ZERO_"
                           "DISABLED_PENDING_INCREMENTAL_VALUE "
                           "(engine form term not applied to score means)"))
    factors.append(_factor("home_advantage", USED, "FREE_MODELS_ENGINE",
                           "STATIC_DECLARED_HFA_PRIOR: league baseline only, "
                           "no venue-specific coefficient"))
    factors.append(_factor("pace_tempo", NOT_WIRED, "NONE",
                           "PACE_TEMPO_NOT_WIRED"))
    if sport == "MLB":
        factors.append(_factor(
            "lineups_usage", PENDING_VALIDATION,
            "MLB_BATTER_LINEUP_VERIFICATION_PATH",
            "MLB_BATTER_PROP_LINEUP_PATH_EXISTS; "
            "THIS_GAME_LINEUP_NOT_VERIFIED_BY_PREPRICING; "
            "GAME_LEVEL_PRICING_EFFECT_ZERO_PENDING_CHRONOLOGICAL_VALIDATION"))
    else:
        factors.append(_factor("lineups_usage", NOT_WIRED, "NONE",
                               "PROJECTED_LINEUPS_USAGE_NOT_WIRED"))
    factors.append(_factor("advanced_metrics", NOT_WIRED, "NONE",
                           "EPA_DVOA_STATCAST_NEXTGEN_NOT_WIRED"))
    factors.append(_factor("situational", NOT_WIRED, "NONE",
                           "MOTIVATION_SPOTS_NEWS_SPEED_OFFICIATING_NOT_WIRED_PER_STANDING_RULE"))
    if sport == "NFL":
        factors.append(_factor("efficiency_epa", NOT_WIRED, "NONE", "EPA_SUCCESS_RATE_NOT_WIRED"))
        factors.append(_factor("key_numbers", USED, "FREE_MODELS_ENGINE",
                               "PUSH_AWARE_ONLY: integer push refund modeled; "
                               "NFL 3/7 distribution not trained"))
        factors.append(_factor("turnover_special_teams", NOT_WIRED, "NONE",
                               "TURNOVER_DIFFERENTIAL_SPECIAL_TEAMS_NOT_WIRED"))
    elif sport == "CFB":
        factors.append(_factor("talent_portal", NOT_WIRED, "NONE", "TALENT_PORTAL_NOT_WIRED"))
        factors.append(_factor("key_numbers", USED, "FREE_MODELS_ENGINE",
                               "PUSH_AWARE_ONLY"))
    elif sport == "NBA":
        factors.append(_factor("four_factors", NOT_WIRED, "NONE",
                               "ORtg_DRtg_FOUR_FACTORS_NOT_WIRED"))
    elif sport == "MLB":
        factors.append(_factor(
            "bullpen", PENDING_VALIDATION if _BULLPEN_AVAILABLE else NOT_WIRED,
            "MLB_STATSAPI_BULLPEN_SOURCE_PATH" if _BULLPEN_AVAILABLE else "NONE",
            "SOURCE_MODULE_AVAILABLE_NOT_GAME_VERIFIED: prior-game workload collector; "
            "no sample fetched by this prepricing stage; zero pricing impact; "
            "chronological validation pending"
            if _BULLPEN_AVAILABLE else "BULLPEN_SOURCE_UNAVAILABLE"))
        factors.append(_factor(
            "statcast", PENDING_VALIDATION if _SAVANT_AVAILABLE else NOT_WIRED,
            "BASEBALL_SAVANT_SOURCE_PATH" if _SAVANT_AVAILABLE else "NONE",
            "SOURCE_MODULE_AVAILABLE_NOT_GAME_VERIFIED: Savant metrics collector; "
            "no sample fetched by this prepricing stage; zero pricing impact; "
            "chronological validation pending"
            if _SAVANT_AVAILABLE else "STATCAST_SOURCE_UNAVAILABLE"))
        factors.append(_factor(
            "park_factors",
            PENDING_VALIDATION if _FREE_FACTORS_AVAILABLE else NOT_WIRED,
            "FREE_FACTORS_INGEST_MLB_PARK" if _FREE_FACTORS_AVAILABLE else "NONE",
            "PARK_FACTORS_HARNESS_GATED: free_factors.ingest_mlb_park "
            "(2022-2024 regressed) available; awaiting backtest validation "
            "before pricing use"
            if _FREE_FACTORS_AVAILABLE else
            "PARK_FACTORS_NOT_WIRED: queued behind backtest bar"))
        factors.append(_factor(
            "umpire",
            PENDING_VALIDATION if _FREE_FACTORS_AVAILABLE else NOT_WIRED,
            "MLB_STATSAPI_OFFICIALS" if _FREE_FACTORS_AVAILABLE else "NONE",
            "UMPIRE_ASSIGNMENT_HARNESS_GATED: home-plate umpire from MLB "
            "StatsAPI schedule hydrate=officials (free, pregame, no key); "
            "assignment verified and audit-visible; tendency pricing effect "
            "inactive pending harness validation; missing assignment stays "
            "unknown, never inferred from crew rotation"
            if _FREE_FACTORS_AVAILABLE else
            "UMPIRE_NOT_WIRED: no stable free source"))
        factors.append(_factor("opponent_adjusted_offense", NOT_WIRED, "NONE",
                               "WRCPLUS_OPPONENT_ADJUSTED_OFFENSE_NOT_WIRED"))

    # -- Free factors integration (harness-gated) ---------------------------
    # sportsedge/free_factors.py provides declared, bounded factor
    # calculations. They are wired into the audit as PENDING_VALIDATION:
    # computed and visible, but NOT applied to pricing adjustments until
    # the backtest harness confirms chronological out-of-sample improvement
    # vs the existing model. See sportsedge/free_factors.py for the full
    # factor registry and validation status.
    if _FREE_FACTORS_AVAILABLE:
        factors.append(_factor(
            "free_factors_module", PENDING_VALIDATION,
            "SPORTSEDGE_FREE_FACTORS_V1",
            "HARNESS_GATED: park/rest/travel/weather/key_numbers available "
            "via free_factors.ingest_*; awaiting backtest validation; "
            "adjustments NOT applied to pricing"))
    else:
        factors.append(_factor(
            "free_factors_module", NOT_WIRED, "NONE",
            "FREE_FACTORS_MODULE_UNAVAILABLE: sportsedge.free_factors "
            "could not be imported"))

    receipts.extend(provider.receipts)
    # Fail-closed: a blocked game must never carry partial adjustments.
    if blocked:
        adjustments = {}
    return {"game_key": f"{sport}:{game_label}:{kickoff.date().isoformat()}",
            "game_label": game_label, "sport": sport,
            "kickoff_utc": kickoff.isoformat(), "blocked": blocked,
            "block_reason": block_reason, "block_detail": block_detail,
            "availability_status": availability_status,
            "adjustments": adjustments, "factors": factors,
            "receipts": receipts,
            "qb_form2_identities": qb_form2_identities}


def _normalize_form2_bundles(qb_form2_bundles):
    """Index Form 2 bundles by ESPN team ID (str). Accepts a mapping of
    team ID -> bundle, or an iterable of bundle dicts (each carrying its
    own team binding). Malformed entries are dropped here; a bundle that
    cannot be indexed by its own asserted team ID is not evidence for
    any team and the evaluator never sees it."""
    if not qb_form2_bundles:
        return {}
    if isinstance(qb_form2_bundles, dict):
        return {str(k): v for k, v in qb_form2_bundles.items()}
    indexed = {}
    for bundle in qb_form2_bundles:
        if isinstance(bundle, dict):
            team_id = (bundle.get("team") or {}).get("espn_id")
            if team_id is not None:
                indexed[str(team_id)] = bundle
    return indexed


def stage_games(game_rows, *, now, getter, enforce_blocks=True, as_of=None, historical=False,
                qb_form2_bundles=None):
    """Run the pre-pricing stage for each game row.

    Rows sharing one game share one stage execution. Returns a list aligned
    with ``game_rows``; each entry is the _stage_one_game dict. ``now`` must
    be timezone-aware. ``enforce_blocks=False`` audits without blocking
    (manual --no-fetch mode: critical factors report MISSING instead of
    downgrading, preserving the explicit manual-only research path).

    ``qb_form2_bundles`` carries QB_IDENTITY_EVIDENCE Form 2 bundles
    (owner ruling, issue #2154) from a trusted capture/loader step --
    never from an input row. Default None: the gate behaves exactly as
    it did before Form 2 existed.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("STAGE_NOW_TIMEZONE_REQUIRED")
    groups, order = {}, []
    staged = [None] * len(game_rows)
    for i, r in enumerate(game_rows):
        if not isinstance(r, dict):
            raise ValueError("STAGE_LINE_MUST_BE_OBJECT")
        sport = str(r.get("sport") or "").upper()
        away, home = _resolve_teams(r)
        kickoff = dt(r.get("commence_time") or r.get("kickoff"))
        key = (sport, away, home,
               kickoff.date().isoformat() if kickoff else "NO_KICKOFF")
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(i)
    bundles = _normalize_form2_bundles(qb_form2_bundles)
    for key in order:
        idxs = groups[key]
        result = _stage_one_game([game_rows[i] for i in idxs], now=now,
                                 getter=getter, enforce_blocks=enforce_blocks,
                                 qb_form2_bundles=bundles)
        for i in idxs:
            staged[i] = dict(result)
    return staged
