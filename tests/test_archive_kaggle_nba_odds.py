"""Tests for scripts/archive_kaggle_nba_odds.py.

Fake credentials, stubbed download transport, synthetic raw CSVs.
No network. No real secrets.
"""

import csv
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "archive_kaggle_nba_odds.py"
SPEC = importlib.util.spec_from_file_location("archive_kaggle_nba_odds", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)

CONFIG = mod.DATASET_REGISTRY["cviaxmiwnptr/nba-betting-data"]

RAW_HEADER = ["Date", "Home Team", "Away Team", "Spread", "Total",
              "Moneyline Home", "Moneyline Away"]
RAW_ROWS = [
    {"Date": "2025-11-05", "Home Team": "Boston Celtics",
     "Away Team": "Philadelphia 76ers", "Spread": "-5.5", "Total": "224.5",
     "Moneyline Home": "-220", "Moneyline Away": "180"},
    {"Date": "2026-01-12", "Home Team": "Los Angeles Lakers",
     "Away Team": "Denver Nuggets", "Spread": "3.0", "Total": "231.0",
     "Moneyline Home": "140", "Moneyline Away": "-160"},
]


def test_self_test_passes():
    assert mod.self_test() == 0


def test_missing_credentials_fail_closed():
    with pytest.raises(mod.KaggleCredentialsMissing):
        mod.read_credentials(env={})
    with pytest.raises(mod.KaggleCredentialsMissing):
        mod.read_credentials(env={"SPORTSEDGE_KAGGLE_USERNAME": "u"})


def test_normalize_rows_canonical_schema():
    rows, stats = mod.normalize_rows(RAW_HEADER, RAW_ROWS, CONFIG)
    assert stats["rows_accepted"] == 2
    first = rows[0]
    assert first["game_date"] == "2025-11-05"
    assert first["season_label"] == 2025          # Nov 2025 -> season 2025
    assert rows[1]["season_label"] == 2025        # Jan 2026 -> season 2025
    assert first["home_team"] == "Boston Celtics"
    assert first["closing_spread_home"] == pytest.approx(-5.5)
    assert first["closing_ml_home"] == pytest.approx(-220.0)
    # No juice columns in this raw file -> None (loader returns MISSING).
    assert first["spread_home_juice"] is None


def test_unrecognized_schema_fails_closed_with_header():
    with pytest.raises(mod.KaggleArchiveError) as excinfo:
        mod.normalize_rows(["foo", "bar"], [{"foo": 1}], CONFIG)
    message = str(excinfo.value)
    assert "KAGGLE_NBA_RAW_SCHEMA_UNRECOGNIZED" in message
    assert "foo" in message  # observed header is safe to log (not a secret)


def test_offseason_rows_excluded():
    rows = [{"Date": "2025-08-15", "Home Team": "A", "Away Team": "B",
             "Spread": "-1", "Total": "200",
             "Moneyline Home": "-110", "Moneyline Away": "-110"}]
    out, stats = mod.normalize_rows(RAW_HEADER, rows, CONFIG)
    assert out == []
    assert stats["skipped_offseason"] == 1


def test_spread_orientation_verified_home():
    rows = [
        {"closing_spread_home": -5.5, "closing_ml_home": -220.0,
         "closing_ml_away": 180.0},
        {"closing_spread_home": 3.0, "closing_ml_home": 140.0,
         "closing_ml_away": -160.0},
    ] * 20
    home_perspective, audit = mod.verify_spread_orientation(rows, None)
    assert home_perspective is True
    assert audit["home_agreement_rate"] == pytest.approx(1.0)


