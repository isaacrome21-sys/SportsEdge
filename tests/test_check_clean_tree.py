"""Unit tests for the clean-working-tree CI guard (scripts/check_clean_tree.py).

These tests never write into the repository tree: the comparison logic is
exercised on canned porcelain lines, and the CLI end-to-end run uses a
throwaway git repository inside pytest's tmp_path.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_clean_tree import git_status_entries, main, new_entries

ROOT = Path(__file__).resolve().parents[1]


def test_new_entries_flags_only_additions():
    baseline = [" M tracked.py", "?? kept.txt"]
    current = [" M tracked.py", "?? kept.txt", "?? stray.json", " M other.py"]
    assert new_entries(baseline, current) == [" M other.py", "?? stray.json"]


def test_new_entries_empty_when_tree_unchanged():
    lines = [" M tracked.py", "?? kept.txt"]
    assert new_entries(lines, list(lines)) == []


def test_new_entries_baseline_dirt_does_not_mask_new_damage():
    baseline = ["?? preexisting_stray.json"]
    current = ["?? preexisting_stray.json", "?? another_stray.json"]
    assert new_entries(baseline, current) == ["?? another_stray.json"]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)


def test_cli_round_trip_in_temp_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "guard@example.com")
    _git(repo, "config", "user.name", "guard")
    (repo / "tracked.txt").write_text("v1\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-qm", "init")

    baseline = tmp_path / "baseline.txt"  # outside the repo tree, like CI
    script = ROOT / "scripts" / "check_clean_tree.py"

    def run_cli(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=repo, text=True, capture_output=True, check=False)

    assert git_status_entries(repo) == []

    snap = run_cli("--snapshot", str(baseline))
    assert snap.returncode == 0, snap.stderr

    clean = run_cli("--check", str(baseline))
    assert clean.returncode == 0, clean.stderr

    (repo / "stray.json").write_text("{}\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("v2\n", encoding="utf-8")
    dirty = run_cli("--check", str(baseline))
    assert dirty.returncode == 1
    assert "stray.json" in dirty.stderr
    assert "tracked.txt" in dirty.stderr

    missing = run_cli("--check", str(tmp_path / "nope.txt"))
    assert missing.returncode == 2


def test_main_module_importable_without_side_effects():
    assert callable(main)


@pytest.mark.parametrize("kind", ["tracked", "untracked", "index"])
def test_cli_detects_mutation_when_status_entries_stay_identical(tmp_path, kind):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "guard@example.com")
    _git(repo, "config", "user.name", "guard")
    tracked = repo / "tracked.txt"
    tracked.write_text("v1\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-qm", "init")
    target = repo / "untracked.txt" if kind == "untracked" else tracked
    target.write_text("v2\n")
    if kind == "index":
        _git(repo, "add", "tracked.txt")
        target.write_text("v3\n")

    baseline = tmp_path / "baseline.json"
    script = ROOT / "scripts" / "check_clean_tree.py"

    def run_cli(*args):
        return subprocess.run([sys.executable, str(script), *args], cwd=repo,
                              capture_output=True, text=True, check=False)

    before = git_status_entries(repo)
    assert run_cli("--snapshot", str(baseline)).returncode == 0
    assert run_cli("--check", str(baseline)).returncode == 0
    target.write_text("v4\n")
    if kind == "index":
        _git(repo, "add", "tracked.txt")
        target.write_text("v3\n")  # same worktree contents, different staged blob
    assert git_status_entries(repo) == before
    result = run_cli("--check", str(baseline))
    assert result.returncode == 1, result.stdout + result.stderr
    assert ("index" if kind == "index" else target.name) in result.stderr
