"""Tests for sportsedge/nba_period_lines_intake.py — the §4.2 DK
capture-grammar extension for NBA period totals (prereg draft PR
#2843). Bodies are verbatim-style lane captures: header, Captured line,
full-game lines, then the period sections. Every refusal is named;
NOT_OFFERED sections are census data, never silently dropped.
"""
import pytest

from sportsedge import nba_period_lines_intake as intake


def _period_lines(home="Celtics", away="Nets", skip=(), not_offered=()):
    """All 18 period sections for one game (6 game + 12 team)."""
    out = []
    for w in ("Q1", "Q2", "Q3", "Q4", "1H", "2H"):
        label = f"{w} Total"
        if ("GAME", w) not in skip:
            out.append(f"{label} NOT_OFFERED" if ("GAME", w) in not_offered
                       else f"{label} 55.5 -110 -110")
        for team in (away, home):
            tlabel = f"{team} {w} TT"
            if (team, w) in skip:
                continue
            out.append(f"{tlabel} NOT_OFFERED" if (team, w) in not_offered
                       else f"{tlabel} 27.5 -110 -110")
    return out


def _body(**kw):
    lines = ["Nets @ Celtics",
             "Captured: 2026-10-27T18:31:00-04:00",
             "ML +110 -130",
             "Spread +2.5 -110 -110",
             "Total 224.5 -110 -110"]
    lines += _period_lines(**kw)
    return "\n".join(lines) + "\n"


def test_full_capture_parses_all_sections_and_census():
    caps = intake.parse_period_capture(_body())
    assert len(caps) == 1
    cap = caps[0]
    assert (cap.away, cap.home) == ("BKN", "BOS")
    assert cap.captured_at == "2026-10-27T18:31:00-04:00"
    assert len(cap.quotes) == 18
    assert all(q.status == "PRICED" for q in cap.quotes)
    assert cap.census() == {s: "PRICED" for s in intake.SUBFAMILIES}
    q1 = next(q for q in cap.quotes if q.market == "Q1_TOTAL")
    assert (q1.subfamily, q1.window, q1.team) == ("GAME_QUARTER_TOTAL", "Q1", None)
    assert (q1.line, q1.over_price, q1.under_price) == (55.5, -110, -110)
    tt = next(q for q in cap.quotes
              if q.market == "FIRST_HALF_TEAM_TOTAL" and q.team == "BOS")
    assert tt.subfamily == "TEAM_HALF_TOTAL" and tt.window == "1H"


def test_not_offered_sections_are_recorded_not_dropped():
    body = _body(not_offered={("GAME", "Q3"), ("Celtics", "Q3"), ("Nets", "Q3")})
    cap = intake.parse_period_capture(body)[0]
    assert len(cap.quotes) == 18
    no = [q for q in cap.quotes if q.status == "NOT_OFFERED"]
    assert len(no) == 3 and all(q.line is None and q.over_price is None for q in no)
    assert cap.census()["GAME_QUARTER_TOTAL"] == "MIXED"
    assert cap.census()["TEAM_QUARTER_TOTAL"] == "MIXED"
    assert cap.census()["GAME_HALF_TOTAL"] == "PRICED"


def test_all_not_offered_subfamily_still_completes_census():
    skip_nothing = {("GAME", w) for w in ("Q1", "Q2", "Q3", "Q4")}
    body = _body(not_offered=skip_nothing)
    cap = intake.parse_period_capture(body)[0]
    assert cap.census()["GAME_QUARTER_TOTAL"] == "NOT_OFFERED"


def test_missing_section_refuses_capture_incomplete_by_name():
    body = _body(skip={("GAME", "Q2")})
    with pytest.raises(intake.NBAPeriodLinesIntakeError) as e:
        intake.parse_period_capture(body)
    assert "NBA_PERIOD_CAPTURE_INCOMPLETE" in str(e.value)
    assert "GAME_QUARTER_TOTAL" in str(e.value) and "Q2" in str(e.value)


def test_missing_team_section_refuses_incomplete():
    body = _body(skip={("Nets", "2H")})
    with pytest.raises(intake.NBAPeriodLinesIntakeError) as e:
        intake.parse_period_capture(body)
    assert "NBA_PERIOD_CAPTURE_INCOMPLETE" in str(e.value)
    assert "TEAM_HALF_TOTAL" in str(e.value)


