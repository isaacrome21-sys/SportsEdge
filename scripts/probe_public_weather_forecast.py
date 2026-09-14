#!/usr/bin/env python3
"""One bounded public transport check; never writes game/PIT observations."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from sportsedge.public_weather_forecast import forecast_url, kickoff_hour_forecast

def main():
    started = datetime.now(timezone.utc)
    target = started + timedelta(hours=2)
    url = forecast_url(40.0, -88.0, target)
    request = Request(url, headers={'User-Agent':'SportsEdge-public-weather-probe/1'})
    with urlopen(request, timeout=30) as response:
        raw = response.read()
    received = datetime.now(timezone.utc)
    weather = kickoff_hour_forecast(json.loads(raw), target)
    out = ROOT/'artifacts/public-weather-probe'
    out.mkdir(parents=True, exist_ok=True)
    (out/'response.json').write_bytes(raw)
    report = {'status':'PASS','scope':'TRANSPORT_AND_SCHEMA_ONLY',
              'source_uri':url,'requested_at':started.isoformat(),'received_at':received.isoformat(),
              'raw_sha256':sha256(raw).hexdigest(),'weather':weather,
              'game_evidence_created':False,'promotion_authority':False}
    (out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,sort_keys=True))

if __name__=='__main__':main()
