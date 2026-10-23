"""NFL team defense count research engine (Grok lane, SCREEN only).

Families: TEAM_SACKS (sacks recorded by the team's defense) and
TEAM_TURNOVERS (interceptions thrown + fumbles lost by the team's offense).

Inputs: per-team-game rows built from the official nflverse
play_by_play_{season}.csv.gz releases already on the box, hashed in
research/grok_nfl_team_defense_counts_screen_20261023/SOURCES.json.  No
quotes, no market inputs, no EV.  Point-in-time: only games dated strictly
before the priced game are used.

Construction (declared a priori, nothing fitted):
  rate     per-game count for the team (sacks made / giveaways) and the
           count its opponents concede (sacks allowed / takeaways), current
           season weight 1 + previous season weight PREV_W, shrunk toward
           the league mean with SHRINK_G pseudo-games.
  lambda   L * (team / L) * (opponent / L).
  pmf      Poisson(lambda) on 0..MAX_COUNT, tail folded into MAX_COUNT.
Fail-closed: unknown family, malformed rows, < MIN_TEAM_GAMES history, empty
pool, non-finite values or bool/str lines raise NflTeamDefenseError.

Governance: SCREEN, NOT_VALIDATED, eligible=false, play_allowed=false.
Research only.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

ENGINE_ID = "NFL_TEAM_DEFENSE_COUNTS_EMPIRICAL"
ENGINE_VERSION = "nfl_team_defense_counts_empirical_v1_20261023"
GOVERNANCE = {"state": "SCREEN", "validation_status": "NOT_VALIDATED",
              "eligible": False, "play_allowed": False}
FAMILIES = {"TEAM_SACKS": "sacks", "TEAM_TURNOVERS": "turnovers"}
PREV_W = 0.5
SHRINK_G = 6.0
MIN_TEAM_GAMES = 3
MAX_COUNT = 15


class NflTeamDefenseError(ValueError):
    pass


def _date(v, what):
    if not isinstance(v, str) or len(v) != 10 or v[4] != "-" or v[7] != "-":
        raise NflTeamDefenseError(f"{what}_DATE_INVALID")
    return v


def _rows(history, key):
    out = []
    for r in history:
        try:
            v = r[key]
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise NflTeamDefenseError("MALFORMED_COUNT")
            out.append((_date(r["date"], "HISTORY"), int(r["season"]), r["team"], r["opp"], v))
        except KeyError as e:
            raise NflTeamDefenseError(f"HISTORY_FIELD_MISSING:{e.args[0]}") from None
        except (TypeError, ValueError) as e:
            if isinstance(e, NflTeamDefenseError):
                raise
            raise NflTeamDefenseError("HISTORY_ROW_MALFORMED") from None
    return out


def poisson_pmf(lam: float) -> list:
    if not (lam > 0 and math.isfinite(lam)):
        raise NflTeamDefenseError("DEGENERATE_LAMBDA")
    p = [math.exp(-lam)]
    for k in range(1, MAX_COUNT + 1):
        p.append(p[-1] * lam / k)
    p[-1] += max(0.0, 1.0 - math.fsum(p))
    return p


def price_team_count(history: Iterable[Mapping[str, Any]], *, family: str, date: str,
                     season: int, team: str, opp: str) -> dict:
    if family not in FAMILIES:
        raise NflTeamDefenseError(f"UNKNOWN_FAMILY:{family}")
    if isinstance(season, bool) or not isinstance(season, int):
        raise NflTeamDefenseError("SEASON_REQUIRED_INT")
    _date(date, "GAME")
    if not isinstance(team, str) or not isinstance(opp, str) or not team or team == opp:
        raise NflTeamDefenseError("TEAMS_INVALID")
    rows = [r for r in _rows(history, FAMILIES[family])
            if r[0] < date and r[1] in (season, season - 1)]
    if not rows:
        raise NflTeamDefenseError("EMPTY_LEAGUE_POOL")
    L = sum(r[4] for r in rows) / len(rows)
    if not L > 0:
        raise NflTeamDefenseError("DEGENERATE_LEAGUE_MEAN")

    def rate(who, col):
        s = w = 0.0
        for r in rows:
            if r[col] == who:
                wt = 1.0 if r[1] == season else PREV_W
                s += wt * r[4]; w += wt
        if w < MIN_TEAM_GAMES * PREV_W:
            raise NflTeamDefenseError(f"TEAM_HISTORY_INSUFFICIENT:{who}")
        return (s + SHRINK_G * L) / (w + SHRINK_G)

    if family == "TEAM_SACKS":
        # row team = defense making sacks; opp = offense conceding them
        t, o = rate(team, 2), rate(opp, 3)
    else:
        # row team = offense giving the ball away; opp = defense taking it
        t, o = rate(team, 2), rate(opp, 3)
    lam = L * (t / L) * (o / L)
    return {"engine_id": ENGINE_ID, "engine_version": ENGINE_VERSION, "family": family,
            "lambda": lam, "pmf": poisson_pmf(lam), "governance": dict(GOVERNANCE)}


def over_under(priced: dict, line) -> dict:
    if isinstance(line, bool) or not isinstance(line, (int, float)) or not math.isfinite(line):
        raise NflTeamDefenseError("LINE_REQUIRED_FINITE_NUMBER")
    if abs(line * 2 - round(line * 2)) > 1e-9 or line < 0:
        raise NflTeamDefenseError("LINE_NOT_HALF_POINT")
    pmf = priced["pmf"]
    return {"over": math.fsum(p for k, p in enumerate(pmf) if k > line),
            "push": math.fsum(p for k, p in enumerate(pmf) if k == line),
            "under": math.fsum(p for k, p in enumerate(pmf) if k < line)}
