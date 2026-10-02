from __future__ import annotations

from copy import deepcopy
import unittest

from sportsedge.sports.cfb.prop_usage_input import CFBPropUsageInputError, build_live_features


class CFBPropUsageInputTests(unittest.TestCase):
    def _player(self, player_id, name, position, team, *, active=True):
        return {
            "player_id": player_id, "player_name": name, "position": position,
            "team": team, "active": active, "snap_share": 0.80,
            "route_participation": 0.70, "target_share": 0.20,
            "rush_share": 0.10, "red_zone_share": 0.20,
        }

    def _payload(self):
        return {
            "schema_version": "CFB_PROP_USAGE_INPUT_V1", "sport": "CFB",
            "source_id": "TEST_MARKET_BLIND_USAGE",
            "source_updated_at": "2026-09-12T14:00:00Z",
            "retrieved_at": "2026-09-12T14:10:00Z",
            "asof_ts": "2026-09-12T14:10:00Z",
            "games": [{
                "game_id": "g1", "provider_event_id": "evt1",
                "game_start_ts": "2026-09-12T17:00:00Z",
                "home_team": "HOME", "away_team": "AWAY",
                "provider_home_team": "Home", "provider_away_team": "Away",
                "home_usage": {"quarterback_id": "h-qb", "players": [
                    self._player("h-qb", "Home QB", "QB", "HOME"),
                    self._player("h-wr", "Home WR", "WR", "HOME"),
                ]},
                "away_usage": {"quarterback_id": "a-qb", "players": [
                    self._player("a-qb", "Away QB", "QB", "AWAY"),
                    self._player("a-wr", "Away WR", "WR", "AWAY"),
                ]},
            }],
        }

    def _build(self, payload=None, *, now="2026-09-12T14:20:00Z"):
        return build_live_features(
            payload=payload or self._payload(), input_bytes_sha256="a" * 64,
            now=now, max_age_seconds=7200,
        )

    def test_valid_input_is_market_blind_and_non_promoting(self):
        live = self._build()
        self.assertEqual(live["sport"], "CFB")
        self.assertFalse(live["governance"]["market_fields_consumed"])
        self.assertFalse(live["governance"]["usage_synthesized"])
        self.assertFalse(live["governance"]["promotion_authority"])

    def test_manifest_is_deterministic(self):
        self.assertEqual(self._build(), self._build(deepcopy(self._payload())))

    def test_missing_share_is_rejected_not_filled(self):
        payload = self._payload()
        del payload["games"][0]["home_usage"]["players"][1]["target_share"]
        with self.assertRaisesRegex(CFBPropUsageInputError, "CFB_PROP_USAGE_SHARE_MISSING"):
            self._build(payload)

    def test_bad_share_is_rejected(self):
        for value in (float("nan"), 1.01, -0.01):
            payload = self._payload()
            payload["games"][0]["home_usage"]["players"][1]["rush_share"] = value
            with self.assertRaisesRegex(CFBPropUsageInputError, "CFB_PROP_USAGE_SHARE_INVALID"):
                self._build(payload)

    def test_market_field_is_rejected(self):
        payload = self._payload()
        payload["games"][0]["home_usage"]["players"][1]["american_odds"] = -110
        with self.assertRaisesRegex(CFBPropUsageInputError, "CFB_PROP_USAGE_MARKET_FIELD_FORBIDDEN"):
            self._build(payload)

    def test_stale_snapshot_is_rejected(self):
        with self.assertRaisesRegex(CFBPropUsageInputError, "CFB_PROP_USAGE_SNAPSHOT_STALE"):
            self._build(now="2026-09-12T16:20:01Z")

    def test_post_kick_is_rejected(self):
        payload = self._payload()
        payload["asof_ts"] = payload["retrieved_at"] = "2026-09-12T17:00:00Z"
        with self.assertRaisesRegex(CFBPropUsageInputError, "CFB_PROP_USAGE_GAME_NOT_PREGAME"):
            self._build(payload, now="2026-09-12T17:00:00Z")

    def test_inactive_starting_qb_is_rejected(self):
        payload = self._payload()
        payload["games"][0]["home_usage"]["players"][0]["active"] = False
        with self.assertRaisesRegex(CFBPropUsageInputError, "CFB_PROP_USAGE_STARTING_QB_UNAVAILABLE"):
            self._build(payload)


if __name__ == "__main__":
    unittest.main()
