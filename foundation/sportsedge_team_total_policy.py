#!/usr/bin/env python3
"""Team-total line policy from registry v1.6, fail closed."""
BLOCKED_LINES = {2.5, 3.5}
CAUTION_LINES = {4.5}
ALLOWED_MIN_LINE = 5.5


def team_total_policy(line: float) -> dict:
    if line in BLOCKED_LINES:
        return {"eligible": False, "status": "BLOCKED",
                "reason": f"line {line} failed OOS calibration (>2 SE); never authorize"}
    if line in CAUTION_LINES:
        return {"eligible": True, "status": "CAUTION",
                "reason": f"line {line} borderline (~2.1 SE); grade with penalty"}
    if line >= ALLOWED_MIN_LINE:
        return {"eligible": True, "status": "PASS",
                "reason": f"line {line} calibrates cleanly (<1 SE)"}
    return {"eligible": False, "status": "BLOCKED",
            "reason": f"line {line} not in validated range; fail closed on unknown lines"}


if __name__ == "__main__":
    assert team_total_policy(2.5)["eligible"] is False
    assert team_total_policy(3.5)["eligible"] is False
    assert team_total_policy(4.5)["status"] == "CAUTION"
    assert team_total_policy(5.5)["status"] == "PASS"
    assert team_total_policy(6.5)["status"] == "PASS"
    assert team_total_policy(1.5)["eligible"] is False
    assert team_total_policy(4.0)["eligible"] is False
    print("ALL TEAM TOTAL POLICY TESTS PASS")
