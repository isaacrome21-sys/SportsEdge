"""Composition regression: live score means remain importable and respect disabled factors.

No network, quote, capture, or historical collector runs. These cases encode
the owner-ruled canonical factor exclusions as strict live-path invariants.
"""

import pytest

from artifacts.free_models import CONTEXT_KEYS, PRIORS, score_means


@pytest.mark.parametrize("sport", ("MLB", "NFL", "CFB", "NBA"))
def test_live_score_means_match_canonical_base(sport):
    ctx = {key: 0.0 for key in CONTEXT_KEYS[sport]}
    ctx["home_rating"] = 0.4
    ctx["away_rating"] = -0.3
    base, _, _, hfa = PRIORS[sport]
    actual = score_means(sport, ctx)
    assert actual == pytest.approx(
        (base + hfa / 2 + 0.4, base - hfa / 2 - 0.3))


@pytest.mark.parametrize("sport", ("MLB", "NFL", "CFB", "NBA"))
def test_live_score_means_ignore_disabled_unvalidated_factors(sport):
    ctx = {key: 0.0 for key in CONTEXT_KEYS[sport]}
    original = score_means(sport, ctx)
    for key in ("home_pitcher_adj", "away_pitcher_adj",
                "home_form", "away_form", "rest_diff_adj", "rest_adj"):
        if key in ctx:
            ctx[key] = 9.0 if key.startswith(("home", "rest")) else -9.0
    assert score_means(sport, ctx) == original


def test_live_score_means_preserve_active_context():
    nfl = {key: 0.0 for key in CONTEXT_KEYS["NFL"]}
    base = score_means("NFL", nfl)
    nfl["home_injury_pts"] = -1.5
    nfl["away_injury_pts"] = -0.5
    nfl["weather_total_adj"] = -0.8
    expected = (base[0] - 1.5 - 0.4, base[1] - 0.5 - 0.4)
    assert score_means("NFL", nfl) == pytest.approx(expected)

    nba = {key: 0.0 for key in CONTEXT_KEYS["NBA"]}
    before = score_means("NBA", nba)
    # Owner ruling (Oct 13, 2026, extended on PR #2120): the NBA rest
    # adjustment is DISABLED_PENDING_INCREMENTAL_VALUE in every canonical
    # pricing path, regardless of its key name (rest_adj, not
    # rest_diff_adj). It previously shifted the means (+1/-1 at 2.0);
    # that expectation is superseded — the value stays in context for
    # research and its pricing contribution is exactly zero.
    nba["rest_adj"] = 2.0
    assert score_means("NBA", nba) == before


def test_live_score_means_keep_implausible_floor():
    mlb = {key: 0.0 for key in CONTEXT_KEYS["MLB"]}
    mlb["home_rating"] = -10.0
    with pytest.raises(ValueError, match="IMPLAUSIBLE_SCORE_MEAN"):
        score_means("MLB", mlb)
