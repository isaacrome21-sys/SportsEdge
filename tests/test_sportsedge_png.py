"""PNG must be usable from GitHub Actions on a phone; never invent absent values."""
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

SPEC=importlib.util.spec_from_file_location("sportsedge_png",Path(__file__).resolve().parents[1]/"scripts"/"render_sportsedge_png.py")
png=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(png)


def test_all_three_sports_produce_actual_png_with_correct_dimensions():
    examples={
        "NFL":{"sport":"NFL","games":[{"away":"PHI","home":"JAX","markets":[
            {"market":"total","lean":{"engine_status":"RESEARCH_CANDIDATE_NOT_VALIDATED","selection":"Over","line":41.5,"price_american":-110,
             "estimate_p":.56,"ev_per_dollar":.069,"edge_probability_points":.06}}]}]},
        "CFB":{"sport":"CFB","results":[{"matchup":"A @ B","market":"TOTAL","side":"OVER",
            "line":52.5,"american_odds":-110,"model_p":.55,"expected_roi":.05,
            "edge":.04,"engine_status":"RESEARCH_CANDIDATE_NOT_VALIDATED","bet_status":"LEAN"}]},
        "MLB":{"sport":"MLB","results":[{"matchup":"A @ B","market":"MONEYLINE","side":"AWAY",
            "american_odds":110,"estimate_p":.55,"ev_per_dollar":.155,"edge":.07,
            "engine_status":"RESEARCH_CANDIDATE_NOT_VALIDATED","scored_status":"ACTIONABLE"}]}
    }
    with TemporaryDirectory() as t:
        for sport,card in examples.items():
            target=Path(t)/f"{sport.lower()}.png"
            result=png.render(card,sport,target,Path(t)/"no-assets")
            assert target.read_bytes()[:8]==b"\x89PNG\r\n\x1a\n"
            with Image.open(target) as img:
                assert img.size==(1440,1580)
            assert result["best"]+result["leans"]==1


def test_missing_model_is_not_promoted_to_best_or_zero_filled():
    card={"sport":"CFB","results":[{"matchup":"A @ B","market":"TOTAL",
           "side":"OVER","american_odds":-110,"model_p":None,
           "expected_roi":None,"edge":None,"engine_status":"RESEARCH_CANDIDATE_NOT_VALIDATED","bet_status":"CANDIDATE"}]}
    rows=png.as_rows(card,"CFB")
    assert len(rows)==1
    assert rows[0]["status"]=="LEAN"
    assert rows[0]["est"] is None and rows[0]["ev"] is None
    assert png.fmt_pct(None)=="MISSING" and png.fmt_prob(None)=="MISSING"


def test_ranking_is_ev_then_edge_and_score_never_controls_rank():
    card={"results":[
        {"matchup":"A @ B","market":"TOTAL","side":"OVER","american_odds":-110,
         "estimate_p":.55,"ev_per_dollar":.07,"edge":.04,"confidence_score":10,"engine_status":"RESEARCH_CANDIDATE_NOT_VALIDATED","scored_status":"ACTIONABLE"},
        {"matchup":"A @ B","market":"TOTAL","side":"UNDER","american_odds":-110,
         "estimate_p":.55,"ev_per_dollar":.04,"edge":.09,"confidence_score":99,"engine_status":"RESEARCH_CANDIDATE_NOT_VALIDATED","scored_status":"ACTIONABLE"}
    ]}
    out=png.as_rows(card,"MLB")
    assert [r["side"] for r in out]==["OVER","UNDER"]


def test_multigame_png_shows_actual_lean_matchup_never_first_game_false_context():
    from unittest.mock import patch
    captured=[]
    original=png.text_fit
    def record(draw,x,y,raw,maximum,*,fill,face):
        captured.append(str(raw))
        return original(draw,x,y,raw,maximum,fill=fill,face=face)
    payload={"games":[
        {"away":"CHI","home":"GB","context":{"starters":"FIRST GAME QB ONLY"},"markets":[]},
        {"away":"DET","home":"ARI","markets":[{"market":"total","lean":{"engine_status":"RESEARCH_CANDIDATE_NOT_VALIDATED",
          "selection":"Under","line":54.5,"price_american":-102,
          "estimate_p":.529,"edge_probability_points":.048,
          "ev_per_dollar":.048,"lean_reason":"UNVALIDATED"}}]}
    ]}
    with TemporaryDirectory() as temp,patch.object(png,"text_fit",side_effect=record),patch.object(png,"mascot") as logos:
        target=Path(temp)/"slate.png"
        result=png.render(payload,"NFL",target,Path(temp))
        assert result["leans"]==1
        assert target.is_file()
        assert "NFL MULTI-GAME SLATE" in captured
        assert any("#1  DET @ ARI" in t for t in captured)
        assert not any("FIRST GAME QB ONLY" in t for t in captured)
        logos.assert_not_called()
