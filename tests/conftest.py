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


def pytest_configure(config):
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
