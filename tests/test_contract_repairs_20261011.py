"""Priority-1 contract repairs (Oct 11 2026): override gate, two pricing lanes,
centralized 180s freshness, as-of snapshots, edge/EV/validated-profit labeling.

All fixtures are offline (injected getters); no network, no betting authority.
"""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "free_models_contracts", ROOT / "artifacts" / "free_models.py")
model = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model)

from sportsedge.quote_freshness import (
    MAX_QUOTE_AGE_SECONDS,
    check_quote_freshness,
    is_fresh,
)
from sportsedge.research_three_sport_bridge import price_three_sport_research

NOW = datetime(2026, 10, 11, 13, 0, tzinfo=timezone.utc)
KICKOFF = "2026-10-12T01:15:00Z"
FRESH_QUOTE = "2026-10-11T12:59:00Z"  # 60s before NOW


def row(**kw):
    x = {"sport": "NFL", "away": "Buffalo Bills", "home": "Los Angeles Rams",
         "market": "TOTAL", "side": "UNDER", "line": 54.5, "odds": -105,
         "kickoff": KICKOFF, "quote_captured_at": FRESH_QUOTE}
    x.update(kw)
    return x


def card(rows, **kw):
    return model.run({"sport": "NFL", "lines": rows}, now=NOW,
                     auto_context=False, **kw)


# ---- Repair 1: untrusted context overrides are gated, never silent. ----

def test_undeclared_context_dict_override_blocks_with_explicit_code():
    c = card([row(context={"weather_total_adj": -3.0})])
    r = c["evaluated_rows"][0]
    assert r["status"] == "BLOCKED_MANUAL_CONTEXT_UNDECLARED"
    assert "MANUAL_CONTEXT_OVERRIDES_REQUIRE_EXPLICIT_FLAG" in r["reason"]
    assert r["attempted_override_keys"] == ["context.weather_total_adj"]
    assert c["summary"]["status_counts"]["BLOCKED_MANUAL_CONTEXT_UNDECLARED"] == 1


def test_undeclared_top_level_context_key_override_blocks():
    c = card([row(home_injury_pts=-2.0)])
    r = c["evaluated_rows"][0]
    assert r["status"] == "BLOCKED_MANUAL_CONTEXT_UNDECLARED"
    assert r["attempted_override_keys"] == ["home_injury_pts"]


def test_conflicting_override_never_silently_replaces_verified_factors():
    # Even when verified context exists, an unflagged override must block
    # rather than silently win. (auto_context exercised via fixture getter.)
    def getter(url):
        if "scoreboard?" in url:
            return {"events": []}
        # Fixture recovery may independently request an NFL team index
        # before attempting a team-schedule fallback. No matching teams
        # means there is still NO verified fixture in this negative test.
        if url == "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams?limit=500":
            return {"sports": []}
        raise AssertionError("unexpected " + url)
    c = model.run(
        {"sport": "NFL", "lines": [dict(row(), context={"home_rating": 5.0},
                                        kickoff="2026-10-11T20:25:00Z")]},
        now=NOW, getter=getter, allow_manual_context=False)
    r = c["evaluated_rows"][0]
    assert r["status"] in ("BLOCKED_MANUAL_CONTEXT_UNDECLARED",
                           "BLOCKED_CONTEXT_UNVERIFIED")
    # The verified path never carries a silently-overridden value.
    assert r.get("context", {}).get("home_rating", 0.0) != 5.0


def test_flagged_override_applies_and_is_labeled_in_audit():
    c = card([row(context={"weather_total_adj": -3.0})],
             allow_manual_context=True)
    r = c["evaluated_rows"][0]
    assert r["status"] != "BLOCKED_MANUAL_CONTEXT_UNDECLARED"
    assert r["context"]["weather_total_adj"] == -3.0
    assert r["context_provenance"]["weather_total_adj"] == "USER_SUPPLIED_MANUAL"
    assert r["context_provenance"]["home_rating"] == "VERIFIED_PUBLIC"
    assert "OVERRIDE_USER_SUPPLIED:weather_total_adj" in r["context_notes"]


def test_unbounded_override_rejected_not_clamped():
    c = card([row(context={"weather_total_adj": 99.0})],
             allow_manual_context=True)
    assert c["evaluated_rows"][0]["status"] == "BLOCKED_INVALID"
    assert "CONTEXT_ADJUSTMENT_UNBOUNDED" in c["evaluated_rows"][0]["reason"]


# ---- Repair 2: two pricing lanes, every probability labeled. ----

