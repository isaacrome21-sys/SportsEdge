"""Offline tests for opt-in month-partitioned SmartStake MLB source pulls.

No live dataset request and no model-validation claim are made by these tests.
"""
import csv
import gzip
import sys
import types

import pytest

from scripts import download_mlb_props as dl


def test_default_download_remains_full_dataset():
    assert dl.dataset_options("") == {}


@pytest.mark.parametrize("month", ["2026-03", "2026-04", "2026-05", "2026-06"])
def test_settled_month_selects_only_its_parquet_partition(month):
    assert dl.dataset_options(month) == {
        "data_files": {"train": f"mon={month}/part-*.parquet"}
    }


@pytest.mark.parametrize("month", ["2026-07", "2025-12", "../2026-04", "2026-04/*", "all"])
def test_ungraded_or_unexpected_partitions_refused(month):
    with pytest.raises(ValueError, match="MLB_MONTH_NOT_SETTLED"):
        dl.dataset_options(month)


def test_cli_month_reports_games_dates_and_market_coverage(monkeypatch, tmp_path, capsys):
    rows = [
        {"game_id": "a", "start_time": "2026-04-01T19:00:00Z",
         "market": "player bases", "odds": 1.9},
        {"game_id": "b", "start_time": "2026-04-03T19:00:00Z",
         "market": "player strikeouts", "odds": 1.8},
        {"game_id": "b", "start_time": "2026-04-03T19:00:00Z",
         "market": "player home runs", "odds": 2.0},
    ]
    seen = {}

    def fake_load_dataset(path, **kwargs):
        seen["path"] = path
        seen.update(kwargs)
        return rows

    monkeypatch.setitem(sys.modules, "datasets", types.SimpleNamespace(load_dataset=fake_load_dataset))
    monkeypatch.setattr(sys, "argv", [
        "download_mlb_props.py", "--month", "2026-04",
        "--max-rows", "0", "--out", str(tmp_path),
    ])
    assert dl.main() == 0
    assert seen["path"] == "SmartStake/mlb-player-props"
    assert seen["data_files"] == {"train": "mon=2026-04/part-*.parquet"}
    assert seen["streaming"] is True
    with gzip.open(tmp_path / "mlb_props_targets_2026-04.csv.gz", "rt") as fh:
        items = list(csv.DictReader(fh))
    assert len(items) == 2
    assert {row["market"] for row in items} == {"player bases", "player strikeouts"}
    output = capsys.readouterr().out
    assert "games=2" in output and "dates=2" in output
    assert "CANDIDATE HISTORICAL DATA ONLY" in output


def test_empty_month_refuses_success(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "datasets", types.SimpleNamespace(
        load_dataset=lambda *a, **kw: [
            {"game_id": "a", "start_time": "2026-04-01", "market": "player home runs"}
        ]))
    monkeypatch.setattr(sys, "argv", [
        "download_mlb_props.py", "--month", "2026-04",
        "--max-rows", "0", "--out", str(tmp_path),
    ])
    assert dl.main() == 2


def test_negative_row_cap_refused_before_network_or_files(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", [
        "download_mlb_props.py", "--month", "2026-04",
        "--max-rows", "-1", "--out", str(tmp_path),
    ])
    with pytest.raises(SystemExit) as err:
        dl.main()
    assert err.value.code == 2
    assert not list(tmp_path.iterdir())
