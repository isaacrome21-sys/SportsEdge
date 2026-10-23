"""t263: the v2k lane's numpy runtime must equal the frozen identity pin.

The frozen preflight test fails with V2K_RUNTIME_NUMPY_MISMATCH whenever an
environment drifts to a newer numpy (e.g. 2.5.4). The frozen test is NOT
changed; instead every install path must resolve to the frozen pin.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "sportsedge/sports/nfl/NFL_V2K_DEVELOPMENT_VALIDATION_PREATTEMPT_V1.json"
CONSTRAINTS = ROOT / "constraints" / "v2k-runtime.txt"
PIN_RE = re.compile(r"numpy==([0-9][0-9A-Za-z.]*)")


def _frozen_numpy() -> str:
    c = json.loads(CONTRACT.read_text(encoding="utf-8"))
    return c["unresolved_required_freezes"]["final_hardened_implementation_identity"]["runtime"]["numpy"]


def test_constraints_file_pins_frozen_numpy():
    assert CONSTRAINTS.is_file(), "constraints/v2k-runtime.txt missing"
    pins = PIN_RE.findall(CONSTRAINTS.read_text(encoding="utf-8"))
    assert pins == [_frozen_numpy()]


def test_requirements_and_pyproject_match_frozen_numpy():
    want = _frozen_numpy()
    for rel in ("requirements-test.txt", "pyproject.toml"):
        pins = PIN_RE.findall((ROOT / rel).read_text(encoding="utf-8"))
        assert pins and set(pins) == {want}, rel


def test_every_v2k_workflow_numpy_install_is_frozen_pin():
    want = _frozen_numpy()
    wfs = sorted((ROOT / ".github/workflows").glob("nfl-v2k-*.yml"))
    assert wfs
    for wf in wfs:
        text = wf.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "pip install" in line and "numpy" in line:
                assert PIN_RE.findall(line) == [want], f"{wf.name}: {line.strip()}"


def test_venv_helper_uses_constraints():
    sh = (ROOT / "scripts" / "make_pinned_test_venv.sh").read_text(encoding="utf-8")
    assert "-c constraints/v2k-runtime.txt" in sh
    assert "-r requirements-test.txt" in sh


def test_pinned_venv_dir_is_gitignored():
    lines = {l.strip() for l in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert ".venv-pinned/" in lines
