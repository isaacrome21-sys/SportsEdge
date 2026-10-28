"""Sports Reference HTML tables (Pro-Football-Reference / Basketball-Reference).

These sites publish NO CSV/JSON endpoint; their pages are server-
rendered HTML tables, which makes them genuinely machine-readable
without any account. Verified live 2026-10-27: PFR 2026 season page
(534,802 bytes, sha256 73fe6f5c3c90f41889d9990d03896cb04b9ab3aa47080f02117b6a6a69d1008e)
carries id="team_stats"; BBR 2026-27 per-game page (1,061,985 bytes,
sha256 4664a1d50660e8e7d8062313f4da5a0a5a69f7bc6207ac7c14b755d5e62b0c34)
carries id="per_game_stats".

BOT-POLICY DISCIPLINE (Sports Reference publishes one, and this module
is written to it): keep request rates far below their stated ceiling
(their guidance caps automated requests at 10/minute; this layer's
intended use is a handful of single pulls per day, one page per call,
no crawling, no pagination chasing). If a pull ever returns 403/429,
the fetcher fails closed for that call and callers must NOT retry,
rotate agents, or otherwise evade -- a block is a stop signal, and the
surface degrades to browse-only for the owner.

POINT-IN-TIME NOTE: Reference pages are season-to-date as of the pull
and carry no as-of stamp of their own; receipts stamp retrieval time +
sha256, and the factoring spec requires pre-game archived pulls.

RESEARCH-ONLY: labeled context only.
"""
from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from typing import Any

from .common import Opener, fetch_bytes, receipt_of, to_float, to_int

PFR = "https://www.pro-football-reference.com"
BBR = "https://www.basketball-reference.com"


