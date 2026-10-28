"""Guards for the CBB first-half (1H) design-screen attempt-1 packet.

The packet records NOT_EXECUTABLE — SCREEN_SPEC_INCOMPLETE_1H. These
tests pin that the committed result agrees with a fresh run of the
spec audit against the governing texts and the admission manifest, so
the record cannot drift from its own evidence.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKET = REPO / "research" / "cbb_first_half_screen_20261028"
RESULT = json.loads((PACKET / "screen_result.json").read_text(encoding="utf-8"))


def _audit():
    spec = importlib.util.spec_from_file_location(
        "audit_screen_spec", PACKET / "audit_screen_spec.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.audit()


def test_verdict_is_not_executable_with_named_refusal():
    assert RESULT["verdict"] == "NOT_EXECUTABLE"
    assert RESULT["refusal"]["code"] == "SCREEN_SPEC_INCOMPLETE_1H"


def test_all_criteria_not_run_and_nothing_scored():
    assert all("NOT RUN" in v for v in RESULT["criteria"].values())
    assert RESULT["fixture_universe"]["scored"] == 0


def test_gaps_match_fresh_audit():
    audit = _audit()
    assert audit["verdict"] == "NOT_EXECUTABLE"
    recorded = [g["id"] for g in RESULT["gaps"]]
    assert recorded == audit["gaps"] == [
        "G-1H-1",
        "G-1H-2",
        "G-1H-3",
        "G-1H-4",
        "G-1H-5",
        "G-1H-6",
    ]


def test_prerequisite_satisfied_and_universe_recomputes():
    audit = _audit()
    pre = next(
        e for e in audit["elements"] if e["element"].startswith("data_prerequisite")
    )
    assert pre["state"] == "PRESENT"
    u = pre["universe_from_manifest"]
    fu = RESULT["fixture_universe"]
    assert u["schedule_games"] == fu["schedule_games_in_span"] == 52126
    assert u["pbp_games"] == fu["pbp_games"] == 48623
    assert u["no_pbp_no_data"] == fu["excluded_no_pbp_no_data"] == 3503
    assert u["method_a_final_agreement_gated"] == fu[
        "method_a_final_agreement_gated"
    ] == 47903
    assert RESULT["prerequisite"]["status"] == "SATISFIED"


def test_method_b_refused_and_never_used():
    detail = RESULT["prerequisite"]["detail"]
    assert "Method B" in detail and "REFUSED" in detail
    assert "was not used" in detail