def test_independent_lane_never_touches_a_market_price():
    # The Lane A PROBABILITY never sees a market price: same teams/kickoff,
    # different odds -> bit-identical Lane A p. (EV legitimately uses the
    # quoted price afterwards; the line defines the bet being priced, but the
    # Lane A score MEANS must not move with it either.)
    base = dict(row(), odds=-105)
    price_moved = dict(row(), odds=-150)
    line_moved = dict(row(), odds=-105, line=48.5)
    a = model.calculate(base, model.PublicContext(NOW), NOW, auto_context=False)
    p = model.calculate(price_moved, model.PublicContext(NOW), NOW, auto_context=False)
    l = model.calculate(line_moved, model.PublicContext(NOW), NOW, auto_context=False)
    la = a["pricing_lanes"]["lane_a_independent"]
    lp = p["pricing_lanes"]["lane_a_independent"]
    ll = l["pricing_lanes"]["lane_a_independent"]
    assert la["lane"] == "LANE_A_INDEPENDENT"
    assert la["estimate_p"] == lp["estimate_p"]
    assert la["projected_total"] == lp["projected_total"]
    assert la["uses_sportsbook_price_in_projection"] is False
    assert la["ev_per_dollar"] != lp["ev_per_dollar"]
    assert la["home_mean"] == ll["home_mean"]
    assert la["away_mean"] == ll["away_mean"]
    assert la["projected_total"] == ll["projected_total"]
    ba = a["pricing_lanes"]["lane_b_anchored"]
    bl = l["pricing_lanes"]["lane_b_anchored"]
    assert ba["lane"] == "LANE_B_ANCHORED"
    assert ba["estimate_p"] != bl["estimate_p"]


def test_every_probability_labeled_by_lane_on_card():
    c = card([row(), row(side="OVER", odds=-115)])
    for r in c["evaluated_rows"]:
        lanes = r["pricing_lanes"]
        assert lanes["lane_a_independent"]["lane"] == "LANE_A_INDEPENDENT"
        assert lanes["lane_b_anchored"]["lane"] == "LANE_B_ANCHORED"
        assert r["pricing_lane"] == "LANE_A_INDEPENDENT"  # default lane
    assert c["primary_lane"] == "LANE_A_INDEPENDENT"
    assert c["summary"]["lane_b_edges"] >= 0
    assert all("lane" in e["pricing_lanes"]["lane_b_anchored"]
               for e in c["lane_b_edges"])


def test_explicit_lane_b_request_labels_primary_view():
    c = card([row()], lane="B")
    r = c["evaluated_rows"][0]
    assert r["pricing_lane"] == "LANE_B_ANCHORED"
    assert c["primary_lane"] == "LANE_B_ANCHORED"
    assert r["estimate_p"] == r["pricing_lanes"]["lane_b_anchored"]["estimate_p"]
    assert r["market_anchor"]["status"] == "MARKET_ANCHORED_UNVALIDATED"
    assert r["market_anchor"]["weight"] == 0.15


def test_anchor_weight_declared_unvalidated_hypothesis():
    c = card([row()])
    anchor = c["evaluated_rows"][0]["market_anchor"]
    assert anchor["hypothesis"] == "UNVALIDATED_OUT_OF_SAMPLE_REQUIRED"


# ---- Repair 3: centralized 180s freshness on all pricing paths. ----

def test_centralized_freshness_codes():
    assert MAX_QUOTE_AGE_SECONDS == 180
    assert check_quote_freshness(FRESH_QUOTE, now=NOW)["code"] == "QUOTE_FRESH_UNDER_180S"
    stale = (NOW - timedelta(seconds=181)).isoformat()
    assert check_quote_freshness(stale, now=NOW)["code"] == "QUOTE_STALE_OVER_180S"
    future = (NOW + timedelta(seconds=60)).isoformat()
    assert check_quote_freshness(future, now=NOW)["code"] == "QUOTE_TIMESTAMP_IN_FUTURE"
    assert check_quote_freshness(None, now=NOW)["code"] == "QUOTE_FRESHNESS_UNVERIFIED"
    assert check_quote_freshness("not-a-time", now=NOW)["code"] == "QUOTE_TIMESTAMP_INVALID"
    assert is_fresh(check_quote_freshness(FRESH_QUOTE, now=NOW)) is True
    assert is_fresh(check_quote_freshness(stale, now=NOW)) is False


def test_stale_quote_is_watch_only_never_a_candidate():
    stale = (NOW - timedelta(seconds=600)).isoformat()
    c = card([row(quote_captured_at=stale),
              row(side="OVER", odds=-115, quote_captured_at=stale)])
    for r in c["evaluated_rows"]:
        assert r["status"] == "WATCH_QUOTE_NOT_CURRENT"
        assert r["quote_freshness"]["code"] == "QUOTE_STALE_OVER_180S"
        assert r["reason"].startswith("QUOTE_NOT_FRESH:")
    assert c["edges"] == []
    assert c["independent_candidates"] == []
    assert c["lane_b_edges"] == []
    assert c["summary"]["status_counts"]["WATCH_QUOTE_NOT_CURRENT"] == 2


def test_missing_quote_timestamp_is_watch_only():
    c = card([dict(row(), quote_captured_at=None)])
    r = c["evaluated_rows"][0]
    assert r["status"] == "WATCH_QUOTE_NOT_CURRENT"
    assert r["quote_freshness"]["code"] == "QUOTE_FRESHNESS_UNVERIFIED"


