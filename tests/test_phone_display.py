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


@pytest.mark.parametrize("freshness", [
    {"code": "QUOTE_STALE_OVER_180S", "age_seconds": 900},
    {"code": "QUOTE_TIMESTAMP_INVALID", "age_seconds": None},
    {"code": "QUOTE_TIMESTAMP_IN_FUTURE", "age_seconds": -60},
    {"code": "QUOTE_FRESHNESS_UNVERIFIED", "age_seconds": None},
    {},
])
def test_explicit_nonfresh_evidence_preserves_submitted_price_metrics(freshness):
    row = result(quote_status="RECENT_CAPTURED_QUOTE",
                 quote_freshness=freshness)
    displayed = build_phone_card(card(row))["selections"][0]
    assert displayed["status"] == "REFRESH REQUIRED"
    assert displayed["probability"] == row["model_probability"]
    assert displayed["estimated_ev"] == row["ev_per_dollar"]


def test_market_anchored_provenance_marker_alone_suppresses_metrics():
    row = result(pricing_provenance={"lane": "MARKET_ANCHORED",
                                    "mechanism": "MARKET_SHRINK_15PCT"},
                 pricing_lane=None)
    displayed = build_phone_card(card(row))["selections"][0]
    assert displayed["status"] == "WATCH"
    assert displayed["probability"] is None
    assert displayed["estimated_ev"] is None
    assert displayed["fair_odds"] is None


def test_undetermined_provenance_fails_closed_despite_positive_ev():
    row = result(pricing_provenance={"lane": "UNDETERMINED",
                                    "source": "NO_PROVENANCE_MARKERS_ON_PRICED_ROW"})
    displayed = build_phone_card(card(row))["selections"][0]
    assert displayed["status"] == "BLOCKED"
    assert displayed["reason"] == "PROVENANCE_UNDETERMINED"
    assert displayed["probability"] is None
    assert displayed["estimated_ev"] is None


@pytest.mark.parametrize("provenance", [
    {"lane": "UNKNOWN_NEW_LANE"}, {"lane": None}, "MARKET_ANCHORED",
])
def test_unknown_or_malformed_pricing_provenance_fails_closed(provenance):
    row = result(pricing_provenance=provenance)
    displayed = build_phone_card(card(row))["selections"][0]
    assert displayed["status"] == "BLOCKED"
    assert displayed["reason"] == "PROVENANCE_UNDETERMINED"
    assert displayed["estimated_ev"] is None


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


@pytest.mark.registry_lane_internals
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


def test_large_board_pages_keep_every_selection_under_comment_limit():
    from sportsedge.phone_display import phone_card_pages
    c = card(*(result(player_name=f"UniquePlayer{i}") for i in range(2000)))
    pages = phone_card_pages(render_phone_card(c))
    assert len(pages) > 1
    assert all(len(page.encode("utf-8")) < 55000 for page in pages)
    joined = "".join(pages)
    assert joined.count("| LEAN |") == 2000
    assert all(f"UniquePlayer{i} " in joined for i in range(2000))
    assert all("| Selection / market |" in page for page in pages[:-1])


def test_utf8_page_limits_count_bytes_not_characters():
    from sportsedge.phone_display import phone_card_pages
    text = "".join("| " + "球" * 100 + " |\n" for _ in range(100))
    pages = phone_card_pages(text, max_bytes=2000)
    assert all(len(page.encode("utf-8")) < 2000 for page in pages)
    assert "".join(pages).count("球") == 10000


@pytest.mark.parametrize("malformed", [True, 7, "bad", [], [1]])
def test_malformed_independent_projection_blocks_row_without_crashing(malformed):
    c = card(result(independent_projection=malformed), result())
    view = build_phone_card(c)
    assert view["coverage"]["input_rows"] == 2
    assert view["selections"][0]["status"] == "BLOCKED"
    assert view["selections"][0]["estimated_ev"] is None
    assert view["selections"][1]["status"] == "LEAN"


def test_malformed_context_notes_cannot_produce_eligible_status_or_crash():
    display = build_phone_card(card(result(context_notes=42)))["selections"][0]
    assert display["status"] == "WATCH"
    assert display["reason"] == "CONTEXT_METADATA_MALFORMED"


def test_untrusted_intake_row_is_refused_before_any_card_output():
    c = card(result())
    c["selection_intake"] = [42]
    with pytest.raises(ValueError, match="SELECTION_INTAKE_ROW_NOT_OBJECT"):
        build_phone_card(c)
