"""Synthetic-fixture battery for the CFB four-family evaluation harness.

Every fixture in this file is synthetic and generated in-memory. No real
game, line, or CFBD record is touched; no evaluation of real data is
performed or authorized by these tests. They prove the machinery of
``sportsedge/research/cfb_four_family_evaluation_v1.py``:

* the injury-neutral configuration is machine-checked and fails closed;
* fold construction is chronological with no train/test leakage;
* the CFBD descriptive label propagates and never becomes a verdict;
* verdict functions cap at the draft's ceilings and never change a
  family status (UNVALIDATED everywhere);
* PIT discipline is canary-tested;
* the shipped configuration refuses to run (rulings UNRULED, no freeze).
"""

from __future__ import annotations

import ast
import hashlib
import json
import random
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sportsedge.research import cfb_four_family_evaluation_v1 as harness
from sportsedge.research.cfb_four_family_evaluation_v1 import (
    CandidateGameInput,
    EvalConfig,
    ExternalFeature,
    FamilyProbabilities,
    FreezeManifest,
    GameLines,
    GameRecord,
    OwnerRulings,
    PredictionRecord,
    RatingsBaselineProducer,
    ScoredRow,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_CONFIG_PATH = (
    REPO_ROOT / "config" / "research" / "cfb_four_family_evaluation_v1.json"
)

DRAFT_RULINGS = OwnerRulings(
    candidate_mode="CAND_2_INJURY_NEUTRAL",
    cfbd_role="DESCRIPTIVE_ONLY",
    population_rule="EXCLUDE_FCS_OPPONENTS",
    fold_window="SEASONS_2021_2025",
)

SMALL = dict(
    fold_min_games=10,
    pooled_min_games=40,
    bootstrap_reps=400,
    bootstrap_seed=1234,
)


def small_config(**overrides) -> EvalConfig:
    cfg = EvalConfig(rulings=DRAFT_RULINGS, **{**SMALL, **overrides})
    cfg.validate()
    return cfg


def synthetic_freeze(**overrides) -> FreezeManifest:
    base = dict(
        freeze_sha="SYNTHETIC-TEST-ONLY-NOT-A-REAL-FREEZE",
        artifact_sha256="a" * 64,
        feature_schema_sha256="b" * 64,
        predictive_code_manifest_sha256="c" * 64,
        acquisition_code_manifest_sha256="d" * 64,
        policy_sha256="e" * 64,
        close_definition_id="SYNTHETIC",
    )
    base.update(overrides)
    return FreezeManifest(**base)


# ----------------------------------------------------------------------
# Synthetic slate generation
# ----------------------------------------------------------------------

FBS_TEAMS = [str(100 + i) for i in range(24)]
FCS_TEAM = "900"
IL_TEAM = "356"  # Illinois — in the frozen IL registry


def make_games(
    *,
    seed: int = 7,
    seasons=range(2013, 2026),
    games_per_season: int = 60,
    plant_specials: bool = True,
) -> tuple[list[GameRecord], dict[str, GameLines]]:
    """Deterministic synthetic slate. Latent strengths give the ratings
    machinery real signal; scores are noisy realizations of them."""
    rng = random.Random(seed)
    strength = {t: rng.gauss(0.0, 7.0) for t in FBS_TEAMS}
    games: list[GameRecord] = []
    lines: dict[str, GameLines] = {}
    for season in seasons:
        season_start = datetime(season, 9, 2, 17, 0, tzinfo=timezone.utc)
        for i in range(games_per_season):
            home, away = rng.sample(FBS_TEAMS, 2)
            kickoff = season_start + timedelta(days=7 * (i % 12), hours=i % 5)
            margin_mu = strength[home] - strength[away] + 2.5
            home_score = max(
                0, round(rng.gauss((55.0 + margin_mu) / 2.0, 10.0))
            )
            away_score = max(
                0, round(rng.gauss((55.0 - margin_mu) / 2.0, 10.0))
            )
            if home_score == away_score:
                home_score += 3  # FBS games cannot end tied
            gid = "%d-g%02d" % (season, i)
            games.append(
                GameRecord(
                    game_id=gid,
                    season=season,
                    week=(i % 12) + 1,
                    kickoff_utc=kickoff,
                    home_team_id=home,
                    away_team_id=away,
                    home_fbs=True,
                    away_fbs=True,
                    home_score=home_score,
                    away_score=away_score,
                )
            )
            total_points = home_score + away_score
            lines[gid] = GameLines(
                spread_home=float(rng.choice([-7.5, -3.5, -1.5, 2.5, 6.5])),
                total=float(rng.choice([44.5, 51.5, 57.5, 63.5])),
                team_total_home=float(rng.choice([20.5, 27.5, 34.5])),
                team_total_away=float(rng.choice([17.5, 24.5, 31.5])),
                home_moneyline=-150,
                away_moneyline=130,
            )
        if plant_specials:
            base = season_start + timedelta(days=84)
            specials = [
                # Illinois fixture — excluded before population counting.
                GameRecord(
                    "%d-il" % season, season, 13, base, IL_TEAM, FBS_TEAMS[0],
                    True, True, 21, 17,
                ),
                # FCS opponent — excluded under the draft population rule.
                GameRecord(
                    "%d-fcs" % season, season, 13,
                    base + timedelta(hours=1), FBS_TEAMS[1], FCS_TEAM,
                    True, False, 45, 10,
                ),
                # No-contest — excluded and counted.
                GameRecord(
                    "%d-nc" % season, season, 13,
                    base + timedelta(hours=2), FBS_TEAMS[2], FBS_TEAMS[3],
                    True, True, None, None, no_contest=True,
                ),
            ]
            games.extend(specials)
    return games, lines


def run_synthetic(cfg=None, games=None, lines=None, **kwargs):
    cfg = cfg or small_config()
    if games is None:
        games, lines = make_games()
    producer = RatingsBaselineProducer(cfg)
    return harness.run_historical_leg(
        games,
        lines,
        config=cfg,
        freeze=synthetic_freeze(),
        candidate=producer,
        **kwargs,
    )


def _walk(obj, path=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from _walk(value, "%s.%s" % (path, key))
    elif isinstance(obj, (list, tuple)):
        for idx, value in enumerate(obj):
            yield from _walk(value, "%s[%d]" % (path, idx))
    else:
        yield path, obj


def verdict_values(records):
    return [
        value
        for record in records
        for path, value in _walk(record)
        if path.endswith(".verdict") and value is not None
    ]


# ----------------------------------------------------------------------
# Configuration and the section 10 switches
# ----------------------------------------------------------------------


def test_shipped_config_loads_with_rulings_unruled_and_no_freeze():
    raw = json.loads(SHIPPED_CONFIG_PATH.read_text())
    assert raw["freeze_sha"] is None
    assert raw["status"] == "PREREGISTRATION_DRAFT_NOT_FILED_NOT_IN_FORCE"
    cfg = harness.load_config_json(SHIPPED_CONFIG_PATH.read_text())
    assert cfg.rulings.unresolved() == (
        "candidate_mode",
        "cfbd_role",
        "population_rule",
        "fold_window",
    )


def test_shipped_config_refuses_to_run_and_consumes_no_attempt():
    cfg = harness.load_config_json(SHIPPED_CONFIG_PATH.read_text())
    games, lines = make_games(seasons=range(2021, 2023), games_per_season=5)
    ledger = harness.AttemptLedger()
    result = harness.run_historical_leg(
        games,
        lines,
        config=cfg,
        freeze=synthetic_freeze(),
        candidate=RatingsBaselineProducer(cfg),
        ledger=ledger,
    )
    assert result.status == "NOT_RUN"
    assert result.reason == harness.NOT_RUN_OWNER_RULINGS_UNRESOLVED
    assert ledger.consumed == 0


def test_config_rejects_verdict_grade_cfbd_role_structurally():
    payload = json.loads(SHIPPED_CONFIG_PATH.read_text())
    payload["rulings"] = {
        "candidate_mode": "CAND_2_INJURY_NEUTRAL",
        "cfbd_role": "VERDICT_GRADE",
        "population_rule": "EXCLUDE_FCS_OPPONENTS",
        "fold_window": "SEASONS_2021_2025",
    }
    with pytest.raises(harness.ConfigError):
        harness.config_from_dict(payload)


def test_config_rejects_strengthened_cfbd_without_verification_steps():
    rulings = replace(
        DRAFT_RULINGS,
        cfbd_role="DESCRIPTIVE_STRENGTHENED",
        cfbd_verification_steps_completed=False,
    )
    with pytest.raises(harness.ConfigError):
        replace(small_config(), rulings=rulings).validate()


def test_config_accepts_strengthened_cfbd_with_verification_recorded():
    rulings = replace(
        DRAFT_RULINGS,
        cfbd_role="DESCRIPTIVE_STRENGTHENED",
        cfbd_verification_steps_completed=True,
    )
    cfg = replace(small_config(), rulings=rulings)
    cfg.validate()  # descriptive ceiling unchanged; no error


def test_resolve_config_applies_draft_recommendations():
    resolved = harness.resolve_config(small_config())
    assert resolved.evaluation_seasons == (2021, 2022, 2023, 2024, 2025)
    assert resolved.burn_in_seasons == tuple(range(2013, 2021))
    assert resolved.include_fcs_opponents is False
    assert resolved.candidate_mode == "CAND_2_INJURY_NEUTRAL"


def test_resolve_config_long_window_and_fcs_switches():
    rulings = replace(
        DRAFT_RULINGS,
        fold_window="SEASONS_2018_2025",
        population_rule="INCLUDE_FCS_OPPONENTS",
    )
    resolved = harness.resolve_config(replace(small_config(), rulings=rulings))
    assert resolved.evaluation_seasons == tuple(range(2018, 2026))
    assert resolved.burn_in_seasons == tuple(range(2013, 2018))
    assert resolved.include_fcs_opponents is True


# ----------------------------------------------------------------------
# Freeze gates (draft section 7 kill criteria)
# ----------------------------------------------------------------------


class ExplodingProducer:
    name = "MUST_NEVER_BE_CALLED"

    def family_probabilities(self, inp, lines):  # pragma: no cover
        raise AssertionError("scoring began despite a pre-scoring abort")


def test_unestablished_freeze_aborts_before_scoring():
    cfg = small_config()
    games, lines = make_games(seasons=range(2021, 2022), games_per_season=5)
    result = harness.run_historical_leg(
        games, lines, config=cfg, freeze=FreezeManifest(),
        candidate=ExplodingProducer(),
    )
    assert result.status == "NOT_RUN"
    assert result.reason == harness.NOT_RUN_FREEZE_NOT_ESTABLISHED


def test_freeze_hash_mismatch_aborts_before_parse_and_scoring():
    cfg = small_config()
    games, lines = make_games(seasons=range(2021, 2022), games_per_season=5)
    freeze = synthetic_freeze(file_hashes={"engine.py": "0" * 64})
    result = harness.run_historical_leg(
        games, lines, config=cfg, freeze=freeze,
        candidate=ExplodingProducer(),
        freeze_file_bytes={"engine.py": b"anything at all"},
    )
    assert result.status == "NOT_RUN"
    assert result.reason == harness.NOT_RUN_FREEZE_HASH_MISMATCH


def test_freeze_hash_match_lets_the_run_proceed():
    cfg = small_config()
    games, lines = make_games()
    blob = b"frozen engine bytes (synthetic)"
    freeze = synthetic_freeze(
        file_hashes={"engine.py": hashlib.sha256(blob).hexdigest()}
    )
    result = harness.run_historical_leg(
        games, lines, config=cfg, freeze=freeze,
        candidate=RatingsBaselineProducer(cfg),
        freeze_file_bytes={"engine.py": blob},
    )
    assert result.status == "SCORED"


def test_forward_only_candidate_disables_historical_leg():
    rulings = replace(DRAFT_RULINGS, candidate_mode="CAND_3_FORWARD_ONLY")
    cfg = replace(small_config(), rulings=rulings)
    games, lines = make_games(seasons=range(2021, 2022), games_per_season=5)
    result = harness.run_historical_leg(
        games, lines, config=cfg, freeze=synthetic_freeze(),
        candidate=ExplodingProducer(),
    )
    assert result.status == "NOT_RUN"
    assert result.reason == harness.NOT_RUN_FORWARD_ONLY_CANDIDATE


# ----------------------------------------------------------------------
# Neutrality guard (draft CAND-2): machine-checked, fail closed
# ----------------------------------------------------------------------

KICKOFF = datetime(2024, 9, 7, 17, 0, tzinfo=timezone.utc)


def _game(**overrides) -> GameRecord:
    base = dict(
        game_id="g1", season=2024, week=2, kickoff_utc=KICKOFF,
        home_team_id="100", away_team_id="101", home_fbs=True,
        away_fbs=True, home_score=28, away_score=24,
    )
    base.update(overrides)
    return GameRecord(**base)


def test_builder_neutralizes_poisoned_production_context():
    raw = {
        "home_injury_pts": 7.5,
        "away_injury_pts": 3.0,
        "home_form": 1.2,
        "away_form": -0.6,
        "rest_diff_adj": 0.8,
        "weather_total_adj": 2.0,
        "qb_context": 1.0,
        "home_rating": 4.0,
        "away_rating": 1.0,
    }
    inp = harness.build_candidate_input(
        _game(), home_rating=4.0, away_rating=1.0,
        home_advantage_points=2.5, raw_context=raw,
    )
    inp.validate_neutral()  # the constructed input is neutral
    assert inp.context["home_injury_pts"] == 0.0
    assert inp.context["away_injury_pts"] == 0.0
    assert inp.context["home_form"] == 0.0
    assert inp.context["rest_diff_adj"] == 0.0
    assert inp.context["weather_total_adj"] == 0.0
    assert "qb_context" not in inp.context
    assert set(inp.neutralized_fields) == {
        "home_injury_pts", "away_injury_pts", "home_form", "away_form",
        "rest_diff_adj", "weather_total_adj",
    }
    assert inp.omitted_fields == ("qb_context",)


def test_guard_refuses_nonzero_injury_points_reaching_the_model():
    inp = CandidateGameInput(
        game_id="g1",
        context={"home_rating": 0.0, "away_rating": 0.0,
                 "home_injury_pts": 3.0},
    )
    with pytest.raises(harness.NonNeutralInputError):
        inp.validate_neutral()


def test_guard_refuses_any_qb_context_key_present():
    for key in ("qb_context", "starting_qb", "qb1_identity",
                "availability_status"):
        inp = CandidateGameInput(
            game_id="g1",
            context={"home_rating": 0.0, "away_rating": 0.0, key: 0.0},
        )
        with pytest.raises(harness.NonNeutralInputError):
            inp.validate_neutral()


def test_guard_refuses_unlisted_context_key():
    inp = CandidateGameInput(
        game_id="g1",
        context={"home_rating": 0.0, "away_rating": 0.0, "coach_adj": 1.0},
    )
    with pytest.raises(harness.NonNeutralInputError):
        inp.validate_neutral()


def test_run_converts_a_neutrality_refusal_to_not_run(monkeypatch):
    poisoned = CandidateGameInput(
        game_id="x", context={"home_injury_pts": 9.0}
    )
    monkeypatch.setattr(
        harness, "build_candidate_input", lambda *a, **k: poisoned
    )
    ledger = harness.AttemptLedger()
    result = run_synthetic(ledger=ledger)
    assert result.status == "NOT_RUN"
    assert result.reason == harness.NOT_RUN_NEUTRALITY_GUARD_REFUSAL
    assert ledger.consumed == 0


# ----------------------------------------------------------------------
# Population, exclusions, settlement (draft sections 4.1 and 6.2)
# ----------------------------------------------------------------------


def test_population_exclusions_carry_the_drafts_reason_strings():
    games, _ = make_games(seasons=range(2024, 2025), games_per_season=10)
    resolved = harness.resolve_config(small_config())
    population, exclusions = harness.classify_population(games, resolved)
    reasons = {e.game_id: e.reason for e in exclusions}
    assert reasons["2024-il"] == "BLOCKED_PREPRICING_IL_COLLEGE_EXCLUDED"
    assert reasons["2024-fcs"] == "POPULATION_NON_FBS_OPPONENT"
    assert reasons["2024-nc"] == "GAME_NO_CONTEST_OR_CANCELLED"
    assert all(g.game_id not in reasons for g in population)
    assert len(population) == 10


def test_population_includes_fcs_games_only_under_the_include_ruling():
    games, _ = make_games(seasons=range(2024, 2025), games_per_season=10)
    rulings = replace(
        DRAFT_RULINGS, population_rule="INCLUDE_FCS_OPPONENTS"
    )
    resolved = harness.resolve_config(replace(small_config(), rulings=rulings))
    population, exclusions = harness.classify_population(games, resolved)
    assert any(g.game_id == "2024-fcs" for g in population)
    assert all(
        e.reason != "POPULATION_NON_FBS_OPPONENT" for e in exclusions
    )


def test_population_refuses_unresolved_team_identity():
    games = [_game(home_team_id=""), _game(game_id="g2")]
    resolved = harness.resolve_config(small_config())
    population, exclusions = harness.classify_population(games, resolved)
    assert [e.reason for e in exclusions] == ["BLOCK_TEAMS_UNRESOLVED"]
    assert [g.game_id for g in population] == ["g2"]


def test_integer_line_push_is_excluded_and_counted_not_scored():
    game = _game(home_score=31, away_score=28)  # margin exactly 3
    lines = GameLines(spread_home=-3.0, total=59.0)
    assert harness.grade_outcome(game, "spread", lines) is None
    assert harness.grade_outcome(game, "total", lines) is None
    result = run_synthetic()
    spread_records = [
        r for r in result.family_records if r["family"] == "spread"
    ]
    assert spread_records and "push_exclusions" in spread_records[0]
    assert (
        spread_records[0]["push_exclusion_reason"]
        == "PUSH_AT_INTEGER_LINE_EXCLUDED"
    )


# ----------------------------------------------------------------------
# Fold chronology, leakage canaries, PIT discipline (draft section 4.1)
# ----------------------------------------------------------------------


def test_fold_construction_is_chronological_no_future_leakage():
    """Canary: flipping a 2025 result must not move any 2021 prediction.
    If a later season's information leaked into an earlier fold, this
    fails."""
    games_a, lines = make_games()
    result_a = run_synthetic(games=games_a, lines=lines)
    assert result_a.status == "SCORED"

    games_b = []
    for game in games_a:
        if game.game_id == "2025-g00":
            game = replace(game, home_score=3, away_score=49)
        games_b.append(game)
    result_b = run_synthetic(games=games_b, lines=lines)

    def fold_2021(result):
        return {
            p.game_id: p.candidate
            for p in result.predictions
            if p.season == 2021
        }

    assert fold_2021(result_a) == fold_2021(result_b)
    assert fold_2021(result_a)  # the fold is non-empty


def test_selection_hook_sees_training_window_games_only():
    seen: dict[int, list[str]] = {}

    def hook(season, training_games):
        seen[season] = [g.game_id for g in training_games]

    games, lines = make_games()
    games_by_id = {g.game_id: g for g in games}
    result = run_synthetic(
        games=games, lines=lines, selection_hook=hook
    )
    assert result.status == "SCORED"
    assert set(seen) == {2021, 2022, 2023, 2024, 2025}
    for fold_season, ids in seen.items():
        assert ids, "selection must receive the training window"
        assert all(
            games_by_id[gid].season < fold_season for gid in ids
        ), "a validation-season game reached parameter selection"


def test_prediction_evidence_audit_passes_on_harness_output():
    result = run_synthetic()
    games, _ = make_games()
    harness.audit_prediction_evidence(
        result.predictions, {g.game_id: g for g in games}
    )  # no exception: every evidence game kicked off strictly earlier


def test_pit_canary_feature_available_after_kickoff_aborts_not_run():
    games, lines = make_games(seasons=range(2021, 2026),
                               games_per_season=20)
    target = next(g for g in games if g.game_id == "2023-g00")
    poison = ExternalFeature(
        game_id=target.game_id, name="future_result_leak", value=1.0,
        available_at=target.kickoff_utc + timedelta(hours=1),
    )
    ledger = harness.AttemptLedger()
    result = run_synthetic(
        games=games, lines=lines, external_features=[poison], ledger=ledger
    )
    assert result.status == "NOT_RUN"
    assert result.reason == harness.NOT_RUN_PIT_AUDIT_FAILURE
    assert ledger.consumed == 0


def test_pit_feature_available_before_kickoff_is_admitted():
    games, lines = make_games(seasons=range(2021, 2026),
                               games_per_season=20)
    target = next(g for g in games if g.game_id == "2023-g00")
    honest = ExternalFeature(
        game_id=target.game_id, name="schedule_fact", value=1.0,
        available_at=target.kickoff_utc - timedelta(hours=1),
    )
    result = run_synthetic(
        games=games, lines=lines, external_features=[honest]
    )
    assert result.status == "SCORED"


# ----------------------------------------------------------------------
# End-to-end synthetic run: invariants, determinism, attempt accounting
# ----------------------------------------------------------------------


def test_end_to_end_run_invariants_and_attempt_consumption():
    ledger = harness.AttemptLedger()
    result = run_synthetic(ledger=ledger)
    assert result.status == "SCORED"
    assert ledger.consumed == 1 and result.attempts_consumed == 1
    assert {r["family"] for r in result.family_records} == set(
        harness.FAMILIES
    )
    for record in result.all_records():
        assert record["family_status"] == "UNVALIDATED"
        assert record["status_change"] == "NONE"
        assert (
            record["evaluated_object"]
            == "frozen CFB game engine, injury-neutral evaluation "
            "configuration"
        )
    for verdict in verdict_values(result.all_records()):
        assert verdict in harness.ALL_VERDICT_LABELS


def test_identical_inputs_produce_byte_identical_result_hash():
    first = run_synthetic()
    second = run_synthetic()
    assert first.result_hash() == second.result_hash()


def test_thin_fold_marks_family_not_run_but_program_scores():
    games, lines = make_games()
    trimmed = dict(lines)
    for gid, gl in lines.items():
        if gid.startswith("2023") and not gid.endswith(("g00", "g01")):
            trimmed[gid] = replace(
                gl, team_total_home=None, team_total_away=None
            )
    result = run_synthetic(games=games, lines=trimmed)
    assert result.status == "SCORED"
    team_total = next(
        r for r in result.family_records if r["family"] == "team_total"
    )
    assert team_total["verdict"] is None
    assert team_total["not_run_reason"] == harness.NOT_RUN_FOLD_BELOW_MINIMUM


def test_two_thin_families_abort_the_program_not_run():
    games, lines = make_games()
    trimmed = dict(lines)
    for gid, gl in lines.items():
        if gid.startswith("2023") and not gid.endswith(("g00", "g01")):
            trimmed[gid] = replace(
                gl, team_total_home=None, team_total_away=None,
                total=None,
            )
    ledger = harness.AttemptLedger()
    result = run_synthetic(games=games, lines=trimmed, ledger=ledger)
    assert result.status == "NOT_RUN"
    assert result.reason == harness.NOT_RUN_PROGRAM_ABORT
    assert ledger.consumed == 0


# ----------------------------------------------------------------------
# Metrics and bootstrap units
# ----------------------------------------------------------------------


def test_metric_known_values():
    assert harness.brier(0.8, 1.0) == pytest.approx(0.04)
    assert harness.log_loss(0.5, 1.0, 1e-15) == pytest.approx(0.693147, abs=1e-6)


def test_cover_probability_push_band_is_symmetric():
    # Pick'em at an integer threshold with a centered distribution:
    # decisive outcomes split evenly after the push band is removed.
    assert harness._cover_probability(0.0, 19.0, 0.0) == pytest.approx(
        0.5, abs=1e-9
    )
    assert harness._cover_probability(10.0, 19.0, -7.5) > 0.5


def test_bootstrap_is_deterministic_and_brackets_the_point_estimate():
    rows = [
        ScoredRow("g%d" % i, "moneyline", 2024, "2024:%d" % (i % 4),
                  0.9 if i % 2 else 0.1, 0.55, 1.0 if i % 2 else 0.0)
        for i in range(40)
    ]
    first = harness.cluster_bootstrap_ci(
        rows, lambda r: r.delta_brier(), reps=400, seed=99
    )
    second = harness.cluster_bootstrap_ci(
        rows, lambda r: r.delta_brier(), reps=400, seed=99
    )
    assert first == second
    point, lo, hi = first
    assert lo <= point <= hi and hi < 0.0


# ----------------------------------------------------------------------
# Historical verdict function (draft section 5.4)
# ----------------------------------------------------------------------


def _verdict_rows(*, candidate_better: bool, n_per_fold: int = 60):
    rows = []
    for season in (2021, 2022, 2023, 2024, 2025):
        for i in range(n_per_fold):
            outcome = 1.0 if i % 2 == 0 else 0.0
            sharp, dull = (0.9, 0.6) if outcome else (0.1, 0.4)
            p_cand, p_base = (
                (sharp, dull) if candidate_better else (dull, sharp)
            )
            rows.append(
                ScoredRow(
                    "%d-%d" % (season, i), "moneyline", season,
                    "%d:%d" % (season, i % 6), p_cand, p_base, outcome,
                )
            )
    return rows


def test_verdict_beats_frozen_baseline_and_changes_no_status():
    cfg = small_config()
    record = harness.historical_verdict(
        "moneyline", _verdict_rows(candidate_better=True),
        config=cfg, scored_fraction=1.0,
    )
    assert record["verdict"] == "BEATS_FROZEN_BASELINE"
    assert record["family_status"] == "UNVALIDATED"
    assert record["status_change"] == "NONE"
    assert record["folds_better_on_both_metrics"] == 5


def test_verdict_worse_than_frozen_baseline():
    record = harness.historical_verdict(
        "moneyline", _verdict_rows(candidate_better=False),
        config=small_config(), scored_fraction=1.0,
    )
    assert record["verdict"] == "WORSE_THAN_FROZEN_BASELINE"


def test_verdict_inconclusive_when_candidate_equals_baseline():
    rows = [
        replace(r, p_candidate=r.p_comparator)
        for r in _verdict_rows(candidate_better=True)
    ]
    record = harness.historical_verdict(
        "moneyline", rows, config=small_config(), scored_fraction=1.0
    )
    assert record["verdict"] == "INCONCLUSIVE"


def test_verdict_coverage_presumption_overrides_metrics():
    record = harness.historical_verdict(
        "moneyline", _verdict_rows(candidate_better=True),
        config=small_config(), scored_fraction=0.50,
    )
    assert record["verdict"] == "INCONCLUSIVE (COVERAGE)"


def test_verdict_below_sample_floor_is_not_run_not_failed():
    record = harness.historical_verdict(
        "moneyline", _verdict_rows(candidate_better=True, n_per_fold=5),
        config=small_config(), scored_fraction=1.0,
    )
    assert record["verdict"] is None
    assert record["not_run_reason"] == harness.NOT_RUN_INSUFFICIENT_BOUND_DATA


# ----------------------------------------------------------------------
# Descriptive CFBD comparison (draft sections 2.1, 5.3, 5.4)
# ----------------------------------------------------------------------


def _predictions(games, lines, cfg):
    producer = RatingsBaselineProducer(cfg)
    out = []
    for game in games:
        if game.game_id not in lines or not game.decided:
            continue
        inp = harness.build_candidate_input(
            game, home_rating=3.0, away_rating=0.0,
            home_advantage_points=2.5,
        )
        out.append(
            PredictionRecord(
                game.game_id, game.season, game.week,
                producer.family_probabilities(inp, lines[game.game_id]),
                producer.family_probabilities(inp, lines[game.game_id]),
                (),
            )
        )
    return out


def test_descriptive_records_carry_the_label_and_no_verdict():
    cfg = small_config()
    games, lines = make_games(seasons=range(2024, 2025), games_per_season=8)
    games_by_id = {g.game_id: g for g in games}
    predictions = _predictions(games, lines, cfg)
    for family in ("moneyline", "spread", "total"):
        record = harness.descriptive_market_comparison(
            family, predictions, games_by_id, lines, config=cfg
        )
        assert record["verdict"] is None
        assert (
            record["comparison_label"]
            == "DESCRIPTIVE_MARKET_COMPARISON_NOT_A_VERDICT"
        )
        assert "no per-row timestamps" in record["label_text"]
        assert record["n"] > 0
    assert (
        harness.descriptive_market_comparison(
            "moneyline", predictions, games_by_id, lines, config=cfg
        )["construction"]
        == "NO_VIG_PROPORTIONAL_FROM_CFBD_MONEYLINES"
    )
    assert (
        harness.descriptive_market_comparison(
            "spread", predictions, games_by_id, lines, config=cfg
        )["construction"]
        == "IMPLIED_PARITY_AT_CFBD_LINE_NOT_A_PRICED_PAIR"
    )


def test_descriptive_team_total_has_no_market_comparator():
    cfg = small_config()
    games, lines = make_games(seasons=range(2024, 2025), games_per_season=4)
    games_by_id = {g.game_id: g for g in games}
    record = harness.descriptive_market_comparison(
        "team_total", _predictions(games, lines, cfg),
        games_by_id, lines, config=cfg,
    )
    assert record["market_comparator"] == "NO_HISTORICAL_MARKET_COMPARATOR"
    assert "delta_brier" not in record
    assert record["verdict"] is None
    assert (
        record["comparison_label"]
        == "DESCRIPTIVE_MARKET_COMPARISON_NOT_A_VERDICT"
    )


def test_descriptive_label_propagates_through_a_full_run():
    result = run_synthetic()
    assert len(result.descriptive_records) == 4
    for record in result.descriptive_records:
        blob = json.dumps(record)
        assert "DESCRIPTIVE_MARKET_COMPARISON_NOT_A_VERDICT" in blob
        assert record["verdict"] is None


# ----------------------------------------------------------------------
# Forward verdict (draft section 5.5): the program ceiling
# ----------------------------------------------------------------------


def _forward_rows(*, candidate_better=True, games=320, blocks=24):
    rows = []
    for i in range(games):
        outcome = 1.0 if i % 2 == 0 else 0.0
        sharp, dull = (0.9, 0.6) if outcome else (0.1, 0.4)
        p_cand, p_mkt = (sharp, dull) if candidate_better else (dull, sharp)
        rows.append(
            ScoredRow(
                "fg%03d" % i, "moneyline", 2027, "2027:%d" % (i % blocks),
                p_cand, p_mkt, outcome,
            )
        )
    return rows


def _forward_config():
    return replace(
        small_config(), forward_target_games=300, forward_target_blocks=20
    )


def test_forward_below_target_is_accrual_only_never_a_verdict():
    record = harness.forward_verdict(
        "moneyline", _forward_rows(games=120), config=_forward_config()
    )
    assert record["verdict"] is None
    assert record["label"] == "ACCRUAL_ONLY_NOT_A_VERDICT"


def test_forward_at_target_can_reach_the_program_ceiling():
    record = harness.forward_verdict(
        "moneyline", _forward_rows(), config=_forward_config()
    )
    assert record["verdict"] == "DEMONSTRATED_EDGE_RESEARCH_ONLY"
    assert record["family_status"] == "UNVALIDATED"
    assert record["status_change"] == "NONE"


def test_forward_at_target_worse_is_refuted():
    record = harness.forward_verdict(
        "moneyline", _forward_rows(candidate_better=False),
        config=_forward_config(),
    )
    assert record["verdict"] == "REFUTED"


def test_forward_method_sensitive_sign_is_inconclusive():
    rows = _forward_rows()
    flipped = [replace(r, p_candidate=r.p_comparator,
                       p_comparator=r.p_candidate) for r in rows]
    record = harness.forward_verdict(
        "moneyline", rows, config=_forward_config(),
        sensitivity_rows=flipped,
    )
    assert record["verdict"] == "INCONCLUSIVE"
    assert record["method_sensitive"] is True


def test_forward_extension_is_single_and_requires_favorable_points():
    cfg = _forward_config()
    rows = [
        replace(r, p_candidate=0.62 if r.outcome else 0.38,
                p_comparator=0.60 if r.outcome else 0.40)
        for r in _forward_rows()
    ]
    record = harness.forward_verdict("moneyline", rows, config=cfg)
    if record["verdict"] == "INCONCLUSIVE":
        assert harness.forward_extension_available(
            record, config=cfg, already_extended=False
        )
        assert not harness.forward_extension_available(
            record, config=cfg, already_extended=True
        )


# ----------------------------------------------------------------------
# Ceiling scan and module hygiene
# ----------------------------------------------------------------------


def test_no_verdict_anywhere_exceeds_the_program_ceiling():
    result = run_synthetic()
    fwd = harness.forward_verdict(
        "moneyline", _forward_rows(), config=_forward_config()
    )
    all_records = result.all_records() + [fwd]
    emitted = set(verdict_values(all_records))
    assert emitted <= harness.ALL_VERDICT_LABELS
    forbidden_fragments = ("VALIDATED_EDGE", "PLAY", "DEPLOYMENT_ELIGIBLE")
    for verdict in emitted:
        assert not any(f in verdict for f in forbidden_fragments)
    for record in all_records:
        assert record["family_status"] == "UNVALIDATED"


def test_module_has_no_network_subprocess_or_io_imports():
    source = Path(harness.__file__).read_text()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    banned = {
        "socket", "urllib", "requests", "http", "subprocess", "os",
        "sys", "pathlib", "io", "shutil",
    }
    assert imported & banned == set()
    assert "ACTIVATION" not in source or "NOT ACTIVATED" in source
