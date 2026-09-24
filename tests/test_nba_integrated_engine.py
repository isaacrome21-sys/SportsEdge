from datetime import datetime, timezone

from sportsedge.sports.nba.binding import NBAQuote
from sportsedge.sports.nba.integrated_engine import bind_integrated_card, build_integrated_paths
from sportsedge.sports.nba.pace_efficiency import fit_pace_efficiency
from sportsedge.sports.nba.period_history import NBAPeriodObservation, fit_period_parameters
from sportsedge.sports.nba.player_history import NBAPlayerBoxObservation, fit_player_role
from sportsedge.sports.nba.training import NBATrainingRow

AS_OF = datetime(2026, 9, 23, 8, tzinfo=timezone.utc)
TIP = datetime(2026, 9, 20, 0, tzinfo=timezone.utc)
FEAT = datetime(2026, 9, 19, 20, tzinfo=timezone.utc)
OBS = datetime(2026, 9, 20, 3, tzinfo=timezone.utc)

def _row(gid="g1", hp=110, ap=104):
    return NBATrainingRow(gid, TIP, FEAT, "H", "A", 100.0, 112.0, 110.0, 108.0, 111.0, hp, ap, "v1")

def _bundle():
    rows = (_row("g1", 112, 100), _row("g2", 108, 106)); pace = fit_pace_efficiency(rows)
    periods = fit_period_parameters([
        NBAPeriodObservation("g1", TIP, OBS, (28,27,26,31), (24,26,25,25), "box", "v1"),
        NBAPeriodObservation("g2", TIP, OBS, (27,26,27,28), (26,27,26,27), "box", "v1"),
    ], as_of=AS_OF)
    role = fit_player_role([
        NBAPlayerBoxObservation("g1", "p1", "H", TIP, OBS, 34.0, 24, 7, 6, 3, 112, "box", "v1"),
        NBAPlayerBoxObservation("g2", "p1", "H", TIP, OBS, 32.0, 22, 8, 5, 2, 108, "box", "v1"),
    ], player_id="p1", team="HOME", as_of=AS_OF)
    return build_integrated_paths(_row("live"), pace, periods, [role], simulations=800)

def _q(market, selection, line=None, odds=1.91):
    return NBAQuote("live", market, selection, line, odds, "dk", datetime(2026, 9, 23, 7, 59, tzinfo=timezone.utc))

def test_supported_markets_bind_from_shared_paths():
    card = bind_integrated_card([
        _q("MONEYLINE", "HOME"), _q("SPREAD", "HOME", -3.5), _q("TOTAL", "OVER", 220.5),
        _q("HOME_TEAM_TOTAL", "OVER", 112.5), _q("FIRST_HALF_TOTAL", "UNDER", 110.5),
        _q("PLAYER_POINTS", "p1", 23.5), _q("PLAYER_PRA", "p1", 36.5),
    ], _bundle(), as_of=AS_OF, model_quality=0.8, context_quality=0.8)
    markets = {r.market for r in card.rows}
    assert "MONEYLINE" in markets and "PLAYER_PRA" in markets and "FIRST_HALF_TOTAL" in markets
    assert card.unsupported_markets == ()
    assert all(0 <= r.score <= 100 for r in card.rows)
    assert all(r.model_probability > 0 for r in card.rows)

def test_unsupported_markets_remain_explicitly_unsupported():
    card = bind_integrated_card([_q("FIRST_BASKET", "p1"), _q("DOUBLE_DOUBLE", "p1", 0.5)], _bundle(), as_of=AS_OF, model_quality=1.0, context_quality=1.0)
    assert card.rows == ()
    assert set(card.unsupported_markets) == {"FIRST_BASKET", "DOUBLE_DOUBLE"}
