"""Tests for sportsedge.cfb_game_epa_joint_v1 (CFB_GAME_EPA_JOINT_V1).

Adversarial coverage per the prereg's failure modes: the 24h
embargo boundary, the close-validity boundary at exactly 60:00,
single-sided closes, the missing-close disposition (excluded from
all three arms, retained in MAE flagged MARKET_REF_SDV), the
missing-share trip at exactly 20% (not tripping) and above
(tripping, without consuming the single look), bootstrap
determinism at the pinned seed, single-look enforcement,
NOT_FROZEN refusals on every counted entry point, no-lookahead
feature construction, and exact reproduction of the repo's PM
baseline (scripts/evaluate_cfb_sdv_closes.py).
"""

from __future__ import annotations

import importlib.util
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import sportsedge.cfb_game_epa_joint_v1 as m
from sportsedge.cfb_game_epa_joint_v1 import (
    CfbEpaError, CfbGameEpaJointV1, CloseRecord, FreezeRecord,
    GameFixture, GameResult, PlayRow, PredictionLedger,
    PredictionRecord, Snapshot, TeamFeatures, VerdictLedger)

UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[1]
KICK = datetime(2026, 11, 7, 17, 0, tzinfo=UTC)


def _load_evaluator():
    spec = importlib.util.spec_from_file_location(
        "evaluate_cfb_sdv_closes",
        REPO_ROOT / "scripts" / "evaluate_cfb_sdv_closes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(gid, kickoff, home, away, hp, ap, season=2026, week=1):
    return GameResult(game_id=gid, season=season, week=week,
                      kickoff=kickoff, home=home, away=away,
                      home_points=float(hp), away_points=float(ap))


def _plays_for(game, seed=0, strength=0.0):
    """Deterministic synthetic PBP for one game, both teams."""
    rng = random.Random(seed)
    plays = []
    for team, opp in ((game.home, game.away), (game.away, game.home)):
        for drive in range(10):
            for _ in range(6):
                yds = rng.choice([1, 2, 3, 4, 5, 6, 8, 11, 24])
                plays.append(PlayRow(
                    game_id=game.game_id, offense=team, defense=opp,
                    epa=rng.uniform(-0.3, 0.4) + strength,
                    success=yds >= 4, explosive=yds >= 20,
                    yards_gained=float(yds),
                    drive_id=f"{game.game_id}-{team}-{drive}"))
    return plays


def _world(n_weeks=4, seed=3):
    """Four teams, four games a week, results + plays."""
    rng = random.Random(seed)
    base = datetime(2026, 9, 5, 16, 0, tzinfo=UTC)
    results, plays = [], []
    gid = 0
    pairings = [("Alpha", "Beta"), ("Gamma", "Delta"),
                ("Alpha", "Gamma"), ("Beta", "Delta")]
    for wk in range(1, n_weeks + 1):
        for h, a in pairings:
            gid += 1
            g = _result(f"G{gid}", base + timedelta(days=7 * (wk - 1)),
                        h, a, rng.randint(14, 42), rng.randint(10, 38),
                        week=wk)
            results.append(g)
            plays += _plays_for(g, seed=gid)
    return results, plays


def _freeze_record(k=12):
    return FreezeRecord(
        freeze_commit_sha="b" * 40,
        frozen_at=datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
        k_at_freeze=k, prereg_sha256="a" * 64,
        implementation_sha256="c" * 64)


def _counted_sample(n_games=12, model_offset=10.0, pm_offset=0.0,
                    prices=(-110, -110), totals_price=(-110, -110),
                    missing_close_ids=()):
    """A fully counted sample in the evaluator's shapes:
    predictions are the ledger's own records, finals are
    GameResult objects, closes are keyed (game_id, market).
    Model/PM estimates sit at line + offset * sign(actual - line)
    so the realized side is favored (offset > 0) or faded (< 0)
    deterministically."""
    ledger = PredictionLedger()
    finals, closes = {}, {}
    base = datetime(2026, 11, 7, 17, 0, tzinfo=UTC)
    for i in range(n_games):
        gid = f"S{i}"
        kickoff = base + timedelta(hours=i)
        home, away = f"H{i % 4}", f"A{i % 4}"
        hp, ap = 31, 21
        finals[gid] = _result(gid, kickoff, home, away, hp, ap,
                              season=2026, week=11)
        spread_line, total_line = -3.5, 55.5
        sign_m = 1.0 if (hp - ap) > spread_line else -1.0
        sign_t = 1.0 if (hp + ap) > total_line else -1.0
        ledger.commit(
            game_id=gid, kickoff=kickoff, home=home, away=away,
            model_margin=spread_line + model_offset * sign_m,
            model_total=total_line + model_offset * sign_t,
            pm_margin=spread_line + pm_offset * sign_m,
            pm_total=total_line + pm_offset * sign_t,
            snapshot_id="snap", snapshot_content_hash="x" * 64,
            committed_at=kickoff - timedelta(hours=2), mode="COUNTED")
        if gid not in missing_close_ids:
            closes[(gid, "SPREAD")] = CloseRecord(
                game_id=gid, market="SPREAD", line=spread_line,
                price_first=prices[0], price_second=prices[1],
                captured_at=kickoff - timedelta(minutes=30))
            closes[(gid, "TOTAL")] = CloseRecord(
                game_id=gid, market="TOTAL", line=total_line,
                price_first=totals_price[0],
                price_second=totals_price[1],
                captured_at=kickoff - timedelta(minutes=30))
    return ledger, finals, closes


def _evaluate(ledger, finals, closes, verdict_ledger=None, k=12,
              sdv_closes=None, freeze=None):
    return m.evaluate_validation_sample(
        predictions=[ledger.get(g) for g in finals],
        ledger=ledger, finals=finals, dk_closes=closes,
        sdv_closes=sdv_closes or {},
        verdict_ledger=verdict_ledger or VerdictLedger(),
        freeze_record=freeze or _freeze_record(), k_at_verdict=k)


# ------------------------------------------------------------------
# PM baseline: exact reproduction of the repo evaluator
# ------------------------------------------------------------------

def test_pm_matches_repo_evaluator_exactly():
    ev = _load_evaluator()
    for seed in (7, 19):
        rng = random.Random(seed)
        teams = [f"T{i}" for i in range(8)]
        base = datetime(2026, 9, 5, 16, 0, tzinfo=UTC)
        games = []
        for i in range(48):
            h, a = rng.sample(teams, 2)
            games.append(dict(
                game_id=1000 + i,
                instant=base + timedelta(days=7 * (i // 4), hours=i % 4),
                home_id=h, away_id=a,
                home_points=float(rng.randint(10, 45)),
                away_points=float(rng.randint(10, 45))))
        games.sort(key=lambda g: g["instant"])
        script = {g["game_id"]: (pm_m, pm_t)
                  for g, _am, _at, pm_m, pm_t in ev.project_season(games)}
        mine = {gid: (a, b) for gid, a, b in m.pm_project_season([
            dict(game_id=g["game_id"], kickoff=g["instant"],
                 home=g["home_id"], away=g["away_id"],
                 home_points=g["home_points"],
                 away_points=g["away_points"])
            for g in games])}
        assert set(mine) == set(script)
        for gid, (pm_m, pm_t) in script.items():
            mm, mt = mine[gid]
            if pm_m is None:
                assert mm is None and mt is None
            else:
                assert abs(pm_m - mm) < 1e-12 and abs(pm_t - mt) < 1e-12


def test_pm_needs_three_prior_games():
    base = datetime(2026, 9, 5, 16, 0, tzinfo=UTC)
    games = [dict(game_id=i, kickoff=base + timedelta(days=7 * i),
                  home="A", away="B", home_points=28.0,
                  away_points=21.0)
             for i in range(4)]
    out = {gid: (a, b) for gid, a, b in m.pm_project_season(games)}
    assert out[0] == (None, None)
    assert out[1] == (None, None)
    assert out[2] == (None, None)
    assert out[3][0] is not None


# ------------------------------------------------------------------
# Point-in-time discipline: embargo, snapshots, ledger
# ------------------------------------------------------------------

def _bare_snapshot(results, committed_at):
    return Snapshot(snapshot_id="s", season=2026, week_label="W1",
                    committed_at=committed_at, mode="RESEARCH",
                    results=tuple(results), plays=(),
                    prior_features=None, content_hash="0" * 64)


def test_embargo_boundary_exactly_24h():
    target = KICK
    g_exact = _result("EXACT", target - timedelta(hours=48),
                      "A", "B", 28, 21)
    # kickoff exactly 24h before the target kickoff: available
    # exactly at the target kickoff under the kickoff+24h proxy.
    g_edge = _result("EDGE", target - timedelta(hours=24),
                     "C", "D", 28, 21)
    g_inside = _result("INSIDE", target - timedelta(hours=24)
                       + timedelta(seconds=1), "E", "F", 28, 21)
    snap = _bare_snapshot([g_exact, g_edge, g_inside],
                          target - timedelta(hours=49))
    ids = {g.game_id for g in snap.eligible_results(target)}
    assert ids == {"EXACT", "EDGE"}


def test_snapshot_refuses_result_not_available_at_commit():
    g = _result("LATE", KICK, "A", "B", 28, 21)
    with pytest.raises(CfbEpaError) as exc:
        m.build_snapshot(season=2026, week_label="W1",
                         committed_at=KICK + timedelta(hours=1),
                         results=[g], plays=_plays_for(g),
                         mode="RESEARCH")
    assert exc.value.reason == "RESULT_NOT_AVAILABLE_AT_SNAPSHOT"
    # Committed exactly at kickoff + 24h: available, accepted.
    snap = m.build_snapshot(season=2026, week_label="W1",
                            committed_at=KICK + timedelta(hours=24),
                            results=[g], plays=_plays_for(g),
                            mode="RESEARCH")
    assert snap.results[0].game_id == "LATE"


def test_future_game_in_snapshot_provably_excluded_from_features():
    results, plays = _world(n_weeks=3)
    runner = CfbGameEpaJointV1()
    fixture_kick = datetime(2026, 10, 10, 16, 0, tzinfo=UTC)
    committed = fixture_kick - timedelta(days=3)
    base_snap = runner.build_snapshot(
        season=2026, week_label="W5", committed_at=committed,
        results=results, plays=plays)
    fixture = GameFixture(game_id="FX", season=2026, week=6,
                          kickoff=fixture_kick, home="Alpha",
                          away="Beta")
    base_pred = runner.predict_fixture(base_snap, fixture)
    # A game that kicked off only 10h before the fixture sits inside
    # the 24h embargo. Inject it directly into a snapshot object
    # (bypassing build-time validation, as a corrupt or foreign
    # snapshot would): the per-fixture eligibility filter must
    # exclude it provably -- identical output.
    late = _result("LATE1", fixture_kick - timedelta(hours=10),
                   "Alpha", "Beta", 63, 0, week=5)
    poisoned = Snapshot(
        snapshot_id=base_snap.snapshot_id, season=2026,
        week_label="W5", committed_at=committed, mode="RESEARCH",
        results=tuple(results) + (late,),
        plays=tuple(plays) + tuple(_plays_for(late, seed=99)),
        prior_features=None, content_hash=base_snap.content_hash)
    pred2 = runner.predict_fixture(poisoned, fixture)
    assert pred2["model_margin"] == base_pred["model_margin"]
    assert pred2["model_total"] == base_pred["model_total"]
    assert pred2["pm_margin"] == base_pred["pm_margin"]
    # The lawful route refuses to build such a snapshot at all.
    with pytest.raises(CfbEpaError) as exc:
        runner.build_snapshot(
            season=2026, week_label="W5", committed_at=committed,
            results=results + [late],
            plays=plays + _plays_for(late, seed=99))
    assert exc.value.reason == "RESULT_NOT_AVAILABLE_AT_SNAPSHOT"


def test_ledger_commit_must_be_pre_kickoff():
    ledger = PredictionLedger()
    kwargs = dict(game_id="X", kickoff=KICK, home="A", away="B",
                  model_margin=3.0, model_total=50.0, pm_margin=None,
                  pm_total=None, snapshot_id="s",
                  snapshot_content_hash="0" * 64, mode="COUNTED")
    with pytest.raises(CfbEpaError) as exc:
        ledger.commit(committed_at=KICK, **kwargs)
    assert exc.value.reason == "PREDICTION_NOT_COMMITTED_PREKICKOFF"
    with pytest.raises(CfbEpaError):
        ledger.commit(committed_at=KICK + timedelta(seconds=1),
                      **kwargs)
    rec = ledger.commit(committed_at=KICK - timedelta(seconds=1),
                        **kwargs)
    assert rec.record_hash and len(rec.record_hash) == 64


def test_ledger_hash_tamper_detected_on_reload():
    ledger = PredictionLedger()
    ledger.commit(game_id="X", kickoff=KICK, home="A", away="B",
                  model_margin=3.0, model_total=50.0, pm_margin=1.0,
                  pm_total=49.0, snapshot_id="s",
                  snapshot_content_hash="0" * 64,
                  committed_at=KICK - timedelta(hours=1),
                  mode="COUNTED")
    text = ledger.to_jsonl()
    assert PredictionLedger.from_jsonl(text).get("X") is not None
    tampered = text.replace('"model_margin":3.0', '"model_margin":30.0')
    assert tampered != text
    with pytest.raises(CfbEpaError) as exc:
        PredictionLedger.from_jsonl(tampered)
    assert exc.value.reason == "PREDICTION_HASH_MISMATCH"


def test_duplicate_commit_refused():
    ledger = PredictionLedger()
    kw = dict(game_id="X", kickoff=KICK, home="A", away="B",
              model_margin=3.0, model_total=50.0, pm_margin=None,
              pm_total=None, snapshot_id="s",
              snapshot_content_hash="0" * 64,
              committed_at=KICK - timedelta(hours=1), mode="RESEARCH")
    ledger.commit(**kw)
    with pytest.raises(CfbEpaError) as exc:
        ledger.commit(**kw)
    assert exc.value.reason == "DUPLICATE_PREDICTION_COMMIT"


# ------------------------------------------------------------------
# Exclusions (prereg section 3)
# ------------------------------------------------------------------

def test_exclusions_exact_match_semantics():
    assert m.is_excluded_team("Illinois")
    assert m.is_excluded_team(" illinois ")
    assert m.is_excluded_team("Tennessee")
    assert not m.is_excluded_team("Northwestern State")
    assert not m.is_excluded_team("Middle Tennessee")
    assert not m.is_excluded_team("Ohio State")
    results, plays = _world(n_weeks=2)
    runner = CfbGameEpaJointV1()
    snap = runner.build_snapshot(
        season=2026, week_label="W3",
        committed_at=datetime(2026, 10, 1, tzinfo=UTC),
        results=results, plays=plays)
    with pytest.raises(CfbEpaError) as exc:
        runner.predict_fixture(snap, GameFixture(
            game_id="BAD", season=2026, week=4,
            kickoff=datetime(2026, 10, 3, 16, 0, tzinfo=UTC),
            home="Tennessee", away="Alpha"))
    assert exc.value.reason == "EXCLUDED_FIXTURE"


# ------------------------------------------------------------------
# Loaders: tallied, fail-closed reads of the SDV release form
# ------------------------------------------------------------------

def test_pbp_loader_success_fallback_and_tallies():
    rows = [
        {"game_id": "g1", "offense": "A", "defense": "B", "epa": 0.2,
         "yards_gained": 25, "down": 1, "distance": 10,
         "drive_id": "d1"},
        {"game_id": "g1", "offense": "A", "defense": "B",
         "epa": float("nan"), "yards_gained": 3, "drive_id": "d1"},
        {"game_id": "g1", "offense": "A", "defense": "B", "epa": 0.1,
         "yards_gained": "many", "drive_id": "d1"},
    ]
    out = m.load_sdv_pbp_rows(rows)
    assert len(out.rows) == 1
    assert out.rows[0].success is True      # 25 yards on 1st & 10
    assert out.rows[0].explosive is True
    assert out.excluded["PLAY_EPA_NONFINITE"] == 1
    assert out.excluded["PLAY_YARDS_MISSING"] == 1
    with pytest.raises(CfbEpaError):
        m.load_sdv_pbp_rows("not-a-list")


def test_schedule_loader_excludes_unplayed():
    rows = [
        {"game_id": "g1", "season": 2026, "week": 1,
         "start_date": "2026-09-05T16:00:00Z", "home_team": "A",
         "away_team": "B", "home_points": 28, "away_points": 21},
        {"game_id": "g2", "season": 2026, "week": 1,
         "start_date": "2026-09-05T20:00:00Z", "home_team": "C",
         "away_team": "D", "home_points": None, "away_points": None},
    ]
    out = m.load_sdv_schedule_rows(rows)
    assert [g.game_id for g in out.rows] == ["g1"]
    assert out.excluded["SCHEDULE_GAME_NOT_COMPLETED"] == 1


# ------------------------------------------------------------------
# Feature construction: adjustment direction + prior mechanism
# ------------------------------------------------------------------

def test_adjustment_rewards_dominant_team_and_centers():
    results, plays = [], []
    base = datetime(2026, 9, 5, 16, 0, tzinfo=UTC)
    gid = 0
    for wk in range(3):
        for h, a in (("Strong", "Weak"), ("Mid1", "Mid2")):
            gid += 1
            g = _result(f"D{gid}", base + timedelta(days=7 * wk),
                        h, a, 35, 17, week=wk + 1)
            results.append(g)
            plays += _plays_for(
                g, seed=gid, strength=0.5 if h == "Strong" else 0.0)
    feats, _league = m.compute_features(results, plays)
    assert feats["Strong"].off_epa_play > feats["Weak"].off_epa_play
    # Every team plays the same number of synthetic plays, so the
    # play-weighted recentering shows up as a zero plain mean.
    mean_adj = sum(f.off_epa_play for f in feats.values()) / len(feats)
    assert abs(mean_adj) < 1e-6


def test_prior_only_team_uses_retained_prior_not_league_average():
    prior = TeamFeatures(
        team="Veteran", games=13, off_epa_play=0.30,
        def_epa_play=-0.20, off_epa_poss=2.0, def_epa_poss=-1.0,
        off_success=0.08, def_success=-0.05, off_explosive=0.04,
        def_explosive=-0.02, off_points=0.10, def_points=-0.06,
        pace_plays=70.0, pace_possessions=12.0)
    results, plays = _world(n_weeks=2)
    runner = CfbGameEpaJointV1()
    snap = runner.build_snapshot(
        season=2026, week_label="W3",
        committed_at=datetime(2026, 10, 1, tzinfo=UTC),
        results=results, plays=plays,
        prior_features={"Veteran": prior})
    fixture = GameFixture(
        game_id="PV", season=2026, week=4,
        kickoff=datetime(2026, 10, 3, 16, 0, tzinfo=UTC),
        home="Veteran", away="Alpha")
    with_prior = runner.predict_fixture(snap, fixture)
    snap2 = runner.build_snapshot(
        season=2026, week_label="W3",
        committed_at=datetime(2026, 10, 1, tzinfo=UTC),
        results=results, plays=plays)
    without_prior = runner.predict_fixture(snap2, fixture)
    assert with_prior["model_margin"] > without_prior["model_margin"]


# ------------------------------------------------------------------
# Close validity (prereg section 2.2)
# ------------------------------------------------------------------

def _close(**kw):
    base = dict(game_id="X", market="SPREAD", line=-3.5,
                price_first=-110, price_second=-110,
                captured_at=None)
    base.update(kw)
    return CloseRecord(**base)


def test_close_exactly_sixty_minutes_is_valid():
    state, reason = m.classify_close(
        _close(captured_at=KICK - timedelta(minutes=60)), KICK)
    assert (state, reason) == ("VALID", None)


def test_close_just_past_sixty_is_stale():
    state, reason = m.classify_close(
        _close(captured_at=KICK - timedelta(minutes=60, seconds=1)),
        KICK)
    assert (state, reason) == ("MISSING", "CLOSE_STALE")


def test_close_at_or_after_kickoff_not_pre_kickoff():
    state, reason = m.classify_close(_close(captured_at=KICK), KICK)
    assert (state, reason) == ("MISSING", "CLOSE_NOT_PREKICKOFF")
    state, reason = m.classify_close(
        _close(captured_at=KICK + timedelta(minutes=5)), KICK)
    assert reason == "CLOSE_NOT_PREKICKOFF"


def test_close_single_sided_and_missing():
    state, reason = m.classify_close(
        _close(price_second=None,
               captured_at=KICK - timedelta(minutes=5)), KICK)
    assert (state, reason) == ("MISSING", "CLOSE_SINGLE_SIDED")
    assert m.classify_close(None, KICK) == ("MISSING", "NO_CLOSE_ROW")


def test_close_invalid_prices_raise():
    for bad in (0, -99, 99, 50, float("nan")):
        with pytest.raises(CfbEpaError) as exc:
            m.classify_close(
                _close(price_first=bad,
                       captured_at=KICK - timedelta(minutes=5)), KICK)
        assert exc.value.reason == "CLOSE_PRICE_INVALID"
    state, _ = m.classify_close(
        _close(price_first=100, price_second=-100,
               captured_at=KICK - timedelta(minutes=5)), KICK)
    assert state == "VALID"


# ------------------------------------------------------------------
# Evaluator dispositions (sections 2.2(c), 4)
# ------------------------------------------------------------------

def test_missing_close_excluded_from_all_arms_but_in_mae():
    ledger, finals, closes = _counted_sample(
        n_games=6, missing_close_ids=("S0",))
    sdv = {"S0": {"spread_line": -3.5, "total_line": 55.5}}
    report = _evaluate(ledger, finals, closes, sdv_closes=sdv)
    spread = report["markets"]["SPREAD"]
    assert spread["status"] == "SAMPLE_MINIMUM_UNMET"
    assert spread["missing_close_games"] == 1
    assert spread["graded_games"] == 5
    assert spread["mae"]["market_ref_sdv_rows"] == 1
    assert spread["exclusions_by_reason"]["NO_CLOSE_ROW"]["n"] == 1
    # The missing game contributes to no arm's log loss: 5 graded.
    assert spread["log_loss"]["model"] is not None


def test_push_excluded_from_primary_and_reported():
    ledger = PredictionLedger()
    ledger.commit(game_id="P1", kickoff=KICK, home="A", away="B",
                  model_margin=3.0, model_total=50.0, pm_margin=2.0,
                  pm_total=49.0, snapshot_id="s",
                  snapshot_content_hash="x" * 64,
                  committed_at=KICK - timedelta(hours=2),
                  mode="COUNTED")
    finals = {"P1": _result("P1", KICK, "A", "B", 24, 21)}
    closes = {("P1", "SPREAD"): CloseRecord(
        game_id="P1", market="SPREAD", line=3.0, price_first=-110,
        price_second=-110, captured_at=KICK - timedelta(minutes=30))}
    report = _evaluate(ledger, finals, closes)
    spread = report["markets"]["SPREAD"]
    assert spread["graded_games"] == 0
    assert spread["exclusions_by_reason"]["PUSH"]["n"] == 1
    total = report["markets"]["TOTAL"]
    assert total["exclusions_by_reason"]["NO_CLOSE_ROW"]["n"] == 1


def test_pm_unavailable_row_excluded_from_primary():
    ledger = PredictionLedger()
    ledger.commit(game_id="P1", kickoff=KICK, home="A", away="B",
                  model_margin=3.0, model_total=50.0, pm_margin=None,
                  pm_total=None, snapshot_id="s",
                  snapshot_content_hash="x" * 64,
                  committed_at=KICK - timedelta(hours=2),
                  mode="COUNTED")
    finals = {"P1": _result("P1", KICK, "A", "B", 31, 21)}
    closes = {("P1", "SPREAD"): CloseRecord(
        game_id="P1", market="SPREAD", line=-3.5, price_first=-110,
        price_second=-110, captured_at=KICK - timedelta(minutes=30))}
    report = _evaluate(ledger, finals, closes)
    spread = report["markets"]["SPREAD"]
    assert spread["graded_games"] == 0
    assert spread["exclusions_by_reason"][
        "PM_BASELINE_UNAVAILABLE"]["n"] == 1


def test_identical_rows_and_market_arm_is_power_devig():
    """One graded game: all three arms' log losses are computed on
    that same row, and the market arm equals the POWER_V1
    de-vigged probability -- not the ln 2 placeholder."""
    from sportsedge.devig import power_devig

    ledger, finals, closes = _counted_sample(
        n_games=1, model_offset=10.0, pm_offset=0.0,
        prices=(-150, 130))
    report = _evaluate(ledger, finals, closes)
    ll = report["markets"]["SPREAD"]["log_loss"]
    assert report["markets"]["SPREAD"]["graded_games"] == 1
    p_model = m._phi(10.0 / m.CONSTRUCTION_SD_MARGIN)
    assert ll["model"] == pytest.approx(-math.log(p_model), abs=1e-12)
    assert ll["pm"] == pytest.approx(math.log(2), abs=1e-12)
    first = {"game_id": "S0", "market": "SPREAD", "entity_id": "S0",
             "side": "HOME", "line": -3.5, "american_odds": -150}
    second = {"game_id": "S0", "market": "SPREAD", "entity_id": "S0",
              "side": "AWAY", "line": -3.5, "american_odds": 130}
    p_home = power_devig(first, second).candidate_fair_probability
    assert ll["market"] == pytest.approx(-math.log(p_home), abs=1e-12)
    assert abs(ll["market"] - math.log(2)) > 0.01


def test_research_prediction_never_counts():
    ledger = PredictionLedger()
    rec = ledger.commit(
        game_id="R1", kickoff=KICK, home="A", away="B",
        model_margin=3.0, model_total=50.0, pm_margin=2.0,
        pm_total=49.0, snapshot_id="s",
        snapshot_content_hash="x" * 64,
        committed_at=KICK - timedelta(hours=2), mode="RESEARCH")
    finals = {"R1": _result("R1", KICK, "A", "B", 31, 21)}
    report = m.evaluate_validation_sample(
        predictions=[rec], ledger=ledger, finals=finals,
        dk_closes={}, sdv_closes={}, verdict_ledger=VerdictLedger(),
        freeze_record=_freeze_record(), k_at_verdict=12)
    assert report["game_exclusions_by_reason"][
        "PREDICTION_NOT_COUNTED_MODE"]["n"] == 1
    assert report["markets"]["SPREAD"]["graded_games"] == 0


def test_uncommitted_prediction_refused():
    ghost = PredictionRecord(
        game_id="GHOST", kickoff=KICK, home="A", away="B",
        model_margin=1.0, model_total=50.0, pm_margin=1.0,
        pm_total=50.0, snapshot_id="s",
        snapshot_content_hash="x" * 64,
        committed_at=KICK - timedelta(hours=1), mode="COUNTED",
        record_hash="f" * 64)
    with pytest.raises(CfbEpaError) as exc:
        m.evaluate_validation_sample(
            predictions=[ghost], ledger=PredictionLedger(),
            finals={"GHOST": _result("GHOST", KICK, "A", "B", 1, 0)},
            dk_closes={}, sdv_closes={},
            verdict_ledger=VerdictLedger(),
            freeze_record=_freeze_record(), k_at_verdict=12)
    assert exc.value.reason == "PREDICTION_NOT_COMMITTED"


def test_excluded_fixture_in_sample_is_a_defect():
    ledger = PredictionLedger()
    rec = ledger.commit(
        game_id="T1", kickoff=KICK, home="Tennessee", away="Georgia",
        model_margin=3.0, model_total=50.0, pm_margin=2.0,
        pm_total=49.0, snapshot_id="s",
        snapshot_content_hash="x" * 64,
        committed_at=KICK - timedelta(hours=2), mode="COUNTED")
    finals = {"T1": _result("T1", KICK, "Tennessee", "Georgia", 31, 21)}
    with pytest.raises(CfbEpaError) as exc:
        m.evaluate_validation_sample(
            predictions=[rec], ledger=ledger, finals=finals,
            dk_closes={}, sdv_closes={},
            verdict_ledger=VerdictLedger(),
            freeze_record=_freeze_record(), k_at_verdict=12)
    assert exc.value.reason == "EXCLUDED_FIXTURE_IN_SAMPLE"


# ------------------------------------------------------------------
# Bootstrap determinism + verdicts + single look + sufficiency
# ------------------------------------------------------------------

def test_bootstrap_deterministic_at_pinned_seed():
    diffs = [-0.2, -0.1, -0.3, 0.05, -0.15, -0.25, -0.05, -0.4]
    a = m._bootstrap_ci(diffs, k=1)
    b = m._bootstrap_ci(diffs, k=1)
    assert a == b
    assert a["reps"] == 10000 and a["seed"] == 20261028
    assert a["level"] == pytest.approx(0.95)
    neg = m._bootstrap_ci([-0.1] * 5, k=1)
    assert neg["ci_upper"] == pytest.approx(-0.1)
    pos = m._bootstrap_ci([0.2] * 5, k=1)
    assert pos["ci_lower"] == pytest.approx(0.2)


@pytest.fixture
def small_minimum(monkeypatch):
    monkeypatch.setattr(m, "MIN_GRADED_GAMES", 4)


def test_verdict_pass(small_minimum):
    ledger, finals, closes = _counted_sample(n_games=12)
    vledger = VerdictLedger()
    report = _evaluate(ledger, finals, closes, verdict_ledger=vledger)
    assert report["k_governing"] == 12
    for market in ("SPREAD", "TOTAL"):
        block = report["markets"][market]
        assert block["status"] == "PASS"
        assert block["verdict"]["verdict"] == "PASS"
        assert block["verdict"]["k"] == 12
        assert block["log_loss"]["model"] < block["log_loss"]["pm"]
        assert block["log_loss"]["model"] < block["log_loss"]["market"]
        assert vledger.recorded(market)["verdict"] == "PASS"


def test_verdict_fail_is_terminal(small_minimum):
    ledger, finals, closes = _counted_sample(n_games=12,
                                             model_offset=-10.0)
    vledger = VerdictLedger()
    report = _evaluate(ledger, finals, closes, verdict_ledger=vledger)
    block = report["markets"]["SPREAD"]
    assert block["status"] == "FAIL"
    assert block["verdict"]["verdict"] == "FAIL"
    assert block["verdict"]["terminal_if_fail"] is True


def test_single_look_refused(small_minimum):
    ledger, finals, closes = _counted_sample(n_games=12)
    vledger = VerdictLedger()
    _evaluate(ledger, finals, closes, verdict_ledger=vledger)
    with pytest.raises(CfbEpaError) as exc:
        _evaluate(ledger, finals, closes, verdict_ledger=vledger)
    assert exc.value.reason == "VERDICT_ALREADY_RECORDED"
    with pytest.raises(CfbEpaError):
        vledger.record("SPREAD", {"verdict": "PASS"})


def test_missing_share_exactly_twenty_percent_does_not_trip(
        small_minimum):
    # 10 games, 2 missing closes -> share exactly 0.20, graded 8.
    ledger, finals, closes = _counted_sample(
        n_games=10, missing_close_ids=("S0", "S1"))
    report = _evaluate(ledger, finals, closes)
    spread = report["markets"]["SPREAD"]
    assert spread["missing_close_share"] == pytest.approx(0.20)
    assert spread["status"] == "PASS"
    assert spread["verdict"] is not None


def test_missing_share_above_twenty_trips_without_consuming_look(
        small_minimum):
    # 10 games, 3 missing closes -> share 0.30 -> INSUFFICIENT.
    ledger, finals, closes = _counted_sample(
        n_games=10, missing_close_ids=("S0", "S1", "S2"))
    vledger = VerdictLedger()
    report = _evaluate(ledger, finals, closes, verdict_ledger=vledger)
    assert report["markets"]["SPREAD"]["status"] == \
        "INSUFFICIENT_MARKET_DATA"
    assert vledger.recorded("SPREAD") is None  # look NOT consumed
    # A later, sufficient sample can still take the look.
    ledger2, finals2, closes2 = _counted_sample(n_games=10)
    report2 = _evaluate(ledger2, finals2, closes2,
                        verdict_ledger=vledger)
    assert report2["markets"]["SPREAD"]["status"] == "PASS"


def test_k_governing_is_max_of_freeze_and_verdict(small_minimum):
    ledger, finals, closes = _counted_sample(n_games=12)
    report = _evaluate(ledger, finals, closes, k=3,
                       freeze=_freeze_record(k=7))
    assert report["k_governing"] == 7
    assert report["markets"]["SPREAD"]["verdict"]["k"] == 7


def test_unestablishable_k_refuses():
    ledger, finals, closes = _counted_sample(n_games=4)
    with pytest.raises(CfbEpaError) as exc:
        _evaluate(ledger, finals, closes, k=0)
    assert exc.value.reason == "K_UNESTABLISHED"


# ------------------------------------------------------------------
# NOT_FROZEN state safety (every counted entry point)
# ------------------------------------------------------------------

def test_not_frozen_refusals():
    runner = CfbGameEpaJointV1()
    assert runner.freeze_state == "DRAFT_NOT_IN_FORCE"
    with pytest.raises(CfbEpaError) as exc:
        runner.run_verdict(predictions=[], ledger=PredictionLedger(),
                           finals={}, dk_closes={}, sdv_closes={},
                           verdict_ledger=VerdictLedger(),
                           k_at_verdict=12)
    assert exc.value.reason == "CFB_GAME_EPA_JOINT_NOT_FROZEN"
    with pytest.raises(CfbEpaError) as exc:
        m.evaluate_validation_sample(
            predictions=[], ledger=PredictionLedger(), finals={},
            dk_closes={}, sdv_closes={},
            verdict_ledger=VerdictLedger(),
            freeze_record=None, k_at_verdict=12)
    assert exc.value.reason == "CFB_GAME_EPA_JOINT_NOT_FROZEN"
    # Counted commits refuse; research commits succeed and label.
    results, plays = _world(n_weeks=2)
    snap = runner.build_snapshot(
        season=2026, week_label="W3",
        committed_at=datetime(2026, 10, 1, tzinfo=UTC),
        results=results, plays=plays)
    fixture = GameFixture(
        game_id="F1", season=2026, week=4,
        kickoff=datetime(2026, 10, 3, 16, 0, tzinfo=UTC),
        home="Alpha", away="Beta")
    ledger = PredictionLedger()
    with pytest.raises(CfbEpaError) as exc:
        runner.commit_predictions(
            snap, [fixture], ledger,
            committed_at=datetime(2026, 10, 2, tzinfo=UTC),
            counted=True)
    assert exc.value.reason == "CFB_GAME_EPA_JOINT_NOT_FROZEN"
    out = runner.commit_predictions(
        snap, [fixture], ledger,
        committed_at=datetime(2026, 10, 2, tzinfo=UTC), counted=False)
    assert out[0].mode == "RESEARCH"


def test_frozen_runner_verdict_path(small_minimum):
    runner = CfbGameEpaJointV1(freeze_record=_freeze_record())
    ledger, finals, closes = _counted_sample(n_games=12)
    report = runner.run_verdict(
        predictions=[ledger.get(g) for g in finals], ledger=ledger,
        finals=finals, dk_closes=closes, sdv_closes={},
        verdict_ledger=VerdictLedger(), k_at_verdict=12)
    assert report["markets"]["SPREAD"]["status"] == "PASS"


def test_freeze_record_validation():
    with pytest.raises(CfbEpaError) as exc:
        _freeze_record(k=0)
    assert exc.value.reason == "FREEZE_RECORD_INVALID"
    with pytest.raises(CfbEpaError):
        FreezeRecord(freeze_commit_sha="zz", frozen_at=KICK,
                     k_at_freeze=12, prereg_sha256="a" * 64,
                     implementation_sha256="c" * 64)


# ------------------------------------------------------------------
# Research backtest: labeled, claims nothing
# ------------------------------------------------------------------

def test_research_backtest_is_labeled_and_marketless():
    results, plays = _world(n_weeks=4)
    runner = CfbGameEpaJointV1()
    report = runner.research_backtest([{
        "season": 2026, "results": results, "plays": plays,
        "sdv_closes": {g.game_id: {"spread_line": -3.5,
                                   "total_line": 55.5}
                       for g in results}}])
    assert report["mode"] == "RESEARCH_DESIGN_DATA_NOT_VALIDATION"
    assert report["claims"] == "NONE"
    assert report["production_eligible"] is False
    assert report["market_arm"] == \
        "NOT_AVAILABLE_SDV_CLOSES_CARRY_NO_PRICES"
    assert report["overall"]["SPREAD"]["graded_rows"] > 0
