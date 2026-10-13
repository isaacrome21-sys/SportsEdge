from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from sportsedge.phone_display import build_phone_card, identity_rows, render_phone_card
from sportsedge.quote_freshness import QUOTE_FRESH


def result(**changes):
    row = {"status": "RESEARCH_CANDIDATE_NOT_VALIDATED", "sport": "MLB",
           "game": "A @ B", "market": "PITCHER_K", "selection": "OVER",
           "player_name": "Pitcher", "line": 5.5, "dk_odds": -110,
           "model_probability": .6, "ev_per_dollar": .145,
           "quote_status": "RECENT_CAPTURED_QUOTE"}
    row.update(changes)
    return row


def card(*rows):
    return {"evaluated_rows": list(rows), "summary": {"rows": len(rows)},
            "min_ev": .02, "as_of_utc": "2026-10-13T10:00:00Z"}


@pytest.mark.parametrize("changes, expected", [
    ({}, "LEAN"),
    ({"ev_per_dollar": -.01}, "PASS"),
    ({"ev_per_dollar": .01}, "WATCH"),
    ({"dk_odds": -170}, "WATCH"),
    ({"quote_status": "STALE_QUOTE"}, "REFRESH REQUIRED"),
    ({"quote_status": "UNVERIFIED_QUOTE_FRESHNESS"}, "REFRESH REQUIRED"),
    ({"status": "NO_MODEL_OR_MARKET"}, "BLOCKED"),
    ({"status": "WATCH_NFL_TOTAL_PRIOR_ONLY"}, "WATCH"),
    ({"status": "PLAY", "validated_vs_close": True}, "WATCH"),
    ({"model_probability": float("nan")}, "BLOCKED"),
    ({"ev_per_dollar": float("inf")}, "BLOCKED"),
    ({"model_probability": 1.1}, "BLOCKED"),
    ({"model_probability": True}, "BLOCKED"),
    ({"dk_odds": None}, "BLOCKED"),
])
def test_dispositions_do_not_promote_missing_evidence(changes, expected):
    view = build_phone_card(card(result(**changes)))
    assert view["selections"][0]["status"] == expected


def test_no_research_labels_no_mutation_and_no_silent_row_limit():
    original = card(*(result(player_name=f"Pitcher {i}") for i in range(194)))
    saved = deepcopy(original)
    rendered = render_phone_card(original)
    assert "research" not in rendered.lower()
    assert "hypothetical" not in rendered.lower()
    assert "Pitcher 193" in rendered
    assert rendered.count("| LEAN |") == 194
    assert "Model verification pending" in rendered
    assert original == saved
    view = build_phone_card(original)
    assert view["coverage"]["input_rows"] == 194
    assert view["coverage"]["distinct_market_families"] == 1
    assert view["coverage"]["dk_catalog_complete"] is False


def test_exclusive_family_counts_and_unknown_dimensions():
    c = card(result(), result(quote_status="STALE_QUOTE"),
             result(status="NO_ENGINE"), result(status="BLOCKED_INVALID"))
    counts = build_phone_card(c)["coverage"]["families"][0]
    assert [counts[k] for k in ("priced", "stale", "blocked", "rejected", "rows")] == [1, 1, 1, 1, 4]
    assert counts["period"] == counts["settlement_type"] == "UNSPECIFIED"


def test_period_alternate_live_and_settlement_not_collapsed():
    c = card(*(result() for _ in range(5)))
    c["selection_intake"] = [{}, {"period": "FIRST_5"}, {"alternate": True},
                              {"phase": "LIVE"}, {"settlement_type": "THREE_WAY"}]
    coverage = build_phone_card(c)["coverage"]
    assert coverage["distinct_market_families"] == 1
    assert coverage["distinct_market_variants"] == 5


def test_intake_identity_cannot_supply_probability_or_validation():
    raw = {"sport": "CFB", "away": "A", "home": "B", "side": "OVER",
           "market": "NEW_DK_MARKET", "estimate_p": .99, "status": "PLAY",
           "validated_vs_close": True}
    c = card({"status": "NO_MODEL_OR_MARKET"})
    c["selection_intake"] = identity_rows([raw])
    row = build_phone_card(c)["selections"][0]
    assert row["game"] == "A @ B" and row["market"] == "NEW_DK_MARKET"
    assert row["status"] == "BLOCKED" and row["probability"] is None
    assert "estimate_p" not in c["selection_intake"][0]


