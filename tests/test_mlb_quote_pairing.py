from sportsedge.mlb_quote_pairing import MAX_PAIRED_SKEW_SECONDS, pair_opposite_odds

T0="2026-09-22T17:00:00+00:00"
T10="2026-09-22T17:00:10+00:00"
T31="2026-09-22T17:00:31+00:00"

def _row(side,odds,*,line=8.5,book="dk",retrieved_at=T0,market="TOTALS",entity="g",**extra):
    row={"game_id":"g","market":market,"entity_id":entity,"line":line,"side":side,"american_odds":odds,"book_key":book}
    if retrieved_at is not None:
        row["retrieved_at"]=retrieved_at
    row.update(extra)
    return row

def test_pairs_same_book_same_line_same_entity():
    out=pair_opposite_odds([_row("OVER",-110),_row("UNDER",-105,retrieved_at=T10)])
    assert out[0]["opposite_odds"]==-105 and out[1]["opposite_odds"]==-110

def test_does_not_cross_book_or_line():
    rows=[_row("OVER",-110),_row("UNDER",-105,line=9.5),_row("UNDER",-115,book="fd")]
    assert "opposite_odds" not in pair_opposite_odds(rows)[0]

def test_first_home_run_never_binary_pairs():
    rows=[
      _row("YES",500,market="FIRST_HOME_RUN",entity="a",line=None),
      _row("NO",-700,market="FIRST_HOME_RUN",entity="a",line=None),
    ]
    assert "opposite_odds" not in pair_opposite_odds(rows)[0]

def test_skew_limit_is_thirty_seconds():
    assert MAX_PAIRED_SKEW_SECONDS==30.0
    at_limit=pair_opposite_odds([_row("OVER",-110),_row("UNDER",-105,retrieved_at="2026-09-22T17:00:30+00:00")])
    assert at_limit[0]["opposite_odds"]==-105

def test_sides_more_than_thirty_seconds_apart_do_not_pair():
    out=pair_opposite_odds([_row("OVER",-110),_row("UNDER",-105,retrieved_at=T31)])
    assert "opposite_odds" not in out[0] and "opposite_odds" not in out[1]

def test_missing_or_naive_timestamp_never_pairs():
    missing=pair_opposite_odds([_row("OVER",-110,retrieved_at=None),_row("UNDER",-105)])
    assert "opposite_odds" not in missing[0] and "opposite_odds" not in missing[1]
    naive=pair_opposite_odds([_row("OVER",-110,retrieved_at="2026-09-22T17:00:00"),_row("UNDER",-105)])
    assert "opposite_odds" not in naive[0] and "opposite_odds" not in naive[1]

def test_moneyline_pairs_team_names_not_home_away_tokens():
    rows=[
        _row("NYY",-150,market="MONEYLINE",line=None,home="NYY",away="BOS"),
        _row("BOS",130,market="MONEYLINE",line=None,home="NYY",away="BOS",retrieved_at=T10),
    ]
    out=pair_opposite_odds(rows)
    assert out[0]["opposite_odds"]==130 and out[1]["opposite_odds"]==-150

def test_run_line_pairs_opposite_signed_lines_on_team_sides():
    rows=[
        _row("LAD",-115,market="RUN_LINE",line=-1.5,home="LAD",away="SDP"),
        _row("SDP",-105,market="RUN_LINE",line=1.5,home="LAD",away="SDP",retrieved_at=T10),
    ]
    out=pair_opposite_odds(rows)
    assert out[0]["opposite_odds"]==-105 and out[1]["opposite_odds"]==-115
