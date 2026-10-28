"""NBA period-lines FORWARD wiring — build only, NOT FROZEN, no clock.

This module wires the calibration-screened candidate
``NBA_TEAM_PERIOD_RATINGS_V1`` (``sportsedge/nba_team_period_engine.py``)
to the one admitted period-outcomes feed and stamps every output
NON_COUNTED. It implements the build the NBA period-lines preregistration
draft (``research/nba_cbb_activation_20261028/NBA_PERIOD_LINES_PREREG_DRAFT.md``,
PR #2843) names in its §6: the period-lines forward build becomes
dispatchable once the §4.1 feed admission lands and the §4.2 capture
grammar exists (``sportsedge/nba_period_lines_intake.py``).

Admitted feed (§4.1): the ESPN summary API, admitted by
``research/nba_quarter_score_feed_admission_20261028/ADMISSION_RECORD.md``
(PR #2880) for exactly three scopes — DESIGN_SCREEN,
FORWARD_GRADING_OUTCOMES, IN_SEASON_PRIOR_BASELINES. It is NOT a
pregame-pricing input and NOT an in-play feed; nothing here uses it as
one. The target game's own quarters are consumed only after the game is
final, as grading labels; prior games enter only as in-season baselines
dated strictly before the target game (the engine enforces this).

Form gate (§4.1): observations are accepted only in the exact
``NBAPeriodObservation`` form the draft demands — source
``ESPN_SUMMARY_API`` / version ``espn-summary-v1:20261028``, four
regulation quarters per side as real ints (bools, floats and numeric
strings refuse), overtime periods carried separately and NEVER inside
the quarter tuples, halves exactly Q1+Q2 / Q3+Q4. Every refusal is
named and fail-closed; nothing is coerced.

Freeze state: the preregistration is a DRAFT (``DRAFT_NOT_IN_FORCE``).
Freezing is the owner's separate act. Any counted / forward-test entry
point in this module raises ``NBA_PERIOD_FORWARD_NOT_FROZEN``; the
research pricing path below stamps ``counted: False`` on every record
and grants no validation credit, no forward-clock credit and no PLAY
eligibility. PAPER / research only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

from sportsedge.nba_team_period_engine import price_game as _engine_price_game
from sportsedge.sports.nba.lines_card import NBALinesError, team_abbr
from sportsedge.sports.nba.period_history import NBAPeriodObservation

# The admitted feed identity (admission record, PR #2880).
ADMITTED_SOURCE = "ESPN_SUMMARY_API"
ADMITTED_SOURCE_VERSION = "espn-summary-v1:20261028"
ADMISSION_RECORD = ("research/nba_quarter_score_feed_admission_20261028/"
                    "ADMISSION_RECORD.md")
PREREG_DRAFT = ("research/nba_cbb_activation_20261028/"
                "NBA_PERIOD_LINES_PREREG_DRAFT.md")

FREEZE_STATE = "DRAFT_NOT_IN_FORCE"

# Named fail-closed refusals.
REFUSAL_NOT_FROZEN = "NBA_PERIOD_FORWARD_NOT_FROZEN"
REFUSAL_FORM_INVALID = "NBA_PERIOD_OBSERVATION_FORM_INVALID"
REFUSAL_SOURCE_NOT_ADMITTED = "NBA_PERIOD_OBSERVATION_SOURCE_NOT_ADMITTED"
REFUSAL_HALF_SUM_MISMATCH = "NBA_PERIOD_HALF_SUM_MISMATCH"
REFUSAL_SCORE_MISMATCH = "NBA_PERIOD_SCORE_MISMATCH"
REFUSAL_IDENTITY_UNVERIFIED = "NBA_PERIOD_IDENTITY_UNVERIFIED"
REFUSAL_GRADE_IDENTITY_MISMATCH = "NBA_PERIOD_GRADE_IDENTITY_MISMATCH"
REFUSAL_TARGET_NOT_FINAL = "NBA_PERIOD_TARGET_NOT_FINAL"

# Engine game dates are the game's US/Eastern local date (the
# scoreboard/slate convention): a 02:30Z tip belongs to the prior ET
# evening's slate, and same-slate games must never consume each other.
GAME_DATE_TZ = ZoneInfo("America/New_York")

SUBFAMILIES = ("TEAM_QUARTER_TOTAL", "GAME_QUARTER_TOTAL",
               "TEAM_HALF_TOTAL", "GAME_HALF_TOTAL")


class NBAPeriodForwardError(ValueError):
    """Named fail-closed refusal from the period forward wiring."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}:{detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def _refuse(reason: str, detail: str = ""):
    raise NBAPeriodForwardError(reason, detail)


