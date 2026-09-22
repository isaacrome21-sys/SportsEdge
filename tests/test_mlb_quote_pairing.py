from sportsedge.mlb_quote_pairing import pair_opposite_odds

def test_pairs_same_book_same_line_same_entity():
    rows=[
      {"game_id":"g","market":"TOTALS","entity_id":"g","line":8.5,"side":"OVER","american_odds":-110,"book_key":"dk"},
      {"game_id":"g","market":"TOTALS","entity_id":"g","line":8.5,"side":"UNDER","american_odds":-105,"book_key":"dk"},
    ]
    out=pair_opposite_odds(rows)
    assert out[0]["opposite_odds"]==-105 and out[1]["opposite_odds"]==-110

def test_does_not_cross_book_or_line():
    rows=[
      {"game_id":"g","market":"TOTALS","entity_id":"g","line":8.5,"side":"OVER","american_odds":-110,"book_key":"dk"},
      {"game_id":"g","market":"TOTALS","entity_id":"g","line":9.5,"side":"UNDER","american_odds":-105,"book_key":"dk"},
      {"game_id":"g","market":"TOTALS","entity_id":"g","line":8.5,"side":"UNDER","american_odds":-115,"book_key":"fd"},
    ]
    assert "opposite_odds" not in pair_opposite_odds(rows)[0]

def test_first_home_run_never_binary_pairs():
    rows=[
      {"game_id":"g","market":"FIRST_HOME_RUN","entity_id":"a","line":None,"side":"YES","american_odds":500,"book_key":"dk"},
      {"game_id":"g","market":"FIRST_HOME_RUN","entity_id":"a","line":None,"side":"NO","american_odds":-700,"book_key":"dk"},
    ]
    assert "opposite_odds" not in pair_opposite_odds(rows)[0]
