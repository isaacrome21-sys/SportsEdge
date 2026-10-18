"""Owner ruling Oct 17 2026 (#2384/#2385): NFL moneyline and spread are held
as diagnostic WATCH until a new side model beats closing lines. The 22-pt
prior compresses side probabilities toward even, which surfaced every
underdog as a large 'edge' in the composite acceptance run (#2383)."""
from artifacts.free_models import NFL_SIDE_WATCH_STATUS, run
from artifacts.run_it_full import run_full
from tests.test_prepricing_ingestion import FakeGetter, nfl_mapping, nfl_row, NOW


def side_rows():
    stamp = NOW.isoformat()
    return [
        nfl_row(market="ML", side="AWAY", odds=275, quote_captured_at=stamp),
        nfl_row(market="ML", side="HOME", odds=-340, quote_captured_at=stamp),
        nfl_row(market="SPREAD", side="AWAY", line=7.5, odds=-112, quote_captured_at=stamp),
        nfl_row(market="SPREAD", side="HOME", line=-7.5, odds=-108, quote_captured_at=stamp),
    ]


def _assert_held(card):
    assert card["evaluated_rows"]
    assert card["edges"] == []
    assert card["independent_candidates"] == []
    assert card["lane_b_edges"] == []
    for r in card["evaluated_rows"]:
        assert r["status"] == NFL_SIDE_WATCH_STATUS, r["status"]
        assert "ISSUE_2384" in r["reason"]
        assert r["research_only"] is True
        assert r["validated_profitability"] is False


def test_nfl_sides_never_surface_as_candidates():
    _assert_held(run({"lines": side_rows()}, now=NOW, getter=FakeGetter(nfl_mapping())))


def test_nfl_sides_held_on_canonical_run_full_path():
    _assert_held(run_full({"lines": side_rows()}, now=NOW, getter=FakeGetter(nfl_mapping())))


def test_nfl_sides_held_in_anchored_lane_too():
    card = run({"lines": side_rows()}, now=NOW, lane="B", getter=FakeGetter(nfl_mapping()))
    assert card["edges"] == [] and card["lane_b_edges"] == []
    priced = [r for r in card["evaluated_rows"] if r.get("market") == "SPREAD"]
    assert len(priced) == 2  # lane B prices the paired spreads
    assert {r["status"] for r in priced} == {NFL_SIDE_WATCH_STATUS}
