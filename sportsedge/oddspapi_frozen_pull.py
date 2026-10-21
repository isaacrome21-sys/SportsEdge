"""OddsPapi admission-run frozen pull: evidence acquisition, never admission.

Given a FROZEN target list (sport, provider fixtureId, date), fetch each
/v4/historical-odds payload through an injected fetch callable and freeze
the raw bytes to disk, content-addressed by SHA-256, with a manifest of
{target, retrieved_at, sha256, bytes}. The manifest written by a pull that
fails for any target is NO manifest at all: a partial freeze is refused,
never silently narrowed.

This module never sees a credential. The live fetch factory mirrors the
registered custom.oddspapi connector pattern (see
custom-connectors/custom.oddspapi/bin/oddspapi_get.py): the connection
surrogate rides in the `apiKey` query parameter and the connector layer
swaps in the real key on the approved request. Tests inject recorded
fixtures; nothing in this module's test path touches the network.

Outputs are EVIDENCE PACKETS ONLY: every artifact carries
admission=NOT_ADMITTED / verdict=NO_VERDICT. A frozen payload proves only
that these bytes were retrieved at the recorded time; it authenticates
nothing about the provider, the cohort, or any market.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

VERSION = "ODDSPAPI_FROZEN_PULL_V1"
ENDPOINT_PATH = "/v4/historical-odds"
BOOKMAKER = "draftkings"
_TARGET_KEYS = {"sport", "event_id", "date"}
_ID = re.compile(r"^[A-Za-z0-9:_-]{1,128}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")

# fetch(path, params) -> (http_status, raw_body_bytes); injected by caller.
FetchFn = Callable[[str, Mapping[str, str]], tuple[int, bytes]]


class FrozenPullRefusal(ValueError):
    """Stable refusal code; never include payload text or credentials."""


def _stamp(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise FrozenPullRefusal(name + "_UTC_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FrozenPullRefusal(name + "_UTC_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FrozenPullRefusal(name + "_UTC_OFFSET_REQUIRED")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_target(target: Any) -> dict:
    if not isinstance(target, Mapping) or set(target) != _TARGET_KEYS:
        raise FrozenPullRefusal("PULL_TARGET_SCHEMA_INVALID")
    sport = target.get("sport")
    if not isinstance(sport, str) or not _ID.fullmatch(sport):
        raise FrozenPullRefusal("PULL_TARGET_SPORT_INVALID")
    event_id = target.get("event_id")
    if not isinstance(event_id, str) or not _ID.fullmatch(event_id):
        raise FrozenPullRefusal("PULL_TARGET_EVENT_ID_INVALID")
    date = target.get("date")
    if not isinstance(date, str) or not _DATE.fullmatch(date):
        raise FrozenPullRefusal("PULL_TARGET_DATE_INVALID")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise FrozenPullRefusal("PULL_TARGET_DATE_INVALID") from exc
    return {"sport": sport, "event_id": event_id, "date": date}


def request_params_for(target: Mapping[str, Any]) -> dict:
    """Provider request for one frozen target (mirrors the #2436 pattern:
    /v4/historical-odds?fixtureId=<id>&bookmakers=draftkings). The sport and
    date are freeze-list metadata, recorded in the manifest, not sent."""
    return {"fixtureId": target["event_id"], "bookmakers": BOOKMAKER}


def connector_fetch() -> FetchFn:
    """Live fetch factory mirroring the registered connector pattern.

    Lazy by design: importing this module never imports the connector
    machinery, and tests never call this factory. The credential itself
    never appears here; dynamic_credentials places the connection
    surrogate in the apiKey query parameter and the real key is swapped
    in only on the approved request to api.oddspapi.io. Redirects are
    refused. One request per call: the provider's documented 5000 ms
    cooldown is the orchestrator's responsibility, as with #2436.
    """
    import sys
    import urllib.error
    import urllib.parse
    import urllib.request

    sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
    from dynamic_credentials import (  # noqa: PLC0415
        read_response_body,
        url_with_surrogate_query_param,
    )

    base = "https://api.oddspapi.io"
    hosts = ["api.oddspapi.io"]
    credential = "custom.oddspapi"

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):  # noqa: ANN002, ANN202
            raise RuntimeError("redirect refused, verify the endpoint")

    def _fetch(path: str, params: Mapping[str, str]) -> tuple[int, bytes]:
        url = base + path
        if params:
            url = url + "?" + urllib.parse.urlencode(dict(params))
        url = url_with_surrogate_query_param(url, credential, allowed_hosts=hosts)
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.build_opener(_NoRedirect()).open(
                    request, timeout=30) as response:
                return response.status, read_response_body(response)
        except urllib.error.HTTPError as exc:
            return exc.code, read_response_body(exc)

    return _fetch


def pull_frozen_targets(
    targets: Sequence[Mapping[str, Any]],
    fetch: FetchFn,
    out_dir: str | Path,
    *,
    retrieved_at: str | None = None,
) -> dict:
    """Freeze every target's raw payload plus a manifest. Fail-closed:
    any refusal aborts the pull and NO manifest is written."""
    if not isinstance(targets, Sequence) or isinstance(targets, (str, bytes)) \
            or not targets:
        raise FrozenPullRefusal("PULL_TARGET_LIST_EMPTY_OR_INVALID")
    frozen = [_validate_target(t) for t in targets]
    keys = [(t["sport"], t["event_id"], t["date"]) for t in frozen]
    if len(set(keys)) != len(keys):
        raise FrozenPullRefusal("PULL_DUPLICATE_TARGET")
    stamp = _stamp(
        retrieved_at or datetime.now(timezone.utc).isoformat(), "RETRIEVED_AT")

    out = Path(out_dir)
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for target in frozen:
        status, body = fetch(ENDPOINT_PATH, request_params_for(target))
        if status != 200:
            raise FrozenPullRefusal(f"PULL_HTTP_STATUS_NOT_200:{status}")
        if not isinstance(body, (bytes, bytearray)) or not body:
            raise FrozenPullRefusal("PULL_BODY_INVALID")
        raw = bytes(body)
        digest = sha256(raw).hexdigest()
        raw_path = raw_dir / f"{digest}.json"
        if raw_path.exists():
            if raw_path.read_bytes() != raw:
                raise FrozenPullRefusal("PULL_RAW_CONTENT_COLLISION")
        else:
            raw_path.write_bytes(raw)
        entries.append({
            "target": target,
            "endpoint": ENDPOINT_PATH,
            "bookmaker": BOOKMAKER,
            "retrieved_at": stamp,
            "sha256": digest,
            "bytes": len(raw),
            "raw_file": f"raw/{digest}.json",
        })
    manifest = {
        "version": VERSION,
        "admission": "NOT_ADMITTED",
        "verdict": "NO_VERDICT",
        "evidence_state": "FROZEN_PULL_UNVERIFIED",
        "retrieved_at": stamp,
        "target_count": len(entries),
        "entries": entries,
    }
    # Manifest is written LAST: its presence is the freeze's completeness
    # claim, so it may only exist when every target succeeded.
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def verify_pull_dir(out_dir: str | Path) -> dict:
    """Recompute every manifest entry against the frozen bytes on disk.
    Any mismatch, missing file, or malformed manifest is refused."""
    out = Path(out_dir)
    manifest_path = out / "manifest.json"
    if not manifest_path.is_file():
        raise FrozenPullRefusal("PULL_MANIFEST_MISSING")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise FrozenPullRefusal("PULL_MANIFEST_INVALID") from exc
    if not isinstance(manifest, Mapping) or manifest.get("version") != VERSION:
        raise FrozenPullRefusal("PULL_MANIFEST_INVALID")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise FrozenPullRefusal("PULL_MANIFEST_ENTRIES_INVALID")
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise FrozenPullRefusal("PULL_MANIFEST_ENTRY_INVALID")
        digest = entry.get("sha256")
        if not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise FrozenPullRefusal("PULL_MANIFEST_SHA_INVALID")
        raw_path = out / str(entry.get("raw_file", ""))
        if not raw_path.is_file():
            raise FrozenPullRefusal("PULL_RAW_MISSING")
        raw = raw_path.read_bytes()
        if sha256(raw).hexdigest() != digest:
            raise FrozenPullRefusal("PULL_MANIFEST_SHA_MISMATCH")
        if entry.get("bytes") != len(raw):
            raise FrozenPullRefusal("PULL_MANIFEST_BYTES_MISMATCH")
    return {
        "version": VERSION,
        "admission": "NOT_ADMITTED",
        "verdict": "NO_VERDICT",
        "verified_entries": len(entries),
        "manifest_sha256": sha256(manifest_path.read_bytes()).hexdigest(),
    }
