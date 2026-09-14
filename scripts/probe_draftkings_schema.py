#!/usr/bin/env python3
"""Bounded public response inspection; no market or model admission."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sportsedge.draftkings_prop_source import DK_HOME, _discover, _request


def main():
    out = ROOT / 'artifacts/draftkings-schema-probe'
    out.mkdir(parents=True, exist_ok=True)
    records = []

    def capture(url):
        raw = _request(url)
        received = datetime.now(timezone.utc).isoformat()
        digest = sha256(raw).hexdigest()
        (out / (digest + '.json')).write_bytes(raw)
        data = json.loads(raw)
        records.append({'source_uri': url, 'received_at': received,
                        'raw_sha256': digest, 'payload': data})
        return data

    base, league_id = _discover(_request(DK_HOME).decode('utf-8'))
    league = capture(f'{base}v1/leagues/{league_id}')
    for event in league.get('events', [])[:2]:
        event_id = int(event['id'])
        capture(f'{base}v1/events/{event_id}/categories')
    report = {'scope': 'PROVIDER_SCHEMA_INSPECTION_ONLY',
              'game_evidence_created': False, 'promotion_authority': False,
              'responses': records}
    (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
