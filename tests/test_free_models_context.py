"""Offline regression tests: price, provenance, fail-closed context and CLI."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path

MOD = Path(__file__).resolve().parents[1] / 'artifacts' / 'free_models.py'
spec = importlib.util.spec_from_file_location('free_models_research', MOD)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)
NOW = datetime(2026, 10, 11, 13, 0, tzinfo=timezone.utc)
START = '2026-10-11T20:25:00Z'


def fixture_getter(url):
    if '/teams?limit=' in url:
        return {'sports':[{'leagues':[{'teams':[
            {'team': {'id':'1','displayName':'Detroit Lions','name':'Lions','abbreviation':'DET'}},
            {'team': {'id':'2','displayName':'Arizona Cardinals','name':'Cardinals','abbreviation':'ARI'}}
        ]}]}]}
    if 'scoreboard?' in url:
        return {'events':[{'id':'event1','date':START,
            'competitions':[{'venue': {'indoor': False,'address': {'city':'Phoenix','state':'Arizona'}},
                             'competitors':[
                {'homeAway':'away','team':{'id':'1','displayName':'Detroit Lions','abbreviation':'DET'}},
                {'homeAway':'home','team':{'id':'2','displayName':'Arizona Cardinals','abbreviation':'ARI'}}]}]}]}
    if '/schedule?' in url:
        identity = '1' if '/teams/1/' in url else '2'
        other = '2' if identity == '1' else '1'
        games = []
        for day in ('2026-09-01','2026-09-08','2026-09-15','2026-09-22','2026-09-29'):
            games.append({'date':day+'T18:00:00Z','status':{'type':{'completed':True}},
                          'competitions':[{'competitors':[
                              {'team':{'id':identity},'score':'24'},
                              {'team':{'id':other},'score':'18'}]}]})
        # Future-scored game must NOT leak into features
        games.append({'date':'2026-10-18T20:00:00Z','status':{'type':{'completed':True}},
                      'competitions':[{'competitors':[
                          {'team':{'id':identity},'score':'99'},
                          {'team':{'id':other},'score':'0'}]}]})
        return {'events':games}
    if '/injuries' in url:
        return {'injuries':[{'status':'Out', 'athlete':{'id':'8', 'position':{'abbreviation':'WR'}}}]}
    if 'geocoding-api' in url:
        return {'results':[{'name':'Phoenix','admin1':'Arizona','latitude':33.4,'longitude':-112.1}]}
    if 'api.open-meteo.com' in url:
        return {'hourly':{'time':['2026-10-11T20:00'],
                          'wind_speed_10m':[19],'precipitation_probability':[10]}}
    raise AssertionError('unexpected remote '+url)


def line(**kw):
    x = {'sport':'NFL','game':'Detroit Lions @ Arizona Cardinals',
         'market':'total','side':'UNDER','line':54.5,'odds':-102}
    x.update(kw)
    return x


def test_context_binds_both_teams_future_game_weather_and_ignores_future_scores():
    x = model.run({'lines':[line()]}, now=NOW, getter=fixture_getter)
    assert x['summary']['rows'] == 1
    assert x['edges'] or x['diagnostics']
    output = model.calculate(line(),model.PublicContext(NOW,fixture_getter),NOW)
    assert output['context']['home_rating'] == 0.72
    assert output['context']['away_rating'] == 0.72
    assert output['context']['home_injury_pts'] == -0.15
    assert output['context']['weather_total_adj'] == -0.8
    assert output['kickoff_utc'] == '2026-10-11T20:25:00+00:00'
    assert output['research_only'] is True
    assert output['official_authority'] is False


def test_context_does_not_invent_missing_team_or_kickoff():
    obj = model.run({'lines':[{'sport':'CFB','home':'A', 'away':'B',
                               'market':'SPREAD','side':'HOME','line':-3,'odds':-110}]},
                    now=NOW,getter=lambda _: {})
    assert obj['edges'] == []
    assert obj['summary']['status_counts']['BLOCKED_KICKOFF_UNVERIFIED'] == 1


def test_manual_override_and_push_aware_ev():
    x = model.run({'lines':[line(commence_time=START,context={'weather_total_adj':-3.0})]},
                  now=NOW,auto_context=False)
    obj = (x['edges'] or [])
    if obj:
        assert obj[0]['context']['weather_total_adj'] == -3.0
    total = model.calculate(line(commence_time=START,line=54,context={'weather_total_adj':-3}),
                            model.PublicContext(NOW),NOW,auto_context=False)
    assert total['push_p'] > 0
    expected = total['estimate_p']*(100/102)-(1-total['estimate_p']-total['push_p'])
    assert abs(total['ev_per_dollar']-expected) < 1e-5


def test_ml_mlb_poisson_and_price_cap():
    score = model.calculate({'sport':'MLB','away':'A','home':'B','market':'ML',
                             'side':'HOME','odds':-180,'kickoff':START},
                            model.PublicContext(NOW),NOW,auto_context=False)
    assert score['status'] == 'PRICE_CAP'
    assert 0 < score['estimate_p'] < 1
    assert score['push_p'] == 0


def test_unvalidated_props_rejected_and_no_quotes_fabricated():
    x = model.run({'lines':[line(market='PLAYER_RECEPTIONS')]},now=NOW,auto_context=False)
    assert x['summary']['status_counts']['BLOCKED_INVALID'] == 1
    assert x['edges'] == []


def test_old_kickoff_rejected_without_fetch():
    x = model.run({'lines':[line(kickoff='2026-10-10T18:00:00Z')]},
                  now=NOW,getter=lambda url: (_ for _ in ()).throw(AssertionError('called')))
    assert x['summary']['status_counts']['BLOCKED_STARTED'] == 1


def test_normalized_sides_do_not_reverse_spread_sign():
    home = model.calculate({'sport':'NFL','home':'ARI','away':'DET',
        'market':'spread','side':'home','line':-2.5,'odds':-110,'kickoff':START},
        model.PublicContext(NOW),NOW,auto_context=False)
    away = model.calculate({'sport':'NFL','home':'ARI','away':'DET',
        'market':'spread','side':'away','line':2.5,'odds':-110,'kickoff':START},
        model.PublicContext(NOW),NOW,auto_context=False)
    assert abs(home['estimate_p']+away['estimate_p']-1) < 1e-5
