"""Adversarial nested-sigma / fold-discipline leakage verification for
NFL_SCORE_COUNTS_G2 attempt 2 (issue #2218 M3 directive, Oct 14 2026).

Attempt 2 remains NO-GO and unspent. Every dataset here is the existing
synthetic battery's seeded fixture universe; nothing reads real game
data, touches the network, or opens any holdout path. The frozen code
under test is commit 2f3af2a2 (Amendment 2: nested training-window-only
sigma selection; preregistration section 6 governs, section 2.5 as
amended; K3 per section 4).

WHAT THIS ADDS over the existing battery (tests/
test_nfl_score_counts_g2_attempt2.py):

* The existing driver-level sigma test perturbs only the LAST
  validation season (a training season for no fold) and only PERMUTES
  its outcomes (the season's outcome multiset is unchanged). This file
  REPLACES the outcomes of a MIDDLE validation season (2022, with
  folds 2021/2022/2023) with different synthetic values drawn from a
  different-seed universe, so the season's outcome distribution itself
  changes -- and 2022 IS a training season for the later fold (2023),
  which makes the identity assertions scoped rather than global.
* It asserts bit-identity of the PREDICTIONS issued for the perturbed
  season and every earlier season (per-game candidate PMFs, rebuilt
  through the driver's own fold machinery), not only of the fitted
  parameter records.
* Non-vacuity is asserted, not assumed: the later fold (2023), whose
  training window legitimately contains the perturbed season, MUST
  change its fitted values; if it does not, the perturbation was
  impotent and this suite fails loudly.

PERTURBATION SCOPE, and why it is exactly the final kickoff batch of
2022: within a validation season, one legitimate causal channel exists
-- the rare-score PIT rates (fold_rare_rates) process the season's
games in kickoff batches, so a game's rare rates may depend on the
outcomes of games at STRICTLY EARLIER kickoffs in the same season
(preregistration section 6 PIT discipline: team history updates only
after a prior game completes). Replacing only the FINAL kickoff
batch's outcomes keeps every 2022 prediction's inputs strictly prior
to, or uninfluenced by, the replaced values: the perturbed games' own
candidate PMFs consume their rows' feature/band-snapshot fields (not
replaced), rare rates computed from the pre-batch state, and
fold-fitted quantities (bundle, sigma, K3 lambda) that are functions
of training rows only. Scoring quantities for 2022 (log scores, PITs,
gate accumulators) DO legitimately change, because scoring consumes
realized outcomes; they are not predictions and are not asserted.
"""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pytest

from sportsedge.research import nfl_score_counts_g2_v2 as m
from sportsedge.research import nfl_score_counts_g2_eval_v2 as ev

REPO_ROOT = Path(__file__).resolve().parents[1]

# The existing battery module is loaded by path so this file exercises
# EXACTLY the same synthetic fixture universe (same factory, same
# _OUTCOME_KEYS contract) rather than a re-implementation of it.
_spec = importlib.util.spec_from_file_location(
    "g2_attempt2_battery",
    REPO_ROOT / "tests" / "test_nfl_score_counts_g2_attempt2.py")
battery = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(battery)

SEASONS = (2018, 2019, 2020, 2021, 2022, 2023)
VALIDATION_SEASONS = (2021, 2022, 2023)
PERTURBED_SEASON = 2022
PATHS = 10000  # the driver's scored minimum; same as the battery fixture

# Outcome fields replaced on the perturbed games: the battery's
# _OUTCOME_KEYS, plus the FG-attempt accounting fields that are
# deterministic functions of the band counts (kept consistent with the
# donor row so later folds train on coherent rows).
_REPLACE_KEYS = list(battery._OUTCOME_KEYS) + [
    "fg_attempts_with_distance", "fg_attempts_missing_distance",
    "fg_makes_missing_distance", "fg_attempts_total",
]


