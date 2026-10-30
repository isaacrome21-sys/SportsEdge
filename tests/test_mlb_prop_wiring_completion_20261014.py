"""MLB prop wiring completion (Oct 14, 2026) — offline, exact-source.

Covers the families wired (or verified wired) on branch
feat/mlb-prop-wiring-completion-20261014:

* ITEM 1 (pitcher): PITCHER_OUTS / PITCHER_HITS_ALLOWED / PITCHER_BB /
  PITCHER_ER were already priced by the joint empirical-Bayes engine
  from verified StatsAPI prior starts -- pinned here end-to-end.
  PITCHER_PITCHES is newly wired: the history source carries the
  measured per-start numberOfPitches, the joint engine prices the same
  empirical construction over it, and pools without a measured pitch
  count refuse by name.
* ITEM 2 (batter): the ladder-only families (HOME_RUNS, BATTER_K,
  TRIPLES, EXTRA_BASE_HITS, RUNS_RBIS) now reach the empirical gamelog
  engine -- paired fixtures for every O/U 0.5 family, milestone-ladder
  fixtures for the ladder-only five. TRIPLES reads the measured
  per-game triples field; EXTRA_BASE_HITS and RUNS_RBIS are exact
  per-game arithmetic over measured components and fail closed when a
  component is missing. The official-lineup gate is unchanged.
* ITEM 3 (registry truth): pins the invariant that makes the surface
  availability swap a ratification item -- the market-surface loader
  forbids UNAVAILABLE + provider_expected, and the finish-line
  composition requires the surface's provider-external set to equal
  the Odds-API capability audit's external set exactly.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pytest

from artifacts.run_it_full import run_full
from sportsedge.canonical_coverage import resolve_market
from sportsedge.market_surface import MarketSurfaceError, load_market_surface
from sportsedge.milestone_ladder_intake import expand_milestone_ladder_rows
from sportsedge.mlb_batter_empirical import (
    BatterEmpiricalError, price_batter_market)
from sportsedge.mlb_public_pitcher_history import MLBPitcherPublicSource
from sportsedge.pitcher_joint_engine import (
    PitcherJointEngineError, price_pitcher_market)

NOW = datetime(2026, 10, 11, 21, 13, tzinfo=timezone.utc)
KICKOFF = "2026-10-12T00:00:00Z"
CAPTURE = "2026-10-11T21:12:10Z"
AWAY, HOME = "Los Angeles Dodgers", "Milwaukee Brewers"
ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- fixtures

def _pitcher_schedule():
    return {"dates": [{"date": "2026-10-11", "games": [{
        "gamePk": 831111, "gameDate": KICKOFF,
        "teams": {
            "home": {"team": {"name": HOME, "id": 158},
                     "probablePitcher": {"id": 800222,
                                         "fullName": "Jacob Misiorowski"}},
            "away": {"team": {"name": AWAY, "id": 119},
                     "probablePitcher": {"id": 800111,
                                         "fullName": "Tarik Skubal"}},
        }}]}]}


_PITCHER_IPS = ["5.1", "6.0", "5.2", "6.1", "4.2", "7.0", "5.0", "6.2"]


def _pitcher_logs(starts=8, *, with_pitches=True):
    splits = []
    for i in range(starts):
        stat = {"gamesStarted": 1, "strikeOuts": 4 + i % 5,
                "inningsPitched": _PITCHER_IPS[i % len(_PITCHER_IPS)],
                "earnedRuns": i % 4, "hits": 3 + i % 5,
                "baseOnBalls": i % 4}
        if with_pitches:
            stat["numberOfPitches"] = 78 + (i * 3) % 25
        splits.append({"date": f"2026-09-{i+1:02d}",
                       "game": {"gamePk": 900100 + i}, "stat": stat})
    return {"stats": [{"splits": splits}]}


def pitcher_getter(url, *, with_pitches=True):
    parsed = urlparse(url)
    assert parsed.hostname == "statsapi.mlb.com", url
    if parsed.path.endswith("/schedule"):
        assert "probablePitcher" in parse_qs(parsed.query)["hydrate"][0]
        return _pitcher_schedule()
    if "/people/" in url and "/stats" in url:
        return _pitcher_logs(with_pitches=with_pitches)
    raise AssertionError(url)


# (hits, doubles, triples, home_runs, rbi, runs, walks, strikeouts) per
# game; singles and total bases are derived exactly as the public source
# derives them, so every game is internally consistent.
_BATTER_GAMES = [
    (2, 1, 0, 0, 1, 1, 0, 1),
    (0, 0, 0, 0, 0, 0, 1, 2),
    (1, 0, 0, 1, 2, 1, 0, 0),
    (3, 1, 1, 0, 1, 2, 1, 1),
    (0, 0, 0, 0, 0, 1, 0, 3),
    (2, 0, 0, 1, 3, 0, 0, 0),
    (1, 0, 1, 0, 0, 1, 1, 2),
    (0, 0, 0, 0, 0, 0, 0, 1),
    (4, 2, 0, 1, 2, 2, 0, 0),
    (1, 1, 0, 0, 0, 0, 1, 0),
    (2, 0, 0, 0, 1, 1, 0, 2),
    (0, 0, 0, 0, 1, 0, 0, 0),
]


def _batter_stat(hits, doubles, triples, hr, rbi, runs, bb, k):
    singles = hits - doubles - triples - hr
    assert singles >= 0
    return {"plateAppearances": 4, "hits": hits,
            "totalBases": singles + 2 * doubles + 3 * triples + 4 * hr,
            "rbi": rbi, "runs": runs, "homeRuns": hr, "stolenBases": 0,
            "baseOnBalls": bb, "strikeOuts": k,
            "doubles": doubles, "triples": triples}


def batter_getter(url, *, lineup=True):
    parsed = urlparse(url)
    assert parsed.hostname == "statsapi.mlb.com", url
    path = parsed.path
    if path.endswith("/schedule"):
        return {"dates": [{"games": [{
            "gamePk": 810001, "gameDate": KICKOFF,
            "teams": {"away": {"team": {"name": AWAY, "id": 119}},
                      "home": {"team": {"name": HOME, "id": 158}}}}]}]}
    if path.endswith("/boxscore"):
        player = {"person": {"id": 605141, "fullName": "Mookie Betts"}}
        if lineup:
            player["battingOrder"] = "100"
        return {"teams": {"away": {"players": {"ID605141": player}},
                          "home": {"players": {}}}}
    if "/people/" in path and path.endswith("/stats"):
        splits = [{"date": f"2026-09-{i+1:02d}", "game": {"gamePk": 700100 + i},
                   "stat": _batter_stat(*game)}
                  for i, game in enumerate(_BATTER_GAMES)]
        return {"stats": [{"splits": splits}]}
    raise AssertionError(url)


def prow(market, side, line, odds=-110, player="Jacob Misiorowski", **extra):
    row = {"sport": "MLB", "away": AWAY, "home": HOME, "kickoff": KICKOFF,
           "market": market, "side": side, "line": line, "odds": odds,
           "book": "draftkings", "player_name": player,
           "quote_captured_at": CAPTURE}
    row.update(extra)
    return row


def brow(market, side, line, odds=-110, **extra):
    return prow(market, side, line, odds, player="Mookie Betts", **extra)


def ladder_row(market, form, rungs, *, player):
    row = prow(market, None, None, player=player)
    for key in ("side", "line", "odds"):
        row.pop(key)
    row["milestone_ladder"] = {
        "form": form, "quote_captured_at": CAPTURE,
        "rungs": [{"threshold": t, "odds": o} for t, o in rungs]}
    return row


def full(lines, getter):
    return run_full({"sport": "MLB", "lines": lines},
                    now=NOW, getter=getter)


def _pa_history():
    out = []
    for hits, doubles, triples, hr, rbi, runs, bb, k in _BATTER_GAMES:
        singles = hits - doubles - triples - hr
        out.append({
            "plate_appearances": 4, "hits": hits, "doubles": doubles,
            "triples": triples, "home_runs": hr, "rbi": rbi, "runs": runs,
            "walks": bb, "strikeouts": k, "singles": singles,
            "total_bases": singles + 2 * doubles + 3 * triples + 4 * hr,
            "stolen_bases": 0, "hits_runs_rbis": hits + runs + rbi,
        })
    return out


# ------------------------------------------------------- ITEM 1: pitcher

def _pool(with_pitches=True):
    pool = []
    for i in range(8):
        row = {"strikeouts": 4 + i % 5, "outs": 15 + i % 6,
               "earned_runs": i % 4, "hits_allowed": 3 + i % 5,
               "walks_allowed": i % 4}
        if with_pitches:
            row["pitches"] = 78 + (i * 3) % 25
        pool.append(row)
    return pool


def test_pitcher_pitches_prices_from_measured_pool_counts():
    out = price_pitcher_market({
        "market": "PITCHER_PITCHES", "side": "OVER", "line": 88.5,
        "features": {"history_pool": _pool()}, "game_id": "g",
        "entity_id": "p"})
    raw_over = sum(1 for r in _pool() if r["pitches"] > 88.5) / len(_pool())
    assert 0 < out["model_p"] < 1
    assert out["meta"]["raw_empirical_p"] == raw_over


def test_pitcher_pitches_refuses_pool_without_measured_counts():
    with pytest.raises(PitcherJointEngineError) as exc:
        price_pitcher_market({
            "market": "PITCHER_PITCHES", "side": "OVER", "line": 88.5,
            "features": {"history_pool": _pool(with_pitches=False)},
            "game_id": "g", "entity_id": "p"})
    assert "PITCHER_PITCHES_REQUIRES_MEASURED_PITCH_COUNT" in str(exc.value)


def test_pitcher_history_source_carries_measured_pitch_counts():
    src = MLBPitcherPublicSource(getter=pitcher_getter)
    record = src.prior_starts(
        away=AWAY, home=HOME, player_name="Jacob Misiorowski",
        owner_kickoff=KICKOFF, as_of=NOW.isoformat())
    pitches = [row["pitches"] for row in record["features"]["history_pool"]]
    # Prior starts come back latest-first (dates Sep-08 down to Sep-01).
    assert pitches == [78 + (i * 3) % 25 for i in range(7, -1, -1)]
    assert all(isinstance(p, int) and p > 0 for p in pitches)


@pytest.mark.parametrize("market,line", [
    ("PITCHER_OUTS", 16.5), ("PITCHER_HITS_ALLOWED", 5.5),
    ("PITCHER_BB", 1.5), ("PITCHER_ER", 2.5), ("PITCHER_PITCHES", 88.5),
])
def test_pitcher_family_pairs_price_end_to_end(market, line):
    card = full([prow(market, "OVER", line),
                 prow(market, "UNDER", line, odds=-114)], pitcher_getter)
    assert not card["prop_unpriced"]
    assert (len(card["prop_candidates"]) + len(card["prop_watchlist"])
            + len(card["prop_quarantined"])) == 2
    assert all(held["reason"] == "EXTREME_CLAIMED_EV_QUARANTINE"
               for held in card["prop_quarantined"])
    for row in card["evaluated_rows"]:
        assert row["model_source"].startswith("mlb_pitcher_joint:")
        assert row["source"] == "FREE_MLB_STATSAPI_GAMELOG"
        assert row["prior_start_count"] == 8
        assert 0 < row["model_probability"] < 1
        assert row["research_only"] is True
        assert row["official_authority"] is False


def test_pitcher_pitches_pair_blocked_when_payload_lacks_pitch_counts():
    card = full([prow("PITCHER_PITCHES", "OVER", 88.5),
                 prow("PITCHER_PITCHES", "UNDER", 88.5, odds=-114)],
                lambda url: pitcher_getter(url, with_pitches=False))
    assert len(card["prop_unpriced"]) == 2
    assert all("PITCHER_PITCHES_REQUIRES_MEASURED_PITCH_COUNT"
               in r["reason"] for r in card["prop_unpriced"])


@pytest.mark.parametrize("market,form,rungs,quote_form,state", [
    ("PITCHER_ER", "OR_FEWER", [(0, 150), (1, -150), (2, -450)],
     "MILESTONE_OR_FEWER", "NOT_RUN"),
    ("PITCHER_OUTS", "X_PLUS", [(15, -300), (18, 130)], "MILESTONE_X_PLUS",
     "NOT_RUN"),
    # PITCHER_PITCHES resolves in the canonical coverage authority since
    # its V2 family registration (#2361), carrying the recorded M29
    # verdict as its validation_status; the gate names that state exactly.
    ("PITCHER_PITCHES", "X_PLUS", [(85, -200), (95, 200)],
     "MILESTONE_X_PLUS", "DOES_NOT_BEAT_BASELINE"),
])
def test_pitcher_ladders_reach_model_and_stop_at_single_side_gate(
        market, form, rungs, quote_form, state):
    card = full([ladder_row(market, form, rungs,
                             player="Jacob Misiorowski")], pitcher_getter)
    rows = card["evaluated_rows"]
    assert len(rows) == len(rungs)
    # The model ran (a pitcher receipt exists) and no price was invented:
    # one-sided rows stop at the bridge's single-side validation gate --
    # no family is VALIDATED, and the refusal names the validation state.
    assert card["source_receipts"]
    for row in rows:
        assert row["status"] == "NO_MODEL_OR_MARKET"
        assert row["reason"] == (
            "MILESTONE_SINGLE_SIDE_REQUIRES_VALIDATED_MODEL:" + state)
        assert row["source_quote_form"] == quote_form
        assert "dk_no_vig_p" not in row


# -------------------------------------------------------- ITEM 2: batter

def test_batter_empirical_triples_and_derived_markets_exact_masses():
    hist = _pa_history()
    triples = price_batter_market(
        market="BATTER_TRIPLES", side="OVER", line=0.5, pa_history=hist)
    assert triples["model_p"] == 2 / 12  # games 4 and 7
    xbh = price_batter_market(
        market="BATTER_EXTRA_BASE_HITS", side="OVER", line=0.5,
        pa_history=hist)
    expected = sum(1 for g in hist
                   if g["doubles"] + g["triples"] + g["home_runs"] > 0.5)
    assert xbh["model_p"] == expected / 12
    rr = price_batter_market(
        market="RUNS_RBIS", side="UNDER", line=0.5, pa_history=hist)
    expected_under = sum(1 for g in hist if g["runs"] + g["rbi"] < 0.5)
    assert rr["model_p"] == expected_under / 12


def test_batter_empirical_derived_market_missing_component_fails_closed():
    hist = _pa_history()
    del hist[3]["triples"]
    with pytest.raises(BatterEmpiricalError) as exc:
        price_batter_market(market="EXTRA_BASE_HITS", side="OVER",
                            line=0.5, pa_history=hist)
    assert "triples_INVALID" in str(exc.value)
    # The unrelated HITS market is unaffected by the missing component.
    hits = price_batter_market(market="BATTER_HITS", side="OVER",
                               line=0.5, pa_history=hist)
    assert hits["model_p"] == 8 / 12


def test_batter_empirical_triples_integer_line_push_mass():
    out = price_batter_market(market="TRIPLES", side="OVER", line=0,
                              pa_history=_pa_history())
    assert out["model_p"] == 2 / 12
    assert out["push_p"] == 10 / 12


@pytest.mark.parametrize("market", [
    "BATTER_HITS", "BATTER_TOTAL_BASES", "BATTER_RBIS", "BATTER_RUNS",
    "BATTER_HOME_RUNS", "BATTER_BB", "BATTER_K", "BATTER_SINGLES",
    "DOUBLES", "HITS_RUNS_RBIS",
    "BATTER_TRIPLES", "TRIPLES", "BATTER_EXTRA_BASE_HITS",
    "EXTRA_BASE_HITS", "BATTER_RUNS_RBIS", "RUNS_RBIS",
])
def test_batter_family_pairs_price_end_to_end(market):
    card = full([brow(market, "OVER", 0.5),
                 brow(market, "UNDER", 0.5, odds=-114)], batter_getter)
    assert not card["prop_unpriced"], card["prop_unpriced"]
    assert (len(card["prop_candidates"]) + len(card["prop_watchlist"])
            + len(card["prop_quarantined"])) == 2
    assert all(held["reason"] == "EXTREME_CLAIMED_EV_QUARANTINE"
               for held in card["prop_quarantined"])
    for row in card["evaluated_rows"]:
        assert row["model_source"] == "mlb_batter_empirical_game_log_v1"
        assert row["lineup_status"] == "PUBLIC_BOXSCORE_STARTER_VERIFIED"
        assert row["research_only"] is True


@pytest.mark.parametrize("market,rungs", [
    ("BATTER_HOME_RUNS", [(1, 350)]),
    ("BATTER_K", [(1, -400), (2, 220), (3, 750)]),
    ("BATTER_TRIPLES", [(1, 900)]),
    ("BATTER_EXTRA_BASE_HITS", [(1, -250), (2, 400)]),
    ("BATTER_RUNS_RBIS", [(1, -300), (2, 200), (3, 650)]),
])
def test_batter_ladder_only_families_reach_model(market, rungs):
    card = full([ladder_row(market, "X_PLUS", rungs,
                            player="Mookie Betts")], batter_getter)
    rows = card["evaluated_rows"]
    assert len(rows) == len(rungs)
    assert card["source_receipts"]  # batter history was verified + priced
    for row in rows:
        assert row["status"] == "NO_MODEL_OR_MARKET"
        # Ladder-only family: one-sided rows refuse at the bridge's
        # single-side validation gate, naming the family state.
        assert row["reason"] == (
            "MILESTONE_SINGLE_SIDE_REQUIRES_VALIDATED_MODEL:NOT_RUN")
        assert row["source_quote_form"] == "MILESTONE_X_PLUS"
        assert "dk_no_vig_p" not in row


def test_batter_ladder_rung_beyond_empirical_support_refuses_by_name():
    # No fixture game has 2+ home runs: the empirical distribution assigns
    # the rung zero mass and the adapter's degenerate-probability rule
    # refuses it by name instead of emitting a 0/1 probability.
    card = full([ladder_row("BATTER_HOME_RUNS", "X_PLUS", [(2, 1400)],
                            player="Mookie Betts")], batter_getter)
    row = card["evaluated_rows"][0]
    assert row["status"] == "NO_MODEL_OR_MARKET"
    # Re-contract: this is a valid 0-event empirical count, not corrupted
    # probability accounting. No calibrated extrapolation model exists.
    assert row["reason"] == "EMPIRICAL_DEGENERATE_TAIL_NO_VALIDATED_MODEL"
    assert "model_probability" not in row
    assert "ev_per_dollar" not in row
    assert "dk_no_vig_p" not in row


def test_batter_ladder_conversion_and_monotonicity_refusal():
    rows = expand_milestone_ladder_rows([{
        "sport": "MLB", "market": "BATTER_HOME_RUNS",
        "player_name": "Mookie Betts", "quote_captured_at": CAPTURE,
        "milestone_ladder": {"form": "X_PLUS",
                             "rungs": [{"threshold": 1, "odds": 350},
                                       {"threshold": 2, "odds": 1400}]}}])
    assert [r["line"] for r in rows] == [0.5, 1.5]
    assert all(r["side"] == "OVER" for r in rows)
    assert all(r["source_quote_form"] == "MILESTONE_X_PLUS" for r in rows)
    refused = expand_milestone_ladder_rows([{
        "sport": "MLB", "market": "BATTER_K",
        "player_name": "Mookie Betts", "quote_captured_at": CAPTURE,
        "milestone_ladder": {"form": "X_PLUS",
                             "rungs": [{"threshold": 1, "odds": 500},
                                       {"threshold": 2, "odds": -200}]}}])
    assert refused[0]["milestone_ladder_refusal"] == \
        "MILESTONE_LADDER_NON_MONOTONE"


def test_batter_lineup_gate_unchanged_no_lineup_no_candidate():
    card = full([brow("BATTER_HITS", "OVER", 0.5),
                 brow("BATTER_HITS", "UNDER", 0.5, odds=-114)],
                lambda url: batter_getter(url, lineup=False))
    assert not card["prop_candidates"]
    status = {r["selection"]: r["status"] for r in card["evaluated_rows"]}
    # The gate demotes the row that would otherwise be a candidate; a
    # below-floor row was never a candidate and keeps its own status.
    # The invariant the gate guarantees: no candidate without a lineup.
    assert status["OVER"] == "WATCH_LINEUP_NOT_CONFIRMED"
    assert status["UNDER"] == "WATCH_BELOW_EV_FLOOR"


def test_coverage_resolves_newly_wired_batter_families_priced():
    for name in ("TRIPLES", "EXTRA_BASE_HITS", "RUNS_RBIS",
                 "BATTER_TRIPLES", "BATTER_EXTRA_BASE_HITS",
                 "BATTER_RUNS_RBIS"):
        res = resolve_market("MLB", name)
        assert res["state"] == "PRICED_PATH", name
    detail = resolve_market("MLB", "EXTRA_BASE_HITS")["detail"]
    assert "milestone ladder" in detail  # form truth recorded (ITEM 3d)


def test_stolen_bases_still_blocked_no_quote():
    card = full([brow("BATTER_STOLEN_BASES", "OVER", 0.5),
                 brow("BATTER_STOLEN_BASES", "UNDER", 0.5, odds=-114)],
                batter_getter)
    assert len(card["prop_unpriced"]) == 2
    assert all(r["blocker"] == "NO_QUOTE" for r in card["prop_unpriced"])


# ------------------------------------------- ITEM 3: ratification pins

def test_surface_loader_forbids_unavailable_plus_provider_expected(
        tmp_path):
    # The loader's contradiction rule is why the DK-board availability
    # truth for F5_TOTALS (DK: verified absent) cannot be written into
    # the surface while its verified Odds-API route exists: the fused
    # schema has no field that separates the two claims.
    raw = json.loads((ROOT / "config/mlb_market_surface.json").read_text())
    for row in raw["markets"]:
        if row["market"] == "F5_TOTALS":
            row["declared_availability"] = "UNAVAILABLE"
    bad = tmp_path / "surface.json"
    bad.write_text(json.dumps(raw))
    with pytest.raises(MarketSurfaceError) as exc:
        load_market_surface(bad)
    assert "AVAILABILITY_PROVIDER_CONTRADICTION" in str(exc.value)


def test_surface_external_set_matches_capability_audit_today():
    # mlb_finish_line raises unless these sets are identical: any
    # provider_expected flip in the surface forces a matching edit to
    # the Odds-API capability audit, whose claims are separately
    # verified (published key catalog). This identity is the bounded
    # blast radius documented in the wiring report's ratification item.
    surface = json.loads(
        (ROOT / "config/mlb_market_surface.json").read_text())
    external = {row["market"] for row in surface["markets"]
                if row["provider_expected"] is not True}
    audit = json.loads(
        (ROOT / "config/mlb_provider_capability_audit.json").read_text())
    assert external == set(audit["external_markets"])
    # The audited provider frame, stated in the audit itself.
    assert audit["provider"] == "THE_ODDS_API"
    assert "totals_1st_5_innings" in \
        audit["published_baseball_period_market_keys_relevant_to_catalog"]
    assert "batter_stolen_bases" in audit["published_mlb_player_market_keys"]


@pytest.mark.parametrize("invalid", [True, False, 1.8, 3.2, "2.5", float("nan"), float("inf"), None])
@pytest.mark.parametrize("market", ["EXTRA_BASE_HITS", "RUNS_RBIS"])
def test_derived_batter_market_rejects_noninteger_or_boolean_components(invalid, market):
    base = {"doubles": 1, "triples": 0, "home_runs": 0, "runs": 1, "rbi": 1}
    component = "doubles" if market == "EXTRA_BASE_HITS" else "runs"
    rows = [dict(base) for _ in range(10)]
    rows[0][component] = invalid
    with pytest.raises(BatterEmpiricalError, match="INVALID|NONINTEGER"):
        price_batter_market(market=market, side="OVER", line=0.5,
                            pa_history=rows)


def test_stolen_bases_quote_refusal_is_fixture_specific_not_global_absence():
    result = resolve_market("MLB", "STOLEN_BASES")
    assert result["state"] == "BLOCKED" and result["blocker"] == "NO_QUOTE"
    assert "NOT_OBSERVED_ON_INSPECTED_FIXTURE" in result["detail"]
    assert "global" in result["detail"]


def test_mlb_ladder_only_form_claims_are_observation_scoped():
    for market in ("HOME_RUNS", "BATTER_K", "EXTRA_BASE_HITS", "TRIPLES", "RUNS_RBIS"):
        result = resolve_market("MLB", market)
        assert result["state"] == "PRICED_PATH"
        assert "FIXTURE OBSERVATION" in result["detail"]
