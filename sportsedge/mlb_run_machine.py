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
    Full frozen snapshot -> MANUAL; non-empty supplied quotes -> HYBRID; otherwise
    AUTOMATIC.
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
from .prediction_journal import normalize_legacy_block_reason
from .mlb_edge_score import score_mlb_edge
from .mlb_market_dispositions import market_dispositions
from .mlb_quote_pairing import pair_opposite_odds
from .mlb_input_readiness import scored_input_readiness

CHICAGO_TZ = ZoneInfo("America/Chicago")
MEMORY_QUOTES_URL = "https://sportsedge.local/run-it-quotes"
VALID_MODES = frozenset({"AUTO_SELECT", "MANUAL", "HYBRID", "AUTOMATIC"})

# Frozen quote-hygiene defaults shared with the replay policy: 180s TTL, 30s paired skew.
DEFAULT_QUOTE_TTL_SECONDS = 180

# Provenance of a quote's retrieved_at. INTAKE_STAMPED means SportsEdge stamped the
# moment the line was received, NOT when the sportsbook price was observed. It is
# presentation-freshness only: never CLV, replay, Truth Gate, or OFFICIAL evidence.
TIMESTAMP_SOURCE_PROVIDED = "PROVIDED"
TIMESTAMP_SOURCE_INTAKE_STAMPED = "INTAKE_STAMPED"
TIMESTAMP_SOURCE_MISSING = "MISSING"
TIMESTAMP_SOURCE_INVALID = "INVALID"


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
    raw_implied_probability: float | None = None
    market_no_vig_p_status: str | None = None
    edge: float | None = None
    ev_per_dollar: float | None = None
    model_input_hash: str | None = None
    distribution_sha256: str | None = None
    readout_sha256: str | None = None
    readout_version: str | None = None
    engine_version: str | None = None
    seed_policy: str | None = None
    mc_paths: int | None = None
    book_key: str | None = None
    sportsbook: str | None = None
    quote_retrieved_at: str | None = None
    offer_id: str | None = None
    confidence_score: int | None = None
    scored_status: str | None = None
    fair_odds: int | None = None
    scored_market_p: float | None = None
    score_reason_codes: tuple[str, ...] = ()
    timestamp_source: str | None = None


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


def _resolve_mode(mode: str, *, quotes, games, feature_rows) -> str:
    selected = str(mode or "AUTO_SELECT").strip().upper()
    if selected not in VALID_MODES:
        raise MLBRunMachineError(f"RUN_MODE_UNSUPPORTED:{selected}")
    if selected != "AUTO_SELECT":
        return selected
    has_snapshot_quotes = quotes is not None
    has_nonempty_quotes = bool(quotes)
    has_games = games is not None
    has_features = feature_rows is not None
    if has_snapshot_quotes and has_games and has_features:
        return "MANUAL"
    if has_nonempty_quotes and not has_games and not has_features:
        return "HYBRID"
    if not has_nonempty_quotes and not has_games and not has_features:
        return "AUTOMATIC"
    raise MLBRunMachineError("AUTO_SELECT_INPUTS_AMBIGUOUS")


def _hybrid_period(market: str) -> str:
    name = str(market or "").strip().upper()
    if name.startswith("F5_"):
        return "F5"
    if name in {"NRFI", "YRFI"}:
        return "1ST"
    return "FG"


def _parse_provided_timestamp(value: Any) -> datetime:
    """Parse a caller-provided retrieved_at; naive or unparseable values fail closed."""
    try:
        stamp = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MLBRunMachineError("RETRIEVED_AT_INVALID") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise MLBRunMachineError("RETRIEVED_AT_TIMEZONE_REQUIRED")
    return stamp.astimezone(timezone.utc)