def _final_batch_game_ids(rows, season):
    """Game ids in the season's last kickoff batch (max game_start_ts)."""
    season_rows = [r for r in rows if int(r["season"]) == season]
    last_ts = max(str(r["game_start_ts"]) for r in season_rows)
    return {str(r["game_id"]) for r in season_rows
            if str(r["game_start_ts"]) == last_ts}


def _replace_final_batch_outcomes(rows, season, donor_rows):
    """Replace (not permute) the outcome fields of the season's final
    kickoff batch with the donor universe's outcomes for the same
    (game_id, team). Feature and PIT-snapshot fields are never touched."""
    donor = {(str(r["game_id"]), str(r["team"])): r for r in donor_rows}
    targets = _final_batch_game_ids(rows, season)
    out = []
    for r in rows:
        r2 = dict(r)
        if int(r["season"]) == season and str(r["game_id"]) in targets:
            src = donor[(str(r["game_id"]), str(r["team"]))]
            for k in _REPLACE_KEYS:
                v = src[k]
                r2[k] = list(v) if isinstance(v, list) else v
        out.append(r2)
    return out


def _pmf_digest(pmf) -> str:
    canonical = json.dumps(
        [[h, a, p] for (h, a), p in sorted(pmf.items())],
        separators=(",", ":")).encode("utf-8")
    return sha256(canonical).hexdigest()


def _fold_predictions(rows, season, paths=PATHS):
    """Rebuild one fold's issued predictions through the driver's own
    machinery (eval driver Pass 1 / 1.5 / 2 construction, in order):
    fit_fold_bundle on the training slice -> nested sigma selection on
    the training slice -> fold rare rates -> K3 estimation from the
    TRAINING games -> per-game candidate PMFs for the validation games.

    Returns the fold's fitted-values digest (bundle incl. K3 lambdas),
    the selected sigma and its full selection detail, the K3 lambdas,
    and the per-game candidate-PMF digests."""
    train = [r for r in rows if int(r["season"]) < season]
    valid = [r for r in rows if int(r["season"]) == season]
    bundle = m.fit_fold_bundle(train, m.V2_CONFIG)
    sigma, sigma_detail = m.select_sigma_nested_v2(train, bundle)
    eval_rates, train_rates = m.fold_rare_rates(bundle, train, valid)
    train_map = {(str(r["game_id"]), str(r["team"])): train_rates[i]
                 for i, r in enumerate(train)}
    eval_map = {(str(r["game_id"]), str(r["team"])): eval_rates[i]
                for i, r in enumerate(valid)}
    skeleton_pmfs: list[dict] = []
    realized_margins: list[int] = []
    for gid, (home, away) in sorted(m.game_pairs(train).items()):
        if not (m.row_has_band_context(home, m.V2_CONFIG)
                and m.row_has_band_context(away, m.V2_CONFIG)):
            continue  # ZERO_MODEL_ROW: excluded from estimation (driver)
        sim = m.simulate_full_game_v2(
            bundle, game_id=gid, home_row=home, away_row=away,
            home_rates=train_map[(gid, str(home["team"]))],
            away_rates=train_map[(gid, str(away["team"]))],
            sigma=sigma, paths=paths)
        skeleton_pmfs.append(m.pmf_from_counts(
            m.pmf_counts(sim["home_score"], sim["away_score"]), paths))
        realized_margins.append(
            m.realized_final_score(home) - m.realized_final_score(away))
    k3 = m.estimate_k3_lambdas(skeleton_pmfs, realized_margins)
    bundle["k3"] = k3
    pmf_digests: dict[str, str] = {}
    for gid, (home, away) in sorted(m.game_pairs(valid).items()):
        if not (m.row_has_band_context(home, m.V2_CONFIG)
                and m.row_has_band_context(away, m.V2_CONFIG)):
            continue  # ZERO_MODEL_ROW games are not issued predictions
        sim = m.simulate_full_game_v2(
            bundle, game_id=gid, home_row=home, away_row=away,
            home_rates=eval_map[(gid, str(home["team"]))],
            away_rates=eval_map[(gid, str(away["team"]))],
            sigma=sigma, paths=paths)
        skeleton = m.pmf_from_counts(
            m.pmf_counts(sim["home_score"], sim["away_score"]), paths)
        candidate = m.apply_k3(skeleton, k3["lambdas"])
        pmf_digests[gid] = _pmf_digest(candidate)
    return {
        "fitted_digest": m.fitted_values_digest(bundle),
        "sigma": sigma,
        "sigma_detail": sigma_detail,
        "lambdas": k3["lambdas"],
        "pmf_digests": pmf_digests,
    }


