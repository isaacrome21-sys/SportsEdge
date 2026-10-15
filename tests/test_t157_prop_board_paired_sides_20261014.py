"""t157: paired O/U board intake on main (port of #2283 f955f317a,
without run_it_automation.py). Prices are the Oct 13 SEA@DEN run
record's own (from #2283's fixture); nothing is invented."""
import json
from datetime import datetime, timezone

import pytest

from artifacts import prop_board_intake as B
from artifacts import run_it_full as R

NOW = datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc)
GAME = "GAME: Seattle Seahawks @ Denver Broncos | 2026-10-16T00:15:00Z"
YARDAGE = [
    ("Jaxon Smith-Njigba", "Seattle Seahawks", "RECEIVING_YARDS", 94.5, -112, -112),
    ("Jaylen Waddle", "Denver Broncos", "RECEIVING_YARDS", 49.5, -111, -113),
    ("Emanuel Wilson", "Seattle Seahawks", "RUSHING_YARDS", 66.5, -113, -111),
    ("Bo Nix", "Denver Broncos", "RUSHING_YARDS", 16.5, -111, -113),
]


def _p(pl, tm, mk, ln, o, u, prefix="PROP:"):
    return f"{prefix} {pl} ({tm}) | {mk} | {ln} | O ({o}) | U ({u})"


def _board(*lines):
    return "\n".join((GAME,) + lines)


@pytest.mark.parametrize("prefix", ["PROP:", "PLAYER_PROP:"])
def test_valid_pairs_emit_both_sides_with_board_prices(prefix):
    rows, refusals = B.parse_prop_board(
        _board(*[_p(*y, prefix=prefix) for y in YARDAGE]), sport="NFL", now=NOW,
        book="DK")
    assert refusals == []
    assert len(rows) == 2 * len(YARDAGE)
    for i, (pl, tm, mk, ln, o, u) in enumerate(YARDAGE):
        over, under = rows[2 * i], rows[2 * i + 1]
        assert (over["side"], over["odds"]) == ("OVER", o)
        assert (under["side"], under["odds"]) == ("UNDER", u)
        for r in (over, under):
            assert r["player_name"] == pl and r["market"] == mk and r["line"] == ln
            assert r["away"] == "Seattle Seahawks" and r["home"] == "Denver Broncos"
            assert r["kickoff"] == "2026-10-16T00:15:00+00:00"
            assert r["book"] == "DK" and r["sport"] == "NFL"
            assert set(r) & R_PRICE_KEYS == set()


R_PRICE_KEYS = {"model_p", "probability", "fair_odds", "ev_per_dollar", "edge"}

MALFORMED = [
    ("PROP: Bo Nix (DEN) | RUSHING_YARDS | 16.5 | -111", B.ONE_SIDED),
    ("PROP: Bo Nix (DEN) | RUSHING_YARDS | 16.5 | O (-111)", B.ONE_SIDED),
    ("PROP: Bo Nix (DEN) | RUSHING_YARDS | 16.5 | U (-113)", B.ONE_SIDED),
    ("PLAYER_PROP: Bo Nix (DEN) | RUSHING_YARDS | 16.5 | -111", B.ONE_SIDED),
    ("PROP: Bo Nix (DEN) | RUSHING_YARDS | 16.5 | U (-113) | O (-111)", B.SIDES_MALFORMED),
    ("PROP: Bo Nix (DEN) | RUSHING_YARDS | 16.5 | O (-111) | O (-113)", B.SIDES_MALFORMED),
    ("PROP: Bo Nix (DEN) | RUSHING_YARDS | 16.5 | U (-111) | U (-113)", B.SIDES_MALFORMED),
    ("PROP: Bo Nix (DEN) | RUSHING_YARDS | 16.5 | X (-111) | Y (-113)", B.SIDES_MALFORMED),
    ("PROP: Bo Nix (DEN) | RUSHING_YARDS | 16.5 | Over (-111) | Under (-113)", B.SIDES_MALFORMED),
    ("PROP: Bo Nix (DEN) | RUSHING_YARDS | 16.5 | O (abc) | U (-113)", B.SIDES_MALFORMED),
    ("PROP: Bo Nix (DEN) | RUSHING_YARDS | 16.5 | O (-111) | U ()", B.SIDES_MALFORMED),
    ("PROP: Bo Nix (DEN) | RUSHING_YARDS | 16.5 | O (-1.5) | U (-113)", B.SIDES_MALFORMED),
    ("PROP: Bo Nix (DEN) | RUSHING_YARDS | 16.5 | O (50) | U (-113)", B.SIDES_MALFORMED),
    ("PROP: Bo Nix (DEN) | RUSHING_YARDS | 16.5 | O (-111) | U (-113) | O (-110)", B.SIDES_MALFORMED),
    ("PROP: Bo Nix (DEN) | RUSHING_YARDS | 16.5 | O -111 | U -113", B.SIDES_MALFORMED),
    ("PROP: Bo Nix (DEN) | RUSHING_YARDS | abc | O (-111) | U (-113)", B.MALFORMED),
    ("PROP: Bo Nix | RUSHING_YARDS | 16.5 | O (-111) | U (-113)", B.MALFORMED),
    ("PROPS Bo Nix (DEN) | RUSHING_YARDS | 16.5 | O (-111) | U (-113)", B.UNRECOGNIZED),
]


