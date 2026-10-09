"""Reject lossy numeric coercion in CFB historical acquisition manifests."""

import pytest

from sportsedge.sports.cfb.acquisition_readiness import _positive_int


@pytest.mark.parametrize("value", [0, 1, 500, "0", "0012"])
def test_exact_nonnegative_counts(value):
    assert _positive_int(value) == int(value)


@pytest.mark.parametrize(
    "value", [True, False, -1, "-1", 1.9, 1.0, "1.0", "1e2",
              " 12", "+12", "", None, [], {}, float("inf"), float("nan")],
)
def test_invalid_counts_fail_closed(value):
    assert _positive_int(value) is None
