import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.update_nfl_forward_state import export_mode, plan, close_mode
from sportsedge.core.clv.nfl_forward_capture import build_forward_decision_rows
from sportsedge.sports.nfl.m2 import NFLM2ScoreModel, NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID
from sportsedge.sports.nfl.model_artifact import build_nfl_m2_model_artifact


class NFLForwardStateTests(unittest.TestCase):
    def _model_artifact(self, path: Path):
        model=NFLM2ScoreModel(
            model_id=PRODUCTION_NFL_M2_MODEL_ID,
            feature_contract=NFL_M2_FEATURE_CONTRACT,
            feature_names=("x",), feature_means=(0.0,), feature_scales=(1.0,),
            margin_coefficients=(1.0,0.0), total_coefficients=(44.0,0.0),
            train_seasons=(2022,2023,2024,2025), ridge_alpha=10.0,
            margin_sigma=13.0,total_sigma=10.0,residual_correlation=0.0,
            residual_pairs=((1.0,1.0),(-1.0,-1.0)),
        )
        payload=build_nfl_m2_model_artifact(model,code_git_sha="1"*40,source_manifest_sha256="a"*64)
        path.write_text(json.dumps(payload,sort_keys=True)+"\n",encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _event(self, *, spread=-3.0,total=45.5):
        return {"id":"evt-1","sport_key":"americanfootball_nfl","commence_time":"2026-09-11T00:20:00Z","home_team":"Alpha Aces","away_team":"Beta Bears","bookmakers":[{"key":"draftkings","markets":[
            {"key":"h2h","outcomes":[{"name":"Alpha Aces","price":-120},{"name":"Beta Bears","price":100}]},
            {"key":"spreads","outcomes":[{"name":"Alpha Aces","price":-110,"point":spread},{"name":"Beta Bears","price":-110,"point":-spread}]},
            {"key":"totals","outcomes":[{"name":"Over","price":-105,"point":total},{"name":"Under","price":-115,"point":total}]},
        ]}]}

    def _game(self):
        return {"game_id":"2026_01_BET_ALP","game_start_ts":"2026-09-11T00:20:00+00:00","home_team":"ALP","away_team":"BET","provider_home_team":"Alpha Aces","provider_away_team":"Beta Bears"}

    def _decisions(self, model_hash: str):
        dist=[
            {"home_score":31,"away_score":20,"margin":11,"total":51},
            {"home_score":28,"away_score":20,"margin":8,"total":48},
            {"home_score":27,"away_score":20,"margin":7,"total":47},
            {"home_score":24,"away_score":20,"margin":4,"total":44},
            {"home_score":17,"away_score":20,"margin":-3,"total":37},
        ]
        rows=build_forward_decision_rows(self._game(),self._event(),dist,captured_at="2026-09-10T23:10:00+00:00",identity={"code_git_sha":"1"*40,"model_id":PRODUCTION_NFL_M2_MODEL_ID,"feature_contract":NFL_M2_FEATURE_CONTRACT,"model_artifact_sha256":model_hash})
        for row in rows: row["live_feature_source_manifest_sha256"]="b"*64
        return rows

    def _write_jsonl(self,path,rows):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text("".join(json.dumps(x,sort_keys=True)+"\n" for x in rows),encoding="utf-8")

    def test_plan_uses_eastern_nflverse_clock_and_never_redecides_game(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); state=root/"state"; state.mkdir()
            schedule=root/"games.csv"
            schedule.write_text("season,week,game_type,game_id,gameday,gametime,home_team,away_team\n2026,1,REG,2026_01_BET_ALP,2026-09-10,20:20,ALP,BET\n",encoding="utf-8")
            p=plan(schedule,state,__import__('datetime').datetime.fromisoformat("2026-09-10T23:10:00+00:00"),decision_min=45,decision_max=120,close_min=2,close_max=20)
            self.assertTrue(p["decision_due"])
            self.assertEqual(p["decision_game_ids"],["2026_01_BET_ALP"])
            self._write_jsonl(state/"decisions.jsonl",[{"game_id":"2026_01_BET_ALP","market":"spread","side":"ALP","book":"draftkings","gate_result":"REJECTED_NO_POSITIVE_EV"}])
            p=plan(schedule,state,__import__('datetime').datetime.fromisoformat("2026-09-10T23:10:00+00:00"),decision_min=45,decision_max=120,close_min=2,close_max=20)
            self.assertFalse(p["decision_due"])

    def test_close_is_partial_and_original_threshold_failures_stay_unpublished(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); state=root/"state"; state.mkdir(); model=root/"model.json"; model_hash=self._model_artifact(model)
            decisions=self._decisions(model_hash)
            self._write_jsonl(state/"decisions.jsonl",decisions)
            odds=root/"odds"; odds.mkdir()
            moved=self._event(spread=-3.5,total=46.0)
            (odds/"evt-1.json").write_text(json.dumps(moved),encoding="utf-8")
            result=close_mode(state,model,odds,__import__('datetime').datetime.fromisoformat("2026-09-11T00:10:00+00:00"))
            self.assertGreaterEqual(result["unresolved_original_threshold"],1)
            exported=export_mode(state,root/"out")
            self.assertLess(exported["complete_pair_count"],sum(r["gate_result"] in {"SHADOW_QUALIFIED","OFFICIAL"} for r in decisions))

    def test_export_excludes_rejected_rows_even_when_a_close_exists(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); state=root/"state"; state.mkdir(); model=root/"model.json"; model_hash=self._model_artifact(model)
            decisions=self._decisions(model_hash)
            rejected=dict(decisions[0]); rejected["game_id"]="rejected-game"; rejected["market"]="moneyline"; rejected["side"]="X"; rejected["gate_result"]="REJECTED_NO_POSITIVE_EV"
            qualifying=[r for r in decisions if r["gate_result"] in {"SHADOW_QUALIFIED","OFFICIAL"}]
            rows=qualifying+[rejected]
            self._write_jsonl(state/"decisions.jsonl",rows)
            closes=[]
            for d in rows:
                closes.append({"game_id":d["game_id"],"market":d["market"],"side":d["side"],"book":d["book"],"sport":"nfl"})
            self._write_jsonl(state/"closes.jsonl",closes)
            result=export_mode(state,root/"out")
            self.assertEqual(result["complete_pair_count"],len(qualifying))
            exported=(root/"out"/"nfl_forward_decisions.jsonl").read_text()
            self.assertNotIn("rejected-game",exported)


if __name__=="__main__": unittest.main()
