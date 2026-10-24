"""CFB projection is offense-vs-opposing-defense, not a capped 28-28 prior.

The Oct 24 2026 slate priced every total near 56 and every spread inside
+/-8.5, producing all-OVER/all-underdog cards at +40-68% EV. This pins the
fix: projected margin and total follow each side's points for/against,
adjusted for the strength of the opponents those points came against.
"""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "free_models", Path(__file__).resolve().parents[1] / "artifacts" / "free_models.py")
fm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fm)

KICK = datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc)


class Provider:
    def __init__(self, games):
        self.games = games

    def fixture(self, sport, away, home, start):
        return KICK, {}

    def identify(self, sport, name):
        return {"id": name}

    def schedule(self, sport, team, kickoff):
        pf, pa = self.games[team["id"]]
        return [(kickoff - timedelta(days=7 * (i + 1)), pf, pa) for i in range(5)]

    def injury_points(self, sport, team):
        return 0.0, "NONE"

    def weather(self, *a, **k):
        return 0.0, "NONE"


def means(home_pf_pa, away_pf_pa):
    ctx, _, notes = fm.context_for("CFB", "Away", "Home", KICK,
                                   Provider({"Home": home_pf_pa, "Away": away_pf_pa}), {})
    assert "CFB_MATCHUP_OFF_DEF_V1" in notes
    return fm.score_means("CFB", ctx)


def test_mismatch_projects_a_wide_margin():
    h, a = means((42, 14), (17, 35))
    assert h - a > 15          # old capped model could never exceed ~8.5


def test_two_bad_offenses_project_a_low_total():
    h, a = means((17, 16), (16, 17))
    assert h + a < 45          # old model pinned totals near 56


def test_two_explosive_offenses_bad_defenses_project_a_high_total():
    h, a = means((40, 34), (38, 36))
    assert h + a > 66


class OppProvider(Provider):
    """Home scored 40/game, but against defenses that allow 45/game."""

    def __init__(self):
        super().__init__({"Home": (40, 20), "Away": (30, 30),
                          "SoftD": (28, 45), "Mid": (28, 28)})
        self._opponents = {}

    def schedule(self, sport, team, kickoff):
        games = super().schedule(sport, team, kickoff)
        opp = {"Home": "SoftD", "Away": "Mid"}.get(team["id"])
        if opp:
            self._opponents[(sport, team["id"], kickoff)] = {g[0]: opp for g in games}
        return games


def test_opponent_adjustment_discounts_soft_schedules():
    ctx, _, notes = fm.context_for("CFB", "Away", "Home", KICK, OppProvider(), {})
    assert "CFB_OPPONENT_ADJUSTED_V1" in notes
    assert "HOME_OPP_ADJUSTED_GAMES:5/5" in notes
    adj_home, _ = fm.score_means("CFB", ctx)
    raw_home, _ = means((40, 20), (30, 30))
    assert adj_home < raw_home - 3   # 40 ppg vs 45-allowed defenses is ~23 adjusted


def test_additive_not_averaged():
    # 42-ppg offense vs a defense allowing 35: expect ~49 before shrink/HFA,
    # not the averaged 38.5 that compressed every card.
    h, a = means((42, 28), (28, 35))
    assert h > 40
