from pathlib import Path
import unittest


class ProviderPRTerminalGateTests(unittest.TestCase):
    def test_exact_head_ci_gate_is_explicit(self):
        body = Path("docs/provider_abstraction_pr_body.md").read_text()
        self.assertIn("Do not merge until `market-provider-contract` is green on the exact PR head", body)


if __name__ == "__main__":
    unittest.main()
