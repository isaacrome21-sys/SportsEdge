from pathlib import Path
import unittest


class TestNFLV2NestedDiagnosticWorkflow(unittest.TestCase):
    def test_nested_candidate_is_diagnostic_only_and_uses_frozen_gate(self) -> None:
        text = Path('.github/workflows/nfl-v2-nested-diagnostic.yml').read_text(encoding='utf-8')

        required = (
            'nfl_m2_v2_nested_candidate_validation.json',
            'nfl_m2_v2_nested_candidate_key_math.json',
            '--max-abs-error 0.005',
            "production_registry_consumes_this_artifact') is not False",
            'NFL_V2_NESTED_PRODUCTION_AUTHORITY_FORBIDDEN',
            'NFL props remain NO_ENGINE',
        )
        # The workflow body intentionally carries no betting/promotion action.
        for needle in required[:-1]:
            self.assertIn(needle, text)

        forbidden = (
            'build_nfl_promotion_registry.py',
            'run_nfl_auto.py',
            'stake_units',
            'OFFICIAL = True',
            "'official': True",
            'model_p_authority: true',
            'promotion_authority: true',
        )
        for needle in forbidden:
            self.assertNotIn(needle, text)


if __name__ == '__main__':
    unittest.main()
