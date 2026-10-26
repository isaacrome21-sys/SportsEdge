import math
import pytest
from sportsedge.nba_phone_prop_pricing import phone_nba_prop_rows
from tests.test_nba_prop_engines_20261020 import make_store, quote_row, NOW

@pytest.mark.parametrize('market', ['PLAYER_POINTS', 'PLAYER_REBOUNDS', 'PLAYER_ASSISTS', 'PLAYER_PRA'])
@pytest.mark.parametrize('odds', [float('nan'), float('inf'), -float('inf'), 'NaN', 'Infinity', '-Infinity'])
def test_nonfinite_quote_is_refused_without_ev(market, odds):
    rows, _ = phone_nba_prop_rows([quote_row(market=market, odds=odds)], now=NOW, store=make_store())
    assert rows[0]['status'] == 'NO_MODEL_OR_MARKET'
    assert rows[0]['reason'] == 'NBA_PROP_QUOTE_PRICE_MISSING'
    assert 'ev_per_dollar' not in rows[0]

@pytest.mark.parametrize('odds', [-110, '+150', -10000, 10000])
def test_finite_quotes_keep_existing_ev(odds):
    rows, _ = phone_nba_prop_rows([quote_row(odds=odds)], now=NOW, store=make_store())
    assert math.isfinite(rows[0]['ev_per_dollar'])
