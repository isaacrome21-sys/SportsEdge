"""NBA market probabilities derived only from coherent shared simulation paths."""
from __future__ import annotations

from .periods import NBAPeriodPaths, half_margin, half_total, quarter_margin, quarter_total
from .player_stats import NBAPlayerStatPaths
from .pricing import NBAFairPrice, moneyline_probability, path_outcome
from .simulation import NBAGamePaths


def _side(values, line: float, selection: str) -> NBAFairPrice:
    side=str(selection).strip().upper()
    if side in {"HOME", "OVER"}:
        return path_outcome(values, line, over=True)
    if side in {"AWAY", "UNDER"}:
        return path_outcome(values, line, over=False)
    raise ValueError("selection must identify HOME/AWAY or OVER/UNDER")


def game_market_probability(game: NBAGamePaths, market: str, selection: str, *, line: float = 0.0) -> NBAFairPrice:
    """Price a supported full-game market from the same final-score paths."""
    key=str(market).strip().upper(); sel=str(selection).strip().upper()
    if not game.home_final or len(game.home_final) != len(game.away_final):
        raise ValueError("coherent final-score paths are required")
    if key == "MONEYLINE":
        if sel not in {"HOME","AWAY"}: raise ValueError("moneyline selection must be HOME or AWAY")
        return moneyline_probability(game.home_final, game.away_final, home=sel == "HOME")
    if key == "SPREAD":
        margins=tuple(h-a for h,a in zip(game.home_final,game.away_final))
        # line is the selected team's sportsbook handicap (e.g. HOME -4.5).
        values=margins if sel == "HOME" else tuple(-x for x in margins)
        if sel not in {"HOME","AWAY"}: raise ValueError("spread selection must be HOME or AWAY")
        return path_outcome(values, -line, over=True)
    if key == "TOTAL":
        return _side(tuple(h+a for h,a in zip(game.home_final,game.away_final)),line,sel)
    if key in {"HOME_TEAM_TOTAL","AWAY_TEAM_TOTAL"}:
        values=game.home_final if key.startswith("HOME") else game.away_final
        return _side(values,line,sel)
    raise ValueError(f"unsupported full-game market: {key}")


def period_market_probability(periods: NBAPeriodPaths, market: str, selection: str, *, line: float, quarter: int | None=None, half: int | None=None) -> NBAFairPrice:
    """Price quarter/half markets from explicit period paths; never scale full-game lines."""
    key=str(market).strip().upper(); sel=str(selection).strip().upper()
    if key == "QUARTER_SPREAD":
        if quarter is None: raise ValueError("quarter is required")
        values=quarter_margin(periods,quarter)
        if sel == "AWAY": values=tuple(-x for x in values)
        elif sel != "HOME": raise ValueError("spread selection must be HOME or AWAY")
        return path_outcome(values,-line,over=True)
    if key == "QUARTER_TOTAL":
        if quarter is None: raise ValueError("quarter is required")
        return _side(quarter_total(periods,quarter),line,sel)
    if key == "FIRST_HALF_SPREAD":
        values=half_margin(periods,1)
        if sel == "AWAY": values=tuple(-x for x in values)
        elif sel != "HOME": raise ValueError("spread selection must be HOME or AWAY")
        return path_outcome(values,-line,over=True)
    if key == "FIRST_HALF_TOTAL":
        return _side(half_total(periods,1),line,sel)
    raise ValueError(f"unsupported period market: {key}")


def player_market_probability(player: NBAPlayerStatPaths, market: str, selection: str, *, line: float) -> NBAFairPrice:
    """Price supported player props, including combos, from each player's same paths."""
    key=str(market).strip().upper()
    values={
        "PLAYER_POINTS": player.points,
        "PLAYER_REBOUNDS": player.rebounds,
        "PLAYER_ASSISTS": player.assists,
        "PLAYER_THREES": player.threes,
        "PLAYER_PRA": player.pra,
        "PLAYER_PR": player.pr,
        "PLAYER_PA": player.pa,
        "PLAYER_RA": player.ra,
    }.get(key)
    if values is None: raise ValueError(f"unsupported player market: {key}")
    return _side(values,line,selection)
