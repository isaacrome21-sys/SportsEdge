from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from sportsedge.sports.cfb.joint_model import (
    CFBJointScoreModel, CFBModelError, CFB_FEATURE_CONTRACT, CFB_JOINT_MODEL_ID,
    _feature_names, price_cfb_game_markets, simulate_cfb_joint_distribution,
)
from sportsedge.sports.cfb.run_machine import run_cfb_machine
from sportsedge.sports.cfb.source import (
    CFBGame, CFBQuote, CFBSourceError, CFBTeamMetrics, attach_weather,
    bind_provider_team, build_team_alias_index, parse_the_odds_api_quotes,
)

NOW = datetime(2026, 8, 26, 17, 0, tzinfo=timezone.utc)
START = datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc)


def metric(team, bump=0.0):
    return CFBTeamMetrics(
        team=team, season=2026, through_week=0, sample_source="PRIOR_SEASON_FALLBACK",
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

    def test_exact_schedule_name_can_bind_fcs_without_fuzzy_guessing(self):
        fcs = CFBGame("2002", 2026, 1, START.isoformat(), "Alpha State", "FCS Academy", False,
                      "Test", {"game_indoor": True}, "FBS", "FCS")
        idx = build_team_alias_index(self.teams, games=[fcs])
        self.assertEqual(bind_provider_team("FCS Academy", idx), "FCS Academy")
        self.assertEqual(fcs.matchup_classification(), "FBS_FCS")


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

    def test_manual_hybrid_auto_results_are_byte_identical(self):
        common=dict(season=2026,week=1,model=model(),now=NOW,n_paths=500,root_seed=44)
        m=run_cfb_machine(mode="MANUAL",games=self.games,metrics=self.metrics,quotes=self.q,**common)
        h=run_cfb_machine(mode="HYBRID",quotes=self.q,cfbd_api_key="cfbd",team_fetcher=self.ft,game_fetcher=self.fg,metric_fetcher=self.fm,weather_fetcher=self.fw,**common)
        a=run_cfb_machine(mode="AUTOMATIC",cfbd_api_key="cfbd",odds_api_key="odds",team_fetcher=self.ft,game_fetcher=self.fg,metric_fetcher=self.fm,weather_fetcher=self.fw,odds_fetcher=self.fo,**common)
        self.assertEqual(m.results,h.results); self.assertEqual(m.results,a.results); self.assertEqual(m.summary,a.summary)

    def test_all_three_readouts_share_one_distribution_and_seed(self):
        r=run_cfb_machine(mode="MANUAL",season=2026,week=1,model=model(),now=NOW,games=self.games,metrics=self.metrics,quotes=self.q,n_paths=500,root_seed=44)
        self.assertEqual({x.market for x in r.results},{"MONEYLINE","SPREAD","TOTAL"})
        self.assertEqual(len({x.distribution_sha256 for x in r.results}),1); self.assertEqual(len({x.seed for x in r.results}),1)

    def test_devig_both_sides_hold_and_promotion_block(self):
        r=run_cfb_machine(mode="MANUAL",season=2026,week=1,model=model(),now=NOW,games=self.games,metrics=self.metrics,quotes=self.q,n_paths=100)
        for market in ("MONEYLINE","SPREAD","TOTAL"):
            xs=[x for x in r.results if x.market==market]
            self.assertAlmostEqual(sum(x.fair_market_p for x in xs),1.0,places=12)
            self.assertEqual(len({x.hold for x in xs}),1)
        self.assertTrue(all(x.engine_status=="PRICED" and x.bet_status=="BLOCKED" for x in r.results))
        self.assertTrue(all(x.reason=="CFB_PROMOTION_EVIDENCE_REQUIRED" for x in r.results))

    def test_no_engine_never_becomes_pass(self):
        q=self.q[0].to_dict(); q.update(market="FIRST_HALF_TOTAL",side="OVER",line=24.5)
        r=run_cfb_machine(mode="MANUAL",season=2026,week=1,model=model(),now=NOW,games=self.games,metrics=self.metrics,quotes=[q],n_paths=10).results[0]
        self.assertEqual((r.engine_status,r.bet_status,r.reason),("NO_ENGINE","BLOCKED","NO_ENGINE")); self.assertIsNone(r.model_p)

    def test_stale_quote_blocks_entire_two_sided_market_pair(self):
        stale=[replace(q,retrieved_at=(NOW-timedelta(hours=1)).isoformat()) for q in self.q]
        r=run_cfb_machine(mode="MANUAL",season=2026,week=1,model=model(),now=NOW,games=self.games,metrics=self.metrics,quotes=stale,n_paths=20)
        self.assertTrue(all(x.engine_status=="BLOCKED" and x.reason=="CFB_QUOTE_STALE" for x in r.results))
        self.assertTrue(all(x.fair_market_p is None and x.edge is None for x in r.results))

    def test_future_quote_blocks_entire_pair(self):
        future=[replace(q,retrieved_at=(NOW+timedelta(seconds=1)).isoformat()) for q in self.q]
        r=run_cfb_machine(mode="MANUAL",season=2026,week=1,model=model(),now=NOW,games=self.games,metrics=self.metrics,quotes=future,n_paths=20)
        self.assertTrue(all(x.engine_status=="BLOCKED" and x.reason=="CFB_QUOTE_FROM_FUTURE" for x in r.results))

    def test_asynchronous_two_sided_pair_is_rejected(self):
        qs=quotes()[:2]
        qs[1]=replace(qs[1],retrieved_at=(NOW-timedelta(seconds=80)).isoformat())
        r=run_cfb_machine(mode="MANUAL",season=2026,week=1,model=model(),now=NOW,games=self.games,metrics=self.metrics,quotes=qs,n_paths=20,quote_pair_skew_seconds=30)
        self.assertTrue(all(x.engine_status=="BLOCKED" and x.reason=="CFB_QUOTE_PAIR_SKEW" for x in r.results))

    def test_one_game_missing_metrics_does_not_abort_other_game(self):
        g2=CFBGame("1002",2026,1,START.isoformat(),"Alpha State","Missing FCS",False,"Test",dict(game().weather),"FBS","FCS")
        ts=(NOW-timedelta(seconds=20)).isoformat()
        base=dict(game_id="1002",period="FG",entity_id="1002",book_key="draftkings",sportsbook="DraftKings",retrieved_at=ts,is_alternate=False)
        q2=[CFBQuote(market="MONEYLINE",side="HOME",line=0,american_odds=-150,offer_id="x1",**base),
            CFBQuote(market="MONEYLINE",side="AWAY",line=0,american_odds=130,offer_id="x2",**base)]
        r=run_cfb_machine(mode="MANUAL",season=2026,week=1,model=model(),now=NOW,games=[game(),g2],metrics=self.metrics,quotes=[*self.q,*q2],n_paths=20)
        good=[x for x in r.results if x.game_id=="1001"]
        bad=[x for x in r.results if x.game_id=="1002"]
        self.assertTrue(all(x.edge is not None for x in good))
        self.assertTrue(all(x.engine_status=="BLOCKED" and x.reason.startswith("CFB_MODEL_INPUT_BLOCKED:") for x in bad))
        self.assertEqual(r.run_status,"DEGRADED")

    def test_automatic_requires_real_credentials(self):
        with self.assertRaisesRegex(Exception,"CFBD_API_KEY_REQUIRED"):
            run_cfb_machine(mode="AUTOMATIC",season=2026,week=1,model=model(),now=NOW)


if __name__ == "__main__": unittest.main()
