"""Tests for the 1st-inning runs BOARD-FORM intake binding.

DraftKings serves the 1st-inning market as "Runs - 1st Inning" OVER/UNDER
lines (CATALOG_MLB.md: "Runs O/U (0.5/1.5 alts)"; the inspected-menu
census carries it as INNING_1_RUNS, group inning, period INNING_1)
rather than an NRFI/YRFI label. Before this binding such a row died
unrouted as NO_VERIFIED_MODEL_FOR_THIS_MARKET even though the
first-inning engine (MLB_FIRST_INNING_TEAM_RATES_POISSON_JEFFREYS)
prices the identical market as FIRST_INNING_RUNS.

Covered here:
- the 0.5-line equivalence, explicitly: board OVER 0.5 IS the YRFI
  side and board UNDER 0.5 IS the NRFI side — identical
  model_probability through run_full on identical history/quotes;
- alias spellings (RUNS_1ST_INNING / 1ST_INNING_RUNS) bind the same way;
- a missing line defaults to the 0.5 binary line (DK's main board line);
- the 1.5 alternate reaches the engine and is refused by the engine's
  own name (FIRST_INNING_RUNS_LINE_MUST_BE_0_5);
- malformed rows refuse at intake by name (P0 style) and never price;
- the board label is restored on the result row.

The fake-history harness (_game/_schedule_getter/_fixture_game/
_history_games/_row) is copied from tests/test_mlb_first_inning.py so
the equivalence runs see byte-identical history.
"""
from datetime import datetime, timezone

import pytest

NOW = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)


# ------------------------------------------------------- fake history

def _game(game_pk, date, away_id, home_id, a1r, h1r, a1h, h1h, ah, hh,
          game_type="R", detailed="Final"):
    return {
        "gamePk": game_pk, "gameDate": date, "gameType": game_type,
        "status": {"detailedState": detailed},
        "teams": {
            "away": {"team": {"id": away_id, "name": "Away Team"}},
            "home": {"team": {"id": home_id, "name": "Home Team"}},
        },
        "linescore": {
            "innings": [{"num": 1,
                         "away": {"runs": a1r, "hits": a1h},
                         "home": {"runs": h1r, "hits": h1h}}],
            "teams": {"away": {"hits": ah}, "home": {"hits": hh}},
        },
    }


def _schedule_getter(games_by_date, fixture_game):
    def get(url):
        if "/people/" in url and "gameLog" in url:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(url).query)
            if qs.get("season", [""])[0] != "2026":
                return {"stats": []}
            pid = url.split("/people/")[1].split("/")[0]
            if pid == "1":
                pks, team = [3, 5, 7, 9, 11], 119
            elif pid == "2":
                pks, team = [4, 6, 8, 10, 12], 158
            else:
                return {"stats": []}
            base = datetime(2026, 7, 28, tzinfo=timezone.utc).date()
            splits = []
            for pk in pks:
                day = base + __import__("datetime").timedelta(days=(pk - 1) // 2)
                splits.append({"date": day.isoformat(), "gameType": "R",
                               "game": {"gamePk": pk}, "team": {"id": team},
                               "stat": {"gamesStarted": 1}})
            return {"stats": [{"splits": splits}]}
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(url).query)
        start, end = qs["startDate"][0], qs["endDate"][0]
        dates = []
        day = start
        while day <= end:
            day_games = list(games_by_date.get(day, []))
            if day == "2026-10-11":
                day_games = day_games + [fixture_game]
            if day_games:
                dates.append({"date": day, "games": day_games})
            day = (datetime.strptime(day, "%Y-%m-%d").date()
                   + __import__("datetime").timedelta(days=1)).isoformat()
        return {"dates": dates}
    return get


def _fixture_game():
    return {
        "gamePk": 999, "gameDate": "2026-10-12T00:00:00Z",
        "status": {"detailedState": "Scheduled"},
        "teams": {
            "away": {"team": {"id": 119, "name": "Los Angeles Dodgers"},
                     "probablePitcher": {"id": 1, "fullName": "Away Ace"}},
            "home": {"team": {"id": 158, "name": "Milwaukee Brewers"},
                     "probablePitcher": {"id": 2, "fullName": "Home Ace"}},
        },
    }


def _history_games():
    games_by_date = {}
    pk = 1
    day = datetime(2026, 7, 28, tzinfo=timezone.utc).date()
    end = datetime(2026, 10, 10, tzinfo=timezone.utc).date()
    while day <= end:
        iso = day.isoformat()
        games_by_date[iso] = [
            _game(pk, iso + "T19:00:00Z", 119, 900, 0, 1, 1, 2, 8, 9),
            _game(pk + 1, iso + "T23:00:00Z", 901, 158, 1, 0, 2, 1, 9, 8),
        ]
        pk += 2
        day += __import__("datetime").timedelta(days=1)
    return games_by_date


def _row(**kw):
    base = {"sport": "MLB", "away": "Los Angeles Dodgers",
            "home": "Milwaukee Brewers",
            "kickoff": "2026-10-11T19:00:00-05:00",
            "book": "draftkings",
            "quote_captured_at": "2026-10-11T20:00:00Z",
            "market": "INNING_1_RUNS", "line": 0.5,
            "side": "OVER", "odds": 105}
    base.update(kw)
    return base


def _getter():
    return _schedule_getter(_history_games(), _fixture_game())


def _run(rows, *, with_history):
    from artifacts.run_it_full import run_full
    if with_history:
        return run_full({"lines": rows, "sport": "MLB"}, now=NOW,
                        getter=_getter(), auto_context=True)
    return run_full({"lines": rows, "sport": "MLB"}, now=NOW,
                    auto_context=False)


