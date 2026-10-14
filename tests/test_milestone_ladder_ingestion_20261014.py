"""Milestone-ladder prop ingestion battery (SPEC rev. 2, Oct 14 2026).

Owner contract: DraftKings "X+" converts to Over (X - 0.5) with the REAL
offered price and the ladder's original shared capture; the "N or Fewer"
mirror converts to Under (N + 0.5). No opposite-side price is ever
invented; one-sided rows take the existing pipelines' own named blockers
(the three-sport bridge's EXACT_PAIRED_DK_QUOTE_REQUIRED). CFB ladders are
parser fixtures only -- their rows must still die at the registry gate.

Fixtures are verbatim from the Oct 14, 2026 DraftKings pull recorded in
~/workspace/sportsedge/diagnostic_run_20261014/REPORT.md.
"""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pytest

from artifacts.run_it_full import run_full
from sportsedge.milestone_ladder_intake import (
    MILESTONE_OR_FEWER, MILESTONE_X_PLUS, expand_milestone_ladder_rows)

CAP = "2026-10-14T19:44:00Z"
MLB_GAME = {"sport": "MLB", "away": "Milwaukee Brewers",
            "home": "Los Angeles Dodgers",
            "kickoff": "2026-10-14T19:00:00-05:00", "book": "draftkings",
            "quote_captured_at": CAP}

SNELL_K_RUNGS = [(3, -2600), (4, -890), (5, -382), (6, -184), (7, 106),
                 (8, 199), (9, 370), (10, 680), (11, 1240)]
GASSER_K_RUNGS = [(2, -730), (3, -229), (4, 105), (5, 239), (6, 537),
                  (7, 1140)]
GASSER_ER_RUNGS = [(0, 250), (1, -115), (2, -273), (3, -680), (4, -2100)]
COLLINS_YDS_RUNGS = [(150, -710), (160, -550), (170, -425), (180, -333),
                     (190, -259), (200, -205), (210, -163), (220, -133),
                     (226, -117), (230, -108), (240, 115), (250, 140),
                     (260, 175), (270, 218), (280, 272), (290, 340),
                     (300, 424), (310, 536), (320, 680), (330, 850),
                     (340, 1080)]


def ladder_row(base, form, rungs, **ladder_kw):
    row = dict(base)
    lad = {"form": form,
           "rungs": [{"threshold": t, "odds": o} for t, o in rungs]}
    lad.update(ladder_kw)
    row["milestone_ladder"] = lad
    return row


def snell_ladder(**kw):
    base = dict(MLB_GAME, market="PITCHER_K", player_name="Blake Snell")
    return ladder_row(base, "X_PLUS", SNELL_K_RUNGS, **kw)


# ---------------------------------------------------------------- adapter

def test_snell_k_ladder_conversion_exactness():
    out = expand_milestone_ladder_rows([snell_ladder()])
    assert len(out) == len(SNELL_K_RUNGS)
    assert [r["line"] for r in out] == [2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5,
                                        9.5, 10.5]
    assert [r["odds"] for r in out] == [o for _, o in SNELL_K_RUNGS]
    assert all(r["side"] == "OVER" for r in out)
    # Spot-check the owner's table: 3+ = Over 2.5, 11+ = Over 10.5.
    assert out[0]["milestone_threshold"] == 3 and out[0]["line"] == 2.5
    assert out[-1]["milestone_threshold"] == 11 and out[-1]["line"] == 10.5


def test_emitted_rows_carry_real_price_original_capture_provenance():
    out = expand_milestone_ladder_rows([snell_ladder()])
    for r in out:
        assert r["quote_captured_at"] == CAP  # never retimestamped
        assert r["source_quote_form"] == MILESTONE_X_PLUS
        assert r["book"] == "draftkings"
        assert r["player_name"] == "Blake Snell"
        assert "milestone_ladder" not in r