def _parse_instant(value, field: str) -> datetime:
    if not isinstance(value, str):
        _refuse(REFUSAL_FORM_INVALID, f"{field} must be an ISO string: {value!r}")
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _refuse(REFUSAL_FORM_INVALID, f"{field} is not ISO-8601: {value!r}")
    if out.tzinfo is None or out.utcoffset() is None:
        _refuse(REFUSAL_FORM_INVALID, f"{field} carries no timezone: {value!r}")
    return out


def _quarters(value, field: str) -> tuple:
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list):
        _refuse(REFUSAL_FORM_INVALID, f"{field} must be a list of 4 ints: {value!r}")
    if len(value) != 4:
        _refuse(REFUSAL_FORM_INVALID,
                f"{field} must carry exactly four regulation quarters, "
                f"got {len(value)}: {value!r}")
    for x in value:
        # Real ints only: bool is an int subclass and floats / numeric
        # strings are coercions — the form gate refuses all three.
        if isinstance(x, bool) or not isinstance(x, int):
            _refuse(REFUSAL_FORM_INVALID,
                    f"{field} entries must be ints, got {x!r}")
        if x < 0:
            _refuse(REFUSAL_FORM_INVALID,
                    f"{field} entries must be non-negative, got {x!r}")
    return tuple(value)


def observation_from_record(record: Mapping) -> NBAPeriodObservation:
    """Build an ``NBAPeriodObservation`` from an admitted-feed record
    (the manifest/puller ``observation`` object), enforcing the §4.1
    form gate exactly. Refuses by name; never coerces."""
    if not isinstance(record, Mapping):
        _refuse(REFUSAL_FORM_INVALID, f"observation record is not a mapping: {record!r}")
    source = record.get("source")
    version = record.get("source_version")
    if source != ADMITTED_SOURCE or version != ADMITTED_SOURCE_VERSION:
        _refuse(REFUSAL_SOURCE_NOT_ADMITTED,
                f"source={source!r} source_version={version!r}; the admitted "
                f"feed is {ADMITTED_SOURCE} / {ADMITTED_SOURCE_VERSION}")
    game_id = record.get("game_id")
    if not isinstance(game_id, str) or not game_id.isdigit():
        _refuse(REFUSAL_FORM_INVALID,
                f"game_id must be an ESPN event id string: {game_id!r}")
    tipoff = _parse_instant(record.get("tipoff"), "tipoff")
    observed_at = _parse_instant(record.get("observed_at"), "observed_at")
    obs = NBAPeriodObservation(
        game_id=game_id, tipoff=tipoff, observed_at=observed_at,
        home_quarters=_quarters(record.get("home_quarters"), "home_quarters"),
        away_quarters=_quarters(record.get("away_quarters"), "away_quarters"),
        source=source, source_version=version)
    try:
        obs.validate()
    except ValueError as exc:
        _refuse(REFUSAL_FORM_INVALID, str(exc))
    return obs


def _entry_int_list(entry: Mapping, key: str) -> list:
    value = entry.get(key)
    if not isinstance(value, list) or any(
            isinstance(x, bool) or not isinstance(x, int) for x in value):
        _refuse(REFUSAL_FORM_INVALID, f"manifest entry {key} is not an int list: {value!r}")
    return value


