from pathlib import Path
import unittest

class RuntimePolicyTests(unittest.TestCase):
    def test_policy_is_fail_closed_per_row(self):
        text=Path("docs/BINDING_RUNTIME_POLICY.md").read_text()
        self.assertIn("`BLOCKED`",text);self.assertIn("before model engine invocation",text);self.assertIn("must not synthesize",text)

if __name__=="__main__":unittest.main()
