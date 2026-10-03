"""Price NHL ML / puck line / totals from the frozen rate v1 owner."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from sportsedge.sports.nhl.rate_model import NHLRateParameters

FREEZE_PATH = Path(__file__).resolve().parents[1] / "artifacts" / "nhl" / "nhl_rate_v1_freeze.json"

PRIORS_BY_ABBREV = {
    "ANA": (3.329268, 3.512195, 30.804878, 28.365854),
    "BOS": (3.317073, 3.048780, 27.024390, 29.695122),
    "BUF": (3.512195, 2.939024, 28.121951, 29.060976),
    "CAR": (3.609756, 2.926829, 32.158537, 23.926829),
    "CBJ": (3.085366, 3.085366, 29.390244, 28.841463),
    "CGY": (2.585366, 3.158537, 28.109756, 29.914634),
    "CHI": (2.597561, 3.353659, 24.585366, 29.963415),
    "COL": (3.682927, 2.475610, 33.731707, 26.134146),
    "DAL": (3.402439, 2.756098, 25.292683, 26.158537),
    "DET": (2.939024, 3.146341, 28.243902, 27.743902),
    "EDM": (3.439024, 3.280488, 29.743902, 26.707317),
    "FLA": (3.060976, 3.365854, 27.987805, 26.792683),
    "LAK": (2.743902, 3.012195, 28.012195, 27.170732),
    "MIN": (3.317073, 2.926829, 29.182927, 29.402439),
    "MTL": (3.451220, 3.121951, 26.292683, 27.829268),
    "NJD": (2.804878, 3.097561, 29.585366, 27.365854),
    "NSH": (3.012195, 3.280488, 27.865854, 29.621951),
    "NYI": (2.841463, 2.939024, 28.170732, 27.695122),
    "NYR": (2.902439, 3.048780, 25.195122, 28.829268),
    "OTT": (3.390244, 3.000000, 28.914634, 24.402439),
    "PHI": (3.048780, 2.963415, 25.463415, 25.451220),
    "PIT": (3.573171, 3.268293, 28.573171, 27.365854),
    "SEA": (2.756098, 3.207317, 25.585366, 29.451220),
    "SJS": (3.060976, 3.560976, 25.756098, 29.646341),
    "STL": (2.817073, 3.146341, 25.329268, 27.707317),
    "TBL": (3.536585, 2.817073, 28.109756, 26.695122),
    "TOR": (3.085366, 3.646341, 26.329268, 32.439024),
    "UTA": (3.268293, 2.926829, 27.707317, 26.146341),
    "VAN": (2.634146, 3.853659, 25.963415, 29.817073),
    "VGK": (3.231707, 3.048780, 28.987805, 24.390244),
    "WPG": (2.817073, 3.170732, 26.365854, 27.768293),
    "WSH": (3.207317, 2.975610, 28.048780, 28.134146),
}

ALIASES = {
    "RANGERS": "NYR", "NY RANGERS": "NYR", "NEW YORK RANGERS": "NYR",
    "BRUINS": "BOS", "BOSTON": "BOS",
    "MAPLE LEAFS": "TOR", "LEAFS": "TOR", "TORONTO": "TOR",
    "CANADIENS": "MTL", "HABS": "MTL", "MONTREAL": "MTL",
    "SENATORS": "OTT", "OTTAWA": "OTT",
    "SABRES": "BUF", "BUFFALO": "BUF",
    "RED WINGS": "DET", "DETROIT": "DET",
    "PANTHERS": "FLA", "FLORIDA": "FLA",
    "LIGHTNING": "TBL", "TAMPA": "TBL", "TAMPA BAY": "TBL",
    "CAPITALS": "WSH", "WASHINGTON": "WSH",
    "HURRICANES": "CAR", "CAROLINA": "CAR",
    "JACKETS": "CBJ", "BLUE JACKETS": "CBJ", "COLUMBUS": "CBJ",
    "ISLANDERS": "NYI", "NY ISLANDERS": "NYI", "NEW YORK ISLANDERS": "NYI",
    "DEVILS": "NJD", "NEW JERSEY": "NJD",
    "FLYERS": "PHI", "PHILADELPHIA": "PHI",
    "PENGUINS": "PIT", "PITTSBURGH": "PIT",
    "BLACKHAWKS": "CHI", "CHICAGO": "CHI",
    "BLUES": "STL", "ST LOUIS": "STL", "ST. LOUIS": "STL",
    "PREDATORS": "NSH", "NASHVILLE": "NSH",
    "WILD": "MIN", "MINNESOTA": "MIN",
    "JETS": "WPG", "WINNIPEG": "WPG",
    "AVALANCHE": "COL", "COLORADO": "COL",
    "STARS": "DAL", "DALLAS": "DAL",
    "OILERS": "EDM", "EDMONTON": "EDM",
    "FLAMES": "CGY", "CALGARY": "CGY",
    "CANUCKS": "VAN", "VANCOUVER": "VAN",
    "KRAKEN": "SEA", "SEATTLE": "SEA",
    "KNIGHTS": "VGK", "GOLDEN KNIGHTS": "VGK", "VEGAS": "VGK",
    "KINGS": "LAK", "LOS ANGELES": "LAK", "LA KINGS": "LAK",
    "DUCKS": "ANA", "ANAHEIM": "ANA",
    "SHARKS": "SJS", "SAN JOSE": "SJS",
    "MAMMOTH": "UTA", "UTAH": "UTA",
}


@lru_cache(maxsize=1)
def load_freeze() -> NHLRateParameters:
    raw = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    return NHLRateParameters(**raw["parameters"])


def resolve_team(name: str) -> str | None:
    token = str(name or "").strip().upper().replace(".", " ")
    if token in PRIORS_BY_ABBREV:
        return token
    if token in ALIASES:
        return ALIASES[token]
    parts = token.split()
    if parts and parts[-1] in ALIASES:
        return ALIASES[parts[-1]]
    if len(parts) >= 2:
        tail = " ".join(parts[-2:])
        if tail in ALIASES:
            return ALIASES[tail]
    return None


def _row(team: str, opp: str, *, home: bool) -> tuple[float, ...]:
    gf, _ga, sf, _sa = PRIORS_BY_ABBREV[team]
    _ogf, oga, osf, osa = PRIORS_BY_ABBREV[opp]
    shot_share = sf / max(1e-9, sf + osa)
    return (gf, oga, shot_share, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0 if home else 0.0)


def _lam(params: NHLRateParameters, features: tuple[float, ...]) -> float:
    coef = (
        params.offense_xg, params.opponent_xga, params.shot_share, params.special_teams,
        params.goalie_gsax, params.rest, params.travel, params.lineup, params.home_ice,
    )
    eta = params.intercept + sum(c * x for c, x in zip(coef, features))
    return math.exp(max(-8.0, min(4.0, eta)))


def _pois_pmf(mean: float, kmax: int = 20) -> list[float]:
    out = [math.exp(-mean)]
    for k in range(1, kmax + 1):
        out.append(out[-1] * mean / k)
    return out


def final_score_distribution(away: str, home: str) -> dict | None:
    """Exact final (home, away) goal distribution incl. the OT/SO winner goal.

    Regulation goals are independent Poisson. A regulation tie adds one goal
    to a coin-flip winner (DK totals and puck lines count the OT/SO winner).
    """
    a = resolve_team(away)
    h = resolve_team(home)
    if a is None or h is None:
        return None
    params = load_freeze()
    lh = _lam(params, _row(h, a, home=True))
    la = _lam(params, _row(a, h, home=False))
    ph, pa = _pois_pmf(lh), _pois_pmf(la)
    dist: dict[tuple[int, int], float] = {}
    for i, pi in enumerate(ph):
        for j, pj in enumerate(pa):
            p = pi * pj
            if i == j:
                dist[(i + 1, j)] = dist.get((i + 1, j), 0.0) + 0.5 * p
                dist[(i, j + 1)] = dist.get((i, j + 1), 0.0) + 0.5 * p
            else:
                dist[(i, j)] = dist.get((i, j), 0.0) + p
    z = sum(dist.values())
    return {"home_lambda": lh, "away_lambda": la, "dist": {k: v / z for k, v in dist.items()}}


def total_probs(fsd: dict, line: float) -> tuple[float, float, float]:
    """(over, push, under) for a full-game total line."""
    over = push = under = 0.0
    for (hg, ag), p in fsd["dist"].items():
        t = hg + ag
        if t > line:
            over += p
        elif t < line:
            under += p
        else:
            push += p
    return over, push, under


def puck_line_probs(fsd: dict, away_line: float) -> tuple[float, float, float]:
    """(away_cover, push, home_cover) where away gets `away_line` (e.g. +1.5)."""
    away = push = home = 0.0
    for (hg, ag), p in fsd["dist"].items():
        margin = ag - hg + away_line
        if margin > 0:
            away += p
        elif margin < 0:
            home += p
        else:
            push += p
    return away, push, home


def simulate_matchup(away: str, home: str, *, n: int = 8000, seed: int = 1) -> dict[str, float] | None:
    """Backward-compatible summary (exact; n/seed ignored)."""
    fsd = final_score_distribution(away, home)
    if fsd is None:
        return None
    hw = sum(p for (hg, ag), p in fsd["dist"].items() if hg > ag)
    return {
        "home_win": hw,
        "away_win": 1.0 - hw,
        "over_5_5": total_probs(fsd, 5.5)[0],
        "over_6_5": total_probs(fsd, 6.5)[0],
        "home_pl_minus_1_5": puck_line_probs(fsd, 1.5)[2],
        "home_lambda": fsd["home_lambda"],
        "away_lambda": fsd["away_lambda"],
    }


def no_vig(price_a: int, price_b: int) -> tuple[float, float]:
    ia = 1.0 / american_to_decimal(price_a)
    ib = 1.0 / american_to_decimal(price_b)
    return ia / (ia + ib), ib / (ia + ib)


def american_to_decimal(odds: int) -> float:
    if odds > 0:
        return 1.0 + odds / 100.0
    return 1.0 + 100.0 / abs(odds)


def ev_return(model_p: float, odds: int, push_p: float = 0.0) -> float:
    """Expected return per $1; a push refunds the stake."""
    return model_p * american_to_decimal(odds) + push_p - 1.0
