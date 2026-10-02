"""Transport-neutral raw asset receipt validation for SportsDataverse CFB history."""
from __future__ import annotations
from dataclasses import dataclass,asdict
import hashlib
from typing import Iterable
from .sportsdataverse_acquisition import Asset,PROHIBITED,SDVAcquisitionError

class SDVReceiptError(ValueError): pass

@dataclass(frozen=True)
class AssetReceipt:
 dataset:str
 season:int
 url:str
 byte_count:int
 sha256:str
 def to_dict(self): return asdict(self)

def receipt(asset:Asset,payload:bytes)->AssetReceipt:
 if asset.dataset in PROHIBITED: raise SDVReceiptError("CFB_SDV_BETTING_DATASET_PROHIBITED")
 if not payload: raise SDVReceiptError("CFB_SDV_ASSET_EMPTY")
 return AssetReceipt(asset.dataset,asset.season,asset.url,len(payload),hashlib.sha256(payload).hexdigest())

def validate_receipts(plan:Iterable[Asset],receipts:Iterable[AssetReceipt])->None:
 expected={(a.dataset,a.season,a.url) for a in plan}
 rs=list(receipts)
 got={(r.dataset,r.season,r.url) for r in rs}
 if len(got)!=len(rs): raise SDVReceiptError("CFB_SDV_RECEIPT_DUPLICATE")
 if got!=expected:
  missing=sorted(expected-got); extra=sorted(got-expected)
  raise SDVReceiptError(f"CFB_SDV_RECEIPT_COVERAGE_MISMATCH:missing={missing[:3]}:extra={extra[:3]}")
