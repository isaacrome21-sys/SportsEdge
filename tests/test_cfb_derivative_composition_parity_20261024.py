"""t272 audit fix: team-half / team-total and coverage markets must compose
CFB means through the canonical engine composition (free_models._base_means),
never the legacy base + hfa/2 + rating shortcut (91-point totals)."""
from datetime import datetime, timedelta, timezone

import pytest

from artifacts import free_models as engine
from sportsedge import market_coverage as mc
from sportsedge import team_half_pricing as th

NOW = datetime(2026, 10, 24, 3, tzinfo=timezone.utc)
START = NOW + timedelta(days=1)
NOTES = ["HOME_HISTORY_COUNT:5", "AWAY_HISTORY_COUNT:5",
         "HOME_INJURIES:HEURISTIC_OUT_DOUBTFUL_REPORTED_0",
         "AWAY_INJURIES:HEURISTIC_OUT_DOUBTFUL_REPORTED_0",
         "WEATHER:INDOOR_VERIFIED"]


def _ctx():
    c = {k: 0.0 for k in engine.CONTEXT_KEYS["CFB"]}
    c.update(home_rating=20.0, away_rating=-12.0,
             home_total_rating=55.0, away_total_rating=54.0)
    return c


class _Prov:
    receipts = []

    def identify(self, sport, name):
        return {"id": "9" + str(len(name))}

    def fixture(self, sport, away, home, start):
        return START, {"id": "e1"}


def _expected():
    return engine.score_means("CFB", _ctx())


def test_team_half_scoring_uses_engine_composition(monkeypatch):
    monkeypatch.setattr(engine, "context_for",
                        lambda *a, **k: (_ctx(), START, list(NOTES)))
    hm, am, *_ = th._scoring("CFB", "Home U", "Away St", START.isoformat(), NOW, _Prov())
    eh, ea = _expected()
    assert (hm, am) == pytest.approx((eh, ea))
    assert hm + am < 70  # legacy shortcut gave ~ 54 + 20 - 12 + ... far off


def test_market_coverage_base_means_uses_engine_composition(monkeypatch):
    monkeypatch.setattr(mc, "context_for",
                        lambda *a, **k: (_ctx(), START, list(NOTES)))
    out = mc._base_means({"sport": "CFB", "home": "Home U", "away": "Away St",
                          "kickoff": START.isoformat()}, now=NOW, provider=_Prov())
    eh, ea = _expected()
    assert (out["home_mean"], out["away_mean"]) == pytest.approx((eh, ea))
