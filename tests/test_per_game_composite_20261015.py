"""Per-game freshness composite tests (issue #2359, owner contract).

Covers the contract cases:
(a) two games, the second captured ~200s after the first -> the first
    game's rows still price under per-game evaluation (they were stale
    under the old single global as-of), each row's age judged against its
    own game's operative instant;
(b) a single game whose own section was read >180s before that game's
    operative instant -> that section is still REFRESH REQUIRED
    (per-game evaluation does not rescue an over-long single-game span);
(c) a duplicate selection across game runs (or twice in one) -> the merge
    refuses fail-closed;
(d) quote_captured_at values are byte-identical pre/post merge;
(e) golden: a single-game card through the composite path equals today's
    single-run output on every pre-existing surface;
(f) the composite carries correlated-stack cluster structure for grading
    (owner's card_correlation semantics, not a fork).
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest

from sportsedge.per_game_composite import (
    CompositeRefusal, group_intake_rows, operative_instant_for,
    run_composite)

NOW = datetime(2026, 10, 15, 23, 40, 0, tzinfo=timezone.utc)

MLB_AWAY, MLB_HOME = "Milwaukee Brewers", "Los Angeles Dodgers"
MLB_KICKOFF = "2026-10-16T00:00:00Z"
NFL_AWAY, NFL_HOME = "Seattle Seahawks", "Denver Broncos"
NFL_KICKOFF = "2026-10-16T00:15:00Z"


def _row(sport, away, home, kickoff, market, side, odds, captured, **extra):
    row = {"sport": sport, "away": away, "home": home, "kickoff": kickoff,
           "book": "draftkings", "quote_captured_at": captured,
           "market": market, "side": side, "odds": odds}
    row.update(extra)
    return row


def _two_game_payload():
    """Night-card geometry: game A's first read is >180s before game B's
    final read, but each game's own span is inside 180s."""
    return {"lines": [
        # Game A (MLB): own span 23:33:04 -> 23:33:41 (37s).
        _row("MLB", MLB_AWAY, MLB_HOME, MLB_KICKOFF, "TEAM_TOTALS", "OVER",
             114, "2026-10-15T23:33:04Z", line=4.5, team_side="HOME"),
        _row("MLB", MLB_AWAY, MLB_HOME, MLB_KICKOFF, "MONEYLINE", "AWAY",
             135, "2026-10-15T23:33:41Z"),
        # Game B (NFL): own span 23:36:48 -> 23:36:55 (7s); its final read
        # is 231s after game A's first read.
        _row("NFL", NFL_AWAY, NFL_HOME, NFL_KICKOFF, "MONEYLINE", "AWAY",
             -155, "2026-10-15T23:36:48Z"),
        _row("NFL", NFL_AWAY, NFL_HOME, NFL_KICKOFF, "TOTAL", "OVER",
             -110, "2026-10-15T23:36:55Z", line=44.5),
    ]}


def _freshness(row):
    return row.get("quote_freshness") or {}


# ---------------------------------------------------------------- (a) --

def test_a_cross_game_delay_no_longer_kills_first_game():
    from artifacts.run_it_full import run_full

    payload = _two_game_payload()

    # The old world: one global as-of at the LAST game's final read.
    global_card = run_full(copy.deepcopy(payload), now=NOW,
                           as_of="2026-10-15T23:36:55Z", auto_context=False)
    stale = [r for r in global_card["evaluated_rows"]
             if _freshness(r).get("code") == "QUOTE_STALE_OVER_180S"]
    assert stale, "fixture must reproduce the Oct 15 failure under global as-of"
    assert all(r["status"] == "WATCH_QUOTE_NOT_CURRENT" for r in stale)
    assert {r["market"] for r in stale} == {"TEAM_TOTALS", "ML"}
    assert all(r["game"] == f"{MLB_AWAY} @ {MLB_HOME}" for r in stale)

    # The composite: each game judged at its own operative instant.
    card = run_composite(payload, now=NOW, auto_context=False)
    games = card["composite"]["games"]
    assert [g["operative_instant_utc"] for g in games] == [
        "2026-10-15T23:33:41+00:00", "2026-10-15T23:36:55+00:00"]

    by_market = {(r["sport"], r["market"]): r for r in card["evaluated_rows"]}
    tt = by_market[("MLB", "TEAM_TOTALS")]
    ml = by_market[("MLB", "ML")]
    # Ages judged vs game A's own instant (23:33:41), not game B's.
    assert _freshness(tt)["age_seconds"] == 37.0
    assert _freshness(ml)["age_seconds"] == 0.0
    assert _freshness(tt)["code"] == "QUOTE_FRESH_UNDER_180S"
    assert tt["status"] != "WATCH_QUOTE_NOT_CURRENT"
    assert ml["status"] != "WATCH_QUOTE_NOT_CURRENT"
    # Game B judged vs its own instant too.
    nfl_ml = by_market[("NFL", "ML")]
    assert _freshness(nfl_ml)["age_seconds"] == 7.0
    # The first game's moneyline actually prices (it was stale globally).
    assert ml["status"] == "RESEARCH_POSITIVE_EV_UNVALIDATED"
    assert any(e["input_index"] == ml["input_index"] for e in card["edges"])


