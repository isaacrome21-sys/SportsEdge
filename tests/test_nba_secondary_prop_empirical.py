"""NBA new secondary stat family synthetic research tests (not calibration)."""
from copy import deepcopy

import pytest

from sportsedge.nba_secondary_prop_empirical import (
    NBASecondaryError, research_nba_secondary_readout as read,
    FAMILIES,
)

TARGET = {
    "game_id": "NBA-G999",
    "player_id": "NBA-P1",
    "position_group": "G",
    "season_start_year": 2026,
    "target_start_utc": "2026-10-21T23:00:00Z",
    "as_of_utc": "2026-10-20T20:00:00Z",
}


def rows():
    result = []
    for player in range(1, 5):
        for day in range(1, 13):
            game = f"NBA-G{day}"
            row = {
                "game_id": game, "player_id": f"NBA-P{player}",
                "team_id": f"NBA-T{player}",
                "position_group": "G" if player <= 3 else "C",
                "season_start_year": 2026,
                "game_start_utc": f"2026-10-{day:02d}T18:00:00Z",
                "result_observed_utc": f"2026-10-{day:02d}T21:00:00Z",
                "snapshot_sha256": f"{player * 100 + day:064x}",
                "minutes": 28.0,
                "points": 14 + (player % 3),
                "rebounds": 10 + (day % 3),
                "assists": 10 if day % 3 == 0 else 3,
                "steals": day % 3,
                "blocks": player % 2,
                "turnovers": day % 4,
                "three_pointers": 2 + day % 2,
            }
            result.append(row)
    return result


def estimate(family, selection, line=None, source=None, **kw):
    params = TARGET | kw
    return read(rows=rows() if source is None else source,
                family=family, selection=selection, line=line, **params)


@pytest.mark.parametrize("family,line", [
    ("THREE_POINTERS", 2.5), ("STEALS", 0.5),
    ("BLOCKS", 0.5), ("TURNOVERS", 1.5),
    ("STEALS_PLUS_BLOCKS", 1.5),
])
def test_integer_count_opposing_sides_and_rung_conservation(family, line):
    over = estimate(family, "OVER", line=line)
    under = estimate(family, "UNDER", line=line)
    assert abs(over.probability + under.probability - 1) < 1e-12
    assert over.push_probability == under.push_probability == 0
    assert over.pool_player_n == 12
    assert over.pool_position_n == 36
    assert over.pool_scope == "POSITION"
    assert not over.eligible and over.market_test == "NO_MARKET_TEST"
    assert over.conditional_on_participation
    assert not over.participation_model_verified


def test_real_same_game_double_and_triple_double_not_product_marginals():
    dd = estimate("DOUBLE_DOUBLE", "YES")
    ddno = estimate("DOUBLE_DOUBLE", "NO")
    td = estimate("TRIPLE_DOUBLE", "YES")
    tdno = estimate("TRIPLE_DOUBLE", "NO")
    assert abs(dd.probability + ddno.probability - 1) < 1e-12
    assert abs(td.probability + tdno.probability - 1) < 1e-12
    assert dd.probability > td.probability
    assert td.probability > 0
    assert dd.push_probability == td.push_probability == 0


def test_integer_line_push_present_and_opposites_account_it():
    over = estimate("STEALS", "OVER", line=1)
    under = estimate("STEALS", "UNDER", line=1)
    assert over.push_probability > 0
    assert abs(over.probability + under.probability +
               over.push_probability - 1) < 1e-12


def test_pit_future_or_same_day_result_is_refused_even_for_other_player():
    archive = rows()
    archive[0]["game_start_utc"] = "2026-10-21T19:00:00Z"
    archive[0]["result_observed_utc"] = "2026-10-21T21:00:00Z"
    with pytest.raises(NBASecondaryError, match="FUTURE_OR_SAME_DATE_GAME_RESULT"):
        estimate("STEALS", "OVER", line=0.5, source=archive)


def test_unobserved_result_at_asof_is_refused():
    archive = rows()
    archive[0]["result_observed_utc"] = "2026-10-20T21:00:00Z"
    with pytest.raises(NBASecondaryError, match="RESULT_UNAVAILABLE_AT_ASOF"):
        estimate("STEALS", "OVER", line=0.5, source=archive)


def test_min_player_history_is_strict_without_zero_dnp_imputation():
    archive = [r for r in rows()
               if r["player_id"] != "NBA-P1" or int(r["game_id"].split("G")[1]) <= 9]
    with pytest.raises(NBASecondaryError, match="INSUFFICIENT_SAME_SEASON_PLAYER_HISTORY"):
        estimate("STEALS", "OVER", line=0.5, source=archive)
    archive = rows()
    for r in archive:
        if r["player_id"] == "NBA-P1" and r["game_id"] in ("NBA-G1", "NBA-G2", "NBA-G3"):
            r["minutes"] = 0
            for stat in ("points", "rebounds", "assists", "steals",
                         "blocks", "turnovers", "three_pointers"):
                r[stat] = 0
    with pytest.raises(NBASecondaryError, match="INSUFFICIENT_SAME_SEASON_PLAYER_HISTORY"):
        estimate("STEALS", "OVER", line=0.5, source=archive)


@pytest.mark.parametrize("field,value,error", [
    ("snapshot_sha256", "missing", "BOX_SOURCE_HASH_REQUIRED"),
    ("three_pointers", 50, "THREE_POINTERS_IMPOSSIBLE_POINTS"),
    ("steals", float("nan"), "STEALS_OBSERVATION_INVALID"),
    ("minutes", -1, "MINUTES_INVALID"),
    ("position_group", "UNKNOWN", "POSITION_GROUP_UNVERIFIED"),
])
def test_hostile_box_history_refuses(field, value, error):
    archive = rows()
    archive[0][field] = value
    with pytest.raises(NBASecondaryError, match=error):
        estimate("STEALS", "OVER", line=0.5, source=archive)


def test_duplicate_player_game_and_target_game_outcome_refused():
    archive = rows()
    archive.append(deepcopy(archive[0]))
    with pytest.raises(NBASecondaryError, match="DUPLICATE_PLAYER_GAME_RECORD"):
        estimate("STEALS", "OVER", line=0.5, source=archive)
    archive = rows()
    archive[0]["game_id"] = TARGET["game_id"]
    with pytest.raises(NBASecondaryError, match="TARGET_GAME_RESULT_LEAKAGE"):
        estimate("STEALS", "OVER", line=0.5, source=archive)


def test_same_input_hash_reproducible_with_new_version():
    a = estimate("STEALS_PLUS_BLOCKS", "OVER", line=1.5)
    b = estimate("STEALS_PLUS_BLOCKS", "OVER", line=1.5)
    assert a.readout_sha256 == b.readout_sha256
    assert a.status == "RESEARCH_UNSCREENED_NEW_FAMILY"
    assert not hasattr(a, "odds_american")
    assert not hasattr(a, "staking_units")
    assert not hasattr(a, "ev_per_dollar")


def test_registered_existing_nba_stat_families_are_not_modified():
    assert FAMILIES.isdisjoint({
        "PLAYER_POINTS", "PLAYER_REBOUNDS", "PLAYER_ASSISTS", "PLAYER_PRA"})