def test_spread_orientation_ambiguous_fails_closed():
    rows = (
        [{"closing_spread_home": -5.5, "closing_ml_home": -220.0,
          "closing_ml_away": 180.0}] * 10
        + [{"closing_spread_home": -5.5, "closing_ml_home": 180.0,
            "closing_ml_away": -220.0}] * 10
    )
    with pytest.raises(mod.KaggleArchiveError) as excinfo:
        mod.verify_spread_orientation(rows, None)
    assert "KAGGLE_NBA_SPREAD_ORIENTATION_UNRESOLVED" in str(excinfo.value)


def test_spread_flip_to_home_perspective(tmp_path):
    """Away-perspective raw spreads are flipped to home perspective."""
    rows = [
        {"game_date": "2025-11-05", "season_label": 2025,
         "home_team": "Boston Celtics", "away_team": "Philadelphia 76ers",
         "home_score": None, "away_score": None,
         "closing_spread_home": -5.5,  # applies to AWAY here
         "spread_home_juice": -105.0, "spread_away_juice": -115.0,
         "closing_total": 224.5, "over_juice": None, "under_juice": None,
         "closing_ml_home": 180.0, "closing_ml_away": -220.0},
    ] * 20
    # Sanity: with away perspective, spread -5.5 + away ML favorite agrees.
    is_home, _ = mod.verify_spread_orientation(rows, None)
    assert is_home is False
    flipped = []
    for r in rows[:1]:
        row = dict(r)
        row["closing_spread_home"] = -r["closing_spread_home"]
        row["spread_home_juice"] = r["spread_away_juice"]
        row["spread_away_juice"] = r["spread_home_juice"]
        flipped.append(row)
    manifest = mod.write_archive(tmp_path, "nba-kaggle-odds", flipped,
                                 {"spread_home_perspective": False})
    season_csv = tmp_path / "archive" / "nba-kaggle-odds" / "2025" / "games.csv"
    with season_csv.open(newline="") as handle:
        stored = list(csv.DictReader(handle))[0]
    assert float(stored["closing_spread_home"]) == pytest.approx(5.5)
    assert manifest["seasons"][0]["games"] == 1


def test_write_archive_manifest(tmp_path):
    rows, _ = mod.normalize_rows(RAW_HEADER, RAW_ROWS, CONFIG)
    manifest = mod.write_archive(tmp_path, "nba-kaggle-odds", rows,
                                 {"dataset": "cviaxmiwnptr/nba-betting-data"})
    assert manifest["schema_version"] == mod.SCHEMA_VERSION
    assert len(manifest["seasons"]) == 1
    assert manifest["seasons"][0]["season"] == 2025
    season_csv = tmp_path / "archive" / "nba-kaggle-odds" / "2025" / "games.csv"
    with season_csv.open(newline="") as handle:
        stored = list(csv.DictReader(handle))
    assert len(stored) == 2
    assert set(stored[0].keys()) == set(mod.CANONICAL_COLUMNS)