class _TableExtractor(HTMLParser):
    """Collect rows of one <table id=...> as lists of cell texts.

    Also captures each cell's data-stat attribute (Sports Reference's
    stable column key) so headers survive their display relabeling.
    """

    def __init__(self, table_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.table_id = table_id
        self.in_table = False
        self.depth = 0
        self.rows: list[list[tuple[str, str | None]]] = []
        self._row: list[tuple[str, str | None]] | None = None
        self._cell: list[str] | None = None
        self._cell_stat: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "table":
            if self.in_table:
                self.depth += 1
            elif attr.get("id") == self.table_id:
                self.in_table = True
                self.depth = 1
        if not self.in_table:
            return
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
            self._cell_stat = attr.get("data-stat")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.in_table:
            return
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append((" ".join("".join(self._cell).split()), self._cell_stat))
            self._cell = None
            self._cell_stat = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag == "table":
            self.depth -= 1
            if self.depth == 0:
                self.in_table = False


def _table_fragment(html_text: str, table_id: str) -> str | None:
    """The named table's own markup, sliced out of the page bytes.

    Sports Reference serves several tables wrapped in HTML comments
    (the page's JS unwraps them in a browser). The bytes are publicly
    served either way, so the fetcher slices the table's markup
    directly -- no extra requests, no browser emulation. Nested
    tables inside cells do not occur in these stats tables.
    """
    id_pos = html_text.find(f'id="{table_id}"')
    if id_pos == -1:
        return None
    start = html_text.rfind("<table", 0, id_pos)
    end = html_text.find("</table>", id_pos)
    if start == -1 or end == -1:
        return None
    return html_text[start : end + len("</table>")]


def extract_table(html_text: str, table_id: str) -> list[dict[str, str]]:
    """Rows of the named table as dicts keyed by data-stat (or header)."""
    fragment = _table_fragment(html_text, table_id)
    if fragment is None:
        return []
    parser = _TableExtractor(table_id)
    parser.feed(fragment)
    if not parser.rows:
        return []
    # Sports Reference tables may carry a grouping over-header (fewer,
    # colspan-merged cells) above the real column header. The real
    # header is a row of the modal length whose cells carry data-stat
    # keys; rows before it are preamble and are skipped.
    modal_length = Counter(len(row) for row in parser.rows).most_common(1)[0][0]
    header_index = next(
        (
            index
            for index, row in enumerate(parser.rows)
            if len(row) == modal_length and any(stat for _, stat in row)
        ),
        None,
    )
    if header_index is None:
        return []
    header = parser.rows[header_index]
    keys = [stat or text for text, stat in header]
    header_texts = [text for text, _ in header]
    out: list[dict[str, str]] = []
    for row in parser.rows[header_index + 1 :]:
        if len(row) != modal_length:
            continue
        # Sports Reference repeats header rows mid-table; drop them.
        if [text for text, _ in row] == header_texts:
            continue
        out.append({keys[i]: row[i][0] for i in range(len(keys))})
    return out


def _fetch_table(url: str, table_id: str, opener: Opener | None) -> dict[str, Any]:
    result = fetch_bytes(url, opener=opener)
    if result["status"] != "OK":
        return result
    try:
        text = result["body"].decode("utf-8", errors="strict")
    except Exception:
        return {"status": "MISSING", "reason": "SCHEMA_DRIFT", "receipt": receipt_of(result)}
    rows = extract_table(text, table_id)
    if not rows:
        return {"status": "MISSING", "reason": "TABLE_NOT_FOUND", "receipt": receipt_of(result)}
    return {"status": "OK", "receipt": receipt_of(result), "rows": rows}


def pfr_team_stats(*, season: int, opener: Opener | None = None) -> dict[str, Any]:
    """PFR team season table (standings-adjacent team stats) for one year."""
    fetched = _fetch_table(f"{PFR}/years/{season}/", "team_stats", opener)
    if fetched["status"] != "OK":
        return fetched
    teams: dict[str, dict[str, Any]] = {}
    for row in fetched["rows"]:
        name = row.get("team") or row.get("team_name_abbr") or row.get("Tm") or ""
        if not name or name in ("Avg Team", "League Total", "Avg Tm/G"):
            continue
        teams[name] = {
            key: (to_float(value) if value not in ("", None) else None)
            for key, value in row.items()
            if key not in ("team", "Tm")
        }
        teams[name]["games"] = to_int(row.get("g") or row.get("G"))
    return {
        "status": "OK",
        "source": "Pro-Football-Reference season page team_stats table (HTML)",
        "label": "RESEARCH_CONTEXT_ONLY",
        "season": season,
        "receipt": fetched["receipt"],
        "teams": teams,
    }


def bbr_per_game(*, season_end_year: int, opener: Opener | None = None) -> dict[str, Any]:
    """BBR per-game player table for one season (named by ending year).

    One row per player-team stint in the source; multi-team players also
    carry a combined row in the source -- rows are passed through as
    published (team column preserved), never silently merged.
    """
    fetched = _fetch_table(
        f"{BBR}/leagues/NBA_{season_end_year}_per_game.html", "per_game_stats", opener
    )
    if fetched["status"] != "OK":
        return fetched
    players: list[dict[str, Any]] = []
    for row in fetched["rows"]:
        name = row.get("name_display") or row.get("player") or row.get("Player") or ""
        if not name:
            continue
        entry: dict[str, Any] = {
            "player": name,
            "team": row.get("team_name_abbr") or row.get("team_id") or row.get("Tm"),
        }
        for key, value in row.items():
            if key in ("name_display", "player", "Player", "team_name_abbr", "team_id", "Tm",
                       "ranker", "awards", "pos", "Pos"):
                if key in ("pos", "Pos"):
                    entry["position"] = value
                continue
            entry[key] = to_float(value)
        players.append(entry)
    return {
        "status": "OK",
        "source": "Basketball-Reference per-game player table (HTML)",
        "label": "RESEARCH_CONTEXT_ONLY",
        "season_end_year": season_end_year,
        "receipt": fetched["receipt"],
        "players": players,
    }
