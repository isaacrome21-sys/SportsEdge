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
import pandas as pd

UA = "SportsEdge-NFL-prop-v1-source-admission/1.0"
LINE_COMMIT = "5133c1b7ff56608cd1c2924d60512a6f33eaf99d"
LINE_URL = (
    "https://raw.githubusercontent.com/gcampb41/nfl_data-/"
    + LINE_COMMIT
    + "/data/processed/football/nfl/player_props/2025.parquet"
)
BOOKS = {68: "draftkings", 69: "fanduel"}
FULL_GAME_PERIODS = {
    "0", "0.0", "game", "full", "fullgame", "full_game", "full game", "event", "match", "all"
}
MARKET_BET_TYPES = {
    "player_pass_yds": {
        "passing_yards", "player_pass_yds", "player_passing_yards", "pass_yards",
        "core_bet_type_9_passing_yards",
    },
    "player_rush_yds": {"rushing_yards", "player_rush_yds", "rush_yards"},
    "player_reception_yds": {
        "receiving_yards", "player_reception_yds", "player_receiving_yards", "rec_yards",
    },
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

def _norm_text_series(series):
    return series.astype("string").fillna("").str.strip().str.lower()

def probe_line_archive() -> list[dict]:
    raw, final = fetch(LINE_URL, timeout=90)
    try:
        frame = pd.read_parquet(io.BytesIO(raw))
    except Exception as exc:
        raise ProbeError(f"LINE_PARQUET_READ_FAILED:{type(exc).__name__}:{exc}") from exc
    frame.columns = [str(x).strip().lower() for x in frame.columns]
    required = {"bet_type", "book_id", "side", "value", "week", "period"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ProbeError("LINE_SCHEMA_MISSING:" + ",".join(missing))

    if "season" in frame.columns:
        season = pd.to_numeric(frame["season"], errors="coerce")
        frame = frame.loc[season.eq(2025)].copy()
    week = pd.to_numeric(frame["week"], errors="coerce")
    frame = frame.loc[week.between(1, 18, inclusive="both")].copy()
    frame["week"] = pd.to_numeric(frame["week"], errors="coerce").astype("Int64")
    if frame.empty:
        raise ProbeError("NO_2025_LINE_ROWS")

    period = _norm_text_series(frame["period"]).str.replace(r"\s+", " ", regex=True)
    frame = frame.loc[period.isin(FULL_GAME_PERIODS)].copy()
    if frame.empty:
        raise ProbeError("NO_FULL_GAME_PROP_ROWS")

    frame["book_id"] = pd.to_numeric(frame["book_id"], errors="coerce")
    frame = frame.loc[frame["book_id"].isin(BOOKS)].copy()
    frame["book"] = frame["book_id"].map(BOOKS)
    if frame.empty:
        raise ProbeError("NO_DK_FD_PROP_ROWS")

    bet = _norm_text_series(frame["bet_type"])
    type_to_market = {
        bet_type: market
        for market, bet_types in MARKET_BET_TYPES.items()
        for bet_type in bet_types
    }
    frame["market"] = bet.map(type_to_market)
    frame = frame.loc[frame["market"].notna()].copy()

    side = _norm_text_series(frame["side"])
    frame["side_norm"] = side.map({"over": "OVER", "o": "OVER", "under": "UNDER", "u": "UNDER"}).fillna("")
    frame["line"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.loc[frame["side_norm"].ne("") & frame["line"].notna() & frame["line"].gt(0)].copy()

    name_col = next(
        (col for col in ("join_name", "player_name", "player", "name", "full_name") if col in frame.columns),
        None,
    )
    id_col = next(
        (col for col in ("player_id", "gsis_id", "player_gsis_id") if col in frame.columns),
        None,
    )
    if name_col is None and id_col is None:
        raise ProbeError("LINE_PLAYER_IDENTITY_MISSING")
    frame["player_identity"] = (
        frame[id_col].astype("string").fillna("").str.strip()
        if id_col is not None
        else frame[name_col].astype("string").fillna("").str.strip()
    )
    if name_col is not None:
        fallback = frame[name_col].astype("string").fillna("").str.strip()
        frame["player_identity"] = frame["player_identity"].where(frame["player_identity"].ne(""), fallback)
    frame = frame.loc[frame["player_identity"].ne("")].copy()

    source_fields = sorted(str(x) for x in frame.columns)
    results: list[dict] = []
    for market in MARKET_BET_TYPES:
        m = frame.loc[frame["market"].eq(market)].copy()
        if m.empty:
            raise ProbeError(f"NO_2025_LINE_ROWS:{market}")
        weeks = sorted(int(x) for x in m["week"].dropna().unique())
        group_cols = ["week", "market", "player_identity", "book", "line"]
        paired = 0
        unique_groups = 0
        for _, g in m.groupby(group_cols, dropna=False):
            unique_groups += 1
            sides = set(g["side_norm"].astype(str))
            if {"OVER", "UNDER"}.issubset(sides):
                paired += 1
        if paired <= 0:
            raise ProbeError(f"NO_PAIRED_PROP_ROWS:{market}")
        results.append({
            "market": market,
            "source_url": final,
            "raw_sha256": digest(raw),
            "raw_bytes": len(raw),
            "rows_2025": int(len(m)),
            "weeks_2025": weeks,
            "books": sorted(str(x) for x in m["book"].dropna().unique()),
            "unique_player_market_book_line_groups": int(unique_groups),
            "paired_player_market_book_line_groups": int(paired),
            "line_definition": "ACTION_NETWORK_ARCHIVE_LATEST_PER_BOOK_FULL_GAME_PROP",
            "source_fields": source_fields,
            "outcome_columns_used": False,
        })
    return results

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

    lines = probe_line_archive()
    expected, schedule_receipt = schedule_team_weeks()
    inactives = inactive_coverage(expected)

    line_gate = all(
        row["rows_2025"] > 0
        and row["paired_player_market_book_line_groups"] > 0
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
