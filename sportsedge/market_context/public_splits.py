"""Public betting split market context for football.

This module is intentionally isolated from predictive features and Truth Gate semantics.
It captures source-attributed handle/money percentages, ticket/bet percentages, and
quoted lines for later market-context analysis. It must never alter Model_P.

V1 uses the public VSiN DraftKings betting-splits table as the automatic source.
Network transport is injectable and parser failures are fail-closed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from math import isfinite
import re
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

PUBLIC_SPLITS_CONTRACT = "FOOTBALL_PUBLIC_SPLITS_V1"
VSIN_CFB_DK_URL = "https://data.vsin.com/betting-splits/?source=DK&sport=CFB"
SUPPORTED_MARKETS = ("SPREAD", "TOTAL", "MONEYLINE")


class PublicSplitsError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _utc_dt(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise PublicSplitsError(f"{name}:TIMESTAMP_REQUIRED")
        try:
            out = datetime.fromisoformat(text)
        except ValueError as exc:
            raise PublicSplitsError(f"{name}:ISO8601_REQUIRED") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise PublicSplitsError(f"{name}:TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise PublicSplitsError(f"{name}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PublicSplitsError(f"{name}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise PublicSplitsError(f"{name}:FINITE_REQUIRED")
    return out


def _pct(value: Any, name: str) -> float:
    text = str(value or "").strip().replace("↑", "").replace("↓", "")
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*%", text)
    if not match:
        raise PublicSplitsError(f"{name}:PERCENT_REQUIRED")
    out = _finite(match.group(1), name)
    if not 0.0 <= out <= 100.0:
        raise PublicSplitsError(f"{name}:PERCENT_RANGE")
    return out


def _line(value: Any, name: str) -> float:
    text = str(value or "").strip().replace("↑", "").replace("↓", "").replace("−", "-")
    match = re.search(r"(?<!\d)([+-]?\d+(?:\.\d+)?)", text)
    if not match:
        raise PublicSplitsError(f"{name}:LINE_REQUIRED")
    return _finite(match.group(1), name)


def _team_name(value: Any) -> str:
    text = " ".join(str(value or "").replace("\xa0", " ").split())
    text = re.sub(r"^[↺↻⟳\s]+", "", text)
    text = re.sub(r"^\d+\s+", "", text)
    text = re.sub(r"^(Compare splits|View graded results)\s*", "", text, flags=re.I)
    if not text or not re.search(r"[A-Za-z]", text):
        raise PublicSplitsError("VSIN_TEAM_IDENTITY_REQUIRED")
    return text


def _implied_american(odds: float) -> float:
    if odds == 0:
        raise PublicSplitsError("MONEYLINE_ZERO_FORBIDDEN")
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return (-odds) / ((-odds) + 100.0)


@dataclass(frozen=True)
class PublicSplitObservation:
    source: str
    source_book: str
    sport: str
    captured_at: str
    source_url: str
    away_team: str
    home_team: str
    market: str
    side: str
    line: float
    money_pct: float
    ticket_pct: float
    contract: str = PUBLIC_SPLITS_CONTRACT

    def __post_init__(self) -> None:
        if self.market not in SUPPORTED_MARKETS:
            raise PublicSplitsError("PUBLIC_SPLIT_MARKET_UNSUPPORTED")
        _utc_dt(self.captured_at, "captured_at")
        _finite(self.line, "line")
        for name, value in (("money_pct", self.money_pct), ("ticket_pct", self.ticket_pct)):
            v = _finite(value, name)
            if not 0.0 <= v <= 100.0:
                raise PublicSplitsError(f"{name}:PERCENT_RANGE")
        if not self.away_team or not self.home_team or not self.side:
            raise PublicSplitsError("PUBLIC_SPLIT_IDENTITY_REQUIRED")

    @property
    def money_ticket_gap_pp(self) -> float:
        return float(self.money_pct - self.ticket_pct)

    @property
    def key(self) -> tuple[str, str, str, str, str]:
        return (self.source, self.away_team, self.home_team, self.market, self.side)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["money_ticket_gap_pp"] = self.money_ticket_gap_pp
        return out


@dataclass(frozen=True)
class PublicSplitSnapshot:
    source: str
    source_book: str
    sport: str
    captured_at: str
    source_url: str
    observations: tuple[PublicSplitObservation, ...]
    state: str = "OK"
    notes: tuple[str, ...] = ()
    contract: str = PUBLIC_SPLITS_CONTRACT

    def __post_init__(self) -> None:
        _utc_dt(self.captured_at, "captured_at")
        if self.state not in {"OK", "NO_PUBLIC_SPLIT_DATA"}:
            raise PublicSplitsError("PUBLIC_SPLIT_SNAPSHOT_STATE_INVALID")
        if self.state == "OK" and not self.observations:
            raise PublicSplitsError("PUBLIC_SPLIT_OBSERVATIONS_REQUIRED")
        if self.state == "NO_PUBLIC_SPLIT_DATA" and self.observations:
            raise PublicSplitsError("NO_DATA_STATE_MUST_BE_EMPTY")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_book": self.source_book,
            "sport": self.sport,
            "captured_at": self.captured_at,
            "source_url": self.source_url,
            "state": self.state,
            "contract": self.contract,
            "observations": [x.to_dict() for x in self.observations],
            "notes": list(self.notes),
        }

    def content_hash(self) -> str:
        return sha256(_canonical_bytes(self.to_dict())).hexdigest()


class _TableRows(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            text = " ".join(data.split())
            if text:
                self._cell.append(text)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def _vsin_team_row(cells: list[str]) -> dict[str, Any] | None:
    pct_indices = [i for i, cell in enumerate(cells) if re.search(r"\d+(?:\.\d+)?\s*%", cell)]
    if len(pct_indices) != 6:
        return None
    p0, p1, p2, p3, p4, p5 = pct_indices
    if not (p1 == p0 + 1 and p3 == p2 + 1 and p5 == p4 + 1):
        return None
    team_i = p0 - 2
    spread_i = p0 - 1
    total_i = p1 + 1
    ml_i = p3 + 1
    if min(team_i, spread_i) < 0 or max(total_i, ml_i, p5) >= len(cells):
        return None
    try:
        return {
            "team": _team_name(cells[team_i]),
            "spread": _line(cells[spread_i], "vsin.spread"),
            "spread_money": _pct(cells[p0], "vsin.spread_handle"),
            "spread_tickets": _pct(cells[p1], "vsin.spread_bets"),
            "total": _line(cells[total_i], "vsin.total"),
            "total_money": _pct(cells[p2], "vsin.total_handle"),
            "total_tickets": _pct(cells[p3], "vsin.total_bets"),
            "moneyline": _line(cells[ml_i], "vsin.moneyline"),
            "ml_money": _pct(cells[p4], "vsin.ml_handle"),
            "ml_tickets": _pct(cells[p5], "vsin.ml_bets"),
        }
    except PublicSplitsError:
        return None


def _complement_ok(a: float, b: float, *, tolerance_pp: float = 2.1) -> bool:
    return abs((a + b) - 100.0) <= tolerance_pp


def parse_vsin_html(
    html: str,
    *,
    captured_at: datetime | str,
    source_url: str = VSIN_CFB_DK_URL,
    sport: str = "CFB",
) -> PublicSplitSnapshot:
    stamp = _utc_dt(captured_at, "captured_at").isoformat()
    parser = _TableRows()
    parser.feed(str(html or ""))
    team_rows = [parsed for row in parser.rows if (parsed := _vsin_team_row(row)) is not None]
    if not team_rows:
        return PublicSplitSnapshot(
            source="VSIN_DK",
            source_book="DraftKings",
            sport=sport,
            captured_at=stamp,
            source_url=source_url,
            observations=(),
            state="NO_PUBLIC_SPLIT_DATA",
            notes=("NO_PARSEABLE_CFB_SPLIT_ROWS",),
        )
    if len(team_rows) % 2:
        raise PublicSplitsError("VSIN_GAME_ROW_PAIRING_FAILED")

    observations: list[PublicSplitObservation] = []
    for index in range(0, len(team_rows), 2):
        away = team_rows[index]
        home = team_rows[index + 1]
        away_team, home_team = away["team"], home["team"]
        for prefix in ("spread", "total", "ml"):
            if not _complement_ok(away[f"{prefix}_money"], home[f"{prefix}_money"]):
                raise PublicSplitsError(f"VSIN_{prefix.upper()}_HANDLE_COMPLEMENT_INVALID")
            if not _complement_ok(away[f"{prefix}_tickets"], home[f"{prefix}_tickets"]):
                raise PublicSplitsError(f"VSIN_{prefix.upper()}_BET_COMPLEMENT_INVALID")
        if abs(away["total"] - home["total"]) > 1e-9:
            raise PublicSplitsError("VSIN_TOTAL_LINE_PAIR_MISMATCH")

        specs = (
            ("SPREAD", away_team, away["spread"], away["spread_money"], away["spread_tickets"]),
            ("SPREAD", home_team, home["spread"], home["spread_money"], home["spread_tickets"]),
            ("TOTAL", "OVER", away["total"], away["total_money"], away["total_tickets"]),
            ("TOTAL", "UNDER", home["total"], home["total_money"], home["total_tickets"]),
            ("MONEYLINE", away_team, away["moneyline"], away["ml_money"], away["ml_tickets"]),
            ("MONEYLINE", home_team, home["moneyline"], home["ml_money"], home["ml_tickets"]),
        )
        for market, side, line, money, tickets in specs:
            observations.append(PublicSplitObservation(
                source="VSIN_DK",
                source_book="DraftKings",
                sport=sport,
                captured_at=stamp,
                source_url=source_url,
                away_team=away_team,
                home_team=home_team,
                market=market,
                side=side,
                line=float(line),
                money_pct=float(money),
                ticket_pct=float(tickets),
            ))

    return PublicSplitSnapshot(
        source="VSIN_DK",
        source_book="DraftKings",
        sport=sport,
        captured_at=stamp,
        source_url=source_url,
        observations=tuple(observations),
    )


def _fetch_text(url: str, *, opener: Callable = urlopen, timeout: int = 20) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "SportsEdge/1.0 public-market-context",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read()
    except Exception as exc:
        raise PublicSplitsError(f"PUBLIC_SPLITS_FETCH_FAILED:{type(exc).__name__}:{exc}") from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublicSplitsError("PUBLIC_SPLITS_RESPONSE_UTF8_REQUIRED") from exc


def capture_vsin_cfb(
    *,
    now: datetime | None = None,
    opener: Callable = urlopen,
    source_url: str = VSIN_CFB_DK_URL,
) -> PublicSplitSnapshot:
    current = _utc_dt(now or datetime.now(timezone.utc), "now")
    html = _fetch_text(source_url, opener=opener)
    return parse_vsin_html(html, captured_at=current, source_url=source_url, sport="CFB")


def diagnostics(
    snapshot: PublicSplitSnapshot,
    *,
    money_ticket_gap_pp: float,
    public_ticket_pct: float,
) -> tuple[dict[str, Any], ...]:
    gap_floor = abs(_finite(money_ticket_gap_pp, "money_ticket_gap_pp"))
    ticket_floor = _finite(public_ticket_pct, "public_ticket_pct")
    if not 0.0 <= ticket_floor <= 100.0:
        raise PublicSplitsError("public_ticket_pct:PERCENT_RANGE")
    out: list[dict[str, Any]] = []
    for obs in snapshot.observations:
        flags: list[str] = []
        if abs(obs.money_ticket_gap_pp) >= gap_floor:
            flags.append("MONEY_TICKET_DIVERGENCE")
        if obs.ticket_pct >= ticket_floor:
            flags.append("PUBLIC_TICKET_HEAVY")
        if flags:
            out.append({
                "away_team": obs.away_team,
                "home_team": obs.home_team,
                "market": obs.market,
                "side": obs.side,
                "line": obs.line,
                "money_pct": obs.money_pct,
                "ticket_pct": obs.ticket_pct,
                "money_ticket_gap_pp": obs.money_ticket_gap_pp,
                "flags": flags,
                "source": obs.source,
                "source_book": obs.source_book,
                "captured_at": obs.captured_at,
            })
    return tuple(out)


def compare_snapshots(
    previous: PublicSplitSnapshot,
    current: PublicSplitSnapshot,
    *,
    public_ticket_pct: float = 70.0,
    minimum_point_move: float = 0.5,
) -> tuple[dict[str, Any], ...]:
    if previous.source != current.source or previous.sport != current.sport:
        raise PublicSplitsError("PUBLIC_SPLIT_SNAPSHOT_IDENTITY_MISMATCH")
    ticket_floor = _finite(public_ticket_pct, "public_ticket_pct")
    move_floor = abs(_finite(minimum_point_move, "minimum_point_move"))
    prior = {obs.key: obs for obs in previous.observations}
    out: list[dict[str, Any]] = []
    for obs in current.observations:
        old = prior.get(obs.key)
        if old is None:
            continue
        line_delta = float(obs.line - old.line)
        money_delta = float(obs.money_pct - old.money_pct)
        ticket_delta = float(obs.ticket_pct - old.ticket_pct)
        movement_metric = line_delta
        if obs.market == "MONEYLINE":
            movement_metric = _implied_american(obs.line) - _implied_american(old.line)

        reverse_candidate = False
        if obs.ticket_pct >= ticket_floor:
            if obs.market == "SPREAD":
                reverse_candidate = line_delta >= move_floor
            elif obs.market == "TOTAL" and obs.side == "OVER":
                reverse_candidate = line_delta <= -move_floor
            elif obs.market == "TOTAL" and obs.side == "UNDER":
                reverse_candidate = line_delta >= move_floor
            elif obs.market == "MONEYLINE":
                reverse_candidate = movement_metric < 0.0

        meaningful = (
            (obs.market in {"SPREAD", "TOTAL"} and abs(line_delta) >= move_floor)
            or (obs.market == "MONEYLINE" and abs(movement_metric) >= 0.01)
            or abs(money_delta) >= 5.0
            or abs(ticket_delta) >= 5.0
        )
        if meaningful:
            flags = ["LINE_OR_SPLIT_MOVEMENT"]
            if reverse_candidate:
                flags.append("REVERSE_LINE_MOVEMENT_CANDIDATE")
            out.append({
                "away_team": obs.away_team,
                "home_team": obs.home_team,
                "market": obs.market,
                "side": obs.side,
                "previous_line": old.line,
                "current_line": obs.line,
                "line_delta": line_delta,
                "money_pct_delta": money_delta,
                "ticket_pct_delta": ticket_delta,
                "market_probability_delta": movement_metric if obs.market == "MONEYLINE" else None,
                "flags": flags,
                "source": obs.source,
                "previous_captured_at": old.captured_at,
                "current_captured_at": obs.captured_at,
            })
    return tuple(out)


def snapshot_from_dict(value: Mapping[str, Any]) -> PublicSplitSnapshot:
    try:
        observations = tuple(
            PublicSplitObservation(
                source=str(row["source"]),
                source_book=str(row["source_book"]),
                sport=str(row["sport"]),
                captured_at=str(row["captured_at"]),
                source_url=str(row["source_url"]),
                away_team=str(row["away_team"]),
                home_team=str(row["home_team"]),
                market=str(row["market"]),
                side=str(row["side"]),
                line=float(row["line"]),
                money_pct=float(row["money_pct"]),
                ticket_pct=float(row["ticket_pct"]),
                contract=str(row.get("contract", PUBLIC_SPLITS_CONTRACT)),
            )
            for row in value.get("observations", [])
        )
        return PublicSplitSnapshot(
            source=str(value["source"]),
            source_book=str(value["source_book"]),
            sport=str(value["sport"]),
            captured_at=str(value["captured_at"]),
            source_url=str(value["source_url"]),
            observations=observations,
            state=str(value.get("state", "OK")),
            notes=tuple(str(x) for x in value.get("notes", [])),
            contract=str(value.get("contract", PUBLIC_SPLITS_CONTRACT)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PublicSplitsError("PUBLIC_SPLIT_SNAPSHOT_JSON_INVALID") from exc
