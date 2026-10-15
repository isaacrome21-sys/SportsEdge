"""t197 (#2319/#2354): an unattested owner-screenshot quote is not a stale quote.

RED before the fix: every one of the 16 game rows on the Oct 15 card showed
"REFRESH REQUIRED / Current quote required" with no estimate, although the
engine had priced them and no quote age existed at all.
"""
from sportsedge.phone_display import build_phone_card, render_phone_card
from sportsedge.research_estimate import build_research_estimate


def _game_row(code, age=None, **extra):
    row = {"input_index": 0, "sport": "NFL", "market": "ML",
           "game": "Seattle Seahawks @ Denver Broncos",
           "selection": "Seattle Seahawks ML", "odds_american": -142,
           "status": "WATCH_QUOTE_NOT_CURRENT",
           "reason": "QUOTE_NOT_FRESH:" + code,
           "estimate_p": 0.48201, "fair_american": 107, "ev_per_dollar": -0.18,
           "pricing_provenance": {"lane": "INDEPENDENT"},
           "quote_freshness": {"code": code, "age_seconds": age, "max_age_seconds": 180}}
    row.update(extra)
    return row


def _card(row, intake=None):
    card = {"evaluated_rows": [row], "summary": {"rows": 1}, "min_ev": 0.02,
            "as_of_utc": "2026-10-15T22:06:15+00:00"}
    if intake is not None:
        card["selection_intake"] = [intake]
    return card


SCREENSHOT = {"sport": "NFL", "market": "ML", "side": "AWAY",
              "quote_source": "OWNER_DK_SCREENSHOT",
              "book_quote_receipt_verified": False}


def test_screenshot_unattested_quote_gets_research_estimate_not_refresh():
    sel = build_phone_card(_card(_game_row("QUOTE_FRESHNESS_UNVERIFIED"), SCREENSHOT))["selections"][0]
    assert sel["status"] == "RESEARCH ONLY"
    assert "OWNER_SCREENSHOT_QUOTE_NOT_ATTESTED" in sel["reason"]
    assert "RESEARCH_ONLY_UNVALIDATED" in sel["reason"]
    assert sel["probability"] == 0.48201
    assert sel["fair_odds"] == 107
    assert sel["estimated_ev"] is None  # no EV against an unattested price
    assert sel["eligible"] is False and sel["research_only_estimate"] is True


def test_unattested_non_screenshot_quote_named_receipt_not_attested():
    # Existing contract (test_phone_display): a generic unattested quote stays
    # REFRESH REQUIRED; it is now named instead of "Current quote required".
    sel = build_phone_card(_card(_game_row("QUOTE_FRESHNESS_UNVERIFIED"),
                                 {"sport": "NFL", "market": "ML"}))["selections"][0]
    assert sel["status"] == "REFRESH REQUIRED"
    assert sel["reason"] == "QUOTE_RECEIPT_NOT_ATTESTED"
    assert sel["probability"] is None


def test_genuinely_stale_quote_stays_refresh_required_and_names_age():
    sel = build_phone_card(_card(_game_row("QUOTE_STALE_OVER_180S", age=912.4), SCREENSHOT))["selections"][0]
    assert sel["status"] == "REFRESH REQUIRED"
    assert sel["reason"].startswith("QUOTE_STALE")
    assert "912" in sel["reason"]
    assert sel["probability"] is None and sel["estimated_ev"] is None


def test_future_or_invalid_quote_never_becomes_research():
    for code in ("QUOTE_TIMESTAMP_FUTURE", "QUOTE_TIMESTAMP_INVALID"):
        sel = build_phone_card(_card(_game_row(code, age=-5), SCREENSHOT))["selections"][0]
        assert sel["status"] == "REFRESH REQUIRED"
        assert code in sel["reason"]
        assert sel["probability"] is None


def test_anchored_row_never_research_estimate():
    row = _game_row("QUOTE_FRESHNESS_UNVERIFIED", pricing_lane="LANE_B_ANCHORED")
    sel = build_phone_card(_card(row, SCREENSHOT))["selections"][0]
    assert sel["status"] != "RESEARCH ONLY"
    assert sel["probability"] is None


def test_research_rows_never_lean_play_and_counted_separately():
    view = build_phone_card(_card(_game_row("QUOTE_FRESHNESS_UNVERIFIED"), SCREENSHOT))
    assert view["status_counts"] == {"RESEARCH ONLY": 1}
    fam = view["coverage"]["families"][0]
    assert fam["research"] == 1 and fam["priced"] == 0
    md = render_phone_card(_card(_game_row("QUOTE_FRESHNESS_UNVERIFIED"), SCREENSHOT))
    assert "| PLAY |" not in md and "| LEAN |" not in md
    assert "RESEARCH ONLY" in md


def test_blocked_row_with_valid_research_estimate_keeps_blocker_name():
    est = build_research_estimate(0.62, engine="free_models.CFB", blocker="FAMILY_REGISTRY_NOT_VALIDATED")
    row = {"input_index": 0, "sport": "CFB", "market": "ML", "status": "NO_MODEL_OR_MARKET",
           "reason": "FAMILY_REGISTRY_NOT_VALIDATED: family registry state BLOCKED",
           "blocker": "NO_VALIDATION", "research_estimate": est}
    sel = build_phone_card(_card(row))["selections"][0]
    assert sel["status"] == "RESEARCH ONLY"
    assert "FAMILY_REGISTRY_NOT_VALIDATED" in sel["reason"]
    assert sel["probability"] == 0.62 and sel["estimated_ev"] is None
    assert sel["source_status"] == "NO_MODEL_OR_MARKET"


def test_forged_or_authority_claiming_estimate_is_ignored():
    est = build_research_estimate(0.62, engine="x", blocker="FAMILY_REGISTRY_NOT_VALIDATED")
    for forged in ({**est, "eligible": True}, {**est, "counts_as_validation": True},
                   {**est, "play": True}, {**est, "probability": 1.4},
                   {**est, "schema": "OTHER"}, "0.62"):
        row = {"input_index": 0, "sport": "CFB", "market": "ML", "status": "NO_MODEL_OR_MARKET",
               "reason": "FAMILY_REGISTRY_NOT_VALIDATED", "research_estimate": forged}
        sel = build_phone_card(_card(row))["selections"][0]
        assert sel["status"] == "BLOCKED" and sel["probability"] is None


def test_no_engine_and_illinois_never_carry_estimate():
    assert build_research_estimate(0.5, engine="x", blocker="NO_ENGINE: no paths") is None
    assert build_research_estimate(0.5, engine="x", blocker="ILLINOIS_COLLEGE_EXCLUDED") is None
    est = build_research_estimate(0.5, engine="x", blocker="FAMILY_REGISTRY_NOT_VALIDATED")
    for blocker in ("ILLINOIS_COLLEGE_EXCLUDED", "NO_ENGINE"):
        row = {"input_index": 0, "sport": "CFB", "market": "ML", "status": "NO_MODEL_OR_MARKET",
               "reason": blocker + ": x", "blocker": blocker, "research_estimate": est}
        assert build_phone_card(_card(row))["selections"][0]["status"] == "BLOCKED"
