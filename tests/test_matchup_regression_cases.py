"""Regression harness cases for the two withdrawn cards of 2026-10-11.

These are the executable proof that the flaw class Isaac caught is fixed:
a model that is blind to a verified key-participant absence can no longer
emit a priced "edge". Each case replays the flawed game through the harness:

  BEFORE: the pre-hotfix blind means (base prior + HFA + margin proxy only;
          no injury_points, no QB scan / no probable-pitcher requirement)
          -> reproduces the fake +EV edge from the withdrawn card.
  AFTER:  the refined matchup-aware path
          -> the edge is gone: either correctly BLOCKED (input unverifiable)
          or correctly PRICED with the verified adjustment applied.

Case 1 (NFL): Ravens @ Falcons, Oct 2026. Lamar Jackson verified OUT.
  The withdrawn card showed Ravens 1H ML +140 at +$0.169 EV, priced as if
  team strength were intact. The refined path applies the 538-adapted
  per-QB VALUE adjustment (Tier 1: Huntley-for-Lamar gap from verified
  nflverse weekly data, documented below).

Case 2 (MLB): elite-starter game (Tarik Skubal vs Jacob Misiorowski,
  real 2026 game logs). The withdrawn card showed team totals with
  estimated positive EV priced pitcher-blind. The refined path applies the
  538-adapted rolling-game-score adjustment.

Same bar as everything else: point-in-time clean, fail-closed, research
only -- no claim of a validated betting edge anywhere.
"""
from datetime import datetime, timezone

from artifacts.free_models import model_probability, odds_decimal
from sportsedge import team_half_pricing as th

NOW = datetime(2026, 10, 11, 17, 0, tzinfo=timezone.utc)
KICKOFF = "2026-10-18T20:25:00Z"

# Real-data-derived Tier-1 inputs for the Lamar case (documented, not guessed):
# rolling 538-VALUE ratings through the 2024 season from verified nflverse
# weekly box scores (player_stats_2015..2024; 2025/2026 weekly files were not
# in nflverse releases at study time). Backup identity (Tyler Huntley, QB2)
# verified from nflverse depth_charts_2026 (snapshot 2026-10-11).
LAMAR_RATING = 45.77
HUNTLEY_RATING = 4.90
LAMAR_HUNTLEY_GAP = HUNTLEY_RATING - LAMAR_RATING  # -40.87
# sportsedge.qb_value calibration: total = -0.014 + 0.1176 * gap
LAMAR_TOTAL_EFFECT = -0.014 + 0.1176 * LAMAR_HUNTLEY_GAP  # -4.821
LAMAR_EXTRA = LAMAR_TOTAL_EFFECT - (-1.5)  # stacked on injury_points: -3.321


class _FakeCtx:
    """Minimal PublicContext fake; feeds are real-shaped, values documented."""

    def __init__(self, injury=None, injury_rows=None, blind=False):
        self._injury = injury
        self._injury_rows = injury_rows
        self._blind = blind

    def fixture(self, sport, away, home, kickoff):
        return {"away": away, "home": home}

    def identify(self, sport, name):
        tid = "2" if "ravens" in name.lower() else "1"
        return {"id": tid, "displayName": name, "abbreviation": name[:3].upper()}

    def schedule(self, sport, team, kickoff):
        return []

    def injury_points(self, sport, team):
        if self._blind:
            return 0.0, "BLIND_RECONSTRUCTION"
        default = (0.0, "HEURISTIC_OUT_DOUBTFUL_REPORTED_0_UNKNOWN_COMPLETENESS")
        if isinstance(self._injury, dict):
            return self._injury.get(str(team.get("id")), default)
        return default

    def fetch(self, url):
        if self._blind:
            return {"injuries": []}
        if "injuries" in url:
            rows = []
            if isinstance(self._injury_rows, dict):
                for tid, rs in self._injury_rows.items():
                    if ("/teams/%s/injuries" % tid) in url:
                        rows = rs
            return {"injuries": rows}
        return None


def _lamar_row():
    return {"sport": "NFL", "market": "ML_1H", "side": "AWAY",
            "away": "Baltimore Ravens", "home": "Atlanta Falcons",
            "kickoff": KICKOFF, "odds": 140, "line": None}


def _blind_price(monkeypatch, row):
    """Reconstruct the pre-hotfix blind price: no injury_points, no QB scan."""
    monkeypatch.setattr(th, "PublicContext",
                        lambda now, getter=None: _FakeCtx(blind=True))
    # Bypass the matchup-adjustment stage entirely, as the old code did.
    orig = th._apply_matchup_adjustments
    monkeypatch.setattr(th, "_apply_matchup_adjustments",
                        lambda *a: (a[8], a[9]))
    try:
        return th.price_team_or_half(row, now=NOW, getter=lambda url: None)
    finally:
        monkeypatch.setattr(th, "_apply_matchup_adjustments", orig)


