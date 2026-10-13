"""Daily phone summary only publishes real market/model artifact values."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

M=Path(__file__).resolve().parents[1]/"scripts"/"render_auto_dk_phone_summary.py"
sp=importlib.util.spec_from_file_location("auto_summary",M)
card=importlib.util.module_from_spec(sp)
sp.loader.exec_module(card)


def test_nfl_ev_ranking_not_score_or_raw_price():
    payload={"games":[{"away":"CIN","home":"MIA","markets":[
        {"market":"total","lean":{"selection":"Under","line":43.5,"price_american":-105,
         "estimate_p":.53,"edge_probability_points":.04,"ev_per_dollar":.03,
         "score_0_100":99,"lean_reason":"UNVALIDATED"}},
        {"market":"total","lean":{"selection":"Over","line":43.5,"price_american":-108,
         "estimate_p":.55,"edge_probability_points":.05,"ev_per_dollar":.06,
         "score_0_100":10,"lean_reason":"UNVALIDATED"}}
    ]}]}
    rows=card.candidates("NFL",payload)
    assert [r["side"] for r in rows]==["Over","Under"]
    assert all(r["role"]=="LEAN" for r in rows)


def test_cfb_missing_model_never_promotes_market_p_to_estimate():
    rows=card.candidates("CFB",{"results":[
      {"bet_status":"TRACK","market":"TOTAL","market_p":.60,
       "model_p":None,"american_odds":-110},
      {"bet_status":"LEAN","matchup":"A @ B","market":"TOTAL","side":"OVER",
       "line":51.5,"american_odds":-110,"model_p":.55,"edge":.05,
       "expected_roi":.05,"reason":"MODEL_EDGE_NOT_VALIDATED_VS_CLOSE"}]})
    assert len(rows)==1
    assert rows[0]["estimate_p"]==.55
    assert rows[0]["role"]=="LEAN"


def test_phone_issue_summary_includes_actual_dk_rows_and_missing_notice():
    with TemporaryDirectory() as temp:
        root=Path(temp)
        (root/"summary.json").write_text(json.dumps({
          "NFL":{"status":"READY","cards":[{"json":"artifacts/auto_dk_cards/nfl_card.json","state":"READY"}]},
          "CFB":{"status":"MODEL_READY","cards":[{"json":"artifacts/auto_dk_cards/cfb_card.json",
                   "state":"MODEL_READY","model_status":"MODEL_SDV_PUBLIC_LIVE_UNVALIDATED",
                   "priced_rows":12}],"unmatched_games":1}
        }))
        (root/"nfl_card.json").write_text(json.dumps({"games":[
          {"away":"CHI","home":"GB","commence_time":"2026-10-11T17:00:00Z","markets":[{"market":"total","quote_retrieved_at":"2026-10-11T13:59:00Z","lean":{
            "selection":"Under","line":47.5,"price_american":-108,
            "estimate_p":.55,"edge_probability_points":.06,"ev_per_dollar":.07,
            "lean_reason":"LEAN_ONLY:NO_PROVEN_EDGE"}}]}]}))
        (root/"cfb_card.json").write_text(json.dumps({"results":[
          {"bet_status":"LEAN","matchup":"Texas @ Oklahoma","market":"SPREAD",
           "side":"AWAY","line":4.5,"american_odds":-110,
           "model_p":.56,"edge":.04,"expected_roi":.066,
           "reason":"MODEL_EDGE_NOT_VALIDATED_VS_CLOSE"}]}))
        result=card.render(root,"https://github.com/example/repo/actions/runs/123",
                           asof=datetime(2026,10,11,14,0,tzinfo=timezone.utc))
        assert "NFL · READY" in result
        assert "CFB · MODEL_READY" in result
        assert "Under 47.5" in result
        assert "kickoff Sun Oct 11 12:00 PM CT" in result
        assert "DK quote Sun Oct 11 8:59 AM CT" in result
        assert "edge +6.0%" in result
        assert "estimate 56.0%" in result
        assert "out-of-sample validation" in result
        assert "unmatched games: 1" in result
        assert "/actions/runs/123" in result

def test_nfl_today_and_thursday_are_separate_date_sections():
    with TemporaryDirectory() as temp:
        root=Path(temp)
        (root/"summary.json").write_text(json.dumps({
          "NFL":{"status":"READY","cards":[
            {"json":"nfl_sunday.json","date":"2026-10-11","state":"READY"},
            {"json":"nfl_thursday.json","date":"2026-10-15","state":"READY"}
          ]},"CFB":{"status":"NO_DK_GAMES","cards":[]}
        }))
        def simple_card(a,b,ev,kickoff):
            return {"games":[{"away":a,"home":b,"commence_time":kickoff,"markets":[{"market":"total","lean":{
                "selection":"Under","line":54.5,"price_american":-105,
                "estimate_p":.54,"edge_probability_points":.04,
                "ev_per_dollar":ev,"lean_reason":"TRACK_ONLY"}}]}]}
        (root/"nfl_sunday.json").write_text(json.dumps(simple_card("DET","ARI",.048,"2026-10-11T20:25:00Z")))
        (root/"nfl_thursday.json").write_text(json.dumps(simple_card("BUF","LAR",.10,"2026-10-15T22:00:00Z")))
        result=card.render(root,"https://example.com",as_of_date="2026-10-11",
                           asof=datetime(2026,10,11,14,0,tzinfo=timezone.utc))
        a=result.index("NFL slate: Sun Oct 11 · TODAY")
        b=result.index("NFL slate: Thu Oct 15 · UPCOMING")
        assert a<b
        assert "DET @ ARI" in result[a:b]
        assert "BUF @ LAR" not in result[a:b]
        assert "BUF @ LAR" in result[b:]


def test_nfl_london_game_started_is_not_a_pregame_candidate():
    with TemporaryDirectory() as temp:
        root=Path(temp)
        (root/"summary.json").write_text(json.dumps({
          "NFL":{"status":"READY","cards":[{"json":"nfl.json","date":"2026-10-11","state":"READY"}]},
          "CFB":{"status":"NO_DK_GAMES","cards":[]}
        }))
        def game(away,home,kickoff,side):
            return {"away":away,"home":home,"commence_time":kickoff,
                    "markets":[{"market":"total","quote_retrieved_at":"2026-10-11T13:00:00Z",
                       "lean":{"selection":side,"line":42.5,"price_american":-110,
                       "estimate_p":.55,"edge_probability_points":.05,
                       "ev_per_dollar":.05,"lean_reason":"RESEARCH_ONLY"}}]}
        (root/"nfl.json").write_text(json.dumps({"games":[
          game("PHI","JAX","2026-10-11T13:30:00Z","Over"),
          game("CIN","MIA","2026-10-11T17:00:00Z","Under")
        ]}))
        output=card.render(root,"https://example.com",as_of_date="2026-10-11",
            asof=datetime(2026,10,11,14,0,tzinfo=timezone.utc))
        assert "PHI @ JAX" not in output
        assert "CIN @ MIA" in output
        assert "game starts invalidate pregame prices" in output


def test_unknown_kickoff_not_listed_as_pregame_pick():
    with TemporaryDirectory() as temp:
        root=Path(temp)
        (root/"summary.json").write_text(json.dumps({
          "NFL":{"status":"READY","cards":[{"json":"nfl.json","date":"2026-10-11","state":"READY"}]},
          "CFB":{"status":"NO_DK_GAMES","cards":[]}
        }))
        (root/"nfl.json").write_text(json.dumps({"games":[
           {"away":"CIN","home":"MIA","markets":[{"market":"total","lean":{
                "selection":"Under","line":43.5,"price_american":-105,
                "estimate_p":.53,"edge_probability_points":.04,"ev_per_dollar":.033}}]}
        ]}))
        out=card.render(root,"https://example.com",as_of_date="2026-10-11",
             asof=datetime(2026,10,11,14,0,tzinfo=timezone.utc))
        assert "CIN @ MIA" not in out
        assert "No priced NFL candidates" in out


def test_research_prop_surface_only_displays_real_selected_model_rows():
    from datetime import datetime,timezone
    with TemporaryDirectory() as temp:
        root=Path(temp)
        (root/"summary.json").write_text(json.dumps({
          "NFL":{"status":"READY","cards":[
             {"date":"2026-10-11","json":"nfl.json","state":"READY",
              "props":{"status":"RESEARCH_ONLY","json":"nfl_prop.json"}}]},
          "CFB":{"status":"NO_DK_GAMES","cards":[]}
        }))
        (root/"nfl.json").write_text(json.dumps({"games":[
           {"away":"CIN","home":"MIA","commence_time":"2026-10-11T17:00:00Z","markets":[]}
        ]}))
        (root/"nfl_prop.json").write_text(json.dumps({"selected_rows":[
           {"status":"PRICED","player":"Sample RB","market":"rushing_yards",
            "selection":"Sample RB Over","line":61.5,"price_american":-110,
            "estimate_p":.58,"edge_probability_points":.06,"ev_per_dollar":.11},
           {"status":"NO_MODEL","player":"Another RB","market":"rushing_yards",
            "selection":"Another RB Over","line":41.5,"price_american":-110,
            "estimate_p":None,"edge_probability_points":None,"ev_per_dollar":None}
        ]}))
        result=card.render(root,"https://github.com/example",
                           asof=datetime(2026,10,11,15,10,tzinfo=timezone.utc),
                           as_of_date="2026-10-11")
        assert "Sample RB rushing_yards" in result
        assert "estimate 58.0%" in result
        assert "EV +11.0%" in result
        assert "Another RB Over" not in result
        assert "RESEARCH ONLY" in result


def test_radar_requires_market_exact_fresh_peer_receipts():
    """A fresh DK leg never launders old or unidentified peer-book odds."""
    with TemporaryDirectory() as temp:
        root=Path(temp)/"auto_dk_cards"
        (root.parent/"auto_dk").mkdir()
        root.mkdir()
        now=datetime(2026,10,11,17,1,tzinfo=timezone.utc)
        fresh="2026-10-11T17:00:00Z"
        from scripts.collect_auto_dk_four_sports import _pair_fair
        peer_prices={"line":45.5,"over":-117,"under":101}
        base={
            "status":"READY",
            "games":[{
                "provider_event_id":"game_1","away":"BUF","home":"LAR",
                "commence_time":"2026-10-11T19:00:00Z",
                "markets":{"totals":{"line":45.5,"over":100,"under":-120,
                                     "observed_at":fresh}},
                "reference":{"totals":{
                    "method":"PINNACLE_POWER_V1","fair":_pair_fair(peer_prices),
                    "books":["pinnacle"],"model_probability":None,
                    "provider_event_id":"game_1","market_key":"totals",
                    "dk_observed_at":fresh,"dk_line":45.5,
                    "peer_evidence":[{"book":"pinnacle","observed_at":fresh,"line":45.5}],
                    "peer_price_pairs":[{"book":"pinnacle","prices":{"over":-117,"under":101}}],
                }},
            }],
        }
        import copy
        def scan(edit=None):
            state=copy.deepcopy(base)
            if edit:
                edit(state["games"][0]["reference"]["totals"])
            (root.parent/"auto_dk"/"nfl_odds.json").write_text(json.dumps(state))
            return card.nfl_market_price_radar(root,now)[0]
        assert len(scan()) == 1
        assert scan(lambda ref: ref["peer_evidence"][0].update(observed_at="2026-10-11T16:45:00Z")) == []
        # Both timestamps are <10 minutes old, but three minutes apart;
        # a peer price this far from DK is not a paired price opportunity.
        assert scan(lambda ref: ref["peer_evidence"][0].update(observed_at="2026-10-11T16:57:00Z")) == []
        assert scan(lambda ref: ref.update(peer_evidence=[None])) == []
        assert scan(lambda ref: ref.update(books=[{"unhashable":"book"}])) == []
        assert scan(lambda ref: ref.update(books=["pinnacle","pinnacle"])) == []
        assert scan(lambda ref: ref["peer_evidence"][0].update(line=46.5)) == []
        assert scan(lambda ref: ref.update(provider_event_id="wrong")) == []
        assert scan(lambda ref: ref.update(peer_evidence=[])) == []
        assert scan(lambda ref: ref.update(dk_observed_at="2026-10-11T16:45:00Z")) == []
        # A price-only positive discrepancy cannot use an unbound or edited
        # reference probability, even when book names and clocks match.
        assert scan(lambda ref: ref["fair"].__setitem__(0,.85)) == []
        assert scan(lambda ref: ref["peer_price_pairs"][0]["prices"].update(over=-125)) == []
        assert scan(lambda ref: ref.update(peer_price_pairs=[])) == []