# ---------------------------------------------------------------- (b) --

def test_b_single_game_overlong_span_still_refresh_required():
    payload = {"lines": [
        # One game, own span 221s: the totals section was read long before
        # the game's final verification read (the moneyline).
        _row("MLB", MLB_AWAY, MLB_HOME, MLB_KICKOFF, "TOTALS", "OVER",
             -110, "2026-10-15T23:30:00Z", line=8.5),
        _row("MLB", MLB_AWAY, MLB_HOME, MLB_KICKOFF, "MONEYLINE", "AWAY",
             135, "2026-10-15T23:33:41Z"),
    ]}
    card = run_composite(payload, now=NOW, auto_context=False)
    assert len(card["composite"]["games"]) == 1
    by_market = {r["market"]: r for r in card["evaluated_rows"]}
    totals = by_market["TOTAL"]
    assert _freshness(totals)["age_seconds"] == 221.0
    assert _freshness(totals)["code"] == "QUOTE_STALE_OVER_180S"
    assert totals["status"] == "WATCH_QUOTE_NOT_CURRENT"  # REFRESH REQUIRED
    # The fresh section of the same game is unaffected.
    assert by_market["ML"]["status"] == "RESEARCH_POSITIVE_EV_UNVALIDATED"


# ---------------------------------------------------------------- (c) --

def _stub_card(rows, *, as_of):
    """Minimal per-game card in run_full's shape for merge unit tests."""
    evaluated = []
    for i, row in enumerate(rows):
        evaluated.append({"input_index": i, "status": "RESEARCH_POSITIVE_EV_UNVALIDATED",
                          **row})
    return {
        "schema": "SPORTSEDGE_FREE_RESEARCH_CARD_V1",
        "as_of_utc": as_of, "wall_utc": as_of,
        "authority": {}, "quote_freshness_policy": {"max_age_seconds": 180},
        "min_ev": 0.02, "primary_lane": "LANE_A_INDEPENDENT",
        "play_gate": {}, "canonical_coverage": {}, "runner": "STUB",
        "research_projection_note": "stub",
        "edges": list(evaluated), "lane_b_edges": [], "lane_b_watchlist": [],
        "independent_candidates": [], "independent_watchlist": [],
        "evaluated_rows": evaluated,
        "prop_candidates": [], "prop_watchlist": [], "prop_unpriced": [],
        "diagnostics": [], "source_receipts": [],
        "selection_intake": [{"sport": r["sport"]} for r in evaluated],
        "summary": {"rows": len(evaluated), "edges": len(evaluated),
                    "lane_b_edges": 0, "lane_b_watchlist": 0,
                    "status_counts": {"RESEARCH_POSITIVE_EV_UNVALIDATED": len(evaluated)}},
        "factor_coverage": {"schema": "FC", "by_input_index": [],
                            "status_counts": {}, "advanced_metrics": {}},
        "prepricing_factor_audit": {"schema": "PF",
                                    "market_odds_as_features": False,
                                    "by_input_index": []},
        "prop_model_status": {"unsupported_player_markets_blocked": 0},
        "input_snapshot": {"n_rows": len(evaluated), "rows_sha1": "x",
                           "as_of_utc": as_of, "wall_utc": as_of,
                           "historical_repriced": False},
    }


def _game_row(game, kickoff, market, selection, line=None, **extra):
    row = {"sport": "MLB", "game": game, "kickoff_utc": kickoff,
           "market": market, "selection": selection, "line": line}
    row.update(extra)
    return row


