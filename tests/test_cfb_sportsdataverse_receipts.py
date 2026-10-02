from sportsedge.sports.cfb.sportsdataverse_acquisition import acquisition_plan
from sportsedge.sports.cfb.sportsdataverse_receipts import receipt,validate_receipts,SDVReceiptError
import pytest

def test_receipts_cover_exact_frozen_plan_and_hash_raw_bytes():
 plan=acquisition_plan()
 rs=[receipt(a,(a.dataset+str(a.season)).encode()) for a in plan]
 validate_receipts(plan,rs)
 assert len(rs)==44
 assert all(len(r.sha256)==64 and r.byte_count>0 for r in rs)

def test_receipts_fail_closed_on_missing_asset():
 plan=acquisition_plan(); rs=[receipt(a,b"x") for a in plan[:-1]]
 with pytest.raises(SDVReceiptError,match="COVERAGE_MISMATCH"):
  validate_receipts(plan,rs)
