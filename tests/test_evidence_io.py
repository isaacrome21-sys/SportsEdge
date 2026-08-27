import tempfile
from pathlib import Path
import json
import unittest

from sportsedge.evidence import EvidenceError
from sportsedge.evidence_io import (
    EVIDENCE_FILE_SCHEMA,
    evidence_packets_from_payload,
    load_evidence_file,
)


class EvidenceIOTests(unittest.TestCase):
    def test_schema_envelope_defaults_to_manual_acquisition(self):
        packets = evidence_packets_from_payload({
            "schema_version": EVIDENCE_FILE_SCHEMA,
            "packets": [{
                "game_id": "823014",
                "fact_type": "STARTER_ID",
                "subject_id": "STL",
                "value": "GRACEFFO",
                "source_name": "MLB.com screenshot",
                "observed_at_utc": "2026-08-27T15:45:00+00:00",
                "authority": "AUTHORITATIVE",
                "verified": True,
            }],
        })
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].acquisition_mode, "MANUAL")
        self.assertEqual(packets[0].value, "GRACEFFO")

    def test_unknown_packet_fields_fail_closed(self):
        with self.assertRaisesRegex(EvidenceError, "unknown evidence packet fields"):
            evidence_packets_from_payload([{
                "game_id": "823014",
                "fact_type": "STARTER_ID",
                "subject_id": "STL",
                "value": "GRACEFFO",
                "source_name": "MLB.com",
                "observed_at_utc": "2026-08-27T15:45:00+00:00",
                "trust_me": True,
            }])

    def test_missing_timestamp_fails_closed(self):
        with self.assertRaisesRegex(EvidenceError, "missing evidence packet fields"):
            evidence_packets_from_payload([{
                "game_id": "823014",
                "fact_type": "STARTER_ID",
                "subject_id": "STL",
                "value": "GRACEFFO",
                "source_name": "MLB.com",
            }])

    def test_file_loader_reads_schema_payload(self):
        payload = {
            "schema_version": EVIDENCE_FILE_SCHEMA,
            "packets": [{
                "game_id": "823014",
                "fact_type": "WEATHER_RAIN_RISK",
                "subject_id": "BUSCH_STADIUM",
                "value": "CLEAR",
                "source_name": "manual weather",
                "observed_at_utc": "2026-08-27T15:45:00+00:00",
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            path.write_text(json.dumps(payload))
            packets = load_evidence_file(path)
        self.assertEqual(packets[0].fact_type, "WEATHER_RAIN_RISK")


if __name__ == "__main__":
    unittest.main()
