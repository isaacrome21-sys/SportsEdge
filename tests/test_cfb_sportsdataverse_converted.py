import pytest
from sportsedge.sports.cfb.sportsdataverse_acquisition import acquisition_plan
from sportsedge.sports.cfb.sportsdataverse_receipts import receipt
from sportsedge.sports.cfb.sportsdataverse_converted import bind_converted_rows,verify_converted_rows,SDVConvertedError

def test_converted_rows_are_bound_to_raw_rds_sha_and_content():
 a=acquisition_plan()[0]; raw=receipt(a,b"raw-rds")
 rows=[{"season":a.season,"game_id":1,"x":1.25}]
 cr=bind_converted_rows(raw,rows)
 verify_converted_rows(cr,rows,raw)
 assert cr.raw_rds_sha256==raw.sha256 and len(cr.converted_rows_sha256)==64

def test_converted_content_substitution_fails_closed():
 a=acquisition_plan()[0]; raw=receipt(a,b"raw-rds")
 rows=[{"season":a.season,"game_id":1,"x":1.25}]
 cr=bind_converted_rows(raw,rows)
 with pytest.raises(SDVConvertedError,match="HASH_MISMATCH"):
  verify_converted_rows(cr,[{"season":a.season,"game_id":1,"x":9.0}],raw)

def test_wrong_parent_raw_asset_fails_closed():
 plan=acquisition_plan(); raw=receipt(plan[0],b"a"); other=receipt(plan[0],b"b")
 rows=[{"season":raw.season,"game_id":1}]
 cr=bind_converted_rows(raw,rows)
 with pytest.raises(SDVConvertedError,match="PARENT_RECEIPT_MISMATCH"):
  verify_converted_rows(cr,rows,other)
