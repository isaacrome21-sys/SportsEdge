#!/usr/bin/env python3
"""Probe frozen free sources for NFL prop-usage V1 without scoring 2025."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from hashlib import sha256
import io
import json
import re
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, Tag

UA = "SportsEdge-NFL-prop-v1-source-admission/1.0"
LINE_REPO = "firstandthirty/nfl-tools"
LINE_COMMIT = "38af9f64b42d2817dc172af637abebe2b7799194"
LINE_FILES = {
    "player_pass_yds": "player_props/data/processed/fanduel_pass_yds_history.csv",
    "player_rush_yds": "player_props/data/analysis/rush_yds_market_analysis_rows.csv",
    "player_reception_yds": "player_props/data/analysis/reception_yds_market_analysis_rows.csv",
}
SCHEDULE_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
SEASON_MONTHS = [(2025, 9), (2025, 10), (2025, 11), (2025, 12), (2026, 1)]

TEAM_ALIASES = {
    "ARI": ["ARIZONA CARDINALS", "CARDINALS"], "ATL": ["ATLANTA FALCONS", "FALCONS"],
    "BAL": ["BALTIMORE RAVENS", "RAVENS"], "BUF": ["BUFFALO BILLS", "BILLS"],
    "CAR": ["CAROLINA PANTHERS", "PANTHERS"], "CHI": ["CHICAGO BEARS", "BEARS"],
    "CIN": ["CINCINNATI BENGALS", "BENGALS"], "CLE": ["CLEVELAND BROWNS", "BROWNS"],
    "DAL": ["DALLAS COWBOYS", "COWBOYS"], "DEN": ["DENVER BRONCOS", "BRONCOS"],
    "DET": ["DETROIT LIONS", "LIONS"], "GB": ["GREEN BAY PACKERS", "PACKERS"],
    "HOU": ["HOUSTON TEXANS", "TEXANS"], "IND": ["INDIANAPOLIS COLTS", "COLTS"],
    "JAX": ["JACKSONVILLE JAGUARS", "JAGUARS"], "KC": ["KANSAS CITY CHIEFS", "CHIEFS"],
    "LV": ["LAS VEGAS RAIDERS", "RAIDERS"], "LAC": ["LOS ANGELES CHARGERS", "L.A. CHARGERS", "CHARGERS"],
    "LAR": ["LOS ANGELES RAMS", "L.A. RAMS", "RAMS"], "MIA": ["MIAMI DOLPHINS", "DOLPHINS"],
    "MIN": ["MINNESOTA VIKINGS", "VIKINGS"], "NE": ["NEW ENGLAND PATRIOTS", "PATRIOTS"],
    "NO": ["NEW ORLEANS SAINTS", "SAINTS"], "NYG": ["NEW YORK GIANTS", "N.Y. GIANTS", "GIANTS"],
    "NYJ": ["NEW YORK JETS", "N.Y. JETS", "JETS"], "PHI": ["PHILADELPHIA EAGLES", "EAGLES"],
    "PIT": ["PITTSBURGH STEELERS", "STEELERS"], "SEA": ["SEATTLE SEAHAWKS", "SEAHAWKS"],
    "SF": ["SAN FRANCISCO 49ERS", "49ERS", "NINERS"], "TB": ["TAMPA BAY BUCCANEERS", "BUCCANEERS", "BUCS"],
    "TEN": ["TENNESSEE TITANS", "TITANS"], "WAS": ["WASHINGTON COMMANDERS", "COMMANDERS"],
}
POSITION_TOKENS = {
    "QB","RB","FB","HB","WR","TE","OL","OT","T","LT","RT","OG","G","LG","RG","C",
    "DL","DT","NT","DE","EDGE","OLB","LB","ILB","CB","DB","S","FS","SS","K","P","LS",
}

class ProbeError(RuntimeError):
    pass

def fetch(url: str, timeout: int = 60) -> tuple[bytes, str]:
    req = Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        final = resp.geturl()
    if not data:
        raise ProbeError(f"EMPTY_SOURCE:{url}")
    return data, final

def digest(data: bytes) -> str:
    return sha256(data).hexdigest()

def norm_space(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()

def norm_heading(value: object) -> str:
    out = norm_space(value).upper()
    out = out.replace("’", "'").replace("–", "-").replace("—", "-")
    out = re.sub(r"[^A-Z0-9.' -]+", " ", out)
    out = re.sub(r"\b\d{1,2}-\d{1,2}(?:-\d)?\b", " ", out)
    return norm_space(out)

def team_from_heading(value: object) -> str | None:
    h = norm_heading(value)
    for team, aliases in TEAM_ALIASES.items():
        if h in aliases:
            return team
    return None

def parse_player_bullet(value: object) -> tuple[str, str] | None:
    text = norm_space(value)
    if not text or text.upper().startswith(("WHERE:", "WHEN:", "TV:", "WATCH:")):
        return None
    text = re.sub(r"\s*\([^)]*(?:QB|quarterback|inactive|injury|third)[^)]*\)\s*$", "", text, flags=re.I)
    parts = text.split()
    if len(parts) < 2:
        return None
    pos = parts[0].upper().rstrip(".:")
    if pos not in POSITION_TOKENS:
        return None
    return pos, norm_space(" ".join(parts[1:]))

def extract_week(title: str) -> int | None:
    m = re.search(r"\bWeek\s+(\d{1,2})\b", title, flags=re.I)
    if not m:
        return None
    week = int(m.group(1))
    return week if 1 <= week <= 18 else None

def parse_timestamp(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None

def _first(row: dict[str, str], names: tuple[str, ...]) -> str:
    lower = {str(k).lower(): k for k in row}
    for name in names:
        key = lower.get(name.lower())
        if key is not None and row.get(key) not in (None, ""):
            return str(row[key])
    return ""

def probe_line_source(market: str, path: str) -> dict:
    url = f"https://raw.githubusercontent.com/{LINE_REPO}/{LINE_COMMIT}/{path}"
    raw, final = fetch(url, timeout=90)
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    fields = {str(x) for x in (reader.fieldnames or [])}
    if not fields:
        raise ProbeError(f"LINE_SCHEMA_EMPTY:{market}")

    rows_2025 = 0
    strictly_prekick = 0
    weeks: set[int] = set()
    player_events: set[tuple[str, str]] = set()
    snapshots: dict[tuple[str, str], datetime] = {}

    for row in reader:
        season_raw = _first(row, ("season", "season_guess", "season_str"))
        try:
            season = int(float(season_raw))
        except (TypeError, ValueError):
            continue
        if season != 2025:
            continue
        rows_2025 += 1

        week_raw = _first(row, ("week", "week_guess_numeric", "week_guess", "week_str"))
        try:
            week = int(float(week_raw))
            if 1 <= week <= 18:
                weeks.add(week)
        except (TypeError, ValueError):
            pass

        player = _first(row, ("player", "player_name"))
        event = _first(row, ("event_id", "game_id"))
        if player and event:
            player_events.add((player, event))

        snapshot = parse_timestamp(_first(row, ("requested_snapshot_time", "snapshot_ts", "captured_at")))
        kickoff = parse_timestamp(_first(row, ("commence_time", "kickoff", "kickoff_at")))
        if snapshot is not None and kickoff is not None and snapshot < kickoff:
            strictly_prekick += 1
            key = (player, event)
            prev = snapshots.get(key)
            if prev is None or snapshot > prev:
                snapshots[key] = snapshot

    if rows_2025 <= 0:
        raise ProbeError(f"NO_2025_LINE_ROWS:{market}")
    if strictly_prekick <= 0:
        raise ProbeError(f"NO_PROVEN_PREKICK_ROWS:{market}")

    return {
        "market": market,
        "source_url": final,
        "raw_sha256": digest(raw),
        "raw_bytes": len(raw),
        "fields": sorted(fields),
        "rows_2025": rows_2025,
        "weeks_2025": sorted(weeks),
        "unique_player_events_2025": len(player_events),
        "strictly_prekick_rows_2025": strictly_prekick,
        "latest_prekick_player_events_2025": len(snapshots),
        "model_input_columns": [
            "season","week","event_id/game_id","player/player_name","line",
            "over_price","under_price","requested_snapshot_time/snapshot_ts","commence_time/kickoff"
        ],
        "outcome_columns_used": False
    }

def schedule_team_weeks() -> tuple[set[tuple[int,str]], dict]:
    raw, final = fetch(SCHEDULE_URL, timeout=90)
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    expected: set[tuple[int,str]] = set()
    for row in reader:
        try:
            season = int(float(row.get("season", "")))
            week = int(float(row.get("week", "")))
        except (TypeError, ValueError):
            continue
        if season != 2025 or str(row.get("game_type", "")).upper() != "REG":
            continue
        for key in ("home_team", "away_team"):
            team = str(row.get(key) or "").strip().upper()
            if team == "LA":
                team = "LAR"
            if team:
                expected.add((week, team))
    if len(expected) != 544:
        raise ProbeError(f"EXPECTED_TEAM_WEEK_DRIFT:{len(expected)}")
    return expected, {"source_url": final, "raw_sha256": digest(raw), "raw_bytes": len(raw)}

def discover_inactive_articles() -> tuple[list[str], list[dict]]:
    urls: set[str] = set()
    receipts: list[dict] = []
    for year, month in SEASON_MONTHS:
        sitemap = f"https://www.nfl.com/sitemap/html/articles/{year}/{month}"
        try:
            raw, final = fetch(sitemap)
        except Exception as exc:
            receipts.append({"url": sitemap, "status": "ERROR", "error": f"{type(exc).__name__}:{exc}"})
            continue
        receipts.append({"url": final, "status": "OK", "sha256": digest(raw), "raw_bytes": len(raw)})
        soup = BeautifulSoup(raw, "html.parser")
        for a in soup.find_all("a", href=True):
            text = norm_space(a.get_text(" ", strip=True))
            href = urljoin("https://www.nfl.com", str(a.get("href") or ""))
            if "inactive" not in text.lower() and "inactive" not in href.lower():
                continue
            if "/news/" not in href:
                continue
            path = urlparse(href).path
            urls.add(f"https://amp.nfl.com{path}")
    return sorted(urls), receipts

def inactive_coverage(expected: set[tuple[int,str]]) -> dict:
    urls, sitemap_receipts = discover_inactive_articles()
    found: set[tuple[int,str]] = set()
    article_receipts: list[dict] = []
    parsed_players = 0
    for url in urls:
        try:
            raw, final = fetch(url)
        except Exception as exc:
            article_receipts.append({"url": url, "status": "ERROR", "error": f"{type(exc).__name__}:{exc}"})
            continue
        soup = BeautifulSoup(raw, "html.parser")
        h1 = soup.find("h1")
        title = norm_space(h1.get_text(" ", strip=True) if h1 else soup.title.get_text(" ", strip=True) if soup.title else "")
        week = extract_week(title)
        article_receipts.append({
            "url": final, "status": "OK", "sha256": digest(raw),
            "raw_bytes": len(raw), "week": week, "title": title
        })
        if week is None:
            continue

        labels = list(soup.find_all(["h2","h3","h4"])) + list(soup.find_all(True))
        seen_sections: set[tuple[str,int]] = set()
        for label in labels:
            team = team_from_heading(label.get_text(" ", strip=True))
            if not team:
                continue
            ul = label.find_next("ul")
            if ul is None:
                continue
            key = (team, id(ul))
            if key in seen_sections:
                continue
            seen_sections.add(key)
            bullets = []
            for li in ul.find_all("li"):
                parsed = parse_player_bullet(li.get_text(" ", strip=True))
                if parsed is not None:
                    bullets.append(parsed)
            if len(bullets) < 3:
                continue
            found.add((week, team))
            parsed_players += len(bullets)

    missing = sorted(expected - found)
    extra = sorted(found - expected)
    coverage = len(expected & found) / len(expected) if expected else 0.0
    return {
        "discovered_article_urls": len(urls),
        "official_team_weeks_found": len(found),
        "expected_schedule_team_weeks": len(expected),
        "coverage": coverage,
        "missing_team_weeks": [{"week": w, "team": t} for w,t in missing],
        "extra_team_weeks": [{"week": w, "team": t} for w,t in extra],
        "parsed_inactive_players": parsed_players,
        "sitemap_receipts": sitemap_receipts,
        "article_receipts": article_receipts
    }

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    lines = [probe_line_source(m, p) for m,p in LINE_FILES.items()]
    expected, schedule_receipt = schedule_team_weeks()
    inactives = inactive_coverage(expected)

    line_gate = all(
        row["rows_2025"] > 0
        and row["strictly_prekick_rows_2025"] > 0
        and row["latest_prekick_player_events_2025"] > 0
        for row in lines
    )
    inactive_gate = (
        inactives["expected_schedule_team_weeks"] == 544
        and inactives["coverage"] == 1.0
        and not inactives["missing_team_weeks"]
    )
    result = {
        "schema": "SPORTSEDGE_NFL_PROP_USAGE_V1_SOURCE_PROBE",
        "status": "SOURCE_ADMISSION_PASS" if line_gate and inactive_gate else "SOURCE_ADMISSION_FAIL",
        "model_scoring_performed": False,
        "validation_outcomes_read": False,
        "line_gate_passed": line_gate,
        "inactive_gate_passed": inactive_gate,
        "line_sources": lines,
        "schedule_source": schedule_receipt,
        "inactive_source": inactives,
        "next_step": "FIT_2021_2024_WITH_VALIDATION_STILL_UNSPENT" if line_gate and inactive_gate else "REPAIR_SOURCE_ADMISSION_WITHOUT_MODEL_SCORING"
    }
    encoded = json.dumps(result, indent=2, sort_keys=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(encoded + "\n")
    print("NFL_PROP_USAGE_V1_SOURCE_PROBE=" + json.dumps({
        "status": result["status"],
        "line_gate_passed": line_gate,
        "inactive_gate_passed": inactive_gate,
        "market_rows": {r["market"]: r["rows_2025"] for r in lines},
        "inactive_coverage": inactives["coverage"],
        "missing_team_weeks": len(inactives["missing_team_weeks"]),
        "model_scoring_performed": False
    }, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
