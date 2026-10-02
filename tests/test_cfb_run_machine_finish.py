from __future__ import annotations

import json
import unittest
from pathlib import Path
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from sportsedge.sports.cfb.classification_policy import CFBClassificationError
from sportsedge.sports.cfb.joint_model import (
    CFBJointScoreModel, CFBModelError, CFB_FEATURE_CONTRACT, CFB_JOINT_MODEL_ID,
    _feature_names, price_cfb_game_markets, simulate_cfb_joint_distribution,
)
from sportsedge.sports.cfb.run_machine import CFBRunMachineError, run_cfb_machine
from sportsedge.sports.cfb.team_total_readout import price_cfb_team_total
from sportsedge.sports.cfb.source import (
    CFBGame, CFBQuote, CFBSourceError, CFBTeamMetrics, attach_weather,
    bind_provider_team, build_team_alias_index, parse_the_odds_api_quotes,
)

NOW = datetime(2026, 8, 26, 17, 0, tzinfo=timezone.utc)
START = datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc)


def metric(team, bump=0.0):
    return CFBTeamMetrics(
        team=team, season=2025, through_week=99, sample_source="PRIOR_SEASON_FALLBACK",
        off_ppa_rush=.11+bump, off_ppa_dropback=.19+bump, def_ppa_rush_allowed=.05-bump,
        def_ppa_dropback_allowed=.08-bump, off_success_rate=.46+bump/10,
        def_success_rate_allowed=.42-bump/10, standard_down_ppa=.13+bump,
        passing_down_success_rate=.39+bump/10, eckel_rate=.31+bump/10,
        points_per_eckel=4.7+bump, points_per_drive=2.3+bump, net_field_position=1.8+bump,
        explosive_rate=.12+bump/10, feature_asof_ts=NOW.isoformat())


def game():
    return CFBGame("1001", 2026, 1, START.isoformat(), "Alpha State", "Beta Tech", False,
                   "Test Stadium", {"game_indoor": False, "wind_speed": 7.0, "temperature": 76.0})


def model(home=28, away=21, overtime=True):
    n = len(_feature_names())
    return CFBJointScoreModel(
        CFB_JOINT_MODEL_ID, CFB_FEATURE_CONTRACT, _feature_names(), (0.0,)*n, (1.0,)*n,
        (float(home),)+(0.0,)*n, (float(away),)+(0.0,)*n,
        ((0.0,0.0),(1.0,-1.0),(-1.0,1.0),(2.0,0.0)),
        ((6,0),(0,6)) if overtime else (), (2024,2025), 10.0)


def row():
    g = game()
    return {"game_id":g.game_id,"season":g.season,"week":g.week,"neutral_site":False,
            "home_metrics":metric("Alpha State").to_dict(),"away_metrics":metric("Beta Tech",.02).to_dict(),
            "weather":dict(g.weather)}


