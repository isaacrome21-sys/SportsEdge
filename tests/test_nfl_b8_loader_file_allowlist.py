"""B8 live-loader filename admission: no unpinned ps_*/sp_* inputs.

Research-only guard verification. This test runs via the hosted default tests
directory and spies on actual cmd_price to prove zero evaluator loads/output
when a loader-visible file is not among the frozen eight hash-pinned inputs.
Frozen evaluators, pins, training math and timing terms are not modified.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
PRICERS = (
    "research/nfl_props_part2_20261018/price_nfl_props_part2.py",
    "research/nfl_props_part2b_20261020/price_nfl_props_part2b.py",
)
PINNED = (
    "ps_2018.csv.gz",
    "ps_2019.csv.gz",
    "ps_2020.csv.gz",
    "ps_2021.csv.gz",
    "ps_2022.csv.gz",
    "ps_2023.csv.gz",
    "ps_2024.csv.gz",
    "sp_2025_played_v2.csv.gz",
)


@pytest.fixture(params=PRICERS)
def setup_pricer(request, tmp_path):
    module_path = ROOT / request.param
    spec = importlib.util.spec_from_file_location(
        "b8_allowlist_" + module_path.parent.name, module_path
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    data = tmp_path / "data"
    data.mkdir()
    for name in PINNED:
        (data / name).write_bytes(b"synthetic-not-real-player-data")
    return mod, data


@pytest.mark.parametrize("untrusted", (
    "sp_extra.csv.gz", "ps_extra.csv.gz",
    "sp_2026.csv.gz", "ps_2026.csv.gz",
))
def test_unpinned_glob_input_refuses_before_load_or_commit(
    setup_pricer, tmp_path, monkeypatch, untrusted
):
    mod, data = setup_pricer
    (data / untrusted).write_bytes(b"synthetic malicious extra player rows")
    invoked = []

    def no_load(_directory):
        invoked.append("load")
        raise AssertionError("B8_UNPINNED_INPUT_REACHED_LOADER")

    def no_hashes(_directory):
        invoked.append("hashes")
        raise AssertionError("B8_UNPINNED_INPUT_REACHED_HASH_VALIDATION")

    monkeypatch.setattr(mod, "load_evaluator", lambda: SimpleNamespace(
        load=no_load, check_hashes=no_hashes
    ))
    monkeypatch.setattr(mod, "check_training_pins", lambda _directory: {})
    output = tmp_path / "would_be_counted"
    args = SimpleNamespace(
        player_data=str(data),
        capture=str(tmp_path / "not_read.json"),
        out_dir=str(output),
    )
    with pytest.raises(SystemExit, match="B8_RUNTIME_UNPINNED_PLAYER_FILE_SET"):
        mod.cmd_price(args)
    assert invoked == []
    assert not output.exists()


def test_missing_other_pinned_season_fails_before_hash_check(setup_pricer):
    mod, data = setup_pricer
    (data / "ps_2024.csv.gz").unlink()
    seen = []
    stub = SimpleNamespace(
        check_hashes=lambda _data: seen.append("checked")
    )
    with pytest.raises(SystemExit, match="B8_RUNTIME_UNPINNED_PLAYER_FILE_SET"):
        mod.check_b8_active_runtime(data, stub)
    assert seen == []


def test_exact_eight_filenames_reach_existing_full_sha_gate(setup_pricer):
    mod, data = setup_pricer
    seen = []
    def pinned_hash_check(directory):
        seen.append(directory)
        return {"full_pinned_hash_check": "caller_supplied_evaluator"}
    stub = SimpleNamespace(check_hashes=pinned_hash_check)
    assert mod.check_b8_active_runtime(data, stub) == {
        "full_pinned_hash_check": "caller_supplied_evaluator"
    }
    assert seen == [data]
