"""Prop pairing + freshness fixes (Oct 14, 2026 operative-run defects).

DEFECT 1 -- native/ladder duplicate-quote collision. DraftKings hangs
BOTH a native two-sided O/U and a milestone ladder for MLB pitcher K
and ER; the ladder rung that converts onto the native line (7+ ==
Over 6.5; "1 or Fewer" == Under 1.5) duplicated the native quote on
the bridge's pairing identity, so the bridge's exactly-one rule
refused the genuine pair with EXACT_PAIRED_DK_QUOTE_REQUIRED. The
milestone intake now suppresses ONLY the exact-identity converted
rung, emitting a named LADDER_RUNG_DUPLICATES_NATIVE_QUOTE
disposition carrying both prices; the bridge's strictness is
untouched (two native quotes still refuse).

DEFECT 2 -- prop freshness judged against the wall clock. run_full
passed only the wall clock to the prop lanes while the game engine
priced against the declared --as-of, so a run declared as-of the
capture instant judged its own fresh quotes stale once wall time
drifted past the 180s bound (tonight: captured 23:03:00Z, --as-of
23:03:00Z, wall 23:07:38Z -> WATCH_QUOTE_NOT_CURRENT). The prop lanes
now judge against the declared as-of (the operative instant);
quote_captured_at is never rewritten, and a quote genuinely old
relative to as-of still judges STALE.

Fixtures reuse the exact-source StatsAPI harness from
test_mlb_prop_wiring_completion_20261014 (offline getters).
"""
from datetime import datetime, timezone

from artifacts.run_it_full import run_full
from sportsedge.milestone_ladder_intake import (
    REFUSAL_DUPLICATES_NATIVE_QUOTE, expand_milestone_ladder_rows)

from test_mlb_prop_wiring_completion_20261014 import (
    CAPTURE, KICKOFF, NOW, pitcher_getter, prow)

AWAY_T, HOME_T = "Milwaukee Brewers", "Los Angeles Dodgers"
KICKOFF_T = "2026-10-14T19:00:00-05:00"
CAPTURE_T = "2026-10-14T23:03:00Z"


# ------------------------------------------- tonight's exact shapes

def tonight_native(market, player, side, line, odds):
    return {"sport": "MLB", "away": AWAY_T, "home": HOME_T,
            "kickoff": KICKOFF_T, "book": "draftkings",
            "quote_captured_at": CAPTURE_T, "market": market,
            "side": side, "odds": odds, "line": line,
            "player_name": player}


def tonight_ladder(market, player, form, rungs):
    return {"sport": "MLB", "away": AWAY_T, "home": HOME_T,
            "kickoff": KICKOFF_T, "book": "draftkings",
            "quote_captured_at": CAPTURE_T, "market": market,
            "player_name": player,
            "milestone_ladder": {
                "form": form,
                "rungs": [{"threshold": t, "odds": o} for t, o in rungs]}}


SNELL_K_LADDER = [(3, -2800), (4, -940), (5, -404), (6, -194), (7, -103),
                  (8, 184), (9, 346), (10, 640), (11, 1160)]


def _quotes(expanded):
    return [r for r in expanded if not r.get("milestone_ladder_refusal")]


def _dispositions(expanded):
    return [r for r in expanded
            if r.get("milestone_ladder_refusal")
            == REFUSAL_DUPLICATES_NATIVE_QUOTE]


# ------------------------------------------------------- DEFECT 1 unit

