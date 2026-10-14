"""Exact numeric threshold identity for already timestamped MLB count quotes.

No market price, side, player, fixture, book, or capture-time information is
inferred here. In particular, a one-sided milestone stays one-sided.
"""
from __future__ import annotations

from math import isfinite


def same_quoted_count_threshold(left, right) -> bool:
    """Treat 5.5, '5.5', and '5.50' as the same quoted counting-stat line.

    Reject missing, booleans, objects, nonfinite values and malformed strings.
    Numeric equality is exact after parsing; there is no tolerance that can
    accidentally merge two adjacent milestone rungs.
    """
    if type(left) not in (str, int, float) or type(right) not in (str, int, float):
        return False
    try:
        a, b = float(left), float(right)
    except (ValueError, TypeError, OverflowError):
        return False
    return isfinite(a) and isfinite(b) and a == b
