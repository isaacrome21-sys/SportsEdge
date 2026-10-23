"""Shared pytest hooks.

``registry_lane_internals`` marker (t115 runtime registry enforcement):
some pre-existing tests drive artifacts/run_it_full.run_full with markets
the canonical registry now BLOCKS (NFL player props, NFL team-total /
first-half derivatives, NFL anytime/first TD, MLB F5) in order to exercise
the *downstream lane's own* fail-closed logic (ESPN name resolution,
settlement-basis gates, derivative guards, F5 quote binding). With the
registry gate active those rows never reach the lane, so these tests
would stop testing the lane at all. Marked tests run with the registry
gate disabled so lane logic keeps its coverage; the gate itself (that the
same markets are blocked on the real card, with no pricer invoked) is
asserted in tests/test_runtime_registry_enforcement_20261013.py.
"""
import pytest


def _install_net_audit_hook():
    """t260: one session-wide network audit hook, off unless a guard activates it."""
    import importlib.util
    import sys
    from pathlib import Path
    if "sportsedge_net_audit" not in sys.modules:
        path = Path(__file__).resolve().parent / "net_jail" / "audit_hook.py"
        spec = importlib.util.spec_from_file_location("sportsedge_net_audit", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["sportsedge_net_audit"] = mod
        spec.loader.exec_module(mod)
    sys.modules["sportsedge_net_audit"].install()


def pytest_configure(config):
    _install_net_audit_hook()
    config.addinivalue_line(
        "markers", "registry_lane_internals: run with the run_it_full "
        "registry gate disabled to exercise downstream lane logic")


@pytest.fixture(autouse=True)
def _registry_lane_internals(request, monkeypatch):
    if request.node.get_closest_marker("registry_lane_internals"):
        from artifacts import run_it_full
        monkeypatch.setattr(run_it_full, "_registry_blocked_row",
                            lambda *a, **k: None)
    yield
