"""Offline guards for the MLB_GAME_STATE_V1 Retrosheet scope-extension packet.

These tests never touch the network. They pin the admission invariants:
the step-A verdict is SCOPE_EXTENSION_ADMITTED with the design's escape
hatch NOT triggered; the packet is design/screen scope only (no validation
credit, no forward-clock credit, no play eligibility); the 2022-2024
Retrosheet event zips carry exactly the PR #2856 pins; the 2025 zip is
pinned by the same pattern; the recorded coverage arithmetic is internally
consistent (9,719 games, 733,260 plate appearances, zero unresolved
batters/pitchers, zero batting-order slot violations); the StatsAPI
cross-check recorded in proof_results.json is 3 of 3 exact; and the
umpire byte-verification (info,umphome present in every game) is recorded
as a separate finding.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "research" / "mlb_game_state_scope_extension_20261028"
MANIFEST = json.loads((PACKET / "extension_manifest.json").read_text(encoding="utf-8"))
PROOF = json.loads((PACKET / "proof_results.json").read_text(encoding="utf-8"))
# Whitespace-normalized: Markdown line wraps must not break phrase checks.
RECORD = re.sub(r"\s+", " ", (PACKET / "SCOPE_EXTENSION_RECORD.md").read_text(encoding="utf-8"))
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

PR2856_PINS = {
    2022: ("2022eve.zip", 2497692, "cce73b21bed02283eb70f95e18575f4c8b60b968c75f926530b43f35c85f4c61"),
    2023: ("2023eve.zip", 2532820, "301e6d36afd58f3c2f9b3dfa546cb7953b24c90a4de57a69565ccc2f2a5eb8d1"),
    2024: ("2024eve.zip", 2674738, "5dfd9ed678c9c619f6a216322922c99234c067d0ec15b12790546f620ced2fa4"),
}
PIN_2025 = ("2025eve.zip", 2527926, "5ece2be6c8ec5b47b9d8d90f2ca533ceca7eee915c7e0997f9bd6d64b879303c")


def _zip(season):
    return next(z for z in MANIFEST["zips"] if z["season"] == season)


def test_verdict_is_scope_extension_admitted_escape_hatch_not_triggered():
    assert MANIFEST["verdict"] == "SCOPE_EXTENSION_ADMITTED"
    assert MANIFEST["escape_hatch"]["triggered"] is False
    assert "NO_VIABLE_SUCCESSOR" in MANIFEST["escape_hatch"]["declared_in"]
    assert MANIFEST["construction"] == "MLB_GAME_STATE_V1"
    assert "Verdict: SCOPE_EXTENSION_ADMITTED" in RECORD


def test_scope_is_design_screen_only():
    assert MANIFEST["design_only"] is True
    assert MANIFEST["screen_only"] is True
    assert MANIFEST["validation_credit"] is False
    assert MANIFEST["forward_clock_credit"] is False
    assert MANIFEST["play_eligible"] is False
    assert MANIFEST["sport"] == "MLB"


def test_zips_carry_pr2856_pins_and_the_new_2025_pin():
    assert len(MANIFEST["zips"]) == 4
    for season, (fname, nbytes, sha) in PR2856_PINS.items():
        z = _zip(season)
        assert z["file"] == fname
        assert z["bytes"] == nbytes
        assert z["sha256"] == sha
        assert "PR #2856" in z["pin_origin"]
        assert z["url"] == f"https://www.retrosheet.org/events/{fname}"
    z = _zip(2025)
    assert (z["file"], z["bytes"], z["sha256"]) == PIN_2025
    assert SHA256_RE.match(z["sha256"])
    assert "this packet" in z["pin_origin"]
    for z in MANIFEST["zips"]:
        assert SHA256_RE.match(z["sha256"])


def test_coverage_arithmetic_is_internally_consistent():
    cov = MANIFEST["coverage"]
    games = cov["games"]
    assert sum(games[str(y)] for y in (2022, 2023, 2024, 2025)) == games["total"] == 9719
    assert games["2022"] + games["2023"] + games["2024"] == 7289  # the #2856 count
    pas = cov["plate_appearances"]
    assert sum(pas[str(y)] for y in (2022, 2023, 2024, 2025)) == pas["total"] == 733260
    assert cov["unresolved_batter_total"] == 0
    assert cov["unresolved_pitcher_total"] == 0
    assert cov["slot_violations"] == 0
    assert cov["slot_transitions_checked"] == 713822
    assert cov["start_records_per_game"] == 20


def test_proof_results_agree_with_manifest():
    totals = PROOF["audit"]["totals"]
    cov = MANIFEST["coverage"]
    assert totals["games"] == cov["games"]["total"]
    assert totals["plate_appearances"] == cov["plate_appearances"]["total"]
    assert totals["slot_violations"] == 0
    assert totals["unresolved_batter"] == 0
    assert totals["unresolved_pitcher"] == 0
    for year in ("2022", "2023", "2024", "2025"):
        row = PROOF["audit"][year]
        assert row["games"] == cov["games"][year]
        assert row["plate_appearances"] == cov["plate_appearances"][year]
        assert row["umphome_present"] == row["games"]


def test_crosscheck_is_three_of_three_exact():
    rows = PROOF["crosscheck_statsapi"]
    assert len(rows) == 3
    assert {r["game_id"] for r in rows} == {"HOU202303300", "LAN202403280", "ANA202504040"}
    for r in rows:
        assert r["runs_match"] is True
        assert r["pa_match"] is True
        assert r["runs_retrosheet"] == r["runs_statsapi"]
        assert r["pa_retrosheet"] == r["pa_statsapi"]


def test_umpire_input_recorded_separately_and_present_in_every_game():
    ump = MANIFEST["umpire_input"]
    assert ump["field"] == "info,umphome"
    assert ump["present_games"] == ump["total_games"] == 9719
    assert ump["missing_or_none"] == 0
    assert "PRESENT_IN_PINNED_BYTES" in ump["verdict"]
    assert ump["distinct_home_plate_umpire_ids"] == {
        "2022": 96, "2023": 94, "2024": 90, "2025": 92,
    }
    assert "info,umphome" in RECORD


def test_schema_and_parsing_rules_are_recorded():
    schema = MANIFEST["schema"]
    assert "start" in schema["lineup_fields"]
    assert "play" in schema["pa_fields"]
    assert "bats" in schema["handedness_fields"]
    rules = " ".join(MANIFEST["parsing_rules"])
    assert "NP" in rules  # NP substitution-marker rule
    assert "baserunning" in rules or "Baserunning" in rules or "steal" in rules.lower()
    assert "position-1" in rules  # pitcher-of-record derivation
    assert "opposite" in rules  # switch-hitter convention
