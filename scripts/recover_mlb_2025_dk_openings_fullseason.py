#!/usr/bin/env python3
"""Recover 2025 MLB DraftKings opening moneylines from SportsBookReview.

Acquisition/provenance only. This module never fits, scores, grades, or reads
SportsEdge's frozen 2025 confirmatory feature/outcome files.

Important identity rule: MLB can expose the same gamePk on an original
postponed/suspended date and again on the date the game is actually completed.
The primary pricing identity is the latest completed official occurrence. If a
completed occurrence has no recoverable SBR opener, an earlier official
occurrence may be used only as a separately labelled original-schedule opener
for the *same* gamePk and only when the match is unique. No price is imputed
from a neighbouring game or another bookmaker.
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
FINAL_STATES = {"final", "game over", "completed early"}
MAX_START_DELTA_SECONDS = 8 * 3600

# These gamePks were the concrete regression that exposed the stale-date bug.
# They are assertions over acquisition identity only; no outcomes/model values.
KNOWN_FULL_SEASON_BINDINGS = {
    776907: "2025-08-03",
    777294: "2025-07-02",
    777277: "2025-07-02",
    777623: "2025-06-07",
    777612: "2025-06-07",
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
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def american_open_valid(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and value != 0
        and abs(float(value)) >= 100.0
    )


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

    @property
    def is_postponed(self) -> bool:
        return "postpon" in self.detailed_state.lower()

    @property
    def is_final(self) -> bool:
        return self.detailed_state.lower() in FINAL_STATES


def select_primary_occurrence(rows: list[OfficialGame]) -> OfficialGame:
    """Select the actual/latest completed occurrence for one stable gamePk.

    The previous implementation sorted official_date ascending after status,
    which selected stale original dates whenever MLB returned two Final rows
    for a rescheduled game. That collapsed doubleheaders and created false
    missing/duplicate gamePks.
    """
    if not rows:
        raise ValueError("OFFICIAL_OCCURRENCES_EMPTY")
    return max(
        rows,
        key=lambda g: (
            int(g.is_final),
            int(not g.is_postponed),
            g.start.timestamp(),
            g.official_date,
        ),
    )


def official_schedule(
    start: str,
    end: str,
) -> tuple[dict[int, OfficialGame], dict[int, list[OfficialGame]], bytes]:
    query = urllib.parse.urlencode(
        {"sportId": 1, "startDate": start, "endDate": end, "hydrate": "status"}
    )
    raw = fetch_bytes("https://statsapi.mlb.com/api/v1/schedule?" + query)
    payload = json.loads(raw)
    histories: dict[int, list[OfficialGame]] = {}
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
            histories.setdefault(game.game_pk, []).append(game)

    for rows in histories.values():
        rows.sort(key=lambda g: (g.start, g.official_date, g.detailed_state))
    selected = {pk: select_primary_occurrence(rows) for pk, rows in histories.items()}
    return selected, histories, raw


def parse_sbr_moneyline(next_bytes: bytes, page_date: str) -> list[dict[str, Any]]:
    payload = json.loads(next_bytes)
    tables = payload.get("props", {}).get("pageProps", {}).get("oddsTables", [])
    if not tables:
        return []
    rows = tables[0].get("oddsTableModel", {}).get("gameRows", []) or []
    out: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows):
        gv = row.get("gameView") or {}
        away = (gv.get("awayTeam") or {}).get("fullName", "")
        home = (gv.get("homeTeam") or {}).get("fullName", "")
        dk = next(
            (
                view
                for view in (row.get("oddsViews") or [])
                if view and str(view.get("sportsbook", "")).lower() == "draftkings"
            ),
            None,
        )
        opening = (dk or {}).get("openingLine") or {}
        out.append(
            {
                "source_row_id": f"{page_date}:{row_index}",
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


def scrape_one(
    page_date: str,
    raw_dir: Path,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    url = f"https://www.sportsbookreview.com/betting-odds/mlb-baseball/?date={page_date}"
    html = fetch_bytes(url)
    match = NEXT_DATA_RE.search(html)
    if not match:
        raise RuntimeError(f"SBR_NEXT_DATA_MISSING:{page_date}")
    next_bytes = match.group(1)
    (raw_dir / f"sbr_next_data_{page_date}.json").write_bytes(next_bytes)
    rows = parse_sbr_moneyline(next_bytes, page_date)
    return page_date, rows, {
        "date": page_date,
        "sha256": sha256_bytes(next_bytes),
        "bytes": len(next_bytes),
        "rows": len(rows),
    }


def same_matchup(row: dict[str, Any], game: OfficialGame) -> bool:
    return (
        normalize_team(row.get("away", "")) == game.away_key
        and normalize_team(row.get("home", "")) == game.home_key
    )


def row_delta(row: dict[str, Any], game: OfficialGame) -> float | None:
    start = parse_ts(row.get("sbr_start"))
    if start is None:
        return None
    return abs((game.start - start).total_seconds())


def row_has_valid_dk(row: dict[str, Any]) -> bool:
    return bool(
        row.get("has_dk")
        and american_open_valid(row.get("away_open"))
        and american_open_valid(row.get("home_open"))
    )


def make_bound_row(
    row: dict[str, Any],
    primary: OfficialGame,
    price_occurrence: OfficialGame,
    delta: float,
    binding_mode: str,
) -> dict[str, Any]:
    return {
        "gamePk": primary.game_pk,
        "official_date": primary.official_date,
        "official_start": primary.game_date,
        "price_schedule_date": price_occurrence.official_date,
        "price_schedule_start": price_occurrence.game_date,
        "price_schedule_state": price_occurrence.detailed_state,
        "binding_mode": binding_mode,
        "sbr_page_date": row["page_date"],
        "sbr_start": row.get("sbr_start"),
        "away": primary.away,
        "home": primary.home,
        "awayML_open_DK": row.get("away_open"),
        "homeML_open_DK": row.get("home_open"),
        "draftkings_open_valid": row_has_valid_dk(row),
        "start_delta_seconds": int(delta),
        "source_row_id": row["source_row_id"],
    }


def bind_rows(
    official: dict[int, OfficialGame],
    histories: dict[int, list[OfficialGame]],
    sbr_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    matchup_to_games: dict[tuple[str, str], list[OfficialGame]] = {}
    for game in official.values():
        matchup_to_games.setdefault((game.away_key, game.home_key), []).append(game)

    proposals: dict[int, list[tuple[float, str, dict[str, Any], OfficialGame]]] = {}
    unmatched_source_ids: set[str] = set()
    ambiguous_rows: list[dict[str, Any]] = []

    # Pass 1: bind against the primary/latest completed occurrence.
    for row in sbr_rows:
        key = (normalize_team(row.get("away", "")), normalize_team(row.get("home", "")))
        ranked: list[tuple[float, int, OfficialGame]] = []
        for game in matchup_to_games.get(key, []):
            delta = row_delta(row, game)
            if delta is not None:
                ranked.append((delta, game.game_pk, game))
        ranked.sort(key=lambda item: (item[0], item[1]))
        if not ranked or ranked[0][0] > MAX_START_DELTA_SECONDS:
            unmatched_source_ids.add(row["source_row_id"])
            continue
        if len(ranked) > 1 and ranked[1][0] == ranked[0][0]:
            ambiguous_rows.append(
                {
                    "row": row,
                    "candidate_gamePks": [ranked[0][1], ranked[1][1]],
                    "delta_seconds": ranked[0][0],
                }
            )
            continue
        delta, _, game = ranked[0]
        proposals.setdefault(game.game_pk, []).append(
            (delta, row["source_row_id"], row, game)
        )

    by_pk: dict[int, dict[str, Any]] = {}
    used_source_ids: set[str] = set()
    duplicate_game_pks: list[int] = []
    duplicate_details: dict[str, Any] = {}

    for game_pk, items in proposals.items():
        items.sort(key=lambda item: (item[0], item[1]))
        best = items[0]
        if len(items) > 1 and items[1][0] == best[0]:
            duplicate_game_pks.append(game_pk)
            duplicate_details[str(game_pk)] = [
                {"source_row_id": item[1], "delta_seconds": item[0]}
                for item in items
            ]
            continue
        delta, source_id, row, game = best
        by_pk[game_pk] = make_bound_row(row, game, game, delta, "PRIMARY_FINAL_OCCURRENCE")
        used_source_ids.add(source_id)

    # Pass 2: if the completed occurrence has no row, permit a unique valid DK
    # opener from another official occurrence of the *same* stable gamePk.
    # This is particularly important for games postponed after an opener was
    # already posted. The original occurrence is preserved explicitly.
    history_recoveries: list[dict[str, Any]] = []
    unresolved_before_history = sorted(set(official) - set(by_pk))
    for game_pk in unresolved_before_history:
        primary = official[game_pk]
        candidate_matches: list[
            tuple[float, datetime, str, dict[str, Any], OfficialGame]
        ] = []
        for occurrence in histories.get(game_pk, []):
            if occurrence == primary:
                continue
            for row in sbr_rows:
                source_id = row["source_row_id"]
                if source_id in used_source_ids or not row_has_valid_dk(row):
                    continue
                if not same_matchup(row, occurrence):
                    continue
                delta = row_delta(row, occurrence)
                if delta is None or delta > MAX_START_DELTA_SECONDS:
                    continue
                candidate_matches.append(
                    (delta, occurrence.start, source_id, row, occurrence)
                )
        candidate_matches.sort(key=lambda item: (item[0], item[1], item[2]))
        if not candidate_matches:
            continue
        best = candidate_matches[0]
        if len(candidate_matches) > 1 and candidate_matches[1][0] == best[0]:
            ambiguous_rows.append(
                {
                    "gamePk": game_pk,
                    "reason": "HISTORY_FALLBACK_EQUAL_DELTA",
                    "source_row_ids": [best[2], candidate_matches[1][2]],
                    "delta_seconds": best[0],
                }
            )
            continue
        delta, _, source_id, row, occurrence = best
        by_pk[game_pk] = make_bound_row(
            row,
            primary,
            occurrence,
            delta,
            "ORIGINAL_SCHEDULE_OCCURRENCE",
        )
        used_source_ids.add(source_id)
        history_recoveries.append(
            {
                "gamePk": game_pk,
                "primary_official_date": primary.official_date,
                "price_schedule_date": occurrence.official_date,
                "price_schedule_state": occurrence.detailed_state,
                "source_row_id": source_id,
            }
        )

    missing_game_pks = sorted(set(official) - set(by_pk))
    invalid_open_game_pks = sorted(
        game_pk
        for game_pk, row in by_pk.items()
        if not row["draftkings_open_valid"]
    )
    unused_unmatched_rows = [
        row
        for row in sbr_rows
        if row["source_row_id"] not in used_source_ids
        and row["source_row_id"] in unmatched_source_ids
    ]
    report = {
        "official_unique_gamePks": len(official),
        "sbr_rows_total": len(sbr_rows),
        "uniquely_bound_gamePks": len(by_pk),
        "valid_dk_open_gamePks": sum(
            bool(row["draftkings_open_valid"]) for row in by_pk.values()
        ),
        "missing_gamePks": missing_game_pks,
        "invalid_open_gamePks": invalid_open_game_pks,
        "duplicate_bound_gamePks": sorted(duplicate_game_pks),
        "duplicate_details": duplicate_details,
        "history_recoveries": history_recoveries,
        "ambiguous_rows": ambiguous_rows,
        "unmatched_sbr_rows": unused_unmatched_rows,
    }
    return [by_pk[k] for k in sorted(by_pk)], report


def assert_known_full_season_bindings(
    bound: list[dict[str, Any]],
    start: str,
    end: str,
) -> None:
    if start > "2025-03-18" or end < "2025-09-28":
        return
    by_pk = {int(row["gamePk"]): row for row in bound}
    for game_pk, expected_page_date in KNOWN_FULL_SEASON_BINDINGS.items():
        row = by_pk.get(game_pk)
        if row is None:
            raise AssertionError(f"KNOWN_GAMEPK_NOT_BOUND:{game_pk}")
        if row["sbr_page_date"] != expected_page_date:
            raise AssertionError(
                f"KNOWN_GAMEPK_WRONG_SBR_DATE:{game_pk}:"
                f"{row['sbr_page_date']}!={expected_page_date}"
            )


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

    official, histories, schedule_raw = official_schedule(args.start, args.end)
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

    bound, reconciliation = bind_rows(official, histories, all_rows)
    assert_known_full_season_bindings(bound, args.start, args.end)
    source_manifest.sort(key=lambda item: item["date"])

    opening_path = outdir / "dk_openings_2025_gamepk.csv"
    fields = [
        "gamePk",
        "official_date",
        "official_start",
        "price_schedule_date",
        "price_schedule_start",
        "price_schedule_state",
        "binding_mode",
        "sbr_page_date",
        "sbr_start",
        "away",
        "home",
        "awayML_open_DK",
        "homeML_open_DK",
        "draftkings_open_valid",
        "start_delta_seconds",
        "source_row_id",
    ]
    with opening_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(bound)

    source_manifest_path = outdir / "sbr_source_manifest.json"
    source_manifest_path.write_text(
        json.dumps(source_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = {
        "schema_version": 2,
        "purpose": "2025_DK_OPENING_ACQUISITION_ONLY",
        "start": args.start,
        "end": args.end,
        "source": "SportsBookReview __NEXT_DATA__ moneyline pages",
        "official_schedule_source": "MLB StatsAPI",
        "identity_policy": "LATEST_COMPLETED_GAMEPK_WITH_UNIQUE_ORIGINAL_OCCURRENCE_FALLBACK",
        "reconciliation": reconciliation,
        "artifacts": {
            "mlb_statsapi_schedule_raw.json": {
                "sha256": sha256_bytes(schedule_raw),
                "bytes": len(schedule_raw),
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
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))

    if not report["admissible_for_full_confirmatory_input"]:
        raise SystemExit("FULL_2025_DK_OPENING_RECOVERY_BLOCKED")


if __name__ == "__main__":
    main()
