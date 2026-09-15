from pathlib import Path
import unittest


class ProviderTerminalStateTests(unittest.TestCase):
    def test_hosted_ci_is_required_for_terminal_state(self):
        text = Path("docs/provider_abstraction_terminal_state.md").read_text()
        self.assertIn("Hosted `market-provider-contract` CI passes on the exact PR head", text)
        self.assertIn("cannot be claimed until GitHub Actions reports it green", text)


if __name__ == "__main__":
    unittest.main()