def test_no_fabricated_opposite_side_price_on_emitted_rows():
    row = snell_ladder()
    row["under_odds"] = -110          # intake junk claiming an Under price
    row["opposite_odds"] = -110
    out = expand_milestone_ladder_rows([row])
    for r in out:
        for key in ("under_odds", "opposite_odds", "paired_odds",
                    "complement_odds", "no_vig_p", "dk_no_vig_p",
                    "fair_odds", "under_price", "opposite_price"):
            assert key not in r, key
        # The only price on the row is the rung's own real Over price.
        assert r["odds"] == r["price"]


def test_gasser_er_mirror_ladder_converts_to_under():
    base = dict(MLB_GAME, market="PITCHER_ER", player_name="Robert Gasser")
    out = expand_milestone_ladder_rows(
        [ladder_row(base, "OR_FEWER", GASSER_ER_RUNGS)])
    assert [r["line"] for r in out] == [0.5, 1.5, 2.5, 3.5, 4.5]
    assert all(r["side"] == "UNDER" for r in out)
    assert all(r["source_quote_form"] == MILESTONE_OR_FEWER for r in out)
    # Owner's table: 2-or-Fewer = Under 2.5.
    assert out[2]["milestone_threshold"] == 2 and out[2]["line"] == 2.5


def test_nfl_passing_yard_threshold_conversion():
    base = {"sport": "NFL", "market": "PASSING_YARDS",
            "player_name": "Matthew Stafford", "away": "Buffalo Bills",
            "home": "Los Angeles Rams", "kickoff": "2026-10-13T00:15:00Z",
            "book": "draftkings", "quote_captured_at": CAP}
    out = expand_milestone_ladder_rows(
        [ladder_row(base, "X_PLUS", [(150, -710), (340, 1080)])])
    assert [(r["line"], r["side"]) for r in out] == [(149.5, "OVER"),
                                                     (339.5, "OVER")]


def test_irregular_rung_accepted_without_interpolation():
    base = {"sport": "CFB", "market": "PLAYER_PASSING_YARDS",
            "player_name": "Rickie Collins", "away": "Kennesaw State Owls",
            "home": "Missouri State Bears",
            "kickoff": "2026-10-14T18:30:00-05:00", "book": "draftkings",
            "quote_captured_at": CAP}
    out = expand_milestone_ladder_rows(
        [ladder_row(base, "X_PLUS", COLLINS_YDS_RUNGS)])
    assert len(out) == len(COLLINS_YDS_RUNGS)  # nothing interpolated
    lines = [r["line"] for r in out]
    assert 225.5 in lines        # the irregular 226+ rung, converted
    assert 226.5 not in lines    # ... and no invented neighbours
    assert lines == sorted(lines)


def _refusal(row):
    out = expand_milestone_ladder_rows([row])
    assert len(out) == 1
    return out[0]["milestone_ladder_refusal"]


def test_refusal_non_monotone_ge_ladder():
    row = snell_ladder()
    row["milestone_ladder"]["rungs"] = [
        {"threshold": 3, "odds": -110}, {"threshold": 4, "odds": -2600}]
    assert _refusal(row) == "MILESTONE_LADDER_NON_MONOTONE"


def test_refusal_non_monotone_mirror_ladder():
    base = dict(MLB_GAME, market="PITCHER_ER", player_name="Robert Gasser")
    row = ladder_row(base, "OR_FEWER", [(1, -680), (2, 250)])
    assert _refusal(row) == "MILESTONE_LADDER_NON_MONOTONE"


def test_refusal_duplicate_rung():
    row = snell_ladder()
    row["milestone_ladder"]["rungs"] = [
        {"threshold": 3, "odds": -2600}, {"threshold": 3, "odds": -900}]
    assert _refusal(row) == "MILESTONE_LADDER_DUPLICATE_RUNG"


def test_refusal_mixed_capture():
    row = snell_ladder()
    row["milestone_ladder"]["rungs"] = [
        {"threshold": 3, "odds": -2600, "quote_captured_at": CAP},
        {"threshold": 4, "odds": -890,
         "quote_captured_at": "2026-10-14T19:40:00Z"}]
    assert _refusal(row) == "MILESTONE_LADDER_MIXED_CAPTURE"


