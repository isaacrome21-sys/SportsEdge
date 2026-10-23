"""Fail-closed MLB moneyline adapter for rendered DraftKings board snapshots.

This module performs no network access.  It binds a rendered-page snapshot to
the official MLB schedule and emits the immutable quote shape consumed by the
existing forward-evidence lane.  It grants no promotion or betting authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .dk_rendered_page_fetcher import SOURCE_CLASS as RENDERED_SOURCE_CLASS
from .mlb_source import GameSnapshot, parse_game_start

SOURCE_CLASS = "DRAFTKINGS_RENDERED_PAGE_V1"
EVIDENCE_DISPOSITION = "FORWARD_CAPTURE_PARTIAL"
CAPTURE_WINDOWS = (("T60", 45.0, 75.0), ("T30", 20.0, 45.0), ("T10", 0.0, 20.0))


class RenderedMLBCaptureBlocked(RuntimeError):
    def __init__(self, reason: str, detail: Any = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


_TEAM_ALIASES = {
    "ari diamondbacks": "Arizona Diamondbacks",
    "arizona diamondbacks": "Arizona Diamondbacks",
    "ath athletics": "Athletics",
    "oak athletics": "Athletics",
    "athletics": "Athletics",
    "atl braves": "Atlanta Braves",
    "atlanta braves": "Atlanta Braves",
    "bal orioles": "Baltimore Orioles",
    "baltimore orioles": "Baltimore Orioles",
    "bos red sox": "Boston Red Sox",
    "boston red sox": "Boston Red Sox",
    "chc cubs": "Chicago Cubs",
    "chicago cubs": "Chicago Cubs",
    "chw white sox": "Chicago White Sox",
    "chicago white sox": "Chicago White Sox",
    "cin reds": "Cincinnati Reds",
    "cincinnati reds": "Cincinnati Reds",
    "cle guardians": "Cleveland Guardians",
    "cleveland guardians": "Cleveland Guardians",
    "col rockies": "Colorado Rockies",
    "colorado rockies": "Colorado Rockies",
    "det tigers": "Detroit Tigers",
    "detroit tigers": "Detroit Tigers",
    "hou astros": "Houston Astros",
    "houston astros": "Houston Astros",
    "kc royals": "Kansas City Royals",
    "kansas city royals": "Kansas City Royals",
    "laa angels": "Los Angeles Angels",
    "los angeles angels": "Los Angeles Angels",
    "lad dodgers": "Los Angeles Dodgers",
    "los angeles dodgers": "Los Angeles Dodgers",
    "mia marlins": "Miami Marlins",
    "miami marlins": "Miami Marlins",
    "mil brewers": "Milwaukee Brewers",
    "milwaukee brewers": "Milwaukee Brewers",
    "min twins": "Minnesota Twins",
    "minnesota twins": "Minnesota Twins",
    "nym mets": "New York Mets",
    "new york mets": "New York Mets",
    "nyy yankees": "New York Yankees",
    "new york yankees": "New York Yankees",
    "phi phillies": "Philadelphia Phillies",
    "philadelphia phillies": "Philadelphia Phillies",
    "pit pirates": "Pittsburgh Pirates",
    "pittsburgh pirates": "Pittsburgh Pirates",
    "sd padres": "San Diego Padres",
    "san diego padres": "San Diego Padres",
    "sea mariners": "Seattle Mariners",
    "seattle mariners": "Seattle Mariners",
    "sf giants": "San Francisco Giants",
    "san francisco giants": "San Francisco Giants",
    "stl cardinals": "St. Louis Cardinals",
    "st louis cardinals": "St. Louis Cardinals",
    "tb rays": "Tampa Bay Rays",
    "tampa bay rays": "Tampa Bay Rays",
    "tex rangers": "Texas Rangers",
    "texas rangers": "Texas Rangers",
    "tor blue jays": "Toronto Blue Jays",
    "toronto blue jays": "Toronto Blue Jays",
    "wsh nationals": "Washington Nationals",
    "washington nationals": "Washington Nationals",
}


def _norm(value: Any) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", str(value or "").lower())
    return " ".join(text.split())


def canonical_team(value: Any) -> str:
    team = _TEAM_ALIASES.get(_norm(value))
    if team is None:
        raise RenderedMLBCaptureBlocked("TEAM_NAME_UNMAPPED", str(value or ""))
    return team


def _ts(value: Any, name: str) -> datetime:
    try:
        out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise RenderedMLBCaptureBlocked("TIMESTAMP_INVALID", name) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise RenderedMLBCaptureBlocked("TIMESTAMP_TIMEZONE_REQUIRED", name)
    return out.astimezone(timezone.utc)


def window_for(minutes_before: float) -> str | None:
    for label, low, high in CAPTURE_WINDOWS:
        if low < minutes_before <= high:
            return label
    return None


def _price(row: Mapping[str, Any]) -> int:
    value = row.get("price_american")
    if isinstance(value, bool):
        raise RenderedMLBCaptureBlocked("PRICE_INVALID")
    try:
        price = int(value)
    except (TypeError, ValueError) as exc:
        raise RenderedMLBCaptureBlocked("PRICE_INVALID") from exc
    if price != value or not 100 <= abs(price) <= 50000:
        raise RenderedMLBCaptureBlocked("PRICE_INVALID")
    return price


def _schedule_match(
    *, away: str, home: str, schedule: Iterable[GameSnapshot], observed: datetime
) -> tuple[GameSnapshot, float, str]:
    candidates: list[tuple[GameSnapshot, float, str]] = []
    for game in schedule:
        if game.away_name != away or game.home_name != home or game.status != "Preview":
            continue
        start = parse_game_start(game.game_date)
        minutes = (start - observed).total_seconds() / 60.0
        window = window_for(minutes)
        if window is not None:
            candidates.append((game, minutes, window))
    if not candidates:
        raise RenderedMLBCaptureBlocked(
            "OFFICIAL_SCHEDULE_MATCH_NOT_IN_CAPTURE_WINDOW", {"away": away, "home": home}
        )
    if len(candidates) != 1:
        raise RenderedMLBCaptureBlocked(
            "OFFICIAL_SCHEDULE_MATCH_AMBIGUOUS",
            {"away": away, "home": home, "game_pks": [g.game_pk for g, _, _ in candidates]},
        )
    return candidates[0]


def adapt_rendered_moneylines(
    board: Mapping[str, Any],
    schedule: Iterable[GameSnapshot],
    *,
    model_artifact_sha256: str,
) -> list[dict[str, Any]]:
    if board.get("source_class") != RENDERED_SOURCE_CLASS:
        raise RenderedMLBCaptureBlocked("RENDERED_SOURCE_CLASS_REQUIRED")
    if board.get("page_status") != "OK":
        raise RenderedMLBCaptureBlocked("RENDERED_PAGE_NOT_OK", board.get("page_status"))
    digest = str(board.get("page_html_sha256") or "").lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise RenderedMLBCaptureBlocked("PAGE_HTML_SHA256_INVALID")
    artifact = str(model_artifact_sha256 or "").lower()
    if len(artifact) != 64 or any(ch not in "0123456789abcdef" for ch in artifact):
        raise RenderedMLBCaptureBlocked("MODEL_ARTIFACT_SHA256_INVALID")
    observed = _ts(board.get("observed_at_utc"), "observed_at_utc")
    if board.get("card_refusals"):
        raise RenderedMLBCaptureBlocked("RENDERED_CARD_REFUSED", board.get("card_refusals"))
    if any(row.get("market") == "h2h" for row in board.get("refused_rows") or []):
        raise RenderedMLBCaptureBlocked("RENDERED_MONEYLINE_SIDE_REFUSED")

    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in board.get("rows") or []:
        if row.get("market") == "h2h":
            groups.setdefault(str(row.get("provider_event_id") or ""), []).append(row)
    if not groups:
        raise RenderedMLBCaptureBlocked("RENDERED_MONEYLINE_EMPTY")

    output: list[dict[str, Any]] = []
    for event_id, rows in sorted(groups.items()):
        if not event_id or len(rows) != 2 or any(r.get("status") != "OK" for r in rows):
            raise RenderedMLBCaptureBlocked("RENDERED_MONEYLINE_NOT_EXACTLY_TWO_SIDED", event_id)
        homes = {canonical_team(r.get("home_team")) for r in rows}
        aways = {canonical_team(r.get("away_team")) for r in rows}
        if len(homes) != 1 or len(aways) != 1:
            raise RenderedMLBCaptureBlocked("RENDERED_EVENT_TEAM_IDENTITY_CONFLICT", event_id)
        home, away = next(iter(homes)), next(iter(aways))
        sides = {canonical_team(r.get("outcome")): _price(r) for r in rows}
        if set(sides) != {away, home}:
            raise RenderedMLBCaptureBlocked("RENDERED_MONEYLINE_OUTCOME_IDENTITY_CONFLICT", event_id)
        game, minutes, window = _schedule_match(
            away=away, home=home, schedule=schedule, observed=observed
        )
        start = parse_game_start(game.game_date)
        output.append({
            "evidence_disposition": EVIDENCE_DISPOSITION,
            "promotion_authority": False,
            "source_class": SOURCE_CLASS,
            "sportsbook": "draftkings",
            "provider": "DRAFTKINGS_RENDERED_PAGE",
            "sport_key": "baseball_mlb",
            "provider_event_id": event_id,
            "game_pk": game.game_pk,
            "home_team": home,
            "away_team": away,
            "scheduled_start_utc": start.isoformat(),
            "observed_at_utc": observed.isoformat(),
            "capture_window": window,
            "minutes_before_start": round(minutes, 2),
            "pit_basis": "RENDERED_DOM_OBSERVED_AT_UTC_VS_MLB_STATSAPI_SCHEDULE",
            "quote_side_skew_seconds": 0,
            "quote_synchronization": "SINGLE_DOM_SNAPSHOT_BOTH_SIDES",
            "quote_synchronization_note": (
                "Structural same-snapshot synchronization; not independent quote timestamps."
            ),
            "book_last_update": None,
            "provider_quote_timestamp_available": False,
            "moneyline": {
                "status": "OK",
                "home_price_american": sides[home],
                "away_price_american": sides[away],
            },
            "model_artifact_sha256": artifact,
            "raw_sha256": digest,
            "source_uri": board.get("source_uri"),
            "final_url": board.get("final_url"),
            "capture_transport": "HEADED_RENDERED_PAGE",
        })
    return output


def persist_create_only(rows: Iterable[Mapping[str, Any]], output_dir: str | Path) -> list[str]:
    written: list[str] = []
    for source in rows:
        row = dict(source)
        observed = _ts(row.get("observed_at_utc"), "observed_at_utc")
        digest = str(row.get("raw_sha256") or "")
        game_pk = int(row.get("game_pk"))
        key = (
            f"{game_pk}__{row.get('capture_window')}__"
            f"{observed.strftime('%Y%m%dT%H%M%SZ')}__{digest[:16]}"
        )
        row["capture_observation_id"] = key
        payload = (json.dumps(row, indent=2, sort_keys=True) + "\n").encode("utf-8")
        path = Path(output_dir) / observed.date().isoformat() / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != payload:
                raise RenderedMLBCaptureBlocked("IMMUTABLE_CAPTURE_COLLISION", str(path))
            continue
        try:
            with path.open("xb") as handle:
                handle.write(payload)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise RenderedMLBCaptureBlocked("IMMUTABLE_CAPTURE_COLLISION", str(path))
            continue
        written.append(str(path))
    return written