def test_priced_and_not_offered_conflict_refuses():
    body = _body() + "Q1 Total NOT_OFFERED\n"
    with pytest.raises(intake.NBAPeriodLinesIntakeError) as e:
        intake.parse_period_capture(body)
    assert "NBA_PERIOD_SECTION_CONFLICT" in str(e.value)


def test_duplicate_not_offered_refuses():
    body = _body(not_offered={("GAME", "Q3")}) + "Q3 Total NOT_OFFERED\n"
    with pytest.raises(intake.NBAPeriodLinesIntakeError) as e:
        intake.parse_period_capture(body)
    assert "NBA_PERIOD_NOT_OFFERED_DUPLICATE" in str(e.value)


def test_unrecognized_not_offered_label_refuses():
    body = _body() + "Q5 Total NOT_OFFERED\n"
    with pytest.raises(intake.NBAPeriodLinesIntakeError) as e:
        intake.parse_period_capture(body)
    assert "NBA_PERIOD_NOT_OFFERED_UNRECOGNIZED" in str(e.value)


def test_not_offered_for_team_not_in_game_refuses():
    body = _body() + "Lakers Q1 TT NOT_OFFERED\n"
    with pytest.raises(intake.NBAPeriodLinesIntakeError) as e:
        intake.parse_period_capture(body)
    assert "NBA_PERIOD_NOT_OFFERED_TEAM_NOT_IN_GAME" in str(e.value)


@pytest.mark.parametrize("bad_line", [
    "Q1 Total 55.5 -110",              # one-sided: never invent a side
    "Q1 Total 55.5 -110 -110 -110",    # extra price
    "Q1 Total 1e2 -110 -110",          # scientific notation is not a line
    "Q1 Total 5_5.5 -110 -110",        # underscore separator
    "Q1 Total 55.5 -110 -99",          # price inside (-100, 100) band
    "Q1 TT 27.5 -110 -110",            # team total without its team
    "Celtics Q1 TT abc -110 -110",     # non-numeric line
])
def test_malformed_period_lines_refuse_by_name(bad_line):
    body = _body().replace("Q1 Total 55.5 -110 -110", bad_line, 1) \
                  .replace("Celtics Q1 TT 27.5 -110 -110",
                           "Celtics Q1 TT 27.5 -110 -110", 1)
    if bad_line.startswith("Celtics"):
        body = _body().replace("Celtics Q1 TT 27.5 -110 -110", bad_line, 1)
    with pytest.raises(intake.NBAPeriodLinesIntakeError) as e:
        intake.parse_period_capture(body)
    assert "NBA_INTAKE_" in str(e.value) or "NBA_PERIOD_" in str(e.value)


def test_duplicate_priced_section_refuses():
    body = _body() + "Q2 Total 54.5 -110 -110\n"
    with pytest.raises(intake.NBAPeriodLinesIntakeError) as e:
        intake.parse_period_capture(body)
    assert "DUPLICATE" in str(e.value)


def test_round_trip_render_parse_reproduces_quotes():
    body = _body(not_offered={("GAME", "Q3"), ("Celtics", "1H")})
    cap = intake.parse_period_capture(body)[0]
    rendered = intake.render_period_capture(cap)
    cap2 = intake.parse_period_capture(rendered)[0]
    strip = lambda qs: [{k: v for k, v in q.to_dict().items() if k != "raw"}
                          for q in qs]
    assert strip(cap2.quotes) == strip(cap.quotes)
    assert cap2.census() == cap.census()


def test_two_game_body_keeps_census_per_game():
    g2 = ["Lakers @ Knicks",
          "Captured: 2026-10-27T18:32:00-04:00",
          "ML -150 +130", "Spread -3.5 -110 -110", "Total 219.5 -110 -110"]
    g2 += _period_lines(home="Knicks", away="Lakers",
                        not_offered={("GAME", "2H")})
    caps = intake.parse_period_capture(_body() + "\n".join(g2) + "\n")
    assert len(caps) == 2
    assert caps[1].home == "NYK" and caps[1].away == "LAL"
    assert caps[1].census()["GAME_HALF_TOTAL"] == "MIXED"
    assert caps[0].census()["GAME_HALF_TOTAL"] == "PRICED"
