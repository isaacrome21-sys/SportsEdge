"""One canonical MLB execution entrypoint for manual, hybrid, and automatic modes.

The mode changes only ownership of inputs. Predictive pricing always converges on
SportsEdge's unified card / canonical engine registry. No sportsbook probability is
ever used as a predictive feature.

Modes
-----
MANUAL
    Caller supplies live-game snapshots, frozen feature rows, and quotes.
HYBRID
    Caller supplies quotes; SportsEdge fetches schedule/lineups/history and builds
    price-independent features automatically.
AUTOMATIC
    SportsEdge acquires sportsbook quotes plus MLB context automatically.
AUTO_SELECT
    Full frozen snapshot -> MANUAL; quotes only -> HYBRID; no quotes -> AUTOMATIC.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.request import urlopen
from zoneinfo import ZoneInfo
import json

from .auto_joint_runner import run_auto_joint_mlb
from .auto_native_odds import run_auto_mlb_native_odds
from .edge_floors import DEFAULT_EDGE_FLOOR_CONFIG
from .live_slate import LiveGame
from .manual_hybrid_joint_runner import run_manual_hybrid_joint_mlb

CHICAGO_TZ = ZoneInfo("America/Chicago")
MEMORY_QUOTES_URL = "https://sportsedge.local/run-it-quotes"
VALID_MODES = frozenset({"AUTO_SELECT", "MANUAL", "HYBRID", "AUTOMATIC"})


class MLBRunMachineError(RuntimeError):
    pass


@dataclass(frozen=True)
class MLBMachineResult:
    source_index: int
    game_id: str
    market: str
    entity_id: str
    line: Any
    side: str
    american_odds: Any
    model_p: float | None
    bet_status: str
    reason: str
    shadow_status: str | None = None
    implied_probability: float | None = None
    edge: float | None = None
    ev_per_dollar: float | None = None


@dataclass(frozen=True)
class MLBMachineReport:
    mode: str
    slate_date_ct: str
    generated_at_utc: str
    run_status: str
    results: tuple[MLBMachineResult, ...]
    source_failures: tuple[dict[str, Any], ...]
    summary: dict[str, Any]


class _MemoryResponse:
    def __init__(self, value: Any):
        self._raw = json.dumps(value, default=str).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._raw


def _url(req: Any) -> str:
    return req if isinstance(req, str) else str(req.full_url)


def _aware_utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise MLBRunMachineError("NOW_TIMEZONE_REQUIRED")
    return current.astimezone(timezone.utc)


def _resolve_mode(
    mode: str,
    *,
    quotes: Sequence[Mapping[str, Any]] | None,
    games: Sequence[LiveGame] | None,
    feature_rows: Sequence[Mapping[str, Any]] | None,
) -> str:
    selected = str(mode or "AUTO_SELECT").strip().upper()
    if selected not in VALID_MODES:
        raise MLBRunMachineError(f"RUN_MODE_UNSUPPORTED:{selected}")
    if selected != "AUTO_SELECT":
        return selected

    has_quotes = quotes is not None
    has_games = games is not None
    has_features = feature_rows is not None
    if has_quotes and has_games and has_features:
        return "MANUAL"
    if has_quotes and not has_games and not has_features:
        return "HYBRID"
    if not has_quotes and not has_games and not has_features:
        return "AUTOMATIC"
    raise MLBRunMachineError("AUTO_SELECT_INPUTS_AMBIGUOUS")


def _summary(results: Sequence[MLBMachineResult]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    markets: set[str] = set()
    model_priced = 0
    for row in results:
        statuses[row.bet_status] = statuses.get(row.bet_status, 0) + 1
        if row.market and row.market != "UNKNOWN":
            markets.add(row.market)
        if row.model_p is not None:
            model_priced += 1
    return {
        "quote_count": len(results),
        "markets_seen": sorted(markets),
        "market_count_seen": len(markets),
        "model_priced": model_priced,
        "bet_status_counts": statuses,
        "official_bets": statuses.get("OFFICIAL_BET", 0),
        "blocked": statuses.get("BLOCKED", 0),
    }


def _machine_result(source_index: int, row: Any) -> MLBMachineResult:
    return MLBMachineResult(
        source_index=int(getattr(row, "source_index", source_index)),
        game_id=str(getattr(row, "game_id", "UNKNOWN")),
        market=str(getattr(row, "market", "UNKNOWN")),
        entity_id=str(getattr(row, "entity_id", "UNKNOWN")),
        line=getattr(row, "line", None),
        side=str(getattr(row, "side", "UNKNOWN")),
        american_odds=getattr(row, "american_odds", None),
        model_p=getattr(row, "model_p", None),
        bet_status=str(getattr(row, "bet_status", "BLOCKED")),
        reason=str(getattr(row, "reason", "UNKNOWN")),
        shadow_status=getattr(row, "shadow_status", None),
        implied_probability=getattr(row, "implied_probability", None),
        edge=getattr(row, "edge", None),
        ev_per_dollar=getattr(row, "ev_per_dollar", None),
    )


def _report(
    *,
    mode: str,
    current: datetime,
    slate_date_ct: str,
    run_status: str,
    rows: Sequence[Any],
    source_failures: Sequence[Mapping[str, Any]] = (),
) -> MLBMachineReport:
    results = tuple(_machine_result(i, row) for i, row in enumerate(rows))
    return MLBMachineReport(
        mode=mode,
        slate_date_ct=slate_date_ct,
        generated_at_utc=current.isoformat(),
        run_status=str(run_status),
        results=results,
        source_failures=tuple(dict(x) for x in source_failures),
        summary=_summary(results),
    )


def run_mlb_machine(
    *,
    mode: str = "AUTO_SELECT",
    quotes: Sequence[Mapping[str, Any]] | None = None,
    games: Sequence[LiveGame] | None = None,
    feature_rows: Sequence[Mapping[str, Any]] | None = None,
    target_date: date | None = None,
    odds_api_key: str | None = None,
    odds_api_keys: tuple[str, ...] = (),
    projected_lineups_url: str | None = None,
    provider_token: str | None = None,
    now: datetime | None = None,
    opener: Callable = urlopen,
    registry_path: str = "config/deployments.json",
    require_confirmed_lineup: bool = False,
    edge_floor_config_path: str = DEFAULT_EDGE_FLOOR_CONFIG,
    kelly_multiplier: float = 0.25,
    bookmakers: tuple[str, ...] = ("draftkings",),
    history_cache_dir: str | Path | None = None,
) -> MLBMachineReport:
    """Run the canonical MLB machine.

    This function never turns deployment/evidence blockers into bets. It only
    standardizes input ownership and orchestration around the same runtime engines.
    """
    current = _aware_utc(now)
    selected = _resolve_mode(mode, quotes=quotes, games=games, feature_rows=feature_rows)
    slate_date = target_date or current.astimezone(CHICAGO_TZ).date()

    if selected == "MANUAL":
        if quotes is None or games is None or feature_rows is None:
            raise MLBRunMachineError("MANUAL_REQUIRES_GAMES_QUOTES_FEATURE_ROWS")
        rows = run_manual_hybrid_joint_mlb(
            games=list(games),
            quotes=list(quotes),
            target_date=slate_date,
            feature_rows=list(feature_rows),
            now=current,
            opener=opener,
            registry_path=registry_path,
            require_confirmed_lineup=require_confirmed_lineup,
            edge_floor_config_path=edge_floor_config_path,
            kelly_multiplier=kelly_multiplier,
        )
        return _report(
            mode=selected,
            current=current,
            slate_date_ct=slate_date.isoformat(),
            run_status="PASS" if rows else "NO_QUOTES",
            rows=rows,
        )

    if selected == "HYBRID":
        if quotes is None or games is not None or feature_rows is not None:
            raise MLBRunMachineError("HYBRID_REQUIRES_QUOTES_ONLY")
        quote_payload = [dict(row) for row in quotes]

        def wrapped(req: Any, timeout: int = 15):
            if _url(req) == MEMORY_QUOTES_URL:
                return _MemoryResponse(quote_payload)
            return opener(req, timeout=timeout)

        report = run_auto_joint_mlb(
            quote_url=MEMORY_QUOTES_URL,
            projected_lineups_url=projected_lineups_url,
            provider_token=provider_token,
            now=current,
            opener=wrapped,
            registry_path=registry_path,
            require_confirmed_lineup=require_confirmed_lineup,
            edge_floor_config_path=edge_floor_config_path,
            kelly_multiplier=kelly_multiplier,
        )
        return _report(
            mode=selected,
            current=current,
            slate_date_ct=report.slate_date_ct,
            run_status=report.run_status,
            rows=report.results,
            source_failures=report.source_failures,
        )

    if selected == "AUTOMATIC":
        key = str(odds_api_key or "").strip()
        if not key:
            raise MLBRunMachineError("AUTOMATIC_REQUIRES_ODDS_API_KEY")
        report = run_auto_mlb_native_odds(
            odds_api_key=key,
            odds_api_keys=tuple(odds_api_keys),
            feature_url=None,
            projected_lineups_url=projected_lineups_url,
            provider_token=provider_token,
            now=current,
            opener=opener,
            registry_path=registry_path,
            require_confirmed_lineup=require_confirmed_lineup,
            edge_floor_config_path=edge_floor_config_path,
            kelly_multiplier=kelly_multiplier,
            bookmakers=tuple(bookmakers),
            history_cache_dir=history_cache_dir,
        )
        return _report(
            mode=selected,
            current=current,
            slate_date_ct=report.slate_date_ct,
            run_status=report.run_status,
            rows=report.results,
            source_failures=report.source_failures,
        )

    raise MLBRunMachineError(f"RUN_MODE_UNREACHABLE:{selected}")


def run_it_mlb(**kwargs: Any) -> MLBMachineReport:
    """Conversation-facing alias for the canonical SportsEdge MLB machine."""
    return run_mlb_machine(**kwargs)


def machine_report_to_dict(report: MLBMachineReport) -> dict[str, Any]:
    return asdict(report)
