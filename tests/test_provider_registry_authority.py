import json
from pathlib import Path
import unittest


class ProviderRegistryAuthorityTests(unittest.TestCase):
    def test_registry_has_audit_only_authority(self):
        payload = json.loads(Path("config/provider_consumer_registry_v1.json").read_text())
        self.assertEqual(payload["authority"], "AUDIT_ONLY")
        self.assertEqual(payload["schema_version"], "PROVIDER_CONSUMER_REGISTRY_V1")


if __name__ == "__main__":
    unittest.main()
