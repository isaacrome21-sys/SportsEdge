import pytest

from sportsedge.manual_line_paste import ManualLinePasteError, parse_manual_line_paste


PASTE = """
NFL 2026-09-21 DK retrieved_at=2026-09-21T10:40:00-05:00
KC @ NYJ
  ML   KC -185 / NYJ +155
  spread KC -3.5 -110 / NYJ +3.5 -110
  total  43.5  over -108 / under -112
"""


def test_parses_paired_dk_sides_totals():
    bundle = parse_manual_line_paste(PASTE)
    assert bundle["sport"] == "NFL"
    assert bundle["book"] == "draftkings"
    assert bundle["odds_api"] is False
    assert bundle["source"] == "MANUAL"
    assert len(bundle["quotes"]) == 6
    markets = {q["market"] for q in bundle["quotes"]}
    assert markets == {"moneyline", "spread", "total"}
    assert bundle["authority_footer"].startswith("NOT Model_P")


def test_refuses_missing_retrieved_at_and_one_sided_header():
    with pytest.raises(ManualLinePasteError, match="RETRIEVED_AT_REQUIRED"):
        parse_manual_line_paste("NFL 2026-09-21 DK\nKC @ NYJ\nML KC -185 / NYJ +155")
    with pytest.raises(ManualLinePasteError, match="PASTE_LINE_UNRECOGNIZED"):
        parse_manual_line_paste(
            "NFL 2026-09-21 DK retrieved_at=2026-09-21T10:40:00-05:00\n"
            "KC @ NYJ\nML KC -185"
        )


def test_refuses_naive_timestamp():
    with pytest.raises(ManualLinePasteError, match="RETRIEVED_AT_TIMEZONE_REQUIRED"):
        parse_manual_line_paste(
            "NFL 2026-09-21 DK retrieved_at=2026-09-21T10:40:00\n"
            "KC @ NYJ\nML KC -185 / NYJ +155"
        )
