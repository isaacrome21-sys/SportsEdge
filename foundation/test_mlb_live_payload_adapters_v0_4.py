#!/usr/bin/env python3
from mlb_live_payload_adapters_v0_4 import *
from mlb_source_adapters_v0_2 import AdapterError


def _fixture(with_subs=True):
    players={}
    ids=[678882,646240,665839,594807,677800,596115,622569,666915,657136]
    for slot,pid in enumerate(ids,1):
        players[f'ID{pid}']={'person':{'id':pid},'battingOrder':f'{slot}00'}
    order=ids[:]
    if with_subs:
        # Observed behavior class: original slot occupant retained as x00; substitute is x01;
        # team-level array reflects current/end-state occupant.
        players['ID999003']={'person':{'id':999003},'battingOrder':'301'}
        players['ID999005']={'person':{'id':999005},'battingOrder':'501'}
        order[2]=999003; order[4]=999005
    # Pitcher record intentionally has no battingOrder.
    players['ID601713']={'person':{'id':601713}}
    return {'gamePk':716390,'liveData':{'boxscore':{'teams':{'away':{'players':players,'battingOrder':order}}}}}


# Final/current payload: original lineup is reconstructable despite substitutions.
f=_fixture(True)
starters=extract_initial_lineup_for_audit(f,'away')
assert starters[3]=='665839' and starters[5]=='677800'
chains=extract_substitution_chain_for_audit(f,'away')
assert chains[3]==[(0,'665839'),(1,'999003')]
assert chains[5]==[(0,'677800'),(1,'999005')]
assert compare_team_array_to_current_occupants(f,'away') is True

# A final payload must not be allowed to masquerade as pregame even if caller lies.
try:
    adapt_pregame_lineup_from_player_codes(
        f,'away','MLB_STATS_API','MLB_OFFICIAL','2023-09-29T22:50:00Z',
        snapshot_time='2023-09-29T22:45:00Z',pregame_attested=True)
    raise AssertionError('expected fail closed on substitution codes')
except AdapterError as e:
    assert 'substitution' in str(e)

# True pregame-shaped snapshot: 9 x00 codes, no substitutions, emits slots 1..9.
p=_fixture(False)
out=adapt_pregame_lineup_from_player_codes(
    p,'away','MLB_STATS_API','MLB_OFFICIAL','2023-09-29T22:50:00Z',
    snapshot_time='2023-09-29T22:45:00Z',pregame_attested=True)
assert len(out)==9
assert [x.fact_key for x in out]==[f'lineup_slot:716390:away:{i}' for i in range(1,10)]
assert [x.value for x in out]==[str(x) for x in [678882,646240,665839,594807,677800,596115,622569,666915,657136]]
assert all(x.status=='CONFIRMED' for x in out)

# Missing/invalid battingOrder codes fail closed.
bad=_fixture(False); bad['liveData']['boxscore']['teams']['away']['players']['ID678882']['battingOrder']='1000'
try:
    extract_initial_lineup_for_audit(bad,'away')
    raise AssertionError('expected invalid code failure')
except AdapterError:
    pass

print('ALL MLB LIVE PAYLOAD V0.4 BATTING-ORDER TESTS PASS')
