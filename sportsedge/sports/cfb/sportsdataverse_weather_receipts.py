"""Deterministic receipts for frozen CFB historical weather inputs."""
from __future__ import annotations
from dataclasses import dataclass,asdict
import hashlib,json
from typing import Any,Iterable,Mapping

class SDVWeatherReceiptError(ValueError): pass

@dataclass(frozen=True)
class WeatherReceipt:
 source_id:str
 byte_count:int
 sha256:str
 row_count:int
 rows_sha256:str
 def to_dict(self): return asdict(self)

def _canon(rows:list[Mapping[str,Any]])->bytes:
 return (json.dumps(rows,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n").encode()

def bind_weather_rows(raw:bytes,rows:Iterable[Mapping[str,Any]],*,source_id:str)->WeatherReceipt:
 if not raw: raise SDVWeatherReceiptError("CFB_SDV_WEATHER_RAW_EMPTY")
 if not source_id.strip(): raise SDVWeatherReceiptError("CFB_SDV_WEATHER_SOURCE_ID_REQUIRED")
 material=[dict(r) for r in rows]
 if not material: raise SDVWeatherReceiptError("CFB_SDV_WEATHER_ROWS_EMPTY")
 seen=set()
 for r in material:
  if "game_id" not in r: raise SDVWeatherReceiptError("CFB_SDV_WEATHER_GAME_ID_REQUIRED")
  gid=int(r["game_id"])
  if gid in seen: raise SDVWeatherReceiptError(f"CFB_SDV_WEATHER_DUPLICATE_GAME:{gid}")
  seen.add(gid)
  if type(r.get("game_indoor")) is not bool:
   raise SDVWeatherReceiptError(f"CFB_SDV_WEATHER_INDOOR_REQUIRED:{gid}")
  if not r["game_indoor"] and (r.get("wind_speed") is None or r.get("temperature") is None):
   raise SDVWeatherReceiptError(f"CFB_SDV_WEATHER_OUTDOOR_FIELDS_REQUIRED:{gid}")
 payload=_canon(sorted(material,key=lambda x:int(x["game_id"])))
 return WeatherReceipt(source_id,len(raw),hashlib.sha256(raw).hexdigest(),len(material),hashlib.sha256(payload).hexdigest())

def verify_weather_rows(receipt:WeatherReceipt,raw:bytes,rows:Iterable[Mapping[str,Any]])->None:
 actual=bind_weather_rows(raw,rows,source_id=receipt.source_id)
 if actual!=receipt: raise SDVWeatherReceiptError("CFB_SDV_WEATHER_RECEIPT_MISMATCH")
