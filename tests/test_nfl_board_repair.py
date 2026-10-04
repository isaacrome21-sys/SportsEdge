import pytest
from scripts.run_auto_nfl_resilient import build_card
from scripts.render_football_board_card import render_markdown


def test_no_synthetic_period_team_or_prop_probabilities():
    markets = ['first_half_moneyline', 'quarter_spread', 'second_half_total', 'team_total', 'player_pass_yds']
    card = build_card([{'game_id': 'g', 'margin': 3, 'total': 48, 'quotes': [
        {'market': m, 'line': 20.5, 'side': 'OVER', 'american_odds': -110, 'model_p': .99} for m in markets
    ]}])
    assert all(r['model_p'] is None and r['reason'] == 'NO_ENGINE' for r in card['results'])
    assert card['bets'] == []


def test_paired_prices_ev_and_straight_price_limit():
    card = build_card([{'game_id': 'g', 'quotes': [
        {'market': 'moneyline', 'side': 'HOME', 'american_odds': -110, 'model_p': .60},
        {'market': 'moneyline', 'side': 'AWAY', 'american_odds': -110, 'model_p': .40},
    ]}])
    home = card['results'][0]
    assert home['fair_market_p'] == pytest.approx(.5)
    assert home['edge'] == pytest.approx(.1)
    assert home['ev_per_dollar'] == pytest.approx(.6 * 100 / 110 - .4)
    assert card['research_leans'] == [home]
    assert card['bets'] == []
    expensive = build_card([{'game_id': 'g', 'quotes': [{'market': 'moneyline', 'side': 'HOME', 'american_odds': -200, 'opposite_odds': 170, 'model_p': .9}]}])
    assert expensive['research_leans'] == []


def test_spread_pair_identity_and_integer_push_unknown():
    card = build_card([{'game_id': 'g', 'margin': 4, 'total': 48, 'quotes': [
        {'market': 'spread', 'side': 'HOME', 'line': -3.5, 'american_odds': -110},
        {'market': 'spread', 'side': 'AWAY', 'line': 3.5, 'american_odds': -110},
        {'market': 'total', 'side': 'OVER', 'line': 48, 'american_odds': -110},
    ]}])
    rows = [r for r in card['full_board']['rows'] if r['game_id'] == 'g' and r['market'] == 'spread']
    assert len(rows) == 2
    assert card['results'][0]['fair_market_p'] == pytest.approx(.5)
    assert card['results'][2]['model_p'] is None
    assert card['results'][2]['reason'] == 'PUSH_PROBABILITY_REQUIRED'


def test_sgp_no_authority_and_renderer_handles_nested_unsupported_labels():
    card = build_card([{'game_id': 'g', 'margin': 4, 'total': 48}], sgp_legs=[{'game_id': 'g', 'market': 'moneyline', 'side': 'HOME', 'american_odds': 100}])
    assert card['sgp_bets'] == []
    assert card['sgp_legs'][0]['bet_status'] == 'BLOCKED'
    assert 'floor' not in card['sgp_legs'][0]['correlation_note']
    text = render_markdown({'report': {'results': [{'market': 'SGP', 'reason': 'NO_ENGINE'}]}})
    assert 'passing_yards' in text
    assert not any(label in text for label in ['Model_P', 'model_p', 'Truth Gate', 'OFFICIAL'])
