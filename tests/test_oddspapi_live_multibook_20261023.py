"""Offline regression coverage for budgeted live OddsPapi quote intake."""
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from pathlib import Path
from scripts import collect_oddspapi_live_multibook as m

NOW = datetime(2026, 10, 23, 18, 0, tzinfo=timezone.utc)


def fixture(fid="fixtureA"):
    last=(NOW-timedelta(seconds=30)).isoformat()
    return {"fixtureId":fid, "startTime":(NOW+timedelta(hours=2)).isoformat(),
            "hasOdds":True, "statusId":0, "sportId":10,
            "participant1Name":"Away", "participant2Name":"Home",
            "bookmakerOdds":{"draftkings":{
                "bookmakerIsActive":True, "suspended":False,
                "markets":{"123":{"marketActive":True,"outcomes":{
                    "overX":{"players":{"0":{"active":True,"bookmakerOutcomeId":"27.5/over",
                                             "priceAmerican":"-110","changedAt":last,
                                             "bookmakerChangedAt":last,"mainLine":True,
                                             "playerName":"Player A"}}},
                    "underX":{"players":{"0":{"active":True,"bookmakerOutcomeId":"27.5/under",
                                              "priceAmerican":"-115","changedAt":last,
                                              "bookmakerChangedAt":last,"mainLine":True,
                                              "playerName":"Player A"}}}}}}}}}


def account(count=100,limit=250):
    return {"current_subscription_id":"active",
            "subscriptions":[{"subscription_id":"active","is_active":True,
                              "request_count":count,"request_limit":limit}]}