def _prepare_hybrid_quotes(quotes: Sequence[Mapping[str, Any]], *, current: datetime) -> list[dict[str, Any]]:
    """Normalize manual HYBRID quotes.

    A missing retrieved_at is stamped with the intake instant and labeled
    INTAKE_STAMPED. A provided retrieved_at is preserved and labeled PROVIDED; a
    naive or invalid provided value raises instead of being silently replaced.
    """
    intake = _aware_utc(current)
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(quotes):
        if not isinstance(raw, Mapping):
            raise MLBRunMachineError("HYBRID_QUOTE_MUST_BE_OBJECT")
        row = dict(raw)
        market = str(row.get("market") or "").strip().upper()
        if market:
            row["market"] = market
        provided = row.get("retrieved_at")
        if provided is None or (isinstance(provided, str) and not provided.strip()):
            row["retrieved_at"] = intake.isoformat()
            row["timestamp_source"] = TIMESTAMP_SOURCE_INTAKE_STAMPED
        else:
            try:
                stamp = _parse_provided_timestamp(provided)
            except MLBRunMachineError as exc:
                raise MLBRunMachineError(f"{exc}:quote[{index}]") from exc
            if stamp == intake:
                # Keeps the intake-stamp join in _machine_result unambiguous.
                raise MLBRunMachineError(f"RETRIEVED_AT_COLLIDES_WITH_INTAKE_STAMP:quote[{index}]")
            row["timestamp_source"] = TIMESTAMP_SOURCE_PROVIDED
        row.setdefault("ttl_seconds", DEFAULT_QUOTE_TTL_SECONDS)
        row.setdefault("period", _hybrid_period(market))
        row.setdefault("book_key", "manual_input")
        row.setdefault("sportsbook", "Manual Input")
        row.setdefault("raw_market_name", f"MANUAL:{market or 'UNKNOWN'}")
        row.setdefault("is_alternate", False)
        out.append(row)
    return out


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
        "model_candidates": statuses.get("MODEL_CANDIDATE", 0),
        "bet_status_counts": statuses,
        "official_bets": statuses.get("OFFICIAL_BET", 0),
        "blocked": statuses.get("BLOCKED", 0),
        "scored_market_dispositions": market_dispositions([asdict(x) for x in results]),
    }


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _parse_quote_age(row: Any, *, current: datetime | None = None) -> tuple[float, float, datetime | None, str | None]:
    """Return (age_seconds, ttl_seconds, parsed_stamp, timestamp_problem).

    A missing, naive, or unparseable timestamp is treated as stale (age > ttl) and
    reported as QUOTE_TIMESTAMP_MISSING / RETRIEVED_AT_TIMEZONE_REQUIRED /
    RETRIEVED_AT_INVALID. It is never treated as fresh.
    """
    ttl = float(_row_value(row, "ttl_seconds", DEFAULT_QUOTE_TTL_SECONDS) or DEFAULT_QUOTE_TTL_SECONDS)
    retrieved = _row_value(row, "quote_retrieved_at") or _row_value(row, "retrieved_at")
    if not retrieved:
        return ttl + 1.0, ttl, None, "QUOTE_TIMESTAMP_MISSING"
    if isinstance(retrieved, datetime):
        stamp = retrieved
    else:
        try:
            stamp = datetime.fromisoformat(str(retrieved).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return ttl + 1.0, ttl, None, "RETRIEVED_AT_INVALID"
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return ttl + 1.0, ttl, None, "RETRIEVED_AT_TIMEZONE_REQUIRED"
    stamp = stamp.astimezone(timezone.utc)
    reference = _aware_utc(current) if current is not None else datetime.now(timezone.utc)
    age = max(0.0, (reference - stamp).total_seconds())
    return age, ttl, stamp, None


def _timestamp_source(row: Any, stamp: datetime | None, problem: str | None, intake_stamp: datetime | None) -> str:
    if problem == "QUOTE_TIMESTAMP_MISSING":
        return TIMESTAMP_SOURCE_MISSING
    if problem is not None or stamp is None:
        return TIMESTAMP_SOURCE_INVALID
    declared = str(_row_value(row, "timestamp_source") or "").strip().upper()
    if declared in {TIMESTAMP_SOURCE_PROVIDED, TIMESTAMP_SOURCE_INTAKE_STAMPED}:
        return declared
    if intake_stamp is not None and stamp == _aware_utc(intake_stamp):
        return TIMESTAMP_SOURCE_INTAKE_STAMPED
    return TIMESTAMP_SOURCE_PROVIDED


def _machine_result(source_index: int, row: Any, *, current: datetime | None = None,
                    intake_stamp: datetime | None = None) -> MLBMachineResult:
    model_p = _row_value(row, "model_p")
    odds = _row_value(row, "american_odds")
    raw_row = row if isinstance(row, Mapping) else vars(row)
    inputs_complete, missing_families = scored_input_readiness(raw_row)
    quote_age, quote_ttl, stamp, timestamp_problem = _parse_quote_age(row, current=current)
    timestamp_source = _timestamp_source(row, stamp, timestamp_problem, intake_stamp)
    opposite_odds = _row_value(row, "opposite_odds")
    market = str(_row_value(row, "market", "UNKNOWN")).upper()
    n_way = market == "FIRST_HOME_RUN"
    reliability = float(_row_value(row, "model_reliability", 1.0) or 1.0)
    scored = score_mlb_edge(
        model_p=model_p, american_odds=odds, opposite_odds=opposite_odds,
        n_way_market=n_way, quote_age_seconds=quote_age, quote_ttl_seconds=quote_ttl,
        reliability=reliability, inputs_complete=inputs_complete,
    )
    extra_codes = (timestamp_problem,) if timestamp_problem else ()
    return MLBMachineResult(
        source_index=int(_row_value(row, "source_index", source_index)),
        game_id=str(_row_value(row, "game_id", "UNKNOWN")),
        market=market,
        entity_id=str(_row_value(row, "entity_id", "UNKNOWN")),
        line=_row_value(row, "line"),
        side=str(_row_value(row, "side", "UNKNOWN")),
        american_odds=_row_value(row, "american_odds"),
        model_p=model_p,
        bet_status=str(_row_value(row, "bet_status", "BLOCKED")),
        reason=str(_row_value(row, "reason", "UNKNOWN")),
        shadow_status=_row_value(row, "shadow_status"),
        implied_probability=_row_value(row, "implied_probability"),
        raw_implied_probability=_row_value(row, "raw_implied_probability"),
        market_no_vig_p_status=_row_value(row, "market_no_vig_p_status"),
        edge=_row_value(row, "edge"),
        ev_per_dollar=_row_value(row, "ev_per_dollar"),
        model_input_hash=_row_value(row, "model_input_hash"),
        distribution_sha256=_row_value(row, "distribution_sha256"),
        readout_sha256=_row_value(row, "readout_sha256"),
        readout_version=_row_value(row, "readout_version"),
        engine_version=_row_value(row, "engine_version"),
        seed_policy=_row_value(row, "seed_policy"),
        mc_paths=_row_value(row, "mc_paths"),
        book_key=_row_value(row, "book_key"),
        sportsbook=_row_value(row, "sportsbook"),
        quote_retrieved_at=_row_value(row, "quote_retrieved_at"),
        offer_id=_row_value(row, "offer_id"),
        confidence_score=scored.confidence_score,
        scored_status=scored.status,
        fair_odds=scored.fair_odds,
        scored_market_p=scored.market_p,
        score_reason_codes=scored.reason_codes + extra_codes + tuple(f"MISSING_FEATURE_FAMILY:{x}" for x in missing_families),
        timestamp_source=timestamp_source,
    )


def _report(*, mode: str, current: datetime, slate_date_ct: str, run_status: str, rows: Sequence[Any],
            source_failures: Sequence[Mapping[str, Any]] = (), intake_stamp: datetime | None = None) -> MLBMachineReport:
    paired_rows = pair_opposite_odds(rows)
    results = tuple(
        _machine_result(i, row, current=current, intake_stamp=intake_stamp)
        for i, row in enumerate(paired_rows)
    )
    status = str(run_status)
    summary = _summary(results)
    if summary["model_candidates"] and summary["official_bets"] == 0:
        status = "MODEL_CANDIDATES_AVAILABLE_OFFICIAL_BLOCKED"
    return MLBMachineReport(
        mode=mode,
        slate_date_ct=slate_date_ct,
        generated_at_utc=current.isoformat(),
        run_status=status,
        results=results,
        source_failures=tuple(dict(x) for x in source_failures),
        summary=summary,
    )


def run_mlb_machine(
    *, mode: str = "AUTO_SELECT", quotes: Sequence[Mapping[str, Any]] | None = None,
    games: Sequence[LiveGame] | None = None, feature_rows: Sequence[Mapping[str, Any]] | None = None,
    target_date: date | None = None, odds_api_key: str | None = None, odds_api_keys: tuple[str, ...] = (),
    projected_lineups_url: str | None = None, provider_token: str | None = None,
    now: datetime | None = None, opener: Callable = urlopen,
    registry_path: str = "config/deployments.json", require_confirmed_lineup: bool = True,
    edge_floor_config_path: str = DEFAULT_EDGE_FLOOR_CONFIG, kelly_multiplier: float = 0.25,
    bookmakers: tuple[str, ...] = ("draftkings",), history_cache_dir: str | Path | None = None,
) -> MLBMachineReport:
    current = _aware_utc(now)
    selected = _resolve_mode(mode, quotes=quotes, games=games, feature_rows=feature_rows)
    slate_date = target_date or current.astimezone(CHICAGO_TZ).date()
    if selected == "MANUAL":
        if quotes is None or games is None or feature_rows is None:
            raise MLBRunMachineError("MANUAL_REQUIRES_GAMES_QUOTES_FEATURE_ROWS")
        rows = run_manual_hybrid_joint_mlb(
            games=list(games), quotes=list(quotes), target_date=slate_date, feature_rows=list(feature_rows),
            now=current, opener=opener, registry_path=registry_path,
            require_confirmed_lineup=require_confirmed_lineup,
            edge_floor_config_path=edge_floor_config_path, kelly_multiplier=kelly_multiplier,
        )
        return _report(mode=selected, current=current, slate_date_ct=slate_date.isoformat(), run_status="PASS" if rows else "NO_QUOTES", rows=rows)
    if selected == "HYBRID":
        if quotes is None or games is not None or feature_rows is not None:
            raise MLBRunMachineError("HYBRID_REQUIRES_QUOTES_ONLY")
        quote_payload = _prepare_hybrid_quotes(quotes, current=current)
        def wrapped(req: Any, timeout: int = 15):
            if _url(req) == MEMORY_QUOTES_URL:
                return _MemoryResponse(quote_payload)
            return opener(req, timeout=timeout)
        report = run_auto_joint_mlb(
            quote_url=MEMORY_QUOTES_URL, projected_lineups_url=projected_lineups_url,
            provider_token=provider_token, now=current, opener=wrapped, registry_path=registry_path,
            require_confirmed_lineup=require_confirmed_lineup,
            edge_floor_config_path=edge_floor_config_path, kelly_multiplier=kelly_multiplier,
        )
        return _report(mode=selected, current=current, slate_date_ct=report.slate_date_ct, run_status=report.run_status, rows=report.results, source_failures=report.source_failures, intake_stamp=current)
    if selected == "AUTOMATIC":
        keys: list[str] = []
        for raw in (odds_api_key, *odds_api_keys):
            key = str(raw or "").strip()
            if key and key not in keys:
                keys.append(key)
        if not keys:
            raise MLBRunMachineError("AUTOMATIC_REQUIRES_ODDS_API_KEY")
        report = run_auto_mlb_native_odds(
            odds_api_key=keys[0], odds_api_keys=tuple(keys[1:]), feature_url=None,
            projected_lineups_url=projected_lineups_url, provider_token=provider_token,
            now=current, opener=opener, registry_path=registry_path,
            require_confirmed_lineup=require_confirmed_lineup,
            edge_floor_config_path=edge_floor_config_path, kelly_multiplier=kelly_multiplier,
            bookmakers=tuple(bookmakers), history_cache_dir=history_cache_dir,
        )
        return _report(mode=selected, current=current, slate_date_ct=report.slate_date_ct, run_status=report.run_status, rows=report.results, source_failures=report.source_failures)
    raise MLBRunMachineError(f"RUN_MODE_UNREACHABLE:{selected}")


def run_it_mlb(**kwargs: Any) -> MLBMachineReport:
    return run_mlb_machine(**kwargs)


def machine_report_to_dict(report: MLBMachineReport) -> dict[str, Any]:
    return {
        "mode": report.mode,
        "slate_date_ct": report.slate_date_ct,
        "generated_at_utc": report.generated_at_utc,
        "run_status": report.run_status,
        "results": [normalize_legacy_block_reason(asdict(x)) for x in report.results],
        "source_failures": [dict(x) for x in report.source_failures],
        "summary": dict(report.summary),
    }


def report_to_dict(report: MLBMachineReport) -> dict[str, Any]:
    return machine_report_to_dict(report)
