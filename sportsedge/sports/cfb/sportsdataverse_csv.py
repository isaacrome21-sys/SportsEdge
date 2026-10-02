"""Deterministic stdlib CSV parser for frozen SportsDataverse CFB assets."""
from __future__ import annotations
import csv,io,hashlib
from typing import Mapping
from .sportsdataverse_converted import bind_parsed_rows,ParsedReceipt
from .sportsdataverse_receipts import AssetReceipt

class SDVCSVError(ValueError): pass

REQUIRED={
 "cfb_schedules":{"game_id","season","week","season_type","fbs_game","home_id","away_id","home_points","away_points"},
 "espn_cfb_adv_team":{"game_id","season","week","pos_team","EPA_rushing_per_play","EPA_passing_per_play","EPA_explosive_rate"},
 "espn_cfb_adv_situational":{"game_id","season","week","pos_team","EPA_success_rate","EPA_standard_down_per_play","EPA_success_passing_down_rate"},
 "espn_cfb_adv_drives":{"game_id","season","pos_team","avg_field_position"},
}
MARKET_TOKENS=("spread","moneyline","money_line","over_under","betting","odds")

def parse_csv(raw:bytes,*,dataset:str,season:int,source_url:str,raw_csv_sha256:str)->tuple[list[dict[str,str]],ParsedReceipt]:
 if dataset not in REQUIRED: raise SDVCSVError("CFB_SDV_CSV_DATASET_NOT_FROZEN:"+dataset)
 actual_sha256=hashlib.sha256(raw).hexdigest()
 if actual_sha256 != raw_csv_sha256: raise SDVCSVError("CFB_SDV_CSV_RAW_HASH_MISMATCH")
 try: text=raw.decode("utf-8-sig")
 except UnicodeDecodeError as e: raise SDVCSVError("CFB_SDV_CSV_UTF8_REQUIRED") from e
 reader=csv.DictReader(io.StringIO(text,newline=""))
 fields=reader.fieldnames or []
 if not fields: raise SDVCSVError("CFB_SDV_CSV_HEADER_REQUIRED")
 if len(fields)!=len(set(fields)): raise SDVCSVError("CFB_SDV_CSV_DUPLICATE_HEADER")
 missing=sorted(REQUIRED[dataset]-set(fields))
 if missing: raise SDVCSVError("CFB_SDV_CSV_REQUIRED_COLUMNS_MISSING:"+",".join(missing))
 for name in fields:
  low=name.lower()
  if any(tok in low for tok in MARKET_TOKENS): raise SDVCSVError("CFB_SDV_CSV_MARKET_COLUMN_PROHIBITED:"+name)
 rows=[]
 for n,row in enumerate(reader,2):
  if None in row: raise SDVCSVError(f"CFB_SDV_CSV_EXTRA_FIELDS:{n}")
  clean={k:(v.strip() if isinstance(v,str) else v) for k,v in row.items()}
  if not clean.get("game_id"): raise SDVCSVError(f"CFB_SDV_CSV_GAME_ID_REQUIRED:{n}")
  if not clean.get("season"): raise SDVCSVError(f"CFB_SDV_CSV_SEASON_REQUIRED:{n}")
  try: row_season=int(float(clean["season"]))
  except ValueError as e: raise SDVCSVError(f"CFB_SDV_CSV_SEASON_INVALID:{n}") from e
  if row_season!=int(season): raise SDVCSVError(f"CFB_SDV_CSV_SEASON_MISMATCH:{n}")
  rows.append(clean)
 if not rows: raise SDVCSVError("CFB_SDV_CSV_ROWS_REQUIRED")
 parent=AssetReceipt(dataset,int(season),source_url,len(raw),raw_csv_sha256)
 receipt=bind_parsed_rows(parent,rows)
 return rows,receipt
