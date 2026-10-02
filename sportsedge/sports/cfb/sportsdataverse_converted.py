"""Deterministic converted-row binding for frozen SportsDataverse RDS assets."""
from __future__ import annotations
from dataclasses import dataclass,asdict
import hashlib,json
from typing import Any,Mapping,Sequence
from .sportsdataverse_receipts import AssetReceipt

class SDVConvertedError(ValueError): pass

def canonical_rows_sha256(rows:Sequence[Mapping[str,Any]])->str:
 normalized=[dict(r) for r in rows]
 payload=json.dumps(normalized,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode()
 return hashlib.sha256(payload).hexdigest()

@dataclass(frozen=True)
class ConvertedReceipt:
 dataset:str
 season:int
 source_url:str
 raw_rds_sha256:str
 row_count:int
 converted_rows_sha256:str
 conversion_format:str="CANONICAL_JSON_ROWS_V1"
 def to_dict(self): return asdict(self)

def bind_converted_rows(raw:AssetReceipt,rows:Sequence[Mapping[str,Any]])->ConvertedReceipt:
 if not rows: raise SDVConvertedError("CFB_SDV_CONVERTED_ROWS_EMPTY")
 for row in rows:
  if row.get("season") is not None and int(row["season"])!=raw.season:
   raise SDVConvertedError("CFB_SDV_CONVERTED_SEASON_MISMATCH")
 return ConvertedReceipt(raw.dataset,raw.season,raw.url,raw.sha256,len(rows),canonical_rows_sha256(rows))

def verify_converted_rows(receipt:ConvertedReceipt,rows:Sequence[Mapping[str,Any]],raw:AssetReceipt)->None:
 if (receipt.dataset,receipt.season,receipt.source_url,receipt.raw_rds_sha256)!=(raw.dataset,raw.season,raw.url,raw.sha256):
  raise SDVConvertedError("CFB_SDV_CONVERTED_PARENT_RECEIPT_MISMATCH")
 if receipt.row_count!=len(rows): raise SDVConvertedError("CFB_SDV_CONVERTED_ROW_COUNT_MISMATCH")
 if receipt.converted_rows_sha256!=canonical_rows_sha256(rows):
  raise SDVConvertedError("CFB_SDV_CONVERTED_HASH_MISMATCH")
