"""CFB runner wiring for the Option B research registration (Oct 20, 2026).

The registration (PR #2416) made CFB moneyline / spread / total
REGISTERED_RESEARCH_ONLY in sportsedge.registry_gate, and gate_payload
already kept pricing keys for rows carrying satisfied Form 2 identity
evidence. The canonical phone runner (artifacts/run_it_full.py) never
let such a fixture reach the engine: it precomputed the family blocker
from the RAW intake line and substituted it after prepricing, because
at intake time no Form 2 verdicts exist yet.

This suite pins the wired behavior end-to-end, reusing the Form 2
loader adapter battery's recorded fixtures (Delaware 48 @ Middle
Tennessee 2393, event 401871067) and its pinned-archive construction:

  * identity satisfied for BOTH teams (pinned archive admitted, stage
    verdicts at QB_IDENTITY_SATISFIED_FORM2_DEPTH_ROSTER_COMPOSITE)
    -> ML / SPREAD / TOTAL price through the game engine and land on
    the card as registered research rows (registration stamp,
    AVAILABILITY_UNVERIFIED, play-blocked); PLAY stays impossible.
  * stale or one-sided identity -> the emitted row is EXACTLY the
    registry blocker row the un-wired runner emitted (the regression
    bar), constructed here from registry_gate.family_gate_row itself.
  * an Illinois fixture is excluded even with a pinned archive.
  * a team-total row stays blocked even when the fixture's identity
    is satisfied and its spread prices beside it.
  * identity fields forged onto the intake row never price anything:
    evidence is system-produced by the pre-pricing stage only.
"""
import importlib.util
import unittest
from pathlib import Path

from sportsedge import registry_gate

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "cfb_form2_adapter_fixtures",
    ROOT / "tests" / "test_cfb_form2_loader_adapter_20261013.py")
fx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fx)

full = fx.full
SATISFIED = "QB_IDENTITY_SATISFIED_FORM2_DEPTH_ROSTER_COMPOSITE"
AVAILABILITY = "AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT"
PRICE_KEYS = ("model_p", "probability", "estimate_p", "ev_per_dollar",
              "fair_american", "fair_odds", "fair_price", "edge")


def expected_gate_row(row_in, input_index=0):
    """The exact blocker row the un-wired runner emits for this line:
    registry_gate.family_gate_row over the intake row, plus the
    runner's input_index stamp."""
    row = registry_gate.family_gate_row(
        "CFB", str(row_in.get("market") or "").upper(),
        {**row_in, "sport": "CFB"})
    row["input_index"] = input_index
    return row


class RunnerWiringCase(fx.AdapterCase):
    def pinned_two_team_archive(self):
        _, entry48 = self.preserve(fx.make_bundle("48"), "48")
        _, entry2393 = self.preserve(fx.make_bundle("2393"), "2393")
        raw, pin = self.combined_manifest([entry48, entry2393])
        self.publish_raw(raw)
        return pin

    def run_card(self, rows, pin=None):
        kw = {}
        if pin is not None:
            kw = {"form2_bundles_dir": self.dir,
                  "form2_manifest_sha256": pin}
        return full.run_full(
            {"lines": rows}, now=fx.NOW,
            getter=lambda url: fx.cfb_mapping().get(url, {}), **kw)

    def assert_no_pricing_keys(self, row):
        for key in PRICE_KEYS:
            self.assertIsNone(row.get(key), key)


