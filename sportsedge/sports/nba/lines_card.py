"""NBA phone-lines intake + card.

Input (issue body, one block per game; away first, like DK):

    Celtics @ Knicks
    ML +130 -155
    Spread +3.5 -110 -110      <- away line, away price, home price
    Total 224.5 -110 -110      <- line, over price, under price

Model: ``ratings_model`` replayed over completed games (ESPN results) gives a
margin and total; probabilities come from normal residuals with the holdout
residual SDs. Labels: a market is a BET only if listed in ``VALIDATED_MARKETS``
(filled only from a passing out-of-sample backtest). Today it is empty, so
every positive-EV side is a LEAN.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .ratings_model import NBARatings, NBARatingsParams, replay

# Out-of-sample backtest (research_notes/nba_ratings_backtest_v1.md): nothing passed.
VALIDATED_MARKETS: tuple[str, ...] = ()
BACKTEST_NOTE = ("v1 ratings model, holdout 2015-16..2021-22 vs closing lines: no market validated "
                 "(model-vs-close disagreements hit ~49% ATS and O/U).")
# Tuned on 2012-14 by score MSE (scripts/backtest_nba_ratings_vs_lines.py).
PARAMS = NBARatingsParams(k=0.04, carry=0.5, k_league=0.005)
# Residual SDs ~ 1.25 x holdout MAE (10.26 margin, 14.58 total).
MARGIN_SD = 12.8
TOTAL_SD = 18.2
# Market-anchored blend: fair = market + W * (model - market). W is the latest
# walk-forward fit of closing-line residuals on (model - close) through 2021-22
# (spread w=0.057; total w=-0.086 -> clipped to 0: the model adds nothing on totals).
W_SPREAD = 0.057
W_TOTAL = 0.0

TEAMS = {  # abbr: (city, nickname, extra aliases)
    "ATL": ("Atlanta", "Hawks", ()), "BOS": ("Boston", "Celtics", ()),
    "BKN": ("Brooklyn", "Nets", ("BRK", "BKLYN")), "CHA": ("Charlotte", "Hornets", ("CHO",)),
    "CHI": ("Chicago", "Bulls", ()), "CLE": ("Cleveland", "Cavaliers", ("Cavs",)),
    "DAL": ("Dallas", "Mavericks", ("Mavs",)), "DEN": ("Denver", "Nuggets", ()),
    "DET": ("Detroit", "Pistons", ()), "GSW": ("Golden State", "Warriors", ("GS",)),
    "HOU": ("Houston", "Rockets", ()), "IND": ("Indiana", "Pacers", ()),
    "LAC": ("LA", "Clippers", ("Los Angeles Clippers",)), "LAL": ("Los Angeles", "Lakers", ("LA Lakers",)),
    "MEM": ("Memphis", "Grizzlies", ()), "MIA": ("Miami", "Heat", ()),
    "MIL": ("Milwaukee", "Bucks", ()), "MIN": ("Minnesota", "Timberwolves", ("Wolves",)),
    "NOP": ("New Orleans", "Pelicans", ("NO", "Pels")), "NYK": ("New York", "Knicks", ("NY",)),
    "OKC": ("Oklahoma City", "Thunder", ()), "ORL": ("Orlando", "Magic", ()),
    "PHI": ("Philadelphia", "76ers", ("Sixers",)), "PHX": ("Phoenix", "Suns", ("PHO",)),
    "POR": ("Portland", "Trail Blazers", ("Blazers", "Trailblazers")), "SAC": ("Sacramento", "Kings", ()),
    "SAS": ("San Antonio", "Spurs", ("SA",)), "TOR": ("Toronto", "Raptors", ()),
    "UTA": ("Utah", "Jazz", ("UTAH",)), "WAS": ("Washington", "Wizards", ("WSH",)),
}


class NBALinesError(ValueError):
    pass


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


_ALIAS: dict[str, str] = {}
for _abbr, (_city, _nick, _extra) in TEAMS.items():
    for _a in (_abbr, _nick, f"{_city} {_nick}", f"{_abbr} {_nick}", *_extra):
        _ALIAS[_key(_a)] = _abbr


def team_abbr(name: str) -> str:
    k = _key(name)
    if k in _ALIAS:
        return _ALIAS[k]
    found = [(len(alias), a) for alias, a in _ALIAS.items() if len(alias) >= 4 and alias in k]
    if found:
        best = max(n for n, _ in found)
        hits = {a for n, a in found if n == best}
        if len(hits) == 1:
            return hits.pop()
    raise NBALinesError(f"NBA_UNKNOWN_TEAM:{name}")


@dataclass
class Market:
    market: str          # MONEYLINE | SPREAD | TOTAL
    line: float | None   # SPREAD: away line; TOTAL: total
    p1: int              # away / over price
    p2: int              # home / under price
    raw: str


@dataclass
class Game:
    away: str
    home: str
    header: str
    markets: list[Market] = field(default_factory=list)


def _american(tok: str, raw: str) -> int:
    t = tok.strip().replace("−", "-").replace("–", "-")
    if t.lower() in ("even", "ev"):
        return 100
    try:
        v = int(float(t))
    except ValueError as exc:
        raise NBALinesError(f"NBA_ODDS_INVALID:{raw}") from exc
    if -100 < v < 100:
        raise NBALinesError(f"NBA_ODDS_INVALID:{raw}")
    return v


def _line(tok: str, raw: str) -> float:
    t = tok.strip().replace("−", "-").replace("–", "-").lstrip("oOuU")
    if t.lower() in ("pk", "pick"):
        return 0.0
    try:
        return float(t)
    except ValueError as exc:
        raise NBALinesError(f"NBA_LINE_INVALID:{raw}") from exc


_PRICE_RE = re.compile(r"(?<![\w.])[+\-−–]?\d{3,4}(?![\w.])|\beven\b", re.I)


def parse_lines(body: str) -> list[Game]:
    if "### Lines" in body:
        body = body.split("### Lines", 1)[1].split("\n### ", 1)[0]
    body = body.replace("```text", "").replace("```", "")
    games: list[Game] = []
    cur: Game | None = None
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("<!--"):
            continue
        if "@" in line and not re.match(r"^(ml|moneyline|spread|sp|total|ou|o/u)\b", line, re.I):
            a, h = [p.strip() for p in line.split("@", 1)]
            cur = Game(team_abbr(a), team_abbr(h), line)
            games.append(cur)
            continue
        if cur is None:
            if not _PRICE_RE.search(line):
                continue  # leading free-text note
            raise NBALinesError(f"NBA_MARKET_BEFORE_GAME:{line}")
        parts = line.replace(",", " ").split()
        kind = parts[0].lower()
        if kind in ("ml", "moneyline"):
            if len(parts) != 3:
                raise NBALinesError(f"NBA_ONE_SIDED_OR_MALFORMED:{line}")
            cur.markets.append(Market("MONEYLINE", None, _american(parts[1], line), _american(parts[2], line), line))
        elif kind in ("spread", "sp", "ps"):
            if len(parts) != 4:
                raise NBALinesError(f"NBA_ONE_SIDED_OR_MALFORMED:{line}")
            cur.markets.append(Market("SPREAD", _line(parts[1], line), _american(parts[2], line), _american(parts[3], line), line))
        elif kind in ("total", "ou", "o/u"):
            if len(parts) != 4:
                raise NBALinesError(f"NBA_ONE_SIDED_OR_MALFORMED:{line}")
            cur.markets.append(Market("TOTAL", _line(parts[1], line), _american(parts[2], line), _american(parts[3], line), line))
        elif not _PRICE_RE.search(line):
            # Free-text note (no American price on the line) -- e.g. "Smoke test only."
            # Market lines always carry prices, so a mistyped market still fails closed.
            continue
        else:
            raise NBALinesError(f"NBA_UNRECOGNIZED:{line}")
    if not games:
        raise NBALinesError("NBA_NO_GAMES")
    for g in games:
        if not g.markets:
            raise NBALinesError(f"NBA_GAME_WITHOUT_MARKETS:{g.header}")
    return games


def dec(a: int) -> float:
    return 1 + (a / 100 if a > 0 else 100 / -a)


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def fmt_am(a: int) -> str:
    return f"+{a}" if a > 0 else str(a)


@dataclass
class Row:
    game: str
    market: str
    side: str
    price: int
    model_p: float
    novig_p: float
    ev: float
    label: str


def _inv_phi(p: float) -> float:
    lo, hi = -10.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _phi(mid) < p else (lo, mid)
    return (lo + hi) / 2


def _novig(p1: int, p2: int) -> tuple[float, float]:
    i1, i2 = 1 / dec(p1), 1 / dec(p2)
    return i1 / (i1 + i2), i2 / (i1 + i2)


def blended(g: Game, m: float, t: float) -> tuple[float, float]:
    """Anchor the raw model to the market (home margin, total) using backtest weights."""
    by = {mk.market: mk for mk in g.markets}
    if "SPREAD" in by:
        mkt_m = by["SPREAD"].line  # away +3.5 => home favored by 3.5
    elif "MONEYLINE" in by:
        mkt_m = MARGIN_SD * _inv_phi(_novig(by["MONEYLINE"].p1, by["MONEYLINE"].p2)[1])
    else:
        mkt_m = m
    mkt_t = by["TOTAL"].line if "TOTAL" in by else t
    return mkt_m + W_SPREAD * (m - mkt_m), mkt_t + W_TOTAL * (t - mkt_t)


def price_game(g: Game, ratings: NBARatings) -> tuple[float, float, list[Row]]:
    """Returns raw model (margin, total) and rows priced from the market-anchored blend."""
    raw_m, raw_t = ratings.margin_total(g.home, g.away)  # m = home - away
    m, t = blended(g, raw_m, raw_t)
    rows: list[Row] = []
    name = f"{g.away} @ {g.home}"
    for mk in g.markets:
        if mk.market == "MONEYLINE":
            ph = _phi(m / MARGIN_SD)
            sides = ((f"{g.away} ML", 1 - ph, mk.p1), (f"{g.home} ML", ph, mk.p2))
        elif mk.market == "SPREAD":
            home_line = -mk.line
            p_home = _phi((m + home_line) / MARGIN_SD)
            sides = ((f"{g.away} {mk.line:+g}", 1 - p_home, mk.p1), (f"{g.home} {home_line:+g}", p_home, mk.p2))
        else:
            p_over = 1 - _phi((mk.line - t) / TOTAL_SD)
            sides = ((f"Over {mk.line:g}", p_over, mk.p1), (f"Under {mk.line:g}", 1 - p_over, mk.p2))
        i1, i2 = 1 / dec(sides[0][2]), 1 / dec(sides[1][2])
        nv = (i1 / (i1 + i2), i2 / (i1 + i2))
        for (side, p, price), q in zip(sides, nv):
            ev = p * dec(price) - 1
            if ev <= 0:
                label = "PASS"
            elif mk.market in VALIDATED_MARKETS:
                label = "BET"
            else:
                label = "LEAN"
            rows.append(Row(name, mk.market, side, price, p, q, ev, label))
    return raw_m, raw_t, rows


def render(games: list[Game], ratings: NBARatings, *, observed: str, results_note: str) -> str:
    out = ["# SportsEdge NBA card", "",
           f"Lines observed {observed}. {results_note}",
           f"**Validated markets: {', '.join(VALIDATED_MARKETS) or 'NONE'}** — {BACKTEST_NOTE} "
           "Edges use a market-anchored fair line (raw model gets ~6% weight on spreads/ML, 0% on totals), "
           "so most sides PASS after the vig. LEAN = positive EV but not a proven bet.", ""]
    all_rows = []
    for g in games:
        m, t, rows = price_game(g, ratings)
        all_rows += rows
        fav = g.home if m >= 0 else g.away
        out.append(f"### {g.away} @ {g.home}")
        bm, bt = blended(g, m, t)
        out.append(f"Raw model: {fav} by {abs(m):.1f}, total {t:.1f} "
                   f"(games rated: {g.away} {ratings.games.get(g.away, 0)}, {g.home} {ratings.games.get(g.home, 0)}). "
                   f"Priced from market-anchored fair: {g.home if bm >= 0 else g.away} by {abs(bm):.1f}, total {bt:.1f}.")
        out.append("")
        out.append("| Side | DK | Fair % | No-vig % | Edge | EV | Call |")
        out.append("|---|---|---|---|---|---|---|")
        for r in rows:
            out.append(f"| {r.side} | {fmt_am(r.price)} | {r.model_p:.1%} | {r.novig_p:.1%} | "
                       f"{(r.model_p - r.novig_p) * 100:+.1f} pts | {r.ev:+.1%} | {r.label} |")
        out.append("")
    bets = [r for r in all_rows if r.label == "BET"]
    leans = sorted((r for r in all_rows if r.label == "LEAN"), key=lambda r: -r.ev)[:5]
    out.append("## Bets")
    out.append("\n".join(f"- {r.side} {fmt_am(r.price)} (EV {r.ev:+.1%})" for r in bets) or "- None. No NBA market has passed out-of-sample validation.")
    out.append("")
    out.append("## Top leans (not bets)")
    out.append("\n".join(f"- {r.side} {fmt_am(r.price)} — fair {r.model_p:.1%} vs no-vig {r.novig_p:.1%}" for r in leans) or "- None.")
    return "\n".join(out) + "\n"


def ratings_from_results(results: Iterable[Mapping]) -> NBARatings:
    """results: dicts with season, date (YYYYMMDD int), home, away (abbr), home_pts, away_pts."""
    return replay(results, PARAMS)
