"""Phone free MLB source must not import optional numpy/football packages."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def test_phone_runner_module_importable_without_site_packages():
    script=("import sys; sys.path.insert(0," + repr(str(ROOT)) +
            "); from artifacts.run_it_full import run_full; print('FREE_PHONE_IMPORT_OK')")
    process=subprocess.run([sys.executable,"-S","-c",script],
                           cwd=ROOT,stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,text=True,timeout=20)
    assert process.returncode==0,process.stderr
    assert "FREE_PHONE_IMPORT_OK" in process.stdout
