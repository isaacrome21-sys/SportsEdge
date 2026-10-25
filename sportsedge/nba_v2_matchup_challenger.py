"""NBA v2 matchup challenger (research only, NOT wired to production).

Point-in-time, matchup-driven feature engine for NBA games:
  * offense-vs-defense efficiency matchup (rolling EWMA, shrunk to league)
  * pace-vs-pace expected possessions (totals)
  * rest / back-to-back / 3-in-4 / travel distance
  * player availability: minutes-weighted, impact-weighted missing players
  * home court (regression intercept)

Clock rule: every rating input comes from games on strictly earlier calendar
dates. The only same-day input is the availability status of each player for
the game itself, taken ONLY from pregame-knowable box-score codes:
  DND (did not dress = league inactive list, filed before tip),
  NWT (not with team), and players absent from the box while still on the
  roster in the team's last game. "DNP - Coach's Decision" and "DNP - Injury"
  (decided in-game) are treated as AVAILABLE and never used.

Nothing in production imports this module. No thresholds, promotion state or
production model math are touched.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

# Arena coordinates (lat, lon) by tricode; relocated franchises share an entry.
ARENAS = {
    "ATL": (33.757, -84.396), "BOS": (42.366, -71.062), "BKN": (40.683, -73.976),
    "NJN": (40.734, -74.171), "CHA": (35.225, -80.839), "CHI": (41.881, -87.674),
    "CLE": (41.497, -81.688), "DAL": (32.790, -96.810), "DEN": (39.749, -105.008),
    "DET": (42.341, -83.055), "GSW": (37.768, -122.388), "HOU": (29.751, -95.362),
    "IND": (39.764, -86.156), "LAC": (34.043, -118.267), "LAL": (34.043, -118.267),
    "MEM": (35.138, -90.051), "MIA": (25.781, -80.188), "MIL": (43.045, -87.917),
    "MIN": (44.979, -93.276), "NOH": (29.949, -90.082), "NOP": (29.949, -90.082),
    "NYK": (40.751, -73.993), "OKC": (35.463, -97.515), "ORL": (28.539, -81.384),
    "PHI": (39.901, -75.172), "PHX": (33.446, -112.071), "POR": (45.532, -122.667),
    "SAC": (38.580, -121.500), "SAS": (29.427, -98.438), "TOR": (43.643, -79.379),
    "UTA": (40.768, -111.901), "WAS": (38.898, -77.021),
}
GSW_OAKLAND = (37.750, -122.203)  # Oracle Arena before 2019-20

INACTIVE_PREFIXES = ("DND", "NWT")
EWMA_DECAY = 0.94          # per team game
SEASON_CARRY = 0.67        # keep 2/3 of last season's deviation
PLAYER_DECAY = 0.97
PLAYER_SHRINK_MIN = 600.0  # minutes of prior toward 0 impact
ROTATION_MIN = 12.0        # expected minutes to count as a rotation player
ABSENCE_DAYS = 21          # absent-from-box players count as out this long


def haversine_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def arena(tri, season_start_year):
    if tri == "GSW" and season_start_year < 2019:
        return GSW_OAKLAND
    return ARENAS[tri]


def day_ordinal(iso):
    from datetime import date
    y, m, d = (int(x) for x in iso[:10].split("-"))
    return date(y, m, d).toordinal()


@dataclass
class TeamState:
    o: float = 0.0       # offensive pts/100 deviation from league
    d: float = 0.0       # defensive pts/100 allowed deviation from league
    pace: float = 0.0    # possessions deviation from league
    w: float = 0.0       # effective sample weight this season
    season: int | None = None
    dates: list = field(default_factory=list)
    loc: tuple | None = None
    roster_last: set = field(default_factory=set)


@dataclass
class PlayerState:
    expmin: float = 0.0
    wmin: float = 0.0
    rel_pm: float = 0.0     # decayed sum of on-court margin vs team, pts
    rel_min: float = 0.0    # decayed minutes for rel_pm
    team: str | None = None
    last_day: int = -10**9


class MatchupEngine:
    """Feed games in date order: features(game) for all games of a date first,
    then update(game_result) for all games of that date."""

    def __init__(self):
        self.teams = defaultdict(TeamState)
        self.players = defaultdict(PlayerState)
        self.lg_ppp = 1.06   # pts per possession
        self.lg_pace = 95.0
        self.max_input_day = -10**9

    # ---------------- pregame features ----------------
    def _team_pre(self, tri, season):
        t = self.teams[tri]
        if t.season is not None and t.season != season:
            t.o *= SEASON_CARRY; t.d *= SEASON_CARRY; t.pace *= SEASON_CARRY
            t.w = 0.0; t.season = season
        return t

    def _rest(self, t, day, here, season):
        prev = [x for x in t.dates if x < day]
        last = prev[-1] if prev else None
        rest = min(day - last - 1, 3) if last is not None else 3
        b2b = int(last is not None and day - last == 1)
        three_in_four = int(sum(1 for x in prev if day - x <= 3) >= 2)
        travel = haversine_km(t.loc, here) / 1000.0 if (t.loc is not None and last is not None and day - last <= 3) else 0.0
        return rest, b2b, three_in_four, travel

    def _availability(self, tri, day, inactive, active):
        """inactive/active: sets of personIds for THIS game (pregame-knowable)."""
        miss_val = miss_min = 0.0
        for pid, p in self.players.items():
            if p.team != tri or p.expmin < ROTATION_MIN:
                continue
            out = pid in inactive or (pid not in active and day - p.last_day <= ABSENCE_DAYS)
            if not out:
                continue
            val = 48.0 * p.rel_pm / (p.rel_min + PLAYER_SHRINK_MIN)
            miss_val += val * p.expmin / 48.0
            miss_min += p.expmin / 240.0
        return miss_val, miss_min

    def features(self, g):
        """g: dict(day, season, home, away, inactive_home, inactive_away,
        active_home, active_away). Returns a feature dict."""
        day, s = g["day"], g["season"]
        th, ta = self._team_pre(g["home"], s), self._team_pre(g["away"], s)
        here = arena(g["home"], s)
        pace = self.lg_pace + th.pace + ta.pace
        h_ppp = self.lg_ppp * 100 + th.o + ta.d     # home pts/100 vs this defense
        a_ppp = self.lg_ppp * 100 + ta.o + th.d
        rh, bh, th3, trh = self._rest(th, day, here, s)
        ra, ba, ta3, tra = self._rest(ta, day, here, s)
        mvh, mmh = self._availability(g["home"], day, g["inactive_home"], g["active_home"])
        mva, mma = self._availability(g["away"], day, g["inactive_away"], g["active_away"])
        return {
            "matchup_margin": (h_ppp - a_ppp) * pace / 100.0,
            "matchup_total": (h_ppp + a_ppp) * pace / 100.0,
            "pace_exp": pace, "rating_weight": min(th.w, ta.w),
            "rest_diff": rh - ra, "b2b_diff": bh - ba, "b2b_sum": bh + ba,
            "three4_diff": th3 - ta3, "travel_diff": trh - tra, "travel_sum": trh + tra,
            "miss_val_diff": mvh - mva, "miss_min_diff": mmh - mma,
            "miss_val_sum": mvh + mva, "miss_min_sum": mmh + mma,
            "max_rating_input_day": self.max_input_day,
        }

    # ---------------- postgame update ----------------
    def update(self, r):
        """r: dict(day, season, home, away, poss_home, poss_away, pts_home,
        pts_away, players_home, players_away) where players_* = list of
        (personId, minutes, plus_minus)."""
        poss = 0.5 * (r["poss_home"] + r["poss_away"])
        if poss <= 50:
            return
        here = arena(r["home"], r["season"])
        lg100 = self.lg_ppp * 100
        for tri, opp, pf, pa, plist in ((r["home"], r["away"], r["pts_home"], r["pts_away"], r["players_home"]),
                                         (r["away"], r["home"], r["pts_away"], r["pts_home"], r["players_away"])):
            t, o = self.teams[tri], self.teams[opp]
            t.season = r["season"]
            off = 100 * pf / poss - lg100 - o.d          # opponent-adjusted
            de = 100 * pa / poss - lg100 - o.o
            pc = poss - self.lg_pace - o.pace
            a = 1 - EWMA_DECAY
            t.o += a * (off - t.o); t.d += a * (de - t.d); t.pace += a * (pc - t.pace)
            t.w = t.w * EWMA_DECAY + 1
            t.dates.append(r["day"]); t.loc = here
            margin = pf - pa
            t.roster_last = set()
            for pid, mins, pm in plist:
                p = self.players[pid]
                if p.team != tri:
                    p.expmin *= 0.5 if p.team else 0.0
                p.team = tri; p.last_day = r["day"]
                if mins > 0:
                    p.expmin = PLAYER_DECAY * p.expmin + (1 - PLAYER_DECAY) * mins if p.wmin > 0 else mins
                    p.wmin += 1
                    p.rel_pm = PLAYER_DECAY * p.rel_pm + (pm - margin * mins / 48.0)
                    p.rel_min = PLAYER_DECAY * p.rel_min + mins
                    t.roster_last.add(pid)
        self.lg_ppp += 0.002 * ((r["pts_home"] + r["pts_away"]) / (2 * poss) - self.lg_ppp)
        self.lg_pace += 0.002 * (poss - self.lg_pace)
        self.max_input_day = max(self.max_input_day, r["day"])


# ---------------- model (linear, walk-forward fit) ----------------
SPECS = {
    # attempt id -> (margin feature list, total feature list)
    "A1_matchup": (["matchup_margin"], ["matchup_total"]),
    "A2_matchup_rest": (["matchup_margin", "rest_diff", "b2b_diff", "three4_diff", "travel_diff"],
                        ["matchup_total", "b2b_sum", "travel_sum"]),
    "A3_full": (["matchup_margin", "rest_diff", "b2b_diff", "three4_diff", "travel_diff",
                 "miss_val_diff", "miss_min_diff"],
                ["matchup_total", "b2b_sum", "travel_sum", "miss_val_sum", "miss_min_sum"]),
}


def fit_ols(X, y, ridge=1.0):
    X = np.column_stack([np.ones(len(X)), np.asarray(X, float)])
    I = np.eye(X.shape[1]); I[0, 0] = 0
    beta = np.linalg.solve(X.T @ X + ridge * I, X.T @ np.asarray(y, float))
    resid = np.asarray(y, float) - X @ beta
    return beta, float(np.sqrt(np.mean(resid ** 2) * len(y) / max(len(y) - X.shape[1], 1)))


def predict(beta, x):
    return float(beta[0] + np.dot(beta[1:], x))


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))
