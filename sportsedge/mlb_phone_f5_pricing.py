"""Phone-only MLB first-five (F5) market intake wired to the empirical F5 stack.

Uses the verified research components already in the tree:
- ``sportsedge.mlb_f5_features.MLBF5HistorySource``: strictly-prior F5
  runs-for/against per club (last 30 games, innings 1-5 from StatsAPI
  linescores; never scaled full-game runs) plus the league prior.
- ``sportsedge.f5_distribution.build_f5_distribution`` /
  ``read_f5_probability``: joint F5 score PMF and market read-outs for
  F5_MONEYLINE / F5_RUN_LINE / F5_TOTALS / F5_TEAM_TOTALS.

Team identity resolves names to StatsAPI team IDs via the free
``/api/v1/teams`` directory; unmatched names fail closed. Research only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.request import Request

from artifacts.free_models import dt, numeric, odds_decimal

from .f5_distribution import (
    F5_MARKETS,
    F5DistributionError,
    build_f5_distribution,
    read_f5_probability,
)
from .market_coverage import finalize_research_row
from .mlb_f5_features import HISTORY_WINDOW_GAMES, MLBF5FeatureError, MLBF5HistorySource

F5_PHONE_VERSION = "mlb_phone_f5_v1_20261011"

# The F5 empirical stack is wired and unit-tested, but FAILED harness
# validation vs the naive baseline (2026-10-11, chronological out-of-sample:
# Brier 0.2179 vs 0.2132, log-loss 0.7038 vs 0.6940, n=2898). Per Isaac's bar
# a failing market does not enter production pricing: all F5 markets fail
# closed until a verifying model exists.
F5_FAILED_VALIDATION = True

F5_PHONE_ALIASES = {
    "F5_ML": "F5_MONEYLINE",
    "FIRST_5_MONEYLINE": "F5_MONEYLINE",
    "FIRST_FIVE_MONEYLINE": "F5_MONEYLINE",
    "FIRST_5_RUN_LINE": "F5_RUN_LINE",
    "FIRST_FIVE_RUN_LINE": "F5_RUN_LINE",
    "FIRST_5_TOTAL": "F5_TOTALS",
    "FIRST_FIVE_TOTAL": "F5_TOTALS",
    "FIRST_5_TOTALS": "F5_TOTALS",
    "FIRST_5_TEAM_TOTAL": "F5_TEAM_TOTALS",
    "FIRST_FIVE_TEAM_TOTAL": "F5_TEAM_TOTALS",
}


class PhoneF5Error(ValueError):
    pass


def normalize_f5_market(market: Any) -> str | None:
    if not isinstance(market, str):
        return None
    m = market.strip().upper().replace(" ", "_").replace("-", "_")
    m = F5_PHONE_ALIASES.get(m, m)
    return m if m in F5_MARKETS else None


def blocked(row: Mapping[str, Any], reason: str, **extra: Any) -> dict[str, Any]:
    out = {
        "status": "NO_MODEL_OR_MARKET",
        "reason": str(reason)[:180],
        "sport": "MLB",
        "market": str(row.get("market") or "").upper(),
        "selection": row.get("side") or row.get("selection"),
        "research_only": True,
        "official_authority": False,
        "model_p_authority": False,
        "staking_authority": False,
    }
    out.update(extra)
    return out


def _norm_key(value: Any) -> str:
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in str(value)).split())


class _GetterOpener:
    """Adapt the phone runner's getter (url -> parsed JSON) to urlopen shape."""

    def __init__(self, getter):
        self._getter = getter

    def __call__(self, request, timeout=None):
        url = request.full_url if isinstance(request, Request) else str(request)
        if self._getter is None:
            raise OSError("F5_GETTER_UNAVAILABLE:" + url[:80])
        data = self._getter(url)
        if data is None:
            raise OSError("F5_GETTER_RETURNED_NONE:" + url[:80])
        payload = json.dumps(data).encode("utf-8")

        class _Resp:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return _Resp()


def _statsapi_team_id(teams_payload: Mapping[str, Any], name: str) -> int | None:
    needle = _norm_key(name)
    if not needle:
        return None
    candidates = []
    teams = teams_payload.get("teams") if isinstance(teams_payload, Mapping) else None
    for team in teams or []:
        if not isinstance(team, Mapping):
            continue
        keys = {_norm_key(team.get(k, "")) for k in
                ("name", "abbreviation", "teamName", "locationName",
                 "shortName", "franchiseName", "clubName")}
        if needle in keys:
            try:
                tid = int(team.get("id"))
            except (TypeError, ValueError):
                continue
            if tid > 0:
                candidates.append(tid)
    return candidates[0] if len(candidates) == 1 else None


