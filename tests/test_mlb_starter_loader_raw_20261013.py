"""Adversarial tests: starter_capture raw-response store + research loader.

Offline only. Fake clocks drive capture; nothing here manufactures a
receipt time for production. The loader is research-only: success is at
most WATCH and never authorizes pricing or betting.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from sportsedge import mlb_source
from sportsedge.mlb_pit_binding import load_research_starter_binding
from sportsedge.sports.mlb import starter_capture as sc

UTC = timezone.utc
PK = 823001
PITCH = datetime(2026, 10, 13, 23, 5, tzinfo=UTC)
PITCH_S = "2026-10-13T23:05:00Z"
T_CAP = datetime(2026, 10, 13, 22, 35, tzinfo=UTC)
AS_OF = datetime(2026, 10, 13, 22, 50, tzinfo=UTC)
NOW = datetime(2026, 10, 13, 23, 0, tzinfo=UTC)


def _game(pitch=PITCH, away=("id", 605001), home=("id", 605002),
          coded="S", detailed="Scheduled", abstract="Preview"):
    def prob(spec):
        if spec[0] == "absent":
            return {}
        if spec[0] == "name_only":
            return {"probablePitcher": {"fullName": "Name Only"}}
        return {"probablePitcher": {"id": spec[1], "fullName": "X"}}
    return {
        "gamePk": PK, "gameDate": pitch.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "officialDate": "2026-10-13", "gameType": "R", "doubleHeader": "N",
        "gameNumber": 1,
        "status": {"abstractGameState": abstract, "codedGameState": coded,
                   "detailedState": detailed},
        "teams": {"away": {"team": {"id": 111, "name": "A"}, **prob(away)},
                  "home": {"team": {"id": 112, "name": "H"}, **prob(home)}},
    }


def _payload(game):
    return {"dates": [{"date": "2026-10-13", "games": [game]}]}


class Harness:
    def __init__(self, root: Path):
        self.root = root
        self.cap = root / "capture.jsonl"
        self.man = root / "manifest.jsonl"
        self.raw = root / "raw"
        self.rcpt = root / "receipts"
        self.plan = sc.build_plan(_payload(_game()),
                                  planned_at=datetime(2026, 10, 12, 12, tzinfo=UTC))["games"][0]

    def capture(self, game=None, at=T_CAP, receipt=True, receipt_at=None, plan=None):
        raw = json.dumps(_payload(game or _game())).encode()
        r_at = receipt_at or at

        def fetcher(url):
            if receipt:
                with mock.patch.object(mlb_source, "_trusted_now", return_value=r_at):
                    mlb_source.MLBSourceCapture(self.rcpt, clock=lambda: r_at).record(
                        url=url, raw=raw, fetch_started_at=r_at, received_at=r_at)
            return raw

        rec = sc.capture_snapshot_with_raw(plan or self.plan, "T-30M", fetcher=fetcher,
                                           clock=lambda: at, raw_dir=self.raw)
        sc.append_record(self.cap, self.man, rec, verifier_now=NOW)
        return rec

    def load(self, **kw):
        args = dict(capture_path=self.cap, manifest_path=self.man, raw_dir=self.raw,
                    receipt_root=self.rcpt, game_pk=PK, as_of=AS_OF,
                    plan_first_pitch_utc=PITCH_S, verifier_now=NOW)
        args.update(kw)
        return load_research_starter_binding(**args)


class Base(unittest.TestCase):
    def setUp(self):
        if getattr(self, "_tmp", None) is not None:
            self._tmp.cleanup()
        self._tmp = tempfile.TemporaryDirectory()
        self.h = Harness(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def assertBlocked(self, out, reason):
        self.assertEqual(out["binding_status"], "BLOCKED", out)
        self.assertTrue(out["block_reason"].startswith(reason), out["block_reason"])
        self.assertFalse(out["pricing_authorized"])
        self.assertFalse(out["betting_authorized"])
        self.assertIsNone(out["away_probable_id"])
        self.assertIsNone(out["home_probable_id"])


class RawStoreTests(Base):
    def test_raw_bytes_and_sha_linked_on_record(self):
        rec = self.h.capture()
        self.assertEqual(rec["raw_sha256"], rec["response_sha256"])
        self.assertEqual(rec["raw_store_kind"], "LOCAL_UNANCHORED_NOT_RETENTION_LOCKED")
        self.assertTrue((self.h.raw / rec["raw_store_file"]).is_file())
        self.assertTrue(sc.verify_raw_store(self.h.cap, self.h.raw)["ok"])

    def test_missing_raw_fails_closed(self):
        rec = self.h.capture()
        (self.h.raw / rec["raw_store_file"]).unlink()
        v = sc.verify_raw_store(self.h.cap, self.h.raw)
        self.assertEqual(v["failure"]["reason"], "RAW_BYTES_MISSING")

    def test_tampered_raw_fails_closed(self):
        rec = self.h.capture()
        (self.h.raw / rec["raw_store_file"]).write_bytes(b"{}")
        self.assertEqual(sc.verify_raw_store(self.h.cap, self.h.raw)["failure"]["reason"],
                         "RAW_BYTES_TAMPERED")

    def test_same_length_tamper_fails_closed(self):
        rec = self.h.capture()
        p = self.h.raw / rec["raw_store_file"]
        b = bytearray(p.read_bytes()); b[5] ^= 1; p.write_bytes(bytes(b))
        self.assertEqual(sc.verify_raw_store(self.h.cap, self.h.raw)["failure"]["reason"],
                         "RAW_BYTES_TAMPERED")

    def test_symlinked_raw_fails_closed(self):
        rec = self.h.capture()
        p = self.h.raw / rec["raw_store_file"]
        other = self.h.root / "elsewhere.json"; other.write_bytes(p.read_bytes())
        p.unlink(); p.symlink_to(other)
        self.assertEqual(sc.verify_raw_store(self.h.cap, self.h.raw)["failure"]["reason"],
                         "RAW_STORE_PATH_UNSAFE")

    def test_record_without_raw_link_fails_closed(self):
        raw = json.dumps(_payload(_game())).encode()
        rec = sc.capture_snapshot(self.h.plan, "T-30M", fetcher=lambda u: raw, clock=lambda: T_CAP)
        sc.append_record(self.h.cap, self.h.man, rec, verifier_now=NOW)
        self.assertEqual(sc.verify_raw_store(self.h.cap, self.h.raw)["failure"]["reason"],
                         "RAW_LINK_MISSING")
        self.assertBlocked(self.h.load(), "RAW_BYTES_UNVERIFIED:RAW_LINK_MISSING")

    def test_path_traversal_name_rejected(self):
        raw = json.dumps(_payload(_game())).encode()
        rec = sc.capture_snapshot(self.h.plan, "T-30M", fetcher=lambda u: raw, clock=lambda: T_CAP)
        rec.update(sc.store_raw_response(self.h.raw, raw))
        rec["raw_store_file"] = "../" + rec["raw_store_file"]
        sc.append_record(self.h.cap, self.h.man, rec, verifier_now=NOW)
        self.assertEqual(sc.verify_raw_store(self.h.cap, self.h.raw)["failure"]["reason"],
                         "RAW_STORE_PATH_UNSAFE")

    def test_retention_lock_kind_claim_rejected(self):
        raw = json.dumps(_payload(_game())).encode()
        rec = sc.capture_snapshot(self.h.plan, "T-30M", fetcher=lambda u: raw, clock=lambda: T_CAP)
        rec.update(sc.store_raw_response(self.h.raw, raw))
        rec["raw_store_kind"] = "WORM_RETENTION_LOCKED"
        sc.append_record(self.h.cap, self.h.man, rec, verifier_now=NOW)
        self.assertEqual(sc.verify_raw_store(self.h.cap, self.h.raw)["failure"]["reason"],
                         "RAW_STORE_KIND_INVALID")

    def test_store_collision_refused(self):
        info = sc.store_raw_response(self.h.raw, b"abc")
        (self.h.raw / info["raw_store_file"]).write_bytes(b"abd")
        with self.assertRaisesRegex(sc.StarterCaptureError, "RAW_STORE_COLLISION"):
            sc.store_raw_response(self.h.raw, b"abc")

    def test_fetch_failure_has_no_raw_link_and_verifies(self):
        def boom(url):
            raise OSError("offline")
        rec = sc.capture_snapshot_with_raw(self.h.plan, "T-30M", fetcher=boom,
                                           clock=lambda: T_CAP, raw_dir=self.h.raw)
        self.assertNotIn("raw_sha256", rec)
        sc.append_record(self.h.cap, self.h.man, rec, verifier_now=NOW)
        self.assertTrue(sc.verify_raw_store(self.h.cap, self.h.raw)["ok"])


class LoaderTests(Base):
    def test_happy_path_is_research_watch_only(self):
        self.h.capture()
        out = self.h.load()
        self.assertEqual(out["binding_status"], "RESEARCH_BOUND", out)
        self.assertEqual(out["max_action"], "WATCH")
        self.assertFalse(out["pricing_authorized"])
        self.assertFalse(out["betting_authorized"])
        self.assertFalse(out["model_eligible"])
        self.assertEqual((out["away_probable_id"], out["home_probable_id"]), (605001, 605002))
        self.assertIn("NO_EXTERNAL_TIME_ANCHOR", out["evidence_limits"])

    def test_loader_is_read_only(self):
        self.h.capture()
        before = {p: p.read_bytes() for p in self.h.root.rglob("*") if p.is_file()}
        self.h.load()
        after = {p: p.read_bytes() for p in self.h.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_unverified_chain_blocks(self):
        self.h.capture()
        lines = self.h.cap.read_bytes().replace(b"605001", b"605009")
        self.h.cap.write_bytes(lines)
        self.assertBlocked(self.h.load(), "CAPTURE_CHAIN_UNVERIFIED")

    def test_missing_manifest_blocks(self):
        self.h.capture()
        self.h.man.unlink()
        self.assertBlocked(self.h.load(), "CAPTURE_CHAIN_UNVERIFIED")

    def test_missing_raw_blocks(self):
        rec = self.h.capture()
        (self.h.raw / rec["raw_store_file"]).unlink()
        self.assertBlocked(self.h.load(), "RAW_BYTES_UNVERIFIED:RAW_BYTES_MISSING")

    def test_tampered_receipt_journal_blocks(self):
        self.h.capture()
        j = self.h.rcpt / mlb_source.RECEIPT_JOURNAL_NAME
        j.write_text(j.read_text().replace("22:35:00", "22:34:00"))
        self.assertBlocked(self.h.load(), "RECEIPT_JOURNAL_UNVERIFIED")

    def test_no_receipt_blocks(self):
        self.h.capture(receipt=False)
        self.assertBlocked(self.h.load(), "RECEIPT_NOT_FOUND_FOR_RAW_BYTES")

    def test_receipt_from_different_fetch_blocks(self):
        self.h.capture(receipt_at=T_CAP - timedelta(minutes=10))
        self.assertBlocked(self.h.load(), "RECEIPT_NOT_SAME_FETCH_AS_RECORD")

    def test_receipt_after_as_of_blocks(self):
        self.h.capture()
        out = self.h.load(as_of=T_CAP - timedelta(seconds=1))
        self.assertBlocked(out, "NO_SNAPSHOT_AT_OR_BEFORE_AS_OF")
        # Receipt landed after as_of while record clock claims before it.
        self.setUp()
        self.h.capture(at=AS_OF, receipt_at=AS_OF + timedelta(seconds=3))
        self.assertBlocked(self.h.load(), "RECEIPT_AFTER_AS_OF")

    def test_postponed_blocks(self):
        self.h.capture(game=_game(coded="D", detailed="Postponed"))
        self.assertBlocked(self.h.load(), "POSTPONED_NOT_IDENTITY_EVIDENCE")

    def test_observed_only_blocks(self):
        self.h.capture(game=_game(home=("absent",)))
        self.assertBlocked(self.h.load(), "OBSERVED_ONLY_NOT_IDENTITY_EVIDENCE")

    def test_id_missing_blocks(self):
        self.h.capture(game=_game(away=("name_only",)))
        self.assertBlocked(self.h.load(), "ID_MISSING")

    def test_bad_ids_block(self):
        for bad in ("abc", 0, True, -5, 1.9):
            with self.subTest(bad=bad):
                self.setUp()
                self.h.capture(game=_game(away=("id", bad)))
                self.assertBlocked(self.h.load(), "ID_MISSING")

    def test_live_status_blocks(self):
        self.h.capture(game=_game(coded="I", detailed="In Progress", abstract="Live"))
        self.assertBlocked(self.h.load(), "RECORD_NOT_CAPTURED")

    def test_stale_reschedule_epoch_blocks(self):
        self.h.capture()
        self.assertBlocked(self.h.load(plan_first_pitch_utc="2026-10-14T00:05:00Z"),
                           "STALE_RESCHEDULE_EPOCH")

    def test_later_postponement_supersedes_earlier_bound(self):
        self.h.capture()
        self.h.capture(game=_game(coded="D", detailed="Postponed"),
                       at=T_CAP + timedelta(minutes=5))
        self.assertBlocked(self.h.load(), "POSTPONED_NOT_IDENTITY_EVIDENCE")

    def test_as_of_after_first_pitch_blocks(self):
        self.h.capture()
        self.assertBlocked(self.h.load(as_of=PITCH, verifier_now=PITCH + timedelta(minutes=1)),
                           "AS_OF_NOT_PREGAME")

    def test_naive_as_of_blocks(self):
        self.h.capture()
        self.assertBlocked(self.h.load(as_of=datetime(2026, 10, 13, 22, 50)), "AS_OF_INVALID")

    def test_invalid_game_pk_blocks(self):
        for bad in (True, "823001", 0, None):
            with self.subTest(bad=bad):
                self.assertBlocked(self.h.load(game_pk=bad), "GAME_PK_INVALID")

    def test_y2k_record_clock_blocks(self):
        self.h.capture()
        recs = self.h.cap.read_bytes().replace(b"2026-10-13T22:35:00", b"2000-01-01T00:00:00")
        self.h.cap.write_bytes(recs)
        self.assertBlocked(self.h.load(), "CAPTURE_CHAIN_UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