class OddsPapiTests(unittest.TestCase):
    def test_exact_over_under_pair_preserves_source_ids_prices_and_fair_reference(self):
        out=m.normalize_fixture(fixture(),"fixtureA",asof=NOW)
        self.assertEqual(out["status"],"PAIRS_FOUND")
        self.assertIsNone(out["model_p"])
        self.assertFalse(out["play_eligible"])
        row=out["pairs"][0]
        self.assertEqual((row["book"],row["market_id"],row["player_id"],row["line"]),
                         ("draftkings","123","0","27.5"))
        self.assertEqual((row["over"]["price"],row["under"]["price"]),(-110,-115))
        self.assertEqual(row["over"]["outcome_id"],"overX")
        self.assertAlmostEqual(sum(row["no_vig_market_reference"].values()),1.0)

    def test_180_inclusive_181_rejected_for_each_side(self):
        raw=fixture()
        player=raw["bookmakerOdds"]["draftkings"]["markets"]["123"]["outcomes"]["overX"]["players"]["0"]
        at=(NOW-timedelta(seconds=180)).isoformat()
        player["changedAt"]=player["bookmakerChangedAt"]=at
        self.assertEqual(len(m.normalize_fixture(raw,"fixtureA",asof=NOW)["pairs"]),1)
        player["bookmakerChangedAt"]=(NOW-timedelta(seconds=181)).isoformat()
        self.assertEqual(m.normalize_fixture(raw,"fixtureA",asof=NOW)["status"],"RAW_ONLY_NO_SAFE_PAIRS")
        player["bookmakerChangedAt"]=(NOW+timedelta(seconds=2)).isoformat()
        self.assertEqual(m.normalize_fixture(raw,"fixtureA",asof=NOW)["status"],"RAW_ONLY_NO_SAFE_PAIRS")

    def test_missing_or_mismatched_opposite_is_never_guessed(self):
        raw=fixture()
        outcomes=raw["bookmakerOdds"]["draftkings"]["markets"]["123"]["outcomes"]
        del outcomes["underX"]
        self.assertFalse(m.normalize_fixture(raw,"fixtureA",asof=NOW)["pairs"])
        raw=fixture()
        opposite=raw["bookmakerOdds"]["draftkings"]["markets"]["123"]["outcomes"]["underX"]["players"]["0"]
        opposite["bookmakerOutcomeId"]="28.5/under"
        self.assertFalse(m.normalize_fixture(raw,"fixtureA",asof=NOW)["pairs"])
        opposite["bookmakerOutcomeId"]="27.5/under"
        opposite["playerName"]="Different Player"
        self.assertFalse(m.normalize_fixture(raw,"fixtureA",asof=NOW)["pairs"])

    def test_price_and_status_fail_closed(self):
        raw=fixture()
        book=raw["bookmakerOdds"]["draftkings"]
        book["suspended"]=True
        self.assertFalse(m.normalize_fixture(raw,"fixtureA",asof=NOW)["pairs"])
        book["suspended"]=False
        book["markets"]["123"]["marketActive"]=False
        self.assertFalse(m.normalize_fixture(raw,"fixtureA",asof=NOW)["pairs"])
        book["markets"]["123"]["marketActive"]=True
        over=book["markets"]["123"]["outcomes"]["overX"]["players"]["0"]
        over["priceAmerican"]="0"
        self.assertFalse(m.normalize_fixture(raw,"fixtureA",asof=NOW)["pairs"])

    def test_duplicate_same_side_refused(self):
        raw=fixture()
        outcomes=raw["bookmakerOdds"]["draftkings"]["markets"]["123"]["outcomes"]
        outcomes["anotherOver"]=copy.deepcopy(outcomes["overX"])
        self.assertFalse(m.normalize_fixture(raw,"fixtureA",asof=NOW)["pairs"])

    def test_unknown_market_no_opaque_stat_guess(self):
        raw=fixture()
        for outcome in raw["bookmakerOdds"]["draftkings"]["markets"]["123"]["outcomes"].values():
            outcome["players"]["0"]["bookmakerOutcomeId"]="opaque-id"
        out=m.normalize_fixture(raw,"fixtureA",asof=NOW)
        self.assertEqual(out["status"],"RAW_ONLY_NO_SAFE_PAIRS")
        self.assertTrue(out["unmapped_market_ids_are_not_model_priced"])

    def test_game_identity_and_live_refusal(self):
        with self.assertRaisesRegex(m.IntakeRefusal,"FIXTURE_ID_MISMATCH"):
            m.normalize_fixture(fixture(),"wrong",asof=NOW)
        raw=fixture()
        raw["statusId"]=2
        with self.assertRaisesRegex(m.IntakeRefusal,"NOT_PROSPECTIVE"):
            m.normalize_fixture(raw,"fixtureA",asof=NOW)

    def test_quota_account_pinned_active_subscription_only(self):
        self.assertEqual(m.account_remaining(account()),150)
        bad=account()
        bad["subscriptions"].append(copy.deepcopy(bad["subscriptions"][0]))
        with self.assertRaisesRegex(m.IntakeRefusal,"NOT_UNIQUE"):
            m.account_remaining(bad)
        with self.assertRaisesRegex(m.IntakeRefusal,"QUOTA_COUNT_INVALID"):
            m.account_remaining(account(count="99"))

    def test_default_is_zero_cost_no_key_needed(self):
        def forbidden(*args,**kwargs):
            raise AssertionError("dry run must not call provider")
        result=m.collect(["fixtureA"],["draftkings"],request=forbidden)
        self.assertEqual(result["status"],"DRY_RUN_NO_BILLABLE_CALLS")
        self.assertEqual(result["cost"],0)

    def test_quota_reserve_blocks_paid_odds_call(self):
        calls=[]
        def provider(endpoint,params,key):
            calls.append(endpoint)
            return account(count=226)
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(m.IntakeRefusal,"QUOTA_RESERVE"):
                m.collect(["fixtureA"],["draftkings"],max_billable=1,
                          out_dir=folder,key="secret",request=provider,clock=lambda:NOW)
        self.assertEqual(calls,["/account"])

    def test_fetch_keeps_raw_unmapped_market_data_without_credentials(self):
        calls=[]
        def provider(endpoint,params,key):
            calls.append(endpoint)
            self.assertEqual(key,"secret-not-in-file")
            if endpoint=="/account":
                return account()
            return fixture("fixtureA")
        with TemporaryDirectory() as folder:
            result=m.collect(["fixtureA"],["draftkings","pinnacle"],
                             max_billable=1,out_dir=folder,key="secret-not-in-file",
                             request=provider,clock=lambda:NOW)
            self.assertEqual(calls,["/account","/odds"])
            self.assertEqual(result["fixtures"][0]["pairs"],1)
            data=(Path(folder)/"fixtureA.json").read_text()
            self.assertIn("raw_unmapped_provider_response",data)
            self.assertNotIn("secret-not-in-file",data)
            self.assertFalse(json.loads(data)["play_eligible"])

    def test_per_fixture_quota_check_and_spend_cap(self):
        seen=[]
        def provider(endpoint,params,key):
            seen.append(endpoint)
            if endpoint=="/account":
                return account(count=100+len(seen))
            return fixture(params["fixtureId"])
        with TemporaryDirectory() as folder:
            result=m.collect(["f1","f2"],["draftkings"],
                             max_billable=2,out_dir=folder,key="secret",
                             request=provider,clock=lambda:NOW)
            self.assertEqual(result["calls"],2)
            self.assertEqual(seen,["/account","/odds","/account","/odds"])
        with self.assertRaisesRegex(m.IntakeRefusal,"BILLABLE_LIMIT_BELOW"):
            m.collect(["f1","f2"],["draftkings"],max_billable=1,key="secret",out_dir="unused")

    def test_reject_invalid_selection_and_unverified_book_count(self):
        for bad in (["x","x"],["bad!"],[]):
            with self.assertRaises(m.IntakeRefusal):
                m.validate_selection(bad,["draftkings"])
        for bad in ([],["draftkings"]*2,["a","b","c","d"]):
            with self.assertRaises(m.IntakeRefusal):
                m.validate_selection(["fixtureA"],bad)


if __name__ == "__main__":
    unittest.main()