def observation_from_manifest_entry(entry: Mapping) -> NBAPeriodObservation:
    """Validate one admission-manifest / puller entry end to end and
    return its observation. The entry's own cross-checks are re-run:
    regulation quarters equal the observation's tuples, linescore sums
    equal the payload finals (``SCORE_MISMATCH``), halves are the exact
    mechanical sums (``NBA_PERIOD_HALF_SUM_MISMATCH``), and overtime
    periods — present in the entry's linescores — never enter the
    tuples."""
    if not isinstance(entry, Mapping):
        _refuse(REFUSAL_FORM_INVALID, f"manifest entry is not a mapping: {entry!r}")
    obs = observation_from_record(entry.get("observation") or {})
    home_q = _entry_int_list(entry, "home_quarters_regulation")
    away_q = _entry_int_list(entry, "away_quarters_regulation")
    if tuple(home_q) != obs.home_quarters or tuple(away_q) != obs.away_quarters:
        _refuse(REFUSAL_FORM_INVALID,
                "entry regulation quarters disagree with its observation")
    for side, lines_key, final_key, quarters in (
            ("home", "home_linescores", "home_final", obs.home_quarters),
            ("away", "away_linescores", "away_final", obs.away_quarters)):
        lines = _entry_int_list(entry, lines_key)
        if len(lines) < 4 or tuple(lines[:4]) != quarters:
            _refuse(REFUSAL_FORM_INVALID,
                    f"{lines_key} does not start with the regulation quarters")
        final = entry.get(final_key)
        if isinstance(final, bool) or not isinstance(final, int):
            _refuse(REFUSAL_FORM_INVALID, f"{final_key} is not an int: {final!r}")
        if sum(lines) != final:
            _refuse(REFUSAL_SCORE_MISMATCH,
                    f"{side} linescores sum {sum(lines)} != final {final}")
    for side, key, quarters in (
            ("home", "home_half_scores", obs.home_quarters),
            ("away", "away_half_scores", obs.away_quarters)):
        halves = _entry_int_list(entry, key)
        expect = [quarters[0] + quarters[1], quarters[2] + quarters[3]]
        if halves != expect:
            _refuse(REFUSAL_HALF_SUM_MISMATCH,
                    f"{side} halves {halves} != Q1+Q2 / Q3+Q4 {expect}")
    return obs


