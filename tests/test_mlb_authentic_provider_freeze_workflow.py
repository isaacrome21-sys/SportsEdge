from pathlib import Path
import unittest


class MlbAuthenticProviderFreezeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = Path('.github/workflows/mlb-authentic-provider-freeze.yml').read_text(encoding='utf-8')

    def test_manual_and_fail_closed_private_destination(self) -> None:
        workflow = self.workflow
        self.assertIn('workflow_dispatch:', workflow)
        self.assertIn('SPORTSEDGE_MLB_EVIDENCE_REPO', workflow)
        self.assertIn('SPORTSEDGE_MLB_EVIDENCE_TOKEN', workflow)
        self.assertIn('BLOCKED_PRIVATE_EVIDENCE_DESTINATION_UNAVAILABLE', workflow)
        self.assertIn('MLB_EVIDENCE_DESTINATION_MUST_BE_SEPARATE_REPOSITORY', workflow)
        self.assertIn("payload.get('private') is not True", workflow)
        self.assertIn('MLB_EVIDENCE_REPOSITORY_NOT_PRIVATE', workflow)

    def test_raw_bytes_are_captured_and_verified_only_under_private_checkout(self) -> None:
        workflow = self.workflow
        self.assertIn('path: .private/mlb-evidence', workflow)
        self.assertIn('--private-root .private/mlb-evidence', workflow)
        self.assertIn('scripts/capture_mlb_odds_api_freeze.py', workflow)
        self.assertIn('scripts/verify_mlb_odds_api_freeze.py', workflow)
        self.assertIn('captures/$CAPTURE_ID', workflow)
        self.assertIn("-name '*.bin'", workflow)
        self.assertIn('PUBLIC_MLB_FREEZE_RAW_BYTES_PRESENT', workflow)

    def test_public_binding_is_metadata_only_and_non_promotional(self) -> None:
        workflow = self.workflow
        self.assertIn("'private_repository_identity_sha256'", workflow)
        self.assertNotIn("'private_repository': os.environ['PRIVATE_REPO']", workflow)
        self.assertIn("'raw_bytes_location': 'PRIVATE_REPOSITORY_ONLY'", workflow)
        self.assertIn("'network_fallback': False", workflow)
        self.assertIn("'truth_gate_promotion': False", workflow)
        self.assertIn("'official_evidence': False", workflow)
        self.assertIn("'eligibility_change': False", workflow)
        self.assertIn('runtime/mlb-provider-freezes/$CAPTURE_ID', workflow)

    def test_private_commit_precedes_public_metadata_persistence(self) -> None:
        workflow = self.workflow
        private_commit = workflow.index('Commit exact raw bytes only to private repository')
        bind = workflow.index('Bind public manifest to exact private Git commit')
        persist = workflow.index('Persist safe freeze metadata to data branch')
        self.assertLess(private_commit, bind)
        self.assertLess(bind, persist)

    def test_workflow_has_explicit_eligibility_lock(self) -> None:
        workflow = self.workflow
        self.assertIn('Assert deployment eligibility remains untouched', workflow)
        self.assertIn("any(bool(row.get('eligible')) for row in markets.values())", workflow)
        self.assertIn('MLB_FREEZE_WORKFLOW_ELIGIBILITY_GUARD_FAILED', workflow)


if __name__ == '__main__':
    unittest.main()
