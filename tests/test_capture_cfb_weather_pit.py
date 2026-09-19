import json
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from datetime import datetime, timezone
from pathlib import Path

from scripts.capture_cfb_weather_pit import (
    CFBWeatherCaptureError,
    ESPN_KEYLESS_USER_AGENTS,
    _default_opener,
    _fetch_bytes,
    capture_weather,
    main,
)

UTC = timezone.utc


class _Response:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def read(self):
        return self._raw


class CFBWeatherCaptureTests(unittest.TestCase):
    def test_prestart_weather_is_hash_bound_and_append_only(self):
        now = datetime(2026, 9, 18, 23, 45, tzinfo=UTC)
        event = {
            "id": "401000001",
            "date": "2026-09-19T00:00:00Z",
            "competitions": [{
                "date": "2026-09-19T00:00:00Z",
                "status": {"type": {"state": "pre"}},
                "competitors": [
                    {"homeAway": "home", "team": {"displayName": "Home State"}},
                    {"homeAway": "away", "team": {"displayName": "Away Tech"}},
                ],
            }],
        }
        summary = {
            "header": {"competitions": [{
                "status": {"type": {"state": "pre"}},
                "weather": {"temperature": 72, "displayValue": "Clear"},
            }]}
        }
        def opener(url, timeout=20):
            if "summary?event=401000001" in url:
                return _Response(summary)
            if "dates=20260918" in url:
                return _Response({"events": [event]})
            if "dates=20260919" in url:
                return _Response({"events": []})
            raise AssertionError(url)

        policy = {
            "windows": {
                "t0_prestart": {"min_minutes_before_start": 0, "max_minutes_before_start": 5},
                "close": {"min_minutes_before_start": 2, "max_minutes_before_start": 20},
                "decision": {"min_minutes_before_start": 45, "max_minutes_before_start": 120},
            }
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = capture_weather(now=now, policy=policy, out_dir=root, opener=opener, clock=lambda: now)
            self.assertEqual(report["observations_written"], 1)
            path = root / "history/cfb/weather/2026-09-19.ndjson"
            row = json.loads(path.read_text().strip())
            self.assertEqual(row["status_state"], "pre")
            self.assertTrue(row["prestart_attested"])
            self.assertEqual(row["window"], "close")
            self.assertEqual(row["weather"]["temperature"], 72)
            raw_path = root / row["raw_relative_path"]
            self.assertTrue(raw_path.is_file())
            import hashlib
            self.assertEqual(hashlib.sha256(raw_path.read_bytes()).hexdigest(), row["raw_sha256"])
            self.assertFalse(row["promotion_authority"])

    def test_started_event_is_not_captured(self):
        now = datetime(2026, 9, 18, 23, 45, tzinfo=UTC)
        event = {
            "id": "401000002",
            "date": "2026-09-19T00:00:00Z",
            "competitions": [{
                "status": {"type": {"state": "in"}},
                "competitors": [],
            }],
        }
        def opener(url, timeout=20):
            if "scoreboard" in url:
                return _Response({"events": [event] if "20260918" in url else []})
            raise AssertionError("summary must not be fetched after start")
        policy = {"windows": {
            "close": {"min_minutes_before_start": 2, "max_minutes_before_start": 20},
            "t0_prestart": {"min_minutes_before_start": 0, "max_minutes_before_start": 5},
            "decision": {"min_minutes_before_start": 45, "max_minutes_before_start": 120},
        }}
        with tempfile.TemporaryDirectory() as td:
            report = capture_weather(now=now, policy=policy, out_dir=Path(td), opener=opener)
            self.assertEqual(report["observations_written"], 0)
            self.assertEqual(report["skips"][0]["reason"], "SCOREBOARD_NOT_PRESTART")

    def test_only_transient_http_failures_retry(self):
        opener = Mock(side_effect=[HTTPError('https://example.test',503,'unavailable',{},None),_Response({})])
        pause = Mock()
        self.assertEqual(_fetch_bytes('https://example.test', opener, pause=pause), b'{}')
        self.assertEqual(opener.call_count, 2)
        pause.assert_called_once_with(1.0)
        opener = Mock(side_effect=HTTPError('https://example.test',401,'unauthorized',{},None))
        with self.assertRaisesRegex(CFBWeatherCaptureError, 'CFB_WEATHER_HTTP_401'):
            _fetch_bytes('https://example.test', opener, pause=pause)
        self.assertEqual(opener.call_count, 1)

    def test_default_opener_rotates_keyless_nonbrowser_user_agent_after_403(self):
        blocked = HTTPError('https://site.api.espn.com/test', 403, 'forbidden', {}, None)
        with patch(
            'scripts.capture_cfb_weather_pit.urllib.request.urlopen',
            side_effect=[blocked, _Response({})],
        ) as network:
            response = _default_opener('https://site.api.espn.com/test')
            self.assertEqual(response.read(), b'{}')
        self.assertEqual(network.call_count, 2)
        seen = [call.args[0].get_header('User-agent') for call in network.call_args_list]
        self.assertEqual(seen, list(ESPN_KEYLESS_USER_AGENTS))

    def test_live_cli_cannot_backdate_capture(self):
        with patch('scripts.capture_cfb_weather_pit._default_opener') as network:
            self.assertEqual(main(['--now','2020-01-01T00:00:00Z']), 2)
        network.assert_not_called()

    def _capture_fixture(self, *, received_at, forecast=False):
        now = datetime(2026,9,18,23,45,tzinfo=UTC)
        comp = {'status':{'type':{'state':'pre'}},'competitors':[
            {'homeAway':'home','team':{'displayName':'Home'}},
            {'homeAway':'away','team':{'displayName':'Away'}}]}
        event = {'id':'1','date':'2026-09-19T00:00:00Z','competitions':[comp]}
        summary = {'header':{'competitions':[{'status':{'type':{'state':'pre'}}}]},
                   'gameInfo':{'venue':{'latitude':40.0,'longitude':-88.0}}}
        if not forecast:
            summary['weather']={'temperature':72}
        from tests.test_public_weather_forecast import payload
        def opener(url, timeout=20):
            if 'api.open-meteo.com' in url:
                return _Response(payload())
            if 'summary?' in url:
                return _Response(summary)
            return _Response({'events':[event] if '20260918' in url else []})
        policy = {'windows':{'close':{'min_minutes_before_start':2,'max_minutes_before_start':20},
                             't0_prestart':{'min_minutes_before_start':0,'max_minutes_before_start':5}}}
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            result=capture_weather(now=now, policy=policy, out_dir=root, opener=opener, clock=lambda:received_at)
            files=list((root/'history/cfb/weather').glob('*.ndjson'))
            row=json.loads(files[0].read_text()) if files else None
            if row:
                import hashlib
                self.assertEqual(hashlib.sha256((root/row['raw_relative_path']).read_bytes()).hexdigest(),row['raw_sha256'])
                for support in row['supporting_raw']:
                    self.assertEqual(hashlib.sha256((root/support['raw_relative_path']).read_bytes()).hexdigest(),support['raw_sha256'])
            return result,row

    def test_response_after_kickoff_is_not_pregame(self):
        result,row=self._capture_fixture(received_at=datetime(2026,9,19,0,0,1,tzinfo=UTC))
        self.assertEqual(result['observations_written'],0)
        self.assertEqual(result['skips'][0]['reason'],'RESPONSE_OUTSIDE_PRESTART_WINDOW')
        self.assertIsNone(row)

    def test_open_meteo_fallback_preserves_receipt_and_venue_raw_evidence(self):
        result,row=self._capture_fixture(received_at=datetime(2026,9,18,23,46,0,123456,tzinfo=UTC),forecast=True)
        self.assertEqual(result['observations_written'],1)
        self.assertEqual(row['source'],'OPEN_METEO_FORECAST')
        self.assertEqual(row['weather']['kind'],'FORECAST')
        self.assertEqual(row['captured_at_utc'],'2026-09-18T23:46:00.123456Z')
        self.assertEqual(len(row['supporting_raw']),2)
        self.assertFalse(row['promotion_authority'])


if __name__ == "__main__":
    unittest.main()