def test_c_duplicate_selection_across_game_runs_refuses():
    game_a = f"{MLB_AWAY} @ {MLB_HOME}"
    game_b = "Chicago Cubs @ St. Louis Cardinals"
    shared = _game_row(game_a, "2026-10-16T00:00:00+00:00", "MONEYLINE",
                       "Los Angeles Dodgers", game_id="evt-1")
    cards = iter([
        _stub_card([shared], as_of="2026-10-15T23:33:41+00:00"),
        # A different game run surfacing the SAME selection identity
        # (same recorded game_id) is a data-integrity failure.
        _stub_card([dict(shared)], as_of="2026-10-15T23:36:55+00:00"),
    ])
    payload = {"lines": [
        _row("MLB", MLB_AWAY, MLB_HOME, MLB_KICKOFF, "MONEYLINE", "HOME",
             -150, "2026-10-15T23:33:41Z"),
        _row("MLB", "Chicago Cubs", "St. Louis Cardinals",
             "2026-10-16T00:05:00Z", "MONEYLINE", "HOME", -120,
             "2026-10-15T23:36:55Z"),
    ]}
    with pytest.raises(CompositeRefusal, match="COMPOSITE_DUPLICATE_SELECTION"):
        run_composite(payload, now=NOW, run_full_fn=lambda *a, **k: next(cards))


def test_c_duplicate_selection_twice_in_one_run_refuses():
    game_a = f"{MLB_AWAY} @ {MLB_HOME}"
    dup = _game_row(game_a, "2026-10-16T00:00:00+00:00", "MONEYLINE",
                    "Los Angeles Dodgers")
    payload = {"lines": [
        _row("MLB", MLB_AWAY, MLB_HOME, MLB_KICKOFF, "MONEYLINE", "HOME",
             -150, "2026-10-15T23:33:04Z"),
        _row("MLB", MLB_AWAY, MLB_HOME, MLB_KICKOFF, "MONEYLINE", "HOME",
             -150, "2026-10-15T23:33:41Z"),
    ]}
    card = _stub_card([dup, dict(dup)], as_of="2026-10-15T23:33:41+00:00")
    with pytest.raises(CompositeRefusal, match="COMPOSITE_DUPLICATE_SELECTION"):
        run_composite(payload, now=NOW, run_full_fn=lambda *a, **k: card)


def test_c_duplicate_real_duplicate_intake_row_refuses():
    row = _row("MLB", MLB_AWAY, MLB_HOME, MLB_KICKOFF, "MONEYLINE", "AWAY",
               135, "2026-10-15T23:33:41Z")
    with pytest.raises(CompositeRefusal, match="COMPOSITE_DUPLICATE_SELECTION"):
        run_composite({"lines": [row, dict(row)]}, now=NOW, auto_context=False)


# ---------------------------------------------------------------- (d) --

def test_d_quote_captured_at_byte_identical_pre_post_merge():
    payload = _two_game_payload()
    before = json.dumps(payload, sort_keys=True)
    stamps_before = [r["quote_captured_at"] for r in payload["lines"]]
    card = run_composite(payload, now=NOW, auto_context=False)
    # The caller's payload object is untouched, byte for byte.
    assert json.dumps(payload, sort_keys=True) == before
    assert [r["quote_captured_at"] for r in payload["lines"]] == stamps_before
    # The composite audit block records the original stamps verbatim.
    recorded = [s for g in card["composite"]["games"]
                for s in g["quote_captured_at_stamps"]]
    assert sorted(recorded) == sorted(set(stamps_before))
    for stamp in recorded:
        assert stamp in stamps_before


# ---------------------------------------------------------------- (e) --

def _strip_composite_additions(row):
    out = dict(row)
    out.pop("game_id", None)  # composite cluster-key enrichment (additive)
    return out