def test_snell_k_rung_duplicating_native_over_suppressed_with_conflict():
    rows = [
        tonight_native("PITCHER_K", "Blake Snell", "OVER", 6.5, -104),
        tonight_native("PITCHER_K", "Blake Snell", "UNDER", 6.5, -122),
        tonight_ladder("PITCHER_K", "Blake Snell", "X_PLUS", SNELL_K_LADDER),
    ]
    expanded = expand_milestone_ladder_rows(rows)
    quotes = _quotes(expanded)
    over_65 = [r for r in quotes if r.get("side") == "OVER"
               and r.get("line") == 6.5]
    # Exactly one Over 6.5 quote survives: the native row, untouched,
    # with its own price and no milestone provenance.
    assert len(over_65) == 1
    assert over_65[0]["odds"] == -104
    assert "source_quote_form" not in over_65[0]
    # The converted 7+ rung is the single disposition; -103 vs the
    # native -104 is a recorded price conflict, never merged.
    disp = _dispositions(expanded)
    assert len(disp) == 1
    assert disp[0]["line"] == 6.5 and disp[0]["side"] == "OVER"
    assert "odds" not in disp[0] and "price" not in disp[0]
    detail = disp[0]["milestone_duplicate"]
    assert detail["ladder_odds"] == -103
    assert detail["native_odds"] == -104
    assert detail["price_conflict"] is True
    assert detail["native_quote_captured_at"] == CAPTURE_T
    # Every other rung converts normally as a one-sided milestone row.
    converted = [r for r in quotes if r.get("source_quote_form")
                 == "MILESTONE_X_PLUS"]
    assert sorted(r["line"] for r in converted) == [
        2.5, 3.5, 4.5, 5.5, 7.5, 8.5, 9.5, 10.5]


def test_gasser_k_same_price_duplicate_suppressed_without_conflict():
    rows = [
        tonight_native("PITCHER_K", "Robert Gasser", "OVER", 3.5, 110),
        tonight_native("PITCHER_K", "Robert Gasser", "UNDER", 3.5, -140),
        tonight_ladder("PITCHER_K", "Robert Gasser", "X_PLUS",
                       [(2, -690), (3, -218), (4, 110), (5, 253)]),
    ]
    expanded = expand_milestone_ladder_rows(rows)
    disp = _dispositions(expanded)
    assert len(disp) == 1
    detail = disp[0]["milestone_duplicate"]
    assert detail["ladder_odds"] == 110
    assert detail["native_odds"] == 110
    assert detail["price_conflict"] is False
    over_35 = [r for r in _quotes(expanded) if r.get("side") == "OVER"
               and r.get("line") == 3.5]
    assert len(over_35) == 1 and over_35[0]["odds"] == 110


def test_er_or_fewer_rung_duplicating_native_under_suppressed():
    rows = [
        tonight_native("PITCHER_ER", "Blake Snell", "OVER", 1.5, 127),
        tonight_native("PITCHER_ER", "Blake Snell", "UNDER", 1.5, -170),
        tonight_ladder("PITCHER_ER", "Blake Snell", "OR_FEWER",
                       [(1, -173), (2, -461), (3, -1380)]),
    ]
    expanded = expand_milestone_ladder_rows(rows)
    disp = _dispositions(expanded)
    assert len(disp) == 1
    assert disp[0]["side"] == "UNDER" and disp[0]["line"] == 1.5
    detail = disp[0]["milestone_duplicate"]
    assert detail["ladder_odds"] == -173
    assert detail["native_odds"] == -170
    assert detail["price_conflict"] is True
    converted = [r for r in _quotes(expanded)
                 if r.get("source_quote_form") == "MILESTONE_OR_FEWER"]
    assert sorted(r["line"] for r in converted) == [2.5, 3.5]


def test_duplicate_requires_full_pairing_identity():
    ladder = tonight_ladder("PITCHER_K", "Blake Snell", "X_PLUS",
                            [(7, -103)])
    # Different player on the native row: no suppression.
    rows = [tonight_native("PITCHER_K", "Robert Gasser", "OVER", 6.5, -104),
            ladder]
    assert not _dispositions(expand_milestone_ladder_rows(rows))
    # Different game (different kickoff) on the native row: none either.
    other_game = tonight_native("PITCHER_K", "Blake Snell", "OVER", 6.5, -104)
    other_game["kickoff"] = "2026-10-15T19:00:00-05:00"
    assert not _dispositions(
        expand_milestone_ladder_rows([other_game, ladder]))
    # Different line: none.
    rows = [tonight_native("PITCHER_K", "Blake Snell", "OVER", 7.5, -104),
            ladder]
    assert not _dispositions(expand_milestone_ladder_rows(rows))
    # Opposite side only: the converted OVER rung has no native twin.
    rows = [tonight_native("PITCHER_K", "Blake Snell", "UNDER", 6.5, -122),
            ladder]
    assert not _dispositions(expand_milestone_ladder_rows(rows))


