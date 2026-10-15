"""Synthetic fixtures only; no historical performance evidence."""
import pytest

from sportsedge.research.mlb_first_pa_pool import (
    SELECTION_GATE, build_first_pa_pool, read_first_pa_on_base,
)


def _game(pk, start, plays, status="Final"):
    return {"game_pk": pk, "first_pitch_utc": start, "status": status,
            "plays": [dict(at_bat_index=i, **p) for i, p in enumerate(plays)]}


def P(half, b, p, e):
    return {"half": half, "batter_id": b, "pitcher_id": p, "event_type": e}


G1 = _game(1, "2026-09-01T23:05:00Z", [
    P("top", "A", "SP_H", "single"), P("top", "B", "SP_H", "strikeout"),
    P("bottom", "X", "SP_A", "walk"), P("top", "A", "SP_H", "home_run"),
    P("top", "C", "RP_H", "double"),
])
G2 = _game(2, "2026-09-02T23:05:00Z", [
    P("top", "A", "SP_H", "field_out"), P("bottom", "X", "SP_A", "hit_by_pitch"),
])
TARGET = _game(3, "2026-09-03T23:05:00Z", [P("top", "A", "SP_H", "home_run")])


def test_only_strictly_prior_games_and_only_first_pa():
    pool = build_first_pa_pool([G1, G2, TARGET], cutoff_utc="2026-09-03T23:05:00Z")
    assert pool["games_used"] == ["1", "2"]
    assert pool["games_excluded_not_strictly_prior"] == 1
    assert pool["batters"]["A"] == {"OUT_IN_PLAY": 1, "SINGLE": 1}  # 2nd PA HR ignored
    assert pool["starters_first_pa_faced"]["SP_H"] == {"OUT_IN_PLAY": 1, "SINGLE": 1, "STRIKEOUT": 1}
    assert "RP_H" not in pool["starters_first_pa_faced"]  # reliever-faced first PA excluded
    assert pool["settlement_gate"] == SELECTION_GATE


def test_order_invariant_and_deterministic():
    a = build_first_pa_pool([G1, G2], cutoff_utc="2026-09-03T00:00:00Z")
    b = build_first_pa_pool([G2, G1], cutoff_utc="2026-09-03T00:00:00Z")
    assert a["pool_sha256"] == b["pool_sha256"]


def test_on_base_shrinkage_math():
    pool = build_first_pa_pool([G1, G2], cutoff_utc="2026-09-03T00:00:00Z")
    r = read_first_pa_on_base(pool, batter_id="A", prior_strength=4)
    # league: A single, A out, B K, X walk, X hbp, C double -> 4/6 on base
    assert r["league_on_base_rate"] == pytest.approx(4 / 6)
    assert r["research_p_on_base"] == pytest.approx((1 + 4 * 4 / 6) / (2 + 4))
    unseen = read_first_pa_on_base(pool, batter_id="NEW", prior_strength=4)
    assert unseen["research_p_on_base"] == pytest.approx(4 / 6)
    assert r["settlement_gate"] == SELECTION_GATE and not r["production_ready"]


@pytest.mark.parametrize("games,code", [
    ([G1, G1], "FIRST_PA_GAME_DUPLICATE"),
    ([_game(9, "2026-09-01T00:00:00", [P("top", "A", "S", "single")])], "FIRST_PA_START_INVALID"),
    ([_game(9, "2026-09-01T00:00:00Z", [P("top", "A", "S", "single")], status="Live")], "FIRST_PA_GAME_NOT_FINAL"),
    ([_game(9, "2026-09-01T00:00:00Z", [])], "FIRST_PA_PLAYS_MISSING"),
    ([_game(9, "2026-09-01T00:00:00Z", [P("top", "A", "S", "balk_mystery")])], "FIRST_PA_EVENT_UNMAPPED"),
    ([_game(9, "2026-09-01T00:00:00Z", [P("middle", "A", "S", "single")])], "FIRST_PA_HALF_INVALID"),
    ([_game(9, "2026-09-01T00:00:00Z", [P("top", True, "S", "single")])], "FIRST_PA_BATTER_ID_INVALID"),
    ([{"game_pk": 9, "first_pitch_utc": "2026-09-01T00:00:00Z", "status": "Final",
       "plays": [dict(at_bat_index=1, **P("top", "A", "S", "single")),
                 dict(at_bat_index=0, **P("top", "B", "S", "single"))]}], "FIRST_PA_PLAYS_NOT_CHRONOLOGICAL"),
    ([{"game_pk": 9, "first_pitch_utc": "2026-09-01T00:00:00Z", "status": "Final",
       "plays": [dict(at_bat_index=0, **P("top", "A", "S", "single")),
                 dict(at_bat_index=0, **P("top", "B", "S", "single"))]}], "FIRST_PA_AT_BAT_INDEX_DUPLICATE"),
])
def test_pool_refusals(games, code):
    with pytest.raises(ValueError, match=code):
        build_first_pa_pool(games, cutoff_utc="2026-09-03T00:00:00Z")


def test_reader_refusals():
    pool = build_first_pa_pool([G1], cutoff_utc="2026-09-03T00:00:00Z")
    for bad in (0, -1, float("nan"), True):
        with pytest.raises(ValueError, match="FIRST_PA_PRIOR_STRENGTH_INVALID"):
            read_first_pa_on_base(pool, batter_id="A", prior_strength=bad)
    tampered = dict(pool, batters={"A": {"HOME_RUN": 50}})
    with pytest.raises(ValueError, match="FIRST_PA_POOL_HASH_MISMATCH"):
        read_first_pa_on_base(tampered, batter_id="A", prior_strength=4)
    empty = build_first_pa_pool([G1], cutoff_utc="2026-01-01T00:00:00Z")
    with pytest.raises(ValueError, match="FIRST_PA_POOL_EMPTY"):
        read_first_pa_on_base(empty, batter_id="A", prior_strength=4)
    with pytest.raises(ValueError, match="FIRST_PA_CUTOFF_INVALID"):
        build_first_pa_pool([G1], cutoff_utc="yesterday")