def test_anchored_lane_never_displays_independent_ev_as_its_own():
    row = result(pricing_lane="LANE_B_ANCHORED",
                 independent_projection={"estimate_p": .9, "ev_per_dollar": .8})
    public = build_phone_card(card(row))["selections"][0]
    assert public["status"] == "WATCH"
    assert public["probability"] is None and public["estimated_ev"] is None


def test_unpaired_game_cannot_become_a_lean():
    row = result(independent_projection={"estimate_p": .7, "ev_per_dollar": .2,
                                         "paired_market_status": "MISSING_EXACT_OPPOSITE_DK_PRICE"})
    assert build_phone_card(card(row))["selections"][0]["status"] == "WATCH"


def test_missing_rows_and_bad_order_are_not_hidden():
    with pytest.raises(ValueError, match="COMPLETE_EVALUATED_ROWS"):
        build_phone_card({"edges": [result()]})
    c = card(result()); c["summary"]["rows"] = 2
    with pytest.raises(ValueError, match="COUNT_MISMATCH"):
        build_phone_card(c)
    with pytest.raises(ValueError, match="ORDER_MISMATCH"):
        build_phone_card(card(result(input_index=4)))


def test_canonical_runner_embeds_complete_identity_and_display():
    from artifacts.run_it_full import run_full
    payload = {"sport": "CBB", "lines": [{"away": "A", "home": "B",
               "market": "NEW_DK_MARKET", "side": "OVER", "line": 2.5,
               "odds": -110, "estimate_p": .99}]}
    output = run_full(payload, now=datetime(2026, 10, 13, tzinfo=timezone.utc), auto_context=False)
    assert output["phone_card"]["coverage"]["input_rows"] == 1
    assert output["phone_card"]["selections"][0]["status"] == "BLOCKED"
    assert output["selection_intake"][0]["sport"] == "CBB"


def test_default_cli_uses_complete_plain_phone_card(tmp_path):
    from scripts.free_models_phone_issue import main
    source = tmp_path / "card.json"; source.write_text(json.dumps(card(result())))
    event = tmp_path / "event.json"; event.write_text('{"issue": {}}')
    output = tmp_path / "phone.md"
    main(["--mode", "render", "--event-json", str(event), "--card", str(source), "--output", str(output)])
    text = output.read_text()
    assert "research" not in text.lower() and "| LEAN |" in text


def test_intake_accepts_full_board_and_cbb_without_claiming_engine_support():
    from scripts.free_models_phone_issue import parse_issue
    lines = [{"sport": "CBB", "market": "TOTAL", "side": "OVER", "odds": -110} for _ in range(194)]
    parsed = parse_issue({"issue": {"title": "[FREE RUN IT] full board", "body": json.dumps({"lines": lines})}})
    assert len(parsed["lines"]) == 194


def test_unconfirmed_lineup_remains_watch():
    row = result(lineup_status="PUBLIC_BOXSCORE_LINEUP_NOT_VERIFIED")
    assert build_phone_card(card(row))["selections"][0]["status"] == "WATCH"


def test_canonical_pitcher_family_routes_are_exercised_without_network():
    # Known-input route test, NOT a historical model-quality evaluation.
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("pitcher_fixture", Path(__file__).with_name("test_mlb_phone_pitcher_real_public_history.py"))
    fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
    markets = ("PITCHER_K", "PITCHER_OUTS", "PITCHER_HITS_ALLOWED", "PITCHER_BB", "PITCHER_ER", "PITCHER_HITS_WALKS_ER")
    lines = [fixture.prop(market=market, side=side) for market in markets for side in ("OVER", "UNDER")]
    c = fixture.full(lines)
    assert len(c["evaluated_rows"]) == 12
    assert all(r.get("model_probability") is not None for r in c["evaluated_rows"])
    assert c["phone_card"]["coverage"]["distinct_market_families"] == 6
    assert sum(r["priced"] for r in c["phone_card"]["coverage"]["families"]) == 12


def test_no_fetch_league_prior_cannot_be_a_lean():
    row = result(context_notes=["NO_FETCH_MANUAL_MODE_NO_PUBLIC_CONTEXT"])
    assert build_phone_card(card(row))["selections"][0]["status"] == "WATCH"
