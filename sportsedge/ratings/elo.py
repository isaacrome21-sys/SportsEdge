"""Per-sport Elo rating engine with strict no-lookahead semantics.

The core invariant: the rating used for game N may only reflect games
played strictly BEFORE game N. This is enforced structurally:

* ``record_game`` requires non-decreasing timestamps (out-of-order games
  raise; the tracker cannot be silently rewound).
* ``rating_at(team, as_of)`` only reflects games with ``date < as_of``.
* No-lookahead unit tests live in ``tests/test_ratings.py`` and assert this
  invariant directly (a game recorded later must not change a rating
  queried at an earlier ``as_of``).

Update math (standard Elo, neutral-site ratings):
* expected = 1 / (1 + 10 ** (-(r_team - r_opp) / scale))
* K_eff = K * mov_multiplier(margin, pre_diff)
* r_new = r_old + K_eff * (score - expected), score in {1, 0}
  (ties split 0.5 each; NFL ties are the only realistic case).

Home-field advantage is deliberately NOT part of the update: ratings are
neutral-site quality estimates. HFA is a separate declared layer applied
when score means are built (see ``sportsedge.ratings.layers``).

Margin-of-victory handling: the FiveThirtyEight NFL multiplier, with each
sport's margin and pre-game diff normalized into NFL-scale units via
``margin_sd`` (see ``params.MOV_FORMULA``). Blowouts move ratings more,
expected blowouts move them less. Documented, not invented.
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import datetime
from math import isfinite
from typing import Any, Iterable, Mapping

from . import params


class EloError(ValueError):
    """Fail-closed rating errors; never silently produce a rating."""


def _clock(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            result = datetime.fromisoformat(text)
        except ValueError as exc:
            raise EloError(name + "_UNPARSEABLE") from exc
    else:
        raise EloError(name + "_TYPE_INVALID")
    if result.tzinfo is None:
        # Naive clocks are ambiguous; treat as UTC rather than guessing.
        from datetime import timezone
        result = result.replace(tzinfo=timezone.utc)
    return result


def _key(name: Any) -> str:
    text = str(name or "").strip().lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch == " ")
    return " ".join(text.split())


def mov_multiplier(margin: float, pre_diff: float, sport: str) -> float:
    """FiveThirtyEight NFL MOV multiplier, normalized to NFL-scale units.

    ``margin`` is the winner's score margin (positive), ``pre_diff`` the
    winner's pre-game rating minus the loser's. Both are divided by the
    sport's ``margin_sd`` and multiplied by the NFL ``margin_sd`` so the
    538 NFL-calibrated constants apply uniformly across sports.
    """
    margin_sd = params.get(sport, "margin_sd")
    nfl_sd = params.ELO["NFL"]["margin_sd"]["value"]
    mov_nfl = abs(float(margin)) * nfl_sd / margin_sd
    diff_nfl = abs(float(pre_diff)) * nfl_sd / margin_sd
    mult = ((mov_nfl + 3.0) ** 0.8) / (7.45 + 0.006 * diff_nfl)
    if not isfinite(mult) or mult <= 0:
        raise EloError("MOV_MULTIPLIER_INVALID")
    return mult


def expected_score(rating_a: float, rating_b: float, sport: str) -> float:
    """Neutral-site win probability of A over B (no HFA in the rating)."""
    scale = params.get(sport, "scale")
    return 1.0 / (1.0 + 10.0 ** (-(rating_a - rating_b) / scale))


class EloTracker:
    """Chronological Elo ratings for one sport.

    Games must be recorded in non-decreasing timestamp order. Querying a
    rating at ``as_of`` sees only games with ``date < as_of``.
    """

    def __init__(self, sport: str):
        self.sport = str(sport or "").upper().strip()
        if self.sport not in params.SPORTS:
            raise EloError("RATINGS_SPORT_UNSUPPORTED:" + self.sport)
        self.k = params.get(self.sport, "k")
        self.init = params.get(self.sport, "init")
        # Per team: parallel lists of (date, rating_after_game, season).
        self._dates: dict[str, list[datetime]] = {}
        self._ratings: dict[str, list[float]] = {}
        self._seasons: dict[str, list[str]] = {}
        self._last_date: datetime | None = None
        self._games_recorded = 0

    # -- recording ----------------------------------------------------

    def record_game(self, *, date: Any, home: str, away: str,
                    home_score: int, away_score: int,
                    season: str | None = None) -> dict[str, float]:
        """Record a completed game; returns the post-game ratings.

        ``season`` labels the campaign (e.g. "2024"). When a team's season
        label changes, its rating first regresses toward the mean by
        ``SEASON_REGRESS`` before the update is applied (declared
        carryover convention).
        """
        when = _clock(date, "GAME_DATE")
        if self._last_date is not None and when < self._last_date:
            raise EloError(
                "GAME_OUT_OF_ORDER:no-lookahead requires non-decreasing dates")
        hk, ak = _key(home), _key(away)
        if not hk or not ak:
            raise EloError("GAME_TEAM_IDENTITY_MISSING")
        if hk == ak:
            raise EloError("GAME_TEAMS_IDENTICAL")
        try:
            hs, aws = int(home_score), int(away_score)
        except (TypeError, ValueError) as exc:
            raise EloError("GAME_SCORES_UNVERIFIED") from exc
        if hs < 0 or aws < 0:
            raise EloError("GAME_SCORES_NEGATIVE")

        season = str(season or "").strip() or None
        r_home = self._current(hk, season)
        r_away = self._current(ak, season)
        pre_diff = r_home - r_away

        if hs > aws:
            s_home, s_away, margin, w_diff = 1.0, 0.0, hs - aws, pre_diff
        elif aws > hs:
            s_home, s_away, margin, w_diff = 0.0, 1.0, aws - hs, -pre_diff
        else:
            s_home = s_away = 0.5
            margin, w_diff = 0.0, pre_diff

        mult = mov_multiplier(margin, w_diff, self.sport)
        k_eff = self.k * mult
        exp_home = expected_score(r_home, r_away, self.sport)
        new_home = r_home + k_eff * (s_home - exp_home)
        new_away = r_away + k_eff * (s_away - (1.0 - exp_home))

        self._append(hk, when, new_home, season)
        self._append(ak, when, new_away, season)
        self._last_date = when
        self._games_recorded += 1
        return {"home": new_home, "away": new_away,
                "k_eff": k_eff, "mov_mult": mult}

    def _current(self, team_key: str, season: str | None) -> float:
        ratings = self._ratings.get(team_key)
        if not ratings:
            return self.init
        last_season = self._seasons[team_key][-1]
        if season is not None and last_season != season:
            regress = params.SEASON_REGRESS["value"]
            return ratings[-1] + regress * (self.init - ratings[-1])
        return ratings[-1]

    def _append(self, team_key: str, when: datetime, rating: float,
                season: str | None) -> None:
        if not isfinite(rating):
            raise EloError("RATING_NONFINITE")
        self._dates.setdefault(team_key, []).append(when)
        self._ratings.setdefault(team_key, []).append(rating)
        prev = self._seasons.get(team_key, [season or ""])
        self._seasons.setdefault(team_key, []).append(season or prev[-1])

    # -- querying (no-lookahead) ---------------------------------------

    def rating_at(self, team: str, as_of: Any) -> tuple[float, int]:
        """Rating reflecting only games with date < as_of.

        Returns (rating, games_counted). Unknown teams return the init
        rating with count 0 (callers decide whether that is usable).
        """
        key = _key(team)
        if not key:
            raise EloError("TEAM_IDENTITY_MISSING")
        when = _clock(as_of, "AS_OF")
        dates = self._dates.get(key)
        if not dates:
            return self.init, 0
        # bisect_left on (date < when): index of first date >= when.
        idx = bisect_left(dates, when)
        if idx == 0:
            return self.init, 0
        return self._ratings[key][idx - 1], idx

    def teams(self) -> list[str]:
        return sorted(self._ratings)

    @property
    def games_recorded(self) -> int:
        return self._games_recorded

    # -- persistence ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "sport": self.sport,
            "games_recorded": self._games_recorded,
            "last_date": self._last_date.isoformat() if self._last_date else None,
            "teams": {
                team: {
                    "dates": [d.isoformat() for d in self._dates[team]],
                    "ratings": list(self._ratings[team]),
                    "seasons": list(self._seasons[team]),
                }
                for team in self._ratings
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EloTracker":
        if not isinstance(data, Mapping):
            raise EloError("TRACKER_DATA_INVALID")
        try:
            tracker = cls(data["sport"])
        except KeyError as exc:
            raise EloError("TRACKER_SPORT_MISSING") from exc
        teams = data.get("teams")
        if not isinstance(teams, dict):
            raise EloError("TRACKER_TEAMS_INVALID")
        for team, blob in teams.items():
            key = _key(team)
            if not key or key in tracker._dates:
                raise EloError("TRACKER_TEAM_INVALID_OR_DUPLICATE:" + key)
            if not isinstance(blob, Mapping):
                raise EloError("TRACKER_HISTORY_INVALID:" + key)
            if any(not isinstance(blob.get(field, []), (list, tuple))
                   for field in ("dates", "ratings", "seasons")):
                raise EloError("TRACKER_HISTORY_INVALID:" + key)
            dates = [_clock(d, "TRACKER_DATE") for d in blob.get("dates", [])]
            raw_ratings = blob.get("ratings", [])
            try:
                ratings = [float(r) for r in raw_ratings]
            except (TypeError, ValueError, OverflowError) as exc:
                raise EloError("TRACKER_RATING_INVALID:" + key) from exc
            if any(isinstance(r, bool) for r in raw_ratings) or any(
                    not isfinite(r) for r in ratings):
                raise EloError("TRACKER_RATING_INVALID:" + key)
            seasons = [str(s) for s in blob.get("seasons", [])]
            if not (len(dates) == len(ratings) == len(seasons)):
                raise EloError("TRACKER_HISTORY_MISMATCH:" + key)
            if any(b < a for a, b in zip(dates, dates[1:])):
                raise EloError("TRACKER_DATES_OUT_OF_ORDER:" + key)
            tracker._dates[key] = dates
            tracker._ratings[key] = ratings
            tracker._seasons[key] = seasons
            if dates:
                last = dates[-1]
                if tracker._last_date is None or last > tracker._last_date:
                    tracker._last_date = last
        tracker._games_recorded = int(data.get("games_recorded", 0))
        return tracker
