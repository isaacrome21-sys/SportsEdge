"""Nonzero-sigma extension of the G2 attempt-2 nested-sigma leakage
verification (issue #2218 M3 follow-up, owner-directed Oct 14 2026).

Attempt 2 remains NO-GO and unspent. Synthetic fixtures only; the
frozen code (commit 2f3af2a2) is not modified.

WHY THIS FILE EXISTS: the companion leakage suite
(tests/test_nfl_score_counts_g2_nested_sigma_leakage_20261014.py)
proves the fold discipline of the nested sigma selection, but on its
fixture the selected sigma is 0.0 in every fold of both arms, so the
sigma claim there binds through the bit-identity of the full
sigma-selection detail (the nested per-candidate MSE table) rather
than through a nonzero winner. This file closes that gap with a
fixture ENGINEERED FOR GENUINE CO-MOVEMENT, then re-runs the same
adversarial protocol on it:

* Fixture construction (generative, documented, seeded): start from
  the battery's own enriched synthetic universe (same factory, same
  row schema, same build_g2_rows_v2 path), then regenerate each game's
  scoring outcomes from ONE SHARED per-game latent multiplier --
  L ~ Gamma(shape = 1/v, scale = v), mean 1, variance v = 0.09 --
  applied to BOTH teams' touchdown rates and BOTH teams' field-goal
  attempt rates. Home and away scoring therefore genuinely co-move:
  the expected residual product of a game's two totals is
  approximately v * mu_home * mu_away > 0, which is exactly the
  covariance the nested statistic prices (implied factor
  exp(sigma^2) - 1; v = 0.09 sits at the sigma = 0.3 grid point,
  factor 0.0942). Every regenerated field stays internally coherent:
  band attempts/makes, FG accounting fields, quarter splits
  (multinomial on the battery's QUARTER_WEIGHTS), and per-quarter
  conversion draws use the battery factory's own probabilities.
  Defensive-TD and safety counts are left at the base universe's
  values (independent small counts; not part of the co-movement
  channel). Robustness was checked before committing to the seed:
  sigma > 0 is selected in every fold for several regeneration seeds
  and at v = 0.06 as well; the seed below is not load-bearing.
* Clean-run result on this fixture: the nested selection picks
  sigma = 0.3 in ALL THREE folds (2021, 2022, 2023) with
  monotone-decreasing MSE tables -- a real nonzero winner, not a
  tie-break artifact.
* Adversarial protocol: IDENTICAL to the companion suite (its helpers
  are imported, not re-implemented): replace -- not permute -- the
  outcome fields of the middle validation season's (2022) final
  kickoff batch with a different-seed donor universe's outcomes, then
  assert bit-identity of fitted values, of the sigma selection
  (including the NONZERO selected sigma and the full MSE table), of
  the K3 lambdas, and of every issued per-game candidate PMF for folds
  2021 and 2022 -- and assert that fold 2023, whose training window
  legitimately contains the perturbed season, changes (non-vacuity).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from sportsedge.research import nfl_score_counts_g2_v2 as m
from sportsedge.research import nfl_score_counts_g2_eval_v2 as ev

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "tests" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Same loading pattern as the companion suite: exercise EXACTLY the
# battery's fixture universe and the companion suite's protocol
# helpers rather than re-implementations of either.
battery = _load("g2_attempt2_battery",
                "test_nfl_score_counts_g2_attempt2.py")
leak = _load("g2_nested_sigma_leakage",
             "test_nfl_score_counts_g2_nested_sigma_leakage_20261014.py")

SEASONS = leak.SEASONS
VALIDATION_SEASONS = leak.VALIDATION_SEASONS
PERTURBED_SEASON = leak.PERTURBED_SEASON
PATHS = leak.PATHS

LATENT_VAR = 0.09  # shared per-game latent variance; see module docstring
REGEN_SEED = 424242
DONOR_BASE_SEED = 777
DONOR_REGEN_SEED = 777777

_BAND_PROFILE = np.array([6, 8, 6, 3, 1], dtype=float)
_BAND_PROFILE = _BAND_PROFILE / _BAND_PROFILE.sum()


def comoving_universe(*, base_seed=None, regen_seed=REGEN_SEED,
                      seasons=SEASONS, rounds_per_season=6):
    """The battery's enriched universe with each game's scoring
    outcomes regenerated from a shared per-game latent multiplier
    (module docstring). base_seed=None selects the battery factory's
    own default universe, exactly as the companion suite uses it."""
    kwargs = {"seasons": seasons, "rounds_per_season": rounds_per_season}
    if base_seed is not None:
        kwargs["seed"] = base_seed
    base = battery.enriched_universe(**kwargs)
    rng = np.random.default_rng(regen_seed)
    shape = 1.0 / LATENT_VAR
    by_game: dict[str, list[dict]] = {}
    for r in base:
        by_game.setdefault(str(r["game_id"]), []).append(r)
    out: list[dict] = []
    for gid in sorted(by_game):
        pair = by_game[gid]
        assert len(pair) == 2
        latent = float(rng.gamma(shape, LATENT_VAR))  # mean 1, var LATENT_VAR
        for r in pair:
            r2 = dict(r)
            off_td = int(rng.poisson(float(r["off_td_per_game"]) * latent))
            att_total = int(rng.poisson(1.55 * latent))
            missing = int(rng.binomial(att_total, 0.08))
            att_dist = att_total - missing
            band_att = rng.multinomial(att_dist, _BAND_PROFILE)
            band_made = [int(rng.binomial(int(band_att[b]),
                                           battery.BAND_MAKE_RATE[b]))
                         for b in range(5)]
            made_missing = int(rng.binomial(missing, 0.80))
            made_fg = int(sum(band_made)) + made_missing
            r2["offense_touchdowns"] = off_td
            r2["made_field_goals"] = made_fg
            r2["fg_att_band"] = [int(v) for v in band_att]
            r2["fg_made_band"] = band_made
            r2["fg_attempts_total"] = att_total
            r2["fg_attempts_with_distance"] = att_dist
            r2["fg_attempts_missing_distance"] = missing
            r2["fg_makes_missing_distance"] = made_missing
            q_off = rng.multinomial(off_td, battery.QUARTER_WEIGHTS)
            q_fg = rng.multinomial(made_fg, battery.QUARTER_WEIGHTS)
            pat = two = none = 0
            for qi in range(4):
                tds_q = int(q_off[qi]) + int(r[f"q{qi + 1}_def_td"])
                pat_q = two_q = 0
                for _ in range(tds_q):
                    u = rng.random()
                    if u < 0.93:
                        if rng.random() < 0.955:
                            pat_q += 1
                        else:
                            none += 1
                    elif u < 0.98:
                        if rng.random() < 0.48:
                            two_q += 1
                        else:
                            none += 1
                    else:
                        none += 1
                pat += pat_q
                two += two_q
                r2[f"q{qi + 1}_off_td"] = int(q_off[qi])
                r2[f"q{qi + 1}_made_fg"] = int(q_fg[qi])
                r2[f"q{qi + 1}_points"] = (
                    6 * tds_q + pat_q + 2 * two_q + 3 * int(q_fg[qi])
                    + 2 * int(r[f"q{qi + 1}_safeties"]))
            r2["pat_made"] = pat
            r2["two_point_made"] = two
            r2["no_conversion"] = none
            out.append(r2)
    out.sort(key=lambda r: (str(r["game_start_ts"]), str(r["game_id"]),
                            str(r["team"])))
    return out


@pytest.fixture(scope="module")
def arms():
    rows = comoving_universe()
    donor = comoving_universe(base_seed=DONOR_BASE_SEED,
                              regen_seed=DONOR_REGEN_SEED)
    corrupted = leak._replace_final_batch_outcomes(
        rows, PERTURBED_SEASON, donor)
    eval_clean = ev.run_development_evaluation_v2(
        rows, paths=PATHS, validation_seasons=VALIDATION_SEASONS,
        fold_min_games=10)
    eval_corrupt = ev.run_development_evaluation_v2(
        corrupted, paths=PATHS, validation_seasons=VALIDATION_SEASONS,
        fold_min_games=10)
    folds_clean = {s: leak._fold_predictions(rows, s)
                   for s in VALIDATION_SEASONS}
    folds_corrupt = {s: leak._fold_predictions(corrupted, s)
                     for s in VALIDATION_SEASONS}
    return {
        "rows": rows, "corrupted": corrupted,
        "eval_clean": eval_clean, "eval_corrupt": eval_corrupt,
        "folds_clean": folds_clean, "folds_corrupt": folds_corrupt,
    }


def test_comoving_fixture_selects_nonzero_sigma_in_clean_run(arms):
    """The fixture's reason to exist: on genuinely co-moving synthetic
    scoring, the nested (training-window-only) selection picks a
    NONZERO sigma -- in every fold of the clean run -- where the
    companion suite's independent-scoring fixture picks 0.0. An
    independent hand reimplementation of the frozen statistic agrees
    with the module's selection on the perturbed fold's window."""
    for season in VALIDATION_SEASONS:
        assert arms["folds_clean"][season]["sigma"] > 0.0, (
            f"fold {season}: expected nonzero sigma on the co-moving "
            f"fixture, got {arms['folds_clean'][season]['sigma']}")
        assert arms["eval_clean"]["sigma_by_fold"][str(season)] > 0.0
    train = [r for r in arms["rows"]
             if int(r["season"]) < PERTURBED_SEASON]
    bundle = m.fit_fold_bundle(train, m.V2_CONFIG)
    hand_sigma, _hand_mse, mean_rp = battery._hand_nested_sigma(
        train, bundle)
    assert mean_rp > 0  # construction sanity: positive inner products
    assert hand_sigma == arms["folds_clean"][PERTURBED_SEASON]["sigma"]


def test_perturbation_is_real_and_scoped_nonzero(arms):
    """Same scoping discipline as the companion suite, on this
    fixture: the adversary changed the final-batch games' outcomes,
    changed nothing else anywhere, and touched no feature or
    PIT-snapshot field."""
    rows, corrupted = arms["rows"], arms["corrupted"]
    assert len(rows) == len(corrupted)
    targets = leak._final_batch_game_ids(rows, PERTURBED_SEASON)
    assert targets
    changed_games = set()
    realized_changed = False
    for clean, corr in zip(rows, corrupted):
        assert clean["game_id"] == corr["game_id"]
        assert clean["season"] == corr["season"]
        non_outcome = {k: v for k, v in clean.items()
                       if k not in leak._REPLACE_KEYS}
        assert {k: v for k, v in corr.items()
                if k not in leak._REPLACE_KEYS} == non_outcome
        if str(clean["game_id"]) in targets:
            changed_games.add(str(clean["game_id"]))
            if m.realized_final_score(corr) != m.realized_final_score(clean):
                realized_changed = True
        else:
            assert corr == clean
    assert changed_games == targets
    assert realized_changed


def test_nonzero_sigma_selection_invariant_under_perturbation(arms):
    """The headline claim, now with a nonzero winner: for the perturbed
    season's fold and the earlier fold, the selected sigma ITSELF --
    not only the MSE table behind a 0.0 argmin -- plus the full
    selection detail, the driver fold metadata, and the K3 records are
    bit-identical between the clean and perturbed runs."""
    clean, corr = arms["eval_clean"], arms["eval_corrupt"]
    for season in (2021, PERTURBED_SEASON):
        key = str(season)
        assert clean["sigma_by_fold"][key] > 0.0  # nonzero winner asserted
        assert corr["sigma_by_fold"][key] == clean["sigma_by_fold"][key]
        assert corr["sigma_selection"][key] == clean["sigma_selection"][key]
        assert corr["k3_folds"][key] == clean["k3_folds"][key]
        a = arms["folds_clean"][season]
        b = arms["folds_corrupt"][season]
        assert b["sigma"] == a["sigma"] > 0.0
        assert b["sigma_detail"] == a["sigma_detail"]
        assert b["sigma_detail"]["selection_rule"] == \
            "AMENDMENT_2_NESTED_TRAINING_WINDOW_ONLY"
    meta_clean = {f["validation_season"]: f for f in clean["fold_meta"]}
    meta_corr = {f["validation_season"]: f for f in corr["fold_meta"]}
    for season in (2021, PERTURBED_SEASON):
        assert meta_corr[season] == meta_clean[season]


def test_predictions_and_k3_invariant_nonzero(arms):
    """Per-game candidate PMFs issued for the perturbed season --
    including the perturbed games themselves -- and for the earlier
    season are bit-identical across arms, as are the fitted-values
    digests and the K3 lambdas."""
    for season in (2021, PERTURBED_SEASON):
        a = arms["folds_clean"][season]
        b = arms["folds_corrupt"][season]
        assert a["pmf_digests"], "fold issued no predictions"
        assert b["pmf_digests"] == a["pmf_digests"]
        assert b["fitted_digest"] == a["fitted_digest"]
        assert b["lambdas"] == a["lambdas"]
        for lam in a["lambdas"].values():
            assert 0.0 <= lam <= 0.50
    targets = leak._final_batch_game_ids(arms["rows"], PERTURBED_SEASON)
    assert targets <= set(arms["folds_clean"][PERTURBED_SEASON]["pmf_digests"])


def test_later_fold_legitimately_changes_nonzero_nonvacuity(arms):
    """Non-vacuity on this fixture: fold 2023 trains on the perturbed
    season, so its fitted values MUST change; if they did not, the
    perturbation was impotent and every identity above is vacuous."""
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