def test_e_golden_single_game_composite_equals_single_run():
    from artifacts.run_it_full import run_full

    payload = {"lines": [
        _row("MLB", MLB_AWAY, MLB_HOME, MLB_KICKOFF, "TEAM_TOTALS", "OVER",
             114, "2026-10-15T23:33:04Z", line=4.5, team_side="HOME"),
        _row("MLB", MLB_AWAY, MLB_HOME, MLB_KICKOFF, "MONEYLINE", "AWAY",
             135, "2026-10-15T23:33:41Z"),
        _row("MLB", MLB_AWAY, MLB_HOME, MLB_KICKOFF, "MONEYLINE", "HOME",
             -155, "2026-10-15T23:33:41Z"),
    ]}
    single = run_full(copy.deepcopy(payload), now=NOW,
                      as_of="2026-10-15T23:33:41Z", auto_context=False)
    composite = run_composite(payload, now=NOW, auto_context=False)

    assert [_strip_composite_additions(r) for r in composite["evaluated_rows"]] == \
           [_strip_composite_additions(r) for r in single["evaluated_rows"]]
    for surface in ("edges", "lane_b_edges", "lane_b_watchlist",
                    "independent_candidates", "independent_watchlist",
                    "prop_candidates", "prop_watchlist", "prop_unpriced"):
        assert [_strip_composite_additions(r) for r in composite[surface]] == \
               [_strip_composite_additions(r) for r in single[surface]], surface
    assert composite["summary"]["rows"] == single["summary"]["rows"]
    assert composite["summary"]["edges"] == single["summary"]["edges"]
    assert composite["summary"]["status_counts"] == single["summary"]["status_counts"]
    assert composite["summary"]["mlb_market_coverage"] == \
        single["summary"]["mlb_market_coverage"]
    assert composite["mlb_full_board"]["input_coverage"] == \
        single["mlb_full_board"]["input_coverage"]
    assert composite["as_of_utc"] == single["as_of_utc"]
    assert composite["schema"] == single["schema"]
    # The composite only ADDS structure; it does not present as one instant.
    assert composite["composite"]["kind"] == "PER_GAME_EVALUATION_COMPOSITE"
    assert composite["composite"]["games"][0]["operative_instant_utc"] == \
        "2026-10-15T23:33:41+00:00"
    assert composite["input_snapshot"]["composite"] is True


# ---------------------------------------------------------------- (f) --

def test_f_cluster_structure_present_for_grading():
    game_a = f"{MLB_AWAY} @ {MLB_HOME}"
    game_b = f"{NFL_AWAY} @ {NFL_HOME}"
    cards = iter([
        _stub_card([
            _game_row(game_a, "2026-10-16T00:00:00+00:00", "MONEYLINE",
                      "Los Angeles Dodgers"),
            _game_row(game_a, "2026-10-16T00:00:00+00:00", "TOTALS",
                      "OVER 8.5", line=8.5),
        ], as_of="2026-10-15T23:33:41+00:00"),
        _stub_card([
            _game_row(game_b, "2026-10-16T00:15:00+00:00", "MONEYLINE",
                      "Seattle Seahawks"),
        ], as_of="2026-10-15T23:36:55+00:00"),
    ])
    payload = {"lines": [
        _row("MLB", MLB_AWAY, MLB_HOME, MLB_KICKOFF, "MONEYLINE", "HOME",
             -150, "2026-10-15T23:33:41Z"),
        _row("MLB", MLB_AWAY, MLB_HOME, MLB_KICKOFF, "TOTALS", "OVER",
             -110, "2026-10-15T23:33:30Z", line=8.5),
        _row("NFL", NFL_AWAY, NFL_HOME, NFL_KICKOFF, "MONEYLINE", "AWAY",
             -155, "2026-10-15T23:36:55Z"),
    ]}
    card = run_composite(payload, now=NOW, run_full_fn=lambda *a, **k: next(cards))
    accounting = card["position_accounting"]
    assert accounting["accounting"] == "CORRELATED_STACK_AS_SINGLE_POSITION"
    # Two legs in game A are ONE position (one evidence cluster); game B's
    # leg is a second position.  Legs never grade as independent positions.
    assert accounting["positions"] == 2
    assert accounting["legs"] == 3
    assert card["summary"]["surfaced_positions"] == 2
    assert card["summary"]["surfaced_legs"] == 3
    stack_sizes = sorted(len(s["legs"]) for s in accounting["stacks"])
    assert stack_sizes == [1, 2]
    # The owner's own function, applied to the merged surfaces, agrees.
    from sportsedge.card_correlation import grade_card_positions
    recomputed = grade_card_positions(card["edges"])
    assert recomputed["positions"] == accounting["positions"]
    assert recomputed["legs"] == accounting["legs"]


