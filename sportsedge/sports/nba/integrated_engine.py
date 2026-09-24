"""Coherent NBA simulation binding for RUN IT markets.

Fitted pace/efficiency, period parameters, player roles and optional temporal
calibration feed one shared path set. Sportsbook quotes never create Model_P.
Unsupported markets stay unsupported instead of receiving manufactured numbers.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .binding import NBABoundEdge, NBAQuote, bind_quote
from .calibration import NBACalibrator
from .market_capabilities import capability_for
from .pace_efficiency import NBAPaceEfficiencyModel, predict_state
from .periods import NBAPeriodParameters, simulate_period_paths, half_margin, half_total, quarter_margin, quarter_total
from .player_stats import NBAPlayerStatPaths, NBAPlayerStatRole, simulate_player_stats
from .pricing import NBAFairPrice, moneyline_probability, path_outcome
from .run_it import NBARunItCard, build_run_it_card
from .simulation import NBAGamePaths, NBAGameState, simulate_game_paths
from .training import NBATrainingRow

SUPPORTED_GAME = frozenset({"MONEYLINE", "SPREAD", "TOTAL", "HOME_TEAM_TOTAL", "AWAY_TEAM_TOTAL"})
SUPPORTED_PERIOD = frozenset({"FIRST_HALF_SPREAD", "FIRST_HALF_TOTAL", "QUARTER_SPREAD", "QUARTER_TOTAL"})
SUPPORTED_PLAYER = frozenset({"PLAYER_POINTS", "PLAYER_REBOUNDS", "PLAYER_ASSISTS", "PLAYER_THREES", "PLAYER_PRA", "PLAYER_PR", "PLAYER_PA", "PLAYER_RA"})

@dataclass(frozen=True)
class NBAIntegratedPaths:
    game: NBAGamePaths
    periods: object
    players: dict[str, NBAPlayerStatPaths]
    pace_version: str
    period_version: str
    model_version: str

def build_integrated_paths(row: NBATrainingRow, pace: NBAPaceEfficiencyModel, periods: NBAPeriodParameters, roles: Iterable[NBAPlayerStatRole], *, simulations: int = 4_000) -> NBAIntegratedPaths:
    predicted = predict_state(pace, row)
    state = NBAGameState(game_id=row.game_id, expected_possessions=predicted["expected_possessions"], home_points_per_100=predicted["home_points_per_100"], away_points_per_100=predicted["away_points_per_100"])
    version = f"{pace.version}|{predicted['training_sha256'][:12]}|{periods.version}"
    game = simulate_game_paths(state, simulations=simulations, model_version=version)
    period_paths = simulate_period_paths(game, periods)
    player_paths = {role.player_id: simulate_player_stats(game, role) for role in roles}
    return NBAIntegratedPaths(game, period_paths, player_paths, pace.version, periods.version, version)

def _player_values(paths: NBAPlayerStatPaths, market: str) -> tuple[int, ...]:
    return {"PLAYER_POINTS": paths.points, "PLAYER_REBOUNDS": paths.rebounds, "PLAYER_ASSISTS": paths.assists, "PLAYER_THREES": paths.threes, "PLAYER_PRA": paths.pra, "PLAYER_PR": paths.pr, "PLAYER_PA": paths.pa, "PLAYER_RA": paths.ra}[market]

def _fair_for_quote(quote: NBAQuote, bundle: NBAIntegratedPaths) -> NBAFairPrice:
    market = quote.market.strip().upper()
    cap = capability_for(market)
    if cap.status != "REQUIRES_ENGINE": raise ValueError(f"unsupported NBA market: {market}")
    selection = quote.selection.strip().upper(); game = bundle.game
    if market == "MONEYLINE":
        if selection not in {"HOME", "AWAY"}: raise ValueError("moneyline selection must be HOME or AWAY")
        return moneyline_probability(game.home_final, game.away_final, home=selection == "HOME")
    if quote.line is None: raise ValueError(f"{market} requires a finite line")
    over = selection in {"OVER", "HOME"}
    if market == "SPREAD": return path_outcome(tuple(h-a for h,a in zip(game.home_final, game.away_final)), quote.line if selection == "HOME" else -quote.line, over=True)
    if market == "TOTAL": return path_outcome(tuple(h+a for h,a in zip(game.home_final, game.away_final)), quote.line, over=over)
    if market == "HOME_TEAM_TOTAL": return path_outcome(game.home_final, quote.line, over=over)
    if market == "AWAY_TEAM_TOTAL": return path_outcome(game.away_final, quote.line, over=over)
    if market == "FIRST_HALF_SPREAD": return path_outcome(half_margin(bundle.periods, 1), quote.line if selection == "HOME" else -quote.line, over=True)
    if market == "FIRST_HALF_TOTAL": return path_outcome(half_total(bundle.periods, 1), quote.line, over=over)
    if market == "QUARTER_SPREAD":
        quarter = int(quote.selection.split(":")[-1]) if ":" in quote.selection else 1
        return path_outcome(quarter_margin(bundle.periods, quarter), quote.line if "HOME" in selection else -quote.line, over=True)
    if market == "QUARTER_TOTAL":
        quarter = int(quote.selection.split(":")[-1]) if ":" in quote.selection else 1
        return path_outcome(quarter_total(bundle.periods, quarter), quote.line, over=over)
    if market in SUPPORTED_PLAYER:
        player_id = quote.selection.split(":")[0]
        if player_id not in bundle.players: raise ValueError(f"no fitted role for player {player_id}")
        return path_outcome(_player_values(bundle.players[player_id], market), quote.line, over=over)
    raise ValueError(f"unsupported NBA market: {market}")

def bind_integrated_card(quotes: Iterable[NBAQuote], bundle: NBAIntegratedPaths, *, as_of: datetime, model_quality: float, context_quality: float, calibrator: NBACalibrator | None = None) -> NBARunItCard:
    edges: list[NBABoundEdge] = []; requested = []
    for quote in quotes:
        requested.append(quote.market); cap = capability_for(quote.market)
        if cap.status != "REQUIRES_ENGINE": continue
        fair = _fair_for_quote(quote, bundle)
        if calibrator is not None and fair.push_probability == 0:
            wp = calibrator.calibrate(min(0.999, max(0.001, fair.win_probability))); lp = 1.0 - wp
            fair = NBAFairPrice(wp, 0.0, lp, 1.0 / wp if wp else float("inf"))
        edges.append(bind_quote(quote, fair, as_of=as_of, model_quality=model_quality, context_quality=context_quality))
    return build_run_it_card(edges, generated_at=as_of, requested_markets=requested)
