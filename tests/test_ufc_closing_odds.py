import json

from sportsedge.ufc_closing_odds import (
    ClosingQuote,
    archive_provenance_errors,
    closing_archive_template,
    enrich_metadata_with_closing_market,
    load_archive,
    match_closing_market,
    no_vig_probability_a,
)


def quote(
    bookmaker,
    odds_a,
    odds_b,
    *,
    snapshot="2026-08-15T23:55:00Z",
    commence="2026-08-16T00:00:00Z",
    event_id="e1",
    a="Alpha",
    b="Beta",
):
    return ClosingQuote.from_mapping(
        {
            "event_id": event_id,
            "snapshot_time": snapshot,
            "commence_time": commence,
            "bookmaker": bookmaker,
            "fighter_a": a,
            "fighter_b": b,
            "odds_a": odds_a,
            "odds_b": odds_b,
        }
    )


def test_no_vig_removes_two_way_hold():
    p = no_vig_probability_a(-120, +100)
    assert 0.52 < p < 0.53


def test_match_uses_latest_quote_per_book_and_consensus():
    rows = [
        quote("draftkings", -110, -110, snapshot="2026-08-15T23:45:00Z"),
        quote("draftkings", -120, +100, snapshot="2026-08-15T23:55:00Z"),
        quote("fanduel", -130, +110, snapshot="2026-08-15T23:55:00Z"),
    ]
    meta = {
        "fight_date": "2026-08-15",
        "fighter_a": "Alpha",
        "fighter_b": "Beta",
    }
    match = match_closing_market(meta, rows, min_bookmakers=2)
    assert match is not None
    assert match.bookmakers == ("draftkings", "fanduel")
    assert match.quote_count == 2
    assert 0.52 < match.probability_a < 0.55


def test_orientation_is_reversed_when_archive_lists_opposite_fighter_first():
    rows = [
        quote("draftkings", +100, -120, a="Beta", b="Alpha"),
        quote("fanduel", +110, -130, a="Beta", b="Alpha"),
    ]
    meta = {
        "fight_date": "2026-08-15",
        "fighter_a": "Alpha",
        "fighter_b": "Beta",
    }
    match = match_closing_market(meta, rows, min_bookmakers=2)
    assert match is not None
    assert 0.52 < match.probability_a < 0.55


def test_pair_plus_date_disambiguates_rematch():
    old = [
        quote(
            "draftkings",
            -300,
            +240,
            snapshot="2025-08-15T23:55:00Z",
            commence="2025-08-16T00:00:00Z",
            event_id="old",
        ),
        quote(
            "fanduel",
            -310,
            +250,
            snapshot="2025-08-15T23:55:00Z",
            commence="2025-08-16T00:00:00Z",
            event_id="old",
        ),
    ]
    new = [
        quote("draftkings", -120, +100, event_id="new"),
        quote("fanduel", -130, +110, event_id="new"),
    ]
    meta = {
        "fight_date": "2026-08-15",
        "fighter_a": "Alpha",
        "fighter_b": "Beta",
    }
    match = match_closing_market(meta, old + new, min_bookmakers=2)
    assert match is not None
    assert match.event_ids == ("new",)


def test_match_revalidates_direct_quotes_and_rejects_post_commence():
    rows = [
        quote(
            "draftkings",
            -120,
            +100,
            snapshot="2026-08-16T00:01:00Z",
            commence="2026-08-16T00:00:00Z",
        ),
        quote("fanduel", -130, +110),
    ]
    meta = {
        "fight_date": "2026-08-15",
        "fighter_a": "Alpha",
        "fighter_b": "Beta",
    }
    assert match_closing_market(meta, rows, min_bookmakers=2) is None


def test_archive_rejects_post_commence_and_unverified_provenance(tmp_path):
    payload = closing_archive_template()
    payload["provider"] = "Unverified Provider"
    payload["quotes"] = [
        {
            "event_id": "e1",
            "snapshot_time": "2026-08-16T00:01:00Z",
            "commence_time": "2026-08-16T00:00:00Z",
            "bookmaker": "draftkings",
            "fighter_a": "Alpha",
            "fighter_b": "Beta",
            "odds_a": -120,
            "odds_b": +100,
        }
    ]
    path = tmp_path / "closing.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    _, quotes, errors = load_archive(path)
    assert quotes == []
    assert "CLOSING_PROVIDER_UNVERIFIED" in errors
    assert any(x.startswith("CLOSING_ROWS_NOT_PRECOMMENCE:") for x in errors)


def test_enrichment_requires_multiple_books():
    meta = [
        {
            "fight_date": "2026-08-15",
            "fighter_a": "Alpha",
            "fighter_b": "Beta",
        }
    ]
    one_book = [quote("draftkings", -120, +100)]
    rows, summary = enrich_metadata_with_closing_market(
        meta, one_book, min_bookmakers=2
    )
    assert rows[0].get("market_probability_a") is None
    assert summary["matched"] == 0
    assert summary["coverage"] == 0.0


def test_exact_provenance_template_has_no_errors():
    payload = closing_archive_template()
    assert archive_provenance_errors(payload) == []
