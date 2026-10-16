"""MLB free phone card must expose the entire declared market catalog honestly."""
from datetime import datetime, timezone

from artifacts.run_it_full import run_full
from sportsedge.mlb_full_board import catalog_markets, catalog_complete
from sportsedge.mlb_phone_full_board import phone_market_board

NOW = datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc)
KICKOFF = "2026-10-12T21:00:00Z"


def sample(market="ML", side="HOME", **changes):
    row = {
        "sport": "MLB", "away": "Los Angeles Dodgers",
        "home": "Milwaukee Brewers", "commence_time": KICKOFF,
        "quote_captured_at": "2026-10-12T18:59:00Z",
        "market": market, "side": side, "odds": +109,
    }
    row.update(changes)
    return row


def test_single_moneyline_can_never_pass_as_all_markets_priced():
    result = run_full({"lines": [sample()]}, now=NOW, auto_context=False)
    board = result["mlb_full_board"]
    coverage = board["input_coverage"]
    assert coverage["catalog_market_count"] >= 38
    assert coverage["supplied_market_count"] == 1
    assert coverage["priced_research_market_count"] == 1
    assert coverage["supplied_markets"] == ["MONEYLINE"]
    assert "RUN_LINE" in coverage["not_supplied_markets"]
    assert "TOTALS" in coverage["not_supplied_markets"]
    assert "F5_MONEYLINE" in coverage["not_supplied_markets"]
    assert "PITCHER_K" in coverage["not_supplied_markets"]
    assert board["authority"] == "PRESENTATION_ONLY"
    assert board["official_authority"] is False
    assert catalog_complete(board["summary"]) is True
    missing = [r for r in board["rows"] if r["market"] == "F5_MONEYLINE"]
    assert len(missing) == 2
    assert all(r["presentation"] == "BLOCKED" and r["model_p"] is None for r in missing)
    assert result["evaluated_rows"][0]["status"] in {"RESEARCH_DIAGNOSTIC_LANE_A_RETIRED",
        "RESEARCH_POSITIVE_EV_UNVALIDATED", "BELOW_THRESHOLD", "PRICE_CAP"
    }


def test_quoted_unsupported_f5_is_retained_without_fabricated_probability():
    rows = [sample("ML"), sample("F5_MONEYLINE", side="AWAY", odds=-115)]
    r = run_full({"lines": rows}, now=NOW, auto_context=False)
    coverage = r["mlb_full_board"]["input_coverage"]
    assert "F5_MONEYLINE" in coverage["supplied_markets"]
    assert "F5_MONEYLINE" in coverage["supplied_but_unpriced_markets"]
    f5 = [x for x in r["mlb_full_board"]["rows"] if x["market"] == "F5_MONEYLINE"
          and x["side"] == "AWAY"]
    assert len(f5) == 1
    assert f5[0]["american_odds"] == -115
    assert f5[0]["model_p"] is None


def test_watch_or_blocked_result_not_rebranded_as_model_price():
    board = phone_market_board(
        [sample()],
        [{"status": "WATCH_QUOTE_NOT_CURRENT", "estimate_p": 0.91,
          "reason": "QUOTE_NOT_FRESH:QUOTE_STALE_OVER_180S"}],
    )
    assert board["input_coverage"]["priced_research_market_count"] == 0
    rows = [r for r in board["rows"] if r["market"] == "MONEYLINE"]
    assert all(r["model_p"] is None for r in rows)


def test_game_only_board_does_not_impersonate_pitcher_or_batter_models():
    board = phone_market_board([sample()], [
        {"status": "RESEARCH_POSITIVE_EV_UNVALIDATED", "estimate_p": .506}
    ])
    assert "PITCHER_K" in board["input_coverage"]["not_supplied_markets"]
    assert "HITS" in board["input_coverage"]["not_supplied_markets"]
    assert set(catalog_markets()) >= set(board["input_coverage"]["not_supplied_markets"])
