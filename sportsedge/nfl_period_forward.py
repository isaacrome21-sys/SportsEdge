"""NFL_PERIOD_DRIVE_STATE_V2 forward runner — BUILD, NOT FROZEN.

The family's forward-validation preregistration revision draft
(``research/nfl_period_forward_20261028/PREREG_NFL_PERIOD_LINES_FORWARD_V1_REVISION_DRAFT.md``,
PR #2914 — a DRAFT, not on main, adopting nothing) records in its
§14 FLAG 3 that the family had no forward runner: the §2 engine pin
is the design-screen implementation of record, a research script,
and refusal was effected only by the framework config's ``UNPINNED``
sentinel. This module is that build. It changes nothing about the
family's state:

  * ``FREEZE_STATE`` stays ``"DRAFT_NOT_IN_FORCE"``; no freeze act
    has happened and this build performs no part of it.
  * Every counted entry point refuses with
    ``NFL_PERIOD_FORWARD_NOT_FROZEN`` (the draft's §11 naming).
  * Every record this build writes carries ``counted=False`` and
    grants no validation, forward-clock, or PLAY credit. PAPER / 0u.

What the runner does (NON_COUNTED): price a slate of NFL games for
the family's twenty config markets (TOTAL / SPREAD / ML /
TEAM_TOTAL x 1Q-4Q + 1H) with the pinned construction
(``nfl_period_drive_state_v2@sha256:16593a87...`` — the screen
implementation in ``research/nfl_period_drive_state_screen_20261028/``,
imported unmodified after a sha256 pin check), apply the revision
draft's §6 pick rule, emit the draft's §4 per-row committed record,
and settle priced rows under the draft's §8 close-validity and
v1.1 moved-row rules. The construction takes no market input; entry
lines and prices come from the caller's captures.

Gaps and readings — stamped, never filled:

  * CAPTURE EXPANSION (draft §4/§15, still open): period lines are
    NOT in the priced capture subset and the NFL intake grammar has
    no period line forms. This runner consumes capture RECORDS
    (``PeriodQuote``) in its own form; it does not invent a capture
    pipeline, and no record it emits claims a real DraftKings
    capture existed. Landing-check quotes are a labeled synthetic
    fixture (``SYNTHETIC_LANDING_FIXTURE``).
  * B0 FORWARD FORM (draft §14 FLAG 5): the quarter-market §7b
    baseline is the sibling full-game mean x point-in-time league
    period shares. The share table here is fit on games final
    before the game's entry capture (same-season priors
    supplemented by the prior season's final shares, the screen's
    ``baseline_rows`` state machine driven by final-before-entry
    instead of week batches), and its hash is committed per row and
    per run. This is the draft's drafted-by-analogy reading, stamped
    ``B0_SHARE_FIT_READING_FLAG5`` wherever it is emitted, for the
    freeze review to confirm.
  * 1H BASELINE EMISSIONS (draft §4/§7b): the 1H baseline is the
    Lane A surface's derivative (``sportsedge/team_half_pricing.py``)
    as EMITTED at entry. That surface prices only against a live,
    verified pregame ESPN fixture, so its emissions cannot be
    re-derived from historical point-in-time inputs by this build.
    The runner records caller-supplied emissions verbatim; where no
    emission is supplied the row carries
    ``BASELINE_1H_EMISSION_ABSENT`` — never a substitute value.
  * GAME COMPLETION (draft §2 "games final before the entry
    capture"): a game counts as final for a later game's pricing
    state at kickoff + 4 hours (the completion convention, stamped
    ``COMPLETION_CONVENTION_KICKOFF_PLUS_4H`` in the run record).
  * ML CLOSES (draft §8): ``LINE_MOVED`` is defined by a different
    LINE; moneyline rows carry no line, so an ML close is valid or
    a capture failure on the timing/two-sidedness reasons only,
    and its CLV is the no-vig probability change. Stated here
    because the draft's text fixes the moved-row machinery on
    lined markets.

Point-in-time discipline mirrors the pinned screen exactly: the
league fit for a season is built on strictly prior seasons (RD-2),
team rates come from the screen's own ``TeamRateBook`` walked
chronologically (a game's rates are read before the game is
recorded), the sibling means come from the activation pack's
``WalkForward`` advanced in its own order, simulation streams
derive from (master seed 20261028, slate game index) with the
slate's game index order committed in the run record.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

# ------------------------------------------------------------------
# Identity, pins, freeze state
# ------------------------------------------------------------------
ENGINE_ID = "NFL_PERIOD_DRIVE_STATE_V2"
FAMILY_ID = "NFL_PERIOD_LINES"
FORWARD_SCHEMA = "SPORTSEDGE_NFL_PERIOD_FORWARD_ROW_V1"
RUN_SCHEMA = "SPORTSEDGE_NFL_PERIOD_FORWARD_RUN_V1"
SETTLEMENT_SCHEMA = "SPORTSEDGE_NFL_PERIOD_FORWARD_SETTLEMENT_V1"
FREEZE_STATE = "DRAFT_NOT_IN_FORCE"

ENGINE_PIN = ("nfl_period_drive_state_v2@sha256:"
              "16593a8779986f653705c481eaf0e079387933975123e386f8efd7e865b4658c")
MASTER_SEED = 20261028  # the screen's seed A; draft section 2

# The revision draft itself (PR #2914) is not on main; its sha256 is
# recorded here from that PR's SPEC_HASHES.txt as the document of
# record this build implements. It is recorded, not disk-verified —
# the freeze act lands the frozen document on main and pins it then.
PREREG_REVISION_DRAFT = ("research/nfl_period_forward_20261028/"
                         "PREREG_NFL_PERIOD_LINES_FORWARD_V1_REVISION_DRAFT.md")
PREREG_REVISION_DRAFT_SHA256 = \
    "5fd4079a5e9d781b394f12195fc976a03d48fd705ae8df8779c5120698f1cc84"
PREREG_DOCUMENT_ON_MAIN = False

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENGINE_REL = ("research/nfl_period_drive_state_screen_20261028/"
               "screen_nfl_period_drive_state_v2.py")
_CONFIG_REL = "sportsedge/forward_validation/configs/nfl_period_lines.json"

# Construction-of-record pins (PR #2914 SPEC_HASHES.txt, recomputed
# on the build's base head). Verified at runner construction; any
# disagreement refuses PIN_MISMATCH before any pricing.
EXPECTED_PINS = {
    "engine_sha256": (
        _ENGINE_REL,
        "16593a8779986f653705c481eaf0e079387933975123e386f8efd7e865b4658c"),
    "design_sha256": (
        "research/successor_designs_20261028/"
        "DESIGN_NFL_PERIOD_DRIVE_STATE_V2.md",
        "50b5f556ebcb6c7f951afdc8138595f4902a8a93bced8b22b85c5f8a0c257f1e"),
    "screen_results_sha256": (
        "research/nfl_period_drive_state_screen_20261028/"
        "screen_results_v2.json",
        "7089e33b7a6f6ba28d7776445515ebc7a38474f9ba7449c480897909f3d65cb8"),
    "v1_panel_machinery_sha256": (
        "research/nfl_activation_20261027/screen_nfl_activation_v1.py",
        "d8a11d8249c8142aa71062240ba92a799b4fa43ea0d2c7ffff757459460e568a"),
    "v1_prereg_draft_sha256": (
        "research/nfl_activation_20261027/"
        "PREREG_NFL_PERIOD_LINES_FORWARD_V1_DRAFT.md",
        "e992296160d73d61cd0c15faf904a02d90f61af0f87da34d615de04988a17928"),
    "config_sha256": (
        _CONFIG_REL,
        "7d677a841f3edb82a3809bdc97a7866779b89643f0c6eae41eaee5b16803f045"),
    "sibling_engine_sha256": (
        "sportsedge/nfl_team_total_dist.py",
        "50c5d9ff068b3bf629a725d5713a956d3149565c2f29c59ac8af3fc6461dcc27"),
    "team_half_pricing_sha256": (
        "sportsedge/team_half_pricing.py",
        "3d76cf730111d75c415a682e3f733b1374e19745f61b49b83dfb68e06f430308"),
}

# Markets (the framework config's twenty; asserted against it).
MARKETS = (
    "TOTAL_1Q", "SPREAD_1Q", "ML_1Q", "TEAM_TOTAL_1Q",
    "TOTAL_2Q", "SPREAD_2Q", "ML_2Q", "TEAM_TOTAL_2Q",
    "TOTAL_3Q", "SPREAD_3Q", "ML_3Q", "TEAM_TOTAL_3Q",
    "TOTAL_4Q", "SPREAD_4Q", "ML_4Q", "TEAM_TOTAL_4Q",
    "TOTAL_1H", "SPREAD_1H", "ML_1H", "TEAM_TOTAL_1H",
)
PERIODS = ("1Q", "2Q", "3Q", "4Q", "1H")
_QUARTER_INDEX = {"1Q": 0, "2Q": 1, "3Q": 2, "4Q": 3}

# Pick rule (draft section 6, fixed terms).
PICK_GAP_QUARTER = 1.5
PICK_GAP_1H = 2.0
PICK_ML_EDGE = 0.04

# Close validity (draft section 8); the config carries the same
# values and construction refuses if they ever disagree.
CLOSE_MAX_AGE = timedelta(minutes=60)
CAPTURE_FAILURE_REASONS = ("NO_CLOSE_ROW", "CLOSE_SINGLE_SIDED",
                           "CLOSE_NOT_PREKICKOFF", "CLOSE_STALE")
INSUFFICIENT_CLOSE_DATA_TRIP = 0.20
MOVED_SHARE_CAP = 0.50

# Named fail-closed refusals.
REFUSAL_NOT_FROZEN = "NFL_PERIOD_FORWARD_NOT_FROZEN"
REFUSAL_PIN_MISMATCH = "PIN_MISMATCH"
REFUSAL_CONFIG_MISMATCH = "CONFIG_MISMATCH"
REFUSAL_FORM_INVALID = "NFL_PERIOD_CAPTURE_FORM_INVALID"
REFUSAL_IDENTITY_UNVERIFIED = "NFL_PERIOD_IDENTITY_UNVERIFIED"
REFUSAL_FIT_UNAVAILABLE = "NFL_PERIOD_FIT_UNAVAILABLE"
REFUSAL_RECORD_EXISTS = "RECORD_FILE_EXISTS"

# Stamps for drafted readings / absent emissions (never filled).
STAMP_B0_READING = "B0_SHARE_FIT_READING_FLAG5"
STAMP_1H_ABSENT = "BASELINE_1H_EMISSION_ABSENT"
STAMP_COMPLETION = "COMPLETION_CONVENTION_KICKOFF_PLUS_4H"
GAME_COMPLETION = timedelta(hours=4)

GAME_TZ = ZoneInfo("America/New_York")


class NflPeriodForwardError(ValueError):
    """Named fail-closed refusal from the NFL period forward runner."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}:{detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def _refuse(reason: str, detail: str = ""):
    raise NflPeriodForwardError(reason, detail)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_instant(value, field: str) -> datetime:
    if not isinstance(value, str):
        _refuse(REFUSAL_FORM_INVALID,
                f"{field} must be an ISO string: {value!r}")
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _refuse(REFUSAL_FORM_INVALID, f"{field} is not ISO-8601: {value!r}")
    if out.tzinfo is None or out.utcoffset() is None:
        _refuse(REFUSAL_FORM_INVALID, f"{field} carries no timezone: {value!r}")
    return out


