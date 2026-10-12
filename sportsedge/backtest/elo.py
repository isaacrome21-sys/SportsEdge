"""Per-sport Elo baselines: the comparison floor. Research only.

Simple, transparent Elo per sport (NFL/CFB/MLB/NBA). Free data only:
wins, losses, and scores from the harness's outcome loaders. NO market
data anywhere in the ratings — market prices must never become model
features, and that includes the floor.

Parameters are documented starting values, NOT tuned. The point of this
leg is a transparent, hard-to-beat-by-accident floor for the "existing
model", not an optimized rating system.

Sport parameters (K, home-field advantage in Elo points, margin-of-victory
handling, offseason carryover toward 1500):

    NFL: K=20,  HFA=65,  MOV on,  carryover=0.67
    CFB: K=20,  HFA=65,  MOV on,  carryover=0.50
    MLB: K=5,   HFA=25,  MOV off, carryover=0.60
    NBA: K=20,  HFA=100, MOV on,  carryover=0.75

K/HFA follow standard FiveThirtyEight practice (NFL K=20/HFA=65,
NBA K=20/HFA=100); MLB uses a smaller K because single baseball games
carry less signal, and MOV is off because run differential is noisy.
CFB uses NFL-style values with heavier offseason regression (roster
turnover). CBB is not wired: no CBB outcomes exist in the harness yet,
and the code is sport-agnostic when they do.

Formulas:
    expected_home = 1 / (1 + 10^(-(elo_h + hfa - elo_a) / 400))
    mov_mult      = ln(|mov| + 1) * 2.2 / (0.001 * elo_diff + 2.2)
                    (538-style; mov sports only; ties use mov_mult = 1)
    elo_diff      = winner_pregame_incl_hfa - loser_pregame_incl_hfa
    delta         = K * mov_mult * (actual - expected_winner)
Offseason (when a game's ``season`` differs from the previous game's):
    elo = 1500 + (elo - 1500) * carryover, applied to every team.
New/unknown teams start at 1500. Updates are zero-sum within a season:
no rating inflation.

Harness wiring: ``make_elo_price_fn(sport, games_by_fixture_id)`` returns
a runner-compatible price_fn for the model name ``"elo"`` (ML only —
Elo prices winners, not lines). ``naive_price_fn`` is the coin-flip floor
(ML 0.5/0.5). Run with models=["existing", "candidate", "elo", ...] and
the floor appears in compare_models; pass its summary to
report.to_markdown(..., extra_models={"elo": ...}) to render it.
"""
from __future__ import annotations

import math

from .market_baseline import BaselineError, canonical_team, parse_ts_utc

INIT_RATING = 1500.0

SPORT_PARAMS = {
    # K, HFA (Elo points), margin-of-victory, offseason carryover.
    "nfl": {"k": 20, "hfa": 65, "mov": True, "carryover": 0.67},
    "cfb": {"k": 20, "hfa": 65, "mov": True, "carryover": 0.50},
    "mlb": {"k": 5, "hfa": 25, "mov": False, "carryover": 0.60},
    "nba": {"k": 20, "hfa": 100, "mov": True, "carryover": 0.75},
}


class EloError(BaselineError):
    pass


def _check_score(value, name):
    try:
        score = int(value)
    except (TypeError, ValueError) as exc:
        raise EloError("ELO_SCORE_UNVERIFIED:" + name) from exc
    if score < 0:
        raise EloError("ELO_SCORE_INVALID:" + name)
    return score


class EloRatings:
    """One sport's rating table. Market-free by construction."""

    def __init__(self, sport, *, k=None, hfa=None, mov=None, carryover=None,
                 init=INIT_RATING):
        if sport not in SPORT_PARAMS:
            raise EloError("ELO_SPORT_UNSUPPORTED:" + str(sport))
        params = SPORT_PARAMS[sport]
        self.sport = sport
        self.k = params["k"] if k is None else k
        self.hfa = params["hfa"] if hfa is None else hfa
        self.mov = params["mov"] if mov is None else mov
        self.carryover = (params["carryover"] if carryover is None
                          else carryover)
        self.init = float(init)
        for name, value in (("k", self.k), ("hfa", self.hfa),
                            ("carryover", self.carryover)):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise EloError("ELO_PARAM_INVALID:" + name)
        if not 0.0 <= self.carryover <= 1.0:
            raise EloError("ELO_PARAM_INVALID:carryover")
        self.ratings: dict[str, float] = {}
        self.n_games = 0
        self.season = None

    # -- core ----------------------------------------------------------
    def rating(self, team) -> float:
        key = canonical_team(team)
        if not key:
            raise EloError("ELO_TEAM_MISSING")
        return self.ratings.get(key, self.init)

    def expected_home(self, home, away, *, neutral=False) -> float:
        """Pre-game P(home win)."""
        hfa = 0.0 if neutral else self.hfa
        diff = self.rating(home) + hfa - self.rating(away)
        return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))

    def _mov_multiplier(self, mov, elo_diff) -> float:
        if not self.mov:
            return 1.0
        if mov == 0:
            return 1.0  # tie: no MOV signal, plain K update
        return math.log(abs(mov) + 1.0) * 2.2 / (0.001 * elo_diff + 2.2)

    def update_game(self, home, away, home_score, away_score, *,
                    season=None, neutral=False) -> dict:
        """Process one completed game. Returns diagnostics."""
        hs = _check_score(home_score, "home_score")
        aws = _check_score(away_score, "away_score")
        if season != self.season:
            self.regress_offseason()
            self.season = season
        hfa = 0.0 if neutral else self.hfa
        elo_h = self.rating(home)
        elo_a = self.rating(away)
        p_home = self.expected_home(home, away, neutral=neutral)
        if hs > aws:
            actual_h, mov = 1.0, hs - aws
            elo_diff = (elo_h + hfa) - elo_a
        elif aws > hs:
            actual_h, mov = 0.0, aws - hs
            elo_diff = (elo_a) - (elo_h + hfa)
        else:
            actual_h, mov = 0.5, 0
            elo_diff = 0.0
        mult = self._mov_multiplier(mov, elo_diff)
        delta = self.k * mult * (actual_h - p_home)
        key_h, key_a = canonical_team(home), canonical_team(away)
        self.ratings[key_h] = elo_h + delta
        self.ratings[key_a] = elo_a - delta
        self.n_games += 1
        return {"p_home_before": p_home, "mov_multiplier": mult,
                "delta": delta, "actual_home": actual_h}

    def regress_offseason(self):
        """Pull every rated team toward 1500 by (1 - carryover)."""
        for team, rating in self.ratings.items():
            self.ratings[team] = self.init + (rating - self.init) * self.carryover

    def prob_home(self, home, away, *, neutral=False) -> float:
        p = self.expected_home(home, away, neutral=neutral)
        if not 0.0 < p < 1.0:
            raise EloError("ELO_PROBABILITY_INVALID")
        return p


