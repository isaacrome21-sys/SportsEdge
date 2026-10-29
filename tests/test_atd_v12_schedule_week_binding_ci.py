"""CI discovery bridge for the dependent, UNFROZEN ATD v1.2 draft.

The hosted full-discovery job runs `python -m pytest -q tests`, which does not
discover tests under research/. This bridge executes the nine genuine-pricer
schedule-week regressions as a subprocess and fails if any case is skipped,
renamed, missing, or unsuccessful. No provider quotes or counting authority.
"""
from pathlib import Path
import re
import subprocess
import sys


_REQUIRED = (
    "test_valid_real_pricer_week_counts",
    "test_all_unpriced_valid_week_cannot_count",
    "test_all_unpriced_wrong_week_cannot_bypass_binding",
    "test_numeric_string_board_week_cannot_replay_as_integer_week",
    "test_matching_board_run_but_wrong_schedule_week_refuses",
    "test_schedule_week_changed_but_board_run_unchanged_refuses",
    "test_run_week_bool_refuses_without_numeric_coercion",
    "test_run_week_float_refuses_without_numeric_coercion",
    "test_run_week_numeric_string_refuses_without_coercion",
)


def test_atd_v12_schedule_week_binding_real_pricer_regressions():
    package = (Path(__file__).resolve().parents[1]
               / "research" / "nfl_atd_engine_v1_2_20261029")
    module = package / "test_nfl_atd_v12_schedule_week_binding.py"
    assert module.is_file(), f"Required ATD v1.2 test module missing: {module}"

    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "-v",
         "test_nfl_atd_v12_schedule_week_binding"],
        cwd=str(package),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    log = completed.stdout + "\n" + completed.stderr
    missing = [name for name in _REQUIRED if name not in log]
    assert not missing, f"Required focused cases not executed: {missing}\n{log}"
    match = re.search(r"Ran (\d+) tests? in", log)
    assert match is not None and int(match.group(1)) >= len(_REQUIRED), (
        f"Focused ATD v1.2 suite count incomplete; expected at least "
        f"{len(_REQUIRED)}.\n{log}"
    )
    assert completed.returncode == 0 and re.search(r"(?m)^OK$", log), (
        f"ATD v1.2 focused suite failed closed (exit {completed.returncode}).\n{log}"
    )
