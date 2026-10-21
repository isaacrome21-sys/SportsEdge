"""NBA prop engines ("Build the engines", owner directive 2026-10-20).

Covers sportsedge.nba_prop_empirical (the Oct 17/18 calibration
construction, parity-reproduced in
research/nba_props_forward_20261020/parity_reproduction.py), the
REGISTERED_RESEARCH_ONLY registration of NBA PTS/REB/AST/PRA in
sportsedge.family_market_registry, the engine-sufficiency limb of
sportsedge.registry_gate, and the artifacts/run_it_full.py NBA prop
lane. Calibration is not validation: every family here stays
NOT_VALIDATED, eligible False, promotable False.
"""
import csv
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts"))

from sportsedge.family_market_registry import family_market_decision
from sportsedge.nba_phone_prop_pricing import phone_nba_prop_rows
from sportsedge.nba_prop_empirical import (
    ENGINE_ID, GameLogStore, MixtureDistribution, empirical_crps,
    records_from_boxscore_rows)
from sportsedge.registry_gate import (
    family_gate_row, gate_and_stamp, nba_engine_sufficiency_met,
    research_pricing_allowed)

D0 = date(2026, 10, 1)


def game(pid, name, pos, day, pts, reb=5, ast=5, minutes=30, gid=None):
    return {"player_id": pid, "player_name": name, "position": pos,
            "game_date": D0 + timedelta(days=day),
            "game_id": gid or f"g{pid}-{day}", "minutes": minutes,
            "points": pts, "rebounds": reb, "assists": ast}


def guard_history(n=12, pts=20):
    """One guard with n prior games, three more guards (so the
    position pool clears the 30-game floor) and a forward pool."""
    records = [game("p1", "Test Guard", "G", i, pts) for i in range(n)]
    for j in range(3):
        records += [game(f"g{j}", f"Guard {j}", "G", i, 18)
                    for i in range(12)]
        records += [game(f"f{j}", f"Fwd {j}", "F", i, 15)
                    for i in range(12)]
    return records


# ---------------------------------------------------------------- engine: PIT

def test_pit_same_day_and_future_games_never_enter_priors_or_pools():
    records = guard_history(12, pts=20)
    # A same-day 60-point game and a future 60-point game for the
    # priced player, plus same-day pool games: none may count.
    records.append(game("p1", "Test Guard", "G", 12, 60, gid="same-day"))
    records.append(game("p1", "Test Guard", "G", 20, 60, gid="future"))
    records.append(game("f0", "Fwd 0", "F", 12, 60, gid="pool-same-day"))
    store = GameLogStore(records)
    target = D0 + timedelta(days=12)
    assert len(store.player_prior_values("p1", "points", target)) == 12
    priced = store.price("p1", "points", 19.5, target)
    assert priced["status"] == "PRICED"
    assert priced["n_prior"] == 12
    # Every prior is 20, so the player component contributes 20; the
    # pool (all priors are 15 or 20) keeps the mean below 21. If the
    # 60-point games leaked in, the mean would jump.
    assert priced["model_mean"] < 21.0


def test_dnp_rows_enter_neither_priors_nor_pools():
    records = guard_history(12)
    records.append(game("p1", "Test Guard", "G", 3, 0, minutes=0,
                        gid="dnp"))
    records.append(game("f0", "Fwd 0", "F", 4, 99, minutes=0,
                        gid="pool-dnp"))
    store = GameLogStore(records)
    assert store.counters["excluded_dnp_minutes0"] == 2
    target = D0 + timedelta(days=12)
    assert len(store.player_prior_values("p1", "points", target)) == 12
    priced = store.price("p1", "points", 19.5, target)
    # The 99-point DNP pool row must not exist in any pool.
    assert priced["model_mean"] < 21.0


