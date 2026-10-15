"""Phone-only MLB first-inning intake: user odds, independently fetched model data.

The user's JSON supplies quotes and team names, never p or history. Team
first-inning rates come solely from free MLB StatsAPI linescores
(sportsedge.mlb_first_inning_data); probabilities from the pure-math
team-rate model (sportsedge.mlb_first_inning_model). Research only. Stale
quotes produce WATCH status.

Starter first-inning adjustment and park factors are IN_BUILD: the verified
data path exists and is unit-tested, but neither is applied to pricing until
it passes the backtest harness. The factor audit discloses this.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .mlb_first_inning_data import (
    MLBFirstInningPublicSource,
    FirstInningDataError,
    build_team_histories,
    collect_completed_games,
    pitcher_prior_starts,
    prior_pools,
    resolve_pregame_fixture,
)
from .mlb_first_inning_model import (
    BLOCKED_MARKETS,
    FIRST_INNING_BINARY_VERSION,
    MODEL_MARKETS,
    FirstInningModelError,
    price_first_inning_binary,
)
from .research_three_sport_bridge import price_three_sport_research

FIRST_INNING_PHONE_MARKETS = frozenset(MODEL_MARKETS) | frozenset(BLOCKED_MARKETS)
MODEL_SOURCE = "FREE_MLB_STATSAPI_LINESCORE"
HISTORY_LOOKBACK_DAYS = 75

# Only FIRST_INNING_RUNS passed the harness bar (binary starter model).
# The sibling team markets have verified data paths but their models did not
# pass; they stay IN_BUILD with explicit reasons -- no probabilities emitted.
PRICED_MARKETS = frozenset({"FIRST_INNING_RUNS"})
IN_BUILD_MARKETS = {
    "FIRST_INNING_TEAM_RUNS":
        "IN_BUILD_HARNESS_NOT_ROBUST:per-half binary signal flips between "
        "train/test windows; game-level YRFI passes but halves do not",
    "FIRST_INNING_HITS":
        "IN_BUILD_HARNESS_FAIL:team-rate model shows no out-of-sample signal; "
        "starter hits-allowed path not yet validated",
    "TEAM_HITS":
        "IN_BUILD_HARNESS_FAIL:team-rate Poisson model does not beat the "
        "naive baseline out-of-sample",
}


def blocked(row, reason):
    return {"status": "NO_MODEL_OR_MARKET", "reason": str(reason)[:180],
            "sport": "MLB", "market": row.get("market"),
            "selection": row.get("side"), "team": row.get("team"),
            "research_only": True, "official_authority": False,
            "model_p_authority": False, "staking_authority": False}


def _team_side(row):
    side = str(row.get("team") or "").strip().upper()
    if side in ("AWAY", "HOME"):
        return side
    label = str(row.get("label") or "")
    away = str(row.get("away") or "")
    home = str(row.get("home") or "")
    if away and away.lower() in label.lower():
        return "AWAY"
    if home and home.lower() in label.lower():
        return "HOME"
    return None


def _starter_binary_indicators(fixture, games_by_pk, src, *, seasons):
    """Verified 1st-inning 'allowed a run' indicators per probable starter.

    Returns (away_indicators, home_indicators) as 0/1 lists (most recent
    last). Raises FirstInningDataError when either starter's history is
    unverifiable -- fail closed, never fall back to a guess.
    """
    before = fixture["kickoff_utc"][:10]
    out = []
    for key in ("probable_away_pitcher", "probable_home_pitcher"):
        info = fixture.get(key) or {}
        pid = info.get("id")
        if pid is None:
            raise FirstInningDataError(
                "STARTER_IDENTITY_UNVERIFIED:" + key)
        prior = [s for s in pitcher_prior_starts(pid, seasons=seasons,
                                                 source=src)
                 if s["date"] < before]
        # Fetch linescores for starts outside the team-history window.
        for start in prior:
            if start["game_pk"] not in games_by_pk:
                for block in src.schedule_chunk(start["date"], start["date"]):
                    for game in block.get("games") or []:
                        parsed = None
                        try:
                            from .mlb_first_inning_data import (
                                parse_completed_linescore_game)
                            parsed = parse_completed_linescore_game(game)
                        except FirstInningDataError:
                            parsed = None
                        if parsed is not None:
                            games_by_pk[parsed["game_pk"]] = parsed
        indicators = []
        for start in prior[-15:]:
            game = games_by_pk.get(start["game_pk"])
            if game is None:
                continue
            if start["team_id"] == game["away_id"]:
                indicators.append(1 if game["inn1_home_runs"] >= 1 else 0)
            elif start["team_id"] == game["home_id"]:
                indicators.append(1 if game["inn1_away_runs"] >= 1 else 0)
        if len(indicators) < 5:
            raise FirstInningDataError(
                f"STARTER_FIRST_INNING_HISTORY_INSUFFICIENT:{pid}")
        out.append(indicators)
    return out[0], out[1]


def _price_first_inning_runs(line, pools_away, pools_home, fixture,
                             games_by_pk, src):
    try:
        numeric_line = float(line)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FirstInningModelError("FIRST_INNING_RUNS_LINE_INVALID") from exc
    if isinstance(line, bool) or not math.isfinite(numeric_line):
        raise FirstInningModelError("FIRST_INNING_RUNS_LINE_INVALID")
    if abs(numeric_line - 0.5) > 1e-9:
        raise FirstInningModelError("FIRST_INNING_RUNS_LINE_MUST_BE_0_5")
    kickoff_year = int(fixture["kickoff_utc"][:4])
    away_allow_ind, home_allow_ind = _starter_binary_indicators(
        fixture, games_by_pk, src,
        seasons=(kickoff_year - 1, kickoff_year))
    out = price_first_inning_binary(
        away_score_ind=[1 if v >= 1 else 0 for v in pools_away["inn1_for"]],
        home_starter_allow_ind=home_allow_ind,
        home_score_ind=[1 if v >= 1 else 0 for v in pools_home["inn1_for"]],
        away_starter_allow_ind=away_allow_ind,
    )
    return out, "GAME"


def phone_first_inning_rows(rows, *, now=None, getter=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    now_utc = now.astimezone(timezone.utc).isoformat()
    src = MLBFirstInningPublicSource(getter=getter)
    outputs = []
    cache = {}
    for row in rows:
        market = str(row.get("market") or "").upper()
        if market in BLOCKED_MARKETS:
            outputs.append(blocked(row, BLOCKED_MARKETS[market]))
            continue
        if market in IN_BUILD_MARKETS:
            outputs.append(blocked(row, IN_BUILD_MARKETS[market]))
            continue
        if market not in PRICED_MARKETS:
            outputs.append(blocked(row, "MARKET_NOT_SUPPORTED_BY_FIRST_INNING_MODEL"))
            continue
        away = str(row.get("away") or "").strip()
        home = str(row.get("home") or "").strip()
        start = row.get("kickoff") or row.get("commence_time")
        key = (away, home, str(start), market)
        if key not in cache:
            try:
                if not away or not home or not start:
                    raise FirstInningDataError("GAME_IDENTITY_OR_KICKOFF_MISSING")
                fixture = resolve_pregame_fixture(
                    away=away, home=home, kickoff=start, now=now_utc,
                    source=src)
                kickoff_dt = datetime.fromisoformat(
                    fixture["kickoff_utc"].replace("Z", "+00:00"))
                lookback_start = (kickoff_dt - timedelta(days=HISTORY_LOOKBACK_DAYS)).date()
                lookback_end = (kickoff_dt - timedelta(days=1)).date()
                dates = []
                for chunk in src.schedule_range(lookback_start.isoformat(),
                                                lookback_end.isoformat()):
                    dates.extend(chunk)
                games, skipped = collect_completed_games(dates)
                histories = build_team_histories(games)
                before = fixture["kickoff_utc"]
                pools_away = prior_pools(histories, fixture["away_id"],
                                         was_home=False, before_iso=before)
                pools_home = prior_pools(histories, fixture["home_id"],
                                         was_home=True, before_iso=before)
                cache[key] = {
                    "fixture": fixture,
                    "pools_away": pools_away,
                    "pools_home": pools_home,
                    "games_by_pk": {g["game_pk"]: g for g in games},
                    "history_games": len(games),
                    "history_skipped": skipped,
                }
            except (FirstInningDataError, FirstInningModelError,
                    TypeError, ValueError, KeyError) as exc:
                cache[key] = str(exc)
        verified = cache[key]
        if not isinstance(verified, dict):
            outputs.append(blocked(row, verified))
            continue
        side = str(row.get("side") or row.get("selection") or "").upper()
        if side not in ("OVER", "UNDER"):
            outputs.append(blocked(row, "FIRST_INNING_SIDE_MUST_BE_OVER_UNDER"))
            continue
        try:
            line = float(row["line"])
        except (KeyError, TypeError, ValueError):
            outputs.append(blocked(row, "FIRST_INNING_LINE_UNVERIFIED"))
            continue
        try:
            priced, player_id = _price_first_inning_runs(
                line, verified["pools_away"], verified["pools_home"],
                verified["fixture"], verified["games_by_pk"], src)
        except (FirstInningModelError, FirstInningDataError) as exc:
            outputs.append(blocked(row, str(exc)))
            continue
        p = priced["p_over"] if side == "OVER" else priced["p_under"]
        fixture = verified["fixture"]
        model_row = {
            "sport": "MLB",
            "game_id": fixture["game_pk"],
            "market": market,
            "selection": side,
            "player_id": player_id,
            "line": line,
            "status": "PRICED_RESEARCH",
            "market_blind": True,
            "model_source": MODEL_SOURCE,
            "as_of_utc": now_utc,
            "kickoff_utc": fixture["kickoff_utc"],
            "estimate_p": p,
            "push_p": 0.0,
            "validated_vs_close": False,
            "official_authority": False,
            "phase": "PREGAME",
        }
        quotes = []
        for another in rows:
            if (str(another.get("market") or "").upper() != market
                    or another.get("line") != row.get("line")
                    or _team_side(another) != _team_side(row)
                    or str(another.get("away")) != away
                    or str(another.get("home")) != home):
                continue
            quotes.append({
                "sport": "MLB",
                "game_id": fixture["game_pk"],
                "market": market,
                "selection": str(another.get("side") or another.get("selection") or "").upper(),
                "player_id": player_id,
                "line": line,
                "odds": another.get("odds", another.get("price")),
                "book": another.get("book") or "draftkings",
                "quote_captured_at": another.get("quote_captured_at"),
            })
        judged = price_three_sport_research([model_row], quotes,
                                            as_of=now_utc)["rows"][0]
        if judged.get("status") == "NO_MODEL_OR_MARKET":
            outputs.append(blocked(row, judged.get("reason") or "FIRST_INNING_QUOTE_PAIRING_FAILED"))
            continue
        judged["line"] = line
        judged["team"] = _team_side(row)
        judged["engine_version"] = FIRST_INNING_BINARY_VERSION
        judged["model_p_half"] = {
            "p_away_scores": priced["p_away_scores"],
            "p_home_scores": priced["p_home_scores"],
        }
        judged["prior_game_count"] = {
            "away": verified["pools_away"]["game_count"],
            "home": verified["pools_home"]["game_count"],
        }
        judged["history_games_scanned"] = verified["history_games"]
        # The starter component IS the validated model (binary Jeffreys
        # indicators from verified gameLog starts x linescores; PASS in the
        # harness). Park stays NOT_WIRED (Phase 2).
        judged["starter_adjustment"] = {
            "status": "VALIDATED_APPLIED",
            "detail": ("Opposing probable starter's verified 1st-inning "
                       "'allowed a run' rate over prior starts is blended "
                       "50/50 with the team's own 1st-inning scoring rate. "
                       "Harness PASS vs naive baseline (2024 train / 2025 "
                       "test)."),
            "probable_away_pitcher": (fixture.get("probable_away_pitcher") or {}).get("name"),
            "probable_home_pitcher": (fixture.get("probable_home_pitcher") or {}).get("name"),
        }
        judged["park_adjustment"] = {
            "status": "NOT_WIRED",
            "detail": "Park factor not applied; Phase 2 free-factors work.",
        }
        judged["source"] = MODEL_SOURCE
        judged["source_game_id"] = fixture["game_pk"]
        outputs.append(judged)
    return outputs, [{
        "source": MODEL_SOURCE,
        "status": "PUBLIC_MLB_LINESCORE_FIRST_INNING_VERIFIED",
        "game_pk": d["fixture"]["game_pk"],
        "prior_games_away": d["pools_away"]["game_count"],
        "prior_games_home": d["pools_home"]["game_count"],
        "engine": FIRST_INNING_BINARY_VERSION,
    } for d in cache.values() if isinstance(d, dict)]
