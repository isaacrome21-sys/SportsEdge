from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.persist_forward_evidence_data_branch import (
    PersistenceBlocked,
    _copy_create_only,
    _source_files,
    classify_push_failure,
)


class PersistForwardEvidenceDataBranchTest(unittest.TestCase):
    def test_copy_create_only_creates_then_accepts_identical(self):
        with TemporaryDirectory() as source_tmp, TemporaryDirectory() as worktree_tmp:
            root = Path(source_tmp)
            source = root / "data/mlb_forward_predictions/2026-09-16/game_123.json"
            source.parent.mkdir(parents=True)
            source.write_text('{"model_p":0.55}\n', encoding="utf-8")
            files = _source_files(root, ["data/mlb_forward_predictions"])
            copied, identical = _copy_create_only(files, worktree=Path(worktree_tmp))
            self.assertEqual(copied, ["data/mlb_forward_predictions/2026-09-16/game_123.json"])
            self.assertEqual(identical, [])
            copied2, identical2 = _copy_create_only(files, worktree=Path(worktree_tmp))
            self.assertEqual(copied2, [])
            self.assertEqual(identical2, copied)

    def test_copy_create_only_rejects_different_existing_bytes(self):
        with TemporaryDirectory() as source_tmp, TemporaryDirectory() as worktree_tmp:
            root = Path(source_tmp)
            source = root / "data/mlb_forward_capture/2026-09-16/game_123__T60.json"
            source.parent.mkdir(parents=True)
            source.write_text('{"price":-120}\n', encoding="utf-8")
            files = _source_files(root, ["data/mlb_forward_capture"])
            destination = Path(worktree_tmp) / source.relative_to(root)
            destination.parent.mkdir(parents=True)
            destination.write_text('{"price":-125}\n', encoding="utf-8")
            with self.assertRaisesRegex(PersistenceBlocked, "BLOCKED_CREATE_ONLY_COLLISION"):
                _copy_create_only(files, worktree=Path(worktree_tmp))

    def test_missing_capture_directory_is_not_fabricated(self):
        with TemporaryDirectory() as source_tmp:
            self.assertEqual(_source_files(Path(source_tmp), ["data/missing"]), [])

    def test_push_failure_classification(self):
        self.assertEqual(classify_push_failure("rejected non-fast-forward"), "NON_FAST_FORWARD")
        self.assertEqual(classify_push_failure("protected branch hook declined"), "PERMISSION_DENIED")
        self.assertEqual(classify_push_failure("Could not resolve host github.com"), "NETWORK")
        self.assertEqual(classify_push_failure("some other error"), "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
