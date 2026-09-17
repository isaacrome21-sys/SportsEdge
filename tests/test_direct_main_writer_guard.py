from __future__ import annotations

from pathlib import Path
import subprocess

from scripts.audit_direct_main_writers import audit, classify_git_push


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _repo(tmp_path: Path, workflow: str, extras: dict[str, str] | None = None) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    wf = repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "case.yml").write_text(workflow, encoding="utf-8")
    for path, text in (extras or {}).items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo


def test_target_classifier_proves_only_static_non_main_destinations() -> None:
    assert classify_git_push("git push origin HEAD:data") == ("NON_MAIN", "PUSH_TARGETS_PROVEN_NON_MAIN")
    assert classify_git_push("git push origin refs/heads/data") == ("NON_MAIN", "PUSH_TARGETS_PROVEN_NON_MAIN")
    assert classify_git_push("git push origin feature/x") == ("NON_MAIN", "PUSH_TARGETS_PROVEN_NON_MAIN")
    assert classify_git_push("git push origin main") == ("MAIN_WRITER", "PUSH_TARGET_MAIN")
    assert classify_git_push("git push origin HEAD:main") == ("MAIN_WRITER", "PUSH_TARGET_MAIN")
    assert classify_git_push("git push origin refs/heads/main") == ("MAIN_WRITER", "PUSH_TARGET_MAIN")
    assert classify_git_push("git push origin --all") == ("MAIN_WRITER", "PUSH_ALL_INCLUDES_MAIN")
    assert classify_git_push("git push --mirror origin") == ("MAIN_WRITER", "PUSH_MIRROR_INCLUDES_MAIN")


def test_shell_wrapped_static_non_main_push_stays_non_main() -> None:
    assert classify_git_push("if git push origin HEAD:data; then exit 0; fi") == ("NON_MAIN", "PUSH_TARGETS_PROVEN_NON_MAIN")
    assert classify_git_push("git push origin HEAD:data && echo persisted") == ("NON_MAIN", "PUSH_TARGETS_PROVEN_NON_MAIN")


def test_static_env_refspec_resolves_without_weakening_unknown_variables() -> None:
    assert classify_git_push('git push origin "HEAD:${DATA_BRANCH}"', static_env={"DATA_BRANCH": "data"}) == (
        "NON_MAIN", "PUSH_TARGETS_PROVEN_NON_MAIN"
    )
    assert classify_git_push('git push origin "HEAD:${DATA_BRANCH}"') == ("UNRESOLVABLE", "PUSH_TARGET_INTERPOLATED")


def test_unresolvable_push_forms_fail_closed_with_distinct_reason_codes() -> None:
    assert classify_git_push("git push") == ("UNRESOLVABLE", "BARE_GIT_PUSH_TARGET_UNRESOLVED")
    assert classify_git_push("git push origin $BRANCH") == ("UNRESOLVABLE", "PUSH_TARGET_INTERPOLATED")
    assert classify_git_push("git push origin $(pick_ref)") == ("UNRESOLVABLE", "PUSH_TARGET_INTERPOLATED")
    assert classify_git_push("git push origin HEAD") == ("UNRESOLVABLE", "PUSH_HEAD_TARGET_UNRESOLVED")
    assert classify_git_push("git push origin HEAD", "data") == ("NON_MAIN", "PUSH_TARGETS_PROVEN_NON_MAIN")


def test_inherited_permissions_do_not_clear_non_git_writer(tmp_path: Path) -> None:
    repo = _repo(tmp_path, """name: x\non: workflow_dispatch\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/github-script@v7\n        with:\n          script: github.rest.repos.createOrUpdateFileContents({path: 'x'})\n""")
    report = audit(repo)
    finding = next(f for f in report["blocking_findings"] if f["reason"] == "GITHUB_SCRIPT_CONTENT_WRITE")
    assert finding["classification"] == "MAIN_WRITER"
    assert finding["permission_reason"] == "CONTENTS_PERMISSION_INHERITED_OR_UNSPECIFIED"


def test_non_literal_writer_families_are_detected(tmp_path: Path) -> None:
    workflow = """name: x\non: workflow_dispatch\npermissions:\n  contents: write\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n      - run: gh api -X PATCH repos/o/r/git/refs/heads/main\n      - run: gh api -X PUT repos/o/r/contents/b\n      - run: curl -X PUT https://api.github.com/repos/o/r/contents/a\n      - uses: stefanzweifel/git-auto-commit-action@v5\n      - uses: ad-m/github-push-action@v0.8.0\n"""
    report = audit(_repo(tmp_path, workflow))
    reasons = {f["reason"] for f in report["blocking_findings"]}
    assert {"GH_API_MAIN_REF", "GH_API_CONTENTS_WRITE", "HTTP_CONTENTS_API_WRITE", "GIT_AUTO_COMMIT_ACTION", "GITHUB_PUSH_ACTION"}.issubset(reasons)


def test_called_shell_script_is_scanned(tmp_path: Path) -> None:
    workflow = """name: x\non: workflow_dispatch\npermissions:\n  contents: write\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n      - run: bash scripts/persist.sh\n"""
    report = audit(_repo(tmp_path, workflow, {"scripts/persist.sh": "git push origin main\n"}))
    finding = next(f for f in report["blocking_findings"] if f["reason"] == "PUSH_TARGET_MAIN")
    assert finding["source"] == "scripts/persist.sh"


def test_yaml_shell_key_is_not_misread_as_local_bash_call(tmp_path: Path) -> None:
    workflow = """name: x\non: workflow_dispatch\npermissions:\n  contents: read\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n      - shell: bash\n        run: echo safe\n"""
    report = audit(_repo(tmp_path, workflow))
    assert not any(f["reason"] == "CALLED_LOCAL_SOURCE_NOT_FOUND" for f in report["blocking_findings"])


def test_quoted_fixture_text_is_not_treated_as_executable_push(tmp_path: Path) -> None:
    workflow = """name: x\non: workflow_dispatch\npermissions:\n  contents: read\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n      - run: |\n          python - <<'PY'\n          rows = [\n              'git push origin HEAD:data',\n          ]\n          print(rows)\n          PY\n"""
    report = audit(_repo(tmp_path, workflow))
    assert report["blocking_findings"] == []


def test_explicit_separate_repository_checkout_push_is_not_public_main(tmp_path: Path) -> None:
    workflow = """name: x\non: workflow_dispatch\npermissions:\n  contents: read\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          repository: ${{ vars.PRIVATE_REPOSITORY }}\n          path: _private/evidence\n      - name: persist private bytes\n        working-directory: _private/evidence\n        run: |\n          git commit -m evidence\n          git push\n"""
    report = audit(_repo(tmp_path, workflow))
    assert report["blocking_findings"] == []


def test_separate_checkout_does_not_clear_push_from_public_checkout(tmp_path: Path) -> None:
    workflow = """name: x\non: workflow_dispatch\npermissions:\n  contents: write\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          repository: other/repo\n          path: _private/evidence\n      - name: unsafe public push\n        run: git push origin main\n"""
    report = audit(_repo(tmp_path, workflow))
    assert any(f["reason"] == "PUSH_TARGET_MAIN" for f in report["blocking_findings"])


def test_mlb_head_data_case_clears(tmp_path: Path) -> None:
    workflow = """name: mlb\non: workflow_dispatch\npermissions:\n  contents: write\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n      - run: git push origin HEAD:data\n"""
    report = audit(_repo(tmp_path, workflow))
    assert report["blocking_findings"] == []
    assert report["status"] == "QUIESCED"