def test_sufficiency_refusal_at_nine_and_pricing_at_ten():
    store9 = GameLogStore(guard_history(9))
    refused = store9.price("p1", "points", 19.5, D0 + timedelta(days=30))
    assert refused["status"] == "REFUSED"
    assert refused["reason"] == "NBA_PROP_INSUFFICIENT_PRIOR_GAMES"
    assert refused["n_prior"] == 9
    store10 = GameLogStore(guard_history(10))
    priced = store10.price("p1", "points", 19.5, D0 + timedelta(days=30))
    assert priced["status"] == "PRICED"
    assert priced["sufficiency_met"] is True


def test_no_position_player_is_outside_the_universe():
    records = guard_history(12)
    records.append(game("px", "No Pos", None, 0, 30))
    records.append(game("py", "Bad Pos", "X", 0, 30))
    store = GameLogStore(records)
    assert store.counters["excluded_no_position"] == 2
    out = store.price("px", "points", 19.5, D0 + timedelta(days=30))
    assert out["status"] == "REFUSED"
    assert out["reason"] == "NBA_PROP_PLAYER_NOT_IN_STORE"


def test_pool_fallback_to_league_when_position_pool_thin():
    records = [game("p1", "Lone Guard", "G", i, 20) for i in range(10)]
    for j in range(3):
        records += [game(f"f{j}", f"Fwd {j}", "F", i, 15)
                    for i in range(12)]
    store = GameLogStore(records)
    priced = store.price("p1", "points", 19.5, D0 + timedelta(days=30))
    assert priced["status"] == "PRICED"
    assert priced["b1_fallback_to_b2"] is True
    assert priced["pool_source"] == "LEAGUE_FALLBACK"
    # Guard pool alone would be exactly the player's own 10 priors.
    priced2 = GameLogStore(guard_history(12)).price(
        "p1", "points", 19.5, D0 + timedelta(days=30))
    assert priced2["b1_fallback_to_b2"] is False
    assert priced2["pool_source"] == "POSITION_GROUP"


def test_probability_coherence_and_push_mass():
    store = GameLogStore(guard_history(12, pts=20))
    target = D0 + timedelta(days=30)
    half = store.price("p1", "points", 19.5, target)
    assert half["p_push"] == 0.0
    assert abs(half["p_over"] + half["p_under"] - 1.0) < 1e-12
    whole = store.price("p1", "points", 20, target)
    assert whole["p_push"] > 0.0
    total = whole["p_over"] + whole["p_push"] + whole["p_under"]
    assert abs(total - 1.0) < 1e-12


def test_pra_is_the_summed_per_game_distribution():
    # Components correlated within the game: big games are big in
    # all three stats together — (30,10,10)=50 and (10,2,2)=14
    # alternate. The summed empirical is {50 x6, 14 x6}. An
    # independence convolution of the marginals would spread mass
    # over {50,42,42,34,30,22,22,14} and price over-39.5 at 3/8 of
    # the player component instead of the summed 1/2.
    records = []
    for i in range(12):
        if i % 2 == 0:
            records.append(game("p1", "Combo", "F", i, 30, reb=10,
                                ast=10))
        else:
            records.append(game("p1", "Combo", "F", i, 10, reb=2,
                                ast=2))
    for j in range(3):
        records += [game(f"g{j}", f"F {j}", "F", i, 10, reb=2, ast=2)
                    for i in range(12)]
    store = GameLogStore(records)
    target = D0 + timedelta(days=30)
    priced = store.price("p1", "pra", 39.5, target)
    assert priced["status"] == "PRICED"
    assert priced["pool_source"] == "POSITION_GROUP"
    # The position pool includes the player's own priors (as in the
    # calibration programs): 48 pool values, six of them 50. The
    # mixture's p_over is the weighted sum of the summed fractions.
    w_player = 12 / 17.0
    expected = w_player * 0.5 + (1 - w_player) * (6 / 48.0)
    assert abs(priced["p_over"] - expected) < 1e-12
    independence_over = w_player * (3 / 8.0) + (1 - w_player) * (6 / 48.0)
    assert abs(priced["p_over"] - independence_over) > 0.05
    # Linearity through the identical mixture: mean(PRA) equals the
    # sum of the three component means, exactly.
    means = sum(store.price("p1", s, 0.5, target)["model_mean"]
                for s in ("points", "rebounds", "assists"))
    assert abs(priced["model_mean"] - means) < 1e-9


