import unittest
from datetime import datetime, timezone

from sportsedge.feature_bridge import FeatureBridgeError, resolve_feature_row
from sportsedge.hits_engine import FEATURE_CONTRACT_VERSION as HITS_FEATURE_VERSION
from sportsedge.live_slate import assemble_hitter_candidate, make_live_game
from sportsedge.mlb_source import GameSnapshot

UTC=timezone.utc
NOW=datetime(2026,8,10,20,0,tzinfo=UTC)
CUTOFF=datetime(2026,8,10,23,0,tzinfo=UTC)


def fact(key,value,source="s1",minutes=1,status=None,event=None):
    return {
        "source_id":source,"fact_key":key,"value":value,"provider":"MLB_STATS_API",
        "event_time":event or "2026-08-10T19:00:00Z",
        "retrieved_at":f"2026-08-10T19:{60-minutes:02d}:00Z" if minutes<=60 else "2026-08-10T18:00:00Z",
        **({"status":status} if status else {}),
    }


def hits_sources():
    return [
        fact("b_rate:777:100",.25,"b"),
        fact("p_rate:777:100",.23,"p"),
        fact("pa_pool:777:100",[4,4,5,3],"pa"),
    ]


def hit_keys(): return {"b_rate":"b_rate:777:100","p_rate":"p_rate:777:100","pa_pool":"pa_pool:777:100"}
def hit_ttls(): return {"b_rate":3600,"p_rate":3600,"pa_pool":3600}


def game():
    s=GameSnapshot(game_pk=777,game_date="2026-08-10T23:00:00Z",status="Preview",away_id=1,away_name="Away",home_id=2,home_name="Home",away_probable_pitcher_id=11,away_probable_pitcher_name="A",home_probable_pitcher_id=22,home_probable_pitcher_name="H",retrieved_at="2026-08-10T19:59:00+00:00")
    rows=lambda start:[{"player_id":start+i,"slot":i+1,"sequence":0} for i in range(9)]
    return make_live_game(s,rows(100),rows(200))


class FeatureBridgeTests(unittest.TestCase):
    def resolve(self,sources=None, now=NOW, cutoff=CUTOFF):
        return resolve_feature_row(market="HITS",game_pk=777,player_id=100,team_id=1,feature_fact_keys=hit_keys(),sources=sources or hits_sources(),ttl_by_feature=hit_ttls(),now=now,wager_cutoff=cutoff)

    def test_resolves_versioned_hits_row_with_provenance(self):
        row=self.resolve()
        self.assertEqual(row["feature_version"],HITS_FEATURE_VERSION)
        self.assertEqual(len(row["source_subset_hash"]),64)
        self.assertEqual(len(row["provenance"]),3)
        self.assertNotIn("model_p",row)

    def test_order_invariant_resolution_and_hash(self):
        a=self.resolve(hits_sources())
        b=self.resolve(list(reversed(hits_sources())))
        self.assertEqual(a["source_subset_hash"],b["source_subset_hash"])
        self.assertEqual(a["provenance"],b["provenance"])

    def test_missing_fact_fails_closed(self):
        with self.assertRaises(FeatureBridgeError) as cm: self.resolve(hits_sources()[:-1])
        self.assertEqual(cm.exception.reason,"MISSING")

    def test_stale_fact_fails_closed(self):
        s=hits_sources(); s[0]["retrieved_at"]="2026-08-10T18:00:00Z"
        with self.assertRaises(FeatureBridgeError) as cm: self.resolve(s)
        self.assertEqual(cm.exception.reason,"STALE")

    def test_future_event_time_fails_closed(self):
        s=hits_sources(); s[0]["event_time"]="2026-08-10T23:01:00Z"; s[0]["retrieved_at"]="2026-08-10T19:59:00Z"
        with self.assertRaises(FeatureBridgeError) as cm: self.resolve(s)
        self.assertEqual(cm.exception.reason,"IMPOSSIBLE_SOURCE_CHRONOLOGY")

    def test_impossible_source_chronology_fails_closed(self):
        s=hits_sources(); s[0]["event_time"]="2026-08-10T19:59:30Z"; s[0]["retrieved_at"]="2026-08-10T19:59:00Z"
        with self.assertRaises(FeatureBridgeError) as cm: self.resolve(s)
        self.assertEqual(cm.exception.reason,"IMPOSSIBLE_SOURCE_CHRONOLOGY")

    def test_post_cutoff_retrieval_fails_closed(self):
        s=hits_sources(); s[0]["event_time"]="2026-08-10T22:59:00Z"; s[0]["retrieved_at"]="2026-08-10T23:00:30Z"
        with self.assertRaises(FeatureBridgeError) as cm: self.resolve(s, now=datetime(2026,8,10,23,1,tzinfo=UTC))
        self.assertEqual(cm.exception.reason,"POST_CUTOFF_RETRIEVAL")

    def test_conflicting_fresh_values_fail_closed(self):
        s=hits_sources()+[fact("b_rate:777:100",.30,"b2")]
        with self.assertRaises(FeatureBridgeError) as cm: self.resolve(s)
        self.assertEqual(cm.exception.reason,"CONFLICT")

    def test_identical_duplicate_is_order_invariant(self):
        s=hits_sources()+[fact("b_rate:777:100",.25,"b2")]
        a=self.resolve(s); b=self.resolve(list(reversed(s)))
        self.assertEqual(a["source_subset_hash"],b["source_subset_hash"])

    def test_banned_fact_key_fails(self):
        keys=hit_keys(); keys["b_rate"]="sportsbook_probability:777:100"
        s=hits_sources()+[fact("sportsbook_probability:777:100",.25,"bad")]
        with self.assertRaises(FeatureBridgeError) as cm:
            resolve_feature_row(market="HITS",game_pk=777,player_id=100,team_id=1,feature_fact_keys=keys,sources=s,ttl_by_feature=hit_ttls(),now=NOW,wager_cutoff=CUTOFF)
        self.assertEqual(cm.exception.reason,"BANNED_FACT")

    def test_bridge_row_flows_into_live_candidate_and_binds_source_hash(self):
        row=self.resolve()
        q={"game_id":"777","market":"HITS","entity_id":"100","line":.5,"side":"OVER","american_odds":-110,"retrieved_at":NOW,"ttl_seconds":300}
        c=assemble_hitter_candidate(game=game(),market="HITS",feature_row=row,quote=q)
        self.assertEqual(c["model_input"]["feature_source_hash"],row["source_subset_hash"])
        self.assertEqual(c["model_input"]["provenance"],row["provenance"])

    def test_source_hash_changes_when_source_identity_changes_even_same_value(self):
        a=self.resolve()
        s=hits_sources(); s[0]["source_id"]="different-source"
        b=self.resolve(s)
        self.assertNotEqual(a["source_subset_hash"],b["source_subset_hash"])

if __name__=="__main__": unittest.main()
