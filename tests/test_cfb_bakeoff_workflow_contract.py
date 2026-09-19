from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class TestCFBBakeoffWorkflowContract(unittest.TestCase):
    def test_evaluation_is_explicit_and_private_rows_never_uploaded(self):
        text=(ROOT/".github/workflows/cfb-reconstructed-selection-materialize.yml").read_text()
        self.assertIn("CONSUME_ALL_FOUR_CFB_ATTEMPTS",text)
        self.assertIn("scripts/run_cfb_candidate_bakeoff.py",text)
        self.assertIn('--private-rows "$RUNNER_TEMP/cfb_reconstructed_selection_rows.json"',text)
        self.assertIn("artifacts/cfb/candidate_bakeoff_result.json",text)
        upload=text.split("Upload public reconstructed-selection attestations only",1)[1]
        self.assertNotIn("cfb_reconstructed_selection_rows.json",upload)
        self.assertNotIn("cfb_reconstructed_acquisition_payload.json",upload)

if __name__=="__main__":
    unittest.main()
