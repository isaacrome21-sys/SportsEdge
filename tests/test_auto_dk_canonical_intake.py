"""Already-paid DK snapshots go to canonical current-value screening safely."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from sportsedge.auto_dk_canonical_intake import bind_capture
from scripts.run_auto_dk_live_value_card import run_capture_directory


NOW = datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc)


def snapshot(sport="MLB"):
    observed = (NOW - timedelta(seconds=30)).isoformat()
    return {
        "sport": sport, "source": "THE_ODDS_API_V4", "status": "READY",
        "captured_at_utc": NOW.isoformat(),
        "estimate_p": None,
        "games": [{
            "provider_event_id": "evt-01", "away": "A", "home": "B",
            "commence_time": (NOW + timedelta(hours=1)).isoformat(),
            "estimate_p": None,
            "markets": {
                "h2h": {"book": "draftkings", "observed_at": observed,
                        "line": None, "away": 135, "home": -150},
                "spreads": {"book": "draftkings", "observed_at": observed,
                            "line": 3.5, "away": -110, "home": -110},
                "totals": {"book": "draftkings", "observed_at": observed,
                           "line": 8.5, "over": -120, "under": 100},
            },
        }],
    }


@pytest.mark.parametrize("sport", ["MLB", "NBA", "CFB", "NFL"])
def test_existing_four_sport_board_binds_both_sides_no_model_p(sport):
    source = snapshot(sport)
    original = deepcopy(source)
    rows, refused = bind_capture(source, now=NOW)
    assert refused == []
    assert len(rows) == 6
    assert {(r["market"], r["side"]) for r in rows} == {
        ("ML", "AWAY"), ("ML", "HOME"),
        ("SPREAD", "AWAY"), ("SPREAD", "HOME"),
        ("TOTAL", "OVER"), ("TOTAL", "UNDER")}
    assert [r["line"] for r in rows if r["market"] == "SPREAD"] == [3.5, -3.5]
    assert all(r["book"] == "draftkings" and r["capture_event_id"] == "evt-01"
               for r in rows)
    assert all("model_probability" not in r and "estimate_p" not in r for r in rows)
    assert source == original


def test_stale_snapshot_and_market_fail_closed_without_backfill():
    source = snapshot()
    source["captured_at_utc"] = (NOW - timedelta(seconds=181)).isoformat()
    rows, failed = bind_capture(source, now=NOW)
    assert rows == [] and failed[0]["reason"] == "SNAPSHOT_CAPTURE_EXPIRED_OR_INVALID"
    source = snapshot()
    source["games"][0]["markets"]["totals"]["observed_at"] = (
        NOW - timedelta(seconds=181)).isoformat()
    rows, failed = bind_capture(source, now=NOW)
    assert len(rows) == 4
    assert failed[0]["reason"] == "MARKET_QUOTE_EXPIRED_OR_FUTURE"


def test_market_families_do_not_launder_unknown_or_incomplete_pair():
    source = snapshot()
    source["games"][0]["markets"]["h2h"].pop("home")
    source["games"][0]["markets"]["totals"]["book"] = "fanduel"
    source["games"][0]["markets"]["fantasy"] = {"side": "OVER", "odds": -110}
    rows, refused = bind_capture(source, now=NOW)
    assert len(rows) == 2 and all(row["market"] == "SPREAD" for row in rows)
    assert {x["reason"] for x in refused} == {
        "PAIR_PRICE_OR_THRESHOLD_INVALID", "BOOK_IDENTITY_OR_MARKET_MISSING",
        "MARKET_NOT_SUPPORTED_BY_CAPTURE"}


def test_duplicate_event_and_illinois_cfb_block():
    source = snapshot("CFB")
    source["games"].append(deepcopy(source["games"][0]))
    rows, refused = bind_capture(source, now=NOW)
    assert len(rows) == 6 and refused[0]["reason"] == "DUPLICATE_PROVIDER_EVENT_ID"
    source = snapshot("CFB")
    source["games"][0]["home"] = "Illinois Fighting Illini"
    rows, refused = bind_capture(source, now=NOW)
    assert rows == [] and refused[0]["reason"] == "ILLINOIS_COLLEGE_EXCLUDED"


def test_untrusted_provider_and_invalid_clock_refused():
    source = snapshot()
    source["source"] = "USER_SUPPLIED_MODEL_P"
    with pytest.raises(ValueError, match="PROVENANCE_INVALID"):
        bind_capture(source, now=NOW)
    with pytest.raises(ValueError, match="TIMEZONE_REQUIRED"):
        bind_capture(snapshot(), now=datetime(2026, 10, 23))


def test_no_model_when_snapshots_missing_or_unavailable(tmp_path):
    audit, card, markdown = run_capture_directory(
        tmp_path, now=NOW, runner=lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("must not invoke engine")))
    assert card is None
    assert audit["status"] == "NO_FRESH_PAIRED_QUOTES"
    assert len(audit["capture_refusals"]) == 4
    assert "No fresh paired DK" in markdown


def test_existing_capture_reaches_canonical_runner_without_extra_odds_requests(tmp_path):
    (tmp_path / "mlb_odds.json").write_text(json.dumps(snapshot()) + "\n")
    observed = {}

    def runner(payload, **kwargs):
        observed["lines"] = payload["lines"]
        observed["kwargs"] = kwargs
        return {"evaluated_rows": [{} for _ in payload["lines"]]}

    def render(card, *, now):
        assert now.tzinfo is not None
        assert len(card["evaluated_rows"]) == 6
        return "phone preview"

    audit, card, markdown = run_capture_directory(tmp_path, now=NOW,
                                                  runner=runner, render=render)
    assert audit["input_rows"] == 6
    assert audit["new_sportsbook_calls"] == 0
    assert markdown == "phone preview"
    assert len(observed["lines"]) == 6
    assert observed["kwargs"]["as_of"] == NOW.isoformat()
    assert observed["kwargs"]["auto_context"] is True


def test_real_canonical_no_fetch_seam_cannot_create_an_actionable_value_screen():
    from artifacts.run_it_full import run_full
    from sportsedge.phone_display import build_current_value_screens

    rows, refused = bind_capture(snapshot(), now=NOW)
    assert not refused
    card = run_full({"lines": rows}, now=NOW, auto_context=False)
    assert len(card["evaluated_rows"]) == 6
    # Without independently fetched matchup context, even a nominal +EV
    # game model is not a current trusted priced opportunity.
    assert build_current_value_screens(card, now=NOW)["total_positive_screens"] == 0