def test_refusal_player_mismatch():
    row = snell_ladder()
    row["milestone_ladder"]["rungs"] = [
        {"threshold": 3, "odds": -2600, "player_name": "Robert Gasser"}]
    assert _refusal(row) == "MILESTONE_LADDER_PLAYER_MISMATCH"


def test_refusal_unsupported_market_and_malformed():
    row = snell_ladder()
    row["market"] = "BATTER_HITS"
    assert _refusal(row) == "MILESTONE_LADDER_MARKET_UNSUPPORTED"
    row = snell_ladder()
    row["milestone_ladder"]["rungs"] = []
    assert _refusal(row) == "MILESTONE_LADDER_MALFORMED"


def test_single_rung_is_a_single_milestone_quote():
    row = snell_ladder()
    row["milestone_ladder"]["rungs"] = [{"threshold": 7, "odds": 106}]
    out = expand_milestone_ladder_rows([row])
    assert len(out) == 1
    assert out[0]["side"] == "OVER" and out[0]["line"] == 6.5


def test_non_ladder_rows_pass_through_untouched():
    plain = {"sport": "MLB", "market": "MONEYLINE", "side": "AWAY",
             "odds": 150}
    out = expand_milestone_ladder_rows([plain])
    assert out[0] is plain


# ------------------------------------------------------- runner: MLB K

def _statsapi_schedule():
    return {"dates": [{"date": "2026-10-11", "games": [{
        "gamePk": 831111, "gameDate": "2026-10-12T00:00:00Z",
        "teams": {
            "home": {"team": {"name": "Milwaukee Brewers", "id": 158},
                     "probablePitcher": {"id": 800222,
                                         "fullName": "Robert Gasser"}},
            "away": {"team": {"name": "Los Angeles Dodgers", "id": 119},
                     "probablePitcher": {"id": 800111,
                                         "fullName": "Blake Snell"}},
        }}]}]}


def _statsapi_logs(starts=7):
    splits = []
    for i in range(starts):
        splits.append({
            "date": f"2026-09-{i+1:02d}",
            "game": {"gamePk": 900100 + i},
            "stat": {"gamesStarted": 1, "strikeOuts": 5 + i % 4,
                     "inningsPitched": "5.2", "earnedRuns": i % 3,
                     "hits": 3 + i % 4, "baseOnBalls": i % 3}})
    return {"stats": [{"type": {"displayName": "gameLog"},
                       "group": {"displayName": "pitching"},
                       "splits": splits}]}


def _statsapi_getter(url):
    host = urlparse(url).hostname
    assert host == "statsapi.mlb.com", url
    if urlparse(url).path.endswith("/schedule"):
        return _statsapi_schedule()
    if "/people/" in url and "/stats" in url:
        return _statsapi_logs()
    raise AssertionError(url)


MLB_AS_OF = datetime(2026, 10, 11, 21, 13, tzinfo=timezone.utc)
MLB_CAPTURE = "2026-10-11T21:12:10Z"


def test_pitcher_k_ladder_reaches_k_pipeline_named_blocker():
    row = {"sport": "MLB", "market": "PITCHER_K",
           "player_name": "Robert Gasser",
           "away": "Los Angeles Dodgers", "home": "Milwaukee Brewers",
           "kickoff": "2026-10-12T00:00:00Z", "book": "draftkings",
           "quote_captured_at": MLB_CAPTURE,
           "milestone_ladder": {"form": "X_PLUS", "rungs": [
               {"threshold": t, "odds": o} for t, o in GASSER_K_RUNGS]}}
    card = run_full({"sport": "MLB", "lines": [row]}, now=MLB_AS_OF,
                    getter=_statsapi_getter, auto_context=True)
    rows = card["evaluated_rows"]
    assert len(rows) == len(GASSER_K_RUNGS)
    assert card["prop_candidates"] == []
    for r in rows:
        # The starter verified via StatsAPI and the empirical model ran;
        # the row then takes the bridge's existing pair requirement --
        # a one-sided milestone quote is never de-vigged or paired with
        # an invented Under price.
        assert r["status"] == "NO_MODEL_OR_MARKET", r
        assert "EXACT_PAIRED_DK_QUOTE_REQUIRED" in (r.get("reason") or "")
        assert r["source"] == "FREE_MLB_STATSAPI_GAMELOG"
        assert r["source_quote_form"] == MILESTONE_X_PLUS
        assert "dk_no_vig_p" not in r
        assert r["prior_start_count"] == 7