class IdentitySatisfiedPricesResearchTests(RunnerWiringCase):
    """Both teams' identity satisfied by the stage -> the fixture's
    game markets price as registered research rows."""

    def test_ml_spread_total_price_with_registration_stamp(self):
        pin = self.pinned_two_team_archive()
        rows = [fx.cfb_row(market="ML", side="HOME", odds=-125),
                fx.cfb_row(),
                fx.cfb_row(market="TOTAL", side="OVER", line=55.5,
                           odds=-110)]
        card = self.run_card(rows, pin=pin)
        self.assertEqual(
            card["qb_form2_bundle_loader_audit"]["admitted_team_ids"],
            ["2393", "48"])
        evaluated = card["evaluated_rows"]
        self.assertEqual([r["market"] for r in evaluated],
                         ["ML", "SPREAD", "TOTAL"])
        for row in evaluated:
            # Priced by the engine, not blocked.
            self.assertNotEqual(row["status"], "NO_MODEL_OR_MARKET")
            self.assertIsNotNone(row["estimate_p"])
            self.assertIsNotNone(row["ev_per_dollar"])
            self.assertIsNotNone(row["fair_american"])
            # Nested engine detail survived the final gate routing
            # (no gate_payload-style stripping of priced sub-rows).
            self.assertEqual(
                row["pricing_lanes"]["lane_a_independent"]["estimate_p"],
                row["estimate_p"])
            # The registry's research registration stamp.
            self.assertEqual(row["registration_state"],
                             "REGISTERED_RESEARCH_ONLY")
            self.assertEqual(row["validation_status"], "NOT_VALIDATED")
            self.assertIs(row["eligible"], False)
            self.assertIs(row["promotable"], False)
            self.assertEqual(
                row["registry_disposition"],
                "RESEARCH_PRICING_ALLOWED_FORM2_IDENTITY_SATISFIED")
            self.assertIs(row["registry_enforced"], True)
            self.assertIs(row["research_only"], True)
            self.assertIs(row["official_authority"], False)
            self.assertIs(row["model_p_authority"], False)
            self.assertIs(row["staking_authority"], False)
            # System-stamped evidence that admitted the row.
            verdicts = row["qb_form2_identities"]
            self.assertEqual(set(verdicts), {"HOME", "AWAY"})
            for verdict in verdicts.values():
                self.assertIs(verdict["ok"], True)
                self.assertEqual(verdict["status"], SATISFIED)
            # Identity is not availability: the label rides along and
            # the availability gate forces the row research-only.
            self.assertEqual(row["availability_status"], AVAILABILITY)
            self.assertIs(row["availability_research_only"], True)
            self.assertEqual(
                row["play_blocked_reason"],
                "QB_AVAILABILITY_UNVERIFIED_CANNOT_SURFACE_AS_PLAY")
        # Card-level gate stamp reflects that research pricing happened.
        self.assertEqual(card["registry_gate"]["module"],
                         "sportsedge.registry_gate")
        self.assertEqual(card["registry_gate"]["family_state"],
                         "BLOCKED_WITH_CFB_RESEARCH_PRICING")
        self.assertEqual(card["registry_gate"]["research_priced"], 3)
        # Nothing surfaced as a play/candidate in this fixture.
        self.assertEqual(card["edges"], [])
        self.assertEqual(card["independent_candidates"], [])
        self.assertEqual(card["prop_candidates"], [])
        self.assertNotIn("NO_MODEL_OR_MARKET",
                         card["summary"]["status_counts"])


class UnprovenIdentityKeepsExactBlockerTests(RunnerWiringCase):
    """Stale / one-sided identity: the emitted row is byte-for-byte
    the registry blocker row the un-wired runner emitted."""

    def test_stale_identity_keeps_exact_blocker_row(self):
        # Delaware's depth stamp predates its previous game's kickoff
        # -> the stage's Form 2 consult returns QB_DEPTH_EVIDENCE_STALE
        # and the stage blocks; the card row is the registry refusal.
        stale = fx.make_bundle("48", depth_stamp="09/25/2026 9:07AM")
        digest = self.publish_raw(fx.bundle_bytes(stale))
        entry_stale = {"team_id": "48", "event_id": "401871067",
                       "home_team_id": "2393", "away_team_id": "48",
                       "kickoff_utc": fx.KICKOFF_ISO,
                       "recorded_at_utc": fx.NOW.isoformat(),
                       "bundle_sha256": digest}
        _, entry2393 = self.preserve(fx.make_bundle("2393"), "2393")
        raw, pin = self.combined_manifest([entry_stale, entry2393])
        self.publish_raw(raw)
        row_in = fx.cfb_row()
        card = self.run_card([row_in], pin=pin)
        (entry,) = card["prepricing_factor_audit"]["by_input_index"]
        self.assertTrue(entry["blocked"])
        self.assertEqual(entry["block_reason"],
                         "BLOCKED_PREPRICING_QB_IDENTITY_UNVERIFIED")
        self.assertIn("QB_DEPTH_EVIDENCE_STALE", entry["block_detail"])
        (row,) = card["evaluated_rows"]
        self.assertEqual(row, expected_gate_row(row_in))
        self.assert_no_pricing_keys(row)
        self.assertEqual(card["registry_gate"]["family_state"], "BLOCKED")
        self.assertEqual(card["registry_gate"]["research_priced"], 0)

    def test_one_sided_identity_keeps_exact_blocker_row(self):
        # Only Delaware's bundle is covered by the pinned manifest;
        # Middle Tennessee has no admitted Form 2 evidence. Identity
        # is a both-teams condition: the fixture stays blocked.
        _, entry48 = self.preserve(fx.make_bundle("48"), "48")
        self.preserve(fx.make_bundle("2393"), "2393")
        raw, pin = self.combined_manifest([entry48])
        self.publish_raw(raw)
        row_in = fx.cfb_row()
        card = self.run_card([row_in], pin=pin)
        self.assertEqual(
            card["qb_form2_bundle_loader_audit"]["admitted_team_ids"],
            ["48"])
        (entry,) = card["prepricing_factor_audit"]["by_input_index"]
        self.assertTrue(entry["blocked"])
        self.assertEqual(entry["block_reason"],
                         "BLOCKED_PREPRICING_QB_IDENTITY_UNVERIFIED")
        (row,) = card["evaluated_rows"]
        self.assertEqual(row, expected_gate_row(row_in))
        self.assert_no_pricing_keys(row)


