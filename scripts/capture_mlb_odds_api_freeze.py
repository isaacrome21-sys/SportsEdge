#!/usr/bin/env python3
"""Capture a complete MLB The Odds API request set as exact raw response bytes.

Raw bytes are written only beneath ``--private-root`` (intended to be a checkout
of a separate private repository). The public manifest contains hashes, lengths,
and opaque private paths only. No provider response body or API key is written to
the public manifest.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.game_odds_source import GAME_MARKETS  # noqa: E402
from sportsedge.odds_api_frozen import (  # noqa: E402
    MANIFEST_SCHEMA,
    build_public_manifest_entry,
    request_sha256,
)
from sportsedge.odds_api_source import (  # noqa: E402
    DEFAULT_BOOKMAKERS,
    MARKETS,
    SPORT_KEY,
    _event_url,
)

_CAPTURE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _fetch_raw(url: str) -> bytes:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
    except HTTPError as exc:
        raise RuntimeError(f"ODDS_FREEZE_FETCH_HTTP_{int(exc.code)}") from exc
    except URLError as exc:
        raise RuntimeError("ODDS_FREEZE_FETCH_NETWORK") from exc
    if not isinstance(raw, bytes) or not raw:
        raise RuntimeError("ODDS_FREEZE_EMPTY_RESPONSE")
    return raw


def _parse_events(raw: bytes) -> list[dict]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("ODDS_FREEZE_EVENTS_INVALID_JSON") from exc
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise RuntimeError("ODDS_FREEZE_EVENTS_RESPONSE_INVALID")
    ids: set[str] = set()
    out: list[dict] = []
    for row in payload:
        event_id = str(row.get("id") or "").strip()
        if not event_id:
            raise RuntimeError("ODDS_FREEZE_EVENT_ID_MISSING")
        if event_id in ids:
            raise RuntimeError(f"ODDS_FREEZE_EVENT_ID_DUPLICATE:{event_id}")
        ids.add(event_id)
        out.append(row)
    return out


def _manifest_sha256(payload: dict) -> str:
    body = dict(payload)
    body.pop("manifest_sha256", None)
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--private-root", type=Path, required=True)
    ap.add_argument("--capture-id", required=True)
    ap.add_argument("--manifest-out", type=Path, required=True)
    ap.add_argument("--bookmaker", action="append", dest="bookmakers")
    args = ap.parse_args()

    capture_id = str(args.capture_id or "").strip()
    if not _CAPTURE_ID_RE.fullmatch(capture_id):
        raise SystemExit("ODDS_FREEZE_CAPTURE_ID_INVALID")
    if not isinstance(args.api_key, str) or not args.api_key.strip():
        raise SystemExit("ODDS_FREEZE_API_KEY_MISSING")
    bookmakers = tuple(str(x).strip() for x in (args.bookmakers or DEFAULT_BOOKMAKERS) if str(x).strip())
    if not bookmakers:
        raise SystemExit("ODDS_FREEZE_BOOKMAKERS_MISSING")

    private_root = args.private_root.resolve()
    final_rel = Path("captures") / capture_id
    final_dir = private_root / final_rel
    staging_dir = private_root / "captures" / f".{capture_id}.staging"
    if final_dir.exists():
        raise SystemExit("ODDS_FREEZE_CAPTURE_ALREADY_EXISTS")
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=False)

    entries: list[dict] = []

    def capture(url: str) -> bytes:
        raw = _fetch_raw(url)
        req_sha = request_sha256(url)
        staging_path = staging_dir / "responses" / f"{req_sha}.bin"
        staging_path.parent.mkdir(parents=True, exist_ok=True)
        staging_path.write_bytes(raw)
        private_path = (final_rel / "responses" / f"{req_sha}.bin").as_posix()
        entries.append(
            build_public_manifest_entry(
                url_or_request=url,
                raw_response_bytes=raw,
                private_path=private_path,
            )
        )
        return raw

    try:
        events_url = _event_url(f"/sports/{SPORT_KEY}/events", api_key=args.api_key)
        events_raw = capture(events_url)
        events = _parse_events(events_raw)

        requested_books = ",".join(bookmakers)
        game_url = _event_url(
            f"/sports/{SPORT_KEY}/odds",
            api_key=args.api_key,
            params={
                "regions": "us",
                "bookmakers": requested_books,
                "markets": ",".join(GAME_MARKETS),
                "oddsFormat": "american",
                "dateFormat": "iso",
                "includeSids": "true",
            },
        )
        capture(game_url)

        requested_markets = ",".join(MARKETS)
        for event in events:
            event_id = str(event["id"]).strip()
            prop_url = _event_url(
                f"/sports/{SPORT_KEY}/events/{event_id}/odds",
                api_key=args.api_key,
                params={
                    "bookmakers": requested_books,
                    "markets": requested_markets,
                    "oddsFormat": "american",
                    "dateFormat": "iso",
                    "includeSids": "true",
                },
            )
            capture(prop_url)

        request_ids = [row["request_sha256"] for row in entries]
        if len(request_ids) != len(set(request_ids)):
            raise RuntimeError("ODDS_FREEZE_DUPLICATE_REQUEST_IDENTITY")
        staging_dir.rename(final_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "provider": "THE_ODDS_API",
        "sport": "mlb",
        "capture_id": capture_id,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "bookmakers": list(bookmakers),
        "response_count": len(entries),
        "responses": sorted(entries, key=lambda row: row["request_sha256"]),
    }
    manifest["manifest_sha256"] = _manifest_sha256(manifest)
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "capture_id": capture_id,
        "manifest_sha256": manifest["manifest_sha256"],
        "response_count": manifest["response_count"],
        "raw_bytes_location": "PRIVATE_REPOSITORY_ONLY",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
