import ast
from pathlib import Path
import unittest


class NFLProductionRunnerManifestBindingTests(unittest.TestCase):
    def test_runner_passes_canonical_manifest_hash_to_validation_builder(self):
        tree = ast.parse(Path("scripts/run_nfl_production_validation.py").read_text(encoding="utf-8"))
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "build_production_nfl_validation_evidence"
        ]
        self.assertEqual(len(calls), 1)
        keywords = {kw.arg: kw.value for kw in calls[0].keywords if kw.arg}
        self.assertIn("source_manifest_sha256", keywords)
        value = keywords["source_manifest_sha256"]
        self.assertIsInstance(value, ast.Name)
        self.assertEqual(value.id, "manifest_hash")


if __name__ == "__main__":
    unittest.main()