def test_mixture_crps_matches_brute_force():
    import random
    rng = random.Random(11)
    for _ in range(60):
        player = [rng.randint(0, 40) for _ in range(rng.randint(1, 9))]
        pool = [rng.randint(0, 40) for _ in range(rng.randint(1, 15))]
        mix = MixtureDistribution(player, pool)
        y = rng.randint(0, 40)
        # Brute force over the mixture's discrete support.
        support = {}
        wp = len(player) / (len(player) + 5.0)
        for v in player:
            support[v] = support.get(v, 0.0) + wp / len(player)
        for v in pool:
            support[v] = support.get(v, 0.0) + (1 - wp) / len(pool)
        items = sorted(support.items())
        ex_abs = sum(w * abs(v - y) for v, w in items)
        exx = sum(w1 * w2 * abs(v1 - v2)
                  for v1, w1 in items for v2, w2 in items)
        brute = ex_abs - 0.5 * exx
        assert abs(mix.crps(y) - brute) < 1e-9


def test_empirical_crps_known_value():
    # Degenerate distribution at 10, observation 14 -> CRPS = 4.
    from sportsedge.nba_prop_empirical import _sorted_prefix
    sv, prefix = _sorted_prefix([10.0, 10.0, 10.0])
    assert empirical_crps(sv, prefix, 14.0) == 4.0


def test_records_from_boxscore_rows_pull_shape():
    rows = [
        {"PLAYER_ID": "1", "PLAYER_NAME": "A", "GAME_ID": "g1",
         "MIN": "30", "PTS": "20", "REB": "5", "AST": "5"},
        {"PLAYER_ID": "1", "PLAYER_NAME": "A", "GAME_ID": "g2",
         "MIN": "0", "PTS": "0", "REB": "0", "AST": "0"},
        {"PLAYER_ID": "1", "PLAYER_NAME": "A", "GAME_ID": "g3",
         "MIN": "28", "PTS": "22", "REB": "6", "AST": "4"},
        {"PLAYER_ID": "2", "PLAYER_NAME": "B", "GAME_ID": "g1",
         "MIN": "30", "PTS": "10", "REB": "5", "AST": "5"},
    ]
    records = records_from_boxscore_rows(
        rows, {"g1": "2026-10-01", "g2": "2026-10-03"},
        {"1": "G-F", "2": "F"})
    store = GameLogStore(records)
    # g3 has no date (undated -> dropped); g2 is a DNP (dropped).
    assert store.counters["records_kept"] == 2
    assert store.counters["excluded_no_date"] == 1
    assert store.counters["excluded_dnp_minutes0"] == 1
    assert store.position_group_of("1") == "Guard"


# ------------------------------------------------------------------ registry

REGISTERED = [("PLAYER_POINTS", "player_points"),
              ("PTS", "player_points"),
              ("PLAYER_REBOUNDS", "player_rebounds"),
              ("PLAYER_ASSISTS", "player_assists"),
              ("PLAYER_PRA", "player_pra"),
              ("PRA", "player_pra"),
              ("PTS_REB_AST", "player_pra")]


@pytest.mark.parametrize("market,family", REGISTERED)
def test_nba_prop_families_registered_research_only(market, family):
    d = family_market_decision("NBA", market)
    assert d["market"] == family
    assert d["state"] == "REGISTERED_RESEARCH_ONLY"
    assert d["registration_state"] == "REGISTERED_RESEARCH_ONLY"
    assert d["validation_status"] == "NOT_VALIDATED"
    assert d["blocker"] == "NO_VALIDATION"
    assert d["reason"] == "FAMILY_REGISTRY_NOT_VALIDATED"
    assert d["eligible"] is False and d["promotable"] is False
    assert d["official_authority"] is False
    assert d["model_p_authority"] is False
    assert d["staking_authority"] is False
    assert d["pricing_condition"] == "ENGINE_SUFFICIENCY_MET"


