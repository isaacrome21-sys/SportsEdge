"""Shared plumbing for the current-form analytics fetchers.

Design rules (Isaac's standing data bar, same family as
sportsedge/free_factors.py and sportsedge/mlb_savant_features.py):

  - free, public, keyless sources only; no credentials, no paywall
    bypass, no account surfaces;
  - every fetch is stamped (source URL, retrieval time UTC, sha256 and
    byte count of the raw body) so a card can cite exactly what it used;
  - fail closed: any HTTP error, schema drift, or empty body returns
    {"status": "MISSING", "reason": <CODE>} and NEVER raises into a
    pricing path and NEVER fabricates a value;
  - research-only: nothing in this package changes a model, a price, a
    threshold, a verified status, or PLAY eligibility. Outputs feed the
    card's labeled current-form context block only (see
    research/analytics_current_form_20261027/).
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

USER_AGENT = (
    "SportsEdgeResearch/1.0 (current-form analytics fetcher; "
    "public keyless endpoints only)"
)
DEFAULT_TIMEOUT_SECONDS = 30

# An opener is injectable so tests run fully offline against fixtures.
Opener = Callable[[urllib.request.Request, int], bytes]


def _default_opener(request: urllib.request.Request, timeout: int) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_bytes(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    opener: Opener | None = None,
) -> dict[str, Any]:
    """GET a URL and return a stamped receipt, or fail closed.

    Success: {"status": "OK", "url", "retrieved_at_utc", "sha256",
    "bytes", "body"}. Failure: {"status": "MISSING", "reason": CODE,
    "url"} where CODE is FETCH_HTTP_ERROR / FETCH_NETWORK_ERROR /
    FETCH_EMPTY_BODY.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        body = (opener or _default_opener)(request, timeout)
    except urllib.error.HTTPError:
        return {"status": "MISSING", "reason": "FETCH_HTTP_ERROR", "url": url}
    except Exception:
        return {"status": "MISSING", "reason": "FETCH_NETWORK_ERROR", "url": url}
    if not body:
        return {"status": "MISSING", "reason": "FETCH_EMPTY_BODY", "url": url}
    return {
        "status": "OK",
        "url": url,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "body": body,
    }


def receipt_of(fetch_result: Mapping[str, Any]) -> dict[str, Any]:
    """Strip the raw body, keeping the citable provenance stamp."""
    return {
        key: fetch_result[key]
        for key in ("status", "url", "retrieved_at_utc", "sha256", "bytes")
        if key in fetch_result
    }


def parse_csv_body(body: bytes, *, gzipped: bool = False) -> list[dict[str, str]]:
    """Parse a CSV body (optionally gzipped) into row dicts.

    Raises ValueError on undecodable or headerless content; callers turn
    that into a fail-closed SCHEMA_DRIFT result.
    """
    raw = gzip.decompress(body) if gzipped else body
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("csv missing header row")
    return [row for row in reader]


def parse_json_body(body: bytes) -> Any:
    return json.loads(body.decode("utf-8-sig"))


def require_columns(rows: list[dict[str, str]], columns: list[str]) -> bool:
    """True when the first row carries every required column."""
    if not rows:
        return False
    return all(column in rows[0] for column in columns)


def to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    number = to_float(value)
    return int(number) if number is not None else None