def test_bridge_routes_through_centralized_check():
    asof = "2026-10-11T20:30:00Z"
    m = {"sport": "MLB", "game_id": "g", "market": "PITCHER_K", "player_id": "1",
         "line": 5.5, "selection": "OVER", "estimate_p": 0.61, "push_p": 0,
         "status": "PRICED_RESEARCH", "model_source": "T",
         "market_blind": True, "as_of_utc": "2026-10-11T20:29:00Z",
         "kickoff_utc": "2026-10-12T03:00:00Z"}
    def q(captured, selection):
        return {"sport": "MLB", "game_id": "g", "market": "PITCHER_K",
                "player_id": "1", "line": 5.5, "selection": selection,
                "odds": -110, "book": "draftkings",
                "quote_captured_at": captured}
    stale = "2026-10-11T19:00:00Z"
    out = price_three_sport_research([m], [q(stale, "OVER"), q(stale, "UNDER")],
                                     as_of=asof)["rows"][0]
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "QUOTE_OVER_300S_REFUSED"
    assert "ev_per_dollar" not in out


# ---- Repair 4: as-of snapshots; no leakage of current-state sources. ----

def test_historical_mode_refuses_current_state_sources():
    p = model.PublicContext(NOW, getter=lambda url: {}, historical=True)
    injury, istatus = p.injury_points("NFL", {"id": "1"})
    assert injury == 0.0
    assert istatus == "AS_OF_HISTORICAL_INJURIES_UNAVAILABLE"
    weather, wstatus = p.weather("NFL", {"venue": {"indoor": False}}, NOW)
    assert weather == 0.0
    assert wstatus == "AS_OF_HISTORICAL_WEATHER_UNAVAILABLE"


def test_live_mode_still_fetches_current_injuries():
    p = model.PublicContext(NOW, getter=lambda url: {"injuries": []})
    _, istatus = p.injury_points("NFL", {"id": "1"})
    assert istatus != "AS_OF_HISTORICAL_INJURIES_UNAVAILABLE"


def test_card_carries_input_snapshot_and_clocks():
    c = card([row()])
    snap = c["input_snapshot"]
    assert snap["n_rows"] == 1
    assert len(snap["rows_sha1"]) == 40
    assert snap["as_of_utc"] == NOW.isoformat()
    assert snap["wall_utc"] == NOW.isoformat()
    assert snap["historical_repriced"] is False
    # Deterministic: same inputs, same hash.
    c2 = card([row()])
    assert c2["input_snapshot"]["rows_sha1"] == snap["rows_sha1"]


def test_explicit_as_of_clock_is_respected():
    asof = "2026-10-10T13:00:00Z"
    c = model.run({"sport": "NFL", "lines": [row()]}, now=NOW, as_of=asof,
                  auto_context=False)
    assert c["as_of_utc"] == "2026-10-10T13:00:00+00:00"
    assert c["wall_utc"] == NOW.isoformat()
    assert c["input_snapshot"]["as_of_utc"] == c["as_of_utc"]


# ---- Repair 5: edge vs EV vs validated profit stay distinct. ----

def test_no_validated_edge_status_anywhere():
    c = card([row(), row(side="OVER", odds=-115)])
    statuses = [r["status"] for r in c["evaluated_rows"]]
    assert "RESEARCH_EDGE" not in statuses
    assert "RESEARCH_EDGE" not in c["summary"]["status_counts"]
    for r in c["evaluated_rows"]:
        lanes = r.get("pricing_lanes") or {}
        assert lanes, "priced row must carry both lanes"
        for lane_view in lanes.values():
            assert lane_view.get("validated_profitability") is False
        assert r.get("validated_profitability") is False


def test_edge_ev_and_validated_profit_are_three_distinct_fields():
    c = card([row(), row(side="OVER", odds=-115)])
    for r in c["evaluated_rows"]:
        lanes = r["pricing_lanes"]
        la = lanes["lane_a_independent"]
        # (a) model edge estimate: P_model vs quoted breakeven ...
        assert "edge_over_break_even_pp" in la
        # ... and vs DK no-vig when an exact pair exists.
        assert "edge_vs_dk_no_vig_pp" in la or \
            la.get("paired_market_status") != "EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH"
        # (b) EV at the available quoted price ...
        assert "ev_per_dollar" in la
        assert la["ev_per_dollar"] != la["edge_over_break_even_pp"]
        # (c) validated profitability: tracked separately, always False here.
        assert la["validated_profitability"] is False
        assert c["authority"]["validated_profitability"] is False


def test_positive_raw_ev_from_no_fetch_is_diagnostic_not_candidate():
    # A league-prior projection can mathematically be +EV against a quote,
    # but absent team-specific data it cannot be displayed as a wager idea.
    c = card([row(side="OVER", line=40.5)])
    assert not c["edges"]
    assert not c["independent_candidates"]
    assert not c["lane_b_edges"]
    r = c["evaluated_rows"][0]
    assert r["status"] == "WATCH_NFL_NO_VERIFIED_CONTEXT"
    assert r["independent_projection"]["ev_per_dollar"] > 0
    assert r["research_only"] is True
    assert r["model_validation"] == "NOT_PROVEN_VS_CLOSE"
