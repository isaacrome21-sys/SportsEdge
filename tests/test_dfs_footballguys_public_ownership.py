"""Public NFL DFS ownership is provenance-bearing research, not admitted input."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone

import pytest

from sportsedge.dfs.sources.footballguys_ownership import (
    MAX_RAW_BYTES,
    PublicOwnershipError,
    main,
    match_public_ownership,
    parse_public_ownership,
)
from sportsedge.dfs.types import DKPlayer


WHEN = datetime(2026, 10, 25, 17, 0, tzinfo=timezone.utc)
HTML = (
    b'<table id="data-qb"><tr><th>Player</th><th>Percent</th></tr>'
    b'<tr><td class="la">Jared Goff</td><td style="background:red">11.7%</td></tr>'
    b'</table><table id="data-rb"><tr><td>Jahmyr Gibbs</td><td>24.0%</td></tr>'
    b'</table><table id="data-td"><tr><td>Minnesota Vikings</td>'
    b'<td>9.3%</td></tr></table>'
)


def _player(player_id: str, name: str, position: str, team: str = "DET") -> DKPlayer:
    return DKPlayer(player_id, name, team, "GB", (position,), 4000)


def test_parse_public_html_is_research_only_and_preserves_evidence() -> None:
    result = parse_public_ownership(HTML, received_at=WHEN)
    assert result["status"] == "RESEARCH_ONLY_UNVERIFIED"
    assert result["collection_method"] == "provided_html"
    assert result["site_publication_time"] is None
    assert result["quote_time_status"] == "UNVERIFIED"
    assert result["slate_id_status"] == "UNVERIFIED"
    assert result["received_at_utc"] == "2026-10-25T17:00:00+00:00"
    assert result["raw_sha256"] == hashlib.sha256(HTML).hexdigest()
    assert result["raw_bytes"] == len(HTML)
    assert result["positions_present"] == ["DST", "QB", "RB"]
    assert result["positions_missing"] == ["TE", "WR"]
    assert [(row["name"], row["position"]) for row in result["players"]] == [
        ("Jared Goff", "QB"), ("Jahmyr Gibbs", "RB"), ("Minnesota Vikings", "DST")
    ]
    assert [row["projected_ownership"] for row in result["players"]] == pytest.approx(
        [0.117, 0.24, 0.093]
    )


@pytest.mark.parametrize("raw,reason", [
    (b"", "FOOTBALLGUYS_RAW_INVALID"),
    (b"x" * (MAX_RAW_BYTES + 1), "FOOTBALLGUYS_RAW_INVALID"),
    (b"\xff", "FOOTBALLGUYS_HTML_ENCODING_INVALID"),
    (b"<html>Paywall</html>", "FOOTBALLGUYS_NO_PUBLIC_OWNERSHIP"),
    (b'<table id="data-qb"><tr><td>Goff</td><td>100.1%</td></tr></table>',
     "FOOTBALLGUYS_OWNERSHIP_INVALID"),
    (b'<table id="data-qb"><tr><td>Goff</td><td>-1%</td></tr></table>',
     "FOOTBALLGUYS_ROW_VALUE_INVALID"),
    (b'<table id="data-qb"><tr><td>Goff</td><td>NaN%</td></tr></table>',
     "FOOTBALLGUYS_ROW_VALUE_INVALID"),
    (b'<table id="data-qb"><tr><td>Goff</td><td>11.7</td></tr></table>',
     "FOOTBALLGUYS_ROW_VALUE_INVALID"),
    (b'<table id="data-qb"><tr><td>Goff</td><td>11.7%</td><td>extra</td></tr></table>',
     "FOOTBALLGUYS_ROW_SHAPE_INVALID"),
    (b'<table id="data-qb"><tr><td>Goff</td><td>11.7%</td></tr>'
     b'<tr><td>goff</td><td>12%</td></tr></table>',
     "FOOTBALLGUYS_DUPLICATE_PLAYER"),
])
def test_parse_rejects_bad_evidence(raw: bytes, reason: str) -> None:
    with pytest.raises(PublicOwnershipError, match=reason):
        parse_public_ownership(raw, received_at=WHEN)


@pytest.mark.parametrize("received_at", [
    datetime(2026, 10, 25, 17, 0),
    None,
])
def test_receipt_clock_must_be_timezone_aware(received_at) -> None:
    with pytest.raises(PublicOwnershipError, match="RECEIPT_TIMEZONE_REQUIRED"):
        parse_public_ownership(HTML, received_at=received_at)


def test_exact_player_match_and_strict_canonical_defense_match() -> None:
    report = parse_public_ownership(HTML, received_at=WHEN)
    players = [
        _player("dk-1", "Jared Goff", "QB"),
        _player("dk-2", "Jahmyr Gibbs", "RB"),
        _player("dk-3", "Vikings", "DST", "MIN"),
        _player("dk-4", "Goff", "QB"),
    ]
    joined = match_public_ownership(report, players)
    assert joined["status"] == "RESEARCH_ONLY_UNVERIFIED"
    assert {row["dk_player_id"] for row in joined["matched"]} == {"dk-1", "dk-2", "dk-3"}
    assert joined["blocked"] == []
    assert joined["source_sha256"] == report["raw_sha256"]


def test_defense_join_requires_name_and_team_to_agree() -> None:
    report = parse_public_ownership(HTML, received_at=WHEN)
    mismatched = _player("wrong-team", "Vikings", "DST", "GB")
    misleading = _player("wrong-name", "Packers", "DST", "MIN")
    safe = match_public_ownership(report, [mismatched, misleading])
    assert safe["matched"] == []
    assert safe["blocked"] == []


def test_two_distinct_dst_ids_remain_ambiguous() -> None:
    report = parse_public_ownership(HTML, received_at=WHEN)
    dupes = [_player("one", "Vikings", "DST", "MIN"),
             _player("two", "Minnesota Vikings", "DST", "MIN")]
    joined = match_public_ownership(report, dupes)
    assert joined["matched"] == []
    assert joined["blocked"] == [
        {"name": "Minnesota Vikings", "position": "DST", "reason": "AMBIGUOUS_DK_ID"}
    ]


def test_ambiguous_player_id_never_guessed() -> None:
    report = parse_public_ownership(HTML, received_at=WHEN)
    players = [_player("a", "Jared Goff", "QB"), _player("b", "Jared Goff", "QB")]
    joined = match_public_ownership(report, players)
    assert joined["matched"] == []
    assert joined["blocked"] == [
        {"name": "Jared Goff", "position": "QB", "reason": "AMBIGUOUS_DK_ID"}
    ]


def test_iterable_consumed_once_and_duplicate_id_refused() -> None:
    report = parse_public_ownership(HTML, received_at=WHEN)
    multi = DKPlayer("same", "Jared Goff", "DET", "GB", ("QB", "RB"), 4000)
    joined = match_public_ownership(report, (p for p in [multi]))
    assert [row["dk_player_id"] for row in joined["matched"]] == ["same"]


def test_cannot_join_unverified_or_invalid_report_values() -> None:
    report = parse_public_ownership(HTML, received_at=WHEN)
    report["status"] = "VERIFIED"
    with pytest.raises(PublicOwnershipError, match="RESEARCH_STATUS_REQUIRED"):
        match_public_ownership(report, [])
    report["status"] = "RESEARCH_ONLY_UNVERIFIED"
    report["players"][0]["projected_ownership"] = float("nan")
    with pytest.raises(PublicOwnershipError, match="MATCH_OWNERSHIP_INVALID"):
        match_public_ownership(report, [])


def test_offline_cli_preserves_raw_and_refuses_overwrite(tmp_path, monkeypatch, capsys) -> None:
    source = tmp_path / "provided.html"
    output = tmp_path / "parsed.json"
    raw_output = tmp_path / "raw.html"
    source.write_bytes(HTML)
    monkeypatch.setattr(sys, "argv", [
        "footballguys_ownership", "--input-html", str(source),
        "--output", str(output), "--raw-output", str(raw_output),
    ])
    main()
    report = json.loads(output.read_text())
    assert raw_output.read_bytes() == HTML
    assert report["collection_method"] == "provided_html"
    assert report["raw_sha256"] == hashlib.sha256(HTML).hexdigest()
    assert "research-only" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert raw_output.read_bytes() == HTML