def test_malformed_native_row_never_suppresses_a_rung():
    bad = tonight_native("PITCHER_K", "Blake Snell", "OVER", 6.5, -50)
    ladder = tonight_ladder("PITCHER_K", "Blake Snell", "X_PLUS",
                            [(7, -103)])
    expanded = expand_milestone_ladder_rows([bad, ladder])
    assert not _dispositions(expanded)
    converted = [r for r in _quotes(expanded)
                 if r.get("source_quote_form") == "MILESTONE_X_PLUS"]
    assert len(converted) == 1 and converted[0]["line"] == 6.5


def test_ladder_without_native_twin_converts_unchanged():
    ladder = tonight_ladder("PITCHER_K", "Blake Snell", "X_PLUS",
                            SNELL_K_LADDER)
    expanded = expand_milestone_ladder_rows([ladder])
    assert not _dispositions(expanded)
    assert len(_quotes(expanded)) == len(SNELL_K_LADDER)


# ------------------------------------------------- DEFECT 1 end-to-end

def test_native_k_pair_prices_with_ladder_present_end_to_end():
    lines = [
        prow("PITCHER_K", "OVER", 6.5, odds=-110),
        prow("PITCHER_K", "UNDER", 6.5, odds=-114),
        {"sport": "MLB", "away": "Los Angeles Dodgers",
         "home": "Milwaukee Brewers", "kickoff": KICKOFF,
         "book": "draftkings", "quote_captured_at": CAPTURE,
         "market": "PITCHER_K", "player_name": "Jacob Misiorowski",
         "milestone_ladder": {"form": "X_PLUS", "rungs": [
             {"threshold": 5, "odds": -400}, {"threshold": 6, "odds": -200},
             {"threshold": 7, "odds": -110}, {"threshold": 8, "odds": 150}]}},
    ]
    card = run_full({"sport": "MLB", "lines": lines},
                    now=NOW, getter=pitcher_getter)
    priced = [r for r in card["evaluated_rows"]
              if r.get("market") == "PITCHER_K" and r.get("line") == 6.5
              and r.get("status") != "NO_MODEL_OR_MARKET"]
    assert len(priced) == 2  # the native pair priced through the bridge
    for row in priced:
        assert row["quote_status"] == "RECENT_CAPTURED_QUOTE"
        assert 0 < row["model_probability"] < 1
    unpriced = {(r.get("line"), r.get("reason"))
                for r in card["prop_unpriced"] if r.get("market") == "PITCHER_K"}
    # The duplicated rung is visible as its named disposition...
    assert (6.5, REFUSAL_DUPLICATES_NATIVE_QUOTE) in unpriced
    # ...and the non-duplicated rungs keep their one-sided fate.
    assert (4.5, "EXACT_PAIRED_DK_QUOTE_REQUIRED") in unpriced
    assert (5.5, "EXACT_PAIRED_DK_QUOTE_REQUIRED") in unpriced
    assert (7.5, "EXACT_PAIRED_DK_QUOTE_REQUIRED") in unpriced
    disp = [r for r in card["prop_unpriced"]
            if r.get("reason") == REFUSAL_DUPLICATES_NATIVE_QUOTE]
    assert len(disp) == 1
    assert disp[0]["milestone_duplicate"]["ladder_odds"] == -110
    assert disp[0]["milestone_duplicate"]["native_odds"] == -110
    assert disp[0]["milestone_duplicate"]["price_conflict"] is False


