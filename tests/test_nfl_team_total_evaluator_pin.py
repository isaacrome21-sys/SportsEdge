"""Pin-verification tests for the NFL team-totals evaluator pin
(Amendment 1): research/nfl_team_totals_forward_20261028/
AMENDMENT_1_EVALUATOR_PIN.md.

The family evaluator is the settlement code path of the frozen
runner — ``evaluate_close`` in sportsedge/nfl_team_total_runner.py
(preregistration sections 7/8 dispositions, section 3 settlement).
Amendment 1 pins that module's sha256 under the evaluator heading
of preregistration section 11, closing the FREEZE_RECORD's
"Evaluator pin: PENDING" item. These tests bind the amendment
document, the pinned constant below, and the module's actual
bytes together: any drift in the evaluator's bytes, in the frozen
artifacts the amendment re-verifies, or in the frozen disposition
vocabulary fails here, and the pin is void until re-struck by a
further amendment — never by editing frozen text.

Mirrors the NBA team-totals evaluator-pin enforcement pattern
(research/nba_team_totals_forward_20261022/EVALUATOR_PIN.md and
its test_eval_nba_team_totals_v1.py amendment-hash assertions).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sportsedge import nfl_team_total_runner as runner

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "research" / "nfl_team_totals_forward_20261028"
AMENDMENT = PACKAGE / "AMENDMENT_1_EVALUATOR_PIN.md"
EVALUATOR_PATH = REPO_ROOT / "sportsedge" / "nfl_team_total_runner.py"

# The Amendment 1 evaluator pin (the same bytes the FREEZE_RECORD
# pins as the runner; pinned a second time under the evaluator
# heading of preregistration section 11).
EVALUATOR_PIN_SHA256 = (
    "076da740f5ac0517bbe2f52b28decf77d9923226c51a8228ff5e57b4b14f323e"
)

# Frozen artifacts as re-verified in Amendment 1 against the
# FREEZE_RECORD pins. Drift in any of them breaks the amendment's
# no-frozen-term-change statement and must fail loudly.
FROZEN_SHA256 = {
    "sportsedge/nfl_team_total_dist.py":
        "50c5d9ff068b3bf629a725d5713a956d3149565c2f29c59ac8af3fc6461dcc27",
    "sportsedge/nfl_team_total_runner.py": EVALUATOR_PIN_SHA256,
    "sportsedge/forward_validation/configs/nfl_team_total.json":
        "4c5d7afbfe97d0c5f48644b7fe36c2f7666fba6caf10421f16e3a516485aa3d7",
    "research/nfl_team_totals_forward_20261028/"
    "PREREG_NFL_TEAM_TOTALS_FORWARD_V1.md":
        "83f25f0e92c3ea39c8b18e194ce5743ceff6b595dc7dcb342175a57e46743581",
    "research/nfl_team_totals_forward_20261028/FREEZE_RECORD.md":
        "18036772e0d468ecd4757899163e7de4476c37f647eba2cc2f545fc8c3c23393",
    "tests/test_nfl_team_total_dist.py":
        "6a23308516832507cccce36cc056e75fc9ebaca66af313e14d723e189fb4c91a",
    "tests/test_nfl_team_total_runner.py":
        "e3dd97d83c381d513bbec25e5f5ebf506207f97f5818efedb954b91496aed922",
    "artifacts/free_models.py":
        "a8abf4606acafd2405ec037ea3bf69f1a6a5168baa4750631cc0fbebcece1fa3",
    "free_models.py":
        "9160bbd3fd02147875942a709d2793e001281886a0969758acbcfdadf4356f67",
}

FROZEN_CLOSE_DISPOSITIONS = (
    "READABLE",
    "LINE_MOVED",
    "NO_CLOSE_ROW",
    "CLOSE_SINGLE_SIDED",
    "CLOSE_NOT_PREKICKOFF",
    "CLOSE_STALE",
    "PAIR_SPAN_EXCEEDED",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_evaluator_module_matches_amendment_pin():
    assert _sha256(EVALUATOR_PATH) == EVALUATOR_PIN_SHA256


def test_amendment_document_carries_the_same_pin():
    text = AMENDMENT.read_text(encoding="utf-8")
    assert EVALUATOR_PIN_SHA256 in text
    assert "sportsedge/nfl_team_total_runner.py" in text
    assert "evaluate_close" in text
    # The document also carries the re-verification table (the
    # other frozen hashes); the evaluator pin must be among the
    # backticked hashes it asserts, and the module-bytes test above
    # binds that value to the code itself.
    pins = set(re.findall(r"`([0-9a-f]{64})`", text))
    assert EVALUATOR_PIN_SHA256 in pins


def test_evaluator_entry_point_and_frozen_vocabulary():
    assert callable(runner.evaluate_close)
    assert runner.RUNNER_ID == "NFL_TEAM_TOTAL_RUNNER_V1"
    assert tuple(runner.CLOSE_DISPOSITIONS) == FROZEN_CLOSE_DISPOSITIONS
    # Section 7 close rule constants, as declared at the freeze.
    assert runner.CLOSE_WINDOW_S == 3600
    assert runner.CLOSE_PAIR_SPAN_S == 150


def test_frozen_artifacts_match_freeze_record_pins():
    for rel, expected in FROZEN_SHA256.items():
        assert _sha256(REPO_ROOT / rel) == expected, rel


def test_amendment_states_its_governing_terms():
    text = AMENDMENT.read_text(encoding="utf-8")
    # The pin takes effect only at the carrying PR's merge, after
    # independent exact-head review; before that the bar stands.
    assert "takes effect only at the merge" in text
    assert "No §6 metric may be computed" in text
    # Scope: counted rows only, first counted slate as the
    # FREEZE_RECORD instantiates it, no backfill.
    assert "first NFL slate priced by the pinned" in text
    assert "no backfill" in text
    # No frozen term changes.
    assert "changes **no** frozen term" in text
