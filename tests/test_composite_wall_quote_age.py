from datetime import datetime, timezone
import pytest
from sportsedge.per_game_composite import run_composite, CompositeRefusal

@pytest.mark.parametrize("capture", ["2026-10-25T11:29:59Z", "2026-10-25T12:00:01Z", "2026-10-25T12:00:00"])
def test_bad_wall_capture_refuses_before_pricing(capture):
    row = dict(sport="NFL", away="Away", home="Home", kickoff="2026-10-25T18:00:00Z",
               market="TOTAL", side="OVER", line=45.5, odds=-110, quote_captured_at=capture)
    def must_not_run(*a, **k):
        raise AssertionError("pricing ran before wall quote refusal")
    with pytest.raises(CompositeRefusal, match="COMPOSITE_WALL_QUOTE_NOT_CURRENT"):
        run_composite({"lines":[row]}, now=datetime(2026,10,25,12,tzinfo=timezone.utc), run_full_fn=must_not_run)
    assert row["quote_captured_at"] == capture

@pytest.mark.parametrize("capture", ["2026-10-25T11:30:00Z", "2026-10-25T12:00:00Z"])
def test_current_and_exact_thirty_minutes_reach_pricing(capture):
    row = dict(sport="NFL", away="Away", home="Home", kickoff="2026-10-25T18:00:00Z",
               market="TOTAL", side="OVER", line=45.5, odds=-110, quote_captured_at=capture)
    def reached(*a, **k):
        assert k["as_of"] == capture.replace("Z", "+00:00")
        raise RuntimeError("PRICE_REACHED")
    with pytest.raises(RuntimeError, match="PRICE_REACHED"):
        run_composite({"lines":[row]}, now=datetime(2026,10,25,12,tzinfo=timezone.utc), run_full_fn=reached)
