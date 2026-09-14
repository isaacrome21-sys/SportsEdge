from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sportsedge.dfs.contest import ContestStructure, evaluate_candidate_ev
from sportsedge.dfs.field import FieldGenerationConfig, GeneratedField, generate_field, lineup_key
from sportsedge.dfs.objective import DEFAULT_OBJECTIVE_WEIGHTS, ObjectiveWeights
from sportsedge.dfs.rules import get_rules
from sportsedge.dfs.score_paths import AlignedScorePaths, load_aligned_score_paths
from sportsedge.dfs.tuning import BacktestMetrics, HistoricalSlate, chronological_holdout_tune
from sportsedge.dfs.types import DKPlayer, Projection


def _p(pid: str, team: str, opp: str, pos: str, salary: int, mean: float, own: float):
    player = DKPlayer(pid, pid, team, opp, (pos,), salary)
    proj = Projection(pid, mean, mean * 1.5, ownership=own, source="TEST")
    return player, proj


def test_field_generation_is_seeded_correlated_and_counts_duplicates() -> None:
    rows = [
        _p("qa", "A", "B", "QB", 6500, 22, .18), _p("qb", "B", "A", "QB", 6200, 20, .15),
        _p("r1", "A", "B", "RB", 7000, 19, .22), _p("r2", "B", "A", "RB", 6500, 18, .20), _p("r3", "C", "D", "RB", 5200, 14, .12),
        _p("w1", "A", "B", "WR", 7000, 20, .19), _p("w2", "A", "B", "WR", 5200, 15, .14), _p("w3", "B", "A", "WR", 6100, 17, .17), _p("w4", "C", "D", "WR", 4700, 13, .10),
        _p("t1", "A", "B", "TE", 4000, 12, .11), _p("t2", "B", "A", "TE", 3600, 10, .08),
        _p("d1", "C", "D", "DST", 3000, 8, .09), _p("d2", "D", "C", "DST", 2800, 7, .07),
    ]
    players = [x[0] for x in rows]
    projections = {x[0].player_id: x[1] for x in rows}
    config = FieldGenerationConfig(field_size=40, seed=42, min_salary=40_000, max_attempt_multiplier=500)
    a = generate_field("NFL", get_rules("NFL"), players, projections, config)
    b = generate_field("NFL", get_rules("NFL"), players, projections, config)
    assert a.counts == b.counts
    assert sum(a.counts.values()) == 40
    assert a.unique_lineups <= 40
    assert a.duplicate_entries == 40 - a.unique_lineups


def test_contest_ev_splits_duplicate_first_place_prizes() -> None:
    config = FieldGenerationConfig(field_size=2, seed=1, min_salary=0)
    candidate = ("a", "b")
    field = GeneratedField(
        counts={tuple(sorted(candidate)): 1, ("c", "d"): 1},
        salaries={tuple(sorted(candidate)): 10000, ("c", "d"): 10000},
        field_size=2,
        unique_lineups=2,
        duplicate_entries=0,
        attempts=2,
        config=config,
        ownership_coverage=1.0,
    )
    paths = AlignedScorePaths(
        sport="NFL",
        path_set_id="joint-1",
        path_count=1000,
        player_scores={
            "a": (10.0,) * 1000,
            "b": (10.0,) * 1000,
            "c": (5.0,) * 1000,
            "d": (5.0,) * 1000,
        },
        source="TEST",
    )
    contest = ContestStructure(field_size=3, entry_fee=10.0, payouts=(100.0, 50.0, 0.0))
    result = evaluate_candidate_ev(candidate=candidate, field=field, contest=contest, score_paths=paths)
    assert result.candidate_duplication == 2
    assert result.mean_gross_payout == 75.0
    assert result.mean_profit == 65.0
    assert result.first_place_or_tied_rate == 1.0


def test_aligned_path_loader_preserves_joint_path_index(tmp_path) -> None:
    player_a = DKPlayer("a", "A", "AAA", "BBB", ("WR",), 5000)
    player_b = DKPlayer("b", "B", "AAA", "BBB", ("WR",), 5000)
    rows_a = [{"dk_points": float(i % 2)} for i in range(1000)]
    rows_b = [{"dk_points": float(1 - (i % 2))} for i in range(1000)]
    import json
    path = tmp_path / "paths.json"
    path.write_text(json.dumps({
        "path_set_id": "joint-x",
        "source": "TEST",
        "players": [
            {"player_id": "a", "samples": rows_a},
            {"player_id": "b", "samples": rows_b},
        ],
    }), encoding="utf-8")
    loaded = load_aligned_score_paths(path, [player_a, player_b], "NFL")
    assert loaded.path_count == 1000
    assert loaded.lineup_scores(["a", "b"]) == (1.0,) * 1000


def _history(n: int = 30):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return tuple(
        HistoricalSlate(f"s{i:02d}", base + timedelta(days=i), f"/frozen/s{i:02d}.json")
        for i in range(n)
    )


def test_tuning_blocks_train_winner_that_fails_holdout_roi() -> None:
    baseline = DEFAULT_OBJECTIVE_WEIGHTS
    candidate = ObjectiveWeights(version="CANDIDATE", upside_weight=.44)

    def evaluator(weights, slates):
        is_holdout = int(slates[0].slate_id[1:]) >= 22
        if weights.version == "CANDIDATE":
            return BacktestMetrics(len(slates), .30 if not is_holdout else .09, .08, .22, .18)
        return BacktestMetrics(len(slates), .10, .05, .20, .17)

    result = chronological_holdout_tune(
        slates=_history(), baseline=baseline, candidates=[candidate], evaluator=evaluator,
        min_holdout_slates=8,
    )
    assert not result.promoted
    assert result.selected.digest() == baseline.digest()
    assert "ROI" in result.reason


def test_tuning_promotes_only_when_roi_top1_and_drawdown_all_pass() -> None:
    baseline = DEFAULT_OBJECTIVE_WEIGHTS
    candidate = ObjectiveWeights(version="CANDIDATE_PASS", upside_weight=.44)

    def evaluator(weights, slates):
        is_holdout = int(slates[0].slate_id[1:]) >= 22
        if weights.version == "CANDIDATE_PASS":
            return BacktestMetrics(len(slates), .30 if not is_holdout else .13, .065, .22, .18)
        return BacktestMetrics(len(slates), .10, .05, .20, .17)

    result = chronological_holdout_tune(
        slates=_history(), baseline=baseline, candidates=[candidate], evaluator=evaluator,
        min_holdout_slates=8,
    )
    assert result.promoted
    assert result.selected.version == "CANDIDATE_PASS"
    assert result.reason == "HOLDOUT_PASS"
