"""Tests for the MLB plate-appearance engine v1 (M49 construction).

The engine implements SPEC_M49_PA.md unchanged (Oct 17 backtest
program; spec sha256 2e2cb70d...).  The exact formula is pinned two
ways: a hand-computed case on the pure construction function below,
and the screen's bit-exact parity with the frozen Oct 17 record
(research/mlb_pa_engine_20261020/screen_results_v1.json — population
counters exact, every compared figure within 1.2e-16).  These tests
pin the engine's own contract: fail-closed sufficiency gates, PIT
invariance under hostile injection, identity refusal, and the
grouped form's partition refusal.  Nothing here touches the gate:
the last test asserts the PLATE_APPEARANCE families still terminate
BLOCKED at PLATE_APPEARANCE_PBP_POOL_UNBUILT — the gate lift is a
separate owner-ruled step.
"""
from collections import Counter
from fractions import Fraction

import pytest

from sportsedge.mlb_plate_appearance_engine import (
    CATEGORIES, K_SHRINK, MIN_PRIOR_PA, REACHED_CATEGORIES,
    PlateAppearanceEngineError, PlateAppearancePool, category_of,
    load_pool_rows, price_plate_appearance, resolve_batter_id,
    shrunk_distribution)

K, BB, S, X, HR, O = "STRIKEOUT", "WALK", "HIT_SINGLE", "HIT_DOUBLE", \
    "HOME_RUN", "OUT_IN_PLAY"


def _pa(game_id, game_date, completed, batter, pa_no, outcome, season=2025):
    return {"batter_id": batter, "game_id": game_id, "season": season,
            "game_date": game_date, "game_completed_date": completed,
            "batter_pa_number": pa_no, "outcome_class": outcome}


def _game(game_id, game_date, pas, completed=None):
    """pas: list of (batter_id, outcome_class); PA numbers assigned
    per batter in order."""
    seen = Counter()
    rows = []
    for batter, outcome in pas:
        seen[batter] += 1
        rows.append(_pa(game_id, game_date, completed or game_date,
                        batter, seen[batter], outcome))
    return rows


# ---- fixture population (all May 2025, completed on game date) ----
B101_OUTCOMES = [K] * 15 + [BB] * 5 + [S] * 12 + [X] * 3 + [HR] * 3 + [O] * 22
B102_OUTCOMES = [O] * 25 + [K] * 25            # exactly 50 priors
B103_OUTCOMES = [S] * 49                       # one short of the gate
OTHERS = list(range(201, 210))                 # 9 batters, filler PAs


def _fixture_rows():
    rows = []
    gid = 900000
    # batter 101: 12 games x 5 PAs; the other batters appear once
    # per game in the same games (league mass).
    for g in range(12):
        gid += 1
        day = f"2025-05-{g + 1:02d}"
        pas = [(101, oc) for oc in B101_OUTCOMES[g * 5:(g + 1) * 5]]
        pas += [(b, O) for b in OTHERS]
        rows += _game(gid, day, pas)
    # batter 102: 10 games x 5 PAs
    for g in range(10):
        gid += 1
        day = f"2025-05-{g + 1:02d}"
        rows += _game(gid, day,
                      [(102, oc) for oc in B102_OUTCOMES[g * 5:(g + 1) * 5]])
    # batter 103: 49 PAs over 10 games (5,5,5,5,5,5,5,5,5,4)
    left = list(B103_OUTCOMES)
    for g in range(10):
        gid += 1
        day = f"2025-05-{g + 1:02d}"
        take, left = left[:5], left[5:]
        rows += _game(gid, day, [(103, oc) for oc in take])
    return rows


def _pool():
    return PlateAppearancePool(_fixture_rows())


def _expected(batter_outcomes, all_outcomes):
    """Independent rational arithmetic over the fixture literals."""
    b = Counter(category_of(oc) for oc in batter_outcomes)
    lg = Counter(category_of(oc) for oc in all_outcomes)
    n_b, n_l = sum(b.values()), sum(lg.values())
    return {c: float((b[c] + K_SHRINK * Fraction(lg[c], n_l)) / (n_b + K_SHRINK))
            for c in CATEGORIES}


ALL_OUTCOMES = (B101_OUTCOMES + B102_OUTCOMES + B103_OUTCOMES
                + [O] * (12 * len(OTHERS)))


