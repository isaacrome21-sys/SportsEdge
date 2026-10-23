"""t256 test fixture (research/ helper). Enters the guard and runs a callable.

Used only by tests/test_screen_only_bypasses_v2_20261023.py to show that calling
this helper from sportsedge/ or scripts/, or handing it a sportsedge/ lambda that
runs an unrestricted pricer, is refused. Not a screen; produces no results."""
from sportsedge.screen_only_guard import screen_only


def run_in_screen(fn):
    with screen_only():
        return fn()
