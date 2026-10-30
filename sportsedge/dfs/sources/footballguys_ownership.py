"""Read-only public Footballguys NFL DFS ownership research intake.

No authentication, market quotes, model blending or betting authority. These
public roster estimates lack DK player IDs, slate identity and a trustworthy
publication clock, so even a successful fetch is *not* model admission.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from argparse import ArgumentParser
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.request import Request, urlopen

from sportsedge.dfs.types import DKPlayer
from sportsedge.nfl_team_aliases import NflTeamAliasError, resolve_team

SOURCE_URL = "https://www.footballguys.com/percent-rostered-projections"
MAX_RAW_BYTES = 2_000_000
_TABLE_POSITIONS = {
    "data-qb": "QB", "data-rb": "RB", "data-wr": "WR",
    "data-te": "TE", "data-td": "DST", "data-dst": "DST",
}
_PERCENT = re.compile(r"^([0-9]+(?:\.[0-9]+)?)%$")


class PublicOwnershipError(ValueError):
    pass


class _OwnershipTable(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.position: str | None = None
        self.cell_parts: list[str] | None = None
        self.cells: list[str] = []
        self.rows: list[dict] = []
        self.seen: set[tuple[str, str]] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            table_id = dict(attrs).get("id")
            self.position = _TABLE_POSITIONS.get(str(table_id or "").lower())
        elif tag == "tr" and self.position is not None:
            self.cells = []
        elif tag == "td" and self.position is not None:
            self.cell_parts = []

    def handle_data(self, data: str) -> None:
        if self.cell_parts is not None:
            self.cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.cell_parts is not None:
            self.cells.append(" ".join("".join(self.cell_parts).split()))
            self.cell_parts = None
        elif tag == "tr" and self.position is not None and self.cells:
            if len(self.cells) != 2:
                raise PublicOwnershipError("FOOTBALLGUYS_ROW_SHAPE_INVALID")
            name, percent = self.cells
            match = _PERCENT.fullmatch(percent)
            if not name or not match:
                raise PublicOwnershipError("FOOTBALLGUYS_ROW_VALUE_INVALID")
            value = float(match.group(1)) / 100.0
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise PublicOwnershipError("FOOTBALLGUYS_OWNERSHIP_INVALID")
            key = (self.position, name.casefold())
            if key in self.seen:
                raise PublicOwnershipError("FOOTBALLGUYS_DUPLICATE_PLAYER")
            self.seen.add(key)
            self.rows.append({"name": name, "position": self.position,
                              "projected_ownership": value})
            self.cells = []
        elif tag == "table":
            self.position = None
            self.cell_parts = None


def parse_public_ownership(raw: bytes, *, received_at: datetime) -> dict:
    """Hash the unchanged response; never substitute its receipt time for publish time."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_RAW_BYTES:
        raise PublicOwnershipError("FOOTBALLGUYS_RAW_INVALID")
    if (not isinstance(received_at, datetime) or received_at.tzinfo is None
            or received_at.utcoffset() is None):
        raise PublicOwnershipError("FOOTBALLGUYS_RECEIPT_TIMEZONE_REQUIRED")
    parser = _OwnershipTable()
    try:
        parser.feed(raw.decode("utf-8", errors="strict"))
        parser.close()
    except UnicodeDecodeError as exc:
        raise PublicOwnershipError("FOOTBALLGUYS_HTML_ENCODING_INVALID") from exc
    if not parser.rows:
        raise PublicOwnershipError("FOOTBALLGUYS_NO_PUBLIC_OWNERSHIP")
    return {
        "schema": "sportsedge.footballguys_ownership_research.v1",
        "source": "FOOTBALLGUYS_PUBLIC_NFL_DFS",
        "source_url": SOURCE_URL,
        "status": "RESEARCH_ONLY_UNVERIFIED",
        "site_publication_time": None,
        "quote_time_status": "UNVERIFIED",
        "slate_id_status": "UNVERIFIED",
        "received_at_utc": received_at.astimezone(timezone.utc).isoformat(),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw),
        "positions_present": sorted({row["position"] for row in parser.rows}),
        "positions_missing": sorted(set(_TABLE_POSITIONS.values()) -
                                    {row["position"] for row in parser.rows}),
        "collection_method": "provided_html",
        "players": parser.rows,
    }


