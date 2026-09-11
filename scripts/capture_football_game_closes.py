#!/usr/bin/env python3
"""Append-only CFB/NFL game-line close capture for Promotion Evidence V2.

The script never creates candidates or Model_P. It consumes already-qualified
candidate game identities, captures one named-book bulk odds snapshot only when a
candidate is near kickoff, and later creates one immutable final-close record from
the last valid prestart observation. Missing observations become CLOSE_MISSED.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config/football_game_close_policy_v1.json"
DEFAULT_CANDIDATES = ROOT / "runtime/promotion_candidates/football_game_candidates.json"
DEFAULT_LEDGER = ROOT / "ledger/promotion_football_game_closes"
BASE_URL = "https://api.the-odds-api.com/v4"


class CloseCaptureError(ValueError):
    pass


def _utc(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CloseCaptureError("CLOSE_CAPTURE_TIMESTAMP_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CloseCaptureError("CLOSE_CAPTURE_TIMESTAMP_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _load(path: Path, error: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CloseCaptureError(error) from exc


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return sha256(raw).hexdigest()


def _candidate_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = _load(path, "FOOTBALL_CLOSE_CANDIDATE_FILE_INVALID")
    rows = payload.get("candidates") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise CloseCaptureError("FOOTBALL_CLOSE_CANDIDATES_INVALID")
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise CloseCaptureError("FOOTBALL_CLOSE_CANDIDATE_ROW_INVALID")
        if row.get("qualifies_for_evidence") is not True:
            continue
        required = ("evidence_id", "sport", "game_id", "provider_home_team", "provider_away_team", "game_start_ts")
        missing = [name for name in required if not str(row.get(name) or "").strip()]
        if missing:
            raise CloseCaptureError("FOOTBALL_CLOSE_CANDIDATE_FIELDS_MISSING:" + ",".join(missing))
        sport = str(row["sport"]).upper()
        if sport not in {"CFB", "NFL"}:
            raise CloseCaptureError(f"FOOTBALL_CLOSE_SPORT_UNSUPPORTED:{sport}")
        out.append(dict(row, sport=sport))
    return out


def _safe_id(value: str) -> str:
    text = str(value).strip()
    if not text or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for ch in text):
        raise CloseCaptureError("FOOTBALL_CLOSE_ID_INVALID")
    return text


def _dirs(root: Path, row: dict[str, Any]) -> tuple[Path, Path]:
    sport = _safe_id(row["sport"].lower())
    game = _safe_id(row["game_id"])
    base = root / sport / game
    return base / "observations", base / "final.json"


def _close_api_key() -> str:
    """Return only the dedicated close-capture key.

    The general SportsEdge odds key is intentionally not a fallback because close
    collection has its own credit budget and must never silently consume the EV
    tracker reserve.
    """
    return str(os.environ.get("SPORTSEDGE_FOOTBALL_CLOSE_ODDS_API_KEY") or "").strip()


def _fetch_bulk(*, key: str, sport_key: str, bookmaker: str, markets: list[str]) -> list[dict[str, Any]]:
    params = {
        "apiKey": key,
        "bookmakers": bookmaker,
        "markets": ",".join(markets),
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    url = f"{BASE_URL}/sports/{sport_key}/odds?{urlencode(params)}"
    with urlopen(Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-Football-Close/1"}), timeout=20) as response:
        body = response.read()
    try:
        value = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise CloseCaptureError("FOOTBALL_CLOSE_PROVIDER_JSON_INVALID") from exc
    if not isinstance(value, list):
        raise CloseCaptureError("FOOTBALL_CLOSE_PROVIDER_RESPONSE_INVALID")
    return value


def _match_event(events: list[dict[str, Any]], row: dict[str, Any]) -> dict[str, Any]:
    home = str(row["provider_home_team"]).strip()
    away = str(row["provider_away_team"]).strip()
    start = _utc(row["game_start_ts"])
    matches = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if str(event.get("home_team") or "").strip() != home or str(event.get("away_team") or "").strip() != away:
            continue
        try:
            event_start = _utc(event.get("commence_time"))
        except CloseCaptureError:
            continue
        if abs((event_start - start).total_seconds()) <= 60:
            matches.append(event)
    if len(matches) != 1:
        raise CloseCaptureError(f"FOOTBALL_CLOSE_EVENT_MATCH_COUNT:{row['game_id']}:{len(matches)}")
    return matches[0]


def _write_create_only(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise CloseCaptureError(f"FOOTBALL_CLOSE_CREATE_ONLY_VIOLATION:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _observations(obs_dir: Path) -> list[dict[str, Any]]:
    rows = []
    if not obs_dir.is_dir():
        return rows
    for path in sorted(obs_dir.glob("*.json")):
        value = _load(path, "FOOTBALL_CLOSE_OBSERVATION_INVALID")
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _finalize(*, row: dict[str, Any], policy: dict[str, Any], ledger: Path, now: datetime) -> bool:
    obs_dir, final_path = _dirs(ledger, row)
    if final_path.exists():
        return False
    start = _utc(row["game_start_ts"])
    if now < start:
        return False
    window = int(policy["capture"]["max_minutes_before_start"])
    valid = []
    for obs in _observations(obs_dir):
        seen = _utc(obs.get("observed_at"))
        delta = (start - seen).total_seconds() / 60.0
        if 0 <= delta <= window:
            valid.append((seen, obs))
    if not valid:
        final = {
            "schema_version": "FOOTBALL_GAME_FINAL_CLOSE_V1",
            "status": "CLOSE_MISSED",
            "policy_id": policy["policy_id"],
            "evidence_id": row["evidence_id"],
            "sport": row["sport"],
            "game_id": row["game_id"],
            "game_start_ts": start.isoformat(),
            "promotion_authority": False,
        }
    else:
        _, selected = max(valid, key=lambda item: item[0])
        final = {
            "schema_version": "FOOTBALL_GAME_FINAL_CLOSE_V1",
            "status": "CAPTURED",
            "policy_id": policy["policy_id"],
            "evidence_id": row["evidence_id"],
            "sport": row["sport"],
            "game_id": row["game_id"],
            "game_start_ts": start.isoformat(),
            "selected_observed_at": selected["observed_at"],
            "bookmaker": selected["bookmaker"],
            "markets": selected["markets"],
            "observation_sha256": selected["observation_sha256"],
            "selection_rule": policy["capture"]["selection_rule"],
            "devig_method": policy["pricing"]["devig_method"],
            "promotion_authority": False,
        }
    _write_create_only(final_path, final)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--asof")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    policy = _load(args.policy, "FOOTBALL_CLOSE_POLICY_INVALID")
    if not isinstance(policy, dict) or policy.get("policy_id") != "FOOTBALL_GAME_CLOSE_POLICY_V1":
        raise CloseCaptureError("FOOTBALL_CLOSE_POLICY_INVALID")
    now = _utc(args.asof)
    candidates = _candidate_rows(args.candidates)

    finalized = 0
    for row in candidates:
        finalized += int(_finalize(row=row, policy=policy, ledger=args.ledger, now=now))

    due_by_sport: dict[str, list[dict[str, Any]]] = {"CFB": [], "NFL": []}
    window = int(policy["capture"]["max_minutes_before_start"])
    for row in candidates:
        obs_dir, final_path = _dirs(args.ledger, row)
        if final_path.exists():
            continue
        start = _utc(row["game_start_ts"])
        minutes = (start - now).total_seconds() / 60.0
        if 0 <= minutes <= window:
            due_by_sport[row["sport"]].append(row)

    captured = 0
    api_key = _close_api_key()
    for sport, rows in due_by_sport.items():
        if not rows:
            continue
        if args.dry_run:
            continue
        if not api_key:
            raise CloseCaptureError("FOOTBALL_CLOSE_ODDS_API_KEY_REQUIRED")
        spec = policy["sports"][sport]
        events = _fetch_bulk(
            key=api_key,
            sport_key=spec["provider_sport_key"],
            bookmaker=spec["bookmaker"],
            markets=list(spec["markets"]),
        )
        for row in rows:
            event = _match_event(events, row)
            books = event.get("bookmakers")
            if not isinstance(books, list) or len(books) != 1:
                raise CloseCaptureError(f"FOOTBALL_CLOSE_BOOK_COUNT_INVALID:{row['game_id']}")
            book = books[0]
            if str(book.get("key") or "").lower() != str(spec["bookmaker"]).lower():
                raise CloseCaptureError(f"FOOTBALL_CLOSE_BOOK_MISMATCH:{row['game_id']}")
            markets = book.get("markets")
            if not isinstance(markets, list):
                raise CloseCaptureError(f"FOOTBALL_CLOSE_MARKETS_INVALID:{row['game_id']}")
            observed_at = now.isoformat()
            payload = {
                "schema_version": "FOOTBALL_GAME_CLOSE_OBSERVATION_V1",
                "policy_id": policy["policy_id"],
                "evidence_id": row["evidence_id"],
                "sport": sport,
                "game_id": row["game_id"],
                "game_start_ts": _utc(row["game_start_ts"]).isoformat(),
                "observed_at": observed_at,
                "bookmaker": spec["bookmaker"],
                "provider_event_id": event.get("id"),
                "markets": markets,
                "promotion_authority": False,
            }
            payload["observation_sha256"] = _canonical_sha(payload)
            obs_dir, _ = _dirs(args.ledger, row)
            stamp = now.strftime("%Y%m%dT%H%M%SZ")
            _write_create_only(obs_dir / f"{stamp}.json", payload)
            captured += 1

    print(json.dumps({"status": "OK", "candidates": len(candidates), "captured": captured, "finalized": finalized}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())