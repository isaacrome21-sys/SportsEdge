"""Cross-stack wrong-type / malformed-input battery for MLB starter capture.

Every public entry point of ``sportsedge.sports.mlb.starter_capture`` is fed
hostile, wrongly-typed input. The contract (STOP-MERGE finding on #2171,
Oct 13, 2026): a malformed input either produces a fail-closed result
(FAILED / dropped-with-issue / ok=False) or raises ``StarterCaptureError``.
Any other exception type (TypeError, AttributeError, KeyError, ...) is an
unhandled crash and fails this battery. Nothing here touches the network.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sportsedge.sports.mlb import starter_capture as sc

UTC = timezone.utc
FIRST = datetime(2026, 10, 14, 0, 8, tzinfo=UTC)
PLANNED = FIRST - timedelta(hours=30)

WRONG = [None, 0, -1, 1.5, True, "x", "", b"x", [], [1], {}, {"a": 1}, (1,), object()]


def good_game(**over):
    g = {
        "gamePk": 777001, "gameType": "R", "officialDate": "2026-10-13",
        "gameDate": FIRST.isoformat().replace("+00:00", "Z"),
        "doubleHeader": "N", "gameNumber": 1,
        "status": {"codedGameState": "S", "detailedState": "Scheduled", "abstractGameState": "Preview"},
        "teams": {"away": {"team": {"id": 111}, "probablePitcher": {"id": 5001}},
                  "home": {"team": {"id": 147}, "probablePitcher": {"id": 5002}}},
    }
    g.update(over)
    return g


def payload(*games):
    return {"dates": [{"games": list(games) or [good_game()]}]}


def plan_game():
    return sc.build_plan(payload(), planned_at=PLANNED)["games"][0]


def ok_clock():
    return FIRST - timedelta(minutes=90)


def fetch_json(obj):
    raw = json.dumps(obj).encode()
    return lambda url: raw


class _Battery(unittest.TestCase):
    def assertFailClosed(self, fn, *a, **k):
        try:
            return fn(*a, **k)
        except sc.StarterCaptureError:
            return None
        except Exception as exc:  # noqa: BLE001
            self.fail(f"UNHANDLED {type(exc).__name__}: {exc}")


def _payload_cases():
    cases = [("payload", w) for w in WRONG]
    cases += [("dates", {"dates": w}) for w in WRONG]
    cases += [("block", {"dates": [w]}) for w in WRONG if w is not None]
    cases += [("games", {"dates": [{"games": w}]}) for w in WRONG]
    cases += [("game", {"dates": [{"games": [w]}]}) for w in WRONG if w is not None]
    for field in ("teams", "status"):
        cases += [(field, payload(good_game(**{field: w}))) for w in WRONG if w not in (None, {})]
    for side in ("away", "home"):
        for w in WRONG:
            if w in (None, {}):
                continue
            g = good_game(); g["teams"][side] = w
            cases.append((f"teams.{side}", payload(g)))
            g = good_game(); g["teams"][side]["team"] = w
            cases.append((f"teams.{side}.team", payload(g)))
    for w in WRONG:
        cases.append(("gameDate", payload(good_game(gameDate=w))))
        cases.append(("gamePk", payload(good_game(gamePk=w))))
    return cases


PAYLOAD_CASES = _payload_cases()


class WrongTypePayloadBattery(_Battery):
    def test_parse_and_plan_never_crash(self):
        for label, p in PAYLOAD_CASES:
            with self.subTest(label=label, value=repr(p)[:60]):
                rows = self.assertFailClosed(sc.parse_schedule_games, p)
                if rows is not None:
                    for row in rows:
                        self.assertIsInstance(row["game_pk"], int)
                plan = self.assertFailClosed(sc.build_plan, p, planned_at=PLANNED)
                if plan is not None:
                    for g in plan["games"]:
                        self.assertIsInstance(g["away_team_id"], int)
                        self.assertIsInstance(g["home_team_id"], int)

    def test_capture_with_hostile_response_is_failed_never_crash(self):
        pg = plan_game()
        for label, p in PAYLOAD_CASES:
            with self.subTest(label=label, value=repr(p)[:60]):
                try:
                    raw = json.dumps(p).encode()
                except TypeError:
                    continue
                rec = self.assertFailClosed(
                    sc.capture_snapshot, pg, "T-90M", fetcher=lambda u, r=raw: r, clock=ok_clock
                )
                if rec is not None:
                    self.assertTrue(
                        rec.get("record_type") == "CAPTURE_ATTEMPT_FAILED"
                        or rec.get("record_status") == "FAILED",
                        rec,
                    )

    def test_fetcher_returning_non_bytes(self):
        pg = plan_game()
        for w in WRONG + [bytearray(b"{}"), memoryview(b"{}")]:
            with self.subTest(value=repr(w)[:40]):
                rec = self.assertFailClosed(sc.capture_snapshot, pg, "T-90M", fetcher=lambda u, w=w: w, clock=ok_clock)
                if rec is not None:
                    self.assertNotEqual(rec.get("record_status"), "CAPTURED")

    def test_clock_returning_wrong_type(self):
        pg = plan_game()
        for w in WRONG + [datetime(2026, 10, 13)]:
            with self.subTest(value=repr(w)[:40]):
                with self.assertRaises(sc.StarterCaptureError):
                    sc.capture_snapshot(pg, "T-90M", fetcher=fetch_json(payload()), clock=lambda w=w: w)

    def test_hostile_plan_game_and_slot(self):
        for w in WRONG:
            with self.subTest(plan_game=repr(w)[:40]):
                self.assertFailClosed(sc.capture_snapshot, w, "T-90M", fetcher=fetch_json(payload()), clock=ok_clock)
            with self.subTest(slot_id=repr(w)[:40]):
                self.assertFailClosed(sc.capture_snapshot, plan_game(), w, fetcher=fetch_json(payload()), clock=ok_clock)
            pg = plan_game(); pg["slots"] = w
            with self.subTest(slots=repr(w)[:40]):
                self.assertFailClosed(sc.capture_snapshot, pg, "T-90M", fetcher=fetch_json(payload()), clock=ok_clock)
            pg = plan_game(); pg["slots"][2]["window_start_utc"] = w
            with self.subTest(window=repr(w)[:40]):
                rec = self.assertFailClosed(sc.capture_snapshot, pg, "T-90M", fetcher=fetch_json(payload()), clock=ok_clock)
                if rec is not None:
                    self.assertNotEqual(rec.get("slot_disposition"), "ON_TIME")
            pg = plan_game(); pg["game_pk"] = w
            with self.subTest(game_pk=repr(w)[:40]):
                rec = self.assertFailClosed(sc.capture_snapshot, pg, "T-90M", fetcher=fetch_json(payload()), clock=ok_clock)
                if rec is not None:
                    self.assertNotEqual(rec.get("record_status"), "CAPTURED")


class WrongTypeEvaluationBattery(_Battery):
    def test_evaluate_missed_slots_hostile(self):
        plan = sc.build_plan(payload(), planned_at=PLANNED)
        now = FIRST + timedelta(hours=1)
        for w in WRONG:
            with self.subTest(plan=repr(w)[:40]):
                self.assertFailClosed(sc.evaluate_missed_slots, w, [], now=now)
            with self.subTest(records=repr(w)[:40]):
                self.assertFailClosed(sc.evaluate_missed_slots, plan, w, now=now)
            with self.subTest(record=repr(w)[:40]):
                self.assertFailClosed(sc.evaluate_missed_slots, plan, [w], now=now)
            with self.subTest(record_game_pk=repr(w)[:40]):
                self.assertFailClosed(sc.evaluate_missed_slots, plan, [{"record_type": "SNAPSHOT", "game_pk": w, "slot_id": w}], now=now)
            p2 = json.loads(json.dumps(plan)); p2["games"] = w
            with self.subTest(games=repr(w)[:40]):
                self.assertFailClosed(sc.evaluate_missed_slots, p2, [], now=now)
            p3 = json.loads(json.dumps(plan)); p3["games"][0]["slots"][0]["window_end_utc"] = w
            with self.subTest(window_end=repr(w)[:40]):
                self.assertFailClosed(sc.evaluate_missed_slots, p3, [], now=now)
            with self.subTest(now=repr(w)[:40]):
                with self.assertRaises(sc.StarterCaptureError):
                    sc.evaluate_missed_slots(plan, [], now=w)

    def test_detect_changes_hostile(self):
        for w in WRONG:
            with self.subTest(records=repr(w)[:40]):
                self.assertFailClosed(sc.detect_changes, w)
            with self.subTest(record=repr(w)[:40]):
                self.assertFailClosed(sc.detect_changes, [w])
            with self.subTest(game_pk=repr(w)[:40]):
                recs = [{"record_type": "SNAPSHOT", "game_date_utc": "2026-10-14T00:08:00+00:00", "game_pk": w, "captured_at_utc": "a"},
                        {"record_type": "SNAPSHOT", "game_date_utc": "2026-10-14T00:08:00+00:00", "game_pk": w, "captured_at_utc": "b"}]
                out = self.assertFailClosed(sc.detect_changes, recs)
                if out and not (type(w) is int and w > 0):
                    self.fail("change events derived for invalid game_pk")


class WrongTypeStoreBattery(_Battery):
    def test_append_and_verify_hostile(self):
        for w in WRONG:
            with tempfile.TemporaryDirectory() as d, self.subTest(record=repr(w)[:40]):
                cap, man = Path(d) / "c.jsonl", Path(d) / "m.jsonl"
                self.assertFailClosed(sc.append_record, cap, man, w)
                v = sc.verify_capture_chain(cap, man)
                self.assertTrue(v["ok"], v)
                self.assertEqual(v["records_checked"], 1 if isinstance(w, dict) else 0)

    def test_read_hostile_lines(self):
        for raw in [b"not json\n", b"[1]\n", b"\xff\n", b"1\n", b"null\n"]:
            with tempfile.TemporaryDirectory() as d, self.subTest(raw=raw):
                p = Path(d) / "c.jsonl"; p.write_bytes(raw)
                self.assertFailClosed(sc.read_records, p)
                self.assertFailClosed(sc.read_manifest, p)

    def test_verify_wrong_path_types(self):
        for w in [None, 1, 1.5, [], {}, object()]:
            with self.subTest(path=repr(w)[:40]):
                self.assertFailClosed(sc.verify_capture_chain, w, w)


if __name__ == "__main__":
    unittest.main()