class ExclusionAndScopeTests(RunnerWiringCase):
    """Exclusions and unregistered families keep their refusals even
    on an identity-satisfied fixture."""

    def test_illinois_fixture_blocked_despite_archive(self):
        _, entry48 = self.preserve(fx.make_bundle("48"), "48")
        raw, pin = self.combined_manifest([entry48])
        self.publish_raw(raw)
        row_in = fx.cfb_row(away="Delaware Blue Hens",
                            home="Northern Illinois Huskies")
        card = self.run_card([row_in], pin=pin)
        (row,) = card["evaluated_rows"]
        self.assertEqual(row, expected_gate_row(row_in))
        self.assertEqual(row["blocker"], "ILLINOIS_COLLEGE_EXCLUDED")
        self.assert_no_pricing_keys(row)
        self.assertEqual(card["registry_gate"]["family_state"], "BLOCKED")

    def test_team_total_blocked_even_when_identity_satisfied(self):
        pin = self.pinned_two_team_archive()
        rows = [fx.cfb_row(),
                fx.cfb_row(market="TEAM_TOTAL", side="HOME", line=27.5,
                           odds=-110)]
        card = self.run_card(rows, pin=pin)
        spread_row, team_total_row = card["evaluated_rows"]
        # The fixture's identity IS satisfied: its spread prices.
        self.assertEqual(spread_row["registry_disposition"],
                         "RESEARCH_PRICING_ALLOWED_FORM2_IDENTITY_SATISFIED")
        self.assertIsNotNone(spread_row["estimate_p"])
        # The team-total family is not registered: still blocked.
        self.assertEqual(team_total_row["status"], "NO_MODEL_OR_MARKET")
        self.assertEqual(team_total_row["blocker"], "NO_VALIDATION")
        self.assertEqual(team_total_row["family_decision"]["state"],
                         "BLOCKED")
        self.assert_no_pricing_keys(team_total_row)


class ForgedIntakeEvidenceTests(RunnerWiringCase):
    """Identity evidence is system-produced by the pre-pricing stage
    only. Identity fields written onto the intake row itself -- even a
    perfectly shaped satisfied verdict map -- price nothing."""

    def test_forged_intake_identity_fields_never_price(self):
        row_in = fx.cfb_row()
        row_in["identity_status"] = SATISFIED
        row_in["qb_form2_identities"] = {
            "HOME": {"ok": True, "status": SATISFIED},
            "AWAY": {"ok": True, "status": SATISFIED}}
        card = self.run_card([row_in])
        (row,) = card["evaluated_rows"]
        self.assertEqual(row, expected_gate_row(fx.cfb_row()))
        self.assert_no_pricing_keys(row)
        self.assertNotIn("qb_form2_identities", row)


if __name__ == "__main__":
    unittest.main()
