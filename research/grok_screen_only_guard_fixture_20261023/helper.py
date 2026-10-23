"""t256/t257 test fixture (research/ helper). Enters the guard and runs the
guarded check itself. It accepts NO callables (t257: the generic run_in_screen
helper was removed after the auditor's thread-pool + functools.partial bypass).

Used only by tests/test_screen_only_bypasses_v2_20261023.py and
tests/test_screen_only_bypasses_v3_20261023.py. Not a screen; produces no results."""
from sportsedge.screen_only_guard import checked_require, screen_only


def probe():
    with screen_only():
        checked_require("fixture-probe")
        return "PROBE_OK"
