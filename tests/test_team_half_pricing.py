"""Offline tests for team-total / first-half pricing (sportsedge/team_half_pricing.py).

Pins the declared (not fitted) 0.50 first-half scale, the runner routing for
TEAM_TOTAL / TOTAL_1H / SPREAD_1H / ML_1H, and the fail-closed gates:
unverified fixture, unmatched identity, started games, bad lines, unsupported
markets. No network calls; PublicContext is faked where the pricer is tested
directly, and the runner is exercised in no-fetch mode.
Research-only semantics are asserted throughout.
"""
from datetime import datetime, timezone

from artifacts.free_models import model_probability
from artifacts import run_it_full as runner
from sportsedge import team_half_pricing as th

NOW = datetime(2026, 10, 11, 17, 0, tzinfo=timezone.utc)
KICKOFF = "2026-10-18T20:25:00Z"


class _FakeCtx:
    def __init__(self, now, getter=None, fixture_ok=True, identify_ok=True):
        self._fixture_ok = fixture_ok
        self._identify_ok = identify_ok

    def fixture(self, sport, away, home, kickoff):
        return {"away": away, "home": home} if self._fixture_ok else None

    def identify(self, sport, name):
        return name.upper().replace(" ", "_") if self._identify_ok else None

    def schedule(self, sport, team, kickoff):
        return []  # no history -> zero margin proxy


def _row(**kw):
    base = {"sport": "NFL", "market": "TOTAL_1H", "side": "OVER", "line": 21.5,
            "away": "Baltimore Ravens", "home": "Atlanta Falcons",
            "kickoff": KICKOFF, "odds": -110}
    base.update(kw)
    return base


def _price(monkeypatch, row, **ctxkw):
    monkeypatch.setattr(th, "PublicContext",
                        lambda now, getter=None: _FakeCtx(now, getter, **ctxkw))
    return th.price_team_or_half(row, now=NOW)


def test_half_scale_is_declared_0_50(monkeypatch):
    # NFL PRIORS: base 22.0, hfa 1.5 -> home 22.75 / away 21.25 with no history.
    out = _price(monkeypatch, _row())
    assert out["status"] == "PRICED_RESEARCH"
    assert out["home_mean"] == 22.75
    assert out["away_mean"] == 21.25
    exp_p, exp_push = model_probability(
        "NFL", "TOTAL", "OVER", 21.5, 22.75 * 0.50, 21.25 * 0.50)
    assert out["estimate_p"] == exp_p
    assert out["push_p"] == exp_push
    assert out["research_only"] is True
    assert out["official_authority"] is False
    assert out["model_p_authority"] is False
    assert out["staking_authority"] is False


def test_half_scale_declaration_is_explicit():
    doc = (th.__doc__ or "").lower()
    assert "0.50" in (th.__doc__ or "")
    assert "not a fitted" in doc
    assert "declared" in doc


def test_spread_and_ml_first_half_use_half_scale(monkeypatch):
    for market, mkt in (("SPREAD_1H", "SPREAD"), ("ML_1H", "ML")):
        row = _row(market=market, side="HOME" if market == "ML_1H" else "HOME -3.5",
                   line=None if market == "ML_1H" else 3.5)
        out = _price(monkeypatch, row)
        assert out["status"] == "PRICED_RESEARCH", (market, out)
        exp_p, exp_push = model_probability(
            "NFL", mkt, out["selection"],
            None if market == "ML_1H" else 3.5, 22.75 * 0.50, 21.25 * 0.50)
        assert out["estimate_p"] == exp_p


