"""t197 (#2319/#2354): one-sided MLB prop quotes keep their named blocker but
surface the real engine probability as a RESEARCH_ONLY estimate.

RED before the fix: 28 HR/Hits rows and 2 first-inning rows carried a
model probability inside the bridge but the card received only the blocker;
PITCHER_STRIKEOUTS never reached the real pitcher engine at all.
"""
from artifacts import run_it_full
from sportsedge.research_estimate import valid_research_estimate
from sportsedge.research_three_sport_bridge import price_three_sport_research

ASOF = "2026-10-15T21:52:00Z"
FUTURE = "2026-10-16T00:00:00Z"


def model(**other):
    row = {"sport": "MLB", "game_id": "849810", "market": "BATTER_HOME_RUNS",
           "home_team": "Los Angeles Dodgers", "away_team": "Milwaukee Brewers",
           "player_id": "660271", "line": 0.5, "selection": "OVER",
           "estimate_p": .18, "push_p": 0, "status": "PRICED_RESEARCH",
           "model_source": "mlb_batter_test", "market_blind": True,
           "as_of_utc": "2026-10-15T21:51:00Z", "kickoff_utc": FUTURE}
    row.update(other)
    return row


def quote(selection="OVER", odds=452, captured=None):
    return {"sport": "MLB", "game_id": "849810", "market": "BATTER_HOME_RUNS",
            "home_team": "Los Angeles Dodgers", "away_team": "Milwaukee Brewers",
            "player_id": "660271", "line": 0.5, "selection": selection,
            "odds": odds, "book": "draftkings", "quote_captured_at": captured}


def judge(m, quotes):
    return price_three_sport_research([m], quotes, as_of=ASOF)["rows"][0]


def test_one_sided_quote_keeps_blocker_and_carries_research_estimate():
    row = judge(model(), [quote()])
    assert row["status"] == "NO_MODEL_OR_MARKET"
    assert row["reason"] == "EXACT_PAIRED_DK_QUOTE_REQUIRED"
    est = valid_research_estimate(row)
    assert est is not None and est["probability"] == 0.18
    assert est["blocker_kept"] == "EXACT_PAIRED_DK_QUOTE_REQUIRED"
    assert est["eligible"] is False and est["counts_as_validation"] is False
    assert "ev_per_dollar" not in row and "dk_no_vig_p" not in row


def test_paired_without_capture_clock_keeps_blocker_and_estimate():
    row = judge(model(), [quote(), quote("UNDER", -700)])
    assert row["reason"] == "PAIRED_QUOTES_CAPTURE_TIMESTAMPS_REQUIRED"
    assert valid_research_estimate(row)["probability"] == 0.18


def test_started_game_live_or_model_failure_never_get_estimate():
    assert "research_estimate" not in judge(model(kickoff_utc="2026-10-15T21:00:00Z"), [quote()])
    assert "research_estimate" not in judge(model(phase="LIVE"), [quote()])
    assert "research_estimate" not in judge(model(status="NO_MODEL"), [quote()])
    assert "research_estimate" not in judge(model(estimate_p=1.3), [quote()])
    assert "research_estimate" not in judge(model(market_blind=False), [quote()])


def test_properly_paired_fresh_quote_is_unchanged_and_has_no_annex():
    row = judge(model(), [quote(captured="2026-10-15T21:51:30Z"),
                          quote("UNDER", -700, captured="2026-10-15T21:51:40Z")])
    assert "research_estimate" not in row
    assert "ev_per_dollar" in row


def test_pitcher_strikeouts_board_name_routes_to_real_pitcher_engine():
    line = {"sport": "MLB", "away": "Milwaukee Brewers", "home": "Los Angeles Dodgers",
            "kickoff": "2026-10-15T19:00:00-05:00", "book": "draftkings",
            "market": "PITCHER_STRIKEOUTS", "side": "OVER", "odds": 112,
            "line": 6.5, "player_name": "Tyler Glasnow"}
    def no_network(url, *a, **k):
        raise OSError("offline test")
    card = run_it_full.run_full({"lines": [line]}, auto_context=False, getter=no_network)
    row = card["evaluated_rows"][0]
    assert row.get("reason") != "MARKET_NOT_SUPPORTED_BY_REAL_PITCHER_ENGINE"
    assert row["status"] not in {"RESEARCH_CANDIDATE_NOT_VALIDATED", "PLAY"}
    assert card["edges"] == []


def test_first_inning_lane_carries_annex_through_its_blocked_row(monkeypatch):
    import sportsedge.mlb_phone_first_inning_pricing as fi
    src = open(fi.__file__).read()
    # Contract check on the lane: a bridge refusal must not drop the annex.
    assert 'out["research_estimate"] = judged["research_estimate"]' in src


def test_pitcher_lane_pairs_aliased_quotes():
    from sportsedge.mlb_phone_pitcher_pricing import _canonical_market
    assert _canonical_market("pitcher_strikeouts") == "PITCHER_K"
    assert _canonical_market("PITCHER_OUTS") == "PITCHER_OUTS"


def test_pitcher_k_research_annex_withheld_under_forward_hold():
    from sportsedge.mlb_phone_pitcher_pricing import withhold_pitcher_k_annex
    row = judge(model(market="PITCHER_K", line=6.5), [])
    assert "research_estimate" in row  # bridge produced one ...
    out = withhold_pitcher_k_annex(row, "PITCHER_K")
    assert "research_estimate" not in out  # ... the pitcher-K lane withholds it
    assert out["research_estimate_withheld"] == "PITCHER_K_FORWARD_HOLD_RESEARCH_ESTIMATE_WITHHELD"
    assert out["reason"] == "EXACT_PAIRED_DK_QUOTE_REQUIRED"
    other = withhold_pitcher_k_annex(judge(model(market="PITCHER_OUTS", line=17.5), []), "PITCHER_OUTS")
    assert "research_estimate" in other
