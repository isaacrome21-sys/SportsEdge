from datetime import datetime, timezone
import json
from scripts.cfb_evidence_jobs import due_starts, eligible_close_rows, select_closes

NOW = datetime(2026, 10, 24, 18, 55, tzinfo=timezone.utc)
START = '2026-10-24T19:00:00+00:00'

def board():
    return {'away':'Away','home':'Home','start_ts':START,'total':[50.5,-110,-110],
            'quote_observed_at_by_market':{'totals':NOW.isoformat()},'recorded_at_utc':NOW.isoformat()}

def test_only_upcoming_pre_games():
    events = [{'date':START, 'status':{'type':{'state':'pre'}}},
              {'date':START, 'status':{'type':{'state':'in'}}},
              {'date':NOW.isoformat(), 'status':{'type':{'state':'pre'}}}]
    assert due_starts({'events':events},NOW) == [datetime.fromisoformat(START)]

def test_poststart_stale_and_future_quotes_are_never_close():
    g=board()
    assert len(eligible_close_rows([g],now=NOW,target_starts={datetime.fromisoformat(START)})) == 1
    assert eligible_close_rows([g],now=datetime.fromisoformat(START),target_starts={datetime.fromisoformat(START)}) == []
    for stamp in ['2026-10-24T18:50:00Z','2026-10-24T18:56:00Z']:
        g['quote_observed_at_by_market']['totals']=stamp
        assert eligible_close_rows([g],now=NOW,target_starts={datetime.fromisoformat(START)}) == []

def test_select_latest_prestart_exact_game(tmp_path):
    earlier=board(); later=dict(earlier,recorded_at_utc='2026-10-24T18:58:00Z',total=[51.5,-108,-112])
    post=dict(later,recorded_at_utc=START,total=[60.5,-110,-110])
    other=dict(later,start_ts='2026-11-24T19:00:00Z')
    path=tmp_path/'close_board.json';path.write_text(json.dumps([earlier,later,post,other]))
    ledger={'plays':[{'away':'Away','home':'Home','start_ts':START}]}
    assert select_closes(ledger,[path]) == [later]
