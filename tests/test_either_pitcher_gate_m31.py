"""RED: after M31 (dependence measured ~0; either-error comes from the
single-pitcher marginals' tail shape) the gate must name the marginal
defect, not unmeasured dependence. Label-only: pricing stays refused."""
from datetime import datetime, timezone

import pytest

NOW = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)
MARKETS = ("EITHER_PITCHER_HITS_ALLOWED", "EITHER_PITCHER_BB", "EITHER_PITCHER_ER")
NEW = "EITHER_PITCHER_MARGINAL_TAIL_ERROR"
OLD = "EITHER_PITCHER_DEPENDENCE_UNMEASURED"


def _run(market):
    from artifacts.run_it_full import run_full
    row = {"sport": "MLB", "away": "Los Angeles Dodgers", "home": "Milwaukee Brewers",
           "kickoff": "2026-10-11T19:00:00-05:00", "book": "draftkings",
           "quote_captured_at": "2026-10-11T20:00:00Z", "market": market,
           "side": "OVER", "line": 5.5, "odds": -110, "player": "Either Pitcher"}
    return run_full({"lines": [row], "sport": "MLB"}, now=NOW, auto_context=False)["evaluated_rows"][0]


@pytest.mark.parametrize("market", MARKETS)
def test_gate_names_marginal_defect(market):
    r = _run(market)
    assert r["reason"].startswith(f"NO_ENGINE: {NEW}")
    assert OLD not in r["reason"]
    assert r.get("model_probability") is None and r.get("ev") is None


@pytest.mark.parametrize("market", MARKETS)
def test_detail_cites_m31_evidence(market):
    from sportsedge.canonical_coverage import MARKET_RESOLUTIONS
    d = MARKET_RESOLUTIONS[("MLB", market)]
    assert d["state"] == "BLOCKED" and d["validation_status"] == "NOT_RUN"
    assert "M31" in d["detail"] and "DEPENDENCE_MEASURED" in d["detail"]
    assert "5e0eb543" in d["detail"]
    assert OLD not in d["detail"] and OLD not in d.get("engine", "")
