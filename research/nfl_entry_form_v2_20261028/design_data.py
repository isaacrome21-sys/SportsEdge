"""Shared design-data loading for the NFL_ENTRY_FORM_V2 build scripts.

DESIGN DATA ONLY (2020-2025): data already seen by retired constructions;
zero validation credit (standing law). Loads exactly the pinned inputs in
``PINS.json`` beside this file — the nflverse games file (PR #2831 pin)
and the weekly team/player parquets (sha256-verified before use; a
mismatch refuses) — and walks them with the construction module's own
books (``sportsedge.nfl_entry_form_v2``), so the build-stage fit and the
landing check share ONE feature implementation with the priced path.
2026 rows are never loaded (PINS/design scope): the 2026 remainder is
the preregistration draft's reserved validation split.
"""
import gzip
import hashlib
import json
import math
import os
import urllib.request

import pandas as pd

from sportsedge.nfl_entry_form_v2 import (
    EPABooks, GameContext, QBBook, QBWeekLine, TeamWeekLine, build_features,
)

HERE = os.path.dirname(os.path.abspath(__file__))
SEASONS = [2020, 2021, 2022, 2023, 2024, 2025]
RELEASE_URL = "https://github.com/nflverse/nflverse-data/releases/download/{tag}/{name}"

with open(os.path.join(HERE, "PINS.json")) as fh:
    PINS = json.load(fh)
GAMES_SHA256 = PINS["games_csv_gz"]["sha256"]
PARQUET_PINS = {name: spec["sha256"]
                for name, spec in PINS["weekly_parquets"].items()}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_parquets(data_dir):
    os.makedirs(data_dir, exist_ok=True)
    for name, pin in PARQUET_PINS.items():
        path = os.path.join(data_dir, name)
        if not os.path.exists(path):
            tag = "stats_team" if name.startswith("stats_team") else "stats_player"
            urllib.request.urlretrieve(RELEASE_URL.format(tag=tag, name=name), path)
        got = sha256_file(path)
        if got != pin:
            raise SystemExit(f"PIN MISMATCH {name}: got {got}, want {pin} — refusing")


def load_games(path):
    if sha256_file(path) != GAMES_SHA256:
        raise SystemExit("games.csv.gz sha256 does not match the PR #2831 pin — refusing")
    with gzip.open(path, "rt") as fh:
        g = pd.read_csv(fh)
    g = g[(g.game_type == "REG") & g.season.isin(SEASONS)]
    g = g.dropna(subset=["spread_line", "total_line", "home_score", "away_score"])
    return g.sort_values(["season", "week", "gameday"]).reset_index(drop=True)


def load_team_week(data_dir):
    frames = []
    for s in SEASONS:
        df = pd.read_parquet(os.path.join(data_dir, f"stats_team_week_{s}.parquet"))
        frames.append(df[df.season_type == "REG"].copy())
    tw = pd.concat(frames, ignore_index=True)
    by_game = {}
    for row in tw.itertuples(index=False):
        by_game.setdefault(row.game_id, {})[row.team] = TeamWeekLine(
            team=row.team, passing_epa=row.passing_epa, rushing_epa=row.rushing_epa,
            attempts=row.attempts, sacks_suffered=row.sacks_suffered,
            carries=row.carries)
    return by_game


def _isnan(x):
    return isinstance(x, float) and math.isnan(x)


def load_qb_week(data_dir):
    frames = []
    for s in SEASONS:
        df = pd.read_parquet(os.path.join(data_dir, f"stats_player_week_{s}.parquet"))
        frames.append(df[df.position == "QB"].copy())
    qw = pd.concat(frames, ignore_index=True)
    by_key = {}
    for row in qw.itertuples(index=False):
        by_key.setdefault((row.season, row.week, row.team), []).append(QBWeekLine(
            player_id=row.player_id, attempts=row.attempts,
            passing_epa=(row.passing_epa if not _isnan(row.passing_epa) else 0.0),
            rushing_epa=(row.rushing_epa if not _isnan(row.rushing_epa) else 0.0)))
    return by_key


def _num(x, default):
    return default if x is None or _isnan(x) else float(x)


def _starter(x):
    if x is None or _isnan(x):
        return None
    return str(x)


def game_context(gm) -> GameContext:
    """Pricing-time context for a design-data game. Starter identity comes
    from the games file's recorded starters — post-hoc identity, the
    plan's named leak class (SCREEN_RESULTS §3); fit/landing use only,
    never a forward input."""
    return GameContext(
        game_id=gm.game_id, home_team=gm.home_team, away_team=gm.away_team,
        home_rest=_num(gm.home_rest, 0.0), away_rest=_num(gm.away_rest, 0.0),
        roof="" if _isnan(gm.roof) else str(gm.roof),
        wind=_num(gm.wind, 0.0), temp=_num(gm.temp, 55.0),
        home_starter_id=_starter(gm.home_qb_id),
        away_starter_id=_starter(gm.away_qb_id),
        home_starter_known=_starter(gm.home_qb_id) is not None,
        away_starter_known=_starter(gm.away_qb_id) is not None)


class DesignWalk:
    """Walks design games in order with the construction's books. Each
    ``step`` computes the game's features from the books' CURRENT state
    (prior games only) and only then ingests the game — the design
    screen's walk-forward discipline, shared by every build script."""

    def __init__(self, games, tw_by_game, qw_by_key):
        self.books = EPABooks()
        self.qb_book = QBBook()
        self._rows = list(games.itertuples(index=False))
        self._tw = tw_by_game
        self._qw = qw_by_key
        self._i = 0
        self._cur_season = None
        self._prior_final = {}
        self._qb_carry = {}

    def peek(self):
        return self._rows[self._i] if self._i < len(self._rows) else None

    def step(self):
        gm = self.peek()
        if gm is None:
            return None
        self._i += 1
        if gm.season != self._cur_season:
            if self._cur_season is not None:
                self._prior_final = self.books.final()
                self._qb_carry = self.qb_book.final_qb()
            self.books.roll_season(self._prior_final)
            self.qb_book.roll_season(self._qb_carry)
            self._cur_season = gm.season
        ctx = game_context(gm)
        feat = build_features(self.books, self.qb_book, ctx)
        rows = self._tw.get(gm.game_id, {})
        home_line = rows.get(gm.home_team)
        away_line = rows.get(gm.away_team)
        if home_line is None or away_line is None:
            raise SystemExit(f"team-week rows missing for {gm.game_id} — refusing")
        self.books.add_game(home_line, away_line)
        self.qb_book.add_game(gm.home_team,
                              self._qw.get((gm.season, gm.week, gm.home_team), []))
        self.qb_book.add_game(gm.away_team,
                              self._qw.get((gm.season, gm.week, gm.away_team), []))
        return gm, feat, ctx

    def run_until(self, stop_pred):
        """Step while the next game does NOT satisfy ``stop_pred``;
        leaves the books at the state strictly before that game."""
        while True:
            gm = self.peek()
            if gm is None or stop_pred(gm):
                return
            self.step()


def default_games_path():
    return os.path.join(HERE, "..", "nfl_cfb_design_baselines_20261027",
                        "nflverse_games.csv.gz")


def default_data_dir():
    return os.path.join(HERE, "data")
