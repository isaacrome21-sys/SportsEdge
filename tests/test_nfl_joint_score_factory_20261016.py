"""NFL joint-score research factory: schema, PIT, identity, labels.

The factory feeds the canonical derivative pricers from the integrated
Engine A+C simulator using ONLY the frozen 2022-2025 fitted artifact.
These tests pin: (1) emitted rows match the pricers' schema exactly;
(2) the PIT gate is structural -- a fit window covering the game's own
season is refused (tripwire), as is any market key inside a profile;
(3) priced team-total probabilities are the rows' own empirical
fractions (identity, exact); (4) research-only / NOT_VALIDATED labels
ride every row and every priced output; (5) determinism.
"""
import copy
import unittest

from sportsedge.nfl_joint_score_research import (
    RESEARCH_LABELS,
    FrozenProfileSource,
    NFLJointScoreResearchError,
    build_game_profiles,
    load_frozen_profile_source,
    price_research_derivatives,
    simulate_joint_score_rows,
)

N_SIMS = 48


def _profiles(season=2026, week=7):
    source = load_frozen_profile_source()
    return build_game_profiles(
        source, home_team="DEN", away_team="SEA", season=season, week=week)


def _rows(n=N_SIMS, **profile_kwargs):
    profiles = _profiles(**profile_kwargs)
    return simulate_joint_score_rows(
        profiles, game_id="TEST_FIXTURE", n_sims=n, base_seed=424242)


class FrozenSourceTests(unittest.TestCase):
    def test_frozen_chain_verifies(self):
        source = load_frozen_profile_source()
        self.assertEqual(source.artifact_version,
                         "NFL_PROP_SHARED_PATH_2022_2025_V1")
        self.assertEqual(source.fit_seasons, (2022, 2023, 2024, 2025))
        self.assertEqual(len(source.source_manifest_sha256), 64)
        self.assertEqual(len(source.artifact_canonical_sha256), 64)

    def test_provenance_records_window_and_hashes(self):
        profiles = _profiles()
        for bundle in (profiles.home, profiles.away):
            prov = bundle.provenance
            self.assertEqual(prov["fit_seasons"], [2022, 2023, 2024, 2025])
            self.assertEqual(prov["artifact_version"],
                             "NFL_PROP_SHARED_PATH_2022_2025_V1")
            self.assertIn("source_manifest_sha256", prov)
            self.assertIn("STRUCTURAL_DEFAULT", prov["field_position_provenance"])
            self.assertIn("AGGREGATE_FIT", prov["kicker_provenance"])


class PitGateTests(unittest.TestCase):
    def test_game_inside_fit_window_refused(self):
        source = load_frozen_profile_source()
        for season in (2022, 2024, 2025):
            with self.assertRaises(NFLJointScoreResearchError) as ctx:
                build_game_profiles(source, home_team="DEN", away_team="SEA",
                                    season=season, week=10)
            self.assertIn("FIT_WINDOW_NOT_STRICTLY_PRIOR", str(ctx.exception))

    def test_tripwire_synthetic_window_covering_game_season_refused(self):
        """A source whose fit window includes the target season must trip
        the gate even though the real artifact does not -- the gate is
        structural, not a hardcoded season check."""
        real = load_frozen_profile_source()
        synthetic = FrozenProfileSource(
            payload=real.payload,
            bundle_path=real.bundle_path,
            bundle_file_sha256=real.bundle_file_sha256,
            artifact_canonical_sha256=real.artifact_canonical_sha256,
            artifact_version="SYNTHETIC_TRIPWIRE",
            source_manifest_sha256=real.source_manifest_sha256,
            fit_seasons=(2024, 2025, 2026),
            fit_season_type="REG")
        with self.assertRaises(NFLJointScoreResearchError) as ctx:
            build_game_profiles(synthetic, home_team="DEN", away_team="SEA",
                                season=2026, week=3)
        self.assertIn("FIT_WINDOW_NOT_STRICTLY_PRIOR", str(ctx.exception))
        # ...and the same synthetic source is fine for a later season.
        ok = build_game_profiles(synthetic, home_team="DEN", away_team="SEA",
                                 season=2027, week=3)
        self.assertEqual(ok.season, 2027)

    def test_market_key_inside_profile_refused(self):
        real = load_frozen_profile_source()
        payload = copy.deepcopy(real.payload)
        payload["team_drive_profiles"]["DEN"]["closing_spread"] = -2.5
        poisoned = FrozenProfileSource(
            payload=payload, bundle_path=real.bundle_path,
            bundle_file_sha256=real.bundle_file_sha256,
            artifact_canonical_sha256=real.artifact_canonical_sha256,
            artifact_version="POISONED", source_manifest_sha256=real.source_manifest_sha256,
            fit_seasons=(2022,), fit_season_type="REG")
        with self.assertRaises(NFLJointScoreResearchError) as ctx:
            build_game_profiles(poisoned, home_team="DEN", away_team="SEA",
                                season=2026, week=1)
        self.assertIn("MARKET_KEY_FORBIDDEN", str(ctx.exception))

    def test_unknown_team_refused(self):
        source = load_frozen_profile_source()
        with self.assertRaises(NFLJointScoreResearchError):
            build_game_profiles(source, home_team="DEN", away_team="XXX",
                                season=2026, week=1)


class RowSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.manifest = _rows()

    def test_rows_carry_full_pricer_schema(self):
        from sportsedge.core.simulate.markets import (
            derive_alternate_markets, derive_period_markets)
        from sportsedge.sports.nfl.team_totals import price_nfl_team_totals

        required = {
            "home_score", "away_score",
            "q1_home_score", "q1_away_score", "q2_home_score", "q2_away_score",
            "q3_home_score", "q3_away_score", "q4_home_score", "q4_away_score",
            "first_half_home_score", "first_half_away_score",
            "second_half_regulation_home_score",
            "second_half_regulation_away_score",
            "second_half_with_ot_home_score", "second_half_with_ot_away_score",
        }
        for row in self.rows:
            self.assertTrue(required.issubset(row.keys()))
            self.assertEqual(
                row["home_score"],
                row["first_half_home_score"]
                + row["second_half_with_ot_home_score"])
        # The pricers themselves accept the rows (their guards are the test).
        priced = price_nfl_team_totals(
            self.rows, home_total_line=19.5, away_total_line=20.5)
        self.assertIn("home_team_total", priced)
        for period, kwargs in (
                ("first_half", {}), ("q1", {}), ("q4", {}),
                ("second_half", {"include_ot": False}),
                ("second_half", {"include_ot": True})):
            derived = derive_period_markets(
                self.rows, period=period, total_line=20.5, **kwargs)
            self.assertIn("total", derived)
        alts = derive_alternate_markets(
            self.rows, spread_lines=[-2.5], total_lines=[40.5])
        self.assertIn("alternate_total", alts)

    def test_determinism_same_seed_identical_rows(self):
        rows_a, _ = _rows()
        rows_b, _ = _rows()
        self.assertEqual(
            [(r["home_score"], r["away_score"]) for r in rows_a],
            [(r["home_score"], r["away_score"]) for r in rows_b])


class IdentityTests(unittest.TestCase):
    def test_priced_team_totals_equal_empirical_fractions_exactly(self):
        from sportsedge.sports.nfl.team_totals import price_nfl_team_totals

        rows, _ = _rows(n=240)
        priced = price_nfl_team_totals(
            rows, home_total_line=19.5, away_total_line=20.5)
        n = float(len(rows))
        for side, field, line in (("home_team_total", "home_score", 19.5),
                                  ("away_team_total", "away_score", 20.5)):
            empirical = {
                "over": sum(r[field] > line for r in rows) / n,
                "under": sum(r[field] < line for r in rows) / n,
                "push": sum(r[field] == line for r in rows) / n,
            }
            for key, value in empirical.items():
                self.assertAlmostEqual(priced[side][key], value, places=12)