# ------------------------------------------------------------------
# construction pins
# ------------------------------------------------------------------
def test_category_partition_matches_spec_exactly():
    table = {
        "STRIKEOUT": "K", "WALK": "BB_HBP", "INTENT_WALK": "BB_HBP",
        "HIT_BY_PITCH": "BB_HBP", "HIT_SINGLE": "SINGLE",
        "HIT_DOUBLE": "XBH", "HIT_TRIPLE": "XBH", "HOME_RUN": "HR",
        "OUT_IN_PLAY": "OTHER", "SAC_FLY": "OTHER", "SAC_BUNT": "OTHER",
        "REACH_ON_ERROR": "OTHER", "FIELDERS_CHOICE": "OTHER",
        "INTERFERENCE": "OTHER"}
    assert len(table) == 14
    for outcome_class, cat in table.items():
        assert category_of(outcome_class) == cat
    with pytest.raises(PlateAppearanceEngineError):
        category_of("BALK")
    with pytest.raises(PlateAppearanceEngineError):
        category_of(None)


def test_shrunk_distribution_hand_computed():
    # batter (10,10,10,10,10,10) n=60; league shares (.2,.1,.1,.1,.1,.4)
    dist = shrunk_distribution((10, 10, 10, 10, 10, 10),
                               (600, 300, 300, 300, 300, 1200))
    assert dist == pytest.approx(
        (20 / 110, 15 / 110, 15 / 110, 15 / 110, 15 / 110, 30 / 110),
        rel=1e-12)
    assert sum(dist) == pytest.approx(1.0, abs=1e-12)
    with pytest.raises(PlateAppearanceEngineError):
        shrunk_distribution((1, 2, 3, 4, 5, 6), (0, 0, 0, 0, 0, 0))


def test_price_carries_no_scoring_floor():
    # raw candidate value ~1.25e-7 must come back unfloored: the
    # spec's 1e-6 floor is a scoring-only device, never a price.
    dist = shrunk_distribution((200000, 0, 0, 0, 0, 0),
                               (2000000, 1, 0, 0, 0, 0))
    assert 0 < dist[1] < 1e-6
    assert dist[1] == pytest.approx(
        float((0 + 50 * Fraction(1, 2000001)) / 200050), rel=1e-9)


# ------------------------------------------------------------------
# pricing + sufficiency gates
# ------------------------------------------------------------------
def test_price_result_distribution_matches_fixture_counts():
    row = price_plate_appearance(_pool(), market="PLATE_APPEARANCE_RESULT",
                                 batter_id=101, target_date="2025-06-01")
    assert row["status"] == "PRICED"
    assert row["prior_pa"] == 60
    assert row["league_prior_pa"] == len(ALL_OUTCOMES)
    expected = _expected(B101_OUTCOMES, ALL_OUTCOMES)
    for c in CATEGORIES:
        assert row["probabilities"][c] == pytest.approx(expected[c],
                                                        rel=1e-12)
        # shrinkage is a convex pull: each price sits between the
        # batter's raw rate and the league rate
        emp = row["batter_empirical"][c]
        lg = row["league_climatology"][c]
        assert min(emp, lg) - 1e-15 <= row["probabilities"][c] \
            <= max(emp, lg) + 1e-15
    assert row["shrink_weight_league"] == pytest.approx(50 / 110)
    assert row["engine"] == "mlb_plate_appearance_engine_v1"
    assert row["research_only"] is True
    assert row["model_p_authority"] is False


def test_on_base_is_the_same_distribution_summed():
    pool = _pool()
    dist = price_plate_appearance(pool, market="PLATE_APPEARANCE_RESULT",
                                  batter_id=101, target_date="2025-06-01")
    ob = price_plate_appearance(pool, market="PLATE_APPEARANCE_ON_BASE",
                                batter_id=101, target_date="2025-06-01")
    # no independence shortcut: on-base is the reached mass of the
    # one priced joint distribution
    assert ob["p_on_base"] == pytest.approx(
        sum(dist["probabilities"][c] for c in REACHED_CATEGORIES),
        abs=1e-15)
    assert ob["p_on_base"] + ob["p_not_on_base"] == pytest.approx(1.0)


