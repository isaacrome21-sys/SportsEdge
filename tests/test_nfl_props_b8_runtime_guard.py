"""B8 operational composition is enforced before the frozen loader runs."""
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
CORRECTED = "sp_2025_played_v2.csv.gz"


@pytest.fixture(params=[
    "research/nfl_props_part2_20261018/price_nfl_props_part2.py",
    "research/nfl_props_part2b_20261020/price_nfl_props_part2b.py",
])
def package(request, tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("b8_runtime_pricer", ROOT / request.param)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    here, data = tmp_path / "spec", tmp_path / "data"
    here.mkdir()
    data.mkdir()
    prereg = here / mod.CALIBRATION_PREREG_NAME
    prereg.write_bytes(b"synthetic prereg")
    files = [prereg]
    for name in ("ps_2018.csv.gz", "ps_2019.csv.gz", CORRECTED):
        path = data / name
        path.write_bytes(name.encode())
        files.append(path)
    (here / "SPEC_HASHES.txt").write_text("".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in files
    ))
    monkeypatch.setattr(mod, "HERE", here)
    return mod, data, here


@pytest.mark.parametrize("fault", [
    "original", "ps_alias", "sp_backup", "missing", "tampered",
])
def test_bad_b8_input_aborts_before_load_or_output(package, monkeypatch, tmp_path, fault):
    mod, data, _ = package
    aliases = {"original": "sp_2025.csv.gz", "ps_alias": "ps_2025.csv.gz",
               "sp_backup": "sp_2025_backup.csv.gz"}
    if fault in aliases:
        (data / aliases[fault]).write_bytes(b"duplicate season")
    elif fault == "missing":
        (data / CORRECTED).unlink()
    else:
        (data / CORRECTED).write_bytes(b"tampered")
    def forbidden_load(_):
        pytest.fail("loader called before B8 input validation")
    monkeypatch.setattr(mod, "load_evaluator", lambda: SimpleNamespace(load=forbidden_load))
    out = tmp_path / "output"
    args = SimpleNamespace(player_data=str(data), capture="not-read.json", out_dir=str(out))
    reason = "B8_CORRECTED_INPUT_HASH_MISMATCH" if fault == "tampered" else "B8_DATA_COMPOSITION_INVALID"
    with pytest.raises(SystemExit, match=reason):
        mod.cmd_price(args)
    assert not out.exists()


def test_corrected_composition_passes_and_preserves_training_receipt(package):
    mod, data, _ = package
    pins = mod.check_training_pins(data)
    assert set(pins) == {"ps_2018.csv.gz", "ps_2019.csv.gz"}


def test_old_registry_keeps_old_freeze_behavior(package):
    mod, data, here = package
    registry = here / "SPEC_HASHES.txt"
    registry.write_text("\n".join(
        line for line in registry.read_text().splitlines() if CORRECTED not in line
    ) + "\n")
    (data / CORRECTED).unlink()
    (data / "sp_2025.csv.gz").write_bytes(b"preserved original")
    assert set(mod.check_training_pins(data)) == {"ps_2018.csv.gz", "ps_2019.csv.gz"}
