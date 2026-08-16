#!/usr/bin/env python3
"""Secret-safe, zero-cost Odds API quota diagnostics."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://api.the-odds-api.com/v4/sports/"


def _keys():
    values=[]
    for name in ("SPORTSEDGE_ODDS_API_KEY","SPORTSEDGE_ODDS_API_KEY_2","SPORTSEDGE_ODDS_API_KEY_3","SPORTSEDGE_ODDS_API_KEY_4"):
        value=os.environ.get(name,"").strip()
        if value and value not in values:
            values.append(value)
    return values


def _provider_code(raw: bytes) -> str | None:
    try:
        payload=json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return None
    if not isinstance(payload,dict):
        return None
    for key in ("error_code","code"):
        value=payload.get(key)
        if isinstance(value,(str,int,float)) and str(value).strip():
            return str(value).strip()[:80]
    return None


def _h(headers, name):
    try:
        value=headers.get(name)
    except Exception:
        return None
    try:
        return int(value) if value not in (None,"") else None
    except (TypeError,ValueError):
        return None


def main() -> int:
    rows=[]
    for slot,key in enumerate(_keys(),start=1):
        url=BASE+"?"+urlencode({"apiKey":key})
        try:
            with urlopen(Request(url,headers={"Accept":"application/json"}),timeout=15) as response:
                raw=response.read()
                rows.append({
                    "key_slot":slot,
                    "status":int(getattr(response,"status",200)),
                    "provider_code":_provider_code(raw),
                    "transport":"HTTP",
                    "requests_remaining":_h(response.headers,"x-requests-remaining"),
                    "requests_used":_h(response.headers,"x-requests-used"),
                    "requests_last":_h(response.headers,"x-requests-last"),
                })
        except HTTPError as exc:
            try: raw=exc.read()
            except Exception: raw=b""
            rows.append({
                "key_slot":slot,"status":int(exc.code),"provider_code":_provider_code(raw),
                "transport":"HTTP_ERROR","requests_remaining":_h(exc.headers,"x-requests-remaining"),
                "requests_used":_h(exc.headers,"x-requests-used"),"requests_last":_h(exc.headers,"x-requests-last"),
            })
        except URLError as exc:
            reason=type(getattr(exc,"reason",None)).__name__ or "URLError"
            rows.append({"key_slot":slot,"status":None,"provider_code":None,"transport":f"URL_ERROR:{reason}","requests_remaining":None,"requests_used":None,"requests_last":None})
        except Exception as exc:
            rows.append({"key_slot":slot,"status":None,"provider_code":None,"transport":f"ERROR:{type(exc).__name__}","requests_remaining":None,"requests_used":None,"requests_last":None})
    payload={"configured_key_count":len(rows),"results":rows,"probe_cost":0}
    out=Path("artifacts/odds_http_diagnostics.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps(payload,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
