"""t266: make_pinned_test_venv.sh must rebuild the target venv from scratch.

Reusing an existing venv would keep stale extra packages, so the pinned test
environment would not be what requirements-test.txt + constraints describe.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_pinned_test_venv.sh"


def test_stale_package_in_existing_venv_is_removed(tmp_path):
    venv = tmp_path / "pinned"
    subprocess.run(["python3", "-m", "venv", "--without-pip", str(venv)], check=True)
    site = next(venv.glob("lib/python*/site-packages"))
    stale = site / "sportsedge_stale_extra_pkg.py"
    stale.write_text("STALE = True\n", encoding="utf-8")
    r = subprocess.run(["bash", str(SCRIPT), str(venv)], cwd=ROOT, capture_output=True, text=True,
                       timeout=120, env={"PATH": "/usr/bin:/bin", "SPORTSEDGE_PINNED_VENV_CREATE_ONLY": "1"})
    assert r.returncode == 0, r.stderr
    assert (venv / "pyvenv.cfg").is_file()
    assert not stale.exists(), "stale package survived: venv was reused, not cleared"


def test_script_creates_venv_with_clear():
    assert "-m venv --clear" in SCRIPT.read_text(encoding="utf-8")
