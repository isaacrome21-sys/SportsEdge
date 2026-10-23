import pytest

from sportsedge.week_cluster_bootstrap import ClusterBootstrapError, cluster_ci, week_key


def test_week_key():
    assert week_key("2024_07_BUF_KC") == "2024_07"
    for bad in ("2024-07-BUF-KC", "24_07_A_B", None, "2024_7_A_B"):
        with pytest.raises(ClusterBootstrapError):
            week_key(bad)


def test_clustered_interval_wider_than_iid_when_weeks_correlated():
    deltas, clusters = [], []
    for w in range(30):
        shift = 1.0 if w % 2 else -1.0
        for g in range(16):
            deltas.append(shift + 0.01 * g); clusters.append(w)
    lo, hi, k = cluster_ci(deltas, clusters, alpha=0.05)
    iid_lo, iid_hi, _ = cluster_ci(deltas, list(range(len(deltas))), alpha=0.05)
    assert k == 30 and (hi - lo) > 2 * (iid_hi - iid_lo)
    assert lo < sum(deltas) / len(deltas) < hi


def test_deterministic():
    d = [0.1, -0.2, 0.3, 0.05] * 10; c = list(range(10)) * 4
    assert cluster_ci(d, c, alpha=0.05) == cluster_ci(d, c, alpha=0.05)


@pytest.mark.parametrize("d,c,kw", [
    ([], [], {}), ([1.0], [1, 2], {}), ([1.0, 2.0], [1, 1], {}),
    ([float("nan"), 1.0], [1, 2], {}), ([True, 1.0], [1, 2], {}),
    ([1.0, 2.0], [1, 2], {"alpha": 0}), ([1.0, 2.0], [1, 2], {"reps": 10}),
])
def test_refusals(d, c, kw):
    kw.setdefault("alpha", 0.05)
    with pytest.raises(ClusterBootstrapError):
        cluster_ci(d, c, **kw)
