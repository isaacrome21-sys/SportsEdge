from datetime import datetime, timezone

import pytest

from scripts import research_mlb_pitcher_prop_promotion as R
from sportsedge.mlb_lineup_k_context import adjusted_values
from sportsedge.mlb_opp_k_context_research import K_THRESH, adjusted_mass_over, posterior_over
from sportsedge import mlb_umpire_context_research as U
from sportsedge.pitcher_joint_engine import price_pitcher_market


def _quote(side, odds, *, captured, line=5.5, market="PITCHER_K"):
    return {
        "provider_event_id": "evt1",
        "market": market,
        "entity_name": "Test Pitcher",
        "entity_name_normalized": "testpitcher",
        "side": side,
        "line": line,
        "american_odds": odds,
        "book_key": "draftkings_direct",
        "pit_eligible": True,
        "is_alternate": False,
        "quote_retrieved_at": captured,
        "first_pitch_at": "2026-10-04T23:00:00+00:00",
        "event_name": "Chicago Cubs @ Milwaukee Brewers",
    }


def _payload(captured, quotes):
    return {
        "archive_type": "MLB_PROP_PIT_QUOTES",
        "provider": "DRAFTKINGS_WEB_RESEARCH",
        "captured_at": captured,
        "quotes": quotes,
    }


def test_price_helpers_and_devig():
    assert R.american_to_decimal(100) == pytest.approx(2.0)
    assert R.american_to_decimal(-110) == pytest.approx(1 + 100 / 110)
    assert R.fair_over_probability(-110, -110) == pytest.approx(0.5)
    assert R.is_half_line(5.5)
    assert not R.is_half_line(5.0)


def test_select_units_keeps_last_snapshot_that_is_actually_two_sided():
    p1 = _payload("2026-10-04T20:00:00+00:00", [
        _quote("OVER", -110, captured="2026-10-04T20:00:00+00:00"),
        _quote("UNDER", -110, captured="2026-10-04T20:00:00+00:00"),
    ])
    p2 = _payload("2026-10-04T21:00:00+00:00", [
        _quote("OVER", -105, captured="2026-10-04T21:00:00+00:00"),
    ])
    units, _ = R.select_units([p1, p2])
    assert len(units) == 1
    assert units[0]["over_odds"] == -110

    p3 = _payload("2026-10-04T22:00:00+00:00", [
        _quote("OVER", 105, captured="2026-10-04T22:00:00+00:00", line=6.5),
        _quote("UNDER", -125, captured="2026-10-04T22:00:00+00:00", line=6.5),
    ])
    units, _ = R.select_units([p1, p2, p3])
    assert len(units) == 1
    assert units[0]["line"] == 6.5
    assert units[0]["over_odds"] == 105


def test_market_metrics_enforce_preregistered_thresholds():
    rows = []
    for pitcher in range(16):
        for j in range(10):
            y = 1 if j < 7 else 0
            rows.append({
                "pitcher_id": pitcher,
                "model_p_over": 0.70,
                "market_q_over": 0.50,
                "outcome_over": y,
                "ll_diff": R._ll(0.70, y) - R._ll(0.50, y),
                "brier_diff": (0.70 - y) ** 2 - (0.50 - y) ** 2,
                "flagged": {"won": bool(y), "ev": 0.40, "pnl": 1.0 if y else -1.0},
            })
    out = R.market_metrics(rows)
    assert out["units"] == 160
    assert out["flagged_bets"] == 160
    assert out["delta_log_loss"]["hi"] < 0
    assert out["flagged_roi"]["lo"] > 0
    assert out["passes_promotion_rule"] is True


def _history(ks, bbs):
    return [
        {"strikeouts": k, "outs": 18, "earned_runs": 2, "hits_allowed": 5, "walks_allowed": bb}
        for k, bb in zip(ks, bbs)
    ]


def test_pitcher_k_engine_matches_frozen_research_math_with_lineup_layer():
    history = _history([4, 5, 6, 7, 8], [1, 2, 2, 3, 1])
    adj = {
        "market": "PITCHER_K",
        "beta": 1.0,
        "target_rel": 1.08,
        "history_rel": [0.94, 0.98, 1.02, 1.04, 1.07],
        "lineup_k_adjustment": {
            "W": 200.0,
            "gamma": 0.5,
            "target_deviation": 1.06,
            "history_deviation": [0.96, 0.99, 1.01, 1.03, 1.05],
        },
    }
    line = 5.5
    got = price_pitcher_market({
        "game_id": "1", "market": "PITCHER_K", "entity_id": "9", "line": line, "side": "OVER",
        "features": {"history_pool": history, "opp_k_adjustment": adj},
    })["model_p"]
    xs = adjusted_values([row["strikeouts"] for row in history], adj)
    mass = adjusted_mass_over(xs)
    research = posterior_over(mass, float(len(history)))
    idx = next(i for i, threshold in enumerate(K_THRESH) if float(threshold) == line)
    assert got == pytest.approx(float(research[idx]), abs=1e-12, rel=0)