def quotes():
    ts = (NOW-timedelta(seconds=20)).isoformat()
    base = dict(game_id="1001",period="FG",entity_id="1001",book_key="draftkings",sportsbook="DraftKings",
                retrieved_at=ts,is_alternate=False)
    return [
        CFBQuote(market="MONEYLINE",side="HOME",line=0,american_odds=-150,offer_id="mlh",**base),
        CFBQuote(market="MONEYLINE",side="AWAY",line=0,american_odds=130,offer_id="mla",**base),
        CFBQuote(market="SPREAD",side="HOME",line=-3.5,american_odds=-110,offer_id="sph",**base),
        CFBQuote(market="SPREAD",side="AWAY",line=-3.5,american_odds=-110,offer_id="spa",**base),
        CFBQuote(market="TOTAL",side="OVER",line=49.5,american_odds=-105,offer_id="to",**base),
        CFBQuote(market="TOTAL",side="UNDER",line=49.5,american_odds=-115,offer_id="tu",**base)]


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.teams=[{"school":"Alpha State","abbreviation":"ASU","mascot":"Owls","alternateNames":["Alpha St."]},
                    {"school":"Beta Tech","abbreviation":"BT","mascot":"Bears","alternateNames":["Beta Institute"]}]
        self.idx=build_team_alias_index(self.teams)

    def test_exact_authorized_aliases_and_near_names(self):
        self.assertEqual(bind_provider_team("ASU",self.idx),"Alpha State")
        self.assertEqual(bind_provider_team("Alpha St.",self.idx),"Alpha State")
        for name in ("Alfa State","Alpha Stat","Beta Teck","B. Tech"):
            with self.subTest(name=name), self.assertRaisesRegex(CFBSourceError,"CFB_PROVIDER_TEAM_UNRESOLVED"):
                bind_provider_team(name,self.idx)

    def test_alias_collision_removed(self):
        idx=build_team_alias_index(self.teams+[{"school":"Gamma","abbreviation":"ASU","alternateNames":[]}])
        with self.assertRaises(CFBSourceError): bind_provider_team("ASU",idx)

    def test_real_three_market_normalization_uses_one_home_spread_identity(self):
        payload=[{"id":"evt1","home_team":"Alpha State","away_team":"Beta Tech","bookmakers":[{
            "key":"draftkings","title":"DraftKings","last_update":"2026-08-26T16:59:00Z","markets":[
                {"key":"h2h","outcomes":[{"name":"Alpha State","price":-150},{"name":"Beta Tech","price":130}]},
                {"key":"spreads","outcomes":[{"name":"Alpha State","price":-110,"point":-3.5},{"name":"Beta Tech","price":-110,"point":3.5}]},
                {"key":"totals","outcomes":[{"name":"Over","price":-105,"point":49.5},{"name":"Under","price":-115,"point":49.5}]}]}]}]
        out=parse_the_odds_api_quotes(payload,games=[game()],alias_index=self.idx)
        self.assertEqual(len(out),6); self.assertEqual({q.market for q in out},{"MONEYLINE","SPREAD","TOTAL"})
        self.assertEqual({q.line for q in out if q.market=="SPREAD"},{-3.5})
        self.assertTrue(all(len(q.offer_id)==64 for q in out))

    def test_unknown_provider_team_and_missing_weather_fail_closed(self):
        with self.assertRaises(CFBSourceError):
            parse_the_odds_api_quotes([{"id":"e","home_team":"Alfa State","away_team":"Beta Tech","bookmakers":[]}],games=[game()],alias_index=self.idx)
        with self.assertRaisesRegex(CFBSourceError,"CFB_WEATHER_MISSING"):
            attach_weather([replace(game(),weather=None)],{})


