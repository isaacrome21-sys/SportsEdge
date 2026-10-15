"""Synthetic fixtures only; no historical performance evidence."""
import pytest

from sportsedge.research.mlb_first_pa_pool import (
    SELECTION_GATE, build_first_pa_pool, read_first_pa_on_base,
)


_DEFAULT = object()


def _game(pk, start, plays, status="Final", final_observed=_DEFAULT, starters=_DEFAULT):
    # t190: pool games now carry the final/settled observation timestamp and the
    # independently confirmed starters (owner review 6202306708).
    g = {"game_pk": pk, "first_pitch_utc": start, "status": status,
         "plays": [dict(at_bat_index=i, **p) for i, p in enumerate(plays)]}
    g["final_observed_utc"] = start.replace("T23:05", "T23:59") if final_observed is _DEFAULT else final_observed
    g["starting_pitchers"] = {"home": "SP_H", "away": "SP_A"} if starters is _DEFAULT else starters
    if g["final_observed_utc"] is None:
        del g["final_observed_utc"]
    if g["starting_pitchers"] is None:
        del g["starting_pitchers"]
    return g


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


# --- t190 PIT availability and PBP completeness battery ---------------------

_FULL = [P("top", "A", "SP_H", "single"), P("bottom", "X", "SP_A", "walk")]
CUT = "2026-09-03T00:00:00Z"


@pytest.mark.parametrize("game,code", [
    (_game(9, "2026-09-01T23:05:00Z", _FULL, final_observed=None), "FIRST_PA_FINAL_AS_OF_MISSING"),
    (_game(9, "2026-09-01T23:05:00Z", _FULL, final_observed="2026-09-01T23:59:00"), "FIRST_PA_FINAL_AS_OF_INVALID"),
    (_game(9, "2026-09-01T23:05:00Z", _FULL, final_observed="2026-09-01T22:00:00Z"), "FIRST_PA_FINAL_BEFORE_START"),
    (_game(9, "2026-09-01T23:05:00Z", _FULL, starters=None), "FIRST_PA_STARTER_UNCONFIRMED"),
    (_game(9, "2026-09-01T23:05:00Z", _FULL, starters={"home": "SP_H"}), "FIRST_PA_STARTER_UNCONFIRMED"),
    (_game(9, "2026-09-01T23:05:00Z", _FULL, starters={"home": "OPENER", "away": "SP_A"}), "FIRST_PA_STARTER_MISMATCH"),
    (_game(9, "2026-09-01T23:05:00Z", [P("top", "A", "SP_H", "single")]), "FIRST_PA_PLAYS_INCOMPLETE"),
    (_game(9, "2026-09-01T23:05:00Z", [P("bottom", "X", "SP_A", "walk"), P("top", "A", "SP_H", "single")]),
     "FIRST_PA_PLAYS_INCOMPLETE"),
])
def test_pit_and_completeness_refusals_t190(game, code):
    with pytest.raises(ValueError, match=code):
        build_first_pa_pool([game], cutoff_utc=CUT)


def test_truncated_pbp_not_starting_at_zero_refused_t190():
    g = _game(9, "2026-09-01T23:05:00Z", _FULL)
    for i, play in enumerate(g["plays"]):
        play["at_bat_index"] = i + 3  # first PAs missing from the feed
    with pytest.raises(ValueError, match="FIRST_PA_PLAYS_INCOMPLETE"):
        build_first_pa_pool([g], cutoff_utc=CUT)


def test_gap_in_pbp_refused_t190():
    g = _game(9, "2026-09-01T23:05:00Z", _FULL + [P("top", "B", "SP_H", "single")])
    g["plays"][2]["at_bat_index"] = 5
    with pytest.raises(ValueError, match="FIRST_PA_PLAYS_INCOMPLETE"):
        build_first_pa_pool([g], cutoff_utc=CUT)


def test_final_observed_after_cutoff_is_excluded_not_used_t190():
    late = _game(9, "2026-09-02T23:05:00Z", _FULL, final_observed="2026-09-03T04:00:00Z")
    pool = build_first_pa_pool([G1, late], cutoff_utc=CUT)
    assert pool["games_used"] == ["1"]
    assert pool["games_excluded_final_not_observed_by_cutoff"] == 1
    assert "X" in pool["batters"] and pool["batters"]["X"] == {"WALK": 1}
