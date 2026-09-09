#!/usr/bin/env python3
"""Recover the missing 2025 MLB DraftKings window without consuming outcomes.

This acquisition script intentionally emits only pregame identity and sportsbook fields.
It does not serialize scores, game results, or winner labels from the source page.
Raw source HTML may be retained outside the repository as an immutable evidence artifact.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

NEXT_DATA_PATTERN = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
BASE_URL = "https://www.sportsbookreview.com/betting-odds/mlb-baseball"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
CSV_FIELDS = [
    "date",
    "start_date_utc",
    "away_team",
    "away_name",
    "home_team",
    "home_name",
    "dk_open_away_ml",
    "dk_open_home_ml",
    "dk_current_away_ml",
    "dk_current_home_ml",
    "dk_current_away_spread",
    "dk_current_home_spread",
    "close_eligible",
    "moneyline_page_sha256",
    "pointspread_page_sha256",
]


class RecoveryError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def daterange(start: date, end: date) -> list[str]:
    if end < start:
        raise RecoveryError("end date precedes start date")
    out: list[str] = []
    current = start
    while current <= end:
        out.append(current.isoformat())
        current += timedelta(days=1)
    return out


def source_url(day: str, market: str) -> str:
    if market == "moneyline":
        return f"{BASE_URL}/?date={day}"
    if market == "pointspread":
        return f"{BASE_URL}/pointspread/full-game/?date={day}"
    raise RecoveryError(f"unsupported market: {market}")


def fetch_page(url: str, retries: int = 4, timeout: int = 25) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urlopen(req, timeout=timeout) as response:
                body = response.read()
                if response.status != 200:
                    raise RecoveryError(f"HTTP_{response.status}:{url}")
                if not body:
                    raise RecoveryError(f"EMPTY_BODY:{url}")
                return body
        except (HTTPError, URLError, TimeoutError, RecoveryError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1.0 + attempt * 1.5 + random.random())
    raise RecoveryError(f"FETCH_FAILED:{url}:{last_error}")


def extract_next_data(page: bytes) -> dict[str, Any]:
    text = page.decode("utf-8", errors="strict")
    match = NEXT_DATA_PATTERN.search(text)
    if not match:
        raise RecoveryError("NEXT_DATA_NOT_FOUND")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise RecoveryError(f"NEXT_DATA_INVALID_JSON:{exc}") from exc
    if not isinstance(payload, dict):
        raise RecoveryError("NEXT_DATA_ROOT_NOT_OBJECT")
    return payload


def game_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    tables = payload.get("props", {}).get("pageProps", {}).get("oddsTables", [])
    if not isinstance(tables, list) or not tables:
        return []
    for table in tables:
        rows = table.get("oddsTableModel", {}).get("gameRows", []) if isinstance(table, dict) else []
        if isinstance(rows, list) and rows:
            return [row for row in rows if isinstance(row, dict)]
    return []


def _book_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def draftkings_view(game: dict[str, Any]) -> dict[str, Any] | None:
    views = game.get("oddsViews", [])
    if not isinstance(views, list):
        return None
    for view in views:
        if not isinstance(view, dict):
            continue
        if "draftkings" in _book_name(view.get("sportsbook")):
            return view
    return None


def game_identity(game: dict[str, Any]) -> tuple[str, str, str]:
    view = game.get("gameView", {})
    if not isinstance(view, dict):
        raise RecoveryError("GAME_VIEW_INVALID")
    away = view.get("awayTeam", {})
    home = view.get("homeTeam", {})
    if not isinstance(away, dict) or not isinstance(home, dict):
        raise RecoveryError("TEAM_VIEW_INVALID")
    away_team = str(away.get("shortName") or "").strip().upper()
    home_team = str(home.get("shortName") or "").strip().upper()
    start_date = str(view.get("startDate") or "").strip()
    if not away_team or not home_team or not start_date:
        raise RecoveryError("GAME_IDENTITY_INCOMPLETE")
    return start_date, away_team, home_team


def parse_market_page(page: bytes, market: str) -> dict[tuple[str, str, str], dict[str, Any]]:
    payload = extract_next_data(page)
    rows = game_rows(payload)
    if not rows:
        raise RecoveryError(f"NO_GAME_ROWS:{market}")
    parsed: dict[tuple[str, str, str], dict[str, Any]] = {}
    for game in rows:
        key = game_identity(game)
        book = draftkings_view(game)
        if book is None:
            parsed[key] = {"draftkings_missing": True}
            continue
        opening = book.get("openingLine", {})
        current = book.get("currentLine", {})
        if not isinstance(opening, dict):
            opening = {}
        if not isinstance(current, dict):
            current = {}
        parsed[key] = {
            "draftkings_missing": False,
            "opening": opening,
            "current": current,
            "game_view": {
                "away": game.get("gameView", {}).get("awayTeam", {}),
                "home": game.get("gameView", {}).get("homeTeam", {}),
            },
        }
    return parsed


def _number_or_none(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        numeric = float(str(value))
    except ValueError:
        return None
    return int(numeric) if numeric.is_integer() else numeric


def build_rows(
    day: str,
    moneyline_page: bytes,
    pointspread_page: bytes,
) -> tuple[list[dict[str, Any]], list[str]]:
    ml = parse_market_page(moneyline_page, "moneyline")
    ps = parse_market_page(pointspread_page, "pointspread")
    ml_sha = sha256_bytes(moneyline_page)
    ps_sha = sha256_bytes(pointspread_page)
    normalized: list[dict[str, Any]] = []
    blockers: list[str] = []

    for key in sorted(ml):
        start_date, away_team, home_team = key
        ml_row = ml[key]
        ps_row = ps.get(key)
        if ml_row.get("draftkings_missing"):
            blockers.append(f"DK_MONEYLINE_MISSING:{day}:{away_team}@{home_team}")
            continue
        if ps_row is None or ps_row.get("draftkings_missing"):
            blockers.append(f"DK_POINTSPREAD_MISSING:{day}:{away_team}@{home_team}")
            continue

        opening = ml_row["opening"]
        current = ml_row["current"]
        ps_current = ps_row["current"]
        open_away = _number_or_none(opening.get("awayOdds"))
        open_home = _number_or_none(opening.get("homeOdds"))
        current_away = _number_or_none(current.get("awayOdds"))
        current_home = _number_or_none(current.get("homeOdds"))
        away_spread = _number_or_none(ps_current.get("awaySpread"))
        home_spread = _number_or_none(ps_current.get("homeSpread"))

        if open_away in (None, 0) or open_home in (None, 0):
            blockers.append(f"DK_OPEN_MALFORMED:{day}:{away_team}@{home_team}")
            continue

        close_eligible = (
            current_away not in (None, 0)
            and current_home not in (None, 0)
            and isinstance(away_spread, (int, float))
            and isinstance(home_spread, (int, float))
            and abs(float(away_spread)) <= 2.5
            and abs(float(home_spread)) <= 2.5
        )
        game_view = ml_row.get("game_view", {})
        away_view = game_view.get("away", {}) if isinstance(game_view, dict) else {}
        home_view = game_view.get("home", {}) if isinstance(game_view, dict) else {}
        normalized.append(
            {
                "date": day,
                "start_date_utc": start_date,
                "away_team": away_team,
                "away_name": str(away_view.get("fullName") or ""),
                "home_team": home_team,
                "home_name": str(home_view.get("fullName") or ""),
                "dk_open_away_ml": open_away,
                "dk_open_home_ml": open_home,
                "dk_current_away_ml": current_away,
                "dk_current_home_ml": current_home,
                "dk_current_away_spread": away_spread,
                "dk_current_home_spread": home_spread,
                "close_eligible": bool(close_eligible),
                "moneyline_page_sha256": ml_sha,
                "pointspread_page_sha256": ps_sha,
            }
        )
    return normalized, blockers


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def self_test() -> int:
    payload = {
        "props": {
            "pageProps": {
                "oddsTables": [
                    {
                        "oddsTableModel": {
                            "gameRows": [
                                {
                                    "gameView": {
                                        "startDate": "2025-09-28T19:05:00+00:00",
                                        "awayTeam": {"shortName": "COL", "fullName": "Colorado Rockies"},
                                        "homeTeam": {"shortName": "SF", "fullName": "San Francisco Giants"},
                                        "awayTeamScore": 0,
                                        "homeTeamScore": 4,
                                    },
                                    "oddsViews": [
                                        {"sportsbook": "fanduel", "openingLine": {}},
                                        {
                                            "sportsbook": "draftkings",
                                            "openingLine": {"awayOdds": 225, "homeOdds": -310},
                                            "currentLine": {
                                                "awayOdds": 235,
                                                "homeOdds": -333,
                                                "awaySpread": 1.5,
                                                "homeSpread": -1.5,
                                            },
                                        },
                                    ],
                                }
                            ]
                        }
                    }
                ]
            }
        }
    }
    html = (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + "</script></html>"
    ).encode()
    parsed = parse_market_page(html, "moneyline")
    assert len(parsed) == 1
    value = next(iter(parsed.values()))
    assert value["opening"]["awayOdds"] == 225
    # Outcome fields exist in the synthetic source but are not returned by the parser.
    assert "awayTeamScore" not in json.dumps(value)
    print("SELF_TEST_OK")
    return 0


def run(args: argparse.Namespace) -> int:
    start = parse_iso_date(args.start_date)
    end = parse_iso_date(args.end_date)
    days = daterange(start, end)
    output = Path(args.output)
    manifest_path = Path(args.manifest)
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    pages: dict[str, Any] = {}
    date_row_counts: dict[str, int] = {}

    for index, day in enumerate(days):
        day_pages: dict[str, bytes] = {}
        for market in ("moneyline", "pointspread"):
            url = source_url(day, market)
            try:
                body = fetch_page(url)
            except RecoveryError as exc:
                blockers.append(f"FETCH:{day}:{market}:{exc}")
                continue
            raw_path = raw_dir / f"{day}_{market}.html"
            raw_path.write_bytes(body)
            day_pages[market] = body
            pages[f"{day}:{market}"] = {
                "url": url,
                "sha256": sha256_bytes(body),
                "bytes": len(body),
                "artifact_path": raw_path.as_posix(),
            }
        if set(day_pages) != {"moneyline", "pointspread"}:
            date_row_counts[day] = 0
            continue
        try:
            rows, row_blockers = build_rows(day, day_pages["moneyline"], day_pages["pointspread"])
        except RecoveryError as exc:
            blockers.append(f"PARSE:{day}:{exc}")
            date_row_counts[day] = 0
            continue
        if not rows:
            blockers.append(f"NO_DK_ROWS:{day}")
        all_rows.extend(rows)
        blockers.extend(row_blockers)
        date_row_counts[day] = len(rows)
        if index + 1 < len(days):
            time.sleep(args.delay_seconds)

    all_rows.sort(key=lambda r: (r["date"], r["start_date_utc"], r["away_team"], r["home_team"]))
    write_csv(output, all_rows)
    output_sha = sha256_bytes(output.read_bytes())
    script_path = Path(__file__).resolve()
    script_sha = sha256_bytes(script_path.read_bytes())
    missing_dates = [day for day in days if date_row_counts.get(day, 0) == 0]

    manifest = {
        "schema_version": 1,
        "purpose": "SPORTSEDGE_2025_DK_MONEYLINE_HOLDOUT_RECOVERY",
        "source": "SportsBookReview dated MLB odds pages",
        "source_scraper_reference": "ArnavSaraogi/mlb-odds-scraper",
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": os.environ.get("GITHUB_SHA"),
        "script_sha256": script_sha,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "expected_calendar_dates": len(days),
        "date_row_counts": date_row_counts,
        "missing_dates": missing_dates,
        "normalized_rows": len(all_rows),
        "normalized_csv_sha256": output_sha,
        "close_eligible_rows": sum(1 for row in all_rows if row["close_eligible"]),
        "close_ineligible_rows": sum(1 for row in all_rows if not row["close_eligible"]),
        "blockers": sorted(set(blockers)),
        "raw_pages": pages,
        "normalized_fields_exclude_outcomes": True,
        "status": "COMPLETE" if not blockers and not missing_dates else "INCOMPLETE",
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    print(json.dumps({
        "status": manifest["status"],
        "rows": manifest["normalized_rows"],
        "close_eligible_rows": manifest["close_eligible_rows"],
        "missing_dates": missing_dates,
        "blocker_count": len(manifest["blockers"]),
        "normalized_csv_sha256": output_sha,
        "script_sha256": script_sha,
    }, sort_keys=True))
    return 0 if manifest["status"] == "COMPLETE" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2025-08-17")
    parser.add_argument("--end-date", default="2025-09-28")
    parser.add_argument("--output", default="artifacts/evidence/mlb_2025_dk_recovery.csv")
    parser.add_argument("--manifest", default="artifacts/evidence/mlb_2025_dk_recovery_manifest.json")
    parser.add_argument("--raw-dir", default="artifacts/evidence/mlb_2025_sbr_raw")
    parser.add_argument("--delay-seconds", type=float, default=0.75)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.self_test:
        return self_test()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