@pytest.mark.parametrize("market", [
    "PLAYER_THREES", "PLAYER_STEALS", "PLAYER_BLOCKS",
    "PLAYER_TURNOVERS", "DOUBLE_DOUBLE", "TEAM_TOTAL", "TEAM_TOTALS"])
def test_other_nba_families_unchanged_blocked(market):
    d = family_market_decision("NBA", market)
    assert d["state"] == "BLOCKED"
    assert d["blocker"] == "NO_ENGINE"
    assert d["reason"] == "FAMILY_MARKET_UNREGISTERED"
    assert d["validation_status"] == "UNVALIDATED"


@pytest.mark.parametrize("market", ["ML", "SPREAD", "TOTAL"])
def test_nba_game_markets_unchanged_blocked(market):
    d = family_market_decision("NBA", market)
    assert d["state"] == "BLOCKED"
    assert d["blocker"] == "NO_VALIDATION"
    assert d["validation_status"] == "UNVALIDATED"


def test_cbb_and_cfb_unaffected_by_nba_registration():
    d = family_market_decision("CBB", "PLAYER_POINTS")
    assert d["state"] == "BLOCKED" and d["blocker"] == "NO_ENGINE"
    cfb = family_market_decision("CFB", "TOTAL")
    assert cfb["state"] == "REGISTERED_RESEARCH_ONLY"
    assert cfb["pricing_condition"] == "FORM2_IDENTITY_SATISFIED_BOTH_TEAMS"


# ---------------------------------------------------------------------- gate

def stamped_row(**overrides):
    row = {"sport": "NBA", "market": "PLAYER_POINTS",
           "side": "OVER", "line": 24.5, "odds": -110,
           "model_p": 0.55, "ev_per_dollar": 0.04,
           "nba_prop_engine": {"engine_id": ENGINE_ID,
                               "sufficiency_met": True, "n_prior": 14}}
    row.update(overrides)
    return row


def test_gate_keeps_priced_nba_row_with_valid_stamp():
    gated = gate_and_stamp({"rows": [stamped_row()]}, "NBA", "t")
    row = gated["rows"][0]
    assert row["model_p"] == 0.55
    assert row["registry_disposition"] == \
        "RESEARCH_PRICING_ALLOWED_ENGINE_SUFFICIENCY_MET"
    assert row["registration_state"] == "REGISTERED_RESEARCH_ONLY"
    assert gated["registry_gate"]["family_state"] == \
        "BLOCKED_WITH_NBA_RESEARCH_PRICING"
    assert gated["registry_gate"]["research_priced_nba"] == 1


@pytest.mark.parametrize("stamp", [
    None,
    {"engine_id": "SOME_OTHER_ENGINE", "sufficiency_met": True,
     "n_prior": 20},
    {"engine_id": ENGINE_ID, "sufficiency_met": False, "n_prior": 20},
    {"engine_id": ENGINE_ID, "sufficiency_met": True, "n_prior": 9},
    {"engine_id": ENGINE_ID, "sufficiency_met": True, "n_prior": "20"},
    {"engine_id": ENGINE_ID, "sufficiency_met": True, "n_prior": True},
    {"engine_id": ENGINE_ID, "sufficiency_met": 1, "n_prior": 20},
])
def test_gate_strips_nba_row_without_valid_stamp(stamp):
    row = stamped_row()
    if stamp is None:
        row.pop("nba_prop_engine")
    else:
        row["nba_prop_engine"] = stamp
    assert nba_engine_sufficiency_met(row) is False
    assert research_pricing_allowed("NBA", "PLAYER_POINTS", row) is False
    gated = gate_and_stamp({"rows": [row]}, "NBA", "t")
    out = gated["rows"][0]
    # The gate strips model-output keys (the quote itself stays as
    # the record of what was refused — the gate's standing semantics).
    assert "model_p" not in out and "ev_per_dollar" not in out
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["blocker"] == "NO_VALIDATION"
    assert out["reason"].startswith("FAMILY_REGISTRY_NOT_VALIDATED")


