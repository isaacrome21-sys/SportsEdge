import json
import unittest
from urllib.parse import urlencode
from urllib.request import urlopen

BASE='https://statsapi.mlb.com/api/v1'


def get(path, params=None):
    url=BASE+path
    if params: url += '?' + urlencode(params)
    with urlopen(url, timeout=15) as r:
        return json.loads(r.read().decode())


class FieldingStartProbe(unittest.TestCase):
    def test_fielding_game_log_exposes_start_identity(self):
        data=get('/people/514888/stats', {'stats':'gameLog','group':'fielding','season':'2026','gameType':'R'})
        splits=((data.get('stats') or [{}])[0].get('splits') or [])
        self.assertTrue(splits, 'no fielding game-log splits')
        sample=splits[-1]
        print('FIELDING_STAT', json.dumps(sample.get('stat') or {}, sort_keys=True))
        self.assertTrue(any('gamesStarted' in (s.get('stat') or {}) for s in splits), 'gamesStarted absent')

    def test_ohtani_dh_start_visibility(self):
        hitting=get('/people/660271/stats', {'stats':'gameLog','group':'hitting','season':'2026','gameType':'R'})
        hs=((hitting.get('stats') or [{}])[0].get('splits') or [])
        self.assertTrue(hs, 'no Ohtani hitting splits')
        fielding=get('/people/660271/stats', {'stats':'gameLog','group':'fielding','season':'2026','gameType':'R'})
        fs=((fielding.get('stats') or [{}])[0].get('splits') or [])
        print('OHTANI_HITTING_GAMES', len(hs))
        print('OHTANI_FIELDING_GAMES', len(fs))
        print('OHTANI_HIT_POSITIONS', json.dumps(hs[-1].get('positionsPlayed') or [], sort_keys=True))
        if fs:
            print('OHTANI_FIELDING_LAST', json.dumps(fs[-1], sort_keys=True))
        dh_positions=[]
        for s in hs:
            positions=s.get('positionsPlayed') or []
            if any(str(p.get('abbreviation') or '').upper()=='DH' for p in positions if isinstance(p,dict)):
                dh_positions.append((s.get('date'), (s.get('game') or {}).get('gamePk')))
        print('OHTANI_HITTING_DH_POSITION_GAMES', len(dh_positions))
        self.assertTrue(dh_positions, 'no DH positions exposed in hitting gameLog')


if __name__=='__main__': unittest.main()