def _real_number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _refuse(REFUSAL_FORM_INVALID, f"{field} must be a number: {value!r}")
    out = float(value)
    if out != out or out in (float("inf"), float("-inf")):
        _refuse(REFUSAL_FORM_INVALID, f"{field} must be finite: {value!r}")
    return out


def _american_price(value, field: str) -> Optional[int]:
    """An American odds price as a real int, or None (side absent —
    the form a single-sided close arrives in). Bools, floats and
    numeric strings refuse: no coercion at the form gate."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        _refuse(REFUSAL_FORM_INVALID,
                f"{field} must be an int American price or None: {value!r}")
    if value == 0 or -100 < value < 100:
        _refuse(REFUSAL_FORM_INVALID,
                f"{field} is not a valid American price: {value!r}")
    return value


def implied_prob(price: int) -> float:
    """Implied probability of an American price."""
    if price < 0:
        return (-price) / ((-price) + 100.0)
    return 100.0 / (price + 100.0)


def no_vig_pair(price_a: int, price_b: int) -> tuple:
    ia, ib = implied_prob(price_a), implied_prob(price_b)
    total = ia + ib
    return ia / total, ib / total


# ------------------------------------------------------------------
# Capture + slate forms
# ------------------------------------------------------------------
@dataclass(frozen=True)
class PeriodQuote:
    """One captured two-sided quote for one period market of one
    game, in the runner's capture-record form. Side A is the
    value-scale "over" side (OVER for totals / team totals, HOME
    for spreads and moneylines); side B is UNDER / AWAY. ``line``
    is on the realized-value scale for side A (a home spread is
    stored on the home-margin scale); moneylines carry no line.
    A price of None marks an absent side (single-sided)."""
    game_id: str
    market: str
    team: Optional[str]
    line: Optional[float]
    price_a: Optional[int]
    price_b: Optional[int]
    captured_at: str
    source: str

    def validate(self) -> None:
        if self.market not in MARKETS:
            _refuse(REFUSAL_FORM_INVALID, f"unknown market {self.market!r}")
        kind, period = self.market.rsplit("_", 1)
        if period not in PERIODS:
            _refuse(REFUSAL_FORM_INVALID, f"unknown period in {self.market!r}")
        if kind == "TEAM_TOTAL":
            if not isinstance(self.team, str) or not self.team:
                _refuse(REFUSAL_FORM_INVALID,
                        f"TEAM_TOTAL quote needs a team: {self.team!r}")
        elif self.team is not None:
            _refuse(REFUSAL_FORM_INVALID,
                    f"{self.market} quote must not carry a team")
        if kind == "ML":
            if self.line is not None:
                _refuse(REFUSAL_FORM_INVALID, "ML quotes carry no line")
        else:
            _real_number(self.line, "line")
        _american_price(self.price_a, "price_a")
        _american_price(self.price_b, "price_b")
        _parse_instant(self.captured_at, "captured_at")
        if not isinstance(self.source, str) or not self.source:
            _refuse(REFUSAL_FORM_INVALID, "quote source must be named")

    @property
    def two_sided(self) -> bool:
        return self.price_a is not None and self.price_b is not None

    def key(self) -> tuple:
        return (self.game_id, self.market, self.team)


@dataclass(frozen=True)
class SlateGame:
    game_id: str
    season: int
    week: int
    gameday: str          # ISO date, the schedules record's gameday
    kickoff: str          # ISO instant with timezone
    home: str
    away: str

    def validate(self, schedules_row) -> None:
        if schedules_row is None:
            _refuse(REFUSAL_IDENTITY_UNVERIFIED,
                    f"game {self.game_id!r} is not in the schedules record")
        if (schedules_row["home_team"] != self.home
                or schedules_row["away_team"] != self.away
                or int(schedules_row["season"]) != self.season
                or int(schedules_row["week"]) != self.week):
            _refuse(REFUSAL_IDENTITY_UNVERIFIED,
                    f"slate game {self.game_id!r} disagrees with the "
                    f"schedules record ({schedules_row['away_team']} @ "
                    f"{schedules_row['home_team']}, season "
                    f"{schedules_row['season']} week {schedules_row['week']})")
        _parse_instant(self.kickoff, "kickoff")


# ------------------------------------------------------------------
# Market distribution summaries + pick rule (pure; unit-tested)
# ------------------------------------------------------------------
def period_values(home_q: np.ndarray, away_q: np.ndarray,
                  period: str) -> tuple:
    """Per-replication realized values on each market's scale:
    (total, home team, away team, home margin) for one period.
    1H is Q1+Q2 (regulation only; overtime never enters)."""
    if period == "1H":
        h = home_q[:, 0] + home_q[:, 1]
        a = away_q[:, 0] + away_q[:, 1]
    else:
        i = _QUARTER_INDEX[period]
        h = home_q[:, i]
        a = away_q[:, i]
    return h + a, h, a, h - a


def line_market_summary(values: np.ndarray, line: float) -> dict:
    """Mean + both-side probabilities for a lined market on its
    value scale: side A wins when value > line."""
    values = np.asarray(values, dtype=float)
    return {
        "mean": float(values.mean()),
        "p_a": float(np.mean(values > line)),
        "p_b": float(np.mean(values < line)),
        "p_push": float(np.mean(values == line)),
    }


def ml_summary(home_values: np.ndarray, away_values: np.ndarray) -> dict:
    """Moneyline probabilities from per-replication team points:
    a tied period is its own mass (the market pushes)."""
    return {
        "p_a": float(np.mean(home_values > away_values)),
        "p_b": float(np.mean(home_values < away_values)),
        "p_push": float(np.mean(home_values == away_values)),
        "margin_mean": float(np.mean(home_values - away_values)),
    }


def classify_pick(market: str, *, model_mean: Optional[float],
                  line: Optional[float], p_a: float, p_b: float,
                  novig_a: float, novig_b: float) -> dict:
    """The revision draft's section 6 pick rule, fixed terms.
    Totals / team totals / spreads: PICKED at |gap| >= 1.5 (quarter)
    or >= 2.0 (1H), gap = model mean - entry line on the market's
    value scale, pick side by the gap's sign. Moneylines: PICKED
    when the model's win probability exceeds the entry no-vig
    probability by >= 0.04 on the model-favored side."""
    kind, period = market.rsplit("_", 1)
    threshold = PICK_GAP_1H if period == "1H" else PICK_GAP_QUARTER
    if kind == "ML":
        if p_a == p_b:
            return {"classification": "NOT_PICKED", "gap": 0.0,
                    "pick_side": None, "selected_side": "TIE",
                    "threshold": PICK_ML_EDGE}
        side = "A" if p_a > p_b else "B"
        edge = (p_a - novig_a) if side == "A" else (p_b - novig_b)
        return {"classification": "PICKED" if edge >= PICK_ML_EDGE
                else "NOT_PICKED",
                "gap": float(edge), "pick_side": side if edge >= PICK_ML_EDGE
                else None, "selected_side": side, "threshold": PICK_ML_EDGE}
    gap = float(model_mean - line)
    if gap == 0.0:
        return {"classification": "NOT_PICKED", "gap": 0.0,
                "pick_side": None, "selected_side": "TIE",
                "threshold": threshold, "stamp": "GAP_ZERO"}
    side = "A" if gap > 0 else "B"
    selected = "TIE" if p_a == p_b else ("A" if p_a > p_b else "B")
    return {"classification": "PICKED" if abs(gap) >= threshold
            else "NOT_PICKED",
            "gap": gap, "pick_side": side if abs(gap) >= threshold else None,
            "selected_side": selected, "threshold": threshold}


def side_name(market: str, side: Optional[str]) -> Optional[str]:
    if side is None:
        return None
    if side == "TIE":
        return "TIE"
    kind, _ = market.rsplit("_", 1)
    if kind in ("TOTAL", "TEAM_TOTAL"):
        return "OVER" if side == "A" else "UNDER"
    return "HOME" if side == "A" else "AWAY"


# ------------------------------------------------------------------
# Close validity + the v1.1 moved-row rules (draft section 8; pure)
# ------------------------------------------------------------------
def evaluate_close(*, market: str, entry_line: Optional[float],
                   selected_side: Optional[str],
                   close: Optional[PeriodQuote], kickoff: datetime) -> dict:
    """Exactly one disposition per priced row. Validity (timing,
    two-sidedness, line identity) is checked before any moved
    classification; a row is a capture failure or a moved row,
    never both. Reasons: NO_CLOSE_ROW, CLOSE_SINGLE_SIDED,
    CLOSE_NOT_PREKICKOFF, CLOSE_STALE (the four capture failures),
    LINE_MOVED, or VALID."""
    if close is None:
        return {"disposition": "CLV_MISSING", "reason": "NO_CLOSE_ROW"}
    if not close.two_sided:
        return {"disposition": "CLV_MISSING", "reason": "CLOSE_SINGLE_SIDED"}
    captured = _parse_instant(close.captured_at, "close captured_at")
    if captured >= kickoff:
        return {"disposition": "CLV_MISSING",
                "reason": "CLOSE_NOT_PREKICKOFF"}
    if kickoff - captured > CLOSE_MAX_AGE:
        return {"disposition": "CLV_MISSING", "reason": "CLOSE_STALE"}
    kind, _ = market.rsplit("_", 1)
    if kind != "ML" and float(close.line) != float(entry_line):
        direction = None
        if selected_side in ("A", "B"):
            lower = float(close.line) < float(entry_line)
            # A lower line helps side A (OVER / HOME), hurts side B.
            favorable = lower if selected_side == "A" else not lower
            direction = "FAVORABLE" if favorable else "ADVERSE"
        return {"disposition": "LINE_MOVED",
                "reason": "LINE_MOVED", "direction": direction,
                "close_line": float(close.line)}
    novig_a, novig_b = no_vig_pair(close.price_a, close.price_b)
    return {"disposition": "VALID", "reason": None,
            "close_novig": {"a": novig_a, "b": novig_b},
            "close_line": None if kind == "ML" else float(close.line)}


def market_close_accounting(rows: Sequence[Mapping]) -> dict:
    """Per-market section 8 accounting over settled rows: the 20%
    trip counts ONLY the four capture failures; moved rows are
    their own bucket with a direction split; a moved share above
    50% labels the market LOW_COVERAGE (draft FLAG 1's reading of
    the v1.1 ruling)."""
    by_market: dict[str, dict] = {}
    for row in rows:
        slot = by_market.setdefault(row["market"], {
            "priced_rows": 0, "clv_missing": {r: 0 for r in
                                              CAPTURE_FAILURE_REASONS},
            "moved_rows": 0, "moved_favorable": 0, "moved_adverse": 0,
            "valid_closes": 0})
        slot["priced_rows"] += 1
        reason = row.get("close_reason")
        if reason in CAPTURE_FAILURE_REASONS:
            slot["clv_missing"][reason] += 1
        elif reason == "LINE_MOVED":
            slot["moved_rows"] += 1
            if row.get("move_direction") == "FAVORABLE":
                slot["moved_favorable"] += 1
            elif row.get("move_direction") == "ADVERSE":
                slot["moved_adverse"] += 1
        elif row.get("close_disposition") == "VALID":
            slot["valid_closes"] += 1
    for slot in by_market.values():
        n = slot["priced_rows"]
        failures = sum(slot["clv_missing"].values())
        slot["capture_failure_share"] = failures / n if n else 0.0
        slot["insufficient_close_data"] = bool(
            n and slot["capture_failure_share"] > INSUFFICIENT_CLOSE_DATA_TRIP)
        slot["moved_share"] = slot["moved_rows"] / n if n else 0.0
        slot["low_coverage"] = bool(n and slot["moved_share"] > MOVED_SHARE_CAP)
    return by_market


# ------------------------------------------------------------------
# B0 forward share fit (draft section 7b + section 14 FLAG 5)
# ------------------------------------------------------------------
def fit_b0_shares(panel: pd.DataFrame, *, season: int,
                  final_before_game_ids) -> tuple:
    """Point-in-time league period shares for ``season``: the
    pinned screen's ``baseline_rows`` league-share state machine,
    driven by games final before the entry capture instead of week
    batches (the FLAG 5 forward form — a READING, stamped as such).
    Same-season priors first; if none, the prior season's final
    shares; if neither, uniform. Accumulation follows the panel's
    canonical (season, week, game_id, team) order exactly, so for a
    week-opening game — where the final-before set equals the
    screen's strictly-prior-weeks set — the shares are float-exact
    against ``baseline_rows``.

    Returns (shares, fit_record); the fit record's sha256 commits
    the season, the basis, and the exact game set fitted on."""
    final_ids = set(final_before_game_ids)
    ordered = panel.sort_values(["season", "week", "game_id", "team"])

    def accumulate(season_rows, only_final: bool) -> tuple:
        pts = np.zeros(4)
        total = 0.0
        ids = []
        for r in season_rows.itertuples():
            if only_final and r.game_id not in final_ids:
                continue
            arr = np.array([r.q1, r.q2, r.q3, r.q4], dtype=float)
            pts = pts + arr
            total += float(arr.sum())
            if r.game_id not in ids:
                ids.append(r.game_id)
        return pts, total, ids

    season_rows = ordered[ordered["season"] == season]
    pts, total, ids = accumulate(season_rows, only_final=True)
    if total > 0:
        shares, basis = pts / total, "SAME_SEASON_PRIORS"
        used_ids = sorted(ids)
    else:
        prior_rows = ordered[ordered["season"] == season - 1]
        pts, total, ids = accumulate(prior_rows, only_final=False)
        if total > 0:
            shares, basis = pts / total, "PRIOR_SEASON_FINAL"
            used_ids = sorted(ids)
        else:
            shares, basis = np.array([0.25, 0.25, 0.25, 0.25]), \
                "UNIFORM_FALLBACK"
            used_ids = []
    fit_record = {
        "season": int(season), "basis": basis,
        "game_ids": used_ids, "n_team_games": int(2 * len(used_ids)),
        "shares": [float(x) for x in shares],
        "stamp": STAMP_B0_READING,
    }
    fit_record["fit_sha256"] = hashlib.sha256(json.dumps(
        {k: fit_record[k] for k in ("season", "basis", "game_ids")},
        sort_keys=True).encode("utf-8")).hexdigest()
    return shares, fit_record


# ------------------------------------------------------------------
# History: schedules + period panel + PBP, loaded through the
# pinned machinery (never re-implemented here)
# ------------------------------------------------------------------
class PeriodHistory:
    """Point-in-time inputs for the runner, built by the pinned
    screen's own loaders and the activation pack's panel machinery,
    imported unmodified. ``input_hashes`` are the sha256 of the
    bytes actually used; ``snapshot_sha256`` commits the set (the
    draft section 2 history snapshot, hashed before pricing)."""

    def __init__(self, *, games: pd.DataFrame, panel: pd.DataFrame,
                 plays: pd.DataFrame, starts: pd.DataFrame,
                 agg: pd.DataFrame, input_hashes: Mapping,
                 panel_integrity: Mapping):
        self.games = games
        self.panel = panel
        self.plays = plays
        self.starts = starts
        self.agg = agg
        self.input_hashes = dict(input_hashes)
        self.panel_integrity = dict(panel_integrity)
        self.snapshot_sha256 = hashlib.sha256(json.dumps(
            self.input_hashes, sort_keys=True).encode("utf-8")).hexdigest()
        self.schedules_by_id = {}
        for r in games.itertuples():
            self.schedules_by_id[r.game_id] = {
                "game_id": r.game_id, "season": int(r.season),
                "week": int(r.week), "gameday": str(r.gameday),
                "gametime": getattr(r, "gametime", None),
                "home_team": r.home_team, "away_team": r.away_team,
                "home_score": (None if pd.isna(r.home_score)
                               else float(r.home_score)),
                "away_score": (None if pd.isna(r.away_score)
                               else float(r.away_score)),
                "game_type": r.game_type,
            }
        self.panel_by_game: dict[str, dict[str, tuple]] = {}
        for r in panel.itertuples():
            self.panel_by_game.setdefault(r.game_id, {})[r.team] = (
                float(r.q1), float(r.q2), float(r.q3), float(r.q4))
        # Chronological REG-final order shared by the walks
        # (season, week, gameday, game_id — the screen's own order).
        reg = games[(games["game_type"] == "REG")
                    & games["home_score"].notna()].copy()
        reg = reg.sort_values(["season", "week", "gameday", "game_id"])
        self.reg_final_order = [r.game_id for r in reg.itertuples()]
        agg_ids = set(agg["game_id"]) if len(agg) else set()
        self.book_order = [g for g in self.reg_final_order if g in agg_ids]

    # -- kickoff / completion instants ------------------------------
    def kickoff_of(self, game_id: str) -> datetime:
        row = self.schedules_by_id[game_id]
        gametime = row.get("gametime")
        if isinstance(gametime, str) and gametime.strip():
            clock = datetime.strptime(gametime.strip(), "%I:%M%p").time()
        else:
            clock = datetime.strptime("1:00PM", "%I:%M%p").time()
        day = datetime.fromisoformat(row["gameday"]).date()
        return datetime.combine(day, clock, tzinfo=GAME_TZ)

    def end_of(self, game_id: str) -> datetime:
        """When a game counts as final for a later game's pricing
        state: kickoff + 4h (the completion convention)."""
        return self.kickoff_of(game_id) + GAME_COMPLETION

    # -- settlement finals ------------------------------------------
    def finals_for(self, game_id: str) -> Optional[dict]:
        """Regulation period finals for one game from the panel +
        schedules record. None when the schedules record lacks a
        final (the caller stamps RESULT_UNAVAILABLE); a schedules
        row with no scores is VOID (postponed / cancelled)."""
        row = self.schedules_by_id.get(game_id)
        if row is None:
            return None
        if row["home_score"] is None or row["away_score"] is None:
            return {"status": "VOID", "game_id": game_id}
        panel_game = self.panel_by_game.get(game_id)
        if panel_game is None or row["home_team"] not in panel_game \
                or row["away_team"] not in panel_game:
            return None
        return {"status": "FINAL", "game_id": game_id,
                "home": row["home_team"], "away": row["away_team"],
                "home_quarters": panel_game[row["home_team"]],
                "away_quarters": panel_game[row["away_team"]]}

    @classmethod
    def load(cls, cache_dir, *, engine, v1,
             pbp_seasons=(2022, 2023, 2024, 2025)) -> "PeriodHistory":
        """Load through the pinned loaders: schedules and the PBP
        seasons are fetched (or read from cache) by the activation
        pack's ``fetch`` with hashes recorded; the period panel is
        the v1 pack's own ``build_period_panel``; plays / starts /
        aggregates are the pinned screen's own functions."""
        hashes: dict[str, str] = {}
        gpath, gh = v1.fetch(cache_dir, "games.csv.gz", v1.SCHEDULES_URL)
        hashes["games_csv_gz"] = gh
        games = pd.read_csv(gpath, low_memory=False)
        panel = v1.build_period_panel(cache_dir, hashes)
        integrity = engine.panel_integrity(panel, games)
        pbp = engine.load_pbp(cache_dir, pbp_seasons, hashes)
        plays = engine.prepare_plays(pbp)
        starts = engine.drive_starts(plays)
        season_of_game = plays.groupby("game_id")["season"].first()
        starts = starts.assign(
            season=starts["game_id"].map(season_of_game)).dropna(
                subset=["season"])
        agg = engine.team_game_aggregates(plays, starts)
        return cls(games=games, panel=panel, plays=plays, starts=starts,
                   agg=agg, input_hashes=hashes, panel_integrity=integrity)