def test_refused_ladder_blocks_by_name_through_runner():
    row = snell_ladder()
    row["milestone_ladder"]["rungs"] = [
        {"threshold": 3, "odds": -110}, {"threshold": 4, "odds": -2600}]
    card = run_full({"sport": "MLB", "lines": [row]}, now=MLB_AS_OF,
                    auto_context=False)
    rows = card["evaluated_rows"]
    assert len(rows) == 1
    assert rows[0]["status"] == "NO_MODEL_OR_MARKET"
    assert rows[0]["reason"] == "MILESTONE_LADDER_NON_MONOTONE"
    assert card["prop_candidates"] == [] and card["edges"] == []


# ------------------------------------------------------- runner: NFL

_NFL_FIXTURE = (Path(__file__).parent / "fixtures" / "nfl" /
                "gamelog_stafford_12483_20261012_7games.json")
NFL_KICKOFF = "2026-10-13T00:15:00+00:00"
NFL_AS_OF = datetime(2026, 10, 12, 21, 50, tzinfo=timezone.utc)
NFL_CAPTURE = "2026-10-12T21:49:00Z"
_NFL_ROSTERS = {
    "2": {"team": {"id": "2"}, "athletes": [{"items": [
        {"id": "3918298", "displayName": "Josh Allen"}]}]},
    "14": {"team": {"id": "14"}, "athletes": [{"items": [
        {"id": "12483", "displayName": "Matthew Stafford"}]}]},
}


def _nfl_getter(url):
    path = urlparse(url).path
    if path.endswith("/scoreboard"):
        return {"events": [{"id": "401873001", "date": NFL_KICKOFF,
                "competitions": [{"competitors": [
                    {"homeAway": "home",
                     "team": {"id": "14", "displayName": "Los Angeles Rams"}},
                    {"homeAway": "away",
                     "team": {"id": "2", "displayName": "Buffalo Bills"}},
                ]}]}]}
    if "/teams/" in path and path.endswith("/roster"):
        return _NFL_ROSTERS.get(path.split("/teams/")[1].split("/")[0])
    if path.endswith("/gamelog"):
        data = json.loads(_NFL_FIXTURE.read_text())
        for meta in data["events"].values():
            meta.setdefault("gameResult", "W")
        return data
    if path.endswith("/search/v2"):
        return {"results": []}
    raise AssertionError("Unexpected ESPN URL: " + url)


def _stafford_ladder_row():
    return {"sport": "NFL", "market": "PASSING_YARDS",
            "player_name": "Matthew Stafford", "away": "Buffalo Bills",
            "home": "Los Angeles Rams", "kickoff": NFL_KICKOFF,
            "book": "draftkings", "quote_captured_at": NFL_CAPTURE,
            "milestone_ladder": {"form": "X_PLUS", "rungs": [
                {"threshold": 200, "odds": -205},
                {"threshold": 250, "odds": 140},
                {"threshold": 300, "odds": 295}]}}


def test_nfl_passing_ladder_canonical_path_governance_blocker():
    # On the canonical path, NFL player props are governance NO_ENGINE
    # (canonical_coverage): converted rung rows land at exactly the same
    # named blocker a native O/U pair lands at -- with one-sided
    # provenance visible -- instead of dying as an unconverted ladder.
    card = run_full({"sport": "NFL", "lines": [_stafford_ladder_row()]},
                    now=NFL_AS_OF, getter=_nfl_getter, auto_context=True)
    rows = card["evaluated_rows"]
    assert len(rows) == 3
    assert card["prop_candidates"] == []
    for r in rows:
        assert r["status"] == "NO_MODEL_OR_MARKET", r
        assert r.get("blocker") == "NO_ENGINE"
        assert "GOVERNANCE_NO_ENGINE" in (r.get("reason") or "")
        assert r["source_quote_form"] == MILESTONE_X_PLUS
        assert "dk_no_vig_p" not in r