@pytest.fixture(scope="module")
def arms():
    rows = battery.enriched_universe(seasons=SEASONS, rounds_per_season=6)
    donor = battery.enriched_universe(seed=777, seasons=SEASONS,
                                      rounds_per_season=6)
    corrupted = _replace_final_batch_outcomes(rows, PERTURBED_SEASON, donor)
    eval_clean = ev.run_development_evaluation_v2(
        rows, paths=PATHS, validation_seasons=VALIDATION_SEASONS,
        fold_min_games=10)
    eval_corrupt = ev.run_development_evaluation_v2(
        corrupted, paths=PATHS, validation_seasons=VALIDATION_SEASONS,
        fold_min_games=10)
    folds_clean = {s: _fold_predictions(rows, s) for s in VALIDATION_SEASONS}
    folds_corrupt = {s: _fold_predictions(corrupted, s)
                     for s in VALIDATION_SEASONS}
    return {
        "rows": rows, "corrupted": corrupted,
        "eval_clean": eval_clean, "eval_corrupt": eval_corrupt,
        "folds_clean": folds_clean, "folds_corrupt": folds_corrupt,
    }


def test_perturbation_is_real_and_scoped(arms):
    """The adversary actually changed the perturbed games' outcomes,
    changed nothing else anywhere, and left every row's feature /
    PIT-snapshot fields untouched."""
    rows, corrupted = arms["rows"], arms["corrupted"]
    assert len(rows) == len(corrupted)
    targets = _final_batch_game_ids(rows, PERTURBED_SEASON)
    assert targets  # the season has a final kickoff batch
    changed_games = set()
    realized_changed = False
    for clean, corr in zip(rows, corrupted):
        assert clean["game_id"] == corr["game_id"]
        assert clean["season"] == corr["season"]
        non_outcome = {k: v for k, v in clean.items()
                       if k not in _REPLACE_KEYS}
        assert {k: v for k, v in corr.items()
                if k not in _REPLACE_KEYS} == non_outcome
        if str(clean["game_id"]) in targets:
            changed_games.add(str(clean["game_id"]))
            if any(corr[k] != clean[k] for k in _REPLACE_KEYS):
                pass  # per-row difference recorded below at game level
            if m.realized_final_score(corr) != m.realized_final_score(clean):
                realized_changed = True
        else:
            assert corr == clean  # every other row fully identical
    assert changed_games == targets
    # At least one perturbed game's realized score actually moved: the
    # replacement is not a no-op relabeling.
    assert realized_changed


def test_driver_fitted_parameters_invariant_for_perturbed_and_earlier_folds(arms):
    """Driver level: for the perturbed season's fold and every earlier
    fold, the issued fitted-parameter records (alphas, thetas, rare
    prior, sigma, full sigma-selection detail, K3 lambdas + detail) are
    bit-identical between the clean and perturbed runs."""
    clean, corr = arms["eval_clean"], arms["eval_corrupt"]
    for season in (2021, PERTURBED_SEASON):
        key = str(season)
        assert corr["sigma_by_fold"][key] == clean["sigma_by_fold"][key]
        assert corr["sigma_selection"][key] == clean["sigma_selection"][key]
        assert corr["k3_folds"][key] == clean["k3_folds"][key]
    meta_clean = {f["validation_season"]: f for f in clean["fold_meta"]}
    meta_corr = {f["validation_season"]: f for f in corr["fold_meta"]}
    for season in (2021, PERTURBED_SEASON):
        assert meta_corr[season] == meta_clean[season]
    # The earlier fold's scored joint row is also identical: its
    # predictions AND its realized outcomes are both untouched.
    joint_clean = {f["validation_season"]: f
                   for f in clean["gates"]["G_JOINT"]
                   ["baseline_i_league_empirical_pmf"]["folds"]}
    joint_corr = {f["validation_season"]: f
                  for f in corr["gates"]["G_JOINT"]
                  ["baseline_i_league_empirical_pmf"]["folds"]}
    assert joint_corr[2021] == joint_clean[2021]
    assert clean["sigma_selection_rule"] == \
        "AMENDMENT_2_NESTED_TRAINING_WINDOW_ONLY"


