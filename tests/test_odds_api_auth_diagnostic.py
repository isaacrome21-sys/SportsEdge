import io
import json
import unittest
import urllib.error
from email.message import Message

from scripts.diagnose_odds_api_auth import diagnose


class _Response:
    def __init__(self, payload, *, status=200, headers=None):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _http_error(code, provider_code, headers=None):
    body = json.dumps({"message": "redacted by test", "error_code": provider_code}).encode("utf-8")
    return urllib.error.HTTPError(
        "https://example.invalid/redacted",
        code,
        "provider error",
        headers or Message(),
        io.BytesIO(body),
    )


class OddsApiAuthDiagnosticTests(unittest.TestCase):
    def test_stops_on_first_authenticated_slot_and_never_emits_key(self):
        calls = []

        def opener(url, timeout=30):
            calls.append(url)
            if len(calls) == 1:
                raise _http_error(401, "OUT_OF_USAGE_CREDITS")
            return _Response(
                [],
                headers={
                    "x-requests-remaining": "499",
                    "x-requests-used": "1",
                    "x-requests-last": "0",
                },
            )

        report = diagnose([("KEY_SLOT_1", "SECRET_ONE"), ("KEY_SLOT_2", "SECRET_TWO")], opener)
        rendered = json.dumps(report, sort_keys=True)
        self.assertEqual(report["state"], "AUTHENTICATED")
        self.assertEqual(report["authenticated_key_slot"], "KEY_SLOT_2")
        self.assertEqual(report["attempts"][0]["provider_error_code"], "OUT_OF_USAGE_CREDITS")
        self.assertEqual(report["attempts"][1]["quota_headers"]["x-requests-remaining"], "499")
        self.assertNotIn("SECRET_ONE", rendered)
        self.assertNotIn("SECRET_TWO", rendered)
        self.assertFalse(report["authority"]["model_p_input"])
        self.assertFalse(report["authority"]["promotion_authority"])

    def test_invalid_and_deactivated_keys_are_classified_without_messages(self):
        errors = iter([
            _http_error(401, "INVALID_KEY"),
            _http_error(401, "DEACTIVATED_KEY"),
        ])

        def opener(url, timeout=30):
            raise next(errors)

        report = diagnose([("A", "first"), ("B", "second")], opener)
        self.assertEqual(report["state"], "BLOCKED")
        self.assertEqual(
            [x["provider_error_code"] for x in report["attempts"]],
            ["INVALID_KEY", "DEACTIVATED_KEY"],
        )
        rendered = json.dumps(report, sort_keys=True)
        self.assertNotIn("redacted by test", rendered)
        self.assertNotIn("first", rendered)
        self.assertNotIn("second", rendered)

    def test_unknown_provider_body_is_not_echoed(self):
        def opener(url, timeout=30):
            body = io.BytesIO(b'{"error_code":"SOMETHING_NEW","secret":"do-not-log"}')
            raise urllib.error.HTTPError(
                "https://example.invalid/redacted", 401, "provider error", Message(), body
            )

        report = diagnose([("A", "key")], opener)
        self.assertEqual(report["attempts"][0]["provider_error_code"], "HTTP_401_UNCLASSIFIED")
        self.assertNotIn("do-not-log", json.dumps(report))

    def test_no_configured_key_fails_closed(self):
        report = diagnose([], lambda *_args, **_kwargs: None)
        self.assertEqual(report["state"], "BLOCKED")
        self.assertEqual(report["reason"], "NO_CONFIGURED_KEY")
        self.assertEqual(report["tested_key_slots"], [])


if __name__ == "__main__":
    unittest.main()