def test_nfl_passing_ladder_reaches_empirical_stage():
    # At the stage level (where governance admits the empirical pricer),
    # expanded rung rows verify identity from ESPN gamelogs, the model
    # runs, and each one-sided row takes the bridge's pair requirement.
    from sportsedge.nfl_phone_player_pricing import phone_nfl_player_rows
    row = _stafford_ladder_row()
    row["market"] = "PLAYER_PASSING_YARDS"  # canonical stage-level name
    expanded = expand_milestone_ladder_rows([row])
    assert len(expanded) == 3
    results, receipts = phone_nfl_player_rows(
        expanded, now=NFL_AS_OF, getter=_nfl_getter)
    assert len(results) == 3 and len(receipts) == 1
    for r in results:
        assert r["status"] == "NO_MODEL_OR_MARKET", r
        assert "EXACT_PAIRED_DK_QUOTE_REQUIRED" in (r.get("reason") or "")
        assert r["source"] == "FREE_ESPN_NFL_GAMELOG"
        assert r["prior_game_count"] == 7
        assert "dk_no_vig_p" not in r


# ------------------------------------------------------- runner: CFB HOLD

def test_cfb_ladder_rows_die_at_registry_gate_not_intake():
    row = {"sport": "CFB", "market": "PLAYER_PASSING_YARDS",
           "player_name": "Rickie Collins", "away": "Kennesaw State Owls",
           "home": "Missouri State Bears",
           "kickoff": "2026-10-14T18:30:00-05:00",
           "commence_time": "2026-10-14T23:30:00Z", "book": "draftkings",
           "quote_captured_at": CAP,
           "milestone_ladder": {"form": "X_PLUS", "rungs": [
               {"threshold": t, "odds": o} for t, o in COLLINS_YDS_RUNGS]}}
    now = datetime(2026, 10, 14, 19, 46, tzinfo=timezone.utc)
    card = run_full({"lines": [row]}, now=now, auto_context=False)
    rows = card["evaluated_rows"]
    assert len(rows) == len(COLLINS_YDS_RUNGS)  # ingested, not intake-dead
    assert card["prop_candidates"] == [] and card["edges"] == []
    for r in rows:
        assert r["status"] == "NO_MODEL_OR_MARKET", r
        assert r.get("registry_enforced") is True
        # The family-registry refusal: PLAYER_PASSING_YARDS is an
        # unregistered CFB family market (blocker NO_ENGINE); registered
        # families name FAMILY_REGISTRY_NOT_VALIDATED instead. Both are
        # the same gate -- the rows were ingested and refused there,
        # never priced and never intake-dead.
        assert "family registry state BLOCKED" in (r.get("reason") or "")
        assert r.get("blocker") in {"NO_VALIDATION", "NO_ENGINE"}
        for key in ("model_probability", "dk_odds", "ev_per_dollar",
                    "dk_no_vig_p"):
            assert r.get(key) is None, (key, r)


# --------------------------------------------- mixed-slate regression

_DIAG = Path("/home/hatch/workspace/sportsedge/diagnostic_run_20261014")


@pytest.mark.skipif(not _DIAG.exists(),
                    reason="diagnostic run folder not present")