def test_f_real_card_carries_position_accounting():
    card = run_composite(_two_game_payload(), now=NOW, auto_context=False)
    accounting = card["position_accounting"]
    assert accounting["accounting"] == "CORRELATED_STACK_AS_SINGLE_POSITION"
    # One evidence cluster per game across the whole composite: the four
    # surfaced legs collapse to two positions, never four independents.
    assert accounting["positions"] == 2
    assert accounting["legs"] == 4
    assert card["summary"]["surfaced_positions"] == 2
    assert card["summary"]["surfaced_legs"] == 4
    assert {s["stack_key"] for s in accounting["stacks"]} == {
        "MLB|Milwaukee Brewers|Los Angeles Dodgers|2026-10-16T00:00:00+00:00",
        "NFL|Seattle Seahawks|Denver Broncos|2026-10-16T00:15:00+00:00",
    }


# ------------------------------------------------------- guard rails --

def test_grouping_binds_complete_market_set_and_doubleheaders():
    rows = [
        _row("MLB", MLB_AWAY, MLB_HOME, MLB_KICKOFF, "MONEYLINE", "AWAY",
             135, "2026-10-15T23:33:41Z"),
        _row("NFL", NFL_AWAY, NFL_HOME, NFL_KICKOFF, "MONEYLINE", "AWAY",
             -155, "2026-10-15T23:36:55Z"),
        # Same MLB game, separated in the payload: still one group.
        _row("MLB", MLB_AWAY, MLB_HOME, MLB_KICKOFF, "TOTALS", "OVER",
             -110, "2026-10-15T23:33:20Z", line=8.5),
        # Doubleheader: same teams, different kickoff -> its own game.
        _row("MLB", MLB_AWAY, MLB_HOME, "2026-10-16T03:00:00Z", "MONEYLINE",
             "AWAY", 120, "2026-10-15T23:37:10Z"),
    ]
    groups = group_intake_rows(rows)
    assert len(groups) == 3
    assert [len(g) for _, g in groups] == [2, 1, 1]


def test_operative_instant_rules():
    stamps = ["2026-10-15T23:33:04Z", "2026-10-15T23:33:41Z"]
    instant = operative_instant_for(stamps)
    assert instant.isoformat() == "2026-10-15T23:33:41+00:00"
    with pytest.raises(CompositeRefusal,
                       match="COMPOSITE_OPERATIVE_INSTANT_UNRECORDED"):
        operative_instant_for([None, "not-a-time"])
    earlier = datetime(2026, 10, 15, 23, 33, 0, tzinfo=timezone.utc)
    with pytest.raises(CompositeRefusal,
                       match="COMPOSITE_OPERATIVE_INSTANT_PRECEDES_CAPTURE"):
        operative_instant_for(stamps, override=earlier)


def test_unsupported_payload_key_refuses():
    payload = _two_game_payload()
    payload["cfb_public_context"] = {"declared": True}
    with pytest.raises(CompositeRefusal,
                       match="COMPOSITE_PAYLOAD_KEY_UNSUPPORTED"):
        run_composite(payload, now=NOW, auto_context=False)


def test_missing_game_identity_refuses():
    row = _row("MLB", MLB_AWAY, MLB_HOME, MLB_KICKOFF, "MONEYLINE", "AWAY",
               135, "2026-10-15T23:33:41Z")
    del row["kickoff"]
    with pytest.raises(CompositeRefusal,
                       match="COMPOSITE_GAME_IDENTITY_MISSING"):
        run_composite({"lines": [row]}, now=NOW, auto_context=False)


def test_composite_discloses_per_game_pit_divergence():
    card = run_composite(_two_game_payload(), now=NOW, auto_context=False)
    block = card["composite"]
    assert block["pit_context"] == "PER_GAME_SNAPSHOTS_MAY_DIVERGE"
    assert block["research_only"] is True
    assert block["release_status"].startswith("RESEARCH_ONLY_UNTIL_")
    contexts = [g["context_as_of_utc"] for g in block["games"]]
    assert contexts == ["2026-10-15T23:33:41+00:00",
                        "2026-10-15T23:36:55+00:00"]
    # Top-level as_of is the LATEST operative instant and the card is
    # explicitly marked a composite, never a single-instant snapshot.
    assert card["as_of_utc"] == "2026-10-15T23:36:55+00:00"
    assert card["input_snapshot"]["composite"] is True
