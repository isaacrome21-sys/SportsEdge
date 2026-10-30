"""Offline negative controls for unadmitted NFL weekly injury HTML archive."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.collect_nfl_official_injury_report import (
    MAX_HTML_BYTES,
    archive_report,
    inspect_report,
    main,
    official_url,
)

NOW = "2026-10-25T04:00:00+00:00"


def fixture_html(season=2026, week=7):
    return (
        f"<html><head><title>Official NFL Injury Report for Players "
        f"- Week {week} of the {season} Season</title></head><body>"
        "<h1>NFL Injury Report</h1><table><tr>"
        "<th>Player</th><th>Practice Status</th><th>Game Status</th>"
        "</tr></table></body></html>"
    ).encode()


def test_url_contract():
    assert official_url(2026, "REG", 7) == "https://www.nfl.com/injuries/league/2026/REG7"
    for season, phase, week in ((1999, "REG", 1), (2026, "REG", 19),
                                (2026, "post", 1), (2026, "POST", 6)):
        with pytest.raises(ValueError):
            official_url(season, phase, week)


def test_html_gross_shape_not_player_parser():
    result = inspect_report(fixture_html(), 2026, "REG", 7)
    assert result["html_bytes"] > 0
    assert result["player_rows_verified"] is None


@pytest.mark.parametrize("bad", [
    b"", b"%PDF-1.5" + fixture_html(),
    b"PK\x03\x04" + fixture_html(),
    b"<html><title>NFL Injury Report</title></html>",
    b"<html>NFL Injury Report Player Practice Status Game Status Week 7 2025</html>",
    b"<html>Week 7 2026 Player Practice Status Game Status</html>",
    b"\xff" * 200,
])
def test_refuses_missing_or_misidentified_html(bad):
    with pytest.raises(ValueError):
        inspect_report(bad, 2026, "REG", 7)


def test_refuses_too_large():
    with pytest.raises(ValueError, match="TOO_LARGE"):
        inspect_report(fixture_html() + b" " * MAX_HTML_BYTES, 2026, "REG", 7)


def test_archive_immutable_repeated_observations(tmp_path):
    raw = fixture_html()
    first = archive_report(tmp_path, raw, NOW, 2026, "REG", 7)
    assert first["raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert first["pit_available"] is False
    assert first["roster_completeness_verified"] is False
    assert first["pricing_input"] is False
    assert first["parsed_players"] is None
    assert first["page_type"] == "WEEKLY_INJURY_NOT_GAMEDAY_INACTIVES"
    second = archive_report(tmp_path, raw, "2026-10-25T04:00:01+00:00", 2026, "REG", 7)
    assert first["raw_sha256"] == second["raw_sha256"]
    assert len(list(tmp_path.glob("*.html"))) == 1
    receipts = [json.loads(path.read_text()) for path in tmp_path.glob("*.json")]
    assert len(receipts) == 2
    archive_path = Path(first["raw_path"])
    archive_path.write_bytes(b"altered")  # simulated external tampering
    with pytest.raises(ValueError, match="CONFLICT"):
        archive_report(tmp_path, raw, "2026-10-25T04:00:02+00:00", 2026, "REG", 7)


@pytest.mark.parametrize("bad_time", [
    "2026-10-25T04:00:00", "2026-10-25T04:00:00-05:00",
])
def test_rejects_nonutc_timestamp(tmp_path, bad_time):
    with pytest.raises(ValueError, match="RECEIPT_TIME"):
        archive_report(tmp_path, fixture_html(), bad_time, 2026, "REG", 7)
    assert list(tmp_path.iterdir()) == []


def test_off_by_default_no_network_no_io(tmp_path, capsys):
    with patch("scripts.collect_nfl_official_injury_report._fetch_official", side_effect=AssertionError):
        assert main(["--output-dir", str(tmp_path), "--season", "2026",
                     "--season-type", "REG", "--week", "7"]) == 0
    assert "DISABLED_REQUIRES_LIVE" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_invalid_input_fails_before_fetch(tmp_path, capsys):
    with patch("scripts.collect_nfl_official_injury_report._fetch_official", side_effect=AssertionError):
        assert main(["--live", "--output-dir", str(tmp_path),
                     "--season", "2026", "--season-type", "REG", "--week", "19"]) == 2
    assert "NFL_INJURY_ARCHIVE_BLOCKED" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_network_error_fails_closed(tmp_path, capsys):
    with patch("scripts.collect_nfl_official_injury_report._fetch_official",
               side_effect=OSError("blocked")):
        assert main(["--live", "--output-dir", str(tmp_path),
                     "--season", "2026", "--season-type", "REG", "--week", "7"]) == 2
    assert "NFL_INJURY_ARCHIVE_BLOCKED" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