def observations_from_admission_manifest(path) -> list:
    """Load the merged admission packet's sample manifest and return
    its observations, each re-validated through the form gate."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("source_id") != ADMITTED_SOURCE:
        _refuse(REFUSAL_SOURCE_NOT_ADMITTED,
                f"manifest source_id {doc.get('source_id')!r}")
    return [observation_from_manifest_entry(e) for e in doc.get("samples", [])]


def _team(value, entry) -> str:
    try:
        return team_abbr(str(value))
    except NBALinesError:
        _refuse(REFUSAL_IDENTITY_UNVERIFIED,
                f"team tricode {value!r} in entry {entry.get('espn_event_id')!r} "
                "does not resolve under the repo's NBA conventions")


def game_date_of(tipoff: datetime) -> str:
    return tipoff.astimezone(GAME_DATE_TZ).date().isoformat()


def game_row_from_entry(entry: Mapping) -> dict:
    """Adapt one admitted-feed entry into an engine game row: full
    finals (overtime included — ratings walk on full-game points),
    regulation quarters only, ET game date, engine season."""
    obs = observation_from_manifest_entry(entry)
    season = entry.get("engine_season")
    if isinstance(season, bool) or not isinstance(season, int):
        _refuse(REFUSAL_FORM_INVALID, f"engine_season is not an int: {season!r}")
    return {
        "game_id": obs.game_id,
        "date": game_date_of(obs.tipoff),
        "season": season,
        "home": _team(entry.get("home_team"), entry),
        "away": _team(entry.get("away_team"), entry),
        "home_pts": float(entry["home_final"]),
        "away_pts": float(entry["away_final"]),
        "home_quarters": obs.home_quarters,
        "away_quarters": obs.away_quarters,
    }


def history_from_entries(entries: Iterable[Mapping], *,
                         before_date: str) -> list:
    """In-season prior baselines from the admitted feed: engine rows
    dated strictly before ``before_date`` (the engine re-enforces the
    strictly-before rule at pricing; this filter is the feed-side
    statement of the same discipline)."""
    rows = [game_row_from_entry(e) for e in entries]
    return [r for r in rows if r["date"] < str(before_date)]


_NON_COUNTED_STAMPS = {
    "counted": False,
    "state": "NON_COUNTED",
    "freeze_state": FREEZE_STATE,
    "validation_credit": False,
    "forward_clock_credit": False,
    "play_eligible": False,
    "outcomes_feed": ADMITTED_SOURCE,
    "admission_record": ADMISSION_RECORD,
    "prereg_draft": PREREG_DRAFT,
}


def price_period_game(history: Iterable[Mapping], home: str, away: str, *,
                      season: int, target_date: str,
                      counted: bool = False) -> dict:
    """NON_COUNTED research pricing of one game's period totals from
    in-season prior baselines built on the admitted feed. The frozen
    period fit is reproduced from the history's fit-span quarters under
    the engine's own protocol, sourced as the admitted feed.

    Asking for a counted row refuses ``NBA_PERIOD_FORWARD_NOT_FROZEN``:
    the preregistration is a draft and no clock runs."""
    if counted:
        _refuse(REFUSAL_NOT_FROZEN,
                "the period-lines preregistration is DRAFT_NOT_IN_FORCE; "
                "freezing is the owner's separate act")
    out = _engine_price_game(
        history, home, away, season=season, target_date=target_date,
        period_source=(ADMITTED_SOURCE, ADMITTED_SOURCE_VERSION))
    return {**out, **_NON_COUNTED_STAMPS}


def price_counted_slate(*args, **kwargs):
    """The forward test's counted pricing entry point. It does not
    exist until the owner freezes the preregistration; calling it is a
    named refusal, never a silent NON_COUNTED downgrade."""
    _refuse(REFUSAL_NOT_FROZEN,
            "no counted period-lines slate may be priced before the "
            "owner freezes the preregistration")


def run_forward_test(*args, **kwargs):
    """The §5 forward test itself. NOT FROZEN — refuses by name."""
    _refuse(REFUSAL_NOT_FROZEN,
            "the period-lines forward test has not been frozen; no "
            "verdict, clock or counted row exists")


@dataclass(frozen=True)
class PeriodActuals:
    game_id: str
    date: str
    home: str
    away: str
    team_quarters: dict          # team -> (q1, q2, q3, q4)
    game_quarters: tuple         # (q1, q2, q3, q4)
    team_halves: dict            # team -> (h1, h2)
    game_halves: tuple           # (h1, h2)

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id, "date": self.date,
            "home": self.home, "away": self.away,
            "team_quarters": {t: list(q) for t, q in self.team_quarters.items()},
            "game_quarters": list(self.game_quarters),
            "team_halves": {t: list(h) for t, h in self.team_halves.items()},
            "game_halves": list(self.game_halves),
        }


def actuals_from_entry(entry: Mapping) -> PeriodActuals:
    """Post-final grading labels from one admitted-feed entry.
    Regulation periods only; overtime never enters a period actual."""
    obs = observation_from_manifest_entry(entry)
    home, away = _team(entry.get("home_team"), entry), _team(entry.get("away_team"), entry)
    hq, aq = obs.home_quarters, obs.away_quarters
    return PeriodActuals(
        game_id=obs.game_id, date=game_date_of(obs.tipoff),
        home=home, away=away,
        team_quarters={home: hq, away: aq},
        game_quarters=tuple(hq[i] + aq[i] for i in range(4)),
        team_halves={home: (hq[0] + hq[1], hq[2] + hq[3]),
                     away: (aq[0] + aq[1], aq[2] + aq[3])},
        game_halves=(hq[0] + hq[1] + aq[0] + aq[1],
                     hq[2] + hq[3] + aq[2] + aq[3]))


def _settle(model: float, line: float, actual: float) -> str:
    pick = "OVER" if model > line else "UNDER" if model < line else "NO_PICK"
    if pick == "NO_PICK" or actual == line:
        return "PUSH"
    won = (actual > line) if pick == "OVER" else (actual < line)
    return "WIN" if won else "LOSS"


def grade_period_game(priced: Mapping, entry: Mapping, *,
                      closing_quotes: Optional[Sequence[Mapping]] = None) -> dict:
    """Grade one NON_COUNTED priced game against the admitted feed's
    post-final observation for the same game. Identity is proven, not
    assumed: the entry's teams and ET date must equal the priced
    game's, else ``NBA_PERIOD_GRADE_IDENTITY_MISMATCH``. When parsed
    DK period captures (``nba_period_lines_intake`` quote dicts) are
    supplied, each priced quote is also settled against its actual —
    research grading only, ``counted: False`` throughout."""
    if priced.get("counted"):
        _refuse(REFUSAL_NOT_FROZEN,
                "a counted priced record cannot exist before the freeze")
    actuals = actuals_from_entry(entry)
    if (actuals.home != priced.get("home") or actuals.away != priced.get("away")
            or actuals.date != str(priced.get("target_date"))):
        _refuse(REFUSAL_GRADE_IDENTITY_MISMATCH,
                f"entry is {actuals.away} @ {actuals.home} on {actuals.date}; "
                f"priced game is {priced.get('away')} @ {priced.get('home')} "
                f"on {priced.get('target_date')}")
    periods = priced.get("periods") or {}
    if periods.get("status") != "PRICED":
        return {"game_id": actuals.game_id, "status": "NOT_GRADED",
                "reason": (periods.get("reason")
                           or priced.get("reason")
                           or "PERIODS_NOT_PRICED"),
                "actuals": actuals.to_dict(), **_NON_COUNTED_STAMPS}
    errors = {name: [] for name in SUBFAMILIES}
    for i in range(4):
        errors["TEAM_QUARTER_TOTAL"].append(
            abs(periods["team_quarter_totals"]["home"][i]
                - actuals.team_quarters[actuals.home][i]))
        errors["TEAM_QUARTER_TOTAL"].append(
            abs(periods["team_quarter_totals"]["away"][i]
                - actuals.team_quarters[actuals.away][i]))
        errors["GAME_QUARTER_TOTAL"].append(
            abs(periods["game_quarter_totals"][i] - actuals.game_quarters[i]))
    for i in range(2):
        errors["TEAM_HALF_TOTAL"].append(
            abs(periods["team_half_totals"]["home"][i]
                - actuals.team_halves[actuals.home][i]))
        errors["TEAM_HALF_TOTAL"].append(
            abs(periods["team_half_totals"]["away"][i]
                - actuals.team_halves[actuals.away][i]))
        errors["GAME_HALF_TOTAL"].append(
            abs(periods["game_half_totals"][i] - actuals.game_halves[i]))
    mae = {name: (sum(v) / len(v) if v else None) for name, v in errors.items()}

    settlements = []
    if closing_quotes:
        model_by_key = {}
        for i, w in enumerate(("Q1", "Q2", "Q3", "Q4")):
            model_by_key[("GAME_QUARTER_TOTAL", w, None)] = periods["game_quarter_totals"][i]
            model_by_key[("TEAM_QUARTER_TOTAL", w, actuals.home)] = periods["team_quarter_totals"]["home"][i]
            model_by_key[("TEAM_QUARTER_TOTAL", w, actuals.away)] = periods["team_quarter_totals"]["away"][i]
        for i, w in enumerate(("1H", "2H")):
            model_by_key[("GAME_HALF_TOTAL", w, None)] = periods["game_half_totals"][i]
            model_by_key[("TEAM_HALF_TOTAL", w, actuals.home)] = periods["team_half_totals"]["home"][i]
            model_by_key[("TEAM_HALF_TOTAL", w, actuals.away)] = periods["team_half_totals"]["away"][i]
        actual_by_key = {}
        for i, w in enumerate(("Q1", "Q2", "Q3", "Q4")):
            actual_by_key[("GAME_QUARTER_TOTAL", w, None)] = actuals.game_quarters[i]
            actual_by_key[("TEAM_QUARTER_TOTAL", w, actuals.home)] = actuals.team_quarters[actuals.home][i]
            actual_by_key[("TEAM_QUARTER_TOTAL", w, actuals.away)] = actuals.team_quarters[actuals.away][i]
        for i, w in enumerate(("1H", "2H")):
            actual_by_key[("GAME_HALF_TOTAL", w, None)] = actuals.game_halves[i]
            actual_by_key[("TEAM_HALF_TOTAL", w, actuals.home)] = actuals.team_halves[actuals.home][i]
            actual_by_key[("TEAM_HALF_TOTAL", w, actuals.away)] = actuals.team_halves[actuals.away][i]
        for q in closing_quotes:
            if q.get("status") != "PRICED":
                continue
            key = (q.get("subfamily"), q.get("window"), q.get("team"))
            if key not in model_by_key:
                continue
            model = model_by_key[key]
            settlements.append({
                "subfamily": key[0], "window": key[1], "team": key[2],
                "line": q.get("line"), "model": model,
                "actual": actual_by_key[key],
                "result": _settle(model, float(q["line"]), float(actual_by_key[key])),
                "counted": False})
    return {"game_id": actuals.game_id, "status": "GRADED",
            "mae": mae, "n_errors": {k: len(v) for k, v in errors.items()},
            "actuals": actuals.to_dict(), "settlements": settlements,
            **_NON_COUNTED_STAMPS}