def test_gate_strips_nba_game_market_even_with_prop_stamp():
    row = {"sport": "NBA", "market": "TOTAL", "line": 220.5,
           "odds": -110, "model_p": 0.55,
           "nba_prop_engine": {"engine_id": ENGINE_ID,
                               "sufficiency_met": True, "n_prior": 30}}
    gated = gate_and_stamp({"rows": [row]}, "NBA", "t")
    assert "model_p" not in gated["rows"][0]


def test_family_gate_row_names_engine_sufficiency_for_nba():
    row = family_gate_row("NBA", "PLAYER_POINTS",
                          {"sport": "NBA", "market": "PLAYER_POINTS"})
    assert row["blocker"] == "NO_VALIDATION"
    assert ">= 10 point-in-time prior games" in row["reason"]
    assert "Form 2" not in row["reason"]


def test_cfb_gate_state_string_unchanged_when_only_cfb_prices():
    gated = gate_and_stamp({"rows": []}, "CFB", "t")
    assert gated["registry_gate"]["family_state"] == "BLOCKED"


# ------------------------------------------------------------- phone pricing

def make_store(n=12):
    return GameLogStore(guard_history(n))


def quote_row(**kw):
    row = {"sport": "NBA", "market": "PLAYER_POINTS",
           "player_name": "Test Guard", "side": "OVER", "line": 19.5,
           "odds": -110, "commence_time": "2026-11-05T00:00:00+00:00",
           "quote_captured_at": "2026-10-20T12:00:00+00:00"}
    row.update(kw)
    return row


NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def test_phone_rows_price_with_stamp():
    outputs, receipts = phone_nba_prop_rows(
        [quote_row()], now=NOW, store=make_store())
    (out,) = outputs
    assert out["status"] in {"PRICED_RESEARCH",
                             "RESEARCH_CANDIDATE_NOT_VALIDATED"}
    assert out["registry_enforced"] is True
    assert out["registry_disposition"] == \
        "RESEARCH_PRICING_ALLOWED_ENGINE_SUFFICIENCY_MET"
    assert out["nba_prop_engine"]["sufficiency_met"] is True
    assert out["nba_prop_engine"]["participation_feed"] == "NOT_WIRED"
    assert out["pricing_provenance"]["lane"] == "INDEPENDENT"
    assert out["pricing_provenance"]["play_eligible"] is False
    assert out["eligible"] is False and out["promotable"] is False
    assert abs(out["p_over"] + out["p_push"] + out["p_under"] - 1) < 1e-12


def test_phone_rows_block_without_store():
    outputs, _ = phone_nba_prop_rows([quote_row()], now=NOW, store=None,
                                     store_dir="/nonexistent-dir")
    (out,) = outputs
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["blocker"] == "NBA_PROP_HISTORY_STORE_UNAVAILABLE"
    assert out["registry_enforced"] is True


def test_phone_rows_block_on_sufficiency():
    outputs, _ = phone_nba_prop_rows(
        [quote_row()], now=NOW, store=make_store(4))
    (out,) = outputs
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["blocker"] == "NBA_PROP_INSUFFICIENT_PRIOR_GAMES"


def test_phone_rows_block_unknown_player_and_bad_side():
    outputs, _ = phone_nba_prop_rows(
        [quote_row(player_name="Nobody Here")], now=NOW,
        store=make_store())
    assert outputs[0]["blocker"] == "NBA_PROP_PLAYER_NOT_IN_STORE"
    outputs, _ = phone_nba_prop_rows(
        [quote_row(side="YES")], now=NOW, store=make_store())
    assert outputs[0]["blocker"] == "NBA_PROP_SIDE_UNVERIFIED"