def test_mixed_slate_regression_oct14_diagnostic():
    payload = json.loads((_DIAG / "lines.json").read_text())
    now = datetime(2026, 10, 14, 19, 46, tzinfo=timezone.utc)
    card = run_full(payload, now=now, auto_context=False)
    rows = card["evaluated_rows"]
    lines = payload["lines"]
    assert len(rows) == len(lines) == 42

    def group(sport, markets):
        return [r for l, r in zip(lines, rows)
                if l["sport"] == sport and l["market"] in markets]

    # MLB game markets still price exactly as the diagnostic card.
    mlb_core = group("MLB", {"MONEYLINE", "RUN_LINE", "TOTALS"})
    assert [r["status"] for r in mlb_core] == [
        "RESEARCH_POSITIVE_EV_UNVALIDATED", "PRICE_CAP",
        "RESEARCH_POSITIVE_EV_UNVALIDATED", "BELOW_THRESHOLD",
        "RESEARCH_POSITIVE_EV_UNVALIDATED", "BELOW_THRESHOLD"]
    # Composed state (P0 team-totals intake merged, PR #2259): the priced
    # MIL team-total row is a fourth edge. On this branch's pre-P0 base
    # the count was 3 because the team-total rows died at intake.
    assert len(card["edges"]) == 4
    assert sum(1 for e in card["edges"]
               if e.get("market") == "TEAM_TOTALS") == 1

    # F5 refusals intact.
    f5 = [r for l, r in zip(lines, rows)
          if l["market"].startswith("F5")]
    assert len(f5) == 12
    for r in f5:
        assert r["status"] == "NO_MODEL_OR_MARKET"
        assert "F5_DEPLOYMENT_NOT_ELIGIBLE" in (r.get("reason") or "")

    # CFB refusals intact.
    cfb = group("CFB", {"MONEYLINE", "SPREAD", "TOTALS", "TEAM_TOTALS"})
    assert len(cfb) == 20
    for r in cfb:
        assert r["status"] == "NO_MODEL_OR_MARKET"
        assert r.get("registry_enforced") is True

    # MLB team totals are the parallel P0 branch's scope: on this branch
    # they keep the known TEAM_TOTALS_TEAM_REQUIRED intake outcome; the
    # assertion accepts either that or a priced outcome so the battery
    # stays green whichever branch lands first, while still failing on
    # any NEW breakage (missing rows, crashes, wrong families).
    tt = group("MLB", {"TEAM_TOTALS"})
    assert len(tt) == 4
    for r in tt:
        assert (r["status"] == "BLOCKED_INVALID"
                and "TEAM_TOTALS_TEAM_REQUIRED" in (r.get("reason") or "")
                ) or r["status"] in {
                    "RESEARCH_POSITIVE_EV_UNVALIDATED", "PRICE_CAP",
                    "BELOW_THRESHOLD", "RESEARCH_CANDIDATE_NOT_VALIDATED"}


# --------------------------------------- composition with P0 (shared table)

def test_shared_intake_table_carries_both_refusal_producers():
    # Composition proof (post-P0 main): the milestone-ladder refusal and
    # the P0 team-totals intake refusal are deposited by two different
    # producers into the ONE shared intake_gated table in run_full and
    # both surface by name in a single run -- neither overwrites the
    # other, and neither row is priced.
    ladder = snell_ladder()
    ladder["milestone_ladder"]["rungs"] = [
        {"threshold": 3, "odds": -110}, {"threshold": 4, "odds": -2600}]
    tt_row = {"sport": "MLB", "market": "TEAM_TOTALS",
              "away": "Milwaukee Brewers", "home": "Los Angeles Dodgers",
              "kickoff": "2026-10-14T19:00:00-05:00", "book": "draftkings",
              "quote_captured_at": CAP, "side": "OVER", "line": 4.5,
              "odds": 114, "team": "Los Angeles Dodgers",
              "team_side": "MIL"}
    now = datetime(2026, 10, 14, 19, 46, tzinfo=timezone.utc)
    card = run_full({"lines": [ladder, tt_row]}, now=now,
                    auto_context=False)
    rows = card["evaluated_rows"]
    assert len(rows) == 2
    milestone = [r for r in rows
                 if r.get("reason") == "MILESTONE_LADDER_NON_MONOTONE"]
    team_total = [r for r in rows
                  if r.get("blocker") == "TEAM_TOTALS_TEAM_SIDE_INVALID"]
    assert len(milestone) == 1 and len(team_total) == 1
    assert milestone[0]["status"] == "NO_MODEL_OR_MARKET"
    assert team_total[0]["status"] == "NO_MODEL_OR_MARKET"
    assert team_total[0]["intake_enforced"] is True
    for r in rows:
        assert "ev_per_dollar" not in r
    assert card["edges"] == []
