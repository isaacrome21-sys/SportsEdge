from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sportsedge.market_context.public_splits import (
    PublicSplitsError,
    PublicSplitSnapshot,
    compare_snapshots,
    diagnostics,
    parse_vsin_html,
)


STAMP = datetime(2026, 8, 29, 15, 0, tzinfo=timezone.utc)


def table_row(team, spread, sh, sb, total, th, tb, ml, mh, mb, button="↺"):
    return f"""
    <tr>
      <td>{button}</td><td>{team}</td><td>{spread}</td><td>{sh}%</td><td>{sb}%</td>
      <td>{total}</td><td>{th}%</td><td>{tb}%</td>
      <td>{ml}</td><td>{mh}%</td><td>{mb}%</td>
    </tr>
    """


def fixture_html(*, away_spread="+4.5", home_spread="-4.5", away_total="56.5", home_total="56.5"):
    return "<table>" + "".join([
        table_row("Memphis Tigers", away_spread, 58, 52, away_total, 35, 76, "+160", 63, 29),
        table_row("UNLV Rebels", home_spread, 42, 48, home_total, 65, 24, "-192", 37, 71, button="6"),
        table_row("North Carolina", "+8.5", 30, 41, "58.5", 54, 61, "+250", 25, 35),
        table_row("TCU", "-8.5", 70, 59, "58.5", 46, 39, "-310", 75, 65, button="4"),
    ]) + "</table>"


def test_vsin_parser_produces_two_games_six_market_side_rows_each():
    snap = parse_vsin_html(fixture_html(), captured_at=STAMP)
    assert snap.state == "OK"
    assert len(snap.observations) == 12
    first_six = snap.observations[:6]
    assert {(x.market, x.side) for x in first_six} == {
        ("SPREAD", "Memphis Tigers"),
        ("SPREAD", "UNLV Rebels"),
        ("TOTAL", "OVER"),
        ("TOTAL", "UNDER"),
        ("MONEYLINE", "Memphis Tigers"),
        ("MONEYLINE", "UNLV Rebels"),
    }


def test_vsin_total_first_row_is_over_second_is_under():
    snap = parse_vsin_html(fixture_html(), captured_at=STAMP)
    rows = [x for x in snap.observations if x.away_team == "Memphis Tigers" and x.market == "TOTAL"]
    over = next(x for x in rows if x.side == "OVER")
    under = next(x for x in rows if x.side == "UNDER")
    assert over.money_pct == 35
    assert over.ticket_pct == 76
    assert under.money_pct == 65
    assert under.ticket_pct == 24


def test_money_ticket_gap_is_signed_and_diagnostic_only():
    snap = parse_vsin_html(fixture_html(), captured_at=STAMP)
    rows = diagnostics(snap, money_ticket_gap_pp=15, public_ticket_pct=70)
    memphis_over = next(x for x in rows if x["side"] == "OVER" and x["away_team"] == "Memphis Tigers")
    assert memphis_over["money_ticket_gap_pp"] == -41
    assert "MONEY_TICKET_DIVERGENCE" in memphis_over["flags"]
    assert "PUBLIC_TICKET_HEAVY" in memphis_over["flags"]


def test_no_rows_is_explicit_no_public_split_data_not_zeroes():
    snap = parse_vsin_html("<html><body>No games</body></html>", captured_at=STAMP)
    assert snap.state == "NO_PUBLIC_SPLIT_DATA"
    assert snap.observations == ()


def test_non_complementary_provider_pair_fails_closed():
    bad = "<table>" + "".join([
        table_row("A", "+3", 80, 60, "50", 50, 50, "+120", 50, 50),
        table_row("B", "-3", 30, 40, "50", 50, 50, "-140", 50, 50),
    ]) + "</table>"
    with pytest.raises(PublicSplitsError, match="HANDLE_COMPLEMENT_INVALID"):
        parse_vsin_html(bad, captured_at=STAMP)


def test_odd_team_row_count_fails_closed():
    html = "<table>" + table_row("A", "+3", 50, 50, "50", 50, 50, "+120", 50, 50) + "</table>"
    with pytest.raises(PublicSplitsError, match="ROW_PAIRING_FAILED"):
        parse_vsin_html(html, captured_at=STAMP)


def test_snapshot_hash_is_deterministic():
    a = parse_vsin_html(fixture_html(), captured_at=STAMP)
    b = parse_vsin_html(fixture_html(), captured_at=STAMP)
    assert a.content_hash() == b.content_hash()


def test_compare_snapshots_captures_line_and_split_movement():
    old = parse_vsin_html(fixture_html(), captured_at=STAMP)
    later = datetime(2026, 8, 29, 15, 15, tzinfo=timezone.utc)
    new = parse_vsin_html(
        fixture_html(away_spread="+5.5", home_spread="-5.5"),
        captured_at=later,
    )
    rows = compare_snapshots(old, new, public_ticket_pct=50, minimum_point_move=0.5)
    away = next(x for x in rows if x["market"] == "SPREAD" and x["side"] == "Memphis Tigers")
    assert away["line_delta"] == pytest.approx(1.0)
    assert "REVERSE_LINE_MOVEMENT_CANDIDATE" in away["flags"]


def test_model_isolation_contract_not_embedded_as_prediction_fields():
    snap = parse_vsin_html(fixture_html(), captured_at=STAMP)
    payload = snap.to_dict()
    text = repr(payload).lower()
    assert "model_prob" not in text
    assert "model_p" not in text
    assert "truth_gate" not in text


def test_boolean_and_invalid_percent_are_rejected_without_fabrication():
    bad = "<table>" + "".join([
        table_row("A", "+3", 101, 50, "50", 50, 50, "+120", 50, 50),
        table_row("B", "-3", -1, 50, "50", 50, 50, "-140", 50, 50),
    ]) + "</table>"
    snap = parse_vsin_html(bad, captured_at=STAMP)
    assert snap.state == "NO_PUBLIC_SPLIT_DATA"


def test_source_identity_is_part_of_snapshot_hash():
    snap = parse_vsin_html(fixture_html(), captured_at=STAMP)
    changed = PublicSplitSnapshot(
        source="OTHER",
        source_book=snap.source_book,
        sport=snap.sport,
        captured_at=snap.captured_at,
        source_url=snap.source_url,
        observations=tuple(
            type(x)(**{**x.__dict__, "source": "OTHER"})
            for x in snap.observations
        ),
    )
    assert snap.content_hash() != changed.content_hash()
