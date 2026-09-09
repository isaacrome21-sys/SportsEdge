from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.audit_workflow_script_refs import WorkflowRefError, _candidate_paths, audit


def _tree(tmp: Path, workflow_text: str, present: tuple[str, ...] = ()) -> Path:
    (tmp / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (tmp / ".github" / "workflows" / "sample.yml").write_text(workflow_text, encoding="utf-8")
    for rel in present:
        target = tmp / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# present\n", encoding="utf-8")
    return tmp


class TestCandidateExtraction(unittest.TestCase):
    def test_plain_and_quoted_and_interpolated_all_extract(self):
        text = (
            "- run: python scripts/a.py\n"
            "- run: python 'scripts/b.py'\n"
            '- run: bash "ops/c.sh"\n'
            "- run: python ${{ github.workspace }}/scripts/d.py\n"
            "- run: python ./scripts/e.py\n"
        )
        self.assertEqual(
            _candidate_paths(text),
            {"scripts/a.py", "scripts/b.py", "ops/c.sh", "scripts/d.py", "scripts/e.py"},
        )

    def test_non_repo_references_are_ignored(self):
        text = (
            "- run: python -m sportsedge.run_it_control\n"
            "- run: pip install numpy\n"
            "- run: curl https://example.com/scripts/remote.py\n"
            "- run: python /usr/lib/python3/site.py\n"
            "- run: python vendor/scripts/nested.py\n"
            "- run: python scripts/glob_*.py\n"
            "- run: python scripts/../scripts/up.py\n"
        )
        self.assertEqual(_candidate_paths(text), set())


class TestAudit(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_reference_fails_with_workflow_and_path(self):
        _tree(self.root, "- run: python scripts/gone.py\n")
        report = audit(self.root)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["missing_count"], 1)
        self.assertEqual(report["missing"][0]["workflow"], "sample.yml")
        self.assertEqual(report["missing"][0]["missing_path"], "scripts/gone.py")

    def test_present_reference_passes(self):
        _tree(self.root, "- run: python scripts/here.py\n", present=("scripts/here.py",))
        self.assertEqual(audit(self.root)["status"], "PASS")

    def test_directory_is_not_accepted_in_place_of_a_script(self):
        _tree(self.root, "- run: python scripts/thing.py\n")
        (self.root / "scripts" / "thing.py").mkdir(parents=True)
        self.assertEqual(audit(self.root)["status"], "FAIL")

    def test_yaml_extension_is_scanned_too(self):
        _tree(self.root, "- run: echo ok\n", present=("scripts/ok.py",))
        (self.root / ".github" / "workflows" / "other.yaml").write_text(
            "- run: python scripts/absent.py\n", encoding="utf-8"
        )
        report = audit(self.root)
        self.assertEqual(report["workflows_scanned"], 2)
        self.assertEqual(report["missing_count"], 1)

    def test_no_workflows_is_an_error_not_a_pass(self):
        (self.root / ".github" / "workflows").mkdir(parents=True)
        with self.assertRaises(WorkflowRefError):
            audit(self.root)

    def test_missing_workflow_directory_is_an_error(self):
        with self.assertRaises(WorkflowRefError):
            audit(self.root)

    def test_guard_has_no_allowlist_surface(self):
        source = Path(__file__).resolve().parents[1] / "scripts" / "audit_workflow_script_refs.py"
        body = source.read_text(encoding="utf-8").lower()
        for token in ("allowlist", "allow_list", "whitelist", "ignore_missing", "skip_missing"):
            self.assertNotIn(token + " =", body)
            self.assertNotIn(token + "=", body)


if __name__ == "__main__":
    unittest.main()