def test_two_native_quotes_still_refuse_exact_paired():
    # The bridge's exactly-one strictness is NOT relaxed by this fix:
    # two genuine native quotes on one side still refuse by name.
    lines = [prow("PITCHER_OUTS", "OVER", 16.5),
             prow("PITCHER_OUTS", "OVER", 16.5),
             prow("PITCHER_OUTS", "UNDER", 16.5, odds=-114)]
    card = run_full({"sport": "MLB", "lines": lines},
                    now=NOW, getter=pitcher_getter)
    rows = [r for r in card["evaluated_rows"] if r.get("market") == "PITCHER_OUTS"]
    assert len(rows) == 3
    for row in rows:
        assert row["status"] == "NO_MODEL_OR_MARKET"
        assert row["reason"] == "EXACT_PAIRED_DK_QUOTE_REQUIRED"


# ------------------------------------------------------------ DEFECT 2

def _outs_pair():
    return [prow("PITCHER_OUTS", "OVER", 16.5),
            prow("PITCHER_OUTS", "UNDER", 16.5, odds=-114)]


def test_prop_freshness_judged_at_declared_as_of_not_wall_clock():
    # The operative CLI form: --as-of at the capture instant, no
    # explicit now. Real wall time is days later; the pair must still
    # judge RECENT at the operative instant and price.
    card = run_full({"sport": "MLB", "lines": _outs_pair()},
                    as_of=CAPTURE, getter=pitcher_getter)
    rows = [r for r in card["evaluated_rows"]
            if r.get("market") == "PITCHER_OUTS"]
    assert len(rows) == 2
    for row in rows:
        assert row["status"] != "WATCH_QUOTE_NOT_CURRENT"
        assert row["quote_status"] == "RECENT_CAPTURED_QUOTE"
    assert {r["status"] for r in rows} <= {
        "RESEARCH_CANDIDATE_NOT_VALIDATED", "WATCH_BELOW_EV_FLOOR",
        "WATCH_PRICE_CAP"}


def test_prop_freshness_stale_when_as_of_is_one_hour_after_capture():
    # Same pair, declared as-of one hour after capture: genuinely old
    # relative to the operative instant -> still STALE, never priced.
    lines = _outs_pair()
    card = run_full({"sport": "MLB", "lines": lines},
                    as_of="2026-10-11T22:12:10Z", getter=pitcher_getter)
    rows = [r for r in card["evaluated_rows"]
            if r.get("market") == "PITCHER_OUTS"]
    assert len(rows) == 2
    for row in rows:
        assert row["status"] == "WATCH_QUOTE_NOT_CURRENT"
        assert row["quote_status"] == "STALE_QUOTE"


def test_capture_timestamps_never_rewritten_by_the_run():
    lines = _outs_pair()
    before = [r["quote_captured_at"] for r in lines]
    card = run_full({"sport": "MLB", "lines": lines},
                    as_of=CAPTURE, getter=pitcher_getter)
    # Intake rows are byte-identical after the run...
    assert [r["quote_captured_at"] for r in lines] == before == [CAPTURE, CAPTURE]
    # ...and the card's paired-capture record names the supplied
    # instant exactly (parsed ISO form), not the wall clock or as-of.
    rows = [r for r in card["evaluated_rows"]
            if r.get("market") == "PITCHER_OUTS"]
    for row in rows:
        assert row["paired_quote_captured_at"] == [
            "2026-10-11T21:12:10+00:00", "2026-10-11T21:12:10+00:00"]


def test_declared_as_of_governs_even_when_now_also_supplied():
    # The declared as-of is the run's single operative instant (the
    # free_models contract: now is wall-clock execution time, as_of is
    # the point-in-time clock pricing must respect). With as_of an
    # hour after capture, the pair judges STALE even though the
    # supplied now sits 50s after capture.
    card = run_full({"sport": "MLB", "lines": _outs_pair()},
                    now=NOW, as_of="2026-10-11T22:12:10Z",
                    getter=pitcher_getter)
    rows = [r for r in card["evaluated_rows"]
            if r.get("market") == "PITCHER_OUTS"]
    assert len(rows) == 2
    for row in rows:
        assert row["quote_status"] == "STALE_QUOTE"
        assert row["status"] == "WATCH_QUOTE_NOT_CURRENT"