class JointModelTests(unittest.TestCase):
    def test_seed_is_explicit_and_deterministic(self):
        with self.assertRaisesRegex(CFBModelError,"CFB_EXPLICIT_INTEGER_SEED_REQUIRED"):
            simulate_cfb_joint_distribution(model(),row(),seed=None,n_paths=10)  # type: ignore[arg-type]
        a=simulate_cfb_joint_distribution(model(),row(),seed=1234,n_paths=200)
        b=simulate_cfb_joint_distribution(model(),row(),seed=1234,n_paths=200)
        self.assertEqual(a,b)

    def test_market_data_prohibited_and_lines_only_read_out(self):
        bad=row(); bad["spread_line"]=-3.5
        with self.assertRaisesRegex(CFBModelError,"CFB_MARKET_DATA_PROHIBITED"):
            simulate_cfb_joint_distribution(model(),bad,seed=1,n_paths=10)
        dist=simulate_cfb_joint_distribution(model(),row(),seed=33,n_paths=400)
        digest=sha256(json.dumps(dist,sort_keys=True).encode()).hexdigest()
        p1=price_cfb_game_markets(dist,spread_line=-6.5,total_line=49.5)
        p2=price_cfb_game_markets(dist,spread_line=-9.5,total_line=45.5)
        self.assertEqual(digest,sha256(json.dumps(dist,sort_keys=True).encode()).hexdigest())
        self.assertNotEqual(p1["spread"]["home"],p2["spread"]["home"])
        self.assertNotEqual(p1["total"]["over"],p2["total"]["over"])


    def test_team_total_readout_uses_team_score_only(self):
        dist=simulate_cfb_joint_distribution(model(),row(),seed=33,n_paths=400)
        digest=sha256(json.dumps(dist,sort_keys=True).encode()).hexdigest()
        home=price_cfb_team_total(dist,team_side="HOME",line=27.5)
        away=price_cfb_team_total(dist,team_side="AWAY",line=20.5)
        self.assertEqual(digest,sha256(json.dumps(dist,sort_keys=True).encode()).hexdigest())
        self.assertAlmostEqual(home["over"]+home["under"]+home["push"],1.0,places=12)
        self.assertAlmostEqual(away["over"]+away["under"]+away["push"],1.0,places=12)
        self.assertEqual(home["team_side"],"HOME")
        self.assertEqual(away["team_side"],"AWAY")

    def test_cfb_empirical_overtime_resolves_ties_and_missing_profile_blocks(self):
        tied=replace(model(24,24,True),residual_pairs=((0.0,0.0),))
        dist=simulate_cfb_joint_distribution(tied,row(),seed=7,n_paths=100)
        self.assertTrue(all(x["home_score"]!=x["away_score"] for x in dist))
        blocked=replace(model(24,24,False),residual_pairs=((0.0,0.0),))
        with self.assertRaisesRegex(CFBModelError,"CFB_OVERTIME_PROFILE_REQUIRED"):
            simulate_cfb_joint_distribution(blocked,row(),seed=7,n_paths=1)