def _zip_bytes(csv_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("nba_betting.csv", csv_text)
    return buf.getvalue()


def test_download_auth_failure_never_logs_key(monkeypatch):
    import urllib.error

    def forbidden(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized",
                                     {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(mod.urllib.request, "urlopen", forbidden)
    with pytest.raises(mod.KaggleArchiveError) as excinfo:
        mod.download_dataset_zip("cviaxmiwnptr/nba-betting-data",
                                 "fake-user", "fake-key-value")
    assert "fake-key-value" not in str(excinfo.value)


def test_end_to_end_with_stubbed_download(tmp_path, monkeypatch):
    """Full main() with a stubbed transport: zip -> normalize -> archive."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=RAW_HEADER)
    writer.writeheader()
    writer.writerows(RAW_ROWS)
    payload = _zip_bytes(buf.getvalue())

    class FakeResp:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mod.urllib.request, "urlopen",
                        lambda request, timeout=None: FakeResp())
    monkeypatch.setenv("SPORTSEDGE_KAGGLE_USERNAME", "fake-user")
    monkeypatch.setenv("SPORTSEDGE_KAGGLE_KEY", "fake-key")
    status_path = tmp_path / "status.json"
    code = mod.main(["--out-dir", str(tmp_path),
                     "--status-out", str(status_path)])
    assert code == 0
    status = json.loads(status_path.read_text())
    assert status["status"] == "ARCHIVED"
    assert status["games"] == 2
    manifest = json.loads(
        (tmp_path / "archive" / "nba-kaggle-odds" / "manifest.json")
        .read_text())
    assert manifest["spread_home_perspective"] is True
    assert manifest["raw_header"] == RAW_HEADER


# ---------------------------------------------------------------------------
# Current Kaggle file schema (nba_2008-2026.csv): lowercase headers, scores
# as score_home/score_away, spread as UNSIGNED magnitude + whos_favored.
# ---------------------------------------------------------------------------

CURRENT_HEADER = ["season", "date", "regular", "playoffs", "away", "home",
                  "score_away", "score_home", "whos_favored", "spread",
                  "total", "moneyline_away", "moneyline_home"]
CURRENT_ROWS = [
    {"season": "2026", "date": "2025-11-05", "regular": "True",
     "playoffs": "False", "away": "phi", "home": "bos",
     "score_away": "100", "score_home": "108", "whos_favored": "home",
     "spread": "5.5", "total": "224.5", "moneyline_away": "180",
     "moneyline_home": "-220"},
    {"season": "2026", "date": "2026-01-12", "regular": "True",
     "playoffs": "False", "away": "den", "home": "lal",
     "score_away": "121", "score_home": "114", "whos_favored": "away",
     "spread": "3.0", "total": "231.0", "moneyline_away": "-160",
     "moneyline_home": "140"},
]


def test_current_schema_scores_and_signed_spread():
    rows, stats = mod.normalize_rows(CURRENT_HEADER, CURRENT_ROWS, CONFIG)
    assert stats["rows_accepted"] == 2
    first, second = rows
    assert first["home_score"] == pytest.approx(108.0)
    assert first["away_score"] == pytest.approx(100.0)
    # Unsigned magnitude 5.5, home favored -> home-perspective -5.5.
    assert first["closing_spread_home"] == pytest.approx(-5.5)
    # Away favored -> home is the underdog -> +3.0.
    assert second["closing_spread_home"] == pytest.approx(3.0)
    assert stats["spread_signed_from_favored"] == 2
    assert stats["spread_dropped_favored_unresolved"] == 0
    # The empirical audit must confirm the signed result.
    home_perspective, audit = mod.verify_spread_orientation(rows, None)
    assert home_perspective is True
    assert audit["home_agreement_rate"] == pytest.approx(1.0)


def test_current_schema_favored_by_team_code():
    rows_in = [dict(CURRENT_ROWS[0], whos_favored="bos")]
    rows, stats = mod.normalize_rows(CURRENT_HEADER, rows_in, CONFIG)
    assert rows[0]["closing_spread_home"] == pytest.approx(-5.5)
    assert stats["spread_signed_from_favored"] == 1


def test_favored_unresolved_drops_spread_leg_but_keeps_row():
    bad = dict(CURRENT_ROWS[0], whos_favored="")
    good = [dict(r) for r in CURRENT_ROWS[1:]] * 20
    rows, stats = mod.normalize_rows(CURRENT_HEADER, [bad] + good, CONFIG)
    assert rows[0]["closing_spread_home"] is None
    assert rows[0]["closing_total"] == pytest.approx(224.5)
    assert stats["spread_dropped_favored_unresolved"] == 1


def test_favored_mostly_unresolved_fails_closed():
    rows_in = [dict(r, whos_favored="???") for r in CURRENT_ROWS]
    with pytest.raises(mod.KaggleArchiveError) as excinfo:
        mod.normalize_rows(CURRENT_HEADER, rows_in, CONFIG)
    assert "KAGGLE_NBA_FAVORED_UNRESOLVED" in str(excinfo.value)
