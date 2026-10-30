from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest
from sportsedge.phone_quote_identity import same_event_start

@pytest.mark.parametrize('value', [None, '', 'bad', '2026-10-12T00:00:00', '2026-10-13T00:00:00Z'])
def test_missing_invalid_naive_or_other_event_cannot_pair(value):
    assert not same_event_start({'kickoff':'2026-10-12T00:00:00Z'}, {'kickoff':value})

def test_equivalent_offset_and_alias_pair():
    assert same_event_start({'kickoff':'2026-10-12T00:00:00Z'}, {'commence_time':'2026-10-11T19:00:00-05:00'})

@pytest.mark.parametrize('sport_path', ['nfl', 'batter', 'pitcher', 'first_inning'])
@pytest.mark.parametrize('different_event', [False, True])
def test_quote_pair_is_bound_to_fixture(sport_path, different_event):
    from contextlib import nullcontext
    context = nullcontext()
    if sport_path == 'nfl':
        from sportsedge.nfl_phone_player_pricing import phone_nfl_player_rows as run
        from tests.test_milestone_ladder_ingestion_20261014 import _stafford_ladder_row, _nfl_getter, NFL_AS_OF
        base = _stafford_ladder_row()
        base.pop('milestone_ladder', None)
        base.update(market='PLAYER_PASSING_YARDS', line=250.5, odds=-110)
        rows = [{**base, 'side':side} for side in ['OVER','UNDER']]
        now, getter = NFL_AS_OF, _nfl_getter
    elif sport_path == 'batter':
        from sportsedge.mlb_phone_batter_pricing import phone_batter_rows as run
        from tests.test_mlb_prop_exact_quote_and_degenerate_tail_20261014 import ExactPairPhoneBridgeTests, NOW
        case=ExactPairPhoneBridgeTests(); case.setUp()
        rows=[case._row('OVER', .5),case._row('UNDER', .5)]
        context=patch('sportsedge.mlb_phone_batter_pricing.MLBBatterPublicSource.prior_games', return_value=case.verified)
        now, getter=NOW, None
    elif sport_path == 'pitcher':
        from sportsedge.mlb_phone_pitcher_pricing import phone_pitcher_rows as run
        from tests.test_mlb_phone_pitcher_real_public_history import prop, getter, AS_OF
        rows=[prop(),prop(side='UNDER',odds=-114)]
        now=AS_OF
    else:
        from sportsedge.mlb_phone_first_inning_pricing import phone_first_inning_rows as run
        from tests.test_mlb_first_inning import _row, _schedule_getter, _history_games, _fixture_game
        rows=[_row(side='OVER',odds=105),_row(side='UNDER',odds=-140)]
        now=datetime(2026,10,11,20,tzinfo=timezone.utc)
        getter=_schedule_getter(_history_games(),_fixture_game())
    start=datetime.fromisoformat(rows[1].pop('kickoff').replace('Z','+00:00'))
    if different_event:
        start += timedelta(days=1)
    rows[1]['commence_time']=start.astimezone(timezone(timedelta(hours=-5))).isoformat()
    with context:
        out,_=run(rows, now=now, getter=getter)
    if different_event:
        assert 'ev_per_dollar' not in out[0], out
    else:
        assert all('ev_per_dollar' in r for r in out), out
