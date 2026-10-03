import unittest
from urllib.error import HTTPError

from sportsedge.sports.cfb.source import CFBSourceError, _json_get


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


class CFBSourceRetryTests(unittest.TestCase):
    def test_429_retries_same_request_and_honors_retry_after(self):
        calls = []
        delays = []

        def opener(req, timeout=20):
            calls.append((req.full_url, timeout))
            if len(calls) < 3:
                raise HTTPError(
                    req.full_url,
                    429,
                    "Too Many Requests",
                    {"Retry-After": "0"},
                    None,
                )
            return _Response(b'{"ok": true}')

        payload = _json_get(
            "https://example.test/cfb",
            headers={"Authorization": "Bearer secret"},
            opener=opener,
            max_attempts=4,
            sleeper=delays.append,
        )

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(url == "https://example.test/cfb" for url, _ in calls))
        self.assertEqual(delays, [0.0, 0.0])

    def test_nonretryable_http_error_still_fails_closed(self):
        delays = []

        def opener(req, timeout=20):
            raise HTTPError(req.full_url, 401, "Unauthorized", {}, None)

        with self.assertRaisesRegex(CFBSourceError, "SOURCE_FETCH_FAILED:HTTPError"):
            _json_get(
                "https://example.test/cfb",
                headers={},
                opener=opener,
                sleeper=delays.append,
            )
        self.assertEqual(delays, [])

    def test_phone_workflow_prefers_alternate_cfbd_secret(self):
        from pathlib import Path

        workflow = Path(".github/workflows/cfb-lines-issue.yml").read_text(encoding="utf-8")
        self.assertIn(
            "secrets.SPORTSEDGE_CFBD_API_KEY || secrets.CFBD_API_KEY",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
