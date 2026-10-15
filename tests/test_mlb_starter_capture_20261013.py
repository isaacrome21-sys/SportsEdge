"""Offline tests for the MLB probable-starter capture module.

All fixtures are synthetic StatsAPI schedule payloads; no test touches
the network. Clocks and fetchers are injected fakes. The module under
test is sportsedge.sports.mlb.starter_capture (owner-approved design,
PR #2156 review, Oct 13 2026; module is NOT activated for live
collection). The OBSERVED vs FAILED status distinction follows the
owner ruling of Oct 13, 2026 (REPORT.md §8).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from sportsedge.sports.mlb.starter_capture import (
    GAME_TYPES,
    StarterCaptureError,
    append_record,
    build_plan,
    capture_snapshot,
    capture_snapshot_production,
    detect_changes,
    evaluate_missed_slots,
    read_manifest,
    read_records,
    schedule_url,
    verify_capture_chain,
)

UTC = timezone.utc

# Game 1: regular season, first pitch 2026-10-13T23:05:00Z.
GAME1_PK = 745001
GAME1_PITCH = datetime(2026, 10, 13, 23, 5, tzinfo=UTC)
AWAY_TEAM, HOME_TEAM = 147, 111
AWAY_PROB, HOME_PROB = 675911, 656302

# Game 2: World Series (gameType W), first pitch 2026-10-24T00:08:00Z.
GAME2_PK = 745210
GAME2_PITCH = datetime(2026, 10, 24, 0, 8, tzinfo=UTC)


def _probable(spec):
    """spec: ('id', n) | ('name_only',) | ('absent',)"""
    if spec[0] == "absent":
        return {}
    if spec[0] == "name_only":
        return {"probablePitcher": {"fullName": "Name Only"}}
    return {"probablePitcher": {"id": spec[1], "fullName": "Fixture Pitcher"}}


def _game(
    game_pk,
    pitch,
    game_type="R",
    official_date="2026-10-13",
    away_prob=("id", AWAY_PROB),
    home_prob=("id", HOME_PROB),
    away_team=AWAY_TEAM,
    home_team=HOME_TEAM,
    detailed="Scheduled",
    coded="S",
    abstract="Preview",
    double_header="N",
    game_number=1,
):
    game = {
        "gamePk": game_pk,
        "gameDate": pitch.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "officialDate": official_date,
        "gameType": game_type,
        "doubleHeader": double_header,
        "gameNumber": game_number,
        "status": {
            "abstractGameState": abstract,
            "codedGameState": coded,
            "detailedState": detailed,
        },
        "teams": {
            "away": {"team": {"id": away_team, "name": "Away Fixture"}, **_probable(away_prob)},
            "home": {"team": {"id": home_team, "name": "Home Fixture"}, **_probable(home_prob)},
        },
    }
    return game


def _payload(*games):
    return {"dates": [{"date": "2026-10-13", "games": list(games)}]}


def _payload_bytes(*games):
    return json.dumps(_payload(*games)).encode("utf-8")


class FakeClock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def set(self, value):
        self.now = value

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


def _static_fetcher(raw: bytes):
    def fetch(url: str) -> bytes:
        return raw

    return fetch


class _FakeResponse:
    """Minimal stand-in for an urlopen response (context manager + read)."""

    def __init__(self, raw: bytes):
        self._raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._raw


def _fake_opener(raw: bytes):
    def opener(req, timeout=None):
        return _FakeResponse(raw)

    return opener


def _plan(payload, planned_at):
    return build_plan(payload, planned_at=planned_at)


def _game1_plan(planned_at=datetime(2026, 10, 12, 12, 0, tzinfo=UTC)):
    plan = _plan(_payload(_game(GAME1_PK, GAME1_PITCH)), planned_at)
    assert not plan["issues"], plan["issues"]
    return plan, plan["games"][0]


class PlanTests(unittest.TestCase):
    def test_schedule_url_covers_every_game_type_including_postseason(self):
        params = parse_qs(urlparse(schedule_url("2026-10-23")).query)
        self.assertEqual(params["gameType"], [",".join(GAME_TYPES)])
        for required in ("R", "F", "D", "L", "W"):
            self.assertIn(required, params["gameType"][0].split(","))
        self.assertEqual(params["sportId"], ["1"])
        self.assertEqual(params["hydrate"], ["probablePitcher,lineups"])

    def test_plan_slots_keyed_to_first_pitch_with_design_windows(self):
        _, game = _game1_plan()
        slots = {s["slot_id"]: s for s in game["slots"]}
        self.assertEqual(
            set(slots), {"T-24H", "T-6H", "T-90M", "T-30M", "T-5M"}
        )
        self.assertEqual(slots["T-24H"]["due_at_utc"], "2026-10-12T23:05:00+00:00")
        self.assertEqual(slots["T-6H"]["due_at_utc"], "2026-10-13T17:05:00+00:00")
        self.assertEqual(slots["T-90M"]["due_at_utc"], "2026-10-13T21:35:00+00:00")
        t30 = slots["T-30M"]
        self.assertEqual(t30["due_at_utc"], "2026-10-13T22:35:00+00:00")
        self.assertEqual(t30["window_start_utc"], "2026-10-13T22:30:00+00:00")
        self.assertEqual(t30["window_end_utc"], "2026-10-13T22:40:00+00:00")
        t5 = slots["T-5M"]
        self.assertEqual(t5["due_at_utc"], "2026-10-13T23:00:00+00:00")
        self.assertEqual(t5["window_start_utc"], "2026-10-13T22:58:00+00:00")
        self.assertEqual(t5["window_end_utc"], "2026-10-13T23:02:00+00:00")

    def test_plan_fails_closed_on_missing_team_id(self):
        game = _game(GAME1_PK, GAME1_PITCH)
        del game["teams"]["home"]["team"]["id"]
        plan = _plan(_payload(game), datetime(2026, 10, 12, tzinfo=UTC))
        self.assertEqual(plan["games"], [])
        self.assertEqual(
            plan["issues"], [{"game_pk": GAME1_PK, "reason": "TEAM_ID_MISSING"}]
        )

    def test_naive_plan_time_refused(self):
        with self.assertRaises(StarterCaptureError) as ctx:
            build_plan(_payload(_game(GAME1_PK, GAME1_PITCH)), planned_at=datetime(2026, 10, 12))
        self.assertIn("CAPTURE_CLOCK_UNVERIFIED", str(ctx.exception))


class CaptureTests(unittest.TestCase):
    def test_on_time_capture_binds_ids_and_stamps_after_fetch(self):
        _, game = _game1_plan()
        clock = FakeClock(datetime(2026, 10, 13, 22, 34, tzinfo=UTC))

        def fetch(url: str) -> bytes:
            # The fetch "takes" a minute; the receipt time must be the
            # completion time (22:35), never the pre-fetch time (22:34).
            clock.advance(minutes=1)
            return _payload_bytes(_game(GAME1_PK, GAME1_PITCH))

        record = capture_snapshot(game, "T-30M", fetcher=fetch, clock=clock)
        self.assertEqual(record["record_status"], "CAPTURED")
        self.assertEqual(record["slot_disposition"], "ON_TIME")
        self.assertEqual(record["captured_at_utc"], "2026-10-13T22:35:00+00:00")
        self.assertEqual(record["minutes_to_first_pitch"], 30.0)
        self.assertEqual(record["away_team_id"], AWAY_TEAM)
        self.assertEqual(record["home_team_id"], HOME_TEAM)
        self.assertEqual(record["away_probable_id"], AWAY_PROB)
        self.assertEqual(record["home_probable_id"], HOME_PROB)
        self.assertEqual(record["away_probable_status"], "BOUND")
        self.assertEqual(record["home_probable_status"], "BOUND")
        self.assertEqual(record["observation_details"], [])
        self.assertEqual(record["game_type"], "R")
        self.assertIsNone(record["failure_reason"])

    def test_name_only_probable_fails_closed_and_is_never_recorded(self):
        _, game = _game1_plan()
        raw = _payload_bytes(_game(GAME1_PK, GAME1_PITCH, away_prob=("name_only",)))
        clock = FakeClock(datetime(2026, 10, 13, 22, 35, tzinfo=UTC))
        record = capture_snapshot(game, "T-30M", fetcher=_static_fetcher(raw), clock=clock)
        self.assertEqual(record["record_status"], "FAILED")
        self.assertEqual(record["failure_reason"], "PROBABLE_PITCHER_ID_MISSING:AWAY")
        self.assertIsNone(record["away_probable_id"])
        # Per-side identity states are explicit (owner ruling, Oct 13
        # 2026): the name-only side is ID_MISSING; the other side stays
        # BOUND with its ID preserved on the (failed) record.
        self.assertEqual(record["away_probable_status"], "ID_MISSING")
        self.assertEqual(record["home_probable_status"], "BOUND")
        self.assertEqual(record["home_probable_id"], HOME_PROB)
        # The untrusted name must not appear anywhere in the record.
        self.assertNotIn("Name Only", json.dumps(record))

    def test_absent_probable_is_observed_as_not_announced(self):
        # RE-CONTRACTED by the owner ruling of Oct 13, 2026 (see
        # REPORT.md §8): this test previously expected a FAILED record.
        # NOT_ANNOUNCED is now a valid OBSERVED observation of an
        # unknown starter — it binds no identity and is never treated
        # as one, but the observation and its timestamp are evidence.
        _, game = _game1_plan()
        raw = _payload_bytes(_game(GAME1_PK, GAME1_PITCH, home_prob=("absent",)))
        clock = FakeClock(datetime(2026, 10, 13, 22, 35, tzinfo=UTC))
        record = capture_snapshot(game, "T-30M", fetcher=_static_fetcher(raw), clock=clock)
        self.assertEqual(record["record_status"], "OBSERVED")
        self.assertIsNone(record["failure_reason"])
        self.assertEqual(
            record["observation_details"], ["PROBABLE_PITCHER_NOT_ANNOUNCED:HOME"]
        )
        self.assertEqual(record["home_probable_status"], "NOT_ANNOUNCED")
        self.assertIsNone(record["home_probable_id"])
        self.assertEqual(record["away_probable_status"], "BOUND")
        self.assertEqual(record["away_probable_id"], AWAY_PROB)
        self.assertEqual(record["captured_at_utc"], "2026-10-13T22:35:00+00:00")

    def test_mixed_announced_and_not_announced_is_observed_one_side_bound(self):
        # Owner ruling (Oct 13, 2026): one side announced with an ID,
        # the other not yet announced -> a single OBSERVED record with
        # exactly one side bound; the unbound side is explicit.
        _, game = _game1_plan()
        raw = _payload_bytes(_game(GAME1_PK, GAME1_PITCH, home_prob=("absent",)))
        clock = FakeClock(datetime(2026, 10, 13, 22, 35, tzinfo=UTC))
        record = capture_snapshot(game, "T-30M", fetcher=_static_fetcher(raw), clock=clock)
        self.assertEqual(record["record_status"], "OBSERVED")
        self.assertIsNone(record["failure_reason"])
        self.assertEqual(record["away_probable_status"], "BOUND")
        self.assertEqual(record["away_probable_id"], AWAY_PROB)
        self.assertEqual(record["home_probable_status"], "NOT_ANNOUNCED")
        self.assertIsNone(record["home_probable_id"])
        self.assertEqual(
            record["observation_details"], ["PROBABLE_PITCHER_NOT_ANNOUNCED:HOME"]
        )

    def test_mixed_bound_and_id_missing_fails_closed(self):
        # Owner ruling (Oct 13, 2026): if EITHER side is ID_MISSING the
        # record is FAILED — the purported binding is unusable — with
        # per-side detail preserved.
        _, game = _game1_plan()
        raw = _payload_bytes(_game(GAME1_PK, GAME1_PITCH, home_prob=("name_only",)))
        clock = FakeClock(datetime(2026, 10, 13, 22, 35, tzinfo=UTC))
        record = capture_snapshot(game, "T-30M", fetcher=_static_fetcher(raw), clock=clock)
        self.assertEqual(record["record_status"], "FAILED")
        self.assertEqual(record["failure_reason"], "PROBABLE_PITCHER_ID_MISSING:HOME")
        self.assertEqual(record["away_probable_status"], "BOUND")
        self.assertEqual(record["away_probable_id"], AWAY_PROB)
        self.assertEqual(record["home_probable_status"], "ID_MISSING")
        self.assertIsNone(record["home_probable_id"])

    def test_naive_clock_refused(self):
        _, game = _game1_plan()
        naive_clock = FakeClock(datetime(2026, 10, 13, 22, 35))  # no tzinfo
        with self.assertRaises(StarterCaptureError) as ctx:
            capture_snapshot(
                game,
                "T-30M",
                fetcher=_static_fetcher(_payload_bytes(_game(GAME1_PK, GAME1_PITCH))),
                clock=naive_clock,
            )
        self.assertIn("CAPTURE_CLOCK_UNVERIFIED", str(ctx.exception))

    def test_capture_completed_after_first_pitch_fails_closed(self):
        _, game = _game1_plan()
        clock = FakeClock(GAME1_PITCH + timedelta(minutes=1))
        record = capture_snapshot(
            game,
            "T-5M",
            fetcher=_static_fetcher(_payload_bytes(_game(GAME1_PK, GAME1_PITCH))),
            clock=clock,
        )
        self.assertEqual(record["record_status"], "FAILED")
        self.assertEqual(
            record["failure_reason"], "CAPTURE_COMPLETED_AFTER_FIRST_PITCH"
        )

    def test_fetch_failure_records_attempt_with_reason(self):
        _, game = _game1_plan()

        def boom(url: str) -> bytes:
            raise RuntimeError("HTTP 503")

        clock = FakeClock(datetime(2026, 10, 13, 22, 35, tzinfo=UTC))
        record = capture_snapshot(game, "T-30M", fetcher=boom, clock=clock)
        self.assertEqual(record["record_type"], "CAPTURE_ATTEMPT_FAILED")
        self.assertEqual(record["failure_reason"], "FETCH_FAILED")
        self.assertIn("HTTP 503", record["failure_detail"])

    def test_postseason_world_series_capture_matches_regular_season(self):
        payload = _payload(
            _game(
                GAME2_PK,
                GAME2_PITCH,
                game_type="W",
                official_date="2026-10-23",
                away_prob=("id", 700001),
                home_prob=("id", 700002),
            )
        )
        plan = _plan(payload, datetime(2026, 10, 22, 12, 0, tzinfo=UTC))
        self.assertEqual(plan["issues"], [])
        game = plan["games"][0]
        self.assertEqual(game["game_type"], "W")
        clock = FakeClock(GAME2_PITCH - timedelta(minutes=30))
        raw = _payload_bytes(
            _game(
                GAME2_PK,
                GAME2_PITCH,
                game_type="W",
                official_date="2026-10-23",
                away_prob=("id", 700001),
                home_prob=("id", 700002),
            )
        )
        record = capture_snapshot(game, "T-30M", fetcher=_static_fetcher(raw), clock=clock)
        self.assertEqual(record["record_status"], "CAPTURED")
        self.assertEqual(record["game_type"], "W")
        self.assertEqual(record["away_probable_id"], 700001)
        self.assertEqual(record["home_probable_id"], 700002)
        self.assertEqual(record["slot_disposition"], "ON_TIME")

    def test_doubleheader_games_keyed_by_gamepk(self):
        g1 = _game(
            745101, datetime(2026, 10, 13, 17, 5, tzinfo=UTC),
            away_prob=("id", 800001), home_prob=("id", 800002),
            double_header="Y", game_number=1,
        )
        g2 = _game(
            745102, GAME1_PITCH,
            away_prob=("id", 800003), home_prob=("id", 800004),
            double_header="Y", game_number=2,
        )
        plan = _plan(_payload(g1, g2), datetime(2026, 10, 12, 12, 0, tzinfo=UTC))
        self.assertEqual(len(plan["games"]), 2)
        game2 = next(g for g in plan["games"] if g["game_pk"] == 745102)
        clock = FakeClock(datetime(2026, 10, 13, 22, 35, tzinfo=UTC))
        record = capture_snapshot(
            game2, "T-30M", fetcher=_static_fetcher(_payload_bytes(g1, g2)), clock=clock
        )
        self.assertEqual(record["record_status"], "CAPTURED")
        self.assertEqual(record["game_pk"], 745102)
        self.assertEqual(record["away_probable_id"], 800003)
        self.assertEqual(record["home_probable_id"], 800004)


class ProductionPathTests(unittest.TestCase):
    """Owner audit point (Oct 13, 2026): caller-supplied timestamps.

    The production wrapper must leave no parameter through which a
    caller-supplied time (or fetcher) can reach an emitted record, and
    the timestamps it emits must be the real system clock's readings.
    """

    def test_production_wrapper_accepts_no_clock_or_fetcher(self):
        import inspect

        params = inspect.signature(capture_snapshot_production).parameters
        self.assertNotIn("clock", params)
        self.assertNotIn("fetcher", params)
        _, game = _game1_plan()
        with self.assertRaises(TypeError):
            capture_snapshot_production(
                game,
                "T-30M",
                opener=_fake_opener(_payload_bytes(_game(GAME1_PK, GAME1_PITCH))),
                clock=lambda: datetime(2026, 10, 13, 22, 35, tzinfo=UTC),
            )

    def test_production_wrapper_timestamps_come_from_the_system_clock(self):
        _, game = _game1_plan()
        raw = _payload_bytes(_game(GAME1_PK, GAME1_PITCH))
        before = datetime.now(UTC)
        record = capture_snapshot_production(
            game, "T-30M", opener=_fake_opener(raw)
        )
        after = datetime.now(UTC)
        # The receipt time is bracketed by the real system times around
        # the call — it is neither the fixture era the injected-clock
        # tests use (22:35) nor any other supplied value.
        captured = datetime.fromisoformat(record["captured_at_utc"])
        self.assertLessEqual(before, captured)
        self.assertLessEqual(captured, after)
        self.assertEqual(record["record_status"], "CAPTURED")
        self.assertEqual(record["away_probable_id"], AWAY_PROB)


class MissedSlotTests(unittest.TestCase):
    def test_slots_missed_once_window_closes(self):
        plan, _ = _game1_plan()
        missed = evaluate_missed_slots(
            plan, [], now=datetime(2026, 10, 13, 22, 0, tzinfo=UTC)
        )
        by_slot = {m["slot_id"]: m for m in missed}
        # T-24H, T-6H, T-90M windows have closed; T-30M/T-5M still open.
        self.assertEqual(set(by_slot), {"T-24H", "T-6H", "T-90M"})
        for record in missed:
            self.assertEqual(record["reason"], "NO_CAPTURE_IN_WINDOW")
            self.assertEqual(record["record_type"], "MISSED_SLOT")

    def test_slot_due_before_plan_is_not_yet_scheduled(self):
        # Plan first sees the game at Oct 13 12:00Z — the T-24H window
        # already closed Oct 12 23:35Z.
        plan, _ = _game1_plan(planned_at=datetime(2026, 10, 13, 12, 0, tzinfo=UTC))
        missed = evaluate_missed_slots(
            plan, [], now=datetime(2026, 10, 13, 12, 5, tzinfo=UTC)
        )
        self.assertEqual(len(missed), 1)
        self.assertEqual(missed[0]["slot_id"], "T-24H")
        self.assertEqual(missed[0]["reason"], "NOT_YET_SCHEDULED")

    def test_late_capture_is_labeled_and_never_satisfies_its_slot(self):
        plan, game = _game1_plan()
        clock = FakeClock(datetime(2026, 10, 13, 22, 45, tzinfo=UTC))  # due 22:35 ±5
        record = capture_snapshot(
            game,
            "T-30M",
            fetcher=_static_fetcher(_payload_bytes(_game(GAME1_PK, GAME1_PITCH))),
            clock=clock,
        )
        self.assertEqual(record["slot_disposition"], "LATE")
        self.assertEqual(record["record_status"], "CAPTURED")
        self.assertEqual(record["captured_at_utc"], "2026-10-13T22:45:00+00:00")
        missed = evaluate_missed_slots(
            plan, [record], now=datetime(2026, 10, 13, 22, 50, tzinfo=UTC)
        )
        t30 = [m for m in missed if m["slot_id"] == "T-30M"]
        self.assertEqual(len(t30), 1)
        self.assertEqual(t30[0]["reason"], "NO_CAPTURE_IN_WINDOW")

    def test_failed_attempt_explains_the_miss(self):
        plan, game = _game1_plan()

        def boom(url: str) -> bytes:
            raise RuntimeError("HTTP 503")

        clock = FakeClock(datetime(2026, 10, 13, 22, 35, tzinfo=UTC))
        attempt = capture_snapshot(game, "T-30M", fetcher=boom, clock=clock)
        missed = evaluate_missed_slots(
            plan, [attempt], now=datetime(2026, 10, 13, 22, 50, tzinfo=UTC)
        )
        t30 = [m for m in missed if m["slot_id"] == "T-30M"]
        self.assertEqual(len(t30), 1)
        self.assertEqual(t30[0]["reason"], "CAPTURE_FAILED:FETCH_FAILED")

    def test_observed_not_announced_on_time_satisfies_t24h_slot(self):
        # Owner ruling (Oct 13, 2026): at T-24H nothing may be
        # announced yet. An on-time OBSERVED capture ran and observed
        # the announcement state, so the slot is satisfied — no
        # MISSED_SLOT — while binding no identity at all.
        plan, game = _game1_plan()
        raw = _payload_bytes(
            _game(GAME1_PK, GAME1_PITCH, away_prob=("absent",), home_prob=("absent",))
        )
        clock = FakeClock(datetime(2026, 10, 12, 23, 5, tzinfo=UTC))
        record = capture_snapshot(game, "T-24H", fetcher=_static_fetcher(raw), clock=clock)
        self.assertEqual(record["record_status"], "OBSERVED")
        self.assertEqual(record["slot_disposition"], "ON_TIME")
        self.assertIsNone(record["away_probable_id"])
        self.assertIsNone(record["home_probable_id"])
        self.assertEqual(record["away_probable_status"], "NOT_ANNOUNCED")
        self.assertEqual(record["home_probable_status"], "NOT_ANNOUNCED")
        self.assertEqual(
            record["observation_details"],
            [
                "PROBABLE_PITCHER_NOT_ANNOUNCED:AWAY",
                "PROBABLE_PITCHER_NOT_ANNOUNCED:HOME",
            ],
        )
        missed = evaluate_missed_slots(
            plan, [record], now=datetime(2026, 10, 12, 23, 40, tzinfo=UTC)
        )
        self.assertEqual(missed, [])

    def test_late_observed_record_does_not_satisfy_its_slot(self):
        # A LATE observation is stored as late evidence but never
        # satisfies the slot it missed (unchanged late semantics).
        plan, game = _game1_plan()
        raw = _payload_bytes(_game(GAME1_PK, GAME1_PITCH, home_prob=("absent",)))
        clock = FakeClock(datetime(2026, 10, 13, 22, 45, tzinfo=UTC))  # window ends 22:40
        record = capture_snapshot(game, "T-30M", fetcher=_static_fetcher(raw), clock=clock)
        self.assertEqual(record["record_status"], "OBSERVED")
        self.assertEqual(record["slot_disposition"], "LATE")
        self.assertEqual(record["captured_at_utc"], "2026-10-13T22:45:00+00:00")
        missed = evaluate_missed_slots(
            plan, [record], now=datetime(2026, 10, 13, 22, 50, tzinfo=UTC)
        )
        t30 = [m for m in missed if m["slot_id"] == "T-30M"]
        self.assertEqual(len(t30), 1)
        self.assertEqual(t30[0]["reason"], "NO_CAPTURE_IN_WINDOW")

    def test_id_missing_failure_explains_the_miss(self):
        # Under the ruling's taxonomy the ID_MISSING failure (unusable
        # binding) leaves the slot unsatisfied, and the missed record
        # cites the failure verbatim.
        plan, game = _game1_plan()
        raw = _payload_bytes(_game(GAME1_PK, GAME1_PITCH, away_prob=("name_only",)))
        clock = FakeClock(datetime(2026, 10, 13, 22, 35, tzinfo=UTC))
        record = capture_snapshot(game, "T-30M", fetcher=_static_fetcher(raw), clock=clock)
        self.assertEqual(record["record_status"], "FAILED")
        missed = evaluate_missed_slots(
            plan, [record], now=datetime(2026, 10, 13, 22, 50, tzinfo=UTC)
        )
        t30 = [m for m in missed if m["slot_id"] == "T-30M"]
        self.assertEqual(len(t30), 1)
        self.assertEqual(
            t30[0]["reason"], "CAPTURE_FAILED:PROBABLE_PITCHER_ID_MISSING:AWAY"
        )

    def test_missed_evaluation_is_idempotent(self):
        plan, _ = _game1_plan()
        now = datetime(2026, 10, 13, 22, 0, tzinfo=UTC)
        first = evaluate_missed_slots(plan, [], now=now)
        second = evaluate_missed_slots(plan, first, now=now)
        self.assertEqual(second, [])


class ChangeDetectionTests(unittest.TestCase):
    def _snap(self, payload_game, slot_id, when):
        _, game = _game1_plan()
        clock = FakeClock(when)
        return capture_snapshot(
            game, slot_id, fetcher=_static_fetcher(_payload_bytes(payload_game)), clock=clock
        )

    def test_starter_change_between_snapshots(self):
        early = self._snap(
            _game(GAME1_PK, GAME1_PITCH, away_prob=("id", 111111)),
            "T-6H",
            datetime(2026, 10, 13, 17, 5, tzinfo=UTC),
        )
        late = self._snap(
            _game(GAME1_PK, GAME1_PITCH, away_prob=("id", 222222)),
            "T-30M",
            datetime(2026, 10, 13, 22, 35, tzinfo=UTC),
        )
        events = detect_changes([early, late])
        starter = [e for e in events if e["change_kind"] == "STARTER_CHANGE"]
        self.assertEqual(len(starter), 1)
        self.assertEqual(starter[0]["change_detail"], "CHANGED")
        self.assertEqual(starter[0]["side"], "away")
        self.assertEqual(starter[0]["from_value"], 111111)
        self.assertEqual(starter[0]["to_value"], 222222)

    def test_starter_announcement_between_snapshots(self):
        early = self._snap(
            _game(GAME1_PK, GAME1_PITCH, away_prob=("absent",)),
            "T-6H",
            datetime(2026, 10, 13, 17, 5, tzinfo=UTC),
        )
        late = self._snap(
            _game(GAME1_PK, GAME1_PITCH, away_prob=("id", 222222)),
            "T-30M",
            datetime(2026, 10, 13, 22, 35, tzinfo=UTC),
        )
        events = detect_changes([early, late])
        starter = [e for e in events if e["change_kind"] == "STARTER_CHANGE"]
        self.assertEqual(len(starter), 1)
        self.assertEqual(starter[0]["change_detail"], "ANNOUNCED")
        self.assertIsNone(starter[0]["from_value"])
        self.assertEqual(starter[0]["to_value"], 222222)

    def test_observed_record_is_never_upgraded_in_the_evidence_stream(self):
        # Owner ruling (Oct 13, 2026): a later announcement derives an
        # ANNOUNCED event from the stream — it must never rewrite the
        # earlier OBSERVED record into a binding one.
        with tempfile.TemporaryDirectory() as tmp:
            capture_path = Path(tmp) / "captures.jsonl"
            manifest_path = Path(tmp) / "manifest.jsonl"
            early = self._snap(
                _game(GAME1_PK, GAME1_PITCH, away_prob=("absent",)),
                "T-24H",
                datetime(2026, 10, 12, 23, 5, tzinfo=UTC),
            )
            late = self._snap(
                _game(GAME1_PK, GAME1_PITCH, away_prob=("id", 222222)),
                "T-30M",
                datetime(2026, 10, 13, 22, 35, tzinfo=UTC),
            )
            self.assertEqual(early["record_status"], "OBSERVED")
            self.assertIsNone(early["away_probable_id"])
            for record in (early, late):
                append_record(capture_path, manifest_path, record)
            events = detect_changes(read_records(capture_path))
            starter = [e for e in events if e["change_kind"] == "STARTER_CHANGE"]
            self.assertEqual(len(starter), 1)
            self.assertEqual(starter[0]["change_detail"], "ANNOUNCED")
            self.assertIsNone(starter[0]["from_value"])
            self.assertEqual(starter[0]["to_value"], 222222)
            # The stored OBSERVED record is exactly the record that was
            # captured — same bytes, same unverified state — and the
            # hash chain still verifies over the untouched stream.
            stored = read_records(capture_path)
            self.assertEqual(stored[0], early)
            self.assertEqual(stored[0]["record_status"], "OBSERVED")
            self.assertEqual(stored[0]["away_probable_status"], "NOT_ANNOUNCED")
            self.assertTrue(verify_capture_chain(capture_path, manifest_path)["ok"])

    def test_postponement_and_first_pitch_move_are_schedule_changes(self):
        early = self._snap(
            _game(GAME1_PK, GAME1_PITCH),
            "T-6H",
            datetime(2026, 10, 13, 17, 5, tzinfo=UTC),
        )
        moved = _game(
            GAME1_PK,
            datetime(2026, 10, 14, 23, 5, tzinfo=UTC),
            detailed="Postponed",
            coded="D",
        )
        late = self._snap(moved, "T-30M", datetime(2026, 10, 13, 22, 35, tzinfo=UTC))
        events = detect_changes([early, late])
        schedule = [e for e in events if e["change_kind"] == "SCHEDULE_CHANGE"]
        details = {e["change_detail"] for e in schedule}
        self.assertEqual(details, {"FIRST_PITCH_MOVED", "POSTPONED"})
        moved_event = next(e for e in schedule if e["change_detail"] == "FIRST_PITCH_MOVED")
        self.assertEqual(moved_event["from_value"], "2026-10-13T23:05:00+00:00")
        self.assertEqual(moved_event["to_value"], "2026-10-14T23:05:00+00:00")


class RescheduleEpochTests(unittest.TestCase):
    """Owner finding (Oct 13, 2026, recorded on PR #2163): "I reproduced
    an old capture incorrectly satisfying a rescheduled game's new
    slot."

    Root cause: slot satisfaction and missed-slot idempotency were
    keyed by (gamePk, slot_id) alone, so a capture taken under the
    original schedule counted toward the replanned schedule for the
    same game. The binding rule these tests pin: a capture belongs to
    the plan epoch it was taken under — the scheduled first pitch
    stamped on the record as ``planned_first_pitch_utc`` — and can
    satisfy only slots of a plan whose first pitch equals that stamp.
    An old-shape record without the stamp fails closed: it satisfies
    nothing and its failures explain nothing.
    """

    NEW_PITCH = datetime(2026, 10, 15, 23, 5, tzinfo=UTC)  # T + 2 days

    def _plan2(self):
        payload = _payload(
            _game(GAME1_PK, self.NEW_PITCH, official_date="2026-10-15")
        )
        plan = _plan(payload, datetime(2026, 10, 14, 12, 0, tzinfo=UTC))
        assert not plan["issues"], plan["issues"]
        return plan, plan["games"][0]

    def test_old_capture_does_not_satisfy_rescheduled_games_new_slot(self):
        # The owner's reproduction: plan at T, take an on-time
        # identity-valid T-6H capture, reschedule to T+2d, replan.
        plan1, game1 = _game1_plan()
        clock = FakeClock(datetime(2026, 10, 13, 17, 5, tzinfo=UTC))
        record = capture_snapshot(
            game1,
            "T-6H",
            fetcher=_static_fetcher(_payload_bytes(_game(GAME1_PK, GAME1_PITCH))),
            clock=clock,
        )
        self.assertEqual(record["record_status"], "CAPTURED")
        self.assertEqual(record["slot_disposition"], "ON_TIME")
        # The capture is stamped with the first pitch it was planned
        # against — the epoch it belongs to.
        self.assertEqual(
            record.get("planned_first_pitch_utc"), "2026-10-13T23:05:00+00:00"
        )
        # Sanity: it still satisfies its OWN plan's T-6H slot.
        own = evaluate_missed_slots(
            plan1, [record], now=datetime(2026, 10, 13, 18, 0, tzinfo=UTC)
        )
        self.assertNotIn("T-6H", {m["slot_id"] for m in own})
        # The new plan (first pitch T+2d) must NOT inherit it: once the
        # new T-6H window closes, the slot is reported missed.
        plan2, _ = self._plan2()
        missed = evaluate_missed_slots(
            plan2, [record], now=datetime(2026, 10, 15, 18, 0, tzinfo=UTC)
        )
        by_slot = {m["slot_id"]: m for m in missed}
        self.assertIn("T-6H", by_slot)
        self.assertEqual(by_slot["T-6H"]["reason"], "NO_CAPTURE_IN_WINDOW")
        self.assertEqual(
            by_slot["T-6H"]["game_date_utc"], "2026-10-15T23:05:00+00:00"
        )

    def test_missed_record_from_another_epoch_does_not_suppress(self):
        # A MISSED_SLOT record belongs to the plan epoch that generated
        # it (its game_date_utc): it must not suppress the same slot of
        # a different epoch's plan (idempotency is per-epoch).
        plan2, _ = self._plan2()
        missed2 = evaluate_missed_slots(
            plan2, [], now=datetime(2026, 10, 15, 18, 0, tzinfo=UTC)
        )
        self.assertIn("T-6H", {m["slot_id"] for m in missed2})
        plan1, _ = _game1_plan()
        missed1 = evaluate_missed_slots(
            plan1, missed2, now=datetime(2026, 10, 13, 18, 0, tzinfo=UTC)
        )
        by_slot = {m["slot_id"]: m for m in missed1}
        self.assertIn("T-6H", by_slot)
        self.assertEqual(by_slot["T-6H"]["reason"], "NO_CAPTURE_IN_WINDOW")

    def test_postponement_without_new_start_lets_old_captures_satisfy_nothing_later(self):
        # Postponed with no new start announced: epoch-1 records exist
        # (a bound T-24H capture and the postponement observation
        # itself). When the game is eventually replanned days later,
        # none of them may satisfy the new plan's slots.
        plan1, game1 = _game1_plan()
        clock = FakeClock(datetime(2026, 10, 12, 23, 5, tzinfo=UTC))
        early = capture_snapshot(
            game1,
            "T-24H",
            fetcher=_static_fetcher(_payload_bytes(_game(GAME1_PK, GAME1_PITCH))),
            clock=clock,
        )
        self.assertEqual(early["record_status"], "CAPTURED")
        postponed_raw = _payload_bytes(
            _game(
                GAME1_PK,
                GAME1_PITCH,
                detailed="Postponed",
                coded="D",
                away_prob=("absent",),
                home_prob=("absent",),
            )
        )
        clock.set(datetime(2026, 10, 13, 17, 5, tzinfo=UTC))
        postponed = capture_snapshot(
            game1, "T-6H", fetcher=_static_fetcher(postponed_raw), clock=clock
        )
        self.assertEqual(postponed["record_status"], "OBSERVED")
        # Days later the game gets its new start (Oct 16) and a new plan.
        plan3 = _plan(
            _payload(
                _game(
                    GAME1_PK,
                    datetime(2026, 10, 16, 23, 5, tzinfo=UTC),
                    official_date="2026-10-16",
                )
            ),
            datetime(2026, 10, 14, 9, 0, tzinfo=UTC),
        )
        assert not plan3["issues"], plan3["issues"]
        missed = evaluate_missed_slots(
            plan3,
            [early, postponed],
            now=datetime(2026, 10, 16, 18, 0, tzinfo=UTC),
        )
        by_slot = {m["slot_id"]: m for m in missed}
        self.assertEqual(by_slot["T-24H"]["reason"], "NO_CAPTURE_IN_WINDOW")
        self.assertEqual(by_slot["T-6H"]["reason"], "NO_CAPTURE_IN_WINDOW")

    def test_same_day_first_pitch_move_old_capture_cannot_satisfy_new_plan(self):
        # 1:05pm -> 7:05pm-style move (17:05Z -> 23:05Z the same day):
        # the afternoon plan's on-time T-90M capture must not satisfy
        # the evening plan's T-90M slot.
        afternoon = datetime(2026, 10, 13, 17, 5, tzinfo=UTC)
        plan_a = _plan(
            _payload(_game(GAME1_PK, afternoon)),
            datetime(2026, 10, 12, 12, 0, tzinfo=UTC),
        )
        game_a = plan_a["games"][0]
        clock = FakeClock(datetime(2026, 10, 13, 15, 35, tzinfo=UTC))
        record = capture_snapshot(
            game_a,
            "T-90M",
            fetcher=_static_fetcher(_payload_bytes(_game(GAME1_PK, afternoon))),
            clock=clock,
        )
        self.assertEqual(record["record_status"], "CAPTURED")
        self.assertEqual(record["slot_disposition"], "ON_TIME")
        plan_b, _ = _game1_plan(planned_at=datetime(2026, 10, 13, 16, 0, tzinfo=UTC))
        missed = evaluate_missed_slots(
            plan_b, [record], now=datetime(2026, 10, 13, 22, 0, tzinfo=UTC)
        )
        by_slot = {m["slot_id"]: m for m in missed}
        self.assertEqual(by_slot["T-90M"]["reason"], "NO_CAPTURE_IN_WINDOW")
        self.assertEqual(by_slot["T-6H"]["reason"], "NO_CAPTURE_IN_WINDOW")
        # The evening plan first saw the game after its T-24H window
        # had closed — the pre-plan case still classifies correctly.
        self.assertEqual(by_slot["T-24H"]["reason"], "NOT_YET_SCHEDULED")

    def test_old_shape_record_without_binding_fails_closed(self):
        # Evidence written before the epoch stamp existed carries no
        # planned_first_pitch_utc. Absent binding = cannot satisfy any
        # slot, and its failures cannot be attributed to a plan either.
        plan1, game1 = _game1_plan()
        clock = FakeClock(datetime(2026, 10, 13, 22, 35, tzinfo=UTC))
        record = capture_snapshot(
            game1,
            "T-30M",
            fetcher=_static_fetcher(_payload_bytes(_game(GAME1_PK, GAME1_PITCH))),
            clock=clock,
        )
        old_shape = {
            k: v for k, v in record.items() if k != "planned_first_pitch_utc"
        }
        missed = evaluate_missed_slots(
            plan1, [old_shape], now=datetime(2026, 10, 13, 22, 50, tzinfo=UTC)
        )
        t30 = [m for m in missed if m["slot_id"] == "T-30M"]
        self.assertEqual(len(t30), 1)
        self.assertEqual(t30[0]["reason"], "NO_CAPTURE_IN_WINDOW")

        def boom(url: str) -> bytes:
            raise RuntimeError("HTTP 503")

        attempt = capture_snapshot(game1, "T-30M", fetcher=boom, clock=clock)
        old_attempt = {
            k: v for k, v in attempt.items() if k != "planned_first_pitch_utc"
        }
        missed = evaluate_missed_slots(
            plan1, [old_attempt], now=datetime(2026, 10, 13, 22, 50, tzinfo=UTC)
        )
        t30 = [m for m in missed if m["slot_id"] == "T-30M"]
        self.assertEqual(len(t30), 1)
        self.assertEqual(t30[0]["reason"], "NO_CAPTURE_IN_WINDOW")

    def test_cross_epoch_detect_changes_emits_schedule_change_not_starter_change(self):
        # Cross-epoch starter semantics: the pre-reschedule capture is
        # the prior epoch's baseline. The pair straddling the
        # reschedule yields the SCHEDULE_CHANGE event (the move itself)
        # and NO starter event — the new plan's cleared probables are
        # the reschedule's artifact, not a REMOVED decision. The first
        # capture of the new epoch becomes its baseline, and an
        # announcement inside the new epoch is detected normally.
        plan1, game1 = _game1_plan()
        clock = FakeClock(datetime(2026, 10, 13, 17, 5, tzinfo=UTC))
        snap1 = capture_snapshot(
            game1,
            "T-6H",
            fetcher=_static_fetcher(_payload_bytes(_game(GAME1_PK, GAME1_PITCH))),
            clock=clock,
        )
        plan2, game2 = self._plan2()
        cleared = _payload_bytes(
            _game(
                GAME1_PK,
                self.NEW_PITCH,
                official_date="2026-10-15",
                away_prob=("absent",),
                home_prob=("absent",),
            )
        )
        clock.set(datetime(2026, 10, 15, 17, 5, tzinfo=UTC))
        snap2 = capture_snapshot(game2, "T-6H", fetcher=_static_fetcher(cleared), clock=clock)
        self.assertEqual(snap2["record_status"], "OBSERVED")
        events = detect_changes([snap1, snap2])
        schedule = [e for e in events if e["change_kind"] == "SCHEDULE_CHANGE"]
        self.assertIn("FIRST_PITCH_MOVED", {e["change_detail"] for e in schedule})
        self.assertEqual(
            [e for e in events if e["change_kind"] == "STARTER_CHANGE"], []
        )
        announced = _payload_bytes(
            _game(
                GAME1_PK,
                self.NEW_PITCH,
                official_date="2026-10-15",
                away_prob=("id", 222222),
                home_prob=("absent",),
            )
        )
        clock.set(datetime(2026, 10, 15, 22, 35, tzinfo=UTC))
        snap3 = capture_snapshot(
            game2, "T-30M", fetcher=_static_fetcher(announced), clock=clock
        )
        events = detect_changes([snap1, snap2, snap3])
        starter = [e for e in events if e["change_kind"] == "STARTER_CHANGE"]
        self.assertEqual(len(starter), 1)
        self.assertEqual(starter[0]["change_detail"], "ANNOUNCED")
        self.assertEqual(starter[0]["side"], "away")
        self.assertIsNone(starter[0]["from_value"])
        self.assertEqual(starter[0]["to_value"], 222222)

    def test_postponement_straddle_suppresses_phantom_starter_removed(self):
        # Same plan, but the pair straddles the postponement itself:
        # probables cleared in the postponement observation are the
        # postponement's artifact. The POSTPONED schedule event is the
        # record of it; no STARTER_CHANGE/REMOVED is derived.
        plan1, game1 = _game1_plan()
        clock = FakeClock(datetime(2026, 10, 13, 17, 5, tzinfo=UTC))
        snap_a = capture_snapshot(
            game1,
            "T-6H",
            fetcher=_static_fetcher(_payload_bytes(_game(GAME1_PK, GAME1_PITCH))),
            clock=clock,
        )
        postponed_raw = _payload_bytes(
            _game(
                GAME1_PK,
                GAME1_PITCH,
                detailed="Postponed",
                coded="D",
                away_prob=("absent",),
                home_prob=("absent",),
            )
        )
        clock.set(datetime(2026, 10, 13, 22, 35, tzinfo=UTC))
        snap_b = capture_snapshot(
            game1, "T-30M", fetcher=_static_fetcher(postponed_raw), clock=clock
        )
        events = detect_changes([snap_a, snap_b])
        schedule = [e for e in events if e["change_kind"] == "SCHEDULE_CHANGE"]
        self.assertIn("POSTPONED", {e["change_detail"] for e in schedule})
        self.assertEqual(
            [e for e in events if e["change_kind"] == "STARTER_CHANGE"], []
        )


class ManifestTests(unittest.TestCase):
    def _store(self, tmp: Path):
        return tmp / "captures.jsonl", tmp / "manifest.jsonl"

    def _sample_records(self):
        _, game = _game1_plan()
        raw = _payload_bytes(_game(GAME1_PK, GAME1_PITCH))
        clock = FakeClock(datetime(2026, 10, 13, 17, 5, tzinfo=UTC))
        snap1 = capture_snapshot(game, "T-6H", fetcher=_static_fetcher(raw), clock=clock)
        clock.set(datetime(2026, 10, 13, 22, 35, tzinfo=UTC))
        snap2 = capture_snapshot(game, "T-30M", fetcher=_static_fetcher(raw), clock=clock)
        plan, _ = _game1_plan()
        missed = evaluate_missed_slots(
            plan, [snap1, snap2], now=datetime(2026, 10, 13, 22, 0, tzinfo=UTC)
        )
        return [snap1, snap2, *missed]

    def test_chain_continuity_across_records_and_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture_path, manifest_path = self._store(Path(tmp))
            records = self._sample_records()
            entries = [
                append_record(capture_path, manifest_path, r) for r in records
            ]
            self.assertEqual(entries[0]["prev_chain_sha256"], "0" * 64)
            for prev, curr in zip(entries, entries[1:]):
                self.assertEqual(curr["prev_chain_sha256"], prev["chain_sha256"])
                self.assertEqual(curr["seq"], prev["seq"] + 1)
            result = verify_capture_chain(capture_path, manifest_path)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["records_checked"], len(records))
            self.assertEqual(read_records(capture_path), records)
            self.assertEqual(len(read_manifest(manifest_path)), len(records))

    def test_capture_file_tampering_breaks_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture_path, manifest_path = self._store(Path(tmp))
            for record in self._sample_records():
                append_record(capture_path, manifest_path, record)
            lines = capture_path.read_bytes().split(b"\n")
            # Flip one byte inside the second record's line.
            tampered = bytearray(lines[1])
            tampered[20] = ord("X") if tampered[20] != ord("X") else ord("Y")
            lines[1] = bytes(tampered)
            capture_path.write_bytes(b"\n".join(lines))
            result = verify_capture_chain(capture_path, manifest_path)
            self.assertFalse(result["ok"])
            self.assertEqual(
                result["failure"]["reason"], "CAPTURE_RECORD_HASH_MISMATCH"
            )
            self.assertEqual(result["failure"]["seq"], 2)

    def test_deleted_record_breaks_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture_path, manifest_path = self._store(Path(tmp))
            for record in self._sample_records():
                append_record(capture_path, manifest_path, record)
            lines = capture_path.read_bytes().split(b"\n")
            del lines[0]
            capture_path.write_bytes(b"\n".join(lines))
            result = verify_capture_chain(capture_path, manifest_path)
            self.assertFalse(result["ok"])
            self.assertEqual(result["failure"]["reason"], "RECORD_COUNT_MISMATCH")


if __name__ == "__main__":
    unittest.main()