def test_grouped_result_refused_partition_unverified():
    row = price_plate_appearance(
        _pool(), market="PLATE_APPEARANCE_GROUPED_RESULT",
        batter_id=101, target_date="2025-06-01")
    assert row["status"] == "NOT_PRICED"
    assert row["reason"] == "PLATE_APPEARANCE_GROUPED_PARTITION_UNVERIFIED"
    assert "probabilities" not in row


def test_sufficiency_boundary_exact():
    pool = _pool()
    ok = price_plate_appearance(pool, market="PLATE_APPEARANCE_RESULT",
                                batter_id=102, target_date="2025-06-01")
    assert ok["status"] == "PRICED" and ok["prior_pa"] == MIN_PRIOR_PA
    short = price_plate_appearance(pool, market="PLATE_APPEARANCE_RESULT",
                                   batter_id=103, target_date="2025-06-01")
    assert short["status"] == "NOT_PRICED"
    assert short["reason"] == "PLATE_APPEARANCE_INSUFFICIENT_PRIOR_PA"
    assert short["prior_pa"] == 49
    assert "probabilities" not in short


def test_batter_not_in_pool_and_pool_unavailable():
    pool = _pool()
    row = price_plate_appearance(pool, market="PLATE_APPEARANCE_RESULT",
                                 batter_id=999999, target_date="2025-06-01")
    assert row["reason"] == "PLATE_APPEARANCE_BATTER_NOT_IN_POOL"
    row = price_plate_appearance(None, market="PLATE_APPEARANCE_RESULT",
                                 batter_id=101, target_date="2025-06-01")
    assert row["reason"] == "PLATE_APPEARANCE_POOL_UNAVAILABLE"
    # a pool holding only another season is unavailable for this one
    rows2024 = [dict(r, season=2024) for r in _fixture_rows()]
    row = price_plate_appearance(PlateAppearancePool(rows2024),
                                 market="PLATE_APPEARANCE_RESULT",
                                 batter_id=101, target_date="2025-06-01")
    assert row["reason"] == "PLATE_APPEARANCE_POOL_UNAVAILABLE"


def test_known_batter_before_his_first_game_is_insufficient_not_unknown():
    row = price_plate_appearance(_pool(), market="PLATE_APPEARANCE_RESULT",
                                 batter_id=101, target_date="2025-04-01")
    assert row["reason"] == "PLATE_APPEARANCE_INSUFFICIENT_PRIOR_PA"
    assert row["prior_pa"] == 0


# ------------------------------------------------------------------
# PIT hostile probes
# ------------------------------------------------------------------
def _price101(pool, target="2025-06-01"):
    return price_plate_appearance(pool, market="PLATE_APPEARANCE_RESULT",
                                  batter_id=101,
                                  target_date=target)["probabilities"]


def test_future_and_target_day_games_do_not_move_the_price():
    base = _price101(_pool())
    rows = _fixture_rows()
    # the target game's own PAs (all home runs) and a future game
    rows += _game(999001, "2025-06-01", [(101, HR)] * 5)
    rows += _game(999002, "2025-06-05", [(101, HR)] * 5)
    assert _price101(PlateAppearancePool(rows)) == base


def test_same_date_doubleheader_game_never_feeds():
    base = _price101(_pool(), target="2025-05-20")
    rows = _fixture_rows()
    # game 1 of a doubleheader played the morning of the target date
    rows += _game(999003, "2025-05-20", [(101, HR)] * 5)
    assert _price101(PlateAppearancePool(rows), target="2025-05-20") == base


def test_suspended_game_feeds_only_after_completion():
    base_rows = _fixture_rows()
    # started May 20, suspended, completed Jun 3 — five HRs that
    # must be invisible to a Jun 1 target and visible to a Jun 4 one
    sus = [_pa(999004, "2025-05-20", "2025-06-03", 101, i + 1, HR)
           for i in range(5)]
    pool = PlateAppearancePool(base_rows + sus)
    assert _price101(pool, target="2025-06-01") == _price101(
        PlateAppearancePool(base_rows), target="2025-06-01")
    later = price_plate_appearance(pool, market="PLATE_APPEARANCE_RESULT",
                                   batter_id=101, target_date="2025-06-04")
    assert later["prior_pa"] == 65
    assert later["probabilities"]["HR"] > _price101(
        PlateAppearancePool(base_rows), target="2025-06-04")["HR"]


