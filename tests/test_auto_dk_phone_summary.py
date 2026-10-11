"""Daily phone summary only publishes real market/model artifact values."""
import importlib.util
import json
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
          {"away":"CHI","home":"GB","markets":[{"market":"total","lean":{
            "selection":"Under","line":47.5,"price_american":-108,
            "estimate_p":.55,"edge_probability_points":.06,"ev_per_dollar":.07,
            "lean_reason":"LEAN_ONLY:NO_PROVEN_EDGE"}}]}]}))
        (root/"cfb_card.json").write_text(json.dumps({"results":[
          {"bet_status":"LEAN","matchup":"Texas @ Oklahoma","market":"SPREAD",
           "side":"AWAY","line":4.5,"american_odds":-110,
           "model_p":.56,"edge":.04,"expected_roi":.066,
           "reason":"MODEL_EDGE_NOT_VALIDATED_VS_CLOSE"}]}))
        result=card.render(root,"https://github.com/example/repo/actions/runs/123")
        assert "NFL · READY" in result
        assert "CFB · MODEL_READY" in result
        assert "Under 47.5" in result
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
        def simple_card(a,b,ev):
            return {"games":[{"away":a,"home":b,"markets":[{"market":"total","lean":{
                "selection":"Under","line":54.5,"price_american":-105,
                "estimate_p":.54,"edge_probability_points":.04,
                "ev_per_dollar":ev,"lean_reason":"TRACK_ONLY"}}]}]}
        (root/"nfl_sunday.json").write_text(json.dumps(simple_card("DET","ARI",.048)))
        (root/"nfl_thursday.json").write_text(json.dumps(simple_card("BUF","LAR",.10)))
        result=card.render(root,"https://example.com",as_of_date="2026-10-11")
        a=result.index("NFL slate: Sun Oct 11 · TODAY")
        b=result.index("NFL slate: Thu Oct 15 · UPCOMING")
        assert a<b
        assert "DET @ ARI" in result[a:b]
        assert "BUF @ LAR" not in result[a:b]
        assert "BUF @ LAR" in result[b:]
