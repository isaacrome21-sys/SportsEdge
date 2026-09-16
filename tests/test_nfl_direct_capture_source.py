import json
import unittest
from datetime import datetime, timezone

from sportsedge.draftkings_game_market_source import DraftKingsGameMarketError, RawDraftKingsBoard
from sportsedge import nfl_direct_capture_source as src

UTC = timezone.utc


def board_payload(*, drop_under=False, mismatch_spread=False, drop_spread_away=False, bad_event_name=False):
    sels = [
        {"marketId": "m1", "label": "Chicago Bears", "points": -3.5,
         "displayOdds": {"american": "-110"}},
        {"marketId": "m1", "label": "Green Bay Packers",
         "points": 3.5 if not mismatch_spread else 4.5,
         "displayOdds": {"american": "-110"}},
        {"marketId": "m2", "label": "Over 44.5", "points": 44.5,
         "displayOdds": {"american": "-105"}},
        {"marketId": "m2", "label": "Under 44.5", "points": 44.5,
         "displayOdds": {"american": "-115"}},
    ]
    if drop_under:
        sels = [s for s in sels if not s["label"].startswith("Under")]
    if drop_spread_away:
        sels = [s for s in sels if not (s["marketId"] == "m1" and s["label"] == "Green Bay Packers")]
    return {
        "events": [{
            "id": "E1",
            "name": "Green Bay Packers vs Chicago Bears" if bad_event_name else "Green Bay Packers @ Chicago Bears",
            "startEventDate": "2026-09-20T17:00:00Z",
        }],
        "markets": [
            {"id": "m1", "eventId": "E1", "name": "Spread"},
            {"id": "m2", "eventId": "E1", "name": "Total"},
        ],
        "selections": sels,
    }


class FakeClock:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return datetime(2026, 9, 22, 14, 0, self.n, tzinfo=UTC)


def week_of(_dt):
    return 3


class DirectCaptureAdapterTest(unittest.TestCase):
    def _transport(self, payload=None, **kw):
        payload = payload or board_payload(**kw)
        raw = (" \n" + json.dumps(payload, separators=(",", ":")) + " \n").encode()

        def _fetch(sk):
            return RawDraftKingsBoard(
                sk,
                src.board_url(sk),
                raw,
                datetime(2026, 9, 22, 14, 0, 5, tzinfo=UTC),
                payload,
            )

        t = src.acquire_board(fetcher=_fetch, clock=FakeClock())
        self.assertEqual(t["raw_bytes"], raw)
        return t

    def test_transport_record_preserves_exact_raw_and_provenance(self):
        t = self._transport()
        self.assertEqual(t["source_class"], "DRAFTKINGS_DIRECT_WEB_V1")
        self.assertEqual(t["transport_host"], "sportsbook-nash.draftkings.com")
        self.assertEqual(len(t["raw_sha256"]), 64)
        self.assertEqual(t["adapter_module_sha256"], src.adapter_module_sha256())
        self.assertEqual(t["attempts"], [{
            "attempt": 1,
            "host": "sportsbook-nash.draftkings.com",
            "result_class": "OK",
            "received_at_utc": "2026-09-22T14:00:05Z",
        }])

    def test_receipt_time_never_leaks_into_provider_timestamp_fields(self):
        t = self._transport()
        self.assertIsNone(t["book_last_update"])
        self.assertFalse(t["provider_quote_timestamp_available"])
        rows = src.game_rows_direct(t, week_of=week_of)
        self.assertIsNone(rows[0]["book_last_update"])
        self.assertIsNone(rows[0]["spread"]["market_last_update"])
        self.assertIsNone(rows[0]["total"]["market_last_update"])
        self.assertNotEqual(rows[0]["observed_at_utc"], rows[0]["spread"].get("market_last_update"))

    def test_two_sided_admission(self):
        rows = src.game_rows_direct(self._transport(), week_of=week_of)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["spread"]["status"], "OK")
        self.assertEqual(rows[0]["spread"]["home_point"], -3.5)
        self.assertEqual(rows[0]["total"]["status"], "OK")
        self.assertEqual(rows[0]["total"]["point"], 44.5)

    def test_one_sided_markets_remain_visible_and_are_not_synthesized(self):
        rows = src.game_rows_direct(self._transport(drop_under=True, drop_spread_away=True), week_of=week_of)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["spread"]["status"], "ONE_SIDED")
        self.assertEqual(rows[0]["total"]["status"], "ONE_SIDED")
        self.assertNotIn("away_price", rows[0]["spread"])
        self.assertNotIn("under_price", rows[0]["total"])

    def test_mismatched_spread_blocks(self):
        rows = src.game_rows_direct(self._transport(mismatch_spread=True), week_of=week_of)
        self.assertEqual(rows[0]["spread"]["status"], "LINE_MISMATCH")

    def test_window_is_end_exclusive(self):
        t = self._transport()
        self.assertEqual(src.game_rows_direct(
            t, week_of=week_of,
            window_start=datetime(2026, 9, 20, 0, 0, tzinfo=UTC),
            window_end=datetime(2026, 9, 20, 17, 0, tzinfo=UTC),
        ), [])

    def test_bad_event_identity_fails_closed_instead_of_disappearing(self):
        with self.assertRaisesRegex(src.DirectCaptureError, "EVENT_IDENTITY_UNADMITTED"):
            src.game_rows_direct(self._transport(bad_event_name=True), week_of=week_of)

    def test_one_bad_identity_cannot_hide_inside_other_valid_games(self):
        payload = board_payload()
        payload["events"].append({
            "id": "E2",
            "name": "Malformed versus Event",
            "startEventDate": "2026-09-20T20:00:00Z",
        })
        with self.assertRaisesRegex(src.DirectCaptureError, "EVENT_IDENTITY_UNADMITTED"):
            src.game_rows_direct(self._transport(payload=payload), week_of=week_of)

    def test_failure_records_attempt_history(self):
        def boom(_sk):
            raise DraftKingsGameMarketError("DK_GAME_HTTP_403")

        with self.assertRaises(src.DirectCaptureError) as ctx:
            src.acquire_board(fetcher=boom, clock=FakeClock())
        self.assertEqual(ctx.exception.attempts[0]["result_class"], "DK_GAME_HTTP_403")
        self.assertEqual(ctx.exception.attempts[0]["host"], "sportsbook-nash.draftkings.com")


if __name__ == "__main__":
    unittest.main()
