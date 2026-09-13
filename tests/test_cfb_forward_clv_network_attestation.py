import unittest
from datetime import datetime, timedelta, timezone

from sportsedge.cfb_forward_clv_network_attestation import build_attestation_record, build_observation

UTC=timezone.utc

class TestNetworkAttestation(unittest.TestCase):
    def summary(self, *, completed=True, first="2026-09-19T18:00:00Z"):
        return {"header":{"competitions":[{"status":{"type":{"completed":completed,"name":"STATUS_FINAL" if completed else "STATUS_IN_PROGRESS"}}}]},"plays":[{"wallclock":first}]}

    def test_single_completed_read_is_not_stable(self):
        o=build_observation(espn_event_id="1",summary=self.summary(),observed_at=datetime(2026,9,20,tzinfo=UTC),raw_sha256="a"*64)
        r=build_attestation_record([o])
        self.assertEqual(r["status"],"PENDING_STABILITY_SECOND_READ")

    def test_two_matching_completed_reads_build_record_but_uncertainty_remains_unverified(self):
        t=datetime(2026,9,20,tzinfo=UTC)
        a=build_observation(espn_event_id="1",summary=self.summary(),observed_at=t,raw_sha256="a"*64)
        b=build_observation(espn_event_id="1",summary=self.summary(),observed_at=t+timedelta(minutes=5),raw_sha256="b"*64)
        r=build_attestation_record([a,b])
        self.assertEqual(r["status"],"STABILITY_OBSERVED_NOT_EVIDENCE_BY_ITSELF")
        self.assertEqual(r["prior_snapshot_sha256"],r["current_snapshot_sha256"])
        self.assertIsNone(r["timestamp_uncertainty_seconds"])
        self.assertEqual(r["timestamp_uncertainty_status"],"UNVERIFIED_FAIL_CLOSED")
        self.assertFalse(r["promotion_authority"])

    def test_changed_canonical_first_play_needs_second_matching_read(self):
        t=datetime(2026,9,20,tzinfo=UTC)
        a=build_observation(espn_event_id="1",summary=self.summary(first="2026-09-19T18:00:00Z"),observed_at=t,raw_sha256="a"*64)
        b=build_observation(espn_event_id="1",summary=self.summary(first="2026-09-19T18:00:01Z"),observed_at=t+timedelta(minutes=5),raw_sha256="b"*64)
        r=build_attestation_record([a,b])
        self.assertEqual(r["status"],"PENDING_STABILITY_SECOND_READ")

    def test_in_progress_observations_do_not_start_final_clock(self):
        o=build_observation(espn_event_id="1",summary=self.summary(completed=False),observed_at=datetime(2026,9,19,19,tzinfo=UTC),raw_sha256="a"*64)
        self.assertEqual(build_attestation_record([o])["status"],"PENDING_FINAL_STATUS")

if __name__=="__main__": unittest.main()
