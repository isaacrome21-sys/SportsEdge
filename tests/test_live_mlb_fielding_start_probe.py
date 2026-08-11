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
        print('FIELDING_SPLIT_KEYS', sorted(sample.keys()))
        print('FIELDING_STAT', json.dumps(sample.get('stat') or {}, sort_keys=True))
        print('FIELDING_DATE', sample.get('date'))
        print('FIELDING_GAME', json.dumps(sample.get('game') or {}, sort_keys=True))
        stats=[s.get('stat') or {} for s in splits]
        self.assertTrue(any('gamesStarted' in st for st in stats), 'gamesStarted absent from fielding gameLog')


if __name__=='__main__': unittest.main()