def fetch_public_ownership(*, clock=None) -> tuple[dict, bytes]:
    """Fetch once from the public exact URL; no credentials or fallback mirror."""
    request = Request(SOURCE_URL, headers={"User-Agent": "SportsEdge-DFS-research/1.0"})
    with urlopen(request, timeout=20) as response:
        if response.headers.get_content_type() != "text/html":
            raise PublicOwnershipError("FOOTBALLGUYS_NOT_HTML")
        raw = response.read(MAX_RAW_BYTES + 1)
    now = clock() if clock is not None else datetime.now(timezone.utc)
    report = parse_public_ownership(raw, received_at=now)
    report["collection_method"] = "site_fetch"
    return report, raw


def match_public_ownership(report: dict, players: Iterable[DKPlayer]) -> dict:
    """Exact unique player match; DST joins require three-way NFL team agreement."""
    if (report.get("status") != "RESEARCH_ONLY_UNVERIFIED"
            or report.get("schema") != "sportsedge.footballguys_ownership_research.v1"):
        raise PublicOwnershipError("FOOTBALLGUYS_RESEARCH_STATUS_REQUIRED")
    by_key: dict[tuple[str, str], list[DKPlayer]] = {}
    defenses: list[DKPlayer] = []
    for player in players:
        for position in player.positions:
            by_key.setdefault((position, player.name.casefold()), []).append(player)
        if player.is_defense:
            by_key.setdefault(("DST", player.name.casefold()), []).append(player)
            defenses.append(player)
    matches, blocked = [], []
    used_ids: set[str] = set()
    for row in report.get("players") or []:
        value = row.get("projected_ownership")
        if (isinstance(value, bool) or not isinstance(value, (float, int))
                or not math.isfinite(value) or not 0 <= value <= 1):
            raise PublicOwnershipError("FOOTBALLGUYS_MATCH_OWNERSHIP_INVALID")
        key = (row["position"], row["name"].casefold())
        if row["position"] == "DST":
            # Team nicknames in DK's upload ("Vikings") differ from the
            # Footballguys full name ("Minnesota Vikings"). A single
            # canonical team must be independently named by all three fields.
            try:
                source_team = resolve_team(row["name"])
            except NflTeamAliasError:
                source_team = None
            candidates = {}
            if source_team is not None:
                for player in defenses:
                    try:
                        if (resolve_team(player.team) == source_team
                                and resolve_team(player.name) == source_team):
                            candidates[player.player_id] = player
                    except NflTeamAliasError:
                        continue
        else:
            candidates = {p.player_id: p for p in by_key.get(key, [])}
        if len(candidates) == 1:
            candidate = next(iter(candidates.values()))
            if candidate.player_id in used_ids:
                blocked.append({"name": row["name"], "position": row["position"],
                                "reason": "DUPLICATE_DK_ID"})
            else:
                used_ids.add(candidate.player_id)
                matches.append({"dk_player_id": candidate.player_id,
                                "name": row["name"], "position": row["position"],
                                "projected_ownership": value})
        elif len(candidates) > 1:
            blocked.append({"name": row["name"], "position": row["position"],
                            "reason": "AMBIGUOUS_DK_ID"})
    return {"status": "RESEARCH_ONLY_UNVERIFIED", "matched": matches,
            "blocked": blocked, "source_sha256": report["raw_sha256"]}


def main() -> None:
    """Explicit audit capture. Both raw HTML and derived JSON are preserved."""
    parser = ArgumentParser(description="Capture public Footballguys NFL DFS ownership as research")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="Fetch the exact public URL once")
    mode.add_argument("--input-html", type=Path, help="Parse supplied HTML (not a live capture)")
    parser.add_argument("--output", required=True, type=Path, help="New evidence JSON path")
    parser.add_argument("--raw-output", required=True, type=Path, help="New unmodified HTML path")
    args = parser.parse_args()
    if args.output.resolve() == args.raw_output.resolve():
        parser.error("--output and --raw-output must be different files")
    if args.output.exists() or args.raw_output.exists():
        parser.error("Refusing to replace existing ownership evidence; select new paths")
    if args.live:
        report, raw = fetch_public_ownership()
    else:
        raw = args.input_html.read_bytes()
        report = parse_public_ownership(raw, received_at=datetime.now(timezone.utc))
    with args.raw_output.open("xb") as stream:
        stream.write(raw)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(f"research-only: {len(report['players'])} public rows, "
          f"sha256={report['raw_sha256']}; publication clock and slate unverified")


if __name__ == "__main__":
    main()
