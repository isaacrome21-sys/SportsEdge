"""t235 RED-first regression tests (Grok ruling under owner delegation).

The earlier fix 1a3c5b3a (bool/negative lines) landed tests and fix in one
commit. This file is committed on its own BEFORE any fix:
  * NEW gap: a non-str / unhashable combo crashed with TypeError instead of
    a coded refusal (fail-closed means a named REFUSED, never a crash).
  * locks for 1a3c5b3a/a5faef0f behaviour (np.int64 line -> LINE_TYPE,
    np.float64 line prices, bool/-0.0 refused).
Research only; nothing here is validated.
"""
from datetime import date

import numpy as np
import pytest

from sportsedge import nba_combo_prop_research as C
from test_nba_combo_prop_research_20261022 import store

D = date(2024, 12, 30)


@pytest.mark.parametrize("combo", [["pr"], {"pr": 1}, {"pa"}, 1, None, b"pr", ("points", "rebounds")])
def test_non_str_combo_coded_refusal(combo):
    out = C.price_combo(store(), "A", combo, 27.5, D)
    assert out["status"] == "REFUSED"
    assert out["reason"] == "NBA_COMBO_UNSUPPORTED"
    assert out["play_allowed"] is False


@pytest.mark.parametrize("combo", ["PR", " pr", "pr ", "p+r", ""])
def test_unknown_str_combo_refused(combo):
    assert C.price_combo(store(), "A", combo, 27.5, D)["reason"] == "NBA_COMBO_UNSUPPORTED"


def test_np_int64_line_refused():
    out = C.price_combo(store(), "A", "pa", np.int64(27), D)
    assert out["status"] == "REFUSED" and out["detail"] == "LINE_TYPE"


def test_np_float64_line_prices_same_as_float():
    a = C.price_combo(store(), "A", "pa", np.float64(27.5), D)
    b = C.price_combo(store(), "A", "pa", 27.5, D)
    assert a["status"] == "PRICED" and a["p_over"] == b["p_over"]


@pytest.mark.parametrize("line,detail", [(True, "LINE_BOOL"), (np.bool_(True), "LINE_BOOL"),
                                         (-0.0, "LINE_NONPOSITIVE"), (-3.5, "LINE_NONPOSITIVE"),
                                         (0, "LINE_NONPOSITIVE")])
def test_locked_line_refusals(line, detail):
    out = C.price_combo(store(), "A", "pa", line, D)
    assert out["status"] == "REFUSED" and out["detail"] == detail
