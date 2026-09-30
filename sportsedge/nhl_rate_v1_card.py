"""Price NHL ML / puck line / totals from the frozen rate v1 owner."""
from __future__ import annotations

import json
import math
import random
from functools import lru_cache
from pathlib import Path

from sportsedge.sports.nhl.rate_model import NHLRateParameters

FREEZE_PATH = Path(__file__).resolve().parents[1] / "artifacts" / "nhl" / "nhl_rate_v1_freeze.json"

# 2025-26 REG official score endpoint. gf60, ga60, sf60, sa60.
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
    "WPG": (2.817073, 2.170732, 26.365854, 27.768293),
    "WSH": (3.207317, 2.975610, 28.048780, 28.134146),
}
# Fix WPG ga60 typo above after verify — recompute from source file if needed.

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
    "ISLANDERS": "NYI", "NY ISLANDERS": "NYI",
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
    "BLUES": "STL",
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
    token = str(name or "").strip().upper()
    token = token.replace(".", " ")
    if token in PRIORS_BY_ABBREV:
        return token
    if token in ALIASES:
        return ALIASES[token]
    # last word: "NY Rangers" -> RANGERS
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


def _poisson(rng: random.Random, mean: float) -> int:
    if mean <= 0:
        return 0
    limit = math.exp(-mean)
    prod = 1.0
    k = 0
    while prod > limit:
        k += 1
        prod *= rng.random()
    return k - 1


def simulate_matchup(away: str, home: str, *, n: int = 8000, seed: int = 1) -> dict[str, float] | None:
    a = resolve_team(away)
    h = resolve_team(home)
    if a is None or h is None:
        return None
    params = load_freeze()
    lh = _lam(params, _row(h, a, home=True))
    la = _lam(params, _row(h, a, home=False))
    rng = random.Random(seed)
    hw = aw = ov55 = ov65 = pl = 0
    for _ in range(n):
        hg = _poisson(rng, lh)
        ag = _poisson(rng, la)
        fh, fa = hg, ag
        if hg == ag:
            if rng.random() < 0.5:
                fh += 1
            else:
                fa += 1
        if fh > fa:
            hw += 1
        elif fa > fh:
            aw += 1
        tot = fh + fa
        if tot > 5.5:
            ov55 += 1
        if tot > 6.5:
            ov65 += 1
        if (fh - fa) > 1.5:
            pl += 1
    return {
        "home_win": hw / n,
        "away_win": aw / n,
        "over_5_5": ov55 / n,
        "over_6_5": ov65 / n,
        "home_pl_minus_1_5": pl / n,
        "home_lambda": lh,
        "away_lambda": la,
    }


def american_to_decimal(odds: int) -> float:
    if odds > 0:
        return 1.0 + odds / 100.0
    return 1.0 + 100.0 / abs(odds)


def ev_return(model_p: float, odds: int) -> float:
    return model_p * american_to_decimal(odds) - 1.0