def _refined_price(monkeypatch, row, **ctxkw):
    monkeypatch.setattr(th, "PublicContext",
                        lambda now, getter=None: _FakeCtx(**ctxkw))
    return th.price_team_or_half(row, now=NOW, getter=lambda url: None)


def _ev_at_plus140(model_p):
    dec = odds_decimal(140)
    return model_p * (dec - 1) - (1 - model_p)


def test_lamar_case_before_blind_price_shows_fake_edge(monkeypatch):
    """BEFORE: QB-blind means reproduce the withdrawn card's fake edge."""
    out = _blind_price(monkeypatch, _lamar_row())
    assert out["status"] == "PRICED_RESEARCH"
    # Blind means: no adjustment at all.
    assert out["away_mean"] == 21.25
    assert out["home_mean"] == 22.75
    ev = _ev_at_plus140(out["estimate_p"])
    assert ev > 0, "blind price must reproduce the fake +EV edge"
    print(f"\n  BEFORE (blind): Ravens 1H ML +140 -> p={out['estimate_p']:.3f}, "
          f"EV=${ev:.3f}  [FAKE EDGE]")


def test_lamar_case_after_verified_adjustment_kills_edge(monkeypatch):
    """AFTER: Lamar verified OUT -> Tier-1 VALUE adjustment; edge gone."""
    def fake_qb_absence_extra(ratings, starter_name, team_abbr, cache):
        assert starter_name == "Lamar Jackson" and team_abbr == "BAL"
        # The real pipeline matches Huntley via depth-chart gsis_id
        # 00-0035993; here the verified study values are pinned.
        return {
            "extra_total": LAMAR_EXTRA,
            "variant": "TIER1_PER_QB_VALUE",
            "source": "TIER1_VERIFIED_DEPTH_CHART",
            "audit": {
                "variant": "TIER1_PER_QB_VALUE",
                "injury_feed_starter": "Lamar Jackson",
                "depth_qb1": "Lamar Jackson",
                "depth_qb2": "Tyler Huntley",
                "starter_rating": LAMAR_RATING,
                "backup_gsis": "00-0035993",
                "backup_rating": HUNTLEY_RATING,
                "gap": round(LAMAR_HUNTLEY_GAP, 2),
            },
            "provenance": "538-adapted-VALUE/nflverse-weekly",
        }
    monkeypatch.setattr(th._qb_value, "qb_absence_extra", fake_qb_absence_extra)
    rows = {"2": [{"status": "Out",
                   "athlete": {"id": "3916387", "fullName": "Lamar Jackson",
                               "position": {"abbreviation": "QB"}}}]}
    injury = {"2": (-1.5, "HEURISTIC_OUT_DOUBTFUL_REPORTED_1_UNKNOWN_COMPLETENESS")}
    out = _refined_price(monkeypatch, _lamar_row(),
                         injury=injury, injury_rows=rows)
    assert out["status"] == "PRICED_RESEARCH"
    # -1.5 generic + -3.321 Tier-1 extra = -4.821 total (empirical).
    assert out["away_mean"] == round(21.25 - 1.5 + LAMAR_EXTRA, 3)
    assert out["matchup_audit"]["away"]["qb_value_audit"]["tier"] == \
        "TIER1_PER_QB_VALUE"
    ev = _ev_at_plus140(out["estimate_p"])
    assert ev <= 0, "verified adjustment must erase the fake edge"
    print(f"\n  AFTER (Tier-1): Ravens 1H ML +140 -> p={out['estimate_p']:.3f}, "
          f"EV=${ev:.3f}  [EDGE GONE]")


def test_lamar_case_after_unverifiable_feed_blocks(monkeypatch):
    """AFTER: participation unverifiable -> blocked, never priced blind."""
    injury = {"2": (0.0, "MISSING_OR_UNRECOGNIZED_SOURCE")}
    out = _refined_price(monkeypatch, _lamar_row(), injury=injury)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "QB_PARTICIPATION_UNVERIFIED"
    print("\n  AFTER (feed down): QB_PARTICIPATION_UNVERIFIED  [BLOCKED]")