@pytest.mark.parametrize("line,code", MALFORMED)
def test_malformed_lines_refused_by_name_never_dropped(line, code):
    good = _p(*YARDAGE[0])
    rows, refusals = B.parse_prop_board(_board(good, line, good), sport="NFL", now=NOW)
    assert [r["code"] for r in refusals] == [code]
    assert refusals[0]["line"] == line.strip() and refusals[0]["line_no"] == 3
    assert len(rows) == 4  # the good lines still parse; bad one emits nothing


@pytest.mark.parametrize("line,code", MALFORMED[:-1])
def test_parse_prop_line_raises_never_returns_none(line, code):
    with pytest.raises(B.BoardRefusal) as e:
        B.parse_prop_line(line, {"away": "A", "home": "B"}, "NFL", NOW)
    assert e.value.code == code


def test_prop_without_game_header_unbound():
    rows, refusals = B.parse_prop_board(_p(*YARDAGE[0]), sport="NFL", now=NOW)
    assert rows == [] and [r["code"] for r in refusals] == [B.UNBOUND]


@pytest.mark.parametrize("hdr", [
    "GAME: Seattle Seahawks @ Denver Broncos | 2026-10-16T00:15:00",
    "GAME: Seattle Seahawks @ Denver Broncos | tomorrow",
    "GAME: Seattle Seahawks vs Denver Broncos | 2026-10-16T00:15:00Z"])
def test_bad_game_header_refused(hdr):
    rows, refusals = B.parse_prop_board(hdr + "\n" + _p(*YARDAGE[0]),
                                        sport="NFL", now=NOW)
    assert [r["code"] for r in refusals] == [B.GAME_MALFORMED, B.UNBOUND]
    assert rows == []


def test_sport_required():
    with pytest.raises(ValueError, match="SPORT_REQUIRED"):
        B.parse_prop_board(_board(_p(*YARDAGE[0])), sport="", now=NOW)


def test_cli_fails_closed_on_any_refusal(tmp_path):
    board = tmp_path / "b.txt"
    out = tmp_path / "lines.json"
    board.write_text(_board(_p(*YARDAGE[0]), MALFORMED[4][0]))
    rc = B.main(["--board", str(board), "--sport", "NFL", "--captured-at",
                 "2026-10-14T02:00:00Z", "--output", str(out)])
    assert rc == 2 and not out.exists()
    board.write_text(_board(_p(*YARDAGE[0])))
    assert B.main(["--board", str(board), "--sport", "NFL", "--captured-at",
                   "2026-10-14T02:00:00Z", "--output", str(out)]) == 0
    assert [r["side"] for r in json.loads(out.read_text())["lines"]] == ["OVER", "UNDER"]


def test_paired_rows_never_hit_side_must_be_over_under_in_run_full():
    rows, refusals = B.parse_prop_board(
        _board(*[_p(*y) for y in YARDAGE]), sport="NFL", now=NOW, book="DK")
    assert refusals == []
    card = R.run_full({"lines": rows}, now=NOW, auto_context=False)
    ev = card["evaluated_rows"]
    assert len(ev) == len(rows)
    for r in ev:
        assert "SIDE_MUST_BE_OVER_UNDER" not in json.dumps(r)