def test_nested_sigma_selection_invariant_under_perturbation(arms):
    """The headline Amendment 2 claim, at the selector level: the
    nested sigma selection for the perturbed season's fold -- selected
    sigma, the full per-candidate MSE table, and the inner-fold
    structure -- is a function of the training window only. Same for
    the earlier fold."""
    for season in (2021, PERTURBED_SEASON):
        a = arms["folds_clean"][season]
        b = arms["folds_corrupt"][season]
        assert b["sigma"] == a["sigma"]
        assert b["sigma_detail"] == a["sigma_detail"]
        assert b["sigma_detail"]["selection_rule"] == \
            "AMENDMENT_2_NESTED_TRAINING_WINDOW_ONLY"
        inner_seasons = [f["inner_validation_season"]
                         for f in a["sigma_detail"]["inner_folds"]]
        assert inner_seasons == [s for s in SEASONS if s < season][1:]


def test_k3_lambdas_invariant_under_perturbation(arms):
    """K3 (section 4.3): the fitted key-number lambdas for the perturbed
    season's fold and the earlier fold are estimated from training
    games only and are bit-identical under the perturbation."""
    for season in (2021, PERTURBED_SEASON):
        a = arms["folds_clean"][season]
        b = arms["folds_corrupt"][season]
        assert b["lambdas"] == a["lambdas"]
        for lam in a["lambdas"].values():
            assert 0.0 <= lam <= 0.50


def test_predictions_issued_for_perturbed_and_earlier_seasons_bit_identical(arms):
    """Per-game candidate PMFs issued for the perturbed season --
    INCLUDING the perturbed games themselves -- and for the earlier
    season are bit-identical between the clean and perturbed runs.
    A game's prediction may not depend on its own outcome, on any
    same-batch outcome, or on any outcome at a later kickoff."""
    for season in (2021, PERTURBED_SEASON):
        a = arms["folds_clean"][season]
        b = arms["folds_corrupt"][season]
        assert a["pmf_digests"], "fold issued no predictions"
        assert b["pmf_digests"] == a["pmf_digests"]
        assert b["fitted_digest"] == a["fitted_digest"]
    # The perturbed games are inside the asserted set, by name.
    targets = _final_batch_game_ids(arms["rows"], PERTURBED_SEASON)
    assert targets <= set(arms["folds_clean"][PERTURBED_SEASON]["pmf_digests"])


def test_later_fold_legitimately_changes_nonvacuity(arms):
    """Non-vacuity: the NEXT fold (2023) trains on the perturbed season,
    so its fitted values MUST change. If they did not, the perturbation
    would be impotent and every identity assertion above would be
    vacuous; this test fails in that case."""
    a = arms["folds_clean"][2023]
    b = arms["folds_corrupt"][2023]
    assert b["fitted_digest"] != a["fitted_digest"]
    meta_clean = {f["validation_season"]: f
                  for f in arms["eval_clean"]["fold_meta"]}
    meta_corr = {f["validation_season"]: f
                 for f in arms["eval_corrupt"]["fold_meta"]}
    assert (meta_corr[2023] != meta_clean[2023]
            or arms["eval_corrupt"]["sigma_by_fold"]["2023"]
            != arms["eval_clean"]["sigma_by_fold"]["2023"]
            or arms["eval_corrupt"]["k3_folds"]["2023"]
            != arms["eval_clean"]["k3_folds"]["2023"])