def test_pitcher_bb_engine_matches_frozen_research_math():
    history = _history([4, 5, 6, 7, 8], [1, 2, 2, 3, 1])
    adj = {
        "market": "PITCHER_BB",
        "W": 6000.0,
        "beta": 2.0,
        "target_rel": 1.05,
        "history_rel": [0.95, 0.98, 1.00, 1.02, 1.04],
    }
    line = 1.5
    got = price_pitcher_market({
        "game_id": "1", "market": "PITCHER_BB", "entity_id": "9", "line": line, "side": "OVER",
        "features": {"history_pool": history, "ump_bb_adjustment": adj},
    })["model_p"]
    xs = [
        min(max(row["walks_allowed"] * (adj["target_rel"] / h) ** adj["beta"], 0.0), 10.0)
        for row, h in zip(history, adj["history_rel"])
    ]
    mass = U.adjusted_mass_over(xs, "bb")
    research = U.posterior_over(mass, float(len(history)))
    idx = next(i for i, threshold in enumerate(U.THRESH["bb"]) if float(threshold) == line)
    assert got == pytest.approx(float(research[idx]), abs=1e-12, rel=0)


def _context_payload(ts, *, lineup="PRESENT", umpire="PRESENT"):
    rows = []
    if lineup == "PRESENT":
        for side, team in (("AWAY", 1), ("HOME", 2)):
            for slot in range(1, 10):
                rows.append({
                    "team_id": str(team), "player_id": str(team * 100 + slot),
                    "batting_order": slot, "starter_status": "CONFIRMED_STARTER",
                    "side": side, "retrieved_at": ts,
                })
    return {
        "game_id": "99",
        "retrieved_at": ts,
        "source_states": {"confirmed_lineup": lineup, "plate_umpire": umpire},
        "lineups": rows,
        "umpire": {
            "home_plate_umpire_id": 777 if umpire == "PRESENT" else None,
            "home_plate_umpire_name": "Test Ump" if umpire == "PRESENT" else None,
        },
    }


def test_choose_pit_context_never_uses_future_or_stale_snapshot():
    observed = datetime(2026, 10, 1, 23, 30, tzinfo=timezone.utc)
    fresh = _context_payload("2026-10-01T23:20:00+00:00")
    future = _context_payload("2026-10-01T23:31:00+00:00")
    stale = _context_payload("2026-10-01T23:00:00+00:00")
    got = R.choose_pit_context(
        [("stale", stale), ("fresh", fresh), ("future", future)], observed_at=observed
    )
    assert got["path"] == "fresh"
    assert R.choose_pit_context([("stale", stale), ("future", future)], observed_at=observed) is None


def test_pit_lineup_binding_uses_archived_current_order_only():
    payload = _context_payload("2026-10-01T23:20:00+00:00")
    proof = {"path": "ctx", "retrieved_at": payload["retrieved_at"], "payload": payload}
    class Source:
        def _lineup_boxscore(self, pk):
            return {"orders": {9: (901, 902)}}
    src = Source()
    R.bind_pit_context(src, game_pk=99, market="PITCHER_K", proof=proof)
    assert src._lineup_boxscore(99)["orders"][1] == tuple(range(101, 110))
    assert src._lineup_boxscore(12)["orders"] == {9: (901, 902)}


def test_pit_absent_context_forces_production_fallback():
    payload = _context_payload("2026-10-01T23:20:00+00:00", lineup="ABSENT", umpire="ABSENT")
    proof = {"path": "ctx", "retrieved_at": payload["retrieved_at"], "payload": payload}
    class Source:
        def _lineup_boxscore(self, pk):
            raise AssertionError("live current-game lineup must not be fetched")
        def plate_umpire(self, *, game_pk, target_date):
            raise AssertionError("live current-game umpire must not be fetched")
    k = Source()
    R.bind_pit_context(k, game_pk=99, market="PITCHER_K", proof=proof)
    assert k._lineup_boxscore(99) == {"orders": {}}
    bb = Source()
    R.bind_pit_context(bb, game_pk=99, market="PITCHER_BB", proof=proof)
    assert bb.plate_umpire(game_pk=99, target_date=datetime(2026, 10, 1).date()) is None


def test_pit_present_umpire_uses_archived_assignment():
    payload = _context_payload("2026-10-01T23:20:00+00:00")
    proof = {"path": "ctx", "retrieved_at": payload["retrieved_at"], "payload": payload}
    class Source:
        def plate_umpire(self, *, game_pk, target_date):
            return {"umpire_id": 999, "umpire_name": "Leaked Final"}
    src = Source()
    R.bind_pit_context(src, game_pk=99, market="PITCHER_BB", proof=proof)
    got = src.plate_umpire(game_pk=99, target_date=datetime(2026, 10, 1).date())
    assert got["umpire_id"] == 777
    assert got["umpire_name"] == "Test Ump"


def test_pit_context_path_regex_matches_real_archive_path():
    path = "runtime/mlb-context/runs/37267617765/2026-10-05/game_849834.json"
    match = R.CONTEXT_PATH_RE.match(path)
    assert match is not None
    assert match.group(1) == "849834"