# ---------------------------------------------------------------------------
# Case 2 (MLB): elite-starter game priced pitcher-blind.
# ---------------------------------------------------------------------------
#
# Real-data inputs (not guessed): Tarik Skubal (id 669373, 26 starts) and
# Jacob Misiorowski (id 694819, 30 starts) 2026 season gameLogs from the free
# MLB StatsAPI, saved as tests/fixtures/gamelog_{skubal,misiorowski}_2026.json
# (regular season only; every start predates the Oct-2026 kickoff, so the
# runtime's strictly-before-kickoff filter keeps them all: point-in-time).
# Trailing rGS as of 2026-10-12: Skubal 62.02 (gap +10.48 -> adj -0.719),
# Misiorowski 66.72 (gap +15.18 -> adj -1.047).
MLB_KICKOFF_CASE2 = "2026-10-12T00:10:00Z"
SKUBAL_ADJ = -0.719    # suppresses the Brewers (home) total
MISIOROWSKI_ADJ = -1.047  # suppresses the Tigers (away) total


def _case2_getter():
    import json as _json
    import os as _os
    base = _os.path.join(_os.path.dirname(__file__), "fixtures")
    logs = {
        669373: _json.load(open(_os.path.join(base, "gamelog_skubal_2026.json"))),
        694819: _json.load(open(_os.path.join(base, "gamelog_misiorowski_2026.json"))),
    }

    def get(url):
        if "/schedule?" in url:
            return {"dates": [{"games": [{
                "status": {"detailedState": "Scheduled"},
                "teams": {
                    "home": {"team": {"id": 158, "name": "Milwaukee Brewers"},
                             "probablePitcher": {"id": 694819,
                                                 "fullName": "Jacob Misiorowski"}},
                    "away": {"team": {"id": 116, "name": "Detroit Tigers"},
                             "probablePitcher": {"id": 669373,
                                                 "fullName": "Tarik Skubal"}},
                }}]}]}
        if "/people/" in url:
            pid = int(url.split("/people/")[1].split("/")[0])
            return logs[pid]
        raise AssertionError("unexpected URL: " + url)
    return get


def _case2_row():
    return {"sport": "MLB", "market": "TEAM_TOTAL", "side": "OVER", "line": 3.5,
            "away": "Detroit Tigers", "home": "Milwaukee Brewers",
            "kickoff": MLB_KICKOFF_CASE2, "odds": -110, "team": "HOME"}


def _case2_blind_price(monkeypatch):
    monkeypatch.setattr(th, "PublicContext",
                        lambda now, getter=None: _FakeCtx())
    monkeypatch.setattr(th, "_apply_matchup_adjustments",
                        lambda *a: (a[8], a[9]))
    return th.price_team_or_half(_case2_row(), now=NOW,
                                 getter=_case2_getter())


def test_sp_case_before_blind_price_shows_fake_edge(monkeypatch):
    """BEFORE: pitcher-blind means reproduce the withdrawn card's fake edge."""
    out = _case2_blind_price(monkeypatch)
    assert out["status"] == "PRICED_RESEARCH"
    assert out["home_mean"] == 4.5  # blind: no starter adjustment
    assert out["ev_per_dollar"] > 0, "blind price must show the fake +EV edge"
    print(f"\n  BEFORE (blind): Brewers TT OVER 3.5 -110 -> "
          f"EV=${out['ev_per_dollar']:.3f}  [FAKE EDGE]")


def test_sp_case_after_verified_rgs_adjustment_kills_edge(monkeypatch):
    """AFTER: verified probable starters -> rGS adjustment; edge gone."""
    monkeypatch.setattr(th, "PublicContext",
                        lambda now, getter=None: _FakeCtx())
    out = th.price_team_or_half(_case2_row(), now=NOW,
                                getter=_case2_getter())
    assert out["status"] == "PRICED_RESEARCH"
    # Home (Brewers) total suppressed by Skubal's verified rGS adjustment.
    assert out["home_mean"] == round(4.5 + SKUBAL_ADJ, 3)
    assert out["away_mean"] == round(4.3 + MISIOROWSKI_ADJ, 3)
    audit = out["matchup_audit"]["home"]
    assert audit["probable_pitcher"] == "Tarik Skubal"
    assert audit["pitcher_rgs"] == 62.02
    assert audit["variant"] == "V2_league_relative_raw"
    assert out["ev_per_dollar"] <= 0, "verified adjustment must erase the edge"
    print(f"\n  AFTER (rGS): Brewers TT OVER 3.5 -110 -> "
          f"EV=${out['ev_per_dollar']:.3f}  [EDGE GONE]")


def test_sp_case_after_unverifiable_probable_blocks(monkeypatch):
    """AFTER: probable pitcher unverifiable -> blocked, never pitcher-blind."""
    def dead_getter(url):
        raise OSError("feed unavailable")
    monkeypatch.setattr(th, "PublicContext",
                        lambda now, getter=None: _FakeCtx())
    out = th.price_team_or_half(_case2_row(), now=NOW, getter=dead_getter)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["reason"] == "PROBABLE_PITCHER_UNVERIFIED"
    print("\n  AFTER (feed down): PROBABLE_PITCHER_UNVERIFIED  [BLOCKED]")
