import pytest
from sportsedge.sports.cfb.sportsdataverse_acquisition import acquisition_plan
from sportsedge.sports.cfb.sportsdataverse_receipts import receipt
from sportsedge.sports.cfb.sportsdataverse_converted import bind_parsed_rows,verify_parsed_rows,SDVParsedError

def test_parsed_rows_are_bound_to_raw_rds_sha_and_content():
 a=acquisition_plan()[0]; raw=receipt(a,b"raw-csv")
 rows=[{"season":a.season,"game_id":1,"x":1.25}]
 cr=bind_parsed_rows(raw,rows)
 verify_parsed_rows(cr,rows,raw)
 assert cr.raw_csv_sha256==raw.sha256 and len(cr.parsed_rows_sha256)==64

def test_parsed_content_substitution_fails_closed():
 a=acquisition_plan()[0]; raw=receipt(a,b"raw-csv")
 rows=[{"season":a.season,"game_id":1,"x":1.25}]
 cr=bind_parsed_rows(raw,rows)
 with pytest.raises(SDVParsedError,match="HASH_MISMATCH"):
  verify_parsed_rows(cr,[{"season":a.season,"game_id":1,"x":9.0}],raw)

def test_wrong_parent_raw_asset_fails_closed():
 plan=acquisition_plan(); raw=receipt(plan[0],b"a"); other=receipt(plan[0],b"b")
 rows=[{"season":raw.season,"game_id":1}]
 cr=bind_parsed_rows(raw,rows)
 with pytest.raises(SDVParsedError,match="PARENT_RECEIPT_MISMATCH"):
  verify_parsed_rows(cr,rows,other)
