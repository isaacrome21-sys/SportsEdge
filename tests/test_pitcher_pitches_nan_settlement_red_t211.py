"""RED (t211u): PITCHER_PITCHES settlement refuses non-finite/non-real lines
(a NaN line previously settled every UNDER as WIN)."""
import math

import pytest

from sportsedge.mlb_family_registry_v2 import settle_pitcher_pitches


@pytest.mark.parametrize("line", [math.nan, math.inf, -math.inf, None, "92.5", True])
@pytest.mark.parametrize("side", ["OVER", "UNDER"])
def test_nonfinite_line_refused(line, side):
    with pytest.raises(ValueError, match="PITCHER_PITCHES_LINE_INVALID"):
        settle_pitcher_pitches({"numberOfPitches": 90}, line, side)


def test_finite_line_still_settles():
    assert settle_pitcher_pitches({"numberOfPitches": 90}, 92.5, "UNDER") == "WIN"
