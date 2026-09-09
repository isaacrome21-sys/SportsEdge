#!/usr/bin/env python3
"""Recover 2025 MLB DraftKings opening moneylines from SportsBookReview.

This is an acquisition/provenance tool only. It does not fit, score, grade, or
run any SportsEdge model and it never reads the frozen 2025 confirmatory
feature/outcome files.

The upstream ArnavSaraogi/mlb-odds-scraper historically keyed rows only by
same-day matchup, which collapses doubleheaders. This implementation binds SBR
rows to MLB gamePk using canonical team identity plus scheduled start time.
Raw SBR __NEXT_DATA__ bytes are retained outside the public source tree by the
calling workflow.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

NEXT_DATA_RE = re.compile(
    rb'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "Chrome/140 Safari/537.36"
)
ATH_ALIASES = {
    "athletics athletics": "athletics",
    "oakland athletics": "athletics",
    "sacramento athletics": "athletics",
    "the athletics": "athletics",
    "athletics": "athletics",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_team(value: str) -> str:
    out = (value or "").lower().replace(".", "").replace("'", "")
    out = out.replace("-", " ").replace("&", "and")
    out = " ".join(out.split())
    return ATH_ALIASES.get(out, out)


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def american_open_valid(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return value != 0 and abs(float(value)) >= 100.0


def daterange(start: str, end: str):
    current = date.fromisoformat(start)
    last = date.fromisoformat(end)
    while current <= last:
        yield current.isoformat()
        current += timedelta(days=1)


def fetch_bytes(url: str, retries: int = 5) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            )
            with urllib.request.urlopen(req, timeout=35) as response:
                data = response.read()
            if data:
                return data
        except Exception as exc:  # pragma: no cover - network lane
            last = exc
            time.sleep(1.25 * (attempt + 1))
    raise RuntimeError(f"FETCH_FAILED:{url}:{last!r}")


@dataclass(frozen=True)
class OfficialGame:
    game_pk: int
    official_date: str
    game_date: str
    away: str
    home: str
    detailed_state: str

    @property
    def away_key(self) -> str:
        return normalize_team(self.away)

    @property
    def home_key(self) -> str:
        return normalize_team(self.home)

    @property
    def start(self) -> datetime:
        parsed = parse_ts(self.game_date)
        if parsed is None:
            raise ValueError(f"OFFICIAL_START_MISSING:{self.game_pk}")
        return parsed


def official_schedule(start: str, end: str) -> tuple[dict[int, OfficialGame], bytes]:
    query = urllib.parse.urlencode(
        {"sportId": 1, "startDate": start, "endDate": end, "hydrate": "status"}
    )
    raw = fetch_bytes("https://statsapi.mlb.com/api/v1/schedule?" + query)
    payload = json.loads(raw)
    by_pk: dict[int, list[OfficialGame]] = {}
    for block in payload.get("dates", []):
        d = block["date"]
        for item in block.get("games", []):
            if item.get("gameType") != "R":
                continue
            game = OfficialGame(
                game_pk=int(item["gamePk"]),
                official_date=d,
                game_date=item["gameDate"],
                away=item["teams"]["away"]["team"]["name"],
                home=item["teams"]["home"]["team"]["name"],
                detailed_state=(item.get("status") or {}).get("detailedState", ""),
            )
            by_pk.setdefault(game.game_pk, []).append(game)

    selected: dict[int, OfficialGame] = {}
    for game_pk, rows in by_pk.items():
        # A postponed game can appear once on the original date and again on its
        # makeup date with the same gamePk. Prefer the non-postponed/final row.
        preferred = sorted(
            rows,
            key=lambda g: (
                "postpon" in g.detailed_state.lower(),
                g.detailed_state.lower() not in {"final", "game over", "completed early"},
                g.official_date,
            ),
        )[0]
        selected[game_pk] = preferred
    return selected, raw


def parse_sbr_moneyline(next_bytes: bytes, page_date: str) -> list[dict[str, Any]]:
    payload = json.loads(next_bytes)
    tables = payload.get("props", {}).get("pageProps", {}).get("oddsTables", [])
    if not tables:
        return []
    rows = tables[0].get("oddsTableModel", {}).get("gameRows", []) or []
    out: list[dict[str, Any]] = []
    for row in rows:
        gv = row.get("gameView") or {}
        away = (gv.get("awayTeam") or {}).get("fullName", "")
        home = (gv.get("homeTeam") or {}).get("fullName", "")
        dk = None
        for view in row.get("oddsViews") or []:
            if view and str(view.get("sportsbook", "")).lower() == "draftkings":
                dk = view
                break
        opening = (dk or {}).get("openingLine") or {}
        out.append(
            {
                "page_date": page_date,
                "sbr_start": gv.get("startDate"),
                "away": away,
                "home": home,
                "away_open": opening.get("awayOdds"),
                "home_open": opening.get("homeOdds"),
                "has_dk": dk is not None,
            }
        )
    return out


def scrape_one(page_date: str, raw_dir: Path) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    url = f"https://www.sportsbookreview.com/betting-odds/mlb-baseball/?date={page_date}"
    html = fetch_bytes(url)
    match = NEXT_DATA_RE.search(html)
    if not match:
        raise RuntimeError(f"SBR_NEXT_DATA_MISSING:{page_date}")
    next_bytes = match.group(1)
    raw_path = raw_dir / f"sbr_next_data_{page_date}.json"
    raw_path.write_bytes(next_bytes)
    rows = parse_sbr_moneyline(next_bytes, page_date)
    meta = {
        "date": page_date,
        "sha256": sha256_bytes(next_bytes),
        "bytes": len(next_bytes),
        "rows": len(rows),
    }
    return page_date, rows, meta


def bind_rows(
    official: dict[int, OfficialGame],
    sbr_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: dict[tuple[str, str], list[OfficialGame]] = {}
    for game in official.values():
        candidates.setdefault((game.away_key, game.home_key), []).append(game)

    bound: list[dict[str, Any]] = []
    unmatched_sbr: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    seen_game_pk: dict[int, int] = {}

    for row in sbr_rows:
        start = parse_ts(row.get("sbr_start"))
        key = (normalize_team(row.get("away", "")), normalize_team(row.get("home", "")))
        pool = candidates.get(key, [])
        ranked = []
        if start is not None:
            for game in pool:
                delta = abs((game.start - start).total_seconds())
                ranked.append((delta, game.game_pk, game))
            ranked.sort(key=lambda x: (x[0], x[1]))
        if not ranked or ranked[0][0] > 8 * 3600:
            unmatched_sbr.append(row)
            continue
        if len(ranked) > 1 and ranked[1][0] == ranked[0][0]:
            ambiguous.append(
                {
                    "row": row,
                    "candidate_gamePks": [ranked[0][1], ranked[1][1]],
                    "delta_seconds": ranked[0][0],
                }
            )
            continue
        delta, _, game = ranked[0]
        seen_game_pk[game.game_pk] = seen_game_pk.get(game.game_pk, 0) + 1
        bound.append(
            {
                "gamePk": game.game_pk,
                "official_date": game.official_date,
                "official_start": game.game_date,
                "sbr_page_date": row["page_date"],
                "sbr_start": row.get("sbr_start"),
                "away": game.away,
                "home": game.home,
                "awayML_open_DK": row.get("away_open"),
                "homeML_open_DK": row.get("home_open"),
                "draftkings_open_valid": bool(
                    row.get("has_dk")
                    and american_open_valid(row.get("away_open"))
                    and american_open_valid(row.get("home_open"))
                ),
                "start_delta_seconds": int(delta),
            }
        )

    duplicate_game_pks = sorted(pk for pk, n in seen_game_pk.items() if n > 1)
    # When a SBR page contains a stale duplicate row for the same gamePk, retain
    # no arbitrary winner. Duplicates are a hard ambiguity until audited.
    by_pk = {int(row["gamePk"]): row for row in bound if seen_game_pk[int(row["gamePk"])] == 1}
    missing_game_pks = sorted(set(official) - set(by_pk))
    invalid_open_game_pks = sorted(
        pk for pk, row in by_pk.items() if not row["draftkings_open_valid"]
    )
    report = {
        "official_unique_gamePks": len(official),
        "sbr_rows_total": len(sbr_rows),
        "uniquely_bound_gamePks": len(by_pk),
        "valid_dk_open_gamePks": sum(r["draftkings_open_valid"] for r in by_pk.values()),
        "missing_gamePks": missing_game_pks,
        "invalid_open_gamePks": invalid_open_game_pks,
        "duplicate_bound_gamePks": duplicate_game_pks,
        "ambiguous_rows": ambiguous,
        "unmatched_sbr_rows": unmatched_sbr,
    }
    return [by_pk[k] for k in sorted(by_pk)], report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-03-18")
    parser.add_argument("--end", default="2025-09-28")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--outdir", default="artifacts/mlb_2025_dk_opening_recovery")
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        raise SystemExit("--workers must be between 1 and 8")

    outdir = Path(args.outdir)
    raw_dir = outdir / "raw_sbr_next_data"
    raw_dir.mkdir(parents=True, exist_ok=True)

    official, schedule_raw = official_schedule(args.start, args.end)
    schedule_path = outdir / "mlb_statsapi_schedule_raw.json"
    schedule_path.write_bytes(schedule_raw)

    all_rows: list[dict[str, Any]] = []
    source_manifest: list[dict[str, Any]] = []
    dates = list(daterange(args.start, args.end))
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(scrape_one, d, raw_dir): d for d in dates}
        for future in concurrent.futures.as_completed(futures):
            d, rows, meta = future.result()
            all_rows.extend(rows)
            source_manifest.append(meta)
            print(f"SBR_CAPTURED:{d}:rows={len(rows)}")

    bound, reconciliation = bind_rows(official, all_rows)
    source_manifest.sort(key=lambda x: x["date"])

    opening_path = outdir / "dk_openings_2025_gamepk.csv"
    fields = [
        "gamePk", "official_date", "official_start", "sbr_page_date", "sbr_start",
        "away", "home", "awayML_open_DK", "homeML_open_DK",
        "draftkings_open_valid", "start_delta_seconds",
    ]
    with opening_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(bound)

    source_manifest_path = outdir / "sbr_source_manifest.json"
    source_manifest_path.write_text(
        json.dumps(source_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    report = {
        "schema_version": 1,
        "purpose": "2025_DK_OPENING_ACQUISITION_ONLY",
        "start": args.start,
        "end": args.end,
        "source": "SportsBookReview __NEXT_DATA__ moneyline pages",
        "official_schedule_source": "MLB StatsAPI",
        "reconciliation": reconciliation,
        "artifacts": {
            "mlb_statsapi_schedule_raw.json": {
                "sha256": sha256_bytes(schedule_raw), "bytes": len(schedule_raw)
            },
            "dk_openings_2025_gamepk.csv": {
                "sha256": sha256_bytes(opening_path.read_bytes()),
                "bytes": opening_path.stat().st_size,
            },
            "sbr_source_manifest.json": {
                "sha256": sha256_bytes(source_manifest_path.read_bytes()),
                "bytes": source_manifest_path.stat().st_size,
            },
        },
        "confirmatory_test_executed": False,
        "model_or_threshold_changed": False,
        "promotion_claimed": False,
        "eligible_changed": False,
    }
    report["admissible_for_full_confirmatory_input"] = bool(
        reconciliation["official_unique_gamePks"] == 2430
        and reconciliation["uniquely_bound_gamePks"] == 2430
        and reconciliation["valid_dk_open_gamePks"] == 2430
        and not reconciliation["missing_gamePks"]
        and not reconciliation["invalid_open_gamePks"]
        and not reconciliation["duplicate_bound_gamePks"]
        and not reconciliation["ambiguous_rows"]
    )
    report_path = outdir / "recovery_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))

    if not report["admissible_for_full_confirmatory_input"]:
        raise SystemExit("FULL_2025_DK_OPENING_RECOVERY_BLOCKED")


if __name__ == "__main__":
    main()
