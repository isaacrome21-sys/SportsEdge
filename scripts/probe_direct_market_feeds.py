#!/usr/bin/env python3
"""One-shot probe for anonymous Pinnacle and FanDuel market-data surfaces.

Endpoint facts are adopted from the MIT-licensed `DanielTomaro13/sportsdata-mcp`
provider catalogue (verified upstream in 2026), but this implementation is original
SportsEdge code. The probe is read-only and zero-authority: it exists only to prove
that the direct public quote transports are reachable and to freeze the response
shape before a normalizer is written.

No account authentication, wager placement, Model_P, Truth Gate, promotion, staking,
OFFICIAL, registry, or evidence-clock authority exists here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UTC = timezone.utc
PINNACLE_ROOT = "https://guest.api.arcadia.pinnacle.com/0.1"
PINNACLE_PUBLIC_WEB_KEY = "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"
FANDUEL_ROOT = "https://api.sportsbook.fanduel.com"
FANDUEL_PUBLIC_WEB_KEY = "FhMFpcPWXMeyZxOx"


class DirectMarketProbeError(RuntimeError):
    pass


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _authority() -> dict[str, bool]:
    return {
        "model_p_input": False,
        "truth_gate_input": False,
        "promotion_authority": False,
        "eligibility_authority": False,
        "staking_authority": False,
        "official_authority": False,
        "production_registry_authority": False,
        "evidence_clock_authority": False,
        "wager_placement_authority": False,
    }


def _request(url: str, *, provider: str) -> Request:
    common = {
        "User-Agent": "Mozilla/5.0 SportsEdge-Direct-Market-Probe/1",
        "Accept": "application/json, text/plain, */*",
    }
    if provider == "pinnacle":
        common.update(
            {
                "Origin": "https://www.pinnacle.com",
                "Referer": "https://www.pinnacle.com/",
                "X-API-Key": PINNACLE_PUBLIC_WEB_KEY,
            }
        )
    elif provider == "fanduel":
        common.update(
            {
                "Origin": "https://sportsbook.fanduel.com",
                "Referer": "https://sportsbook.fanduel.com/",
                "x-sportsbook-region": "NJ",
            }
        )
    else:
        raise DirectMarketProbeError("DIRECT_MARKET_PROBE_PROVIDER_UNKNOWN")
    return Request(url, headers=common)


def _fetch(
    url: str,
    *,
    provider: str,
    opener: Callable[..., Any] = urlopen,
) -> tuple[bytes, Any, int, str | None]:
    try:
        with opener(_request(url, provider=provider), timeout=30) as response:
            raw = response.read()
            status = int(getattr(response, "status", 200) or 200)
            ctype = None
            headers = getattr(response, "headers", None)
            if headers is not None:
                ctype = headers.get("content-type")
    except Exception as exc:
        raise DirectMarketProbeError(
            f"DIRECT_MARKET_PROBE_FETCH_FAILED:{provider}:{type(exc).__name__}"
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise DirectMarketProbeError(
            f"DIRECT_MARKET_PROBE_NON_JSON:{provider}"
        ) from exc
    return raw, payload, status, ctype


def _shape(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        first = payload[0] if payload else None
        return {
            "top_level_type": "list",
            "top_level_count": len(payload),
            "first_item_keys": sorted(str(k) for k in first.keys()) if isinstance(first, Mapping) else [],
        }
    if isinstance(payload, Mapping):
        attachments = payload.get("attachments")
        attachment_keys = sorted(str(k) for k in attachments.keys()) if isinstance(attachments, Mapping) else []
        counts: dict[str, int] = {}
        if isinstance(attachments, Mapping):
            for key in ("events", "markets", "runners", "competitions"):
                value = attachments.get(key)
                if isinstance(value, Mapping):
                    counts[key] = len(value)
                elif isinstance(value, list):
                    counts[key] = len(value)
        return {
            "top_level_type": "object",
            "top_level_keys": sorted(str(k) for k in payload.keys()),
            "attachment_keys": attachment_keys,
            "attachment_counts": counts,
        }
    return {"top_level_type": type(payload).__name__}


def _persist_raw(out_dir: Path, provider: str, label: str, raw: bytes) -> dict[str, Any]:
    digest = _sha(raw)
    target = out_dir / "raw" / provider / f"{label}-{digest}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return {
        "raw_sha256": digest,
        "raw_bytes": len(raw),
        "raw_relative_path": str(target.relative_to(out_dir)),
    }


def probe(
    *,
    out_dir: Path,
    opener: Callable[..., Any] = urlopen,
    now: datetime | None = None,
) -> dict[str, Any]:
    captured_at = (now or datetime.now(UTC)).astimezone(UTC)
    out_dir.mkdir(parents=True, exist_ok=True)

    pinnacle_url = f"{PINNACLE_ROOT}/sports"
    fd_query = urlencode(
        {
            "_ak": FANDUEL_PUBLIC_WEB_KEY,
            "page": "CUSTOM",
            "customPageId": "nfl",
            "timezone": "America/New_York",
        }
    )
    fanduel_url = f"{FANDUEL_ROOT}/sbapi/content-managed-page?{fd_query}"

    report: dict[str, Any] = {
        "contract": "DIRECT_MARKET_PUBLIC_FEED_PROBE_V1",
        "state": "BLOCKED",
        "captured_at": captured_at.isoformat().replace("+00:00", "Z"),
        "upstream_reference": {
            "repository": "DanielTomaro13/sportsdata-mcp",
            "license": "MIT",
            "reference_commit": "8f723fc3fe2836ddb92829084b6aeab7c191a750",
            "usage": "ENDPOINT_FACTS_AND_PUBLIC_WEB_CLIENT_KEYS_ONLY_ORIGINAL_IMPLEMENTATION",
        },
        "authority": _authority(),
        "providers": {},
    }

    for provider, label, url in (
        ("pinnacle", "sports", pinnacle_url),
        ("fanduel", "nfl-content-page", fanduel_url),
    ):
        try:
            raw, payload, status, content_type = _fetch(url, provider=provider, opener=opener)
            persisted = _persist_raw(out_dir, provider, label, raw)
            report["providers"][provider] = {
                "state": "REACHABLE",
                "http_status": status,
                "content_type": content_type,
                **persisted,
                "shape": _shape(payload),
            }
        except DirectMarketProbeError as exc:
            report["providers"][provider] = {
                "state": "BLOCKED",
                "reason": str(exc),
            }

    states = [entry.get("state") for entry in report["providers"].values()]
    report["state"] = "REACHABLE" if states and all(x == "REACHABLE" for x in states) else "BLOCKED"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--status-out", required=True)
    args = parser.parse_args(argv)
    report = probe(out_dir=Path(args.out_dir))
    target = Path(args.status_out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["state"] == "REACHABLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