class MachineTests(unittest.TestCase):
    def setUp(self):
        self.games=[game()]; self.metrics={"Alpha State":metric("Alpha State"),"Beta Tech":metric("Beta Tech",.02)}; self.q=quotes()
        self.teams=[{"school":"Alpha State","abbreviation":"ASU","mascot":"Owls","alternateNames":[]},
                    {"school":"Beta Tech","abbreviation":"BT","mascot":"Bears","alternateNames":[]}]
    def ft(self,**k): return list(self.teams)
    def fg(self,**k): return [replace(game(),weather=None)]
    def fm(self,**k): return dict(self.metrics)
    def fw(self,**k): return {"1001":dict(game().weather)}
    def fo(self,**k): return list(self.q)
    def manual(self, **kwargs):
        return run_cfb_machine(fbs_team_rows=self.teams, **kwargs)

    def test_manual_hybrid_auto_results_are_byte_identical(self):
        common=dict(season=2026,week=1,model=model(),now=NOW,n_paths=500,root_seed=44)
        m=self.manual(mode="MANUAL",games=self.games,metrics=self.metrics,quotes=self.q,**common)
        h=run_cfb_machine(mode="HYBRID",quotes=self.q,cfbd_api_key="cfbd",team_fetcher=self.ft,game_fetcher=self.fg,metric_fetcher=self.fm,weather_fetcher=self.fw,**common)
        a=run_cfb_machine(mode="AUTOMATIC",cfbd_api_key="cfbd",odds_api_key="odds",team_fetcher=self.ft,game_fetcher=self.fg,metric_fetcher=self.fm,weather_fetcher=self.fw,odds_fetcher=self.fo,**common)
        self.assertEqual(m.results,h.results); self.assertEqual(m.results,a.results); self.assertEqual(m.summary,a.summary)

    def test_all_three_readouts_share_one_distribution_and_seed(self):
        r=self.manual(mode="MANUAL",season=2026,week=1,model=model(),now=NOW,games=self.games,metrics=self.metrics,quotes=self.q,n_paths=500,root_seed=44)
        self.assertEqual({x.market for x in r.results},{"MONEYLINE","SPREAD","TOTAL"})
        self.assertEqual(len({x.distribution_sha256 for x in r.results}),1); self.assertEqual(len({x.seed for x in r.results}),1)

    def test_devig_both_sides_hold_and_promotion_block(self):
        r=self.manual(mode="MANUAL",season=2026,week=1,model=model(),now=NOW,games=self.games,metrics=self.metrics,quotes=self.q,n_paths=100)
        for market in ("MONEYLINE","SPREAD","TOTAL"):
            xs=[x for x in r.results if x.market==market]
            self.assertAlmostEqual(sum(x.fair_market_p for x in xs),1.0,places=12)
            self.assertEqual(len({x.hold for x in xs}),1)
        self.assertTrue(all(x.engine_status=="PRICED" and x.bet_status=="BLOCKED" for x in r.results))
        self.assertTrue(all(x.reason=="CFB_PROMOTION_EVIDENCE_REQUIRED" for x in r.results))


    def test_full_game_team_totals_are_priced_from_same_joint_distribution(self):
        ts=(NOW-timedelta(seconds=20)).isoformat()
        tt=[
            CFBQuote(game_id="1001",period="FG",market="TEAM_TOTAL",entity_id="Alpha State",side="OVER",line=27.5,
                     american_odds=-110,book_key="draftkings",sportsbook="DraftKings",retrieved_at=ts,offer_id="ttho",is_alternate=False),
            CFBQuote(game_id="1001",period="FG",market="TEAM_TOTAL",entity_id="Alpha State",side="UNDER",line=27.5,
                     american_odds=-110,book_key="draftkings",sportsbook="DraftKings",retrieved_at=ts,offer_id="tthu",is_alternate=False),
            CFBQuote(game_id="1001",period="FG",market="TEAM_TOTAL",entity_id="Beta Tech",side="OVER",line=20.5,
                     american_odds=-105,book_key="draftkings",sportsbook="DraftKings",retrieved_at=ts,offer_id="ttao",is_alternate=False),
            CFBQuote(game_id="1001",period="FG",market="TEAM_TOTAL",entity_id="Beta Tech",side="UNDER",line=20.5,
                     american_odds=-115,book_key="draftkings",sportsbook="DraftKings",retrieved_at=ts,offer_id="ttau",is_alternate=False),
        ]
        report=self.manual(mode="MANUAL",season=2026,week=1,model=model(),now=NOW,
                           games=self.games,metrics=self.metrics,quotes=[*self.q,*tt],n_paths=500,root_seed=44)
        team_rows=[x for x in report.results if x.market=="TEAM_TOTAL"]
        self.assertEqual(len(team_rows),4)
        self.assertTrue(all(x.engine_status=="PRICED" for x in team_rows))
        self.assertTrue(all(x.bet_status=="BLOCKED" and x.reason=="CFB_PROMOTION_EVIDENCE_REQUIRED" for x in team_rows))
        self.assertEqual(len({x.distribution_sha256 for x in report.results}),1)
        self.assertEqual(len({x.seed for x in report.results}),1)
        for entity in ("Alpha State","Beta Tech"):
            rows=[x for x in team_rows if x.offer_id.startswith("tth") ] if entity=="Alpha State" else [x for x in team_rows if x.offer_id.startswith("tta")]
            self.assertEqual(len(rows),2)
            self.assertAlmostEqual(sum(x.fair_market_p for x in rows),1.0,places=12)

    def test_team_total_unknown_entity_fails_closed(self):
        ts=(NOW-timedelta(seconds=20)).isoformat()
        bad=[
            CFBQuote(game_id="1001",period="FG",market="TEAM_TOTAL",entity_id="Unknown Team",side="OVER",line=20.5,
                     american_odds=-110,book_key="draftkings",sportsbook="DraftKings",retrieved_at=ts,offer_id="bad1",is_alternate=False),
            CFBQuote(game_id="1001",period="FG",market="TEAM_TOTAL",entity_id="Unknown Team",side="UNDER",line=20.5,
                     american_odds=-110,book_key="draftkings",sportsbook="DraftKings",retrieved_at=ts,offer_id="bad2",is_alternate=False),
        ]
        with self.assertRaisesRegex(CFBRunMachineError,"CFB_TEAM_TOTAL_ENTITY_UNRESOLVED"):
            self.manual(mode="MANUAL",season=2026,week=1,model=model(),now=NOW,
                        games=self.games,metrics=self.metrics,quotes=bad,n_paths=50)


    def test_team_total_invalid_side_fails_closed(self):
        ts=(NOW-timedelta(seconds=20)).isoformat()
        bad=[
            CFBQuote(game_id="1001",period="FG",market="TEAM_TOTAL",entity_id="Alpha State",side="HOME",line=27.5,
                     american_odds=-110,book_key="draftkings",sportsbook="DraftKings",retrieved_at=ts,offer_id="badside1",is_alternate=False),
            CFBQuote(game_id="1001",period="FG",market="TEAM_TOTAL",entity_id="Alpha State",side="AWAY",line=27.5,
                     american_odds=-110,book_key="draftkings",sportsbook="DraftKings",retrieved_at=ts,offer_id="badside2",is_alternate=False),
        ]
        with self.assertRaisesRegex(CFBRunMachineError,"CFB_TEAM_TOTAL_SIDE_INVALID"):
            self.manual(mode="MANUAL",season=2026,week=1,model=model(),now=NOW,
                        games=self.games,metrics=self.metrics,quotes=bad,n_paths=50)

    def test_market_surface_marks_cfb_team_total_implemented(self):
        surface=json.loads(Path("config/football_market_surface.json").read_text())
        declared=next(row for row in surface["markets"] if row["market"]=="team_total")
        self.assertEqual(declared["engine_state_by_sport"]["CFB"],"IMPLEMENTED")

    def test_alternate_spread_and_total_reuse_same_joint_distribution(self):
        ts = (NOW-timedelta(seconds=20)).isoformat()
        base = dict(
            game_id="1001",
            period="FG",
            entity_id="1001",
            book_key="draftkings",
            sportsbook="DraftKings",
            retrieved_at=ts,
            is_alternate=True,
        )
        alternate = [
            CFBQuote(market="ALTERNATE_SPREAD", side="HOME", line=-6.5,
                     american_odds=125, offer_id="ash", **base),
            CFBQuote(market="ALTERNATE_SPREAD", side="AWAY", line=-6.5,
                     american_odds=-145, offer_id="asa", **base),
            CFBQuote(market="ALTERNATE_TOTAL", side="OVER", line=52.5,
                     american_odds=110, offer_id="ato", **base),
            CFBQuote(market="ALTERNATE_TOTAL", side="UNDER", line=52.5,
                     american_odds=-130, offer_id="atu", **base),
        ]
        report = self.manual(
            mode="MANUAL",
            season=2026,
            week=1,
            model=model(),
            now=NOW,
            games=self.games,
            metrics=self.metrics,
            quotes=[*self.q, *alternate],
            n_paths=500,
            root_seed=44,
        )
        alt_rows = [
            row for row in report.results
            if row.market in {"ALTERNATE_SPREAD", "ALTERNATE_TOTAL"}
        ]
        self.assertEqual(len(alt_rows), 4)
        self.assertTrue(all(row.engine_status == "PRICED" for row in alt_rows))
        self.assertTrue(all(
            row.bet_status == "BLOCKED"
            and row.reason == "CFB_PROMOTION_EVIDENCE_REQUIRED"
            for row in alt_rows
        ))
        self.assertEqual(len({row.distribution_sha256 for row in report.results}), 1)
        self.assertEqual(len({row.seed for row in report.results}), 1)

        for market in ("ALTERNATE_SPREAD", "ALTERNATE_TOTAL"):
            rows = [row for row in alt_rows if row.market == market]
            self.assertEqual(len(rows), 2)
            self.assertAlmostEqual(
                sum(float(row.fair_market_p) for row in rows),
                1.0,
                places=12,
            )

    def test_market_surface_marks_cfb_alternate_lines_implemented(self):
        surface = json.loads(Path("config/football_market_surface.json").read_text())
        states = {
            row["market"]: row["engine_state_by_sport"]["CFB"]
            for row in surface["markets"]
            if row["market"] in {"alternate_spread", "alternate_total"}
        }
        self.assertEqual(states, {
            "alternate_spread": "IMPLEMENTED",
            "alternate_total": "IMPLEMENTED",
        })

    def test_no_engine_never_becomes_pass(self):
        surface=json.loads(Path("config/football_market_surface.json").read_text())
        declared=next(row for row in surface["markets"] if row["market"]=="first_half_total")
        self.assertEqual(declared["engine_state_by_sport"]["CFB"],"NO_ENGINE")
        q=self.q[0].to_dict(); q.update(market="FIRST_HALF_TOTAL",side="OVER",line=24.5)
        report=self.manual(mode="MANUAL",season=2026,week=1,model=model(),now=NOW,games=self.games,metrics=self.metrics,quotes=[q],n_paths=10)
        r=report.results[0]
        self.assertEqual((r.engine_status,r.bet_status,r.reason),("NO_ENGINE","BLOCKED","NO_ENGINE"))
        self.assertIsNone(r.model_p)
        self.assertEqual(report.summary["official_bets"],0)

    def test_stale_quote_blocks_market_layer_not_engine(self):
        stale=[replace(q,retrieved_at=(NOW-timedelta(hours=1)).isoformat()) for q in self.q]
        r=self.manual(mode="MANUAL",season=2026,week=1,model=model(),now=NOW,games=self.games,metrics=self.metrics,quotes=stale,n_paths=20)
        self.assertTrue(all(x.engine_status=="PRICED" and x.reason=="CFB_QUOTE_STALE" for x in r.results))
        self.assertTrue(all(x.fair_market_p is None for x in r.results))

    def test_manual_requires_frozen_fbs_membership(self):
        with self.assertRaisesRegex(Exception,"CFB_MANUAL_FBS_MEMBERSHIP_REQUIRED"):
            run_cfb_machine(mode="MANUAL",season=2026,week=1,model=model(),now=NOW,
                            games=self.games,metrics=self.metrics,quotes=self.q,n_paths=10)

    def test_manual_fcs_or_unknown_opponent_fails_before_model(self):
        fbs_only=[self.teams[0]]
        with self.assertRaisesRegex(CFBClassificationError,"CFB_FBS_ONLY_POLICY:1001:Beta Tech"):
            run_cfb_machine(mode="MANUAL",season=2026,week=1,model=model(),now=NOW,
                            games=self.games,metrics=self.metrics,quotes=self.q,
                            fbs_team_rows=fbs_only,n_paths=10)

    def test_fetched_modes_reject_non_fbs_game_before_weather_metrics_or_odds(self):
        bad_game=replace(game(),weather=None,away_team="FCS College")
        calls={"weather":0,"metrics":0,"odds":0}
        def fg_bad(**k): return [bad_game]
        def should_not_weather(**k): calls["weather"]+=1; return {}
        def should_not_metrics(**k): calls["metrics"]+=1; return {}
        def should_not_odds(**k): calls["odds"]+=1; return []
        with self.assertRaisesRegex(CFBClassificationError,"CFB_FBS_ONLY_POLICY:1001:FCS College"):
            run_cfb_machine(mode="AUTOMATIC",season=2026,week=1,model=model(),now=NOW,
                            cfbd_api_key="cfbd",odds_api_key="odds",team_fetcher=self.ft,
                            game_fetcher=fg_bad,weather_fetcher=should_not_weather,
                            metric_fetcher=should_not_metrics,odds_fetcher=should_not_odds,n_paths=10)
        self.assertEqual(calls,{"weather":0,"metrics":0,"odds":0})

    def test_automatic_requires_real_credentials(self):
        with self.assertRaisesRegex(Exception,"CFBD_API_KEY_REQUIRED"):
            run_cfb_machine(mode="AUTOMATIC",season=2026,week=1,model=model(),now=NOW)


if __name__ == "__main__": unittest.main()