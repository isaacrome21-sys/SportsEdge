import json, unittest
from datetime import datetime, timezone
from sportsedge.mlb_projected_lineups import project_team_lineup, build_native_projected_lineups
from sportsedge.mlb_source import GameSnapshot

NOW=datetime(2026,8,12,15,0,tzinfo=timezone.utc)

class Resp:
    def __init__(self,obj): self.raw=json.dumps(obj).encode()
    def __enter__(self): return self
    def __exit__(self,*a): return False
    def read(self): return self.raw

def snapshot():
    return GameSnapshot(game_pk=999,game_date='2026-08-12T23:00:00Z',official_date='2026-08-12',away_id=1,home_id=2,away_name='A',home_name='H',away_probable_pitcher_id=11,home_probable_pitcher_id=22,game_number=1,double_header='N',venue_id=1,status='Preview')

def side_players(ids, confirmed=False):
    out={}
    for slot,pid in enumerate(ids,1):
        row={'person':{'id':pid,'fullName':f'P{pid}'}}
        if confirmed: row['battingOrder']=str(slot*100)
        out[f'ID{pid}']=row
    return out

def current_box(confirmed_away=False):
    return {'teams':{'away':{'players':side_players(range(101,111),confirmed_away)},'home':{'players':side_players(range(201,211),False)}}}

def prior_box(ids):
    return {'teams':{'away':{'players':side_players(ids,True)},'home':{'players':{}}}}

def prior_schedule():
    games=[]
    for day,pk in [('2026-08-11',901),('2026-08-10',900)]:
        games.append({'gamePk':pk,'gameDate':day+'T23:00:00Z','status':{'abstractGameState':'Final'},'teams':{'away':{'team':{'id':1}},'home':{'team':{'id':3}}}})
    return {'dates':[{'date':'2026-08-11','games':[games[0]]},{'date':'2026-08-10','games':[games[1]]}]}

class Tests(unittest.TestCase):
    def opener(self, req, timeout=15):
        url=req if isinstance(req,str) else req.full_url
        if '/api/v1/schedule?' in url: return Resp(prior_schedule())
        if '/api/v1/game/901/boxscore' in url: return Resp(prior_box(range(101,110)))
        if '/api/v1/game/900/boxscore' in url: return Resp(prior_box([101,102,103,104,105,106,107,108,999]))
        raise AssertionError(url)

    def test_projection_is_complete_projected_and_roster_filtered(self):
        row=project_team_lineup(game=snapshot(),side='away',current_boxscore=current_box(),now=NOW,opener=self.opener)
        self.assertIsNotNone(row)
        self.assertEqual(row['projection_status'],'PROJECTED')
        self.assertEqual([x['slot'] for x in row['rows']],list(range(1,10)))
        ids=[x['player_id'] for x in row['rows']]
        self.assertEqual(len(set(ids)),9)
        self.assertNotIn(999,ids)
        self.assertTrue(set(ids).issubset(set(range(101,111))))

    def test_official_complete_order_suppresses_projection(self):
        rows,failures=build_native_projected_lineups(schedule=[snapshot()],boxscores_by_game={999:current_box(confirmed_away=True)},now=NOW,opener=self.opener)
        self.assertFalse(any(r['side']=='away' for r in rows))
        self.assertFalse(any(f.get('side')=='away' for f in failures))

if __name__=='__main__': unittest.main()
