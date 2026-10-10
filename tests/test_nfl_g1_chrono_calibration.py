import importlib.util
from pathlib import Path

p = Path(__file__).resolve().parents[1] / 'scripts/research_nfl_g1_chrono_calibration.py'
spec = importlib.util.spec_from_file_location('nfl_g1_cal', p)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def test_research_only():
    assert m.SCHEMA == 'NFL_G1_CHRONO_INTERCEPT_RESEARCH_V1'
    assert m._adjust(0.5, 0) == 0.5
