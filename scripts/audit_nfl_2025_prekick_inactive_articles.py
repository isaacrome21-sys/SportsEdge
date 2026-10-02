#!/usr/bin/env python3
"""Audit official NFL.com 2025 inactive articles with pre-kick timestamp gating.

Source-only research prerequisite for NFL prop V1. This script never loads player
outcomes, model code, calibration, Brier scores, or the fitted prop artifact.

A game is admitted only when:
1) the official NFL.com article exposes a parseable Published/Updated timestamp;
2) the article's final timestamp (Updated if present, otherwise Published) is
   at or before that game's listed kickoff;
3) exactly two recognized NFL team inactive sections follow that game's WHEN
   marker; and
4) both teams have at least one explicit inactive entry.

Articles updated after one game but before a later game admit only the later
game. Missing/ambiguous timestamps, teams, kickoffs, or inactive lists fail
closed. Historical retrieval is source evidence only, never forward capture.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import requests


NFL_HOST = "https://www.nfl.com"
AMP_HOST = "https://amp.nfl.com"
ET = ZoneInfo("America/New_York")
UA = "SportsEdge-NFL-prop-inactive-source-audit/1.0"
SITEMAPS = (
    "https://www.nfl.com/sitemap/html/articles/2025/9",
    "https://www.nfl.com/sitemap/html/articles/2025/10",
    "https://www.nfl.com/sitemap/html/articles/2025/11",
    "https://www.nfl.com/sitemap/html/articles/2025/12",
    "https://www.nfl.com/sitemap/html/articles/2026/1",
)

TEAM_ALIASES = {
    "49ERS": "SF",
    "BEARS": "CHI",
    "BENGALS": "CIN",
    "BILLS": "BUF",
    "BRONCOS": "DEN",
    "BROWNS": "CLE",
    "BUCCANEERS": "TB",
    "BUCS": "TB",
    "CARDINALS": "ARI",
    "CHARGERS": "LAC",
    "CHIEFS": "KC",
    "COLTS": "IND",
    "COMMANDERS": "WAS",
    "COWBOYS": "DAL",
    "DOLPHINS": "MIA",
    "EAGLES": "PHI",
    "FALCONS": "ATL",
    "GIANTS": "NYG",
    "JAGUARS": "JAX",
    "JETS": "NYJ",
    "LIONS": "DET",
    "PACKERS": "GB",
    "PANTHERS": "CAR",
    "PATRIOTS": "NE",
    "RAIDERS": "LV",
    "RAMS": "LA",
    "RAVENS": "BAL",
    "SAINTS": "NO",
    "SEAHAWKS": "SEA",
    "STEELERS": "PIT",
    "TEXANS": "HOU",
    "TITANS": "TEN",
    "VIKINGS": "MIN",
}
POSITION_PREFIX = re.compile(
    r"^(?:QB|RB|FB|WR|TE|OT|T|OL|OG|G|C|DL|DT|DE|EDGE|NT|LB|OLB|ILB|CB|DB|S|K|P|LS)\s+",
    re.IGNORECASE,
)
WHEN_RE = re.compile(
    r"\bWHEN\s*:\s*(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\s*ET\b",
    re.IGNORECASE,
)
WEEK_RE = re.compile(r"\bweek[\s-]+(\d{1,2})\b", re.IGNORECASE)
PUBLISHED_RE = re.compile(
    r"Published:\s*([A-Z][a-z]{2}\s+\d{2},\s+\d{4}\s+at\s+\d{1,2}:\d{2}\s+[AP]M)",
    re.IGNORECASE,
)
UPDATED_RE = re.compile(
    r"Updated:\s*([A-Z][a-z]{2}\s+\d{2},\s+\d{4}\s+at\s+\d{1,2}:\d{2}\s+[AP]M)",
    re.IGNORECASE,
)


class InactiveArticleAuditError(ValueError):
    pass


@dataclass(frozen=True)
class Token:
    kind: str
    text: str


def _get(url: str, *, timeout: int = 30, attempts: int = 3) -> tuple[bytes, str]:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "text/html,application/xhtml+xml",
                },
                timeout=timeout,
            )
            response.raise_for_status()
            raw = response.content
            if not raw:
                raise InactiveArticleAuditError(f"EMPTY_RESPONSE:{url}")
            return raw, response.url
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(1.0 + attempt)
    raise InactiveArticleAuditError(
        f"HTTP_FETCH_FAILED:{url}:{type(last).__name__}:{last}"
    )


def _article_url(href: str) -> str | None:
    href = str(href or "").strip()
    if not href:
        return None
    absolute = urljoin(NFL_HOST, href)
    parsed = urlparse(absolute)
    if parsed.netloc not in {"www.nfl.com", "nfl.com"}:
        return None
    if not parsed.path.startswith("/news/"):
        return None
    if "inactive" not in parsed.path.lower():
        return None
    slug = parsed.path.rstrip("/")
    return AMP_HOST + slug


def discover_articles() -> tuple[list[str], list[dict[str, Any]]]:
    urls: set[str] = set()
    receipts: list[dict[str, Any]] = []
    for sitemap in SITEMAPS:
        raw, final_url = _get(sitemap)
        receipts.append(
            {
                "url": sitemap,
                "final_url": final_url,
                "bytes": len(raw),
                "sha256": sha256(raw).hexdigest(),
                "retrieved_at": datetime.now().astimezone().isoformat(),
            }
        )
        soup = BeautifulSoup(raw, "html.parser")
        for anchor in soup.find_all("a", href=True):
            url = _article_url(anchor.get("href"))
            if url:
                urls.add(url)
    return sorted(urls), receipts


def _parse_display_stamp(text: str) -> datetime:
    clean = " ".join(text.split())
    dt = datetime.strptime(clean, "%b %d, %Y at %I:%M %p")
    return dt.replace(tzinfo=ET)


def _jsonld_dates(soup: BeautifulSoup) -> tuple[datetime | None, datetime | None]:
    published: datetime | None = None
    modified: datetime | None = None

    def walk(value: Any) -> None:
        nonlocal published, modified
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"datePublished", "dateModified"} and isinstance(item, str):
                    try:
                        parsed = datetime.fromisoformat(item.replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=ET)
                        parsed = parsed.astimezone(ET)
                    except ValueError:
                        parsed = None
                    if key == "datePublished" and parsed is not None:
                        published = published or parsed
                    if key == "dateModified" and parsed is not None:
                        modified = modified or parsed
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            walk(json.loads(tag.string or tag.get_text() or "null"))
        except (json.JSONDecodeError, TypeError):
            continue
    return published, modified


def article_timestamps(soup: BeautifulSoup) -> tuple[datetime, datetime | None]:
    published, modified = _jsonld_dates(soup)
    visible = " ".join(soup.stripped_strings)
    if published is None:
        match = PUBLISHED_RE.search(visible)
        if match:
            published = _parse_display_stamp(match.group(1))
    if modified is None:
        match = UPDATED_RE.search(visible)
        if match:
            modified = _parse_display_stamp(match.group(1))
    if published is None:
        raise InactiveArticleAuditError("ARTICLE_PUBLISHED_TIMESTAMP_MISSING")
    return published.astimezone(ET), modified.astimezone(ET) if modified else None


def _tokens(soup: BeautifulSoup) -> list[Token]:
    out: list[Token] = []
    for tag in soup.find_all(["h2", "h3", "li"]):
        text = " ".join(tag.stripped_strings).strip()
        if not text:
            continue
        out.append(Token(tag.name.lower(), text))
    return out


def _team(text: str) -> str | None:
    normalized = re.sub(r"[^A-Z0-9 ]+", " ", str(text).upper())
    normalized = " ".join(normalized.split())
    return TEAM_ALIASES.get(normalized)


def _inactive_name(text: str) -> str | None:
    value = " ".join(str(text).split()).strip()
    if not value:
        return None
    # Reject metadata/navigation list items.
    upper = value.upper()
    if upper.startswith(("WHERE:", "WHEN:", "TV:", "READ:", "WATCH:")):
        return None
    value = POSITION_PREFIX.sub("", value).strip()
    value = re.sub(
        r"\s*\((?:emergency\s+)?(?:third|3rd)\s+quarterback\)\s*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"\s*\((?:emergency\s+)?(?:third|3rd)\s+QB\)\s*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    if not value or len(value) > 80:
        return None
    return value


def parse_games(
    soup: BeautifulSoup,
    *,
    published: datetime,
    modified: datetime | None,
    source_url: str,
) -> tuple[int | None, list[dict[str, Any]]]:
    title_tag = soup.find("h1")
    title = " ".join(title_tag.stripped_strings) if title_tag else ""
    week_match = WEEK_RE.search(title)
    week = int(week_match.group(1)) if week_match else None
    if week is not None and not 1 <= week <= 18:
        week = None

    cutoff = (modified or published).astimezone(ET)
    game_date = published.astimezone(ET).date()
    tokens = _tokens(soup)
    when_indices = [i for i, token in enumerate(tokens) if token.kind == "li" and WHEN_RE.search(token.text)]
    games: list[dict[str, Any]] = []

    for number, start in enumerate(when_indices):
        stop = when_indices[number + 1] if number + 1 < len(when_indices) else len(tokens)
        segment = tokens[start:stop]
        # Stop before related-content navigation if present.
        for offset, token in enumerate(segment):
            if token.kind == "h2" and "related content" in token.text.lower():
                segment = segment[:offset]
                break

        match = WHEN_RE.search(segment[0].text)
        if match is None:
            continue
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridiem = match.group(3).lower()
        if hour == 12:
            hour = 0
        if meridiem.startswith("p"):
            hour += 12
        kickoff = datetime(
            game_date.year,
            game_date.month,
            game_date.day,
            hour,
            minute,
            tzinfo=ET,
        )

        headings: list[tuple[int, str, str]] = []
        for i, token in enumerate(segment[1:], start=1):
            if token.kind != "h3":
                continue
            team = _team(token.text)
            if team:
                headings.append((i, team, token.text))
            if len(headings) == 2:
                break

        entry: dict[str, Any] = {
            "week": week,
            "article_title": title,
            "source_url": source_url,
            "published_at": published.isoformat(),
            "modified_at": modified.isoformat() if modified else None,
            "article_cutoff_at": cutoff.isoformat(),
            "kickoff_at": kickoff.isoformat(),
            "lead_minutes": (kickoff - cutoff).total_seconds() / 60.0,
            "teams": [],
            "inactive_by_team": {},
            "admissible": False,
            "reason": None,
        }
        if len(headings) != 2:
            entry["reason"] = "TWO_RECOGNIZED_TEAM_SECTIONS_REQUIRED"
            games.append(entry)
            continue

        for h_index, (token_index, team, raw_heading) in enumerate(headings):
            next_index = (
                headings[h_index + 1][0]
                if h_index + 1 < len(headings)
                else len(segment)
            )
            names: list[str] = []
            for token in segment[token_index + 1 : next_index]:
                if token.kind != "li":
                    continue
                name = _inactive_name(token.text)
                if name and name not in names:
                    names.append(name)
            entry["teams"].append(
                {"team": team, "heading": raw_heading, "inactive_count": len(names)}
            )
            entry["inactive_by_team"][team] = names

        if cutoff > kickoff:
            entry["reason"] = "ARTICLE_FINAL_TIMESTAMP_AFTER_KICKOFF"
        elif any(not entry["inactive_by_team"].get(row["team"]) for row in entry["teams"]):
            entry["reason"] = "BOTH_TEAM_INACTIVE_LISTS_REQUIRED"
        else:
            entry["admissible"] = True
            entry["reason"] = "ADMITTED_PREKICK_OFFICIAL_INACTIVE_LIST"
        games.append(entry)

    return week, games


def run(out_path: Path) -> dict[str, Any]:
    urls, sitemap_receipts = discover_articles()
    articles: list[dict[str, Any]] = []
    games: list[dict[str, Any]] = []

    for url in urls:
        article: dict[str, Any] = {
            "url": url,
            "status": "UNREAD",
            "sha256": None,
            "bytes": 0,
            "retrieved_at": None,
        }
        try:
            raw, final_url = _get(url)
            article.update(
                {
                    "status": "FETCHED",
                    "final_url": final_url,
                    "sha256": sha256(raw).hexdigest(),
                    "bytes": len(raw),
                    "retrieved_at": datetime.now().astimezone().isoformat(),
                }
            )
            soup = BeautifulSoup(raw, "html.parser")
            published, modified = article_timestamps(soup)
            week, parsed_games = parse_games(
                soup,
                published=published,
                modified=modified,
                source_url=final_url,
            )
            article.update(
                {
                    "status": "PARSED",
                    "week": week,
                    "published_at": published.isoformat(),
                    "modified_at": modified.isoformat() if modified else None,
                    "n_game_blocks": len(parsed_games),
                    "n_admissible_game_blocks": sum(bool(g["admissible"]) for g in parsed_games),
                }
            )
            games.extend(parsed_games)
        except Exception as exc:
            article.update(
                {
                    "status": f"ERROR:{type(exc).__name__}",
                    "error": str(exc),
                }
            )
        articles.append(article)

    # Prevent duplicate game admission from multiple official articles. We do
    # not guess a winner; duplicate canonical team/date identities fail closed.
    admitted = [g for g in games if g["admissible"]]
    identity_counts: dict[tuple[str, str, str], int] = {}
    for game in admitted:
        teams = sorted(row["team"] for row in game["teams"])
        if len(teams) != 2:
            continue
        identity = (game["kickoff_at"][:10], teams[0], teams[1])
        identity_counts[identity] = identity_counts.get(identity, 0) + 1
    duplicates = {key for key, count in identity_counts.items() if count > 1}
    if duplicates:
        for game in games:
            if not game["admissible"]:
                continue
            teams = sorted(row["team"] for row in game["teams"])
            identity = (game["kickoff_at"][:10], teams[0], teams[1])
            if identity in duplicates:
                game["admissible"] = False
                game["reason"] = "DUPLICATE_OFFICIAL_ARTICLE_GAME_IDENTITY_FAIL_CLOSED"

    admitted = [g for g in games if g["admissible"]]
    report = {
        "schema": "SPORTSEDGE_NFL_PROP_V1_PREKICK_INACTIVE_ARTICLE_AUDIT_V1",
        "status": "SOURCE_AUDIT_ONLY_NO_2025_MODEL_SCORING",
        "season": 2025,
        "season_type": "REG",
        "source": "NFL.com official inactive articles",
        "sitemaps": sitemap_receipts,
        "n_article_urls_discovered": len(urls),
        "n_articles_parsed": sum(a["status"] == "PARSED" for a in articles),
        "n_game_blocks": len(games),
        "n_admissible_games": len(admitted),
        "n_admissible_inactive_player_entries": sum(
            sum(len(names) for names in game["inactive_by_team"].values())
            for game in admitted
        ),
        "rejection_counts": {
            reason: sum(g["reason"] == reason for g in games)
            for reason in sorted({str(g["reason"]) for g in games if not g["admissible"]})
        },
        "articles": articles,
        "games": games,
        "admitted_games": admitted,
        "interpretation": {
            "official_source": True,
            "timestamp_rule": "FINAL_ARTICLE_TIMESTAMP_AT_OR_BEFORE_GAME_KICKOFF",
            "updated_overrides_published": True,
            "both_team_lists_required": True,
            "missing_or_ambiguous_evidence_fails_closed": True,
            "historical_retrieval_is_not_forward_capture": True,
            "may_gate_research_validation_population_only": True,
        },
        "authority": {
            "source_audit_only": True,
            "model_scoring": False,
            "validation_window_spent": False,
            "creates_model_p": False,
            "truth_gate": False,
            "official": False,
            "promotion": False,
            "staking": False,
            "backfill": False,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        "NFL_PROP_V1_PREKICK_INACTIVE_ARTICLES="
        + json.dumps(
            {
                "n_article_urls_discovered": report["n_article_urls_discovered"],
                "n_articles_parsed": report["n_articles_parsed"],
                "n_game_blocks": report["n_game_blocks"],
                "n_admissible_games": report["n_admissible_games"],
                "n_admissible_inactive_player_entries": report[
                    "n_admissible_inactive_player_entries"
                ],
                "rejection_counts": report["rejection_counts"],
                "validation_window_spent": False,
            },
            sort_keys=True,
        )
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=(
            "artifacts/nfl_prop_v1_source_audit/"
            "prekick_inactive_article_audit.json"
        ),
    )
    args = parser.parse_args()
    run(Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
