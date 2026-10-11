"""Automatic DK intake: four-sport quote hygiene and free-budget conservation."""
import importlib.util
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("dkauto",ROOT/"scripts"/"collect_auto_dk_four_sports.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
NOW=datetime(2026,10,11,12,0,tzinfo=timezone.utc)


def event(sport, start=None, markets=None):
    started=start or NOW+timedelta(hours=3)
    books=[{"key":"draftkings","last_update":NOW.isoformat(),
            "markets":markets if markets is not None else [
                {"key":"h2h","outcomes":[
                    {"name":"Philadelphia Eagles","price":310},
                    {"name":"Jacksonville Jaguars","price":-380}]},
                {"key":"spreads","outcomes":[
                    {"name":"Philadelphia Eagles","point":7.5,"price":-110},
                    {"name":"Jacksonville Jaguars","point":-7.5,"price":-110}]},
                {"key":"totals","outcomes":[
                    {"name":"Over","point":41.5,"price":-110},
                    {"name":"Under","point":41.5,"price":-110}]}
            ]}]
    return {"id":"e1","sport_key":m.SPORTS[sport],"commence_time":started.isoformat(),
            "away_team":"Philadelphia Eagles","home_team":"Jacksonville Jaguars",
            "bookmakers":books}


class AutoOddsTests(unittest.TestCase):
    def test_four_sport_mapping_is_explicit(self):
        self.assertEqual(set(m.SPORTS),{"NFL","CFB","MLB","NBA"})

    def test_auto_nfl_ticket_has_both_prices_at_correct_threshold(self):
        board=m.events_to_board("NFL",[event("NFL")],NOW)
        self.assertEqual(len(board),1)
        self.assertEqual(set(board[0]["markets"]),{"h2h","spreads","totals"})
        tickets=m.nfl_tickets(board,NOW)
        self.assertEqual(len(tickets),1)
        games=next(iter(tickets.values()))["games"]
        self.assertEqual((games[0]["away"],games[0]["home"]),("PHI","JAX"))
        self.assertEqual(games[0]["markets"][1]["line"],7.5)
        self.assertEqual(games[0]["markets"][2]["home_or_under_price"],-110)
        self.assertIsNone(board[0]["estimate_p"])

    def test_missing_opposite_and_mismatched_spread_fail_closed(self):
        item=event("NFL")
        book=item["bookmakers"][0]
        book["markets"][1]["outcomes"][1]["point"]=-6.5
        book["markets"][2]["outcomes"]=book["markets"][2]["outcomes"][:1]
        b=m.events_to_board("NFL",[item],NOW)
        self.assertEqual(set(b[0]["markets"]),{"h2h"})

    def test_stale_and_started_games_rejected(self):
        stale=event("NFL")
        stale["bookmakers"][0]["last_update"]=(NOW-timedelta(hours=3)).isoformat()
        self.assertFalse(m.events_to_board("NFL",[stale],NOW))
        self.assertFalse(m.events_to_board("NFL",[event("NFL",NOW)],NOW))

    def test_missing_book_does_not_invent_prices(self):
        item=event("MLB")
        item["bookmakers"][0]["key"]="fanduel"
        self.assertEqual(m.events_to_board("MLB",[item],NOW),[])

    def test_peer_fair_from_power_v1_is_context_only(self):
        item=event("NFL")
        peer=json.loads(json.dumps(item["bookmakers"][0]))
        peer["key"]="pinnacle"
        peer["markets"][0]["outcomes"][0]["price"]=290
        peer["markets"][0]["outcomes"][1]["price"]=-350
        item["bookmakers"].append(peer)
        row=m.events_to_board("NFL",[item],NOW)[0]
        ref=row["reference"]["h2h"]
        self.assertEqual(ref["method"],"PINNACLE_POWER_V1")
        self.assertAlmostEqual(sum(ref["fair"]),1.0)
        self.assertIsNone(ref["model_probability"])

    def test_longshots_with_sensitive_devig_have_no_fair_price(self):
        item=event("NFL")
        peer=json.loads(json.dumps(item["bookmakers"][0]))
        peer["key"]="pinnacle"
        peer["markets"][0]["outcomes"][0]["price"]=550
        peer["markets"][0]["outcomes"][1]["price"]=-1100
        item["bookmakers"].append(peer)
        row=m.events_to_board("NFL",[item],NOW)[0]
        self.assertEqual(row["reference"]["h2h"]["method"],"MISSING")

    def test_out_of_credit_never_makes_paid_fetch(self):
        with TemporaryDirectory() as temp:
            def nofetch(*args):
                raise AssertionError("paid fetch forbidden without budget")
            def blocked(keys,minimum_remaining):
                return {"state":"BLOCKED","reason":"INSUFFICIENT_REMAINING_CREDITS",
                        "max_remaining":3,"ready_key_slots":[]}
            res=m.collect(("NFL","MLB","CFB","NBA"),Path(temp),NOW,76,
                          provider_fetch=nofetch,quota_probe=blocked)
            self.assertTrue(all(v["games"]==[] and v["status"]=="UNAVAILABLE" for v in res.values()))
            self.assertIn("INSUFFICIENT_REMAINING_CREDITS",(Path(temp)/"summary.md").read_text())

    def test_free_active_sport_filter_saves_paid_calls(self):
        with TemporaryDirectory() as temp:
            def forbidden(*args,**kwargs):
                raise AssertionError("inactive league must not consume provider calls")
            result=m.collect(("NBA",),Path(temp),NOW,76,
                             provider_fetch=forbidden,quota_probe=forbidden,
                             active_sports={"americanfootball_nfl"})
            self.assertEqual(result["NBA"]["status"],"UNAVAILABLE")
            self.assertEqual(result["NBA"]["reason"],"SPORT_INACTIVE")
            self.assertEqual(result["NBA"]["games"],[])

    def test_provider_failure_does_not_zero_fill_model(self):
        with TemporaryDirectory() as temp:
            def boom(*args):
                raise OSError("no internet")
            def ready(keys,minimum_remaining):
                return {"state":"READY","reason":"RESERVE_SATISFIED",
                        "max_remaining":250,"ready_key_slots":["SPORTSEDGE_ODDS_API_KEY"]}
            orig=m.configured_keys
            m.configured_keys=lambda:[("SPORTSEDGE_ODDS_API_KEY","not-a-real-key")]
            try:
                result=m.collect(("NBA",),Path(temp),NOW,76,provider_fetch=boom,quota_probe=ready)
                self.assertEqual(result["NBA"]["status"],"UNAVAILABLE")
                self.assertIsNone(result["NBA"]["estimate_p"])
            finally:
                m.configured_keys=orig

    def test_games_already_started_removed_from_cfb(self):
        item=event("CFB")
        item["away_team"]="Illinois Fighting Illini"
        self.assertFalse(m.events_to_board("CFB",[item],NOW))

    def test_cfb_and_mlb_formats_both_preserve_dk_pair(self):
        a=m.events_to_board("CFB",[event("CFB")],NOW)
        row=m.cfb_compact(a)[0]
        self.assertEqual(row["ml"],[310,-380])
        self.assertEqual(row["spread"],[7.5,-110,-110])
        b=m.events_to_board("MLB",[event("MLB")],NOW)
        lines=m.mlb_line_text(b)
        self.assertIn("ML 310 -380",lines)
        self.assertIn("RL +7.5 -110 -110",lines)


class AutoModelBridgeTests(unittest.TestCase):
    def test_cfb_week_is_anchored_to_competition_saturday(self):
        from scripts.run_auto_dk_cards import week_candidate
        self.assertEqual(week_candidate("2026-10-10T19:30:00+00:00"),(2026,6))
        self.assertEqual(week_candidate("2026-10-16T23:30:00+00:00"),(2026,7))
        self.assertIsNone(week_candidate("2027-10-16T23:30:00+00:00"))

    def test_mlb_adapter_uses_provider_timestamp_not_fake_intake(self):
        from dataclasses import make_dataclass
        from scripts.run_auto_dk_cards import mlb_auto_snapshot
        game_cls=make_dataclass("FakeGame",[
            ("away_name",str),("home_name",str),("game_pk",int),("game_date",str)])
        schedule=[game_cls("Away Team","Home Team",123,"2026-10-11T19:00:00Z")]
        game={
            "away":"Away Team","home":"Home Team","slate_ct":"2026-10-11",
            "markets":{"h2h":{"away":120,"home":-135,"observed_at":"2026-10-11T11:59:15+00:00"}}
        }
        def source(text,observed_at,schedule):
            self.assertIn("ML 120 -135",text)
            return {"rows":[{
                "game_id":"Away Team@Home Team","market_type":"MONEYLINE",
                "line":0.0,"price":120,"paired_price":-135,
                "observed_at":observed_at,"first_pitch_at":"2026-10-11T19:00:00Z"
            }]}
        result=mlb_auto_snapshot([game],NOW,fetch_schedule=lambda d:schedule,build_bound_input=source)
        row=result["rows"][0]
        self.assertEqual(row["observed_at"],"2026-10-11T11:59:15+00:00")
        self.assertEqual(row["timestamp_source"],"PROVIDED")
        self.assertEqual(row["quote_origin"],"ODDS_API_DK_AUTO")

    def test_mlb_adapter_rejects_quote_price_drift(self):
        from dataclasses import make_dataclass
        from scripts.run_auto_dk_cards import mlb_auto_snapshot
        game_cls=make_dataclass("FakeGame",[
            ("away_name",str),("home_name",str),("game_pk",int),("game_date",str)])
        schedule=[game_cls("Away Team","Home Team",123,"2026-10-11T19:00:00Z")]
        row={"away":"Away Team","home":"Home Team","slate_ct":"2026-10-11",
             "markets":{"h2h":{"away":120,"home":-135,"observed_at":NOW.isoformat()}}}
        def bad(*args,**kwargs):
            return {"rows":[{"game_id":"Away Team@Home Team","market_type":"MONEYLINE",
                "line":0.0,"price":115,"paired_price":-135,"first_pitch_at":"2026-10-11T19:00:00Z"}]}
        with self.assertRaisesRegex(ValueError,"MLB_AUTO_PROVENANCE_ODDS_MISMATCH"):
            mlb_auto_snapshot([row],NOW,fetch_schedule=lambda d:schedule,build_bound_input=bad)


if __name__=="__main__":
    unittest.main()
