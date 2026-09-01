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


class LiveMLBStatsSchemaProbe(unittest.TestCase):
    def test_probe_game_log_schema(self):
        batting=get('/people/514888/stats', {'stats':'gameLog','group':'hitting','season':'2026','gameType':'R'})
        bsplit=((batting.get('stats') or [{}])[0].get('splits') or [])
        self.assertTrue(bsplit, 'no Altuve batting splits')
        print('BATTING_SPLIT_KEYS', sorted(bsplit[-1].keys()))
        print('BATTING_STAT', json.dumps(bsplit[-1].get('stat') or {}, sort_keys=True))
        print('BATTING_POSITIONS', json.dumps(bsplit[-1].get('positionsPlayed') or [], sort_keys=True))
        print('BATTING_FIRST_POSITIONS', json.dumps(bsplit[0].get('positionsPlayed') or [], sort_keys=True))
        print('BATTING_DATE', bsplit[-1].get('date'))
        print('BATTING_GAME', json.dumps(bsplit[-1].get('game') or {}, sort_keys=True))

        sched=get('/schedule', {'sportId':1,'date':'2026-08-11','hydrate':'probablePitcher'})
        pid=None
        for db in sched.get('dates') or []:
            for game in db.get('games') or []:
                teams=game.get('teams') or {}
                for side in ('away','home'):
                    p=((teams.get(side) or {}).get('probablePitcher') or {}).get('id')
                    if p: pid=int(p); break
                if pid: break
            if pid: break
        self.assertIsNotNone(pid, 'no probable pitcher found')
        pitching=get(f'/people/{pid}/stats', {'stats':'gameLog','group':'pitching','season':'2026','gameType':'R'})
        psplit=((pitching.get('stats') or [{}])[0].get('splits') or [])
        self.assertTrue(psplit, f'no pitching splits for {pid}')
        print('PITCHER_ID', pid)
        print('PITCHING_SPLIT_KEYS', sorted(psplit[-1].keys()))
        print('PITCHING_STAT', json.dumps(psplit[-1].get('stat') or {}, sort_keys=True))
        print('PITCHING_DATE', psplit[-1].get('date'))
        print('PITCHING_GAME', json.dumps(psplit[-1].get('game') or {}, sort_keys=True))


if __name__=='__main__': unittest.main()
