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
                       timeout=120, env={"PATH": "/usr/bin:/bin", "SPORTSEDGE_PINNED_VENV_CREATE_ONLY": "1",
                            "PYTEST_CURRENT_TEST": "t266"})
    assert r.returncode == 0, r.stderr
    assert (venv / "pyvenv.cfg").is_file()
    assert not stale.exists(), "stale package survived: venv was reused, not cleared"


def test_script_creates_venv_with_clear():
    assert "-m venv --clear" in SCRIPT.read_text(encoding="utf-8")


def _run(args, env, timeout=120):
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=ROOT, capture_output=True, text=True,
                          timeout=timeout, env={"PATH": "/usr/bin:/bin", **env})


def test_t267_default_venv_is_per_run_mktemp_and_printed(tmp_path):
    env = {"TMPDIR": str(tmp_path), "SPORTSEDGE_PINNED_VENV_CREATE_ONLY": "1", "PYTEST_CURRENT_TEST": "t267"}
    r1, r2 = _run([], env), _run([], env)
    assert r1.returncode == 0 and r2.returncode == 0, (r1.stderr, r2.stderr)
    made = sorted(p for p in tmp_path.iterdir() if p.name.startswith("sportsedge-venv-pinned-"))
    assert len(made) == 2, made  # a fresh directory per run
    for p in made:
        assert (p / "pyvenv.cfg").is_file()
        assert str(p) in (r1.stdout + r2.stdout)


def test_t267_in_repo_paths_still_refused(tmp_path):
    env = {"TMPDIR": str(tmp_path), "SPORTSEDGE_PINNED_VENV_CREATE_ONLY": "1", "PYTEST_CURRENT_TEST": "t267"}
    for bad in (".venv-pinned", str(ROOT / "x"), str(ROOT)):
        r = _run([bad], env)
        assert r.returncode != 0 and "VENV_INSIDE_REPO_REFUSED" in r.stderr, bad


def test_t267_create_only_refused_outside_pytest(tmp_path):
    venv = tmp_path / "v"
    r = _run([str(venv)], {"SPORTSEDGE_PINNED_VENV_CREATE_ONLY": "1"})
    assert r.returncode != 0
    assert "CREATE_ONLY_REQUIRES_PYTEST" in r.stderr
    assert not venv.exists()
