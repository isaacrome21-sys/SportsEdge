"""Synthetic Nov-1 CBB market-scope boundary tests; no authenticated source."""
import copy
import json
import unittest

from sportsedge.cbb_capture_scope import (
    CbbCaptureScopeError, DEFAULT_SECTIONS, parse_cbb_scope_issue,
    validate_cbb_capture_scope,
)

NOW = "2026-11-01T13:45:00Z"
FENCE = chr(96) * 3


def fixture():
    def team(role, ident, state):
        return {
            "role": role, "espn_team_id": ident, "dk_name": role + " Team",
            "is_college": True, "institution_state": state,
            "crosswalk_season": 2027, "crosswalk_sha256": "a" * 64,
            "crosswalk_status": "INDEPENDENTLY_VERIFIED",
        }
    return {
        "schema": "SPORTSEDGE_CBB_CAPTURE_SCOPE_V1", "sport": "CBB",
        "season": 2027, "league": "NCAA_MEN_D1", "source": "DRAFTKINGS_RENDERED",
        "espn_event_id": "123456", "dk_event_id": "789012",
        "scheduled_tip_utc": "2026-11-01T14:30:00Z",
        "captured_at_utc": "2026-11-01T13:40:00Z",
        "raw_sha256": "b" * 64, "raw_locator": "archive/immutable/receipt",
        "away": team("AWAY", "101", "WI"),
        "home": team("HOME", "202", "MI"),
        "sections": {k: {"status": "CAPTURED", "evidence_locator": "browser/" + k}
                     for k in DEFAULT_SECTIONS},
        "props": {"menu_examined": True, "menu_evidence_locator": "browser/props",
                  "offered": [], "captured": []},
    }


def validate(row, now=NOW):
    return validate_cbb_capture_scope(row, received_at_utc=now)