_NON_COUNTED_STAMPS = {
    "counted": False,
    "state": "NON_COUNTED",
    "freeze_state": FREEZE_STATE,
    "validation_credit": False,
    "forward_clock_credit": False,
    "play_eligible": False,
}


# ------------------------------------------------------------------
# The runner
# ------------------------------------------------------------------
class NflPeriodForwardRunner:
    """Prices NFL_PERIOD_DRIVE_STATE_V2 slates in NON_COUNTED mode
    and settles priced rows under the draft's section 8 rules.
    Construction verifies the family's pins; a disagreement refuses
    PIN_MISMATCH before anything is priced."""

    def __init__(self, *, repo_root=None) -> None:
        self.root = Path(repo_root) if repo_root is not None else _REPO_ROOT
        self.pins = {}
        for name, (rel, expected) in EXPECTED_PINS.items():
            path = self.root / rel
            if not path.exists():
                _refuse(REFUSAL_PIN_MISMATCH, f"{rel} is missing")
            actual = _sha256_file(path)
            if actual != expected:
                _refuse(REFUSAL_PIN_MISMATCH,
                        f"{rel} sha256 {actual} != pin {expected}")
            self.pins[name] = actual
        config = json.loads((self.root / _CONFIG_REL).read_text(
            encoding="utf-8"))
        if tuple(sorted(config.get("markets", []))) != tuple(sorted(MARKETS)):
            _refuse(REFUSAL_CONFIG_MISMATCH,
                    "config markets disagree with the family's twenty")
        if float(config.get("close_max_age_minutes", -1)) != 60.0 \
                or float(config.get("max_clv_missing_share", -1)) != 0.20:
            _refuse(REFUSAL_CONFIG_MISMATCH,
                    "config close-validity values disagree with draft "
                    "section 8 (60:00 / 20%)")
        self.config_model_version = config.get("model_version")
        if self.config_model_version not in ("UNPINNED", ENGINE_PIN):
            _refuse(REFUSAL_CONFIG_MISMATCH,
                    f"config model_version {self.config_model_version!r} "
                    "is neither the UNPINNED sentinel nor the section 2 "
                    "pin string")
        self._engine = None
        self._v1 = None

    # -- pinned machinery --------------------------------------------
    def engine(self):
        if self._engine is None:
            path = self.root / _ENGINE_REL
            spec = importlib.util.spec_from_file_location(
                "screen_nfl_period_drive_state_v2", str(path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self._engine = mod
        return self._engine

    def v1(self):
        if self._v1 is None:
            self._v1 = self.engine().load_v1_module()
        return self._v1

    def load_history(self, cache_dir, **kwargs) -> PeriodHistory:
        return PeriodHistory.load(cache_dir, engine=self.engine(),
                                  v1=self.v1(), **kwargs)

    # -- counted entry points: named refusals -------------------------
    def price_counted_slate(self, *args, **kwargs):
        _refuse(REFUSAL_NOT_FROZEN,
                "the family's preregistration revision is a DRAFT — "
                "NOT FROZEN, NOT ADOPTED; freezing is the owner's "
                "separate prospective act (draft section 15)")

    def run_forward_test(self, *args, **kwargs):
        _refuse(REFUSAL_NOT_FROZEN,
                "no forward test exists before the owner freeze act; "
                "no verdict, clock or counted row exists")

    # -- NON_COUNTED pricing -------------------------------------------
    def price_slate(self, history: PeriodHistory, games: Sequence[SlateGame],
                    entry_quotes: Sequence[PeriodQuote], *,
                    baseline_1h_emissions: Optional[Mapping] = None,
                    counted: bool = False) -> dict:
        """Price one slate NON_COUNTED. Rows exist only where a
        paired entry quote was captured (the draft section 4
        universe); per-row failures are recorded in the run's
        refusal list and never abort the slate (draft section 11).
        Asking for counted rows refuses NFL_PERIOD_FORWARD_NOT_FROZEN."""
        if counted:
            _refuse(REFUSAL_NOT_FROZEN,
                    "counted rows are zero until the owner freeze act")
        engine = self.engine()
        v1 = self.v1()
        emissions = dict(baseline_1h_emissions or {})

        quotes_by_game: dict[str, dict[tuple, PeriodQuote]] = {}
        for q in entry_quotes:
            q.validate()
            quotes_by_game.setdefault(q.game_id, {})[q.key()[1:]] = q

        ordered = []
        for g in games:
            g.validate(history.schedules_by_id.get(g.game_id))
            game_quotes = quotes_by_game.get(g.game_id, {})
            if game_quotes:
                entry_time = min(
                    _parse_instant(q.captured_at, "captured_at")
                    for q in game_quotes.values())
            else:
                entry_time = _parse_instant(g.kickoff, "kickoff") \
                    - timedelta(hours=1)
            ordered.append((entry_time, g))
        ordered.sort(key=lambda t: (t[0], t[1].game_id))

        # Walk state: the sibling WalkForward and the screen's
        # TeamRateBook, each advanced in its own canonical order
        # over games final before each game's entry capture.
        wf = v1.WalkForward(history.games)
        wf_rows = list(wf.games.itertuples())
        wf_max_week = {int(s): int(wf.games[wf.games.season == s]
                                   .week.max())
                       for s in wf.games.season.unique()}
        book = engine.TeamRateBook(history.agg, None)
        fits: dict[int, object] = {}

        def fit_for(season: int):
            if season not in fits:
                tr_plays = history.plays[history.plays["season"] < season]
                tr_starts = history.starts[
                    history.starts["season"] < season]
                if len(tr_plays) == 0:
                    return None
                fits[season] = engine.LeagueFit(tr_plays, tr_starts)
            return fits[season]

        wf_i = 0
        book_i = 0

        def advance(entry_time: datetime) -> None:
            nonlocal wf_i, book_i
            while wf_i < len(wf_rows):
                row = wf_rows[wf_i]
                if history.end_of(row.game_id) > entry_time:
                    break
                wf.record_game(row)
                if int(row.week) == wf_max_week[int(row.season)]:
                    sc = wf.season_scores.get(int(row.season), [])
                    if sc:
                        wf.season_league_mean[int(row.season)] = float(
                            np.mean(sc))
                wf_i += 1
            while book_i < len(history.book_order):
                gid = history.book_order[book_i]
                if history.end_of(gid) > entry_time:
                    break
                book.record_game(gid)
                book_i += 1

        rows: list[dict] = []
        refusals: list[dict] = []
        game_index_order: list[str] = []
        share_fits: dict[str, dict] = {}
        j = 0
        for entry_time, g in ordered:
            advance(entry_time)
            game_quotes = quotes_by_game.get(g.game_id, {})
            if not game_quotes:
                refusals.append({"game_id": g.game_id,
                                 "reason": "NO_ENTRY_CAPTURE",
                                 "market": None, "team": None})
                continue
            fit = fit_for(g.season)
            if fit is None:
                refusals.append({"game_id": g.game_id,
                                 "reason": REFUSAL_FIT_UNAVAILABLE,
                                 "market": None, "team": None})
                continue
            final_ids = [gid for gid in history.panel_by_game
                         if history.end_of(gid) <= entry_time]
            shares, fit_record = fit_b0_shares(
                history.panel, season=g.season,
                final_before_game_ids=final_ids)
            share_fits[fit_record["fit_sha256"]] = fit_record
            mu_home = float(wf.mu_for(g.home, g.away, g.season, g.week)[0])
            mu_away = float(wf.mu_for(g.away, g.home, g.season, g.week)[0])
            home_b = book.bundle(g.home, g.season)
            away_b = book.bundle(g.away, g.season)
            rng = np.random.default_rng(
                np.random.SeedSequence([MASTER_SEED, j]))
            sim = engine.simulate_game(fit, home_b, away_b, rng)
            game_index_order.append(g.game_id)
            rows.extend(self._game_rows(
                g, sim["home_q"], sim["away_q"], game_quotes,
                shares=shares, fit_record=fit_record,
                mu_home=mu_home, mu_away=mu_away, emissions=emissions,
                history=history, game_index=j, refusals=refusals))
            j += 1

        run = {
            "schema": RUN_SCHEMA, "kind": "FORWARD_PRICING_RUN",
            "engine_id": ENGINE_ID, "family": FAMILY_ID,
            "construction_pin": ENGINE_PIN,
            "master_seed": MASTER_SEED,
            "game_index_order": game_index_order,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pins": {**self.pins,
                     "prereg_revision_draft_sha256":
                         PREREG_REVISION_DRAFT_SHA256,
                     "prereg_document_on_main": PREREG_DOCUMENT_ON_MAIN,
                     "runner_sha256": _sha256_file(Path(__file__))},
            "config_model_version": self.config_model_version,
            "history_snapshot_sha256": history.snapshot_sha256,
            "input_hashes": history.input_hashes,
            "panel_integrity": history.panel_integrity,
            "b0_share_fits": share_fits,
            "completion_convention": STAMP_COMPLETION,
            "n_rows": len(rows), "n_refusals": len(refusals),
            "counted_rows": 0,
            **_NON_COUNTED_STAMPS,
        }
        return {"run": run, "rows": rows, "refusals": refusals}

    def _game_rows(self, g: SlateGame, home_q: np.ndarray,
                   away_q: np.ndarray, game_quotes: Mapping, *,
                   shares: np.ndarray, fit_record: Mapping,
                   mu_home: float, mu_away: float,
                   emissions: Mapping, history: PeriodHistory,
                   game_index: int, refusals: list) -> list:
        b0_home = mu_home * shares
        b0_away = mu_away * shares
        out = []
        for market in MARKETS:
            kind, period = market.rsplit("_", 1)
            teams = (g.home, g.away) if kind == "TEAM_TOTAL" else (None,)
            total_v, home_v, away_v, margin_v = period_values(
                home_q, away_q, period)
            for team in teams:
                quote = game_quotes.get((market, team))
                if quote is None:
                    continue
                base = {"game_id": g.game_id, "market": market,
                        "team": team}
                if not quote.two_sided:
                    refusals.append({**base, "reason": "ENTRY_SINGLE_SIDED"})
                    continue
                if kind == "TEAM_TOTAL" and team not in (g.home, g.away):
                    refusals.append({**base,
                                     "reason": REFUSAL_IDENTITY_UNVERIFIED})
                    continue
                if kind == "TOTAL":
                    values = total_v
                elif kind == "TEAM_TOTAL":
                    values = home_v if team == g.home else away_v
                else:
                    values = margin_v
                if kind == "ML":
                    summary = ml_summary(home_v, away_v)
                    model_mean = None
                else:
                    summary = line_market_summary(values, float(quote.line))
                    model_mean = summary["mean"]
                novig_a, novig_b = no_vig_pair(quote.price_a, quote.price_b)
                pick = classify_pick(
                    market, model_mean=model_mean, line=quote.line,
                    p_a=summary["p_a"], p_b=summary["p_b"],
                    novig_a=novig_a, novig_b=novig_b)
                row = {
                    "schema": FORWARD_SCHEMA,
                    "row_id": f"{g.game_id}:{market}"
                              + (f":{team}" if team else ""),
                    "game_id": g.game_id, "season": g.season,
                    "week": g.week, "gameday": g.gameday,
                    "kickoff": g.kickoff, "home": g.home, "away": g.away,
                    "market": market, "period": period, "team": team,
                    "line": quote.line,
                    "entry": {"price_a": quote.price_a,
                              "price_b": quote.price_b,
                              "captured_at": quote.captured_at,
                              "source": quote.source},
                    "entry_novig": {"a": novig_a, "b": novig_b},
                    "model": {"mean": model_mean,
                              "margin_mean": summary.get("margin_mean"),
                              "p_a": summary["p_a"], "p_b": summary["p_b"],
                              "p_push": summary["p_push"]},
                    "selected_side": pick["selected_side"],
                    "selected_side_name": side_name(
                        market, pick["selected_side"]),
                    "pick": {"classification": pick["classification"],
                             "gap": pick["gap"],
                             "side": pick["pick_side"],
                             "side_name": side_name(market,
                                                    pick["pick_side"]),
                             "threshold": pick["threshold"]},
                    "baseline_ref": self._baseline_ref(
                        market, period, team, g, b0_home=b0_home,
                        b0_away=b0_away, fit_record=fit_record,
                        mu_home=mu_home, mu_away=mu_away,
                        emissions=emissions),
                    "game_index": game_index,
                    "model_version": self.config_model_version,
                    "construction_pin": ENGINE_PIN,
                    **_NON_COUNTED_STAMPS,
                }
                if "stamp" in pick:
                    row["pick"]["stamp"] = pick["stamp"]
                out.append(row)
        return out

    def _baseline_ref(self, market: str, period: str,
                      team: Optional[str], g: SlateGame, *,
                      b0_home: np.ndarray, b0_away: np.ndarray,
                      fit_record: Mapping, mu_home: float,
                      mu_away: float, emissions: Mapping) -> dict:
        kind, _ = market.rsplit("_", 1)
        if period != "1H":
            idx = _QUARTER_INDEX[period]
            if kind == "TOTAL":
                mean = float(b0_home[idx] + b0_away[idx])
            elif kind == "TEAM_TOTAL":
                mean = float((b0_home if team == g.home else b0_away)[idx])
            else:
                mean = float(b0_home[idx] - b0_away[idx])
            return {"kind": "B0", "mean": mean,
                    "sibling_mu": {"home": mu_home, "away": mu_away},
                    "shares": fit_record["shares"],
                    "share_fit_sha256": fit_record["fit_sha256"],
                    "share_fit_basis": fit_record["basis"],
                    "stamp": STAMP_B0_READING}
        key = (g.game_id, market, team)
        emitted = emissions.get(key)
        return {"kind": "LANE_A_TEAM_HALF_DERIVATIVE",
                "mean": (None if emitted is None else float(emitted)),
                "stamp": None if emitted is not None else STAMP_1H_ABSENT,
                "source": "CALLER_EMISSION" if emitted is not None
                else None}

    # -- settlement (draft sections 3 + 8) ------------------------------
    def settle_records(self, rows: Sequence[Mapping],
                       close_quotes: Sequence[PeriodQuote],
                       finals: Mapping) -> dict:
        """Settle NON_COUNTED priced rows against final period
        scoring and the closing captures. Every row gets exactly
        one disposition; closes are read under section 8 validity
        before any moved classification."""
        closes = {}
        for q in close_quotes:
            q.validate()
            closes[q.key()] = q
        settlements = []
        for row in rows:
            base = {"row_id": row["row_id"], "game_id": row["game_id"],
                    "market": row["market"], "team": row["team"],
                    **_NON_COUNTED_STAMPS}
            final = finals.get(row["game_id"])
            if final is None:
                settlements.append({**base,
                                    "disposition": "RESULT_UNAVAILABLE"})
                continue
            if final.get("status") == "VOID":
                settlements.append({**base, "disposition": "VOID"})
                continue
            actual = _actual_value(row, final)
            result = _grade_row(row, actual)
            kickoff = _parse_instant(row["kickoff"], "kickoff")
            close = closes.get((row["game_id"], row["market"],
                                row["team"]))
            ev = evaluate_close(market=row["market"],
                                entry_line=row["line"],
                                selected_side=row["selected_side"],
                                close=close, kickoff=kickoff)
            clv = None
            if ev["disposition"] == "VALID" \
                    and row["selected_side"] in ("A", "B"):
                side = row["selected_side"].lower()
                clv = ev["close_novig"][side] - row["entry_novig"][side]
            settlements.append({
                **base, "disposition": "GRADED", "actual": actual,
                "result": result,
                "close_disposition": ev["disposition"],
                "close_reason": ev["reason"],
                "move_direction": ev.get("direction"),
                "clv": clv})
        valid_clv = [s["clv"] for s in settlements
                     if s.get("clv") is not None]
        summary = {
            "schema": SETTLEMENT_SCHEMA,
            "n_rows": len(settlements),
            "graded": sum(1 for s in settlements
                          if s["disposition"] == "GRADED"),
            "void": sum(1 for s in settlements
                        if s["disposition"] == "VOID"),
            "result_unavailable": sum(
                1 for s in settlements
                if s["disposition"] == "RESULT_UNAVAILABLE"),
            "push": sum(1 for s in settlements
                        if s.get("result") == "PUSH"),
            "mean_clv_valid_rows": (float(np.mean(valid_clv))
                                    if valid_clv else None),
            "n_clv_valid_rows": len(valid_clv),
            "per_market_close_accounting": market_close_accounting(
                [s for s in settlements if s["disposition"] == "GRADED"]),
            **_NON_COUNTED_STAMPS,
        }
        return {"settlements": settlements, "summary": summary}


def _actual_value(row: Mapping, final: Mapping):
    """The realized value on the row's market scale (regulation
    period scoring only; overtime never enters). ML returns the
    period outcome string."""
    kind, period = row["market"].rsplit("_", 1)
    hq, aq = final["home_quarters"], final["away_quarters"]
    if period == "1H":
        h = hq[0] + hq[1]
        a = aq[0] + aq[1]
    else:
        i = _QUARTER_INDEX[period]
        h, a = hq[i], aq[i]
    if kind == "TOTAL":
        return float(h + a)
    if kind == "TEAM_TOTAL":
        return float(h if row["team"] == final["home"] else a)
    if kind == "SPREAD":
        return float(h - a)
    return "HOME_WIN" if h > a else "AWAY_WIN" if a > h else "TIE"


def _grade_row(row: Mapping, actual) -> str:
    """WIN / LOSS / PUSH for the row's graded side: the pick side
    when PICKED, else the model-selected side. A final value equal
    to the line is a push; a tied ML period pushes."""
    kind, _ = row["market"].rsplit("_", 1)
    side = row["pick"]["side"] or row["selected_side"]
    if kind == "ML":
        if actual == "TIE":
            return "PUSH"
        if side not in ("A", "B"):
            return "NO_PICK"
        won = (actual == "HOME_WIN") if side == "A" \
            else (actual == "AWAY_WIN")
        return "WIN" if won else "LOSS"
    if float(actual) == float(row["line"]):
        return "PUSH"
    if side not in ("A", "B"):
        return "NO_PICK"
    over = float(actual) > float(row["line"])
    return "WIN" if over == (side == "A") else "LOSS"


def write_records(records: Sequence[Mapping], out_path) -> Path:
    """Create-only record write (the frozen runners' rule): a run
    writes its records exactly once; an existing file is a refusal,
    never an overwrite."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(r, sort_keys=True) + "\n" for r in records)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        _refuse(REFUSAL_RECORD_EXISTS,
                f"refusing to overwrite existing records at {path}")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(payload)
    return path