class LabelTests(unittest.TestCase):
    def test_labels_on_every_row_and_manifest(self):
        rows, manifest = _rows(n=12)
        for row in rows:
            self.assertIs(row["research_only"], True)
            self.assertIs(row["validated"], False)
            self.assertEqual(row["validation_state"], "NOT_VALIDATED")
            self.assertIs(row["official_authority"], False)
            self.assertIs(row["staking_authority"], False)
            self.assertIs(row["production_card_path"], False)
        self.assertIs(manifest["research_only"], True)
        self.assertEqual(manifest["validation_state"], "NOT_VALIDATED")
        self.assertIn("calibration_warning", manifest)

    def test_labels_propagate_into_priced_outputs(self):
        rows, manifest = _rows(n=24)
        intake = [
            {"away": "SEA", "home": "DEN", "market": "TEAM_TOTALS",
             "side": "HOME", "team": "DEN", "line": 19.5},
            {"away": "SEA", "home": "DEN", "market": "TEAM_TOTALS",
             "side": "AWAY", "team": "SEA", "line": 20.5},
            {"away": "SEA", "home": "DEN", "market": "FIRST_HALF_TOTAL",
             "line": 20.5},
            {"away": "SEA", "home": "DEN", "market": "ALTERNATE_TOTAL",
             "line": 40.5},
            {"away": "SEA", "home": "DEN", "market": "FIRST_HALF_TEAM_TOTAL",
             "side": "HOME", "team": "DEN", "line": 10.5},
        ]
        result = price_research_derivatives(rows, manifest, intake_rows=intake)
        self.assertIs(result["research_only"], True)
        self.assertEqual(result["validation_state"], "NOT_VALIDATED")
        by_market = {}
        for outcome in result["outcomes"]:
            by_market.setdefault(outcome["market"], []).append(outcome)
        # Team totals + period markets now PRICE through the stage...
        for market in ("TEAM_TOTALS", "FIRST_HALF_TOTAL"):
            for outcome in by_market[market]:
                self.assertEqual(outcome["status"], "PRICED_RESEARCH")
                self.assertIs(outcome["research_only"], True)
                self.assertIs(outcome["validated_vs_close"], False)
                self.assertIs(outcome["staking_authority"], False)
        # ...alternates hit a documented defect in the canonical stage
        # (None passed for the unused lines argument): the stage outcome
        # stands as blocked, and the direct-pricer supplement prices the
        # same rows against the pricer the stage wraps.
        alt_stage = by_market["ALTERNATE_TOTAL"][0]
        self.assertEqual(alt_stage["status"], "NO_MODEL_OR_MARKET")
        self.assertTrue(
            str(alt_stage["reason"]).startswith("ALTERNATE_PRICER_ERROR"))
        self.assertIsNotNone(result["known_stage_defect"])
        supplements = result["direct_pricer_supplements"]
        self.assertEqual(len(supplements), 1)
        supp = supplements[0]
        self.assertEqual(supp["market"], "ALTERNATE_TOTAL")
        self.assertIs(supp["research_only"], True)
        self.assertEqual(supp["validation_state"], "NOT_VALIDATED")
        alt_probs = supp["model_probabilities"]["alternate_total"][40.5]
        self.assertAlmostEqual(
            alt_probs["over"] + alt_probs["under"] + alt_probs["push"],
            1.0, places=12)
        # ...while the first-half team total keeps its standing block:
        # it has no pricer of its own (owner ruling, Oct 13 2026).
        fh_tt = by_market["FIRST_HALF_TEAM_TOTAL"][0]
        self.assertEqual(fh_tt["status"], "NO_MODEL_OR_MARKET")
        self.assertEqual(fh_tt["reason"], "SIMULATION_ROWS_EMPTY")
        # No outcome anywhere may claim validated status.
        for outcome in result["outcomes"]:
            self.assertNotEqual(outcome.get("status"), "PLAY")
            self.assertIs(outcome["research_only"], True)


if __name__ == "__main__":
    unittest.main()