def _side_home_away(row: Mapping[str, Any], home: str, away: str) -> str | None:
    raw = str(row.get("side") or row.get("selection") or "").strip().upper()
    token = raw.replace(" ", "_").replace("-", "_")
    if token in {"HOME", "AWAY"}:
        return token
    key = _norm_key(raw)
    if key and key == _norm_key(home):
        return "HOME"
    if key and key == _norm_key(away):
        return "AWAY"
    return None


def phone_f5_rows(rows, *, now=None, getter=None, auto_context: bool = True,
                  min_ev: float = 0.02):
    """Price F5 market rows; returns (outputs, receipts)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    now = now.astimezone(timezone.utc)
    if not 0 <= min_ev <= 0.15:
        raise ValueError("MIN_EV_OUT_OF_RANGE")
    outputs: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    dist_cache: dict[tuple[int, int, str], Any] = {}
    opener = _GetterOpener(getter if auto_context else None)
    try:
        source = MLBF5HistorySource(opener=opener, retrieved_at=now)
    except Exception as exc:  # noqa: BLE001 - source init must not crash routing
        return ([blocked(r, "F5_SOURCE_INIT_FAILED:" + type(exc).__name__) for r in rows],
                [{"source": "MLBF5HistorySource", "status": "INIT_FAILED"}])

    def team_id(name: str, season: int) -> int | None:
        try:
            payload = opener(f"https://statsapi.mlb.com/api/v1/teams?"
                             f"sportId=1&season={int(season)}")
            data = json.loads(payload.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 - fail closed below
            return None
        return _statsapi_team_id(data, name)

    def distribution(away_id: int, home_id: int, target) -> Any:
        key = (away_id, home_id, target.isoformat())
        if key in dist_cache:
            return dist_cache[key]
        away_rows = source.team_rows(team_id=away_id, target_date=target)[-HISTORY_WINDOW_GAMES:]
        home_rows = source.team_rows(team_id=home_id, target_date=target)[-HISTORY_WINDOW_GAMES:]
        features = {
            "away_f5_runs_for": [r["runs_for"] for r in away_rows],
            "away_f5_runs_against": [r["runs_against"] for r in away_rows],
            "home_f5_runs_for": [r["runs_for"] for r in home_rows],
            "home_f5_runs_against": [r["runs_against"] for r in home_rows],
        }
        features.update(source.league_prior(target_date=target))
        dist = build_f5_distribution(features, league_prior_strength=30)
        dist_cache[key] = dist
        receipts.append({
            "source": "FREE_MLB_STATSAPI_LINESCORE",
            "status": "F5_DISTRIBUTION_BUILT",
            "away_team_id": away_id,
            "home_team_id": home_id,
            "away_f5_games": len(away_rows),
            "home_f5_games": len(home_rows),
            "distribution_sha256": dist.distribution_sha256,
            "target_date": target.isoformat(),
        })
        return dist

    for row in rows:
        if not isinstance(row, dict):
            outputs.append(blocked({}, "LINE_MUST_BE_OBJECT"))
            continue
        market = normalize_f5_market(row.get("market"))
        if market is None:
            outputs.append(blocked(row, "NOT_AN_F5_MARKET"))
            continue
        if F5_FAILED_VALIDATION:
            outputs.append(blocked(row, "F5_MARKET_FAILED_VALIDATION_NOT_WIRED"))
            continue
        if str(row.get("sport") or "").upper() != "MLB":
            outputs.append(blocked(row, "F5_SPORT_MUST_BE_MLB"))
            continue
        away = str(row.get("away") or "").strip()
        home = str(row.get("home") or "").strip()
        if not home or not away or home == away:
            game = str(row.get("game") or "")
            if " @ " in game:
                away, home = (s.strip() for s in game.split(" @ ", 1))
        if not away or not home or away == home:
            outputs.append(blocked(row, "AWAY_HOME_REQUIRED"))
            continue
        kickoff = dt(row.get("commence_time") or row.get("kickoff"))
        if (row.get("commence_time") or row.get("kickoff")) and kickoff is None:
            outputs.append(blocked(row, "KICKOFF_TIMESTAMP_INVALID"))
            continue
        if kickoff is not None and kickoff <= now:
            out = blocked(row, "GAME_ALREADY_STARTED")
            out["status"] = "BLOCKED_STARTED"
            outputs.append(out)
            continue
        if kickoff is None:
            outputs.append(blocked(row, "BLOCKED_KICKOFF_UNVERIFIED"))
            continue
        line = None
        if market in {"F5_RUN_LINE", "F5_TOTALS", "F5_TEAM_TOTALS"}:
            try:
                line = numeric(row.get("line"), "line")
            except (TypeError, ValueError):
                outputs.append(blocked(row, "LINE_UNVERIFIED"))
                continue
            if market != "F5_RUN_LINE" and line < 0:
                outputs.append(blocked(row, "TOTAL_LINE_INVALID"))
                continue
        side = None
        team_side = None
        if market in {"F5_MONEYLINE", "F5_RUN_LINE"}:
            side = _side_home_away(row, home, away)
            if side is None:
                outputs.append(blocked(row, "SIDE_MUST_BE_HOME_AWAY"))
                continue
        elif market == "F5_TOTALS":
            raw = str(row.get("side") or row.get("selection") or "").strip().upper()
            if raw not in {"OVER", "UNDER"}:
                outputs.append(blocked(row, "SIDE_MUST_BE_OVER_UNDER"))
                continue
            side = raw
        else:  # F5_TEAM_TOTALS
            raw = str(row.get("side") or row.get("selection") or "").strip().upper()
            token = raw.replace(" ", "_").replace("-", "_")
            ou = token.rsplit("_", 1)[-1] if "_" in token else token
            team_tok = token.rsplit("_", 2)[0] if "_" in token else ""
            if ou in {"OVER", "UNDER"} and team_tok in {"HOME", "AWAY"}:
                side, team_side = ou, team_tok
            elif ou in {"OVER", "UNDER"}:
                # Team given separately via team_side / team field.
                side = ou
                team_side = _side_home_away(
                    {"side": row.get("team_side") or row.get("team")}, home, away)
                if team_side is None:
                    outputs.append(blocked(row, "F5_TEAM_SIDE_UNRESOLVED"))
                    continue
            else:
                outputs.append(blocked(row, "F5_TEAM_TOTAL_SIDE_INVALID"))
                continue
        try:
            price = numeric(row.get("odds", row.get("price")), "odds")
            dec = odds_decimal(row.get("odds", row.get("price")))
        except (TypeError, ValueError):
            outputs.append(blocked(row, "ODDS_INVALID"))
            continue
        try:
            away_id = team_id(away, kickoff.year)
            home_id = team_id(home, kickoff.year)
            if away_id is None or home_id is None:
                raise PhoneF5Error("F5_TEAM_IDENTITY_UNMATCHED")
            dist = distribution(away_id, home_id, kickoff.date())
            readout = read_f5_probability(dist, market=market, line=line,
                                          side=side, team_side=team_side)
        except (PhoneF5Error, MLBF5FeatureError, F5DistributionError,
                OSError, ValueError) as exc:
            outputs.append(blocked(row, "F5_" + type(exc).__name__ + ":" +
                                   str(exc)[:120]))
            continue
        # Degenerate probabilities fail closed exactly like the research bridge.
        # Guard on rounded values so a 5.4e-9 cannot be reported as clean 0.0.
        win = round(float(readout.probability), 6)
        push = round(float(readout.push_probability), 6)
        if not (0.0 < win < 1.0) or not (0.0 <= push < 1.0) \
                or win + push > 1.0 + 1e-12:
            outputs.append(blocked(row, "DEGENERATE_PROBABILITY_REFUSED"))
            continue
        if market == "F5_MONEYLINE":
            label = f"{home if side == 'HOME' else away} F5 ML"
        elif market == "F5_RUN_LINE":
            label = f"{home if side == 'HOME' else away} F5 {line:+g}"
        elif market == "F5_TOTALS":
            label = f"F5 {'Over' if side == 'OVER' else 'Under'} {line:g}"
        else:
            label = (f"{home if team_side == 'HOME' else away} F5 "
                     f"{'Over' if side == 'OVER' else 'Under'} {line:g}")
        outputs.append(finalize_research_row(
            sport="MLB", game=f"{away} @ {home}", selection=label, market=market,
            price=int(price), dec=dec, line=line,
            win=win, push=push,
            home_mean=float("nan"), away_mean=float("nan"),
            kickoff_iso=kickoff.isoformat(), context={}, context_notes=[],
            model_family="FREE_MLB_F5_EMPIRICAL_UNVALIDATED",
            declared_assumptions={
                "f5_source": "STRICTLY_PRIOR_F5_LINESCORE_LAST30_LEAGUE_PRIOR_M30",
                "full_game_means": "NOT_USED_F5_STATE_ONLY",
            },
            extra={
                "distribution_sha256": readout.distribution_sha256,
                "readout_sha256": readout.readout_sha256,
                "away_f5_games": dist.away_history_games,
                "home_f5_games": dist.home_history_games,
            },
            min_ev=min_ev,
        ))
    if outputs:
        # Lane summary receipts are provenance for work actually performed:
        # like the sibling phone lanes, an invocation that processed no rows
        # must not append a receipt to the card (a rows:0 receipt would
        # fabricate provenance for a source never consulted).
        receipts.append({"source": "sportsedge.mlb_phone_f5_pricing",
                         "status": "F5_PHONE_PRICING_COMPLETE",
                         "version": F5_PHONE_VERSION, "rows": len(outputs)})
    return outputs, receipts
