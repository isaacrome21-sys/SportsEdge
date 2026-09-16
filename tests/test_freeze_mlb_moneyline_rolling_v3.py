import numpy as np

from scripts.freeze_mlb_moneyline_rolling_v3 import _logit, _sigmoid


def test_logit_sigmoid_roundtrip():
    p = np.asarray([0.1, 0.25, 0.5, 0.75, 0.9])
    out = _sigmoid(_logit(p))
    assert np.allclose(out, p, atol=1e-12)