def _board_pair(**kw):
    return [_row(side="OVER", odds=105, **kw),
            _row(side="UNDER", odds=-140, **kw)]


def _label_pair():
    yrfi = _row(market="YRFI", odds=105)
    yrfi.pop("side")
    nrfi = _row(market="NRFI", odds=-140)
    nrfi.pop("side")
    return [yrfi, nrfi]


# ------------------------------------------------------- equivalence

@pytest.mark.registry_lane_internals
def test_board_over_under_0_5_equal_yrfi_nrfi_probabilities():
    # The equivalence, run as separate cards: the exact-pair quote
    # discipline admits exactly one quote per side, so board rows and
    # label rows for the same fixture are evaluated in separate runs on
    # identical history and identical quotes — the binding is the only
    # difference.
    board = _run(_board_pair(), with_history=True)["evaluated_rows"]
    label = _run(_label_pair(), with_history=True)["evaluated_rows"]
    board_by_sel = {r["selection"]: r for r in board}
    label_by_sel = {r["selection"]: r for r in label}
    assert board_by_sel["OVER"]["model_probability"] == \
        label_by_sel["OVER"]["model_probability"]   # OVER 0.5 == YRFI
    assert board_by_sel["UNDER"]["model_probability"] == \
        label_by_sel["UNDER"]["model_probability"]  # UNDER 0.5 == NRFI
    assert board_by_sel["OVER"]["model_probability"] + \
        board_by_sel["UNDER"]["model_probability"] == pytest.approx(1.0)
    for r in board:
        assert 0.0 < r["model_probability"] < 1.0
        assert r["status"] != "NO_MODEL_OR_MARKET"


@pytest.mark.registry_lane_internals
def test_board_label_restored_and_underlying_market_recorded():
    rows = _run(_board_pair(), with_history=True)["evaluated_rows"]
    for r in rows:
        assert r["market"] == "INNING_1_RUNS"
        assert r["underlying_market"] == "FIRST_INNING_RUNS"
        assert r["priced_via"] == "FIRST_INNING_RUNS_BINARY_AT_0_5"


@pytest.mark.registry_lane_internals
@pytest.mark.parametrize("alias", ["RUNS_1ST_INNING", "1ST_INNING_RUNS"])
def test_board_aliases_price_identically(alias):
    rows = _run(_board_pair(market=alias), with_history=True)["evaluated_rows"]
    canon = _run(_board_pair(), with_history=True)["evaluated_rows"]
    assert [r["model_probability"] for r in rows] == \
        [r["model_probability"] for r in canon]
    assert all(r["market"] == alias for r in rows)


@pytest.mark.registry_lane_internals
def test_missing_line_defaults_to_the_binary_line():
    pair = _board_pair()
    for r in pair:
        r.pop("line")
    rows = _run(pair, with_history=True)["evaluated_rows"]
    canon = _run(_board_pair(), with_history=True)["evaluated_rows"]
    assert [r["model_probability"] for r in rows] == \
        [r["model_probability"] for r in canon]
    assert all(r["line"] == 0.5 for r in rows)


# ------------------------------------------------------- refusals

@pytest.mark.registry_lane_internals
def test_alternate_line_1_5_refused_by_the_engines_own_name():
    rows = _run(_board_pair(line=1.5), with_history=True)["evaluated_rows"]
    for r in rows:
        assert r["status"] == "NO_MODEL_OR_MARKET"
        assert r["reason"] == "FIRST_INNING_RUNS_LINE_MUST_BE_0_5"
        assert r.get("model_probability") is None


@pytest.mark.registry_lane_internals
def test_missing_side_refuses_at_intake_by_name():
    row = _row()
    row.pop("side")
    rows = _run([row], with_history=False)["evaluated_rows"]
    assert rows[0]["status"] == "NO_MODEL_OR_MARKET"
    assert rows[0]["reason"] == "INNING_1_RUNS_SIDE_REQUIRED"
    assert rows[0].get("model_probability") is None


@pytest.mark.registry_lane_internals
@pytest.mark.parametrize("alias", ["RUNS_1ST_INNING", "1ST_INNING_RUNS"])
def test_alias_missing_side_refuses_at_intake_by_name(alias):
    row = _row(market=alias)
    row.pop("side")
    rows = _run([row], with_history=False)["evaluated_rows"]
    assert rows[0]["reason"] == "INNING_1_RUNS_SIDE_REQUIRED"


@pytest.mark.registry_lane_internals
def test_non_over_under_side_refuses_at_intake_by_name():
    rows = _run([_row(side="YES")], with_history=False)["evaluated_rows"]
    assert rows[0]["reason"] == "INNING_1_RUNS_SIDE_INVALID"
    assert rows[0].get("model_probability") is None


@pytest.mark.registry_lane_internals
@pytest.mark.parametrize("bad_line", ["abc", True, {"x": 1}])
def test_non_numeric_line_refuses_at_intake_by_name(bad_line):
    rows = _run([_row(line=bad_line)], with_history=False)["evaluated_rows"]
    assert rows[0]["reason"] == "INNING_1_RUNS_LINE_INVALID"
    assert rows[0].get("model_probability") is None


@pytest.mark.registry_lane_internals
def test_board_market_is_no_longer_unrouted():
    card = _run(_board_pair(), with_history=False)
    coverage = card["summary"]["mlb_market_coverage"]
    assert "INNING_1_RUNS" not in coverage["unrouted_input_markets"]
    for r in card["evaluated_rows"]:
        assert r["reason"] != "NO_VERIFIED_MODEL_FOR_THIS_MARKET"
    assert card["prop_model_status"]["first_inning_board_form"] == \
        "INNING_1_RUNS_BOUND_TO_FIRST_INNING_RUNS_ENGINE"
