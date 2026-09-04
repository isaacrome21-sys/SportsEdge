"""Canonical SportsEdge CFB Manual / Hybrid / Automatic execution machine.

Modes differ only in ownership of inputs. Every mode converges on the same canonical
CFB game snapshot, the same joint full-game distribution, and the same market
read-outs. Sportsbook prices are never model features.

SportsEdge CFB currently admits FBS-vs-FBS games only. All modes must bind every
team in every game to a frozen CFBD ``/teams/fbs`` membership snapshot before the
joint model can run. FCS/unknown membership fails closed rather than inheriting
FBS calibration or promotion state.

The canonical boundary also enforces point-in-time safety: the game must still be
pregame, feature snapshots may not come from the future or from the target week,
and sportsbook quotes must be observed before both ``now`` and kickoff.

This foundation prices full-game MONEYLINE / SPREAD / TOTAL only. Other declared
football markets remain explicit NO_ENGINE until their required period/player state
is actually modeled. New CFB pricing remains BLOCKED from official betting until
promotion evidence and a frozen production edge floor exist.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Callable, Mapping, Sequence
from urllib.request import urlopen

from .classification_policy import assert_fbs_only_games
from .joint_model import CFBJointScoreModel, CFB_SEED_POLICY, price_cfb_game_markets, simulate_cfb_joint_distribution
from .source import (
    CFBGame, CFBQuote, CFBTeamMetrics, SUPPORTED_GAME_MARKETS, attach_weather,
    build_team_alias_index, fetch_cfbd_games, fetch_cfbd_team_metrics, fetch_cfbd_teams,
    fetch_cfbd_weather, fetch_the_odds_api_quotes,
)

VALID_MODES = frozenset({"AUTO_SELECT", "MANUAL", "HYBRID", "AUTOMATIC"})
CFB_MACHINE_VERSION = "CFB_RUN_MACHINE_V1"
DEFAULT_QUOTE_TTL_SECONDS = 180


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


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CFBRunMachineError(f"{name} timezone required")
    return value.astimezone(timezone.utc)


def _timestamp(value: Any, error: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise CFBRunMachineError(error)
        try:
            out = datetime.fromisoformat(text)
        except ValueError as exc:
            raise CFBRunMachineError(error) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBRunMachineError(error)
    return out.astimezone(timezone.utc)


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
        row["line"] = float(row.get("line", 0.0)); row["american_odds"] = float(row["american_odds"])
    except Exception as exc:
        raise CFBRunMachineError("CFB_QUOTE_NUMERIC_INVALID") from exc
    return row


def _quote_time(value: Any) -> datetime:
    return _timestamp(value, "CFB_QUOTE_RETRIEVED_AT_INVALID")


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
    return str(q.get("game_id") or ""), str(q.get("market") or "").upper(), float(q.get("line", 0.0)), str(q.get("book_key") or "")


def _distribution_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    raw = json.dumps(list(rows), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def _identity_seed(*, root_seed: int, game_id: str, model_sha: str) -> int:
    if isinstance(root_seed, bool) or not isinstance(root_seed, int):
        raise CFBRunMachineError("CFB_ROOT_SEED_INTEGER_REQUIRED")
    payload = f"{root_seed}|{game_id}|{model_sha}|CFB_GAME_PATH_V1".encode()
    return int.from_bytes(sha256(payload).digest()[:8], "big", signed=False)


def _validate_metric_pit(game: CFBGame, metric: CFBTeamMetrics, *, team: str, current: datetime, start: datetime) -> None:
    if metric.team != team:
        raise CFBRunMachineError(f"CFB_METRIC_TEAM_IDENTITY_MISMATCH:{team}")
    asof = _timestamp(metric.feature_asof_ts, f"CFB_FEATURE_ASOF_INVALID:{team}")
    if asof > current:
        raise CFBRunMachineError(f"CFB_FEATURE_FROM_FUTURE:{team}")
    if asof >= start:
        raise CFBRunMachineError(f"CFB_FEATURE_NOT_PREGAME:{team}")
    source = str(metric.sample_source or "").strip().upper()
    if source == "CURRENT_SEASON_PRIOR_WEEKS":
        if int(metric.season) != int(game.season):
            raise CFBRunMachineError(f"CFB_FEATURE_SEASON_MISMATCH:{team}")
        if int(metric.through_week) < 0 or int(metric.through_week) > int(game.week) - 1:
            raise CFBRunMachineError(f"CFB_TARGET_WEEK_FEATURE_LEAKAGE:{team}")
    elif source == "PRIOR_SEASON_FALLBACK":
        if int(game.week) != 1 or int(metric.season) != int(game.season) - 1:
            raise CFBRunMachineError(f"CFB_PRIOR_SEASON_FALLBACK_INVALID:{team}")
    else:
        raise CFBRunMachineError(f"CFB_FEATURE_SAMPLE_SOURCE_UNSUPPORTED:{team}:{source}")


def _validate_game_pit(game: CFBGame, metrics: Mapping[str, CFBTeamMetrics], *, current: datetime) -> None:
    start = _timestamp(game.start_ts, f"CFB_GAME_START_INVALID:{game.game_id}")
    if current >= start:
        raise CFBRunMachineError(f"CFB_GAME_NOT_PREGAME:{game.game_id}")
    for team in (game.home_team, game.away_team):
        metric = metrics.get(team)
        if not isinstance(metric, CFBTeamMetrics):
            raise CFBRunMachineError(f"CFB_METRICS_MISSING:{team}")
        _validate_metric_pit(game, metric, team=team, current=current, start=start)


def _game_row(game: CFBGame, metrics: Mapping[str, CFBTeamMetrics]) -> dict[str, Any]:
    home, away = metrics.get(game.home_team), metrics.get(game.away_team)
    if not isinstance(home, CFBTeamMetrics):
        raise CFBRunMachineError(f"CFB_HOME_METRICS_MISSING:{game.home_team}")
    if not isinstance(away, CFBTeamMetrics):
        raise CFBRunMachineError(f"CFB_AWAY_METRICS_MISSING:{game.away_team}")
    if not isinstance(game.weather, Mapping):
        raise CFBRunMachineError(f"CFB_WEATHER_MISSING:{game.game_id}")
    return {"game_id": game.game_id, "season": game.season, "week": game.week, "neutral_site": game.neutral_site,
            "home_metrics": home.to_dict(), "away_metrics": away.to_dict(), "weather": dict(game.weather)}


def _readout_probability(readouts: Mapping[str, Any], market: str, side: str) -> tuple[float, float]:
    if market == "MONEYLINE": return float(readouts["moneyline"][side.lower()]), 0.0
    if market == "SPREAD": return float(readouts["spread"][side.lower()]), float(readouts["spread"]["push"])
    if market == "TOTAL": return float(readouts["total"][side.lower()]), float(readouts["total"]["push"])
    raise CFBRunMachineError(f"CFB_NO_ENGINE:{market}")


def _blocked_no_engine(q: Mapping[str, Any]) -> CFBMachineResult:
    return CFBMachineResult(
        game_id=str(q.get("game_id") or "UNKNOWN"), market=str(q.get("market") or "UNKNOWN").upper(),
        side=str(q.get("side") or "UNKNOWN").upper(), line=float(q.get("line", 0.0)),
        american_odds=float(q["american_odds"]) if q.get("american_odds") is not None else None,
        model_p=None, push_p=None, fair_market_p=None, raw_implied_p=None, hold=None, edge=None, ev_per_dollar=None,
        bet_status="BLOCKED", engine_status="NO_ENGINE", reason="NO_ENGINE", model_artifact_sha256=None,
        distribution_sha256=None, seed=None, seed_policy=None, book_key=str(q.get("book_key") or "") or None,
        sportsbook=str(q.get("sportsbook") or "") or None, quote_retrieved_at=str(q.get("retrieved_at") or "") or None,
        offer_id=str(q.get("offer_id") or "") or None)


def _summary(results: Sequence[CFBMachineResult]) -> dict[str, Any]:
    return {"quote_count": len(results), "priced": sum(r.engine_status == "PRICED" for r in results),
            "no_engine": sum(r.engine_status == "NO_ENGINE" for r in results),
            "blocked": sum(r.bet_status == "BLOCKED" for r in results),
            "official_bets": sum(r.bet_status == "OFFICIAL_BET" for r in results),
            "markets_seen": sorted({r.market for r in results})}


def _run_canonical(*, mode: str, season: int, week: int, now: datetime, model: CFBJointScoreModel,
                   games: Sequence[CFBGame], metrics: Mapping[str, CFBTeamMetrics], quotes,
                   fbs_team_rows: Sequence[Mapping[str, Any]], root_seed: int, n_paths: int,
                   quote_ttl_seconds: int, source_failures=()) -> CFBMachineReport:
    current = _aware(now, "now")
    if not games: raise CFBRunMachineError("CFB_GAMES_EMPTY")
    assert_fbs_only_games(games, fbs_team_rows=fbs_team_rows)
    model_sha = model.artifact_sha256(); game_map = {g.game_id: g for g in games}; quote_rows = [_quote_dict(q) for q in quotes]
    distributions = {}; dist_hashes = {}; seeds = {}
    supported_game_ids = sorted({str(q.get("game_id") or "") for q in quote_rows if str(q.get("market") or "").upper() in SUPPORTED_GAME_MARKETS})
    for gid in supported_game_ids:
        game = game_map.get(gid)
        if game is None: raise CFBRunMachineError(f"CFB_QUOTE_GAME_UNRESOLVED:{gid}")
        _validate_game_pit(game, metrics, current=current)
        start = _timestamp(game.start_ts, f"CFB_GAME_START_INVALID:{gid}")
        for q in quote_rows:
            if str(q.get("game_id") or "") != gid or str(q.get("market") or "").upper() not in SUPPORTED_GAME_MARKETS:
                continue
            qt = _quote_time(q.get("retrieved_at"))
            if qt > current:
                raise CFBRunMachineError(f"CFB_QUOTE_FROM_FUTURE:{gid}")
            if qt >= start:
                raise CFBRunMachineError(f"CFB_QUOTE_NOT_PREGAME:{gid}")
        seed = _identity_seed(root_seed=root_seed, game_id=gid, model_sha=model_sha)
        path = simulate_cfb_joint_distribution(model, _game_row(game, metrics), seed=seed, n_paths=n_paths)
        distributions[gid] = path; dist_hashes[gid] = _distribution_hash(path); seeds[gid] = seed
    groups = {}; results = []
    for q in quote_rows:
        if q["market"] not in SUPPORTED_GAME_MARKETS:
            results.append(_blocked_no_engine(q)); continue
        groups.setdefault(_pair_key(q), []).append(q)
    for key in sorted(groups):
        pair = groups[key]; gid, market, line, _book = key; distribution = distributions[gid]
        readouts = price_cfb_game_markets(distribution, spread_line=line if market == "SPREAD" else 0.0,
                                          total_line=line if market == "TOTAL" else 0.0)
        valid_pair = len(pair) == 2 and _complements(str(pair[0]["side"]), str(pair[1]["side"]))
        raws = [_raw_implied(float(q["american_odds"])) for q in pair] if valid_pair else []
        implied_sum = sum(raws) if raws else 0.0; hold = implied_sum - 1.0 if valid_pair else None
        for idx, q in enumerate(pair):
            side = str(q["side"]); model_p, push_p = _readout_probability(readouts, market, side)
            reason = "CFB_PROMOTION_EVIDENCE_REQUIRED"; fair = raw_p = edge = ev = None
            if not valid_pair or implied_sum <= 0.0: reason = "PAIRED_PRICE_REQUIRED_FOR_DEVIG"
            else:
                raw_p = raws[idx]; fair = raw_p / implied_sum; non_push = 1.0 - push_p
                if non_push <= 0.0: reason = "CFB_SETTLED_SAMPLE_SPACE_EMPTY"
                else:
                    edge = model_p / non_push - fair
                    p_loss = max(0.0, 1.0 - model_p - push_p)
                    ev = model_p * (_american_decimal(float(q["american_odds"])) - 1.0) - p_loss
            qt = _quote_time(q.get("retrieved_at"))
            if (current - qt).total_seconds() > int(quote_ttl_seconds):
                reason = "CFB_QUOTE_STALE"; fair = raw_p = edge = ev = None
            results.append(CFBMachineResult(
                game_id=gid, market=market, side=side, line=float(q["line"]), american_odds=float(q["american_odds"]),
                model_p=model_p, push_p=push_p, fair_market_p=fair, raw_implied_p=raw_p, hold=hold, edge=edge, ev_per_dollar=ev,
                bet_status="BLOCKED", engine_status="PRICED", reason=reason, model_artifact_sha256=model_sha,
                distribution_sha256=dist_hashes[gid], seed=seeds[gid], seed_policy=CFB_SEED_POLICY,
                book_key=str(q.get("book_key") or "") or None, sportsbook=str(q.get("sportsbook") or "") or None,
                quote_retrieved_at=qt.isoformat(), offer_id=str(q.get("offer_id") or "") or None))
    ordered = tuple(sorted(results, key=lambda r: (r.game_id, r.market, r.book_key or "", r.line or 0.0, r.side)))
    if not ordered:
        status = "BLOCKED"
    elif source_failures:
        status = "DEGRADED"
    elif all(r.bet_status == "BLOCKED" for r in ordered):
        # Run health is not decision status. A priced model may be healthy while the
        # betting decision layer is intentionally fail-closed, but an all-BLOCKED
        # card must never be advertised as READY/healthy.
        status = "BLOCKED"
    else:
        status = "READY"
    return CFBMachineReport(mode=mode, season=int(season), week=int(week), generated_at_utc=current.isoformat(), run_status=status,
                            machine_version=CFB_MACHINE_VERSION, results=ordered,
                            source_failures=tuple(dict(x) for x in source_failures), summary=_summary(ordered))


def run_cfb_machine(*, mode: str = "AUTO_SELECT", season: int, week: int, model: CFBJointScoreModel, now: datetime,
                    games: Sequence[CFBGame] | None = None, metrics: Mapping[str, CFBTeamMetrics] | None = None,
                    quotes: Sequence[CFBQuote | Mapping[str, Any]] | None = None,
                    fbs_team_rows: Sequence[Mapping[str, Any]] | None = None,
                    cfbd_api_key: str | None = None, odds_api_key: str | None = None,
                    bookmakers: Sequence[str] = ("draftkings",), root_seed: int = 20260826,
                    n_paths: int = 20000, quote_ttl_seconds: int = DEFAULT_QUOTE_TTL_SECONDS, opener: Callable = urlopen,
                    team_fetcher=fetch_cfbd_teams, game_fetcher=fetch_cfbd_games, metric_fetcher=fetch_cfbd_team_metrics,
                    weather_fetcher=fetch_cfbd_weather, odds_fetcher=fetch_the_odds_api_quotes) -> CFBMachineReport:
    current = _aware(now, "now"); selected = _resolve_mode(mode, games=games, metrics=metrics, quotes=quotes)
    if selected == "MANUAL":
        if games is None or metrics is None or quotes is None: raise CFBRunMachineError("CFB_MANUAL_REQUIRES_GAMES_METRICS_QUOTES")
        if fbs_team_rows is None: raise CFBRunMachineError("CFB_MANUAL_FBS_MEMBERSHIP_REQUIRED")
        return _run_canonical(mode=selected, season=season, week=week, now=current, model=model, games=list(games), metrics=metrics,
                              quotes=list(quotes), fbs_team_rows=list(fbs_team_rows), root_seed=root_seed, n_paths=n_paths,
                              quote_ttl_seconds=quote_ttl_seconds)
    if fbs_team_rows is not None:
        raise CFBRunMachineError("CFB_FETCHED_MODE_FBS_MEMBERSHIP_OWNED_BY_SOURCE")
    key = str(cfbd_api_key or "").strip()
    if not key: raise CFBRunMachineError("CFBD_API_KEY_REQUIRED")
    team_rows = team_fetcher(season=season, cfbd_api_key=key, opener=opener); alias_index = build_team_alias_index(team_rows)
    fetched_games = game_fetcher(season=season, week=week, cfbd_api_key=key, opener=opener)
    assert_fbs_only_games(fetched_games, fbs_team_rows=team_rows)
    fetched_games = attach_weather(fetched_games, weather_fetcher(season=season, week=week, cfbd_api_key=key, opener=opener))
    fetched_metrics = metric_fetcher(season=season, week=week, cfbd_api_key=key, now=current, opener=opener)
    if selected == "HYBRID":
        if quotes is None or games is not None or metrics is not None: raise CFBRunMachineError("CFB_HYBRID_REQUIRES_QUOTES_ONLY")
        canonical_quotes = list(quotes)
    elif selected == "AUTOMATIC":
        odds_key = str(odds_api_key or "").strip()
        if not odds_key: raise CFBRunMachineError("ODDS_API_KEY_REQUIRED")
        canonical_quotes = odds_fetcher(api_key=odds_key, games=fetched_games, alias_index=alias_index, bookmakers=bookmakers, opener=opener)
    else: raise CFBRunMachineError(f"CFB_RUN_MODE_UNREACHABLE:{selected}")
    return _run_canonical(mode=selected, season=season, week=week, now=current, model=model, games=fetched_games,
                          metrics=fetched_metrics, quotes=canonical_quotes, fbs_team_rows=team_rows,
                          root_seed=root_seed, n_paths=n_paths, quote_ttl_seconds=quote_ttl_seconds)


def run_it_cfb(**kwargs: Any) -> CFBMachineReport:
    return run_cfb_machine(**kwargs)