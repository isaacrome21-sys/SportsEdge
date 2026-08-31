"""Canonical SportsEdge CFB Manual / Hybrid / Automatic execution machine.

Modes differ only in ownership of inputs. Every mode converges on the same canonical
CFB game snapshot, the same joint full-game distribution, and the same market
read-outs. Sportsbook prices are never model features.

This foundation prices full-game MONEYLINE / SPREAD / TOTAL only. Other declared
football markets remain explicit NO_ENGINE until their required period/player state
is actually modeled. New CFB pricing remains BLOCKED from official betting until
promotion evidence and the governed live-decision layer authorize that market.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Callable, Mapping, Sequence
from urllib.request import urlopen

from .joint_model import CFBJointScoreModel, CFB_SEED_POLICY, price_cfb_game_markets, simulate_cfb_joint_distribution
from .source import (
    CFBGame, CFBQuote, CFBTeamMetrics, SUPPORTED_GAME_MARKETS, attach_weather,
    build_team_alias_index, fetch_cfbd_games, fetch_cfbd_team_metrics, fetch_cfbd_teams,
    fetch_cfbd_weather, fetch_the_odds_api_quotes,
)

VALID_MODES = frozenset({"AUTO_SELECT", "MANUAL", "HYBRID", "AUTOMATIC"})
CFB_MACHINE_VERSION = "CFB_RUN_MACHINE_V1_2_HARDENED"
DEFAULT_QUOTE_TTL_SECONDS = 180
DEFAULT_QUOTE_PAIR_SKEW_SECONDS = 30


class CFBRunMachineError(ValueError):
    pass


@dataclass(frozen=True)
class CFBMachineResult:
    game_id: str
    market: str
    side: str
    line: float | None
    american_odds: float | None
    model_p: float | None
    push_p: float | None
    fair_market_p: float | None
    raw_implied_p: float | None
    hold: float | None
    edge: float | None
    ev_per_dollar: float | None
    bet_status: str
    engine_status: str
    reason: str
    model_artifact_sha256: str | None
    distribution_sha256: str | None
    seed: int | None
    seed_policy: str | None
    book_key: str | None
    sportsbook: str | None
    quote_retrieved_at: str | None
    offer_id: str | None


@dataclass(frozen=True)
class CFBMachineReport:
    mode: str
    season: int
    week: int
    generated_at_utc: str
    run_status: str
    machine_version: str
    results: tuple[CFBMachineResult, ...]
    source_failures: tuple[dict[str, str], ...]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def expected_games_from_schedule(games: Sequence[CFBGame]) -> list[dict[str, str]]:
    return [{"game_id": game.game_id, "classification": game.matchup_classification()} for game in games]


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CFBRunMachineError(f"{name} timezone required")
    return value.astimezone(timezone.utc)


def _resolve_mode(mode: str, *, games, metrics, quotes) -> str:
    selected = str(mode or "AUTO_SELECT").strip().upper()
    if selected not in VALID_MODES:
        raise CFBRunMachineError(f"CFB_RUN_MODE_UNSUPPORTED:{selected}")
    if selected != "AUTO_SELECT":
        return selected
    has_games, has_metrics, has_quotes = games is not None, metrics is not None, quotes is not None
    if has_games and has_metrics and has_quotes:
        return "MANUAL"
    if not has_games and not has_metrics and bool(quotes):
        return "HYBRID"
    if not has_games and not has_metrics and not bool(quotes):
        return "AUTOMATIC"
    raise CFBRunMachineError("CFB_AUTO_SELECT_INPUTS_AMBIGUOUS")


def _quote_dict(value: CFBQuote | Mapping[str, Any]) -> dict[str, Any]:
    row = value.to_dict() if isinstance(value, CFBQuote) else dict(value)
    row["market"] = str(row.get("market") or "").strip().upper()
    row["side"] = str(row.get("side") or "").strip().upper()
    try:
        row["line"] = float(row.get("line", 0.0))
        row["american_odds"] = float(row["american_odds"])
    except Exception as exc:
        raise CFBRunMachineError("CFB_QUOTE_NUMERIC_INVALID") from exc
    return row


def _quote_time(value: Any) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise CFBRunMachineError("CFB_QUOTE_RETRIEVED_AT_REQUIRED")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBRunMachineError("CFB_QUOTE_RETRIEVED_AT_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CFBRunMachineError("CFB_QUOTE_RETRIEVED_AT_TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def _american_decimal(odds: float) -> float:
    value = float(odds)
    if not isfinite(value) or (-100.0 < value < 100.0):
        raise CFBRunMachineError("CFB_AMERICAN_ODDS_INVALID")
    return 1.0 + (100.0 / abs(value) if value < 0 else value / 100.0)


def _raw_implied(odds: float) -> float:
    return 1.0 / _american_decimal(odds)


def _complements(a: str, b: str) -> bool:
    return {a, b} in ({"HOME", "AWAY"}, {"OVER", "UNDER"})


def _pair_key(q: Mapping[str, Any]) -> tuple[str, str, float, str]:
    return (
        str(q.get("game_id") or ""),
        str(q.get("market") or "").upper(),
        float(q.get("line", 0.0)),
        str(q.get("book_key") or ""),
    )


def _distribution_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    raw = json.dumps(list(rows), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def _identity_seed(*, root_seed: int, game_id: str, model_sha: str) -> int:
    if isinstance(root_seed, bool) or not isinstance(root_seed, int):
        raise CFBRunMachineError("CFB_ROOT_SEED_INTEGER_REQUIRED")
    payload = f"{root_seed}|{game_id}|{model_sha}|CFB_GAME_PATH_V1".encode()
    return int.from_bytes(sha256(payload).digest()[:8], "big", signed=False)


def _game_row(game: CFBGame, metrics: Mapping[str, CFBTeamMetrics]) -> dict[str, Any]:
    home, away = metrics.get(game.home_team), metrics.get(game.away_team)
    if not isinstance(home, CFBTeamMetrics):
        raise CFBRunMachineError(f"CFB_HOME_METRICS_MISSING:{game.home_team}")
    if not isinstance(away, CFBTeamMetrics):
        raise CFBRunMachineError(f"CFB_AWAY_METRICS_MISSING:{game.away_team}")
    if not isinstance(game.weather, Mapping):
        raise CFBRunMachineError(f"CFB_WEATHER_MISSING:{game.game_id}")
    return {
        "game_id": game.game_id,
        "season": game.season,
        "week": game.week,
        "neutral_site": game.neutral_site,
        "home_metrics": home.to_dict(),
        "away_metrics": away.to_dict(),
        "weather": dict(game.weather),
        "classification": game.matchup_classification(),
    }


def _readout_probability(readouts: Mapping[str, Any], market: str, side: str) -> tuple[float, float]:
    if market == "MONEYLINE":
        return float(readouts["moneyline"][side.lower()]), 0.0
    if market == "SPREAD":
        return float(readouts["spread"][side.lower()]), float(readouts["spread"]["push"])
    if market == "TOTAL":
        return float(readouts["total"][side.lower()]), float(readouts["total"]["push"])
    raise CFBRunMachineError(f"CFB_NO_ENGINE:{market}")


def _blocked_result(q: Mapping[str, Any], *, reason: str, engine_status: str = "BLOCKED") -> CFBMachineResult:
    retrieved = str(q.get("retrieved_at") or "").strip() or None
    return CFBMachineResult(
        game_id=str(q.get("game_id") or "UNKNOWN"),
        market=str(q.get("market") or "UNKNOWN").upper(),
        side=str(q.get("side") or "UNKNOWN").upper(),
        line=float(q.get("line", 0.0)),
        american_odds=float(q["american_odds"]) if q.get("american_odds") is not None else None,
        model_p=None,
        push_p=None,
        fair_market_p=None,
        raw_implied_p=None,
        hold=None,
        edge=None,
        ev_per_dollar=None,
        bet_status="BLOCKED",
        engine_status=engine_status,
        reason=str(reason),
        model_artifact_sha256=None,
        distribution_sha256=None,
        seed=None,
        seed_policy=None,
        book_key=str(q.get("book_key") or "") or None,
        sportsbook=str(q.get("sportsbook") or "") or None,
        quote_retrieved_at=retrieved,
        offer_id=str(q.get("offer_id") or "") or None,
    )


def _blocked_no_engine(q: Mapping[str, Any]) -> CFBMachineResult:
    return _blocked_result(q, reason="NO_ENGINE", engine_status="NO_ENGINE")


def _summary(results: Sequence[CFBMachineResult]) -> dict[str, Any]:
    return {
        "quote_count": len(results),
        "priced": sum(r.engine_status == "PRICED" and r.edge is not None for r in results),
        "no_engine": sum(r.engine_status == "NO_ENGINE" for r in results),
        "blocked": sum(r.bet_status == "BLOCKED" for r in results),
        "official_bets": sum(r.bet_status == "OFFICIAL_BET" for r in results),
        "markets_seen": sorted({r.market for r in results}),
        "games_with_blocked_model_input": sorted({r.game_id for r in results if r.reason.startswith("CFB_MODEL_INPUT_BLOCKED:")}),
    }


def _pair_time_state(
    pair: Sequence[Mapping[str, Any]],
    *,
    current: datetime,
    quote_ttl_seconds: int,
    quote_pair_skew_seconds: int,
) -> tuple[bool, str, tuple[datetime, ...]]:
    if len(pair) != 2:
        return False, "PAIRED_PRICE_REQUIRED_FOR_DEVIG", ()
    times = tuple(_quote_time(q.get("retrieved_at")) for q in pair)
    if any(ts > current for ts in times):
        return False, "CFB_QUOTE_FROM_FUTURE", times
    if any((current - ts).total_seconds() > int(quote_ttl_seconds) for ts in times):
        return False, "CFB_QUOTE_STALE", times
    if abs((times[0] - times[1]).total_seconds()) > int(quote_pair_skew_seconds):
        return False, "CFB_QUOTE_PAIR_SKEW", times
    return True, "OK", times


def _run_canonical(
    *,
    mode: str,
    season: int,
    week: int,
    now: datetime,
    model: CFBJointScoreModel,
    games: Sequence[CFBGame],
    metrics: Mapping[str, CFBTeamMetrics],
    quotes,
    root_seed: int,
    n_paths: int,
    quote_ttl_seconds: int,
    quote_pair_skew_seconds: int,
    source_failures=(),
) -> CFBMachineReport:
    current = _aware(now, "now")
    if not games:
        raise CFBRunMachineError("CFB_GAMES_EMPTY")
    if isinstance(quote_ttl_seconds, bool) or int(quote_ttl_seconds) < 0:
        raise CFBRunMachineError("CFB_QUOTE_TTL_INVALID")
    if isinstance(quote_pair_skew_seconds, bool) or int(quote_pair_skew_seconds) < 0:
        raise CFBRunMachineError("CFB_QUOTE_PAIR_SKEW_INVALID")
    model_sha = model.artifact_sha256()
    game_map = {g.game_id: g for g in games}
    if len(game_map) != len(games):
        raise CFBRunMachineError("CFB_DUPLICATE_GAME_ID")
    quote_rows = [_quote_dict(q) for q in quotes]
    distributions: dict[str, Sequence[Mapping[str, Any]]] = {}
    dist_hashes: dict[str, str] = {}
    seeds: dict[str, int] = {}
    distribution_failures: dict[str, str] = {}
    modeled_game_ids = sorted({
        str(q.get("game_id") or "")
        for q in quote_rows
        if str(q.get("market") or "").upper() in SUPPORTED_GAME_MARKETS
    })
    for gid in modeled_game_ids:
        game = game_map.get(gid)
        if game is None:
            distribution_failures[gid] = "CFB_QUOTE_GAME_UNRESOLVED"
            continue
        try:
            seed = _identity_seed(root_seed=root_seed, game_id=gid, model_sha=model_sha)
            path = simulate_cfb_joint_distribution(model, _game_row(game, metrics), seed=seed, n_paths=n_paths)
            distributions[gid] = path
            dist_hashes[gid] = _distribution_hash(path)
            seeds[gid] = seed
        except Exception as exc:
            distribution_failures[gid] = f"CFB_MODEL_INPUT_BLOCKED:{type(exc).__name__}:{exc}"

    groups: dict[tuple[str, str, float, str], list[dict[str, Any]]] = {}
    results: list[CFBMachineResult] = []
    for q in quote_rows:
        if q["market"] not in SUPPORTED_GAME_MARKETS:
            results.append(_blocked_no_engine(q))
            continue
        groups.setdefault(_pair_key(q), []).append(q)

    for key in sorted(groups):
        pair = groups[key]
        gid, market, line, _book = key
        if gid in distribution_failures:
            for q in pair:
                results.append(_blocked_result(q, reason=distribution_failures[gid]))
            continue
        distribution = distributions.get(gid)
        if distribution is None:
            for q in pair:
                results.append(_blocked_result(q, reason="CFB_DISTRIBUTION_MISSING"))
            continue
        readouts = price_cfb_game_markets(
            distribution,
            spread_line=line if market == "SPREAD" else 0.0,
            total_line=line if market == "TOTAL" else 0.0,
        )
        valid_pair = len(pair) == 2 and _complements(str(pair[0]["side"]), str(pair[1]["side"]))
        time_ok, time_reason, pair_times = _pair_time_state(
            pair,
            current=current,
            quote_ttl_seconds=quote_ttl_seconds,
            quote_pair_skew_seconds=quote_pair_skew_seconds,
        ) if valid_pair else (False, "PAIRED_PRICE_REQUIRED_FOR_DEVIG", ())
        raws = [_raw_implied(float(q["american_odds"])) for q in pair] if valid_pair else []
        implied_sum = sum(raws) if raws else 0.0
        hold = implied_sum - 1.0 if valid_pair else None
        for idx, q in enumerate(pair):
            side = str(q["side"])
            model_p, push_p = _readout_probability(readouts, market, side)
            reason = "CFB_PROMOTION_EVIDENCE_REQUIRED"
            fair = raw_p = edge = ev = None
            if not valid_pair or implied_sum <= 0.0:
                reason = "PAIRED_PRICE_REQUIRED_FOR_DEVIG"
            elif not time_ok:
                reason = time_reason
            else:
                raw_p = raws[idx]
                fair = raw_p / implied_sum
                non_push = 1.0 - push_p
                if non_push <= 0.0:
                    reason = "CFB_SETTLED_SAMPLE_SPACE_EMPTY"
                else:
                    edge = model_p / non_push - fair
                    p_loss = max(0.0, 1.0 - model_p - push_p)
                    ev = model_p * (_american_decimal(float(q["american_odds"])) - 1.0) - p_loss
            qt = pair_times[idx] if idx < len(pair_times) else _quote_time(q.get("retrieved_at"))
            results.append(CFBMachineResult(
                game_id=gid,
                market=market,
                side=side,
                line=float(q["line"]),
                american_odds=float(q["american_odds"]),
                model_p=model_p,
                push_p=push_p,
                fair_market_p=fair,
                raw_implied_p=raw_p,
                hold=hold,
                edge=edge,
                ev_per_dollar=ev,
                bet_status="BLOCKED",
                engine_status="PRICED" if edge is not None else "BLOCKED",
                reason=reason,
                model_artifact_sha256=model_sha,
                distribution_sha256=dist_hashes[gid],
                seed=seeds[gid],
                seed_policy=CFB_SEED_POLICY,
                book_key=str(q.get("book_key") or "") or None,
                sportsbook=str(q.get("sportsbook") or "") or None,
                quote_retrieved_at=qt.isoformat(),
                offer_id=str(q.get("offer_id") or "") or None,
            ))
    failures = [dict(x) for x in source_failures]
    failures.extend({"game_id": gid, "error": reason} for gid, reason in sorted(distribution_failures.items()))
    status = "READY" if results and not failures else "DEGRADED" if results else "BLOCKED"
    ordered = tuple(sorted(results, key=lambda r: (r.game_id, r.market, r.book_key or "", r.line or 0.0, r.side)))
    return CFBMachineReport(
        mode=mode,
        season=int(season),
        week=int(week),
        generated_at_utc=current.isoformat(),
        run_status=status,
        machine_version=CFB_MACHINE_VERSION,
        results=ordered,
        source_failures=tuple(failures),
        summary=_summary(ordered),
    )


def run_cfb_machine(
    *,
    mode: str = "AUTO_SELECT",
    season: int,
    week: int,
    model: CFBJointScoreModel,
    now: datetime,
    games: Sequence[CFBGame] | None = None,
    metrics: Mapping[str, CFBTeamMetrics] | None = None,
    quotes: Sequence[CFBQuote | Mapping[str, Any]] | None = None,
    cfbd_api_key: str | None = None,
    odds_api_key: str | None = None,
    bookmakers: Sequence[str] = ("draftkings",),
    root_seed: int = 20260826,
    n_paths: int = 20000,
    quote_ttl_seconds: int = DEFAULT_QUOTE_TTL_SECONDS,
    quote_pair_skew_seconds: int = DEFAULT_QUOTE_PAIR_SKEW_SECONDS,
    opener: Callable = urlopen,
    team_fetcher=fetch_cfbd_teams,
    game_fetcher=fetch_cfbd_games,
    metric_fetcher=fetch_cfbd_team_metrics,
    weather_fetcher=fetch_cfbd_weather,
    odds_fetcher=fetch_the_odds_api_quotes,
) -> CFBMachineReport:
    current = _aware(now, "now")
    selected = _resolve_mode(mode, games=games, metrics=metrics, quotes=quotes)
    common = dict(
        mode=selected,
        season=season,
        week=week,
        now=current,
        model=model,
        root_seed=root_seed,
        n_paths=n_paths,
        quote_ttl_seconds=quote_ttl_seconds,
        quote_pair_skew_seconds=quote_pair_skew_seconds,
    )
    if selected == "MANUAL":
        if games is None or metrics is None or quotes is None:
            raise CFBRunMachineError("CFB_MANUAL_REQUIRES_GAMES_METRICS_QUOTES")
        return _run_canonical(games=list(games), metrics=metrics, quotes=list(quotes), **common)
    key = str(cfbd_api_key or "").strip()
    if not key:
        raise CFBRunMachineError("CFBD_API_KEY_REQUIRED")
    team_rows = team_fetcher(season=season, cfbd_api_key=key, opener=opener)
    fetched_games = game_fetcher(season=season, week=week, cfbd_api_key=key, opener=opener)
    alias_index = build_team_alias_index(team_rows, games=fetched_games)
    fetched_games = attach_weather(
        fetched_games,
        weather_fetcher(season=season, week=week, cfbd_api_key=key, opener=opener),
    )
    fetched_metrics = metric_fetcher(season=season, week=week, cfbd_api_key=key, now=current, opener=opener)
    if selected == "HYBRID":
        if quotes is None or games is not None or metrics is not None:
            raise CFBRunMachineError("CFB_HYBRID_REQUIRES_QUOTES_ONLY")
        canonical_quotes = list(quotes)
    elif selected == "AUTOMATIC":
        odds_key = str(odds_api_key or "").strip()
        if not odds_key:
            raise CFBRunMachineError("ODDS_API_KEY_REQUIRED")
        canonical_quotes = odds_fetcher(
            api_key=odds_key,
            games=fetched_games,
            alias_index=alias_index,
            bookmakers=bookmakers,
            opener=opener,
        )
    else:
        raise CFBRunMachineError(f"CFB_RUN_MODE_UNREACHABLE:{selected}")
    return _run_canonical(games=fetched_games, metrics=fetched_metrics, quotes=canonical_quotes, **common)


def run_it_cfb(**kwargs: Any) -> CFBMachineReport:
    return run_cfb_machine(**kwargs)
