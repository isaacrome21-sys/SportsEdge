"""Research-only CFB score construction for a pre-freeze signal screen.

This is deliberately NOT a live model or a source of Model_P/EV.  A separate
screen must establish a nonzero raw residual signal before anyone freezes an
artifact or starts a prospective clock.  Historical score release at kickoff
+24 hours is a conservative UNVERIFIED proxy, not a publication timestamp.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

BASE_POINTS = 28.0
HFA_POINTS = 2.5
LAST_GAMES = 5
RIDGE_GAMES = 3.0
MIN_PRIOR_GAMES = 3
FIRST_ELIGIBLE_WEEK = 5
MAX_RAW_MARGIN = 24.0
MAX_MARKET_DISAGREEMENT = 4.0  # proposed post-freeze issuance ceiling only
EMBARGO = timedelta(hours=24)
ITERATIONS = 500
TOLERANCE = 1e-10


@dataclass(frozen=True)
class Game:
    game_id: int
    season: int
    week: int
    instant: datetime
    home_id: int
    away_id: int
    home_points: float
    away_points: float
    neutral_site: bool
    home_division: str
    away_division: str

    def __post_init__(self):
        if self.instant.tzinfo is None or self.instant.utcoffset() is None:
            raise ValueError("CFB_SUCCESSOR_KICKOFF_CLOCK_MISSING")
        if self.home_id == self.away_id:
            raise ValueError("CFB_SUCCESSOR_DUPLICATE_TEAM")
        if self.week < 1 or self.season < 2000:
            raise ValueError("CFB_SUCCESSOR_INVALID_SEASON_WEEK")
        if (not all(math.isfinite(float(x)) and float(x) >= 0
                    for x in (self.home_points, self.away_points))):
            raise ValueError("CFB_SUCCESSOR_INVALID_SCORE")
        if type(self.neutral_site) is not bool:
            raise ValueError("CFB_SUCCESSOR_NEUTRAL_SITE_UNKNOWN")
        if self.home_division not in ("fbs", "fcs") or self.away_division not in ("fbs", "fcs"):
            raise ValueError("CFB_SUCCESSOR_DIVISION_UNKNOWN")

    @property
    def fbs_fbs(self) -> bool:
        return self.home_division == self.away_division == "fbs"


@dataclass(frozen=True)
class Projection:
    game_id: int
    season: int
    week: int
    raw_margin: float
    raw_total: float
    training_games_available: int
    iterations: int


def _fit_converged_ratings(history: list[Game]):
    """Training-only ridge-regularized simultaneous off/def fixed point.

    Every team's last five FBS/FBS results define two equations.  The
    opponent's defense/offense rating is iterated to convergence rather than
    subtracted once, as in the retired PM model.  League centering removes
    offense/defense location indeterminacy.  All iteration constants are fixed.
    """
    recent = defaultdict(list)
    for g in history:
        if not g.fbs_fbs:
            continue
        half = 0.0 if g.neutral_site else HFA_POINTS / 2.0
        recent[g.home_id].append((g.home_points - half, g.away_points + half, g.away_id))
        recent[g.away_id].append((g.away_points + half, g.home_points - half, g.home_id))
    recent = {team: obs[-LAST_GAMES:] for team, obs in recent.items()}
    teams = sorted(recent)
    if not teams:
        return recent, {}, {}, 0
    off = {t: 0.0 for t in teams}
    deff = {t: 0.0 for t in teams}
    for iteration in range(1, ITERATIONS + 1):
        new_off, new_def = {}, {}
        for team in teams:
            obs = recent[team]
            denominator = len(obs) + RIDGE_GAMES
            new_off[team] = sum(
                pf - BASE_POINTS - deff[opp] for pf, _, opp in obs
            ) / denominator
            new_def[team] = sum(
                pa - BASE_POINTS - off[opp] for _, pa, opp in obs
            ) / denominator
        # Training-only league centering; deterministic order, no target-line
        # information enters the ratings.
        off_mean = sum(new_off.values()) / len(teams)
        def_mean = sum(new_def.values()) / len(teams)
        for team in teams:
            new_off[team] -= off_mean
            new_def[team] -= def_mean
        delta = max(
            max(abs(new_off[t] - off[t]) for t in teams),
            max(abs(new_def[t] - deff[t]) for t in teams),
        )
        off, deff = new_off, new_def
        if delta <= TOLERANCE:
            return recent, off, deff, iteration
    raise ValueError("CFB_SUCCESSOR_RATINGS_DID_NOT_CONVERGE")


def project_season(games: Iterable[Game]) -> list[Projection]:
    """Chronological as-of replay; no same-kickoff or recent finals leakage."""
    pending: deque[Game] = deque()
    admitted = []
    projections = []
    seen_ids = set()
    last_clock = None
    cached_ratings = None
    cache_size = -1
    for game in games:
        clock = game.instant.astimezone(UTC)
        if last_clock is not None and clock < last_clock:
            raise ValueError("CFB_SUCCESSOR_NONCHRONOLOGICAL_RESULTS")
        if game.game_id in seen_ids:
            raise ValueError("CFB_SUCCESSOR_DUPLICATE_RESULT_GAME_ID")
        seen_ids.add(game.game_id)
        last_clock = clock
        while pending and pending[0].instant.astimezone(UTC) + EMBARGO <= clock:
            released = pending.popleft()
            if released.fbs_fbs:
                admitted.append(released)
        if game.fbs_fbs and game.week >= FIRST_ELIGIBLE_WEEK:
            if cache_size != len(admitted):
                cached_ratings = _fit_converged_ratings(admitted)
                cache_size = len(admitted)
            recent, off, deff, iterations = cached_ratings
            if (len(recent.get(game.home_id, ())) >= MIN_PRIOR_GAMES
                    and len(recent.get(game.away_id, ())) >= MIN_PRIOR_GAMES):
                half = 0.0 if game.neutral_site else HFA_POINTS / 2
                hp = BASE_POINTS + off[game.home_id] + deff[game.away_id] + half
                ap = BASE_POINTS + off[game.away_id] + deff[game.home_id] - half
                projections.append(Projection(
                    game_id=game.game_id, season=game.season, week=game.week,
                    raw_margin=max(-MAX_RAW_MARGIN, min(MAX_RAW_MARGIN, hp - ap)),
                    raw_total=hp + ap, training_games_available=len(admitted),
                    iterations=iterations))
        pending.append(game)
    return projections


def proposed_market_anchor(raw: float, observed_entry_line: float) -> float:
    """Mathematical proposal only. Never called by the raw viability screen.

    Actual issuance is separately forbidden until a future freeze/forward
    evaluation authorizes a versioned market pricer. A future caller would
    require an independently timestamped *current entry quote*, never an
    ex-post historical closing line.
    """
    if not math.isfinite(raw) or not math.isfinite(observed_entry_line):
        raise ValueError("CFB_SUCCESSOR_NONFINITE_ANCHOR")
    return observed_entry_line + max(
        -MAX_MARKET_DISAGREEMENT,
        min(MAX_MARKET_DISAGREEMENT, raw - observed_entry_line),
    )
