"""Deterministic parsed-row binding for frozen SportsDataverse CSV assets."""
from __future__ import annotations
from dataclasses import dataclass,asdict
import hashlib,json
from typing import Any,Mapping,Sequence
from .sportsdataverse_receipts import AssetReceipt

class SDVParsedError(ValueError): pass

def canonical_rows_sha256(rows:Sequence[Mapping[str,Any]])->str:
 normalized=[dict(r) for r in rows]
 payload=json.dumps(normalized,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode()
 return hashlib.sha256(payload).hexdigest()

@dataclass(frozen=True)
class ParsedReceipt:
 dataset:str
 season:int
 source_url:str
 raw_csv_sha256:str
 row_count:int
 parsed_rows_sha256:str
 parse_format:str="CSV_TO_CANONICAL_JSON_ROWS_V1"
 def to_dict(self): return asdict(self)

def bind_parsed_rows(raw:AssetReceipt,rows:Sequence[Mapping[str,Any]])->ParsedReceipt:
 if not rows: raise SDVParsedError("CFB_SDV_PARSED_ROWS_EMPTY")
 for row in rows:
  if row.get("season") is not None and int(row["season"])!=raw.season:
   raise SDVParsedError("CFB_SDV_PARSED_SEASON_MISMATCH")
 return ParsedReceipt(raw.dataset,raw.season,raw.url,raw.sha256,len(rows),canonical_rows_sha256(rows))

def verify_parsed_rows(receipt:ParsedReceipt,rows:Sequence[Mapping[str,Any]],raw:AssetReceipt)->None:
 if (receipt.dataset,receipt.season,receipt.source_url,receipt.raw_csv_sha256)!=(raw.dataset,raw.season,raw.url,raw.sha256):
  raise SDVParsedError("CFB_SDV_PARSED_PARENT_RECEIPT_MISMATCH")
 if receipt.row_count!=len(rows): raise SDVParsedError("CFB_SDV_PARSED_ROW_COUNT_MISMATCH")
 if receipt.parsed_rows_sha256!=canonical_rows_sha256(rows):
  raise SDVParsedError("CFB_SDV_PARSED_HASH_MISMATCH")
