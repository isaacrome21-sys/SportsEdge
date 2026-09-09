from pathlib import Path
import unittest


class ProviderAcceptancePublicBoundaryTests(unittest.TestCase):
    def test_acceptance_probe_never_persists_raw_provider_bytes(self) -> None:
        workflow = Path('.github/workflows/archive-provider-acceptance-probe.yml').read_text(encoding='utf-8')
        self.assertIn("'raw_capture_eligible':False", workflow)
        self.assertIn("'raw_evidence_eligible':False", workflow)
        self.assertIn("'raw_bytes_persisted':False", workflow)
        self.assertIn("'raw_retention':'DISCARDED_AFTER_HASH_ACCEPTANCE_ONLY'", workflow)
        self.assertNotIn("write_bytes(raw)", workflow)
        self.assertNotIn("row['raw_file']", workflow)
        self.assertNotIn("cp -R artifacts/provider-probe/.", workflow)
        self.assertIn("find artifacts/provider-probe -type f ! -name 'probe_*.json'", workflow)
        self.assertIn("install -D -m 0644", workflow)

    def test_acceptance_probe_keeps_only_nonsecret_raw_identity(self) -> None:
        workflow = Path('.github/workflows/archive-provider-acceptance-probe.yml').read_text(encoding='utf-8')
        self.assertIn("'raw_response_sha256':hashlib.sha256(raw).hexdigest()", workflow)
        self.assertIn("'raw_byte_length':len(raw)", workflow)
        self.assertNotIn("'provider_body':body", workflow)
        self.assertIn("'provider_code':code", workflow)


if __name__ == '__main__':
    unittest.main()
