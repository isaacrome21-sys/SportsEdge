"""t270 LOW: make_pinned_test_venv.sh must honor PYTHON (e.g. PYTHON=python3.12).

Previously the script always ran ``python3 -m venv`` and silently built on whatever python3 was.
An unusable PYTHON must refuse, never fall back to python3.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_pinned_test_venv.sh"
PATH = "/home/box/.local/bin:/usr/local/bin:/usr/bin:/bin"


def _run(args, env):
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=ROOT, capture_output=True, text=True, timeout=120,
                          env={"PATH": PATH, "SPORTSEDGE_PINNED_VENV_CREATE_ONLY": "1",
                               "PYTEST_CURRENT_TEST": "t270", **env})


def _venv_version(venv):
    cfg = (venv / "pyvenv.cfg").read_text()
    return next(l.split("=", 1)[1].strip() for l in cfg.splitlines() if l.startswith("version"))


@pytest.mark.skipif(shutil.which("python3.12", path=PATH) is None, reason="python3.12 not installed")
def test_python_env_selects_interpreter(tmp_path):
    venv = tmp_path / "v"
    r = _run([str(venv)], {"PYTHON": "python3.12"})
    assert r.returncode == 0, r.stderr
    assert _venv_version(venv).startswith("3.12."), _venv_version(venv)


def test_unusable_python_refuses_without_fallback(tmp_path):
    venv = tmp_path / "v"
    r = _run([str(venv)], {"PYTHON": "definitely-not-a-python-xyz"})
    assert r.returncode != 0
    assert "PYTHON_NOT_FOUND" in r.stderr
    assert not venv.exists()


def test_default_still_python3(tmp_path):
    venv = tmp_path / "v"
    r = _run([str(venv)], {})
    assert r.returncode == 0, r.stderr
    assert (venv / "pyvenv.cfg").is_file()
