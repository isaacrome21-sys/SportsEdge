"""Offline adversarial screening of M22 strictly-prior inning 2..8 research.

These are synthetic unit tests, NOT a scored historical/market backtest.
"""
from copy import deepcopy
from dataclasses import replace

import pytest

from sportsedge.mlb_m22_inning_joint import (
    InningJointError, build_inning_joint, read_inning_probability,
)

TARGET = {
    "game_pk": 99999, "away_team_id": 1, "home_team_id": 2,
    "scheduled_start_utc": "2026-10-20T20:00:00Z",
}
AS_OF = "2026-10-19T20:00:00Z"


def _archive(innings=3, n=12):
    records = []
    for j in range(1, n + 1):
        for club in (1, 2):
            pk = 10000 + 2*j + (club == 2)
            if club == 1:
                away_id, home_id = 1, 400+j
                runs_away, runs_home = j % 4, (j+1) % 3
            else:
                away_id, home_id = 700+j, 2
                runs_away, runs_home = j % 3, (j+2) % 4
            records.append({
                "game_pk": pk,
                "away_team_id": away_id, "home_team_id": home_id,
                "inning": innings,
                "away_runs": runs_away, "home_runs": runs_home,
                "played_halves": "BOTH", "official_innings": 9,
                "game_start_utc": f"2026-09-{j:02d}T15:00:00Z",
                "completed_at_utc": f"2026-09-{j:02d}T18:00:00Z",
                "observed_at_utc": f"2026-09-{j:02d}T18:10:00Z",
                "source_payload_sha256": f"{pk:064x}",
            })
    return records


def _build(innings=3, history=None, strength=0):
    return build_inning_joint(
        TARGET, _archive(innings) if history is None else history,
        innings=innings, as_of_utc=AS_OF,
        league_prior_strength=strength)


@pytest.mark.parametrize("innings", [2, 3, 4, 5, 6, 7, 8])
def test_named_three_way_partition_preserves_tie_mass(innings):
    d = _build(innings)
    assert d.innings == innings and not d.eligible
    assert abs(sum(d.joint_score_pmf.values()) - 1.0) < 1e-12
    choices = [
        read_inning_probability(
            d, market=f"INNING_{innings}_3_WAY", selection=side)
        for side in ("HOME", "TIE", "AWAY")
    ]
    assert choices[1].probability > 0
    assert abs(sum(c.probability for c in choices) - 1.0) < 1e-12
    assert all(c.push_probability == 0 for c in choices)
    assert all(c.eligible is False and c.market_test == "NO_MARKET_TEST"
               for c in choices)


@pytest.mark.parametrize("innings", [2, 3, 4, 5, 6, 7, 8])
@pytest.mark.parametrize("line", [0.5, 1.5])
def test_inning_runs_yes_no_partition(innings, line):
    d = _build(innings)
    over = read_inning_probability(
        d, market=f"INNING_{innings}_RUNS", selection="OVER", line=line)
    under = read_inning_probability(
        d, market=f"INNING_{innings}_RUNS", selection="UNDER", line=line)
    assert abs(over.probability + under.probability - 1) < 1e-12
    assert over.push_probability == under.push_probability == 0.0


@pytest.mark.parametrize("line", [0.5, -0.5, 0.0])
def test_run_line_opposite_signed_sides_and_push(line):
    d = _build()
    home = read_inning_probability(
        d, market="INNING_3_RUN_LINE", selection="HOME", line=line)
    away = read_inning_probability(
        d, market="INNING_3_RUN_LINE", selection="AWAY", line=-line)
    assert abs(home.probability + away.probability +
               home.push_probability - 1) < 1e-12
    assert abs(home.push_probability - away.push_probability) < 1e-12


def test_strict_asof_and_start_admission():
    with pytest.raises(InningJointError, match="AS_OF_NOT_STRICTLY_BEFORE_TARGET"):
        build_inning_joint(TARGET, _archive(), innings=3,
                           as_of_utc="2026-10-20T20:00:00Z")
    corrupted = _archive()
    corrupted[0]["observed_at_utc"] = "2026-10-21T12:00:00Z"
    with pytest.raises(InningJointError, match="PIT_OBSERVATION_TIME_VIOLATION"):
        _build(history=corrupted)


def test_target_game_and_duplicate_games_refused():
    future = _archive()
    future[0]["game_pk"] = TARGET["game_pk"]
    with pytest.raises(InningJointError, match="TARGET_LEAKAGE_OR_DUPLICATE_GAMEPK"):
        _build(history=future)
    duplicate = _archive()
    duplicate[1]["game_pk"] = duplicate[0]["game_pk"]
    with pytest.raises(InningJointError, match="TARGET_LEAKAGE_OR_DUPLICATE_GAMEPK"):
        _build(history=duplicate)


@pytest.mark.parametrize("alter", [
    {"played_halves": "TOP_ONLY"},
    {"official_innings": 7},
])
def test_short_or_missing_bottom_half_refused(alter):
    rows = _archive()
    rows[0].update(alter)
    with pytest.raises(InningJointError, match="INCOMPLETE_OFFICIAL_GAME_OR_INNING"):
        _build(history=rows)


