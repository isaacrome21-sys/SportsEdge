import json
import tempfile
import unittest
from pathlib import Path

from sportsedge.deployments import load_registry, deployment_for, DeploymentRegistryError


class DeploymentTests(unittest.TestCase):
    def test_checked_in_registry_loads_and_hits_is_candidate_not_deployed(self):
        reg = load_registry()
        self.assertFalse(reg["markets"]["HITS"]["eligible"])
        self.assertEqual(deployment_for("HITS")["stage"], "JOINT_ENGINE_CANDIDATE")

    def test_unknown_market_fails_closed(self):
        self.assertFalse(deployment_for("DOES_NOT_EXIST")["eligible"])

    def test_eligible_requires_deployed_stage(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "registry.json"
            p.write_text(json.dumps({"schema_version":1,"markets":{"HITS":{"eligible":True,"stage":"CI_ATTESTED"}}}))
            with self.assertRaises(DeploymentRegistryError):
                load_registry(p)

    def test_eligible_must_be_real_bool(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "registry.json"
            p.write_text(json.dumps({"schema_version":1,"markets":{"HITS":{"eligible":1,"stage":"DEPLOYED"}}}))
            with self.assertRaises(DeploymentRegistryError):
                load_registry(p)


if __name__ == "__main__":
    unittest.main()
