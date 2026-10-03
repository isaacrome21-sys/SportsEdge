"""One thin-history market must not block the rest of an MLB game board.

Regression for the 2026-10-03 White Sox@Guardians card (#1457): an opener with a
single start raised ``pitcher:joint: insufficient chronological sample 1<5`` and
the whole game (ML, RL, total, YRFI, other starter's outs) was BLOCKED.
"""
from __future__ import annotations

import pytest

from sportsedge.canonical_manual_mlb import run_canonical_manual_mlb
from sportsedge.mlb_generic_features import MLBGenericFeatureError
from tests.test_mlb_pitcher_subject_bind import _game, _quote

NO_NET = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no network"))  # noqa: E731
THIN_STARTER = "641835"  # Tyler Mahle in the fixture game


def _moneyline() -> dict:
    row = _quote("MONEYLINE", "", 0.0, 124, -150)
    row.pop("subject_name")
    row.update({"side": "AWAY", "paired_side": "HOME"})
    return row


def _fake_feature_row(self, **kw):
    if kw.get("player_id") is not None and str(kw["player_id"]) == THIN_STARTER:
        raise MLBGenericFeatureError("pitcher:joint: insufficient chronological sample 1<5")
    return {"market": kw["market"], "entity_id": kw["entity_id"], "source": "TEST", "source_subset_hash": "x"}


def test_thin_starter_blocks_only_its_own_market(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_card(**kwargs):
        seen["quotes"] = list(kwargs["quotes"])
        seen["features"] = list(kwargs["feature_rows"])
        return []

    monkeypatch.setattr("sportsedge.canonical_manual_mlb.run_generic_card", fake_card)
    monkeypatch.setattr("sportsedge.canonical_manual_mlb.MLBAllMarketHistorySource.feature_row", _fake_feature_row)
    payload = run_canonical_manual_mlb(
        [
            _moneyline(),
            _quote("PITCHER_OUTS", "Cristopher Sanchez", 17.5, -174, 130),
            _quote("PITCHER_OUTS", "Tyler Mahle", 6.5, 112, -148),
        ],
        schedule=[_game()],
        opener=NO_NET,
    )
    priced_entities = {(q["market"], q["entity_id"]) for q in seen["quotes"]}
    assert ("PITCHER_OUTS", "661563") in priced_entities
    assert any(m == "MONEYLINE" for m, _ in priced_entities)
    assert not any(e == THIN_STARTER for _, e in priced_entities)

    blocked = [r for r in payload["results"] if r["bet_status"] == "BLOCKED"]
    assert len(blocked) == 2  # both sides of the thin starter's quote stay on the card
    assert {r["entity_id"] for r in blocked} == {THIN_STARTER}
    assert all(r["model_p"] is None for r in blocked)
    assert all(str(r["reason"]).startswith("FEATURE_UNAVAILABLE:pitcher:joint") for r in blocked)
    statuses = [m.get("resolution_status") for m in payload["market_resolution"]]
    assert statuses.count("BLOCKED") == 1


def test_all_markets_failing_returns_blocked_rows_not_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict = {"n": 0}

    def fake_card(**kwargs):
        calls["n"] += 1
        assert kwargs["quotes"] == []
        return []

    monkeypatch.setattr("sportsedge.canonical_manual_mlb.run_generic_card", fake_card)
    monkeypatch.setattr("sportsedge.canonical_manual_mlb.MLBAllMarketHistorySource.feature_row", _fake_feature_row)
    payload = run_canonical_manual_mlb(
        [_quote("PITCHER_OUTS", "Tyler Mahle", 6.5, 112, -148)], schedule=[_game()], opener=NO_NET,
    )
    assert payload["results"] and all(r["bet_status"] == "BLOCKED" and r["model_p"] is None for r in payload["results"])


def test_non_feature_errors_still_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self, **kw):
        raise RuntimeError("engine bug")

    monkeypatch.setattr("sportsedge.canonical_manual_mlb.run_generic_card", lambda **_k: [])
    monkeypatch.setattr("sportsedge.canonical_manual_mlb.MLBAllMarketHistorySource.feature_row", boom)
    with pytest.raises(RuntimeError):
        run_canonical_manual_mlb([_moneyline()], schedule=[_game()], opener=NO_NET)