class CaptureScopeTests(unittest.TestCase):
    def test_complete_scope_is_never_quote_or_counted_authority(self):
        row = validate(fixture())
        self.assertEqual(row["scope_state"], "SCOPE_RECORDED_RESEARCH_ONLY")
        self.assertEqual(row["missing_sections"], [])
        for k in ("delivery_verified", "quote_authenticated", "counted",
                  "official", "staking_authority"):
            self.assertIs(row[k], False)

    def test_missing_offered_first_half_and_prop_are_recorded(self):
        row = fixture()
        row["sections"]["FIRST_HALF_TOTAL"]["status"] = "MISSING"
        row["props"]["offered"] = ["PLAYER_POINTS", "PLAYER_REBOUNDS"]
        row["props"]["captured"] = ["PLAYER_POINTS"]
        result = validate(row)
        self.assertEqual(result["scope_state"], "INCOMPLETE_RESEARCH_ONLY")
        self.assertEqual(set(result["missing_sections"]),
                         {"FIRST_HALF_TOTAL", "PLAYER_REBOUNDS"})

    def test_not_offered_requires_evidence_and_does_not_invent_quotes(self):
        row = fixture()
        row["sections"]["FIRST_HALF_TOTAL"] = {
            "status": "NOT_OFFERED", "evidence_locator": "browser/section-absent"}
        self.assertEqual(validate(row)["scope_state"], "SCOPE_RECORDED_RESEARCH_ONLY")
        row["sections"]["FIRST_HALF_TOTAL"].pop("evidence_locator")
        with self.assertRaisesRegex(CbbCaptureScopeError, "FIELD_INVALID"):
            validate(row)

    def test_unexamined_props_refused(self):
        row = fixture()
        row["props"]["menu_examined"] = False
        with self.assertRaisesRegex(CbbCaptureScopeError, "PROP_MENU_NOT_EXAMINED"):
            validate(row)

    def test_unknown_or_duplicate_prop_refused(self):
        for props in (["PLAYER_FOULS"], ["PLAYER_POINTS", "PLAYER_POINTS"]):
            with self.subTest(props=props):
                row = fixture()
                row["props"]["offered"] = props
                with self.assertRaisesRegex(CbbCaptureScopeError, "PROP_SET_INVALID"):
                    validate(row)

    def test_captured_prop_must_have_been_offered(self):
        row = fixture()
        row["props"]["captured"] = ["PLAYER_POINTS"]
        with self.assertRaisesRegex(CbbCaptureScopeError, "PROP_SET_INVALID"):
            validate(row)

    def test_missing_or_extra_board_category_refused(self):
        for extra in (False, True):
            with self.subTest(extra=extra):
                row = fixture()
                if extra:
                    row["sections"]["UNVERIFIED_ALT"] = {"status": "CAPTURED",
                                                           "evidence_locator": "x"}
                else:
                    del row["sections"]["TEAM_TOTAL_HOME"]
                with self.assertRaisesRegex(CbbCaptureScopeError, "SECTION_SET_MISMATCH"):
                    validate(row)

    def test_illinois_colleges_excluded_by_state_not_name(self):
        row = fixture()
        row["home"]["institution_state"] = "IL"
        row["home"]["dk_name"] = "A New Unlisted College"
        with self.assertRaisesRegex(CbbCaptureScopeError, "ILLINOIS_COLLEGE_EXCLUDED"):
            validate(row)

    def test_illinois_ids_refused_even_when_institution_state_is_forged(self):
        # Primary NCAA 2026-27 MBB IL directory returns exactly these 13
        # institutional matches. A caller cannot relabel an Illinois ESPN ID.
        il_espn_ids = (
            "71", "77", "79", "82", "305", "356", "2130",
            "2197", "2287", "2350", "2459", "2565", "2710",
        )
        for espn_team_id in il_espn_ids:
            with self.subTest(espn_team_id=espn_team_id):
                row = fixture()
                row["away"]["espn_team_id"] = espn_team_id
                row["away"]["institution_state"] = "TX"
                row["away"]["dk_name"] = "Disguised Out of State"
                with self.assertRaisesRegex(CbbCaptureScopeError, "ILLINOIS_COLLEGE_EXCLUDED"):
                    validate(row)

    def test_unknown_state_and_pro_team_refuse(self):
        row = fixture()
        row["away"]["institution_state"] = "UNKNOWN"
        with self.assertRaisesRegex(CbbCaptureScopeError, "INSTITUTION_STATE_INVALID"):
            validate(row)
        row = fixture()
        row["away"]["is_college"] = False
        with self.assertRaisesRegex(CbbCaptureScopeError, "COLLEGE_TEAM_IDENTITY_REQUIRED"):
            validate(row)

    def test_unknown_two_letter_state_and_wrong_league_refuse(self):
        row = fixture()
        row["away"]["institution_state"] = "ZZ"
        with self.assertRaisesRegex(CbbCaptureScopeError, "INSTITUTION_STATE_INVALID"):
            validate(row)
        row = fixture()
        row["league"] = "NCAA_WOMEN_D1"
        with self.assertRaisesRegex(CbbCaptureScopeError, "LEAGUE_INVALID"):
            validate(row)

    def test_2026_seed_cannot_claim_2027_crosswalk(self):
        row = fixture()
        row["away"]["crosswalk_season"] = 2026
        with self.assertRaisesRegex(CbbCaptureScopeError, "2027_CROSSWALK_REQUIRED"):
            validate(row)

    def test_crosswalk_digest_and_provenance_mandatory(self):
        row = fixture()
        row["away"]["crosswalk_sha256"] = "not-a-hash"
        with self.assertRaisesRegex(CbbCaptureScopeError, "SHA256_INVALID"):
            validate(row)
        row = fixture()
        row["away"]["crosswalk_status"] = "UNVERIFIED"
        with self.assertRaisesRegex(CbbCaptureScopeError, "CROSSWALK_UNVERIFIED"):
            validate(row)

    def test_duplicate_team_and_bad_event_ids_refused(self):
        row = fixture()
        row["home"]["espn_team_id"] = row["away"]["espn_team_id"]
        with self.assertRaisesRegex(CbbCaptureScopeError, "DUPLICATE_TEAM_ID"):
            validate(row)
        for bad in ("None", "", "0", True):
            with self.subTest(bad=bad):
                row = fixture()
                row["dk_event_id"] = bad
                with self.assertRaises(CbbCaptureScopeError):
                    validate(row)

    def test_future_and_post_tip_capture_refused(self):
        row = fixture()
        row["captured_at_utc"] = "2026-11-01T14:31:00Z"
        with self.assertRaisesRegex(CbbCaptureScopeError, "POST_TIP_CAPTURE"):
            validate(row)
        row["captured_at_utc"] = "2026-11-01T14:00:00Z"
        with self.assertRaisesRegex(CbbCaptureScopeError, "CAPTURE_AFTER_RECEIPT"):
            validate(row)

    def test_missing_timezone_refused(self):
        row = fixture()
        row["captured_at_utc"] = "2026-11-01T13:40:00"
        with self.assertRaisesRegex(CbbCaptureScopeError, "TIMEZONE_REQUIRED"):
            validate(row)

    def test_exact_issue_json_fence(self):
        body = "Operator note\n### CBB_CAPTURE_V1\n" + FENCE + "json\n" + (
            json.dumps(fixture())) + "\n" + FENCE
        result = parse_cbb_scope_issue(body, received_at_utc=NOW)
        self.assertEqual(result["scope_state"], "SCOPE_RECORDED_RESEARCH_ONLY")

    def test_duplicate_json_keys_fail_closed(self):
        payload = json.dumps(fixture()).replace('"sport": "CBB"', '"sport": "CBB", "sport": "NBA"')
        body = "### CBB_CAPTURE_V1\n" + FENCE + "json\n" + payload + "\n" + FENCE
        with self.assertRaisesRegex(CbbCaptureScopeError, "DUPLICATE_JSON_KEY"):
            parse_cbb_scope_issue(body, received_at_utc=NOW)

    def test_numeric_exponent_overflow_rejected_in_extra_json_field(self):
        # Python json parses 1e999 into +inf; parse_constant is NOT called.
        row = json.dumps(fixture())
        overflow = row[:-1] + ', "untrusted_extra": 1e999}'
        body = "### CBB_CAPTURE_V1\n" + FENCE + "json\n" + overflow + "\n" + FENCE
        with self.assertRaisesRegex(CbbCaptureScopeError, "JSON_NONFINITE"):
            parse_cbb_scope_issue(body, received_at_utc=NOW)

    def test_extra_fence_or_unclosed_fence_refused(self):
        body = "### CBB_CAPTURE_V1\n" + FENCE + "json\n{}\n" + FENCE + "\nnotes"
        with self.assertRaisesRegex(CbbCaptureScopeError, "ISSUE_FENCE_INVALID"):
            parse_cbb_scope_issue(body, received_at_utc=NOW)

    def test_no_source_claim_does_not_pass(self):
        row = fixture()
        row["raw_sha256"] = "g" * 64
        with self.assertRaisesRegex(CbbCaptureScopeError, "SHA256_INVALID"):
            validate(row)


if __name__ == "__main__":
    unittest.main()
