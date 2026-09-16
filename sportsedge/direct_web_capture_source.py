"""Sport-neutral keyless direct-web acquisition transport.

Source class DRAFTKINGS_DIRECT_WEB_V1.

Contract
--------
* ``observed_at_utc`` is SportsEdge's receipt time. The direct web board carries
  no provider quote timestamp, so ``book_last_update`` / ``market_last_update``
  are emitted as ``None`` and MUST NOT be populated with our receipt time.
* Raw response bytes are preserved with their SHA256 and source URI. The hash is
  taken over the exact bytes received, never a re-serialization of the parsed
  payload.
* ``attempts`` records the ordered transport history (attempt number, host,
  result class or HTTP status, receipt time). Attempt metadata is provenance
  only and never creates evidence when no admissible response was received.
* ``adapter_module_sha256`` is the executable identity of this module. Any git
  SHA recorded alongside it is repository provenance, not executable identity.
* A single host is attempted. Adding a fallback host is a source-class change,
  not an implementation detail.

This module grants no promotion or Model_P authority. Sport-specific row
construction lives in the per-sport modules that import this transport.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sportsedge.draftkings_game_market_source import (
    DraftKingsGameMarketError,
    board_url,
    fetch_board,
)

SOURCE_CLASS = "DRAFTKINGS_DIRECT_WEB_V1"
PROVIDER = "DRAFTKINGS_DIRECT_WEB"
SPORTSBOOK = "draftkings"


class DirectCaptureError(RuntimeError):
    """Raised when no admissible direct-web response was obtained."""


def adapter_module_sha256() -> str:
    """SHA256 of the exact bytes of this transport module as executed."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def host_of(uri: str) -> str:
    return uri.split("//", 1)[-1].split("/", 1)[0]


def acquire_board(
    sport_key: str,
    *,
    fetcher: Callable[..., Any] = fetch_board,
    clock: Callable[[], datetime] = now_utc,
) -> dict[str, Any]:
    """Fetch a board once and return a transport record.

    Raises DirectCaptureError with the attempt history attached when the board
    cannot be obtained.
    """
    uri = board_url(sport_key)
    attempts: list[dict[str, Any]] = []
    started = clock()
    try:
        board = fetcher(sport_key)
    except DraftKingsGameMarketError as exc:
        attempts.append({
            "attempt": 1,
            "host": host_of(uri),
            "result_class": str(exc),
            "received_at_utc": iso_z(clock()),
        })
        err = DirectCaptureError("DIRECT_BOARD_UNAVAILABLE")
        err.attempts = attempts  # type: ignore[attr-defined]
        raise err from exc

    received = board.received_at
    attempts.append({
        "attempt": 1,
        "host": host_of(board.source_uri),
        "result_class": "OK",
        "received_at_utc": iso_z(received),
    })
    return {
        "source_class": SOURCE_CLASS,
        "provider": PROVIDER,
        "sportsbook": SPORTSBOOK,
        "sport_key": board.sport_key,
        "source_uri": board.source_uri,
        "transport_host": host_of(board.source_uri),
        "requested_at_utc": iso_z(started),
        "observed_at_utc": iso_z(received),
        "raw_sha256": hashlib.sha256(board.raw).hexdigest(),
        "raw_payload": board.payload,
        "attempts": attempts,
        "adapter_module_sha256": adapter_module_sha256(),
        "book_last_update": None,
        "provider_quote_timestamp_available": False,
    }