def test_phone_rows_stale_quote_is_watch():
    outputs, _ = phone_nba_prop_rows(
        [quote_row(quote_captured_at="2026-10-20T11:00:00+00:00")],
        now=NOW, store=make_store())
    assert outputs[0]["status"] == "WATCH_QUOTE_NOT_CURRENT"


def test_store_dir_loading_round_trip(tmp_path):
    pull = tmp_path / "nba_player_games_2026.csv"
    with open(pull, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION",
                    "GAME_ID", "MIN", "PTS", "REB", "AST", "SEASON",
                    "SEASON_TYPE_ID"])
        for i in range(12):
            w.writerow(["1", "Test Guard", "TST", f"g{i}", "30",
                        "20", "5", "5", "2026-27", "2"])
            w.writerow(["2", "Fwd A", "TST", f"g{i}", "30",
                        "15", "5", "5", "2026-27", "2"])
            w.writerow(["3", "Fwd B", "TST", f"g{i}", "30",
                        "15", "5", "5", "2026-27", "2"])
            w.writerow(["4", "Fwd C", "TST", f"g{i}", "30",
                        "15", "5", "5", "2026-27", "2"])
    with open(tmp_path / "game_dates.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["GAME_ID", "GAME_DATE"])
        for i in range(12):
            w.writerow([f"g{i}", f"2026-10-{1 + i:02d}"])
    with open(tmp_path / "positions.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["PLAYER_ID", "POSITION"])
        w.writerow(["1", "G"])
        for pid in ("2", "3", "4"):
            w.writerow([pid, "F"])
    outputs, receipts = phone_nba_prop_rows(
        [quote_row()], now=NOW, store_dir=str(tmp_path))
    assert outputs[0]["status"] in {"PRICED_RESEARCH",
                                    "RESEARCH_CANDIDATE_NOT_VALIDATED"}
    assert receipts[0]["status"] == "NBA_PROP_STORE_LOADED"


# -------------------------------------------------------------------- runner

def _run(lines, **kw):
    import run_it_full as full
    kw.setdefault("getter", lambda url: None)
    kw.setdefault("auto_context", False)
    return full.run_full({"lines": lines}, now=NOW, **kw)


def _nba_line(**kw):
    row = {"sport": "NBA", "market": "PLAYER_POINTS",
           "player_name": "Test Guard",
           "away": "Boston Celtics", "home": "Detroit Pistons",
           "side": "OVER", "line": 19.5, "odds": -110,
           "commence_time": "2026-11-05T00:00:00+00:00",
           "quote_captured_at": NOW.isoformat()}
    row.update(kw)
    return row


def test_runner_blocks_nba_prop_without_store(monkeypatch):
    monkeypatch.delenv("SPORTSEDGE_NBA_PROP_STORE_DIR", raising=False)
    card = _run([_nba_line()])
    (row,) = [r for r in card["prop_unpriced"]
              if r.get("coverage_market") == "player_points"]
    assert row["blocker"] == "NBA_PROP_HISTORY_STORE_UNAVAILABLE"
    assert row["registry_enforced"] is True
    assert card["prop_model_status"]["nba_prop_engine"].startswith(
        "NBA_PROP_EMPIRICAL_V1")


def test_runner_prices_nba_prop_with_store(tmp_path, monkeypatch):
    import sportsedge.nba_phone_prop_pricing as phone
    phone._STORE_CACHE.clear()
    pull = tmp_path / "nba_player_games_2026.csv"
    with open(pull, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["PLAYER_ID", "PLAYER_NAME", "GAME_ID", "MIN",
                    "PTS", "REB", "AST"])
        for i in range(12):
            for pid, name, pts in (("1", "Test Guard", 20),
                                   ("2", "Fwd A", 15), ("3", "Fwd B", 15),
                                   ("4", "Fwd C", 15)):
                w.writerow([pid, name, f"g{i}", "30", str(pts), "5", "5"])
    with open(tmp_path / "game_dates.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["GAME_ID", "GAME_DATE"])
        for i in range(12):
            w.writerow([f"g{i}", f"2026-10-{1 + i:02d}"])
    with open(tmp_path / "positions.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["PLAYER_ID", "POSITION"])
        w.writerow(["1", "G"])
        for pid in ("2", "3", "4"):
            w.writerow([pid, "F"])
    monkeypatch.setenv("SPORTSEDGE_NBA_PROP_STORE_DIR", str(tmp_path))
    card = _run([_nba_line()])
    priced = [r for r in card["evaluated_rows"]
              if r.get("coverage_market") == "player_points"]
    assert len(priced) == 1
    row = priced[0]
    assert row["status"] in {"PRICED_RESEARCH",
                             "RESEARCH_CANDIDATE_NOT_VALIDATED"}
    assert row["registry_disposition"] == \
        "RESEARCH_PRICING_ALLOWED_ENGINE_SUFFICIENCY_MET"
    assert row["nba_prop_engine"]["n_prior"] == 12
    assert row["model_probability"] == row["p_over"]
    receipts = [r for r in card["source_receipts"]
                if r.get("status") == "NBA_PROP_STORE_LOADED"]
    assert len(receipts) == 1


def test_runner_blocks_nba_prop_on_sufficiency(tmp_path, monkeypatch):
    import sportsedge.nba_phone_prop_pricing as phone
    phone._STORE_CACHE.clear()
    pull = tmp_path / "nba_player_games_2026.csv"
    with open(pull, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["PLAYER_ID", "PLAYER_NAME", "GAME_ID", "MIN",
                    "PTS", "REB", "AST"])
        for i in range(4):
            for pid, name in (("1", "Test Guard"), ("2", "Fwd A")):
                w.writerow([pid, name, f"g{i}", "30", "20", "5", "5"])
    with open(tmp_path / "game_dates.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["GAME_ID", "GAME_DATE"])
        for i in range(4):
            w.writerow([f"g{i}", f"2026-10-{1 + i:02d}"])
    with open(tmp_path / "positions.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["PLAYER_ID", "POSITION"])
        w.writerow(["1", "G"])
        w.writerow(["2", "F"])
    monkeypatch.setenv("SPORTSEDGE_NBA_PROP_STORE_DIR", str(tmp_path))
    card = _run([_nba_line()])
    (row,) = [r for r in card["prop_unpriced"]
              if r.get("coverage_market") == "player_points"]
    assert row["blocker"] == "NBA_PROP_INSUFFICIENT_PRIOR_GAMES"


def test_runner_other_nba_prop_keeps_todays_blocker_row():
    from sportsedge.registry_gate import family_gate_row
    line = _nba_line(market="PLAYER_THREES")
    card = _run([line])
    expected = family_gate_row("NBA", "PLAYER_THREES", line)
    (row,) = [r for r in card["prop_unpriced"]
              if r.get("market") == "PLAYER_THREES"]
    for key in ("status", "blocker", "reason", "coverage_market"):
        assert row[key] == expected[key]
    assert row["family_decision"] == expected["family_decision"]
    assert row["blocker"] == "NO_ENGINE"


def test_runner_nba_game_market_row_unchanged():
    line = _nba_line(market="TOTAL")
    line.pop("player_name")
    card = _run([line])
    rows = [r for r in card["prop_unpriced"] + card["evaluated_rows"]
            if r.get("sport") == "NBA" and r.get("market") == "TOTAL"]
    assert rows, "NBA game row vanished"
    assert all(r.get("status") == "NO_MODEL_OR_MARKET" for r in rows)
    assert all(r.get("blocker") == "NO_VALIDATION" for r in rows)
