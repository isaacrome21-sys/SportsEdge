#!/usr/bin/env python3
"""Discover DraftKings Game Lines category IDs for NBA/NHL without granting authority.

This is a read-only diagnostic. Candidate league IDs and the league metadata URL
pattern are adopted as endpoint facts from the public `sjhouston23/oddswrap`
repository at commit 370291c8bfcc0f2032a40cda366d76604f3a29dc. SportsEdge does not treat those
facts, or a successful probe, as production configuration. A separate reviewed
freeze is required before any discovered category ID can feed scheduled capture.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

UTC = timezone.utc
ROOT = "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusnj/v1"
UPSTREAM_REFERENCE = {
    "repository": "sjhouston23/oddswrap",
    "commit": "370291c8bfcc0f2032a40cda366d76604f3a29dc",
    "path": "oddswrap/books/draftkings.py",
    "usage": "LEAGUE_IDS_AND_LEAGUE_METADATA_URL_PATTERN_ONLY",
}
SPORTS = {
    "nba": {"league_id": 42648, "league_name": "NBA"},
    "nhl": {"league_id": 42133, "league_name": "NHL"},
}


class DKCategoryProbeError(RuntimeError):
    pass


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _authority() -> dict[str, bool]:
    return {
        "model_input": False,
        "truth_gate_input": False,
        "promotion": False,
        "eligibility": False,
        "staking": False,
        "official": False,
        "production_config": False,
        "evidence_clock": False,
        "wager_placement": False,
    }


def league_url(league_id: int) -> str:
    return f"{ROOT}/leagues/{league_id}"


def category_url(league_id: int, category_id: str) -> str:
    return f"{ROOT}/leagues/{league_id}/categories/{category_id}"


def _request(url: str) -> Request:
    return Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 SportsEdge-DK-Category-Probe/1",
            "Referer": "https://sportsbook.draftkings.com/",
            "Origin": "https://sportsbook.draftkings.com",
        },
    )


def _fetch_json(
    url: str,
    *,
    opener: Callable[..., Any] = urlopen,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[bytes, Mapping[str, Any], dict[str, Any]]:
    try:
        with opener(_request(url), timeout=20) as response:
            raw = response.read()
            status = int(getattr(response, "status", 200) or 200)
            headers = getattr(response, "headers", None)
            server_date = headers.get("Date") if headers is not None else None
            content_type = headers.get("content-type") if headers is not None else None
    except HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        raise DKCategoryProbeError(
            f"DK_CATEGORY_HTTP_ERROR:status={exc.code}:body_sha256={_sha(body)}:body_bytes={len(body)}"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise DKCategoryProbeError(f"DK_CATEGORY_FETCH_FAILED:{type(exc).__name__}") from exc
    if not raw:
        raise DKCategoryProbeError("DK_CATEGORY_EMPTY_RESPONSE")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise DKCategoryProbeError("DK_CATEGORY_RESPONSE_NOT_JSON") from exc
    if not isinstance(payload, Mapping):
        raise DKCategoryProbeError("DK_CATEGORY_TOP_LEVEL_NOT_OBJECT")
    received = clock().astimezone(UTC)
    return raw, payload, {
        "http_status": status,
        "content_type": content_type,
        "server_date_header": server_date,
        "observed_at_utc": received.isoformat().replace("+00:00", "Z"),
        "timestamp_semantics": "SPORTSEDGE_HTTP_RESPONSE_RECEIPT_UPPER_BOUND",
    }


def _category_id(value: Any) -> str:
    if isinstance(value, bool):
        raise DKCategoryProbeError("DK_GAME_LINES_CATEGORY_ID_INVALID")
    if isinstance(value, int):
        return str(value)
    text = str(value or "").strip()
    if not text or not text.isdigit():
        raise DKCategoryProbeError("DK_GAME_LINES_CATEGORY_ID_INVALID")
    return text


def discover_game_lines(payload: Mapping[str, Any]) -> dict[str, Any]:
    categories = payload.get("categories")
    if not isinstance(categories, list):
        raise DKCategoryProbeError("DK_LEAGUE_CATEGORIES_LIST_MISSING")
    matches: list[dict[str, Any]] = []
    observed: list[dict[str, Any]] = []
    for item in categories:
        if not isinstance(item, Mapping):
            raise DKCategoryProbeError("DK_LEAGUE_CATEGORY_ROW_INVALID")
        name = str(item.get("name") or "").strip()
        cid = item.get("id")
        if name:
            observed.append({"id": cid, "name": name})
        if " ".join(name.casefold().split()) == "game lines":
            matches.append(dict(item))
    if not matches:
        raise DKCategoryProbeError("DK_GAME_LINES_CATEGORY_NOT_FOUND")
    if len(matches) != 1:
        raise DKCategoryProbeError("DK_GAME_LINES_CATEGORY_AMBIGUOUS")
    match = matches[0]
    return {
        "category_id": _category_id(match.get("id")),
        "category_name": str(match.get("name") or "").strip(),
        "observed_categories": observed,
    }


def validate_game_lines_board(payload: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in ("events", "markets", "selections"):
        value = payload.get(key)
        if not isinstance(value, list):
            raise DKCategoryProbeError(f"DK_GAME_LINES_BOARD_{key.upper()}_LIST_MISSING")
        counts[key] = len(value)
    return counts


def _persist_raw(out_dir: Path, sport: str, label: str, raw: bytes) -> dict[str, Any]:
    digest = _sha(raw)
    target = out_dir / "raw" / sport / f"{label}-{digest}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and _sha(target.read_bytes()) != digest:
        raise DKCategoryProbeError("DK_CATEGORY_RAW_HASH_COLLISION")
    if not target.exists():
        target.write_bytes(raw)
    return {
        "raw_sha256": digest,
        "raw_bytes": len(raw),
        "raw_relative_path": str(target.relative_to(out_dir)),
    }


def probe_sport(
    sport: str,
    *,
    out_dir: Path,
    opener: Callable[..., Any] = urlopen,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    key = str(sport or "").strip().lower()
    if key not in SPORTS:
        raise DKCategoryProbeError("DK_CATEGORY_SPORT_UNSUPPORTED")
    cfg = SPORTS[key]
    league_id = int(cfg["league_id"])
    report: dict[str, Any] = {
        "contract": "SPORTSEDGE_DK_GAME_LINES_CATEGORY_PROBE_V1",
        "state": "BLOCKED",
        "sport": key,
        "league_name": cfg["league_name"],
        "candidate_league_id": league_id,
        "candidate_semantics": "UNFROZEN_DISCOVERY_INPUT_ONLY",
        "upstream_reference": UPSTREAM_REFERENCE,
        "authority": _authority(),
    }
    try:
        lurl = league_url(league_id)
        raw, league_payload, league_transport = _fetch_json(lurl, opener=opener, clock=clock)
        report["league_metadata"] = {
            "source_uri": lurl,
            **league_transport,
            **_persist_raw(out_dir, key, "league", raw),
        }
        discovered = discover_game_lines(league_payload)
        curl = category_url(league_id, discovered["category_id"])
        craw, category_payload, category_transport = _fetch_json(curl, opener=opener, clock=clock)
        counts = validate_game_lines_board(category_payload)
        report["discovery"] = {
            "category_id": discovered["category_id"],
            "category_name": discovered["category_name"],
            "category_id_status": "DISCOVERED_NOT_FROZEN",
            "observed_categories": discovered["observed_categories"],
        }
        report["game_lines_board"] = {
            "source_uri": curl,
            **category_transport,
            **_persist_raw(out_dir, key, "game-lines", craw),
            "shape_counts": counts,
        }
        report["state"] = "VERIFIED_DIAGNOSTIC_ONLY"
    except DKCategoryProbeError as exc:
        report["reason"] = str(exc)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport", required=True, choices=sorted(SPORTS))
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--status-out", required=True)
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = probe_sport(args.sport, out_dir=out_dir)
    target = Path(args.status_out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["state"] == "VERIFIED_DIAGNOSTIC_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