class EloBaseline:
    """Harness adapter: chronological, point-in-time Elo probabilities."""

    def __init__(self, sport):
        if sport not in SPORT_PARAMS:
            raise EloError("ELO_SPORT_UNSUPPORTED:" + str(sport))
        self.sport = sport

    def probability(self, train_games, home, away, as_of, *,
                    neutral=False) -> float:
        """P(home win) from games strictly before ``as_of``.

        ``train_games``: iterable of {kickoff, home_team, away_team,
        home_score, away_score, season (optional), neutral (optional)}.
        Only completed games may be passed; anything else is a caller bug
        and raises. No market data is read.
        """
        as_of_dt = parse_ts_utc(as_of)
        upcoming = []
        for game in train_games:
            if not isinstance(game, dict):
                raise EloError("ELO_GAME_NOT_OBJECT")
            kickoff = parse_ts_utc(game.get("kickoff"))
            if not kickoff < as_of_dt:
                # Point-in-time: games at/after as_of are simply not
                # learnable yet. (The splitter already guarantees train
                # precedes the test block; this filter enforces as_of.)
                continue
            for side in ("home_score", "away_score"):
                _check_score(game.get(side), side)
            upcoming.append((kickoff, game))
        upcoming.sort(key=lambda item: item[0])
        table = EloRatings(self.sport)
        for _, game in upcoming:
            table.update_game(
                game.get("home_team"), game.get("away_team"),
                game.get("home_score"), game.get("away_score"),
                season=game.get("season"),
                neutral=bool(game.get("neutral", False)))
        return table.prob_home(home, away, neutral=neutral)


def make_elo_price_fn(sport, games_by_fixture_id):
    """Runner-compatible price_fn for the model name ``"elo"`` (ML only).

    ``games_by_fixture_id``: fixture_id -> completed-game dict (kickoff,
    home_team, away_team, home_score, away_score, season?, neutral?).
    Fixtures must carry ``home_team``/``away_team`` (and optionally
    ``neutral``).
    """
    adapter = EloBaseline(sport)

    def price_fn(model_name, fixture, as_of, train):
        if model_name != "elo":
            raise EloError("ELO_PRICE_FN_WRONG_MODEL:" + str(model_name))
        if not isinstance(fixture, dict):
            raise EloError("ELO_FIXTURE_NOT_OBJECT")
        home = fixture.get("home_team")
        away = fixture.get("away_team")
        if not home or not away:
            raise EloError("ELO_FIXTURE_TEAMS_REQUIRED")
        train_games = []
        for tr in train:
            if not isinstance(tr, dict):
                raise EloError("ELO_TRAIN_FIXTURE_NOT_OBJECT")
            game = games_by_fixture_id.get(tr.get("fixture_id"))
            if game is None:
                raise EloError("ELO_TRAIN_GAME_MISSING:" +
                               str(tr.get("fixture_id")))
            train_games.append(game)
        p = adapter.probability(train_games, home, away, as_of,
                                neutral=bool(fixture.get("neutral", False)))
        return [{"market": "ML", "selection": "HOME", "model_p": p},
                {"market": "ML", "selection": "AWAY", "model_p": 1.0 - p}]

    return price_fn


def naive_price_fn(model_name, fixture, as_of, train):
    """Coin-flip floor (ML 0.5/0.5) for the model name ``"naive"``."""
    if model_name != "naive":
        raise EloError("ELO_PRICE_FN_WRONG_MODEL:" + str(model_name))
    return [{"market": "ML", "selection": "HOME", "model_p": 0.5},
            {"market": "ML", "selection": "AWAY", "model_p": 0.5}]