@pytest.mark.parametrize("invalid", [float("nan"), 2.5, -1, "3", None, True])
def test_noninteger_or_negative_inning_runs_refused(invalid):
    rows = _archive()
    rows[0]["away_runs"] = invalid
    with pytest.raises(InningJointError, match="NONNEGATIVE_INTEGER_REQUIRED"):
        _build(history=rows)


def test_source_hash_or_wrong_inning_refused():
    rows = _archive()
    rows[0]["source_payload_sha256"] = "not-a-hash"
    with pytest.raises(InningJointError, match="SHA256_REQUIRED"):
        _build(history=rows)
    rows = _archive()
    rows[0]["inning"] = 5
    with pytest.raises(InningJointError, match="HISTORY_WRONG_INNING"):
        _build(history=rows)


def test_history_minimum_is_not_imputed():
    with pytest.raises(InningJointError,
                       match="INSUFFICIENT_STRICTLY_PRIOR_TEAM_HISTORY"):
        _build(history=_archive(n=8))


def test_ninth_is_an_explicit_missing_half_and_walkoff_hold():
    with pytest.raises(InningJointError,
                       match="NINTH_OR_UNSUPPORTED_INNING_CONSTRUCTION_HELD"):
        _build(innings=9)
    d = _build(innings=8)
    with pytest.raises(InningJointError, match="NINTH_INNING_CONSTRUCTION_HELD"):
        read_inning_probability(
            d, market="INNING_9_RUNS", selection="OVER", line=.5)


def test_period_or_wrong_inning_cannot_relabel():
    d = _build(innings=4)
    with pytest.raises(InningJointError,
                       match="M22_INNING_DISTRIBUTION_IDENTITY_MISMATCH"):
        read_inning_probability(
            d, market="INNING_5_3_WAY", selection="TIE")
    with pytest.raises(InningJointError, match="UNRECOGNIZED_M22_INNING_MARKET"):
        read_inning_probability(
            d, market="RESULT_AFTER_INNING_4", selection="TIE")


def test_forged_distribution_or_nan_mass_refused():
    d = _build()
    with pytest.raises(InningJointError, match="INNING_JOINT_MASS_NOT_CONSERVED"):
        read_inning_probability(
            replace(d, joint_score_pmf={"0,0": 0.5}),
            market="INNING_3_3_WAY", selection="HOME")
    with pytest.raises(InningJointError, match="INVALID_INNING_JOINT_STATE"):
        read_inning_probability(
            replace(d, joint_score_pmf={"0,0": float("nan")}),
            market="INNING_3_3_WAY", selection="HOME")


@pytest.mark.parametrize("line", [0.0, 2.5, float("inf"), float("nan"), None])
def test_only_catalog_run_totals_accepted(line):
    with pytest.raises(InningJointError, match="INNING_RUNS_CATALOG_LINE_ONLY|INVALID_INNING_NUMERIC_LINE"):
        read_inning_probability(
            _build(), market="INNING_3_RUNS", selection="OVER", line=line)


def test_fixed_m30_requires_real_league_history_and_remains_research():
    with pytest.raises(InningJointError,
                       match="INSUFFICIENT_STRICTLY_PRIOR_LEAGUE_HISTORY"):
        _build(strength=30)
    big = _archive()
    # 100 additional unique prior completed games not involving target clubs.
    for k in range(100):
        row = deepcopy(big[k % len(big)])
        pk = 20000 + k
        row.update({
            "game_pk": pk, "away_team_id": 8000 + 2*k,
            "home_team_id": 8001 + 2*k,
            "source_payload_sha256": f"{pk:064x}",
        })
        big.append(row)
    d = _build(history=big, strength=30)
    assert d.league_history_halves >= 200
    assert d.eligible is False
    assert abs(sum(d.joint_score_pmf.values()) - 1) < 1e-12


def test_hash_binds_source_and_observations_order_independent():
    rows = _archive()
    a = _build(history=rows)
    b = _build(history=list(reversed(rows)))
    assert a.distribution_sha256 == b.distribution_sha256
    changed = deepcopy(rows)
    changed[0]["source_payload_sha256"] = "f" * 64
    c = _build(history=changed)
    assert c.distribution_sha256 != a.distribution_sha256
    read = read_inning_probability(
        a, market="INNING_3_3_WAY", selection="TIE")
    assert read.distribution_sha256 == a.distribution_sha256
    assert not hasattr(read, "odds_american")
    assert not hasattr(read, "ev_per_dollar")


def test_canonical_m22_row_not_promoted_or_overridden():
    from sportsedge.mlb_per_inning_gates import per_inning_blocked_row
    row = per_inning_blocked_row({
        "sport": "MLB", "market": "INNING_3_RUNS",
        "selection": "OVER", "line": 0.5})
    assert row["blocker"] == "NO_ENGINE"
    assert row["research_only"] is True
    assert row["per_inning_gate"] == "PER_INNING_DISTRIBUTION_UNBUILT"