# ------------------------------------------------------------------
# identity + malformed input refusal
# ------------------------------------------------------------------
def test_resolve_batter_id_unique_unknown_ambiguous():
    directory = {"Shohei Ohtani": [660271], "Mike Trout": [545361],
                 "Jose Ramirez": [608070, 123456]}
    assert resolve_batter_id("  shohei   ohtani ", directory) == 660271
    with pytest.raises(PlateAppearanceEngineError, match="BATTER_UNKNOWN"):
        resolve_batter_id("Nobody Here", directory)
    with pytest.raises(PlateAppearanceEngineError,
                       match="IDENTITY_AMBIGUOUS"):
        resolve_batter_id("Jose Ramirez", directory)
    # the same id listed twice is one identity, not an ambiguity
    assert resolve_batter_id("Mike Trout",
                             {"Mike Trout": [545361, 545361]}) == 545361


def test_malformed_inputs_raise_named_errors():
    pool = _pool()
    for bad_id in (True, "660271", 0, -5, 660271.0, None):
        with pytest.raises(PlateAppearanceEngineError,
                           match="BATTER_ID_INVALID"):
            price_plate_appearance(pool, market="PLATE_APPEARANCE_RESULT",
                                   batter_id=bad_id,
                                   target_date="2025-06-01")
    for bad_date in ("June 1 2025", "2025-13-01", "2025-06-01T00:00:00",
                     20250601, None):
        with pytest.raises(PlateAppearanceEngineError,
                           match="TARGET_DATE_INVALID"):
            price_plate_appearance(pool, market="PLATE_APPEARANCE_RESULT",
                                   batter_id=101, target_date=bad_date)
    with pytest.raises(PlateAppearanceEngineError, match="MARKET_UNKNOWN"):
        price_plate_appearance(pool, market="PLATE_APPEARANCE_SIDE",
                               batter_id=101, target_date="2025-06-01")


# ------------------------------------------------------------------
# loader / pool integrity (fail closed, never zero-filled)
# ------------------------------------------------------------------
def test_loader_rejects_bad_rows(tmp_path):
    import gzip
    import json
    good = _pa(1, "2025-05-01", "2025-05-01", 101, 1, S)
    bad_variants = [
        dict(good, outcome_class="BALK"),          # unmapped outcome
        {k: v for k, v in good.items() if k != "batter_id"},  # missing
        dict(good, batter_id=True),                # bool is not an id
        dict(good, batter_pa_number=0),            # PA numbers are 1-based
        dict(good, game_completed_date="05/01/2025"),
    ]
    for i, bad in enumerate(bad_variants):
        path = tmp_path / f"bad{i}.jsonl.gz"
        with gzip.open(path, "wt") as fh:
            fh.write(json.dumps(good) + "\n")
            fh.write(json.dumps(bad) + "\n")
        with pytest.raises(PlateAppearanceEngineError):
            load_pool_rows([path])
    ok_path = tmp_path / "ok.jsonl"
    ok_path.write_text(json.dumps(good) + "\n")
    rows = load_pool_rows([ok_path])
    assert rows[0]["category"] == "SINGLE"


def test_pool_rejects_conflicting_game_metadata():
    rows = _fixture_rows()
    gid = rows[0]["game_id"]
    rows.append(_pa(gid, "2025-05-02", "2025-05-02", 101, 1, S))
    with pytest.raises(PlateAppearanceEngineError,
                       match="POOL_GAME_METADATA_CONFLICT"):
        PlateAppearancePool(rows)


def test_game_metadata_conflict_free_pool_builds():
    pool = _pool()
    assert pool.seasons == {2025}
    assert pool.has_batter(101) and not pool.has_batter(999999)


# ------------------------------------------------------------------
# governance: this build changes no gate state
# ------------------------------------------------------------------
def test_pa_families_still_blocked_at_the_gate():
    from sportsedge.mlb_plate_appearance_gates import (
        plate_appearance_blocked_row)
    for market in ("PLATE_APPEARANCE_RESULT", "PLATE_APPEARANCE_ON_BASE",
                   "PLATE_APPEARANCE_GROUPED_RESULT"):
        row = plate_appearance_blocked_row(
            {"market": market, "side": "YES", "player_name": "X"})
        assert row["blocker"] == "NO_ENGINE"
        assert row["plate_appearance_gate"] == \
            "PLATE_APPEARANCE_PBP_POOL_UNBUILT"
