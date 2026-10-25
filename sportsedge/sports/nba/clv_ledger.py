"""NBA game-market capture -> grade -> CLV ledger (EXPERIMENTAL, research only).

Pure functions, no network, no model.  Builds the evidence chain the frozen
evidence policy needs before any NBA game-market candidate can be judged:

* ``capture_rows``: one row per (event, market, line, side) from a parsed
  ``[NBA LINES]`` issue, stamped with the sportsbook ``Captured:`` instant.
* ``pick_row``: logs a pick at its pregame price.  It REQUIRES a caller-supplied
  model probability and engine id; this module never invents one.  Every pick
  is stamped ``status=EXPERIMENTAL`` and ``countable=False``: promotion is an
  owner act under the frozen policy, never a function of this code.
* ``closing_quote``: last capture strictly before tip for the same event /
  market / line.  Moved line, post-tip only, or missing -> explicit reason.
* ``grade``: WIN/LOSS/PUSH from final score.
* ``clv``: no-vig close probability minus the entry no-vig probability,
  plus decimal-price CLV.  ``clv_summary`` aggregates per market.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable, Mapping

LEDGER_VERSION = "NBA_GAME_CLV_LEDGER_V0_EXPERIMENTAL"
SIDES = {"MONEYLINE": ("AWAY", "HOME"), "SPREAD": ("AWAY", "HOME"), "TOTAL": ("OVER", "UNDER")}


class NBALedgerError(ValueError):
    pass


def _ts(v: str) -> datetime:
    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise NBALedgerError(f"NBA_LEDGER_TZ_REQUIRED:{v}")
    return d


def implied(a: int) -> float:
    a = int(a)
    if -100 < a < 100:
        raise NBALedgerError(f"NBA_LEDGER_ODDS_INVALID:{a}")
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def decimal(a: int) -> float:
    a = int(a)
    return 1 + (a / 100 if a > 0 else 100 / -a)


def event_id(date: str, away: str, home: str) -> str:
    return f"NBA:{date}:{away}@{home}"


def capture_rows(games, *, game_date: str, source: str = "DK_ISSUE", issue: int | None = None) -> list[dict]:
    """Flatten parsed ``lines_card.Game`` objects into two-sided capture rows."""
    rows = []
    for g in games:
        if not g.captured_at:
            raise NBALedgerError(f"NBA_LEDGER_CAPTURED_AT_MISSING:{g.header}")
        eid = event_id(game_date, g.away, g.home)
        for m in g.markets:
            s1, s2 = SIDES[m.market]
            for side, price, other in ((s1, m.p1, m.p2), (s2, m.p2, m.p1)):
                line = m.line
                if m.market == "SPREAD" and side == "HOME" and line is not None:
                    line = -line
                rows.append({
                    "event_id": eid, "market": m.market, "side": side,
                    "line": line, "american": int(price), "other_american": int(other),
                    "captured_at": _ts(g.captured_at).isoformat(),
                    "source": source, "issue": issue,
                })
    return rows


def pick_row(capture: Mapping, *, model_p: float, engine_id: str) -> dict:
    if not engine_id:
        raise NBALedgerError("NBA_LEDGER_ENGINE_ID_REQUIRED")
    if model_p is None or not (0.0 < float(model_p) < 1.0):
        raise NBALedgerError("NBA_LEDGER_MODEL_P_REQUIRED")
    p = float(model_p)
    return {**dict(capture), "engine_id": engine_id, "model_p": p,
            "ev_per_unit": p * decimal(capture["american"]) - 1.0,
            "status": "EXPERIMENTAL", "countable": False, "ledger_version": LEDGER_VERSION}


def closing_quote(pick: Mapping, captures: Iterable[Mapping], *, tip_utc: str) -> tuple[dict | None, str]:
    tip = _ts(tip_utc)
    entry_time = _ts(pick["captured_at"])
    # A quote captured at or after tip is never a valid entry, even when a
    # different earlier capture happens to exist in the supplied board.
    if entry_time >= tip:
        return None, "ENTRY_NOT_PRETIP"
    # Never borrow a closing price from a different quote provider.
    if not pick.get("source"):
        return None, "ENTRY_SOURCE_MISSING"
    same = [c for c in captures if c["event_id"] == pick["event_id"]
            and c["market"] == pick["market"] and c["side"] == pick["side"]
            and c.get("source") == pick["source"]]
    if not same:
        return None, "NO_CLOSE_ROW"
    pre = [c for c in same if _ts(c["captured_at"]) < tip]
    if not pre:
        return None, "CLOSE_NOT_PRETIP"
    # The entry capture must never grade against itself or an older quote.
    # A closing observation is a separate, strictly later prestart snapshot.
    later = [c for c in pre if _ts(c["captured_at"]) > entry_time]
    if not later:
        return None, "CLOSE_NOT_AFTER_ENTRY"
    last_t = max(_ts(c["captured_at"]) for c in later)
    last = [c for c in later if _ts(c["captured_at"]) == last_t]
    if len({(c["line"], c["american"]) for c in last}) > 1:
        return None, "CLOSE_AMBIGUOUS"
    close = last[0]
    if pick["market"] != "MONEYLINE" and close["line"] != pick["line"]:
        return None, "LINE_MOVED"
    return dict(close), "OK"


def grade(pick: Mapping, *, away_pts: int, home_pts: int) -> str:
    m, side, line = pick["market"], pick["side"], pick["line"]
    if m == "MONEYLINE":
        if away_pts == home_pts:
            raise NBALedgerError("NBA_LEDGER_TIE_SCORE")
        return "WIN" if (away_pts > home_pts) == (side == "AWAY") else "LOSS"
    if m == "SPREAD":
        mine, theirs = (away_pts, home_pts) if side == "AWAY" else (home_pts, away_pts)
        v = mine + float(line) - theirs
    else:
        v = (away_pts + home_pts - float(line)) * (1 if side == "OVER" else -1)
    return "PUSH" if v == 0 else ("WIN" if v > 0 else "LOSS")


def profit(pick: Mapping, result: str) -> float:
    return {"WIN": decimal(pick["american"]) - 1.0, "LOSS": -1.0, "PUSH": 0.0}[result]


def clv(pick: Mapping, close: Mapping) -> dict:
    # Compare no-vig to no-vig on BOTH sides of the same market. Comparing
    # a no-vig close to the entry's raw break-even probability embeds the
    # entry vig and reports negative CLV even when the market never moved.
    entry_a, entry_b = implied(pick["american"]), implied(pick["other_american"])
    close_a, close_b = implied(close["american"]), implied(close["other_american"])
    entry_fair = entry_a / (entry_a + entry_b)
    close_fair = close_a / (close_a + close_b)
    return {"close_american": close["american"], "close_fair_p": close_fair,
            "entry_fair_p": entry_fair,
            "clv_prob": close_fair - entry_fair,
            "clv_price_pct": decimal(pick["american"]) / decimal(close["american"]) - 1.0}


def settle(pick, captures, *, tip_utc, away_pts=None, home_pts=None) -> dict:
    out = dict(pick)
    close, reason = closing_quote(pick, captures, tip_utc=tip_utc)
    out["close_reason"] = reason
    if close is not None:
        out.update(clv(pick, close))
    if away_pts is not None and home_pts is not None:
        out["result"] = grade(pick, away_pts=away_pts, home_pts=home_pts)
        out["profit_units"] = profit(pick, out["result"])
    return out


def clv_summary(settled: Iterable[Mapping]) -> dict:
    agg: dict = defaultdict(lambda: {"n": 0, "n_clv": 0, "clv_sum": 0.0, "beat_close": 0,
                                     "graded": 0, "units": 0.0})
    for r in settled:
        a = agg[r["market"]]
        a["n"] += 1
        if "clv_prob" in r:
            a["n_clv"] += 1
            a["clv_sum"] += r["clv_prob"]
            a["beat_close"] += r["clv_prob"] > 0
        if "result" in r:
            a["graded"] += 1
            a["units"] += r["profit_units"]
    return {m: {"n": a["n"], "n_with_close": a["n_clv"],
                "mean_clv_prob": (a["clv_sum"] / a["n_clv"]) if a["n_clv"] else None,
                "beat_close_rate": (a["beat_close"] / a["n_clv"]) if a["n_clv"] else None,
                "graded": a["graded"], "units": a["units"],
                "status": "EXPERIMENTAL_NO_VERDICT"} for m, a in sorted(agg.items())}