def test_team_total_resolves_home_and_away(monkeypatch):
    home = _price(monkeypatch, _row(market="TEAM_TOTAL", team="HOME", line=13.5))
    away = _price(monkeypatch, _row(market="TEAM_TOTAL", team="AWAY", line=10.5))
    assert home["status"] == "PRICED_RESEARCH"
    assert away["status"] == "PRICED_RESEARCH"
    assert home["estimate_p"] != away["estimate_p"]  # priced off different means
    bad = _price(monkeypatch, _row(market="TEAM_TOTAL", team="BOGUS", line=13.5))
    assert bad["status"] == "NO_MODEL_OR_MARKET"
    assert bad["reason"] == "TEAM_TOTAL_TEAM_UNRESOLVED"


def test_missing_identity_fail_closed(monkeypatch):
    out = _price(monkeypatch, _row(sport="XXX"))
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "IDENTITY_OR_SPORT_MISSING"
    out = _price(monkeypatch, _row(away=""))
    assert out["reason"] == "IDENTITY_OR_SPORT_MISSING"


def test_started_game_blocked(monkeypatch):
    out = _price(monkeypatch, _row(kickoff="2026-10-01T20:25:00Z"))
    assert out["status"] == "BLOCKED_STARTED"


def test_fixture_unverified_fail_closed(monkeypatch):
    out = _price(monkeypatch, _row(), fixture_ok=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "FREE_CONTEXT_FIXTURE_NOT_VERIFIED"


def test_identity_unmatched_fail_closed(monkeypatch):
    out = _price(monkeypatch, _row(), identify_ok=False)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "TEAM_IDENTITY_UNMATCHED"


def test_bad_line_fail_closed(monkeypatch):
    out = _price(monkeypatch, _row(line="abc"))
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "LINE_UNVERIFIED"


def test_unsupported_market_fail_closed(monkeypatch):
    out = _price(monkeypatch, _row(market="TOTAL_2H"))
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "UNSUPPORTED_TEAM_HALF_MARKET"


def test_implausible_means_fail_closed(monkeypatch):
    monkeypatch.setattr(th, "PRIORS", {"NFL": (0.1, 13.5, 13.7, 0.0)})
    out = _price(monkeypatch, _row())
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "IMPLAUSIBLE_SCORE_MEAN"


def test_runner_routes_team_half_to_pricer_no_fetch():
    # No-fetch mode: the real PublicContext cannot verify a fixture, so the
    # pricer must fail closed with FREE_CONTEXT_FIXTURE_NOT_VERIFIED --
    # proving the rows reached the team-half pricer instead of the router's
    # NO_VERIFIED_MODEL_FOR_THIS_MARKET block.
    rows = [
        _row(market="TEAM_TOTAL", team="HOME", line=13.5),
        _row(market="TOTAL_1H", line=21.5),
        _row(market="SPREAD_1H", side="HOME -3.5", line=3.5),
        _row(market="ML_1H", side="HOME", line=None),
        _row(market="FIRST_HALF_TOTAL", line=21.5),  # alias -> TOTAL_1H
    ]
    card = runner.run_full({"lines": rows}, now=NOW,
                           getter=lambda url: None, auto_context=False)
    by_market = {r["market"]: r for r in card["evaluated_rows"]}
    assert by_market["TOTAL_1H"]["market"] == "TOTAL_1H"
    assert sum(1 for r in card["evaluated_rows"] if r["market"] == "TOTAL_1H") == 2  # alias normalized
    for r in card["evaluated_rows"]:
        assert r["status"] == "NO_MODEL_OR_MARKET", r
        assert r["reason"] == "FREE_CONTEXT_FIXTURE_NOT_VERIFIED", r
    assert card["prop_model_status"]["team_half_engine"] == \
        "FREE_MODELS_MEANS_DECLARED_HALF_SCALE_UNVALIDATED"
    assert card["runner"].endswith("_TEAM_HALF_V1")
    for entry in card["factor_coverage"]["by_input_index"]:
        pp = entry["factors"]["player_props"]
        assert pp["status"] == "NO_MODEL_OR_MARKET", entry
        assert pp["detail"] == "FREE_CONTEXT_FIXTURE_NOT_VERIFIED", entry
